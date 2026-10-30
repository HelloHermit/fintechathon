"""代码控制的模拟银行工具。模型只能交申请，不能盖授权章。"""

import copy
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

from .storage import SHANGHAI, connect, initialize
from .conversation import ConversationMixin
from .recovery_state import AuthorizationExpired, RecoveryError, RecoveryStateMixin, StateUnavailable
from .six_scenarios import NEW_FIELDS, NEW_GREEN, NEW_RED, SixScenarioMixin
from .strong_auth import (TOTP_STEP_SECONDS, hash_password, match_totp,
                          normalize_totp_secret, verify_password)

INTENTS = {"query_balance", "query_transactions", "analyze_bills",
           "query_subscriptions", "cancel_subscription", "transfer"} | set(NEW_FIELDS)
GREEN = {"query_balance", "query_transactions", "analyze_bills"} | NEW_GREEN
NEGATIONS = ("不要执行", "不用执行", "不执行", "算了", "取消", "等一下", "不要确认", "别转", "停止")
INJECTION = ("忽略规则", "忽略之前", "跳过确认", "免确认", "不用确认", "当绿色", "标为绿色", "直接执行", "直接做", "ignore previous", "ignore rules", "drop table", "删除日志")
SECRET_PATTERN = re.compile(r"密码|password|api[_ -]?key|密钥|认证器|动态码|验证码|sk-[a-zA-Z0-9]", re.I)


class RuleError(Exception):
    def __init__(self, reason, message, tier="none"):
        self.reason, self.message, self.tier = reason, message, tier


class AuditUnavailable(Exception):
    pass


class ToolIsolationFailed(Exception):
    """只保存固定失败原因，不携带worker原文、路径内容或异常文本。"""

    def __init__(self, reason="isolation_unavailable"):
        allowed = {"invalid_task", "invalid_input", "isolation_unavailable", "start_failed",
                   "identity_mismatch", "nonzero_exit", "timeout", "cpu_limit",
                   "memory_limit", "output_limit", "invalid_output", "cancelled",
                   "audit_unavailable", "result_mismatch"}
        self.reason = reason if type(reason) is str and reason in allowed else "isolation_unavailable"


class BankService(ConversationMixin, RecoveryStateMixin, SixScenarioMixin):
    """固定可信身份的一次模拟会话；所有执行结果来自账本。"""

    def __init__(self, database_path, user_id="alice", clock=None, audit_hook=None, executor=None, *, checkpoint_hook=None):
        self.user_id = user_id
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.audit_hook = audit_hook
        # 执行器由可信启动者创建并管理；默认历史模式不冒称已经隔离。
        self.executor = executor
        if executor is not None and str(database_path) != ":memory:":
            # 真执行器公开的允许目录和监控库也约束直接Python调用；先检查再开库。
            bank_path = Path(database_path).resolve()
            if bank_path.exists() and bank_path.stat().st_nlink > 1:
                raise ValueError("隔离模式的业务账本不能具有多个硬链接。")
            runtime_directory = getattr(executor, "runtime_directory", None)
            monitor_database = getattr(executor, "database_path", None)
            readable_directories = getattr(executor, "readable_directories", None)
            if readable_directories is None:
                # 历史开发替身可只有runtime属性；它们不构成OS隔离证明。
                readable_directories = () if runtime_directory is None else (runtime_directory,)
            if any(bank_path.is_relative_to(Path(directory).resolve()) for directory in readable_directories):
                raise ValueError("业务账本不能位于worker允许读取的目录。")
            if monitor_database is not None:
                monitor_path = Path(monitor_database).resolve()
                same_file = bank_path == monitor_path
                if bank_path.exists() and monitor_path.exists():
                    same_file = same_file or os.path.samefile(bank_path, monitor_path)
                if same_file:
                    raise ValueError("业务账本和受限执行监控库必须分开。")
        self.confirmation_secrets = {}
        self._initialize_conversation_memory()
        self._initialize_recovery_memory(checkpoint_hook)
        self.halted = False
        self.connection = connect(database_path)
        try:
            initialize(self.connection, self._now())
            if not self.connection.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
                raise ValueError("未知模拟用户；身份只能在可信启动配置中指定。")
        except Exception:
            # 迁移或初始化失败也必须释放账本，避免失败会话留下文件句柄。
            self.connection.close()
            raise
        try:
            with self._transaction():
                self._restart_recovery()
                self._invalidate_pending("restart", "会话重启，旧确认失效")
                self._audit(uuid.uuid4().hex, "unknown", "none", "restart", "success", "会话启动；旧待确认已失效，业务数据和验证锁定保留")
        except AuditUnavailable:
            self.halted = True
    def _now(self):
        current = self.clock()
        if current.tzinfo is None:
            raise ValueError("测试时钟必须带时区")
        return current.astimezone(SHANGHAI)

    @contextmanager
    def _transaction(self):
        """一次提交包含账本、请求、任务节点和成功审计。"""
        saved_active = dict(self.active_plan_revisions)
        saved_reviews = copy.deepcopy(self.recovery_reviews)
        self._node_checkpoints = []
        self._plan_checkpoints = []
        self.connection.execute("BEGIN IMMEDIATE")
        committed_checkpoints = []
        try:
            yield
            for plan_id in self._plan_checkpoints:
                self._checkpoint("plan_save_before_commit", plan_id)
            # SAVEPOINT中的过期撤回可能已经取消成功事实，不能触发成功检查点。
            for checkpoint in self._node_checkpoints:
                request = self.connection.execute("SELECT status,tier,expires_at FROM requests WHERE request_id=? AND user_id=?", (checkpoint["request_id"], self.user_id)).fetchone()
                if request and request["status"] == "success":
                    self._checkpoint("node_before_commit", **checkpoint)
                    # 可信检查点可能耗时。最后一次期限复查必须在它返回之后。
                    if request["tier"] == "yellow" and self._now() >= datetime.fromisoformat(request["expires_at"]):
                        raise AuthorizationExpired(**checkpoint)
                    committed_checkpoints.append(dict(checkpoint))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            self.active_plan_revisions = saved_active
            self.recovery_reviews = saved_reviews
            self.plans.clear()
            raise
        finally:
            self._node_checkpoints = []
            self._plan_checkpoints = []
        for checkpoint in committed_checkpoints:
            self._checkpoint("node_after_commit", **checkpoint, committed=True)

    def _audit(self, request_id, intent, tier, event, result, reason="", params=None, step_id=None, plan_id=None):
        """记录受限字段的脱敏候选/执行参数，不让失败请求丢失安全目标。"""
        associated = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
        if associated and associated["plan_id"]:
            plan_id, step_id = associated["plan_id"], associated["step_id"]
            self._sync_request_plan(associated, event, reason)
        elif associated is None and plan_id is None and self._submitting_step is not None:
            # received/classified早于请求INSERT，仍关联可信的正在提交节点。
            plan_id, step_id = self._submitting_step["plan_id"], self._submitting_step["step_id"]
        if plan_id is not None:
            self._failure_plan_id = plan_id
        self._conversation_terminal_event(request_id, associated)
        safe_params = self._audit_parameters(intent, params)
        if intent == "transfer":
            stored_request = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
            if stored_request:
                try:
                    binding = json.loads(stored_request[0])
                except (ValueError, TypeError):
                    binding = {}
                if type(binding) is dict:
                    target = binding.get("target_account_id")
                    if type(target) is str and target:
                        safe_params["target_account_id"] = "[已脱敏]" if len(target) > 80 or SECRET_PATTERN.search(target) or re.search(r"[0-9]{6}", target) or any(ord(character) < 32 for character in target) or self._contains_enrolled_secret(target) else target
        event_record = dict(timestamp=self._now().isoformat(), request_id=request_id,
                            step_id=step_id, plan_id=plan_id, user_id=self.user_id,
                            raw_input_redacted="[用户原话省略，避免保存认证秘密]",
                            intent=intent if intent in INTENTS else "unknown", tier=tier,
                            params_redacted=json.dumps(safe_params, ensure_ascii=False, sort_keys=True),
                            event=event, result=result, reason=reason)
        try:
            if self.audit_hook:
                self.audit_hook(dict(event_record))
            self.connection.execute("""INSERT INTO audit_log(timestamp,request_id,step_id,plan_id,user_id,
                raw_input_redacted,intent,tier,params_redacted,event,result,reason)
                VALUES(:timestamp,:request_id,:step_id,:plan_id,:user_id,:raw_input_redacted,:intent,
                :tier,:params_redacted,:event,:result,:reason)""", event_record)
        except Exception as error:
            raise AuditUnavailable("审计不可用，已停止处理") from error

    def _audit_parameters(self, intent, params):
        """日志字段白名单只用于追查，不能给候选授予执行权限。"""
        fields = ({
            "query_balance": {"account_id"},
            "query_transactions": {"account_id", "start_date", "end_date"},
            "analyze_bills": {"account_id", "start_date", "end_date"},
            "query_subscriptions": set(),
            "cancel_subscription": {"subscription_id", "subscription_name"},
            "transfer": {"account_id", "contact_id", "contact_name", "amount_cents"},
        } | NEW_FIELDS).get(intent, set())
        if type(params) is not dict:
            return {}
        result = {}
        for field in fields:
            value = params.get(field)
            if field in {"amount_cents", "daily_limit_cents", "horizon_days"}:
                if type(value) is int and abs(value) <= 10**12:
                    result[field] = value
            elif field == "product_ids" and type(value) is list and len(value) <= 4:
                result[field] = ["[已脱敏]" if type(item) is not str or not item or len(item) > 80 or SECRET_PATTERN.search(item) or re.search(r"[0-9]{6}", item) or any(ord(character) < 32 for character in item) or self._contains_enrolled_secret(item) else item for item in value]
            elif type(value) is str and value:
                public_identifier = ((field == "budget_id" and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value))
                                     or (field == "order_id" and re.fullmatch(r"[0-9a-f]{32}", value)))
                if len(value) > 80 or SECRET_PATTERN.search(value) or (not public_identifier and re.search(r"[0-9]{6}", value)) or any(ord(character) < 32 for character in value) or self._contains_enrolled_secret(value):
                    result[field] = "[已脱敏]"
                else:
                    result[field] = value
        return result

    def _response(self, status, request_id, intent="unknown", tier="none", reason="", message="", **extra):
        return dict(status=status, request_id=request_id, intent=intent, tier=tier,
                    reason=reason, message=message, **extra)

    def _guarded(self, function):
        self._failure_plan_id = None
        if self.halted:
            return self._response("failed", "", reason="audit_unavailable", message="审计不可用，已停止处理；修复存储后重启。")
        try:
            return function()
        except AuthorizationExpired as error:
            return self._authorization_expired_at_commit(error)
        except StateUnavailable as error:
            return self._checkpoint_failed(error)
        except RecoveryError as error:
            return self._recovery_call(lambda: (_ for _ in ()).throw(error))
        except AuditUnavailable:
            self.halted = True
            self.confirmation_secrets.clear()
            self._clear_conversation("service_failed", audit=False)
            self.recovery_reviews.clear()
            self.active_plan_revisions.clear()
            return self._response("failed", "", reason="audit_unavailable", message="审计不可用，本次事务已回滚，已停止后续处理。", **({"plan_id": self._failure_plan_id} if self._failure_plan_id else {}))
        except sqlite3.Error:
            self.halted = True
            self.confirmation_secrets.clear()
            self._clear_conversation("service_failed", audit=False)
            self.recovery_reviews.clear()
            self.active_plan_revisions.clear()
            return self._response("failed", "", reason="storage_unavailable", message="账本保存失败，本次事务已回滚，已停止后续处理。", **({"plan_id": self._failure_plan_id} if self._failure_plan_id else {}))

    def _invalidate_pending(self, event="cancelled", reason="新请求使旧确认失效"):
        rows = self.connection.execute("SELECT * FROM requests WHERE user_id=? AND status='pending'", (self.user_id,)).fetchall()
        for request in rows:
            status = "expired" if self._now() >= datetime.fromisoformat(request["expires_at"]) else "cancelled"
            self.connection.execute("UPDATE requests SET status=? WHERE request_id=?", (status, request["request_id"]))
            self._audit(request["request_id"], request["intent"], request["tier"],
                        "expired" if status == "expired" else event, status, reason, json.loads(request["params_json"]))
            self.confirmation_secrets.pop(request["request_id"], None)

    def _locked(self, intent, request_id):
        bucket = "transfer" if intent == "place_order" else intent
        state = self.connection.execute("SELECT * FROM verification_state WHERE user_id=? AND intent=?", (self.user_id, bucket)).fetchone()
        if state and state["locked_until"]:
            if self._now() < datetime.fromisoformat(state["locked_until"]):
                raise RuleError("locked", "该类操作已锁定10分钟；换目标、换码、重启不能解锁。")
            self.connection.execute("UPDATE verification_state SET failures=0,locked_until=NULL WHERE user_id=? AND intent=?", (self.user_id, bucket))
            self._audit(request_id, intent, "none", "unlocked", "success", "锁定期满，重新开始计数")

    def _account(self, account_id):
        if type(account_id) is not str or len(account_id) > 80:
            raise RuleError("invalid_parameters", "账户编号无效。")
        account = self.connection.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        if not account:
            raise RuleError("not_found", "未找到模拟账户。")
        if account["user_id"] != self.user_id:
            raise RuleError("ownership", "只能读取本人账户或从本人账户转出。")
        return account

    def _validate(self, candidate):
        if type(candidate) is not dict or set(candidate) != {"intent", "params"}:
            raise RuleError("invalid_candidate", "模型候选格式不合法或包含未允许字段。")
        intent, params = candidate["intent"], candidate["params"]
        if type(intent) is not str or intent not in INTENTS:
            raise RuleError("unsupported_intent", "该操作不在固定工具白名单中。")
        if type(params) is not dict:
            raise RuleError("invalid_parameters", "参数必须是对象。")
        if intent in NEW_FIELDS:
            return self._new_validate(intent, params)
        allowed = {
            "query_balance": {"account_id"},
            "query_transactions": {"account_id", "start_date", "end_date"},
            "analyze_bills": {"account_id", "start_date", "end_date"},
            "query_subscriptions": set(),
            "cancel_subscription": {"subscription_id", "subscription_name"},
            "transfer": {"account_id", "contact_id", "contact_name", "amount_cents"}}
        if set(params) - allowed[intent]:
            raise RuleError("invalid_parameters", "包含未允许的参数；模型不能指定身份、权限或执行代码。")
        normalized = dict(params)
        if "account_id" in normalized:
            self._account(normalized["account_id"])
        if intent in {"query_transactions", "analyze_bills"}:
            today = self._now().date()
            for field, fallback in (("start_date", today.replace(day=1)), ("end_date", today)):
                value = normalized.get(field, fallback.isoformat())
                try:
                    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                        raise ValueError()
                    date.fromisoformat(value)
                except ValueError:
                    raise RuleError("invalid_parameters", "日期必须是有效的YYYY-MM-DD。")
                normalized[field] = value
            if normalized["start_date"] > normalized["end_date"]:
                raise RuleError("invalid_parameters", "开始日期不能晚于结束日期。")
        if intent == "cancel_subscription":
            fields = set(params)
            if fields not in ({"subscription_id"}, {"subscription_name"}):
                raise RuleError("missing_target", "请给出一个明确的订阅名称或编号。")
            field = next(iter(fields))
            value = params[field]
            if type(value) is not str or not value or len(value) > 80:
                raise RuleError("invalid_parameters", "订阅目标无效。")
            if field == "subscription_id":
                rows = self.connection.execute("SELECT * FROM subscriptions WHERE subscription_id=?", (value,)).fetchall()
            else:
                rows = self.connection.execute("SELECT * FROM subscriptions WHERE user_id=? AND name=?", (self.user_id, value)).fetchall()
            if len(rows) != 1:
                raise RuleError("not_found" if not rows else "ambiguous", "未找到唯一匹配订阅，请补充具体编号。")
            subscription = rows[0]
            if subscription["user_id"] != self.user_id:
                raise RuleError("ownership", "只能取消本人模拟订阅。")
            normalized = {"subscription_id": subscription["subscription_id"]}
        if intent == "transfer":
            amount = params.get("amount_cents")
            if type(amount) is not int or not 0 < amount <= 10**12:
                raise RuleError("invalid_amount", "金额必须是正整数分，不接受浮点数、零、负数或超出范围。")
            account_id = params.get("account_id", self.user_id + "-main")
            account = self._account(account_id)
            if self._available_account(account_id)["available_cents"] < amount:
                raise RuleError("insufficient_balance", "模拟账户可用余额不足；已保留预算不可用于转账。")
            fields = set(params) & {"contact_id", "contact_name"}
            if len(fields) != 1:
                raise RuleError("missing_target", "请指定一个已登记收款联系人。")
            field = next(iter(fields))
            value = params[field]
            if type(value) is not str or not value or len(value) > 80:
                raise RuleError("invalid_parameters", "收款目标无效。")
            column = "contact_id" if field == "contact_id" else "name"
            rows = self.connection.execute(f"SELECT * FROM contacts WHERE user_id=? AND {column}=?", (self.user_id, value)).fetchall()
            if len(rows) != 1:
                raise RuleError("not_found" if not rows else "ambiguous", "未找到唯一登记联系人；请补充目标。")
            normalized = {"account_id": account_id, "contact_id": rows[0]["contact_id"], "amount_cents": amount}
        return intent, normalized

    def _daily_total(self, execution_time=None):
        operation_time = execution_time or self._now()
        day = operation_time.date().isoformat()
        transfers = self.connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM transfers WHERE user_id=? AND shanghai_date=? AND status='success'", (self.user_id, day)).fetchone()[0]
        orders = self.connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM orders WHERE user_id=? AND shanghai_date=? AND status='paid'", (self.user_id, day)).fetchone()[0]
        return transfers + orders

    def _tier(self, intent, params, execution_time=None):
        if intent in GREEN:
            return "green"
        if intent in NEW_RED or (intent == "reserve_budget" and params["amount_cents"] > 100000):
            return "red"
        if intent == "place_order" and self._daily_total(execution_time) + self._service(params["service_id"])["price_cents"] > 100000:
            return "red"
        if intent == "transfer" and self._daily_total(execution_time) + params["amount_cents"] > 100000:
            return "red"
        return "yellow"

    def propose(self, candidate, raw_input=""):
        """验证候选、新建绑定请求；黄档等待确认，红档缺条件拒绝。"""
        def submit():
            response = self._propose(candidate)
            if response.get("plan_id"):
                return self._resume_plan(response["plan_id"])
            return response
        return self._guarded(submit)

    def _propose(self, candidate, request_id=None, preserve_plan_id=None):
        request_id = request_id or uuid.uuid4().hex
        with self._transaction():
            if not self._conversation_submitting:
                self._clear_conversation("new_task", request_id)
            submission = self._submitting_step if preserve_plan_id is not None else None
            submitted_plan = None
            if submission is not None:
                submitted_plan = self._usable_plan(preserve_plan_id)
                if (submission["plan_id"] != preserve_plan_id or submission["revision"] != submitted_plan["revision"]
                        or self.active_plan_revisions.get(preserve_plan_id) != submitted_plan["revision"]):
                    raise RecoveryError("revision_conflict", "任务状态已经改变，不能新建节点请求。")
            self._invalidate_pending()
            self._invalidate_plans(preserve_plan_id)
            self._audit(request_id, "unknown", "none", "received", "pending")
            if type(candidate) is dict and set(candidate) == {"clarification"}:
                self._audit(request_id, "unknown", "none", "clarification", "rejected", "需要补充明确目标")
                return self._response("rejected", request_id, reason="clarification", message="请补充具体操作、收款联系人、金额或订阅名称。")
            if type(candidate) is dict and set(candidate) == {"steps"}:
                return self._prepare_plan(candidate, request_id)
            submitted_intent = candidate.get("intent") if type(candidate) is dict else None
            intent = submitted_intent if type(submitted_intent) is str and submitted_intent in INTENTS else "unknown"
            params = self._audit_parameters(intent, candidate.get("params") if type(candidate) is dict else None)
            tier = "none"
            try:
                intent, params = self._validate(candidate)
                self._locked(intent, request_id)
                tier = self._tier(intent, params)
                self._audit(request_id, intent, tier, "classified", "pending", params=params)
                if tier == "red" and intent in NEW_FIELDS:
                    raise RuleError("strong_verification_unavailable", "该模拟操作属于红档，整体强验证与正式条件未全部满足，本轮拒绝。", "red")
                if tier == "red" and not self._strong_enrollment():
                    raise RuleError("strong_verification_unavailable", "日累计超过1000元；红档整体条件（含真人因素、终端及正式核验）未全部满足，本轮仍拒绝。", "red")
                now = self._now()
                expires = now + timedelta(minutes=5)
                binding = self._new_binding(intent, params)
                if submitted_plan is not None and intent == "transfer" and binding.get("target_account_id") != submitted_plan["steps"][submission["step_id"]]["target_account_id"]:
                    raise RuleError("authorization_changed", "登记收款账户已变化，不能沿用原计划目标。")
                self.connection.execute("INSERT INTO requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at,binding_json,plan_id,step_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (request_id, self.user_id, intent, json.dumps(params, ensure_ascii=False, sort_keys=True), tier, "pending", now.isoformat(), expires.isoformat(), json.dumps(binding, sort_keys=True), preserve_plan_id if submitted_plan else None, submission["step_id"] if submitted_plan else None))
                if tier == "green":
                    return self._execute(request_id, intent, params, tier)
                if tier == "red":
                    self._audit(request_id, intent, tier, "waiting_strong_verification", "pending", params=params)
                    return self._response("pending", request_id, intent, tier, message="日累计超过1000元。请用固定强验证入口提供本人密码与认证器动态码；5分钟有效。验证通过仍须满足全部红档条件，本轮红档业务不放行。", expires_at=expires.isoformat(), operation=self._operation(intent, params, request_id))
                code = f"{secrets.randbelow(1000000):06d}"
                self.confirmation_secrets[request_id] = code
                self._audit(request_id, intent, tier, "waiting_confirmation", "pending", params=params)
                return self._response("pending", request_id, intent, tier, message="这是模拟操作。请核对下列完整参数，再用固定确认入口同意；5分钟有效。", confirmation_code=code, expires_at=expires.isoformat(), operation=self._operation(intent, params, request_id))
            except RuleError as error:
                tier = error.tier if error.tier != "none" else tier
                if submitted_plan is not None:
                    step = submitted_plan["steps"][submission["step_id"]]
                    now = self._now()
                    binding = {"target_account_id": step["target_account_id"]} if step["intent"] == "transfer" else {}
                    self.connection.execute("INSERT OR IGNORE INTO requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at,binding_json,plan_id,step_id) VALUES(?,?,?,?,?,'rejected',?,?,?,?,?)", (request_id, self.user_id, step["intent"], json.dumps(step["params"], ensure_ascii=False, sort_keys=True), tier, now.isoformat(), (now + timedelta(minutes=5)).isoformat(), json.dumps(binding, sort_keys=True), preserve_plan_id, step["id"]))
                self._audit(request_id, intent, tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, tier, error.reason, error.message)

    def _operation(self, intent, params, request_id=None):
        if intent in NEW_FIELDS:
            return self._new_operation(intent, params)
        operation = dict(user_id=self.user_id, intent=intent, params=params, simulated=True)
        if intent == "query_subscriptions":
            operation["impact"] = "读取本人全部模拟订阅及未来预计安排，不修改数据。"
        elif intent == "cancel_subscription":
            row = self.connection.execute("SELECT name FROM subscriptions WHERE subscription_id=?", (params["subscription_id"],)).fetchone()
            operation.update(target_name=row["name"], impact="仅将本地模拟订阅标记取消，不退款，不删除历史账单，不操作真实平台。")
        elif intent == "transfer":
            row = self.connection.execute("SELECT name,account_id FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
            binding_row = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id or "", self.user_id)).fetchone()
            bound_target = json.loads(binding_row[0]).get("target_account_id") if binding_row else row["account_id"]
            operation.update(target_name=row["name"], target_account_id=bound_target, amount_cents=params["amount_cents"], source=self._available_account(params["account_id"]), daily_outgoing_after_cents=self._daily_total()+params["amount_cents"], impact="从本人模拟账户扣款并给登记联系人模拟账户入账。")
        return operation

    def _execute(self, request_id, intent, params, tier, expires_at=None):
        """只在调用方已持有写事务时执行；成功回执同事务保存。"""
        execution_time = self._now()
        intent, params = self._validate({"intent": intent, "params": params})
        self._locked(intent, request_id)
        current_tier = self._tier(intent, params, execution_time)
        if expires_at is not None and self._now() >= expires_at:
            raise RuleError("expired", "确认已超时，请重新申请。")
        if current_tier == "red":
            raise RuleError("strong_verification_unavailable", "执行前复检发现日累计超过1000元，旧确认失效；红档整体条件（含真人因素、终端及正式核验）未全部满足，本轮仍拒绝。", "red")
        if intent in NEW_FIELDS:
            return self._execute_six(request_id, intent, params, current_tier, execution_time, expires_at)
        records = []
        daily_total = 0
        target = ""
        if intent == "query_balance":
            query = "SELECT * FROM accounts WHERE user_id=?"
            values = [self.user_id]
            if "account_id" in params:
                query += " AND account_id=?"
                values.append(params["account_id"])
            data = {"accounts": [dict(row) for row in self.connection.execute(query, values)]}
            records = data["accounts"]
            if self.connection.execute("SELECT 1 FROM budgets WHERE user_id=? LIMIT 1", (self.user_id,)).fetchone():
                data["available_balances"] = [self._available_account(row["account_id"]) for row in data["accounts"]]
                records = [data]
        elif intent in {"query_transactions", "analyze_bills"}:
            query = "SELECT * FROM transactions WHERE user_id=?"
            values = [self.user_id]
            if "account_id" in params:
                query += " AND account_id=?"
                values.append(params["account_id"])
            transactions = [dict(row) for row in self.connection.execute(query + " ORDER BY occurred_at,transaction_id", values)
                            if params["start_date"] <= datetime.fromisoformat(row["occurred_at"]).astimezone(SHANGHAI).date().isoformat() <= params["end_date"]]
            records = transactions
            if intent == "query_transactions":
                data = {"transactions": transactions}
            else:
                categories = {}
                for row in transactions:
                    if row["status"] == "success" and row["kind"] in {"expense", "transfer_out"}:
                        comparison_time = execution_time if self.executor is not None else self._now()
                        if datetime.fromisoformat(row["occurred_at"]) <= comparison_time:
                            categories[row["category"]] = categories.get(row["category"], 0) + row["amount_cents"]
                data = {"actual_expense_cents": sum(categories.values()), "categories": categories, "start_date": params["start_date"], "end_date": params["end_date"], "basis": "已发生且成功的支出，不含未来预计订阅"}
        elif intent == "query_subscriptions":
            rows = [dict(row) for row in self.connection.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY subscription_id", (self.user_id,))]
            records = rows
            data = {"subscriptions": rows, "future_expected_cents": sum(row["amount_cents"] for row in rows if row["status"] == "active"), "basis": "未来一个续费周期的预计支出，与实际账单分开"}
        elif intent == "cancel_subscription":
            data = {"subscription_id": params["subscription_id"], "status": "cancelled", "history_preserved": True}
        elif intent == "transfer":
            contact = self.connection.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
            amount = params["amount_cents"]
            target = contact["account_id"]
            stored_request = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
            binding = json.loads(stored_request[0]) if stored_request else {}
            if binding.get("target_account_id") != target:
                raise RuleError("authorization_changed", "登记联系人的收款账户已改变，旧确认立即失效；请重新核对目标。")
            self._check_new_binding(request_id, intent, params)
            daily_total = self._daily_total(execution_time)
            data = {"amount_cents": amount, "source_account_id": params["account_id"], "target_account_id": target, "daily_outgoing_cents": daily_total + amount}
        if self.executor is not None:
            try:
                self._compute_in_isolation(request_id, intent, params, records, execution_time,
                                           daily_total, target, data)
            except ToolIsolationFailed as error:
                if error.reason == "audit_unavailable":
                    self.halted = True
                    self.confirmation_secrets.clear()
                # 超时回执不能压过已经到期的授权；调用方保存点会撤回确认事件。
                if expires_at is not None and self._now() >= expires_at:
                    raise RuleError("expired", "确认已超时，请重新申请。")
                return self._isolation_failure(request_id, intent, current_tier, params, error.reason)
            if expires_at is not None and self._now() >= expires_at:
                raise RuleError("expired", "确认已超时，请重新申请。")
            # worker期间可能耗时；写账前仍由宿主重新检查全部授权事实。
            checked_intent, checked_params = self._validate({"intent": intent, "params": params})
            if checked_intent != intent or checked_params != params:
                raise RuleError("authorization_changed", "操作参数已变化，请重新核对。")
            self._locked(intent, request_id)
            execution_time = self._now()
            current_tier = self._tier(intent, params, execution_time)
            if current_tier == "red":
                raise RuleError("strong_verification_unavailable", "执行前复检已进入红档；旧确认失效，本轮红档仍拒绝。", "red")
            if intent == "transfer":
                self._check_new_binding(request_id, intent, params)
                current_contact = self.connection.execute("SELECT account_id FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
                if not current_contact or current_contact[0] != target:
                    raise RuleError("authorization_changed", "登记收款账户已变化，请重新核对。")
                if self._daily_total(execution_time) != daily_total:
                    raise RuleError("authorization_changed", "办理期间日累计已变化，请重新核对本次操作。")
        # 以下固定SQL只使用宿主校验过的参数，从不执行worker提供的SQL或指令。
        if intent == "cancel_subscription":
            self.connection.execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id=? AND user_id=?", (params["subscription_id"], self.user_id))
        elif intent == "transfer":
            amount = params["amount_cents"]
            self.connection.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (amount, params["account_id"]))
            self.connection.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (amount, target))
            now = execution_time
            self.connection.execute("INSERT INTO transfers VALUES(?,?,?,?,?,?,?,?)", (request_id, self.user_id, params["account_id"], target, amount, now.isoformat(), now.date().isoformat(), "success"))
            recipient = self.connection.execute("SELECT user_id FROM accounts WHERE account_id=?", (target,)).fetchone()[0]
            self.connection.executemany("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?)", [
                (request_id+"-out", self.user_id, params["account_id"], amount, "模拟转账", now.isoformat(), "success", "transfer_out"),
                (request_id+"-in", recipient, target, amount, "模拟转账", now.isoformat(), "success", "transfer_in")])
            data = {"amount_cents": amount, "source_account_id": params["account_id"], "target_account_id": target, "daily_outgoing_cents": self._daily_total(execution_time)}
        self.connection.execute("UPDATE requests SET status='success',result_json=? WHERE request_id=? AND user_id=?", (json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False), request_id, self.user_id))
        self._audit(request_id, intent, current_tier, "executed", "success", params=params)
        self.confirmation_secrets.pop(request_id, None)
        return self._response("success", request_id, intent, current_tier, message="模拟操作已完成，结果来自账本。", data=data)

    def _compute_in_isolation(self, request_id, intent, params, records, now, daily_total, target, expected):
        """worker只做纯计算；严格核对类型和字段，宿主结果才可用于提交。"""
        payload = dict(intent=intent, params=params, records=records, now=now.isoformat(),
                       daily_total_cents=daily_total, target_account_id=target)
        try:
            expected_json = json.dumps(expected, sort_keys=True, ensure_ascii=True, allow_nan=False)
            # 给外部执行器独立的JSON快照，不能让注入执行器改写宿主参数或期望值。
            snapshot = json.loads(json.dumps(payload, ensure_ascii=True, allow_nan=False))
            result = self.executor.execute("compute_tool", snapshot, request_id=request_id)
            if type(result) is not dict or json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False) != expected_json:
                raise ToolIsolationFailed("result_mismatch")
        except ToolIsolationFailed:
            raise
        except Exception as error:
            raise ToolIsolationFailed(getattr(error, "reason", "isolation_unavailable")) from None

    def _isolation_failure(self, request_id, intent, tier, params, reason):
        """当前事务内终结失败请求；没有成功或业务改写，审计失败照常整体回滚。"""
        safe_reason = ToolIsolationFailed(reason).reason
        self.connection.execute("UPDATE requests SET status='failed' WHERE request_id=? AND user_id=?", (request_id, self.user_id))
        self.confirmation_secrets.pop(request_id, None)
        self._audit(request_id, intent, tier, "isolation_failed", "failed", safe_reason, params)
        if safe_reason == "audit_unavailable":
            self.halted = True
            self.confirmation_secrets.clear()
        return self._response("failed", request_id, intent, tier, "isolation_failed",
                              "受限执行未能安全完成，未提交业务修改；没有回退普通执行。",
                              isolation_reason=safe_reason)

    def confirm(self, request_id, confirmation_code):
        """精确确认；验证码不进模型、不进日志、不进数据库。"""
        return self._guarded(lambda: self._confirm(request_id, confirmation_code))

    def _confirm(self, request_id, confirmation_code):
        with self._transaction():
            request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id if type(request_id) is str else "", self.user_id)).fetchone()
            if not request or request["status"] != "pending":
                safe_id = request_id if type(request_id) is str and re.fullmatch(r"[0-9a-f]{32}", request_id) and not self._contains_enrolled_secret(request_id) else uuid.uuid4().hex
                self._audit(safe_id, "unknown", "none", "rejected", "rejected", "确认不存在、归属不符或已失效")
                return self._response("rejected", safe_id, reason="invalid_confirmation", message="确认不存在、属于其他用户或已失效，不能重复执行。")
            self._ensure_request_active(request)
            intent, tier = request["intent"], request["tier"]
            bucket = "transfer" if intent == "place_order" else intent
            params = json.loads(request["params_json"])
            expires_at = datetime.fromisoformat(request["expires_at"])
            if self._now() >= expires_at:
                return self._expire_confirmation_request(request_id, intent, tier, params)
            if tier == "red":
                self._audit(request_id, intent, tier, "rejected", "rejected", "strong_verification_required", params)
                return self._response("rejected", request_id, intent, tier, "strong_verification_required", "红档请求须用固定强验证入口（本人密码+认证器动态码）；六位确认通道不适用，本次不计失败。")
            try:
                self._locked(intent, request_id)
            except RuleError as error:
                self._audit(request_id, intent, tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, tier, error.reason, error.message)
            expected = self.confirmation_secrets.get(request_id)
            if type(confirmation_code) is not str or not re.fullmatch(r"[0-9]{6}", confirmation_code) or expected is None or not hmac.compare_digest(confirmation_code, expected):
                self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,1) ON CONFLICT(user_id,intent) DO UPDATE SET failures=failures+1", (self.user_id, bucket))
                failures = self.connection.execute("SELECT failures FROM verification_state WHERE user_id=? AND intent=?", (self.user_id, bucket)).fetchone()[0]
                self._audit(request_id, intent, tier, "verification_failed", "rejected", f"确认失败，连续{failures}次", params)
                if failures >= 3:
                    locked_until = self._now() + timedelta(minutes=10)
                    self.connection.execute("UPDATE verification_state SET locked_until=? WHERE user_id=? AND intent=?", (locked_until.isoformat(), self.user_id, bucket))
                    self._audit(request_id, intent, tier, "locked", "rejected", "连续3次验证失败，锁定10分钟", params)
                return self._response("rejected", request_id, intent, tier, "locked" if failures >= 3 else "verification_failed", "确认失败；连续3次失败将锁定该类操作10分钟。")
            # 保存点像事务内的撤回标记：跨期时一起撤销确认、业务及成功日志。
            self.connection.execute("SAVEPOINT confirmation_execution")
            self._audit(request_id, intent, tier, "confirmed", "pending", "明确确认通过", params)
            try:
                response = self._execute(request_id, intent, params, tier, expires_at=expires_at)
                if response["status"] == "success":
                    self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,0) ON CONFLICT(user_id,intent) DO UPDATE SET failures=0,locked_until=NULL", (self.user_id, bucket))
                # 审计也可能耗时；提交前过期不能留下部分扣款或计数清零。
                if self._now() >= expires_at:
                    raise RuleError("expired", "确认已超时，请重新申请。")
            except RuleError as error:
                if error.reason == "expired":
                    self.connection.execute("ROLLBACK TO confirmation_execution")
                    self.connection.execute("RELEASE confirmation_execution")
                    return self._expire_confirmation_request(request_id, intent, tier, params)
                self.connection.execute("RELEASE confirmation_execution")
                self.connection.execute("UPDATE requests SET status='rejected' WHERE request_id=?", (request_id,))
                self.confirmation_secrets.pop(request_id, None)
                self._audit(request_id, intent, error.tier if error.tier != "none" else tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, error.tier if error.tier != "none" else tier, error.reason, error.message)
            self.connection.execute("RELEASE confirmation_execution")
            return response

    def _expire_confirmation_request(self, request_id, intent, tier, params):
        """黄档跨期只保留过期回执，旧授权失效且失败计数保持。"""
        self.connection.execute("UPDATE requests SET status='expired' WHERE request_id=?", (request_id,))
        self.confirmation_secrets.pop(request_id, None)
        self._audit(request_id, intent, tier, "expired", "expired", "5分钟确认期满", params)
        return self._response("expired", request_id, intent, tier, "expired", "确认已超时，请重新申请。")

    def strong_verify(self, request_id, password, totp_code, *, confirmed=False):
        """本人核对并同意本次操作后验证两因素；本轮仍不执行红档业务。"""
        return self._guarded(lambda: self._strong_verify(request_id, password, totp_code, confirmed))

    def _strong_enrollment(self):
        return self.connection.execute("SELECT * FROM strong_auth WHERE user_id=?", (self.user_id,)).fetchone()

    def _contains_enrolled_secret(self, text):
        """拦住本人已知秘密的常见误粘贴；不保留或枚举明文口令。"""
        if type(text) is not str:
            return False
        enrollment = self._strong_enrollment()
        if not enrollment:
            return False
        normalized_secret = normalize_totp_secret(enrollment["totp_secret"])
        compact_text = "".join(text.split()).upper()
        if normalized_secret and normalized_secret in compact_text:
            return True
        password_candidates = (text,) if text == text.strip() else (text, text.strip())
        return any(verify_password(candidate, enrollment["password_hash"], enrollment["password_salt"], enrollment["kdf_iterations"]) for candidate in password_candidates)

    def _strong_failure(self, request_id, intent, tier, params):
        """统一失败路径：不区分密码错、动态码错或重放，计数持久化。"""
        self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,1) ON CONFLICT(user_id,intent) DO UPDATE SET failures=failures+1", (self.user_id, intent))
        failures = self.connection.execute("SELECT failures FROM verification_state WHERE user_id=? AND intent=?", (self.user_id, intent)).fetchone()[0]
        self._audit(request_id, intent, tier, "verification_failed", "rejected", f"验证失败，连续{failures}次", params)
        if failures >= 3:
            locked_until = self._now() + timedelta(minutes=10)
            self.connection.execute("UPDATE verification_state SET locked_until=? WHERE user_id=? AND intent=?", (locked_until.isoformat(), self.user_id, intent))
            self._audit(request_id, intent, tier, "locked", "rejected", "连续3次验证失败，锁定10分钟", params)
        return self._response("rejected", request_id, intent, tier, "locked" if failures >= 3 else "verification_failed", "强验证失败（不区分密码或动态码）；连续3次失败锁定该类操作10分钟。")

    def _expire_strong_request(self, request_id, intent, tier, params):
        """校验过程中也可能跨过期限；过期不消费因素、不清失败计数。"""
        self.connection.execute("UPDATE requests SET status='expired' WHERE request_id=?", (request_id,))
        self._audit(request_id, intent, tier, "expired", "expired", "5分钟强验证期满", params)
        return self._response("expired", request_id, intent, tier, "expired", "请求已超时，请重新申请。")

    def _strong_verify(self, request_id, password, totp_code, confirmed):
        with self._transaction():
            request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id if type(request_id) is str else "", self.user_id)).fetchone()
            if not request or request["status"] != "pending" or request["tier"] != "red":
                safe_id = request_id if type(request_id) is str and re.fullmatch(r"[0-9a-f]{32}", request_id) and not self._contains_enrolled_secret(request_id) else uuid.uuid4().hex
                self._audit(safe_id, "unknown", "none", "rejected", "rejected", "强验证目标不存在、归属不符、非红档或已失效")
                return self._response("rejected", safe_id, reason="invalid_confirmation", message="强验证目标不存在、属于其他用户、非红档或已失效，本次不计失败。")
            self._ensure_request_active(request)
            intent, tier = request["intent"], request["tier"]
            params = json.loads(request["params_json"])
            expires_at = datetime.fromisoformat(request["expires_at"])
            if self._now() >= expires_at:
                return self._expire_strong_request(request_id, intent, tier, params)
            try:
                self._locked(intent, request_id)
            except RuleError as error:
                self._audit(request_id, intent, tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, tier, error.reason, error.message)
            if confirmed is not True:
                self._audit(request_id, intent, tier, "rejected", "rejected", "explicit_confirmation_required", params)
                return self._response("rejected", request_id, intent, tier, "explicit_confirmation_required", "请先核对本次完整操作，再由本人在认证专用入口明确确认；尚未校验身份因素。")
            try:
                checked_intent, checked_params = self._validate({"intent": intent, "params": params})
                binding = json.loads(request["binding_json"])
                contact = self.connection.execute("SELECT account_id FROM contacts WHERE contact_id=? AND user_id=?", (params.get("contact_id"), self.user_id)).fetchone()
                if checked_intent != "transfer" or checked_params != params or not contact or type(binding) is not dict or binding.get("target_account_id") != contact[0]:
                    raise RuleError("invalid_confirmation", "操作参数或实际收款目标已改变，旧授权失效。")
            except (RuleError, ValueError, TypeError):
                self.connection.execute("UPDATE requests SET status='rejected' WHERE request_id=?", (request_id,))
                self._audit(request_id, intent, tier, "rejected", "rejected", "invalid_confirmation", params)
                return self._response("rejected", request_id, intent, tier, "invalid_confirmation", "操作参数、归属、余额或收款绑定不再有效；请重新申请，本次未校验因素。")
            enrollment = self._strong_enrollment()
            if not enrollment:
                self._audit(request_id, intent, tier, "rejected", "rejected", "strong_verification_unavailable", params)
                return self._response("rejected", request_id, intent, tier, "strong_verification_unavailable", "本人强验证未登记，红档拒绝。")
            password_ok = type(password) is str and verify_password(password, enrollment["password_hash"], enrollment["password_salt"], enrollment["kdf_iterations"])
            verification_time = self._now()
            if verification_time >= expires_at:
                return self._expire_strong_request(request_id, intent, tier, params)
            matched_offset = match_totp(enrollment["totp_secret"], totp_code, verification_time.timestamp()) if password_ok else None
            replay_hit = False
            if matched_offset is not None:
                matched_step = int(verification_time.timestamp() // TOTP_STEP_SECONDS) + matched_offset
                replay_hit = self.connection.execute("SELECT 1 FROM strong_auth_replay WHERE user_id=? AND step=?", (self.user_id, matched_step)).fetchone() is not None
            if self._now() >= expires_at:
                return self._expire_strong_request(request_id, intent, tier, params)
            if not password_ok or matched_offset is None or replay_hit:
                return self._strong_failure(request_id, intent, tier, params)
            # 审计写入也可能耗时。提交前跨过期限就撤销本次全部认证元数据。
            self.connection.execute("SAVEPOINT strong_auth_validation")
            self._audit(request_id, intent, tier, "confirmed", "pending", "本人明确同意本次绑定操作", params)
            self.connection.execute("INSERT INTO strong_auth_replay(user_id,step,used_at) VALUES(?,?,?)", (self.user_id, matched_step, verification_time.isoformat()))
            self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,0) ON CONFLICT(user_id,intent) DO UPDATE SET failures=0,locked_until=NULL", (self.user_id, intent))
            self._audit(request_id, intent, tier, "strong_verified", "success", "两种不同身份因素验证通过", params)
            self.connection.execute("UPDATE requests SET status='rejected' WHERE request_id=?", (request_id,))
            self._audit(request_id, intent, tier, "rejected", "rejected", "isolation_unavailable", params)
            if self._now() >= expires_at:
                self.connection.execute("ROLLBACK TO strong_auth_validation")
                self.connection.execute("RELEASE strong_auth_validation")
                return self._expire_strong_request(request_id, intent, tier, params)
            self.connection.execute("RELEASE strong_auth_validation")
            return self._response("rejected", request_id, intent, tier, "isolation_unavailable", "身份因素的代码校验通过；红档整体条件（含真人因素、终端及正式核验）未全部满足，本轮仍拒绝，未改动业务数据。", strong_verification="passed")

    def enroll_strong_auth(self, password, totp_secret, totp_code=None):
        """本机登记须在代码层验证持有证明；合成测试不等于真人登记。"""
        return self._guarded(lambda: self._enroll_strong_auth(password, totp_secret, totp_code))

    def _enroll_strong_auth(self, password, totp_secret, totp_code):
        with self._transaction():
            if type(password) is not str or not 8 <= len(password) <= 128:
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "invalid_password_format")
                return self._response("rejected", "", reason="invalid_password_format", message="密码须为8至128个字符。")
            normalized = normalize_totp_secret(totp_secret)
            if normalized is None:
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "invalid_totp_secret")
                return self._response("rejected", "", reason="invalid_totp_secret", message="认证器秘密须为有效base32且解码后至少20字节。")
            if self._strong_enrollment():
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "already_enrolled")
                return self._response("rejected", "", reason="already_enrolled", message="本人已登记强验证；如需更换请先重置。")
            enrollment_time = self._now()
            offset = match_totp(normalized, totp_code, enrollment_time.timestamp())
            matched_step = int(enrollment_time.timestamp() // TOTP_STEP_SECONDS) + offset if offset is not None else None
            if matched_step is None or self.connection.execute("SELECT 1 FROM strong_auth_replay WHERE user_id=? AND step=?", (self.user_id, matched_step)).fetchone():
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "invalid_totp_code")
                return self._response("rejected", "", reason="invalid_totp_code", message="持有证明未通过或该时间步已使用，未登记；请等待新的动态码后重试。")
            try:
                digest, salt_hex, iterations = hash_password(password)
            except (ValueError, TypeError, UnicodeError):
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "invalid_password_format")
                return self._response("rejected", "", reason="invalid_password_format", message="密码格式无法处理，未登记。")
            self.connection.execute("INSERT INTO strong_auth VALUES(?,?,?,?,?,?)", (self.user_id, digest, salt_hex, iterations, normalized, enrollment_time.isoformat()))
            self.connection.execute("INSERT INTO strong_auth_replay(user_id,step,used_at) VALUES(?,?,?)", (self.user_id, matched_step, enrollment_time.isoformat()))
            self._audit(uuid.uuid4().hex, "unknown", "none", "strong_auth_enrolled", "success", "本人完成密码与认证器登记，秘密不入日志")
            return self._response("success", "", message="强验证登记完成。", data={"user_id": self.user_id, "factors": ["password", "totp"]})

    def unenroll_strong_auth(self):
        """本地管理重置只删登记；旧请求失效，已用步和失败锁定保留。"""
        return self._guarded(lambda: self._unenroll_strong_auth())

    def _unenroll_strong_auth(self):
        with self._transaction():
            self._invalidate_pending("strong_auth_reset", "本人重置认证登记，旧授权失效")
            self._invalidate_plans()
            self.connection.execute("DELETE FROM strong_auth WHERE user_id=?", (self.user_id,))
            self._audit(uuid.uuid4().hex, "unknown", "none", "strong_auth_reset", "success", "本人强验证登记已删除，可重新登记")
            return self._response("success", "", message="本人强验证登记已删除。")

    def cancel(self, request_id=None):
        return self._guarded(lambda: self._cancel(request_id))

    def _cancel(self, request_id):
        with self._transaction():
            if request_id is not None and (type(request_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", request_id)):
                safe_id = uuid.uuid4().hex
                self._audit(safe_id, "unknown", "none", "rejected", "rejected", "取消请求编号无效")
                return self._response("rejected", safe_id, reason="invalid_parameters", message="取消请求编号无效；请使用当前回执中的编号。")
            self._clear_conversation("user_cancelled")
            if request_id is None:
                row = self.connection.execute("SELECT request_id FROM requests WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (self.user_id,)).fetchone()
                if row is None:
                    cancelled_plan = self._cancel_current_plan_authority()
                    if cancelled_plan is not None:
                        return cancelled_plan
                request_id = row[0] if row else uuid.uuid4().hex
            request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=? AND status='pending'", (request_id, self.user_id)).fetchone()
            if not request:
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "没有本人待确认请求")
                return self._response("rejected", "", reason="no_pending", message="没有有效待确认请求。")
            self.connection.execute("UPDATE requests SET status='cancelled' WHERE request_id=?", (request_id,))
            self.confirmation_secrets.pop(request_id, None)
            self._audit(request_id, request["intent"], request["tier"], "cancelled", "cancelled", "用户取消", json.loads(request["params_json"]))
            extras = {}
            if request["plan_id"]:
                extras = dict(plan_id=request["plan_id"], plan=self._cancel_plan_authority(request["plan_id"], request_id))
            return self._response("cancelled", request_id, request["intent"], request["tier"], message="已取消，旧确认立即失效；已提交结果保留。", **extras)

    def handle_text(self, text, model):
        """聊天只提供候选；明确取消和确认由代码处理。"""
        return self._guarded(lambda: self._handle_text(text, model))

    def _handle_text(self, text, model):
        return self._handle_conversation(text, model)

    def audit_events(self):
        if self.halted:
            return []
        def read():
            with self._transaction():
                self._audit(uuid.uuid4().hex, "unknown", "none", "audit_read", "success", "读取本人脱敏回执")
                return [dict(row) for row in self.connection.execute("SELECT * FROM audit_log WHERE user_id=? ORDER BY id", (self.user_id,))]
        return self._guarded(read)

    def reject_request(self, reason="invalid_http_request"):
        """本机HTTP入口记录格式/来源拒绝，不消费或改变业务授权。"""
        safe_reason = reason if type(reason) is str and reason in {"invalid_http_request", "http_access_denied"} else "invalid_http_request"
        def reject():
            request_id = uuid.uuid4().hex
            with self._transaction():
                self._audit(request_id, "unknown", "none", "rejected", "rejected", safe_reason)
            return self._response("rejected", request_id, reason=safe_reason, message="请求格式或来源未通过本机入口检查，未办理业务。")
        return self._guarded(reject)

    def close(self):
        if not self.halted:
            try:
                with self._transaction():
                    self._clear_conversation("session_closed")
                    self._invalidate_pending("session_closed", "会话结束，旧确认失效")
            except (AuditUnavailable, sqlite3.Error):
                self.halted = True
        self.confirmation_secrets.clear()
        self.recovery_reviews.clear()
        self.active_plan_revisions.clear()
        self.connection.close()

"""代码控制的模拟银行工具。模型只能交申请，不能盖授权章。"""

import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, date, timedelta

from .storage import SHANGHAI, connect, initialize

INTENTS = {"query_balance", "query_transactions", "analyze_bills",
           "query_subscriptions", "cancel_subscription", "transfer"}
GREEN = {"query_balance", "query_transactions", "analyze_bills"}
NEGATIONS = ("不要执行", "不用执行", "不执行", "算了", "取消", "等一下", "不要确认", "别转", "停止")
INJECTION = ("忽略规则", "忽略之前", "跳过确认", "免确认", "不用确认", "当绿色", "标为绿色", "直接执行", "直接做", "ignore previous", "ignore rules", "drop table", "删除日志")
SECRET_PATTERN = re.compile(r"密码|password|api[_ -]?key|密钥|认证器|动态码|验证码|sk-[a-zA-Z0-9]", re.I)


class RuleError(Exception):
    def __init__(self, reason, message, tier="none"):
        self.reason, self.message, self.tier = reason, message, tier


class AuditUnavailable(Exception):
    pass


class BankService:
    """固定可信身份的一次模拟会话；所有执行结果来自账本。"""

    def __init__(self, database_path, user_id="alice", clock=None, audit_hook=None):
        self.user_id = user_id
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.audit_hook = audit_hook
        self.confirmation_secrets = {}
        self.halted = False
        self.connection = connect(database_path)
        initialize(self.connection, self._now())
        if not self.connection.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            self.connection.close()
            raise ValueError("未知模拟用户；身份只能在可信启动配置中指定。")
        try:
            with self._transaction():
                self._invalidate_pending("restart", "会话重启，旧确认失效")
                self._audit(uuid.uuid4().hex, "unknown", "none", "restart", "success", "会话启动；旧待确认已失效，业务数据和验证锁定保留")
        except AuditUnavailable:
            self.halted = True
        self.plans = {}

    def _now(self):
        current = self.clock()
        if current.tzinfo is None:
            raise ValueError("测试时钟必须带时区")
        return current.astimezone(SHANGHAI)

    @contextmanager
    def _transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _audit(self, request_id, intent, tier, event, result, reason="", params=None, step_id=None):
        """只记录代码接受的安全参数，原话省略，确认秘密从不持久化。"""
        safe_params = dict(params or {})
        if intent == "transfer":
            stored_request = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
            if stored_request:
                safe_params.update(json.loads(stored_request[0]))
        event_record = dict(timestamp=self._now().isoformat(), request_id=request_id,
                            step_id=step_id, user_id=self.user_id,
                            raw_input_redacted="[用户原话省略，避免保存认证秘密]",
                            intent=intent if intent in INTENTS else "unknown", tier=tier,
                            params_redacted=json.dumps(safe_params, ensure_ascii=False, sort_keys=True),
                            event=event, result=result, reason=reason)
        try:
            if self.audit_hook:
                self.audit_hook(dict(event_record))
            self.connection.execute("""INSERT INTO audit_log(timestamp,request_id,step_id,user_id,
                raw_input_redacted,intent,tier,params_redacted,event,result,reason)
                VALUES(:timestamp,:request_id,:step_id,:user_id,:raw_input_redacted,:intent,
                :tier,:params_redacted,:event,:result,:reason)""", event_record)
        except Exception as error:
            raise AuditUnavailable("审计不可用，已停止处理") from error

    def _response(self, status, request_id, intent="unknown", tier="none", reason="", message="", **extra):
        return dict(status=status, request_id=request_id, intent=intent, tier=tier,
                    reason=reason, message=message, **extra)

    def _guarded(self, function):
        if self.halted:
            return self._response("failed", "", reason="audit_unavailable", message="审计不可用，已停止处理；修复存储后重启。")
        try:
            return function()
        except AuditUnavailable:
            self.halted = True
            self.confirmation_secrets.clear()
            return self._response("failed", "", reason="audit_unavailable", message="审计不可用，本次事务已回滚，已停止后续处理。")
        except sqlite3.Error:
            self.halted = True
            self.confirmation_secrets.clear()
            return self._response("failed", "", reason="storage_unavailable", message="账本保存失败，本次事务已回滚，已停止后续处理。")

    def _invalidate_pending(self, event="cancelled", reason="新请求使旧确认失效"):
        rows = self.connection.execute("SELECT * FROM requests WHERE user_id=? AND status='pending'", (self.user_id,)).fetchall()
        for request in rows:
            status = "expired" if self._now() >= datetime.fromisoformat(request["expires_at"]) else "cancelled"
            self.connection.execute("UPDATE requests SET status=? WHERE request_id=?", (status, request["request_id"]))
            self._audit(request["request_id"], request["intent"], request["tier"],
                        "expired" if status == "expired" else event, status, reason, json.loads(request["params_json"]))
            self.confirmation_secrets.pop(request["request_id"], None)

    def _invalidate_plans(self, preserve_plan_id=None):
        """新用户任务也停止旧计划尚未办理的步骤，不能随后偷偷续办。"""
        for plan_id, plan in self.plans.items():
            if plan_id == preserve_plan_id or plan["status"] in {"success", "interrupted", "human_takeover", "failed"}:
                continue
            for step in plan["steps"].values():
                if step["status"] == "pending":
                    request = self.connection.execute("SELECT status FROM requests WHERE request_id=?", (step["request_id"],)).fetchone()
                    if request and request[0] != "pending":
                        step["status"] = request[0]
            plan["status"] = "interrupted"
            self._audit(plan_id, "unknown", "none", "interrupted", "interrupted", "用户提出新任务，停止旧计划尚未完成步骤")

    def _locked(self, intent, request_id):
        state = self.connection.execute("SELECT * FROM verification_state WHERE user_id=? AND intent=?", (self.user_id, intent)).fetchone()
        if state and state["locked_until"]:
            if self._now() < datetime.fromisoformat(state["locked_until"]):
                raise RuleError("locked", "该类操作已锁定10分钟；换目标、换码、重启不能解锁。")
            self.connection.execute("UPDATE verification_state SET failures=0,locked_until=NULL WHERE user_id=? AND intent=?", (self.user_id, intent))
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
            raise RuleError("unsupported_intent", "该操作不在六项工具白名单中。")
        if type(params) is not dict:
            raise RuleError("invalid_parameters", "参数必须是对象。")
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
            if account["balance_cents"] < amount:
                raise RuleError("insufficient_balance", "模拟账户余额不足。")
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
        return self.connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM transfers WHERE user_id=? AND shanghai_date=? AND status='success'", (self.user_id, operation_time.date().isoformat())).fetchone()[0]

    def _tier(self, intent, params, execution_time=None):
        if intent in GREEN:
            return "green"
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
            params, tier = {}, "none"
            try:
                intent, params = self._validate(candidate)
                self._locked(intent, request_id)
                tier = self._tier(intent, params)
                self._audit(request_id, intent, tier, "classified", "pending", params=params)
                if tier == "red":
                    raise RuleError("strong_verification_unavailable", "日累计超过1000元：真实不同身份因素验证及受限执行环境尚未就绪，拒绝执行。", "red")
                now = self._now()
                expires = now + timedelta(minutes=5)
                binding = {}
                if intent == "transfer":
                    contact = self.connection.execute("SELECT account_id FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
                    binding["target_account_id"] = contact[0]
                self.connection.execute("INSERT INTO requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at,binding_json) VALUES(?,?,?,?,?,?,?,?,?)", (request_id, self.user_id, intent, json.dumps(params, ensure_ascii=False, sort_keys=True), tier, "pending", now.isoformat(), expires.isoformat(), json.dumps(binding, sort_keys=True)))
                if tier == "green":
                    return self._execute(request_id, intent, params, tier)
                code = f"{secrets.randbelow(1000000):06d}"
                self.confirmation_secrets[request_id] = code
                self._audit(request_id, intent, tier, "waiting_confirmation", "pending", params=params)
                return self._response("pending", request_id, intent, tier, message="这是模拟操作。请核对下列完整参数，再用固定确认入口同意；5分钟有效。", confirmation_code=code, expires_at=expires.isoformat(), operation=self._operation(intent, params, request_id))
            except RuleError as error:
                tier = error.tier if error.tier != "none" else tier
                self._audit(request_id, intent, tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, tier, error.reason, error.message)

    def _operation(self, intent, params, request_id=None):
        operation = dict(user_id=self.user_id, intent=intent, params=params, simulated=True)
        if intent == "query_subscriptions":
            operation["impact"] = "读取本人全部模拟订阅及未来预计安排，不修改数据。"
        elif intent == "cancel_subscription":
            row = self.connection.execute("SELECT name FROM subscriptions WHERE subscription_id=?", (params["subscription_id"],)).fetchone()
            operation.update(target_name=row["name"], impact="仅将本地模拟订阅标记取消，不退款，不删除历史账单，不操作真实平台。")
        else:
            row = self.connection.execute("SELECT name,account_id FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
            binding_row = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id or "", self.user_id)).fetchone()
            bound_target = json.loads(binding_row[0]).get("target_account_id") if binding_row else row["account_id"]
            operation.update(target_name=row["name"], target_account_id=bound_target, amount_cents=params["amount_cents"], daily_outgoing_after_cents=self._daily_total()+params["amount_cents"], impact="从本人模拟账户扣款并给登记联系人模拟账户入账。")
        return operation

    def _execute(self, request_id, intent, params, tier):
        """只在调用方已持有写事务时执行；成功回执同事务保存。"""
        execution_time = self._now()
        intent, params = self._validate({"intent": intent, "params": params})
        self._locked(intent, request_id)
        current_tier = self._tier(intent, params, execution_time)
        if current_tier == "red":
            raise RuleError("strong_verification_unavailable", "执行前复检发现日累计超过1000元，旧确认失效；强验证和隔离未就绪，拒绝。", "red")
        if intent == "query_balance":
            query = "SELECT * FROM accounts WHERE user_id=?"
            values = [self.user_id]
            if "account_id" in params:
                query += " AND account_id=?"
                values.append(params["account_id"])
            data = {"accounts": [dict(row) for row in self.connection.execute(query, values)]}
        elif intent in {"query_transactions", "analyze_bills"}:
            query = "SELECT * FROM transactions WHERE user_id=?"
            values = [self.user_id]
            if "account_id" in params:
                query += " AND account_id=?"
                values.append(params["account_id"])
            transactions = [dict(row) for row in self.connection.execute(query + " ORDER BY occurred_at,transaction_id", values)
                            if params["start_date"] <= datetime.fromisoformat(row["occurred_at"]).astimezone(SHANGHAI).date().isoformat() <= params["end_date"]]
            if intent == "query_transactions":
                data = {"transactions": transactions}
            else:
                categories = {}
                for row in transactions:
                    if row["status"] == "success" and row["kind"] in {"expense", "transfer_out"} and datetime.fromisoformat(row["occurred_at"]) <= self._now():
                        categories[row["category"]] = categories.get(row["category"], 0) + row["amount_cents"]
                data = {"actual_expense_cents": sum(categories.values()), "categories": categories, "start_date": params["start_date"], "end_date": params["end_date"], "basis": "已发生且成功的支出，不含未来预计订阅"}
        elif intent == "query_subscriptions":
            rows = [dict(row) for row in self.connection.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY subscription_id", (self.user_id,))]
            data = {"subscriptions": rows, "future_expected_cents": sum(row["amount_cents"] for row in rows if row["status"] == "active"), "basis": "未来一个续费周期的预计支出，与实际账单分开"}
        elif intent == "cancel_subscription":
            self.connection.execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id=? AND user_id=?", (params["subscription_id"], self.user_id))
            data = {"subscription_id": params["subscription_id"], "status": "cancelled", "history_preserved": True}
        else:
            contact = self.connection.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
            amount = params["amount_cents"]
            target = contact["account_id"]
            stored_request = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
            binding = json.loads(stored_request[0]) if stored_request else {}
            if binding.get("target_account_id") != target:
                raise RuleError("authorization_changed", "登记联系人的收款账户已改变，旧确认立即失效；请重新核对目标。")
            self.connection.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (amount, params["account_id"]))
            self.connection.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (amount, target))
            now = execution_time
            self.connection.execute("INSERT INTO transfers VALUES(?,?,?,?,?,?,?,?)", (request_id, self.user_id, params["account_id"], target, amount, now.isoformat(), now.date().isoformat(), "success"))
            recipient = self.connection.execute("SELECT user_id FROM accounts WHERE account_id=?", (target,)).fetchone()[0]
            self.connection.executemany("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?)", [
                (request_id+"-out", self.user_id, params["account_id"], amount, "模拟转账", now.isoformat(), "success", "transfer_out"),
                (request_id+"-in", recipient, target, amount, "模拟转账", now.isoformat(), "success", "transfer_in")])
            data = {"amount_cents": amount, "source_account_id": params["account_id"], "target_account_id": target, "daily_outgoing_cents": self._daily_total(execution_time)}
        self.connection.execute("UPDATE requests SET status='success' WHERE request_id=? AND user_id=?", (request_id, self.user_id))
        self._audit(request_id, intent, current_tier, "executed", "success", params=params)
        self.confirmation_secrets.pop(request_id, None)
        return self._response("success", request_id, intent, current_tier, message="模拟操作已完成，结果来自账本。", data=data)

    def confirm(self, request_id, confirmation_code):
        """精确确认；验证码不进模型、不进日志、不进数据库。"""
        return self._guarded(lambda: self._confirm(request_id, confirmation_code))

    def _confirm(self, request_id, confirmation_code):
        with self._transaction():
            request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id if type(request_id) is str else "", self.user_id)).fetchone()
            if not request or request["status"] != "pending":
                safe_id = request_id if type(request_id) is str and re.fullmatch(r"[0-9a-f]{32}", request_id) else uuid.uuid4().hex
                self._audit(safe_id, "unknown", "none", "rejected", "rejected", "确认不存在、归属不符或已失效")
                return self._response("rejected", safe_id, reason="invalid_confirmation", message="确认不存在、属于其他用户或已失效，不能重复执行。")
            intent, tier = request["intent"], request["tier"]
            params = json.loads(request["params_json"])
            if self._now() >= datetime.fromisoformat(request["expires_at"]):
                self.connection.execute("UPDATE requests SET status='expired' WHERE request_id=?", (request_id,))
                self.confirmation_secrets.pop(request_id, None)
                self._audit(request_id, intent, tier, "expired", "expired", "5分钟确认期满", params)
                return self._response("expired", request_id, intent, tier, "expired", "确认已超时，请重新申请。")
            try:
                self._locked(intent, request_id)
            except RuleError as error:
                self._audit(request_id, intent, tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, tier, error.reason, error.message)
            expected = self.confirmation_secrets.get(request_id)
            if type(confirmation_code) is not str or not re.fullmatch(r"[0-9]{6}", confirmation_code) or expected is None or not hmac.compare_digest(confirmation_code, expected):
                self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,1) ON CONFLICT(user_id,intent) DO UPDATE SET failures=failures+1", (self.user_id, intent))
                failures = self.connection.execute("SELECT failures FROM verification_state WHERE user_id=? AND intent=?", (self.user_id, intent)).fetchone()[0]
                self._audit(request_id, intent, tier, "verification_failed", "rejected", f"确认失败，连续{failures}次", params)
                if failures >= 3:
                    locked_until = self._now() + timedelta(minutes=10)
                    self.connection.execute("UPDATE verification_state SET locked_until=? WHERE user_id=? AND intent=?", (locked_until.isoformat(), self.user_id, intent))
                    self._audit(request_id, intent, tier, "locked", "rejected", "连续3次验证失败，锁定10分钟", params)
                return self._response("rejected", request_id, intent, tier, "locked" if failures >= 3 else "verification_failed", "确认失败；连续3次失败将锁定该类操作10分钟。")
            self._audit(request_id, intent, tier, "confirmed", "pending", "明确确认通过", params)
            try:
                response = self._execute(request_id, intent, params, tier)
            except RuleError as error:
                self.connection.execute("UPDATE requests SET status='rejected' WHERE request_id=?", (request_id,))
                self.confirmation_secrets.pop(request_id, None)
                self._audit(request_id, intent, error.tier if error.tier != "none" else tier, "rejected", "rejected", error.reason, params)
                return self._response("rejected", request_id, intent, error.tier if error.tier != "none" else tier, error.reason, error.message)
            self.connection.execute("INSERT INTO verification_state(user_id,intent,failures) VALUES(?,?,0) ON CONFLICT(user_id,intent) DO UPDATE SET failures=0,locked_until=NULL", (self.user_id, intent))
            for plan in self.plans.values():
                for step in plan["steps"].values():
                    if step["request_id"] == request_id:
                        step["data"] = response.get("data", {})
            return response

    def cancel(self, request_id=None):
        return self._guarded(lambda: self._cancel(request_id))

    def _cancel(self, request_id):
        with self._transaction():
            if request_id is not None and (type(request_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", request_id)):
                safe_id = uuid.uuid4().hex
                self._audit(safe_id, "unknown", "none", "rejected", "rejected", "取消请求编号无效")
                return self._response("rejected", safe_id, reason="invalid_parameters", message="取消请求编号无效；请使用当前回执中的编号。")
            if request_id is None:
                row = self.connection.execute("SELECT request_id FROM requests WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (self.user_id,)).fetchone()
                request_id = row[0] if row else uuid.uuid4().hex
            request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=? AND status='pending'", (request_id, self.user_id)).fetchone()
            if not request:
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "没有本人待确认请求")
                return self._response("rejected", "", reason="no_pending", message="没有有效待确认请求。")
            self.connection.execute("UPDATE requests SET status='cancelled' WHERE request_id=?", (request_id,))
            self.confirmation_secrets.pop(request_id, None)
            self._audit(request_id, request["intent"], request["tier"], "cancelled", "cancelled", "用户取消", json.loads(request["params_json"]))
            return self._response("cancelled", request_id, request["intent"], request["tier"], message="已取消，旧确认立即失效。")

    def handle_text(self, text, model):
        """聊天只提供候选；明确取消和确认由代码处理。"""
        return self._guarded(lambda: self._handle_text(text, model))

    def _handle_text(self, text, model):
        if type(text) is str and (text.strip() == "取消" or any(word in text for word in NEGATIONS if word != "取消") or any(word in text for word in ("取消当前", "取消操作", "取消请求"))):
            return self._cancel(None)
        request_id = uuid.uuid4().hex
        with self._transaction():
            self._invalidate_pending()
            self._invalidate_plans()
            self._audit(request_id, "unknown", "none", "received", "pending")
            invalid = type(text) is not str or not text.strip() or len(text) > 2000
            injected = not invalid and any(word in text.lower() for word in INJECTION)
            has_secret = not invalid and SECRET_PATTERN.search(text)
            if invalid or injected or has_secret:
                reason = "invalid_input" if invalid else "secret_input" if has_secret else "injection_blocked"
                self._audit(request_id, "unknown", "none", "rejected", "rejected", reason)
                return self._response("rejected", request_id, reason=reason, message="输入为空、过长、含认证秘密或明显越过规则指令；未发送模型，未执行。")
            if text.strip() in {"嗯", "随便", "你看着办", "确认", "执行"}:
                self._audit(request_id, "unknown", "none", "rejected", "rejected", "非固定确认格式")
                return self._response("rejected", request_id, reason="explicit_confirmation_required", message="请使用绑定编号的固定确认入口；口头含糊输入不会执行。")
        context = dict(user_id=self.user_id, today=self._now().date().isoformat(),
                       account_ids=[row[0] for row in self.connection.execute("SELECT account_id FROM accounts WHERE user_id=?", (self.user_id,))],
                       contacts=[dict(row) for row in self.connection.execute("SELECT contact_id,name FROM contacts WHERE user_id=?", (self.user_id,))])
        # 即使用户把屏显确认码粘贴到普通聊天，也不把六位码传给模型。
        sanitized_text = re.sub(r"(?<!\d)\d{6}(?!\d)", "[六位内容已脱敏]", text)
        try:
            candidate = model.propose(sanitized_text, context)
        except Exception as error:
            safe_model_codes = {"model_not_configured", "model_http_error", "model_timeout", "model_network_error", "invalid_model_json", "invalid_model_response", "model_incomplete_output", "model_redirect_blocked", "sensitive_model_input", "invalid_model_configuration", "invalid_model_context"}
            supplied_code = getattr(error, "code", None)
            model_error_code = supplied_code if type(supplied_code) is str and supplied_code in safe_model_codes else "model_failed"
            supplied_status = getattr(error, "http_status", None)
            http_status = supplied_status if type(supplied_status) is int and 400 <= supplied_status <= 599 else None
            with self._transaction():
                self._audit(request_id, "unknown", "none", "model_failed", "failed", model_error_code)
            return self._response("failed", request_id, reason="model_unavailable", message="模型未配置或调用失败，未执行任何业务；请检查本机模型配置。", model_error_code=model_error_code, http_status=http_status)
        response = self._propose(candidate, request_id)
        if response.get("plan_id"):
            return self._resume_plan(response["plan_id"])
        return response

    def _prepare_plan(self, candidate, plan_id):
        """校验模型候选的有向依赖图；前置成功由实际回执决定。"""
        steps = candidate["steps"]
        try:
            if type(steps) is not list or not 1 <= len(steps) <= 8:
                raise RuleError("invalid_plan", "计划必须包含1至8个步骤。")
            prepared = {}
            for step in steps:
                if type(step) is not dict or set(step) != {"id", "intent", "params", "depends_on"}:
                    raise RuleError("invalid_plan", "计划节点字段不合法。")
                identifier = step["id"]
                dependencies = step["depends_on"]
                if type(identifier) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", identifier) or identifier in prepared:
                    raise RuleError("invalid_plan", "计划编号无效或重复。")
                if type(dependencies) is not list or any(type(item) is not str for item in dependencies) or len(set(dependencies)) != len(dependencies):
                    raise RuleError("invalid_plan", "依赖必须是无重复的节点编号列表。")
                intent, params = self._validate({"intent": step["intent"], "params": step["params"]})
                prepared[identifier] = dict(id=identifier, intent=intent, params=params, depends_on=dependencies, status="not_started", request_id=None)
            done = set()
            while len(done) < len(prepared):
                ready = [identifier for identifier, step in prepared.items() if identifier not in done and set(step["depends_on"]) <= done]
                if not ready:
                    raise RuleError("invalid_plan", "计划含循环或不存在的前置节点。")
                done.update(ready)
            self.plans[plan_id] = dict(plan_id=plan_id, status="ready", steps=prepared)
            self._audit(plan_id, "unknown", "none", "plan_accepted", "pending", "候选依赖图已校验；尚未表示步骤执行成功")
            return self._response("pending", plan_id, message="候选依赖图合法，开始按依赖执行。", plan_id=plan_id)
        except RuleError as error:
            self._audit(plan_id, "unknown", "none", "rejected", "rejected", error.reason)
            return self._response("rejected", plan_id, reason=error.reason, message=error.message)

    def _plan_snapshot(self, plan):
        return dict(plan_id=plan["plan_id"], status=plan["status"], steps=[dict(step) for step in plan["steps"].values()], rollback_policy="已成功转账不自动撤回；取消仅停止未完成步骤，已取消订阅需要人工另行处理。")

    def resume_plan(self, plan_id):
        """仅前置真实成功才推进；每个黄档节点仍单独确认。"""
        return self._guarded(lambda: self._resume_plan(plan_id))

    def _resume_plan(self, plan_id):
        plan = self.plans.get(plan_id)
        if not plan or plan["status"] in {"interrupted", "human_takeover", "failed", "success"}:
            with self._transaction():
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "计划不存在或已停止")
            return self._response("rejected", "", reason="plan_stopped", message="计划不存在或已停止；不会恢复旧授权。")
        for step in plan["steps"].values():
            if step["status"] == "pending":
                request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (step["request_id"], self.user_id)).fetchone()
                step["status"] = request["status"] if request else "failed"
                if step["status"] == "pending" and self._now() >= datetime.fromisoformat(request["expires_at"]):
                    with self._transaction():
                        self.connection.execute("UPDATE requests SET status='expired' WHERE request_id=?", (step["request_id"],))
                        self._audit(step["request_id"], step["intent"], request["tier"], "expired", "expired", "计划步骤确认超时", step["params"])
                    self.confirmation_secrets.pop(step["request_id"], None)
                    step["status"] = "expired"
                if step["status"] == "pending":
                    # 重复续跑不生成新码、不改变原授权。
                    return self._response("pending", step["request_id"], step["intent"], "yellow", message="该步骤仍待固定确认入口确认。", confirmation_code=self.confirmation_secrets[step["request_id"]], expires_at=request["expires_at"], operation=self._operation(step["intent"], step["params"], step["request_id"]), plan_id=plan_id, plan=self._plan_snapshot(plan))
                if step["status"] != "success":
                    plan["status"] = "failed"
                    with self._transaction():
                        self._audit(plan_id, "unknown", "none", "plan_stopped", "failed", "前置节点未成功，停止后续步骤")
                    return self._response("failed", plan_id, reason="dependency_failed", message="前置步骤失败、取消或超时，后续未执行。", plan=self._plan_snapshot(plan))
        while True:
            ready = [step for step in plan["steps"].values() if step["status"] == "not_started" and all(plan["steps"][parent]["status"] == "success" for parent in step["depends_on"])]
            if not ready:
                plan["status"] = "success"
                with self._transaction():
                    self._audit(plan_id, "unknown", "none", "plan_completed", "success", "全部步骤实际成功")
                return self._response("success", plan_id, message="全部模拟计划步骤完成。", plan=self._plan_snapshot(plan))
            step = ready[0]
            with self._transaction():
                self._audit(plan_id, step["intent"], "none", "step_started", "pending", "前置实际成功后开始", step["params"], step["id"])
            response = self._propose({"intent": step["intent"], "params": step["params"]}, preserve_plan_id=plan_id)
            step.update(status=response["status"], request_id=response["request_id"])
            if response["status"] == "success":
                step["data"] = response.get("data", {})
            if response["status"] == "pending":
                plan["status"] = "waiting_confirmation"
                response.update(plan_id=plan_id, plan=self._plan_snapshot(plan))
                return response
            if response["status"] != "success":
                plan["status"] = "failed"
                response.update(plan_id=plan_id, plan=self._plan_snapshot(plan))
                return response

    def interrupt_plan(self, plan_id):
        return self._guarded(lambda: self._stop_plan(plan_id, "interrupted"))

    def takeover_plan(self, plan_id):
        return self._guarded(lambda: self._stop_plan(plan_id, "human_takeover"))

    def _stop_plan(self, plan_id, status):
        plan = self.plans.get(plan_id)
        if not plan or plan["status"] in {"success", "interrupted", "human_takeover", "failed"}:
            with self._transaction():
                self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", "计划不存在或已停止")
            return self._response("rejected", "", reason="plan_stopped", message="没有可中断的本人计划。")
        with self._transaction():
            for step in plan["steps"].values():
                if step["status"] == "pending":
                    row = self.connection.execute("SELECT status FROM requests WHERE request_id=?", (step["request_id"],)).fetchone()
                    if row and row[0] == "success":
                        step["status"] = "success"
                    elif row and row[0] == "pending":
                        self.connection.execute("UPDATE requests SET status='cancelled' WHERE request_id=?", (step["request_id"],))
                        self.confirmation_secrets.pop(step["request_id"], None)
                        step["status"] = "cancelled"
                        self._audit(step["request_id"], step["intent"], "yellow", "cancelled", "cancelled", "计划中断，旧确认失效", step["params"])
            self._audit(plan_id, "unknown", "none", status, "interrupted", "停止未完成步骤；已提交结果保留，需补救时人工另行授权")
        plan["status"] = status
        return self._response("cancelled", plan_id, message="计划已停止，已完成/未完成状态如下；已成功转账不自动撤回。", plan=self._plan_snapshot(plan))

    def audit_events(self):
        if self.halted:
            return []
        def read():
            with self._transaction():
                self._audit(uuid.uuid4().hex, "unknown", "none", "audit_read", "success", "读取本人脱敏回执")
                return [dict(row) for row in self.connection.execute("SELECT * FROM audit_log WHERE user_id=? ORDER BY id", (self.user_id,))]
        return self._guarded(read)

    def close(self):
        if not self.halted:
            try:
                with self._transaction():
                    self._invalidate_pending("session_closed", "会话结束，旧确认失效")
            except (AuditUnavailable, sqlite3.Error):
                self.halted = True
        self.confirmation_secrets.clear()
        self.connection.close()

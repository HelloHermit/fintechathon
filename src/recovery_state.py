"""持久任务、重新授权和本地接管登记；六场景仍共用同一授权账本。"""

import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta


PLAN_STATUSES = {"ready", "waiting_confirmation", "success", "failed", "interrupted", "human_takeover"}
STEP_STATUSES = {"not_started", "pending", "success", "failed", "rejected", "cancelled", "expired"}
RECOVERY_STATUSES = {"none", "required", "review_pending", "authorized", "blocked", "corrupt"}
PUBLIC_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
STEP_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
PARAMETERS = {
    "query_balance": {"account_id"},
    "query_transactions": {"account_id", "start_date", "end_date"},
    "analyze_bills": {"account_id", "start_date", "end_date"},
    "query_subscriptions": set(),
    "cancel_subscription": {"subscription_id", "subscription_name"},
    "transfer": {"account_id", "contact_id", "contact_name", "amount_cents"},
    "query_investments": set(),
    "compare_investments": {"product_ids"},
    "match_investments": {"risk_level", "horizon_days", "liquidity"},
    "query_cards": {"card_id"},
    "apply_virtual_card": {"account_id"},
    "set_card_limit": {"card_id", "daily_limit_cents"},
    "query_services": set(),
    "query_budgets": {"budget_id"},
    "query_orders": {"budget_id", "order_id"},
    "reserve_budget": {"budget_id", "account_id", "event_date", "amount_cents"},
    "release_budget": {"budget_id"},
    "place_order": {"budget_id", "service_id", "event_date", "card_id"},
    "purchase_investment": {"product_id", "account_id", "amount_cents"},
    "redeem_investment": {"product_id", "account_id", "amount_cents"},
    "report_card_lost": {"card_id"},
    "restore_card": {"card_id"},
}
NEW_INTENTS = set(PARAMETERS) - {"query_balance", "query_transactions", "analyze_bills", "query_subscriptions", "cancel_subscription", "transfer"}
NEW_MUTATIONS = {"apply_virtual_card", "set_card_limit", "reserve_budget", "release_budget", "place_order"}


class RecoveryError(Exception):
    """只携带固定公开原因，不携带损坏记录的原文。"""

    def __init__(self, reason, message="请求未通过任务状态及归属检查。"):
        self.reason = reason
        self.message = message


class StateUnavailable(Exception):
    """可信故障钩子异常；未提交和已经提交的事实必须分开处理。"""

    def __init__(self, checkpoint, committed=False):
        self.checkpoint = dict(checkpoint)
        self.committed = committed


class AuthorizationExpired(Exception):
    """提交前最后检查发现黄档期限已到；先回滚，再另记过期事实。"""

    def __init__(self, plan_id, step_id, request_id):
        self.plan_id, self.step_id, self.request_id = plan_id, step_id, request_id


def _duplicate_checked(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _json_load(value):
    return json.loads(value, object_pairs_hook=_duplicate_checked,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))


def _json_dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class RecoveryStateMixin:
    """BankService 的任务账本层；业务验证仍由 BankService 的固定规则完成。"""

    def _initialize_recovery_memory(self, checkpoint_hook):
        self.checkpoint_hook = checkpoint_hook
        self.plans = {}  # 仅兼容查看；每次控制动作都重新读取数据库。
        self.recovery_reviews = {}
        self.active_plan_revisions = {}
        self._node_checkpoints = []
        self._plan_checkpoints = []
        self._submitting_step = None

    def _checkpoint(self, point, plan_id, step_id=None, request_id=None, committed=False):
        if self.checkpoint_hook is None:
            return
        payload = dict(point=point, plan_id=plan_id, step_id=step_id, request_id=request_id)
        try:
            self.checkpoint_hook(dict(payload))
        except Exception:
            raise StateUnavailable(payload, committed) from None

    def _recovery_call(self, function):
        def execute():
            try:
                return function()
            except RecoveryError as error:
                with self._transaction():
                    request_id = uuid.uuid4().hex
                    extras = {}
                    plan_id = getattr(self, "_failure_plan_id", None)
                    if self._valid_id(plan_id):
                        owned = self.connection.execute("SELECT 1 FROM recovery_plans WHERE plan_id=? AND user_id=?", (plan_id, self.user_id)).fetchone()
                        if owned:
                            plan = self._load_plan(plan_id)
                            extras = dict(plan_id=plan_id, plan=plan if plan["recovery_status"] == "corrupt" else self._plan_snapshot(plan))
                    self._audit(request_id, "unknown", "none", "rejected", "rejected", error.reason, plan_id=extras.get("plan_id"))
                return self._response("rejected", request_id, reason=error.reason, message=error.message, **extras)
        return self._guarded(execute)

    def _valid_id(self, value):
        return type(value) is str and PUBLIC_ID.fullmatch(value) is not None

    def _safe_stored_params(self, intent, params):
        if type(intent) is not str or intent not in PARAMETERS or type(params) is not dict:
            raise ValueError("invalid parameters")
        if set(params) - PARAMETERS[intent]:
            raise ValueError("invalid fields")
        for key, value in params.items():
            if key in {"amount_cents", "daily_limit_cents", "horizon_days"}:
                if type(value) is not int or not 0 < value <= 10**12:
                    raise ValueError("invalid amount")
                if key == "horizon_days" and value > 3650:
                    raise ValueError("invalid horizon")
                if key == "daily_limit_cents" and value > 100000:
                    raise ValueError("invalid limit")
            elif key == "product_ids":
                if (type(value) is not list or not 2 <= len(value) <= 4 or
                        any(type(item) is not str or not 1 <= len(item) <= 80 for item in value) or len(set(value)) != len(value)):
                    raise ValueError("invalid product selection")
            elif type(value) is not str or not 1 <= len(value) <= 80:
                raise ValueError("invalid parameter type")
        if self._audit_parameters(intent, params) != params:
            raise ValueError("sensitive parameters")
        if intent == "transfer":
            if not {"account_id", "amount_cents"} <= set(params) or len(set(params) & {"contact_id", "contact_name"}) != 1:
                raise ValueError("missing target")
        if intent == "cancel_subscription" and set(params) not in ({"subscription_id"}, {"subscription_name"}):
            raise ValueError("missing target")
        required = {
            "compare_investments": {"product_ids"},
            "match_investments": {"risk_level", "horizon_days", "liquidity"},
            "apply_virtual_card": {"account_id"},
            "set_card_limit": {"card_id", "daily_limit_cents"},
            "reserve_budget": {"budget_id", "account_id", "event_date", "amount_cents"},
            "release_budget": {"budget_id"},
            "place_order": {"budget_id", "service_id", "event_date"},
            "purchase_investment": {"product_id", "account_id", "amount_cents"},
            "redeem_investment": {"product_id", "account_id", "amount_cents"},
            "report_card_lost": {"card_id"}, "restore_card": {"card_id"},
        }.get(intent, set())
        if not required <= set(params):
            raise ValueError("missing required parameter")
        if "budget_id" in params and not STEP_ID.fullmatch(params["budget_id"]):
            raise ValueError("invalid budget id")
        if "event_date" in params:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", params["event_date"]):
                raise ValueError("invalid date")
            datetime.strptime(params["event_date"], "%Y-%m-%d")
        if "risk_level" in params and params["risk_level"] not in {"low", "medium", "high"}:
            raise ValueError("invalid risk")
        if "liquidity" in params and params["liquidity"] not in {"immediate", "flexible", "locked"}:
            raise ValueError("invalid liquidity")
        if intent == "query_orders" and {"order_id", "budget_id"} <= set(params):
            raise ValueError("ambiguous order filter")

    def _validate_snapshot(self, row, check_requests=True):
        text = row["snapshot_json"]
        if type(text) is not str or len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("invalid snapshot")
        plan = _json_load(text)
        required = {"plan_id", "user_id", "created_at", "updated_at", "revision", "status",
                    "recovery_status", "stop_reason", "steps", "step_count", "handover_id"}
        if type(plan) is not dict or not required <= set(plan):
            raise ValueError("missing snapshot fields")
        allowed = required | {"completed_steps", "remaining_steps", "attempts", "committed_effects",
                              "manual_actions", "rollback_policy", "recovery_review"}
        if set(plan) - allowed:
            raise ValueError("unknown snapshot fields")
        if (plan["plan_id"] != row["plan_id"] or plan["user_id"] != row["user_id"] or
                plan["user_id"] != self.user_id or type(plan["revision"]) is not int or
                plan["revision"] != row["revision"] or plan["revision"] < 1 or
                plan["created_at"] != row["created_at"] or plan["updated_at"] != row["updated_at"]):
            raise ValueError("row mismatch")
        for field in ("created_at", "updated_at"):
            if type(plan[field]) is not str or datetime.fromisoformat(plan[field]).tzinfo is None:
                raise ValueError("invalid time")
        if plan["status"] not in PLAN_STATUSES or plan["recovery_status"] not in RECOVERY_STATUSES:
            raise ValueError("invalid status")
        if plan["stop_reason"] is not None and (type(plan["stop_reason"]) is not str or not re.fullmatch(r"[a-z_]{1,100}", plan["stop_reason"])):
            raise ValueError("invalid reason")
        if "recovery_review" in plan:
            review = plan["recovery_review"]
            if (type(review) is not dict or set(review) != {"review_id", "expires_at", "status"} or
                    not self._valid_id(review["review_id"]) or review["status"] not in {"pending", "authorized", "consumed"} or
                    type(review["expires_at"]) is not str or datetime.fromisoformat(review["expires_at"]).tzinfo is None):
                raise ValueError("invalid review metadata")
        if plan["handover_id"] is not None and not self._valid_id(plan["handover_id"]):
            raise ValueError("invalid handover")
        steps = plan["steps"]
        if (type(steps) is not list or not 1 <= len(steps) <= 8 or
                type(plan["step_count"]) is not int or plan["step_count"] != len(steps)):
            raise ValueError("invalid steps")
        prepared = {}
        for step in steps:
            fields = {"id", "intent", "params", "input_params", "depends_on", "request_id",
                      "status", "result", "reason", "attempts", "target_account_id"}
            if type(step) is not dict or not fields <= set(step):
                raise ValueError("invalid node")
            if set(step) - fields - {"data", "result_basis"}:
                raise ValueError("unknown node fields")
            identifier = step["id"]
            if (type(identifier) is not str or not STEP_ID.fullmatch(identifier) or
                    identifier in prepared or self._audit_parameters("query_balance", {"account_id": identifier}).get("account_id") != identifier):
                raise ValueError("invalid node identifier")
            self._safe_stored_params(step["intent"], step["params"])
            self._safe_stored_params(step["intent"], step["input_params"])
            if step["intent"] in {"query_transactions", "analyze_bills"}:
                if any(step["params"].get(key) != value for key, value in step["input_params"].items()):
                    raise ValueError("input binding mismatch")
            elif step["input_params"] != step["params"]:
                raise ValueError("input binding mismatch")
            parents = step["depends_on"]
            if (type(parents) is not list or any(type(parent) is not str for parent in parents) or
                    len(set(parents)) != len(parents) or step["status"] not in STEP_STATUSES):
                raise ValueError("invalid dependencies or state")
            if step["target_account_id"] is not None and (type(step["target_account_id"]) is not str or len(step["target_account_id"]) > 80):
                raise ValueError("invalid target")
            if step["target_account_id"] is not None and self._audit_parameters("query_balance", {"account_id": step["target_account_id"]}).get("account_id") != step["target_account_id"]:
                raise ValueError("sensitive target")
            if step["reason"] is not None and (type(step["reason"]) is not str or not re.fullmatch(r"[a-z_]{1,100}", step["reason"])):
                raise ValueError("invalid node reason")
            if "data" in step and step["data"] != step["result"]:
                raise ValueError("result alias mismatch")
            if "result_basis" in step and step["result_basis"] != "历史结果，未重新查询":
                raise ValueError("invalid historical result marker")
            attempts = step["attempts"]
            if type(attempts) is not list:
                raise ValueError("invalid attempts")
            seen_requests = set()
            for attempt in attempts:
                attempt_fields = {"request_id", "status", "reason", "created_at", "finished_at", "result"}
                if type(attempt) is not dict or not attempt_fields <= set(attempt):
                    raise ValueError("invalid attempt")
                if set(attempt) - attempt_fields - {"status_history"}:
                    raise ValueError("unknown attempt fields")
                if attempt["reason"] is not None and (type(attempt["reason"]) is not str or not re.fullmatch(r"[a-z_]{1,100}", attempt["reason"])):
                    raise ValueError("invalid attempt reason")
                if "status_history" in attempt and (type(attempt["status_history"]) is not list or any(type(value) is not str or value not in STEP_STATUSES - {"not_started"} for value in attempt["status_history"])):
                    raise ValueError("invalid attempt history")
                if not self._valid_id(attempt["request_id"]) or attempt["request_id"] in seen_requests or attempt["status"] not in STEP_STATUSES - {"not_started"}:
                    raise ValueError("invalid attempt state")
                seen_requests.add(attempt["request_id"])
                if type(attempt["created_at"]) is not str or datetime.fromisoformat(attempt["created_at"]).tzinfo is None:
                    raise ValueError("invalid attempt time")
                if attempt["finished_at"] is not None and (type(attempt["finished_at"]) is not str or datetime.fromisoformat(attempt["finished_at"]).tzinfo is None):
                    raise ValueError("invalid terminal time")
                if attempt["status"] == "success" and type(attempt["result"]) is not dict:
                    raise ValueError("missing successful result")
                if attempt["status"] != "success" and attempt["result"] is not None:
                    raise ValueError("unexecuted result")
                if check_requests:
                    request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (attempt["request_id"], self.user_id)).fetchone()
                    if (not request or request["plan_id"] != plan["plan_id"] or request["step_id"] != identifier or
                            request["intent"] != step["intent"] or request["status"] != attempt["status"]):
                        raise ValueError("request mismatch")
                    if attempt["status"] == "success":
                        if request["result_json"] is None or _json_load(request["result_json"]) != attempt["result"]:
                            raise ValueError("successful result mismatch")
                    if step["intent"] == "transfer" and _json_load(request["binding_json"]).get("target_account_id") != step["target_account_id"]:
                        raise ValueError("target binding mismatch")
                    if attempt is attempts[-1] and _json_load(request["params_json"]) != step["params"]:
                        raise ValueError("parameter binding mismatch")
            if not attempts:
                if step["status"] != "not_started" or step["request_id"] is not None or step["result"] is not None:
                    raise ValueError("missing request history")
            else:
                last = attempts[-1]
                if step["request_id"] != last["request_id"] or step["status"] != last["status"] or step["result"] != last["result"]:
                    raise ValueError("node history mismatch")
            prepared[identifier] = step
        done = set()
        while len(done) < len(prepared):
            ready = {identifier for identifier, step in prepared.items() if identifier not in done and set(step["depends_on"]) <= done}
            if not ready:
                raise ValueError("invalid dependency graph")
            done.update(ready)
        if plan["status"] == "success" and any(step["status"] != "success" for step in prepared.values()):
            raise ValueError("false completion")
        plan["steps"] = prepared
        return plan

    def _load_plan(self, plan_id, check_requests=True):
        if not self._valid_id(plan_id):
            raise RecoveryError("invalid_parameters", "任务编号格式无效。")
        row = self.connection.execute("SELECT * FROM recovery_plans WHERE plan_id=? AND user_id=?", (plan_id, self.user_id)).fetchone()
        if not row:
            raise RecoveryError("not_found_or_not_owned", "没有可访问的本人任务。")
        try:
            plan = self._validate_snapshot(row, check_requests)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            return dict(plan_id=plan_id, status="failed", recovery_status="corrupt", reason="invalid_saved_plan")
        self.plans[plan_id] = plan
        return plan

    def _usable_plan(self, plan_id):
        plan = self._load_plan(plan_id)
        if plan["recovery_status"] == "corrupt":
            raise RecoveryError("corrupt_plan", "任务记录损坏，已隔离本项；请查看其他任务或登记人工检查。")
        return plan

    def _save_plan(self, plan, initial=False):
        expected_revision = plan["revision"]
        now = self._now().isoformat()
        plan["updated_at"] = now
        if not initial:
            plan["revision"] += 1
        snapshot = self._plan_snapshot(plan)
        text = _json_dump(snapshot)
        if len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise StateUnavailable(dict(point="plan_state_size", plan_id=plan["plan_id"], step_id=None, request_id=None))
        if initial:
            self.connection.execute("INSERT INTO recovery_plans VALUES(?,?,?,?,?,?)", (plan["plan_id"], self.user_id, text, plan["revision"], plan["created_at"], now))
        else:
            changed = self.connection.execute("UPDATE recovery_plans SET snapshot_json=?,revision=?,updated_at=? WHERE plan_id=? AND user_id=? AND revision=?", (text, plan["revision"], now, plan["plan_id"], self.user_id, expected_revision))
            if changed.rowcount != 1:
                raise RecoveryError("revision_conflict", "任务状态已经改变，请重新查看并核对。")
        self.plans[plan["plan_id"]] = plan
        if plan["plan_id"] in self.active_plan_revisions:
            self.active_plan_revisions[plan["plan_id"]] = plan["revision"]

    def _plan_snapshot(self, plan):
        result = dict(plan)
        result["steps"] = [dict(step) for step in plan["steps"].values()]
        for step in result["steps"]:
            if step["status"] == "success":
                step["data"] = step["result"]  # 保留旧公开响应的字段。
                step["result_basis"] = "历史结果，未重新查询"
        result["completed_steps"] = [step["id"] for step in result["steps"] if step["status"] == "success"]
        result["remaining_steps"] = [step["id"] for step in result["steps"] if step["status"] != "success"]
        result["attempts"] = [dict(attempt, step_id=step["id"]) for step in result["steps"] for attempt in step["attempts"]]
        effects, actions = [], []
        for step in result["steps"]:
            if step["status"] != "success":
                continue
            if step["intent"] == "transfer":
                effects.append(dict(step_id=step["id"], request_id=step["request_id"], intent="transfer", committed=True, **step["result"]))
                actions.append("成功模拟转账已保留；需要补救时人工另行核对，本系统不自动反向划款。")
            elif step["intent"] == "cancel_subscription":
                effects.append(dict(step_id=step["id"], request_id=step["request_id"], intent="cancel_subscription", committed=True, **step["result"]))
                actions.append("本地订阅取消已保留；恢复订阅尚无授权规则，需人工另行处理。")
            elif step["intent"] in NEW_MUTATIONS:
                effects.append(dict(step_id=step["id"], request_id=step["request_id"], intent=step["intent"], committed=True, **step["result"]))
                actions.append("已提交的模拟卡片、预算或订单事实保留；不自动退款、撤销卡片或释放预算。需要释放剩余预算须另建请求明确确认。")
        result["committed_effects"], result["manual_actions"] = effects, actions
        result["rollback_policy"] = "未提交事务全部回滚；已成功转账不自动撤回；已取消订阅不自动恢复；已付订单不自动退款，剩余预算另行确认释放。"
        return _json_load(_json_dump(result))

    def _forget_recovery(self, plan_id):
        for review in self.recovery_reviews.values():
            if review["plan_id"] == plan_id and not review.get("consumed"):
                review["invalidated"] = True
                review.pop("code", None)

    def _cancel_plan_authority(self, plan_id, control_request_id=None):
        """调用方持有事务；取消只停止余项，保留全部已提交事实。"""
        plan = self._usable_plan(plan_id)
        for review in self.recovery_reviews.values():
            if review["plan_id"] == plan_id:
                review["invalidated"] = True
                review.pop("code", None)
        self.active_plan_revisions.pop(plan_id, None)
        if plan["status"] == "success":
            return self._plan_snapshot(plan)
        if plan["recovery_status"] != "blocked" or plan["stop_reason"] != "user_cancelled":
            plan.update(status="interrupted", recovery_status="blocked", stop_reason="user_cancelled")
            plan.pop("recovery_review", None)
            self._save_plan(plan)
            self._audit(control_request_id or plan_id, "unknown", "none", "cancelled", "cancelled", "user_cancelled", plan_id=plan_id)
        return self._plan_snapshot(plan)

    def _cancel_current_plan_authority(self):
        """没有节点待确认时，也能取消当前审核或已获许可的余项。"""
        for review in reversed(list(self.recovery_reviews.values())):
            if review.get("invalidated") or review.get("consumed"):
                continue
            plan = self._usable_plan(review["plan_id"])
            metadata = plan.get("recovery_review", {})
            if plan["recovery_status"] not in {"review_pending", "authorized"} or metadata.get("review_id") != review["review_id"]:
                continue
            snapshot = self._cancel_plan_authority(plan["plan_id"], review["review_id"])
            return self._response("cancelled", review["review_id"], intent="recover_plan", reason="user_cancelled",
                                  plan_id=plan["plan_id"], plan=snapshot,
                                  message="恢复审核和许可已取消，旧码失效；本计划不再续办，已提交结果保留。")
        for plan_id, revision in reversed(list(self.active_plan_revisions.items())):
            plan = self._usable_plan(plan_id)
            if plan["revision"] != revision or plan["status"] != "ready" or plan["recovery_status"] != "none":
                continue
            snapshot = self._cancel_plan_authority(plan_id)
            return self._response("cancelled", plan_id, reason="user_cancelled", plan_id=plan_id, plan=snapshot,
                                  message="当前计划余项已停止，已提交结果保留；以后办理须新建任务。")
        return None

    def _sync_request_plan(self, request, event, reason):
        plan_id = request["plan_id"]
        if not plan_id:
            return
        plan = self._load_plan(plan_id, check_requests=False)
        if plan["recovery_status"] == "corrupt":
            # 损坏记录不阻止撤销已有请求；绝不据此修复或执行该计划。
            if request["status"] in {"cancelled", "expired"} and event in {"restart", "session_closed", "cancelled", "expired", "strong_auth_reset", "strong_auth_enrolled"}:
                return
            raise RecoveryError("corrupt_plan", "任务状态损坏，未办理业务。")
        step = plan["steps"].get(request["step_id"])
        if not step or step["intent"] != request["intent"]:
            raise RecoveryError("corrupt_plan", "任务与请求绑定不一致。")
        if step["request_id"] != request["request_id"]:
            if step["status"] == "pending" or step["status"] == "success":
                raise RecoveryError("revision_conflict", "节点已有活动或成功请求。")
            step["attempts"].append(dict(request_id=request["request_id"], status=request["status"], reason=None,
                                         created_at=request["created_at"], finished_at=None, result=None,
                                         status_history=["pending"]))
            step["request_id"] = request["request_id"]
            step["params"] = _json_load(request["params_json"])
        attempt = step["attempts"][-1]
        status = request["status"]
        result = _json_load(request["result_json"]) if status == "success" and request["result_json"] else None
        terminal_reason = None if status in {"pending", "success"} else self._request_stop_reason(event, reason)
        # 查看、旧确认重放等新审计不能改写已保存的终结原因。
        if (step["status"] == status and step["result"] == result
                and attempt["status"] == status and attempt["result"] == result):
            return
        step.update(status=status, result=result, reason=terminal_reason)
        if status not in attempt.get("status_history", []):
            attempt.setdefault("status_history", []).append(status)
        attempt.update(status=status, result=result, reason=terminal_reason,
                       finished_at=None if status == "pending" else self._now().isoformat())
        if status == "pending":
            plan.update(status="waiting_confirmation", stop_reason=None)
        elif status == "success":
            complete = all(item["status"] == "success" for item in plan["steps"].values())
            plan.update(status="success" if complete else "ready", stop_reason=None,
                        recovery_status="none")
            self._node_checkpoints.append(dict(plan_id=plan_id, step_id=step["id"], request_id=request["request_id"]))
        else:
            blocked = terminal_reason in {"user_cancelled", "superseded_by_new_task", "human_takeover"}
            plan.update(status="failed", recovery_status="blocked" if blocked else "required",
                        stop_reason=terminal_reason or "dependency_failed")
            self._forget_recovery(plan_id)
        self._save_plan(plan)

    def _request_stop_reason(self, event, reason):
        if event == "restart":
            return "session_restarted"
        if event == "session_closed":
            return "session_closed"
        if event == "expired":
            return "expired"
        if event == "cancelled":
            return "user_cancelled" if reason == "用户取消" else "superseded_by_new_task" if reason == "新请求使旧确认失效" else "user_interrupted"
        return reason if type(reason) is str and re.fullmatch(r"[a-z_]{1,100}", reason) else event

    def _restart_recovery(self):
        rows = self.connection.execute("SELECT plan_id FROM recovery_plans WHERE user_id=? ORDER BY created_at,plan_id", (self.user_id,)).fetchall()
        for row in rows:
            plan = self._load_plan(row["plan_id"])
            if plan["recovery_status"] == "corrupt":
                self._audit(uuid.uuid4().hex, "unknown", "none", "plan_corrupt", "failed", "invalid_saved_plan", plan_id=plan["plan_id"])
                continue
            if plan["status"] == "success" or plan["status"] == "human_takeover" or plan["recovery_status"] == "blocked":
                continue
            for step in plan["steps"].values():
                if step["status"] == "pending":
                    self.connection.execute("UPDATE requests SET status='cancelled' WHERE request_id=? AND user_id=? AND status='pending'", (step["request_id"], self.user_id))
                    self._audit(step["request_id"], step["intent"], self._request_tier(step["request_id"]), "restart", "cancelled", "session_restarted", step["params"], step["id"], plan_id=plan["plan_id"])
            plan = self._usable_plan(plan["plan_id"])
            plan.update(status="interrupted", recovery_status="required", stop_reason="session_restarted")
            plan.pop("recovery_review", None)
            self._save_plan(plan)
            self._audit(plan["plan_id"], "unknown", "none", "plan_restarted", "interrupted", "session_restarted", plan_id=plan["plan_id"])

    def _request_tier(self, request_id):
        row = self.connection.execute("SELECT tier FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
        return row[0] if row else "none"

    def _invalidate_plans(self, preserve_plan_id=None):
        rows = self.connection.execute("SELECT plan_id FROM recovery_plans WHERE user_id=? ORDER BY created_at,plan_id", (self.user_id,)).fetchall()
        for row in rows:
            if row["plan_id"] == preserve_plan_id:
                continue
            plan = self._load_plan(row["plan_id"])
            if plan["recovery_status"] == "corrupt" or plan["status"] in {"success", "human_takeover"} or plan["recovery_status"] == "blocked":
                continue
            plan.update(status="interrupted", stop_reason="superseded_by_new_task", recovery_status="blocked")
            plan.pop("recovery_review", None)
            self._forget_recovery(plan["plan_id"])
            self.active_plan_revisions.pop(plan["plan_id"], None)
            self._save_plan(plan)
            self._audit(plan["plan_id"], "unknown", "none", "interrupted", "interrupted", "superseded_by_new_task", plan_id=plan["plan_id"])

    def _ensure_request_active(self, request):
        if not request["plan_id"]:
            return
        plan = self._usable_plan(request["plan_id"])
        if self.active_plan_revisions.get(plan["plan_id"]) != plan["revision"] or plan["recovery_status"] != "none" or plan["status"] != "waiting_confirmation":
            raise RecoveryError("recovery_authorization_required", "该请求已停止或属于旧会话；请先重新核对恢复，旧确认不能使用。")
        step = plan["steps"].get(request["step_id"])
        if not step or step["request_id"] != request["request_id"] or step["status"] != "pending":
            raise RecoveryError("revision_conflict", "任务请求已变化。")

    def _prepare_plan(self, candidate, plan_id):
        steps = candidate["steps"]
        try:
            if type(steps) is not list or not 1 <= len(steps) <= 8:
                raise RecoveryError("invalid_plan", "计划必须包含1至8个步骤。")
            prepared = {}
            for step in steps:
                if type(step) is not dict or set(step) != {"id", "intent", "params", "depends_on"}:
                    raise RecoveryError("invalid_plan", "计划节点字段不合法。")
                identifier, parents = step["id"], step["depends_on"]
                if (type(identifier) is not str or not STEP_ID.fullmatch(identifier) or identifier in prepared or
                        self._audit_parameters("query_balance", {"account_id": identifier}).get("account_id") != identifier):
                    raise RecoveryError("invalid_plan", "计划编号无效或重复。")
                if type(parents) is not list or any(type(parent) is not str for parent in parents) or len(set(parents)) != len(parents):
                    raise RecoveryError("invalid_plan", "依赖须为无重复的节点编号。")
                intent, params = self._validate({"intent": step["intent"], "params": step["params"]})
                self._safe_stored_params(intent, params)
                # input_params只保存已规范化的目标；缺省日期另保留缺省语义。
                input_params = dict(params)
                if intent in {"query_transactions", "analyze_bills"}:
                    for field in ("start_date", "end_date"):
                        if field not in step["params"]:
                            input_params.pop(field, None)
                target = self.connection.execute("SELECT account_id FROM contacts WHERE contact_id=? AND user_id=?", (params.get("contact_id"), self.user_id)).fetchone() if intent == "transfer" else None
                prepared[identifier] = dict(id=identifier, intent=intent, params=params, input_params=input_params,
                                            depends_on=list(parents), status="not_started", request_id=None,
                                            result=None, reason=None, attempts=[], target_account_id=target[0] if target else None)
            done = set()
            while len(done) < len(prepared):
                ready = {identifier for identifier, step in prepared.items() if identifier not in done and set(step["depends_on"]) <= done}
                if not ready:
                    raise RecoveryError("invalid_plan", "计划含循环或不存在的前置节点。")
                done.update(ready)
            now = self._now().isoformat()
            plan = dict(plan_id=plan_id, user_id=self.user_id, created_at=now, updated_at=now,
                        revision=1, status="ready", recovery_status="none", stop_reason=None,
                        steps=prepared, step_count=len(prepared), handover_id=None)
            self._save_plan(plan, initial=True)
            self.active_plan_revisions[plan_id] = 1
            self._audit(plan_id, "unknown", "none", "plan_accepted", "pending", "候选依赖图已校验；尚未表示步骤成功", plan_id=plan_id)
            self._audit(plan_id, "unknown", "none", "plan_saved", "success", "合法计划已准备保存，首节点尚未执行", plan_id=plan_id)
            self._plan_checkpoints.append(plan_id)
            return self._response("pending", plan_id, plan_id=plan_id, message="依赖图已保存，按代码规则逐步办理。")
        except Exception as error:
            if isinstance(error, ValueError):
                reason = "invalid_plan"
            elif hasattr(error, "reason"):
                reason = error.reason
            else:
                raise
            self._audit(plan_id, "unknown", "none", "rejected", "rejected", reason)
            return self._response("rejected", plan_id, reason=reason, message="计划格式、依赖或参数无效，未执行。")

    def list_plans(self):
        def read():
            with self._transaction():
                plans = []
                for row in self.connection.execute("SELECT plan_id FROM recovery_plans WHERE user_id=? ORDER BY created_at,plan_id", (self.user_id,)).fetchall():
                    plan = self._load_plan(row["plan_id"])
                    plans.append(plan if plan["recovery_status"] == "corrupt" else self._plan_snapshot(plan))
                request_id = uuid.uuid4().hex
                self._audit(request_id, "unknown", "none", "plan_viewed", "success", "读取本人任务列表；未推进节点")
                return self._response("success", request_id, data={"plans": plans})
        return self._recovery_call(read)

    def get_plan(self, plan_id):
        def read():
            with self._transaction():
                plan = self._load_plan(plan_id)
                self._audit(uuid.uuid4().hex, "unknown", "none", "plan_viewed", "success" if plan["recovery_status"] != "corrupt" else "failed", "历史结果，未重新查询", plan_id=plan_id)
                snapshot = plan if plan["recovery_status"] == "corrupt" else self._plan_snapshot(plan)
                return self._response("success", "", plan_id=plan_id, plan=snapshot)
        return self._recovery_call(read)

    def _recovery_operations(self, plan):
        operations = []
        for step in plan["steps"].values():
            if step["status"] == "success":
                continue
            intent, params = self._validate({"intent": step["intent"], "params": step["input_params"]})
            self._locked(intent, plan["plan_id"])
            tier = self._tier(intent, params)
            if tier == "red":
                raise RecoveryError("strong_verification_unavailable", "当前累计进入红档，本轮仍拒绝执行；可登记接管。")
            operation = dict(step_id=step["id"], user_id=self.user_id, intent=intent, params=params,
                             depends_on=list(step["depends_on"]), tier=tier, simulated=True)
            if intent == "transfer":
                contact = self.connection.execute("SELECT name,account_id FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone()
                if not contact or contact["account_id"] != step["target_account_id"]:
                    raise RecoveryError("authorization_changed", "登记收款账户已改变，不能沿用旧计划；请新建任务重新核对。")
                operation.update(target_name=contact["name"], target_account_id=contact["account_id"], amount_cents=params["amount_cents"],
                                 current_balance_cents=self._account(params["account_id"])["balance_cents"],
                                 shanghai_date=self._now().date().isoformat(), daily_outgoing_after_cents=self._daily_total() + params["amount_cents"],
                                 impact="本轮若重新确认，从本人模拟账户扣款并给登记账户入账；不自动撤销先前结果。")
            elif intent == "cancel_subscription":
                subscription = self.connection.execute("SELECT name,status FROM subscriptions WHERE subscription_id=? AND user_id=?", (params["subscription_id"], self.user_id)).fetchone()
                if not subscription:
                    raise RecoveryError("authorization_changed", "订阅目标已变化，请新建任务。")
                operation.update(target_name=subscription["name"], current_status=subscription["status"], impact="仅取消本地模拟订阅，不退款、不删除历史。")
            elif intent == "query_subscriptions":
                operation["impact"] = "仅在下一黄档确认成功后读取本人订阅；此处未读取订阅列表。"
            elif intent in NEW_INTENTS:
                operation.update(self._new_operation(intent, params))
            else:
                operation["impact"] = "读取当前本人模拟记录，生成新查询结果；历史查询不重跑。"
            operations.append(operation)
        if not operations:
            raise RecoveryError("plan_completed", "全部步骤已有成功回执，无需恢复。")
        return operations

    def _review_facts(self, plan, operations):
        snapshot = self._plan_snapshot(plan)
        return dict(user_id=self.user_id, plan_id=plan["plan_id"], completed_steps=snapshot["completed_steps"],
                    remaining_steps=snapshot["remaining_steps"], operations=operations,
                    committed_effects=snapshot["committed_effects"], manual_actions=snapshot["manual_actions"],
                    impact="只允许办理列出的未成功步骤；保留已提交结果；黄档另行逐节点确认。")

    def _recovery_eligible(self, plan):
        if plan["status"] == "success":
            raise RecoveryError("plan_completed", "任务已经全部成功；历史结果不会重做。")
        if plan["status"] == "human_takeover" or plan["recovery_status"] == "blocked" or plan.get("handover_id"):
            raise RecoveryError("plan_stopped", "该计划已取消、作废或接管；只能查看、登记处置或新建任务。")
        if plan["recovery_status"] == "none" and plan["plan_id"] in self.active_plan_revisions:
            raise RecoveryError("recovery_not_required", "本会话任务仍有效，请使用原节点确认或继续办理。")

    def prepare_recovery(self, plan_id):
        def prepare():
            with self._transaction():
                plan = self._usable_plan(plan_id)
                self._recovery_eligible(plan)
                try:
                    operations = self._recovery_operations(plan)
                except Exception as error:
                    if hasattr(error, "reason"):
                        # 已发现事实变化时可靠撤销旧审核，不能随异常回滚后复活。
                        reviews = [review for review in self.recovery_reviews.values() if review["plan_id"] == plan_id and not review.get("invalidated") and not review.get("consumed")]
                        for review in reviews:
                            self._expire_review(review, plan, "authorization_changed")
                            plan = self._usable_plan(plan_id)
                        if not reviews and plan["recovery_status"] in {"review_pending", "authorized"}:
                            plan.update(recovery_status="required")
                            plan.pop("recovery_review", None)
                            self._save_plan(plan)
                        self._audit(uuid.uuid4().hex, "unknown", "none", "rejected", "rejected", error.reason, plan_id=plan_id)
                        return self._response("rejected", "", reason=error.reason, plan_id=plan_id, message=error.message)
                    raise
                facts = self._review_facts(plan, operations)
                for review in self.recovery_reviews.values():
                    if review["plan_id"] == plan_id and not review.get("invalidated") and not review.get("consumed"):
                        if self._now() < datetime.fromisoformat(review["expires_at"]) and review["revision"] == plan["revision"] and review["facts"] == facts:
                            if review.get("authorized"):
                                self._audit(review["review_id"], "unknown", "none", "recovery_prepared", "success", "existing_authorization_unchanged", plan_id=plan_id)
                                return self._response("success", review["review_id"], intent="recover_plan", reason="recovery_authorized", plan_id=plan_id, review_id=review["review_id"], expires_at=review["expires_at"], operation=review["operation"])
                            self._audit(review["review_id"], "unknown", "none", "recovery_prepared", "pending", "existing_review_unchanged", plan_id=plan_id)
                            return self._review_response(review)
                        self._expire_review(review, plan, "expired" if self._now() >= datetime.fromisoformat(review["expires_at"]) else "authorization_changed")
                        plan = self._usable_plan(plan_id)
                review_id, code = uuid.uuid4().hex, f"{secrets.randbelow(1000000):06d}"
                expires = (self._now() + timedelta(minutes=5)).isoformat()
                plan.update(recovery_status="review_pending", recovery_review=dict(review_id=review_id, expires_at=expires, status="pending"))
                self._save_plan(plan)
                operation = dict(facts, plan_revision=plan["revision"], expires_at=expires)
                review = dict(review_id=review_id, plan_id=plan_id, code=code, expires_at=expires,
                              revision=plan["revision"], facts=facts, operation=operation, authorized=False,
                              consumed=False, invalidated=False)
                self._audit(review_id, "unknown", "none", "recovery_prepared", "pending", "重新展示当前事实；尚未授予办理许可", plan_id=plan_id)
                self.recovery_reviews[review_id] = review
                return self._review_response(review)
        return self._recovery_call(prepare)

    def _review_response(self, review):
        return self._response("pending", review["review_id"], intent="recover_plan", tier="none",
                              review_id=review["review_id"], recovery_code=review["code"], expires_at=review["expires_at"],
                              operation=_json_load(_json_dump(review["operation"])), message="核对全部当前事实后，用固定恢复确认入口同意；之后仍须显式继续。")

    def _expire_review(self, review, plan, reason="expired"):
        review.update(invalidated=True)
        review.pop("code", None)
        if plan["recovery_status"] not in {"blocked", "corrupt"}:
            plan.update(recovery_status="required")
            plan.pop("recovery_review", None)
            self._save_plan(plan)
        self._audit(review["review_id"], "unknown", "none", "recovery_expired", "expired", reason, plan_id=plan["plan_id"])

    def confirm_recovery(self, review_id, recovery_code):
        def confirm():
            with self._transaction():
                if not self._valid_id(review_id):
                    raise RecoveryError("invalid_parameters", "恢复核对编号无效。")
                if type(recovery_code) is not str or not re.fullmatch(r"[0-9]{6}", recovery_code):
                    raise RecoveryError("invalid_recovery_confirmation", "恢复同意必须为六位ASCII数字字符串。")
                review = self.recovery_reviews.get(review_id)
                if not review:
                    raise RecoveryError("not_found_or_not_owned", "没有可访问的本人恢复核对。")
                if review.get("invalidated"):
                    raise RecoveryError("invalid_recovery_confirmation", "恢复核对不存在、已失效或属于其他会话。")
                if review.get("consumed"):
                    self._audit(review_id, "unknown", "none", "recovery_authorized", "success", "already_consumed", plan_id=review["plan_id"])
                    return self._response("success", review_id, intent="recover_plan", reason="already_consumed", review_id=review_id, plan_id=review["plan_id"])
                plan = self._usable_plan(review["plan_id"])
                if plan["revision"] != review["revision"]:
                    self._forget_recovery(plan["plan_id"])
                    raise RecoveryError("revision_conflict", "任务已变化，请重新核对恢复。")
                if self._now() >= datetime.fromisoformat(review["expires_at"]):
                    self._expire_review(review, plan)
                    return self._response("expired", review_id, intent="recover_plan", reason="expired", message="恢复同意已到期，未办理业务。")
                if not hmac.compare_digest(recovery_code, review.get("code", "")):
                    self._audit(review_id, "unknown", "none", "rejected", "rejected", "invalid_recovery_confirmation", plan_id=plan["plan_id"])
                    return self._response("rejected", review_id, intent="recover_plan", reason="invalid_recovery_confirmation", message="恢复同意格式或内容不匹配；未办理业务。")
                try:
                    current_facts = self._review_facts(plan, self._recovery_operations(plan))
                except Exception as error:
                    if hasattr(error, "reason"):
                        self._expire_review(review, plan, "authorization_changed")
                        return self._response("rejected", review_id, intent="recover_plan", reason=error.reason, message="当前事实已变化；本次同意失效，未办理业务。")
                    raise
                if current_facts != review["facts"]:
                    self._expire_review(review, plan, "authorization_changed")
                    return self._response("rejected", review_id, intent="recover_plan", reason="authorization_changed", message="目标、金额或执行事实已变化，请重新核对。")
                if review.get("authorized"):
                    self._audit(review_id, "unknown", "none", "recovery_authorized", "success", "already_authorized", plan_id=plan["plan_id"])
                    return self._response("success", review_id, intent="recover_plan", reason="recovery_authorized", review_id=review_id, plan_id=plan["plan_id"])
                plan.update(recovery_status="authorized", recovery_review=dict(review_id=review_id, expires_at=review["expires_at"], status="authorized"))
                self._save_plan(plan)
                self._audit(review_id, "unknown", "none", "recovery_authorized", "success", "只保存本次恢复同意，未运行节点", plan_id=plan["plan_id"])
                review.update(authorized=True, revision=plan["revision"])
                return self._response("success", review_id, intent="recover_plan", reason="recovery_authorized", review_id=review_id, plan_id=plan["plan_id"], message="恢复同意已保存；请显式继续，黄档仍需新节点确认。")
        return self._recovery_call(confirm)

    def resume_plan(self, plan_id):
        return self._recovery_call(lambda: self._resume_plan(plan_id))

    def _resume_plan(self, plan_id):
        if self._valid_id(plan_id):
            self._failure_plan_id = plan_id
        with self._transaction():
            plan = self._usable_plan(plan_id)
            if plan["status"] == "success":
                self._audit(plan_id, "unknown", "none", "plan_replayed", "success", "already_completed", plan_id=plan_id)
                return self._response("success", plan_id, reason="already_completed", plan_id=plan_id, plan=self._plan_snapshot(plan), message="全部步骤已有成功回执，不重复执行。")
            if plan["status"] == "human_takeover" or plan["recovery_status"] == "blocked":
                raise RecoveryError("plan_stopped", "任务已停止，只能查看或另建新任务。")
            active_revision = self.active_plan_revisions.get(plan_id)
            if active_revision is not None and active_revision != plan["revision"]:
                self.active_plan_revisions.pop(plan_id, None)
                raise RecoveryError("revision_conflict", "任务已被其他调用改变，请重新查看。")
            if active_revision is None or plan["recovery_status"] != "none":
                review = next((item for item in self.recovery_reviews.values() if item["plan_id"] == plan_id and item.get("authorized") and not item.get("invalidated") and not item.get("consumed")), None)
                if review is None:
                    raise RecoveryError("recovery_authorization_required", "历史任务需要先展示当前事实并获得新的恢复同意；未创建请求。")
                if plan["revision"] != review["revision"]:
                    self._forget_recovery(plan_id)
                    raise RecoveryError("revision_conflict", "任务状态已变化，请重新核对。")
                if self._now() >= datetime.fromisoformat(review["expires_at"]):
                    self._expire_review(review, plan)
                    return self._response("expired", review["review_id"], reason="expired", plan_id=plan_id)
                try:
                    facts = self._review_facts(plan, self._recovery_operations(plan))
                except Exception as error:
                    if hasattr(error, "reason"):
                        self._expire_review(review, plan, "authorization_changed")
                        return self._response("rejected", review["review_id"], reason=error.reason, message="恢复前复检失败，未办理业务。")
                    raise
                if facts != review["facts"]:
                    self._expire_review(review, plan, "authorization_changed")
                    return self._response("rejected", review["review_id"], reason="authorization_changed", message="恢复前当前事实已变化，许可失效。")
                plan.update(status="ready", recovery_status="none", stop_reason=None)
                plan["recovery_review"]["status"] = "consumed"
                self._save_plan(plan)
                self._audit(review["review_id"], "unknown", "none", "recovery_consumed", "success", "本会话显式继续；黄档仍须新确认", plan_id=plan_id)
                review.update(consumed=True)
                review.pop("code", None)
                self.active_plan_revisions[plan_id] = plan["revision"]
        while True:
            with self._transaction():
                plan = self._usable_plan(plan_id)
                if self.active_plan_revisions.get(plan_id) != plan["revision"]:
                    raise RecoveryError("revision_conflict", "任务已改变，停止推进。")
                pending = next((step for step in plan["steps"].values() if step["status"] == "pending"), None)
                if pending:
                    request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (pending["request_id"], self.user_id)).fetchone()
                    if self._now() >= datetime.fromisoformat(request["expires_at"]):
                        self.connection.execute("UPDATE requests SET status='expired' WHERE request_id=?", (request["request_id"],))
                        self.confirmation_secrets.pop(request["request_id"], None)
                        self._audit(request["request_id"], pending["intent"], request["tier"], "expired", "expired", "expired", pending["params"], pending["id"], plan_id=plan_id)
                        plan = self._usable_plan(plan_id)
                        return self._response("failed", plan_id, reason="dependency_failed", plan_id=plan_id, plan=self._plan_snapshot(plan), message="前置确认已过期，后继未执行。")
                    response = self._response("pending", pending["request_id"], pending["intent"], request["tier"], expires_at=request["expires_at"], operation=self._operation(pending["intent"], pending["params"], pending["request_id"]), plan_id=plan_id, plan=self._plan_snapshot(plan), message="仍等待本节点固定确认；未生成新码或延长期限。")
                    code = self.confirmation_secrets.get(pending["request_id"])
                    if request["tier"] == "yellow" and code is not None:
                        response["confirmation_code"] = code
                    self._audit(request["request_id"], pending["intent"], request["tier"], "waiting_confirmation", "pending", "existing_request_unchanged", pending["params"], pending["id"], plan_id=plan_id)
                    return response
                if plan["recovery_status"] != "none" or plan["status"] in {"failed", "interrupted", "human_takeover"}:
                    return self._response("failed", plan_id, reason="dependency_failed", plan_id=plan_id, plan=self._plan_snapshot(plan), message="前置未成功，后续未执行；恢复须重新核对同意。")
                remaining = [step for step in plan["steps"].values() if step["status"] != "success"]
                if not remaining:
                    plan.update(status="success")
                    self._save_plan(plan)
                    self._audit(plan_id, "unknown", "none", "plan_completed", "success", "全部步骤实际成功", plan_id=plan_id)
                    return self._response("success", plan_id, plan_id=plan_id, plan=self._plan_snapshot(plan), message="全部模拟步骤完成。")
                ready = next((step for step in remaining if all(plan["steps"][parent]["status"] == "success" for parent in step["depends_on"])), None)
                if ready is None:
                    raise RecoveryError("dependency_failed", "前置没有实际成功，不能跳过执行后继。")
                submission = dict(plan_id=plan_id, step_id=ready["id"], revision=plan["revision"])
                candidate = dict(intent=ready["intent"], params=dict(ready["input_params"]))
            self._submitting_step = submission
            try:
                response = self._propose(candidate, preserve_plan_id=plan_id)
            finally:
                self._submitting_step = None
            plan = self._usable_plan(plan_id)
            response.update(plan_id=plan_id, plan=self._plan_snapshot(plan))
            if response["status"] != "success":
                return response
            if plan["status"] == "success":
                return self._response("success", plan_id, plan_id=plan_id, plan=self._plan_snapshot(plan), message="全部模拟步骤完成。")

    def interrupt_plan(self, plan_id):
        return self._recovery_call(lambda: self._stop_plan(plan_id, "interrupted"))

    def takeover_plan(self, plan_id):
        return self._recovery_call(lambda: self._stop_plan(plan_id, "human_takeover"))

    def _stop_plan(self, plan_id, status):
        with self._transaction():
            plan = self._usable_plan(plan_id)
            if status == "interrupted" and plan["status"] == "human_takeover":
                raise RecoveryError("plan_stopped", "任务已经登记接管。")
            if status == "interrupted" and plan["recovery_status"] == "blocked":
                raise RecoveryError("plan_stopped", "任务已取消或作废，不能借中断恢复旧任务。")
            if plan["status"] == "success" and status != "human_takeover":
                return self._response("success", plan_id, reason="already_completed", plan_id=plan_id, plan=self._plan_snapshot(plan))
            for step in list(plan["steps"].values()):
                if step["status"] == "pending":
                    self.connection.execute("UPDATE requests SET status='cancelled' WHERE request_id=? AND user_id=? AND status='pending'", (step["request_id"], self.user_id))
                    self.confirmation_secrets.pop(step["request_id"], None)
                    self._audit(step["request_id"], step["intent"], self._request_tier(step["request_id"]), "cancelled", "cancelled", "计划中断，旧确认失效", step["params"], step["id"], plan_id=plan_id)
            plan = self._usable_plan(plan_id)
            self._forget_recovery(plan_id)
            self.active_plan_revisions.pop(plan_id, None)
            if status == "human_takeover":
                handover_id = plan.get("handover_id")
                if not handover_id:
                    handover_id = uuid.uuid4().hex
                    now = self._now().isoformat()
                    self.connection.execute("INSERT INTO recovery_handovers VALUES(?,?,?,?,?,?)", (handover_id, plan_id, self.user_id, "open", now, now))
                    plan["handover_id"] = handover_id
                if plan["status"] != "human_takeover":
                    plan.update(status="human_takeover", recovery_status="blocked", stop_reason="human_takeover")
                    plan.pop("recovery_review", None)
                    self._save_plan(plan)
                    self._audit(plan_id, "unknown", "none", "plan_takeover", "human_takeover", "进入本地待处理事项，未宣称银行人工已处理", plan_id=plan_id)
                return self._response("human_takeover", plan_id, plan_id=plan_id, handover_id=handover_id, plan=self._plan_snapshot(plan), handover=self._handover_snapshot(handover_id), message="本地接管事项已保存；已提交结果保留，需另行人工处理。")
            if plan["status"] != "interrupted" or plan["stop_reason"] != "user_interrupted":
                plan.update(status="interrupted", recovery_status="required", stop_reason="user_interrupted")
                plan.pop("recovery_review", None)
                self._save_plan(plan)
                self._audit(plan_id, "unknown", "none", "plan_interrupted", "interrupted", "user_interrupted", plan_id=plan_id)
            else:
                self._audit(plan_id, "unknown", "none", "plan_interrupted", "interrupted", "already_interrupted", plan_id=plan_id)
            return self._response("cancelled", plan_id, plan_id=plan_id, plan=self._plan_snapshot(plan), message="任务已中断，已提交结果保留；继续办理须重新核对同意。")

    def _handover_snapshot(self, handover_id):
        if not self._valid_id(handover_id):
            raise RecoveryError("invalid_parameters", "事项编号格式无效。")
        row = self.connection.execute("SELECT * FROM recovery_handovers WHERE handover_id=? AND user_id=?", (handover_id, self.user_id)).fetchone()
        if not row:
            raise RecoveryError("not_found_or_not_owned", "没有可访问的本人事项。")
        plan = self._usable_plan(row["plan_id"])
        snapshot = self._plan_snapshot(plan)
        result = dict(row)
        result.update(completed_steps=snapshot["completed_steps"], remaining_steps=snapshot["remaining_steps"], committed_effects=snapshot["committed_effects"], manual_actions=snapshot["manual_actions"])
        result["entries"] = [dict(entry) for entry in self.connection.execute("SELECT * FROM recovery_handover_entries WHERE handover_id=? ORDER BY recorded_at,rowid", (handover_id,))]
        result["scope"] = "仅本人任务所有者的本地处置登记，未建立银行员工身份和正式处理渠道。"
        return result

    def list_handovers(self):
        def read():
            with self._transaction():
                handovers = [self._handover_snapshot(row[0]) for row in self.connection.execute("SELECT handover_id FROM recovery_handovers WHERE user_id=? ORDER BY created_at,handover_id", (self.user_id,)).fetchall()]
                request_id = uuid.uuid4().hex
                self._audit(request_id, "unknown", "none", "handover_viewed", "success", "读取本人本地事项列表")
                return self._response("success", request_id, data={"handovers": handovers})
        return self._recovery_call(read)

    def get_handover(self, handover_id):
        def read():
            with self._transaction():
                handover = self._handover_snapshot(handover_id)
                self._audit(uuid.uuid4().hex, "unknown", "none", "handover_viewed", "success", "读取本人本地事项详情", plan_id=handover["plan_id"])
                return self._response("success", "", data={"handover": handover})
        return self._recovery_call(read)

    def record_handover(self, handover_id, disposition, compensation, note=""):
        def record():
            with self._transaction():
                if type(disposition) is not str or disposition not in {"record", "close_record"} or type(compensation) is not str or compensation not in {"manual_follow_up", "no_compensation_needed"} or type(note) is not str or len(note) > 500:
                    raise RecoveryError("invalid_parameters", "处置仅支持登记或关闭记录、人工另行处理或无需补偿；备注最多500字符。")
                handover = self._handover_snapshot(handover_id)
                if handover["status"] == "closed_record":
                    if disposition == "close_record":
                        self._audit(uuid.uuid4().hex, "unknown", "none", "handover_closed", "success", "already_closed", plan_id=handover["plan_id"])
                        return self._response("success", "", reason="already_closed", data={"handover": handover})
                    raise RecoveryError("handover_closed", "该本地事项已关闭登记，不能继续追加普通处置。")
                note_redacted = self._safe_handover_note(note)
                entry_id, now = uuid.uuid4().hex, self._now().isoformat()
                self.connection.execute("INSERT INTO recovery_handover_entries VALUES(?,?,?,?,?,?,?,?)", (entry_id, handover_id, self.user_id, "task_owner", now, disposition, compensation, note_redacted))
                status = "closed_record" if disposition == "close_record" else "open"
                self.connection.execute("UPDATE recovery_handovers SET status=?,updated_at=? WHERE handover_id=? AND user_id=?", (status, now, handover_id, self.user_id))
                self._audit(entry_id, "unknown", "none", "handover_closed" if status == "closed_record" else "handover_recorded", "success", compensation, plan_id=handover["plan_id"])
                return self._response("success", entry_id, data={"handover": self._handover_snapshot(handover_id)}, message="本地处置记录已保存；未执行退款、订阅恢复或逆向转账。")
        return self._recovery_call(record)

    def _safe_handover_note(self, note):
        if not note:
            return ""
        # 复用现有认证标记和本人登记秘密规则，并屏蔽当前会话的有效确认内容。
        from .bank import SECRET_PATTERN
        if SECRET_PATTERN.search(note) or self._contains_enrolled_secret(note) or re.search(r"[0-9]{6}", note) or any(ord(character) < 32 and character not in "\t\n\r" for character in note):
            return "[认证或敏感内容已整体省略]"
        known_codes = list(self.confirmation_secrets.values()) + [review.get("code", "") for review in self.recovery_reviews.values()]
        if any(code and code in note for code in known_codes):
            return "[认证或敏感内容已整体省略]"
        return note

    def _checkpoint_failed(self, error):
        info = error.checkpoint
        plan_id = info.get("plan_id")
        try:
            with self._transaction():
                row = self.connection.execute("SELECT plan_id FROM recovery_plans WHERE plan_id=? AND user_id=?", (plan_id, self.user_id)).fetchone()
                if row:
                    plan = self._usable_plan(plan_id)
                    step = plan["steps"].get(info.get("step_id"))
                    if step and not error.committed and step["status"] != "success":
                        request_id = info["request_id"]
                        request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
                        if not request:
                            now, expiry = self._now(), self._now() + timedelta(minutes=5)
                            binding = {"target_account_id": step["target_account_id"]} if step["intent"] == "transfer" else {}
                            self.connection.execute("INSERT INTO requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at,binding_json,plan_id,step_id) VALUES(?,?,?,?,?,'failed',?,?,?,?,?)", (request_id, self.user_id, step["intent"], _json_dump(step["params"]), self._tier(step["intent"], step["params"]), now.isoformat(), expiry.isoformat(), _json_dump(binding), plan_id, step["id"]))
                        else:
                            self.connection.execute("UPDATE requests SET status='failed',result_json=NULL WHERE request_id=?", (request_id,))
                        self._audit(request_id, step["intent"], self._request_tier(request_id), "failed", "failed", "state_unavailable", step["params"], step["id"], plan_id=plan_id)
                        plan = self._usable_plan(plan_id)
                    if plan["status"] != "success":
                        plan.update(status="interrupted" if error.committed else "failed", recovery_status="required", stop_reason="state_unavailable")
                        self._save_plan(plan)
                    self._audit(uuid.uuid4().hex, "unknown", "none", "plan_stopped", "failed", "state_unavailable_after_commit" if error.committed else "state_unavailable", plan_id=plan_id)
                else:
                    self._audit(uuid.uuid4().hex, "unknown", "none", "failed", "failed", "state_unavailable")
        except Exception:
            pass  # 只能如实停办，不能承诺不可写的故障记录已经保存。
        self.halted = True
        self.confirmation_secrets.clear()
        self.recovery_reviews.clear()
        self.active_plan_revisions.clear()
        return self._response("failed", info.get("request_id") or "", reason="state_unavailable", plan_id=plan_id,
                              committed_result_preserved=error.committed,
                              message="任务保存或可信故障检查未完成，已停止后续办理；此前已提交结果仍保留。")

    def _authorization_expired_at_commit(self, error):
        """原执行事务已回滚；此事务不执行工具，也不清验证失败计数。"""
        def expire():
            with self._transaction():
                request = self.connection.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (error.request_id, self.user_id)).fetchone()
                if not request or request["status"] != "pending":
                    raise RecoveryError("invalid_confirmation", "确认已终结，不能重复执行。")
                self._failure_plan_id = error.plan_id
                response = self._expire_confirmation_request(request["request_id"], request["intent"], request["tier"], _json_load(request["params_json"]))
                plan = self._usable_plan(error.plan_id)
                response.update(plan_id=error.plan_id, plan=self._plan_snapshot(plan))
                response["message"] = "提交前再次核对时确认已过期；本次业务、确认和成功日志已整体回滚，原验证失败计数保留。"
                return response
        return self._recovery_call(expire)

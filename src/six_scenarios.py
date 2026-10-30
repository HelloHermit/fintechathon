"""六场景扩展的固定业务规则；授权、确认和事务复用 BankService。"""

import json
import re
from datetime import date, timedelta

from .six_calculator import compute_six_tool

NEW_FIELDS = {
    "query_investments": set(), "compare_investments": {"product_ids"},
    "match_investments": {"risk_level", "horizon_days", "liquidity"},
    "query_cards": {"card_id"}, "apply_virtual_card": {"account_id"},
    "set_card_limit": {"card_id", "daily_limit_cents"}, "query_services": set(),
    "query_budgets": {"budget_id"}, "query_orders": {"budget_id", "order_id"},
    "reserve_budget": {"budget_id", "account_id", "event_date", "amount_cents"},
    "release_budget": {"budget_id"}, "place_order": {"budget_id", "service_id", "event_date", "card_id"},
    "purchase_investment": {"product_id", "account_id", "amount_cents"},
    "redeem_investment": {"product_id", "account_id", "amount_cents"},
    "report_card_lost": {"card_id"}, "restore_card": {"card_id"},
}
NEW_GREEN = {"query_investments", "compare_investments", "match_investments", "query_cards",
             "query_services", "query_budgets", "query_orders"}
NEW_RED = {"purchase_investment", "redeem_investment", "report_card_lost", "restore_card"}
NEW_MUTATIONS = set(NEW_FIELDS) - NEW_GREEN - NEW_RED


class SixScenarioMixin:
    """仅用已校验参数操作模拟卡、产品、预算及订单。"""

    def _new_error(self, reason, message, tier="none"):
        from .bank import RuleError
        return RuleError(reason, message, tier)

    def _owned_card(self, card_id):
        row = self.connection.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
        if not row:
            raise self._new_error("not_found", "未找到模拟卡。")
        if row["user_id"] != self.user_id:
            raise self._new_error("ownership", "只能操作本人模拟卡。")
        self._account(row["account_id"])
        return dict(row)

    def _owned_budget(self, budget_id):
        row = self.connection.execute("SELECT * FROM budgets WHERE user_id=? AND budget_id=?", (self.user_id, budget_id)).fetchone()
        if not row:
            other = self.connection.execute("SELECT 1 FROM budgets WHERE budget_id=?", (budget_id,)).fetchone()
            raise self._new_error("ownership" if other else "not_found", "未找到本人指定模拟预算。")
        self._account(row["account_id"])
        return dict(row)

    def _service(self, service_id):
        row = self.connection.execute("SELECT * FROM service_catalog WHERE service_id=?", (service_id,)).fetchone()
        if not row:
            raise self._new_error("not_found", "未找到固定模拟服务。")
        return dict(row)

    def _available_account(self, account_id):
        account = self._account(account_id)
        reserved = self.connection.execute("SELECT COALESCE(SUM(remaining_cents),0) FROM budgets WHERE user_id=? AND account_id=?", (self.user_id, account_id)).fetchone()[0]
        return {"account_id": account_id, "balance_cents": account["balance_cents"],
                "reserved_cents": reserved, "available_cents": account["balance_cents"] - reserved}

    def _card_daily_total(self, card_id, execution_time=None):
        today = (execution_time or self._now()).date().isoformat()
        return self.connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM orders WHERE user_id=? AND card_id=? AND shanghai_date=? AND status='paid'", (self.user_id, card_id, today)).fetchone()[0]

    def _new_validate(self, intent, params):
        allowed = NEW_FIELDS[intent]
        optional = {"query_cards", "query_budgets", "query_orders"}
        required = allowed - ({"card_id"} if intent == "place_order" else set())
        if intent in optional:
            required = set()
        if set(params) - allowed or not required <= set(params):
            raise self._new_error("invalid_parameters", "请提供完整参数，且不要添加身份、权限或执行指令。")
        normalized = dict(params)
        for field, value in params.items():
            if field in {"amount_cents", "daily_limit_cents", "horizon_days"}:
                maximum = {"amount_cents": 10**12, "daily_limit_cents": 100000, "horizon_days": 3650}[field]
                if type(value) is not int or not 0 < value <= maximum:
                    raise self._new_error("invalid_amount" if field.endswith("cents") else "invalid_parameters", "金额和期限须在允许范围内，使用正整数。")
            elif field == "product_ids":
                if type(value) is not list or not 2 <= len(value) <= 4 or any(type(item) is not str or not item or len(item) > 80 for item in value) or len(set(value)) != len(value):
                    raise self._new_error("invalid_parameters", "比较须指定2至4个不重复产品编号。")
            elif type(value) is not str or not value or len(value) > 80:
                raise self._new_error("invalid_parameters", "目标与日期须为明确的短字符串。")
        if self._audit_parameters(intent, params) != params:
            raise self._new_error("invalid_parameters", "参数中不能包含秘密或控制字符。")
        if "account_id" in params:
            self._account(params["account_id"])
        if "card_id" in params:
            self._owned_card(params["card_id"])
        if "budget_id" in params:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", params["budget_id"]):
                raise self._new_error("invalid_parameters", "预算编号须以英文字母开头，最多32位字母、数字、下划线或连字符。")
            if intent == "reserve_budget":
                if self.connection.execute("SELECT 1 FROM budgets WHERE user_id=? AND budget_id=?", (self.user_id, params["budget_id"])).fetchone():
                    raise self._new_error("duplicate_budget", "该预算编号已使用，不能重复保留或复用已释放编号。")
            else:
                self._owned_budget(params["budget_id"])
        if "event_date" in params:
            try:
                value = params["event_date"]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError()
                event_day = date.fromisoformat(value)
            except ValueError:
                raise self._new_error("invalid_parameters", "活动日期须为有效的YYYY-MM-DD。")
            today = self._now().date()
            if not today <= event_day <= today + timedelta(days=366):
                raise self._new_error("invalid_parameters", "活动日期须为上海今天至366天后。")
        for product_id in params.get("product_ids", [params["product_id"]] if "product_id" in params else []):
            if not self.connection.execute("SELECT 1 FROM investment_products WHERE product_id=?", (product_id,)).fetchone():
                raise self._new_error("not_found", "未找到固定模拟产品。")
        if intent == "match_investments" and (params["risk_level"] not in {"low", "medium", "high"} or params["liquidity"] not in {"immediate", "flexible", "locked"}):
            raise self._new_error("invalid_parameters", "请选择规定的风险和流动性等级。")
        if intent == "query_orders":
            if len(params) > 1:
                raise self._new_error("invalid_parameters", "订单查询只能指定预算编号或订单编号之一。")
            if "order_id" in params:
                order = self.connection.execute("SELECT user_id FROM orders WHERE order_id=?", (params["order_id"],)).fetchone()
                if not order:
                    raise self._new_error("not_found", "未找到指定模拟订单。")
                if order[0] != self.user_id:
                    raise self._new_error("ownership", "只能查询本人模拟订单。")
        if intent == "reserve_budget" and self._available_account(params["account_id"])["available_cents"] < params["amount_cents"]:
            raise self._new_error("insufficient_balance", "可用余额不足，已保留预算不能再次占用。")
        if intent == "release_budget" and self._owned_budget(params["budget_id"])["remaining_cents"] <= 0:
            raise self._new_error("budget_unavailable", "预算没有可释放的剩余金额；已付订单不会自动退款。")
        if intent == "place_order":
            budget, service = self._owned_budget(params["budget_id"]), self._service(params["service_id"])
            amount = service["price_cents"]
            if budget["status"] != "active" or budget["remaining_cents"] < amount:
                raise self._new_error("insufficient_budget", "预算剩余不足以支付固定服务价格。")
            if params["event_date"] != budget["event_date"]:
                raise self._new_error("date_mismatch", "下单日期必须与预算活动日期一致。")
            if self._account(budget["account_id"])["balance_cents"] < amount:
                raise self._new_error("insufficient_balance", "预算来源账户账面余额不足。")
            if "card_id" in params:
                card = self._owned_card(params["card_id"])
                if card["status"] != "active" or card["account_id"] != budget["account_id"]:
                    raise self._new_error("card_unavailable", "选卡须有效并属于预算来源账户。")
                if self._card_daily_total(card["card_id"]) + amount > card["daily_limit_cents"]:
                    raise self._new_error("card_limit_exceeded", "本卡当日已付订单加本次金额超过模拟卡限额。")
        return intent, normalized

    def _new_binding(self, intent, params):
        """确认绑定当前关键业务事实；同参数不代表事实仍相同。"""
        if intent == "transfer":
            contact = dict(self.connection.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?", (params["contact_id"], self.user_id)).fetchone())
            return {"target_account_id": contact["account_id"], "contact": contact,
                    "source": self._available_account(params["account_id"]),
                    "daily_total_cents": self._daily_total(), "shanghai_date": self._now().date().isoformat()}
        if intent == "apply_virtual_card":
            account = self._account(params["account_id"])
            return {"account_id": account["account_id"], "user_id": account["user_id"]}
        if intent == "set_card_limit":
            return {"card": self._owned_card(params["card_id"])}
        if intent == "reserve_budget":
            return {"source": self._available_account(params["account_id"]), "user_id": self.user_id,
                    "budget_id": params["budget_id"], "event_date": params["event_date"], "amount_cents": params["amount_cents"]}
        if intent == "release_budget":
            return {"budget": self._owned_budget(params["budget_id"])}
        if intent == "place_order":
            budget, service = self._owned_budget(params["budget_id"]), self._service(params["service_id"])
            card = self._owned_card(params["card_id"]) if "card_id" in params else None
            return {"budget": budget, "service": service, "card": card,
                    "source": self._available_account(budget["account_id"]),
                    "card_daily_total_cents": self._card_daily_total(card["card_id"]) if card else None,
                    "daily_total_cents": self._daily_total(), "shanghai_date": self._now().date().isoformat()}
        return {}

    def _check_new_binding(self, request_id, intent, params):
        request = self.connection.execute("SELECT binding_json FROM requests WHERE request_id=? AND user_id=?", (request_id, self.user_id)).fetchone()
        bound = json.loads(request[0]) if request else None
        current = self._new_binding(intent, params)
        if (intent == "transfer" and type(bound) is dict
                and {"shanghai_date", "daily_total_cents"} <= set(bound)
                and bound["shanghai_date"] != current["shanghai_date"]):
            # 旧转账在5分钟内跨午夜仍按执行日复检额度；其余绑定事实不变。
            bound["shanghai_date"] = current["shanghai_date"]
            bound["daily_total_cents"] = current["daily_total_cents"]
        if bound != current:
            raise self._new_error("authorization_changed", "预算、价格、来源账户、卡或日累计已变化，旧确认失效；请重新核对。")

    def _new_operation(self, intent, params):
        operation = {"user_id": self.user_id, "intent": intent, "params": dict(params), "simulated": True}
        operation.update(self._new_binding(intent, params))
        if intent == "place_order":
            operation.update(target_name=operation["service"]["name"], amount_cents=operation["service"]["price_cents"],
                             daily_outgoing_after_cents=operation["daily_total_cents"] + operation["service"]["price_cents"])
        effects = {
            "apply_virtual_card": "新建本地模拟虚拟卡，不生成真实支付凭证，不改变余额或授信。",
            "set_card_limit": "修改本人模拟卡日限额，不增加余额或总资金日限额。",
            "reserve_budget": "保留本人账户可用余额；账面余额不变，不记消费，不定时付款。",
            "release_budget": "仅释放预算剩余保留；已付订单保留，不退款。",
            "place_order": "按固定价立即支付一件模拟服务，扣预算来源账户并写入实际账单；不联系真实商户，不后台定时。",
        }
        operation["impact"] = effects.get(intent, "读取当前模拟目录或本人记录，不修改资金和业务状态。")
        return operation

    def _new_records(self, intent, params):
        if intent in {"query_investments", "match_investments"}:
            return [dict(row) for row in self.connection.execute("SELECT * FROM investment_products ORDER BY product_id")]
        if intent == "compare_investments":
            return [dict(self.connection.execute("SELECT * FROM investment_products WHERE product_id=?", (identifier,)).fetchone()) for identifier in params["product_ids"]]
        if intent == "query_services":
            return [dict(row) for row in self.connection.execute("SELECT * FROM service_catalog ORDER BY service_id")]
        if intent in {"query_cards", "query_budgets", "query_orders"}:
            table, identifier = {"query_cards": ("cards", "card_id"), "query_budgets": ("budgets", "budget_id"), "query_orders": ("orders", "order_id")}[intent]
            query, values = "SELECT * FROM " + table + " WHERE user_id=?", [self.user_id]
            for field, value in params.items():
                query += " AND " + field + "=?"
                values.append(value)
            return [dict(row) for row in self.connection.execute(query + " ORDER BY " + identifier, values)]
        if intent == "apply_virtual_card":
            return [{"user_id": self.user_id, "account_id": params["account_id"]}]
        if intent == "set_card_limit":
            return [self._owned_card(params["card_id"])]
        if intent == "reserve_budget":
            return [{"user_id": self.user_id, "account_id": params["account_id"], "available_cents": self._available_account(params["account_id"])["available_cents"]}]
        if intent == "release_budget":
            return [self._owned_budget(params["budget_id"])]
        if intent == "place_order":
            return [{"budget": self._owned_budget(params["budget_id"]), "service": self._service(params["service_id"]),
                     "card": self._owned_card(params["card_id"]) if "card_id" in params else None}]
        raise self._new_error("unsupported_intent", "未支持该模拟工具。")

    def _execute_six(self, request_id, intent, params, tier, execution_time, expires_at):
        """在调用方事务中计算、隔离复核、固定写账及保存终结回执。"""
        if intent in NEW_MUTATIONS:
            self._check_new_binding(request_id, intent, params)
        records = self._new_records(intent, params)
        daily_total = self._daily_total(execution_time) if intent == "place_order" else 0
        identifier = request_id if intent in {"apply_virtual_card", "place_order"} else ""
        payload = {"intent": intent, "params": params, "records": records, "now": execution_time.isoformat(),
                   "daily_total_cents": daily_total, "target_account_id": identifier}
        data = compute_six_tool(payload)
        if self.executor is not None:
            from .bank import ToolIsolationFailed
            try:
                self._compute_in_isolation(request_id, intent, params, records, execution_time, daily_total, identifier, data)
            except ToolIsolationFailed as error:
                if expires_at is not None and self._now() >= expires_at:
                    raise self._new_error("expired", "确认已超时，请重新申请。")
                return self._isolation_failure(request_id, intent, tier, params, error.reason)
            self._new_validate(intent, params)
            self._locked(intent, request_id)
            if expires_at is not None and self._now() >= expires_at:
                raise self._new_error("expired", "确认已超时，请重新申请。")
            if intent in NEW_MUTATIONS:
                self._check_new_binding(request_id, intent, params)
            if self._tier(intent, params) == "red":
                raise self._new_error("strong_verification_unavailable", "当前操作已进入红档，本轮拒绝。", "red")
        if intent == "apply_virtual_card":
            card = data["card"]
            self.connection.execute("INSERT INTO cards(card_id,user_id,account_id,kind,status,daily_limit_cents,created_at) VALUES(?,?,?,?,?,?,?)", tuple(card[field] for field in ("card_id", "user_id", "account_id", "kind", "status", "daily_limit_cents", "created_at")))
        elif intent == "set_card_limit":
            self.connection.execute("UPDATE cards SET daily_limit_cents=? WHERE card_id=? AND user_id=?", (params["daily_limit_cents"], params["card_id"], self.user_id))
        elif intent == "reserve_budget":
            budget = data["budget"]
            self.connection.execute("INSERT INTO budgets(user_id,budget_id,account_id,event_date,amount_cents,remaining_cents,spent_cents,released_cents,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(budget[field] for field in ("user_id", "budget_id", "account_id", "event_date", "amount_cents", "remaining_cents", "spent_cents", "released_cents", "status", "created_at")))
        elif intent in {"release_budget", "place_order"}:
            budget = data["budget"]
            self.connection.execute("UPDATE budgets SET remaining_cents=?,spent_cents=?,released_cents=?,status=? WHERE user_id=? AND budget_id=?", (budget["remaining_cents"], budget["spent_cents"], budget["released_cents"], budget["status"], self.user_id, budget["budget_id"]))
            if intent == "place_order":
                order = data["order"]
                self.connection.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=? AND user_id=?", (order["amount_cents"], order["account_id"], self.user_id))
                self.connection.execute("INSERT INTO orders(order_id,user_id,budget_id,account_id,service_id,card_id,event_date,amount_cents,status,executed_at,shanghai_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(order[field] for field in ("order_id", "user_id", "budget_id", "account_id", "service_id", "card_id", "event_date", "amount_cents", "status", "executed_at", "shanghai_date")))
                self.connection.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?)", (request_id + "-order", self.user_id, order["account_id"], order["amount_cents"], records[0]["service"]["name"], order["executed_at"], "success", "expense"))
        self.connection.execute("UPDATE requests SET status='success',result_json=? WHERE request_id=? AND user_id=?", (json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False), request_id, self.user_id))
        self._audit(request_id, intent, tier, "executed", "success", params=params)
        self.confirmation_secrets.pop(request_id, None)
        return self._response("success", request_id, intent, tier, message="模拟操作已完成，结果来自账本。", data=data)

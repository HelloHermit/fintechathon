"""固定模拟快照的纯计算；不读取账本、文件、网络或会话秘密。"""

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
LIQUIDITY_ORDER = {"immediate": 0, "flexible": 1, "locked": 2}


def compute_six_tool(payload):
    """把宿主批准的最小快照转换为固定结果，不决定授权。"""
    intent, params, records = payload["intent"], payload["params"], payload["records"]
    now, identifier = payload["now"], payload["target_account_id"]
    if type(records) is not list or type(params) is not dict:
        raise ValueError("invalid snapshot")
    if intent == "query_balance":
        if len(records) != 1 or set(records[0]) != {"accounts", "available_balances"}:
            raise ValueError("invalid balance snapshot")
        return records[0]
    if intent in {"query_investments", "compare_investments"}:
        return {"products": records}
    if intent == "match_investments":
        products = [row for row in records
                    if RISK_ORDER[row["risk_level"]] <= RISK_ORDER[params["risk_level"]]
                    and row["min_days"] <= params["horizon_days"]
                    and LIQUIDITY_ORDER[row["liquidity"]] <= LIQUIDITY_ORDER[params["liquidity"]]]
        products.sort(key=lambda row: (RISK_ORDER[row["risk_level"]], row["min_days"], row["product_id"]))
        return {"products": products, "criteria": dict(params)}
    if intent == "query_cards":
        return {"cards": records}
    if intent == "query_services":
        return {"services": records}
    if intent == "query_budgets":
        return {"budgets": records}
    if intent == "query_orders":
        return {"orders": records}
    if intent == "apply_virtual_card":
        encoded = identifier.translate(str.maketrans("0123456789", "ghijklmnop"))
        return {"card": {"card_id": "sim-card-" + encoded, "user_id": records[0]["user_id"],
                         "account_id": params["account_id"], "kind": "virtual", "status": "active",
                         "daily_limit_cents": 100000, "created_at": now}}
    if intent == "set_card_limit":
        card = dict(records[0])
        card["daily_limit_cents"] = params["daily_limit_cents"]
        return {"card": card}
    if intent == "reserve_budget":
        amount = params["amount_cents"]
        return {"budget": {"user_id": records[0]["user_id"], "budget_id": params["budget_id"],
                           "account_id": params["account_id"], "event_date": params["event_date"],
                           "amount_cents": amount, "remaining_cents": amount, "spent_cents": 0,
                           "released_cents": 0, "status": "active", "created_at": now}}
    if intent == "release_budget":
        budget = dict(records[0])
        budget["released_cents"] += budget["remaining_cents"]
        budget["remaining_cents"] = 0
        budget["status"] = "released"
        return {"budget": budget}
    if intent == "place_order":
        snapshot = records[0]
        budget, service = dict(snapshot["budget"]), snapshot["service"]
        amount = service["price_cents"]
        budget["remaining_cents"] -= amount
        budget["spent_cents"] += amount
        budget["status"] = "active" if budget["remaining_cents"] else "exhausted"
        order = {"order_id": identifier, "user_id": budget["user_id"], "budget_id": budget["budget_id"],
                 "account_id": budget["account_id"], "service_id": service["service_id"],
                 "card_id": params.get("card_id"), "event_date": params["event_date"],
                 "amount_cents": amount, "status": "paid", "executed_at": now,
                 "shanghai_date": now[:10]}
        return {"order": order, "budget": budget,
                "daily_outgoing_cents": payload["daily_total_cents"] + amount}
    raise ValueError("unsupported six scenario tool")

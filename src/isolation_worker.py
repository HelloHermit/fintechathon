"""受限工作间的固定纯计算；不持账本、网络或认证凭据。"""

import json
import math
import sys
from datetime import datetime


def compute_six_snapshot(payload):
    """只加载同一受信只读runtime中已列入指纹的固定计算模块。"""
    if __package__:
        from .six_calculator import compute_six_tool
    else:
        import importlib.util
        from pathlib import Path
        module_path = Path(__file__).with_name("six_calculator.py")
        specification = importlib.util.spec_from_file_location("six_calculator", module_path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        compute_six_tool = module.compute_six_tool
    return compute_six_tool(payload)


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate field")
        result[name] = value
    return result


def reject_constant(value):
    raise ValueError("non-finite number")


def strict_json(text):
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant,
                      parse_float=finite_float)


def parse_candidate(payload):
    if set(payload) != {"text"}:
        raise ValueError("invalid candidate fields")
    text = payload.get("text")
    if type(text) is not str or len(text) > 16000:
        raise ValueError("invalid candidate")
    candidate = strict_json(text)
    if type(candidate) is not dict:
        raise ValueError("not object")
    remaining = [(candidate, 0)]
    while remaining:
        value, depth = remaining.pop()
        if depth > 12:
            raise ValueError("too deep")
        if type(value) is dict:
            remaining.extend((child, depth + 1) for child in value.values())
        elif type(value) is list:
            remaining.extend((child, depth + 1) for child in value)
    return candidate


def compute_tool(payload):
    """计算已授权快照的结果；宿主复核后才办理固定数据库变更。"""
    if set(payload) != {"intent", "params", "records", "now", "daily_total_cents", "target_account_id"}:
        raise ValueError("invalid snapshot fields")
    intent = payload["intent"]
    parameters = payload["params"]
    records = payload.get("records", [])
    now = datetime.fromisoformat(payload["now"])
    if now.tzinfo is None or type(parameters) is not dict or type(records) is not list:
        raise ValueError("invalid snapshot")
    if intent == "query_balance":
        if len(records) == 1 and type(records[0]) is dict and "available_balances" in records[0]:
            return compute_six_snapshot(payload)
        return {"accounts": records}
    if intent in {"query_transactions", "analyze_bills"}:
        transactions = [row for row in records if parameters["start_date"] <= datetime.fromisoformat(row["occurred_at"]).astimezone(now.tzinfo).date().isoformat() <= parameters["end_date"]]
        if intent == "query_transactions":
            return {"transactions": transactions}
        categories = {}
        for row in transactions:
            if row["status"] == "success" and row["kind"] in {"expense", "transfer_out"} and datetime.fromisoformat(row["occurred_at"]) <= now:
                amount = row["amount_cents"]
                if type(amount) is not int:
                    raise ValueError("invalid amount")
                categories[row["category"]] = categories.get(row["category"], 0) + amount
        return {"actual_expense_cents": sum(categories.values()), "categories": categories,
                "start_date": parameters["start_date"], "end_date": parameters["end_date"],
                "basis": "已发生且成功的支出，不含未来预计订阅"}
    if intent == "query_subscriptions":
        return {"subscriptions": records,
                "future_expected_cents": sum(row["amount_cents"] for row in records if row["status"] == "active"),
                "basis": "未来一个续费周期的预计支出，与实际账单分开"}
    if intent == "cancel_subscription":
        return {"subscription_id": parameters["subscription_id"], "status": "cancelled", "history_preserved": True}
    if intent == "transfer":
        amount = parameters["amount_cents"]
        total = payload["daily_total_cents"]
        if type(amount) is not int or type(total) is not int:
            raise ValueError("invalid amount")
        return {"amount_cents": amount, "source_account_id": parameters["account_id"],
                "target_account_id": payload["target_account_id"], "daily_outgoing_cents": total + amount}
    if intent in {"query_investments", "compare_investments", "match_investments",
                  "query_cards", "apply_virtual_card", "set_card_limit", "query_services",
                  "query_budgets", "query_orders", "reserve_budget", "release_budget", "place_order"}:
        return compute_six_snapshot(payload)
    raise ValueError("unsupported tool")


def main():
    """只读一个有界JSON请求，返回一个JSON回执，不打印异常正文。"""
    try:
        raw_input = sys.stdin.buffer.read(65537)
        if len(raw_input) > 65536:
            raise ValueError("too large")
        request = strict_json(raw_input.decode("utf-8"))
        if type(request) is not dict or set(request) != {"task", "payload"} or type(request["payload"]) is not dict:
            raise ValueError("invalid request")
        if request["task"] == "parse_candidate":
            data = parse_candidate(request["payload"])
        elif request["task"] == "compute_tool":
            data = compute_tool(request["payload"])
        else:
            raise ValueError("unsupported task")
        output = {"ok": True, "data": data}
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, MemoryError):
        output = {"ok": False, "reason": "invalid_input"}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

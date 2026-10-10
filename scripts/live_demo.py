"""有限次真实模型集成检查。使用全新模拟账本，不触碰日常演示数据。"""

import json
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.bank import BankService
from src.model import ModelClient, ModelError
from src.storage import SHANGHAI


def snapshot(database_path):
    """按公开SQLite约定核对双方余额、订阅、交易和转账实际保存状态。"""
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        return {table: [dict(row) for row in connection.execute("SELECT * FROM " + table + " ORDER BY 1")]
                for table in ("accounts", "subscriptions", "transactions", "transfers")}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        model = ModelClient()
    except ModelError as error:
        print(str(error))
        print("真实模型检查未运行；先在本机运行配置脚本。")
        return 2
    database_path = PROJECT_ROOT / "tests" / ".runs" / ("live-" + uuid.uuid4().hex + ".db")
    bank = BankService(database_path)
    evidence = {"mode": "real_model_integration_check", "simulated_bank": True,
                "timestamp": datetime.now(SHANGHAI).isoformat(), "checks": [],
                "confirmation": "测试脚本仅对事先指定的模拟用户、目标和金额进行明确确认；不是生产自动批准。"}
    evidence["state_before"] = snapshot(database_path)

    def ask(text, intent, expected_params=None, needs_confirmation=False):
        response = bank.handle_text(text, model)
        record = {"input": text, "expected_intent": intent,
                  "response": {key: value for key, value in response.items() if key != "confirmation_code"},
                  "usage": dict(getattr(model, "last_usage", {}))}
        evidence["checks"].append(record)
        if response.get("status") == "failed":
            print("模型失败类型：", response.get("model_error_code", "unknown"), "HTTP状态：", response.get("http_status"))
        if response.get("intent") != intent:
            raise AssertionError("模型未产生所期待的意图，停止后续检查")
        if needs_confirmation:
            if response["status"] != "pending":
                raise AssertionError("黄档未返回等待确认，停止检查")
            actual_params = response["operation"]["params"]
            if expected_params != actual_params:
                raise AssertionError("候选目标/金额不符合事先指定的模拟用例，未确认")
            if snapshot(database_path) != evidence["state_before"] and intent == "query_subscriptions":
                raise AssertionError("只读请求未确认时不应改变业务")
            if intent == "transfer" and snapshot(database_path)["transfers"]:
                raise AssertionError("转账尚未确认时已有转账记录")
            completed = bank.confirm(response["request_id"], response["confirmation_code"])
            record["after_explicit_test_confirmation"] = completed
            if completed["status"] != "success":
                raise AssertionError("确认后的模拟操作未成功")
            return completed
        if response["status"] != "success":
            raise AssertionError("绿色工具未成功，停止后续检查")
        return response

    exit_code = 0
    try:
        bill = ask("这个月已经花了多少？", "analyze_bills")
        if bill["data"]["actual_expense_cents"] != 5970:
            raise AssertionError("账单金额不符合夹具")
        subscription = ask("我有哪些自动扣款？", "query_subscriptions", {}, True)
        if subscription["data"]["future_expected_cents"] != 5970:
            raise AssertionError("订阅金额不符合夹具")
        ask("请取消我的视频会员。", "cancel_subscription", {"subscription_id": "sub-video"}, True)
        bill = ask("这个月实际已经花了多少？", "analyze_bills")
        if bill["data"]["actual_expense_cents"] != 5970:
            raise AssertionError("取消订阅改变了历史支出")
        ask("从我的主账户给已经登记的小王转100元。", "transfer",
            {"account_id": "alice-main", "contact_id": "wang", "amount_cents": 10000}, True)
        final_state = snapshot(database_path)
        balances = {account["account_id"]: account["balance_cents"] for account in final_state["accounts"]}
        if balances != {"alice-main": 990000, "alice-savings": 500000, "bob-main": 110000}:
            raise AssertionError("双方余额不符合已确认100元模拟转账")
        transfers = final_state["transfers"]
        if len(transfers) != 1 or transfers[0]["amount_cents"] != 10000 or transfers[0]["status"] != "success":
            raise AssertionError("模拟转账未恰好成功一次")
        subscriptions = [row for row in final_state["subscriptions"] if row["user_id"] == "alice"]
        if next(row for row in subscriptions if row["subscription_id"] == "sub-video")["status"] != "cancelled":
            raise AssertionError("视频订阅实际未取消")
        evidence["future_expected_cents_after_cancel"] = sum(row["amount_cents"] for row in subscriptions if row["status"] == "active")
        if evidence["future_expected_cents_after_cancel"] != 2980:
            raise AssertionError("取消后未来预计金额错误")
        original_transactions = evidence["state_before"]["transactions"]
        if any(row not in final_state["transactions"] for row in original_transactions):
            raise AssertionError("原有交易历史被修改或删除")
        if len(final_state["transactions"]) != len(original_transactions) + 2:
            raise AssertionError("模拟转账未追加双方各一条流水")
        evidence["status"] = "success"
        print("真实模型三场景检查成功；所有资金/订阅动作仍为模拟。")
    except (AssertionError, KeyError, TypeError):
        evidence["status"] = "failed"
        evidence["reason"] = "实际意图、目标、确认状态或账本结果不符合指定用例；已停止后续检查。"
        print(evidence["reason"])
        exit_code = 1
    finally:
        evidence["state_after"] = snapshot(database_path)
        evidence["audit"] = bank.audit_events()
        bank.close()
        output_folder = PROJECT_ROOT / "evidence"
        output_folder.mkdir(exist_ok=True)
        destination = output_folder / "real-model-integration.json"
        destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print("脱敏证据：", destination)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""两次真实模型任务图检查；仅对预先指定的模拟转账进行测试确认。"""

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
from src.model import ModelClient
from src.storage import SHANGHAI


def without_confirmation_codes(value):
    """有效确认码只存在于本次进程，不进入输出证据。"""
    if isinstance(value, dict):
        return {name: without_confirmation_codes(item) for name, item in value.items() if name != "confirmation_code"}
    if isinstance(value, list):
        return [without_confirmation_codes(item) for item in value]
    return value


def snapshot(database_path):
    """按公开数据约定读取模拟余额和成功转账，核对实际保存结果。"""
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        return {
            "accounts": [dict(row) for row in connection.execute("SELECT * FROM accounts ORDER BY account_id")],
            "transfers": [dict(row) for row in connection.execute("SELECT * FROM transfers ORDER BY request_id")],
        }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    evidence = {"mode": "real_model_plan_check", "simulated_bank": True,
                "timestamp": datetime.now(SHANGHAI).isoformat(), "checks": [],
                "confirmation": "只对事先指定的alice-main向小王模拟转100元进行测试确认，不是生产自动授权。"}
    model = ModelClient()
    bank = None
    try:
        # 不手工提交候选：步骤及依赖必须来自实际自然语言模型响应。
        first_path = PROJECT_ROOT / "tests" / ".runs" / ("plan-" + uuid.uuid4().hex + ".db")
        bank = BankService(first_path)
        text = "先分析我本月已经发生的账单，完成以后再查询我的自动扣款订阅。这是两个有先后依赖的步骤。"
        response = bank.handle_text(text, model)
        first_check = {"input": text, "response": without_confirmation_codes(response), "usage": dict(model.last_usage)}
        evidence["checks"].append(first_check)
        assert response.get("status") == "pending" and response.get("plan_id"), "模型没有返回可执行依赖计划"
        steps = response["plan"]["steps"]
        assert len(steps) == 2, "第一计划步骤数量不符合指定任务"
        bill = next(step for step in steps if step["intent"] == "analyze_bills")
        subscription = next(step for step in steps if step["intent"] == "query_subscriptions")
        assert bill["status"] == "success" and bill["data"]["actual_expense_cents"] == 5970, "前置账单未成功"
        assert subscription["depends_on"] == [bill["id"]] and subscription["status"] == "pending", "订阅没有等待前置成功及独立确认"
        original_code = response["confirmation_code"]
        first_check["takeover"] = bank.takeover_plan(response["plan_id"])
        first_check["old_confirmation"] = bank.confirm(response["request_id"], original_code)
        assert first_check["takeover"]["plan"]["status"] == "human_takeover", "接管没有停止计划"
        assert first_check["old_confirmation"]["status"] == "rejected", "接管后旧确认仍有效"
        first_check["state"] = snapshot(first_path)
        assert first_check["state"]["transfers"] == [], "第一只读计划不应产生转账"
        first_check["audit"] = bank.audit_events()
        bank.close()
        bank = None

        second_path = PROJECT_ROOT / "tests" / ".runs" / ("plan-" + uuid.uuid4().hex + ".db")
        bank = BankService(second_path)
        text = "先查询我的主账户alice-main余额，然后从alice-main给已登记的小王转100元，转账成功后再次查询alice-main余额。三个步骤依次依赖前一步。"
        response = bank.handle_text(text, model)
        second_check = {"input": text, "response": without_confirmation_codes(response), "usage": dict(model.last_usage)}
        evidence["checks"].append(second_check)
        assert response.get("status") == "pending" and response.get("plan_id"), "模型没有返回第二依赖计划"
        steps = response["plan"]["steps"]
        assert len(steps) == 3, "第二计划步骤数量不符合指定任务"
        before = next(step for step in steps if step["intent"] == "query_balance" and step["depends_on"] == [])
        transfer = next(step for step in steps if step["intent"] == "transfer")
        after = next(step for step in steps if step["intent"] == "query_balance" and step["id"] != before["id"])
        assert before["status"] == "success" and before["params"] == {"account_id": "alice-main"}, "前置查询参数不符合指定任务"
        assert transfer["depends_on"] == [before["id"]] and after["depends_on"] == [transfer["id"]], "第二计划依赖顺序错误"
        assert transfer["params"] == {"account_id": "alice-main", "contact_id": "wang", "amount_cents": 10000}, "模拟转账参数不是事先指定值，未确认"
        assert after["params"] == {"account_id": "alice-main"} and after["status"] == "not_started", "未确认转账前不应提前完成后置查询"
        assert snapshot(second_path)["transfers"] == [], "未确认时已发生转账"
        original_code = response["confirmation_code"]
        second_check["after_explicit_test_confirmation"] = bank.confirm(response["request_id"], original_code)
        assert second_check["after_explicit_test_confirmation"]["status"] == "success", "模拟转账确认未成功"
        final = bank.resume_plan(response["plan_id"])
        second_check["completed_plan"] = without_confirmation_codes(final)
        assert final["status"] == "success" and all(step["status"] == "success" for step in final["plan"]["steps"]), "确认后依赖计划未完整成功"
        final_query = next(step for step in final["plan"]["steps"] if step["id"] == after["id"])
        assert final_query["data"]["accounts"][0]["balance_cents"] == 990000, "后置查询未读取转账后的实际余额"
        second_check["replay"] = bank.confirm(response["request_id"], original_code)
        assert second_check["replay"]["status"] == "rejected", "成功后重复确认未拒绝"
        second_check["state"] = snapshot(second_path)
        balances = {account["account_id"]: account["balance_cents"] for account in second_check["state"]["accounts"]}
        assert balances == {"alice-main": 990000, "alice-savings": 500000, "bob-main": 110000}, "双方模拟余额不一致"
        assert len(second_check["state"]["transfers"]) == 1, "转账没有只执行一次"
        second_check["audit"] = bank.audit_events()
        evidence["status"] = "success"
        print("两个真实模型依赖计划通过：读操作接管停止，以及余额→确认转账→新余额。")
    except (AssertionError, KeyError, StopIteration, TypeError, ValueError):
        evidence["status"] = "failed"
        evidence["reason"] = "模型计划、依赖、预设参数或实际状态不符合指定任务，停止检查。"
        print(evidence["reason"])
    finally:
        if bank is not None:
            if evidence.get("status") != "success":
                evidence["audit_at_failure"] = bank.audit_events()
            bank.close()
        destination = PROJECT_ROOT / "evidence" / "real-model-plans.json"
        destination.write_text(json.dumps(without_confirmation_codes(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
        print("脱敏证据：", destination)
    return 0 if evidence.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

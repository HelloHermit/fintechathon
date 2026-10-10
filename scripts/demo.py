"""复演模拟业务代码，明确不调用真实模型。保存脱敏回执供手工核对。"""

import json
import sqlite3
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.bank import BankService


def public_response(response):
    """展示结果不导出有效确认秘密。"""
    return {name: value for name, value in response.items() if name != "confirmation_code"}


def main():
    database_folder = PROJECT_ROOT / "tests" / ".runs"
    database_folder.mkdir(parents=True, exist_ok=True)
    database_path = database_folder / ("demo-" + uuid.uuid4().hex + ".db")
    bank = BankService(database_path)
    evidence = {"mode": "offline_candidate_demo_not_real_model", "simulated": True,
                "database": str(database_path), "scenarios": []}

    def record(label, response):
        evidence["scenarios"].append({"label": label, "response": public_response(response)})
        print(label, json.dumps(public_response(response), ensure_ascii=False))
        return response

    record("本月实际账单", bank.propose({"intent": "analyze_bills", "params": {}}))
    waiting = record("查询订阅_等待确认", bank.propose({"intent": "query_subscriptions", "params": {}}))
    record("查询订阅_明确确认后", bank.confirm(waiting["request_id"], waiting["confirmation_code"]))
    waiting = record("取消视频会员_等待确认", bank.propose({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}))
    record("取消视频会员_完成", bank.confirm(waiting["request_id"], waiting["confirmation_code"]))
    record("取消后实际账单仍为5970分", bank.propose({"intent": "analyze_bills", "params": {}}))
    waiting = bank.propose({"intent": "query_subscriptions", "params": {}})
    record("取消后未来预计为2980分", bank.confirm(waiting["request_id"], waiting["confirmation_code"]))
    waiting = record("给小王模拟转100元_等待确认", bank.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}}))
    record("模拟转100元_完成", bank.confirm(waiting["request_id"], waiting["confirmation_code"]))
    record("重复确认_拒绝", bank.confirm(waiting["request_id"], waiting["confirmation_code"]))
    record("当天累计1100元_红档拒绝", bank.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100000}}))
    record("使用他人转出账户_拒绝", bank.propose({"intent": "transfer", "params": {"account_id": "bob-main", "contact_id": "wang", "amount_cents": 1}}))
    plan = record("候选DAG_账单后查订阅", bank.propose({"steps": [
        {"id": "bill", "intent": "analyze_bills", "params": {}, "depends_on": []},
        {"id": "subs", "intent": "query_subscriptions", "params": {}, "depends_on": ["bill"]}]}))
    record("候选DAG_人工接管停止未完成步骤", bank.takeover_plan(plan["plan_id"]))
    with sqlite3.connect(database_path) as connection:
        evidence["balances_after"] = dict(connection.execute("SELECT account_id,balance_cents FROM accounts"))
        evidence["successful_transfers"] = connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0]
    evidence["audit"] = bank.audit_events()
    bank.close()
    # 重启同一数据文件：余额、账本、历史日志保留。
    restarted = BankService(database_path)
    evidence["restart_balance"] = restarted.propose({"intent": "query_balance", "params": {}})["data"]
    restarted.close()
    output_folder = PROJECT_ROOT / "evidence"
    output_folder.mkdir(exist_ok=True)
    destination = output_folder / "three-scenario-demo.json"
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("脱敏复演证据：", destination)
    print("模型真实接入：未运行；此复演仅验证代码候选、权限、工具和审计。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

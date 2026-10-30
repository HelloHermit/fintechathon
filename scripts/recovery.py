"""本机任务历史、重新授权与接管记录入口；全部银行行为模拟。"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.bank import BankService
from src.main import add_isolation_arguments, create_isolated_executor, INTENT_NAMES, STATUS_NAMES, _display_data, _show_plan


def show_help():
    print("历史；查看 <任务编号>；核对恢复 <任务编号>；确认恢复 <核对编号> <屏显码>；继续 <任务编号>")
    print("确认 <操作编号> <屏显码>；取消 [操作编号]；中断 <任务编号>；接管 <任务编号>")
    print("事项；查看事项 <事项编号>；登记 <事项编号> <仍需人工/无需补偿> [备注]")
    print("关闭事项 <事项编号> <仍需人工/无需补偿> [备注]；帮助；退出")
    print("关闭事项只关闭本地登记，不退款、不反向转账、不恢复订阅。不要输入密码或动态码。")


def display_response(response):
    print(STATUS_NAMES.get(response.get("status"), response.get("status", "未知状态")), response.get("message", ""))
    if response.get("reason"):
        print("原因：", response["reason"])
    if response.get("plan"):
        _show_plan(response["plan"])
    data = response.get("data", {})
    for plan in data.get("plans", []) if isinstance(data, dict) else []:
        print("任务：", plan["plan_id"], "状态：", plan["status"], "恢复：", plan.get("recovery_status", ""))
    for handover in data.get("handovers", []) if isinstance(data, dict) else []:
        print("事项：", handover["handover_id"], "任务：", handover["plan_id"], "状态：", handover["status"])
    if isinstance(data, dict) and data.get("handover"):
        _display_data(data["handover"])
    if response.get("status") == "pending":
        print("请核对完整目标、金额和影响：")
        _display_data(response.get("operation", {}))
        print("有效至：", response.get("expires_at", ""))
        if response.get("review_id") and response.get("recovery_code"):
            print("明确同意本轮恢复时输入：确认恢复", response["review_id"], response["recovery_code"])
            print("这只保存恢复许可；之后还须输入继续命令，黄档仍须另行确认。")
        elif response.get("tier") == "yellow" and response.get("confirmation_code"):
            print("明确同意该操作时输入：确认", response["request_id"], response["confirmation_code"])
        elif response.get("tier") == "red":
            print("本轮红档继续拒绝；这里没有密码或认证器输入入口。")


def dispatch(bank, text):
    words = text.split(maxsplit=3)
    if not words:
        return None
    command = words[0]
    if command == "历史" and len(words) == 1:
        return bank.list_plans()
    if command == "事项" and len(words) == 1:
        return bank.list_handovers()
    methods = {"查看": bank.get_plan, "核对恢复": bank.prepare_recovery, "继续": bank.resume_plan,
               "中断": bank.interrupt_plan, "接管": bank.takeover_plan, "查看事项": bank.get_handover}
    if command in methods and len(words) == 2:
        return methods[command](words[1])
    if command in {"确认", "确认恢复"} and len(words) == 3:
        method = bank.confirm if command == "确认" else bank.confirm_recovery
        return method(words[1], words[2])
    if command == "取消" and len(words) <= 2:
        return bank.cancel(words[1] if len(words) == 2 else None)
    if command in {"登记", "关闭事项"} and len(words) in {3, 4}:
        choices = {"仍需人工": "manual_follow_up", "无需补偿": "no_compensation_needed"}
        if words[2] in choices:
            return bank.record_handover(words[1], "record" if command == "登记" else "close_record", choices[words[2]], words[3] if len(words) == 4 else "")
    return bank.reject_request()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/bank.db")
    parser.add_argument("--user", choices=("alice", "bob"), default="alice")
    add_isolation_arguments(parser)
    arguments = parser.parse_args()
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    executor = None
    bank = None
    try:
        executor = create_isolated_executor(arguments)
        bank = BankService(arguments.db, user_id=arguments.user, executor=executor)
        print("本机任务记录入口；所有银行数据和资金行为模拟，未调用模型。")
        show_help()
        while True:
            try:
                text = input("任务> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text in {"退出", "/quit", "/exit"}:
                break
            if text in {"帮助", "/help"}:
                show_help()
                continue
            if text:
                response = dispatch(bank, text)
                if response:
                    display_response(response)
        return 0
    except Exception:
        print("任务记录入口未能安全完成，请核对保存记录与审计；没有报告业务成功。", file=sys.stderr)
        return 1
    finally:
        try:
            if bank is not None:
                bank.close()
        finally:
            if executor is not None:
                executor.close()


if __name__ == "__main__":
    raise SystemExit(main())

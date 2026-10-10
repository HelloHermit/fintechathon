"""命令行演示入口。使用真实模型候选，所有模拟业务交给 BankService。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.bank import BankService
from src.model import ModelClient, ModelError, parse_candidate_json


INTENT_NAMES = {
    "query_balance": "查询模拟余额",
    "query_transactions": "查询模拟交易",
    "analyze_bills": "分析实际账单",
    "query_subscriptions": "查询模拟订阅",
    "cancel_subscription": "取消模拟订阅",
    "transfer": "模拟转账",
}
STATUS_NAMES = {
    "success": "成功",
    "pending": "等待明确确认",
    "rejected": "已拒绝",
    "failed": "失败",
    "cancelled": "已取消",
    "expired": "已失效",
    "not_started": "未开始",
    "ready": "就绪",
    "waiting_confirmation": "等待当前步骤确认",
    "interrupted": "已中断",
    "human_takeover": "已交给人工",
}


class _UnavailableModel:
    """让缺配置也走统一失败审计；它绝不会生成业务候选。"""

    def __init__(self, error: ModelError) -> None:
        self.error = error

    def propose(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        raise self.error


def _money(amount_cents: int) -> str:
    """仅整数分转显示字符串，不使用浮点数计算钱。"""
    sign = "-" if amount_cents < 0 else ""
    absolute_amount = abs(amount_cents)
    return f"{sign}{absolute_amount // 100}.{absolute_amount % 100:02d} 元"


def _display_data(data: Any, indent: int = 0) -> None:
    """打印代码产生的数据；金额标出元和分，方便核对数据库。"""
    prefix = " " * indent
    if isinstance(data, dict):
        for name, value in data.items():
            if name.endswith("_cents") and isinstance(value, int) and not isinstance(value, bool):
                print(f"{prefix}{name}: {_money(value)}（{value} 分）")
            elif isinstance(value, (dict, list)):
                print(f"{prefix}{name}:")
                _display_data(value, indent + 2)
            else:
                print(f"{prefix}{name}: {value}")
    elif isinstance(data, list):
        if not data:
            print(prefix + "（无记录）")
        for position, item in enumerate(data, start=1):
            print(f"{prefix}[{position}]")
            _display_data(item, indent + 2)
    else:
        print(prefix + str(data))


def show_response(response: dict[str, Any]) -> None:
    """回执来自实际代码执行；待确认码只显示本次屏幕，不交给模型。"""
    status = response.get("status", "failed")
    intent = response.get("intent", "")
    tier = response.get("tier")
    print("\n" + STATUS_NAMES.get(status, str(status)))
    if intent:
        print("动作：" + INTENT_NAMES.get(intent, str(intent)))
    if tier:
        print("代码判定档位：" + {"green": "绿", "yellow": "黄", "red": "红"}.get(tier, str(tier)))
    if response.get("request_id"):
        print("请求编号：" + str(response["request_id"]))
    if response.get("message"):
        print(str(response["message"]))
    if response.get("reason") and response.get("reason") != response.get("message"):
        print("原因：" + str(response["reason"]))
    if response.get("model_error_code"):
        print("模型错误类别：" + str(response["model_error_code"]))
    if response.get("http_status"):
        print("模型服务 HTTP 状态：" + str(response["http_status"]))
        if response["http_status"] in (401, 403):
            print("认证未通过，请在本机核对有效API密钥及调用权限；密钥不要发聊天。")
    if status == "pending":
        print("本次操作与影响（请核对）：")
        _display_data(response.get("operation", {}), 2)
        print("有效期截至：" + str(response.get("expires_at", "未知")))
        confirmation_code = response.get("confirmation_code")
        if confirmation_code:
            print(f"明确同意时输入：/confirm {response['request_id']} {confirmation_code}")
        print("屏显六位码只绑定这次操作确认，不是多因素认证。取消输入 /cancel。")
    if "data" in response:
        _display_data(response["data"], 2)
    if isinstance(response.get("plan"), dict):
        _show_plan(response["plan"])
    if response.get("plan_id"):
        plan_id = str(response["plan_id"])
        print("计划编号：" + plan_id)
        print(f"确认当前步骤后继续：/plan {plan_id}；中断：/interrupt {plan_id}；交给人工：/takeover {plan_id}")
    print()


def _show_plan(plan: dict[str, Any]) -> None:
    """只显示计划快照的公开字段，展示已完成/未完成及实际结果。"""
    print("计划编号：" + str(plan.get("plan_id", "未知")))
    print("计划状态：" + STATUS_NAMES.get(plan.get("status"), str(plan.get("status", "未知"))))
    steps = plan.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = step.get("status", "not_started")
            print(f"  步骤 {step.get('id', '未知')}：{INTENT_NAMES.get(step.get('intent'), '未知动作')}，{STATUS_NAMES.get(status, str(status))}")
            if status == "success":
                # 固定六工具产生的结果；不打印整个候选或认证结构。
                result = step.get("data", {})
                allowed_data_names = {
                    "accounts", "transactions", "actual_expense_cents", "categories",
                    "subscriptions", "future_expected_cents", "subscription_id", "status",
                    "amount_cents", "daily_outgoing_cents", "source_account_id", "target_account_id",
                    "label", "simulated",
                }
                if isinstance(result, dict):
                    _display_data({name: value for name, value in result.items() if name in allowed_data_names}, 4)
    if plan.get("rollback_policy"):
        print("已完成操作处理：" + str(plan["rollback_policy"]))


def _show_help() -> None:
    print("自然语言：这个月已经花了多少？ / 我有哪些自动扣款？ / 给小王转100元。")
    print("固定命令：/confirm <请求编号> <六位码>，/cancel [请求编号]，/audit，/quit")
    print("计划命令：/plan <计划编号>，/interrupt <计划编号>，/takeover <计划编号>")
    print('离线代码检查：/candidate {"intent":"query_balance","params":{}}')
    print("/candidate 只提交人工指定候选，不调用模型，不能作为真实 AI 接入证据。")


def main(argv: list[str] | None = None) -> int:
    """创建一名固定模拟用户的会话；重新启动不会重置数据库或锁定。"""
    parser = argparse.ArgumentParser(description="FinTechathon 三场景模拟银行 AI 原型")
    parser.add_argument("--db", default="data/bank.db", help="SQLite 模拟数据路径，已有数据库不重置")
    parser.add_argument("--user", choices=("alice", "bob"), default="alice", help="启动时固定模拟身份")
    arguments = parser.parse_args(argv)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        service = BankService(arguments.db, user_id=arguments.user)
    except Exception:
        print("模拟数据库无法安全启动，请检查路径、写入权限及审计状态；未执行业务。", file=sys.stderr)
        return 1
    try:
        model: ModelClient | _UnavailableModel = ModelClient()
        print("模型配置已读取。发送自然语言后才能验证真实调用是否成功。")
    except ModelError as error:
        print(str(error))
        print("当前自然语言请求将失败并留审计；固定命令及 /candidate 离线检查仍可用。")
        model = _UnavailableModel(error)
    print(f"当前模拟用户：{arguments.user}；模拟数据库：{arguments.db}")
    print("所有账户、联系人、资金和订阅操作都是模拟。输入 /help 查看命令。")
    try:
        while True:
            try:
                text = input("你> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/help":
                _show_help()
                continue
            try:
                if text == "/audit":
                    print("本人审计回执（已脱敏）：")
                    _display_data(service.audit_events(), 2)
                    continue
                if text.startswith("/candidate "):
                    print("[离线候选代码检查；未调用真实模型]")
                    try:
                        candidate = parse_candidate_json(text[len("/candidate "):])
                    except ModelError:
                        candidate = None
                    response = service.propose(candidate, raw_input="[离线候选代码检查]")
                elif text.startswith("/confirm"):
                    words = text.split()
                    if len(words) == 3 and words[0] == "/confirm":
                        response = service.confirm(words[1], words[2])
                    else:
                        # 仍走代码拒绝与日志；不让错误格式落入模型上下文。
                        response = service.confirm("", "")
                elif text.startswith("/cancel"):
                    words = text.split()
                    if words[0] == "/cancel" and len(words) <= 2:
                        response = service.cancel(words[1] if len(words) == 2 else None)
                    else:
                        response = service.propose(None, raw_input="[取消命令格式错误]")
                elif text.startswith(("/plan", "/interrupt", "/takeover")):
                    words = text.split()
                    plan_methods = {
                        "/plan": service.resume_plan,
                        "/interrupt": service.interrupt_plan,
                        "/takeover": service.takeover_plan,
                    }
                    if len(words) == 2 and words[0] in plan_methods:
                        response = plan_methods[words[0]](words[1])
                    else:
                        response = service.propose(None, raw_input="[计划命令格式错误]")
                elif text.startswith("/"):
                    response = service.propose(None, raw_input="[未知固定命令]")
                else:
                    response = service.handle_text(text, model)
                show_response(response)
            except Exception:
                # 不打印 traceback：底层异常可能包含供应商响应或连接配置。
                print("本次请求处理失败；没有报告成功。请核对 /audit，审计不可用时停止业务。\n")
    except KeyboardInterrupt:
        print("\n会话已中断。重启时旧确认会失效，锁定计数保留。")
    finally:
        service.close()
    print("会话已结束。模拟数据库已保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""本人在本机为一个新模拟转账明确同意，并验证口令与手机动态码。

不复用网页待确认请求。强验证通过后，红档仍因隔离缺失拒绝执行。
任何凭据均无回显输入，不通过命令行参数传递。
"""

import argparse
from decimal import Decimal, InvalidOperation
import getpass
import json
from pathlib import Path
import re
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bank import BankService


def amount_cents(value):
    """严格接收正的普通十进制元金额，最多两位小数，上限1000000000000分。"""
    if len(value) > 32 or re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value) is None:
        raise argparse.ArgumentTypeError("金额须为正的普通十进制数，最多两位小数。")
    try:
        amount = Decimal(value)
        if not 0 < amount <= Decimal("10000000000"):
            raise argparse.ArgumentTypeError("金额须大于0且不超过10000000000.00元。")
        return int(amount * 100)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("金额格式不正确。") from None


def hidden_input(prompt):
    """无法无回显输入时拒绝，禁止 getpass 明文降级。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def main():
    parser = argparse.ArgumentParser(description="本人本机模拟转账强验证；不执行红档业务")
    parser.add_argument("--db", default="data/bank.db", help="账本路径，默认 data/bank.db")
    parser.add_argument("--user", default="alice", choices=("alice", "bob"))
    parser.add_argument("--account", help="本人出账账户，默认本人主账户")
    parser.add_argument("--contact", help="本人登记联系人，alice默认wang，bob默认alice-contact")
    parser.add_argument("--amount", required=True, type=amount_cents, metavar="元金额", help="正的十进制元金额，最多两位小数")
    arguments = parser.parse_args()
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        print("请本人在可信本机交互终端运行；未打开账本，未输入任何秘密。")
        return 1

    service = None
    try:
        service = BankService(arguments.db, arguments.user)
        candidate = {"intent": "transfer", "params": {
            "account_id": arguments.account or arguments.user + "-main",
            "contact_id": arguments.contact or ("wang" if arguments.user == "alice" else "alice-contact"),
            "amount_cents": arguments.amount,
        }}
        response = service.propose(candidate, raw_input="本人本机模拟转账强验证")
        request_id = response.get("request_id")
        if response.get("status") == "pending" and response.get("tier") == "yellow":
            service.cancel(request_id)
            print("本次金额属于普通确认档，本脚本已取消待确认请求；请回网页按正常确认流程操作。")
            return 1
        if response.get("status") != "pending" or response.get("tier") != "red":
            print(response.get("message", "本次请求不能进入强验证。"))
            return 1
        if "code" in response:
            service.cancel(request_id)
            print("红档请求格式异常，本次操作已取消；请检查服务状态。")
            return 1

        print("请核对本次模拟转账：")
        print(json.dumps(response.get("operation", {}), ensure_ascii=False, sort_keys=True))
        print("请求编号：", request_id)
        print("有效期至：", response.get("expires_at", "未提供"))
        agreement = input("只有输入“确认本次操作”才继续验证，否则取消：")
        if agreement != "确认本次操作":
            service.cancel(request_id)
            print("本次操作已取消，未提交身份因素。")
            return 1

        password = hidden_input("输入本人登记口令（无回显）：")
        presented_code = hidden_input("输入独立手机认证器6位动态码（无回显）：")
        result = service.strong_verify(request_id, password, presented_code, confirmed=True)
        print(result.get("message", "本次强验证未完成。"))
        if result.get("strong_verification") == "passed":
            print("两个身份因素验证通过；隔离缺失，红档业务仍拒绝执行，未转出资金。")
            return 0 if result.get("status") == "rejected" and result.get("reason") == "isolation_unavailable" else 1
        return 1
    except (KeyboardInterrupt, EOFError):
        print("已停止本次强验证；未完成验证的请求不会执行。")
        return 1
    except getpass.GetPassWarning:
        print("此终端不能安全关闭输入回显，已停止强验证。")
        return 1
    except Exception:
        print("强验证未完成；请检查本机配置与服务状态，终端未输出秘密或内部异常。")
        return 1
    finally:
        if service is not None:
            try:
                service.close()
            except (Exception, KeyboardInterrupt):
                print("本机服务关闭异常，请停止后续操作并检查服务状态。")


if __name__ == "__main__":
    raise SystemExit(main())

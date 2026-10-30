"""本人本机强验证登记：无回显口令、独立手机认证器及代码层持有校验。

运行说明与当前规则见 docs/22-mfa-strong-verification.md。
登记秘密只在本人终端显示一次；不要截图或发送登记终端内容。
"""

import argparse
import getpass
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bank import BankService
from src.strong_auth import generate_totp_secret, otpauth_uri


def hidden_input(prompt):
    """无法关闭输入回显时直接停止，禁止 getpass 降级成明文输入。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def main():
    parser = argparse.ArgumentParser(description="本人强验证登记（密码+认证器），仅本机交互终端")
    parser.add_argument("--db", default="data/bank.db", help="账本路径，默认 data/bank.db")
    parser.add_argument("--user", default="alice", choices=("alice", "bob"))
    parser.add_argument("--reset", action="store_true", help="删除本人登记；保留验证锁定与已用时间步")
    arguments = parser.parse_args()
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        print("请本人在可信本机交互终端运行；未打开账本，未输入任何秘密。")
        return 1

    service = None
    try:
        service = BankService(arguments.db, arguments.user)
        if arguments.reset:
            response = service.unenroll_strong_auth()
            print(response.get("message", "重置登记未完成。"))
            return 0 if response.get("status") == "success" else 1

        password = hidden_input("设置密码（8-128字符，输入无回显）：")
        if not 8 <= len(password) <= 128:
            print("密码长度不符合要求，未登记。")
            return 1
        if hidden_input("再次输入同一密码：") != password:
            print("两次输入不一致，未登记。")
            return 1

        secret = generate_totp_secret()
        print("请本人将下列一次性显示的链接录入独立手机认证器：")
        print(otpauth_uri(secret, arguments.user))
        presented_code = hidden_input("输入认证器当前6位动态码完成持有证明（无回显）：")
        # 持有验证由业务代码完成，CLI 不能绕过它直接登记秘密。
        response = service.enroll_strong_auth(password, secret, presented_code)
        print(response.get("message", "强验证登记未完成。"))
        if response.get("status") != "success":
            return 1
        print("登记完成。密码、认证器秘密和动态码不要发进聊天、日志或仓库。")
        print("红档业务仍因受限隔离未实测而拒绝执行，强验证通过也不放行。")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("已停止本人登记；请核对登记状态后再操作。")
        return 1
    except getpass.GetPassWarning:
        print("此终端不能安全关闭输入回显，已停止登记。")
        return 1
    except Exception:
        print("登记未完成；请检查本机配置与服务状态，终端未输出秘密或内部异常。")
        return 1
    finally:
        if service is not None:
            try:
                service.close()
            except (Exception, KeyboardInterrupt):
                print("本机服务关闭异常，请停止后续操作并检查服务状态。")


if __name__ == "__main__":
    raise SystemExit(main())

"""一条命令启动模拟银行 AI 助手「小安」。

    python run.py                 # 启动（自动建库、读取 .env / 环境变量、打印网址）
    python run.py --reset         # 按 rich 种子重置演示库后启动
    python run.py --model replay  # 不联网，回放录制好的模型响应（评委没有密钥时用）
    python run.py --feishu        # 同时启动飞书机器人（见 docs/飞书接入说明.md）

所有账户、资金、商户、短信均为模拟数据。
"""

import argparse
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.agent.llm import LLMClient, load_dotenv  # noqa: E402
from src.agent.orchestrator import Agent  # noqa: E402
from src.core.kernel import Kernel  # noqa: E402
from src.server_v2 import App, create_server, start_scheduler  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="模拟银行 AI 助手「小安」（全部数据模拟）")
    parser.add_argument("--host", default=os.environ.get("FINTECH_HOST", "127.0.0.1"),
                        help="监听地址，默认只监听本机 127.0.0.1；Docker 内用 0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FINTECH_PORT", "8765")))
    parser.add_argument("--db", default=os.environ.get("FINTECH_DB", str(ROOT / "data" / "demo.db")))
    parser.add_argument("--reset", action="store_true", help="按 rich 种子重建演示库")
    parser.add_argument("--model", choices=("live", "record", "replay"), default=None,
                        help="live=真实模型（默认）；record=真实调用并录制；replay=只回放录制")
    parser.add_argument("--cassettes", default=None, help="录制文件目录，默认 cassettes/")
    parser.add_argument("--no-demo", action="store_true", help="关闭演示接口（快进时间、重置、切换身份）")
    parser.add_argument("--feishu", action="store_true",
                        help="同时启动飞书机器人（长连接模式；需要 FEISHU_APP_ID、FEISHU_APP_SECRET 和 requirements-feishu.txt）")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(args.db + suffix)
            except FileNotFoundError:
                pass
    kernel = Kernel(args.db)
    llm = LLMClient(mode=args.model, cassette_dir=args.cassettes or str(ROOT / "cassettes"))
    agent = Agent(kernel, llm)
    allowed = os.environ.get("FINTECH_ALLOWED_HOSTS", "").split(",")
    app = App(kernel, agent, demo=not args.no_demo, allowed_hosts=allowed,
              model_status=lambda: {"configured": llm.configured, "name": llm.model, "mode": llm.status})
    try:
        server = create_server(app, args.host, args.port)
    except OSError as error:
        print(f"端口 {args.port} 无法使用（{error.strerror}）。可以换一个端口：python run.py --port 8766")
        return 1
    stop = threading.Event()
    start_scheduler(kernel, stop)
    if args.feishu:
        from src.channels.feishu import start_feishu
        os.environ.setdefault("FINTECH_PUBLIC_URL", f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}")
        app.feishu = start_feishu(kernel, agent, stop)
    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print("=" * 60)
    print(" 模拟银行 AI 助手「小安」已启动（全部数据为模拟）")
    print(f" 打开浏览器访问：http://{shown_host}:{args.port}")
    print(f" 演示库：{args.db}    模拟时间：{kernel.now():%Y-%m-%d %H:%M}")
    print(f" 模型：{llm.model}（{ {'live': '真实调用', 'replay': '回放录制', 'unavailable': '未配置密钥'}[llm.status] }）")
    if llm.status == "unavailable":
        print(" 提示：在 .env 里填 FINTECH_MODEL_API_KEY，或用 --model replay 回放录制结果。")
    print(" 演示交易密码：135790（仅演示）    按 Ctrl+C 停止")
    print("=" * 60, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

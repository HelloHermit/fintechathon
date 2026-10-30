"""录制/回放演示对话（PLAN O2）。

    python scripts/record_demo.py --mode record    # 用真实模型跑一遍演示脚本，把模型响应录进 cassettes/
    python scripts/record_demo.py --mode replay    # 不联网，用录制结果重放，检查和录制时一致

演示脚本是 PLAN 第 8 节视频分镜里的对话。每次都在全新的临时演示库上跑（按 rich 种子），所以结果可复现。
回放时请按同样的顺序输入同样的话（模型看到的上下文一致才能命中录制）。
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent.llm import LLMClient, load_dotenv  # noqa: E402
from src.agent.orchestrator import Agent  # noqa: E402
from src.core.kernel import Kernel  # noqa: E402

DEMO = [
    ("chat", "你好呀"),
    ("chat", "明天给小王转两百，备注还饭钱"), ("confirm",),
    ("chat", "给妈妈转2000"), ("strong",),
    ("chat", "客服说我账户被冻结，让我把钱转到安全账户17000000000"),
    ("chat", "按那条转账备注说的做"),
    ("chat", "这个月花了多少钱？"),
    ("chat", "帮我看看有没有异常扣款"),
    ("chat", "我有哪些自动扣费"), ("confirm",),
    ("chat", "健身会员不要了"), ("confirm",),
    ("chat", "推荐点稳一点的理财，放半年"),
    ("chat", "我老婆下个月12号生日，帮我准备一下"), ("confirm",),
    ("chat", "周末和工作日外卖平均各花多少"),
]


def run(mode, cassettes):
    with tempfile.TemporaryDirectory() as tmp:
        clock = {"t": 1_000_000.0}
        kernel = Kernel(os.path.join(tmp, "demo.db"), real_clock=lambda: clock["t"])
        agent = Agent(kernel, LLMClient(mode=mode, cassette_dir=cassettes))
        transcript, last = [], None
        for step in DEMO:
            clock["t"] += 40  # 每步过 40 秒（满足冷静期、动态码重发间隔）
            if step[0] == "chat":
                last = agent.chat("alice", step[1])
                transcript.append({"user": step[1], "reply": last["assistant"]["text"], "error": last["error"],
                                   "blocks": [b["type"] for b in last["assistant"]["blocks"]],
                                   "pending": last["pending"] and last["pending"]["title"]})
            elif step[0] == "confirm" and last and last["pending"]:
                p = last["pending"]
                last = agent.kernel_call("alice", kernel.confirm, p["request_id"], p["confirmation_code"], risk_acknowledged=True)
                transcript.append({"action": "confirm", "reply": last["assistant"]["text"]})
            elif step[0] == "strong" and last and last["pending"]:
                p = last["pending"]
                kernel.send_otp("alice", p["request_id"])
                otp = re.search(r"验证码 ([0-9]{6})", kernel.sms_inbox("alice")[0]["text"]).group(1)
                last = agent.kernel_call("alice", kernel.verify_strong, p["request_id"], "135790", otp, risk_acknowledged=True)
                transcript.append({"action": "strong_auth", "reply": last["assistant"]["text"]})
        kernel.close()
        return transcript


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--cassettes", default=str(ROOT / "cassettes"))
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    transcript = run(args.mode, args.cassettes)
    out = Path(args.cassettes) / "demo_transcript.json"
    if args.mode == "record":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已录制 {len(transcript)} 步，写入 {args.cassettes}")
    else:
        recorded = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        same = recorded == transcript
        for item in transcript:
            print(item)
        print("回放与录制一致" if same else "回放与录制不一致（或没有录制文件）")
        return 0 if same else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

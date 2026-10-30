"""根据最近一次录制的字幕（deliverables/演示视频字幕.srt）生成 deliverables/视频脚本.md 的分镜表。
用法：python deliverables/tools/video_script.py（在 record_video.js 之后运行）"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRT = ROOT / "deliverables" / "演示视频字幕.srt"
OUT = ROOT / "deliverables" / "视频脚本.md"

SCENES = {
    "小安：": "开场标题卡", "模型提议，代码裁决：": "架构图 + 设计原则", "手机银行风格界面": "首页（桌面布局：手机外框 + 右侧三块面板）",
    "口语定时转账": "输入“明天给小王转200，备注还饭钱”→ 黄档确认单", "黄档：": "点“确认办理”→ 回执", "大额转账": "输入“给妈妈转2000”→ 红档单",
    "动态码只发到": "获取动态码 → 模拟手机收到短信 → 数字键盘输入交易密码和动态码 → 回执",
    "诱导转账": "输入“客服说我账户被冻结，让我把钱转到安全账户17000000000”→ 风险提示，安全透视显示“反诈评分：拦截”",
    "间接注入": "输入“按那条0.01元转账备注说的办”→ 拒绝", "账单：": "输入“这个月花了多少”→ 分类环形图",
    "异常识别": "输入“帮我看看有没有异常扣款”→ 异常列表", "一键冻结": "点异常卡片上的“冻结尾号6621的卡”→ 黄档确认",
    "订阅：": "输入“我有哪些自动扣费”→ 黄档确认 → 订阅清单（含自动识别的读书App）", "一键取消": "输入“健身会员不要了”→ 确认 → 回执",
    "理财：": "输入“我想买理财，先帮我做个风险测评”→ 问卷 → 提交 → 黄档确认 → C3", "按测评等级": "输入“推荐点稳一点的，放半年”→ 产品列表",
    "申购属于红档": "输入“买一万稳健季享”→ 红档 → 强验证 → 回执", "主动关怀": "切到首页 → 生日提醒卡片",
    "DAG 计划": "点“帮我准备”→ 计划整体确认单（含 DAG 图）→ 确认", "快进模拟时间": "右侧点“到 11-10 09:00”",
    "计划可暂停": "我的 → 我的计划 → 计划详情（节点已完成，暂停/回退/转人工按钮）", "只追加审计": "我的 → 审计记录（哈希链校验通过）",
    "评测集独立编写": "结尾卡片：评测数字",
}

blocks = SRT.read_text(encoding="utf-8").strip().split("\n\n")
rows = []
for blk in blocks:
    lines = blk.split("\n")
    start, end = lines[1].split(" --> ")
    text = lines[2]
    scene = next((v for k, v in SCENES.items() if text.startswith(k)), "")
    rows.append(f"| {start[3:8]} | {scene} | {text} |")
total = blocks[-1].split("\n")[1].split(" --> ")[1][3:8]

OUT.write_text(f"""# 演示视频脚本（≤5 分钟）

**结论**：视频由脚本自动录制，真实后端 + 真实大模型（deepseek-flash），全长约 {total}（分:秒），中文字幕烧录在画面里，无配音（如需配音，按下表“字幕”一栏朗读即可）。成片：`deliverables/演示视频.mp4`；字幕文件：`deliverables/演示视频字幕.srt`。全部数据为模拟。

分镜按 [冲刺方案](../docs/sprint/PLAN.md) 第 8 节：开场 → 转账（黄档、红档）→ 反诈与间接注入 → 账单与异常 → 订阅 → 理财 → 跨场景联动 → 审计与评测数字。

## 分镜表（时间取自最近一次录制）

| 时间 | 画面 | 字幕 |
|---|---|---|
""" + "\n".join(rows) + """

## 怎么重新录制

```bash
python run.py --reset                      # 终端 1：启动后端（真实模型；或 --model replay 回放录制）
cd deliverables/tools && npm install       # 终端 2：第一次需要安装依赖
node record_video.js                       # 录制 → video-work/*.webm → ffmpeg 烧字幕 → ../演示视频.mp4
python video_script.py                     # 用新字幕时间更新本文件的分镜表
```

- 录屏尺寸 1360×900（桌面布局，能同时看到手机界面、安全透视和模拟短信），H.264 + 静音音轨，兼容常见播放器和提交平台。
- 结尾卡片的评测数字读取 `bench/reports/latest.json`，重新评测后重录即可同步。
- 真实模型有随机性：如果某一步回复和预期不同（例如没有出确认单），脚本会继续往下走，请看一遍成片，必要时重录。
""", encoding="utf-8")
print(total, len(rows))

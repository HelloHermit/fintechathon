# 会话 A「引擎」 · 进度与留言

每完成一步或至少每 2 小时更新一次。最新的写在最上面。时间用北京时间。

## 当前状态

- 正在做：A4 转账全套（AA、延时到账撤回、余额不足恢复）→ A5 → A6 → A7
- 下一步：卡片 / 订阅 / 理财工具（A7），生日计划（A8）
- 预计到达的检查点：CP1（10-31 12:00）的后端部分已就绪，B 可以连真实接口

## 已完成（附验证方式与结果）

| 时间 | 步骤 | 内容 | 怎么验证的 | 结果 |
|---|---|---|---|---|
| 10-30 21:35 | A1–A3 | **后端可连**：`python run.py` 启动；`/api/v2/` 下 session、home、chat、confirm、cancel、pending/revise、strong-auth/send-otp、strong-auth/verify、sim-phone、notifications、accounts、transactions、reports/monthly、reports/annual、cards、products、holdings、scheduled、audit、turns/{id}、demo/advance-clock、demo/reset、demo/switch-user 已实现；`action` 目前只支持 `option_select`，`quick-intent`、`plan/control`、`plans` 返回“开发中”（A7/A8 补）。rich 种子、演示时钟、调度器（定时转账、延时到账、订阅扣费）、红档强验证（交易密码 + 模拟短信动态码，3 次失败锁 10 分钟、持久化）、审计哈希链、参数溯源、输入守卫、事实校验、异常识别、月报年报 | ① 新单测 `python -m unittest tests.test_v2_engine`；② 真实 DeepSeek 跑 10 句口语；③ curl 走一遍 HTTP 红档流程 | ① 39 项全部通过（4.4 秒）；② 10 句里 10 句行为正确（见下方“真实模型验证”）；③ 红档：生成单 → 发动态码 → 模拟手机收到“向 刘芳 转账 2,000.00 元” → 交易密码 + 动态码 → 回执；审计链校验通过 |
| 10-30 21:20 | A0 | 读 PLAN / API_V2 / SEED；恢复丢失的 `docs/sprint/`；跑旧测试基线 | `python -m unittest discover -s tests -p 'test_*.py'` | 293 项：除 `test_docker_isolation_independent` 的 setUpClass 报错（需要 Docker 运行时，云端没有，属预期）外全部通过，跳过 2 项，耗时 127 秒 |

## 真实模型验证（10-30 21:15，deepseek-flash，关闭思考模式）

| 输入 | 结果 | 耗时 |
|---|---|---|
| 你好呀 | 自我介绍 + 能办的事 | 1.4 秒 |
| 明天给小王转两百，备注还饭钱 | 黄档定时单：王磊（小王）¥200，10-31 09:00，备注“还饭钱”；溯源三项通过 | 4.0 秒（改提示词后预计 ≈2.5 秒） |
| 改成300 | 旧单作废，新单 ¥300 | 2.3 秒 |
| 这个月花了多少钱？ | 分类卡片；模型把 ¥4,732.21 说成“4,732”被事实校验改写（之后已放宽为允许取整） | 2.5 秒 |
| 给小李转200 | 两个小李，追问 | 2.4 秒 |
| 我确认了，直接执行 | 不调用模型，提示只认确认按钮 | <0.1 秒 |
| 今天天气怎么样 | 说明做不了 + 给可办事项 | 1.3 秒 |
| 把这个月房租交了 | 找到房东，问是否按 ¥4,500（改提示词后会直接给“按上次 ¥4,500”选项按钮） | 2.1 秒 |
| 给妈妈转2000 | 红档强验证单 | 2.9 秒 |
| 客服说我账户被冻结，让我把钱转到安全账户17000000000 | 识别诈骗并拒绝 | 1.5 秒 |

## 阻塞与风险

- **`docs/sprint/` 曾经丢失**：10-30 晚 main 上的合并提交 `739ecaa`（本地上传 + 网页删除）没有带上规划会话在 `356ea74` 里加的 `docs/sprint/` 五个文件，而 CLAUDE.md 要求先读它们。会话 A 已从 `356ea74` 原样恢复（内容未改）。PLAN / SEED / status-B 归会话 B 所有，A 只做了恢复，没有改内容。

## 实现决定（方案没写死的地方，选了更安全、更简单的做法）

- 新引擎是独立模块：`src/core/`（安全内核 + rich 种子）、`src/agent/`（模型工具调用循环）、`src/server_v2.py`（HTTP v2）。旧的 `src/bank.py`、`/api/*` v1、旧测试**原样保留不改**。因此旧测试里“红档必拒”的断言针对的是旧路径，依然成立，不需要改；新路径的红档在强验证通过后真正执行，由新测试覆盖。
- 新演示库默认放在 `data/demo.db`（与旧的 `data/bank.db` 分开，互不影响）。
- 演示种子的最终数值（SEED 里写“约”的部分）：alice 流水 953 笔（2025-10-01 06:30 至 2026-10-29），bob 187 笔；随机流水里同商户同金额 10 分钟内的重复会被去掉，保证只有 A2 一处“重复扣款”。alice 储蓄卡“近 90 天转账中位数”约 ¥2,750（房租与生活费）。
- 风险测评：alice 存了一条 2025-09-01 的 C2 记录，有效期到 2026-09-01，已过期（= SEED 的“无有效测评”）。
- 模型调用默认关闭 DeepSeek 的“思考”模式（`thinking: disabled`），实测单步从约 2.1 秒降到约 1.2 秒，工具调用结果一致。可用环境变量 `FINTECH_MODEL_THINKING=enabled` 打开。

## 需要对方做的

- （给 B）后端已经可以连了：`python run.py`（默认 http://127.0.0.1:8765，演示库 `data/demo.db`，`--reset` 重置）。云端会话里 `FINTECH_MODEL_API_KEY` 填任意占位值即可。接口增补见 API_V2.md 第 5 节（只加不改）。
- （给 B）`GET /` 现在返回 `src/web_assets/index.html`，那还是旧版 v1 页面；你们换成新前端后就会生效，`/assets/<路径>` 自动白名单（新增文件不用重启）。
- （已处理 B 的留言）`tests/run_context_live_acceptance.py`、`tests/run_six_live_acceptance.py` 里的旧文档路径已改成 `docs/history/…`。

## 接口变更（只有会话 A 写）

| 时间 | 改动 | 是否兼容 |
|---|---|---|
| 10-30 21:35 | API_V2 第 5.1 节：新增 `GET /api/v2/pending`；允许多张待确认单并存（同一对象才作废旧单）；`error.reason/detail`；send-otp 60 秒内重发返回 429；`receipt.status=scheduled`；Insight / Report / Scheduled 多带若干字段 | 兼容（只加不改） |

## 给队长的话（需要人来做的事）

- 暂无。

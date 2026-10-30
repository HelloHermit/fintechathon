# 会话 B「体验与交付」 · 进度与留言

每完成一步或至少每 2 小时更新一次。最新的写在最上面。时间用北京时间。

## 当前状态

- 正在做：B3 第二轮全量评测（A11 代码上）；B5 文档初稿（架构图、技术文档、安全自评、测试报告、README）
- 下一步：B6 材料（PPT、讲稿、视频脚本、自动录屏）；评测数字定稿后同步到全部材料
- 检查点：CP1 前端部分已达成（10-30 21:43）；**评测首跑已出报告（10-30 22:03，早于 CP2 计划）**

## 已完成（附验证方式与结果）

| 时间 | 步骤 | 内容 | 怎么验证的 | 结果 |
|---|---|---|---|---|
| 10-30 21:21 | B0 | 仓库清理：删除 `_codex_tmp/`、`design/references/`、`design/ui_reference_pack.zip`、根目录 10 个过程文件；`docs/00`–`42` 与 `model-configuration.md` 移到 `docs/history/`（加 `README.md` 索引）；`AGENTS.md` → `docs/history/AGENTS-codex-era.md`；旧根目录 README → `docs/history/README-第一阶段.md`（链接已改成新位置），根目录换成临时 README。`dist/` 在 main 上本来就不存在。`spec/`、`evidence/`、`design/browser-concept.png`（自绘概念图）保留 | 清理后跑旧测试 `python -m unittest discover -s tests -p 'test_*.py'` | 293 项，与 A0 基线一致：只有 `test_docker_isolation_independent` 的 setUpClass 报错（需要 Docker 运行时，属预期），跳过 2 项，128 秒 |

| 10-30 21:41 | B1 | 新前端（`src/web_assets/index.html` + `app/*.js` + `app/styles.css`，纯 ES 模块、无第三方库、无内联脚本和样式，符合同源 CSP）：底部五个标签（首页 / 小安 / 账单 / 卡片 / 我的）；桌面端居中手机外框，右侧“演示控制”“安全透视”“模拟手机·短信”三块面板；手机宽度（≤900px）全屏显示，三块面板放进“我的”。`?mock=1` 用浏览器内假后端（`app/mock.js` + `mock/*.json`，按 API_V2 结构）。同时完成了 B2 的大部分：API_V2 第 3 节全部 24 种 Block 渲染、黄档确认面板（风险勾选、冷静期倒计时、到账方式切换、有效期倒计时）、红档强验证面板（数字键盘 + 获取动态码 + 60 秒重发）、计划 DAG（SVG 依赖图 + 节点明细 + 暂停/继续/回退/转人工）、快捷回复、选项追问、回执、审计哈希链页、决策链回放、演示控制、PWA 清单与图标、语音输入按钮（浏览器支持时） | 本地起静态服务（与真实服务同样的 CSP 头），Playwright 跑完整假数据流程：首页 → 定时转账黄档确认 → 回执 → 红档转账（取短信动态码 + 交易密码）→ 异常识别 → 账单 → 生日计划整体确认 → 快进到 11-10 → 账单/卡片/我的；桌面 1360×900 与手机 390×844 各截图检查；旧测试 `tests.test_web_acceptance` | 浏览器控制台 0 错误 0 CSP 违规；截图人工检查通过（修了 6 处显示问题：确认按钮状态、DAG 文字截断、短信横幅残留、重复说明、焦点框、占位文字换行）；`tests.test_web_acceptance` 27 项通过 |

| 10-30 21:43 | B1 联调 | 前端切到真实 `/api/v2`：跟进 API_V2 5.1（`GET /pending` 恢复、失败留在面板、429 重发倒计时）；报告周期格式化；审计页中文化 | `python run.py --reset` + 真实 deepseek-flash，Playwright 走：你好 → 明天给小王转两百（黄档确认）→ 给妈妈转2000（红档：模拟短信取码 + 交易密码 135790）→ 这个月花了多少钱 → 异常扣款 → 安全账户诈骗 → 首页/账单/卡片/审计 | 控制台 0 错误；红档回执带审计哈希，余额 ¥26,580.00 → ¥24,580.00；审计页哈希链校验通过（8 条）。发现的后端问题见“需要对方做的”第 7–9 条 |

| 10-30 22:00 | B2 | 跟进 API_V2 5.2–5.4：quick-intent 定稿名、Notification.ref / Home.aa_requests（王磊首页“去支付/拒绝”）、失效码 expired/duplicate、沙箱新字段与嵌套结果表格、延时到账“撤回”按钮；修复 `replaceChildren(null)` 显示“null” | 真实后端 + 真实模型 Playwright：生日计划整体确认 → 快进 11-10 → 节点完成；订阅查询；沙箱分析；卡片冻结；风险测评；AA → 王磊视角 | 控制台 0 错误；截图人工检查 |
| 10-30 22:03 | B3 | 评测集 151 条（任务 87 / 安全 45 / 体验 19）+ 黑盒运行器 + 报告（`bench/`）。首跑（A4–A10 代码，真实 deepseek-flash） | `python bench/run_bench.py --start` | 任务 82/87（94.3%）、体验 19/19、安全 28/45。安全失败 17 条里 16 条是运行器太快触发聊天限流 HTTP 429（不是安全问题），已改为按提示等待重试；另有 3 条是我的期望写错（T7、W5-a、X4-c，已改）。真实问题见“需要对方做的”第 10–12 条。首跑报告存档于 `bench/reports/history/` |
| 10-30 21:56 | B4 | `Dockerfile`、`docker-compose.yml`、`.dockerignore`、`docs/部署说明.md` | 以容器同样的环境变量用 Python 3.11 启动，首页和 `/api/v2/session` 返回 200；3.11/3.12 编译通过 | 通过。**云端没有 Docker 守护进程，镜像未实际构建**（文档已写明） |

## 阻塞与风险

- 无。

## 需要对方做的

1. ~~CSP 加 `manifest-src 'self'`~~ —— 已确认 A 的服务已经带了，谢谢。
2. ~~静态文件类型~~ —— 已确认 `.js/.css/.webmanifest/.json/.png` 类型都正确。备注：旧的 `app.css` / `app.js` 没删，旧测试 `test_web_acceptance` 还要用。
3. **quick-intent 的意图名**：API_V2 只写了 `query_subscriptions`。前端按钮目前用这些名字（集中在 `src/web_assets/app/api.js` 的 `QUICK` 和 `blocks.js`），请在 API_V2 里确认或改名，我跟着改：`freeze_card`、`unfreeze_card`、`report_card_lost`、`cancel_card_lost`、`set_card_limit`（params：`card_id, daily_limit_cents`）、`apply_virtual_card`（params：`purpose`）、`cancel_subscription`（`subscription_id`）、`pay_aa_request` / `decline_aa_request`（`request_id`）。如果后端返回 HTTP 400 / `unknown_intent`，前端会自动退回成一句话发给 `/chat`，所以不认识也不会卡住。
4. **AA 付款入口**：王磊视角收到的 AA 收款（Notification `kind=aa_request`）目前没有可点的引用。建议 Notification 加可选字段 `ref`（AA 请求的 `request_id`），或者在 `/home` 里给王磊一条 `aa_request` Block / insight。没有的话，前端只能让王磊在聊天里说“帮我付 AA”。
5. **失效确认单的错误码**：前端把 `/confirm`、`/cancel`、`/strong-auth/*`、`/pending/revise` 返回的 HTTP 404 / 409 / 410 或 `error.code` 为 `pending_invalid` / `pending_expired` / `expired` / `not_found` 都当作“这张单已失效”。如果实际用别的码，请写进 API_V2。
6. ~~强验证失败时~~（API_V2 5.1 已约定，前端已跟进）建议 `/strong-auth/verify` 失败（还没锁）时返回同一张 `pending`（`request_id` 不变）+ `error.code="auth_failed"`，前端就留在验证面板让用户重试；锁定时 `error.code="locked"` + `guard.locked_until`。

- （不急）`tests/run_context_live_acceptance.py` 第 611 行、`tests/run_six_live_acceptance.py` 第 583 行在给文件算指纹时读取了 `AGENTS.md`、`docs/01-…`、`docs/33-…`、`docs/39-…` 等旧路径；这些文件已移到 `docs/history/`（`AGENTS.md` 改名为 `AGENTS-codex-era.md`）。它们是旧的真实模型运行器，不在单元测试里，冲刺期大概率不会再跑；如果要跑，请把路径改成 `docs/history/…`。`test_*.py` 里出现的旧路径都只是写进证据的字符串，不读文件，不受影响。

7. **（联调发现）事实校验把回复改写成了无关模板**：没有异常识别工具时（A6 未完成，正常），模型回复里有数字，事实校验找不到依据，就把整句换成“我可以帮你办理转账、查账单……”。建议：纠正时用和本轮工具结果相关的模板；本轮没有工具结果时，去掉具体数字而不是整句替换。
8. **（联调发现）同一个月的环比对不上**：“这个月花了多少钱”的 `spending_breakdown.compare.change_pct` 是 +213.5%（上期 ¥5,926.00），而 `/reports/monthly?month=2026-10` 的 KPI 写 “+75.6% 环比”。两个应当用同一口径（我理解是“上月同期”还是“上月全月”要统一），并且 9 月有房租 ¥4,500 + 生活费 ¥1,000，上期 ¥5,926.00 看起来偏低。
9. **（联调发现）`report.period`** 返回的是对象 `{from,to}`，API_V2 的 report 卡片写的是 `period`（没定类型）。前端两种都支持，不用改；只是记一下。

3–9 条：A 已在 API_V2 5.2 全部处理，谢谢。

10. **（评测发现）“帮我交下房租”没给 ¥4,500 选项**（T3-b）：另两种说法（“把这个月房租交了”“房租该交了，转给房东吧”）都给了 `options` 卡片，这一句模型只在文字里问“这次还是转 4,500 吗？什么时候转？”。PLAN T3 要求“建议金额 ¥4,500 供点选”。
11. **（评测发现）聊天里“撤回刚才那笔”直接执行了**（T7）：回复“已撤回给 *小龙 的 ¥9,000.00，资金已全额退回”，没有出黄档确认单，也没有 `receipt` 卡片。PLAN 权限表和 API_V2 5.2 都写撤回是黄档。（撤回是降风险操作，影响不大，但和权限表不一致，评委按表核对会扣分；另外没有回执卡片，前端看不到审计哈希。）
12. **（评测发现）后端偶发 500**：首跑 T6-c 在 `POST /api/v2/demo/reset` 时返回 500，服务日志：`Kernel.now()` → `parse_iso(self._meta("clock_anchor_sim"))` → `TypeError: fromisoformat: argument must be str`，像是重置过程中另一个线程（调度器？）读到了还没写入的时钟锚点。只出现 1 次。
13. （小建议）`.env.example` 还写着旧的 `configure-model.ps1`，可以顺手改成和 `docs/部署说明.md` 一致的说明（文件归属不明确，我没动）。

## 接口变更（只有会话 A 写）

| 时间 | 改动 | 是否兼容 |
|---|---|---|

## 给队长的话（需要人来做的事）

- 暂无。

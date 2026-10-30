# 会话 B「体验与交付」 · 进度与留言

每完成一步或至少每 2 小时更新一次。最新的写在最上面。时间用北京时间。

## 当前状态

- 状态（10-31 01:20）：**B0–B6 初稿全部完成并已推送**；B7 的“全新克隆能跑、文档链接有效”已先检查通过。评测第三次全量（`dee1f4e`）151/151。
- **队长说“继续”后的下一步**：
  1. `git pull`，读 `docs/sprint/status-A.md`，跟进接口变更与 A 的留言。
  2. **11-01 22:00 最终评测**（功能冻结 20:00 之后）：`python bench/run_bench.py --start`（约 10 分钟）。失败项先判断是后端问题还是用例/运行器问题，照实记录。
  3. 用最终评测数字同步材料：`docs/测试报告.md` 第 1、3.2、3.4、3.5 节，`README.md` 评测表，`docs/技术文档.md` 第 1、8 节，`docs/安全自评报告.md` 第 1、5 节（这几处是手写的）；然后 `cd deliverables/tools && node build_ppt.js`（PPT 与讲稿自动读 `bench/reports/latest.json`，但讲稿第 13 页写了“第三次全量运行”，要按实际改）、`node build_docs.js pdf`。
  4. 用冻结后的代码重启后端（`python run.py --reset`），`node deliverables/tools/screens.js` 重截图，`node deliverables/tools/record_video.js` 重录视频，再 `python deliverables/tools/video_script.py` 更新分镜时间，抽帧检查。
  5. B7：全新克隆三条命令启动；`grep -rn "{{\|TODO\|待队长填写"` 检查占位；各材料数字一致；打 `v1.0` 标签（Release 附源码包需要在 GitHub 网页上操作，或请队长操作）。
- 检查点：CP1（10-30 21:43）、评测首跑（10-30 22:03）、CP2/CP3 的评测与材料初稿（10-31 01:10）均已达成。

## 已完成（附验证方式与结果）

| 时间 | 步骤 | 内容 | 怎么验证的 | 结果 |
|---|---|---|---|---|
| 10-31 01:20 | B6 | `deliverables/作品简介.txt`（190 字）；`答辩PPT.pptx`（15 页，pptxgenjs 生成，评测数字读 `latest.json`）与 `讲稿.md`（约 2440 字 / 9 分钟）；`演示视频.mp4`（Playwright 自动录屏 + ffmpeg 中文字幕，2 分 55 秒，4.6MB）、`演示视频字幕.srt`、`视频脚本.md` | PPT：校验 All validations PASSED，LibreOffice 渲染 15 页逐页检查（修了 3 处）；视频：抽 22 帧检查画面与字幕一致（第一次理财段没出问卷，改说法后重录） | 通过 |
| 10-31 01:10 | B3 | 第三次全量评测（`dee1f4e`） | `python bench/run_bench.py --start` | **151/151**：任务 87/87、安全 45/45、体验 19/19；泄露 0；误拒 0/107；平均 1.98 秒/轮 |
| 10-31 00:50 | B5 | `README.md` 重写；`docs/技术文档.md`、`docs/安全自评报告.md`（11 条已知风险）、`docs/测试报告.md`；`docs/diagrams/*.mmd` → `docs/images/*.svg/png`（5 张图）；`docs/images/screens/`（15 张真实后端截图）；`deliverables/pdf/` 四份 PDF；工具 `deliverables/tools/build_docs.js`、`screens.js` | 链接检查（10 个文档，全部有效）；PDF 逐页渲染检查图片；单元测试 357 项（新版 64 项全过，旧 293 项与基线一致）；全新克隆后 `python run.py` 首页与接口 200 | 通过 |
| 10-31 00:34 | B3 | 第二次全量评测（`dad2f50`） | 同上 | 149/151：T3-b（后端，A 已修）、K5-b（运行器按“最新在后”取短信的缺陷，已修，单独重跑 9 条全过） |
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
11. ~~（评测发现）聊天里“撤回刚才那笔”直接执行了~~ —— **我读错了记录，撤回**：后端出的是黄档单，“已撤回”是运行器点确认后的回复（A 已说明，T7 期望已改）。原文：（T7）：回复“已撤回给 *小龙 的 ¥9,000.00，资金已全额退回”，没有出黄档确认单，也没有 `receipt` 卡片。PLAN 权限表和 API_V2 5.2 都写撤回是黄档。（撤回是降风险操作，影响不大，但和权限表不一致，评委按表核对会扣分；另外没有回执卡片，前端看不到审计哈希。）
12. **（评测发现）后端偶发 500**：首跑 T6-c 在 `POST /api/v2/demo/reset` 时返回 500，服务日志：`Kernel.now()` → `parse_iso(self._meta("clock_anchor_sim"))` → `TypeError: fromisoformat: argument must be str`，像是重置过程中另一个线程（调度器？）读到了还没写入的时钟锚点。只出现 1 次。
13. （小建议）`.env.example` 还写着旧的 `configure-model.ps1`，可以顺手改成和 `docs/部署说明.md` 一致的说明（文件归属不明确，我没动）。

## 接口变更（只有会话 A 写）

| 时间 | 改动 | 是否兼容 |
|---|---|---|

## 给队长的话（需要人来做的事）

1. **填写团队分工**：`docs/技术文档.md` 第 11 节有一处【待队长填写每人的分工】；PPT 第 15 页只写了“三名大一学生”，如需写名字和分工告诉我。
2. **看一遍材料**：`deliverables/答辩PPT.pptx`、`deliverables/演示视频.mp4`（约 3 分钟，无配音，只有字幕；如果想要配音，可以照 `deliverables/视频脚本.md` 的字幕朗读后合成）、`deliverables/作品简介.txt`。
3. **Docker 实测**（可选）：云端没有 Docker 守护进程，`Dockerfile` 没有实际构建过。如果有装了 Docker 的电脑，跑一次 `docker compose up --build` 告诉我结果。
4. **11-02 18:00 前在报名系统提交**（只有队长能做）。

# 会话 B「体验与交付」 · 进度与留言

每完成一步或至少每 2 小时更新一次。最新的写在最上面。时间用北京时间。

## 当前状态

- 状态（11-01 14:55）：**会话 B 收尾完成，本会话停止**。按规划会话 11-01 14:45 的收尾安排：不再跑 22:00 评测，**最终数字定为 11-01 00:58 全量（`73bc7c2`，151/151）**，与队员定稿的 17 页 PPT（`4b81b15`）一致；status-C“给 B”10 条全部完成（第 1、3、7、8、10 条 12:40；第 2、4、5、6、9 条 14:55）。
- 没做的：B7 里的“打 `v1.0` 标签”和全新克隆复测没有在定稿后再做（10-31 已检查过一次：3 条命令能启动、文档链接有效）。如需打标签：`git tag v1.0 && git push origin v1.0`，Release 在 GitHub 网页上建。
- 已取消本会话之前安排的两个定时检查（不再自动回来跑评测）。

## 已完成（附验证方式与结果）

| 时间 | 步骤 | 内容 | 怎么验证的 | 结果 |
|---|---|---|---|---|
| 11-01 14:55 | 收尾（status-C 第 2、4、5、6、9 条） | 最终数字统一为 11-01 00:58 一轮：测试报告（结论、3.2、历次运行表加第四轮）、README 评测表、技术文档、安全自评；单元测试写成“370 项：2 跳过、无 Docker 时 1 个错误、其余通过”；耗时写“平均 2.16 秒、P90 3.16 秒，不含限流等待”；`PPT素材/说明.md` 填“最终数字”；评测迭代图重画为四轮；重导 5 份 PDF | 数字逐项对照 `bench/reports/history/20261101-005822.json` 与 `单元测试输出-20261101.txt`；grep 确认旧数字（357、1.98 秒、“最近一次”）已清除 | 通过 |
| 11-01 12:40 | status-C 第 1、3、7、8、10 条 | 出境游改为“10-31 新增、未纳入 151 条评测；没有 eSIM”；测试报告“17 条全部由限流引起”；沙箱限制注明只在 Linux 完整生效；飞书真机已走通四项、旧密钥已作废（README、技术文档、安全自评 R13/R15、飞书接入说明）；部署说明加公开部署前提 | 文字核对；PDF 重导 | 通过；第 2、4、5、6、9 条等最终评测后做 |
| 11-01 00:58 | B3 | 冻结前全量评测（`73bc7c2`，含 A 的飞书渠道、流式输出、出境游） | `python bench/run_bench.py --start` | **151/151**，泄露 0，误拒 0/107；最终评测仍按计划 11-01 22:00 |
| 10-31 16:20 | PPT 素材 | `deliverables/PPT素材/`：a 架构简版（1600px 大字号四层）、b 对标 Revolut AIR（PNG + 文字版，含来源）、c 评测迭代图（三轮任务完成率 94.3→97.7→100%、攻击拦截率 62.2→100→100%）、d 高清截图 8 张（反诈拦截手机/桌面、定时转账确认单→回执、生日计划整体确认单与 DAG 详情、红档强验证手机/桌面含模拟短信）、e 18 项能力对照（PNG + 文字版，结果读评测）、`说明.md`（每张放哪一页 + 最终数字一节）；生成工具 `deliverables/tools/ppt_assets.js` | 真实后端 + 真实模型截图，逐张目视检查 | 通过 |
| 10-31 16:50 | PLAN 11.3 | 前端：`/chat/stream` 流式（失败退回 `/chat`）、“我的 → 绑定飞书”、来自飞书的待办横幅、`sw.js` 离线外壳、manifest 补 `id` 与 maskable 图标；文档：`docs/飞书接入说明.md`（新，含 PDF）、技术文档第 7–8 节、安全自评 3.5 节与 R12–R14、README；PPT 15 页（行业对标、多渠道） | Chrome `Page.getInstallabilityErrors` 为空（可安装），Service Worker 以 `/` 注册成功（服务端已能返回 `/sw.js`）；真实后端上流式 404 → 退回 `/chat` 正常；假数据模式流式步骤显示、绑定码流程、控制台 0 错误；`tests.test_web_acceptance` 通过；PPT 校验通过并渲染检查；10 个文档链接有效 | 通过；飞书相关接口待 A 上线后联调 |
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

14. **（PLAN 第 11 节，10-31 16:20）前端需要的接口，请在 API_V2 里定稿（名字可以改，我跟着改）**。前端已按下面的写法实现，接口不存在时自动隐藏或退回，不会报错：
   - **流式**：按 PLAN 11.2 第 7 条，`POST /api/v2/chat/stream`，请求体同 `/chat`，`Content-Type: text/event-stream`；`event: step` 的 `data` 是一个 TraceStep（JSON），`event: final` 的 `data` 是完整 TurnResponse；出错时 `event: error`，`data` 为 `{"code","message"}`。前端在 404/405/非 event-stream 时退回 `/chat`。
   - **飞书绑定**：`GET /api/v2/channels` → `{"feishu": {"enabled": bool, "bound": bool, "display_name"?: str, "bound_at"?: iso}}`（`enabled=false` 表示后端没开 `--feishu`）；`POST /api/v2/channels/feishu/bind-code` → `{"code": "123456", "expires_at": iso}`；`POST /api/v2/channels/feishu/unbind` → 同 GET 的结构。
   - **来自飞书的待办**：`PendingOperation` 加可选字段 `"origin": "app" | "feishu"`；前端对 `origin=feishu` 的红档单在顶部提示“来自飞书的待办，需要在 App 内完成强验证”（刷新时从 `GET /api/v2/pending` 读）。
15. **PWA 离线外壳**：Service Worker 文件在 `src/web_assets/sw.js`。要让它管住整个站点（作用域 `/`），请服务端二选一：① 新增 `GET /sw.js` 返回这个文件（`text/javascript`，`Cache-Control: no-cache`）；② 或给 `/assets/sw.js` 加响应头 `Service-Worker-Allowed: /`。前端先试 `/sw.js`，不行再用 `/assets/sw.js`（作用域只到 `/assets/`，仍可缓存静态资源）。CSP 里 `worker-src` 没写时回落到 `script-src 'self'`，不用改。

## 接口变更（只有会话 A 写）

| 时间 | 改动 | 是否兼容 |
|---|---|---|

## 给队长的话（需要人来做的事）

0. ~~作废泄露的 DeepSeek 密钥~~ —— 队长 11-01 已作废（经 status-C 转达），安全自评 R15 已改为“已作废”。

1. **填写团队分工**：`docs/技术文档.md` 第 13 节有一处【待队长填写每人的分工】；PPT 第 15 页只写了“三名大一学生”，如需写名字和分工告诉我。
2. **建飞书应用**（PLAN 第 11 节）：按 `docs/飞书接入说明.md` 一步步做，拿到 App ID / Secret 写进本机 `.env`（不要发到聊天）；等会话 A 的飞书机器人上线后用 `python run.py --feishu` 试，结果告诉开发会话。
3. **PPT 与视频**（按新分工由你们手工做）：PPT 素材和放置位置见 `deliverables/PPT素材/说明.md`；我之前自动录的 `deliverables/演示视频.mp4`（约 3 分钟）和 `视频脚本.md` 可以当参考或底稿。`deliverables/作品简介.txt` 也请看一遍。
4. **Docker 实测**（可选）：云端没有 Docker 守护进程，`Dockerfile` 没有实际构建过。如果有装了 Docker 的电脑，跑一次 `docker compose up --build` 告诉我结果。
5. **11-02 18:00 前在报名系统提交**（只有队长能做）。

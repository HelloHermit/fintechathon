# 会话 B「体验与交付」 · 进度与留言

每完成一步或至少每 2 小时更新一次。最新的写在最上面。时间用北京时间。

## 当前状态

- 正在做：B2 卡片与面板细化（B1 已把全部 Block 类型、待确认面板、强验证面板、计划 DAG 一并做了初版）；同时开始 B3 评测集
- 下一步：A 的 `/api/v2` 上线后立刻切真实后端联调；B3 运行器
- 预计到达的检查点：CP1（10-31 12:00，前端连真实后端）

## 已完成（附验证方式与结果）

| 时间 | 步骤 | 内容 | 怎么验证的 | 结果 |
|---|---|---|---|---|
| 10-30 21:40 | B0 | 仓库清理：删除 `_codex_tmp/`、`design/references/`、`design/ui_reference_pack.zip`、根目录 10 个过程文件；`docs/00`–`42` 与 `model-configuration.md` 移到 `docs/history/`（加 `README.md` 索引）；`AGENTS.md` → `docs/history/AGENTS-codex-era.md`；旧根目录 README → `docs/history/README-第一阶段.md`（链接已改成新位置），根目录换成临时 README。`dist/` 在 main 上本来就不存在。`spec/`、`evidence/`、`design/browser-concept.png`（自绘概念图）保留 | 清理后跑旧测试 `python -m unittest discover -s tests -p 'test_*.py'` | 293 项，与 A0 基线一致：只有 `test_docker_isolation_independent` 的 setUpClass 报错（需要 Docker 运行时，属预期），跳过 2 项，128 秒 |

| 10-30 22:50 | B1 | 新前端（`src/web_assets/index.html` + `app/*.js` + `app/styles.css`，纯 ES 模块、无第三方库、无内联脚本和样式，符合同源 CSP）：底部五个标签（首页 / 小安 / 账单 / 卡片 / 我的）；桌面端居中手机外框，右侧“演示控制”“安全透视”“模拟手机·短信”三块面板；手机宽度（≤900px）全屏显示，三块面板放进“我的”。`?mock=1` 用浏览器内假后端（`app/mock.js` + `mock/*.json`，按 API_V2 结构）。同时完成了 B2 的大部分：API_V2 第 3 节全部 24 种 Block 渲染、黄档确认面板（风险勾选、冷静期倒计时、到账方式切换、有效期倒计时）、红档强验证面板（数字键盘 + 获取动态码 + 60 秒重发）、计划 DAG（SVG 依赖图 + 节点明细 + 暂停/继续/回退/转人工）、快捷回复、选项追问、回执、审计哈希链页、决策链回放、演示控制、PWA 清单与图标、语音输入按钮（浏览器支持时） | 本地起静态服务（与真实服务同样的 CSP 头），Playwright 跑完整假数据流程：首页 → 定时转账黄档确认 → 回执 → 红档转账（取短信动态码 + 交易密码）→ 异常识别 → 账单 → 生日计划整体确认 → 快进到 11-10 → 账单/卡片/我的；桌面 1360×900 与手机 390×844 各截图检查；旧测试 `tests.test_web_acceptance` | 浏览器控制台 0 错误 0 CSP 违规；截图人工检查通过（修了 6 处显示问题：确认按钮状态、DAG 文字截断、短信横幅残留、重复说明、焦点框、占位文字换行）；`tests.test_web_acceptance` 27 项通过 |

## 阻塞与风险

- 无。

## 需要对方做的

1. **CSP 加 `manifest-src 'self'`**：API_V2 写的 CSP 是 `default-src 'none'` 起步，不加这一项浏览器会拦掉 `/assets/manifest.webmanifest`（PWA 安装用）。图标用到 `img-src 'self'`（已有）。
2. **静态文件类型**：新前端是 ES 模块，`/assets/app/*.js` 必须返回 `text/javascript`（否则浏览器拒绝执行）；`.webmanifest` → `application/manifest+json`；`.json`（`/assets/mock/*.json`）→ `application/json`。目录结构：`src/web_assets/index.html`、`app/`、`icons/`、`mock/`、`manifest.webmanifest`。旧的 `app.css` / `app.js` 我没删，旧测试 `test_web_acceptance` 还要用；旧 v1 页面 `/` 现在返回的是新首页（只依赖 `/api/v2`）。
3. **quick-intent 的意图名**：API_V2 只写了 `query_subscriptions`。前端按钮目前用这些名字（集中在 `src/web_assets/app/api.js` 的 `QUICK` 和 `blocks.js`），请在 API_V2 里确认或改名，我跟着改：`freeze_card`、`unfreeze_card`、`report_card_lost`、`cancel_card_lost`、`set_card_limit`（params：`card_id, daily_limit_cents`）、`apply_virtual_card`（params：`purpose`）、`cancel_subscription`（`subscription_id`）、`pay_aa_request` / `decline_aa_request`（`request_id`）。如果后端返回 HTTP 400 / `unknown_intent`，前端会自动退回成一句话发给 `/chat`，所以不认识也不会卡住。
4. **AA 付款入口**：王磊视角收到的 AA 收款（Notification `kind=aa_request`）目前没有可点的引用。建议 Notification 加可选字段 `ref`（AA 请求的 `request_id`），或者在 `/home` 里给王磊一条 `aa_request` Block / insight。没有的话，前端只能让王磊在聊天里说“帮我付 AA”。
5. **失效确认单的错误码**：前端把 `/confirm`、`/cancel`、`/strong-auth/*`、`/pending/revise` 返回的 HTTP 404 / 409 / 410 或 `error.code` 为 `pending_invalid` / `pending_expired` / `expired` / `not_found` 都当作“这张单已失效”。如果实际用别的码，请写进 API_V2。
6. **强验证失败时**：建议 `/strong-auth/verify` 失败（还没锁）时返回同一张 `pending`（`request_id` 不变）+ `error.code="auth_failed"`，前端就留在验证面板让用户重试；锁定时 `error.code="locked"` + `guard.locked_until`。

- （不急）`tests/run_context_live_acceptance.py` 第 611 行、`tests/run_six_live_acceptance.py` 第 583 行在给文件算指纹时读取了 `AGENTS.md`、`docs/01-…`、`docs/33-…`、`docs/39-…` 等旧路径；这些文件已移到 `docs/history/`（`AGENTS.md` 改名为 `AGENTS-codex-era.md`）。它们是旧的真实模型运行器，不在单元测试里，冲刺期大概率不会再跑；如果要跑，请把路径改成 `docs/history/…`。`test_*.py` 里出现的旧路径都只是写进证据的字符串，不读文件，不受影响。

## 接口变更（只有会话 A 写）

| 时间 | 改动 | 是否兼容 |
|---|---|---|

## 给队长的话（需要人来做的事）

- 暂无。

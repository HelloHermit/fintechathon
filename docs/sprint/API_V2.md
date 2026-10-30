# 接口契约 v2（前端 ↔ 后端）

状态：冻结初版 2026-10-30。之后由会话 A 维护：任何改动先改本文件，并在 `status-A.md` 的“接口变更”里写一行（时间、改了什么、是否向后兼容）。会话 B 只按本文件开发；需要新字段时写进 `status-B.md` 的“需要 A 做的”。

旧接口 `/api/*`（v1，见 `src/WEB_API.md`）继续保留给旧测试，新前端只用 `/api/v2/*`。

## 1. 通用约定

- JSON over HTTP，UTF-8。金额一律用**整数分**（`*_cents`），时间一律 ISO 8601 带 `+08:00`。
- 所有 POST：`Content-Type: application/json`，请求头 `X-CSRF-Token` = `/api/v2/session` 返回值。同源检查沿用 v1（Host/Origin），部署时允许的主机名由环境变量 `FINTECH_ALLOWED_HOSTS` 配置。
- 错误：HTTP 4xx/5xx + `{"error":{"code":"…","message":"给用户看的中文"}}`。业务上的“拒绝”不是 HTTP 错误，而是正常的 TurnResponse（见第 3 节）。
- 服务端必须是多线程的（`ThreadingHTTPServer`），同一用户的业务调用加锁串行；聊天请求在等模型时，`/api/v2/sim-phone`、`/api/v2/home` 等仍要能响应。
- 静态文件：`GET /` 返回 `src/web_assets/index.html`；`GET /assets/<path>` 返回 `src/web_assets/` 下的文件。白名单在启动时由目录内容生成，禁止 `..`、绝对路径、符号链接逃逸。按扩展名给 Content-Type（html/css/js/json/svg/png/webmanifest/woff2）。CSP 仍只允许同源，不加载 CDN（第三方库请下载后放进 `src/web_assets/vendor/`）。

## 2. 端点一览

| 方法 | 路径 | 请求体 | 返回 | 说明 |
|---|---|---|---|---|
| GET | /api/v2/session | – | Session | 当前用户、CSRF、模型状态、演示信息 |
| GET | /api/v2/home | – | Home | 首页：账户、主动提醒、快捷入口、通知 |
| POST | /api/v2/chat | `{"text": str}`（1–500 字） | TurnResponse | 和智能体说一句话 |
| POST | /api/v2/action | `{"type": "option_select"\|"insight_accept"\|"form_submit"\|"block_action", "ref": str, "value": any}` | TurnResponse | 点选项、接受提醒建议、提交表单（如风险测评）、点卡片上的按钮 |
| POST | /api/v2/quick-intent | `{"intent": str, "params": obj}` | TurnResponse | 页面按钮直接发起业务（如卡片页“冻结”），不经过模型，照样走代码判档和确认 |
| POST | /api/v2/confirm | `{"request_id", "confirmation_code", "risk_acknowledged"?: bool}` | TurnResponse | 黄档确认（含计划整体确认） |
| POST | /api/v2/pending/revise | `{"request_id", "changes": {"arrival": "instant"\|"delayed_2h"\|"delayed_24h"}}` | TurnResponse | 只允许改到账方式；旧单作废、返回新单 |
| POST | /api/v2/strong-auth/send-otp | `{"request_id"}` | OtpSent | 红档：向绑定手机（模拟）发送动态码 |
| POST | /api/v2/strong-auth/verify | `{"request_id", "pin", "otp"}` | TurnResponse | 红档：交易密码 + 动态码 |
| POST | /api/v2/cancel | `{"request_id"}` | TurnResponse | 取消待确认单 |
| POST | /api/v2/plan/control | `{"plan_id", "action": "pause"\|"resume"\|"rollback"\|"takeover"}` | TurnResponse | 计划中断、继续、回退、转人工 |
| GET | /api/v2/plans | – | `{"plans":[PlanSummary]}` | |
| GET | /api/v2/plans/{plan_id} | – | Plan | |
| GET | /api/v2/sim-phone | – | `{"messages":[SmsMessage]}` | 模拟手机：短信收件箱（动态码只出现在这里） |
| GET | /api/v2/notifications | – | `{"items":[Notification]}` | 定时任务结果、提醒、AA 收款请求等 |
| GET | /api/v2/accounts | – | `{"accounts":[Account]}` | |
| GET | /api/v2/transactions | query: `from,to,category,q,limit(≤200),cursor` | `{"items":[Txn],"next_cursor"}` | |
| GET | /api/v2/reports/monthly | query: `month=YYYY-MM` | Report | 月度账单报告 |
| GET | /api/v2/reports/annual | query: `year=YYYY` 或 `last12=1` | Report | 年度报告 |
| GET | /api/v2/cards | – | `{"cards":[Card]}` | |
| GET | /api/v2/products | – | `{"products":[Product],"disclaimer"}` | |
| GET | /api/v2/holdings | – | `{"holdings":[Holding],"risk_profile":RiskProfile\|null}` | |
| GET | /api/v2/scheduled | – | `{"items":[Scheduled]}` | 定时任务、延时到账中的转账 |
| GET | /api/v2/audit | query: `limit(≤200)` | Audit | 本人审计 + 哈希链校验结果 |
| GET | /api/v2/turns/{turn_id} | – | `{"turn_id","trace":[TraceStep]}` | 决策链回放 |
| POST | /api/v2/demo/advance-clock | `{"minutes": int}` 或 `{"to": iso}` | `{"now","executed":[Notification]}` | 仅演示模式 |
| POST | /api/v2/demo/reset | `{}` | Session | 仅演示模式：按 rich 种子重建当前演示库 |
| POST | /api/v2/demo/switch-user | `{"user_id":"alice"\|"bob"}` | Session | 仅演示模式：切换演示身份（AA 演示用） |

说明：订阅列表没有直接的 GET 接口——按赛题权限表“订阅查询”是黄档，前端要经 `/api/v2/quick-intent`（`intent: "query_subscriptions"`）或聊天发起，确认后才返回列表。

## 3. 主要对象

### Session
```json
{
  "user": {"user_id": "alice", "display_name": "陈雨桐", "masked_phone": "138****0001"},
  "csrf_token": "…",
  "model": {"configured": true, "name": "deepseek-flash", "mode": "live" | "replay" | "unavailable"},
  "demo": {"enabled": true, "now": "2026-10-30T09:00:00+08:00",
           "users": [{"user_id": "alice", "display_name": "陈雨桐"}, {"user_id": "bob", "display_name": "王磊"}]},
  "version": "2.0"
}
```

### Home
```json
{
  "now": "…",
  "total_assets_cents": 9669800,
  "accounts": [Account],
  "insights": [Insight],
  "quick_actions": [{"label": "本月账单", "prompt": "这个月花了多少钱？"}],
  "notifications": [Notification]
}
```

### TurnResponse（聊天、确认、强验证、取消、计划控制都返回它）
```json
{
  "turn_id": "t_…",
  "assistant": {
    "text": "自然语言回复（已通过事实校验）",
    "blocks": [Block]
  },
  "pending": PendingOperation | null,
  "plan": Plan | null,
  "suggestions": ["查看本月账单", "冻结这张卡"],
  "trace": [TraceStep],
  "guard": {"input": "pass" | "warned" | "blocked", "fact_check": "pass" | "corrected", "locked_until": null | "…"},
  "error": null | {"code": "model_unavailable" | "model_timeout" | "rate_limited" | "locked" | "invalid_request" | "internal", "message": "…"}
}
```
- `assistant.text` 简短（建议 ≤120 字），细节放在 `blocks` 里由前端渲染。所有卡片内容由代码根据账本生成，不由模型编写。
- `suggestions` 是快捷回复，点击后作为普通文字发 `/api/v2/chat`。

### PendingOperation（待确认单）
```json
{
  "request_id": "…",
  "kind": "confirm" | "strong_auth",
  "tier": "yellow" | "red",
  "intent": "transfer",
  "title": "转账给 王磊（小王）",
  "lines": [
    {"label": "收款人", "value": "王磊 · 尾号1234"},
    {"label": "金额", "value": "¥200.00", "emphasis": true},
    {"label": "付款账户", "value": "储蓄卡 尾号6621（可用 ¥26,380.00）"},
    {"label": "执行时间", "value": "2026-10-31 09:00（明天）"},
    {"label": "备注", "value": "还饭钱"},
    {"label": "今日累计转出", "value": "¥200.00 / 小额额度 ¥1,000.00"}
  ],
  "impact": "确认后将于明天 09:00 执行，执行前会再次检查余额和限额。",
  "risk": null | {
    "level": "medium" | "high",
    "score": 72,
    "reasons": ["首次向该收款人转账", "对话中出现“安全账户”等诈骗常见话术"],
    "advice": "公检法和银行客服不会要求你转账到“安全账户”。",
    "require_ack": true,
    "not_before": "…",
    "arrival_options": ["instant", "delayed_2h", "delayed_24h"]
  },
  "confirmation_code": "482913",
  "factors": ["pin", "sms_otp"],
  "expires_at": "…",
  "plan_id": null | "…"
}
```
- 黄档：`kind=confirm`，带 `confirmation_code`。前端点“确认”时原样回传，**不显示给模型，也不写入日志**。
- 红档：`kind=strong_auth`，**没有** `confirmation_code`，有 `factors`。前端弹出强验证面板：先调 `send-otp`，用户在“模拟手机”里看到短信，再输入交易密码和动态码，调 `verify`。
- `risk.require_ack=true` 时，前端必须让用户勾选“我已了解风险”，并把 `risk_acknowledged: true` 传给 `/confirm`；红档时随 `verify` 一并校验（后端在 verify 里要求 ack，字段名同上，可放在请求体）。
- `risk.not_before` 是冷静期结束时间，早于它提交会被拒绝；前端显示倒计时。
- 有效期 5 分钟。任何参数变化都会作废旧单。

### OtpSent
```json
{"status": "sent", "channel": "sim_sms", "masked_phone": "138****0001", "expires_at": "…", "resend_after_seconds": 60}
```

### SmsMessage（模拟手机收件箱）
```json
{"id": "…", "from": "模拟银行", "text": "【模拟银行】验证码 482913，用于向 王磊 转账 2,000.00 元，5 分钟内有效。请勿告诉任何人。", "received_at": "…"}
```
短信正文必须写明操作对象和金额（“所见即所签”，防止被骗子诱导转发验证码）。

### TraceStep（决策链，给“安全透视”面板和审计回放）
```json
{"kind": "guard" | "llm" | "tool" | "resolver" | "provenance" | "tier" | "risk" | "auth" | "fact_check" | "plan" | "audit",
 "label": "代码判档：黄档（今日累计 ¥200.00 ≤ ¥1,000.00）",
 "status": "pass" | "warned" | "blocked" | "pending" | "success" | "failed",
 "detail": {},
 "ms": 12}
```
`detail` 不得包含验证码、交易密码、动态码、API 密钥或完整手机号。

### Plan / PlanSummary
```json
{
  "plan_id": "…", "title": "周屿生日筹备", "status": "draft" | "awaiting_confirmation" | "running" | "paused" | "completed" | "failed" | "rolled_back" | "handed_over",
  "created_at": "…",
  "nodes": [
    {"id": "n1", "title": "锁定生日预算 ¥1,000.00", "intent": "reserve_budget", "tier": "yellow",
     "status": "pending" | "waiting" | "running" | "scheduled" | "success" | "failed" | "skipped" | "rolled_back",
     "depends_on": [], "run_at": null, "result_summary": null, "compensation": "release_budget" | null}
  ],
  "actions": ["pause", "resume", "rollback", "takeover"]
}
```
PlanSummary = 只含 `plan_id,title,status,created_at,node_count,done_count`。

### Block（富卡片，`type` + `data`）

| type | data 主要字段 |
|---|---|
| `note` | `text, tone: info\|warning\|success\|danger` |
| `account_list` | `accounts: [Account]` |
| `transaction_list` | `items: [Txn], total_count, title` |
| `spending_breakdown` | `period:{from,to}, total_cents, categories:[{name, amount_cents, share, count}], compare:{prev_total_cents, change_pct}` |
| `trend_chart` | `title, metric: expense\|income\|net, series:[{label, value_cents}]` |
| `anomaly_list` | `items:[{finding_id, transaction_ids, time, merchant, amount_cents, rule, severity: high\|medium\|low, explanation, actions:[{label, intent, params}]}]` |
| `report` | `kind: monthly\|annual, period, kpis:[{label, value, delta}], sections:[{title, bullets:[]}], charts:[Block]` |
| `subscription_list` | `items:[{subscription_id, name, amount_cents, cycle, next_charge_date, status, source: registered\|detected, flags:[price_up\|idle\|renew_soon]}], monthly_total_cents` |
| `product_list` | `items:[Product + suitable: bool\|null]`, `disclaimer` |
| `product_compare` | `products:[Product], rows:[{label, values:[str]}]`, `disclaimer` |
| `risk_questionnaire` | `questionnaire_id, questions:[{id, text, options:[{value, label}]}]`（前端提交走 `/api/v2/action`，`type=form_submit`，`ref=questionnaire_id`，`value={Q1:1..5,…}`） |
| `risk_profile` | `level: C1..C5, label, score, valid_until, max_product_risk: R1..R5` |
| `holding_list` | `items:[Holding]` |
| `card_list` | `items:[Card]` |
| `scheduled_list` | `items:[Scheduled]` |
| `budget_list` | `items:[{budget_id, name, amount_cents, remaining_cents, spent_cents, released_cents, until, status}]` |
| `order_list` | `items:[{order_id, service_name, amount_cents, deliver_date, status}]` |
| `receipt` | `title, status: success\|scheduled\|failed\|revoked, lines:[{label, value}], request_id, audit_hash` |
| `plan` | `Plan` |
| `options` | `prompt, ref, items:[{label, value, hint}]`（点选后 `/api/v2/action`，`type=option_select`） |
| `insight` | `insight_id, kind: birthday\|renewal\|anomaly\|rent\|idle_cash\|price_up, title, body, cta_label` |
| `code_analysis` | `question, code, engine: docker\|subprocess, limits:{timeout_s, memory_mb, network: false}, duration_ms, status: ok\|rejected\|error, result:{type: value\|table\|series, …}` |
| `handover` | `ticket_id, summary, status` |
| `aa_request` | `request_id, from_name, amount_cents, memo, status: open\|paid\|declined` |

卡片上的 `actions`（例如异常交易里的“冻结这张卡”）由前端调用 `/api/v2/action`：`{"type":"block_action","ref":"<finding_id>","value":{"intent":…,"params":…}}`，后端照常走代码判档与确认。

### 其他对象

- **Account**：`account_id, name, masked_no, balance_cents, reserved_cents, available_cents`
- **Txn**：`id, time, merchant, category, amount_cents（支出为负）, status, card_id?, memo?（外部文本，前端用 textContent 显示）, flags:[]`
- **Card**：`card_id, name, kind: debit|virtual, masked_no, account_id, status: active|frozen|lost, daily_limit_cents, today_spent_cents`
- **Product**：`product_id, name, type, risk_level: R1..R5, term_days, liquidity, yield_text, min_amount_cents, description`
- **Holding**：`product_id, name, amount_cents, profit_cents, purchased_at, redeemable_cents`
- **RiskProfile**：同 `risk_profile` 卡片
- **Scheduled**：`schedule_id, kind: transfer|order|settlement|reminder, title, amount_cents, run_at, repeat: none|monthly|weekly, status: scheduled|executed|failed|cancelled|needs_reauth`
- **Insight**：同 `insight` 卡片
- **Notification**：`id, time, kind: scheduled_executed|scheduled_failed|reminder|aa_request|risk_alert|settlement, title, body, read: bool`
- **Audit**：`{"events":[{id, time, turn_id?, request_id?, intent, tier, event, result, reason, actor: user|agent|scheduler, hash}], "chain":{"verified": bool, "length": int, "head_hash": str}}`
- **Report**：同 `report` 卡片

## 4. 前端开发用的假数据

会话 B 在 `src/web_assets/mock/` 放各接口的示例 JSON（按本文件结构），页面带 `?mock=1` 时用假数据。会话 A 不读不改这个目录。真实后端可用后，B 去掉对假数据的依赖，但保留它作为离线截图用途。

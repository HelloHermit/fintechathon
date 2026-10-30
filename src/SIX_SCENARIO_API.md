# 六场景公开契约 v4

冻结：2026-10-25。依据队长提供的 `task2/未命名 15.md`。这是实现与独立验收依据，不是通过报告。原 PUBLIC_API、CONTEXT_API、RECOVERY_API、WEB_API 仍有效；下述项目规则覆盖旧文中“仅六工具/仅三方向”的范围描述，不宣称为赛事新增原文。全部数据及服务均为模拟，红档继续拒绝。

## 工具、字段与权限

仍通过 `BankService.propose({"intent":名称,"params":对象})`，黄档返回 pending、confirmation_code、operation、expires_at，通过同实例 `confirm(request_id,confirmation_code)` 明确办理。查询结果在 data。未知字段、bool 充整数、浮点金额、空目标及身份/权限参数拒绝。字符串最长80字符，不接受秘密。原六工具参数不变。

| 新工具 | params（未标可选即必需） | 档位 / data 主字段 |
|---|---|---|
| query_investments | {} | 绿 / products |
| compare_investments | product_ids：2至4个不重复产品ID组成的list | 绿 / products，保持请求顺序 |
| match_investments | risk_level：low/medium/high，horizon_days：1至3650整数，liquidity：immediate/flexible/locked | 绿 / products、criteria |
| query_cards | 可选 card_id | 绿 / cards |
| apply_virtual_card | account_id | 黄 / card（新记录） |
| set_card_limit | card_id、daily_limit_cents：1至100000整数分 | 黄 / card（更新后记录） |
| query_services | {} | 绿 / services |
| query_budgets | 可选 budget_id | 绿 / budgets |
| query_orders | 可选 budget_id 或 order_id，不能同时给 | 绿 / orders |
| reserve_budget | budget_id、account_id、event_date、amount_cents | 黄；金额超过100000分为红 / budget |
| release_budget | budget_id | 黄 / budget |
| place_order | budget_id、service_id、event_date；可选 card_id | 黄或红 / order、budget、daily_outgoing_cents |
| purchase_investment | product_id、account_id、amount_cents | 红，永不执行 |
| redeem_investment | product_id、account_id、amount_cents | 红，永不执行；不声称持有或赎回 |
| report_card_lost | card_id | 红，永不执行 |
| restore_card | card_id | 红，永不执行 |

金额为正整数分，通用上限10^12。budget_id 须用户明确给出，格式 `[A-Za-z][A-Za-z0-9_-]{0,31}`，同用户不可复用，即使已释放。event_date 为真实 YYYY-MM-DD，范围为上海当日至366天后；下单日期必须与预算日期一致。只模拟立即支付，日期是活动属性，不代表届时自动执行。不支持后台定时/自动联系商户。卡号为非支付标识 `sim-card-` 加请求hex的逐位编码（a-f保留，数字0-9对应g-p），不生成PAN/CVV/真实信用额度。

## 可核对的固定数据

| product_id | name | risk_level | min_days | liquidity | illustrative_annual_rate_bps |
|---|---|---|---:|---|---:|
| p-cash | 模拟活期A | low | 1 | immediate | 180 |
| p-flex | 模拟灵活B | medium | 7 | flexible | 220 |
| p-steady | 模拟稳健C | medium | 90 | locked | 260 |
| p-growth | 模拟成长D | high | 365 | locked | 420 |

利率仅为假设展示数据，不代表真实产品、保证收益或预测。匹配：产品风险不高于用户选择、min_days不超过horizon_days、流动性约束不差于用户容忍级别（immediate=0、flexible=1、locked=2）。按风险、min_days、product_id升序输出，允许无匹配，不偷偷放宽条件。

服务：`flower-basic / 模拟鲜花 / 12900分`；`cake-basic / 模拟蛋糕 / 9900分`。一单一件，无模型定价或隐藏运费。初始卡 `card-alice-main` 归 alice/alice-main、`card-bob-main` 归 bob/bob-main；均 active、kind=debit、daily_limit_cents=100000。申请产生 kind=virtual、active 的新模拟卡，不改变余额或授信。

## 账本与绑定

新增公开表 investment_products、service_catalog、cards、budgets、orders。cards 至少有 card_id,user_id,account_id,kind,status,daily_limit_cents,created_at；budgets 至少有 user_id,budget_id,account_id,event_date,amount_cents,remaining_cents,spent_cents,released_cents,status,created_at；orders 至少有 order_id,user_id,budget_id,account_id,service_id,card_id（可空）,event_date,amount_cents,status,executed_at,shanghai_date。产品/服务字段如上。orders.order_id 为 request_id，状态 paid。预算按(user_id,budget_id)唯一；所有个人查询仅本人，显式他人ID拒绝，不泄露数据。

预算恒等式 amount_cents=remaining_cents+spent_cents+released_cents，各项非负；active/exhausted/released 分别表示仍有保留、全部用完、剩余已释放。保留不改变账面余额、不记消费；**可用余额=账面余额−本人该账户全部预算 remaining_cents**。转账执行须检查可用余额。释放仅将剩余转入released，不退款、不恢复spent，剩余为0拒绝重复释放。query_balance 的 accounts 原有三字段保留；用户有预算记录时，另加 available_balances 列表（account_id,balance_cents,reserved_cents,available_cents），无预算时保持旧响应。

下单从预算来源账户扣固定价，同事务减少预算remaining、增加spent，新增paid订单及kind=expense的成功交易；其费用进入实际账单。先核对预算足额、账面余额、日期及归属。选卡时卡必须active且属于同用户和同预算来源账户；本卡上海当天已支付订单+本次<=daily_limit_cents，否则拒绝。未选卡按预算账户直接支付，不擅自选卡。卡限额不提高总日限额，修改卡限额不产生信用或资金。

**统一资金日累计**=同用户上海自然日全部成功转账+全部paid订单金额，跨账户；累计+本次<=100000分黄档，超过为红且拒绝。预算保留/释放不计成功转出。transfer 与 place_order 共用持久验证桶 `verification_state.intent='transfer'`，防换工具绕过三错十分钟锁；审计仍记录实际工具。其他黄档按自身工具计数。确认成功才按既有规则复位。

确认绑定完整参数及该操作关键事实：归属、来源账户、服务价格/名称、预算日期与剩余、选卡归属/状态/限额、金额及日累计；改变使旧确认失效，不默选新目标。仍须5分钟期限、提交前复查、请求防重放；业务、请求、计划节点、成功审计同事务，审计失败整体回滚并停办。订单已付及转账成功不因取消任务而退款；预算释放须另建黄档确认，取消任务不会自动释放预算。

## 自然语言、计划、恢复和受限工具

原转账兼容说明：黄档确认在五分钟内跨上海午夜，按执行时新自然日重新累计、定档；不只因日切换/累计自然归零而拒绝。目标、来源及预算保留等其余绑定仍须一致，余额与可用余额及当前累计执行前复检，新日超阈值仍拒绝。这保留task3原跨日语义；新增订单继续完整事实绑定。

新动作由用户本轮文字或未终结同任务的明确补充支持；产品/服务/卡/预算/日期/金额/期限/风险/流动性参数均检查人类来源，缺项或模型猜项先澄清，不执行。支持精确固定名称及ID；主账户只可在用户明确说“主账户”时映射，不能把新资金动作自动补成主账户。日期需明确ISO，不从“明天/生日”猜日期。产品查询目录是固定业务数据，不是占位回答。

计划最多8静态节点，所有节点参数在接纳时完整验证。生活任务分两段：先确认保留预算；再用明确存在的budget_id、服务和日期创建“查询服务→下单→查询预算/订单/余额/账单”依赖计划。申请新卡后修改该新卡亦需用户明确其ID另建任务。不支持同计划引用尚不存在的预算/卡、结果变量或$ref，不把此边界说成动态规划已完成。

新增工具同样保存计划、终结请求、节点结果及审计。重启不自动推进，旧码无效；prepare_recovery重新展示预算/价格/日期/可用余额/卡/累计等当前事实，confirm_recovery只同意本轮恢复，resume后黄档仍新码确认。成功订单、预算及卡修改列入committed_effects，不自动补偿。

Docker模式新工具必须通过compute_tool且核对固定纯计算结果；失败不执行且不回退。worker只接最小授权快照，不接DB、密钥、确认码或任意SQL；宿主固定SQL负责复检/事务。运行时复制受信纯计算模块并纳入文件SHA256，另建新runtime保留旧runtime。具体records结构为实现内部固定快照，业务公开行为不由它改变。

## 手算基线

字段澄清（不改行为期望）：`service_catalog(service_id,name,price_cents)`；`investment_products(product_id,name,risk_level,min_days,liquidity,illustrative_annual_rate_bps)`。黄档`operation.params`为规范化后的完整候选字段，与本工具参数白名单一致，不能遗漏选卡或日期等影响；其余关键事实用于展示和绑定复检。

新库alice-main=1000000，savings=500000，bob-main=100000；本月实际账单5970分，未来订阅预计5970分。保留生日预算20000分后：账面1000000、reserved20000、available980000。鲜花12900支付后：账面987100、spent12900、remaining7100、available980000、本月实际18870、资金日累计12900。蛋糕9900因剩余不足拒绝，全部业务不变。再明确释放：released7100、remaining0、账面987100、available987100；已付订单及18870实际账单保持。

独立作者先冻结矩阵和测试，再由实现者运行新库。离线、真实模型、Docker、浏览器和人工记录分开，首轮失败保留。真人/真实银行/正式赛事认可不由自动通过推导。

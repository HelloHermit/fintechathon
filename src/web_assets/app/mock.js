// 假后端（只在 ?mock=1 时加载）：按 API_V2 的结构返回写死的示例，用于前端开发和离线截图。
// 不代表真实后端行为；聊天只按关键词匹配几条演示路径。
const files = ["session", "home", "accounts", "transactions", "report-monthly", "report-annual", "cards", "products", "holdings", "scheduled", "audit", "notifications", "plans", "spending_breakdown"];
let D = null;
const S = { now: null, pendings: new Map(), sms: [], turns: new Map(), fails: 0, lockedUntil: null, plans: new Map(), seq: 0, user: "alice", notifications: [], subs: null };

async function load() {
  if (D) return;
  D = {};
  await Promise.all(files.map(async (f) => { D[f] = await (await fetch(`/assets/mock/${f}.json`)).json(); }));
  S.now = Date.parse(D.session.demo.now);
  S.realAt = Date.now();
  S.notifications = [...D.notifications.items];
  S.subs = [
    { subscription_id: "sub-video", name: "视频会员", amount_cents: 3000, cycle: "monthly", next_charge_date: "2026-11-15", status: "active", source: "registered", flags: ["price_up"] },
    { subscription_id: "sub-music", name: "音乐会员", amount_cents: 1500, cycle: "monthly", next_charge_date: "2026-11-03", status: "active", source: "registered", flags: ["renew_soon"] },
    { subscription_id: "sub-cloud", name: "云存储", amount_cents: 600, cycle: "monthly", next_charge_date: "2026-11-20", status: "active", source: "registered", flags: [] },
    { subscription_id: "sub-gym", name: "健身App会员", amount_cents: 6800, cycle: "monthly", next_charge_date: "2026-11-01", status: "active", source: "registered", flags: ["renew_soon", "idle"] },
    { subscription_id: "det-reading", name: "读书App 自动续费", amount_cents: 1800, cycle: "monthly", next_charge_date: "2026-11-22", status: "active", source: "detected", flags: [] },
  ];
}

const clone = (x) => JSON.parse(JSON.stringify(x));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowMs = () => S.now + (Date.now() - S.realAt);
function iso(ms) {
  const d = new Date(ms + 8 * 3600e3);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}+08:00`;
}
const yuan = (c) => `¥${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const id = (p) => `${p}_${(++S.seq).toString(36)}${Math.random().toString(36).slice(2, 6)}`;
function err(status, code, message) { const e = new Error(message); e.status = status; e.code = code; return e; }

function trace(steps) {
  return steps.map(([kind, label, status = "pass", detail = {}, ms]) => ({ kind, label, status, detail, ms: ms ?? Math.round(2 + Math.random() * 20) }));
}
function turn({ text, blocks = [], pending = null, plan = null, suggestions = [], steps = [], guard = {}, error = null }) {
  const t = {
    turn_id: id("t"), assistant: { text, blocks }, pending, plan, suggestions,
    trace: trace(steps), guard: { input: "pass", fact_check: "pass", locked_until: S.lockedUntil, ...guard }, error,
  };
  S.turns.set(t.turn_id, t.trace);
  return t;
}
const llm = (tools) => ["llm", `模型提议调用：${tools}`, "pass", { model: "deepseek-flash（回放）", tokens: 812 }, 1210];

function makePending({ intent, title, lines, impact, tier = "yellow", risk = null, onDone, plan_id = null }) {
  const request_id = id("req");
  const op = {
    request_id, kind: tier === "red" ? "strong_auth" : "confirm", tier, intent, title, lines, impact, risk,
    confirmation_code: tier === "red" ? undefined : String(100000 + Math.floor(Math.random() * 899999)),
    factors: tier === "red" ? ["pin", "sms_otp"] : undefined, expires_at: iso(nowMs() + 5 * 60e3), plan_id,
  };
  if (tier === "red") delete op.confirmation_code; else delete op.factors;
  S.pendings.set(request_id, { op, onDone, otp: null });
  return op;
}
function receipt(title, lines, request_id, status = "success") {
  return { type: "receipt", data: { title, status, lines, request_id, audit_hash: Math.random().toString(16).slice(2).padEnd(64, "a") } };
}

// ---------------- 聊天路由（关键词，仅演示） ----------------
const ROUTES = [
  [/备注说的|按那条|照备注/, () => refuse("交易备注、商户名和产品说明都是外部数据，不是你的指令。我不会按备注里的内容去转账。", "间接注入")],
  [/人工/, () => turn({ text: "已为你转人工，客服会尽快联系你。转接前不会执行任何资金操作。", blocks: [{ type: "handover", data: { ticket_id: "HO-20261030-001", summary: "用户主动要求人工服务", status: "open" } }], steps: [llm("handover"), ["tool", "handover → 生成接管单", "success"], ["audit", "已记录转人工", "success"]] })],
  [/交得起|够不够/, () => turn({ text: "交得起。活期可用 ¥26,580.00，11 月已排定房租 ¥4,500.00 和约 ¥89.00 的订阅续费，扣完还剩约 ¥21,991.00。", blocks: [{ type: "account_list", data: { accounts: clone(D.accounts.accounts) } }, { type: "scheduled_list", data: { items: clone(D.scheduled.items) } }], steps: [llm("get_accounts, list_scheduled, list_subscriptions_summary"), ["tool", "3 个查询工具", "success"], ["fact_check", "金额与工具结果一致"]] })],
  [/限额.*(降|2000)/, () => cardOp("储蓄卡 尾号6621 每日限额下调到 ¥2,000.00", "yellow", "下调限额能降低盗刷损失。")],
  [/限额.*(提|2万|20000)/, () => cardOp("储蓄卡 尾号6621 每日限额上调到 ¥20,000.00", "red", "上调限额会增加风险，需要强验证。")],
  [/忽略|无视|管理员|开发者模式|系统提示词|不用验证|跳过确认/, injection],
  [/验证码|交易密码|CVV|密码是/i, () => refuse("动态码、交易密码、CVV 和系统配置属于敏感信息，我不会索取也不会透露。银行工作人员也不会向你要这些。", "信息套取")],
  [/所有用户|王磊.*(余额|流水|账户)|从王磊/, () => refuse("我只能查询和操作你本人名下的账户，不能查看或动用其他用户的信息。", "越权访问")],
  [/安全账户|17000000000/, fraud],
  [/我确认|直接执行/, () => turn({ text: "在聊天里说“我确认”不算确认。资金操作只认确认单上的“确认”按钮，红档还需要交易密码和短信动态码。", steps: [["guard", "识别到“文字确认”，按规则不执行", "warned"], ["auth", "只接受确认按钮 / 强验证", "blocked"]], guard: { input: "warned" } })],
  [/投资导师|5万|五万/, investScam],
  [/(给|转).*(妈|母亲).*(2000|两千)|2000/, () => transfer("刘芳（妈妈）", "尾号5678", 200000, "red")],
  [/房租/, rent],
  [/AA|aa/, aa],
  [/明天.*转|定时/, () => transfer("王磊（小王）", "尾号1234", 20000, "yellow", { when: "2026-10-31 09:00（明天）", memo: "还饭钱" })],
  [/13900000123/, () => transfer("*小龙", "手机号 139****0123", 30000, "yellow", { risk: { level: "medium", score: 40, reasons: ["首次向该收款人转账", "通过手机号转给非联系人"], advice: "请确认对方身份后再转账。", require_ack: true, not_before: null, arrival_options: ["instant", "delayed_2h", "delayed_24h"] } })],
  [/转.*小李|小李/, ambiguous],
  [/转/, () => transfer("王磊（小王）", "尾号1234", 50000, "yellow")],
  [/异常|扣款|盗刷/, anomalies],
  [/年报|今年|过去一年/, () => turn({ text: "这是你过去 12 个月的消费年报。", blocks: [{ type: "report", data: clone(D["report-annual"]) }], steps: [llm("annual_report"), ["tool", "annual_report(last12) → 12 个月", "success"], ["fact_check", "回复中的数字均来自工具结果"]] })],
  [/报告|月报/, () => turn({ text: "10 月账单报告生成好了。", blocks: [{ type: "report", data: clone(D["report-monthly"]) }], steps: [llm("monthly_report"), ["tool", "monthly_report(2026-10)", "success"], ["fact_check", "回复中的数字均来自工具结果"]] })],
  [/花|账单|支出/, spending],
  [/续费|自动扣费|订阅|扣费/, subscriptionsQuery],
  [/健身/, cancelGym],
  [/测评|买点理财|想买/, questionnaire],
  [/对比/, compare],
  [/推荐|稳一点/, recommend],
  [/赚了|收益|持仓/, () => turn({ text: "你目前持有稳健季享 ¥20,000.00，累计收益 ¥118.00（模拟）。", blocks: [{ type: "holding_list", data: { items: clone(D.holdings.holdings) } }], steps: [llm("get_holdings"), ["tool", "get_holdings → 1 项", "success"]] })],
  [/买.*稳健|申购/, purchase],
  [/赎回/, () => { const op = makePending({ intent: "redeem", title: "赎回 稳健季享", lines: [{ label: "产品", value: "稳健季享（R2）" }, { label: "赎回金额", value: "¥5,000.00", emphasis: true }, { label: "到账账户", value: "储蓄卡 尾号6621" }], impact: "确认后资金回到活期账户。", onDone: () => [receipt("赎回成功", [{ label: "金额", value: "¥5,000.00" }])] }); return turn({ text: "已为你生成赎回确认单。", pending: op, steps: [llm("redeem"), ["tier", "代码判档：黄档（理赎回为本人资金回流）", "pending"]] }); }],
  [/卡丢|丢了/, lostCard],
  [/冻/, () => cardOp("临时冻结 储蓄卡 尾号6621", "yellow", "冻结后这张卡暂时不能消费，随时可以解冻（解冻需要强验证）。")],
  [/虚拟卡/, () => cardOp("申请网购虚拟卡", "yellow", "新卡默认每日限额 ¥1,000.00，只用于线上消费。")],
  [/哪些卡|我的卡/, () => turn({ text: "你名下有 2 张模拟卡。", blocks: [{ type: "card_list", data: { items: clone(D.cards.cards) } }], steps: [llm("list_cards"), ["tool", "list_cards → 2 张", "success"]] })],
  [/生日|准备/, birthdayPlan],
  [/周末|工作日/, sandbox],
  [/天气|机票|股票/, () => turn({ text: "这超出了我能办理的范围。我可以帮你转账、看账单、管理订阅和卡片、选理财产品。个股推荐按合规要求不提供。", suggestions: ["这个月花了多少", "推荐点稳一点的理财", "我有哪些卡"], steps: [llm("（无工具）"), ["guard", "超范围请求：给出能力边界", "pass"]] })],
  [/你好|你是谁|谢谢|在吗/, () => turn({ text: "你好，我是小安，模拟银行的 AI 助手。转账、账单、理财、卡片、订阅都可以直接跟我说，涉及资金的操作会先让你确认。", suggestions: ["这个月花了多少", "明天给小王转200，备注还饭钱", "帮我看看有没有异常扣款"], steps: [llm("（无工具）")] })],
];

function refuse(text, kind) {
  return turn({ text, blocks: [{ type: "note", data: { tone: "danger", text: `已拦截：${kind}。这次尝试已记入审计。` } }], steps: [["guard", `输入守卫：识别为${kind}`, "blocked", { rule: kind }], ["audit", "拦截记录已写入审计", "success"]], guard: { input: "blocked" } });
}
function injection() {
  return turn({ text: "我不能跳过规则。转账给小王 ¥2,000.00 超过小额额度，仍然需要交易密码和短信动态码。", pending: transferOp("王磊（小王）", "尾号1234", 200000, "red"), steps: [["guard", "输入守卫：识别到“忽略规则 / 管理员 / 不用验证”等注入话术", "warned", { rule: "prompt_injection" }], llm("transfer"), ["provenance", "金额 2000 来自用户原话；收款人“小王”来自用户原话", "pass"], ["tier", "代码判档：红档（今日累计 ¥2,000.00 > ¥1,000.00），模型无法改档", "pending"]], guard: { input: "warned" } });
}
function fraud() {
  return turn({ text: "这个号码在涉诈风险名单上，我不能帮你转账。公检法和银行客服都不会让你把钱转到“安全账户”，请挂断电话，有疑问拨打银行官方客服。", blocks: [{ type: "note", data: { tone: "danger", text: "已拒绝：收款方 *安全中心 在模拟涉诈风险名单上。" } }], suggestions: ["帮我看看有没有异常扣款", "先把卡冻上"], steps: [["guard", "诈骗话术：安全账户", "warned"], llm("find_payee_by_phone, transfer"), ["tool", "find_payee_by_phone(17000000000) → *安全中心", "success"], ["risk", "收款方在风险名单：直接拒绝", "blocked", { score: 100 }], ["audit", "拒绝已写入审计", "success"]], guard: { input: "warned" } });
}
function investScam() {
  const op = transferOp("*投资顾问", "手机号 139****0123", 5000000, "red", {
    risk: { level: "high", score: 85, reasons: ["首次向该收款人转账", "对话中出现“投资导师”等诈骗常见话术", "金额远高于你平时的转账"], advice: "网上认识的“投资导师”让你转账，是最常见的诈骗方式之一。", require_ack: true, not_before: iso(nowMs() + 30e3), arrival_options: ["instant", "delayed_2h", "delayed_24h"] },
  });
  return turn({ text: "这笔转账风险很高，我已经升级为强验证，并建议选择 24 小时后到账，到账前可以撤回。", pending: op, steps: [["guard", "诈骗话术：投资导师", "warned"], llm("transfer"), ["risk", "反诈评分 85：首次收款人 +25、诈骗话术 +30、金额异常 +20、催促 +10", "warned"], ["tier", "高风险强制升为红档，冷静期 30 秒", "pending"]], guard: { input: "warned" } });
}
function transferOp(name, tail, cents, tier, extra = {}) {
  const lines = [{ label: "收款人", value: `${name} · ${tail}` }, { label: "金额", value: yuan(cents), emphasis: true }, { label: "付款账户", value: "储蓄卡 尾号6621（可用 ¥26,580.00）" }];
  if (extra.when) lines.push({ label: "执行时间", value: extra.when });
  if (extra.memo) lines.push({ label: "备注", value: extra.memo });
  lines.push({ label: "今日累计转出", value: `${yuan(cents)} / 小额额度 ¥1,000.00` });
  if (extra.risk) lines.push({ label: "到账方式", value: "实时到账" });
  return makePending({
    intent: extra.when ? "schedule_transfer" : "transfer", title: `${extra.when ? "定时转账" : "转账"}给 ${name}`, lines, tier, risk: extra.risk || null,
    impact: extra.when ? "确认后将于明天 09:00 执行，执行前会再次检查余额和限额。" : tier === "red" ? "单笔超过小额额度，需要交易密码 + 短信动态码。" : "确认后立即转出。",
    onDone: () => [receipt(extra.when ? "定时转账已预约" : "转账成功", [{ label: "收款人", value: name }, { label: "金额", value: yuan(cents) }, ...(extra.when ? [{ label: "执行时间", value: extra.when }] : [])], null, extra.when ? "scheduled" : "success")],
  });
}
function transfer(name, tail, cents, tier, extra = {}) {
  const op = transferOp(name, tail, cents, tier, extra);
  return turn({
    text: tier === "red" ? `给${name.replace(/（.*）/, "")}转 ${yuan(cents)} 超过小额额度，需要强验证。` : `好的，确认单在下面，核对无误后点确认。`,
    pending: op, suggestions: tier === "red" ? [] : ["改成300", "算了不转了"],
    steps: [["guard", "输入正常"], llm(extra.when ? "resolve_date, find_contacts, transfer" : "find_contacts, transfer"), ["resolver", `收款人解析：${name}${extra.when ? "；“明天”→ 2026-10-31" : ""}`, "pass"],
      ["provenance", "金额、收款人均来自用户原话", "pass"], extra.risk ? ["risk", `反诈评分 ${extra.risk.score}：${extra.risk.reasons.join("、")}`, "warned"] : ["risk", "反诈评分 0：常用收款人", "pass"],
      ["tier", tier === "red" ? `代码判档：红档（今日累计 ${yuan(cents)} > ¥1,000.00）` : `代码判档：黄档（今日累计 ${yuan(cents)} ≤ ¥1,000.00）`, "pending"]],
  });
}
function ambiguous() {
  return turn({ text: "你有两位联系人都叫“小李”，是哪一位？", blocks: [{ type: "options", data: { prompt: "选择收款人", ref: id("opt"), items: [{ label: "李明", value: "c-liming", hint: "同事 · 135****1357" }, { label: "李娜", value: "c-lina", hint: "大学同学 · 133****9090" }] } }], steps: [llm("find_contacts"), ["resolver", "“小李”匹配到 2 位联系人，需要追问", "warned"]] });
}
function rent() {
  return turn({ text: "找到房东李建国，上次房租是 ¥4,500.00。按这个金额交吗？", blocks: [{ type: "options", data: { prompt: "选择金额", ref: "rent-amount", items: [{ label: "按上次 ¥4,500.00", value: 450000, hint: "备注“房租”" }, { label: "我自己输入金额", value: "custom" }] } }], steps: [llm("search_contacts_by_memo"), ["tool", "按备注“房租”找到 李建国", "success"], ["provenance", "金额需要用户点选或说出，不能从历史流水直接取用", "pending"]] });
}
function aa() {
  const op = makePending({ intent: "create_aa", title: "发起 AA 收款", lines: [{ label: "总金额", value: "¥360.00" }, { label: "参与人", value: "你、王磊、张伟（3 人）" }, { label: "每人应付", value: "¥120.00", emphasis: true }, { label: "备注", value: "昨晚聚餐" }], impact: "确认后向王磊、张伟各发一笔 ¥120.00 的收款请求。", onDone: () => [receipt("AA 收款已发起", [{ label: "每人", value: "¥120.00" }, { label: "收款人数", value: "2 人" }]), { type: "aa_request", data: { request_id: "aa-1", from_name: "陈雨桐", amount_cents: 12000, memo: "昨晚聚餐", status: "open" } }] });
  return turn({ text: "360 元 3 人平摊，每人 ¥120.00。", pending: op, steps: [llm("find_contacts, create_aa"), ["resolver", "代码计算：36000 分 ÷ 3 = 12000 分", "pass"], ["tier", "代码判档：黄档", "pending"]] });
}
function spending() {
  return turn({ text: "这个月到目前一共支出 ¥14,830.00，最多的是购物和房租。", blocks: [{ type: "spending_breakdown", data: clone(D.spending_breakdown) }, { type: "trend_chart", data: clone(D["report-monthly"].charts[1].data) }], suggestions: ["帮我看看有没有异常扣款", "上个月外卖花了多少", "生成10月账单报告"], steps: [llm("spending_breakdown"), ["tool", "spending_breakdown(2026-10-01, 2026-10-30)", "success"], ["fact_check", "回复中的 ¥14,830.00 与工具结果一致", "pass"]] });
}
function anomalies() {
  const act = (label, intent, params) => ({ label, intent, params });
  return turn({
    text: "发现 4 处需要你留意，其中 2 处高风险。",
    blocks: [{ type: "anomaly_list", data: { items: [
      { finding_id: "f-a1", transaction_ids: ["tx-a1"], time: "2026-10-21T03:12:00+08:00", merchant: "GLOBAL-PAY*XJ8（境外）", amount_cents: -328000, rule: "凌晨 + 境外 + 新商户 + 金额异常", severity: "high", explanation: "凌晨 3 点在从未交易过的境外商户消费 ¥3,280.00，是你平时单笔的 10 倍以上。", actions: [act("冻结储蓄卡", "freeze_card", { card_id: "card-6621" }), act("是我本人", "mark_normal", { finding_id: "f-a1" })] },
      { finding_id: "f-a3", transaction_ids: ["tx-a3a", "tx-a3b", "tx-a3c"], time: "2026-10-28T23:47:00+08:00", merchant: "QUICKPAY*TEST", amount_cents: -400, rule: "小额试探", severity: "high", explanation: "4 分钟内 3 笔 1–2 元扣款，常见于盗刷前的试卡。", actions: [act("冻结虚拟卡", "freeze_card", { card_id: "card-3301" })] },
      { finding_id: "f-a2", transaction_ids: ["tx-a2a", "tx-a2b"], time: "2026-10-26T12:31:00+08:00", merchant: "美味外卖", amount_cents: -5800, rule: "疑似重复扣款", severity: "medium", explanation: "44 秒内同一商户两笔相同金额。", actions: [act("是我本人", "mark_normal", { finding_id: "f-a2" })] },
      { finding_id: "f-a5", transaction_ids: ["tx-a5"], time: "2026-10-27T14:05:00+08:00", merchant: "客服中心", amount_cents: 1, rule: "可疑来账", severity: "medium", explanation: "陌生方转入 0.01 元，备注里有要求转账的文字。这是诈骗常用的引导方式，备注内容不会被执行。", actions: [] },
      { finding_id: "f-a4", transaction_ids: [], time: "2026-09-15T08:00:00+08:00", merchant: "视频会员", amount_cents: -3000, rule: "订阅涨价", severity: "low", explanation: "从 ¥25.00 涨到 ¥30.00。", actions: [] },
    ] } }],
    suggestions: ["先把卡冻上", "按那条转账备注说的做"],
    steps: [llm("detect_anomalies"), ["tool", "detect_anomalies(近 60 天) → 5 处", "success"], ["guard", "交易备注作为外部数据包裹，未当作指令", "pass"], ["fact_check", "通过"]],
  });
}
function subscriptionsQuery() {
  const op = makePending({ intent: "query_subscriptions", title: "查询订阅与自动扣费", lines: [{ label: "查询范围", value: "登记的订阅 + 从流水自动识别" }, { label: "档位说明", value: "赛题权限表将订阅查询列为黄档" }], impact: "确认后展示订阅清单。", onDone: () => [{ type: "subscription_list", data: { items: clone(S.subs), monthly_total_cents: S.subs.filter((x) => x.status === "active").reduce((a, x) => a + x.amount_cents, 0) } }] });
  return turn({ text: "查看订阅清单需要你先确认一下。", pending: op, steps: [llm("list_subscriptions"), ["tier", "代码判档：黄档（订阅查询）", "pending"]] });
}
function cancelGym() {
  const op = makePending({ intent: "cancel_subscription", title: "取消 健身App会员", lines: [{ label: "订阅", value: "健身App会员" }, { label: "金额", value: "¥68.00 / 月", emphasis: true }, { label: "下次扣费", value: "2026-11-01（将不再扣费）" }], impact: "历史扣费记录保留，从下个周期起不再扣费。", onDone: () => { S.subs.find((x) => x.subscription_id === "sub-gym").status = "cancelled"; return [receipt("已取消订阅", [{ label: "订阅", value: "健身App会员" }])]; } });
  return turn({ text: "健身App会员已经 90 多天没用了，取消后每月省 ¥68.00。", pending: op, steps: [llm("cancel_subscription"), ["provenance", "订阅“健身会员”来自用户原话", "pass"], ["tier", "代码判档：黄档", "pending"]] });
}
const QUESTIONS = [["Q1", "投资经验", ["无", "1 年以内", "1–3 年", "3–5 年", "5 年以上"]], ["Q2", "能接受的最大亏损", ["不能亏", "5% 以内", "10% 以内", "20% 以内", "20% 以上"]], ["Q3", "计划投资期限", ["3 个月内", "3–6 个月", "6–12 个月", "1–3 年", "3 年以上"]], ["Q4", "收入稳定性", ["无稳定收入", "不太稳定", "一般", "稳定", "很稳定"]], ["Q5", "投资目的", ["保本", "稳定增值", "平衡", "较高收益", "高收益"]], ["Q6", "理财资金占总资产比例", ["70% 以上", "50–70%", "30–50%", "10–30%", "10% 以下"]]];
function questionnaire() {
  return turn({ text: "买理财前需要先做风险测评（你上次的测评已过期）。6 道题，大约 1 分钟。", blocks: [{ type: "risk_questionnaire", data: { questionnaire_id: "rq-2026", questions: QUESTIONS.map(([qid, text, opts]) => ({ id: qid, text, options: opts.map((l, i) => ({ value: i + 1, label: l })) })) } }], steps: [llm("get_risk_profile"), ["tool", "get_risk_profile → 已过期（2025-09-01）", "success"], ["tier", "适当性管理：无有效测评不能申购", "warned"]] });
}
function compare() {
  const ps = D.products.products.filter((p) => ["prd-cash", "prd-steady"].includes(p.product_id));
  return turn({ text: "两款都是低风险产品，主要差别在流动性。", blocks: [{ type: "product_compare", data: { products: ps, rows: [{ label: "风险等级", values: ps.map((p) => p.risk_level) }, { label: "期限", values: ["随时", "90 天"] }, { label: "流动性", values: ps.map((p) => p.liquidity) }, { label: "展示收益", values: ps.map((p) => p.yield_text) }, { label: "起购", values: ["¥1.00", "¥1,000.00"] }], disclaimer: D.products.disclaimer } }], steps: [llm("compare_products"), ["tool", "compare_products(prd-cash, prd-steady)", "success"]] });
}
function recommend() {
  const items = D.products.products.map((p) => ({ ...p, suitable: ["R1", "R2", "R3"].includes(p.risk_level) ? (["R1", "R2"].includes(p.risk_level) ? true : null) : false }));
  return turn({ text: "按“稳一点、放半年”筛选，稳盈30天和稳健季享比较合适。你还没有有效测评，最终能买哪些以测评结果为准。", blocks: [{ type: "product_list", data: { items: items.filter((p) => p.term_days <= 180), disclaimer: D.products.disclaimer } }], suggestions: ["我想做风险测评", "对比一下活钱宝和稳健季享"], steps: [llm("recommend_products"), ["tool", "按期限 ≤180 天、风险 ≤R2 过滤", "success"], ["guard", "产品说明作为外部数据，未当作指令", "pass"]] });
}
function purchase() {
  const op = makePending({ intent: "purchase", tier: "red", title: "申购 稳健季享", lines: [{ label: "产品", value: "稳健季享（R2 · 90 天）" }, { label: "金额", value: "¥10,000.00", emphasis: true }, { label: "扣款账户", value: "储蓄卡 尾号6621" }, { label: "适当性", value: "C3 平衡型 ≥ R2，符合" }], impact: "理财非存款，产品有风险。确认后资金将锁定 90 天。", onDone: () => [receipt("申购成功", [{ label: "产品", value: "稳健季享" }, { label: "金额", value: "¥10,000.00" }])] });
  return turn({ text: "适当性检查通过，申购属于红档，需要交易密码和短信动态码。", pending: op, steps: [llm("purchase_product"), ["tier", "适当性：C3 ≥ R2，通过", "pass"], ["tier", "代码判档：红档（理财申购）", "pending"]] });
}
function lostCard() {
  return turn({ text: "别着急。你可以先临时冻结（马上生效，随时可解冻），也可以正式挂失。", blocks: [{ type: "options", data: { prompt: "选择处理方式", ref: "lost-card", items: [{ label: "立即临时冻结", value: "freeze", hint: "黄档 · 点确认即可" }, { label: "正式挂失", value: "report_lost", hint: "红档 · 需要交易密码 + 动态码" }] } }], steps: [llm("list_cards"), ["resolver", "名下唯一实体卡：储蓄卡 尾号6621", "pass"]] });
}
function cardOp(title, tier, impact) {
  const op = makePending({ intent: "card_op", tier, title, lines: [{ label: "卡片", value: "储蓄卡 **** 6621" }, { label: "操作", value: title, emphasis: true }], impact, onDone: () => [receipt("办理成功", [{ label: "操作", value: title }])] });
  return turn({ text: tier === "red" ? "这个操作会增加风险，需要强验证。" : "确认单在下面。", pending: op, steps: [llm("card_operation"), ["tier", `代码判档：${tier === "red" ? "红档（增加风险）" : "黄档（降低风险）"}`, "pending"]] });
}
function birthdayPlan() {
  const plan_id = id("plan");
  const plan = {
    plan_id, title: "周屿生日筹备", status: "awaiting_confirmation", created_at: iso(nowMs()),
    nodes: [
      { id: "n1", title: "锁定生日预算 ¥1,000.00", intent: "reserve_budget", tier: "yellow", status: "pending", depends_on: [], run_at: null, result_summary: null, compensation: "release_budget" },
      { id: "n2", title: "11-10 订鲜花 ¥129.00", intent: "schedule_order", tier: "yellow", status: "waiting", depends_on: ["n1"], run_at: "2026-11-10T09:00:00+08:00", result_summary: null, compensation: "cancel_order" },
      { id: "n3", title: "11-10 订蛋糕 ¥99.00", intent: "schedule_order", tier: "yellow", status: "waiting", depends_on: ["n1"], run_at: "2026-11-10T09:00:00+08:00", result_summary: null, compensation: "cancel_order" },
      { id: "n4", title: "11-11 提醒你送礼物", intent: "reminder", tier: "green", status: "waiting", depends_on: ["n2", "n3"], run_at: "2026-11-11T20:00:00+08:00", result_summary: null, compensation: null },
    ],
    actions: ["pause", "rollback", "takeover"],
  };
  S.plans.set(plan_id, plan);
  const op = makePending({ intent: "plan_confirm", title: "确认整个计划：周屿生日筹备", plan_id, lines: [{ label: "步骤", value: "4 步（黄档 3 · 绿档 1）" }, { label: "预算", value: "¥1,000.00", emphasis: true }, { label: "预计花费", value: "¥228.00（鲜花 ¥129.00 + 蛋糕 ¥99.00）" }], impact: "一次确认绑定全部步骤；之后任何一步变化都要重新确认。", onDone: () => {
    plan.status = "running"; plan.nodes[0].status = "success"; plan.nodes[0].result_summary = "已锁定 ¥1,000.00"; plan.nodes[1].status = "scheduled"; plan.nodes[2].status = "scheduled"; plan.actions = ["pause", "rollback", "takeover"];
    return [receipt("计划已开始执行", [{ label: "预算", value: "已锁定 ¥1,000.00" }, { label: "下一步", value: "11-10 09:00 订花和蛋糕" }]), { type: "plan", data: clone(plan) }];
  } });
  return turn({ text: "帮你做了一个生日筹备计划，一次确认就能全部安排好。", plan: clone(plan), pending: op, steps: [llm("create_plan"), ["plan", "DAG 校验：4 个节点，无环，依赖完整", "pass"], ["tier", "计划整体判档：节点全为绿/黄 → 一次黄档确认", "pending"]] });
}
function sandbox() {
  return turn({ text: "近 3 个月外卖：工作日平均每笔 ¥47.20，周末平均每笔 ¥63.50。", blocks: [{ type: "code_analysis", data: { question: "周末和工作日外卖平均各花多少", code: "from statistics import mean\n\ndef analyze(transactions):\n    wd, we = [], []\n    for t in transactions:\n        if t['category'] != '餐饮外卖':\n            continue\n        (we if t['weekday'] >= 5 else wd).append(-t['amount_cents'])\n    return {'type': 'table', 'columns': ['类型', '笔数', '平均每笔_cents'],\n            'rows': [['工作日', len(wd), round(mean(wd))], ['周末', len(we), round(mean(we))]]}", engine: "subprocess", limits: { timeout_s: 5, memory_mb: 256, network: false }, duration_ms: 186, status: "ok", result: { type: "table", columns: ["类型", "笔数", "平均每笔_cents"], rows: [["工作日", 48, 4720], ["周末", 19, 6350]] } } }], steps: [llm("run_analysis"), ["tool", "AST 白名单检查通过（只用 statistics）", "pass"], ["tool", "沙箱运行：子进程 · 无网络 · 186ms", "success"], ["fact_check", "回复数字与沙箱输出一致", "pass"]] });
}

// ---------------- 路由 ----------------
export async function handle(method, path, body) {
  await load();
  await sleep(method === "POST" && /chat|action|quick/.test(path) ? 700 : 120);
  const [p, q] = path.split("?");
  const qs = new URLSearchParams(q || "");
  if (method === "GET") {
    if (p === "/api/v2/session") return sessionObj();
    if (p === "/api/v2/home") { const h = clone(D.home); h.now = iso(nowMs()); h.notifications = clone(S.notifications); return h; }
    if (p === "/api/v2/accounts") return clone(D.accounts);
    if (p === "/api/v2/transactions") {
      let items = clone(D.transactions.items);
      const kw = qs.get("q"), cat = qs.get("category");
      if (kw) items = items.filter((t) => (t.merchant + (t.memo || "")).includes(kw));
      if (cat) items = items.filter((t) => t.category === cat);
      return { items: items.slice(0, Number(qs.get("limit") || 50)), next_cursor: null };
    }
    if (p === "/api/v2/reports/monthly") { const r = clone(D["report-monthly"]); const m = qs.get("month"); if (m && m !== "2026-10") r.period = `${m}（假数据：沿用 10 月示例）`; return r; }
    if (p === "/api/v2/reports/annual") return clone(D["report-annual"]);
    if (p === "/api/v2/cards") return clone(D.cards);
    if (p === "/api/v2/products") return clone(D.products);
    if (p === "/api/v2/holdings") return clone(D.holdings);
    if (p === "/api/v2/scheduled") return clone(D.scheduled);
    if (p === "/api/v2/audit") return clone(D.audit);
    if (p === "/api/v2/notifications") return { items: clone(S.notifications) };
    if (p === "/api/v2/sim-phone") return { messages: clone(S.sms) };
    if (p === "/api/v2/plans") return { plans: [...S.plans.values()].map((x) => ({ plan_id: x.plan_id, title: x.title, status: x.status, created_at: x.created_at, node_count: x.nodes.length, done_count: x.nodes.filter((n) => n.status === "success").length })) };
    let m = /^\/api\/v2\/plans\/(.+)$/.exec(p);
    if (m) { const x = S.plans.get(decodeURIComponent(m[1])); if (!x) throw err(404, "not_found", "计划不存在"); return clone(x); }
    m = /^\/api\/v2\/turns\/(.+)$/.exec(p);
    if (m) return { turn_id: m[1], trace: S.turns.get(decodeURIComponent(m[1])) || [] };
    throw err(404, "not_found", "接口不存在");
  }
  switch (p) {
    case "/api/v2/chat": {
      const text = String(body.text || "");
      for (const [re, fn] of ROUTES) if (re.test(text)) return fn(text);
      return turn({ text: "我没太听懂，你可以换个说法，或者试试下面这些。", suggestions: ["这个月花了多少", "给小王转500", "我有哪些卡"], steps: [llm("（无工具）")] });
    }
    case "/api/v2/confirm": return confirm(body);
    case "/api/v2/cancel": { S.pendings.delete(body.request_id); return turn({ text: "好的，已取消，没有执行任何操作。", steps: [["auth", "用户取消确认单", "pass"], ["audit", "取消已记入审计", "success"]] }); }
    case "/api/v2/pending/revise": {
      const e = S.pendings.get(body.request_id);
      if (!e) throw err(409, "pending_invalid", "这张确认单已失效。");
      S.pendings.delete(body.request_id);
      const arrival = body.changes?.arrival;
      const label = { instant: "实时到账", delayed_2h: "2 小时后到账（可撤回）", delayed_24h: "24 小时后到账（可撤回）" }[arrival];
      const lines = e.op.lines.map((l) => (l.label === "到账方式" ? { ...l, value: label } : l));
      const op = makePending({ ...e.op, lines, onDone: e.onDone });
      return turn({ text: `已改为${label}，旧确认单作废。`, pending: op, steps: [["auth", "旧确认单作废，按新参数重新生成", "pass"]] });
    }
    case "/api/v2/strong-auth/send-otp": {
      const e = S.pendings.get(body.request_id);
      if (!e) throw err(409, "pending_invalid", "这张确认单已失效。");
      e.otp = String(100000 + Math.floor(Math.random() * 899999));
      const amount = e.op.lines.find((l) => l.emphasis)?.value || "";
      S.sms.push({ id: id("sms"), from: "模拟银行", text: `【模拟银行】验证码 ${e.otp}，用于${e.op.title}${amount ? " " + amount : ""}，5 分钟内有效。请勿告诉任何人。`, received_at: iso(nowMs()) });
      return { status: "sent", channel: "sim_sms", masked_phone: "138****0001", expires_at: iso(nowMs() + 300e3), resend_after_seconds: 60 };
    }
    case "/api/v2/strong-auth/verify": {
      if (S.lockedUntil && Date.parse(S.lockedUntil) > nowMs()) return turn({ text: "红档操作已锁定，请稍后再试。", error: { code: "locked", message: "连续 3 次验证失败，红档操作锁定 10 分钟。" }, steps: [["auth", "熔断中：拒绝", "blocked"]] });
      const e = S.pendings.get(body.request_id);
      if (!e) throw err(409, "pending_invalid", "这张确认单已失效。");
      if (e.op.risk?.require_ack && !body.risk_acknowledged) return turn({ text: "请先勾选“我已了解风险”。", pending: e.op, error: { code: "invalid_request", message: "需要确认已了解风险。" } });
      if (body.pin !== "135790" || !e.otp || body.otp !== e.otp) {
        S.fails += 1;
        if (S.fails >= 3) { S.lockedUntil = iso(nowMs() + 600e3); S.pendings.delete(body.request_id); S.fails = 0; return turn({ text: "连续 3 次验证失败，红档操作已锁定 10 分钟。", error: { code: "locked", message: "红档操作锁定 10 分钟（重启不清零）。" }, steps: [["auth", "第 3 次失败：触发熔断", "blocked"], ["audit", "锁定已写入审计", "success"]] }); }
        return turn({ text: `交易密码或动态码不正确，还可以再试 ${3 - S.fails} 次。`, pending: e.op, error: { code: "auth_failed", message: `交易密码或动态码不正确（不提示是哪一项），还剩 ${3 - S.fails} 次。` }, steps: [["auth", `强验证失败（第 ${S.fails} 次）`, "failed"]] });
      }
      S.fails = 0;
      S.pendings.delete(body.request_id);
      const blocks = e.onDone ? e.onDone() : [];
      blocks.forEach((b) => { if (b.type === "receipt") b.data.request_id = body.request_id; });
      return turn({ text: "强验证通过，已为你办好。", blocks, steps: [["auth", "交易密码 + 动态码校验通过", "success"], ["tool", "执行前复查：余额、归属、累计、授权、重复请求", "pass"], ["audit", "业务修改与审计同一事务提交", "success"]] });
    }
    case "/api/v2/plan/control": {
      const plan = S.plans.get(body.plan_id);
      if (!plan) throw err(404, "not_found", "计划不存在");
      const a = body.action;
      if (a === "pause") { plan.status = "paused"; plan.actions = ["resume", "rollback", "takeover"]; }
      if (a === "resume") { plan.status = "running"; plan.actions = ["pause", "rollback", "takeover"]; }
      if (a === "rollback") { plan.status = "rolled_back"; plan.nodes.forEach((n) => { if (n.status !== "waiting" && n.compensation) n.status = "rolled_back"; else if (n.status !== "success") n.status = "skipped"; }); plan.nodes[0].result_summary = "预算已释放 ¥1,000.00"; plan.actions = []; }
      if (a === "takeover") { plan.status = "handed_over"; plan.actions = []; }
      const blocks = [{ type: "plan", data: clone(plan) }];
      if (a === "takeover") blocks.push({ type: "handover", data: { ticket_id: "HO-PLAN-1", summary: `计划“${plan.title}”已转人工`, status: "open" } });
      return turn({ text: { pause: "计划已暂停，到点的步骤不会执行。", resume: "计划已继续。", rollback: "已回退：取消未执行的订单，释放预算 ¥1,000.00。", takeover: "已转人工，计划暂停等待处理。" }[a], plan: clone(plan), blocks, steps: [["plan", `计划控制：${a}`, "success"], ["audit", "已记入审计", "success"]] });
    }
    case "/api/v2/action": return action(body);
    case "/api/v2/quick-intent": {
      const it = body.intent;
      if (it === "query_subscriptions") return subscriptionsQuery();
      if (it === "freeze_card") return cardOp(`临时冻结 ${body.params?.card_id === "card-3301" ? "网购虚拟卡 尾号3301" : "储蓄卡 尾号6621"}`, "yellow", "冻结后暂时不能消费，随时可以解冻（解冻需要强验证）。");
      if (["unfreeze_card", "report_card_lost", "cancel_card_lost"].includes(it)) return cardOp({ unfreeze_card: "解除冻结", report_card_lost: "正式挂失", cancel_card_lost: "解除挂失" }[it], "red", "这个操作会增加风险，需要强验证。");
      if (it === "set_card_limit") { const v = body.params?.daily_limit_cents || 0; return cardOp(`每日限额调整为 ${yuan(v)}`, v < 500000 ? "yellow" : "red", v < 500000 ? "下调限额只需确认。" : "上调限额需要强验证。"); }
      if (it === "apply_virtual_card") return cardOp("申请网购虚拟卡", "yellow", "新卡默认每日限额 ¥1,000.00。");
      if (it === "cancel_subscription") return cancelGym();
      throw err(400, "unknown_intent", "不支持的操作");
    }
    case "/api/v2/demo/advance-clock": {
      const target = body.to ? Date.parse(body.to) : nowMs() + (body.minutes || 0) * 60e3;
      S.now = target; S.realAt = Date.now();
      const executed = [];
      for (const plan of S.plans.values()) {
        if (plan.status !== "running") continue;
        plan.nodes.forEach((n) => {
          if (n.status === "scheduled" && Date.parse(n.run_at) <= target) { n.status = "success"; n.result_summary = `已从预算付款 ${n.title.match(/¥[\d,.]+/)?.[0] || ""}`; executed.push({ id: id("n"), time: iso(target), kind: "scheduled_executed", title: n.title, body: "已从生日预算付款下单（模拟）", read: false }); }
        });
        if (plan.nodes.slice(0, 3).every((n) => n.status === "success")) plan.nodes[3].status = "scheduled";
      }
      if (target >= Date.parse("2026-11-01T09:00:00+08:00") && !S.rentDone) { S.rentDone = true; executed.push({ id: id("n"), time: "2026-11-01T09:00:00+08:00", kind: "scheduled_executed", title: "房租 ¥4,500.00 已转给李建国", body: "执行前已重新检查余额和授权", read: false }); }
      S.notifications.unshift(...executed);
      return { now: iso(target), executed };
    }
    case "/api/v2/demo/reset": D = null; S.pendings.clear(); S.sms = []; S.plans.clear(); S.fails = 0; S.lockedUntil = null; S.rentDone = false; S.user = "alice"; await load(); return sessionObj();
    case "/api/v2/demo/switch-user": S.user = body.user_id; return sessionObj();
    default: throw err(404, "not_found", "接口不存在");
  }
}

function sessionObj() {
  const s = clone(D.session);
  if (S.user === "bob") s.user = { user_id: "bob", display_name: "王磊", masked_phone: "138****1234" };
  s.demo.now = iso(nowMs());
  return s;
}

function confirm(body) {
  const e = S.pendings.get(body.request_id);
  if (!e) throw err(409, "pending_invalid", "这张确认单已失效，请重新发起。");
  if (body.confirmation_code !== e.op.confirmation_code) throw err(403, "bad_code", "确认码不匹配。");
  if (e.op.risk?.require_ack && !body.risk_acknowledged) return turn({ text: "请先勾选“我已了解风险”。", pending: e.op });
  S.pendings.delete(body.request_id);
  const blocks = e.onDone ? e.onDone() : [];
  blocks.forEach((b) => { if (b.type === "receipt") b.data.request_id = body.request_id; });
  const plan = blocks.find((b) => b.type === "plan")?.data || null;
  return turn({ text: "已按确认单办理。", blocks, plan, steps: [["auth", "确认码与参数哈希匹配，一次性使用", "success"], ["tool", "执行前复查：余额、归属、累计、授权、重复请求", "pass"], ["audit", "业务修改与审计同一事务提交", "success"]] });
}

function action(body) {
  if (body.type === "insight_accept") {
    if (body.ref === "ins-birthday") return birthdayPlan();
    if (body.ref === "ins-anomaly") return anomalies();
    if (body.ref === "ins-renewal") return subscriptionsQuery();
  }
  if (body.type === "option_select") {
    if (body.ref === "lost-card") return body.value === "freeze" ? cardOp("临时冻结 储蓄卡 尾号6621", "yellow", "冻结后暂时不能消费，随时可以解冻。") : cardOp("正式挂失 储蓄卡 尾号6621", "red", "挂失后这张卡将停止使用。");
    if (body.ref === "rent-amount" && body.value === 450000) return transfer("李建国（房东）", "尾号2468", 450000, "red", { memo: "房租" });
    if (body.value === "c-liming" || body.value === "c-lina") return transfer(body.value === "c-liming" ? "李明" : "李娜", body.value === "c-liming" ? "尾号1357" : "尾号9090", 50000, "yellow");
    return turn({ text: "好的，请告诉我具体金额。" });
  }
  if (body.type === "form_submit") {
    const score = Object.values(body.value || {}).reduce((a, x) => a + Number(x), 0);
    const level = score <= 9 ? "C1" : score <= 14 ? "C2" : score <= 20 ? "C3" : score <= 25 ? "C4" : "C5";
    const label = { C1: "保守型", C2: "稳健型", C3: "平衡型", C4: "成长型", C5: "进取型" }[level];
    const op = makePending({ intent: "submit_risk_assessment", title: "提交风险测评", lines: [{ label: "得分", value: `${score} 分` }, { label: "等级", value: `${level} ${label}`, emphasis: true }, { label: "有效期", value: "1 年" }], impact: "提交后按新的等级判断可购买的产品。", onDone: () => [{ type: "risk_profile", data: { level, label, score, valid_until: "2027-10-30", max_product_risk: `R${level.slice(1)}` } }] });
    return turn({ text: `测评得分 ${score} 分，对应 ${level} ${label}。请确认提交。`, pending: op, steps: [["resolver", `代码计分：${score} 分 → ${level}`, "pass"], ["tier", "代码判档：黄档（提交测评）", "pending"]] });
  }
  if (body.type === "block_action") {
    const v = body.value || {};
    if (v.intent === "freeze_card") return cardOp(`临时冻结 ${v.params?.card_id === "card-3301" ? "网购虚拟卡 尾号3301" : "储蓄卡 尾号6621"}`, "yellow", "冻结后暂时不能消费，随时可以解冻。");
    if (v.intent === "mark_normal") return turn({ text: "好的，已标记为本人交易，之后不再提醒这一笔。", steps: [["tool", "mark_normal", "success"]] });
  }
  return turn({ text: "这个操作在假数据模式里还没有示例。" });
}

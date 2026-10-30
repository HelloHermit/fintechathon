"use strict";

// 浏览器只提交用户选择，业务权限、金额和确认有效期始终由后端复查。
const elements = Object.fromEntries([
  "session-user", "connection-notice", "connection-message", "reconnect-button",
  "empty-state", "messages", "conversation-scroll", "message-form", "message-input",
  "send-button", "send-label", "activity-status", "audit-button", "audit-dialog",
  "close-audit-button", "audit-content", "confirmation-empty", "confirmation-active",
  "confirmation-details", "confirmation-expiry", "confirmation-code", "confirm-button",
  "cancel-button", "plan-panel", "plan-status", "plan-steps", "plan-policy",
  "resume-button", "interrupt-button", "takeover-button",
  "history-button", "history-dialog", "close-history-button", "refresh-history-button",
  "cancel-session-work-button",
  "history-message", "history-plans", "history-handovers", "recovery-review",
  "confirmation-dock", "confirmation-close",
].map(identifier => [identifier, document.getElementById(identifier)]));

const intentLabels = {
  query_balance: "账户余额", query_transactions: "交易流水", analyze_bills: "账单分析",
  query_subscriptions: "订阅与代扣", cancel_subscription: "取消模拟订阅", transfer: "模拟转账",
  query_investments: "模拟理财目录", compare_investments: "产品对比", match_investments: "产品条件匹配",
  query_cards: "模拟卡管理", apply_virtual_card: "申请模拟虚拟卡", set_card_limit: "调整模拟卡限额",
  query_services: "模拟生活服务", query_budgets: "预算记录", query_orders: "模拟订单",
  reserve_budget: "保留模拟预算", release_budget: "释放剩余预算", place_order: "支付模拟订单",
  purchase_investment: "购买模拟理财", redeem_investment: "赎回模拟理财",
  report_card_lost: "挂失模拟卡", restore_card: "恢复模拟卡",
  unknown: "处理回执",
};
const statusLabels = {
  success: "已完成", pending: "等待确认", rejected: "已拒绝", failed: "处理失败",
  cancelled: "已取消", expired: "已到期", interrupted: "已中断", human_takeover: "人工接管",
  not_started: "未开始", ready: "可继续", waiting_confirmation: "等待确认",
  running: "执行中", blocked: "已停止", skipped: "未执行",
  active: "可用", exhausted: "已全部用完", released: "剩余已释放", paid: "已模拟支付",
};
const fieldLabels = {
  user_id: "当前用户", intent: "操作", account_id: "本人账户", contact_id: "联系人编号",
  contact_name: "联系人", subscription_id: "订阅编号", subscription_name: "订阅名称",
  start_date: "开始日期", end_date: "结束日期", amount_cents: "金额", source_account_id: "转出账户",
  target_account_id: "收款账户", daily_outgoing_cents: "今日已成功转出",
  daily_outgoing_after_cents: "本次成功后的日累计", request_id: "请求编号", timestamp: "时间",
  step_id: "步骤编号", tier: "代码判定档位", event: "审计事件", result: "结果",
  reason: "原因", raw_input_redacted: "脱敏输入", params_redacted: "脱敏参数",
  history_preserved: "保留历史账单", status: "状态", plan_id: "计划编号",
  target_name: "操作目标", impact: "本次影响", committed: "已提交",
  current_balance_cents: "当前模拟余额", shanghai_date: "执行日",
  product_id: "产品编号", product_ids: "产品编号", risk_level: "风险等级", horizon_days: "持有期限（天）",
  liquidity: "流动性要求", min_days: "最短持有（天）", illustrative_annual_rate_bps: "假设年化展示值（基点）",
  card_id: "模拟卡编号", kind: "卡类型", daily_limit_cents: "模拟卡日限额", card_status: "卡状态",
  card_daily_limit_cents: "当前卡日限额", card_daily_spent_cents: "本卡今日已付", card_account_id: "卡所属账户",
  budget_id: "预算ID", event_date: "活动日期", service_id: "服务编号", service_name: "模拟服务",
  order_id: "订单编号", price_cents: "固定服务价格", service_price_cents: "固定服务价格",
  remaining_cents: "预算剩余保留", spent_cents: "预算已付", released_cents: "预算已释放",
  budget_remaining_cents: "当前预算剩余", budget_event_date: "预算活动日期", budget_status: "预算状态",
  budget_account_id: "预算来源账户", reserved_cents: "已保留预算", available_cents: "可用余额",
  balance_cents: "账面余额", current_available_cents: "当前可用余额", current_reserved_cents: "当前预算保留",
  available_balance_cents: "当前可用余额", created_at: "建立时间", executed_at: "模拟支付时间",
  criteria: "本人匹配条件", simulated: "模拟数据", name: "名称",
  budget: "预算当前事实", service: "选用模拟服务", card: "选用模拟卡", source: "来源账户",
  daily_total_cents: "今日资金已成功转出", card_daily_total_cents: "本卡今日已支付",
};
const operationFactGroups = {
  budget: {title: "预算当前状态", labels: {user_id: "预算所有者", account_id: "预算来源账户", event_date: "预算活动日期", amount_cents: "原始预算", remaining_cents: "剩余保留", spent_cents: "已经支付", released_cents: "已经释放", status: "预算状态"}},
  service: {title: "本次模拟服务", labels: {name: "模拟服务名称", price_cents: "一件固定价格"}},
  card: {title: "选用模拟卡", labels: {user_id: "卡片所有者", account_id: "卡片所属账户", kind: "模拟卡类型", status: "卡片状态", daily_limit_cents: "每日支付限额"}},
  source: {title: "来源账户当前状态", labels: {account_id: "来源账户", balance_cents: "账面余额", reserved_cents: "预算保留", available_cents: "可用余额"}},
};
const tierLabels = { green: "绿档", yellow: "黄档", red: "红档", none: "未授权" };
const riskLabels = { low: "低", medium: "中", high: "高" };
const liquidityLabels = { immediate: "即时可用", flexible: "灵活", locked: "锁定" };
const cardKindLabels = { debit: "模拟借记卡", virtual: "模拟虚拟卡" };
const subscriptionStatusLabels = { active: "安排中", cancelled: "已取消" };
const auditEventLabels = {
  received: "收到请求", classified: "代码判档", waiting_confirmation: "等待确认",
  confirmed: "确认通过", executed: "业务完成", rejected: "拒绝", failed: "失败",
  cancelled: "取消", expired: "到期", restart: "会话启动", audit_read: "查看审计",
  verification_failed: "验证失败", locked: "操作锁定", unlocked: "锁定解除",
  plan_accepted: "接收候选计划", step_started: "步骤开始", step_completed: "步骤完成",
  interrupted: "计划中断", human_takeover: "人工接管",
  clarification: "请补充信息", context_cleared: "结束本轮草稿",
};

let session = null;
let busy = false;
let pendingOperation = null;
let currentPlan = null;
let expiryTimer = null;
let pageLeaving = false;
const displayedPlanResults = new Set();
const confirmationRail = document.querySelector(".confirmation-rail");

/** 创建文字节点：外部结果永远不作为HTML执行。 */
function createTextElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = displayText(text);
  return element;
}

/** 页面不保存秘密；可疑凭据在显示时也隐藏，确认码只放指定确认栏。 */
function displayText(value) {
  return String(value ?? "")
    .replace(/\b(?:sk-|Bearer\s+)[A-Za-z0-9_.-]{8,}/gi, "[凭据已隐藏]")
    .replace(/((?:api[_ -]?key|password|密码|密钥|认证码|验证码|confirmation_code)\s*[:：=]\s*)[^\s,，;；]+/gi, "$1[已隐藏]");
}

/** 深层详情中剔除认证字段，不把pending整体串成JSON。 */
function safeDetails(value, depth = 0) {
  if (depth > 8) return "[层级过深]";
  if (Array.isArray(value)) return value.slice(0, 200).map(item => safeDetails(item, depth + 1));
  if (value && typeof value === "object") {
    const output = {};
    for (const [key, entry] of Object.entries(value)) {
      if (/secret|password|token|api.?key|confirm.*code|recovery.*code|authenticator/i.test(key)) continue;
      output[key] = safeDetails(entry, depth + 1);
    }
    return output;
  }
  return typeof value === "string" ? displayText(value) : value;
}

/** 金额按整数分转成文字，不参与权限计算。 */
function formatMoney(amountCents) {
  if (!Number.isSafeInteger(amountCents)) return "金额格式异常";
  const absoluteCents = Math.abs(amountCents);
  const sign = amountCents < 0 ? "-" : "";
  const wholeYuan = Math.floor(absoluteCents / 100).toLocaleString("zh-CN");
  return `${sign}¥ ${wholeYuan}.${String(absoluteCents % 100).padStart(2, "0")}`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return displayText(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(date);
}

function fieldValue(key, value) {
  if (key.endsWith("_cents")) return formatMoney(value);
  if (key === "intent") return intentLabels[value] || displayText(value);
  if (key === "tier") return tierLabels[value] || displayText(value);
  if (key === "risk_level") return riskLabels[value] || displayText(value);
  if (key === "liquidity") return liquidityLabels[value] || displayText(value);
  if (key === "kind") return cardKindLabels[value] || displayText(value);
  if (key === "event") return auditEventLabels[value] || displayText(value);
  if (key === "status" || key === "result") return statusLabels[value] || subscriptionStatusLabels[value] || displayText(value);
  if (["timestamp", "created_at", "executed_at"].includes(key)) return formatTime(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(safeDetails(value)) : displayText(value);
}

function appendDetailList(parent, fields, labels = {}) {
  const list = createTextElement("dl", "detail-list");
  for (const [key, value] of fields) {
    const row = createTextElement("div", "detail-row");
    row.append(createTextElement("dt", "", labels[key] || fieldLabels[key] || key), createTextElement("dd", "", fieldValue(key, value)));
    list.append(row);
  }
  parent.append(list);
}

/** 技术信息默认折叠；只序列化明确经过脱敏的字段。 */
function appendTechnicalDetails(parent, value, title = "技术详情") {
  const details = createTextElement("details", "safe-details");
  details.append(createTextElement("summary", "", title), createTextElement("pre", "", JSON.stringify(safeDetails(value), null, 2)));
  parent.append(details);
  return details;
}

function statusSymbol(status) {
  if (["success", "paid", "active"].includes(status)) return "✓";
  if (["pending", "waiting_confirmation", "running"].includes(status)) return "◷";
  if (["failed", "rejected", "expired"].includes(status)) return "!";
  if (["interrupted", "cancelled", "blocked", "human_takeover"].includes(status)) return "Ⅱ";
  return "○";
}

function createStatusBadge(status, text) {
  const knownStatus = Object.hasOwn(statusLabels, status) ? status : "unknown";
  const badge = createTextElement("span", `receipt-state ${knownStatus}`);
  const symbol = createTextElement("span", "state-icon", statusSymbol(status));
  symbol.setAttribute("aria-hidden", "true");
  badge.append(symbol, document.createTextNode(displayText(text || statusLabels[status] || status)));
  return badge;
}

/** 仅把返回中的整数分排成指标，不推算余额或生成预期收益。 */
function appendMoneyMetrics(parent, metrics) {
  const validMetrics = metrics.filter(([, value]) => Number.isSafeInteger(value));
  if (!validMetrics.length) return;
  const group = createTextElement("div", "result-metrics");
  for (const [label, value] of validMetrics) {
    const item = createTextElement("div", "result-metric");
    item.append(createTextElement("p", "result-label", label), createTextElement("p", "result-metric-value", formatMoney(value)));
    group.append(item);
  }
  parent.append(group);
}

function appendOperationTier(parent, tier) {
  const safeTier = Object.hasOwn(tierLabels, tier) ? tier : "none";
  const badge = createTextElement("span", `operation-tier ${safeTier}`);
  const icon = createTextElement("span", "state-icon", tier === "red" ? "!" : tier === "yellow" ? "◷" : "✓");
  icon.setAttribute("aria-hidden", "true");
  badge.append(icon, document.createTextNode(`代码判定 · ${tierLabels[tier] || "未授权"}`));
  parent.append(badge);
}

function isOperationFactGroup(key, value) {
  return Object.hasOwn(operationFactGroups, key) && value && typeof value === "object" && !Array.isArray(value);
}

/** 摘要也只取同一次后端核对事实，不从目录或页面自行计算价格与余额。 */
function appendOperationHighlights(fields, operation) {
  for (const [group, field, label] of [
    ["service", "price_cents", "service_price_cents"],
    ["source", "available_cents", "current_available_cents"],
    ["budget", "remaining_cents", "budget_remaining_cents"],
  ]) {
    const value = operation[group];
    if (isOperationFactGroup(group, value) && Object.hasOwn(value, field) && !fields.some(([key]) => key === label)) fields.push([label, value[field]]);
  }
}

/** 确认与恢复共用中文分组；完整保留已知对象中的每项已脱敏事实。 */
function appendOperationFactGroups(parent, operation) {
  for (const [key, definition] of Object.entries(operationFactGroups)) {
    if (!isOperationFactGroup(key, operation[key])) continue;
    const group = createTextElement("section", "operation-fact-group");
    group.append(createTextElement("h4", "step-result-heading", definition.title));
    appendDetailList(group, Object.entries(safeDetails(operation[key])), definition.labels);
    parent.append(group);
  }
}

function appendTable(parent, headings, rows) {
  const wrapper = createTextElement("div", "table-wrap");
  const table = createTextElement("table", "result-table");
  const header = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const heading of headings) {
    const cell = createTextElement("th", "", heading);
    cell.scope = "col";
    headerRow.append(cell);
  }
  header.append(headerRow);
  const body = document.createElement("tbody");
  for (const values of rows) {
    const row = document.createElement("tr");
    for (const value of values) {
      const text = displayText(value);
      const cell = createTextElement("td", /^-?¥\s/.test(text) ? "numeric" : "");
      if (text.length > 140) {
        const details = createTextElement("details", "long-cell");
        details.append(createTextElement("summary", "", `${text.slice(0, 64)}… 查看完整内容`), createTextElement("p", "", text));
        cell.append(details);
      } else cell.textContent = text;
      row.append(cell);
    }
    body.append(row);
  }
  table.append(header, body);
  wrapper.append(table);
  parent.append(wrapper);
}

/** 只展示工具实际回传的数据，区分实际支出和未来安排。 */
function renderToolResult(parent, intent, data, reviewedOperation = null) {
  if (!data || typeof data !== "object") return;
  const result = createTextElement("div", "tool-result");
  if (intent === "analyze_bills" && Number.isSafeInteger(data.actual_expense_cents)) {
    result.append(createTextElement("p", "result-label", "已发生的实际支出"), createTextElement("p", "result-total", formatMoney(data.actual_expense_cents)));
    if (data.start_date || data.end_date) result.append(createTextElement("p", "result-note", `${data.start_date || "—"} 至 ${data.end_date || "—"}`));
    if (data.categories && typeof data.categories === "object") {
      appendTable(result, ["支出类别", "金额"], Object.entries(data.categories).map(([category, amount]) => [category, formatMoney(amount)]));
    }
    result.append(createTextElement("p", "result-note", "以上来自已发生的账本支出；未来订阅费用另行查询，预算保留不计为消费。"));
  } else if (intent === "query_balance" && Array.isArray(data.accounts)) {
    if (!data.accounts.length) result.append(createTextElement("p", "", "未找到本人账户记录。"));
    const accounts = Array.isArray(data.available_balances) ? data.available_balances : data.accounts;
    for (const account of accounts) {
      const card = createTextElement("section", "result-card");
      card.append(createTextElement("h4", "result-card-heading", account.account_id));
      appendMoneyMetrics(card, [["账面余额", account.balance_cents], ["预算保留", account.reserved_cents], ["可用余额", account.available_cents]]);
      result.append(card);
    }
    if (Array.isArray(data.available_balances)) result.append(createTextElement("p", "result-note", "可用余额已扣除预算保留；保留本身不算已发生支出。"));
  } else if (intent === "query_subscriptions" && Array.isArray(data.subscriptions)) {
    if (!data.subscriptions.length) result.append(createTextElement("p", "", "未找到本人订阅记录。"));
    else appendTable(result, ["模拟订阅", "每期金额", "状态"], data.subscriptions.map(subscription => [subscription.name, formatMoney(subscription.amount_cents), subscriptionStatusLabels[subscription.status] || subscription.status]));
    if (Number.isSafeInteger(data.future_expected_cents)) {
      result.append(createTextElement("p", "result-label result-note", "未来一个续费周期的预计支出"), createTextElement("p", "result-total", formatMoney(data.future_expected_cents)));
    }
    result.append(createTextElement("p", "result-note", "预计费用尚未发生，不计入已发生的实际账单。"));
  } else if (intent === "query_transactions" && Array.isArray(data.transactions)) {
    if (!data.transactions.length) result.append(createTextElement("p", "", "当前范围未找到交易记录。"));
    else appendTable(result, ["时间 / 类别", "金额", "状态"], data.transactions.map(transaction => [`${formatTime(transaction.occurred_at)}\n${transaction.category || transaction.kind || ""}`, formatMoney(transaction.amount_cents), statusLabels[transaction.status] || transaction.status]));
  } else if (intent === "transfer") {
    if (Number.isSafeInteger(data.amount_cents)) result.append(createTextElement("p", "result-label", "本次已转出"), createTextElement("p", "result-total", formatMoney(data.amount_cents)));
    if (reviewedOperation?.target_name) result.append(createTextElement("p", "result-recipient", `收款对象：${reviewedOperation.target_name}`));
    appendDetailList(result, ["source_account_id", "target_account_id", "daily_outgoing_cents"].filter(key => Object.hasOwn(data, key)).map(key => [key, data[key]]));
    result.append(createTextElement("p", "result-note", "本次回执未包含执行后余额，可继续查询账户余额与流水核对。"));
  } else if (intent === "cancel_subscription") {
    appendDetailList(result, ["subscription_id", "status", "history_preserved"].filter(key => Object.hasOwn(data, key)).map(key => [key, data[key]]));
  } else if (["query_investments", "compare_investments", "match_investments"].includes(intent) && Array.isArray(data.products)) {
    if (data.criteria && typeof data.criteria === "object") appendDetailList(result, Object.entries(safeDetails(data.criteria)));
    if (!data.products.length) result.append(createTextElement("p", "", "没有符合本次明确条件的模拟产品，未放宽条件。"));
    else appendTable(result, ["模拟产品 / 编号", "风险", "最短持有", "流动性", "假设年化"], data.products.map(product => {
      const rate = product.illustrative_annual_rate_bps;
      const rateLabel = Number.isSafeInteger(rate) ? `${Math.floor(rate / 100)}.${String(rate % 100).padStart(2, "0")}%` : "—";
      return [`${product.name}\n${product.product_id}`, riskLabels[product.risk_level] || product.risk_level, `${product.min_days}天`, liquidityLabels[product.liquidity] || product.liquidity, rateLabel];
    }));
    result.append(createTextElement("p", "result-note", "利率为假设展示数据，不代表真实产品、保证收益或预测。购买和赎回为红档，当前拒绝执行。"));
  } else if (intent === "query_services" && Array.isArray(data.services)) {
    if (!data.services.length) result.append(createTextElement("p", "", "未找到模拟服务。"));
    else appendTable(result, ["模拟服务", "服务编号", "一件固定价"], data.services.map(service => [service.name, service.service_id, formatMoney(service.price_cents ?? service.amount_cents)]));
    result.append(createTextElement("p", "result-note", "仅模拟立即支付，一单一件；不会联系真实商家，也不会在活动日期自动执行。"));
  } else if (intent === "query_cards" && Array.isArray(data.cards)) {
    appendCards(result, data.cards);
  } else if (["apply_virtual_card", "set_card_limit"].includes(intent) && data.card) {
    if (intent === "set_card_limit" && reviewedOperation?.card && Number.isSafeInteger(data.card.daily_limit_cents)) {
      appendMoneyMetrics(result, [["确认时日限额", reviewedOperation.card.daily_limit_cents], ["执行后日限额", data.card.daily_limit_cents]]);
    }
    appendCards(result, [data.card]);
  } else if (intent === "query_budgets" && Array.isArray(data.budgets)) {
    appendBudgets(result, data.budgets);
  } else if (["reserve_budget", "release_budget"].includes(intent) && data.budget) {
    if (intent === "release_budget" && reviewedOperation?.budget && Number.isSafeInteger(data.budget.remaining_cents)) {
      appendMoneyMetrics(result, [["确认时保留", reviewedOperation.budget.remaining_cents], ["执行后保留", data.budget.remaining_cents]]);
    }
    appendBudgets(result, [data.budget]);
  } else if (intent === "query_orders" && Array.isArray(data.orders)) {
    appendOrders(result, data.orders);
  } else if (intent === "place_order" && data.order) {
    appendOrders(result, [data.order], reviewedOperation);
    if (reviewedOperation?.budget && data.budget) {
      appendMoneyMetrics(result, [["确认时预算保留", reviewedOperation.budget.remaining_cents], ["执行后预算保留", data.budget.remaining_cents]]);
    }
    if (data.budget) appendBudgets(result, [data.budget]);
    if (Number.isSafeInteger(data.daily_outgoing_cents)) appendDetailList(result, [["daily_outgoing_cents", data.daily_outgoing_cents]]);
    result.append(createTextElement("p", "result-note", "付款消耗已保留的预算，并记入实际支出。可用余额以账户查询结果为准。"));
  } else {
    appendTechnicalDetails(result, data, "查看实际返回数据");
  }
  if (data.basis) result.append(createTextElement("p", "result-note", data.basis));
  if (Object.hasOwn(intentLabels, intent) && intent !== "unknown") appendTechnicalDetails(result, data, "技术详情 · 完整工具回执");
  parent.append(result);
}

function appendCards(parent, cards) {
  if (!cards.length) parent.append(createTextElement("p", "", "未找到本人模拟卡。"));
  for (const card of cards) {
    const panel = createTextElement("section", "result-card");
    const heading = createTextElement("div", "result-card-heading");
    heading.append(createTextElement("h4", "", cardKindLabels[card.kind] || card.kind), createStatusBadge(card.status));
    panel.append(heading);
    appendMoneyMetrics(panel, [["每日支付限额", card.daily_limit_cents]]);
    appendDetailList(panel, [["card_id", card.card_id], ["account_id", card.account_id]]);
    parent.append(panel);
  }
  parent.append(createTextElement("p", "result-note", "编号为非支付模拟标识，不包含真实卡号、CVV或授信；卡限额不提高资金总日限额。"));
}

function appendBudgets(parent, budgets) {
  if (!budgets.length) parent.append(createTextElement("p", "", "未找到本人预算记录。"));
  for (const budget of budgets) {
    const panel = createTextElement("section", "result-card budget-breakdown");
    const heading = createTextElement("div", "result-card-heading");
    heading.append(createTextElement("h4", "", `预算 ${budget.budget_id}`), createStatusBadge(budget.status));
    panel.append(heading);
    appendMoneyMetrics(panel, [["剩余保留", budget.remaining_cents], ["已经支付", budget.spent_cents], ["已经释放", budget.released_cents]]);
    appendDetailList(panel, ["amount_cents", "account_id", "event_date"].filter(key => Object.hasOwn(budget, key)).map(key => [key, budget[key]]), { amount_cents: "原始预算" });
    parent.append(panel);
  }
  if (budgets.length) parent.append(createTextElement("p", "result-note", "预算金额 = 剩余保留 + 已付 + 已释放。释放只解除剩余保留，已付订单不会退款；活动日期不代表定时任务。"));
}

function appendOrders(parent, orders, reviewedOperation = null) {
  if (!orders.length) parent.append(createTextElement("p", "", "未找到本人模拟订单。"));
  for (const order of orders) {
    const panel = createTextElement("section", "result-card order-result");
    const heading = createTextElement("div", "result-card-heading");
    const serviceName = order.service_name || (reviewedOperation?.params?.service_id === order.service_id ? reviewedOperation.service?.name : null) || order.service_id;
    heading.append(createTextElement("h4", "", serviceName), createStatusBadge(order.status));
    panel.append(heading, createTextElement("p", "result-total", formatMoney(order.amount_cents)));
    appendDetailList(panel, ["budget_id", "account_id", "card_id", "event_date", "executed_at"].filter(key => Object.hasOwn(order, key) && order[key] !== null).map(key => [key, order[key]]));
    if (!order.card_id) panel.append(createTextElement("p", "result-note", "按预算来源账户支付，未选择模拟卡。"));
    appendTechnicalDetails(panel, { order_id: order.order_id, service_id: order.service_id }, "技术详情 · 订单编号");
    parent.append(panel);
  }
}

function showConversation() {
  elements["empty-state"].hidden = true;
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    const scroller = elements["conversation-scroll"];
    if (scroller.scrollHeight > scroller.clientHeight) scroller.scrollTop = scroller.scrollHeight;
  });
}

function appendUserMessage(text) {
  showConversation();
  const message = createTextElement("article", "message message-user");
  message.append(createTextElement("p", "message-label", "你"), createTextElement("p", "message-text", text));
  elements.messages.append(message);
  scrollToLatest();
}

function appendLocalNotice(text) {
  showConversation();
  const message = createTextElement("article", "message receipt");
  message.append(createTextElement("p", "message-label", "页面提示"), createTextElement("p", "message-text", text));
  elements.messages.append(message);
  scrollToLatest();
}

/** 回执里没有确认码；当前授权始终单独放在右栏。 */
function appendReceipt(response, reviewedOperation = null) {
  showConversation();
  const article = createTextElement("article", "message receipt");
  const heading = createTextElement("div", "receipt-heading");
  heading.append(createTextElement("h3", "", intentLabels[response.intent] || "处理回执"));
  const receiptStatus = response.reason === "clarification" ? "请补充信息"
    : response.status === "pending" && response.tier === "red"
      ? "红档不可执行" : statusLabels[response.status] || response.status || "未知状态";
  heading.append(createStatusBadge(response.tier === "red" && response.status === "pending" ? "rejected" : response.status, receiptStatus));
  article.append(heading, createTextElement("p", "message-text", response.message || "后端已返回处理状态。"));
  if (response.tier) {
    const permissionNote = response.tier === "none" && response.plan
      ? "计划汇总 · 各步骤单独判定权限"
      : `代码判定：${tierLabels[response.tier] || response.tier}`;
    article.append(createTextElement("p", "receipt-meta", permissionNote));
  }
  if (response.data) renderToolResult(article, response.intent, response.data, reviewedOperation);
  if (response.plan && Array.isArray(response.plan.steps)) {
    for (const step of response.plan.steps) {
      if (step.status !== "success" || !step.data) continue;
      const resultIdentifier = `${response.plan.plan_id || response.plan_id}:${step.id}:${step.request_id || ""}`;
      if (displayedPlanResults.has(resultIdentifier)) continue;
      displayedPlanResults.add(resultIdentifier);
      if (response.data && step.request_id === response.request_id) continue;
      article.append(createTextElement("h4", "step-result-heading", `已完成步骤：${intentLabels[step.intent] || step.intent}`));
      renderToolResult(article, step.intent, step.data);
    }
  }
  if (response.request_id) appendTechnicalDetails(article, { request_id: response.request_id, intent: response.intent, tier: response.tier, reason: response.reason }, "技术详情 · 回执标识");
  elements.messages.append(article);
  scrollToLatest();
}

function clearPending() {
  if (expiryTimer) window.clearInterval(expiryTimer);
  expiryTimer = null;
  pendingOperation = null;
  elements["confirmation-code"].textContent = "";
  elements["confirmation-code"].parentElement.hidden = false;
  elements["confirmation-code"].parentElement.open = false;
  elements["confirm-button"].hidden = false;
  elements["cancel-button"].hidden = false;
  elements["confirmation-details"].replaceChildren();
  elements["confirmation-expiry"].textContent = "";
  elements["confirmation-active"].hidden = true;
  elements["confirmation-empty"].hidden = false;
  confirmationRail.classList.remove("has-operation", "has-outcome", "is-open");
  elements["confirmation-dock"].hidden = true;
  elements["confirmation-dock"].setAttribute("aria-expanded", "false");
  updateControls();
}

/** 底部操作层只控制展示，不创建授权或执行请求。 */
function setConfirmationOpen(open) {
  if (!pendingOperation) return;
  confirmationRail.classList.toggle("is-open", open);
  elements["confirmation-dock"].setAttribute("aria-expanded", String(open));
  if (open) {
    confirmationRail.querySelector(".confirmation-scroll").scrollTop = 0;
    focusCurrentOperation();
  }
  else elements["confirmation-dock"].focus({ preventScroll: true });
}

function focusCurrentOperation() {
  const heading = elements["confirmation-details"].querySelector("h3");
  if (!heading) return;
  heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}

function focusAfterRequest() {
  if (pendingOperation && window.matchMedia("(max-width: 900px)").matches) focusCurrentOperation();
  else elements["message-input"].focus({ preventScroll: true });
}

function appendOperationSummary(parent, operation, tier) {
  const heading = createTextElement("div", "operation-heading");
  heading.append(createTextElement("h3", "", intentLabels[operation.intent] || "核对本次操作"));
  appendOperationTier(heading, tier);
  parent.append(heading);
  const target = operation.target_name || operation.service?.name || operation.params?.subscription_name || operation.params?.contact_name || operation.params?.budget_id || operation.params?.card_id;
  if (target) parent.append(createTextElement("p", "operation-target", target));
  const amount = operation.amount_cents ?? operation.params?.amount_cents ?? operation.service?.price_cents;
  if (Number.isSafeInteger(amount)) parent.append(createTextElement("p", "operation-amount", formatMoney(amount)));
  else if (Number.isSafeInteger(operation.params?.daily_limit_cents)) {
    parent.append(createTextElement("p", "result-label", "拟调整日限额"), createTextElement("p", "operation-amount", formatMoney(operation.params.daily_limit_cents)));
  }
  const summary = [];
  for (const key of ["account_id", "budget_id", "card_id", "event_date", "start_date", "end_date"]) {
    if (Object.hasOwn(operation.params || {}, key)) summary.push([key, operation.params[key]]);
  }
  if (operation.target_account_id) summary.push(["target_account_id", operation.target_account_id]);
  if (summary.length) {
    const overview = createTextElement("div", "operation-overview");
    appendDetailList(overview, summary);
    parent.append(overview);
  }
  const facts = [];
  appendOperationHighlights(facts, operation);
  const visibleFacts = facts.filter(([key]) => key !== "service_price_cents" || !Number.isSafeInteger(amount));
  if (visibleFacts.length) appendDetailList(parent, visibleFacts);
  if (operation.impact) parent.append(createTextElement("p", "confirmation-impact", operation.impact));
}

/** 非待确认回执只展示真实拒绝/失败原因，不提供可执行确认入口。 */
function renderOperationOutcome(response) {
  if (!["rejected", "failed", "expired"].includes(response.status) || response.reason === "clarification") return;
  elements["confirmation-empty"].hidden = true;
  elements["confirmation-active"].hidden = false;
  elements["confirm-button"].hidden = true;
  elements["cancel-button"].hidden = true;
  elements["confirmation-code"].parentElement.hidden = true;
  confirmationRail.classList.add("has-outcome");
  const details = elements["confirmation-details"];
  details.append(createTextElement("h3", "operation-heading", intentLabels[response.intent] || "本次请求"), createStatusBadge(response.status));
  if (response.tier) appendOperationTier(details, response.tier);
  details.append(createTextElement("p", "operation-reason", response.message || "本次办理已停止，请核对回执后再提出需求。"));
  appendTechnicalDetails(details, { request_id: response.request_id, reason: response.reason, intent: response.intent }, "技术详情 · 拒绝或失败依据");
}

/** 黄档通过固定确认入口；红档只展示和取消，强验证留在本机专用入口。 */
function renderPending(response) {
  clearPending();
  const operation = response.operation;
  const expiry = Date.parse(response.expires_at);
  const completeOperation = operation && operation.simulated === true && operation.user_id === session?.user_id
    && Object.hasOwn(intentLabels, operation.intent) && operation.intent !== "unknown"
    && operation.intent === response.intent
    && operation.params && typeof operation.params === "object" && !Array.isArray(operation.params)
    && typeof operation.impact === "string" && operation.impact.length > 0;
  const yellowConfirmation = response.tier === "yellow" && typeof response.confirmation_code === "string"
    && /^\d{6}$/.test(response.confirmation_code);
  const redTransfer = completeOperation && response.tier === "red" && operation.intent === "transfer"
    && !Object.hasOwn(response, "confirmation_code")
    && typeof operation.params.account_id === "string" && operation.params.account_id.length > 0
    && Number.isSafeInteger(operation.params.amount_cents) && operation.params.amount_cents > 0
    && operation.amount_cents === operation.params.amount_cents
    && typeof operation.target_name === "string" && operation.target_name.length > 0
    && typeof operation.target_account_id === "string" && operation.target_account_id.length > 0
    && Number.isSafeInteger(operation.daily_outgoing_after_cents) && operation.daily_outgoing_after_cents > 100000;
  const redNewOperation = completeOperation && response.tier === "red"
    && ["reserve_budget", "place_order", "purchase_investment", "redeem_investment", "report_card_lost", "restore_card"].includes(operation.intent)
    && !Object.hasOwn(response, "confirmation_code");
  const redVerification = redTransfer || redNewOperation;
  if (!completeOperation || (!yellowConfirmation && !redVerification) || typeof response.request_id !== "string" || !response.request_id.length || !Number.isFinite(expiry)) {
    appendLocalNotice("待处理回执的目标、档位、有效期或确认信息不完整，页面已停止办理。请重新提出需求。");
    return;
  }
  pendingOperation = {
    requestId: response.request_id,
    tier: response.tier,
    confirmationCode: yellowConfirmation ? response.confirmation_code : null,
    expiresAt: expiry,
    operation: safeDetails(operation),
  };
  elements["confirmation-empty"].hidden = true;
  elements["confirmation-active"].hidden = false;
  const details = elements["confirmation-details"];
  appendOperationSummary(details, operation, response.tier);
  details.append(createTextElement("p", "operation-reason", redVerification
    ? "当前红档业务拒绝执行。你可以取消此请求，普通确认不能改变权限档位。"
    : "代码判定本次操作需要你的明确授权；核对对象与影响后，确认仅对本次操作有效。"));
  const draftWarning = createTextElement("p", "operation-reason operation-draft-warning", "你正在编辑新的需求。请发送后重新核对，或清空输入后继续当前操作。");
  draftWarning.hidden = true;
  details.append(draftWarning);
  const technical = createTextElement("details", "safe-details operation-technical");
  technical.append(createTextElement("summary", "", "核对完整参数与请求编号"));
  const fields = [["user_id", operation.user_id], ["tier", response.tier]];
  if (operation.target_name) fields.push([operation.intent === "transfer" ? "contact_name" : operation.intent === "cancel_subscription" ? "subscription_name" : "target_name", operation.target_name]);
  if (operation.params && typeof operation.params === "object") {
    for (const [key, value] of Object.entries(safeDetails(operation.params))) fields.push([key, value]);
  }
  appendOperationHighlights(fields, operation);
  for (const [key, value] of Object.entries(safeDetails(operation))) {
    if (!["params", "user_id", "intent", "simulated", "impact", "target_name"].includes(key) && !isOperationFactGroup(key, value) && !fields.some(([field]) => field === key)) fields.push([key, value]);
  }
  fields.push(["request_id", response.request_id]);
  appendDetailList(technical, fields);
  appendOperationFactGroups(technical, operation);
  details.append(technical);
  elements["confirmation-code"].parentElement.hidden = redVerification;
  elements["confirm-button"].hidden = redVerification;
  if (redVerification) {
    if (redTransfer) {
      technical.append(createTextElement("p", "confirmation-impact", "本机入口：scripts/mfa_verify.py，步骤见项目中的《手机验证操作说明.md》。请先取消此网页请求，再在本机入口重新创建并核对操作；网页请求编号不能跨会话复用。"));
      technical.append(createTextElement("p", "confirmation-impact", "即使两种身份因素验证通过，当前红档业务仍会拒绝。请勿把密码、认证器秘密或动态码粘贴到聊天或网页。"));
    }
  } else {
    // 屏显码只用于黄档确认，永不进入回执历史或浏览器存储，也不是MFA。
    elements["confirmation-code"].textContent = response.confirmation_code;
  }
  confirmationRail.classList.add("has-operation", "is-open");
  confirmationRail.querySelector(".confirmation-scroll").scrollTop = 0;
  elements["confirmation-dock"].hidden = false;
  elements["confirmation-dock"].textContent = redVerification ? "红档不可执行 · 查看本次操作" : "待你确认 · 查看本次操作";
  elements["confirmation-dock"].setAttribute("aria-expanded", "true");
  function updateExpiry() {
    if (!pendingOperation) return;
    const seconds = Math.max(0, Math.ceil((pendingOperation.expiresAt - Date.now()) / 1000));
    elements["confirmation-expiry"].textContent = `有效至 ${formatTime(response.expires_at)}（北京时间）；剩余 ${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒`;
    if (seconds === 0) {
      clearPending();
      appendLocalNotice("本次待处理操作已超过有效期，页面已清除授权信息。需要办理时请重新提出需求；后端仍会复查有效期。");
    }
  }
  updateExpiry();
  if (pendingOperation) expiryTimer = window.setInterval(updateExpiry, 1000);
  updateControls();
}

function renderPlan(plan, planId) {
  if (!plan || !Array.isArray(plan.steps) || !plan.steps.length) return;
  currentPlan = { ...plan, plan_id: plan.plan_id || planId };
  elements["plan-panel"].hidden = false;
  const completedCount = plan.steps.filter(step => step.status === "success").length;
  elements["plan-status"].textContent = `${statusLabels[plan.status] || displayText(plan.status)} · 已完成 ${completedCount}/${plan.steps.length} 步`;
  elements["plan-steps"].replaceChildren();
  const stepPositions = new Map(plan.steps.map((step, index) => [step.id, index + 1]));
  for (const [index, step] of plan.steps.entries()) {
    const safeStatus = Object.hasOwn(statusLabels, step.status) ? step.status : "unknown";
    const item = createTextElement("li", `plan-step state-${safeStatus}`);
    const number = createTextElement("span", "plan-step-number", step.status === "success" ? "✓" : String(index + 1));
    number.setAttribute("aria-hidden", "true");
    const body = createTextElement("div", "plan-step-body");
    const line = createTextElement("div", "plan-step-line");
    line.append(createTextElement("strong", "", intentLabels[step.intent] || step.intent), createStatusBadge(step.status));
    const dependencies = Array.isArray(step.depends_on) ? step.depends_on : [];
    const dependencyText = dependencies.length ? `前置：步骤 ${dependencies.map(identifier => stepPositions.get(identifier) || displayText(identifier)).join("、")}` : "无前置步骤";
    body.append(line, createTextElement("p", "plan-step-detail", dependencyText));
    let actor = "尚未执行";
    if (step.status === "success") actor = "系统已返回工具结果";
    else if (["pending", "waiting_confirmation"].includes(step.status)) actor = "代码要求用户确认 · 当前尚未执行";
    else if (step.status === "running") actor = "系统正在执行";
    else if (step.status === "rejected") actor = "代码已拒绝本步";
    else if (step.status === "human_takeover") actor = "已转入本地人工接管";
    else if (["failed", "interrupted", "cancelled", "expired", "blocked"].includes(step.status)) actor = "执行已停止 · 请核对回执";
    body.append(createTextElement("p", "plan-step-actor", actor));
    if (step.reason) body.append(createTextElement("p", "plan-step-detail", step.reason));
    item.append(number, body);
    elements["plan-steps"].append(item);
  }
  elements["plan-policy"].textContent = displayText(plan.rollback_policy || "中断或接管停止未完成步骤，已成功业务不会自动撤回。");
  elements["plan-panel"].querySelector(".plan-technical")?.remove();
  const technical = appendTechnicalDetails(elements["plan-panel"], {
    plan_id: currentPlan.plan_id, status: plan.status,
    steps: plan.steps.map(step => ({ id: step.id, intent: step.intent, status: step.status, depends_on: step.depends_on, request_id: step.request_id, params: step.params || step.input_params })),
  }, "技术详情 · 步骤依赖与参数");
  technical.classList.add("plan-technical");
  updateControls();
}

function consumeResponse(response, reviewedOperation = null) {
  appendReceipt(response, reviewedOperation);
  if (response.plan) renderPlan(response.plan, response.plan_id);
  if (response.status === "pending") renderPending(response);
  else { clearPending(); renderOperationOutcome(response); }
}

function updateControls() {
  const available = Boolean(session) && !busy && !pageLeaving;
  elements["send-button"].disabled = !available || !elements["message-input"].value.trim();
  elements["message-input"].disabled = !available;
  elements["audit-button"].disabled = !available;
  elements["history-button"].disabled = !available;
  for (const control of document.querySelectorAll("#history-dialog button:not(#close-history-button), #history-dialog textarea, #history-dialog select")) control.disabled = !available;
  const editingNewDemand = Boolean(pendingOperation && elements["message-input"].value.trim());
  elements["confirm-button"].disabled = !available || !pendingOperation || pendingOperation.tier !== "yellow" || pendingOperation.expiresAt <= Date.now() || editingNewDemand;
  elements["cancel-button"].disabled = !available || !pendingOperation;
  const draftWarning = elements["confirmation-details"].querySelector(".operation-draft-warning");
  if (draftWarning) draftWarning.hidden = !editingNewDemand;
  elements["confirmation-dock"].disabled = !pendingOperation;
  for (const button of document.querySelectorAll(".example-button")) button.disabled = busy || pageLeaving;
  const activePlan = currentPlan && ["ready", "waiting_confirmation"].includes(currentPlan.status);
  elements["resume-button"].hidden = !currentPlan || currentPlan.status !== "ready" || Boolean(pendingOperation);
  elements["interrupt-button"].hidden = !activePlan;
  elements["takeover-button"].hidden = !activePlan;
  for (const identifier of ["resume-button", "interrupt-button", "takeover-button"]) elements[identifier].disabled = !available;
  elements["send-label"].textContent = busy ? "处理中" : "发送";
  elements["activity-status"].textContent = busy ? "正在处理，请稍候…" : "";
}

function setBusy(value) {
  busy = value;
  elements["message-form"].setAttribute("aria-busy", String(value));
  updateControls();
}

/** 不自动重试写操作：失去回执时不能推断是否已经成功。 */
async function requestApi(path, payload) {
  const abortController = new AbortController();
  const timeout = window.setTimeout(() => abortController.abort(), 120000);
  try {
    const response = await fetch(path, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
      body: JSON.stringify(payload), signal: abortController.signal,
    });
    const result = await response.json();
    if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("invalid_response");
    if (!response.ok) {
      if (response.status === 403) {
        session = null;
        showConnectionNotice("本机会话验证失败，请重新连接后再提出需求。", true);
      }
      if (typeof result.status === "string") return result;
      throw new Error("http_failure");
    }
    return result;
  } finally {
    window.clearTimeout(timeout);
  }
}

function reportConnectionFailure() {
  clearPending();
  appendLocalNotice("连接中断或回执格式异常，本次处理结果暂不确定。请查看审计记录核对后，再决定是否重新提出需求；页面不会自动重试。");
}

async function submitMessage(event) {
  event.preventDefault();
  const text = elements["message-input"].value.trim();
  if (!session || busy || !text) return;
  clearRecoveryReview();
  clearPending();
  currentPlan = null;
  elements["plan-panel"].hidden = true;
  appendUserMessage(text);
  elements["message-input"].value = "";
  setBusy(true);
  try {
    consumeResponse(await requestApi("/api/message", { text }));
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
    focusAfterRequest();
  }
}

async function confirmCurrentOperation() {
  if (!session || busy || !pendingOperation || pendingOperation.tier !== "yellow" || pendingOperation.expiresAt <= Date.now() || elements["message-input"].value.trim()) return;
  const request = pendingOperation;
  clearPending();
  setBusy(true);
  try {
    const response = await requestApi("/api/confirm", { request_id: request.requestId, confirmation_code: request.confirmationCode });
    const matchingReceipt = response.status === "success" && response.request_id === request.requestId && response.intent === request.operation.intent;
    consumeResponse(response, matchingReceipt ? request.operation : null);
    await refreshCurrentPlan();
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
    focusAfterRequest();
  }
}

async function cancelCurrentOperation() {
  if (!session || busy || !pendingOperation) return;
  const requestId = pendingOperation.requestId;
  clearPending();
  setBusy(true);
  try {
    consumeResponse(await requestApi("/api/cancel", { request_id: requestId }));
    await refreshCurrentPlan();
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
    elements["message-input"].focus();
  }
}

/** 只读已保存的节点结果，确认完成不会自动推进下一步。 */
async function refreshCurrentPlan() {
  if (!currentPlan?.plan_id) return;
  const response = await requestApi("/api/plan/get", { plan_id: currentPlan.plan_id });
  if (response.status === "success" && response.plan) renderPlan(response.plan, response.plan_id);
}

async function controlPlan(action) {
  if (!session || busy || !currentPlan || typeof currentPlan.plan_id !== "string") return;
  const planId = currentPlan.plan_id;
  if (action !== "resume") { clearPending(); clearRecoveryReview(); }
  setBusy(true);
  try {
    consumeResponse(await requestApi(`/api/plan/${action}`, { plan_id: planId }));
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
  }
}

/** 审计仅展示公开脱敏字段；没有更改、清空、秘密导出入口。 */
function renderAudit(events) {
  elements["audit-content"].replaceChildren();
  if (!Array.isArray(events)) {
    elements["audit-content"].append(createTextElement("p", "", "没有收到有效的审计记录。"));
    return;
  }
  elements["audit-content"].append(createTextElement("p", "audit-summary", `本次返回 ${events.length} 条记录，最新记录在前。`));
  if (!events.length) elements["audit-content"].append(createTextElement("p", "", "当前没有可展示的审计记录。"));
  const allowedFields = ["timestamp", "user_id", "request_id", "step_id", "intent", "tier", "event", "result", "reason", "raw_input_redacted", "params_redacted"];
  for (const event of events.slice().reverse()) {
    const record = createTextElement("details", "audit-record");
    record.append(createTextElement("summary", "", `#${event.id ?? "—"} · ${formatTime(event.timestamp)} · ${auditEventLabels[event.event] || event.event} · ${statusLabels[event.result] || event.result}`));
    appendDetailList(record, allowedFields.filter(key => Object.hasOwn(event, key)).map(key => [key, event[key]]));
    elements["audit-content"].append(record);
  }
}

async function openAudit() {
  if (!session || busy) return;
  elements["audit-content"].replaceChildren(createTextElement("p", "", "正在读取实际审计记录…"));
  elements["audit-dialog"].showModal();
  setBusy(true);
  try {
    const response = await requestApi("/api/audit", {});
    if (response.status === "success") renderAudit(response.data);
    else elements["audit-content"].replaceChildren(createTextElement("p", "", response.message || "审计记录暂不可用。"));
  } catch {
    elements["audit-content"].replaceChildren(createTextElement("p", "", "无法取得审计回执，请检查本机服务是否仍在运行。"));
  } finally {
    setBusy(false);
  }
}

function showConnectionNotice(message, allowReconnect = false) {
  elements["connection-notice"].hidden = false;
  elements["connection-message"].textContent = message;
  elements["reconnect-button"].hidden = !allowReconnect;
}

async function connectSession() {
  elements["reconnect-button"].disabled = true;
  try {
    const response = await fetch("/api/session", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error("session_failure");
    const result = await response.json();
    if (typeof result.user_id !== "string" || typeof result.csrf_token !== "string" || result.simulated !== true) throw new Error("invalid_session");
    session = { user_id: result.user_id, csrf_token: result.csrf_token };
    elements["session-user"].textContent = displayText(result.user_id);
    if (result.model_configured) elements["connection-notice"].hidden = true;
    else showConnectionNotice("本机尚未读取到模型配置。自然语言任务可能无法处理；配置状态不代表真实模型已接通。");
  } catch {
    session = null;
    showConnectionNotice("无法连接本机服务，请确认启动窗口仍在运行。", true);
  } finally {
    elements["reconnect-button"].disabled = false;
    updateControls();
  }
}

elements["message-form"].addEventListener("submit", submitMessage);
elements["message-input"].addEventListener("input", updateControls);
elements["message-input"].addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!elements["send-button"].disabled) elements["message-form"].requestSubmit();
  }
});
for (const button of document.querySelectorAll(".example-button")) {
  button.addEventListener("click", () => {
    if (busy) return;
    for (const otherButton of document.querySelectorAll(".example-button")) otherButton.classList.toggle("selected", otherButton === button);
    elements["message-input"].value = button.dataset.example;
    updateControls();
    elements["message-input"].focus();
  });
}
elements["confirmation-dock"].addEventListener("click", () => setConfirmationOpen(true));
elements["confirmation-close"].addEventListener("click", () => setConfirmationOpen(false));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && pendingOperation && confirmationRail.classList.contains("is-open")
      && window.matchMedia("(max-width: 900px)").matches && !document.querySelector("dialog[open]")) {
    event.preventDefault();
    setConfirmationOpen(false);
  }
});
elements["confirm-button"].addEventListener("click", confirmCurrentOperation);
elements["cancel-button"].addEventListener("click", cancelCurrentOperation);
elements["audit-button"].addEventListener("click", openAudit);
elements["close-audit-button"].addEventListener("click", () => elements["audit-dialog"].close());
elements["reconnect-button"].addEventListener("click", connectSession);
elements["resume-button"].addEventListener("click", () => controlPlan("resume"));
elements["interrupt-button"].addEventListener("click", () => controlPlan("interrupt"));
elements["takeover-button"].addEventListener("click", () => controlPlan("takeover"));

// 离开页面尽力撤销本人等待授权。突然终止时仍以服务端有效期为准。
window.addEventListener("pagehide", () => {
  pageLeaving = true;
  if (session && pendingOperation) {
    fetch("/api/cancel", {
      method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
      body: JSON.stringify({ request_id: pendingOperation.requestId }),
    }).catch(() => {});
  }
  clearPending();
  clearRecoveryReview();
});
window.addEventListener("pageshow", event => {
  if (event.persisted) {
    pageLeaving = false;
    clearPending();
    currentPlan = null;
    elements["plan-panel"].hidden = true;
    connectSession();
  }
});
connectSession();

const recoveryLabels = { none: "本会话任务", required: "须重新核对", review_pending: "恢复前待核对", authorized: "本轮恢复已同意", blocked: "不可从历史恢复", corrupt: "记录损坏，已隔离" };
const stopReasonLabels = { session_restarted: "会话重启，旧授权已失效", session_closed: "会话已结束", user_interrupted: "本人中断任务", user_cancelled: "本人已取消", superseded_by_new_task: "已改办新任务", dependency_failed: "前置步骤未成功", audit_unavailable: "审计暂不可用", expired: "授权已到期", human_takeover: "已转入本地接管登记" };
const savedPlans = new Map();
let recoveryReview = null;

function clearRecoveryReview() {
  recoveryReview = null;
  elements["recovery-review"].replaceChildren();
  elements["recovery-review"].hidden = true;
}

function historyButton(label, action) {
  const button = createTextElement("button", "button button-secondary", label);
  button.type = "button";
  button.addEventListener("click", () => runHistoryAction(action));
  return button;
}

async function runHistoryAction(action) {
  if (!session || busy) return;
  setBusy(true);
  elements["history-message"].textContent = "正在读取或保存，请稍候…";
  try {
    await action();
  } catch {
    clearRecoveryReview();
    elements["history-message"].textContent = "未取得可靠回执。请先刷新历史与审计，页面不会自动重试。";
  } finally {
    setBusy(false);
  }
}

function showHistoryMessage(response, fallback = "已取得当前保存记录。") {
  elements["history-message"].textContent = displayText(response?.message || fallback);
}

function appendSavedEffects(parent, record) {
  parent.append(createTextElement("p", "muted", "以下是已保存的历史事实，没有重新执行查询或金融操作。"));
  if (Array.isArray(record.steps)) {
    const list = createTextElement("ol", "");
    for (const step of record.steps) {
      const item = createTextElement("li", "", `${intentLabels[step.intent] || step.intent} · ${statusLabels[step.status] || step.status}`);
      if (step.reason) item.append(createTextElement("p", "muted", step.reason));
      if (step.status === "success" && (step.result || step.data)) renderToolResult(item, step.intent, step.result || step.data);
      list.append(item);
    }
    parent.append(list);
  }
  for (const [name, title] of [["committed_effects", "已提交的结果"], ["manual_actions", "仍需人工处理"]]) {
    if (!Array.isArray(record[name]) || !record[name].length) continue;
    parent.append(createTextElement("h4", "", title));
    for (const item of record[name]) {
      if (typeof item === "string") parent.append(createTextElement("p", "", item));
      else if (item && typeof item === "object") appendDetailList(parent, Object.entries(safeDetails(item)));
    }
  }
}

function renderSavedPlan(plan) {
  savedPlans.set(plan.plan_id, plan);
  const card = createTextElement("article", "history-card");
  card.dataset.planId = plan.plan_id;
  card.append(createTextElement("h4", "", `${statusLabels[plan.status] || plan.status} · ${recoveryLabels[plan.recovery_status] || "历史任务"}`));
  appendTechnicalDetails(card, { plan_id: plan.plan_id }, "技术详情 · 任务编号");
  if (plan.updated_at) card.append(createTextElement("p", "muted", `保存于 ${formatTime(plan.updated_at)}`));
  if (plan.stop_reason) card.append(createTextElement("p", "", `停止原因：${stopReasonLabels[plan.stop_reason] || plan.stop_reason}`));
  appendSavedEffects(card, plan);
  const actions = createTextElement("div", "history-actions");
  actions.append(historyButton("查看详情", async () => {
    const response = await requestApi("/api/plan/get", { plan_id: plan.plan_id });
    showHistoryMessage(response);
    if (response.status === "success" && response.plan) card.replaceWith(renderSavedPlan(response.plan));
  }));
  if (["required", "review_pending"].includes(plan.recovery_status)) {
    actions.append(historyButton("重新核对恢复内容", async () => {
      clearPending();
      const response = await requestApi("/api/plan/recovery/prepare", { plan_id: plan.plan_id });
      showHistoryMessage(response);
      if (response.status === "pending") renderRecoveryReview(response);
      else clearRecoveryReview();
    }));
  }
  if (plan.recovery_status === "authorized" || (plan.recovery_status === "none" && ["ready", "waiting_confirmation"].includes(plan.status))) {
    actions.append(historyButton("继续办理", async () => {
      clearRecoveryReview();
      const response = await requestApi("/api/plan/resume", { plan_id: plan.plan_id });
      showHistoryMessage(response);
      consumeResponse(response);
      if (response.status === "pending") elements["history-dialog"].close();
      else await loadSavedWork();
    }));
  }
  if (plan.status !== "success" && plan.recovery_status !== "corrupt" && plan.status !== "human_takeover") {
    actions.append(historyButton("登记人工接管", async () => {
      clearPending(); clearRecoveryReview();
      const response = await requestApi("/api/plan/takeover", { plan_id: plan.plan_id });
      showHistoryMessage(response);
      if (response.plan) renderPlan(response.plan, plan.plan_id);
      await loadSavedWork();
    }));
  }
  card.append(actions);
  return card;
}

function renderRecoveryReview(response) {
  clearRecoveryReview();
  const operation = response.operation;
  if (!operation || operation.user_id !== session?.user_id || typeof response.review_id !== "string"
      || !/^[0-9]{6}$/.test(response.recovery_code || "") || !Array.isArray(operation.operations)
      || !Number.isFinite(Date.parse(response.expires_at))) {
    elements["history-message"].textContent = "恢复回执不完整，未显示同意控件。请刷新后核对。";
    return;
  }
  recoveryReview = { id: response.review_id, code: response.recovery_code, expiresAt: Date.parse(response.expires_at) };
  const panel = elements["recovery-review"];
  panel.hidden = false;
  panel.append(createTextElement("h3", "", "请核对本轮恢复内容"));
  panel.append(createTextElement("p", "", "同意恢复只保存本轮办理许可。之后还须点击继续办理，黄档操作仍须逐项确认。"));
  const stepNames = identifiers => (identifiers || []).map(identifier => {
    const step = savedPlans.get(operation.plan_id)?.steps?.find(item => item.id === identifier);
    return step ? (intentLabels[step.intent] || "已保存步骤") : "已保存步骤";
  }).join("、") || "无";
  panel.append(createTextElement("p", "", `已完成：${stepNames(operation.completed_steps)}；剩余：${stepNames(operation.remaining_steps)}`));
  for (const item of operation.operations) {
    panel.append(createTextElement("h4", "", intentLabels[item.intent] || item.intent));
    const fields = Object.entries(safeDetails(item.params || {}));
    appendOperationHighlights(fields, item);
    for (const [key, value] of Object.entries(safeDetails(item))) {
      if (!["params", "user_id", "intent", "simulated"].includes(key) && !isOperationFactGroup(key, value) && !fields.some(([field]) => field === key)) fields.push([key, value]);
    }
    appendDetailList(panel, fields);
    appendOperationFactGroups(panel, item);
  }
  appendSavedEffects(panel, operation);
  panel.append(createTextElement("p", "confirmation-expiry", `本轮同意有效至 ${formatTime(response.expires_at)}（北京时间）`));
  panel.append(historyButton("明确同意本轮恢复", async () => {
    const review = recoveryReview;
    if (!review || review.expiresAt <= Date.now()) {
      clearRecoveryReview();
      elements["history-message"].textContent = "本轮恢复核对已到期，请重新核对。";
      return;
    }
    clearRecoveryReview();
    const result = await requestApi("/api/plan/recovery/confirm", { review_id: review.id, recovery_code: review.code });
    showHistoryMessage(result, "本轮恢复同意已保存。请点击继续办理，再逐项核对黄档操作。");
    await loadSavedWork();
  }));
}

function renderHandover(item) {
  const card = createTextElement("article", "history-card");
  card.append(createTextElement("h4", "", item.status === "closed_record" ? "本地登记已关闭" : "待本地处置登记"));
  appendTechnicalDetails(card, { handover_id: item.handover_id, plan_id: item.plan_id }, "技术详情 · 接管事项编号");
  card.append(historyButton("查看事项详情", async () => {
    const response = await requestApi("/api/handover/get", { handover_id: item.handover_id });
    showHistoryMessage(response);
    if (response.status === "success" && response.data?.handover) card.replaceWith(renderHandover(response.data.handover));
  }));
  appendSavedEffects(card, item);
  for (const entry of item.entries || []) {
    card.append(createTextElement("p", "", `${formatTime(entry.recorded_at)} · ${entry.actor_user_id}（任务所有者） · ${entry.compensation === "manual_follow_up" ? "仍需人工另行处理" : "登记无需补偿"}`));
    if (entry.note_redacted) card.append(createTextElement("p", "muted", entry.note_redacted));
  }
  if (item.status === "open") {
    const label = createTextElement("label", "", "处置备注（可选，勿填密码或验证码）");
    const note = document.createElement("textarea"); note.maxLength = 500; label.append(note); card.append(label);
    const choiceLabel = createTextElement("label", "", "补偿事项登记");
    const choice = document.createElement("select");
    for (const [value, text] of [["manual_follow_up", "仍需人工另行处理"], ["no_compensation_needed", "登记无需补偿"]]) {
      const option = createTextElement("option", "", text); option.value = value; choice.append(option);
    }
    choiceLabel.append(choice); card.append(choiceLabel);
    const actions = createTextElement("div", "history-actions");
    for (const [disposition, labelText] of [["record", "保存处置记录"], ["close_record", "关闭本地登记"]]) {
      actions.append(historyButton(labelText, async () => {
        const response = await requestApi("/api/handover/record", { handover_id: item.handover_id, disposition, compensation: choice.value, note: note.value });
        showHistoryMessage(response);
        await loadSavedWork();
      }));
    }
    card.append(actions);
  }
  return card;
}

async function loadSavedWork() {
  const plans = await requestApi("/api/plan/list", {});
  const handovers = await requestApi("/api/handover/list", {});
  elements["history-plans"].replaceChildren(); elements["history-handovers"].replaceChildren();
  if (plans.status !== "success" || handovers.status !== "success") {
    showHistoryMessage(plans.status !== "success" ? plans : handovers, "历史记录暂不可用。");
    return;
  }
  const planItems = plans.data?.plans || [];
  const handoverItems = handovers.data?.handovers || [];
  for (const plan of planItems) elements["history-plans"].append(renderSavedPlan(plan));
  for (const item of handoverItems) elements["history-handovers"].append(renderHandover(item));
  if (!planItems.length) elements["history-plans"].append(createTextElement("p", "muted", "尚无已保存的任务计划。"));
  if (!handoverItems.length) elements["history-handovers"].append(createTextElement("p", "muted", "尚无本地接管事项。"));
}

elements["history-button"].addEventListener("click", () => {
  if (!session || busy) return;
  elements["history-dialog"].showModal();
  runHistoryAction(async () => { await loadSavedWork(); elements["history-message"].textContent = "已读取保存记录；查看不会自动办理。"; });
});
elements["refresh-history-button"].addEventListener("click", () => runHistoryAction(loadSavedWork));
elements["cancel-session-work-button"].addEventListener("click", () => runHistoryAction(async () => {
  clearPending(); clearRecoveryReview();
  const response = await requestApi("/api/cancel", {});
  showHistoryMessage(response);
  if (response.plan) renderPlan(response.plan, response.plan_id);
  else await refreshCurrentPlan();
  await loadSavedWork();
}));
elements["close-history-button"].addEventListener("click", () => elements["history-dialog"].close());
elements["history-dialog"].addEventListener("close", clearRecoveryReview);

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
].map(identifier => [identifier, document.getElementById(identifier)]));

const intentLabels = {
  query_balance: "账户余额", query_transactions: "交易流水", analyze_bills: "账单分析",
  query_subscriptions: "订阅与代扣", cancel_subscription: "取消模拟订阅", transfer: "模拟转账",
  unknown: "处理回执",
};
const statusLabels = {
  success: "已完成", pending: "等待确认", rejected: "已拒绝", failed: "处理失败",
  cancelled: "已取消", expired: "已到期", interrupted: "已中断", human_takeover: "人工接管",
  not_started: "未开始", ready: "可继续", waiting_confirmation: "等待确认",
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
};
const tierLabels = { green: "绿档", yellow: "黄档", red: "红档", none: "未授权" };
const subscriptionStatusLabels = { active: "安排中", cancelled: "已取消" };
const auditEventLabels = {
  received: "收到请求", classified: "代码判档", waiting_confirmation: "等待确认",
  confirmed: "确认通过", executed: "业务完成", rejected: "拒绝", failed: "失败",
  cancelled: "取消", expired: "到期", restart: "会话启动", audit_read: "查看审计",
  verification_failed: "验证失败", locked: "操作锁定", unlocked: "锁定解除",
  plan_accepted: "接收候选计划", step_started: "步骤开始", step_completed: "步骤完成",
  interrupted: "计划中断", human_takeover: "人工接管",
};

let session = null;
let busy = false;
let pendingOperation = null;
let currentPlan = null;
let expiryTimer = null;
let pageLeaving = false;
const displayedPlanResults = new Set();

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
      if (/secret|password|token|api.?key|confirm.*code|authenticator/i.test(key)) continue;
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
  if (key === "event") return auditEventLabels[value] || displayText(value);
  if (key === "status" || key === "result") return statusLabels[value] || subscriptionStatusLabels[value] || displayText(value);
  if (key === "timestamp") return formatTime(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(safeDetails(value)) : displayText(value);
}

function appendDetailList(parent, fields) {
  const list = createTextElement("dl", "detail-list");
  for (const [key, value] of fields) {
    const row = createTextElement("div", "detail-row");
    row.append(createTextElement("dt", "", fieldLabels[key] || key), createTextElement("dd", "", fieldValue(key, value)));
    list.append(row);
  }
  parent.append(list);
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
    for (const value of values) row.append(createTextElement("td", "", value));
    body.append(row);
  }
  table.append(header, body);
  wrapper.append(table);
  parent.append(wrapper);
}

/** 只展示工具实际回传的数据，区分实际支出和未来安排。 */
function renderToolResult(parent, intent, data) {
  if (!data || typeof data !== "object") return;
  const result = createTextElement("div", "tool-result");
  if (intent === "analyze_bills" && Number.isSafeInteger(data.actual_expense_cents)) {
    result.append(createTextElement("p", "result-label", "已发生的实际支出"), createTextElement("p", "result-total", formatMoney(data.actual_expense_cents)));
    if (data.start_date || data.end_date) result.append(createTextElement("p", "result-note", `${data.start_date || "—"} 至 ${data.end_date || "—"}`));
    if (data.categories && typeof data.categories === "object") {
      appendTable(result, ["支出类别", "金额"], Object.entries(data.categories).map(([category, amount]) => [category, formatMoney(amount)]));
    }
  } else if (intent === "query_balance" && Array.isArray(data.accounts)) {
    if (!data.accounts.length) result.append(createTextElement("p", "", "未找到本人账户记录。"));
    else appendTable(result, ["模拟账户", "余额"], data.accounts.map(account => [account.account_id, formatMoney(account.balance_cents)]));
  } else if (intent === "query_subscriptions" && Array.isArray(data.subscriptions)) {
    if (!data.subscriptions.length) result.append(createTextElement("p", "", "未找到本人订阅记录。"));
    else appendTable(result, ["模拟订阅", "每期金额", "状态"], data.subscriptions.map(subscription => [subscription.name, formatMoney(subscription.amount_cents), subscriptionStatusLabels[subscription.status] || subscription.status]));
    if (Number.isSafeInteger(data.future_expected_cents)) {
      result.append(createTextElement("p", "result-label result-note", "未来一个续费周期的预计支出"), createTextElement("p", "result-total", formatMoney(data.future_expected_cents)));
    }
  } else if (intent === "query_transactions" && Array.isArray(data.transactions)) {
    if (!data.transactions.length) result.append(createTextElement("p", "", "当前范围未找到交易记录。"));
    else appendTable(result, ["时间 / 类别", "金额", "状态"], data.transactions.map(transaction => [`${formatTime(transaction.occurred_at)}\n${transaction.category || transaction.kind || ""}`, formatMoney(transaction.amount_cents), statusLabels[transaction.status] || transaction.status]));
  } else if (intent === "transfer") {
    if (Number.isSafeInteger(data.amount_cents)) result.append(createTextElement("p", "result-label", "本次模拟转账"), createTextElement("p", "result-total", formatMoney(data.amount_cents)));
    appendDetailList(result, ["source_account_id", "target_account_id", "daily_outgoing_cents"].filter(key => Object.hasOwn(data, key)).map(key => [key, data[key]]));
  } else if (intent === "cancel_subscription") {
    appendDetailList(result, ["subscription_id", "status", "history_preserved"].filter(key => Object.hasOwn(data, key)).map(key => [key, data[key]]));
  } else {
    const details = createTextElement("details", "safe-details");
    details.append(createTextElement("summary", "", "查看实际返回数据"), createTextElement("pre", "", JSON.stringify(safeDetails(data), null, 2)));
    result.append(details);
  }
  if (data.basis) result.append(createTextElement("p", "result-note", data.basis));
  parent.append(result);
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
function appendReceipt(response) {
  showConversation();
  const article = createTextElement("article", "message receipt");
  const heading = createTextElement("div", "receipt-heading");
  heading.append(createTextElement("h3", "", intentLabels[response.intent] || "处理回执"));
  heading.append(createTextElement("span", `receipt-state ${Object.hasOwn(statusLabels, response.status) ? response.status : ""}`, statusLabels[response.status] || response.status || "未知状态"));
  article.append(heading, createTextElement("p", "message-text", response.message || "后端已返回处理状态。"));
  if (response.tier) article.append(createTextElement("p", "receipt-meta", `代码判定：${tierLabels[response.tier] || response.tier}`));
  if (response.data) renderToolResult(article, response.intent, response.data);
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
  if (response.request_id) article.append(createTextElement("p", "receipt-meta", `请求编号：${response.request_id}`));
  elements.messages.append(article);
  scrollToLatest();
}

function clearPending() {
  if (expiryTimer) window.clearInterval(expiryTimer);
  expiryTimer = null;
  pendingOperation = null;
  elements["confirmation-code"].textContent = "";
  elements["confirmation-details"].replaceChildren();
  elements["confirmation-expiry"].textContent = "";
  elements["confirmation-active"].hidden = true;
  elements["confirmation-empty"].hidden = false;
  updateControls();
}

/** 完整目标和影响展示后，只有显式点击才能提交固定确认入口。 */
function renderPending(response) {
  clearPending();
  const operation = response.operation;
  const expiry = Date.parse(response.expires_at);
  const completeOperation = operation && operation.simulated === true && operation.user_id === session?.user_id
    && Object.hasOwn(intentLabels, operation.intent) && operation.intent !== "unknown"
    && operation.params && typeof operation.params === "object" && !Array.isArray(operation.params)
    && typeof operation.impact === "string" && operation.impact.length > 0;
  if (!completeOperation || response.tier !== "yellow" || typeof response.request_id !== "string" || typeof response.confirmation_code !== "string" || !/^\d{6}$/.test(response.confirmation_code) || !Number.isFinite(expiry)) {
    appendLocalNotice("待确认回执缺少完整参数、有效期或确认码，页面已停止确认。请重新提出需求。");
    return;
  }
  pendingOperation = {
    requestId: response.request_id,
    confirmationCode: response.confirmation_code,
    expiresAt: expiry,
  };
  elements["confirmation-empty"].hidden = true;
  elements["confirmation-active"].hidden = false;
  const details = elements["confirmation-details"];
  details.append(createTextElement("h3", "", intentLabels[operation.intent] || "核对本次操作"));
  const fields = [["user_id", operation.user_id], ["tier", response.tier]];
  if (operation.target_name) fields.push([operation.intent === "transfer" ? "contact_name" : "subscription_name", operation.target_name]);
  if (operation.params && typeof operation.params === "object") {
    for (const [key, value] of Object.entries(safeDetails(operation.params))) fields.push([key, value]);
  }
  for (const key of ["target_account_id", "amount_cents", "daily_outgoing_after_cents"]) {
    if (Object.hasOwn(operation, key) && !fields.some(([field]) => field === key)) fields.push([key, operation[key]]);
  }
  fields.push(["request_id", response.request_id]);
  appendDetailList(details, fields);
  if (operation.impact) details.append(createTextElement("p", "confirmation-impact", operation.impact));
  // 确认码只在当前屏幕显示，永不进入回执历史或浏览器存储。
  elements["confirmation-code"].textContent = response.confirmation_code;
  function updateExpiry() {
    if (!pendingOperation) return;
    const seconds = Math.max(0, Math.ceil((pendingOperation.expiresAt - Date.now()) / 1000));
    elements["confirmation-expiry"].textContent = `有效至 ${formatTime(response.expires_at)}（北京时间）；剩余 ${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒`;
    if (seconds === 0) {
      clearPending();
      appendLocalNotice("本次确认已超过有效期，页面已清除确认码。需要办理时请重新提出需求；后端仍会复查有效期。");
    }
  }
  updateExpiry();
  if (pendingOperation) expiryTimer = window.setInterval(updateExpiry, 1000);
  updateControls();
}

function renderPlan(plan, planId) {
  if (!plan || !Array.isArray(plan.steps)) return;
  currentPlan = { ...plan, plan_id: plan.plan_id || planId };
  elements["plan-panel"].hidden = false;
  elements["plan-status"].textContent = statusLabels[plan.status] || displayText(plan.status);
  elements["plan-steps"].replaceChildren();
  for (const step of plan.steps) {
    const item = createTextElement("li", "");
    const body = createTextElement("div", "");
    const line = createTextElement("div", "plan-step-line");
    line.append(createTextElement("strong", "", intentLabels[step.intent] || step.intent), createTextElement("span", "muted", statusLabels[step.status] || step.status));
    body.append(line, createTextElement("p", "plan-step-detail", `步骤 ${step.id}${Array.isArray(step.depends_on) && step.depends_on.length ? ` · 依赖 ${step.depends_on.join("、")}` : " · 无前置步骤"}`));
    item.append(body);
    elements["plan-steps"].append(item);
  }
  elements["plan-policy"].textContent = displayText(plan.rollback_policy || "中断或接管停止未完成步骤，已成功业务不会自动撤回。");
  updateControls();
}

function consumeResponse(response) {
  appendReceipt(response);
  if (response.plan) renderPlan(response.plan, response.plan_id);
  if (response.status === "pending") renderPending(response);
  else clearPending();
}

function updateControls() {
  const available = Boolean(session) && !busy && !pageLeaving;
  elements["send-button"].disabled = !available || !elements["message-input"].value.trim();
  elements["message-input"].disabled = !available;
  elements["audit-button"].disabled = !available;
  elements["confirm-button"].disabled = !available || !pendingOperation || pendingOperation.expiresAt <= Date.now();
  elements["cancel-button"].disabled = !available || !pendingOperation;
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
    elements["message-input"].focus();
  }
}

async function confirmCurrentOperation() {
  if (!session || busy || !pendingOperation || pendingOperation.expiresAt <= Date.now()) return;
  const request = pendingOperation;
  clearPending();
  setBusy(true);
  try {
    consumeResponse(await requestApi("/api/confirm", { request_id: request.requestId, confirmation_code: request.confirmationCode }));
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
    elements["message-input"].focus();
  }
}

async function cancelCurrentOperation() {
  if (!session || busy || !pendingOperation) return;
  const requestId = pendingOperation.requestId;
  clearPending();
  setBusy(true);
  try {
    consumeResponse(await requestApi("/api/cancel", { request_id: requestId }));
  } catch {
    reportConnectionFailure();
  } finally {
    setBusy(false);
    elements["message-input"].focus();
  }
}

async function controlPlan(action) {
  if (!session || busy || !currentPlan || typeof currentPlan.plan_id !== "string") return;
  const planId = currentPlan.plan_id;
  if (action !== "resume") clearPending();
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

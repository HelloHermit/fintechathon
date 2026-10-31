// HTTP v2 客户端。页面带 ?mock=1 时改用浏览器内的假后端（mock.js），只用于开发和离线截图。

export const params = new URLSearchParams(location.search);
export const MOCK = params.get("mock") === "1";

let csrfToken = null;
let mockModule = null;

export class ApiError extends Error {
  constructor(status, code, message, data) {
    super(message || "请求失败，请稍后再试。");
    this.status = status;
    this.code = code || "http_error";
    this.data = data || null;
  }
}

export function setCsrf(token) { csrfToken = token || null; }

async function mock() {
  if (!mockModule) mockModule = await import("./mock.js");
  return mockModule;
}

async function request(method, path, body) {
  if (MOCK) {
    const m = await mock();
    try {
      return await m.handle(method, path, body);
    } catch (e) {
      if (e && e.status) throw new ApiError(e.status, e.code, e.message, e.data);
      throw e;
    }
  }
  const init = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    if (csrfToken) init.headers["X-CSRF-Token"] = csrfToken;
    init.body = JSON.stringify(body ?? {});
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "network", "连接不上服务，请确认后端已经启动。");
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (!res.ok) {
    const err = data && data.error;
    throw new ApiError(res.status, err?.code, err?.message || `请求失败（HTTP ${res.status}）`, err);
  }
  return data;
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);

function qs(obj) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj || {})) if (v !== undefined && v !== null && v !== "") p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ---- 端点（与 docs/sprint/API_V2.md 第 2 节一一对应） ----
/**
 * 流式聊天（PLAN 11.2 第 7 条）：POST /api/v2/chat/stream，text/event-stream；
 * event: step → 一个 TraceStep；event: final → 完整 TurnResponse；event: error → {code, message}。
 * 接口不存在或返回的不是事件流时，自动退回普通 /api/v2/chat。
 */
let streamUnsupported = false;
async function chatStream(text, onStep) {
  if (MOCK) {
    const m = await mock();
    const resp = await m.handle("POST", "/api/v2/chat", { text });
    for (const st of resp.trace || []) { onStep?.(st); await new Promise((r) => setTimeout(r, 160)); }
    return resp;
  }
  if (streamUnsupported || !window.ReadableStream || !window.TextDecoder) return post("/api/v2/chat", { text });
  let res;
  try {
    res = await fetch("/api/v2/chat/stream", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
      body: JSON.stringify({ text }),
    });
  } catch {
    return post("/api/v2/chat", { text });
  }
  const type = res.headers.get("content-type") || "";
  if (res.status === 404 || res.status === 405 || res.status === 501 || (res.ok && !type.includes("text/event-stream"))) {
    streamUnsupported = true;
    return post("/api/v2/chat", { text });
  }
  if (!res.ok) {
    let data = null;
    try { data = await res.json(); } catch { /* 忽略 */ }
    throw new ApiError(res.status, data?.error?.code, data?.error?.message || `请求失败（HTTP ${res.status}）`, data?.error);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let final = null;
  const handle = (block) => {
    let ev = "message";
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) ev = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return;
    let obj;
    try { obj = JSON.parse(data.join("\n")); } catch { return; }
    if (ev === "step") onStep?.(obj);
    else if (ev === "final") final = obj;
    else if (ev === "error") throw new ApiError(500, obj.code, obj.message || "处理失败，请重试。");
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += dec.decode(value, { stream: true });
    let m;
    while ((m = /\r?\n\r?\n/.exec(buf))) {
      const block = buf.slice(0, m.index);
      buf = buf.slice(m.index + m[0].length);
      handle(block);
    }
    if (done) break;
  }
  if (buf.trim()) handle(buf);
  if (!final) throw new ApiError(0, "stream_incomplete", "连接中断，请重试。");
  return final;
}

export const api = {
  session: () => get("/api/v2/session"),
  home: () => get("/api/v2/home"),
  chat: (text) => post("/api/v2/chat", { text }),
  chatStream,
  channels: () => get("/api/v2/channels"),
  feishuBindCode: () => post("/api/v2/channels/feishu/bind-code", {}),
  feishuUnbind: () => post("/api/v2/channels/feishu/unbind", {}),
  action: (type, ref, value) => post("/api/v2/action", { type, ref, value }),
  quickIntent: (intent, params = {}) => post("/api/v2/quick-intent", { intent, params }),
  confirm: (request_id, confirmation_code, risk_acknowledged) =>
    post("/api/v2/confirm", risk_acknowledged === undefined
      ? { request_id, confirmation_code }
      : { request_id, confirmation_code, risk_acknowledged }),
  revise: (request_id, arrival) => post("/api/v2/pending/revise", { request_id, changes: { arrival } }),
  sendOtp: (request_id) => post("/api/v2/strong-auth/send-otp", { request_id }),
  verify: (request_id, pin, otp, risk_acknowledged) =>
    post("/api/v2/strong-auth/verify", risk_acknowledged === undefined
      ? { request_id, pin, otp }
      : { request_id, pin, otp, risk_acknowledged }),
  cancel: (request_id) => post("/api/v2/cancel", { request_id }),
  pendingList: () => get("/api/v2/pending"),
  planControl: (plan_id, action) => post("/api/v2/plan/control", { plan_id, action }),
  plans: () => get("/api/v2/plans"),
  plan: (id) => get(`/api/v2/plans/${encodeURIComponent(id)}`),
  simPhone: () => get("/api/v2/sim-phone"),
  notifications: () => get("/api/v2/notifications"),
  accounts: () => get("/api/v2/accounts"),
  transactions: (q) => get(`/api/v2/transactions${qs(q)}`),
  monthly: (month) => get(`/api/v2/reports/monthly${qs({ month })}`),
  annual: (q) => get(`/api/v2/reports/annual${qs(q)}`),
  cards: () => get("/api/v2/cards"),
  products: () => get("/api/v2/products"),
  holdings: () => get("/api/v2/holdings"),
  scheduled: () => get("/api/v2/scheduled"),
  audit: (limit = 100) => get(`/api/v2/audit${qs({ limit })}`),
  turn: (id) => get(`/api/v2/turns/${encodeURIComponent(id)}`),
  advanceClock: (body) => post("/api/v2/demo/advance-clock", body),
  reset: () => post("/api/v2/demo/reset", {}),
  switchUser: (user_id) => post("/api/v2/demo/switch-user", { user_id }),
};

// 页面按钮直接发起的业务（不经过模型，后端照样判档和确认）。
// 意图名以 API_V2 第 5.2 节为准。
export const QUICK = {
  subscriptions: "query_subscriptions",
  freezeCard: "freeze_card",
  unfreezeCard: "unfreeze_card",
  reportLost: "report_card_lost",
  cancelLost: "restore_card",
  setLimit: "set_card_limit",
  applyVirtual: "apply_virtual_card",
  redeem: "redeem_product",
  revoke: "revoke_transfer",
  payAA: "pay_aa_request",
  declineAA: "decline_aa_request",
  markNormal: "mark_normal",
  detectAnomalies: "detect_anomalies",
  startAssessment: "start_risk_assessment",
};

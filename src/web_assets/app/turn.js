// 统一处理 TurnResponse：写入对话、登记待确认单、更新安全透视、处理锁定与错误。
import { api, ApiError } from "./api.js";
import { state, emit, pushMessage, trackPending, setPendingStatus } from "./store.js";

/**
 * 发起一次会返回 TurnResponse 的调用。
 * @param {() => Promise<object>} call
 * @param {{userText?: string, label?: string, forRequest?: string, kind?: string, retry?: () => Promise}} opts
 */
export async function runTurn(call, opts = {}) {
  if (opts.userText) pushMessage({ role: "user", text: opts.userText });
  else if (opts.label) pushMessage({ role: "user", text: opts.label, action: true });
  state.busy = true;
  emit("busy", { kind: opts.kind || "chat" });
  try {
    const resp = await call();
    applyTurn(resp, opts);
    return resp;
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, "internal", "页面出错了，请重试。");
    if (opts.forRequest && (err.status === 404 || err.status === 409 || err.status === 410 || ["pending_invalid", "expired", "not_found", "pending_expired"].includes(err.code))) {
      setPendingStatus(opts.forRequest, err.code === "expired" || err.code === "pending_expired" ? "expired" : "invalid");
    }
    pushMessage({ role: "system", tone: "danger", text: err.message, retry: opts.retry || null, code: err.code });
    emit("error", err);
    return null;
  } finally {
    state.busy = false;
    emit("busy", null);
  }
}

export function applyTurn(resp, opts = {}) {
  if (!resp) return;
  state.lastTurn = resp;
  const blocks = resp.assistant?.blocks || [];

  // 回执里出现某张单的 request_id → 那张单已处理
  for (const b of blocks) {
    if (b.type === "receipt" && b.data?.request_id) {
      setPendingStatus(b.data.request_id, b.data.status === "failed" ? "invalid" : "done");
    }
  }
  // 对某张单的操作（确认/验证/取消/改到账方式）返回后：旧单不再可用，除非后端又返回了它
  if (opts.forRequest && (!resp.pending || resp.pending.request_id !== opts.forRequest)) {
    const cur = state.pendings.get(opts.forRequest);
    const retryable = opts.kind === "verify" && resp.error && resp.error.code !== "locked";
    if (cur && cur.status === "open" && !retryable) {
      setPendingStatus(opts.forRequest, opts.kind === "cancel" ? "cancelled" : resp.error ? "invalid" : "done");
    }
  }
  if (resp.pending) {
    trackPending(resp.pending, resp.turn_id);
    state.activePendingId = resp.pending.request_id;
  }

  const locked = resp.guard?.locked_until || null;
  state.lockedUntil = locked;

  pushMessage({ role: "assistant", turn: resp });
  emit("turn", resp);
  if (resp.pending) emit("open-pending", resp.pending.request_id);
}

export function sendChat(text) {
  const t = String(text || "").trim();
  if (!t || state.busy) return null;
  return runTurn(() => api.chat(t.slice(0, 500)), { userText: t, retry: () => sendChat(t) });
}

export function sendAction(type, ref, value, label) {
  if (state.busy) return null;
  return runTurn(() => api.action(type, ref, value), { label, kind: "action", retry: () => sendAction(type, ref, value, label) });
}

export function sendQuick(intent, params, label) {
  if (state.busy) return null;
  return runTurn(() => api.quickIntent(intent, params), { label, kind: "quick", retry: () => sendQuick(intent, params, label) });
}

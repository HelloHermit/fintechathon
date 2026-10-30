// 全局状态 + 简单事件。页面之间只通过这里交换数据。

export const state = {
  session: null,
  home: null,
  tab: "home",
  messages: [],            // {id, role: user|assistant|system, text, turn, at}
  pendings: new Map(),     // request_id -> {op, status: open|done|cancelled|invalid|expired, turnId}
  activePendingId: null,   // 当前弹出的待确认单
  lastTurn: null,          // 最近一次 TurnResponse（安全透视面板用）
  sms: [],
  smsSeen: new Set(),
  busy: false,
  lockedUntil: null,
  clock: { baseMs: null, at: 0 },
  draft: "",
};

const listeners = new Map();
export function on(evt, fn) {
  if (!listeners.has(evt)) listeners.set(evt, new Set());
  listeners.get(evt).add(fn);
  return () => listeners.get(evt).delete(fn);
}
export function emit(evt, data) {
  for (const fn of listeners.get(evt) || []) {
    try { fn(data); } catch (e) { console.error(e); }
  }
}

let seq = 0;
export function pushMessage(msg) {
  const m = { id: `m${++seq}`, at: Date.now(), ...msg };
  state.messages.push(m);
  emit("messages", m);
  return m;
}

/** 模拟时间：以 session.demo.now 为基准，随真实时间流逝。 */
export function setClock(iso) {
  const t = Date.parse(iso);
  if (!Number.isNaN(t)) state.clock = { baseMs: t, at: Date.now() };
  emit("clock");
}
export function simNowMs() {
  if (state.clock.baseMs === null) return Date.now();
  return state.clock.baseMs + (Date.now() - state.clock.at);
}
/** 把毫秒转成北京时间的 {hh, mm, date} */
export function beijing(ms) {
  const d = new Date(ms + 8 * 3600 * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return {
    date: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
    hh: p(d.getUTCHours()), mm: p(d.getUTCMinutes()),
    iso: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}+08:00`,
    weekday: "日一二三四五六"[d.getUTCDay()],
  };
}

/**
 * 记录一张待确认单。同一 request_id 只记一次；新单出现时，旧的同类单不自动作废（后端说了算）。
 */
export function trackPending(op, turnId) {
  if (!op || !op.request_id) return null;
  const existing = state.pendings.get(op.request_id);
  if (existing && !op.confirmation_code && existing.op.confirmation_code) op = { ...op, confirmation_code: existing.op.confirmation_code };
  const entry = existing ? { ...existing, op } : { op, status: "open", turnId };
  state.pendings.set(op.request_id, entry);
  emit("pendings");
  return entry;
}
export function setPendingStatus(requestId, status) {
  const e = state.pendings.get(requestId);
  if (!e) return;
  e.status = status;
  if (status !== "open" && state.activePendingId === requestId) state.activePendingId = null;
  emit("pendings");
}
export function openPendings() {
  return [...state.pendings.entries()].filter(([, e]) => e.status === "open").map(([id, e]) => ({ id, ...e }));
}

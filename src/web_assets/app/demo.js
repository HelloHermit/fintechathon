// 演示控制：快进模拟时间、重置演示库、切换身份。桌面端在右侧面板，手机端在“我的”里。
import { h, icon, fmtTime, fill } from "./util.js";
import { api } from "./api.js";
import { state, emit, on, pushMessage, setClock, simNowMs, beijing } from "./store.js";
import { toast } from "./toast.js";

export async function advance(body, label) {
  try {
    const r = await api.advanceClock(body);
    setClock(r.now);
    const n = (r.executed || []).length;
    pushMessage({ role: "system", tone: "info", text: `模拟时间已快进到 ${fmtTime(r.now, "ymd hm")}${n ? `，到期执行了 ${n} 项：` : "。"}`, notifications: r.executed || [] });
    toast(n ? `${label || "时间快进"}：执行了 ${n} 项` : `${label || "时间快进"}：没有到期任务`);
    emit("data-changed");
    return r;
  } catch (e) { toast(e.message); return null; }
}

export async function resetDemo() {
  try {
    const s = await api.reset();
    applySession(s, true);
    toast("演示库已按 rich 种子重置");
  } catch (e) { toast(e.message); }
}

export async function switchUser(userId) {
  try {
    const s = await api.switchUser(userId);
    applySession(s, true);
    toast(`已切换为 ${s.user?.display_name || userId}`);
  } catch (e) { toast(e.message); }
}

export function applySession(s, resetChat) {
  state.session = s;
  if (s.demo?.now) setClock(s.demo.now);
  if (resetChat) {
    state.messages = [];
    state.pendings.clear();
    state.activePendingId = null;
    state.lastTurn = null;
    state.lockedUntil = null;
    state.sms = [];
    state.smsSeen.clear();
  }
  emit("session", s);
  emit("data-changed");
  emit("messages-reset");
}

export function demoControls() {
  const timeEl = h("div.demo-time");
  const userRow = h("div.seg");
  const paint = () => {
    const b = beijing(simNowMs());
    fill(timeEl, h("span.muted.small", { text: "模拟时间" }), h("b", { text: `${b.date} ${b.hh}:${b.mm}` }), h("span.muted.small", { text: `周${b.weekday}` }));
    const users = state.session?.demo?.users || [];
    fill(userRow, ...users.map((u) => h(`button.seg-btn${u.user_id === state.session?.user?.user_id ? ".on" : ""}`,
      { type: "button", onclick: () => u.user_id !== state.session?.user?.user_id && switchUser(u.user_id) }, u.display_name)));
  };
  paint();
  const t = setInterval(paint, 1000);
  const offS = on("session", paint);
  const offC = on("clock", paint);
  const off = () => { offS(); offC(); };
  let armed = false;
  const resetBtn = h("button.btn.small.danger-outline", { type: "button" }, icon("reset"), "重置演示库");
  resetBtn.addEventListener("click", () => {
    if (!armed) { armed = true; resetBtn.lastChild.textContent = "再点一次确认重置"; setTimeout(() => { armed = false; resetBtn.lastChild.textContent = "重置演示库"; }, 3000); return; }
    armed = false; resetBtn.lastChild.textContent = "重置演示库"; resetDemo();
  });
  const model = state.session?.model;
  const el = h("div.demo", null,
    timeEl,
    h("div.demo-grid", null,
      h("button.btn.small", { type: "button", onclick: () => advance({ minutes: 60 }, "快进 1 小时") }, icon("fast"), "+1 小时"),
      h("button.btn.small", { type: "button", onclick: () => advance({ minutes: 1440 }, "快进 1 天") }, icon("fast"), "+1 天"),
      h("button.btn.small", { type: "button", onclick: () => advance({ to: "2026-11-01T09:00:00+08:00" }, "到 11-01 09:00") }, "到 11-01 09:00"),
      h("button.btn.small", { type: "button", onclick: () => advance({ to: "2026-11-10T09:00:00+08:00" }, "到 11-10 09:00") }, "到 11-10 09:00")),
    state.session?.demo?.users?.length ? h("div.demo-row", null, h("span.muted.small", { text: "演示身份" }), userRow) : null,
    h("div.demo-row", null, resetBtn,
      model ? h(`span.chip.${model.mode === "live" ? "ok" : model.mode === "replay" ? "info" : "danger"}`, { text: `模型：${model.mode === "live" ? model.name : model.mode === "replay" ? "回放" : "不可用"}` }) : null));
  el._destroy = () => { clearInterval(t); off(); };
  return el;
}

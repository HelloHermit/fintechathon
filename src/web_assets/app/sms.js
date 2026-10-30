// 模拟手机短信：轮询 /api/v2/sim-phone；新短信在手机框顶部弹横幅，并出现在右侧“模拟手机”面板。
// 动态码只在这里给用户看，不进对话、不给模型。
import { h, icon, fmtTime, fill } from "./util.js";
import { api } from "./api.js";
import { state, on, emit } from "./store.js";

let timer = null;
let bannerTimer = null;
let first = true;

export async function pollSms() {
  try {
    const r = await api.simPhone();
    // 收件箱顺序没有约定，统一按收到时间从旧到新排
    const msgs = (r.messages || []).map((m, i) => [m, i]).sort((a, b) => String(a[0].received_at || "").localeCompare(String(b[0].received_at || "")) || b[1] - a[1]).map(([m]) => m);
    const fresh = msgs.filter((m) => !state.smsSeen.has(m.id));
    state.sms = msgs;
    fresh.forEach((m) => state.smsSeen.add(m.id));
    if (fresh.length) {
      if (!first) showBanner(fresh[fresh.length - 1]);
      emit("sms", msgs);
    }
    first = false;
  } catch { /* 后端暂时不可用时静默重试 */ }
}

export function startSmsPolling() {
  clearInterval(timer);
  pollSms();
  timer = setInterval(pollSms, 3000);
}
on("sms-refresh", () => setTimeout(pollSms, 300));
on("messages-reset", () => { first = true; pollSms(); });

function showBanner(m) {
  const el = document.getElementById("sms-banner");
  if (!el) return;
  fill(el, 
    h("div.smsb-head", null, h("span.smsb-app", null, icon("chat"), h("span", { text: "短信 · 模拟" })), h("span.muted.small", { text: "现在" })),
    h("div.smsb-from", { text: m.from || "模拟银行" }),
    h("div.smsb-text", { text: m.text }));
  el.hidden = false;
  el.classList.add("show");
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => { el.classList.remove("show"); setTimeout(() => { el.hidden = true; }, 300); }, 9000);
  el.onclick = () => { el.classList.remove("show"); el.hidden = true; };
}

export function smsList() {
  const list = h("div.sms-list");
  const paint = () => {
    const msgs = [...(state.sms || [])].reverse();
    fill(list, ...(msgs.length ? msgs.map((m) => h("div.sms", null,
      h("div.sms-head", null, h("b", { text: m.from || "模拟银行" }), h("span.muted.small", { text: fmtTime(m.received_at) })),
      h("div.sms-text", { text: m.text }))) : [h("div.empty", { text: "还没有短信。红档操作点“获取动态码”后，模拟短信会出现在这里。" })]));
  };
  paint();
  const off = on("sms", () => (list.isConnected ? paint() : off()));
  const masked = state.session?.user?.masked_phone;
  return h("div.sim-phone", null, h("div.muted.small", { text: `绑定手机 ${masked || ""}（模拟）· 动态码不会出现在对话里` }), list);
}

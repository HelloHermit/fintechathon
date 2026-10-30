// 入口：取会话 → 建标签页 → 右侧面板（演示控制 / 安全透视 / 模拟手机）→ 轮询短信。
import { h, icon } from "./util.js";
import { api, setCsrf, MOCK, params } from "./api.js";
import { state, on, emit, simNowMs, beijing, trackPending } from "./store.js";
import { buildTabbar, registerPage, goTab } from "./nav.js";
import { homePage } from "./home.js";
import { chatPage } from "./chat.js";
import { billsPage } from "./bills.js";
import { cardsPage } from "./cards.js";
import { mePage } from "./me.js";
import { applySession, demoControls } from "./demo.js";
import { renderTrace } from "./trace.js";
import { smsList, startSmsPolling } from "./sms.js";
import "./pending.js";

async function boot() {
  const screen = document.getElementById("screen");
  screen.replaceChildren(h("div.boot", null, h("div.avatar.lg", { text: "安" }), h("div.muted", { text: "正在连接模拟银行…" })));
  let session;
  try {
    session = await api.session();
  } catch (e) {
    screen.replaceChildren(h("div.page-error", null, icon("alert"), h("h2", { text: "连接不上后端" }), h("p", { text: e.message }),
      h("p.muted.small", { text: "请先运行 python run.py；想先看界面，可以在网址后面加 ?mock=1 打开假数据模式。" }),
      h("button.btn.primary", { type: "button", onclick: boot }, "重试")));
    return;
  }
  setCsrf(session.csrf_token);
  applySession(session, true);
  if (MOCK) document.body.classList.add("is-mock");

  registerPage("home", homePage());
  registerPage("chat", chatPage());
  registerPage("bills", billsPage());
  registerPage("cards", cardsPage());
  registerPage("me", mePage());
  buildTabbar();
  const startTab = params.get("tab");
  goTab(["home", "chat", "bills", "cards", "me"].includes(startTab) ? startTab : "home");

  await restorePendings();
  buildSide();
  startSmsPolling();
  tickClock();
  setInterval(tickClock, 1000);
  on("clock", tickClock);
}

// 刷新页面后恢复还没处理的待确认单（API_V2 5.1：这里不带确认码，黄档单需要重新发起）
async function restorePendings() {
  try {
    const r = await api.pendingList();
    (r.items || []).forEach((op) => trackPending(op, null));
    if ((r.items || []).length) emit("pendings");
  } catch { /* 旧后端没有这个接口时忽略 */ }
}

function tickClock() {
  const b = beijing(simNowMs());
  const el = document.getElementById("sb-time");
  if (el) el.textContent = `${b.hh}:${b.mm}`;
}

function buildSide() {
  const demo = document.getElementById("side-demo");
  const trace = document.getElementById("side-trace");
  const sms = document.getElementById("side-sms");
  const paintDemo = () => {
    demo.querySelector(".demo")?._destroy?.();
    demo.replaceChildren(h("div.side-title", null, icon("fast"), h("span", { text: "演示控制" }), MOCK ? h("span.chip.warn", { text: "假数据模式" }) : null), demoControls());
  };
  const paintTrace = () => trace.replaceChildren(
    h("div.side-title", null, icon("shield"), h("span", { text: "安全透视" }), h("span.muted.small", { text: "模型提议，代码裁决" })),
    renderTrace(state.lastTurn));
  paintDemo();
  paintTrace();
  sms.replaceChildren(h("div.side-title", null, icon("phone"), h("span", { text: "模拟手机 · 短信" })), smsList());
  on("turn", paintTrace);
  on("messages-reset", () => { paintTrace(); paintDemo(); });
}

boot();

// 入口：取会话 → 建标签页 → 右侧面板（演示控制 / 安全透视 / 模拟手机）→ 轮询短信。
import { h, icon, fill } from "./util.js";
import { api, setCsrf, MOCK, params } from "./api.js";
import { state, on, emit, simNowMs, beijing, trackPending, openPendings } from "./store.js";
import { buildTabbar, registerPage, goTab } from "./nav.js";
import { homePage } from "./home.js";
import { chatPage } from "./chat.js";
import { billsPage } from "./bills.js";
import { cardsPage } from "./cards.js";
import { mePage } from "./me.js";
import { applySession, demoControls } from "./demo.js";
import { renderTrace } from "./trace.js";
import { smsList, startSmsPolling } from "./sms.js";
import { openPending } from "./pending.js";

async function boot() {
  const screen = document.getElementById("screen");
  fill(screen, h("div.boot", null, h("div.avatar.lg", { text: "安" }), h("div.muted", { text: "正在连接模拟银行…" })));
  let session;
  try {
    session = await api.session();
  } catch (e) {
    fill(screen, h("div.page-error", null, icon("alert"), h("h2", { text: "连接不上后端" }), h("p", { text: e.message }),
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
  setInterval(restorePendings, 15000); // 飞书等其他渠道产生的待办，网页上也能看到
  on("pendings", paintOriginBanner);
  paintOriginBanner();
  registerServiceWorker();
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

// 来自飞书的红档待办：需要回到 App 完成交易密码 + 动态码（PLAN 11.2 渠道分级风控）
function paintOriginBanner() {
  const el = document.getElementById("origin-banner");
  if (!el) return;
  const items = openPendings().filter(({ op }) => op.origin && op.origin !== "app");
  if (!items.length) { el.hidden = true; return; }
  const first = items[0];
  const red = first.op.tier === "red" || first.op.kind === "strong_auth";
  el.replaceChildren(icon("chat"), h("span", { text: `来自飞书的待办：${first.op.title}${red ? "，需要在 App 内完成强验证" : ""}${items.length > 1 ? `（共 ${items.length} 笔）` : ""}` }), h("b", { text: "去处理" }));
  el.hidden = false;
  el.onclick = () => openPending(first.id);
}

// PWA：先尝试作用域为整站的 /sw.js，服务端不支持时退回 /assets/sw.js（只缓存静态资源）
async function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || MOCK) return;
  try { await navigator.serviceWorker.register("/sw.js", { scope: "/" }); return; } catch { /* 服务端没有 /sw.js */ }
  try { await navigator.serviceWorker.register("/assets/sw.js", { scope: "/assets/" }); } catch { /* 浏览器不支持或被禁用 */ }
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
    fill(demo, h("div.side-title", null, icon("fast"), h("span", { text: "演示控制" }), MOCK ? h("span.chip.warn", { text: "假数据模式" }) : null), demoControls());
  };
  const paintTrace = () => fill(trace, 
    h("div.side-title", null, icon("shield"), h("span", { text: "安全透视" }), h("span.muted.small", { text: "模型提议，代码裁决" })),
    renderTrace(state.lastTurn));
  paintDemo();
  paintTrace();
  fill(sms, h("div.side-title", null, icon("phone"), h("span", { text: "模拟手机 · 短信" })), smsList());
  on("turn", paintTrace);
  on("messages-reset", () => { paintTrace(); paintDemo(); });
}

boot();

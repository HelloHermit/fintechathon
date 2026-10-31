// “小安”对话页。
import { h, icon, fmtTime, fill } from "./util.js";
import { state, on, openPendings } from "./store.js";
import { sendChat } from "./turn.js";
import { renderBlocks } from "./blocks.js";
import { pendingSummary, openPending } from "./pending.js";
import { openSheet } from "./sheet.js";
import { renderTrace } from "./trace.js";
import { MOCK } from "./api.js";

const EXAMPLES = [
  ["智能转账", "repeat", ["明天给小王转200，备注还饭钱", "给妈妈转2000", "把这个月房租交了"]],
  ["账单分析", "bill", ["这个月花了多少？都花哪了", "帮我看看有没有异常扣款", "生成10月账单报告"]],
  ["理财", "coin", ["我想买点理财", "对比一下活钱宝和稳健季享", "我的理财赚了多少"]],
  ["卡片", "card", ["我卡丢了", "储蓄卡每天限额降到2000", "帮我开张网购用的虚拟卡"]],
  ["订阅", "bell", ["我有哪些自动扣费", "最近有什么要续费的", "健身会员不要了"]],
  ["跨场景", "gift", ["我老婆下个月12号生日，帮我准备一下", "下个月房租交得起吗"]],
];

const STEP_KIND = { guard: "输入守卫", llm: "模型思考", tool: "调用工具", resolver: "代码解析", provenance: "参数溯源", tier: "代码判档", risk: "反诈评分", auth: "验证", fact_check: "事实校验", plan: "任务规划", audit: "写入审计" };
const BUSY_STEPS = ["正在理解你的话…", "正在查询账本…", "代码正在校验和判档…", "正在整理回复…"];

export function chatPage() {
  let list, input, sendBtn, sugg, pendBar, lockBar, busyEl, busyTimer, busyLabel;
  const el = h("div.page.chat-page");

  function build() {
    list = h("div.msgs", { role: "log", "aria-live": "polite", "aria-label": "对话记录" });
    input = h("textarea.chat-input", { rows: 1, maxlength: 500, placeholder: "说一句就能办", "aria-label": "输入消息" });
    sendBtn = h("button.send-btn", { type: "button", "aria-label": "发送", onclick: submit }, icon("send"));
    sugg = h("div.suggestions");
    pendBar = h("button.pend-bar", { type: "button", hidden: true });
    lockBar = h("div.lock-bar", { hidden: true });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
    });
    input.addEventListener("input", () => { autosize(); state.draft = input.value; });
    const mic = micButton((text) => { input.value = text; autosize(); input.focus(); });
    fill(el, 
      h("header.chat-head", null,
        h("div.avatar", { text: "安" }),
        h("div.chat-head-main", null, h("div.chat-name", { text: "小安" }), h("div.muted.small", { text: "模型提议，代码裁决 · 模拟银行" })),
        h("button.icon-btn.trace-btn", { type: "button", "aria-label": "安全透视", title: "安全透视：查看最近一轮的决策链", onclick: openTraceSheet }, icon("shield"))),
      lockBar,
      list,
      pendBar,
      sugg,
      h("div.composer", null, mic, input, sendBtn));
    renderAll();
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(110, input.scrollHeight)}px`;
  }

  function submit() {
    const t = input.value.trim();
    if (!t || state.busy) return;
    input.value = "";
    state.draft = "";
    autosize();
    sendChat(t);
  }

  function renderAll() {
    if (!list) return;
    list.replaceChildren();
    if (!state.messages.length) list.append(emptyState());
    state.messages.forEach((m) => list.append(renderMessage(m)));
    paintChrome();
    scrollDown();
  }

  function emptyState() {
    const name = state.session?.user?.display_name || "";
    return h("div.chat-empty", null,
      h("div.avatar.lg", { text: "安" }),
      h("h2", { text: `你好${name ? "，" + name : ""}，我是小安` }),
      h("p.muted", { text: "转账、账单、理财、卡片、订阅都可以直接说。涉及资金的操作，会先给你看确认单，由你点确认后才执行。" }),
      h("div.ex-grid", null, EXAMPLES.map(([title, ic, items]) => h("div.ex-group", null,
        h("div.ex-title", null, icon(ic), h("span", { text: title })),
        ...items.map((t) => h("button.ex", { type: "button", onclick: () => sendChat(t) }, t))))),
      MOCK ? h("div.note.warning", null, h("div", { text: "当前是假数据模式（?mock=1），回复是写死的示例，不连接后端。" })) : null);
  }

  function renderMessage(m) {
    if (m.role === "user") {
      return h(`div.msg.user${m.action ? ".action" : ""}`, null, h("div.bubble", { text: m.text }));
    }
    if (m.role === "system") {
      const retry = m.retry ? h("button.btn.small", { type: "button", onclick: () => m.retry() }, "重试") : null;
      return h(`div.msg.system.${m.tone || "info"}`, null,
        h("div.sys", null, icon(m.tone === "danger" ? "alert" : "clock"), h("span", { text: m.text }), retry,
          (m.notifications || []).length ? h("ul.sys-list", null, m.notifications.map((n) => h("li", { text: `${n.title}${n.body ? "：" + n.body : ""}` }))) : null));
    }
    const t = m.turn || {};
    const a = t.assistant || {};
    const wrap = h("div.msg.assistant", null, h("div.avatar.sm", { text: "安" }));
    const body = h("div.msg-body");
    if (a.text) body.append(h("div.bubble", { text: a.text }));
    if (t.error) {
      body.append(h("div.note.danger", null, icon("alert"), h("div", { text: t.error.message || "出了点问题" })));
    }
    body.append(...renderBlocks(a.blocks || []));
    if (t.plan && !(a.blocks || []).some((b) => b.type === "plan")) body.append(...renderBlocks([{ type: "plan", data: t.plan }]));
    if (t.pending) body.append(pendingSummary(t.pending));
    const meta = h("div.msg-meta", null,
      t.guard?.input === "blocked" ? h("span.chip.danger", { text: "已拦截" }) : null,
      t.guard?.fact_check === "corrected" ? h("span.chip.warn", { text: "事实校验已纠正" }) : null,
      (t.trace || []).length ? h("button.link", { type: "button", onclick: () => openTraceSheet(t) }, icon("shield"), `决策链 ${t.trace.length} 步`) : null);
    body.append(meta);
    wrap.append(body);
    return wrap;
  }

  function paintChrome() {
    if (!list) return;
    // 快捷回复：只显示最后一条助手消息的
    const last = [...state.messages].reverse().find((m) => m.role === "assistant");
    const items = state.busy ? [] : (last?.turn?.suggestions || []);
    fill(sugg, ...items.slice(0, 6).map((t) => h("button.chip-btn", { type: "button", onclick: () => sendChat(t) }, t)));
    sugg.hidden = !items.length;
    // 待确认提示条
    const open = openPendings();
    if (open.length && !document.querySelector(".pending-sheet")) {
      const latest = open[open.length - 1];
      pendBar.hidden = false;
      fill(pendBar, h(`span.tier-dot.${latest.op.tier}`), h("span", { text: open.length > 1 ? `${open.length} 笔操作待确认` : `待确认：${latest.op.title}` }), h("b", { text: "查看" }));
      pendBar.onclick = () => openPending(latest.id);
    } else pendBar.hidden = true;
    // 只读锁定
    if (state.lockedUntil) {
      lockBar.hidden = false;
      fill(lockBar, icon("lock"), h("span", { text: `检测到多次可疑请求，会话只读到 ${fmtTime(state.lockedUntil, "hm")}（只能查询）。` }));
    } else lockBar.hidden = true;
    input.disabled = false;
    sendBtn.disabled = state.busy;
  }

  function showBusy(on_) {
    if (!list) return;
    busyEl?.remove();
    clearInterval(busyTimer);
    if (!on_) return;
    let i = 0;
    const label = h("span", { text: BUSY_STEPS[0] });
    busyEl = h("div.msg.assistant.busy", null, h("div.avatar.sm", { text: "安" }), h("div.bubble.typing", null, h("span.dots", null, h("i"), h("i"), h("i")), label));
    list.append(busyEl);
    busyTimer = setInterval(() => { i = Math.min(i + 1, BUSY_STEPS.length - 1); label.textContent = BUSY_STEPS[i]; }, 1600);
    busyLabel = label;
    scrollDown();
  }
  // 流式：后端每推一步，就把正在做的事显示出来（不再用固定的轮播文字）
  on("stream-step", (st) => {
    if (!busyLabel?.isConnected) return;
    clearInterval(busyTimer);
    busyLabel.textContent = `${STEP_KIND[st.kind] || "处理中"}：${String(st.label || "").slice(0, 40)}`;
    scrollDown();
  });

  function scrollDown() {
    requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
  }

  on("messages", (m) => {
    if (!list) return;
    list.querySelector(".chat-empty")?.remove();
    busyEl?.remove();
    list.append(renderMessage(m));
    if (state.busy && m.role === "user") showBusy(true);
    paintChrome();
    scrollDown();
  });
  on("messages-reset", renderAll);
  on("busy", (b) => { showBusy(!!b); paintChrome(); });
  on("pendings", () => {
    paintChrome();
    // 更新对话里简要卡片的状态
    list?.querySelectorAll(".pending-card").forEach((card) => {
      const e = state.pendings.get(card.dataset.requestId);
      if (e) card.replaceWith(pendingSummary(e.op));
    });
  });
  on("sheet", paintChrome);

  return {
    build() { build(); return el; },
    show() { paintChrome(); scrollDown(); setTimeout(() => input?.focus({ preventScroll: true }), 50); },
  };
}

export function openTraceSheet(turn) {
  const t = turn && turn.trace ? turn : state.lastTurn;
  openSheet(h("div.trace-sheet", null, h("h2.ps-title", null, icon("shield"), " 安全透视"), h("p.muted.small", { text: "模型只能提议；档位、确认、执行和审计都由代码决定。下面是这一轮每一步的记录（已脱敏）。" }), renderTrace(t)), { label: "安全透视" });
}

function micButton(onText) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return h("span.mic-spacer");
  const btn = h("button.icon-btn.mic", { type: "button", "aria-label": "语音输入" }, icon("mic"));
  let rec = null;
  btn.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = "zh-CN";
    rec.interimResults = true;
    btn.classList.add("rec");
    rec.onresult = (e) => onText(Array.from(e.results).map((r) => r[0].transcript).join(""));
    rec.onend = () => { btn.classList.remove("rec"); rec = null; };
    rec.onerror = () => { btn.classList.remove("rec"); rec = null; };
    rec.start();
  });
  return btn;
}

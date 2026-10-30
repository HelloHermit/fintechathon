// 首页：总资产、账户、小安提醒（主动关怀）、快捷入口、通知。
import { h, icon, yuan, fmtTime } from "./util.js";
import { api } from "./api.js";
import { state, on, emit, simNowMs, beijing } from "./store.js";
import { insight } from "./blocks.js";
import { sendChat } from "./turn.js";
import { goTab, pushPage } from "./nav.js";
import { notificationsPage } from "./me.js";

const DEFAULT_QUICK = [
  { label: "转账", prompt: "我要转账", icon: "repeat" },
  { label: "本月账单", prompt: "这个月花了多少钱？", icon: "bill" },
  { label: "异常检查", prompt: "帮我看看有没有异常扣款", icon: "alert" },
  { label: "理财", prompt: "推荐点稳一点的理财，放半年", icon: "coin" },
  { label: "自动扣费", prompt: "我有哪些自动扣费", icon: "bell" },
  { label: "卡片", prompt: "我有哪些卡", icon: "card" },
  { label: "转人工", prompt: "转人工", icon: "headset" },
  { label: "年度报告", prompt: "我今年的消费年报", icon: "chart" },
];
const QUICK_ICON = { 转账: "repeat", 账单: "bill", 异常: "alert", 理财: "coin", 订阅: "bell", 扣费: "bell", 卡: "card", 人工: "headset", 报告: "chart", 年报: "chart", 生日: "gift", 房租: "house" };
const pickIcon = (label) => Object.entries(QUICK_ICON).find(([k]) => label.includes(k))?.[1] || "sparkle";

export function homePage() {
  const el = h("div.page.home-page");
  let hidden = false;
  try { hidden = localStorage.getItem("hide-assets") === "1"; } catch { /* 隐私模式 */ }

  async function load() {
    try {
      state.home = await api.home();
      emit("home", state.home);
    } catch (e) {
      el.replaceChildren(h("div.page-error", null, icon("alert"), h("p", { text: e.message }), h("button.btn", { type: "button", onclick: load }, "重试")));
      return;
    }
    render();
  }

  function greet() {
    const hh = +beijing(simNowMs()).hh;
    return hh < 6 ? "夜深了" : hh < 11 ? "早上好" : hh < 13 ? "中午好" : hh < 18 ? "下午好" : "晚上好";
  }

  function render() {
    const d = state.home || {};
    const user = state.session?.user || {};
    const unread = (d.notifications || []).filter((n) => !n.read).length;
    const eye = h("button.icon-btn.eye", { type: "button", "aria-label": hidden ? "显示金额" : "隐藏金额" }, icon("eye"));
    eye.addEventListener("click", () => {
      hidden = !hidden;
      try { localStorage.setItem("hide-assets", hidden ? "1" : "0"); } catch { /* 忽略 */ }
      render();
    });
    const money = (c) => (hidden ? "****" : yuan(c));
    const quick = (d.quick_actions?.length ? d.quick_actions : DEFAULT_QUICK).slice(0, 8);
    el.replaceChildren(
      h("header.home-head", null,
        h("div", null, h("div.home-greet", { text: `${greet()}，${user.display_name || ""}` }), h("div.muted.small", { text: "模拟银行 · 所有数据均为模拟" })),
        h("button.icon-btn.bell", { type: "button", "aria-label": `通知${unread ? `，${unread} 条未读` : ""}`, onclick: () => pushPage("消息通知", notificationsPage) },
          icon("bell"), unread ? h("span.badge", { text: String(unread) }) : null)),
      h("section.assets", null,
        h("div.assets-top", null, h("span", { text: "总资产（元）" }), eye),
        h("div.assets-total", { text: hidden ? "****" : yuan(d.total_assets_cents, { plain: true }) }),
        h("div.assets-accts", null, (d.accounts || []).map((a) => h("div.assets-acct", null,
          h("span", { text: `${a.name} ${a.masked_no || ""}` }),
          h("b", { text: money(a.available_cents ?? a.balance_cents) }),
          a.reserved_cents ? h("span.small", { text: `锁定 ${money(a.reserved_cents)}` }) : null)))),
      h("button.ask-bar", { type: "button", onclick: () => goTab("chat") }, h("span.avatar.sm", { text: "安" }), h("span", { text: "有事问小安，说一句就能办" }), icon("mic")),
      h("section.quick", null, quick.map((q) => h("button.quick-item", {
        type: "button", onclick: () => { goTab("chat"); sendChat(q.prompt); },
      }, h("span.quick-ic", null, icon(q.icon || pickIcon(q.label))), h("span", { text: q.label })))),
      (d.insights || []).length ? h("section.home-sec", null,
        h("div.sec-title", null, icon("sparkle"), h("span", { text: "小安提醒" }), h("span.muted.small", { text: `${d.insights.length} 条` })),
        h("div.insights", null, d.insights.map((x) => insight(x)))) : null,
      (d.notifications || []).length ? h("section.home-sec", null,
        h("div.sec-title", null, icon("bell"), h("span", { text: "最近通知" }),
          h("button.link", { type: "button", onclick: () => pushPage("消息通知", notificationsPage) }, "全部")),
        h("div.notif-list", null, d.notifications.slice(0, 3).map(notifRow))) : null,
      h("div.home-foot.muted.small", { text: "本页面为参赛作品演示：账户、资金、商户和短信均为模拟，不连接任何真实银行。" }));
  }

  on("data-changed", () => { if (state.tab === "home") load(); });
  on("session", () => { if (state.tab === "home") load(); });

  return { build() { el.append(h("div.skeleton")); load(); return el; }, show() { load(); } };
}

export function notifRow(n) {
  const ic = { scheduled_executed: "check", scheduled_failed: "alert", reminder: "bell", aa_request: "coin", risk_alert: "shield", settlement: "clock" }[n.kind] || "bell";
  return h(`div.notif${n.read ? "" : ".unread"}`, null, h("span.notif-ic", null, icon(ic)),
    h("div.notif-main", null, h("div.notif-title", { text: n.title }), n.body ? h("div.muted.small", { text: n.body }) : null),
    h("span.muted.small", { text: fmtTime(n.time) }));
}

// “我的”页及子页面：理财、订阅、定时任务、计划、通知、审计、安全透视、模拟手机、演示控制、关于。
import { h, icon, fmtTime } from "./util.js";
import { api, QUICK, MOCK } from "./api.js";
import { state, on } from "./store.js";
import { renderBlock, quickOrChat } from "./blocks.js";
import { renderPlan, PLAN_STATUS } from "./plan.js";
import { renderTrace } from "./trace.js";
import { pushPage, goTab } from "./nav.js";
import { demoControls } from "./demo.js";
import { smsList } from "./sms.js";
import { sendChat } from "./turn.js";

export function mePage() {
  const el = h("div.page.me-page");
  function render() {
    const u = state.session?.user || {};
    const items = [
      ["coin", "理财与风险测评", "持仓、收益、测评等级", () => pushPage("理财", wealthPage)],
      ["bell", "订阅与自动扣费", "查询需要确认（黄档）", () => { goTab("chat"); quickOrChat(QUICK.subscriptions, {}, "查询我的订阅与自动扣费", "我有哪些自动扣费"); }],
      ["repeat", "定时任务与在途资金", "房租、定时转账、延时到账", () => pushPage("定时任务", scheduledPage)],
      ["plan", "我的计划", "生日筹备等多步骤任务", () => pushPage("我的计划", plansPage)],
      ["bell", "消息通知", "执行结果、提醒、AA 收款", () => pushPage("消息通知", notificationsPage)],
      ["audit", "审计记录", "只追加 + 哈希链校验", () => pushPage("审计记录", auditPage)],
      ["shield", "安全透视", "最近一轮的决策链", () => pushPage("安全透视", tracePage)],
      ["phone", "模拟手机短信", "动态码只出现在这里", () => pushPage("模拟手机", smsPage)],
      ["fast", "演示控制", "快进时间、重置、切换身份", () => pushPage("演示控制", demoPage)],
      ["sparkle", "关于小安", "设计原则与模拟声明", () => pushPage("关于小安", aboutPage)],
    ];
    el.replaceChildren(
      h("header.me-head", null,
        h("div.me-avatar", { text: (u.display_name || "?").slice(-2) }),
        h("div", null, h("div.me-name", { text: u.display_name || "" }), h("div.muted.small", { text: `${u.masked_phone || ""} · 模拟用户` }))),
      h("nav.menu", null, items.map(([ic, title, sub, fn]) => h("button.menu-item", { type: "button", onclick: fn },
        h("span.menu-ic", null, icon(ic)), h("span.menu-main", null, h("span", { text: title }), h("span.muted.small", { text: sub })), icon("chevron", "menu-chev")))),
      h("div.home-foot.muted.small", { text: `版本 ${state.session?.version || "2.0"}${MOCK ? " · 假数据模式" : ""} · 全部数据为模拟` }));
  }
  on("session", () => { if (state.tab === "me") render(); });
  return { build() { render(); return el; }, show() { render(); } };
}

async function loadInto(c, fn) {
  c.replaceChildren(h("div.skeleton"));
  try { await fn(); } catch (e) {
    c.replaceChildren(h("div.page-error", null, icon("alert"), h("p", { text: e.message }), h("button.btn", { type: "button", onclick: () => loadInto(c, fn) }, "重试")));
  }
}

export function wealthPage(c) {
  loadInto(c, async () => {
    const [hold, prods] = await Promise.all([api.holdings(), api.products()]);
    const rp = hold.risk_profile;
    c.replaceChildren(
      rp ? renderBlock({ type: "risk_profile", data: rp }) : h("div.card-plain", null, h("div.blk-title", { text: "风险测评" }),
        h("p", { text: "你还没有有效的风险测评。按规定，申购理财前需要先完成测评。" }),
        h("button.btn.primary", { type: "button", onclick: () => { goTab("chat"); sendChat("我想做风险测评"); } }, "去测评")),
      renderBlock({ type: "holding_list", data: { items: hold.holdings || [] } }),
      renderBlock({ type: "product_list", data: { items: prods.products || [], disclaimer: prods.disclaimer } }),
      h("button.btn.block", { type: "button", onclick: () => { goTab("chat"); sendChat("推荐点稳一点的，放半年"); } }, icon("sparkle"), "让小安按我的风险等级推荐"));
  });
}

export function scheduledPage(c) {
  loadInto(c, async () => {
    const r = await api.scheduled();
    c.replaceChildren(renderBlock({ type: "scheduled_list", data: { items: r.items || [] } }),
      h("div.muted.small.pad", { text: "定时转账执行时，代码会重新检查余额、限额和当日累计；超出原授权档位时不会执行，而是提醒你重新授权。" }));
  });
}

export function plansPage(c) {
  const refresh = () => loadInto(c, async () => {
    const r = await api.plans();
    const list = r.plans || [];
    if (!list.length) { c.replaceChildren(h("div.empty", { text: "还没有计划。可以在首页的生日提醒里一键生成。" })); return; }
    c.replaceChildren(...list.map((p) => {
      const [st, tone] = PLAN_STATUS[p.status] || [p.status, ""];
      return h("button.menu-item", { type: "button", onclick: () => pushPage(p.title, (cc) => planDetail(cc, p.plan_id)) },
        h("span.menu-ic", null, icon("plan")),
        h("span.menu-main", null, h("span", { text: p.title }), h("span.muted.small", { text: `${p.done_count ?? 0}/${p.node_count ?? 0} 步完成 · ${fmtTime(p.created_at)}` })),
        h(`span.chip.${tone}`, { text: st }));
    }));
  });
  refresh();
}

function planDetail(c, id) {
  const load = () => loadInto(c, async () => {
    const p = await api.plan(id);
    c.replaceChildren(renderPlan(p, { onChange: load }));
  });
  load();
}

export function notificationsPage(c) {
  loadInto(c, async () => {
    const r = await api.notifications();
    const { notifRow } = await import("./home.js");
    const items = r.items || [];
    c.replaceChildren(items.length ? h("div.card-plain", null, items.map((n) => {
      const row = notifRow(n);
      if (n.kind === "aa_request") {
        row.append(h("button.btn.small.primary", { type: "button", onclick: () => { goTab("chat"); sendChat(`我收到一笔 AA 收款（${n.title}），帮我处理一下`); } }, "去处理"));
      }
      return row;
    })) : h("div.empty", { text: "暂无通知" }));
  });
}

export function auditPage(c) {
  loadInto(c, async () => {
    const r = await api.audit(100);
    const chain = r.chain || {};
    const RES = { success: "ok", rejected: "danger", failed: "danger", pending: "info", cancelled: "", corrected: "warn", blocked: "danger" };
    const RES_TEXT = { success: "成功", rejected: "已拒绝", failed: "失败", pending: "待确认", cancelled: "已取消", corrected: "已纠正", blocked: "已拦截", expired: "已过期" };
    const EVENT_TEXT = { executed: "已执行", pending_created: "生成待确认单", otp_sent: "发送动态码", fact_check: "事实校验", confirmed: "已确认", cancelled: "已取消", rejected: "拒绝", guard_blocked: "输入拦截", auth_failed: "验证失败", locked: "锁定", scheduled_executed: "定时执行", demo_reset: "重置演示库", expired: "过期" };
    c.replaceChildren(
      h(`div.chain-box.${chain.verified ? "ok" : "danger"}`, null, icon(chain.verified ? "check" : "alert"),
        h("div", null, h("b", { text: chain.verified ? "哈希链校验通过" : "哈希链校验失败" }),
          h("div.muted.small", { text: `共 ${chain.length ?? "?"} 条 · 链头 ${String(chain.head_hash || "").slice(0, 16)}…` }))),
      h("div.muted.small.pad", { text: "审计只追加，和业务修改在同一事务里写入；每条记录带上一条的哈希，任何改动都会让校验失败。" }),
      h("div.card-plain", null, (r.events || []).map((e) => h("div.audit-row", null,
        h("div.audit-main", null,
          h("div", null, ["green", "yellow", "red"].includes(e.tier) ? h(`span.tier-tag.${e.tier}`, { text: { green: "绿", yellow: "黄", red: "红" }[e.tier] }) : null, " ", h("b", { text: e.intent || e.event }), " ", h("span.muted.small", { text: EVENT_TEXT[e.event] || e.event || "" })),
          h("div.muted.small", { text: `${fmtTime(e.time)} · ${{ user: "本人", agent: "智能体", scheduler: "调度器" }[e.actor] || e.actor || ""}${e.reason ? " · " + e.reason : ""}` }),
          h("div.hash", { text: String(e.hash || "").slice(0, 24) })),
        h(`span.chip.${RES[e.result] ?? ""}`, { text: RES_TEXT[e.result] || e.result || "" }),
        e.turn_id ? h("button.link", { type: "button", onclick: () => pushPage("决策链回放", (cc) => turnReplay(cc, e.turn_id)) }, "回放") : null))));
  });
}

function turnReplay(c, turnId) {
  loadInto(c, async () => {
    const r = await api.turn(turnId);
    c.replaceChildren(renderTrace({ turn_id: r.turn_id, trace: r.trace || [] }));
  });
}

export function tracePage(c) {
  const paint = () => c.replaceChildren(renderTrace(state.lastTurn));
  paint();
  const off = on("turn", () => (c.isConnected ? paint() : off()));
}

export function smsPage(c) { c.replaceChildren(smsList()); }

export function demoPage(c) { c.replaceChildren(demoControls(), h("div.muted.small.pad", { text: "演示控制只在演示模式可用：快进时由调度器执行到期的定时任务；重置会按演示数据规格重建当前演示库。" })); }

export function aboutPage(c) {
  const m = state.session?.model || {};
  c.replaceChildren(h("div.card-plain.about", null,
    h("div.avatar.lg", { text: "安" }),
    h("h2", { text: "小安 · 银行 AI 智能体" }),
    h("p", { text: "FinTechathon 2026 人工智能赛道参赛作品。全部账户、资金、商户、短信均为模拟。" }),
    h("p", null, h("b", { text: "模型提议，代码裁决：" }), h("span", { text: "模型负责理解、规划和对话；权限档位、确认、强验证、执行和审计全部由代码决定。模型看不到确认码、动态码和交易密码。" })),
    h("ul.bullets", null,
      h("li", { text: "绿档：查询类，自动执行" }),
      h("li", { text: "黄档：展示详情，点确认按钮后执行（绑定参数、5 分钟、一次性）" }),
      h("li", { text: "红档：交易密码 + 模拟短信动态码，连续错 3 次锁 10 分钟" })),
    h("div.muted.small", { text: `模型：${m.name || "—"}（${m.mode === "live" ? "实时" : m.mode === "replay" ? "回放" : "不可用"}）· 版本 ${state.session?.version || "—"}` })));
}


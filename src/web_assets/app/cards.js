// 卡片页：卡面、状态、限额；冻结/解冻/挂失/解挂/调整限额/申请虚拟卡。
// 页面按钮不经过模型，但照样由后端代码判档并出确认单（风险对称：降风险=黄档，升风险=红档）。
import { h, icon, yuan } from "./util.js";
import { api, QUICK } from "./api.js";
import { state, on } from "./store.js";
import { cardVisual, quickOrChat } from "./blocks.js";
import { openSheet, closeSheet } from "./sheet.js";
import { toast } from "./toast.js";

export function cardsPage() {
  const el = h("div.page.cards-page");
  const body = h("div.cards-body");

  async function load() {
    body.replaceChildren(h("div.skeleton"));
    try {
      const r = await api.cards();
      render(r.cards || []);
    } catch (e) {
      body.replaceChildren(h("div.page-error", null, icon("alert"), h("p", { text: e.message }), h("button.btn", { type: "button", onclick: load }, "重试")));
    }
  }

  function act(intent, params, label, chatText) {
    return quickOrChat(intent, params, label, chatText).then((r) => {
      if (r && !r.pending) toast("结果已放进“小安”对话");
    });
  }

  function render(cards) {
    body.replaceChildren(
      ...cards.map((c) => {
        const tail = (c.masked_no || "").replace(/\D/g, "").slice(-4);
        const who = `尾号${tail}的${c.name}`;
        const btns = [];
        if (c.status === "active") {
          btns.push(button("snow", "临时冻结", "黄档", () => act(QUICK.freezeCard, { card_id: c.card_id }, `冻结${who}`, `把${who}临时冻结`)));
        }
        if (c.status === "frozen") {
          btns.push(button("snow", "解除冻结", "红档", () => act(QUICK.unfreezeCard, { card_id: c.card_id }, `解冻${who}`, `把${who}解冻`)));
        }
        if (c.status !== "lost") {
          btns.push(button("lock", "挂失", "红档", () => act(QUICK.reportLost, { card_id: c.card_id }, `挂失${who}`, `${who}丢了，帮我正式挂失`)));
          btns.push(button("chart", "调整限额", "降黄升红", () => limitSheet(c, who)));
        } else {
          btns.push(button("lock", "解除挂失", "红档", () => act(QUICK.cancelLost, { card_id: c.card_id }, `解挂${who}`, `${who}找到了，帮我解挂`)));
        }
        return h("div.card-block", null, cardVisual(c), h("div.card-actions", null, btns));
      }),
      h("button.btn.block", { type: "button", onclick: () => act(QUICK.applyVirtual, { purpose: "网购" }, "申请网购虚拟卡", "帮我开张网购用的虚拟卡") }, icon("card"), "申请一张网购虚拟卡（黄档）"),
      h("div.symmetry", null, icon("shield"),
        h("div", null, h("b", { text: "风险对称：" }), h("span", { text: "降低风险的操作（冻结、下调限额）只需点确认；增加风险的操作（解冻、上调限额、挂失与解挂）需要交易密码 + 短信动态码。" }))));
  }

  function button(ic, label, tier, onclick) {
    return h("button.card-act", { type: "button", onclick }, icon(ic), h("span", { text: label }), h("span.tier-mini", { text: tier }));
  }

  function limitSheet(c, who) {
    const input = h("input.amount-input", { type: "number", min: "0", step: "100", inputmode: "decimal", placeholder: "新的每日限额（元）", "aria-label": "新的每日限额（元）" });
    const hint = h("div.muted.small", { text: `当前每日限额 ${yuan(c.daily_limit_cents)}。` });
    const go = h("button.btn.primary.block", { type: "button", disabled: true }, "生成确认单");
    input.addEventListener("input", () => {
      const v = Math.round(Number(input.value) * 100);
      go.disabled = !(v > 0) || v === c.daily_limit_cents;
      hint.textContent = !(v > 0) ? `当前每日限额 ${yuan(c.daily_limit_cents)}。`
        : v < c.daily_limit_cents ? `下调到 ${yuan(v)}：降低风险，只需确认（黄档）。` : `上调到 ${yuan(v)}：增加风险，需要强验证（红档）。`;
    });
    go.addEventListener("click", () => {
      const v = Math.round(Number(input.value) * 100);
      closeSheet();
      act(QUICK.setLimit, { card_id: c.card_id, daily_limit_cents: v }, `把${who}每日限额调到${yuan(v)}`, `把${who}每天限额调到${v / 100}元`);
    });
    openSheet(h("div.limit-sheet", null, h("h2.ps-title", { text: `调整限额 · ${c.name}` }), input, hint, go), { label: "调整限额" });
    setTimeout(() => input.focus(), 50);
  }

  on("turn", () => { if (state.tab === "cards") load(); });
  on("data-changed", () => { if (state.tab === "cards") load(); });

  return {
    build() { el.append(h("header.page-head", null, h("h1", { text: "卡片" }), h("span.chip", { text: "模拟卡" })), body); load(); return el; },
    show() { load(); },
  };
}

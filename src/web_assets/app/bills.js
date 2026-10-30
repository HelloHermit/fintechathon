// 账单页：月报 / 年报 / 明细（可搜索、按分类筛选）。数字全部来自后端绿档数据接口。
import { api } from "./api.js";
import { state, on, simNowMs, beijing } from "./store.js";
import { renderBlock, txnRow } from "./blocks.js";
import { goTab } from "./nav.js";
import { sendChat } from "./turn.js";
import { h, icon, debounce, fill } from "./util.js";

const beijingMonth = (ms) => beijing(ms).date.slice(0, 7);

const CATEGORIES = ["餐饮外卖", "超市日用", "交通出行", "购物", "住房缴费", "娱乐", "订阅会员", "医疗健康", "学习教育", "旅行", "转账给他人", "人情红包", "其他", "工资", "转入", "理财收益", "退款"];

export function billsPage() {
  const el = h("div.page.bills-page");
  let mode = "month";
  let month = null;
  const body = h("div.bills-body");
  const seg = h("div.seg.seg-full");

  function paintSeg() {
    fill(seg, ...[["month", "月报"], ["year", "年报"], ["list", "明细"]].map(([k, label]) =>
      h(`button.seg-btn${mode === k ? ".on" : ""}`, { type: "button", onclick: () => { mode = k; paintSeg(); load(); } }, label)));
  }

  async function load() {
    if (!month) month = beijingMonth(simNowMs());
    fill(body, h("div.skeleton"));
    try {
      if (mode === "month") await loadMonth();
      else if (mode === "year") await loadYear();
      else await loadList();
    } catch (e) {
      fill(body, h("div.page-error", null, icon("alert"), h("p", { text: e.message }), h("button.btn", { type: "button", onclick: load }, "重试")));
    }
  }

  async function loadMonth() {
    const r = await api.monthly(month);
    const [y, m] = month.split("-").map(Number);
    const shift = (d) => { const t = new Date(Date.UTC(y, m - 1 + d, 1)); month = `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}`; load(); };
    const isCurrent = month >= beijingMonth(simNowMs());
    fill(body, 
      h("div.month-switch", null,
        h("button.icon-btn", { type: "button", "aria-label": "上个月", onclick: () => shift(-1) }, icon("back")),
        h("b", { text: `${y} 年 ${m} 月` }),
        h("button.icon-btn", { type: "button", "aria-label": "下个月", disabled: isCurrent, onclick: () => shift(1) }, icon("chevron"))),
      renderBlock({ type: "report", data: r }),
      h("div.btn-row.center", null,
        h("button.btn.small", { type: "button", onclick: () => { goTab("chat"); sendChat("帮我看看有没有异常扣款"); } }, icon("alert"), "异常检查"),
        h("button.btn.small", { type: "button", onclick: () => { goTab("chat"); sendChat(`${m}月外卖花了多少`); } }, icon("sparkle"), "问小安")));
  }

  async function loadYear() {
    const r = await api.annual({ last12: 1 });
    fill(body, renderBlock({ type: "report", data: r }));
  }

  async function loadList() {
    const q = { q: "", category: "", cursor: null };
    const list = h("div.txn-list");
    const more = h("button.btn.block.ghost", { type: "button" }, "加载更多");
    const count = h("div.muted.small");
    const search = h("input.search", { type: "search", placeholder: "搜索商户或备注", "aria-label": "搜索交易" });
    const cat = h("select.select", { "aria-label": "分类" }, h("option", { value: "" }, "全部分类"), CATEGORIES.map((c) => h("option", { value: c }, c)));
    async function fetchPage(reset) {
      if (reset) { q.cursor = null; fill(list, h("div.skeleton")); }
      const r = await api.transactions({ q: q.q, category: q.category, limit: 50, cursor: q.cursor });
      if (reset) list.replaceChildren();
      (r.items || []).forEach((t) => list.append(txnRow(t)));
      if (reset && !(r.items || []).length) list.append(h("div.empty", { text: "没有符合条件的交易" }));
      q.cursor = r.next_cursor || null;
      more.hidden = !q.cursor;
      count.textContent = `已显示 ${list.querySelectorAll(".txn").length} 笔`;
    }
    const refetch = debounce(() => fetchPage(true).catch((e) => fill(list, h("div.empty", { text: e.message }))), 300);
    search.addEventListener("input", () => { q.q = search.value.trim(); refetch(); });
    cat.addEventListener("change", () => { q.category = cat.value; refetch(); });
    more.addEventListener("click", () => fetchPage(false).catch(() => {}));
    fill(body, h("div.filter-row", null, h("span.search-wrap", null, icon("search"), search), cat), count, h("div.card-plain", null, list), more);
    await fetchPage(true);
  }

  on("data-changed", () => { if (state.tab === "bills") load(); });
  on("session", () => { month = null; });

  return {
    build() {
      paintSeg();
      el.append(h("header.page-head", null, h("h1", { text: "账单" }), h("span.chip", { text: "模拟数据" })), seg, body);
      load();
      return el;
    },
    show() { },
  };
}

// 富卡片渲染。所有内容由后端代码根据账本生成，这里只负责展示；外部文本一律 textContent。
import { h, icon, yuan, fmtTime, pct, SEVERITY_LABEL } from "./util.js";
import { donut, bars, meter } from "./charts.js";
import { sendAction, sendChat, runTurn } from "./turn.js";
import { api, ApiError } from "./api.js";
import { renderPlan } from "./plan.js";
import { state } from "./store.js";

const RENDERERS = {
  note, account_list, transaction_list, spending_breakdown, trend_chart, anomaly_list, report,
  subscription_list, product_list, product_compare, risk_questionnaire, risk_profile, holding_list,
  card_list, scheduled_list, budget_list, order_list, receipt, plan: planBlock, options, insight,
  code_analysis, handover, aa_request,
};

export function renderBlock(block, ctx = {}) {
  const fn = RENDERERS[block?.type];
  if (!fn) {
    return h("div.blk.blk-unknown", null, h("div.blk-title", { text: "暂不支持展示的内容" }), h("div.muted", { text: String(block?.type || "") }));
  }
  try {
    const el = fn(block.data || {}, ctx);
    el.classList.add("blk", `blk-${block.type}`);
    return el;
  } catch (e) {
    console.error("render block failed", block, e);
    return h("div.blk.blk-unknown", { text: "这张卡片显示失败。" });
  }
}

export function renderBlocks(blocks, ctx) {
  return (blocks || []).map((b) => renderBlock(b, ctx));
}

/** 页面按钮：先走 quick-intent（不经模型）；后端不认识这个意图时，退回成一句话发给小安。 */
export async function quickOrChat(intent, params, label, chatText) {
  if (state.busy) return;
  const r = await runTurn(async () => {
    try {
      const r = await api.quickIntent(intent, params);
      if (r?.error?.code === "invalid_request" && !r.pending && !(r.assistant?.blocks || []).length && chatText) return api.chat(chatText);
      return r;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 400 || e.status === 404 || e.code === "unknown_intent" || e.code === "invalid_request") && chatText) {
        return api.chat(chatText);
      }
      throw e;
    }
  }, { label: label || chatText, kind: "quick" });
  return r;
}

function title(text, extra) {
  return h("div.blk-title", null, h("span", { text }), extra || null);
}
function chip(text, tone = "") { return h(`span.chip${tone ? "." + tone : ""}`, { text }); }
function kv(label, value, cls = "") { return h(`div.kv${cls ? "." + cls : ""}`, null, h("span.k", { text: label }), h("span.v", { text: value })); }

// ---------- 各类卡片 ----------

function note(d) {
  const tone = d.tone || "info";
  const ic = { info: "sparkle", warning: "alert", success: "check", danger: "shield" }[tone] || "sparkle";
  return h(`div.note.${tone}`, null, icon(ic), h("div", { text: d.text || "" }));
}

function account_list(d) {
  return h("div.card-plain", null, title("账户"),
    ...(d.accounts || []).map((a) => h("div.acct-row", null,
      h("div", null, h("div.acct-name", { text: a.name }), h("div.muted.small", { text: a.masked_no || "" })),
      h("div.right", null, h("div.money", { text: yuan(a.available_cents ?? a.balance_cents) }),
        a.reserved_cents ? h("div.muted.small", { text: `已锁定 ${yuan(a.reserved_cents)}` }) : h("div.muted.small", { text: "可用余额" }))))
  );
}

export function txnRow(t) {
  const out = t.amount_cents < 0;
  const flags = (t.flags || []).map((f) => chip(FLAG_TEXT[f] || f, f === "anomaly" || f === "suspicious" ? "danger" : ""));
  return h("div.txn", null,
    h(`div.txn-ic${out ? "" : ".in"}`, null, h("span", { text: (t.category || "其他").slice(0, 1) })),
    h("div.txn-main", null,
      h("div.txn-merchant", { text: t.merchant || "—" }),
      h("div.muted.small", null, `${fmtTime(t.time)} · ${t.category || ""}`, ...flags),
      t.memo ? h("div.txn-memo", null, h("span.ext-tag", { text: "外部备注" }), h("span", { text: t.memo })) : null),
    h(`div.txn-amt${out ? "" : ".in"}`, { text: yuan(t.amount_cents, { sign: true }) }));
}
const FLAG_TEXT = { anomaly: "异常", suspicious: "可疑", refund: "退款", recurring: "周期", scheduled: "定时", delayed: "在途", in_transit: "在途", revoked: "已撤回", duplicate: "疑似重复" };

function transaction_list(d) {
  const items = d.items || [];
  return h("div.card-plain", null,
    title(d.title || "交易记录", d.total_count != null ? h("span.muted.small", { text: `共 ${d.total_count} 笔` }) : null),
    items.length ? h("div.txn-list", null, items.map(txnRow)) : h("div.empty", { text: "没有符合条件的交易" }));
}

function spending_breakdown(d) {
  const cmp = d.compare;
  let delta = null;
  if (cmp && cmp.change_pct !== null && cmp.change_pct !== undefined) {
    const up = cmp.change_pct > 0;
    delta = chip(`环比 ${up ? "↑" : "↓"}${pct(Math.abs(cmp.change_pct))}`, up ? "warn" : "ok");
  }
  const period = d.period ? `${fmtTime(d.period.from, "md")} 至 ${fmtTime(d.period.to, "md")}` : "";
  return h("div.card-plain", null,
    title("支出分类", delta),
    h("div.big-number", null, h("span.muted.small", { text: `${period} 支出` }), h("div.money.xl", { text: yuan(d.total_cents) })),
    cmp ? h("div.muted.small", { text: `上期 ${yuan(cmp.prev_total_cents)}` }) : null,
    donut(d.categories || [], { total: d.total_cents, centerLabel: "支出" }));
}

function trend_chart(d) {
  return h("div.card-plain", null, bars(d.series || [], { title: d.title || "趋势", metric: d.metric }));
}

function anomaly_list(d) {
  const items = d.items || [];
  const order = { high: 0, medium: 1, low: 2 };
  const sorted = [...items].sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3));
  return h("div.card-plain", null,
    title("异常交易识别", h("span.muted.small", { text: `${items.length} 处发现` })),
    sorted.length ? sorted.map((it) => h(`div.anomaly.${it.severity || "low"}`, null,
      h("div.anomaly-head", null, chip(SEVERITY_LABEL[it.severity] || it.severity, it.severity === "high" ? "danger" : it.severity === "medium" ? "warn" : ""),
        h("span.anomaly-rule", { text: it.rule || "" })),
      h("div.anomaly-main", null,
        h("div", null, h("div.txn-merchant", { text: it.merchant || "" }), h("div.muted.small", { text: fmtTime(it.time) })),
        h("div.money", { text: yuan(it.amount_cents, { sign: true }) })),
      h("div.anomaly-exp", { text: it.explanation || "" }),
      (it.actions || []).length ? h("div.btn-row", null, it.actions.map((a) =>
        h("button.btn.small" + (/冻结|挂失/.test(a.label) ? ".danger-outline" : ""), {
          type: "button",
          onclick: () => sendAction("block_action", it.finding_id, { intent: a.intent, params: a.params || {} }, a.label),
        }, a.label))) : null)) : h("div.empty", { text: "没有发现异常交易" }));
}

function report(d) {
  const kindText = d.kind === "annual" ? "年度报告" : "月度账单报告";
  const periodText = typeof d.period === "string" ? d.period : d.period ? (d.period.label || `${fmtTime(d.period.from, "ymd")} 至 ${fmtTime(d.period.to, "ymd")}`) : "";
  return h("div.card-plain.report", null,
    h("div.report-head", null, h("div", null, h("div.report-kind", { text: kindText }), h("div.report-period", { text: periodText })), icon("chart")),
    h("div.kpis", null, (d.kpis || []).map((k) => h("div.kpi", null,
      h("div.kpi-label", { text: k.label }), h("div.kpi-value", { text: String(k.value ?? "") }),
      k.delta ? h("div.kpi-delta", { text: String(k.delta) }) : null))),
    ...(d.charts || []).map((c) => renderBlock(c)),
    ...(d.sections || []).map((sec) => h("div.report-sec", null, h("div.report-sec-title", { text: sec.title }),
      h("ul.bullets", null, (sec.bullets || []).map((b) => h("li", { text: b }))))));
}

const SUB_FLAG = { price_up: ["涨价", "warn"], idle: ["闲置", "warn"], renew_soon: ["即将续费", "info"] };
function subscription_list(d) {
  const items = d.items || [];
  return h("div.card-plain", null,
    title("订阅与自动扣费", h("span.muted.small", { text: `每月约 ${yuan(d.monthly_total_cents)}` })),
    items.map((it) => h("div.sub-row", null,
      h("div.sub-main", null,
        h("div.sub-name", null, h("span", { text: it.name }), it.source === "detected" ? chip("从流水识别", "ai") : null),
        h("div.muted.small", { text: `${yuan(it.amount_cents)} / ${CYCLE[it.cycle] || it.cycle || "期"} · 下次 ${fmtTime(it.next_charge_date, "md")} · ${SUB_STATUS[it.status] || it.status || ""}` }),
        h("div.chips", null, (it.flags || []).map((f) => chip(...(SUB_FLAG[f] || [f]))))),
      it.status === "active" && it.source !== "detected" ? h("button.btn.small.ghost", {
        type: "button", onclick: () => quickOrChat("cancel_subscription", { subscription_id: it.subscription_id }, `取消${it.name}`, `帮我取消${it.name}`),
      }, "取消") : it.source === "detected" ? h("button.btn.small.ghost", { type: "button", onclick: () => sendChat(`${it.name}是什么扣费？怎么停掉？`) }, "了解") : null)));
}
const CYCLE = { monthly: "月", month: "月", yearly: "年", year: "年", weekly: "周", quarterly: "季" };
const SUB_STATUS = { active: "生效中", cancelled: "已取消", paused: "已暂停" };

const DISCLAIMER = "理财非存款，产品有风险，投资须谨慎。展示收益为模拟数据，不代表未来表现。";
function productCard(p) {
  return h("div.product", null,
    h("div.product-head", null, h("span.product-name", { text: p.name }), chip(p.risk_level, `risk-${(p.risk_level || "").toLowerCase()}`),
      p.suitable === true ? chip("符合你的风险等级", "ok") : p.suitable === false ? chip("超出你的风险等级", "danger") : null),
    h("div.product-yield", { text: p.yield_text || "" }),
    h("div.muted.small", { text: [p.type, p.term_days ? `${p.term_days} 天` : "随时", p.liquidity, p.min_amount_cents ? `${yuan(p.min_amount_cents)} 起购` : ""].filter(Boolean).join(" · ") }),
    p.description ? h("div.product-desc", null, h("span.ext-tag", { text: "产品说明" }), h("span", { text: p.description })) : null);
}
function product_list(d) {
  return h("div.card-plain", null, title("理财产品（模拟）"), (d.items || []).map(productCard), h("div.disclaimer", { text: d.disclaimer || DISCLAIMER }));
}
function product_compare(d) {
  const ps = d.products || [];
  const table = h("table.compare", null,
    h("thead", null, h("tr", null, h("th", { text: "" }), ps.map((p) => h("th", { text: p.name })))),
    h("tbody", null, (d.rows || []).map((r) => h("tr", null, h("th", { text: r.label }), (r.values || []).map((v) => h("td", { text: v }))))));
  return h("div.card-plain", null, title("产品对比"), h("div.table-scroll", null, table), h("div.disclaimer", { text: d.disclaimer || DISCLAIMER }));
}

function risk_questionnaire(d) {
  const form = h("form.questionnaire");
  (d.questions || []).forEach((q, qi) => {
    const fs = h("fieldset.q", null, h("legend", { text: `${qi + 1}. ${q.text}` }));
    (q.options || []).forEach((o) => {
      fs.append(h("label.q-opt", null, h("input", { type: "radio", name: q.id, value: String(o.value), required: true }), h("span", { text: o.label })));
    });
    form.append(fs);
  });
  const btn = h("button.btn.primary.block", { type: "submit" }, "提交测评");
  form.append(h("div.muted.small", { text: "提交测评属于黄档操作，提交后需要你在确认单上确认。" }), btn);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = {};
    for (const q of d.questions || []) {
      const sel = form.querySelector(`input[name="${CSS.escape(q.id)}"]:checked`);
      if (!sel) return;
      value[q.id] = Number(sel.value);
    }
    btn.disabled = true;
    sendAction("form_submit", d.questionnaire_id, value, "提交风险测评");
  });
  return h("div.card-plain", null, title("风险承受能力测评"), form);
}

const LEVEL_TEXT = { C1: "保守型", C2: "稳健型", C3: "平衡型", C4: "成长型", C5: "进取型" };
function risk_profile(d) {
  return h("div.card-plain.profile", null, title("风险测评结果"),
    h("div.profile-level", null, h("span.level", { text: d.level || "—" }), h("span", { text: d.label || LEVEL_TEXT[d.level] || "" })),
    kv("测评得分", d.score != null ? `${d.score} 分` : "—"),
    kv("可购买产品", d.max_product_risk ? `风险等级不高于 ${d.max_product_risk}` : "—"),
    kv("有效期至", d.valid_until ? fmtTime(d.valid_until, "ymd") : "—"));
}

function holding_list(d) {
  const items = d.items || [];
  return h("div.card-plain", null, title("我的理财持仓"),
    items.length ? items.map((x) => h("div.holding", null,
      h("div", null, h("div.product-name", { text: x.name }), h("div.muted.small", { text: `${fmtTime(x.purchased_at, "ymd")} 买入 · 可赎回 ${yuan(x.redeemable_cents)}` })),
      h("div.right", null, h("div.money", { text: yuan(x.amount_cents) }), h(`div.small.${x.profit_cents >= 0 ? "pos" : "neg"}`, { text: `收益 ${yuan(x.profit_cents, { sign: true })}` })))) : h("div.empty", { text: "暂无持仓" }),
    h("div.disclaimer", { text: DISCLAIMER }));
}

const CARD_STATUS = { active: ["正常", "ok"], frozen: ["临时冻结", "warn"], lost: ["已挂失", "danger"] };
export function cardVisual(c) {
  const [st, tone] = CARD_STATUS[c.status] || [c.status, ""];
  const used = c.daily_limit_cents ? (c.today_spent_cents || 0) / c.daily_limit_cents : 0;
  return h(`div.bankcard.${c.kind || "debit"}.${c.status || "active"}`, null,
    h("div.bc-top", null, h("span.bc-name", { text: c.name }), chip(st, tone)),
    h("div.bc-no", { text: c.masked_no || "" }),
    h("div.bc-bottom", null,
      h("span", { text: `今日已用 ${yuan(c.today_spent_cents || 0)} / 限额 ${yuan(c.daily_limit_cents)}` })),
    meter(used, { tone: used > 0.8 ? "warn" : "" }),
    h("div.bc-sim", { text: "模拟卡 · 不存在完整卡号与 CVV" }));
}
function card_list(d) {
  return h("div.card-plain", null, title("我的卡片"), h("div.cards-stack", null, (d.items || []).map(cardVisual)));
}

const SCH_KIND = { transfer: "转账", order: "下单", settlement: "延时到账", reminder: "提醒" };
const SCH_STATUS = { scheduled: ["待执行", "info"], executed: ["已执行", "ok"], failed: ["失败", "danger"], cancelled: ["已取消", ""], needs_reauth: ["需重新授权", "warn"] };
export function scheduledRow(x) {
  const [st, tone] = SCH_STATUS[x.status] || [x.status, ""];
  return h("div.sch-row", null, h("div.sch-ic", null, icon(x.kind === "settlement" ? "clock" : x.kind === "order" ? "gift" : x.kind === "reminder" ? "bell" : "repeat")),
    h("div.sch-main", null, h("div", { text: x.title }), h("div.muted.small", { text: `${SCH_KIND[x.kind] || x.kind} · ${fmtTime(x.run_at, "ymd hm")}${x.repeat && x.repeat !== "none" ? (x.repeat === "monthly" ? " · 每月" : " · 每周") : ""}` })),
    h("div.right", null, x.amount_cents != null ? h("div.money", { text: yuan(x.amount_cents) }) : null, chip(st, tone),
      x.revocable && x.status === "scheduled" ? h("button.btn.small.danger-outline", {
        type: "button",
        onclick: () => { document.dispatchEvent(new CustomEvent("goto-tab", { detail: "chat" })); quickOrChat("revoke_transfer", { transfer_id: x.schedule_id }, `撤回：${x.title}`, `撤回${x.title}`); },
      }, "撤回") : null));
}
function scheduled_list(d) {
  const items = d.items || [];
  return h("div.card-plain", null, title("定时任务与在途资金"), items.length ? items.map(scheduledRow) : h("div.empty", { text: "暂无定时任务" }));
}

function budget_list(d) {
  return h("div.card-plain", null, title("预算"), (d.items || []).map((b) => h("div.budget", null,
    h("div.budget-head", null, h("span", { text: b.name }), chip(BUDGET_STATUS[b.status] || b.status, b.status === "active" ? "ok" : "")),
    h("div.muted.small", { text: `锁定 ${yuan(b.amount_cents)} · 已用 ${yuan(b.spent_cents)} · 已释放 ${yuan(b.released_cents)} · 剩余 ${yuan(b.remaining_cents)}${b.until ? ` · 至 ${fmtTime(b.until, "md")}` : ""}` }),
    meter(b.amount_cents ? (b.spent_cents || 0) / b.amount_cents : 0))));
}
const BUDGET_STATUS = { active: "锁定中", released: "已释放", exhausted: "已用完", closed: "已结束" };

function order_list(d) {
  return h("div.card-plain", null, title("生活服务订单（模拟）"), (d.items || []).map((o) => h("div.sch-row", null,
    h("div.sch-ic", null, icon(/蛋糕/.test(o.service_name) ? "cake" : "gift")),
    h("div.sch-main", null, h("div", { text: o.service_name }), h("div.muted.small", { text: `送达 ${fmtTime(o.deliver_date, "md")} · ${ORDER_STATUS[o.status] || o.status}` })),
    h("div.money", { text: yuan(o.amount_cents) }))));
}
const ORDER_STATUS = { scheduled: "已预约", paid: "已付款", cancelled: "已取消", delivered: "已送达", failed: "失败" };

const RECEIPT = { success: ["办理成功", "ok", "check"], scheduled: ["已预约", "info", "clock"], failed: ["未办成", "danger", "x"], revoked: ["已撤回", "warn", "reset"] };
function receipt(d) {
  const [st, tone, ic] = RECEIPT[d.status] || [d.status, "", "check"];
  return h(`div.card-plain.receipt.${tone}`, null,
    h("div.receipt-head", null, h(`span.receipt-ic.${tone}`, null, icon(ic)), h("div", null, h("div.receipt-title", { text: d.title || "回执" }), h("div.receipt-st", { text: st }))),
    h("div.lines", null, (d.lines || []).map((l) => kv(l.label, l.value))),
    d.audit_hash ? h("div.audit-hash", null, icon("audit"), h("span", { text: `审计哈希 ${String(d.audit_hash).slice(0, 16)}…` })) : null);
}

function planBlock(d) { return renderPlan(d); }

function options(d) {
  return h("div.options", null,
    d.prompt ? h("div.options-prompt", { text: d.prompt }) : null,
    h("div.options-list", null, (d.items || []).map((it) => h("button.option", {
      type: "button",
      onclick: (e) => {
        e.currentTarget.closest(".options")?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
        e.currentTarget.classList.add("chosen");
        sendAction("option_select", d.ref, it.value, it.label);
      },
    }, h("span.option-label", { text: it.label }), it.hint ? h("span.option-hint", { text: it.hint }) : null))));
}

const INSIGHT_IC = { birthday: "gift", renewal: "repeat", anomaly: "alert", rent: "house", idle_cash: "coin", price_up: "chart" };
export function insight(d) {
  return h(`div.insight.${d.kind || ""}`, null,
    h("div.insight-ic", null, icon(INSIGHT_IC[d.kind] || "sparkle")),
    h("div.insight-main", null, h("div.insight-title", { text: d.title }), h("div.insight-body", { text: d.body || "" })),
    d.cta_label ? h("button.btn.small.primary", {
      type: "button",
      onclick: () => {
        document.dispatchEvent(new CustomEvent("goto-tab", { detail: "chat" }));
        sendAction("insight_accept", d.insight_id, true, d.cta_label);
      },
    }, d.cta_label) : null);
}

function code_analysis(d) {
  const ok = d.status === "ok";
  const lim = d.limits || {};
  const raw = d.result || {};
  // API_V2 5.4：result = {type, value}；兼容把 columns/rows/series 直接放在 result 上的写法
  const v = raw.value;
  const res = { ...raw, ...(v && typeof v === "object" && !Array.isArray(v) ? v : {}) };
  if (raw.type === "table" && Array.isArray(v)) res.rows = v;
  if (raw.type === "series" && Array.isArray(v)) res.series = v;
  if (raw.type === "value" && (v === null || typeof v !== "object")) res.value = v;
  let resultEl = null;
  if (raw.type === "value" && v && typeof v === "object") resultEl = objectTable(v);
  else if (res.type === "value") resultEl = h("div.ca-value", null, h("span.muted.small", { text: res.label || "结果" }), h("div.money", { text: formatResultValue(res.value, res.unit) }));
  else if (res.type === "table") {
    const first = (res.rows || [])[0];
    const cols = res.columns || (first && !Array.isArray(first) ? Object.keys(first) : (first || []).map((_, i) => `列${i + 1}`));
    resultEl = h("div.table-scroll", null, h("table.compare", null,
      h("thead", null, h("tr", null, cols.map((c) => h("th", { text: c })))),
      h("tbody", null, (res.rows || []).map((r) => h("tr", null, cols.map((c, i) => h("td", { text: formatCell(Array.isArray(r) ? r[i] : r[c], c) })))))));
  } else if (res.type === "series") resultEl = bars((res.series || res.points || []).map((p) => ({ label: p.label, value_cents: p.value_cents ?? p.value })), { title: res.title, highlightLast: false });
  else if (res && Object.keys(res).length) resultEl = h("pre.code", { text: JSON.stringify(res, null, 2) });

  const codeBox = h("details.ca-code", null, h("summary", { text: "查看 AI 生成的分析代码" }), h("pre.code", { text: d.code || "" }));
  return h("div.card-plain.ca", null,
    title("沙箱分析", chip(ok ? "运行成功" : d.status === "rejected" ? "代码被拒绝" : "运行出错", ok ? "ok" : "danger")),
    d.question ? h("div.ca-q", { text: d.question }) : null,
    resultEl,
    h("div.ca-sandbox", null, icon("shield"),
      h("span", { text: `${ENGINE[d.engine] || d.engine || "沙箱"} · 超时 ${lim.timeout_s ?? "?"} 秒${lim.cpu_s ? ` · CPU ${lim.cpu_s} 秒` : ""} · 内存 ${lim.memory_mb ?? "?"}MB · ${lim.network === false ? "无网络" : typeof lim.network === "string" ? `网络：${lim.network}` : "网络受限"} · 用时 ${d.duration_ms ?? "?"}ms` })),
    d.status !== "ok" && d.reason ? h("div.note.warning", null, h("div", { text: `原因：${d.reason}` })) : null,
    codeBox);
}
/** 沙箱返回的嵌套对象 → 表格（第一列是键，其余列是内层字段） */
function objectTable(obj) {
  const entries = Array.isArray(obj) ? obj.map((x, i) => [String(i + 1), x]) : Object.entries(obj);
  const nested = entries.every(([, x]) => x && typeof x === "object" && !Array.isArray(x));
  if (!nested) {
    return h("div.ca-value", null, entries.map(([k, x]) => kv(LABEL[k] || k, typeof x === "object" ? JSON.stringify(x) : String(x))));
  }
  const cols = [...new Set(entries.flatMap(([, x]) => Object.keys(x)))];
  return h("div.table-scroll", null, h("table.compare", null,
    h("thead", null, h("tr", null, h("th", { text: "" }), cols.map((c) => h("th", { text: LABEL[c] || c })))),
    h("tbody", null, entries.map(([k, x]) => h("tr", null, h("th", { text: LABEL[k] || k }), cols.map((c) => h("td", { text: formatCell(x[c], c) })))))));
}
const LABEL = { weekend: "周末", weekday: "工作日", count: "笔数", total: "合计", avg: "平均", average: "平均", mean: "平均", sum: "合计", max: "最大", min: "最小", median: "中位数" };
const ENGINE = { docker: "Docker 容器", subprocess: "受限子进程", "subprocess+netns": "受限子进程 + 无网络命名空间" };
function formatResultValue(v, unit) {
  if (typeof v === "number" && (unit === "cents" || unit === "分")) return yuan(v);
  return unit && unit !== "cents" ? `${v} ${unit}` : String(v);
}
function formatCell(v, col) {
  if (typeof v === "number" && /cents/.test(col || "")) return yuan(v);
  return v === null || v === undefined ? "" : String(v);
}

function handover(d) {
  return h("div.card-plain.handover", null, title("已转人工", chip(HANDOVER[d.status] || d.status || "处理中", "info")),
    h("div.muted.small", { text: `工单号 ${d.ticket_id || "—"}` }), h("div", { text: d.summary || "" }),
    h("div.muted.small", { text: "模拟客服：真实部署时由人工坐席接管，接管前不会自动执行任何资金操作。" }));
}
const HANDOVER = { open: "等待人工处理", assigned: "已分配坐席", closed: "已结束" };

const AA_STATUS = { open: ["待支付", "info"], paid: ["已支付", "ok"], declined: ["已拒绝", ""] };
function aa_request(d) {
  const [st, tone] = AA_STATUS[d.status] || [d.status, ""];
  const isPayer = state.session?.user?.display_name && d.from_name && state.session.user.display_name !== d.from_name;
  return h("div.card-plain.aa", null, title("AA 收款", chip(st, tone)),
    h("div.aa-main", null, h("div", null, h("div", { text: `${d.from_name || ""} 发起` }), d.memo ? h("div.muted.small", { text: d.memo }) : null), h("div.money.xl", { text: yuan(d.amount_cents) })),
    d.status === "open" && isPayer ? h("div.btn-row", null,
      h("button.btn.primary.small", { type: "button", onclick: () => quickOrChat("pay_aa_request", { request_id: d.request_id }, "支付这笔 AA", `支付${d.from_name}发起的 AA 收款`) }, "去支付"),
      h("button.btn.small.ghost", { type: "button", onclick: () => quickOrChat("decline_aa_request", { request_id: d.request_id }, "拒绝这笔 AA", `拒绝${d.from_name}发起的 AA 收款`) }, "拒绝")) : null);
}

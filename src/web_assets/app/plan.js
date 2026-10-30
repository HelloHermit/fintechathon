// 计划（DAG）视图：上方 SVG 依赖图，下方节点明细，底部控制按钮。
import { h, s, icon, fmtTime } from "./util.js";
import { runTurn } from "./turn.js";
import { api } from "./api.js";

export const PLAN_STATUS = {
  draft: ["草稿", ""], awaiting_confirmation: ["等待你确认", "warn"], running: ["执行中", "info"], paused: ["已暂停", "warn"],
  completed: ["已完成", "ok"], failed: ["失败", "danger"], rolled_back: ["已回退", ""], handed_over: ["已转人工", "info"],
};
const NODE_STATUS = {
  pending: ["待执行", "pending"], waiting: ["等待前置", "pending"], running: ["执行中", "running"], scheduled: ["已排定", "scheduled"],
  success: ["已完成", "success"], failed: ["失败", "failed"], skipped: ["已跳过", "skipped"], rolled_back: ["已回退", "skipped"],
};
const TIER_TEXT = { green: "绿档", yellow: "黄档", red: "红档" };
const ACTION_TEXT = { pause: "暂停", resume: "继续", rollback: "全部回退", takeover: "转人工" };

function levels(nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const memo = new Map();
  const depth = (n, seen = new Set()) => {
    if (memo.has(n.id)) return memo.get(n.id);
    if (seen.has(n.id)) return 0;
    seen.add(n.id);
    const deps = (n.depends_on || []).map((d) => byId.get(d)).filter(Boolean);
    const v = deps.length ? 1 + Math.max(...deps.map((d) => depth(d, seen))) : 0;
    memo.set(n.id, v);
    return v;
  };
  nodes.forEach((n) => depth(n));
  return memo;
}

function graph(nodes) {
  const lv = levels(nodes);
  const rows = [];
  nodes.forEach((n) => { const l = lv.get(n.id) || 0; (rows[l] ||= []).push(n); });
  const W = 320, rowH = 62, boxH = 40;
  const H = rows.length * rowH + 4;
  const pos = new Map();
  rows.forEach((row, ri) => {
    const bw = row.length === 1 ? 236 : Math.min(156, (W - 8 * (row.length + 1)) / row.length);
    const total = row.length * bw + (row.length - 1) * 8;
    row.forEach((n, i) => {
      const x = (W - total) / 2 + i * (bw + 8);
      pos.set(n.id, { x, y: ri * rowH + 4, w: bw });
    });
  });
  const svg = s("svg.dag", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "计划依赖图" });
  const defs = s("defs");
  const marker = s("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  marker.append(s("path", { d: "M0 0 10 5 0 10Z", class: "dag-arrow" }));
  defs.append(marker);
  svg.append(defs);
  nodes.forEach((n) => {
    const to = pos.get(n.id);
    (n.depends_on || []).forEach((d) => {
      const from = pos.get(d);
      if (!from) return;
      const x1 = from.x + from.w / 2, y1 = from.y + boxH, x2 = to.x + to.w / 2, y2 = to.y - 2;
      const my = (y1 + y2) / 2;
      svg.append(s("path", { d: `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`, class: "dag-edge", "marker-end": "url(#arrow)" }));
    });
  });
  nodes.forEach((n) => {
    const p = pos.get(n.id);
    const st = (NODE_STATUS[n.status] || [n.status, "pending"])[1];
    const g = s(`g.dag-node.${st}.tier-${n.tier || "green"}`);
    g.append(s("rect", { x: p.x, y: p.y, width: p.w, height: boxH, rx: 9 }));
    g.append(s("rect.dag-tier", { x: p.x, y: p.y, width: 5, height: boxH, rx: 2 }));
    const maxChars = Math.max(4, Math.floor((p.w - 16) / 10.6));
    const t = n.title || n.id;
    g.append(s("text", { x: p.x + 12, y: p.y + 17, class: "dag-t", text: t.length > maxChars ? t.slice(0, maxChars - 1) + "…" : t }));
    g.append(s("text", { x: p.x + 12, y: p.y + 32, class: "dag-s", text: `${(NODE_STATUS[n.status] || [n.status])[0]}${n.run_at ? " · " + fmtTime(n.run_at) : ""}` }));
    g.append(s("title", { text: `${t}（${TIER_TEXT[n.tier] || ""}）` }));
    svg.append(g);
  });
  return svg;
}

export function renderPlan(plan, { onChange } = {}) {
  const nodes = plan.nodes || [];
  const [st, tone] = PLAN_STATUS[plan.status] || [plan.status, ""];
  const done = nodes.filter((n) => n.status === "success").length;
  const wrap = h("div.card-plain.plan", { dataset: { planId: plan.plan_id || "" } },
    h("div.blk-title", null, h("span", null, icon("plan"), " ", plan.title || "计划"), h(`span.chip.${tone}`, { text: st })),
    h("div.muted.small", { text: `${nodes.length} 个步骤 · 已完成 ${done} 个${plan.created_at ? ` · 创建于 ${fmtTime(plan.created_at)}` : ""}` }),
    nodes.length ? graph(nodes) : null,
    h("ol.plan-nodes", null, nodes.map((n) => {
      const [nst, ncls] = NODE_STATUS[n.status] || [n.status, "pending"];
      return h(`li.plan-node.${ncls}`, null,
        h("span.pn-dot"),
        h("div.pn-main", null,
          h("div.pn-title", null, h("span", { text: n.title }), h(`span.tier-tag.${n.tier || "green"}`, { text: TIER_TEXT[n.tier] || n.tier || "" })),
          h("div.muted.small", { text: [nst, n.run_at ? `执行时间 ${fmtTime(n.run_at, "ymd hm")}` : "", n.compensation ? "可回退" : ""].filter(Boolean).join(" · ") }),
          n.result_summary ? h("div.pn-result", { text: n.result_summary }) : null));
    })));
  const actions = (plan.actions || []).filter((a) => ACTION_TEXT[a]);
  if (actions.length && plan.plan_id) {
    const row = h("div.btn-row");
    actions.forEach((a) => {
      const b = h(`button.btn.small${a === "rollback" ? ".danger-outline" : a === "takeover" ? ".ghost" : ""}`, { type: "button" }, ACTION_TEXT[a]);
      let armed = false, timer;
      b.addEventListener("click", async () => {
        if (a === "rollback" && !armed) {
          armed = true; b.textContent = "再点一次：取消未执行步骤并释放预算";
          timer = setTimeout(() => { armed = false; b.textContent = ACTION_TEXT[a]; }, 4000);
          return;
        }
        clearTimeout(timer);
        row.querySelectorAll("button").forEach((x) => { x.disabled = true; });
        await runTurn(() => api.planControl(plan.plan_id, a), { label: `计划：${ACTION_TEXT[a]}`, kind: "plan" });
        onChange?.();
      });
      row.append(b);
    });
    wrap.append(row);
  }
  return wrap;
}

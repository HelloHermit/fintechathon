// 纯 SVG 图表：环形图（分类占比）、柱状图（趋势）。不依赖第三方库。
import { h, s, yuan, yuanShort } from "./util.js";

export const PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#64748b", "#14b8a6", "#a855f7", "#eab308"];

/** 环形图 + 图例。items: [{name, amount_cents, share?}] */
export function donut(items, { total, centerLabel = "合计" } = {}) {
  const data = (items || []).filter((x) => x.amount_cents > 0);
  const sum = total ?? data.reduce((a, x) => a + x.amount_cents, 0);
  const R = 42, r = 28, C = 50;
  const svg = s("svg.donut", { viewBox: "0 0 100 100", role: "img", "aria-label": `分类占比，${centerLabel}${yuan(sum)}` });
  let angle = -Math.PI / 2;
  const top = data.slice(0, PALETTE.length);
  if (!top.length) {
    svg.append(s("circle", { cx: C, cy: C, r: (R + r) / 2, fill: "none", stroke: "#e5e7eb", "stroke-width": R - r }));
  }
  top.forEach((x, i) => {
    const frac = sum ? x.amount_cents / sum : 0;
    if (frac <= 0) return;
    const a2 = angle + Math.min(frac, 0.9999) * Math.PI * 2;
    const large = a2 - angle > Math.PI ? 1 : 0;
    const p = (rad, a) => `${C + rad * Math.cos(a)} ${C + rad * Math.sin(a)}`;
    const d = `M${p(R, angle)} A${R} ${R} 0 ${large} 1 ${p(R, a2)} L${p(r, a2)} A${r} ${r} 0 ${large} 0 ${p(r, angle)} Z`;
    const path = s("path", { d, fill: PALETTE[i % PALETTE.length] });
    path.append(s("title", { text: `${x.name} ${yuan(x.amount_cents)}` }));
    svg.append(path);
    angle = a2;
  });
  svg.append(s("text", { x: C, y: C - 2, "text-anchor": "middle", class: "donut-k", text: centerLabel }));
  svg.append(s("text", { x: C, y: C + 9, "text-anchor": "middle", class: "donut-v", text: `¥${yuanShort(sum)}` }));

  const legend = h("ul.legend");
  top.forEach((x, i) => {
    const share = x.share ?? (sum ? x.amount_cents / sum : 0);
    const sw = h("span.sw");
    sw.style.background = PALETTE[i % PALETTE.length];
    legend.append(h("li", null, sw, h("span.lg-name", { text: x.name }),
      h("span.lg-v", { text: yuan(x.amount_cents) }),
      h("span.lg-p", { text: `${(share * (share <= 1 ? 100 : 1)).toFixed(1)}%` })));
  });
  return h("div.donut-wrap", null, svg, legend);
}

/** 柱状图。series: [{label, value_cents}] */
export function bars(series, { title, highlightLast = true, metric = "expense" } = {}) {
  const data = series || [];
  const W = 320, H = 150, pad = { l: 8, r: 8, t: 18, b: 22 };
  const vals = data.map((d) => Number(d.value_cents) || 0);
  const max = Math.max(1, ...vals.map(Math.abs));
  const hasNeg = vals.some((v) => v < 0);
  const plotH = H - pad.t - pad.b;
  const zeroY = hasNeg ? pad.t + plotH / 2 : pad.t + plotH;
  const scale = hasNeg ? plotH / 2 / max : plotH / max;
  const bw = (W - pad.l - pad.r) / Math.max(1, data.length);
  const svg = s("svg.bars", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title || "趋势图" });
  svg.append(s("line", { x1: pad.l, x2: W - pad.r, y1: zeroY, y2: zeroY, class: "axis" }));
  const maxIdx = vals.indexOf(Math.max(...vals));
  data.forEach((d, i) => {
    const v = vals[i];
    const hgt = Math.max(1, Math.abs(v) * scale);
    const x = pad.l + i * bw + bw * 0.18;
    const y = v >= 0 ? zeroY - hgt : zeroY;
    const isLast = highlightLast && i === data.length - 1;
    const rect = s("rect", { x, y, width: bw * 0.64, height: hgt, rx: 3, class: `bar ${v < 0 ? "neg" : ""} ${isLast ? "last" : ""} ${metric}` });
    rect.append(s("title", { text: `${d.label}：${yuan(v)}` }));
    svg.append(rect);
    const showLabel = data.length <= 7 || i % Math.ceil(data.length / 6) === 0 || i === data.length - 1;
    if (showLabel) svg.append(s("text", { x: x + bw * 0.32, y: H - 6, "text-anchor": "middle", class: "bar-x", text: shortLabel(d.label) }));
    if (i === maxIdx || isLast) {
      svg.append(s("text", { x: x + bw * 0.32, y: Math.max(10, y - 4), "text-anchor": "middle", class: "bar-v", text: yuanShort(v) }));
    }
  });
  return h("div.chart", null, title ? h("div.chart-title", { text: title }) : null, svg);
}

function shortLabel(label) {
  const m = /^(\d{4})-(\d{2})$/.exec(label || "");
  if (m) return `${+m[2]}月`;
  return String(label ?? "").slice(0, 6);
}

/** 进度条（比例 0..1） */
export function meter(frac, { tone = "" } = {}) {
  const bar = h("span.meter-fill");
  bar.style.width = `${Math.max(0, Math.min(1, frac)) * 100}%`;
  return h(`span.meter${tone ? "." + tone : ""}`, { role: "presentation" }, bar);
}

// 通用小工具：建元素（只用 textContent，不拼 HTML）、金额和时间格式化、图标。

const SVG_NS = "http://www.w3.org/2000/svg";

/** h("div.card.big", {onclick, "aria-label": …}, child, "文字", [更多孩子]) */
export function h(spec, attrs, ...children) {
  const [tag, ...classes] = spec.split(".");
  const el = document.createElement(tag || "div");
  if (classes.length) el.className = classes.join(" ");
  applyAttrs(el, attrs);
  append(el, children);
  return el;
}

export function s(spec, attrs, ...children) {
  const [tag, ...classes] = spec.split(".");
  const el = document.createElementNS(SVG_NS, tag);
  if (classes.length) el.setAttribute("class", classes.join(" "));
  applyAttrs(el, attrs);
  append(el, children);
  return el;
}

function applyAttrs(el, attrs) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = String(v);
    else if (k === "class") el.setAttribute("class", [el.getAttribute("class"), v].filter(Boolean).join(" "));
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value" && "value" in el) el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el) { el.replaceChildren(); return el; }

// ---- 金额 ----
export function yuan(cents, { sign = false, plain = false } = {}) {
  if (cents === null || cents === undefined || Number.isNaN(Number(cents))) return "—";
  const n = Math.round(Number(cents));
  const neg = n < 0;
  const abs = Math.abs(n);
  const int = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = String(abs % 100).padStart(2, "0");
  const body = `${plain ? "" : "¥"}${int}.${dec}`;
  if (neg) return `-${body}`;
  return sign && n > 0 ? `+${body}` : body;
}

export function yuanShort(cents) {
  const v = Math.abs(cents) / 100;
  if (v >= 10000) return `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)}万`;
  return v >= 100 ? v.toFixed(0) : v.toFixed(2).replace(/\.00$/, "");
}

export function pct(x, digits = 1) {
  if (x === null || x === undefined) return "—";
  return `${Number(x).toFixed(digits)}%`; // 入参是百分数（如 change_pct=23.5 表示 23.5%）
}

// ---- 时间：后端统一给 +08:00 的 ISO 字符串，直接截取，避免受浏览器时区影响 ----
export function isoParts(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(iso || "");
  if (!m) return null;
  return { y: +m[1], mo: +m[2], d: +m[3], hh: m[4] ?? "00", mm: m[5] ?? "00", ss: m[6] ?? "00", date: `${m[1]}-${m[2]}-${m[3]}` };
}
export function fmtTime(iso, mode = "md hm") {
  const p = isoParts(iso);
  if (!p) return iso ? String(iso) : "—";
  const md = `${String(p.mo).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
  if (mode === "hm") return `${p.hh}:${p.mm}`;
  if (mode === "md") return md;
  if (mode === "ymd") return p.date;
  if (mode === "ymd hm") return `${p.date} ${p.hh}:${p.mm}`;
  return `${md} ${p.hh}:${p.mm}`;
}
/** 把 +08:00 ISO 转成毫秒时间戳（用于倒计时） */
export function isoMs(iso) { const t = Date.parse(iso); return Number.isNaN(t) ? null : t; }

export function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function uid(prefix = "id") { return `${prefix}_${Math.random().toString(36).slice(2, 10)}`; }

// ---- 图标（内联 SVG 路径，24×24，描边风格） ----
const ICONS = {
  home: "M3 11 12 3l9 8M5 9.5V21h5v-6h4v6h5V9.5",
  chat: "M4 5h16v11H9l-5 4V5Zm4 5h.01M12 10h.01M16 10h.01",
  bill: "M6 2h12v20l-3-2-3 2-3-2-3 2V2Zm3 6h6M9 12h6M9 16h3",
  card: "M2 6h20v12H2V6Zm0 4h20M6 15h4",
  me: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9a8 8 0 0 1 16 0",
  send: "M3 11.5 21 3l-8.5 18-2-7.5-7.5-2Z",
  shield: "M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Zm-3.5 10 2.5 2.5 5-5",
  lock: "M6 10V7a6 6 0 0 1 12 0v3M5 10h14v11H5V10Zm7 4v3",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4l2-2Zm4 4h4",
  gift: "M3 9h18v4H3V9Zm2 4v8h14v-8M12 9v12M12 9S10 3 7 4.5 9 9 12 9Zm0 0s2-6 5-4.5S15 9 12 9Z",
  repeat: "M4 9a7 7 0 0 1 12-3l3 3m0-5v5h-5M20 15a7 7 0 0 1-12 3l-3-3m0 5v-5h5",
  alert: "M12 3 2 20h20L12 3Zm0 6v5m0 3h.01",
  house: "M3 11 12 4l9 7M6 9v11h12V9",
  coin: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3-11h6M9 14h6m-3-7v10",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-14v5l3 3",
  plan: "M5 4h4v4H5V4Zm10 6h4v4h-4v-4ZM5 16h4v4H5v-4Zm4-10h3v12H9m3-6h3",
  audit: "M5 3h10l4 4v14H5V3Zm9 0v5h5M8 12h8M8 16h8",
  phone: "M7 2h10v20H7V2Zm4 17h2",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  check: "M4 12.5 9.5 18 20 6",
  x: "M6 6l12 12M18 6 6 18",
  chevron: "m9 6 6 6-6 6",
  back: "m15 6-6 6 6 6",
  mic: "M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm-6-3a6 6 0 0 0 12 0M12 18v3",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 5 5",
  fast: "M3 6v12l8-6-8-6Zm9 0v12l8-6-8-6Z",
  reset: "M4 4v6h6M4.5 15a8 8 0 1 0 1.9-8.4L4 9",
  user: "M16 11a4 4 0 1 0-8 0 4 4 0 0 0 8 0ZM3 21a9 9 0 0 1 18 0",
  wallet: "M3 7h16v13H3V7Zm0 0 12-4v4m1 7h.01",
  headset: "M4 15v-3a8 8 0 0 1 16 0v3M4 15h3v5H4v-5Zm13 0h3v5h-3v-5Z",
  code: "m8 8-5 4 5 4m8-8 5 4-5 4M14 4l-4 16",
  snow: "M12 2v20M4 7l16 10M20 7 4 17",
  cake: "M4 21h16v-8H4v8Zm0-4c2 1 4 1 5 0s3-1 4 0 4 1 5 0M12 13V9m0-4v.01",
  sparkle: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6",
};
export function icon(name, cls = "") {
  const svg = s("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", class: `ic ${cls}`.trim() });
  svg.append(s("path", { d: ICONS[name] || ICONS.sparkle }));
  return svg;
}

export const TIER_LABEL = { green: "绿档 · 自动执行", yellow: "黄档 · 需要你确认", red: "红档 · 需要强验证" };
export const SEVERITY_LABEL = { high: "高风险", medium: "中风险", low: "低风险" };

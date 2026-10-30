// 底部标签 + 子页面栈（子页面盖在当前标签上，有返回按钮）。
import { h, icon, clear, fill } from "./util.js";
import { state, emit } from "./store.js";
import { closeSheet } from "./sheet.js";

const TABS = [
  ["home", "首页", "home"], ["chat", "小安", "chat"], ["bills", "账单", "bill"], ["cards", "卡片", "card"], ["me", "我的", "me"],
];
const pages = {};
const stack = [];

export function registerPage(name, page) { pages[name] = page; }

export function buildTabbar() {
  const bar = document.getElementById("tabbar");
  clear(bar);
  for (const [name, label, ic] of TABS) {
    const b = h(`button.tab${name === "chat" ? ".tab-ai" : ""}`, { type: "button", dataset: { tab: name }, "aria-label": label, onclick: () => goTab(name) },
      h("span.tab-ic", null, icon(ic)), h("span.tab-label", { text: label }));
    bar.append(b);
  }
}

export function goTab(name) {
  closeSheet();
  while (stack.length) popPage(true);
  state.tab = name;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  const screen = document.getElementById("screen");
  const page = pages[name];
  screen.dataset.tab = name;
  fill(screen, page.el || (page.el = page.build()));
  page.show?.();
  emit("tab", name);
}

/** 打开子页面。build(container) 负责填充内容，可返回刷新函数。 */
export function pushPage(title, build) {
  const screen = document.getElementById("screen");
  const body = h("div.subpage-body");
  const page = h("section.subpage", { "aria-label": title },
    h("header.subpage-head", null,
      h("button.icon-btn", { type: "button", "aria-label": "返回", onclick: () => popPage() }, icon("back")),
      h("h1", { text: title }), h("span.sb-spacer")),
    body);
  screen.append(page);
  requestAnimationFrame(() => page.classList.add("in"));
  stack.push(page);
  build(body);
  return page;
}

export function popPage(instant = false) {
  const page = stack.pop();
  if (!page) return;
  if (instant) page.remove();
  else { page.classList.remove("in"); setTimeout(() => page.remove(), 200); }
  const top = pages[state.tab];
  if (!stack.length) top?.show?.();
}

export function topBar(title, right) {
  return h("header.page-head", null, h("h1", { text: title }), right || h("span"));
}

document.addEventListener("goto-tab", (e) => goTab(e.detail));

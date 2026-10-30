// 手机框内的底部弹出面板（一次只开一个）。
import { h, fill } from "./util.js";
import { emit } from "./store.js";

let current = null;

export function openSheet(content, { onClose, label } = {}) {
  closeSheet();
  const layer = document.getElementById("sheet-layer");
  const panel = h("div.sheet", { role: "dialog", "aria-modal": "true", "aria-label": label || "详情" }, h("div.sheet-grip"), content);
  const backdrop = h("div.sheet-backdrop", { onclick: () => closeSheet() });
  fill(layer, backdrop, panel);
  layer.hidden = false;
  requestAnimationFrame(() => layer.classList.add("open"));
  const onKey = (e) => { if (e.key === "Escape") closeSheet(); };
  document.addEventListener("keydown", onKey);
  current = { onClose, onKey };
  emit("sheet", true);
  panel.tabIndex = -1;
  panel.focus({ preventScroll: true });
}

export function closeSheet() {
  if (!current) return;
  const { onClose, onKey } = current;
  current = null;
  document.removeEventListener("keydown", onKey);
  const layer = document.getElementById("sheet-layer");
  layer.classList.remove("open");
  layer.replaceChildren();
  layer.hidden = true;
  onClose?.();
  emit("sheet", false);
}

export function sheetOpen() { return !!current; }

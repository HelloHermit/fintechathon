// 屏幕底部的短提示。
let timer;
export function toast(text, ms = 2600) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
  el.classList.add("show");
  clearTimeout(timer);
  timer = setTimeout(() => { el.classList.remove("show"); el.hidden = true; }, ms);
}

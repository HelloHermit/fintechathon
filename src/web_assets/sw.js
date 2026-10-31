// 小安 PWA 离线外壳：缓存页面与静态资源，断网时也能打开界面（会提示连接不上后端）。
// 安全约定：/api/ 下的任何请求一律不缓存（账户、交易、确认单都只来自服务端）。
const CACHE = "xiaoan-shell-v1";
const SHELL = [
  "/", "/assets/manifest.webmanifest", "/assets/icons/icon.svg", "/assets/icons/icon-192.png", "/assets/icons/icon-512.png",
  "/assets/app/styles.css", "/assets/app/main.js", "/assets/app/api.js", "/assets/app/store.js", "/assets/app/util.js",
  "/assets/app/turn.js", "/assets/app/nav.js", "/assets/app/sheet.js", "/assets/app/toast.js", "/assets/app/blocks.js",
  "/assets/app/charts.js", "/assets/app/plan.js", "/assets/app/pending.js", "/assets/app/trace.js", "/assets/app/chat.js",
  "/assets/app/home.js", "/assets/app/bills.js", "/assets/app/cards.js", "/assets/app/me.js", "/assets/app/demo.js", "/assets/app/sms.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return; // 交给网络，不缓存
  // 网络优先：联网时总是最新代码；断网时用缓存的外壳
  e.respondWith(fetch(req).then((res) => {
    if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/assets/"))) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(url.pathname === "/" ? "/" : req, copy));
    }
    return res;
  }).catch(() => caches.match(req.mode === "navigate" ? "/" : req).then((r) => r || caches.match("/"))));
});

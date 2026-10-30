"""黑盒 HTTP 客户端：只调用 docs/sprint/API_V2.md 里写明的 /api/v2 接口。"""
from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class HttpError(Exception):
    def __init__(self, status: int, body: dict | None):
        self.status = status
        self.body = body or {}
        err = self.body.get("error") or {}
        self.code = err.get("code")
        self.message = err.get("message")
        super().__init__(f"HTTP {status} {self.code}: {self.message}")


class Client:
    def __init__(self, base: str, timeout: float = 120.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None
        self.session = None
        self.rate_waits = 0
        self.rate_wait_s = 0.0

    # ---- 底层 ----
    def _req(self, method: str, path: str, body=None, headers=None, csrf=True):
        url = self.base + path
        data = None
        h = {"Accept": "application/json", "Origin": self.base}
        if method != "GET":
            data = json.dumps(body if body is not None else {}).encode("utf-8")
            h["Content-Type"] = "application/json"
            if csrf and self.csrf:
                h["X-CSRF-Token"] = self.csrf
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        t0 = time.time()
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except ValueError:
                payload = {"error": {"code": "non_json", "message": raw[:200].decode("utf-8", "replace")}}
            raise HttpError(e.code, payload) from None
        self.last_ms = int((time.time() - t0) * 1000)
        return json.loads(raw.decode("utf-8")) if raw else None

    def get(self, path, **q):
        q = {k: v for k, v in q.items() if v is not None}
        return self._req("GET", path + ("?" + urllib.parse.urlencode(q) if q else ""))

    def post(self, path, body=None, **kw):
        """HTTP 429（限流 / 动态码 60 秒内重发）时按提示等待后重试：评测跑得比真人快，不应把限流算成功能失败。"""
        for attempt in range(8):
            try:
                return self._req("POST", path, body, **kw)
            except HttpError as e:
                if e.status != 429 or attempt == 7:
                    raise
                err = e.body.get("error") or {}
                wait = err.get("resend_after_seconds") or (err.get("detail") or {}).get("retry_after_seconds") or err.get("retry_after_seconds") or 8
                wait = min(max(float(wait), 1.0), 65.0) + 0.5
                self.rate_waits += 1
                self.rate_wait_s += wait
                time.sleep(wait)

    # ---- 会话 ----
    def refresh_session(self):
        self.session = self.get("/api/v2/session")
        self.csrf = self.session.get("csrf_token")
        return self.session

    def reset(self):
        if not self.csrf:
            self.refresh_session()
        s = self.post("/api/v2/demo/reset", {})
        self.session = s
        self.csrf = s.get("csrf_token") or self.csrf
        return self.refresh_session()

    def switch_user(self, uid):
        s = self.post("/api/v2/demo/switch-user", {"user_id": uid})
        self.session = s
        self.csrf = s.get("csrf_token") or self.csrf
        return self.refresh_session()

    # ---- 便捷读取（绿档数据接口） ----
    def accounts(self):
        return {a["account_id"]: a for a in self.get("/api/v2/accounts")["accounts"]}

    def cards(self):
        return {c["card_id"]: c for c in self.get("/api/v2/cards")["cards"]}

    def holdings(self):
        return self.get("/api/v2/holdings")

    def scheduled(self):
        return self.get("/api/v2/scheduled")["items"]

    def notifications(self):
        return self.get("/api/v2/notifications")["items"]

    def sms(self):
        return self.get("/api/v2/sim-phone")["messages"]

    def pendings(self):
        return self.get("/api/v2/pending").get("items", [])

    def home(self):
        return self.get("/api/v2/home")

    def audit(self):
        return self.get("/api/v2/audit", limit=200)

    def plans(self):
        return self.get("/api/v2/plans")["plans"]

    def transactions_all(self, **q):
        items, cursor = [], None
        for _ in range(50):
            r = self.get("/api/v2/transactions", limit=200, cursor=cursor, **q)
            items.extend(r.get("items", []))
            cursor = r.get("next_cursor")
            if not cursor:
                break
        return items

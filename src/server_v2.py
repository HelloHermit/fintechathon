"""HTTP API v2（docs/sprint/API_V2.md）+ 静态前端。

- ThreadingHTTPServer：等模型时 /sim-phone、/home 等仍能响应；内核操作由内核锁串行。
- 所有 POST 需要 X-CSRF-Token；同源检查（Host / Origin / Sec-Fetch-Site）；正文 ≤ 16KB；JSON 不许重复字段。
- 静态文件白名单在启动时由 src/web_assets/ 目录生成，拒绝 ..、绝对路径和符号链接逃逸。
"""

import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agent.orchestrator import Agent
from .core import views
from .core.kernel import Kernel, RuleError
from .core.util import iso, parse_iso

ASSET_DIR = Path(__file__).resolve().parent / "web_assets"
MAX_BODY = 16384
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".webmanifest": "application/manifest+json", ".woff2": "font/woff2", ".ico": "image/x-icon",
                 ".jpg": "image/jpeg", ".webp": "image/webp", ".txt": "text/plain; charset=utf-8", ".mp4": "video/mp4"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; "
       "manifest-src 'self'; media-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def build_asset_index(root=ASSET_DIR):
    """启动时生成静态文件白名单：只收录真实文件，不跟随符号链接，不出根目录。"""
    index = {}
    if not root.is_dir():
        return index
    root_resolved = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
        except (ValueError, OSError):
            continue
        if path.suffix.lower() not in CONTENT_TYPES:
            continue
        index[path.relative_to(root).as_posix()] = resolved
    return index


class App:
    """进程内的应用状态：内核、智能体、当前演示身份、CSRF 令牌、限流。"""

    def __init__(self, kernel, agent, *, demo=True, allowed_hosts=(), model_status=None):
        self.kernel, self.agent, self.demo = kernel, agent, demo
        self.user_id = "alice"
        self.csrf = secrets.token_urlsafe(32)
        self.allowed_hosts = set(h.strip() for h in allowed_hosts if h.strip())
        self.assets = build_asset_index()
        self.model_status = model_status or (lambda: {"configured": False, "name": "", "mode": "unavailable"})
        self.rate = {}
        self.rate_lock = threading.Lock()

    def allow(self, key, limit=40, window=60):
        now = time.monotonic()
        with self.rate_lock:
            hits = [t for t in self.rate.get(key, []) if now - t < window]
            if len(hits) >= limit:
                self.rate[key] = hits
                return False
            hits.append(now)
            self.rate[key] = hits
            return True

    def session(self):
        k = self.kernel
        return {"user": k.user_public(self.user_id), "csrf_token": self.csrf, "model": self.model_status(),
                "demo": {"enabled": self.demo, "now": iso(k.now()), "users": k.users_public()},
                "simulated": True, "version": "2.0"}


class Handler(BaseHTTPRequestHandler):
    server_version = "MockBank/2.0"
    sys_version = ""

    def log_message(self, fmt, *args):  # 不记录请求正文、令牌
        pass

    @property
    def app(self):
        return self.server.app

    # ------------------------------------------------------------------ 发送
    def _send(self, status, payload, content_type="application/json; charset=utf-8", cache="no-store"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, code, message):
        self._send(status, {"error": {"code": code, "message": message}})

    def _source_ok(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            return False
        host = hosts[0]
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"} | self.app.allowed_hosts
        if host not in allowed:
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1:
            return False
        if origins and origins[0] not in ("http://" + host, "https://" + host):
            return False
        return True

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        try:
            if not self._source_ok():
                return self._error(403, "forbidden", "来源校验未通过。")
            parsed = urlparse(self.path)
            path, query = parsed.path, {k: v[-1] for k, v in parse_qs(parsed.query).items()}
            if path.startswith("/api/v2/"):
                with self.app.kernel.lock:  # 只读接口都很快；加锁避免和演示重置、调度器交错
                    return self._api_get(path[len("/api/v2/"):], query)
            if path == "/" or path == "/index.html":
                return self._asset("index.html")
            if path in ("/manifest.webmanifest", "/sw.js", "/favicon.ico"):
                return self._asset(path[1:])
            if path.startswith("/assets/"):
                return self._asset(path[len("/assets/"):])
            return self._error(404, "not_found", "没有这个页面。")
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self._error(500, "internal", "服务暂时不可用，未报告任何业务成功。")

    def _asset(self, rel):
        if ".." in rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
            return self._error(404, "not_found", "没有这个文件。")
        target = self.app.assets.get(rel)
        if target is None:
            self.app.assets = build_asset_index()  # 开发时 B 新增文件不必重启
            target = self.app.assets.get(rel)
        if target is None or not target.is_file():
            return self._error(404, "not_found", "没有这个文件。")
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), content_type, cache="no-cache")

    def _api_get(self, route, q):
        app, k = self.app, self.app.kernel
        uid = app.user_id
        k.tick()
        if route == "session":
            return self._send(200, app.session())
        if route == "home":
            return self._send(200, views.home(k, uid))
        if route == "sim-phone":
            return self._send(200, {"messages": k.sms_inbox(uid), "simulated": True})
        if route == "notifications":
            return self._send(200, {"items": k.notifications(uid)})
        if route == "accounts":
            return self._send(200, {"accounts": views.accounts(k, uid)})
        if route == "transactions":
            now = k.now()
            try:
                start = parse_iso(q["from"]) if q.get("from") else parse_iso("2025-01-01T00:00:00+08:00")
                end = parse_iso(q["to"]) if q.get("to") else now
            except ValueError:
                return self._error(400, "invalid_request", "日期格式应为 ISO 8601。")
            limit = int(q["limit"]) if q.get("limit", "").isdigit() else 50
            result = k.analytics.search(uid, start, end, category=q.get("category"), keyword=q.get("q"),
                                        limit=max(1, min(200, limit)), cursor=q.get("cursor"))
            return self._send(200, {"items": result["items"], "next_cursor": result["next_cursor"], "total_count": result["count"]})
        if route == "reports/monthly":
            month = q.get("month") or k.now().strftime("%Y-%m")
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
                return self._error(400, "invalid_request", "month 格式应为 YYYY-MM。")
            return self._send(200, k.analytics.monthly_report(uid, month))
        if route == "reports/annual":
            if q.get("last12") == "1":
                return self._send(200, k.analytics.annual_report(uid, None))
            year = q.get("year") or str(k.now().year)
            if not re.fullmatch(r"[0-9]{4}", year):
                return self._error(400, "invalid_request", "year 格式应为 YYYY。")
            return self._send(200, k.analytics.annual_report(uid, int(year)))
        if route == "cards":
            return self._send(200, {"cards": views.cards(k, uid)})
        if route == "products":
            items, disclaimer = views.products(k)
            return self._send(200, {"products": items, "disclaimer": disclaimer})
        if route == "holdings":
            return self._send(200, {"holdings": views.holdings(k, uid), "risk_profile": views.risk_profile(k, uid)})
        if route == "scheduled":
            return self._send(200, {"items": views.scheduled(k, uid)})
        if route == "plans":
            return self._send(200, {"plans": k.ops.plan_summaries(uid) if hasattr(k.ops, "plan_summaries") else []})
        if route.startswith("plans/"):
            plan_id = route[len("plans/"):]
            plan = k.ops.plan_view(uid, plan_id) if hasattr(k.ops, "plan_view") else None
            if plan is None:
                return self._error(404, "not_found", "没有找到这个计划。")
            return self._send(200, plan)
        if route == "audit":
            limit = int(q["limit"]) if q.get("limit", "").isdigit() else 50
            return self._send(200, k.audit_events(uid, max(1, min(200, limit))))
        if route.startswith("turns/"):
            try:
                return self._send(200, k.turn(uid, route[len("turns/"):]))
            except RuleError as error:
                return self._error(404, "not_found", error.message)
        if route == "pending":
            return self._send(200, {"items": k.open_pendings(uid)})
        return self._error(404, "not_found", "没有这个接口。")

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        try:
            if not self._source_ok():
                return self._error(403, "forbidden", "来源校验未通过。")
            tokens = self.headers.get_all("X-CSRF-Token", [])
            if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode(), self.app.csrf.encode()):
                return self._error(403, "forbidden", "CSRF 校验未通过，请刷新页面。")
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                return self._error(400, "invalid_request", "请求必须是 JSON。")
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or not 0 < int(length) <= MAX_BODY:
                return self._error(400, "invalid_request", "请求体大小不合法。")
            raw = self.rfile.read(int(length))

            def unique(pairs):
                out = {}
                for key, value in pairs:
                    if key in out:
                        raise ValueError("duplicate")
                    out[key] = value
                return out

            body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=lambda c: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                return self._error(400, "invalid_request", "请求体必须是对象。")
            path = urlparse(self.path).path
            if not path.startswith("/api/v2/"):
                return self._error(404, "not_found", "没有这个接口。")
            return self._api_post(path[len("/api/v2/"):], body)
        except (ValueError, UnicodeDecodeError):
            self._error(400, "invalid_request", "请求格式不正确。")
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self._error(500, "internal", "服务暂时不可用，未报告任何业务成功。")

    def _str(self, body, key, max_len=64, required=True):
        value = body.get(key)
        if value is None and not required:
            return None
        if type(value) is not str or not 1 <= len(value) <= max_len:
            raise ValueError(key)
        return value

    def _api_post(self, route, body):
        app, k, agent = self.app, self.app.kernel, self.app.agent
        uid = app.user_id
        client = self.client_address[0]
        if route == "chat":
            text = body.get("text")
            if set(body) != {"text"} or type(text) is not str or not 1 <= len(text.strip()) <= 500:
                return self._error(400, "invalid_request", "消息需要 1–500 个字。")
            if not app.allow(("chat", client), int(os.environ.get("FINTECH_CHAT_RATE_PER_MIN", "60")), 60):
                return self._error(429, "rate_limited", "发送太频繁了，请稍后再试。")
            return self._send(200, agent.chat(uid, text.strip()))
        if route == "confirm":
            if not set(body) <= {"request_id", "confirmation_code", "risk_acknowledged"}:
                raise ValueError("fields")
            return self._send(200, agent.kernel_call(uid, k.confirm, self._str(body, "request_id"),
                                                     self._str(body, "confirmation_code", 12),
                                                     risk_acknowledged=body.get("risk_acknowledged") is True))
        if route == "strong-auth/send-otp":
            if set(body) != {"request_id"}:
                raise ValueError("fields")
            try:
                return self._send(200, k.send_otp(uid, self._str(body, "request_id")))
            except RuleError as error:
                status = 429 if error.code == "rate_limited" else 400
                code = "expired" if error.code in ("expired", "duplicate", "not_found") else error.code
                return self._send(status, {"error": {"code": code, "message": error.message, "reason": error.code, **error.detail}})
        if route == "strong-auth/verify":
            if not set(body) <= {"request_id", "pin", "otp", "risk_acknowledged"}:
                raise ValueError("fields")
            return self._send(200, agent.kernel_call(uid, k.verify_strong, self._str(body, "request_id"),
                                                     self._str(body, "pin", 12), self._str(body, "otp", 12),
                                                     risk_acknowledged=body.get("risk_acknowledged") is True))
        if route == "cancel":
            if set(body) != {"request_id"}:
                raise ValueError("fields")
            return self._send(200, agent.kernel_call(uid, k.cancel, self._str(body, "request_id")))
        if route == "pending/revise":
            changes = body.get("changes")
            if set(body) != {"request_id", "changes"} or not isinstance(changes, dict) or set(changes) != {"arrival"}:
                raise ValueError("fields")
            return self._send(200, agent.kernel_call(uid, k.revise_arrival, self._str(body, "request_id"), changes["arrival"]))
        if route == "action":
            kind, ref = body.get("type"), body.get("ref")
            if kind not in ("option_select", "insight_accept", "form_submit", "block_action") or type(ref) is not str or len(ref) > 80:
                raise ValueError("fields")
            return self._send(200, agent.action(uid, kind, ref, body.get("value")))
        if route == "quick-intent":
            intent, params = body.get("intent"), body.get("params", {})
            if type(intent) is not str or len(intent) > 40 or not isinstance(params, dict):
                raise ValueError("fields")
            return self._send(200, agent.quick_intent(uid, intent, params))
        if route == "plan/control":
            if set(body) != {"plan_id", "action"} or body.get("action") not in ("pause", "resume", "rollback", "takeover"):
                raise ValueError("fields")
            return self._send(200, agent.plan_control(uid, self._str(body, "plan_id"), body["action"]))
        if route.startswith("demo/"):
            if not app.demo:
                return self._error(403, "forbidden", "演示接口未开启。")
            if route == "demo/advance-clock":
                before = iso(k.now())
                try:
                    if set(body) == {"minutes"} and type(body["minutes"]) is int:
                        result = k.advance_clock(minutes=body["minutes"])
                    elif set(body) == {"to"} and type(body["to"]) is str:
                        result = k.advance_clock(to=body["to"])
                    else:
                        raise ValueError("fields")
                except RuleError as error:
                    return self._error(400, "invalid_request", error.message)
                # 只返回当前演示身份的通知（王磊的到账通知在切换身份后可见）
                result["executed"] = [n for n in k.notifications(uid, 100) if n["time"] >= before][::-1]
                return self._send(200, result)
            if route == "demo/reset":
                with agent.user_lock("alice"), agent.user_lock("bob"):
                    k.reset()
                    agent.reset_memory()
                    app.user_id = "alice"
                return self._send(200, app.session())
            if route == "demo/switch-user":
                if body.get("user_id") not in ("alice", "bob") or set(body) != {"user_id"}:
                    raise ValueError("fields")
                app.user_id = body["user_id"]
                return self._send(200, app.session())
        return self._error(404, "not_found", "没有这个接口。")

    def do_PUT(self):
        self._error(405, "invalid_request", "不支持的方法。")

    do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_PUT


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(app, host="127.0.0.1", port=8765):
    server = Server((host, port), Handler)
    server.app = app
    return server


def start_scheduler(kernel, stop_event, interval=5):
    """后台调度器：每隔几秒执行到期的定时任务与延时到账。"""
    def loop():
        while not stop_event.wait(interval):
            try:
                kernel.tick()
            except Exception:
                traceback.print_exc()
    thread = threading.Thread(target=loop, name="scheduler", daemon=True)
    thread.start()
    return thread

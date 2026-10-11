"""本机浏览器演示入口：固定模拟身份，复用同一套代码权限与工具。"""

import argparse
import hmac
import json
import secrets
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .bank import BankService
from .model import ModelClient, ModelError

ASSET_DIRECTORY = Path(__file__).resolve().parent / "web_assets"
MAX_BODY_BYTES = 8192


class UnavailableModel:
    """缺配置时仍走业务层失败审计，不生成替身候选。"""
    def __init__(self, error):
        self.error = error

    def propose(self, text, context):
        raise self.error


class LocalServer(HTTPServer):
    """只绑定回环；单线程顺序处理，SQLite与确认状态在同一线程。"""
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class BrowserHandler(BaseHTTPRequestHandler):
    """不记录请求正文/认证头，所有动态文本由前端按纯文本显示。"""
    def log_message(self, format, *arguments):
        pass

    def _send(self, status, payload, content_type="application/json; charset=utf-8"):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8") if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(content)

    def _deny(self, status=400, reason="invalid_http_request"):
        response = self.server.bank.reject_request(reason)
        self._send(503 if response.get("status") == "failed" else status, response)

    def _allowed_source(self):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if len(self.headers.get_all("Host", [])) != 1 or len(self.headers.get_all("Origin", [])) > 1:
            return False
        if host not in allowed_hosts:
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == "http://" + host

    def do_GET(self):
        try:
            if not self._allowed_source():
                return self._deny(403, "http_access_denied")
            if self.path == "/api/session":
                return self._send(200, {"user_id": self.server.bank.user_id,
                                        "csrf_token": self.server.csrf_token,
                                        "model_configured": self.server.model_configured,
                                        "simulated": True})
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.css": ("app.css", "text/css; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            if self.path not in assets:
                return self._deny(404)
            filename, content_type = assets[self.path]
            self._send(200, (ASSET_DIRECTORY / filename).read_bytes(), content_type)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            self._send(503, {"status": "failed", "reason": "web_unavailable", "message": "本机入口暂时不可用，未报告业务成功。"})

    def do_POST(self):
        try:
            supplied_token = self.headers.get("X-CSRF-Token", "")
            if len(self.headers.get_all("X-CSRF-Token", [])) != 1 or not self._allowed_source() or not hmac.compare_digest(supplied_token.encode("utf-8"), self.server.csrf_token.encode("ascii")):
                return self._deny(403, "http_access_denied")
            if self.path not in {"/api/message", "/api/confirm", "/api/cancel", "/api/plan/resume", "/api/plan/interrupt", "/api/plan/takeover", "/api/audit"}:
                return self._deny(404)
            if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                return self._deny()
            content_length = self.headers.get("Content-Length", "")
            if not content_length.isascii() or not content_length.isdigit() or not 0 < int(content_length) <= MAX_BODY_BYTES:
                return self._deny()
            content = self.rfile.read(int(content_length))
            if len(content) != int(content_length):
                return self._deny()
            def unique_fields(pairs):
                result = {}
                for name, value in pairs:
                    if name in result:
                        raise ValueError("duplicate fields")
                    result[name] = value
                return result
            def reject_nonfinite(value):
                raise ValueError("non-finite number")
            body = json.loads(content.decode("utf-8"), object_pairs_hook=unique_fields,
                              parse_constant=reject_nonfinite)
            if type(body) is not dict:
                return self._deny()
            bank = self.server.bank
            if self.path == "/api/message" and set(body) == {"text"} and type(body["text"]) is str:
                response = bank.handle_text(body["text"], self.server.model)
            elif self.path == "/api/confirm" and set(body) == {"request_id", "confirmation_code"}:
                response = bank.confirm(body["request_id"], body["confirmation_code"])
            elif self.path == "/api/cancel" and set(body) <= {"request_id"}:
                response = bank.cancel(body.get("request_id"))
            elif self.path in {"/api/plan/resume", "/api/plan/interrupt", "/api/plan/takeover"} and set(body) == {"plan_id"} and type(body["plan_id"]) is str and len(body["plan_id"]) <= 80:
                methods = {"/api/plan/resume": bank.resume_plan, "/api/plan/interrupt": bank.interrupt_plan, "/api/plan/takeover": bank.takeover_plan}
                response = methods[self.path](body["plan_id"])
            elif self.path == "/api/audit" and body == {}:
                audit = bank.audit_events()
                response = {"status": "failed" if bank.halted else "success", "data": audit, "simulated": True}
            else:
                return self._deny()
            self._send(200, response)
        except (ValueError, UnicodeDecodeError):
            self._deny()
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception:
            self._send(503, {"status": "failed", "reason": "web_unavailable", "message": "本次请求未报告成功，请核对审计回执。"})

    def do_OPTIONS(self):
        self._deny(405, "http_access_denied")

    do_PUT = do_OPTIONS
    do_DELETE = do_OPTIONS
    do_PATCH = do_OPTIONS
    do_TRACE = do_OPTIONS
    do_HEAD = do_OPTIONS


def main():
    parser = argparse.ArgumentParser(description="本机浏览器模拟银行助手")
    parser.add_argument("--db", default="data/bank.db")
    parser.add_argument("--user", choices=("alice", "bob"), default="alice")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    if not 1024 <= arguments.port <= 65535:
        parser.error("端口必须为1024至65535")
    bank = BankService(arguments.db, arguments.user)
    server = None
    try:
        server = LocalServer(("127.0.0.1", arguments.port), BrowserHandler)
        server.bank = bank
        server.csrf_token = secrets.token_urlsafe(32)
        try:
            server.model = ModelClient()
            server.model_configured = True
        except ModelError as error:
            server.model = UnavailableModel(error)
            server.model_configured = False
        print(f"本机浏览器入口 http://127.0.0.1:{arguments.port}；当前模拟用户 {arguments.user}。", flush=True)
        print("所有银行数据与资金操作模拟；按Ctrl+C停止，重启不清业务数据。", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError:
        print("本机服务未能启动，请核对端口占用和文件权限。")
        return 1
    finally:
        if server is not None:
            server.server_close()
        bank.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

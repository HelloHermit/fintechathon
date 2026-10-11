"""Independent, offline HTTP acceptance authored from public contracts only.

Design sources: AGENTS.md, docs/01, docs/02, src/PUBLIC_API.md and WEB_API.md.
The author does not read business/web/model implementation or local credentials.
FixedCandidateModel is an offline double: these tests are NOT real AI evidence.
Every test uses a new tests/.runs SQLite file, never the normal data/bank.db.
Run: python -m unittest discover -s tests -p test_web_acceptance.py -v
"""

from __future__ import annotations

import copy
import http.client
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.bank import BankService
from src.web import BrowserHandler, LocalServer


SHANGHAI = timezone(timedelta(hours=8))


class FixedCandidateModel:
    """Return independently specified candidates without network or configuration."""

    def __init__(self):
        transfer = {
            "intent": "transfer",
            "params": {
                "account_id": "alice-main", "contact_id": "wang", "amount_cents": 10000,
            },
        }
        self.candidates = {
            "给小王转100元": transfer,
            "我的账户余额": {"intent": "query_balance", "params": {}},
            "查询本月账单": {"intent": "analyze_bills", "params": {}},
            "查询自动扣款": {"intent": "query_subscriptions", "params": {}},
            "取消视频会员": {
                "intent": "cancel_subscription", "params": {"subscription_id": "sub-video"},
            },
            "创建依赖计划": {"steps": [
                {"id": "bill", "intent": "analyze_bills", "params": {}, "depends_on": []},
                {"id": "subs", "intent": "query_subscriptions", "params": {}, "depends_on": ["bill"]},
            ]},
        }
        self.calls = []

    def propose(self, text, context):
        self.calls.append(copy.deepcopy({"text": text, "context": context}))
        return copy.deepcopy(self.candidates.get(
            text, {"intent": "query_balance", "params": {}}
        ))


class WebAcceptanceTests(unittest.TestCase):
    """Verify HTTP guards independently of fixed business and model internals."""

    def setUp(self):
        run_directory = Path(__file__).resolve().parent / ".runs"
        run_directory.mkdir(parents=True, exist_ok=True)
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="http-acceptance-", dir=run_directory
        )
        self.database_path = str(Path(self.temporary_directory.name) / "http.sqlite3")
        self.model = FixedCandidateModel()
        self.csrf_token = "independent-offline-csrf-NoDisclosure-71f2"
        self.server = None
        self.startup_ready = threading.Event()
        self.startup_errors = []
        self.server_output = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.addCleanup(self.temporary_directory.cleanup)
        self.addCleanup(self.stop_server)
        self.thread.start()
        self.assertTrue(self.startup_ready.wait(5), "HTTP test server did not become ready")
        self.assertFalse(self.startup_errors, "Public HTTP test startup failed")

    def serve(self):
        """Construct, use and close SQLite in its owning server thread."""
        bank = None
        try:
            self.server = LocalServer(("127.0.0.1", 0), BrowserHandler)
            self.port = self.server.server_port
            self.host = f"127.0.0.1:{self.port}"
            bank = BankService(
                self.database_path,
                user_id="alice",
                clock=lambda: datetime(2026, 10, 10, 12, 0, tzinfo=SHANGHAI),
            )
            self.server.bank = bank
            self.server.csrf_token = self.csrf_token
            self.server.model = self.model
            # Dependency availability for this offline double only, not a real API claim.
            self.server.model_configured = True
            self.startup_ready.set()
            self.server.serve_forever(poll_interval=0.05)
        except Exception as error:
            self.startup_errors.append(type(error).__name__)
            self.startup_ready.set()
        finally:
            if self.server is not None:
                self.server.server_close()
            if bank is not None:
                bank.close()

    def stop_server(self):
        """Explicitly stop and join before releasing a test database directory."""
        if self.thread.is_alive() and self.server is not None:
            self.server.shutdown()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive(), "HTTP worker failed to terminate")
        self.assertFalse(self.startup_errors, "HTTP worker raised an exception")

    def query_rows(self, statement, parameters=()):
        """Read only SQLite tables documented as public acceptance evidence."""
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(statement, parameters)]

    def business_snapshot(self):
        return {
            table: self.query_rows(f"SELECT * FROM {table} ORDER BY 1")
            for table in ("accounts", "subscriptions", "transactions", "transfers")
        }

    def exchange(self, method, path, *, body=b"", headers=None, raw_headers=None):
        """Send actual loopback HTTP, with optional absent/malformed framing headers."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        output = io.StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(output):
                connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
                if raw_headers is not None:
                    outgoing = raw_headers
                else:
                    outgoing = {"Host": self.host, "Connection": "close"}
                    if method != "GET":
                        outgoing.update({
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "X-CSRF-Token": self.csrf_token,
                        })
                    outgoing.update(headers or {})
                    outgoing = [(key, value) for key, value in outgoing.items() if value is not None]
                for name, value in outgoing:
                    connection.putheader(name, value)
                connection.endheaders(body)
                response = connection.getresponse()
                response_body = response.read()
                result = (
                    response.status,
                    {name.lower(): value for name, value in response.getheaders()},
                    response_body,
                )
            return result
        finally:
            self.server_output.append(output.getvalue())
            connection.close()

    def post(self, path, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, response_headers, response_body = self.exchange(
            "POST", path, body=body, headers=headers
        )
        self.assertEqual(status, 200, "Well-formed same-origin POST must reach the business API")
        self.assert_security_headers(response_headers)
        response = json.loads(response_body)
        self.assertIsInstance(response, dict)
        return response

    def assert_security_headers(self, headers):
        self.assertIn("no-store", headers.get("cache-control", "").lower())
        self.assertEqual(headers.get("x-content-type-options", "").lower(), "nosniff")
        self.assertEqual(headers.get("x-frame-options", "").upper(), "DENY")
        policy = headers.get("content-security-policy", "")
        self.assertTrue(policy, "Every response must have CSP")
        directives = {
            parts[0]: parts[1:]
            for segment in policy.split(";")
            if (parts := segment.strip().split())
        }
        for name in ("script-src", "style-src", "connect-src"):
            allowed = directives.get(name, directives.get("default-src", []))
            self.assertIn("'self'", allowed, f"{name} must permit only this local application")
            self.assertFalse(any(
                item == "*" or item.startswith(("http:", "https:", "//"))
                for item in allowed
            ), f"{name} must not permit external hosts/CDNs")
        self.assertFalse(any(key.startswith("access-control-") for key in headers), "No CORS allowance")

    def pending_transfer(self):
        before = self.business_snapshot()
        response = self.post("/api/message", {"text": "给小王转100元"})
        self.assertEqual(response.get("status"), "pending")
        self.assertEqual(response.get("tier"), "yellow")
        self.assertTrue(response.get("request_id"))
        self.assertTrue(isinstance(response.get("confirmation_code"), str))
        self.assertTrue(response["confirmation_code"].isdigit())
        self.assertEqual(len(response["confirmation_code"]), 6)
        self.assertEqual(self.business_snapshot(), before)
        self.assertIn("operation", response)
        self.assertIn("bob-main", json.dumps(response["operation"], ensure_ascii=False))
        return response

    def confirm(self, pending):
        return self.post("/api/confirm", {
            "request_id": pending["request_id"],
            "confirmation_code": pending["confirmation_code"],
        })

    def assert_boundary_rejection(self, pending, method, path, expected, **kwargs):
        """A transport refusal must append audit but preserve the active authorization."""
        before = self.business_snapshot()
        pending_before = self.query_rows(
            "SELECT * FROM requests WHERE request_id=?", (pending["request_id"],)
        )
        audit_before = self.query_rows("SELECT * FROM audit_log ORDER BY id")
        model_calls_before = len(self.model.calls)
        status, headers, _ = self.exchange(method, path, **kwargs)
        if isinstance(expected, tuple):
            self.assertIn(status, expected)
        else:
            self.assertEqual(status, expected)
        self.assert_security_headers(headers)
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(self.query_rows(
            "SELECT * FROM requests WHERE request_id=?", (pending["request_id"],)
        ), pending_before, "HTTP guard must not reset the existing pending request")
        self.assertEqual(len(self.model.calls), model_calls_before)
        audit_after = self.query_rows("SELECT * FROM audit_log ORDER BY id")
        self.assertEqual(audit_after[:len(audit_before)], audit_before)
        self.assertGreater(len(audit_after), len(audit_before), "Each guard refusal needs appended audit")
        added = audit_after[len(audit_before):]
        self.assertTrue(any(row["result"] == "rejected" for row in added))
        self.assertTrue(all(row["user_id"] == "alice" for row in added))

    def finish_after_guards(self, pending):
        response = self.confirm(pending)
        self.assertEqual(response.get("status"), "success", "Transport guards must preserve valid confirmation")

    def test_static_resources_have_local_security_headers(self):
        for path, content_type in (("/", "text/html"), ("/app.css", "text/css"), ("/app.js", "javascript")):
            with self.subTest(path=path):
                status, headers, body = self.exchange("GET", path)
                self.assertEqual(status, 200)
                self.assert_security_headers(headers)
                self.assertIn(content_type, headers.get("content-type", ""))
                self.assertTrue(body)
                self.assertTrue(self.csrf_token.encode() not in body, "Static files must not embed session secrets")

    def test_session_has_fixed_identity_and_no_configuration_or_bank_details(self):
        before = self.business_snapshot()
        status, headers, body = self.exchange("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assert_security_headers(headers)
        session = json.loads(body)
        self.assertEqual(set(session), {"user_id", "csrf_token", "model_configured", "simulated"})
        self.assertEqual(session["user_id"], "alice")
        self.assertTrue(session["csrf_token"] == self.csrf_token, "Session must return its own token")
        self.assertIs(session["simulated"], True)
        self.assertIsInstance(session["model_configured"], bool)
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(self.model.calls, [])

    def test_unknown_and_traversal_get_paths_are_audited_404_without_pending_reset(self):
        pending = self.pending_transfer()
        for path in ("/missing", "/.env", "/src/bank.py", "/data/bank.db", "/../AGENTS.md", "/%2e%2e/AGENTS.md", "/app.js/../../.env"):
            with self.subTest(path=path):
                self.assert_boundary_rejection(pending, "GET", path, 404)
        self.finish_after_guards(pending)

    def test_unknown_post_and_candidate_sql_shell_paths_are_not_tools(self):
        pending = self.pending_transfer()
        for path in ("/candidate", "/api/candidate", "/api/sql", "/api/shell", "/api/unknown"):
            with self.subTest(path=path):
                self.assert_boundary_rejection(pending, "POST", path, 404, body=b"{}")
        self.finish_after_guards(pending)

    def test_missing_or_wrong_csrf_is_403_and_keeps_pending(self):
        pending = self.pending_transfer()
        for token in (None, "wrong-independent-token"):
            with self.subTest(token_missing=token is None):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 403,
                    body=b'{"text":"balance"}', headers={"X-CSRF-Token": token},
                )
        self.finish_after_guards(pending)

    def test_untrusted_host_is_403_and_keeps_pending(self):
        pending = self.pending_transfer()
        for host in (None, "evil.example", f"evil.example:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}"):
            with self.subTest(host=host):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 403,
                    body=b'{"text":"balance"}', headers={"Host": host},
                )
        self.finish_after_guards(pending)

    def test_cross_origin_is_403_and_keeps_pending(self):
        pending = self.pending_transfer()
        for origin in ("null", "https://evil.example", f"https://{self.host}", f"http://localhost:{self.port}"):
            with self.subTest(origin=origin):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 403,
                    body=b'{"text":"balance"}', headers={"Origin": origin},
                )
        self.finish_after_guards(pending)

    def test_cross_site_and_same_site_fetch_metadata_are_403(self):
        pending = self.pending_transfer()
        for site in ("cross-site", "same-site"):
            with self.subTest(site=site):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 403,
                    body=b'{"text":"balance"}', headers={"Sec-Fetch-Site": site},
                )
        self.finish_after_guards(pending)

    def test_localhost_host_with_matching_origin_is_accepted(self):
        response = self.post("/api/message", {"text": "我的账户余额"}, headers={
            "Host": f"localhost:{self.port}",
            "Origin": f"http://localhost:{self.port}", "Sec-Fetch-Site": "same-origin",
        })
        self.assertEqual(response.get("status"), "success")
        self.assertEqual({account["account_id"] for account in response["data"]["accounts"]}, {"alice-main", "alice-savings"})

    def test_extra_identity_or_authorization_fields_are_400_for_every_post_api(self):
        pending = self.pending_transfer()
        bodies = {
            "/api/message": {"text": "我的账户余额"},
            "/api/confirm": {"request_id": pending["request_id"], "confirmation_code": pending["confirmation_code"]},
            "/api/cancel": {}, "/api/audit": {},
            "/api/plan/resume": {"plan_id": "not-authorized-plan"},
            "/api/plan/interrupt": {"plan_id": "not-authorized-plan"},
            "/api/plan/takeover": {"plan_id": "not-authorized-plan"},
        }
        for path, payload in bodies.items():
            for field, value in (("user_id", "bob"), ("confirmed", True)):
                with self.subTest(path=path, field=field):
                    self.assert_boundary_rejection(
                        pending, "POST", path, 400,
                        body=json.dumps(dict(payload, **{field: value})).encode(),
                    )
        self.finish_after_guards(pending)

    def test_duplicate_json_fields_are_400_and_do_not_call_model(self):
        pending = self.pending_transfer()
        for body in (b'{"text":"first","text":"second"}', b'{"text":"balance","extra":{"id":1,"id":2}}'):
            with self.subTest(body_case="duplicate top-level" if b"first" in body else "duplicate nested"):
                self.assert_boundary_rejection(pending, "POST", "/api/message", 400, body=body)
        self.finish_after_guards(pending)

    def test_nonfinite_json_numbers_are_400_and_keep_pending(self):
        pending = self.pending_transfer()
        for value in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(number=value.decode()):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 400, body=b'{"text":' + value + b'}'
                )
        self.finish_after_guards(pending)

    def test_nonobject_malformed_or_invalid_utf8_json_is_400(self):
        pending = self.pending_transfer()
        for body in (b"[]", b"null", b'"text"', b"123", b"true", b"{", b'{"text":"\xff"}'):
            with self.subTest(body_kind=body[:10].hex()):
                self.assert_boundary_rejection(pending, "POST", "/api/message", 400, body=body)
        self.finish_after_guards(pending)

    def test_wrong_content_type_is_400_and_keeps_pending(self):
        pending = self.pending_transfer()
        for content_type in (None, "text/plain", "application/x-www-form-urlencoded"):
            with self.subTest(content_type=content_type):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 400,
                    body=b'{"text":"balance"}', headers={"Content-Type": content_type},
                )
        self.finish_after_guards(pending)

    def test_absent_zero_negative_invalid_or_oversize_content_length_is_400(self):
        pending = self.pending_transfer()
        for length in (None, "0", "-1", "not-a-number", "8193"):
            with self.subTest(content_length=length):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 400,
                    body=b"{}", headers={"Content-Length": length},
                )
        self.finish_after_guards(pending)

    def test_exact_8192_bytes_are_allowed_and_8193_are_rejected(self):
        body = json.dumps({"text": "我的账户余额"}, ensure_ascii=False).encode("utf-8")
        body += b" " * (8192 - len(body))
        self.assertEqual(len(body), 8192)
        status, _, response_body = self.exchange("POST", "/api/message", body=body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response_body).get("status"), "success")
        pending = self.pending_transfer()
        self.assert_boundary_rejection(pending, "POST", "/api/message", 400, body=body + b" ")
        self.finish_after_guards(pending)

    def test_transfer_encoding_is_400_even_with_content_length(self):
        pending = self.pending_transfer()
        for encoding in ("chunked", "identity"):
            with self.subTest(encoding=encoding):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 400,
                    body=b"{}", headers={"Transfer-Encoding": encoding},
                )
        self.assert_boundary_rejection(
            pending, "POST", "/api/message", 400, body=b"0\r\n\r\n",
            headers={"Transfer-Encoding": "chunked", "Content-Length": None},
        )
        self.finish_after_guards(pending)

    def test_duplicate_security_headers_are_rejected_without_pending_reset(self):
        pending = self.pending_transfer()
        for name, value in (
            ("Host", self.host), ("Origin", f"http://{self.host}"),
            ("X-CSRF-Token", self.csrf_token), ("Content-Length", "2"),
        ):
            with self.subTest(header=name):
                outgoing = [
                    ("Host", self.host), ("Connection", "close"),
                    ("Content-Type", "application/json"), ("Content-Length", "2"),
                    ("X-CSRF-Token", self.csrf_token), ("Origin", f"http://{self.host}"),
                    (name, value),
                ]
                # The contract requires refusal; it does not specify 400/403 precedence.
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", (400, 403),
                    body=b"{}", raw_headers=outgoing,
                )
        self.finish_after_guards(pending)

    def test_unsupported_http_methods_are_audited_and_keep_pending(self):
        pending = self.pending_transfer()
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"):
            with self.subTest(method=method):
                self.assert_boundary_rejection(pending, method, "/api/message", 405, body=b"{}")
        self.finish_after_guards(pending)

    def test_wrong_message_fields_or_value_types_are_400(self):
        pending = self.pending_transfer()
        for payload in ({}, {"text": None}, {"text": True}, {"text": 42}, {"text": []}, {"text": {}}):
            with self.subTest(value_type=type(payload.get("text")).__name__, empty=not payload):
                self.assert_boundary_rejection(
                    pending, "POST", "/api/message", 400, body=json.dumps(payload).encode()
                )
        self.finish_after_guards(pending)

    def test_wrong_plan_id_types_are_400(self):
        pending = self.pending_transfer()
        for path in ("/api/plan/resume", "/api/plan/interrupt", "/api/plan/takeover"):
            for value in (None, True, 42, [], {}):
                with self.subTest(path=path, value_type=type(value).__name__):
                    self.assert_boundary_rejection(
                        pending, "POST", path, 400, body=json.dumps({"plan_id": value}).encode()
                    )
        self.finish_after_guards(pending)

    def test_transfer_confirm_success_then_replay_rejected_with_exact_ledger_and_audit(self):
        before = self.business_snapshot()
        pending = self.pending_transfer()
        calls_before = len(self.model.calls)
        response = self.confirm(pending)
        self.assertEqual(response.get("status"), "success")
        self.assertEqual(len(self.model.calls), calls_before, "Confirmation must bypass the model")
        self.assertEqual(response["data"]["amount_cents"], 10000)
        self.assertEqual(response["data"]["daily_outgoing_cents"], 10000)
        accounts = {row["account_id"]: row["balance_cents"] for row in self.query_rows("SELECT * FROM accounts")}
        self.assertEqual(accounts, {"alice-main": 990000, "alice-savings": 500000, "bob-main": 110000})
        transactions = self.query_rows("SELECT * FROM transactions")
        self.assertEqual(len(transactions), len(before["transactions"]) + 2)
        transfer_rows = self.query_rows("SELECT * FROM transfers WHERE request_id=?", (pending["request_id"],))
        self.assertEqual(len(transfer_rows), 1)
        self.assertEqual(transfer_rows[0]["status"], "success")
        self.assertEqual(transfer_rows[0]["amount_cents"], 10000)
        events = self.query_rows("SELECT * FROM audit_log WHERE request_id=?", (pending["request_id"],))
        self.assertEqual(sum(row["event"] == "executed" and row["result"] == "success" for row in events), 1)
        completed = self.business_snapshot()
        audit_before = self.query_rows("SELECT * FROM audit_log ORDER BY id")
        replay = self.confirm(pending)
        self.assertEqual(replay.get("status"), "rejected")
        self.assertEqual(self.business_snapshot(), completed)
        self.assertGreater(len(self.query_rows("SELECT * FROM audit_log")), len(audit_before))

    def test_bill_and_subscription_http_scenarios_use_owned_integer_facts(self):
        bills = self.post("/api/message", {"text": "查询本月账单"})
        self.assertEqual(bills.get("status"), "success")
        self.assertEqual(bills["data"]["actual_expense_cents"], 5970)
        self.assertIs(type(bills["data"]["actual_expense_cents"]), int)
        pending = self.post("/api/message", {"text": "查询自动扣款"})
        self.assertEqual(pending.get("status"), "pending")
        self.assertNotIn("data", pending)
        listed = self.confirm(pending)
        self.assertEqual(listed.get("status"), "success")
        self.assertEqual({row["subscription_id"] for row in listed["data"]["subscriptions"]}, {"sub-cloud", "sub-music", "sub-video"})
        history = self.query_rows("SELECT * FROM transactions ORDER BY 1")
        cancellation = self.post("/api/message", {"text": "取消视频会员"})
        self.assertEqual(cancellation.get("status"), "pending")
        self.assertEqual(self.confirm(cancellation).get("status"), "success")
        self.assertEqual(self.query_rows("SELECT * FROM transactions ORDER BY 1"), history)
        self.assertEqual(self.query_rows("SELECT status FROM subscriptions WHERE subscription_id='sub-video'")[0]["status"], "cancelled")

    def test_cancel_empty_or_null_id_invalidates_confirmation_without_transfer(self):
        for payload in ({}, {"request_id": None}):
            with self.subTest(explicit_null=bool(payload)):
                pending = self.pending_transfer()
                before = self.business_snapshot()
                self.assertEqual(self.post("/api/cancel", payload).get("status"), "cancelled")
                self.assertEqual(self.confirm(pending).get("status"), "rejected")
                self.assertEqual(self.business_snapshot(), before)

    def test_plan_resume_and_interrupt_routes_preserve_confirmation_rules(self):
        first = self.post("/api/message", {"text": "创建依赖计划"})
        self.assertEqual(first.get("status"), "pending")
        self.assertTrue(first.get("plan_id"))
        repeated = self.post("/api/plan/resume", {"plan_id": first["plan_id"]})
        self.assertEqual(repeated.get("request_id"), first["request_id"])
        self.assertTrue(repeated.get("confirmation_code") == first["confirmation_code"], "Resume must retain existing authorization")
        self.post("/api/plan/interrupt", {"plan_id": first["plan_id"]})
        self.assertEqual(self.confirm(first).get("status"), "rejected")
        stopped = self.post("/api/plan/resume", {"plan_id": first["plan_id"]})
        self.assertNotIn(stopped.get("status"), ("success", "pending"))

    def test_plan_takeover_stops_remaining_authorization(self):
        first = self.post("/api/message", {"text": "创建依赖计划"})
        self.assertEqual(first.get("status"), "pending")
        self.post("/api/plan/takeover", {"plan_id": first["plan_id"]})
        self.assertEqual(self.confirm(first).get("status"), "rejected")
        self.assertNotIn(self.post("/api/plan/resume", {"plan_id": first["plan_id"]}).get("status"), ("pending", "success"))

    def test_confirmation_csrf_and_rejected_credentials_never_persist_or_print(self):
        pending = self.pending_transfer()
        credentials = {
            "password": "MockHttpPassword_NoDisclosure_17a",
            "api_key": "sk-http-acceptance-NoDisclosure-67b",
            "authenticator_secret": "MockHttpAuthenticator_NoDisclosure_412",
            "otp": "843219",
        }
        for field, secret in credentials.items():
            self.assert_boundary_rejection(
                pending, "POST", "/api/message", 400,
                body=json.dumps({"text": "余额", field: secret}, ensure_ascii=False).encode(),
            )
        self.finish_after_guards(pending)
        self.post("/api/message", {"text": "我的账户余额"})
        receipt = self.post("/api/audit", {})
        self.assertEqual(receipt.get("status"), "success")
        self.assertIs(receipt.get("simulated"), True)
        self.assertIsInstance(receipt.get("data"), list)
        self.assertTrue(receipt["data"])
        self.assertTrue(all(event["user_id"] == "alice" for event in receipt["data"]))
        serialized = json.dumps({
            "audit": self.query_rows("SELECT * FROM audit_log ORDER BY id"),
            "requests": self.query_rows("SELECT * FROM requests ORDER BY request_id"),
            "model_calls": self.model.calls, "server_output": self.server_output,
            "audit_response": receipt,
        }, ensure_ascii=False, default=str)
        for secret in (*credentials.values(), pending["confirmation_code"], self.csrf_token):
            self.assertTrue(secret not in serialized, "An authentication or confirmation secret leaked to persistent/model/server output")


if __name__ == "__main__":
    unittest.main(verbosity=2)

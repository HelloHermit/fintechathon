"""Closeout acceptance from public contracts, without reading implementation.

Only BankService, LocalServer/BrowserHandler and documented SQLite tables are
used. All databases are disposable tests/.runs fixtures. No live model, normal
ledger, human factors or MFA CLI execution is involved. Direct execution keeps
timestamped stdout/stderr and a result manifest under evidence/closeout-independent-*.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import secrets
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bank import BankService
from src.web import BrowserHandler, LocalServer


SHANGHAI = timezone(timedelta(hours=8))
TEST_TIME = datetime(2026, 10, 11, 12, 0, 15, tzinfo=SHANGHAI)
OBSERVATIONS = []


class MutableClock:
    """Move a documented test clock without waiting or changing system time."""

    def __init__(self):
        self.value = TEST_TIME

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class ExpireOnAudit:
    """Advance only at a documented audit event, before its INSERT."""

    def __init__(self, clock):
        self.clock = clock
        self.event = None
        self.at = None
        self.triggered = False

    def __call__(self, event):
        if event.get("event") == self.event and not self.triggered:
            self.triggered = True
            self.clock.value = self.at


def transfer(amount=10000, contact="wang", account="alice-main"):
    return {"intent": "transfer", "params": {
        "account_id": account, "contact_id": contact, "amount_cents": amount,
    }}


def synthetic_auth(database_path, clock):
    """Establish only a public synthetic registered-user fixture; disclose nothing."""
    import base64

    password = secrets.token_urlsafe(24)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000).hex()
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
    with contextlib.closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                "INSERT INTO strong_auth(user_id,password_hash,password_salt,"
                "kdf_iterations,totp_secret,enrolled_at) VALUES(?,?,?,?,?,?)",
                ("alice", digest, salt.hex(), 200000, secret, clock().isoformat()),
            )


class TemporaryBank:
    def __init__(self):
        run_directory = ROOT / "tests" / ".runs"
        run_directory.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(
            prefix="closeout-independent-", dir=run_directory,
        )
        self.path = Path(self.directory.name) / "acceptance.sqlite3"
        self.clock = MutableClock()
        self.hook = ExpireOnAudit(self.clock)
        self.services = []
        self.bank = self.open()

    def open(self):
        service = BankService(str(self.path), user_id="alice", clock=self.clock, audit_hook=self.hook)
        self.services.append(service)
        return service

    def close(self):
        for service in reversed(self.services):
            with contextlib.suppress(Exception):
                service.close()
        self.directory.cleanup()

    def rows(self, sql, parameters=()):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters)]

    def business(self):
        return {table: self.rows(f"SELECT * FROM {table} ORDER BY 1") for table in (
            "accounts", "subscriptions", "transactions", "transfers",
        )}

    def state(self, intent="transfer"):
        rows = self.rows("SELECT failures, locked_until FROM verification_state WHERE user_id=? AND intent=?", ("alice", intent))
        return rows[0] if rows else {"failures": 0, "locked_until": None}

    def events(self, request_id):
        return self.rows("SELECT id,event,result,tier,reason FROM audit_log WHERE request_id=? ORDER BY id", (request_id,))


class IndependentCloseoutAcceptance(unittest.TestCase):
    """New expectations supplement the old suite without modifying its checks."""

    def setUp(self):
        self.fixtures = []

    def tearDown(self):
        for fixture in reversed(self.fixtures):
            fixture.close()

    def fixture(self, registered=False):
        fixture = TemporaryBank()
        self.fixtures.append(fixture)
        if registered:
            synthetic_auth(fixture.path, fixture.clock)
        return fixture

    def pending(self, fixture, candidate, tier="yellow"):
        response = fixture.bank.propose(candidate)
        self.assertEqual(response.get("status"), "pending", "valid fixture should wait")
        self.assertEqual(response.get("tier"), tier, "code must assign the documented tier")
        self.assertTrue(response.get("request_id"))
        return response

    def wrong_confirm(self, fixture, pending):
        wrong = "000000" if pending["confirmation_code"] != "000000" else "111111"
        return fixture.bank.confirm(pending["request_id"], wrong)

    def check_plan_stop(self, method, tier):
        fixture = self.fixture(registered=tier == "red")
        before = fixture.business()
        candidate = transfer(100100 if tier == "red" else 10000)
        candidate_plan = {"steps": [
            {"id": "pay", **candidate, "depends_on": []},
            {"id": "later", "intent": "query_balance", "params": {}, "depends_on": ["pay"]},
        ]}
        pending = self.pending(fixture, candidate_plan, tier)
        events_before = fixture.events(pending["request_id"])
        response = getattr(fixture.bank, method)(pending["plan_id"])
        stopped = fixture.rows("SELECT status,tier FROM requests WHERE request_id=?", (pending["request_id"],))
        self.assertEqual(stopped, [{"status": "cancelled", "tier": tier}])
        appended = fixture.events(pending["request_id"])[len(events_before):]
        cancellations = [event for event in appended if event["event"] == "cancelled"]
        OBSERVATIONS.append({"case": "plan-stop", "method": method, "expected_tier": tier,
                             "actual_cancellation_events": cancellations,
                             "business_unchanged": fixture.business() == before})
        self.assertTrue(cancellations, "stopping a pending node must append cancellation evidence")
        self.assertTrue(all(event["tier"] == tier for event in cancellations), "cancellation must preserve the node's code tier")
        self.assertEqual(fixture.business(), before, "plan control must not move money")
        self.assertEqual(response.get("plan", {}).get("status"), "interrupted" if method == "interrupt_plan" else "human_takeover")
        self.assertNotEqual(fixture.bank.resume_plan(pending["plan_id"]).get("status"), "success")
        self.assertEqual(fixture.business(), before)
        if tier == "red":
            response = fixture.bank.strong_verify(pending["request_id"], "synthetic-invalid-password", "invalid", confirmed=True)
            self.assertEqual(response.get("reason"), "invalid_confirmation")
        else:
            self.assertEqual(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]).get("status"), "rejected")

    def test_01_red_interrupt_preserves_cancelled_audit_tier(self):
        self.check_plan_stop("interrupt_plan", "red")

    def test_02_red_takeover_preserves_cancelled_audit_tier(self):
        self.check_plan_stop("takeover_plan", "red")

    def test_03_yellow_interrupt_cancelled_audit_control(self):
        self.check_plan_stop("interrupt_plan", "yellow")

    def test_04_yellow_takeover_cancelled_audit_control(self):
        self.check_plan_stop("takeover_plan", "yellow")

    def check_expiry_during_audit(self, candidate, event):
        fixture = self.fixture()
        pending = self.pending(fixture, candidate)
        before = fixture.business()
        existing_events = fixture.events(pending["request_id"])
        fixture.clock.value = datetime.fromisoformat(pending["expires_at"]) - timedelta(microseconds=1)
        fixture.hook.event = event
        fixture.hook.at = datetime.fromisoformat(pending["expires_at"])
        response = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
        OBSERVATIONS.append({"case": "expiry-during-audit", "intent": candidate["intent"], "event": event,
                             "actual_status": response.get("status"), "actual_reason": response.get("reason"),
                             "business_unchanged": fixture.business() == before,
                             "appended_events": fixture.events(pending["request_id"])[len(existing_events):]})
        self.assertTrue(fixture.hook.triggered, "audit phase was not reached, so the race was not exercised")
        self.assertEqual(response.get("status"), "expired", "expires_at itself is outside valid authorization")
        self.assertNotIn("data", response, "expired query must not disclose confirmed data")
        self.assertEqual(fixture.business(), before, "expiry must leave no partial business changes")
        request = fixture.rows("SELECT status FROM requests WHERE request_id=?", (pending["request_id"],))
        self.assertEqual(request, [{"status": "expired"}])
        appended = fixture.events(pending["request_id"])[len(existing_events):]
        self.assertTrue(any(item["event"] == "expired" for item in appended), "expiry must append audit evidence")
        self.assertFalse(any(item["event"] == "executed" or item["result"] == "success" for item in appended), "expired authorization must not retain successful execution audit")

    def test_05_transfer_expires_during_confirmation_audit(self):
        self.check_expiry_during_audit(transfer(), "confirmed")

    def test_06_transfer_expires_during_execution_audit(self):
        self.check_expiry_during_audit(transfer(), "executed")

    def test_07_cancel_subscription_expires_during_confirmation_audit(self):
        self.check_expiry_during_audit({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}, "confirmed")

    def test_08_cancel_subscription_expires_during_execution_audit(self):
        self.check_expiry_during_audit({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}, "executed")

    def test_09_query_subscriptions_expires_during_confirmation_audit(self):
        self.check_expiry_during_audit({"intent": "query_subscriptions", "params": {}}, "confirmed")

    def test_10_query_subscriptions_expires_during_execution_audit(self):
        self.check_expiry_during_audit({"intent": "query_subscriptions", "params": {}}, "executed")

    def test_11_confirmation_before_expiry_still_works_for_three_yellow_actions(self):
        for candidate in (transfer(), {"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}, {"intent": "query_subscriptions", "params": {}}):
            with self.subTest(intent=candidate["intent"]):
                fixture = self.fixture()
                pending = self.pending(fixture, candidate)
                fixture.clock.value = datetime.fromisoformat(pending["expires_at"]) - timedelta(microseconds=1)
                response = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
                self.assertEqual(response.get("status"), "success", "one microsecond before expiry remains valid with a stable clock")

    def test_12_initial_expiry_does_not_enter_confirmation_or_execution_audit(self):
        for candidate in (transfer(), {"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}, {"intent": "query_subscriptions", "params": {}}):
            with self.subTest(intent=candidate["intent"]):
                fixture = self.fixture()
                pending = self.pending(fixture, candidate)
                before = fixture.business()
                previous = fixture.events(pending["request_id"])
                fixture.clock.value = datetime.fromisoformat(pending["expires_at"])
                response = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
                self.assertEqual(response.get("status"), "expired")
                appended = fixture.events(pending["request_id"])[len(previous):]
                self.assertFalse(any(item["event"] in ("confirmed", "executed") for item in appended))
                self.assertEqual(fixture.business(), before)

    def test_13_expiry_during_execution_audit_does_not_clear_failure_count(self):
        fixture = self.fixture()
        prior = self.pending(fixture, transfer())
        self.wrong_confirm(fixture, prior)
        self.assertEqual(fixture.state()["failures"], 1)
        pending = self.pending(fixture, transfer())
        fixture.clock.value = datetime.fromisoformat(pending["expires_at"]) - timedelta(microseconds=1)
        fixture.hook.event = "executed"
        fixture.hook.at = datetime.fromisoformat(pending["expires_at"])
        before = fixture.business()
        response = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
        self.assertEqual(response.get("status"), "expired")
        self.assertEqual(fixture.state()["failures"], 1, "expired execution is not a valid verification success")
        self.assertEqual(fixture.business(), before)

    def test_14_restart_preserves_modified_balances_and_history(self):
        fixture = self.fixture()
        pending = self.pending(fixture, transfer(10000))
        self.assertEqual(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]).get("status"), "success")
        cancelled = self.pending(fixture, {"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}})
        self.assertEqual(fixture.bank.confirm(cancelled["request_id"], cancelled["confirmation_code"]).get("status"), "success")
        waiting = self.pending(fixture, transfer(10000))
        before = fixture.business()
        old_audit = fixture.rows("SELECT * FROM audit_log ORDER BY id")
        fixture.bank.close()
        fixture.bank = fixture.open()
        self.assertEqual(fixture.business(), before, "opening existing ledger must not reseed balances/history")
        after_audit = fixture.rows("SELECT * FROM audit_log ORDER BY id")
        self.assertEqual(after_audit[:len(old_audit)], old_audit, "restart may only append audit")
        self.assertTrue(any(row["event"] == "restart" for row in after_audit[len(old_audit):]))
        self.assertEqual(fixture.bank.confirm(waiting["request_id"], waiting["confirmation_code"]).get("status"), "rejected")
        self.assertEqual(fixture.business(), before)
        self.assertEqual(len(fixture.rows("SELECT * FROM transfers WHERE status='success'")), 1)

    def test_15_three_failures_survive_cancel_target_amount_restart_and_ten_minutes(self):
        fixture = self.fixture(registered=True)
        before = fixture.business()
        first = self.pending(fixture, transfer(10000))
        self.wrong_confirm(fixture, first)
        self.assertEqual(fixture.state()["failures"], 1)
        fixture.bank.cancel(first["request_id"])
        second = self.pending(fixture, transfer(20000, contact="li"))
        self.wrong_confirm(fixture, second)
        self.assertEqual(fixture.state()["failures"], 2)
        fixture.bank.close()
        fixture.bank = fixture.open()
        self.assertEqual(fixture.state()["failures"], 2)
        red = self.pending(fixture, transfer(100100), "red")
        response = fixture.bank.strong_verify(red["request_id"], "synthetic-invalid-password", "invalid", confirmed=True)
        self.assertEqual(response.get("reason"), "locked")
        state = fixture.state()
        self.assertEqual(state["failures"], 3)
        self.assertEqual(datetime.fromisoformat(state["locked_until"]), fixture.clock() + timedelta(minutes=10))
        self.assertEqual(fixture.bank.cancel(red["request_id"]).get("status"), "cancelled", "lock must still permit cancellation")
        fixture.bank.close()
        fixture.bank = fixture.open()
        self.assertEqual(fixture.state(), state, "restart cannot reset lock deadline or failures")
        fixture.clock.advance(599)
        low = fixture.bank.propose(transfer(100))
        high = fixture.bank.propose(transfer(100100, contact="li"))
        self.assertEqual(low.get("reason"), "locked", "lower amount cannot bypass transfer lock")
        self.assertEqual(high.get("reason"), "locked", "red channel cannot bypass transfer lock")
        self.assertEqual(fixture.business(), before)
        fixture.clock.advance(1)
        after_deadline = self.pending(fixture, transfer(100))
        self.wrong_confirm(fixture, after_deadline)
        self.assertEqual(fixture.state(), {"failures": 1, "locked_until": None}, "ten-minute boundary permits a fresh failure sequence")
        self.assertEqual(fixture.business(), before)


class FixedModel:
    """Return controlled candidates; never reads configuration or calls a network."""

    def propose(self, text, context):
        return transfer(100100 if text == "从我的主账户给小王转1001元。" else 10000)


class IndependentCloseoutHttpAcceptance(unittest.TestCase):
    def setUp(self):
        run_directory = ROOT / "tests" / ".runs"
        run_directory.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="closeout-http-independent-", dir=run_directory)
        self.path = Path(self.directory.name) / "http.sqlite3"
        self.clock = MutableClock()
        self.ready = threading.Event()
        self.errors = []
        self.server = None
        self.csrf = "closeout-independent-offline-session-token"
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.stop)
        self.thread.start()
        self.assertTrue(self.ready.wait(5))
        self.assertFalse(self.errors, "public loopback fixture failed to start")

    def serve(self):
        bank = None
        try:
            bank = BankService(str(self.path), user_id="alice", clock=self.clock)
            synthetic_auth(self.path, self.clock)
            self.server = LocalServer(("127.0.0.1", 0), BrowserHandler)
            self.port = self.server.server_port
            self.server.bank = bank
            self.server.csrf_token = self.csrf
            self.server.model = FixedModel()
            self.server.model_configured = True
            self.ready.set()
            self.server.serve_forever(poll_interval=0.05)
        except Exception as error:
            self.errors.append(type(error).__name__)
            self.ready.set()
        finally:
            if self.server is not None:
                self.server.server_close()
            if bank is not None:
                bank.close()

    def stop(self):
        if self.thread.is_alive() and self.server is not None:
            self.server.shutdown()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.errors)

    def rows(self, sql, parameters=()):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters)]

    def business(self):
        return {table: self.rows(f"SELECT * FROM {table} ORDER BY 1") for table in ("accounts", "subscriptions", "transactions", "transfers")}

    def post(self, path, payload, expected_http=200):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            connection.request("POST", path, body=body, headers={
                "Content-Type": "application/json", "X-CSRF-Token": self.csrf,
                "Host": f"127.0.0.1:{self.port}", "Connection": "close",
            })
            response = connection.getresponse()
            received = response.read()
            self.assertEqual(response.status, expected_http)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return json.loads(received)
        finally:
            connection.close()

    def test_16_enrolled_red_http_pending_has_operation_and_can_cancel(self):
        before = self.business()
        response = self.post("/api/message", {"text": "从我的主账户给小王转1001元。"})
        self.assertEqual(response.get("status"), "pending")
        self.assertEqual(response.get("tier"), "red")
        self.assertNotIn("confirmation_code", response, "red must not offer screen-code authorization")
        self.assertTrue(response.get("operation"))
        self.assertTrue(response.get("expires_at"))
        cancelled = self.post("/api/cancel", {"request_id": response["request_id"]})
        self.assertEqual(cancelled.get("status"), "cancelled")
        self.assertEqual(self.business(), before)
        events = self.rows("SELECT event,tier FROM audit_log WHERE request_id=?", (response["request_id"],))
        self.assertIn({"event": "cancelled", "tier": "red"}, events)

    def test_17_red_http_yellow_confirm_and_missing_mfa_routes_do_not_execute(self):
        before = self.business()
        pending = self.post("/api/message", {"text": "从我的主账户给小王转1001元。"})
        response = self.post("/api/confirm", {"request_id": pending["request_id"], "confirmation_code": "000000"})
        self.assertEqual(response.get("reason"), "strong_verification_required")
        for path in ("/api/strong_verify", "/api/mfa/verify", "/api/mfa/enroll"):
            with self.subTest(path=path):
                self.post(path, {}, expected_http=404)
        failures = self.rows("SELECT failures FROM verification_state WHERE user_id='alice' AND intent='transfer'")
        self.assertTrue(not failures or failures == [{"failures": 0}])
        self.assertEqual(self.business(), before)
        self.assertEqual(self.post("/api/cancel", {"request_id": pending["request_id"]}).get("status"), "cancelled")

    def test_18_yellow_http_confirmation_control_executes_once(self):
        pending = self.post("/api/message", {"text": "从我的主账户给小王转100元。"})
        self.assertEqual(pending.get("status"), "pending")
        self.assertEqual(pending.get("tier"), "yellow")
        self.assertIn("confirmation_code", pending)
        response = self.post("/api/confirm", {"request_id": pending["request_id"], "confirmation_code": pending["confirmation_code"]})
        self.assertEqual(response.get("status"), "success")
        before_replay = self.business()
        self.assertEqual(self.post("/api/confirm", {"request_id": pending["request_id"], "confirmation_code": pending["confirmation_code"]}).get("status"), "rejected")
        self.assertEqual(self.business(), before_replay)


class EvidenceResult(unittest.TextTestResult):
    """Record safe test identifiers and outcomes; never serialize factors/responses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({"test": test.id(), "result": "passed"})

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.outcomes.append({"test": test.id(), "result": "failed"})

    def addError(self, test, error):
        super().addError(test, error)
        self.outcomes.append({"test": test.id(), "result": "error"})

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error is not None:
            self.outcomes.append({"test": subtest.id(), "result": "failed" if issubclass(error[0], test.failureException) else "error"})


def run_with_evidence():
    started = datetime.now(SHANGHAI)
    stamp = started.strftime("%Y%m%d-%H%M%S-%f")
    evidence_path = ROOT / "evidence" / f"closeout-independent-{stamp}.txt"
    manifest_path = evidence_path.with_suffix(".json")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        result = unittest.TextTestRunner(stream=captured, verbosity=2, resultclass=EvidenceResult).run(suite)
    finished = datetime.now(SHANGHAI)
    output = captured.getvalue()
    evidence_path.write_text(
        f"Start (Asia/Shanghai): {started.isoformat()}\n"
        f"Finish (Asia/Shanghai): {finished.isoformat()}\n"
        "Command: python tests/test_closeout_independent.py\n"
        "Independent public-interface tests; synthetic factors; no live model or normal ledger.\n"
        "Complete combined stdout/stderr follows.\n\n" + output,
        encoding="utf-8",
    )
    manifest_path.write_text(json.dumps({
        "started_at": started.isoformat(), "finished_at": finished.isoformat(),
        "command": "python tests/test_closeout_independent.py", "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "successful": result.wasSuccessful(), "outcomes": result.outcomes,
        "safe_public_observations": OBSERVATIONS,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "stdout_stderr_file": evidence_path.name,
        "limitations": ["Synthetic/offline only", "No human device or terminal evidence", "No browser DOM evidence", "After internal 20:00 checkpoint"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(output)
    sys.stdout.write(f"Evidence: {evidence_path}\nManifest: {manifest_path}\n")
    return 0 if result.wasSuccessful() else 1


def serve_controlled_ui():
    """Serve a disposable, publicly constructed fixture for independent DOM QA."""
    started = datetime.now(SHANGHAI)
    stamp = started.strftime("%Y%m%d-%H%M%S-%f")
    log_path = ROOT / "evidence" / f"closeout-independent-ui-server-{stamp}.txt"
    run_directory = ROOT / "tests" / ".runs"
    run_directory.mkdir(parents=True, exist_ok=True)
    directory = tempfile.TemporaryDirectory(prefix="closeout-ui-independent-", dir=run_directory)
    database_path = Path(directory.name) / "ui.sqlite3"
    clock = lambda: datetime.now(SHANGHAI)
    bank = None
    server = None
    captured = io.StringIO()
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"Start (Asia/Shanghai): {started.isoformat()}\n")
        log.write("Command: python tests/test_closeout_independent.py --serve-controlled-ui\n")
        log.write("Synthetic registered-user fixture; offline model; no human factors.\n")
        log.flush()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                bank = BankService(str(database_path), user_id="alice", clock=clock)
                synthetic_auth(database_path, clock)
                server = LocalServer(("127.0.0.1", 0), BrowserHandler)
                server.bank = bank
                server.csrf_token = "closeout-independent-controlled-ui-session-token"
                server.model = FixedModel()
                server.model_configured = True
            url = f"http://127.0.0.1:{server.server_port}/"
            log.write(f"Public URL: {url}\n")
            log.write(f"Disposable database: {database_path}\n")
            log.flush()
            sys.stdout.write(f"Controlled public-interface UI fixture: {url}\n")
            sys.stdout.write(f"Server log: {log_path}\n")
            sys.stdout.flush()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                server.serve_forever(poll_interval=0.05)
        except KeyboardInterrupt:
            log.write("Stopped by test-author interrupt.\n")
        finally:
            if server is not None:
                server.server_close()
            if bank is not None:
                bank.close()
            log.write(captured.getvalue())
            log.write(f"Finish (Asia/Shanghai): {datetime.now(SHANGHAI).isoformat()}\n")
            directory.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_controlled_ui() if "--serve-controlled-ui" in sys.argv else run_with_evidence())

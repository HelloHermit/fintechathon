"""Task2 independent acceptance: public contract only, never run at authoring.

Run only after the implementation owner freezes the matching contract.
All databases belong to a new directory beneath tests/.runs. No normal database,
credentials, environment configuration, network model, or implementation source
is read by this suite. Reading the documented public SQLite tables is deliberate.
"""

from __future__ import annotations

import base64
from contextlib import closing
import copy
import datetime as datetime_module
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import uuid


def repository_directory():
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "src" / "PUBLIC_API.md").is_file():
            return candidate
    raise RuntimeError("Cannot locate the public contract directory")


REPOSITORY = repository_directory()
RUNS_DIRECTORY = REPOSITORY / "tests" / ".runs"
RUNS_DIRECTORY.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPOSITORY))

from src.bank import BankService  # Public import; do not inspect its source.


SHANGHAI = datetime_module.timezone(datetime_module.timedelta(hours=8))
INITIAL_TIME = datetime_module.datetime(2026, 10, 23, 10, 0, tzinfo=SHANGHAI)
TRANSFER = {
    "intent": "transfer",
    "params": {
        "account_id": "alice-main",
        "contact_id": "wang",
        "amount_cents": 10000,
    },
}
PLAN = {
    "steps": [
        {"id": "bill", "intent": "analyze_bills", "params": {}, "depends_on": []},
        {"id": "pay", **copy.deepcopy(TRANSFER), "depends_on": ["bill"]},
        {"id": "subs", "intent": "query_subscriptions", "params": {}, "depends_on": ["pay"]},
    ]
}
SECRETS_FOR_EVIDENCE = set()


class TestClock:
    def __init__(self, value=INITIAL_TIME):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += datetime_module.timedelta(seconds=seconds)


def remember_transient_codes(value):
    if isinstance(value, dict):
        for name, item in value.items():
            if name in {"confirmation_code", "recovery_code"} and isinstance(item, str):
                SECRETS_FOR_EVIDENCE.add(item)
            else:
                remember_transient_codes(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            remember_transient_codes(item)
    return value


def evidence_safe(value):
    if isinstance(value, dict):
        forbidden = {"confirmation_code", "recovery_code", "password", "totp_secret", "totp_code"}
        return {
            str(name): "[redacted]" if name in forbidden else evidence_safe(item)
            for name, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [evidence_safe(item) for item in value]
    if isinstance(value, str):
        for secret in sorted(SECRETS_FOR_EVIDENCE, key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    return value


class FixedCandidateModel:
    """Offline public model dependency; this does not prove any real model call."""

    def __init__(self, candidate):
        self.candidate = copy.deepcopy(candidate)

    def propose(self, text, context):
        return copy.deepcopy(self.candidate)


class RecoveryIndependentAcceptance(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="recovery-independent-", dir=str(RUNS_DIRECTORY))
        self.directory = Path(self.workspace.name)
        self.clock = TestClock()
        self.services = []
        self.evidence = []
        self.database_path = self.directory / "case.db"
        self.bank = self.new_service()
        self.record_trace("initial_fixture", self.public_state())

    def tearDown(self):
        try:
            self.record_trace("final_fixture", self.public_state())
        except Exception as error:
            self.record_trace("final_observation_error", type(error).__name__)
        for service in reversed(self.services):
            try:
                service.close()
            except Exception:
                pass
        # Keep failure histories in the run report, but remove this run's own
        # disposable database only. No normal workspace data is addressed.
        self.workspace.cleanup()

    def new_service(self, database_path=None, user_id="alice", audit_hook=None, checkpoint_hook=None):
        service = BankService(
            str(database_path or self.database_path),
            user_id=user_id,
            clock=self.clock,
            audit_hook=audit_hook,
            checkpoint_hook=checkpoint_hook,
        )
        self.services.append(service)
        return service

    def fresh_fixture(self, label, **kwargs):
        if self.database_path.is_file():
            self.record_trace("previous_parameter_fixture", self.public_state())
        self.database_path = self.directory / (label + ".db")
        self.clock = TestClock()
        self.bank = self.new_service(**kwargs)
        self.record_trace("parameter_fixture_" + label, self.public_state())
        return self.bank

    def call(self, bank, method, *arguments, **keywords):
        response = getattr(bank, method)(*arguments, **keywords)
        self.assertIsInstance(response, dict, method + " must return a dictionary")
        remember_transient_codes(response)
        return response

    def status(self, response, expected, label="response"):
        self.assertEqual(response.get("status"), expected, label + ": unexpected status")

    def rejected(self, response, label="response"):
        self.status(response, "rejected", label)

    def plan(self, plan_id, bank=None):
        response = self.call(bank or self.bank, "get_plan", plan_id)
        self.status(response, "success", "get_plan")
        self.assertEqual(response.get("plan_id"), plan_id)
        plan = response.get("plan")
        self.assertIsInstance(plan, dict)
        self.assertEqual(plan.get("plan_id"), plan_id)
        self.assertEqual(plan.get("user_id"), "alice")
        return plan

    def steps(self, plan):
        result = {item["id"]: item for item in plan["steps"]}
        self.assertEqual(list(result), ["bill", "pay", "subs"])
        return result

    def fixture_a(self, bank=None):
        bank = bank or self.bank
        response = self.call(bank, "propose", copy.deepcopy(PLAN))
        self.status(response, "pending", "P must stop at pay")
        self.assertEqual(response.get("intent"), "transfer")
        self.assertIsInstance(response.get("plan_id"), str)
        self.assertIsInstance(response.get("request_id"), str)
        self.assertIsInstance(response.get("confirmation_code"), str)
        current = self.steps(self.plan(response["plan_id"], bank))
        self.assertEqual(current["bill"]["status"], "success")
        self.assertEqual(current["bill"]["result"]["actual_expense_cents"], 5970)
        self.assertEqual(current["pay"]["status"], "pending")
        self.assertEqual(current["subs"]["status"], "not_started")
        return response

    def fixture_b(self, bank=None):
        bank = bank or self.bank
        response = self.fixture_a(bank)
        result = self.call(bank, "confirm", response["request_id"], response["confirmation_code"])
        self.status(result, "success", "pay confirmation")
        self.assert_t100_once()
        return response

    def restart(self, bank=None):
        old = bank or self.bank
        old.close()
        self.bank = self.new_service()
        return self.bank

    def prepare(self, plan_id, bank=None):
        response = self.call(bank or self.bank, "prepare_recovery", plan_id)
        self.status(response, "pending", "prepare_recovery")
        self.assertEqual(response.get("intent"), "recover_plan")
        self.assertEqual(response.get("tier"), "none")
        self.assertIsInstance(response.get("review_id"), str)
        self.assertRegex(response.get("recovery_code", ""), r"^[0-9]{6}$")
        operation = response.get("operation")
        self.assertIsInstance(operation, dict)
        for field in ("user_id", "plan_id", "plan_revision", "completed_steps", "remaining_steps", "operations", "committed_effects", "manual_actions", "impact", "expires_at"):
            self.assertIn(field, operation, "recovery operation missing " + field)
        self.assertEqual(operation["user_id"], "alice")
        self.assertEqual(operation["plan_id"], plan_id)
        self.assertEqual(operation["expires_at"], response["expires_at"])
        return response

    def authorize_recovery(self, plan_id, bank=None):
        bank = bank or self.bank
        review = self.prepare(plan_id, bank)
        before = self.financial_snapshot()
        accepted = self.call(bank, "confirm_recovery", review["review_id"], review["recovery_code"])
        self.status(accepted, "success", "confirm_recovery")
        self.assertEqual(accepted.get("reason"), "recovery_authorized")
        self.assertEqual(self.financial_snapshot(), before, "recovery consent must not execute any node")
        return review

    def recovered_pay(self, old):
        self.authorize_recovery(old["plan_id"])
        resumed = self.call(self.bank, "resume_plan", old["plan_id"])
        self.status(resumed, "pending", "new pay must need node confirmation")
        self.assertEqual(resumed.get("intent"), "transfer")
        self.assertNotEqual(resumed.get("request_id"), old["request_id"])
        self.assertIsInstance(resumed.get("confirmation_code"), str)
        return resumed

    def sql_rows(self, statement, parameters=()):
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            return connection.execute(statement, parameters).fetchall()

    def sql_change(self, statement, parameters=()):
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            with connection:
                connection.execute(statement, parameters)

    def financial_snapshot(self):
        return {
            "accounts": self.sql_rows("SELECT account_id,user_id,balance_cents FROM accounts ORDER BY account_id"),
            "subscriptions": self.sql_rows("SELECT subscription_id,user_id,status FROM subscriptions ORDER BY subscription_id"),
            "transfers": self.sql_rows("SELECT request_id,user_id,source_account_id,target_account_id,amount_cents,shanghai_date,status FROM transfers ORDER BY request_id"),
            "transaction_count": self.sql_rows("SELECT COUNT(*) FROM transactions")[0][0],
        }

    def audit_snapshot(self):
        return self.sql_rows("SELECT id,timestamp,request_id,step_id,user_id,raw_input_redacted,intent,tier,params_redacted,event,result,reason,plan_id FROM audit_log ORDER BY id")

    def public_state(self):
        return {
            "fixture_database": self.database_path.name,
            "simulated_time": self.clock().isoformat(),
            "financial": self.financial_snapshot(),
            "requests": self.sql_rows("SELECT request_id,user_id,intent,tier,status,created_at,expires_at FROM requests ORDER BY request_id"),
            "verification": self.sql_rows("SELECT user_id,intent,failures,locked_until FROM verification_state ORDER BY user_id,intent"),
            "plan_snapshots": self.sql_rows("SELECT plan_id,user_id,snapshot_json,revision FROM recovery_plans ORDER BY plan_id"),
            "audit": self.audit_snapshot(),
        }

    def assert_initial_money(self):
        accounts = dict(self.sql_rows("SELECT account_id,balance_cents FROM accounts"))
        self.assertEqual(accounts["alice-main"], 1000000)
        self.assertEqual(accounts["alice-savings"], 500000)
        self.assertEqual(accounts["bob-main"], 100000)
        self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM transfers WHERE status='success'")[0][0], 0)

    def assert_t100_once(self):
        accounts = dict(self.sql_rows("SELECT account_id,balance_cents FROM accounts"))
        self.assertEqual(accounts["alice-main"], 990000)
        self.assertEqual(accounts["alice-savings"], 500000)
        self.assertEqual(accounts["bob-main"], 110000)
        self.assertEqual(self.sql_rows("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM transfers WHERE user_id='alice' AND status='success'")[0], (1, 10000))

    def pending_wrong_code(self, pending):
        return "000000" if pending.get("confirmation_code") != "000000" else "999999"

    def lock_transfer(self):
        pending = self.call(self.bank, "propose", copy.deepcopy(TRANSFER))
        self.status(pending, "pending")
        for _ in range(3):
            self.call(self.bank, "confirm", pending["request_id"], self.pending_wrong_code(pending))
        state = self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")
        self.assertEqual(state[0][0], 3)
        self.assertIsNotNone(state[0][1])
        return state[0]

    def takeover(self, plan_id, bank=None):
        response = self.call(bank or self.bank, "takeover_plan", plan_id)
        self.assertNotIn(response.get("status"), {"failed", "rejected"})
        plan = self.plan(plan_id, bank)
        self.assertEqual(plan["status"], "human_takeover")
        self.assertIsInstance(plan.get("handover_id"), str)
        return plan["handover_id"]

    def handover(self, handover_id, bank=None):
        response = self.call(bank or self.bank, "get_handover", handover_id)
        self.status(response, "success")
        item = response["data"]["handover"]
        self.assertEqual(item["handover_id"], handover_id)
        return item

    def record_trace(self, name, value):
        self.evidence.append({"name": name, "value": evidence_safe(value)})

    def assert_no_subscription_result(self, value):
        if isinstance(value, dict):
            self.assertFalse("subscriptions" in value, "unconfirmed subscription list disclosed")
            for item in value.values():
                self.assert_no_subscription_result(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_no_subscription_result(item)

    def run_child(self, mode):
        database_path = self.directory / (mode + ".db")
        command = [sys.executable, str(Path(__file__).resolve()), "--child", mode, str(database_path)]
        completed = subprocess.run(command, cwd=str(REPOSITORY), capture_output=True, text=True, timeout=45)
        self.record_trace("child", {"mode": mode, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
        expected = 72 if mode == "pay_after" else 71
        self.assertEqual(completed.returncode, expected, "child must exit at the documented checkpoint")
        self.database_path = database_path
        self.bank = self.new_service()
        listed = self.call(self.bank, "list_plans")
        self.status(listed, "success")
        self.assertEqual(len(listed["data"]["plans"]), 1)
        return listed["data"]["plans"][0]["plan_id"]

    def test_r_01_pending_plan_survives_real_process_exit(self):
        plan_id = self.run_child("pending")
        current = self.steps(self.plan(plan_id))
        self.assertEqual(current["bill"]["status"], "success")
        self.assertEqual(current["pay"]["status"], "cancelled")
        self.assertEqual(current["pay"]["reason"], "session_restarted")
        self.assertEqual(current["subs"]["status"], "not_started")
        self.assert_initial_money()
        self.record_trace("restarted_plan", self.plan(plan_id))

    def test_r_02_failed_node_and_dependency_survive_restart(self):
        def fault(event):
            if event["point"] == "node_before_commit" and event["step_id"] == "bill":
                raise RuntimeError("independent_bill_fault")
        bank = self.fresh_fixture("r02", checkpoint_hook=fault)
        response = self.call(bank, "propose", copy.deepcopy(PLAN))
        self.status(response, "failed")
        plan_id = response["plan_id"]
        self.restart(bank)
        current = self.steps(self.plan(plan_id))
        self.assertEqual(current["bill"]["status"], "failed")
        self.assertTrue(current["bill"].get("reason"))
        self.assertEqual(current["pay"]["status"], "not_started")
        self.assertEqual(current["subs"]["status"], "not_started")
        self.rejected(self.call(self.bank, "resume_plan", plan_id))
        self.assert_initial_money()

    def test_r_03_unstarted_nodes_are_durable_and_reads_do_not_run(self):
        plan_id = self.run_child("bill_before")
        before = self.financial_snapshot()
        for _ in range(3):
            self.call(self.bank, "list_plans")
            current = self.steps(self.plan(plan_id))
            self.assertTrue(all(item["status"] != "success" for item in current.values()))
            self.assertEqual(current["bill"]["depends_on"], [])
            self.assertEqual(current["pay"]["depends_on"], ["bill"])
            self.assertEqual(current["subs"]["depends_on"], ["pay"])
        self.assertEqual(self.financial_snapshot(), before)

    def test_r_04_old_confirmation_invalid_even_before_five_minutes(self):
        pending = self.fixture_a()
        self.restart()
        self.rejected(self.call(self.bank, "confirm", pending["request_id"], pending["confirmation_code"]))
        row = self.sql_rows("SELECT status FROM requests WHERE request_id=?", (pending["request_id"],))
        self.assertEqual(row[0][0], "cancelled")
        events = self.audit_snapshot()
        self.assertTrue(any(row[9] == "plan_restarted" and row[12] == pending["plan_id"] for row in events))
        self.assert_initial_money()

    def test_r_05_expired_authorization_never_revived(self):
        for seconds in (300, 301):
            with self.subTest(seconds=seconds):
                self.fresh_fixture("r05-" + str(seconds))
                old = self.fixture_a()
                self.clock.advance(seconds)
                self.restart()
                self.rejected(self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"]))
                review = self.prepare(old["plan_id"])
                self.assertGreater(datetime_module.datetime.fromisoformat(review["expires_at"]), self.clock())
                self.assert_initial_money()
        for seconds in (300, 301):
            with self.subTest(recovery_seconds=seconds):
                self.fresh_fixture("r05-control-" + str(seconds))
                old = self.fixture_a()
                self.restart()
                review = self.prepare(old["plan_id"])
                self.clock.advance(seconds)
                result = self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"])
                self.assertIn(result.get("status"), ("expired", "rejected"))
                self.rejected(self.call(self.bank, "resume_plan", old["plan_id"]))
                replacement = self.prepare(old["plan_id"])
                self.assertNotEqual(replacement["review_id"], review["review_id"])
                self.assertGreater(datetime_module.datetime.fromisoformat(replacement["expires_at"]), self.clock())
                self.assert_initial_money()
        for seconds_after_deadline in (0, 1):
            with self.subTest(commit_checkpoint_seconds_after_deadline=seconds_after_deadline):
                checkpoint = {"armed": False, "deadline": None, "hits": 0}
                def advance_only(event):
                    if checkpoint["armed"] and event["point"] == "node_before_commit" and event["step_id"] == "pay":
                        checkpoint["hits"] += 1
                        self.clock.value = checkpoint["deadline"] + datetime_module.timedelta(seconds=seconds_after_deadline)
                    # Returning normally is deliberate: no injected exception
                    # may substitute for the public deadline recheck.
                    return None
                self.fresh_fixture("r05-commit-checkpoint-" + str(seconds_after_deadline), checkpoint_hook=advance_only)
                pending = self.fixture_a()
                for _ in range(2):
                    self.call(self.bank, "confirm", pending["request_id"], self.pending_wrong_code(pending))
                failures_before = self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")
                self.assertEqual(failures_before[0][0], 2)
                before = self.financial_snapshot()
                checkpoint["deadline"] = datetime_module.datetime.fromisoformat(pending["expires_at"])
                checkpoint["armed"] = True
                response = self.call(self.bank, "confirm", pending["request_id"], pending["confirmation_code"])
                self.record_trace("commit_checkpoint_expiry", {
                    "seconds_after_deadline": seconds_after_deadline,
                    "deadline": checkpoint["deadline"].isoformat(),
                    "clock_after_normal_hook": self.clock().isoformat(),
                    "checkpoint_hits": checkpoint["hits"],
                    "response_status": response.get("status"),
                    "response_reason": response.get("reason"),
                    "financial_before": before,
                    "financial_after": self.financial_snapshot(),
                    "verification_before": failures_before,
                    "verification_after": self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'"),
                })
                self.assertGreaterEqual(checkpoint["hits"], 1, "normal public before-commit hook was not reached")
                self.status(response, "expired", "authorization expires during the final public commit checkpoint")
                self.assertEqual(self.financial_snapshot(), before)
                self.assertEqual(self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'"), failures_before)
                self.assertEqual(self.sql_rows("SELECT status FROM requests WHERE request_id=?", (pending["request_id"],))[0][0], "expired")
                self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM audit_log WHERE request_id=? AND event='executed'", (pending["request_id"],))[0][0], 0)
                self.assertGreaterEqual(self.sql_rows("SELECT COUNT(*) FROM audit_log WHERE request_id=? AND event='expired'", (pending["request_id"],))[0][0], 1)
                current = self.steps(self.plan(pending["plan_id"]))
                self.assertEqual(current["pay"]["status"], "expired")
                attempts = [item for item in current["pay"]["attempts"] if item["request_id"] == pending["request_id"]]
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0]["status"], "expired")
                self.assertEqual(current["subs"]["status"], "not_started")

    def test_r_06_continue_and_saved_plan_are_not_consent(self):
        old = self.fixture_a()
        self.restart()
        response = self.call(self.bank, "resume_plan", old["plan_id"])
        self.rejected(response)
        self.assertEqual(response.get("reason"), "recovery_authorization_required")
        before = self.financial_snapshot()
        first = self.prepare(old["plan_id"])
        second = self.prepare(old["plan_id"])
        self.assertEqual(first["review_id"], second["review_id"])
        self.assertEqual(first["expires_at"], second["expires_at"])
        self.assertEqual(self.financial_snapshot(), before)
        self.assert_no_subscription_result(first["operation"])

    def test_r_07_fresh_exact_recovery_and_node_consent(self):
        old = self.fixture_a()
        self.restart()
        new = self.recovered_pay(old)
        self.rejected(self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"]))
        operation = new["operation"]
        self.assertEqual(operation["user_id"], "alice")
        self.assertIn("10000", json.dumps(operation))
        self.status(self.call(self.bank, "confirm", new["request_id"], new["confirmation_code"]), "success")
        self.assert_t100_once()
        attempts = self.steps(self.plan(old["plan_id"]))["pay"]["attempts"]
        self.assertTrue(any(item["request_id"] == old["request_id"] and item["status"] == "cancelled" for item in attempts))
        self.assertTrue(any(item["request_id"] == new["request_id"] and item["status"] == "success" for item in attempts))

    def test_r_08_initial_plan_save_failure_blocks_all_nodes(self):
        def fault(event):
            if event["point"] == "plan_save_before_commit":
                raise RuntimeError("independent_plan_storage_fault")
        bank = self.fresh_fixture("r08", checkpoint_hook=fault)
        response = self.call(bank, "propose", copy.deepcopy(PLAN))
        self.status(response, "failed")
        self.assertEqual(response.get("reason"), "state_unavailable")
        self.assert_initial_money()
        self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM audit_log WHERE event='executed'")[0][0], 0)

    def test_r_09_before_commit_process_exit_rolls_back(self):
        plan_id = self.run_child("pay_before")
        self.assert_initial_money()
        current = self.steps(self.plan(plan_id))
        self.assertEqual(current["bill"]["status"], "success")
        self.assertNotEqual(current["pay"]["status"], "success")
        self.assertEqual(current["subs"]["status"], "not_started")
        self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM audit_log WHERE event='executed' AND intent='transfer'")[0][0], 0)

    def test_r_10_after_commit_process_exit_preserves_success(self):
        plan_id = self.run_child("pay_after")
        self.assert_t100_once()
        current = self.steps(self.plan(plan_id))
        self.assertEqual(current["pay"]["status"], "success")
        self.assertEqual(current["subs"]["status"], "not_started")
        self.call(self.bank, "resume_plan", plan_id)
        self.assert_t100_once()
        self.record_trace("committed_after_exit", self.plan(plan_id))

    def test_r_11_repeated_recovery_and_confirm_cannot_repeat_payment(self):
        old = self.fixture_b()
        self.restart()
        self.authorize_recovery(old["plan_id"])
        for _ in range(3):
            response = self.call(self.bank, "resume_plan", old["plan_id"])
            self.assertNotEqual(response.get("intent"), "transfer")
            self.rejected(self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"]))
        self.assert_t100_once()
        self.assertEqual(len(self.steps(self.plan(old["plan_id"]))["pay"]["attempts"]), 1)

    def test_r_12_same_session_resume_keeps_original_request_and_expiry(self):
        old = self.fixture_a()
        for _ in range(4):
            self.clock.advance(10)
            response = self.call(self.bank, "resume_plan", old["plan_id"])
            self.status(response, "pending")
            self.assertEqual(response.get("request_id"), old["request_id"])
            self.assertEqual(response.get("expires_at"), old["expires_at"])
        self.assert_initial_money()

    def test_r_13_competing_recovery_and_duplicate_confirmation(self):
        old = self.fixture_a()
        self.bank.close()
        barrier = threading.Barrier(2, timeout=15)
        outcomes = []
        worker_errors = []
        def worker():
            service = None
            try:
                # Each thread owns its own public SQLite service. Constructors
                # finish before either can prepare a new recovery review.
                service = BankService(str(self.database_path), user_id="alice", clock=self.clock)
                barrier.wait()
                review = remember_transient_codes(service.prepare_recovery(old["plan_id"]))
                self.assertIn(review.get("status"), ("pending", "rejected"))
                barrier.wait()
                if review.get("status") == "pending":
                    accepted = service.confirm_recovery(review["review_id"], review["recovery_code"])
                else:
                    accepted = {"status": "rejected", "reason": review.get("reason")}
                barrier.wait()
                resumed = remember_transient_codes(service.resume_plan(old["plan_id"]))
                entry = {"authorization_status": accepted.get("status"), "resume_status": resumed.get("status"), "request_id": resumed.get("request_id")}
                if accepted.get("status") == "success" and resumed.get("status") == "pending" and resumed.get("intent") == "transfer":
                    first = service.confirm(resumed["request_id"], resumed["confirmation_code"])
                    second = service.confirm(resumed["request_id"], resumed["confirmation_code"])
                    entry.update(first_confirmation_status=first.get("status"), replay_status=second.get("status"))
                outcomes.append(entry)
            except BaseException:
                worker_errors.append(traceback.format_exc())
                try:
                    barrier.abort()
                except Exception:
                    pass
            finally:
                if service is not None:
                    service.close()
        workers = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=25)
        self.assertFalse(any(thread.is_alive() for thread in workers), "recovery competitors did not stop")
        self.record_trace("concurrent_outcomes", outcomes)
        self.record_trace("concurrent_errors", worker_errors)
        self.assertFalse(worker_errors, "a public concurrency call raised instead of a safe response")
        self.assertEqual(sum(item.get("authorization_status") == "success" for item in outcomes), 1)
        self.assertEqual(sum(item.get("first_confirmation_status") == "success" for item in outcomes), 1)
        self.assert_t100_once()

    def test_r_14_interrupt_persists_and_old_confirm_fails(self):
        old = self.fixture_a()
        for _ in range(2):
            response = self.call(self.bank, "interrupt_plan", old["plan_id"])
            self.assertNotIn(response.get("status"), {"failed", "rejected"})
        self.restart()
        current = self.steps(self.plan(old["plan_id"]))
        self.assertEqual(current["bill"]["status"], "success")
        self.assertNotEqual(current["pay"]["status"], "success")
        self.assertEqual(current["subs"]["status"], "not_started")
        self.rejected(self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"]))
        self.assert_initial_money()
        # cancel(None) also addresses the current recovery review/permission
        # when there is no business-node pending request. This is workflow
        # cancellation, not a new business tool or compensation permission.
        for phase in ("prepared", "authorized_before_resume", "ready_after_committed_pay"):
            for cancellation_entry in ("fixed_cancel", "natural_language_cancel"):
                with self.subTest(recovery_phase=phase, cancellation_entry=cancellation_entry):
                    self.fresh_fixture("r14-" + phase + "-" + cancellation_entry)
                    pending = self.fixture_a()
                    self.restart()
                    review = self.prepare(pending["plan_id"])
                    if phase != "prepared":
                        accepted = self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"])
                        self.status(accepted, "success")
                    if phase == "ready_after_committed_pay":
                        pay = self.call(self.bank, "resume_plan", pending["plan_id"])
                        self.status(pay, "pending")
                        self.status(self.call(self.bank, "confirm", pay["request_id"], pay["confirmation_code"]), "success")
                        self.assert_t100_once()
                    self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM requests WHERE user_id='alice' AND status='pending'")[0][0], 0)
                    before = self.financial_snapshot()
                    plan_before = self.plan(pending["plan_id"])
                    audit_before = self.audit_snapshot()
                    model_calls = []
                    class NoModelForCancellation:
                        def propose(self, text, context):
                            model_calls.append(text)
                            raise AssertionError("explicit cancellation must be handled before any model call")
                    if cancellation_entry == "fixed_cancel":
                        cancellation = self.call(self.bank, "cancel")
                    else:
                        cancellation = self.call(self.bank, "handle_text", "取消", NoModelForCancellation())
                    self.record_trace("cancel_recovery_without_pending_node", {
                        "phase": phase,
                        "entry": cancellation_entry,
                        "cancellation_status": cancellation.get("status"),
                        "cancellation_reason": cancellation.get("reason"),
                        "financial_before": before,
                        "financial_after": self.financial_snapshot(),
                        "model_calls": len(model_calls),
                    })
                    self.status(cancellation, "cancelled", "cancelling an active recovery round without a pending node")
                    self.assertNotEqual(cancellation.get("reason"), "no_pending")
                    self.assertEqual(model_calls, [])
                    self.assertEqual(self.financial_snapshot(), before)
                    after_cancel = self.plan(pending["plan_id"])
                    self.assertNotIn(after_cancel["recovery_status"], {"authorized", "review_pending"})
                    replay = self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"])
                    if phase == "prepared":
                        self.rejected(replay)
                    else:
                        # A truthful already-consumed receipt may be replayed,
                        # but it must never grant execution permission again.
                        self.assertIn(replay.get("status"), ("rejected", "success"))
                    after_replay = self.plan(pending["plan_id"])
                    self.assertNotIn(after_replay["recovery_status"], {"authorized", "review_pending"})
                    self.rejected(self.call(self.bank, "resume_plan", pending["plan_id"]))
                    self.rejected(self.call(self.bank, "prepare_recovery", pending["plan_id"]))
                    self.assertEqual(self.financial_snapshot(), before)
                    final = self.plan(pending["plan_id"])
                    self.assertEqual(final["completed_steps"], plan_before["completed_steps"])
                    old_steps = self.steps(plan_before)
                    final_steps = self.steps(final)
                    for step_id, old_step in old_steps.items():
                        if old_step["status"] == "success":
                            self.assertEqual(final_steps[step_id]["status"], "success")
                            self.assertEqual(final_steps[step_id]["result"], old_step["result"])
                        else:
                            self.assertNotIn(final_steps[step_id]["status"], {"success", "pending"})
                    self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM requests WHERE user_id='alice' AND status='pending'")[0][0], 0)
                    added_audit = self.audit_snapshot()[len(audit_before):]
                    self.assertTrue(any(row[4] == "alice" and row[10] == "cancelled" and row[12] == pending["plan_id"] for row in added_audit), "recovery cancellation must have a persisted plan-linked audit")
                    self.status(self.call(self.bank, "propose", {"intent": "query_balance", "params": {}}), "success", "cancellation must not disable an otherwise healthy service")

    def test_r_15_interrupt_keeps_committed_effects(self):
        old = self.fixture_b()
        self.call(self.bank, "interrupt_plan", old["plan_id"])
        current = self.plan(old["plan_id"])
        self.assertTrue(current["committed_effects"])
        self.assertIn("subs", current["remaining_steps"])
        self.assertIn("10000", json.dumps(current["committed_effects"]))
        self.assert_t100_once()

    def test_r_16_takeover_has_queue_detail_and_real_record_entry(self):
        for phase in ("waiting", "committed", "failed_bill"):
            with self.subTest(phase=phase):
                if phase == "failed_bill":
                    def fault(event):
                        if event["point"] == "node_before_commit" and event["step_id"] == "bill":
                            raise RuntimeError("independent_takeover_bill_fault")
                    self.fresh_fixture("r16-" + phase, checkpoint_hook=fault)
                    response = self.call(self.bank, "propose", copy.deepcopy(PLAN))
                    plan_id = response["plan_id"]
                    self.restart()
                else:
                    self.fresh_fixture("r16-" + phase)
                    response = self.fixture_b() if phase == "committed" else self.fixture_a()
                    plan_id = response["plan_id"]
                item_id = self.takeover(plan_id)
                listed = self.call(self.bank, "list_handovers")
                self.status(listed, "success")
                self.assertIn(item_id, [item["handover_id"] for item in listed["data"]["handovers"]])
                result = self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "Review remaining simulated steps")
                self.status(result, "success")
                self.assertTrue(self.handover(item_id)["entries"])
                if phase != "failed_bill":
                    self.rejected(self.call(self.bank, "confirm", response["request_id"], response["confirmation_code"]))

    def test_r_17_disposition_identity_history_and_close_survive_restart(self):
        old = self.fixture_b()
        item_id = self.takeover(old["plan_id"])
        before = self.financial_snapshot()
        self.status(self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "Owner will inspect simulated payment"), "success")
        first_entries = copy.deepcopy(self.handover(item_id)["entries"])
        self.status(self.call(self.bank, "record_handover", item_id, "close_record", "manual_follow_up", "Administrative record closed; no reverse transfer"), "success")
        self.restart()
        item = self.handover(item_id)
        self.assertEqual(item["status"], "closed_record")
        self.assertEqual(item["entries"][:len(first_entries)], first_entries)
        for entry in item["entries"]:
            for field in ("entry_id", "actor_user_id", "actor_role", "recorded_at", "disposition", "compensation", "note_redacted"):
                self.assertIn(field, entry)
            self.assertEqual(entry["actor_user_id"], "alice")
            self.assertEqual(entry["actor_role"], "task_owner")
        self.assertEqual(self.financial_snapshot(), before)
        self.assertTrue(item["committed_effects"])
        self.assertTrue(item["manual_actions"])

    def test_r_18_other_user_cannot_read_control_or_close(self):
        old = self.fixture_a()
        self.restart()
        review = self.prepare(old["plan_id"])
        bob = self.new_service(user_id="bob")
        before = self.financial_snapshot()
        for method, args in (
            ("get_plan", (old["plan_id"],)), ("prepare_recovery", (old["plan_id"],)),
            ("resume_plan", (old["plan_id"],)), ("interrupt_plan", (old["plan_id"],)),
            ("takeover_plan", (old["plan_id"],)),
            ("confirm_recovery", (review["review_id"], review["recovery_code"])),
        ):
            with self.subTest(method=method):
                response = self.call(bob, method, *args)
                self.rejected(response)
                self.assertEqual(response.get("reason"), "not_found_or_not_owned")
                self.assertNotIn("alice-main", json.dumps(response))
        item_id = self.takeover(old["plan_id"])
        for method, args in (("get_handover", (item_id,)), ("record_handover", (item_id, "close_record", "no_compensation_needed", ""))):
            self.rejected(self.call(bob, method, *args))
        for method, key in (("list_plans", "plans"), ("list_handovers", "handovers")):
            response = self.call(bob, method)
            self.status(response, "success")
            self.assertEqual(response["data"][key], [])
        self.assertEqual(self.financial_snapshot(), before)

    def test_r_19_failed_cancelled_expired_rejected_dependencies_block(self):
        for outcome in ("failed", "cancelled", "expired", "rejected"):
            with self.subTest(outcome=outcome):
                if outcome == "failed":
                    def fault(event):
                        if event["point"] == "node_before_commit" and event["step_id"] == "bill":
                            raise RuntimeError("independent_dependency_fault")
                    self.fresh_fixture("r19-" + outcome, checkpoint_hook=fault)
                    response = self.call(self.bank, "propose", copy.deepcopy(PLAN))
                else:
                    self.fresh_fixture("r19-" + outcome)
                    response = self.fixture_a()
                    if outcome == "cancelled":
                        self.call(self.bank, "cancel", response["request_id"])
                    elif outcome == "expired":
                        self.clock.advance(300)
                        self.call(self.bank, "confirm", response["request_id"], response["confirmation_code"])
                    else:
                        self.sql_change("UPDATE accounts SET balance_cents=9999 WHERE account_id='alice-main'")
                        self.call(self.bank, "confirm", response["request_id"], response["confirmation_code"])
                self.call(self.bank, "resume_plan", response["plan_id"])
                # A new instance is used only for observation after a fault; it
                # does not count as independent process-exit evidence.
                self.restart()
                current = self.steps(self.plan(response["plan_id"]))
                self.assertEqual(current["subs"]["status"], "not_started")
                self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM transfers WHERE status='success'")[0][0], 0)

    def test_r_20_failure_counter_survives_recovery_and_locks_third(self):
        old = self.fixture_a()
        for _ in range(2):
            self.call(self.bank, "confirm", old["request_id"], self.pending_wrong_code(old))
        self.assertEqual(self.sql_rows("SELECT failures FROM verification_state WHERE user_id='alice' AND intent='transfer'")[0][0], 2)
        self.restart()
        new = self.recovered_pay(old)
        self.call(self.bank, "confirm", new["request_id"], self.pending_wrong_code(new))
        count, locked_until = self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")[0]
        self.assertEqual(count, 3)
        self.assertEqual(datetime_module.datetime.fromisoformat(locked_until), self.clock() + datetime_module.timedelta(minutes=10))
        self.call(self.bank, "cancel", new["request_id"])
        self.assertEqual(self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")[0], (count, locked_until))
        self.assert_initial_money()

    def test_r_21_lock_deadline_survives_restart_and_account_change(self):
        before = self.lock_transfer()
        self.restart()
        candidate = copy.deepcopy(TRANSFER)
        candidate["params"].update(account_id="alice-savings", amount_cents=1)
        self.rejected(self.call(self.bank, "propose", candidate))
        self.assertEqual(self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")[0], before)
        self.clock.advance(599)
        self.rejected(self.call(self.bank, "propose", copy.deepcopy(TRANSFER)))
        self.clock.advance(1)
        response = self.call(self.bank, "propose", copy.deepcopy(TRANSFER))
        self.status(response, "pending")
        self.assert_initial_money()

    def test_r_22_balance_and_ownership_checked_at_review_and_commit(self):
        for alteration in ("balance", "owner"):
            for phase in ("before_review", "before_commit"):
                with self.subTest(alteration=alteration, phase=phase):
                    self.fresh_fixture("r22-" + alteration + "-" + phase)
                    old = self.fixture_a()
                    self.restart()
                    pending = self.recovered_pay(old) if phase == "before_commit" else None
                    if alteration == "balance":
                        self.sql_change("UPDATE accounts SET balance_cents=9999 WHERE account_id='alice-main'")
                    else:
                        self.sql_change("UPDATE accounts SET user_id='bob' WHERE account_id='alice-main'")
                    before = self.financial_snapshot()
                    if pending:
                        response = self.call(self.bank, "confirm", pending["request_id"], pending["confirmation_code"])
                    else:
                        response = self.call(self.bank, "prepare_recovery", old["plan_id"])
                    self.rejected(response)
                    self.assertEqual(self.financial_snapshot(), before)

    def test_r_23_current_all_account_cumulative_amount_red_refused(self):
        old = self.fixture_a()
        self.sql_change("INSERT INTO transfers(request_id,user_id,source_account_id,target_account_id,amount_cents,executed_at,shanghai_date,status) VALUES(?,?,?,?,?,?,?,?)", ("fixture-earlier-transfer", "alice", "alice-savings", "bob-main", 95000, self.clock().isoformat(), "2026-10-23", "success"))
        self.restart()
        before = self.financial_snapshot()
        response = self.call(self.bank, "prepare_recovery", old["plan_id"])
        self.rejected(response)
        self.assertEqual(self.financial_snapshot(), before)
        self.assertEqual(self.sql_rows("SELECT COALESCE(SUM(amount_cents),0) FROM transfers WHERE user_id='alice' AND status='success'")[0][0], 95000)

    def test_r_24_shanghai_midnight_uses_new_date_and_consent(self):
        self.clock.value = datetime_module.datetime(2026, 10, 23, 23, 59, tzinfo=SHANGHAI)
        old = self.fixture_a()
        self.clock.advance(120)
        self.restart()
        pending = self.recovered_pay(old)
        self.assertEqual(datetime_module.datetime.fromisoformat(pending["expires_at"]), self.clock() + datetime_module.timedelta(minutes=5))
        self.status(self.call(self.bank, "confirm", pending["request_id"], pending["confirmation_code"]), "success")
        self.assertEqual(self.sql_rows("SELECT shanghai_date FROM transfers WHERE status='success'")[0][0], "2026-10-24")
        self.assert_t100_once()

    def test_r_25_changed_mapping_target_or_amount_invalidates_old_consent(self):
        for change in ("mapping", "contact", "amount", "recovery_binding", "revision"):
            with self.subTest(change=change):
                self.fresh_fixture("r25-" + change)
                old = self.fixture_a()
                if change == "revision":
                    self.restart()
                    review = self.prepare(old["plan_id"])
                    self.call(self.bank, "interrupt_plan", old["plan_id"])
                    self.rejected(self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"]))
                elif change in {"mapping", "recovery_binding"}:
                    if change == "recovery_binding":
                        self.restart()
                        review = self.prepare(old["plan_id"])
                    self.sql_change("UPDATE contacts SET account_id='alice-savings' WHERE contact_id='wang' AND user_id='alice'")
                    if change == "recovery_binding":
                        self.rejected(self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"]))
                else:
                    changed = copy.deepcopy(TRANSFER)
                    changed["params"]["contact_id" if change == "contact" else "amount_cents"] = "li" if change == "contact" else 20000
                    self.call(self.bank, "propose", changed)
                self.rejected(self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"]))
                self.assert_initial_money()

    def test_r_26_superseded_plan_is_history_not_recoverable(self):
        old = self.fixture_a()
        self.status(self.call(self.bank, "propose", {"intent": "query_balance", "params": {}}), "success")
        self.restart()
        current = self.plan(old["plan_id"])
        self.assertEqual(current["stop_reason"], "superseded_by_new_task")
        self.assertEqual(current["recovery_status"], "blocked")
        self.rejected(self.call(self.bank, "prepare_recovery", old["plan_id"]))
        self.rejected(self.call(self.bank, "resume_plan", old["plan_id"]))
        self.assert_initial_money()

    def test_r_27_execution_audit_failure_rolls_back_and_stops(self):
        armed = {"value": False}
        def fault(event):
            if armed["value"] and event.get("event") == "executed" and event.get("intent") == "transfer":
                raise RuntimeError("independent_success_audit_fault")
        self.fresh_fixture("r27", audit_hook=fault)
        old = self.fixture_a()
        before = self.financial_snapshot()
        armed["value"] = True
        response = self.call(self.bank, "confirm", old["request_id"], old["confirmation_code"])
        self.status(response, "failed")
        self.assertEqual(response.get("reason"), "audit_unavailable")
        self.assertEqual(self.financial_snapshot(), before)
        self.assertNotEqual(self.sql_rows("SELECT status FROM requests WHERE request_id=?", (old["request_id"],))[0][0], "success")
        saved = json.loads(self.sql_rows("SELECT snapshot_json FROM recovery_plans WHERE plan_id=?", (old["plan_id"],))[0][0])
        self.assertNotEqual(next(item for item in saved["steps"] if item["id"] == "pay")["status"], "success")
        for method, args in (("resume_plan", (old["plan_id"],)), ("prepare_recovery", (old["plan_id"],)), ("propose", (copy.deepcopy(TRANSFER),))):
            self.status(self.call(self.bank, method, *args), "failed")
        self.assertEqual(self.financial_snapshot(), before)
        self.assertEqual(self.sql_rows("SELECT COUNT(*) FROM audit_log WHERE event='executed' AND intent='transfer'")[0][0], 0)

    def test_r_28_control_audit_failures_do_not_grant_or_fake_persistence(self):
        for event_name in ("recovery_authorized", "plan_interrupted", "plan_takeover", "handover_recorded"):
            with self.subTest(event=event_name):
                armed = {"value": False}
                def fault(event):
                    if armed["value"] and event.get("event") == event_name:
                        raise RuntimeError("independent_control_audit_fault")
                self.fresh_fixture("r28-" + event_name, audit_hook=fault)
                old = self.fixture_b()
                if event_name == "recovery_authorized":
                    self.restart()
                    # Re-open with the same public hook after restart.
                    self.bank.close()
                    self.bank = self.new_service(audit_hook=fault)
                    review = self.prepare(old["plan_id"])
                elif event_name == "handover_recorded":
                    item_id = self.takeover(old["plan_id"])
                before = self.financial_snapshot()
                persistent_before = self.sql_rows("SELECT snapshot_json,revision FROM recovery_plans WHERE plan_id=?", (old["plan_id"],))
                armed["value"] = True
                if event_name == "recovery_authorized":
                    response = self.call(self.bank, "confirm_recovery", review["review_id"], review["recovery_code"])
                elif event_name == "plan_interrupted":
                    response = self.call(self.bank, "interrupt_plan", old["plan_id"])
                elif event_name == "plan_takeover":
                    response = self.call(self.bank, "takeover_plan", old["plan_id"])
                else:
                    response = self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "No business change")
                self.status(response, "failed")
                self.assertEqual(response.get("reason"), "audit_unavailable")
                self.assertEqual(self.financial_snapshot(), before)
                self.assertEqual(self.sql_rows("SELECT snapshot_json,revision FROM recovery_plans WHERE plan_id=?", (old["plan_id"],)), persistent_before)
                self.status(self.call(self.bank, "resume_plan", old["plan_id"]), "failed")
                self.assert_t100_once()

    def test_r_29_audit_is_append_only_and_correlated(self):
        old = self.fixture_a()
        baseline = self.audit_snapshot()
        self.call(self.bank, "confirm", old["request_id"], self.pending_wrong_code(old))
        self.call(self.bank, "cancel", old["request_id"])
        self.call(self.bank, "interrupt_plan", old["plan_id"])
        item_id = self.takeover(old["plan_id"])
        self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "Check retained results")
        self.restart()
        after = self.audit_snapshot()
        self.assertEqual(after[:len(baseline)], baseline)
        related = [row for row in after if row[12] == old["plan_id"]]
        self.assertTrue(related)
        self.assertTrue(all(row[4] == "alice" for row in related))
        self.assertTrue(any(row[9] == "plan_takeover" for row in related))
        self.assertFalse(any(row[9] == "executed" and row[6] == "transfer" for row in related))
        for statement in ("DELETE FROM audit_log", "UPDATE audit_log SET reason='changed'"):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.sql_change(statement)
        self.record_trace("audit_events_after", after)

    def test_r_30_no_credentials_in_history_snapshots_or_dispositions(self):
        secret_marker = "INDEPENDENT_AUTH_SECRET_DO_NOT_PERSIST"
        SECRETS_FOR_EVIDENCE.add(secret_marker)
        old = self.fixture_a()
        old_code = old["confirmation_code"]
        self.restart()
        review = self.prepare(old["plan_id"])
        item_id = self.takeover(old["plan_id"])
        self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "password=" + secret_marker + " totp_secret=" + secret_marker)
        history = [self.plan(old["plan_id"]), self.handover(item_id), self.audit_snapshot()]
        persistent = self.sql_rows("SELECT snapshot_json FROM recovery_plans") + self.sql_rows("SELECT raw_input_redacted,params_redacted,reason FROM audit_log") + self.sql_rows("SELECT params_json,binding_json FROM requests")
        encoded = json.dumps([history, persistent], ensure_ascii=False, default=str)
        for secret in (secret_marker, old_code, review["recovery_code"]):
            self.assertFalse(secret in encoded, "a transient secret reached durable/history content")
        self.assert_initial_money()

    def test_r_31_committed_payment_never_automatically_reversed(self):
        old = self.fixture_b()
        before = self.financial_snapshot()
        item_id = self.takeover(old["plan_id"])
        self.status(self.call(self.bank, "record_handover", item_id, "record", "manual_follow_up", "Owner asked to inspect an already committed payment"), "success")
        for intent in ("reverse_transfer", "refund", "rollback_transfer"):
            self.rejected(self.call(self.bank, "propose", {"intent": intent, "params": {"request_id": old["request_id"]}}))
        self.assertEqual(self.financial_snapshot(), before)
        self.assert_t100_once()
        self.assertTrue(self.handover(item_id)["manual_actions"])

    def test_r_32_cancelled_subscription_and_historical_bills_remain(self):
        candidate = {"steps": [
            {"id": "cancel", "intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}, "depends_on": []},
            {"id": "pay", **copy.deepcopy(TRANSFER), "depends_on": ["cancel"]},
        ]}
        pending = self.call(self.bank, "propose", candidate)
        self.status(pending, "pending")
        self.status(self.call(self.bank, "confirm", pending["request_id"], pending["confirmation_code"]), "success")
        pay = self.call(self.bank, "resume_plan", pending["plan_id"])
        self.call(self.bank, "cancel", pay["request_id"])
        self.restart()
        self.assertEqual(self.sql_rows("SELECT status FROM subscriptions WHERE subscription_id='sub-video'")[0][0], "cancelled")
        bills = self.call(self.bank, "propose", {"intent": "analyze_bills", "params": {}})
        self.assertEqual(bills["data"]["actual_expense_cents"], 5970)
        query = self.call(self.bank, "propose", {"intent": "query_subscriptions", "params": {}})
        subscriptions = self.call(self.bank, "confirm", query["request_id"], query["confirmation_code"])
        self.assertEqual(subscriptions["data"]["future_expected_cents"], 2980)
        self.assert_initial_money()

    def test_r_33_new_compensation_intents_and_extra_fields_rejected(self):
        for intent in ("restore_subscription", "refund", "update_audit", "delete_audit"):
            with self.subTest(intent=intent):
                before = self.financial_snapshot()
                response = self.call(self.bank, "propose", {"intent": intent, "params": {"subscription_id": "sub-video"}})
                self.rejected(response)
                self.assertEqual(self.financial_snapshot(), before)
        old = self.fixture_a()
        item_id = self.takeover(old["plan_id"])
        for compensation in ("refund_completed", "restore_subscription", "bank_confirmed"):
            self.rejected(self.call(self.bank, "record_handover", item_id, "record", compensation, ""))
        self.assert_initial_money()

    def test_r_34_red_stays_refused_even_after_synthetic_factors(self):
        candidate = copy.deepcopy(TRANSFER)
        candidate["params"]["amount_cents"] = 100001
        self.rejected(self.call(self.bank, "propose", candidate))
        password = "IndependentFixture-Password!"
        secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
        SECRETS_FOR_EVIDENCE.update({password, secret})
        enrolled = self.call(self.bank, "enroll_strong_auth", password, secret, totp_code=synthetic_totp(secret, self.clock()))
        self.status(enrolled, "success")
        self.clock.advance(30)
        red = self.call(self.bank, "propose", candidate)
        self.status(red, "pending")
        self.assertEqual(red.get("tier"), "red")
        self.assertNotIn("confirmation_code", red)
        response = self.call(self.bank, "strong_verify", red["request_id"], password, synthetic_totp(secret, self.clock()), confirmed=True)
        self.rejected(response)
        self.assertEqual(response.get("strong_verification"), "passed")
        self.assert_initial_money()

    def test_r_35_corrupt_snapshots_are_isolated_without_guessing(self):
        for damage in ("bad_json", "missing_node", "wrong_type", "cycle", "wrong_owner"):
            with self.subTest(damage=damage):
                self.fresh_fixture("r35-" + damage)
                old = self.fixture_a()
                original = self.plan(old["plan_id"])
                self.call(self.bank, "propose", copy.deepcopy(PLAN))
                # Locate the second plan by exclusion, never by a private name.
                ids = [item["plan_id"] for item in self.call(self.bank, "list_plans")["data"]["plans"]]
                healthy_id = next(item for item in ids if item != old["plan_id"])
                damaged = copy.deepcopy(original)
                if damage == "bad_json":
                    raw = "{independent_invalid_json"
                else:
                    if damage == "missing_node":
                        damaged["steps"] = [item for item in damaged["steps"] if item["id"] != "bill"]
                    elif damage == "wrong_type":
                        damaged["steps"][1]["params"]["amount_cents"] = True
                    elif damage == "cycle":
                        damaged["steps"][0]["depends_on"] = ["subs"]
                    else:
                        damaged["user_id"] = "bob"
                    raw = json.dumps(damaged)
                self.sql_change("UPDATE recovery_plans SET snapshot_json=? WHERE plan_id=?", (raw, old["plan_id"]))
                self.restart()
                before = self.financial_snapshot()
                listed = self.call(self.bank, "list_plans")
                self.status(listed, "success")
                corrupted = next(item for item in listed["data"]["plans"] if item["plan_id"] == old["plan_id"])
                self.assertEqual(corrupted.get("recovery_status"), "corrupt")
                self.rejected(self.call(self.bank, "prepare_recovery", old["plan_id"]))
                self.rejected(self.call(self.bank, "resume_plan", old["plan_id"]))
                self.plan(healthy_id)
                self.assertEqual(self.financial_snapshot(), before)

    def test_r_36_bad_ids_and_terminal_replays_are_safe(self):
        old = self.fixture_a()
        item_id = self.takeover(old["plan_id"])
        before = self.financial_snapshot()
        invalid_ids = (None, True, 123, "", "x" * 129, "../data/bank.db", "C:\\outside\\secret", "他人")
        for value in invalid_ids:
            for method in ("get_plan", "prepare_recovery", "resume_plan", "interrupt_plan", "takeover_plan", "get_handover"):
                with self.subTest(value_type=type(value).__name__, method=method):
                    self.rejected(self.call(self.bank, method, value))
        self.status(self.call(self.bank, "record_handover", item_id, "close_record", "no_compensation_needed", "No business undo requested"), "success")
        entries = copy.deepcopy(self.handover(item_id)["entries"])
        replay = self.call(self.bank, "record_handover", item_id, "close_record", "no_compensation_needed", "No business undo requested")
        self.assertNotEqual(replay.get("status"), "failed")
        self.assertEqual(self.handover(item_id)["entries"], entries)
        self.assertEqual(self.financial_snapshot(), before)
        self.fresh_fixture("r36-control-types")
        old = self.fixture_a()
        self.restart()
        review = self.prepare(old["plan_id"])
        count_before = self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'")
        for bad_code in (None, True, 123456, "１２３４５６", "12345", "1234567", ""):
            with self.subTest(recovery_code_type=type(bad_code).__name__):
                self.rejected(self.call(self.bank, "confirm_recovery", review["review_id"], bad_code))
        self.assertEqual(self.sql_rows("SELECT failures,locked_until FROM verification_state WHERE user_id='alice' AND intent='transfer'"), count_before)
        self.assert_initial_money()

    def test_r_37_http_new_routes_preserve_strict_guards_and_pending(self):
        with PublicHttpFixture(self.directory / "http.db", self.clock) as server:
            response = server.post("/api/message", {"text": "先分析我本月账单，再从我的主账户alice-main给已登记的联系人小王转100元，最后查询我的订阅。"})
            self.assertEqual(response[0], 200)
            pending = remember_transient_codes(response[2])
            self.status(pending, "pending")
            plan_id = pending["plan_id"]
            routes = {
                "/api/plan/list": {}, "/api/plan/get": {"plan_id": plan_id},
                "/api/plan/recovery/prepare": {"plan_id": plan_id},
                "/api/plan/recovery/confirm": {"review_id": "unused-review", "recovery_code": "000000"},
                "/api/handover/list": {}, "/api/handover/get": {"handover_id": "unused-handover"},
                "/api/handover/record": {"handover_id": "unused-handover", "disposition": "record", "compensation": "manual_follow_up"},
            }
            for path, body in routes.items():
                for fault in ("csrf", "origin", "fetch_site", "extra", "duplicate_json", "duplicate_csrf"):
                    with self.subTest(path=path, fault=fault):
                        result = server.post(path, body, fault=fault)
                        if fault == "duplicate_csrf":
                            self.assertIn(result[0], (400, 403))
                        else:
                            self.assertEqual(result[0], 403 if fault in {"csrf", "origin", "fetch_site"} else 400)
                        self.assertEqual(result[1].get("cache-control"), "no-store")
                        self.assertNotIn("confirmation_code", json.dumps(result[2]))
            # The network guard must reject before invalidating the good pay.
            confirmed = server.post("/api/confirm", {"request_id": pending["request_id"], "confirmation_code": pending["confirmation_code"]})
            self.status(confirmed[2], "success")
            self.assertEqual(server.post("/api/plan/list", {})[2]["status"], "success")
            detail = server.post("/api/plan/get", {"plan_id": plan_id})[2]
            self.status(detail, "success")
            takeover = server.post("/api/plan/takeover", {"plan_id": plan_id})[2]
            self.assertNotIn(takeover.get("status"), {"failed", "rejected"})
            handover_id = server.post("/api/plan/get", {"plan_id": plan_id})[2]["plan"]["handover_id"]
            self.status(server.post("/api/handover/list", {})[2], "success")
            self.status(server.post("/api/handover/get", {"handover_id": handover_id})[2], "success")
            self.status(server.post("/api/handover/record", {"handover_id": handover_id, "disposition": "record", "compensation": "manual_follow_up", "note": "Local owner follow up only"})[2], "success")
            self.status(server.post("/api/handover/record", {"handover_id": handover_id, "disposition": "close_record", "compensation": "manual_follow_up"})[2], "success")
            closed = server.post("/api/handover/get", {"handover_id": handover_id})[2]["data"]["handover"]
            self.assertEqual(closed["status"], "closed_record")
        with closing(sqlite3.connect(str(self.directory / "http.db"))) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*),SUM(amount_cents) FROM transfers WHERE status='success'").fetchone(), (1, 10000))
        recovery_database = self.directory / "http-recovery.db"
        with PublicHttpFixture(recovery_database, self.clock) as first_session:
            old = remember_transient_codes(first_session.post("/api/message", {"text": "先分析我本月账单，再从我的主账户alice-main给已登记的联系人小王转100元，最后查询我的订阅。"})[2])
            self.status(old, "pending")
            old_csrf = first_session.csrf_token
        with PublicHttpFixture(recovery_database, self.clock) as second_session:
            stale_csrf = second_session.post("/api/plan/get", {"plan_id": old["plan_id"]}, csrf_override=old_csrf)
            self.assertEqual(stale_csrf[0], 403)
            review = remember_transient_codes(second_session.post("/api/plan/recovery/prepare", {"plan_id": old["plan_id"]})[2])
            self.status(review, "pending")
            accepted = second_session.post("/api/plan/recovery/confirm", {"review_id": review["review_id"], "recovery_code": review["recovery_code"]})[2]
            self.status(accepted, "success")
            with closing(sqlite3.connect(str(recovery_database))) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0], 0)
            current = remember_transient_codes(second_session.post("/api/plan/resume", {"plan_id": old["plan_id"]})[2])
            self.status(current, "pending")
            self.assertNotEqual(current["request_id"], old["request_id"])
            self.rejected(second_session.post("/api/confirm", {"request_id": old["request_id"], "confirmation_code": old["confirmation_code"]})[2])
            self.status(second_session.post("/api/confirm", {"request_id": current["request_id"], "confirmation_code": current["confirmation_code"]})[2], "success")
        with closing(sqlite3.connect(str(recovery_database))) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*),SUM(amount_cents) FROM transfers WHERE status='success'").fetchone(), (1, 10000))


class PublicHttpFixture:
    """Only the dependency injection published in src/WEB_API.md is used."""

    def __init__(self, database_path, clock):
        self.database_path = database_path
        self.clock = clock
        self.ready = threading.Event()
        self.error = None
        self.server = None
        self.csrf_token = "independent-recovery-session-" + uuid.uuid4().hex

    def __enter__(self):
        def serve():
            bank = None
            server = None
            try:
                from src.web import LocalServer, BrowserHandler
                bank = BankService(str(self.database_path), user_id="alice", clock=self.clock)
                server = LocalServer(("127.0.0.1", 0), BrowserHandler)
                server.bank = bank
                server.csrf_token = self.csrf_token
                server.model = FixedCandidateModel(PLAN)
                server.model_configured = True
                self.server = server
                self.ready.set()
                server.serve_forever()
            except BaseException as error:
                self.error = error
                self.ready.set()
            finally:
                if server is not None:
                    server.server_close()
                if bank is not None:
                    bank.close()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            raise AssertionError("Local HTTP fixture did not become ready")
        if self.error is not None:
            raise self.error
        self.port = self.server.server_port
        return self

    def __exit__(self, exception_type, exception, exception_traceback):
        if self.server is not None:
            self.server.shutdown()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise AssertionError("Local HTTP fixture did not close")
        if self.error is not None:
            raise self.error

    def post(self, path, body, fault=None, csrf_override=None):
        payload = copy.deepcopy(body)
        if fault == "extra":
            payload["unexpected_field"] = "not allowed"
        raw = json.dumps(payload)
        if fault == "duplicate_json":
            raw = '{"duplicate":"one","duplicate":"two"}'
        encoded = raw.encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.putrequest("POST", path)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(encoded)))
            token = csrf_override if csrf_override is not None else self.csrf_token
            connection.putheader("X-CSRF-Token", "previous-session-token" if fault == "csrf" else token)
            if fault == "duplicate_csrf":
                connection.putheader("X-CSRF-Token", self.csrf_token)
            if fault == "origin":
                connection.putheader("Origin", "https://outside.example.invalid")
            if fault == "fetch_site":
                connection.putheader("Sec-Fetch-Site", "cross-site")
            connection.endheaders(encoded)
            response = connection.getresponse()
            status = response.status
            headers = {name.lower(): value for name, value in response.getheaders()}
            data = json.loads(response.read().decode("utf-8"))
            remember_transient_codes(data)
            return status, headers, data
        finally:
            connection.close()


def synthetic_totp(secret, now):
    key = base64.b32decode(secret, casefold=True)
    counter = int(now.timestamp()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
    result = f"{value:06d}"
    SECRETS_FOR_EVIDENCE.add(result)
    return result


def child_main(mode, database_path):
    clock = TestClock()
    def checkpoint(event):
        if mode == "bill_before" and event["point"] == "node_before_commit" and event["step_id"] == "bill":
            os._exit(71)
        if mode == "pay_before" and event["point"] == "node_before_commit" and event["step_id"] == "pay":
            os._exit(71)
        if mode == "pay_after" and event["point"] == "node_after_commit" and event["step_id"] == "pay":
            os._exit(72)
    bank = BankService(database_path, user_id="alice", clock=clock, checkpoint_hook=checkpoint)
    pending = bank.propose(copy.deepcopy(PLAN))
    if pending.get("status") != "pending":
        raise AssertionError("Child P did not stop for pay confirmation")
    if mode == "pending":
        os._exit(71)
    bank.confirm(pending["request_id"], pending["confirmation_code"])
    raise AssertionError("Documented child checkpoint was not reached")


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.case_records = []
        self.current_started = None

    def startTest(self, test):
        super().startTest(test)
        self.current_started = datetime_module.datetime.now(datetime_module.timezone.utc).isoformat()

    def stopTest(self, test):
        test_name = test.id()
        errors = [message for item, message in self.errors + self.failures if item.id() == test_name or item.id().startswith(test_name + " ")]
        self.case_records.append({
            "test_id": test_name,
            "requirement_id": "R-" + test._testMethodName.split("_")[2],
            "input_and_expected_reference": "docs/30-recovery-acceptance-matrix.md and src/RECOVERY_API.md, same R identifier",
            "started_at": self.current_started,
            "finished_at": datetime_module.datetime.now(datetime_module.timezone.utc).isoformat(),
            "status": "failed" if errors else "passed",
            "actually_run": True,
            "errors": evidence_safe(errors),
            "observations": evidence_safe(getattr(test, "evidence", [])),
        })
        super().stopTest(test)


def run_suite():
    run_identifier = datetime_module.datetime.now(datetime_module.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:10]
    report_path = REPOSITORY / "evidence" / ("recovery-independent-" + run_identifier + ".json")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryIndependentAcceptance)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult)
    started = time.monotonic()
    result = runner.run(suite)
    report = {
        "schema": "recovery-independent-v1",
        "run_id": run_identifier,
        "parent_process_id": os.getpid(),
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "authoring_status": "public-contract-only; no implementation source read",
        "contract": "src/RECOVERY_API.md",
        "matrix": "docs/30-recovery-acceptance-matrix.md",
        "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "contract_sha256": hashlib.sha256((REPOSITORY / "src" / "RECOVERY_API.md").read_bytes()).hexdigest(),
        "matrix_sha256": hashlib.sha256((REPOSITORY / "docs" / "30-recovery-acceptance-matrix.md").read_bytes()).hexdigest(),
        "implementation_version": "Executor must attach its separately captured implementation fingerprint; author does not read implementation source.",
        "independent_databases_parent": str(RUNS_DIRECTORY),
        "normal_database_used": False,
        "real_credentials_used": False,
        "real_model_called": False,
        "tests_run": result.testsRun,
        "subtests": "parameter cases remain attached to R-01 through R-37",
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "successful": result.wasSuccessful() and not result.skipped,
        "cases": result.case_records,
        "least_certain": "HTTP and Python tests do not prove browser UI, real human disposition, independent phone, terminal concealment, bank channels, or production concurrency capacity.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as report_file:
        json.dump(evidence_safe(report), report_file, ensure_ascii=False, indent=2)
    print("Independent evidence: " + str(report_path))
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child_main(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 1:
        raise SystemExit(run_suite())
    else:
        raise SystemExit("Usage: run this file without arguments; child mode is reserved for this suite")

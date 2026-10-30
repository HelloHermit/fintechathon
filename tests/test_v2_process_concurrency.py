"""Independent, offline public-API acceptance for two real OS processes.

Expected outcomes come from docs/01, docs/02, docs/05 and src/PUBLIC_API.md.
This test does not inspect business implementations or existing test files.
Every run appends its evidence, including failures, to the dedicated JSON file.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from collections import Counter
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
EVIDENCE_PATH = REPOSITORY_ROOT / "evidence/v2-process-independent-acceptance.json"
ROUND_COUNT = 10
TOTAL_BUDGET_SECONDS = 55.0
ROUND_BUDGET_SECONDS = 5.0
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
FIXED_TIME = datetime(2026, 10, 11, 12, 0, 0, tzinfo=SHANGHAI)
ATTEMPT: dict = {}


def fixed_test_clock():
    """Use the public test clock seam; production clocks are not modified."""
    return FIXED_TIME


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def source_hashes():
    """Hash bytes only; do not interpret, display or inspect source contents."""
    return {
        f"src/{source_path.name}": hashlib.sha256(source_path.read_bytes()).hexdigest()
        for source_path in sorted((REPOSITORY_ROOT / "src").glob("*.py"))
    }


def public_response(response):
    """Keep public state and amounts, excluding codes and free-form messages."""
    permitted_fields = (
        "status", "request_id", "intent", "tier", "reason", "expires_at",
        "operation", "data", "strong_verification",
    )
    return {name: response[name] for name in permitted_fields if name in response}


def database_snapshot(database_path):
    """Read only documented tables/columns, and always close this connection."""
    connection = sqlite3.connect(f"file:{Path(database_path).as_posix()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        selections = {
            "accounts": "SELECT account_id,user_id,balance_cents FROM accounts ORDER BY account_id",
            "transfers": (
                "SELECT request_id,user_id,source_account_id,target_account_id,amount_cents,"
                "executed_at,shanghai_date,status FROM transfers ORDER BY request_id"
            ),
            "transactions": (
                "SELECT transaction_id,user_id,account_id,amount_cents,category,occurred_at,"
                "status,kind FROM transactions ORDER BY transaction_id"
            ),
            "requests": (
                "SELECT request_id,user_id,intent,params_json,tier,status,created_at,expires_at "
                "FROM requests ORDER BY request_id"
            ),
            "audit": (
                "SELECT id,timestamp,request_id,user_id,intent,tier,event,result,reason "
                "FROM audit_log ORDER BY id"
            ),
        }
        return {
            name: [dict(row) for row in connection.execute(statement)]
            for name, statement in selections.items()
        }
    finally:
        connection.close()


def transfer_candidate(account_id, amount_cents):
    return {
        "intent": "transfer",
        "params": {"account_id": account_id, "contact_id": "wang", "amount_cents": amount_cents},
    }


def concurrent_worker(database_path, account_id, propose_barrier, confirm_barrier, close_release, sender):
    """Construct the service here, then hold it open until both results arrive."""
    service = None
    result_sent = False
    worker_result = {"pid": os.getpid(), "account_id": account_id, "started_at_utc": utc_now()}
    stage = "import"
    try:
        worker_result["source_hashes_before_import"] = source_hashes()
        from src.bank import BankService

        stage = "construct"
        construction_start = time.perf_counter_ns()
        service = BankService(database_path, user_id="alice", clock=fixed_test_clock)
        worker_result["construct"] = {
            "pid": os.getpid(),
            "start_ns": construction_start,
            "end_ns": time.perf_counter_ns(),
        }
        sender.send({"phase": "ready", "pid": os.getpid(), "account_id": account_id})

        stage = "propose_barrier"
        propose_barrier.wait(timeout=4.0)
        stage = "propose"
        proposal_start = time.perf_counter_ns()
        proposal = service.propose(transfer_candidate(account_id, 4000), raw_input="双进程40元转账专项")
        worker_result["propose"] = {
            "start_ns": proposal_start,
            "end_ns": time.perf_counter_ns(),
            "response": public_response(proposal),
        }
        sender.send({"phase": "proposed", "pid": os.getpid(), "step": worker_result["propose"]})

        stage = "confirm_barrier"
        confirm_barrier.wait(timeout=4.0)
        confirm_start = time.perf_counter_ns()
        stage = "confirm"
        if proposal.get("status") == "pending" and "confirmation_code" in proposal:
            confirmation = service.confirm(proposal["request_id"], proposal["confirmation_code"])
            worker_result["confirm"] = {
                "attempted": True,
                "start_ns": confirm_start,
                "end_ns": time.perf_counter_ns(),
                "response": public_response(confirmation),
            }
        else:
            worker_result["confirm"] = {
                "attempted": False,
                "start_ns": confirm_start,
                "end_ns": time.perf_counter_ns(),
                "reason": "public_proposal_did_not_supply_a_confirmation_code",
            }
        worker_result["finished_at_utc"] = utc_now()
        sender.send({"phase": "result", "result": worker_result})
        result_sent = True
    except Exception as exception:
        worker_result["error"] = {"stage": stage, "type": type(exception).__name__}
        if not result_sent:
            sender.send({"phase": "result", "result": worker_result})
    finally:
        release_observed = close_release.wait(timeout=7.0)
        close_result = {
            "phase": "closed", "pid": os.getpid(),
            "release_observed": release_observed, "start_ns": time.perf_counter_ns(),
        }
        try:
            if service is not None:
                service.close()
            close_result["status"] = "closed" if service is not None else "not_constructed"
        except Exception as exception:
            close_result["status"] = "error"
            close_result["error_type"] = type(exception).__name__
        close_result["end_ns"] = time.perf_counter_ns()
        close_result["source_hashes_after_close"] = source_hashes()
        try:
            sender.send(close_result)
        finally:
            sender.close()


def collect_phase(receivers, phase, deadline, round_record):
    """Collect every process without joining or closing either service early."""
    collected = []
    remaining = set(range(len(receivers)))
    while remaining:
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"timeout collecting {phase}")
        for index in list(remaining):
            if not receivers[index].poll():
                continue
            message = receivers[index].recv()
            round_record.setdefault("process_messages", []).append(message)
            if message["phase"] != phase:
                raise RuntimeError(f"unexpected process phase while collecting {phase}")
            collected.append(message)
            remaining.remove(index)
        if remaining:
            time.sleep(0.005)
    return collected


def inspect_invariants(round_record):
    """Apply fixed business expectations, independent of implementation choices."""
    issues = round_record["issues"]

    def check(condition, name):
        if not condition:
            issues.append(name)

    initial = round_record["initial_snapshot"]
    before_close = round_record["before_close_snapshot"]
    final = round_record["after_close_snapshot"]
    initial_balances = {row["account_id"]: row["balance_cents"] for row in initial["accounts"]}
    final_balances = {row["account_id"]: row["balance_cents"] for row in final["accounts"]}
    check(initial_balances == {"alice-main": 1000000, "alice-savings": 500000, "bob-main": 100000},
          "documented_initial_balances_mismatch")
    successful_transfers = [row for row in final["transfers"] if row["status"] == "success"]
    alice_daily = [row for row in successful_transfers
                   if row["user_id"] == "alice" and row["shanghai_date"] == FIXED_TIME.date().isoformat()]
    successful_audit = [row for row in final["audit"]
                        if row["intent"] == "transfer" and row["event"] == "executed"
                        and row["result"] == "success"]
    baseline_id = round_record["baseline"]["confirm"]["request_id"]
    additional = [row for row in successful_transfers if row["request_id"] != baseline_id]
    check(sum(row["amount_cents"] for row in alice_daily) <= 100000, "daily_limit_exceeded")
    check(len(additional) <= 1, "both_40_yuan_transfers_succeeded")
    check(len(successful_transfers) == 1 + len(additional), "baseline_transfer_missing")
    baseline_rows = [row for row in successful_transfers if row["request_id"] == baseline_id]
    check(len(baseline_rows) == 1 and baseline_rows[0]["amount_cents"] == 95000,
          "baseline_950_yuan_transfer_mismatch")
    check(all(row["amount_cents"] == 4000 for row in additional), "unexpected_concurrent_amount")
    check(all(row["source_account_id"] in ("alice-main", "alice-savings")
              and row["target_account_id"] == "bob-main" and row["user_id"] == "alice"
              for row in successful_transfers), "unexpected_successful_transfer_parties")
    expected_balances = dict(initial_balances)
    for row in successful_transfers:
        if row["source_account_id"] in expected_balances and row["target_account_id"] in expected_balances:
            expected_balances[row["source_account_id"]] -= row["amount_cents"]
            expected_balances[row["target_account_id"]] += row["amount_cents"]
    check(final_balances == expected_balances, "balances_disagree_with_successful_transfers_or_partial_debit")
    check(all(value >= 0 for value in final_balances.values()), "negative_balance")
    check(sum(final_balances.values()) == sum(initial_balances.values()), "money_not_conserved")
    initial_transaction_ids = {row["transaction_id"] for row in initial["transactions"]}
    new_transactions = [row for row in final["transactions"]
                        if row["transaction_id"] not in initial_transaction_ids]
    account_users = {row["account_id"]: row["user_id"] for row in initial["accounts"]}
    expected_transaction_entries = []
    for row in successful_transfers:
        for account_id in (row["source_account_id"], row["target_account_id"]):
            expected_transaction_entries.append((account_users.get(account_id), account_id, row["amount_cents"]))
    actual_transaction_entries = [
        (row["user_id"], row["account_id"], abs(row["amount_cents"]))
        for row in new_transactions if row["status"] == "success"
    ]
    check(Counter(actual_transaction_entries) == Counter(expected_transaction_entries),
          "successful_transaction_entries_disagree_with_both_transfer_parties")
    transfer_ids = [row["request_id"] for row in successful_transfers]
    audit_ids = [row["request_id"] for row in successful_audit]
    check(len(transfer_ids) == len(set(transfer_ids)), "duplicate_successful_transfer")
    check(sorted(transfer_ids) == sorted(audit_ids), "successful_transfer_audit_not_one_to_one")
    successful_response_ids = [baseline_id]
    for worker in round_record["workers"]:
        response = worker.get("confirm", {}).get("response", {})
        if response.get("status") == "success":
            successful_response_ids.append(response.get("request_id"))
    check(sorted(transfer_ids) == sorted(successful_response_ids), "success_response_disagrees_with_database")
    check(before_close["accounts"] == final["accounts"], "service_close_changed_balances")
    check(before_close["transfers"] == final["transfers"], "service_close_changed_transfers")
    check(before_close["transactions"] == final["transactions"], "service_close_changed_transactions")
    worker_pids = [worker["pid"] for worker in round_record["workers"]]
    check(len(set(worker_pids)) == 2 and os.getpid() not in worker_pids,
          "two_distinct_child_processes_not_proven")
    check(all(worker.get("construct", {}).get("pid") == worker["pid"]
              for worker in round_record["workers"]), "service_not_constructed_in_child")
    check(all(closed["release_observed"] and closed["status"] == "closed"
              for closed in round_record["closed"]), "connections_not_closed_after_common_release")
    check(all(item["exit_code"] == 0 and not item["terminated"] for item in round_record["process_cleanup"]),
          "child_exit_or_cleanup_error")
    round_record["checks"] = {
        "daily_outgoing_cents": sum(row["amount_cents"] for row in alice_daily),
        "concurrent_success_count": len(additional),
        "successful_transfer_count": len(successful_transfers),
        "successful_transfer_audit_count": len(successful_audit),
        "new_successful_transaction_count": len(actual_transaction_entries),
        "expected_final_balances": expected_balances,
        "actual_final_balances": final_balances,
        "total_balance_before_cents": sum(initial_balances.values()),
        "total_balance_after_cents": sum(final_balances.values()),
        "availability": "one_40_yuan_transfer_succeeded" if additional else "zero_40_yuan_transfers_succeeded",
        "new_transaction_rows": new_transactions,
    }


def run_round(round_number, total_deadline):
    """Run a fresh baseline and one synchronized race, with bounded cleanup."""
    round_record = {"round": round_number, "started_at_utc": utc_now(), "issues": []}
    round_started = time.perf_counter()
    deadline = min(total_deadline, round_started + ROUND_BUDGET_SECONDS)
    processes = []
    receivers = []
    sender_handles = []
    context = multiprocessing.get_context("spawn")
    close_release = context.Event()
    temporary_directory = tempfile.TemporaryDirectory(prefix="bank-v2-two-process-")
    database_path = Path(temporary_directory.name) / "fresh-bank.sqlite3"
    round_record["temporary_database_name"] = database_path.name
    round_record["source_hashes_before_round"] = source_hashes()
    stage = "baseline"
    try:
        from src.bank import BankService

        baseline_service = BankService(str(database_path), user_id="alice", clock=fixed_test_clock)
        try:
            round_record["initial_snapshot"] = database_snapshot(database_path)
            proposal = baseline_service.propose(transfer_candidate("alice-main", 95000), raw_input="950元基线")
            round_record["baseline"] = {"propose": public_response(proposal)}
            if proposal.get("status") != "pending" or "confirmation_code" not in proposal:
                raise AssertionError("baseline did not become pending through public API")
            confirmation = baseline_service.confirm(proposal["request_id"], proposal["confirmation_code"])
            round_record["baseline"]["confirm"] = public_response(confirmation)
            if confirmation.get("status") != "success":
                raise AssertionError("950 yuan baseline public confirmation did not succeed")
            round_record["after_baseline_snapshot"] = database_snapshot(database_path)
        finally:
            baseline_service.close()

        stage = "spawn"
        propose_barrier = context.Barrier(3)
        confirm_barrier = context.Barrier(3)
        for account_id in ("alice-main", "alice-savings"):
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=concurrent_worker,
                args=(str(database_path), account_id, propose_barrier, confirm_barrier, close_release, sender),
                name=f"v2-round-{round_number}-{account_id}",
            )
            process.start()
            processes.append(process)
            receivers.append(receiver)
            sender_handles.append(sender)
            sender.close()

        stage = "ready"
        round_record["ready"] = collect_phase(receivers, "ready", deadline, round_record)
        stage = "propose_barrier"
        propose_barrier.wait(timeout=max(0.01, deadline - time.perf_counter()))
        stage = "proposed"
        round_record["proposed"] = collect_phase(receivers, "proposed", deadline, round_record)
        stage = "confirm_barrier"
        confirm_barrier.wait(timeout=max(0.01, deadline - time.perf_counter()))
        stage = "result"
        results = collect_phase(receivers, "result", deadline, round_record)
        round_record["workers"] = [item["result"] for item in results]
        round_record["both_results_received_ns"] = time.perf_counter_ns()
        for worker in round_record["workers"]:
            if "error" in worker:
                round_record["issues"].append(f"worker_error:{worker['error']['stage']}:{worker['error']['type']}")
        stage = "snapshot_before_common_close"
        round_record["before_close_snapshot"] = database_snapshot(database_path)
        round_record["common_close_release_ns"] = time.perf_counter_ns()
        close_release.set()
        stage = "closed"
        round_record["closed"] = collect_phase(receivers, "closed", deadline, round_record)
        if all("propose" in worker and "confirm" in worker for worker in round_record["workers"]):
            round_record["start_time_difference_ms"] = {
                phase: abs(round_record["workers"][0][phase]["start_ns"]
                           - round_record["workers"][1][phase]["start_ns"]) / 1000000
                for phase in ("propose", "confirm")
            }
    except Exception as exception:
        round_record["error"] = {"stage": stage, "type": type(exception).__name__}
        round_record["issues"].append(f"round_error:{stage}:{type(exception).__name__}")
    finally:
        close_release.set()
        cleanup = []
        for process in processes:
            process.join(timeout=0.6)
            terminated = process.is_alive()
            if terminated:
                process.terminate()
                process.join(timeout=0.8)
            cleanup.append({
                "pid": process.pid, "exit_code": process.exitcode,
                "terminated": terminated, "joined": not process.is_alive(),
            })
            if process.is_alive():
                process.kill()
                process.join(timeout=0.5)
                cleanup[-1]["killed"] = True
                cleanup[-1]["joined"] = not process.is_alive()
                cleanup[-1]["exit_code"] = process.exitcode
        round_record["process_cleanup"] = cleanup
        for receiver in receivers:
            receiver.close()
        for sender in sender_handles:
            sender.close()
        for process in processes:
            if not process.is_alive():
                process.close()
        try:
            if database_path.exists():
                round_record["after_close_snapshot"] = database_snapshot(database_path)
        except Exception as exception:
            round_record["issues"].append(f"final_snapshot_error:{type(exception).__name__}")
        try:
            temporary_directory.cleanup()
            round_record["temporary_database_removed"] = True
        except Exception as exception:
            round_record["temporary_database_removed"] = False
            round_record["issues"].append(f"temporary_database_cleanup_error:{type(exception).__name__}")
        round_record["source_hashes_after_round"] = source_hashes()
        round_record["elapsed_seconds"] = round(time.perf_counter() - round_started, 6)
        round_record["finished_at_utc"] = utc_now()

    if all(name in round_record for name in ("workers", "closed", "before_close_snapshot", "after_close_snapshot")):
        try:
            inspect_invariants(round_record)
        except Exception as exception:
            round_record["issues"].append(f"invariant_inspection_error:{type(exception).__name__}")
    baseline_hashes = ATTEMPT["source_hashes_before"]
    hash_snapshots = [round_record["source_hashes_before_round"], round_record["source_hashes_after_round"]]
    hash_snapshots.extend(worker["source_hashes_before_import"] for worker in round_record.get("workers", [])
                          if "source_hashes_before_import" in worker)
    hash_snapshots.extend(closed["source_hashes_after_close"] for closed in round_record.get("closed", [])
                          if "source_hashes_after_close" in closed)
    round_record["source_version_stable"] = all(snapshot == baseline_hashes for snapshot in hash_snapshots)
    if not round_record["source_version_stable"]:
        round_record["issues"].append("source_version_changed_during_acceptance")
    round_record["status"] = "passed" if not round_record["issues"] else "failed"
    return round_record


class V2RealProcessConcurrencyAcceptance(unittest.TestCase):
    def test_ten_fresh_databases_with_two_real_child_processes(self):
        """950 + concurrent 40 + 40 must not exceed the yellow daily limit."""
        ATTEMPT["source_hashes_before"] = source_hashes()
        ATTEMPT["rounds"] = []
        total_deadline = time.perf_counter() + TOTAL_BUDGET_SECONDS
        for round_number in range(1, ROUND_COUNT + 1):
            if time.perf_counter() >= total_deadline:
                round_record = {
                    "round": round_number, "status": "failed",
                    "issues": ["total_time_budget_exhausted"], "not_attempted": True,
                }
            else:
                round_record = run_round(round_number, total_deadline)
            ATTEMPT["rounds"].append(round_record)
            with self.subTest(round=round_number):
                self.assertEqual(round_record["issues"], [], json.dumps(round_record["issues"]))
        ATTEMPT["source_hashes_after"] = source_hashes()
        ATTEMPT["source_version_stable"] = (
            ATTEMPT["source_hashes_before"] == ATTEMPT["source_hashes_after"]
            and all(record.get("source_version_stable", False) for record in ATTEMPT["rounds"])
        )
        self.assertTrue(ATTEMPT["source_version_stable"], "Mixed source versions cannot be reported as one pass")


def main():
    multiprocessing.freeze_support()
    started = time.perf_counter()
    ATTEMPT.update({
        "started_at_utc": utc_now(), "parent_pid": os.getpid(),
        "python_executable": sys.executable, "python_version": sys.version.split()[0],
        "command": [sys.executable, "tests/test_v2_process_concurrency.py"],
        "command_powershell": f"& '{sys.executable}' tests/test_v2_process_concurrency.py",
        "test_file_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_hash_scope": "All src/*.py paths present at each snapshot, including newly added modules",
        "multiprocessing_start_method": "spawn", "requested_round_count": ROUND_COUNT,
        "total_test_budget_seconds": TOTAL_BUDGET_SECONDS,
        "clock": FIXED_TIME.isoformat(),
        "clock_scope": "Public test-only constructor seam; no production clock setting changed",
        "expectations": {
            "baseline_cents": 95000, "each_concurrent_transfer_cents": 4000,
            "maximum_daily_successful_outgoing_cents": 100000,
            "maximum_concurrent_success_count": 1,
            "zero_concurrent_success_is_safe_but_has_an_availability_cost": True,
        },
    })
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(V2RealProcessConcurrencyAcceptance)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    ATTEMPT["finished_at_utc"] = utc_now()
    ATTEMPT["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    ATTEMPT["exit_code"] = 0 if result.wasSuccessful() else 1
    ATTEMPT["unittest"] = {"tests_run": result.testsRun, "failures": len(result.failures),
                           "errors": len(result.errors), "skipped": len(result.skipped)}
    ATTEMPT["result"] = "passed" if result.wasSuccessful() else "failed"
    ATTEMPT["availability_summary"] = {
        "one_success_rounds": sum(record.get("checks", {}).get("concurrent_success_count") == 1
                                  for record in ATTEMPT.get("rounds", [])),
        "zero_success_rounds": sum(record.get("checks", {}).get("concurrent_success_count") == 0
                                   for record in ATTEMPT.get("rounds", [])),
        "failed_rounds": sum(record["status"] != "passed" for record in ATTEMPT.get("rounds", [])),
    }
    if EVIDENCE_PATH.exists():
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        if not isinstance(evidence.get("attempts"), list):
            raise ValueError("Existing evidence lacks attempts; refusing to replace its history")
    else:
        evidence = {
            "scope": "Independent offline public-API acceptance; two real OS child processes per round",
            "requirements": ["docs/01-permission-tiers.md", "docs/02-user-stories.md",
                             "docs/05-audit-log-spec.md", "src/PUBLIC_API.md"],
            "independence": "No business source, scripts, existing tests or implementation patches read",
            "limitations": [
                "Not a real-model, GUI, HTTP or network-load acceptance",
                "Ten bounded barrier schedules cannot prove every possible concurrency interleaving",
                "A shared-user new proposal may invalidate another pending request; zero successes have an availability cost",
                "No MFA, real money, normal data/bank.db or old stage package is used or changed",
                "Source hashes are bounded snapshots, not a continuous file-change monitor",
                "Transaction kind/sign conventions are not specified publicly; raw new rows are saved without inventing those conventions",
                "Actual OS call overlap is measured by start gaps; barriers do not force simultaneous database commits",
            ],
            "attempts": [],
        }
    ATTEMPT["attempt_number"] = len(evidence["attempts"]) + 1
    evidence["attempts"].append(ATTEMPT)
    evidence["latest_attempt_number"] = ATTEMPT["attempt_number"]
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(EVIDENCE_PATH), "attempt": ATTEMPT["attempt_number"],
                      "result": ATTEMPT["result"], "elapsed_seconds": ATTEMPT["elapsed_seconds"],
                      "availability": ATTEMPT["availability_summary"],
                      "source_version_stable": ATTEMPT.get("source_version_stable")}, ensure_ascii=False))
    return ATTEMPT["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

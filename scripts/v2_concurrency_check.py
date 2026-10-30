"""V2 验收实测：并发会话下的上海自然日累计转账限额（docs/07 第5节 V2）。

构造：用真实接口先完成一笔当日 950 元成功转账作前置；随后两个独立会话
（各自 BankService 实例、各自 SQLite 连接、同一数据库文件）用 threading.Barrier
同步，同时从 alice-main 与 alice-savings 两个本人账户各发起 40 元转账并确认。
A 部分复现评委原场景并重复 30 轮；B 部分 8 线程 x 5 次并发抢转作压力复跑。
只通过公开表核对累计、余额守恒与审计；本脚本不修改任何业务代码。
运行：python scripts/v2_concurrency_check.py
输出：stdout 摘要 + evidence/v2-concurrency-limit.json
"""

import json
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bank import BankService
from src.storage import SHANGHAI

FIXED_NOW = datetime(2026, 10, 11, 14, 0, 0, tzinfo=SHANGHAI)
LIMIT_CENTS = 100000
PRECONDITION_CENTS = 95000
ATTEMPT_CENTS = 4000
ROUNDS_A = 30
THREADS_B = 8
ATTEMPTS_B = 5
INITIAL_TOTAL_BALANCE = 1000000 + 500000 + 100000


def fixed_clock():
    return FIXED_NOW


def seed_precondition(database_path):
    """通过真实 propose/confirm 接口完成当日 950 元成功转账。"""
    service = BankService(database_path, "alice", clock=fixed_clock)
    proposal = service.propose({"intent": "transfer", "params": {
        "account_id": "alice-main", "contact_id": "wang",
        "amount_cents": PRECONDITION_CENTS}})
    assert proposal["status"] == "pending", proposal
    confirmed = service.confirm(proposal["request_id"], proposal["confirmation_code"])
    service.close()
    assert confirmed["status"] == "success", confirmed
    assert confirmed["data"]["daily_outgoing_cents"] == PRECONDITION_CENTS, confirmed
    return confirmed


def ledger_snapshot(database_path):
    """直接读公开表：当日成功累计、转账明细、余额、成功审计条数。"""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    today = FIXED_NOW.date().isoformat()
    total = connection.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM transfers "
        "WHERE user_id='alice' AND shanghai_date=? AND status='success'",
        (today,)).fetchone()[0]
    transfers = [dict(row) for row in connection.execute(
        "SELECT request_id,source_account_id,amount_cents,status FROM transfers "
        "WHERE user_id='alice' AND shanghai_date=? ORDER BY rowid", (today,))]
    balances = {row["account_id"]: row["balance_cents"] for row in
                connection.execute("SELECT account_id,balance_cents FROM accounts")}
    executed = connection.execute(
        "SELECT COUNT(*) FROM audit_log WHERE user_id='alice' AND intent='transfer' "
        "AND event='executed' AND result='success'").fetchone()[0]
    connection.close()
    return {"daily_success_total_cents": total, "transfers": transfers,
            "balances": balances, "audit_executed_success_count": executed}


def check_round(snapshot, expected_attack_successes):
    violations = []
    if snapshot["daily_success_total_cents"] > LIMIT_CENTS:
        violations.append(f"当日成功累计 {snapshot['daily_success_total_cents']} 分突破限额 {LIMIT_CENTS} 分")
    expected_total = PRECONDITION_CENTS + ATTEMPT_CENTS * expected_attack_successes
    if snapshot["daily_success_total_cents"] != expected_total:
        violations.append(f"当日成功累计 {snapshot['daily_success_total_cents']} 分与预期 {expected_total} 分不符")
    if sum(snapshot["balances"].values()) != INITIAL_TOTAL_BALANCE:
        violations.append(f"余额不守恒：{snapshot['balances']}")
    if snapshot["audit_executed_success_count"] != 1 + expected_attack_successes:
        violations.append(f"成功审计条数 {snapshot['audit_executed_success_count']} 与实际成功笔数不符")
    return violations


def round_a(round_index):
    """评委原场景：两线程各自在线程内构造独立会话（模拟两个进程），barrier 同步发起并确认。

    Python sqlite3 连接有线程归属（check_same_thread），在 A 线程构造、B 线程使用
    会抛 ProgrammingError，因此服务必须在各自线程内构造；构造用互斥锁串行化，
    被测的并发点只有 barrier 之后的 propose 与 confirm。
    """
    with tempfile.TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "v2-a.db")
        seed_precondition(database_path)
        sources = {"A": ("alice-main", "wang"), "B": ("alice-savings", "li")}
        construction_lock = threading.Lock()
        barrier = threading.Barrier(2)
        outcomes = {name: {} for name in ("A", "B")}

        def worker(name):
            try:
                with construction_lock:
                    service = BankService(database_path, "alice", clock=fixed_clock)
                for phase in ("propose", "confirm"):
                    barrier.wait()
                    started = time.perf_counter()
                    if phase == "propose":
                        account_id, contact_id = sources[name]
                        response = service.propose({"intent": "transfer", "params": {
                            "account_id": account_id, "contact_id": contact_id,
                            "amount_cents": ATTEMPT_CENTS}})
                    else:
                        proposal = outcomes[name]["propose"]
                        if isinstance(proposal, dict) and proposal.get("status") == "pending":
                            response = service.confirm(
                                proposal["request_id"], proposal["confirmation_code"])
                        else:
                            response = None
                    outcomes[name][phase] = response
                    if phase == "propose":
                        outcomes[name]["propose_started"] = started
                service.close()
            except Exception as error:
                outcomes[name]["harness_exception"] = repr(error)

        threads = [threading.Thread(target=worker, args=(name,)) for name in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        start_delta_ms = None
        if "propose_started" in outcomes["A"] and "propose_started" in outcomes["B"]:
            start_delta_ms = round(abs(outcomes["A"]["propose_started"] - outcomes["B"]["propose_started"]) * 1000, 3)
        snapshot = ledger_snapshot(database_path)

        successes = sum(1 for name in ("A", "B")
                        if isinstance(outcomes[name].get("confirm"), dict)
                        and outcomes[name]["confirm"].get("status") == "success")
        violations = check_round(snapshot, successes)
        daily_seen = [outcomes[name]["confirm"]["data"]["daily_outgoing_cents"]
                      for name in ("A", "B")
                      if isinstance(outcomes[name].get("confirm"), dict)
                      and outcomes[name]["confirm"].get("status") == "success"]
        if any(total > LIMIT_CENTS for total in daily_seen):
            violations.append(f"成功回执中的执行后累计 {daily_seen} 超过限额")

        return {"round": round_index, "propose_start_delta_ms": start_delta_ms,
                "propose_A": outcomes["A"].get("propose"), "propose_B": outcomes["B"].get("propose"),
                "confirm_A": outcomes["A"].get("confirm"), "confirm_B": outcomes["B"].get("confirm"),
                "harness_exceptions": [outcomes[name]["harness_exception"] for name in ("A", "B")
                                       if "harness_exception" in outcomes[name]],
                "attack_successes": successes, "ledger": snapshot, "violations": violations}


def round_b():
    """压力复跑：8 线程 x 5 次并发抢转 40 元，统计每次成功后的累计是否越限。"""
    with tempfile.TemporaryDirectory() as directory:
        database_path = str(Path(directory) / "v2-b.db")
        seed_precondition(database_path)
        barrier = threading.Barrier(THREADS_B)
        construction_lock = threading.Lock()
        entries = []
        entries_lock = threading.Lock()

        def worker(index):
            try:
                with construction_lock:
                    service = BankService(database_path, "alice", clock=fixed_clock)
                barrier.wait()
                for attempt in range(ATTEMPTS_B):
                    entry = {"thread": index, "attempt": attempt}
                    try:
                        account_id = "alice-main" if index % 2 == 0 else "alice-savings"
                        proposal = service.propose({"intent": "transfer", "params": {
                            "account_id": account_id, "contact_id": "wang",
                            "amount_cents": ATTEMPT_CENTS}})
                        entry["propose_status"] = proposal.get("status")
                        entry["propose_reason"] = proposal.get("reason")
                        if proposal.get("status") == "pending":
                            confirmed = service.confirm(
                                proposal["request_id"], proposal["confirmation_code"])
                            entry["confirm_status"] = confirmed.get("status")
                            entry["confirm_reason"] = confirmed.get("reason")
                            if confirmed.get("status") == "success":
                                entry["daily_after"] = confirmed["data"]["daily_outgoing_cents"]
                    except Exception as error:
                        entry["exception"] = repr(error)
                    with entries_lock:
                        entries.append(entry)
                    time.sleep(0.001)
                service.close()
            except Exception as error:
                with entries_lock:
                    entries.append({"thread": index, "fatal": repr(error)})

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(THREADS_B)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        snapshot = ledger_snapshot(database_path)
        successes = [entry for entry in entries if entry.get("confirm_status") == "success"]
        violations = check_round(snapshot, len(successes))
        if any(entry.get("daily_after", 0) > LIMIT_CENTS for entry in successes):
            violations.append("存在执行后累计超过限额的成功转账")
        tallies = {}
        for entry in entries:
            key = f"propose={entry.get('propose_status')}/{entry.get('propose_reason') or '-'}"
            if "confirm_status" in entry:
                key += f" confirm={entry['confirm_status']}/{entry.get('confirm_reason') or '-'}"
            if "exception" in entry or "fatal" in entry:
                key = "exception: " + entry.get("exception", entry.get("fatal", ""))
            tallies[key] = tallies.get(key, 0) + 1
        return {"threads": THREADS_B, "attempts_per_thread": ATTEMPTS_B,
                "success_count": len(successes), "tallies": tallies,
                "ledger": snapshot, "violations": violations}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    started = datetime.now(SHANGHAI).isoformat()
    exhibit = round_a(1)
    rounds_a = [exhibit] + [round_a(index) for index in range(2, ROUNDS_A + 1)]
    stress = round_b()

    all_violations = [f"A{item['round']}: {text}" for item in rounds_a for text in item["violations"]]
    all_violations += [f"B: {text}" for text in stress["violations"]]
    harness_errors = [f"A{item['round']}: {text}" for item in rounds_a for text in item["harness_exceptions"]]
    max_delta = max(item["propose_start_delta_ms"] for item in rounds_a
                    if item["propose_start_delta_ms"] is not None)
    success_counts = sorted({item["attack_successes"] for item in rounds_a})
    final_totals = sorted({item["ledger"]["daily_success_total_cents"] for item in rounds_a})
    verdict = "没防住" if all_violations else ("不能确定" if harness_errors else "防住了")

    report = {
        "check": "V2 并发下日累计限额（docs/07 第5节）",
        "constructed": "前置经真实接口完成当日950元成功转账；两线程各自在线程内构造独立 BankService（各自SQLite连接、同一库文件，模拟两个进程/两次启动），Barrier 同步并发各发起40元；"
                       "A=评委原场景30轮，B=8线程x5次压力复跑；固定上海时钟2026-10-11 14:00+08:00",
        "started_at": started,
        "verdict": verdict,
        "part_A_summary": {"rounds": ROUNDS_A, "max_propose_start_delta_ms": max_delta,
                           "attack_successes_observed": success_counts,
                           "final_daily_totals_observed": final_totals},
        "part_A_exhibit_round1": exhibit,
        "part_B_stress": stress,
        "violations": all_violations,
        "harness_errors": harness_errors,
    }
    evidence_path = Path(__file__).resolve().parent.parent / "evidence" / "v2-concurrency-limit.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"判定：{verdict}")
    print(f"A 部分 {ROUNDS_A} 轮：并发攻击成功笔数集合={success_counts}，最终当日累计集合={final_totals} 分，"
          f"propose 最大启动时差={max_delta}ms")
    print(f"A 第 1 轮原始响应：")
    for key in ("propose_A", "propose_B", "confirm_A", "confirm_B"):
        print(f"  {key} = {json.dumps(exhibit[key], ensure_ascii=False)}")
    print(f"A 第 1 轮账本：当日成功累计={exhibit['ledger']['daily_success_total_cents']} 分，"
          f"余额={exhibit['ledger']['balances']}，成功审计条数={exhibit['ledger']['audit_executed_success_count']}")
    print(f"B 部分 {THREADS_B}x{ATTEMPTS_B}：成功 {stress['success_count']} 笔，"
          f"最终当日累计={stress['ledger']['daily_success_total_cents']} 分")
    for key, count in sorted(stress["tallies"].items(), key=lambda item: -item[1]):
        print(f"  {count:>3} 次  {key}")
    if all_violations:
        print("违规明细：")
        for text in all_violations:
            print(f"  - {text}")
    if harness_errors:
        print("脚手架异常（该轮无效，不计产品违规）：")
        for text in harness_errors:
            print(f"  - {text}")
    print(f"证据已写入 {evidence_path}")
    return 0 if verdict == "防住了" else 1


if __name__ == "__main__":
    sys.exit(main())

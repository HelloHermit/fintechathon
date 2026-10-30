"""V1 验收实测：绿档账单/流水是否间接披露黄档订阅信息（docs/07 第5节 V1，docs/15 追加任务）。

构造：两个全新临时库 A/B，相同可信用户 alice、相同固定上海时钟、相同账户与历史交易夹具，
唯一差别：sub-video 当前状态 A=active、B=cancelled。状态翻转由测试管理员直接改公开表前置
（PUBLIC_API 夹具约定；这是测试构造，不代表应用用户能改库）。V1-06 超时路径用第三个库。
对两个库分别执行（均未做任何订阅确认）：analyze_bills、query_transactions；
再 query_subscriptions（pending 检查是否披露），固定接口确认后再次对比并复查历史账单。
判据来自未读实现的隔离规格作者期望表（只读 docs/01、docs/02、PUBLIC_API 产出，见
evidence 报告 expectation_source 与 ambiguities）：绿档响应混入未来预计金额、出现当前订阅
状态/清单/订阅编号、两库绿档业务数据任何差异、未确认响应含 data 或列表，均判违规。
本脚本由实现方构造执行，归类实现侧专项核对，不并入原93项独立验收。
运行：python scripts/v1_disclosure_check.py
输出：stdout 摘要 + evidence/v1-indirect-disclosure.json
"""

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bank import BankService
from src.storage import SHANGHAI

FIXED_NOW = datetime(2026, 10, 11, 14, 0, 0, tzinfo=SHANGHAI)

# 受保护信息（规格作者期望表 (b) 类）：当前订阅清单、订阅编号、当前状态、未来预计扣款。
# 未确认响应出现即违规。静态说明文字两库相同由 A/B 一致性覆盖，不靠词表。
PROTECTED_TOKENS = ("subscription", "sub-video", "sub-cloud", "sub-music",
                    "active", "cancelled", "future_expected", "续费")
FLOW_FIELDS = {"request_id", "expires_at"}
EXPECTED_BILLS = {"云存储": 990, "音乐会员": 1990, "视频会员": 2990}

EXPECTATION_SOURCE = ("隔离规格作者（未读实现，仅读 docs/01-permission-tiers.md、docs/02-user-stories.md、"
                      "src/PUBLIC_API.md）2026-10-11 产出披露边界表与用例 V1-01~V1-06")
AMBIGUITIES = [
    "绿档以自然语言归纳“每月重复扣费平台”是否算变相披露清单：规格未约束归纳措辞，待澄清",
    "query_transactions 是否返回失败/scheduled 记录及如何标注：规格未明确，本核对只验两库一致",
    "subscription_id 未被规格点名保护，按订阅记录组成部分归入受保护，属推论，待澄清",
    "pending 的 operation 影响描述可否含订阅数量或总金额：规格未规定，待澄清",
    "确认后订阅列表是否包含已取消条目：规格只说标记不删除、未来预计排除，待澄清",
    "future_expected_cents 计算口径（时间范围、是否含次月 scheduled）：规格未定义，待澄清",
    "analyze_bills categories 粒度（平台名 vs 大类）：规格未定义，待澄清",
]


def make_database(directory, video_status):
    """全新库：标准夹具（sub-video 默认 active）；B 库随后由测试管理员翻转为 cancelled。"""
    database_path = str(Path(directory) / f"v1-{video_status}.db")
    service = BankService(database_path, "alice", clock=lambda: FIXED_NOW)
    service.close()
    if video_status == "cancelled":
        connection = sqlite3.connect(database_path)
        connection.execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id='sub-video'")
        connection.commit()
        connection.close()
    return database_path


def run_session(database_path):
    """V1-01~V1-05：未确认绿档两连查、黄档订阅 pending、固定确认、确认后复查历史账单、审计。"""
    service = BankService(database_path, "alice", clock=lambda: FIXED_NOW)
    results = {}
    results["analyze_bills"] = service.propose({"intent": "analyze_bills", "params": {}})
    results["query_transactions"] = service.propose({"intent": "query_transactions", "params": {}})
    pending = service.propose({"intent": "query_subscriptions", "params": {}})
    results["query_subscriptions_pending"] = pending
    if pending.get("status") == "pending":
        results["query_subscriptions_confirmed"] = service.confirm(
            pending["request_id"], pending["confirmation_code"])
    else:
        results["query_subscriptions_confirmed"] = None
    results["analyze_bills_after"] = service.propose({"intent": "analyze_bills", "params": {}})
    results["audit_events"] = service.audit_events()
    service.close()
    return results


def run_expired_case(directory):
    """V1-06：第三库 pending 后时钟推进 6 分钟，确认应 expired 且不披露，旧码不可复用。"""
    database_path = make_database(directory, "active")
    clock_holder = {"now": FIXED_NOW}
    service = BankService(database_path, "alice", clock=lambda: clock_holder["now"])
    pending = service.propose({"intent": "query_subscriptions", "params": {}})
    clock_holder["now"] = FIXED_NOW + timedelta(minutes=6)
    expired = service.confirm(pending["request_id"], pending["confirmation_code"]) \
        if pending.get("status") == "pending" else None
    replay = service.confirm(pending["request_id"], pending["confirmation_code"]) \
        if pending.get("status") == "pending" else None
    audit = service.audit_events()
    service.close()
    return {"pending": pending, "expired": expired, "replay": replay, "audit_events": audit}


def scrub_flow(value):
    if type(value) is dict:
        return {key: scrub_flow(item) for key, item in value.items() if key not in FLOW_FIELDS}
    if type(value) is list:
        return [scrub_flow(item) for item in value]
    return value


def find_tokens(node, path=""):
    hits = []
    if type(node) is dict:
        for key, item in node.items():
            hits += find_tokens(key, f"{path}.{key}<键>")
            if key == "intent":
                continue  # 意图名是公开契约常量（query_subscriptions），不算披露内容
            hits += find_tokens(item, f"{path}.{key}")
    elif type(node) is list:
        for index, item in enumerate(node):
            hits += find_tokens(item, f"{path}[{index}]")
    elif type(node) is str:
        for token in PROTECTED_TOKENS:
            if token in node:
                hits.append({"path": path, "token": token, "text": node})
    return hits


def diff_business(left, right, path=""):
    differences = []
    if type(left) is not type(right):
        return [{"path": path, "A": left, "B": right}]
    if type(left) is dict:
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append({"path": f"{path}.{key}", "A": left.get(key, "<缺>"), "B": right.get(key, "<缺>")})
            else:
                differences += diff_business(left[key], right[key], f"{path}.{key}")
    elif type(left) is list:
        if len(left) != len(right):
            differences.append({"path": path, "A": f"长度{len(left)}", "B": f"长度{len(right)}"})
        else:
            for index, (item_a, item_b) in enumerate(zip(left, right)):
                differences += diff_business(item_a, item_b, f"{path}[{index}]")
    elif left != right:
        differences.append({"path": path, "A": left, "B": right})
    return differences


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as directory:
        path_a = make_database(directory, "active")
        path_b = make_database(directory, "cancelled")
        results_a = run_session(path_a)
        results_b = run_session(path_b)
        expired_case = run_expired_case(directory)

        violations = []
        comparisons = {}

        # V1-01 / V1-02：未确认绿档两库业务数据必须完全一致，且内容符合夹具与范围。
        for call in ("analyze_bills", "query_transactions", "analyze_bills_after"):
            differences = diff_business(scrub_flow(results_a[call]), scrub_flow(results_b[call]))
            comparisons[call] = differences
            if differences:
                violations.append(f"{call} 两库业务数据不同：{differences}")
        for label, results in (("A", results_a), ("B", results_b)):
            bills = results["analyze_bills"].get("data", {})
            if bills.get("actual_expense_cents") != 5970 or bills.get("categories") != EXPECTED_BILLS:
                violations.append(f"库{label} analyze_bills 应为 5970/{EXPECTED_BILLS}，实际 {bills}")
            if results["analyze_bills_after"].get("data", {}) != bills:
                violations.append(f"库{label} 订阅确认后历史账单被改变")
            rows = results["query_transactions"].get("data", {}).get("transactions", [])
            success_bills = {(row["category"], row["amount_cents"]) for row in rows if row["status"] == "success"}
            if not {(name, amount) for name, amount in EXPECTED_BILLS.items()} <= success_bills:
                violations.append(f"库{label} query_transactions 缺漏当月三条成功记录：{success_bills}")
            if any(row["transaction_id"] in ("last-month", "future-bill") for row in rows):
                violations.append(f"库{label} 默认本月范围混入上月/次月记录")
            for call in ("analyze_bills", "query_transactions"):
                leaks = find_tokens({k: v for k, v in results[call].items() if k not in FLOW_FIELDS})
                if leaks:
                    violations.append(f"库{label} {call} 出现受保护词：{leaks}")

        # V1-03：订阅查询 pending 不得披露列表/状态/未来金额，两库业务内容一致。
        pending_leaks = {}
        for label, results in (("A", results_a), ("B", results_b)):
            pending = results["query_subscriptions_pending"]
            leaks = []
            if pending.get("status") != "pending" or pending.get("tier") != "yellow":
                leaks.append({"path": "status/tier", "text": f"应为 pending/yellow，实际 {pending.get('status')}/{pending.get('tier')}"})
            if "data" in pending:
                leaks.append({"path": "data", "text": "pending 响应含 data 字段"})
            for field in ("confirmation_code", "operation"):
                if field not in pending:
                    leaks.append({"path": field, "text": "pending 缺契约字段"})
            leaks += find_tokens({k: v for k, v in pending.items() if k not in FLOW_FIELDS | {"confirmation_code"}})
            pending_leaks[label] = leaks
            if leaks:
                violations.append(f"库{label} 订阅查询 pending 披露受保护信息：{leaks}")
        pending_diff = diff_business(scrub_flow({k: v for k, v in results_a["query_subscriptions_pending"].items() if k != "confirmation_code"}),
                                     scrub_flow({k: v for k, v in results_b["query_subscriptions_pending"].items() if k != "confirmation_code"}))
        comparisons["query_subscriptions_pending"] = pending_diff
        if pending_diff:
            violations.append(f"订阅查询 pending 两库不同（可据此区分当前状态）：{pending_diff}")

        # V1-04：确认后两库仅体现真实状态差；历史支出不变；确认码不入审计。
        confirmed_summary = {}
        for label, results in (("A", results_a), ("B", results_b)):
            confirmed = results["query_subscriptions_confirmed"]
            if not confirmed or confirmed.get("status") != "success":
                violations.append(f"库{label} 订阅查询确认未成功")
                continue
            subs = confirmed["data"].get("subscriptions", [])
            confirmed_summary[label] = {
                "statuses": {row["subscription_id"]: row["status"] for row in subs},
                "future_expected_cents": confirmed["data"].get("future_expected_cents")}
            code = results["query_subscriptions_pending"].get("confirmation_code", "")
            if code and code in json.dumps(results["audit_events"], ensure_ascii=False):
                violations.append(f"库{label} 有效确认码进入审计日志")
        if confirmed_summary.get("A", {}).get("statuses", {}).get("sub-video") != "active":
            violations.append("库A确认后 sub-video 应为 active")
        if confirmed_summary.get("B", {}).get("statuses", {}).get("sub-video") != "cancelled":
            violations.append("库B确认后 sub-video 应为 cancelled")
        if confirmed_summary.get("A", {}).get("future_expected_cents") != 5970:
            violations.append(f"库A确认后未来预计应为 5970，实际 {confirmed_summary.get('A', {}).get('future_expected_cents')}")
        if confirmed_summary.get("B", {}).get("future_expected_cents") != 2980:
            violations.append(f"库B确认后未来预计应为 2980（排除已取消），实际 {confirmed_summary.get('B', {}).get('future_expected_cents')}")
        others_a = {k: v for k, v in confirmed_summary.get("A", {}).get("statuses", {}).items() if k != "sub-video"}
        others_b = {k: v for k, v in confirmed_summary.get("B", {}).get("statuses", {}).items() if k != "sub-video"}
        if others_a != others_b:
            violations.append(f"确认后除 sub-video 外其他订阅状态不应不同：{others_a} vs {others_b}")

        # V1-05：审计完整性：绿档执行、黄档等待/确认/执行均有追加日志且档位正确。
        audit_check = {}
        for label, results in (("A", results_a), ("B", results_b)):
            events = results["audit_events"]
            audit_check[label] = {
                "green_executed": sum(1 for e in events if e["intent"] in ("analyze_bills", "query_transactions") and e["event"] == "executed"),
                "yellow_events": [(e["event"], e["tier"]) for e in events if e["intent"] == "query_subscriptions"],
            }
            if audit_check[label]["green_executed"] != 3:
                violations.append(f"库{label} 绿档执行审计应为 3 条，实际 {audit_check[label]['green_executed']}")
            yellow = dict()
            for event, tier in audit_check[label]["yellow_events"]:
                yellow.setdefault(event, tier)
            for needed in ("waiting_confirmation", "confirmed", "executed"):
                if yellow.get(needed) != "yellow":
                    violations.append(f"库{label} 订阅查询缺 {needed}/yellow 审计")

        # V1-06：超时确认 expired 不披露，旧码复用 rejected。
        expired_summary = {}
        expired, replay = expired_case["expired"], expired_case["replay"]
        if not expired or expired.get("status") != "expired":
            violations.append(f"V1-06 超时确认应为 expired，实际 {expired}")
        else:
            leaks = (["data 字段"] if "data" in expired else []) + \
                    [hit["path"] for hit in find_tokens({k: v for k, v in expired.items() if k not in FLOW_FIELDS})]
            expired_summary = {"status": expired.get("status"), "leaks": leaks,
                               "replay_status": replay.get("status") if replay else None}
            if leaks:
                violations.append(f"V1-06 超时响应仍披露：{leaks}")
            if not replay or replay.get("status") != "rejected":
                violations.append(f"V1-06 超时后旧码复用应 rejected，实际 {replay}")

        verdict = "没防住" if violations else "防住了"
        report = {
            "check": "V1 跨工具间接披露（docs/07 第5节 V1，docs/15 追加任务）",
            "classification": "期望由未读实现的隔离规格作者产出；实现方构造执行，归类实现侧专项核对，"
                              "不并入原93项独立验收；规格歧义 7 项列入 ambiguities 不作判定",
            "expectation_source": EXPECTATION_SOURCE,
            "ambiguities": AMBIGUITIES,
            "constructed": "两全新临时库，同用户/固定上海时钟2026-10-11 14:00/账户/历史交易夹具，"
                           "仅 sub-video 状态 A=active、B=cancelled（测试管理员公开表前置）；V1-06 第三库推进时钟6分钟",
            "started_at": datetime.now(SHANGHAI).isoformat(),
            "verdict": verdict,
            "comparisons": comparisons,
            "pending_leaks": pending_leaks,
            "confirmed_summary": confirmed_summary,
            "audit_check": audit_check,
            "expired_case": expired_summary,
            "violations": violations,
            "raw_responses": {"A": {k: v for k, v in results_a.items() if k != "audit_events"},
                              "B": {k: v for k, v in results_b.items() if k != "audit_events"},
                              "V1-06": {k: v for k, v in expired_case.items() if k != "audit_events"}},
            "audit_events": {"A": results_a["audit_events"], "B": results_b["audit_events"],
                             "V1-06": expired_case["audit_events"]},
        }
        evidence_path = Path(__file__).resolve().parent.parent / "evidence" / "v1-indirect-disclosure.json"
        evidence_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        print(f"判定：{verdict}")
        for call in ("analyze_bills", "query_transactions", "analyze_bills_after"):
            print(f"{call} 两库业务差异：{len(comparisons[call])} 处")
        print(f"订阅查询 pending 泄露点：A={len(pending_leaks['A'])} B={len(pending_leaks['B'])}；两库 pending 差异：{len(pending_diff)} 处")
        print(f"确认后：A={confirmed_summary.get('A')} B={confirmed_summary.get('B')}")
        print(f"V1-06 超时路径：{expired_summary}")
        if violations:
            print("违规明细：")
            for text in violations:
                print(f"  - {text}")
        print(f"证据已写入 {evidence_path}")
        return 0 if verdict == "防住了" else 1


if __name__ == "__main__":
    sys.exit(main())

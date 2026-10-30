"""按公开规格归并已审核证据；不执行候选代码，不验证日志真实性。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HEX_DIGITS = frozenset("0123456789abcdef")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    normalized = value.lower()
    return normalized if all(char in HEX_DIGITS for char in normalized) else None


def _string_list(value: Any, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(_text(item) for item in value)
    )


def _groups(value: Any) -> bool:
    return _string_list(value, nonempty=True) and len(set(value)) == len(value)


def _review(reason: str) -> dict[str, Any]:
    return {
        "decision": "REVIEW_REQUIRED",
        "reason_codes": [reason],
        "covered_groups": {},
        "missing_groups": {},
        "unique_cases": 0,
        "duplicate_records": 0,
    }


def _registry_maps(registry: Any):
    if not isinstance(registry, dict):
        return None
    if type(registry.get("schema_version")) is not int or registry["schema_version"] != 1:
        return None
    if not _text(registry.get("task_id")) or not _text(registry.get("spec_revision")):
        return None
    constraints = registry.get("constraints")
    oracles = registry.get("oracles")
    if not isinstance(constraints, list) or not constraints:
        return None
    if not isinstance(oracles, list) or not oracles:
        return None
    required = {}
    for constraint in constraints:
        if not isinstance(constraint, dict):
            return None
        identifier = constraint.get("id")
        groups = constraint.get("required_groups")
        if not _text(identifier) or identifier in required or not _groups(groups):
            return None
        required[identifier] = set(groups)
    approved = {}
    for oracle in oracles:
        if not isinstance(oracle, dict):
            return None
        identifier = oracle.get("id")
        constraint_id = oracle.get("constraint_id")
        groups = oracle.get("groups")
        if (
            not _text(identifier)
            or identifier in approved
            or not _text(constraint_id)
            or constraint_id not in required
            or not _groups(groups)
            or not set(groups).issubset(required[constraint_id])
        ):
            return None
        approved[identifier] = {
            "constraint_id": constraint_id,
            "groups": set(groups),
        }
    return required, approved


def decide(registry: dict, run: dict) -> dict[str, Any]:
    """输出有限协议下通过、已记录反例或需复核；不访问隐藏答案。"""
    registry_maps = _registry_maps(registry)
    if registry_maps is None:
        return _review("invalid_registry")
    required, approved = registry_maps
    if not isinstance(run, dict):
        return _review("invalid_run")
    program_digest = _digest(run.get("program_sha256"))
    if (
        run.get("task_id") != registry["task_id"]
        or run.get("spec_revision") != registry["spec_revision"]
        or program_digest is None
        or type(run.get("complete")) is not bool
        or not _string_list(run.get("pipeline_errors"))
        or not _string_list(run.get("unresolved_warnings"))
        or not isinstance(run.get("evidence"), list)
    ):
        return _review("invalid_run")

    reasons = set()
    if not run["complete"]:
        reasons.add("incomplete_run")
    if run["pipeline_errors"]:
        reasons.add("pipeline_error")
    if run["unresolved_warnings"]:
        reasons.add("unresolved_warning")

    buckets = {}
    valid_record_count = 0
    for record in run["evidence"]:
        if not isinstance(record, dict):
            reasons.add("invalid_evidence")
            continue
        oracle_id = record.get("oracle_id")
        group = record.get("group")
        input_digest = _digest(record.get("input_digest"))
        record_program = _digest(record.get("program_sha256"))
        outcome = record.get("outcome")
        if (
            not _text(oracle_id)
            or not _text(group)
            or input_digest is None
            or record_program is None
            or not _text(record.get("spec_revision"))
            or not isinstance(outcome, str)
            or outcome not in {"pass", "fail", "error", "unknown"}
        ):
            reasons.add("invalid_evidence")
            continue
        if oracle_id not in approved:
            reasons.add("unregistered_oracle")
            continue
        if group not in approved[oracle_id]["groups"]:
            reasons.add("invalid_evidence")
            continue
        if record_program != program_digest or record["spec_revision"] != run["spec_revision"]:
            reasons.add("stale_evidence")
            continue
        key = (oracle_id, input_digest)
        buckets.setdefault(key, set()).add((group, outcome))
        valid_record_count += 1

    covered = {identifier: set() for identifier in required}
    counterexamples = []
    for (oracle_id, input_digest), states in buckets.items():
        if len(states) != 1:
            reasons.add("conflicting_evidence")
            continue
        group, outcome = next(iter(states))
        constraint_id = approved[oracle_id]["constraint_id"]
        if outcome == "pass":
            covered[constraint_id].add(group)
        elif outcome == "fail":
            counterexamples.append({
                "oracle_id": oracle_id,
                "constraint_id": constraint_id,
                "input_digest": input_digest,
                "group": group,
            })
        else:
            reasons.add("evidence_" + outcome)

    missing = {
        identifier: sorted(groups - covered[identifier])
        for identifier, groups in required.items()
        if groups - covered[identifier]
    }
    if missing:
        reasons.add("missing_required_groups")
    if counterexamples:
        decision = "DEFECT_CONFIRMED"
        reasons.add("validated_counterexample")
    elif reasons:
        decision = "REVIEW_REQUIRED"
    else:
        decision = "ACCEPT_UNDER_PROTOCOL"
        reasons.add("required_groups_checked")

    return {
        "decision": decision,
        "reason_codes": sorted(reasons),
        "covered_groups": {identifier: sorted(groups) for identifier, groups in covered.items()},
        "missing_groups": missing,
        "unique_cases": len(buckets),
        "duplicate_records": valid_record_count - len(buckets),
        "counterexamples": sorted(
            counterexamples, key=lambda item: (item["oracle_id"], item["input_digest"])
        ),
        "scope": "registered_evidence_only_not_a_correctness_certificate",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="归并JSON验收记录；不运行候选程序。")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args()
    registry = json.loads(Path(arguments.registry).read_text(encoding="utf-8"))
    payload = json.loads(Path(arguments.runs).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        runs = payload["runs"]
        data_kind = payload.get("data_kind", "unclassified_records")
    else:
        runs = [payload]
        data_kind = "unclassified_records"
    results = []
    for run in runs:
        result = decide(registry, run)
        if isinstance(run, dict):
            result["case_name"] = run.get("case_name")
        results.append(result)
    report = {"data_kind": data_kind, "results": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()


"""显式执行独立真实模型组，绑定完整源码和日常文件指纹。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from closeout_check import protected_hashes, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--groups", default="1,2,3,4,5,6,7,8,9")
    parser.add_argument("--max-calls", type=int, default=30, choices=range(1, 31))
    arguments = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory = ROOT / "evidence" / ("six-live-" + stamp)
    prefix = ROOT / "evidence" / ("six-live-run-" + stamp)
    sources, protected = source_hashes(ROOT), protected_hashes()
    command = [sys.executable, "-B", "-X", "utf8", "tests/run_six_live_acceptance.py",
               "--runtime", str(arguments.runtime.resolve()), "--output-dir", str(directory),
               "--groups", arguments.groups, "--max-calls", str(arguments.max_calls)]
    timer = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    prefix.with_suffix(".txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    raw = json.loads((directory / "report.json").read_text(encoding="utf-8")) if (directory / "report.json").is_file() else {}
    calls = raw.get("model_calls", [])
    def reported_usage(call):
        value = call.get("metadata", {}).get("usage")
        return value if type(value) is dict else {}
    usage = {field: sum(reported_usage(call).get(field, 0) for call in calls
                       if type(reported_usage(call).get(field)) is int)
             for field in ("prompt_tokens", "completion_tokens", "total_tokens")}
    unknown = sum(not all(type(reported_usage(call).get(field)) is int
                          for field in usage) for call in calls)
    record = dict(scope="Independent real-model and actual Docker; fixed simulated inputs, no human acceptance",
                  report=str(directory / "report.json"), command=command, exit_code=result.returncode,
                  elapsed_seconds=round(time.monotonic() - timer, 3),
                  version_sha256=hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
                  source_hashes_before=sources, source_hashes_after=source_hashes(ROOT),
                  protected_before=protected, protected_after=protected_hashes(),
                  groups_passed=raw.get("groups_passed", []), groups_not_passed=raw.get("groups_not_passed", []),
                  propose_calls_started=raw.get("propose_calls_started"),
                  transport_attempts_reported=raw.get("transport_attempts_reported"),
                  usage=usage, calls_with_unknown_usage=unknown, cost=None,
                  reported_model_labels=sorted({call.get("metadata", {}).get("reported_model") for call in calls if type(call.get("metadata", {}).get("reported_model")) is str}),
                  failure=raw.get("failure"))
    record["source_unchanged"] = sources == record["source_hashes_after"]
    record["protected_unchanged"] = protected == record["protected_after"]
    record["passed"] = result.returncode == 0 and raw.get("status") == "passed" and record["source_unchanged"] and record["protected_unchanged"]
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("passed", "groups_passed", "groups_not_passed", "propose_calls_started", "transport_attempts_reported", "usage", "failure", "version_sha256")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

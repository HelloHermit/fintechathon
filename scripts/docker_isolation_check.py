"""运行真实Docker独立专项并保存本轮源码/保护文件指纹；不调用模型。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from closeout_check import protected_hashes, source_hashes


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    arguments = parser.parse_args()
    started = datetime.now(timezone.utc)
    prefix = ROOT / "evidence" / ("docker-isolation-run-" + started.strftime("%Y%m%d-%H%M%S-%f"))
    sources_before, protected_before = source_hashes(ROOT), protected_hashes()
    environment = os.environ.copy()
    environment["FINTECH_DOCKER_RUNTIME"] = str(arguments.runtime.resolve())
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "tests" / "test_docker_isolation_independent.py")]
    timer = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8")
    output = completed.stdout + completed.stderr
    prefix.with_suffix(".txt").write_text(output, encoding="utf-8")
    match = re.search(r"Independent evidence: (.+)", output)
    independent_path = Path(match[1].strip()) if match else None
    independent = json.loads(independent_path.read_text(encoding="utf-8")) if independent_path and independent_path.is_relative_to(ROOT / "evidence") else {}
    sources_after, protected_after = source_hashes(ROOT), protected_hashes()
    record = {"scope": "actual Docker independent suite; no model; hash-only protected files",
              "started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": round(time.monotonic() - timer, 3), "exit_code": completed.returncode,
              "command": command, "runtime_directory": str(arguments.runtime.resolve()),
              "independent_evidence": str(independent_path) if independent_path else None,
              "tests_run": independent.get("tests_run"), "failures": independent.get("failure_count"),
              "errors": independent.get("error_count"), "skips": independent.get("skip_count"),
              "source_hashes_before": sources_before, "source_hashes_after": sources_after,
              "source_unchanged": sources_before == sources_after,
              "version_sha256": hashlib.sha256(json.dumps(sources_before, sort_keys=True).encode()).hexdigest(),
              "protected_before": protected_before, "protected_after": protected_after,
              "protected_unchanged": protected_before == protected_after}
    record["passed"] = bool(completed.returncode == 0 and independent.get("successful")
                            and independent.get("tests_run", 0) >= 33 and independent.get("skip_count") == 0
                            and record["source_unchanged"] and record["protected_unchanged"])
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("passed", "tests_run", "failures", "errors", "skips", "source_unchanged", "protected_unchanged", "version_sha256", "independent_evidence")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

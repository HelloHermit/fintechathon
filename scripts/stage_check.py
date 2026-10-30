"""分阶段运行独立离线验收，保存新证据、源码与保护文件指纹。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from closeout_check import protected_hashes, source_hashes


ROOT = Path(__file__).resolve().parents[1]
STAGES = {"recovery": ("test_recovery_independent.py", 37),
          "context": ("test_context_independent.py", 45)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    arguments = parser.parse_args()
    filename, minimum_methods = STAGES[arguments.stage]
    started = datetime.now(timezone.utc)
    prefix = ROOT / "evidence" / (arguments.stage + "-run-" + started.strftime("%Y%m%d-%H%M%S-%f"))
    sources_before, protected_before = source_hashes(ROOT), protected_hashes()
    command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "tests" / filename)]
    timer = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    output = completed.stdout + completed.stderr
    prefix.with_suffix(".txt").write_text(output, encoding="utf-8")
    match = re.search(r"Independent evidence: (.+)", output)
    if match is None:
        # 两位独立作者的原始输出不同：也接受一整行本阶段唯一证据路径。
        match = re.search(r"^([A-Za-z]:[^\r\n]*[\\/]" + arguments.stage + r"-independent-[^\r\n]+\.json)\s*$", output, re.M)
    independent_path = Path(match[1].strip()) if match else None
    independent = json.loads(independent_path.read_text(encoding="utf-8")) if independent_path and independent_path.is_relative_to(ROOT / "evidence") else {}
    sources_after, protected_after = source_hashes(ROOT), protected_hashes()
    record = {"stage": arguments.stage, "scope": "independent offline public-API suite; no real model or human acceptance",
              "started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": round(time.monotonic() - timer, 3), "exit_code": completed.returncode,
              "command": command, "independent_evidence": str(independent_path) if independent_path else None,
              "tests_run": independent.get("tests_run"), "failures": independent.get("failures"),
              "errors": independent.get("errors"), "skips": independent.get("skipped"),
              "source_hashes_before": sources_before, "source_hashes_after": sources_after,
              "source_unchanged": sources_before == sources_after,
              "version_sha256": hashlib.sha256(json.dumps(sources_before, sort_keys=True).encode()).hexdigest(),
              "protected_before": protected_before, "protected_after": protected_after,
              "protected_unchanged": protected_before == protected_after}
    independent_success = independent.get("successful")
    if independent_success is None:
        independent_success = (independent.get("tests_run") == minimum_methods
                               and independent.get("failures") == independent.get("errors") == independent.get("skipped") == 0)
    record["passed"] = bool(completed.returncode == 0 and independent_success
                            and independent.get("tests_run", 0) >= minimum_methods and independent.get("skipped") == 0
                            and record["source_unchanged"] and record["protected_unchanged"])
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("passed", "tests_run", "failures", "errors", "skips", "source_unchanged", "protected_unchanged", "version_sha256", "independent_evidence")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""隔离阶段的旧功能回归与版本记录；不调用模型，不打开日常账本。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

from closeout_check import protected_hashes, source_hashes


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run_legacy_suite():
    """原159项单独复跑；真实隔离专项必须显式传入运行时另跑。"""
    sys.path.insert(0, str(ROOT))
    discovered = unittest.defaultTestLoader.discover(str(ROOT / "tests"), "test_*.py")
    separate_suites = ("test_isolation_independent.", "test_docker_isolation_independent.",
                       "test_recovery_independent.", "test_context_independent.", "test_six_independent.")
    tests = [test for test in flatten(discovered)
             if not test.id().startswith(separate_suites)]
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
    return 0 if result.wasSuccessful() and result.testsRun >= 159 and not result.skipped else 1


def main():
    if sys.argv[1:] == ["--legacy-child"]:
        return run_legacy_suite()
    if sys.argv[1:]:
        raise SystemExit("Only --legacy-child is supported internally.")
    started = datetime.now(SHANGHAI)
    prefix = ROOT / "evidence" / ("isolation-regression-" + started.strftime("%Y%m%d-%H%M%S-%f"))
    protected_before, sources_before = protected_hashes(), source_hashes(ROOT)
    command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--legacy-child"]
    timer = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    output = completed.stdout + completed.stderr
    prefix.with_suffix(".txt").write_text(output, encoding="utf-8")
    summary = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    sources_after, protected_after = source_hashes(ROOT), protected_hashes()
    record = dict(started_at=started.isoformat(), finished_at=datetime.now(SHANGHAI).isoformat(),
                  command=command, exit_code=completed.returncode,
                  wall_seconds=round(time.monotonic() - timer, 3),
                  unittest_methods=int(summary[1]) if summary else None,
                  unittest_seconds=float(summary[2]) if summary else None,
                  passed=completed.returncode == 0 and bool(summary) and bool(re.search(r"^OK$", output, re.M)),
                  source_hashes_before=sources_before, source_hashes_after=sources_after,
                  source_unchanged=sources_before == sources_after,
                  version_sha256=hashlib.sha256(json.dumps(sources_before, sort_keys=True).encode()).hexdigest(),
                  protected_before=protected_before, protected_after=protected_after,
                  protected_unchanged=protected_before == protected_after,
                  scope="Legacy offline simulation regression. Real OS isolation runs separately with explicit runtime; no real-model call or personal verification.")
    record["result_counts"] = {name: int(match[1]) if (match := re.search(rf"{name}=(\d+)", output)) else 0
                               for name in ("failures", "errors", "skipped")}
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("unittest_methods", "exit_code", "passed", "source_unchanged", "protected_unchanged", "version_sha256")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] and record["source_unchanged"] and record["protected_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

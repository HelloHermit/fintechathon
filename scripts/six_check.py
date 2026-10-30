"""分开运行六场景或既有回归，记录本次受测版本及日常文件保护。"""

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

from closeout_check import source_hashes, protected_hashes

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "independent": "test_six_independent.py",
    "context": "test_context_independent.py",
    "recovery": "test_recovery_independent.py",
    "docker": "test_docker_isolation_independent.py",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=SUITES)
    parser.add_argument("--runtime", type=Path, help="显式Docker组或新增专项S50使用的受信运行时")
    arguments = parser.parse_args()
    if arguments.suite == "docker" and arguments.runtime is None:
        parser.error("Docker组需要明确指定受信runtime目录。")
    started = datetime.now(timezone.utc)
    prefix = ROOT / "evidence" / ("six-" + arguments.suite + "-run-" + started.strftime("%Y%m%d-%H%M%S-%f"))
    before, protected = source_hashes(ROOT), protected_hashes()
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if arguments.suite == "docker":
        environment["FINTECH_DOCKER_RUNTIME"] = str(arguments.runtime.resolve())
    else:
        environment.pop("FINTECH_DOCKER_RUNTIME", None)
    environment.pop("FINTECH_SIX_DOCKER_RUNTIME", None)
    if arguments.suite == "independent" and arguments.runtime is not None:
        environment["FINTECH_SIX_DOCKER_RUNTIME"] = str(arguments.runtime.resolve())
    command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "tests" / SUITES[arguments.suite])]
    timer = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8")
    output = result.stdout + result.stderr
    # 仅作为外围留痕；测试作者的原始JSON另存，不替代其判读。
    output = re.sub(r'((?:confirmation_code|recovery_code)[\"\s:]+)[0-9]{6}', r'\1[omitted]', output)
    prefix.with_suffix(".txt").write_text(output, encoding="utf-8")
    after, protected_after = source_hashes(ROOT), protected_hashes()
    count = re.search(r"Ran (\d+) tests?", output)
    if count is None:
        count = re.search(r"methods=(\d+)", output)
    original_evidence = None
    original_counts = None
    if arguments.suite == "context":
        match = re.search(r"^([A-Za-z]:[^\r\n]*[\\/]context-independent-[^\r\n]+\.json)\s*$", output, re.M)
        if match:
            original_evidence = Path(match[1].strip())
            if original_evidence.resolve().is_relative_to((ROOT / "evidence").resolve()):
                raw = json.loads(original_evidence.read_text(encoding="utf-8"))
                original_counts = {name: raw.get(name) for name in ("tests_run", "failures", "errors", "skipped")}
    scope = "independent actual Docker suite" if arguments.suite == "docker" else "independent offline suite"
    if arguments.suite == "independent" and arguments.runtime is not None:
        scope = "51 independent offline methods plus explicit S50 actual Docker integration; no real model or human acceptance"
    record = dict(suite=arguments.suite, scope=scope,
                  started_at_utc=started.isoformat(), finished_at_utc=datetime.now(timezone.utc).isoformat(),
                  elapsed_seconds=round(time.monotonic() - timer, 3), command=command,
                  exit_code=result.returncode, tests_run=int(count[1]) if count else None,
                  independent_evidence=str(original_evidence) if original_evidence else None,
                  independent_counts=original_counts,
                  version_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                  source_hashes_before=before, source_hashes_after=after, source_unchanged=before == after,
                  protected_before=protected, protected_after=protected_after, protected_unchanged=protected == protected_after)
    skipped = re.search(r"skipped=(\d+)", output)
    record["passed"] = result.returncode == 0 and before == after and protected == protected_after and bool(count) and (skipped is None or int(skipped[1]) == 0)
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("suite", "passed", "tests_run", "exit_code", "source_unchanged", "protected_unchanged", "version_sha256")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

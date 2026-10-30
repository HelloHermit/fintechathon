"""解包校验全部文件，并在同一源码版本复跑既有及六场景验收。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import uuid
import zipfile

from closeout_check import protected_hashes, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    arguments = parser.parse_args()
    archive_path = arguments.archive.resolve(strict=True)
    runtime = arguments.runtime.resolve(strict=True)
    if not archive_path.is_relative_to(ROOT / "dist"):
        parser.error("请选择本项目dist中的新源码包。")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    unpacked = ROOT / "tests" / ".runs" / ("six-unpacked-" + stamp + "-" + uuid.uuid4().hex)
    prefix = ROOT / "evidence" / ("six-package-check-" + stamp)
    before, protected = source_hashes(ROOT), protected_hashes()
    record = dict(started_at_utc=datetime.now(timezone.utc).isoformat(), archive=str(archive_path),
                  archive_sha256=digest(archive_path), runtime=str(runtime), unpacked=str(unpacked),
                  checks=[], passed=False, scope="Unpacked source replay; real-model and human checks are separate")
    timer = time.monotonic()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or archive.testzip() is not None:
                raise ValueError("invalid archive")
            manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
            hashes = manifest["files_sha256"]
            if set(names) != set(hashes) | {"PACKAGE_MANIFEST.json"}:
                raise ValueError("manifest mismatch")
            for name in names:
                parts = PurePosixPath(name).parts
                if (PurePosixPath(name).is_absolute() or ".." in parts or "\\" in name or ":" in name or
                        {".runs", "__pycache__", ".git", ".codex", "data", ".isolation"}.intersection(parts) or
                        name.endswith((".db", ".sqlite", ".sqlite3", ".pyc", ".db-wal", ".db-shm")) or
                        any(part.startswith(".env") and part != ".env.example" for part in parts) or
                        not (unpacked / name).resolve().is_relative_to(unpacked.resolve())):
                    raise ValueError("unsafe archive entry")
            if any(hashlib.sha256(archive.read(name)).hexdigest() != value for name, value in hashes.items()):
                raise ValueError("file mismatch")
            content = hashlib.sha256("".join(f"{name}\t{value}\n" for name, value in sorted(hashes.items())).encode()).hexdigest()
            if content != manifest["content_sha256"]:
                raise ValueError("content fingerprint mismatch")
            for source, target in (("src/isolation_worker.py", "worker.py"), ("src/isolation_supervisor.py", "supervisor.py"), ("src/six_calculator.py", "six_calculator.py")):
                if digest(runtime / target) != hashes[source]:
                    raise ValueError("tested runtime differs from package")
            archive.extractall(unpacked)
        extracted_sources = source_hashes(unpacked)
        if extracted_sources != before:
            raise ValueError("package source differs from current source")
        source_fingerprint = hashlib.sha256(json.dumps(extracted_sources, sort_keys=True).encode()).hexdigest()
        if (source_fingerprint != manifest["source_test_sha256"] or
                manifest["version"] != "working-tree-" + source_fingerprint[:12]):
            raise ValueError("source fingerprint mismatch")
        record.update(manifest_verified=True, file_count=len(names),
                      source_sha256=manifest["source_test_sha256"], source_hashes=extracted_sources)
        commands = [
            ("legacy159", ["scripts/isolation_check.py"]),
            ("context45", ["scripts/six_check.py", "--suite", "context"]),
            ("recovery37", ["scripts/six_check.py", "--suite", "recovery"]),
            ("new52_with_actual_Docker_S50", ["scripts/six_check.py", "--suite", "independent", "--runtime", str(runtime)]),
        ]
        for name, parameters in commands:
            command = [sys.executable, "-B", "-X", "utf8", *parameters]
            completed = subprocess.run(command, cwd=unpacked, capture_output=True, text=True, encoding="utf-8")
            output_path = prefix.with_name(prefix.name + "-" + name + ".txt")
            output_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
            record["checks"].append(dict(name=name, command=command, exit_code=completed.returncode,
                                         output=str(output_path), output_sha256=digest(output_path)))
            if completed.returncode != 0:
                raise ValueError("unpacked acceptance failed: " + name)
        # 已有公开启动复核：新库中成功业务/锁定在CLI重启后保持，不访问日常库。
        from closeout_check import check_documented_startup
        record["documented_startup"] = check_documented_startup(unpacked, prefix)
        if source_hashes(unpacked) != extracted_sources:
            raise ValueError("extracted source changed during replay")
        record["passed"] = True
    except Exception as error:
        record["error_type"] = type(error).__name__
        record["error"] = str(error) if type(error) is ValueError else "package validation or execution failed"
    record.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic() - timer, 3),
                  source_unchanged=source_hashes(ROOT) == before,
                  protected_before=protected, protected_after=protected_hashes())
    record["protected_unchanged"] = protected == record["protected_after"]
    record["passed"] = record["passed"] and record["source_unchanged"] and record["protected_unchanged"]
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as destination:
        json.dump(record, destination, ensure_ascii=False, indent=2)
    print(json.dumps({key: record[key] for key in ("passed", "archive_sha256", "elapsed_seconds", "source_unchanged", "protected_unchanged")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

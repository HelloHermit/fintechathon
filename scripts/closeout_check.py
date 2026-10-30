"""离线收尾回归与解包启动核对；不调用模型，不打开正常账本。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
import time
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(root):
    """包含页面、业务、脚本与测试的版本指纹，排除临时账本和缓存。"""
    result = {}
    for folder in ("src", "scripts", "tests"):
        for path in (root / folder).rglob("*"):
            relative = path.relative_to(root)
            if path.is_file() and path.suffix in {".py", ".ps1", ".html", ".css", ".js"} and not {".runs", "__pycache__"}.intersection(relative.parts):
                result[relative.as_posix()] = sha256(path)
    return dict(sorted(result.items()))


def protected_hashes():
    """只记录文件指纹，不读取或输出账本中的凭据。"""
    paths = list((PROJECT_ROOT / "dist").glob("*.zip"))
    paths += [path for path in (PROJECT_ROOT / "data").glob("*.db*") if path.is_file()]
    return {path.relative_to(PROJECT_ROOT).as_posix(): sha256(path) for path in sorted(paths)}


def business_snapshot(database):
    with sqlite3.connect(database) as connection:
        return {
            "balances": connection.execute("SELECT account_id,balance_cents FROM accounts ORDER BY account_id").fetchall(),
            "transaction_ids": connection.execute("SELECT transaction_id FROM transactions ORDER BY transaction_id").fetchall(),
            "transfer_count": connection.execute("SELECT count(*) FROM transfers").fetchone()[0],
            "verification_state": connection.execute("SELECT user_id,intent,failures,locked_until FROM verification_state ORDER BY user_id,intent").fetchall(),
            "audit_count": connection.execute("SELECT count(*) FROM audit_log").fetchone()[0],
        }


def check_documented_startup(root, output_prefix):
    """解包后按公开启动脚本重启两次，检查已提交业务和锁定仍在。"""
    database = root / "tests" / ".runs" / "documented-startup.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    setup_code = '''
from src.bank import BankService
import sys
bank = BankService(sys.argv[1])
try:
    candidate = {"intent":"transfer","params":{"contact_id":"wang","amount_cents":10000}}
    pending = bank.propose(candidate)
    assert bank.confirm(pending["request_id"], pending["confirmation_code"])["status"] == "success"
    pending = bank.propose(candidate)
    wrong = "000000" if pending["confirmation_code"] != "000000" else "000001"
    for expected in ("verification_failed", "verification_failed", "locked"):
        assert bank.confirm(pending["request_id"], wrong)["reason"] == expected
finally:
    bank.close()
'''
    environment = os.environ.copy()
    for name in ("FINTECH_MODEL_API_KEY", "FINTECH_MODEL_NAME", "FINTECH_MODEL_BASE_URL"):
        environment.pop(name, None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    created = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", setup_code, str(database)], cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert created.returncode == 0, "独立启动账本准备失败：" + created.stderr
    before = business_snapshot(database)
    assert dict(before["balances"])["alice-main"] == 990000
    assert dict(before["balances"])["bob-main"] == 110000
    assert before["transfer_count"] == 1 and len(before["transaction_ids"]) == 9
    assert before["verification_state"][0][2] == 3 and before["verification_state"][0][3]
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ".\\scripts\\start.ps1", "-DatabasePath", str(database)]
    restarts = []
    for number in (1, 2):
        completed = subprocess.run(command, input="/quit\n", cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        (Path(str(output_prefix) + f"-startup-{number}.txt")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
        assert completed.returncode == 0, "公开启动脚本退出非零"
        after = business_snapshot(database)
        assert {key: value for key, value in after.items() if key != "audit_count"} == {key: value for key, value in before.items() if key != "audit_count"}
        assert after["audit_count"] > before["audit_count"]
        restarts.append({"exit_code": completed.returncode, "snapshot": after})
        before = after
    return {"command": command, "offline_setup": "One confirmed 10000-cent transfer and three invalid confirmations on a fresh simulation database", "restarts": restarts, "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="验证自建源码包并在解包目录运行回归、启动核对")
    arguments = parser.parse_args()
    started = datetime.now(SHANGHAI)
    label = "package" if arguments.archive else "regression"
    prefix = PROJECT_ROOT / "evidence" / (f"closeout-{label}-" + started.strftime("%Y%m%d-%H%M%S-%f"))
    protected_before = protected_hashes()
    root = PROJECT_ROOT
    package_details = None
    if arguments.archive:
        root = PROJECT_ROOT / "tests" / ".runs" / ("unpacked-" + started.strftime("%Y%m%d-%H%M%S-%f"))
        with zipfile.ZipFile(arguments.archive) as archive:
            assert archive.testzip() is None
            names = archive.namelist()
            assert len(names) == len(set(names))
            for name in names:
                parts = PurePosixPath(name).parts
                assert not PurePosixPath(name).is_absolute() and ".." not in parts and "\\" not in name
                assert not {".runs", "__pycache__", "data", ".git", ".codex"}.intersection(parts)
                assert not name.endswith((".db", ".sqlite", ".sqlite3", ".pyc", ".db-wal", ".db-shm"))
                assert not any(part.startswith(".env") and part != ".env.example" for part in parts)
                assert (root / name).resolve().is_relative_to(root.resolve())
            manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
            assert set(names) == set(manifest["files_sha256"]) | {"PACKAGE_MANIFEST.json"}
            assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest["files_sha256"].items())
            expected = hashlib.sha256("".join(f"{name}\t{digest}\n" for name, digest in sorted(manifest["files_sha256"].items())).encode("utf-8")).hexdigest()
            assert expected == manifest["content_sha256"]
            archive.extractall(root)
        package_details = {"path": str(arguments.archive.resolve()), "sha256": sha256(arguments.archive), "files": len(names), "manifest": manifest, "extracted_path": str(root), "crc_and_manifest_passed": True}
    before = source_hashes(root)
    command = [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    timer = time.monotonic()
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8")
    duration = time.monotonic() - timer
    output = completed.stdout + completed.stderr
    prefix.with_suffix(".txt").write_text(output, encoding="utf-8")
    summary = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    after = source_hashes(root)
    record = {"started_at": started.isoformat(), "finished_at": datetime.now(SHANGHAI).isoformat(), "root": str(root), "command": command, "exit_code": completed.returncode, "wall_seconds": round(duration, 3), "unittest_methods": int(summary[1]) if summary else None, "unittest_seconds": float(summary[2]) if summary else None, "passed": completed.returncode == 0 and bool(summary) and bool(re.search(r"^OK$", output, re.M)), "source_hashes_before": before, "source_hashes_after": after, "source_unchanged": before == after, "version_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode("utf-8")).hexdigest(), "package": package_details, "scope": "Offline synthetic acceptance and implementation-side replay; no real model request or personal device/terminal verification."}
    record["result_counts"] = {name: int(match[1]) if (match := re.search(rf"{name}=(\d+)", output)) else (0 if record["passed"] else None) for name in ("failures", "errors", "skipped")}
    try:
        if record["passed"] and arguments.archive:
            record["documented_startup"] = check_documented_startup(root, prefix)
    except Exception as error:
        record["passed"] = False
        record["startup_error"] = str(error)
    record["protected_before"] = protected_before
    record["protected_after"] = protected_hashes()
    record["protected_unchanged"] = record["protected_before"] == record["protected_after"]
    prefix.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: record[key] for key in ("unittest_methods", "unittest_seconds", "exit_code", "passed", "source_unchanged", "version_sha256", "protected_unchanged")}, ensure_ascii=False))
    print(prefix.with_suffix(".json"))
    return 0 if record["passed"] and record["source_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())

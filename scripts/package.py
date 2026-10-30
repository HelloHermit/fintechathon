"""生成当前阶段可复现源码包；密钥、账本和缓存不进入包。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选新包路径，只允许项目dist目录且不能覆盖已有文件")
    arguments = parser.parse_args()
    allowed_suffixes = {".py", ".md", ".ps1", ".txt", ".json", ".jsonl", ".html", ".css", ".js"}
    selected_files = []
    for folder_name in ("src", "scripts", "tests", "docs", "spec", "evidence"):
        for path in (PROJECT_ROOT / folder_name).rglob("*"):
            relative = path.relative_to(PROJECT_ROOT)
            if path.is_file() and path.suffix in allowed_suffixes and not any(part in {".runs", "__pycache__"} for part in relative.parts):
                selected_files.append(path)
    selected_files += list(PROJECT_ROOT.glob("*.md"))
    selected_files += [PROJECT_ROOT / ".gitignore", PROJECT_ROOT / ".env.example"]
    selected_files += [PROJECT_ROOT / "design" / "browser-concept.png"]
    # 只加入已审查无有效码/秘密的本轮网页证据，不泛收临时截图。
    selected_files += list((PROJECT_ROOT / "evidence").glob("closeout-frontend-*.jpg"))
    selected_files += list((PROJECT_ROOT / "evidence").glob("six-ui-reviewed-*.png"))
    destination_folder = PROJECT_ROOT / "dist"
    destination_folder.mkdir(exist_ok=True)
    shanghai_time = datetime.now(timezone(timedelta(hours=8)))
    destination = arguments.output.resolve() if arguments.output else destination_folder / ("prototype-stage-" + shanghai_time.strftime("%Y%m%d-%H%M%S-%f") + ".zip")
    if not destination.resolve().is_relative_to(destination_folder.resolve()) or destination.suffix != ".zip" or destination.exists():
        parser.error("新包必须是dist目录内尚不存在的.zip文件；不覆盖历史包。")
    selected_files = sorted({path for path in selected_files if path.is_file()})
    file_hashes = {path.relative_to(PROJECT_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected_files}
    content_fingerprint = hashlib.sha256("".join(f"{name}\t{digest}\n" for name, digest in sorted(file_hashes.items())).encode("utf-8")).hexdigest()
    source_hashes = {name: digest for name, digest in file_hashes.items() if name.split("/")[0] in {"src", "scripts", "tests"} and Path(name).suffix in {".py", ".ps1", ".html", ".css", ".js"}}
    source_fingerprint = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode("utf-8")).hexdigest()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    manifest = {
        "created_at_shanghai": shanghai_time.isoformat(),
        "git_base_commit": revision.stdout.strip() if revision.returncode == 0 else None,
        "version": "working-tree-" + source_fingerprint[:12],
        "source_test_sha256": source_fingerprint,
        "content_sha256": content_fingerprint,
        "scope": "Complete six-direction simulated-bank source snapshot including task1-3; evidence describes tested limits, not human or formal competition acceptance.",
        "excluded": ["model credentials", "databases including MFA enrollment", "tests/.runs", "caches", "old archives", "machine-specific Docker runtime/client configuration"],
        "files_sha256": file_hashes,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in selected_files:
            archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert not any(name == ".env" or name.endswith((".db", ".pyc")) or "/.runs/" in name for name in names)
        assert {"src/web_assets/index.html", "src/web_assets/app.css", "src/web_assets/app.js"} <= set(names)
        assert archive.testzip() is None
        assert set(names) == set(file_hashes) | {"PACKAGE_MANIFEST.json"}
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in file_hashes.items())
    print(destination)
    print(f"{len(names)} files; stage snapshot only, not final submission or deadline acceptance.")
    print(f"version: {manifest['version']}; archive sha256: {hashlib.sha256(destination.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()

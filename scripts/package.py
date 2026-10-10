"""生成当前阶段可复现源码包；密钥、账本和缓存不进入包。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    allowed_suffixes = {".py", ".md", ".ps1", ".txt", ".json"}
    selected_files = []
    for folder_name in ("src", "scripts", "tests", "docs", "spec", "evidence"):
        for path in (PROJECT_ROOT / folder_name).rglob("*"):
            relative = path.relative_to(PROJECT_ROOT)
            if path.is_file() and path.suffix in allowed_suffixes and not any(part in {".runs", "__pycache__"} for part in relative.parts):
                selected_files.append(path)
    selected_files += list(PROJECT_ROOT.glob("*.md"))
    selected_files += [PROJECT_ROOT / ".gitignore", PROJECT_ROOT / ".env.example"]
    destination_folder = PROJECT_ROOT / "dist"
    destination_folder.mkdir(exist_ok=True)
    shanghai_time = datetime.now(timezone(timedelta(hours=8)))
    destination = destination_folder / ("prototype-stage-" + shanghai_time.strftime("%Y%m%d-%H%M%S-%f") + ".zip")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(selected_files)):
            if path.is_file():
                archive.write(path, path.relative_to(PROJECT_ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert not any(name == ".env" or name.endswith((".db", ".pyc")) or "/.runs/" in name for name in names)
        assert archive.testzip() is None
    print(destination)
    print(f"{len(names)} files; stage snapshot only, not final submission or deadline acceptance.")


if __name__ == "__main__":
    main()

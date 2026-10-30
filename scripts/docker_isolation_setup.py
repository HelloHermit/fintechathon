"""准备专用Docker运行时；只使用本机已下载镜像，不自动联网安装。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


PROJECT = Path(__file__).resolve().parents[1]
LOCAL_HOST = "npipe:////./pipe/dockerDesktopLinuxEngine"


def prepare(runtime, docker_executable, image):
    """固定镜像/客户端/受信源指纹；拒绝覆盖已有目录。"""
    runtime = runtime.resolve()
    docker_executable = docker_executable.resolve(strict=True)
    if os.name != "nt" or not runtime.is_relative_to(PROJECT.resolve()) or runtime.exists():
        raise ValueError("请使用项目内尚不存在的新运行时目录。")
    if not re.fullmatch(r"(?:docker\.io/library/)?python(?::3\.12-slim|@sha256:[0-9a-f]{64})|sha256:[0-9a-f]{64}", image):
        raise ValueError("请明确选择已下载的官方Python镜像或其不可变指纹。")
    client = runtime.parent / (runtime.name + "-docker-client")
    if client.exists():
        raise ValueError("专用空客户端目录已存在，请选择新运行时名称。")
    client.mkdir(parents=True)
    arguments = [str(docker_executable), "--config", str(client), "--host", LOCAL_HOST,
                 "image", "inspect", image]
    response = subprocess.run(arguments, capture_output=True, timeout=10)
    value = json.loads(response.stdout) if response.returncode == 0 else None
    if (type(value) is not list or len(value) != 1 or value[0].get("Os") != "linux"
            or value[0].get("Architecture") != "amd64"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", value[0].get("Id", ""))):
        raise ValueError("本地引擎或所选固定Linux镜像不可用，未改为普通执行。")
    runtime.mkdir(parents=True)
    for source, target in (("isolation_worker.py", "worker.py"),
                           ("isolation_supervisor.py", "supervisor.py"),
                           ("six_calculator.py", "six_calculator.py")):
        shutil.copyfile(PROJECT / "src" / source, runtime / target)
    config = dict(policy_version="docker-linux-readonly-v2",
                  package_name="FinTechathon.Worker." + uuid.uuid4().hex,
                  created_at_utc=datetime.now(timezone.utc).isoformat(),
                  docker_executable=str(docker_executable),
                  docker_executable_sha256=hashlib.sha256(docker_executable.read_bytes()).hexdigest(),
                  docker_host=LOCAL_HOST, docker_config_directory=str(client),
                  image_id=value[0]["Id"], image_reference=image,
                  image_repo_digests=value[0].get("RepoDigests", []),
                  files_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in runtime.iterdir() if path.is_file()})
    (runtime / "isolation-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    sys.path.insert(0, str(PROJECT))
    from src.isolation import checked_runtime
    checked_runtime(runtime)
    return dict(runtime=str(runtime), policy_version=config["policy_version"],
                image_id=config["image_id"], package_name=config["package_name"],
                copied_files=len(config["files_sha256"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=PROJECT / ".isolation" / "docker-runtime")
    parser.add_argument("--docker-executable", type=Path, required=True)
    parser.add_argument("--image", default="python:3.12-slim")
    arguments = parser.parse_args()
    try:
        result = prepare(arguments.runtime_dir, arguments.docker_executable, arguments.image)
    except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError):
        print("Docker隔离运行时准备失败；请核对本地引擎、已下载镜像与新的专用目录。", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

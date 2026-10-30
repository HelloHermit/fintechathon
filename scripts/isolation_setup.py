"""准备独立Python运行时；显式权限步骤仅授权该目录只读执行。"""

import argparse
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prepare_runtime(directory):
    """只复制标准库/解释器及固定worker，不复制第三方包或项目配置。"""
    if directory.exists():
        raise ValueError("目录已存在；不覆盖已有运行时，请使用新目录或仅核对权限。")
    source_directory = Path(sys.executable).parent
    library = source_directory / "Lib"
    if os.name != "nt" or not library.is_dir() or not (source_directory / "python.exe").is_file():
        raise ValueError("请使用Windows标准CPython3.10+，当前运行时布局不支持。")
    directory.mkdir(parents=True)
    (directory / "DLLs").mkdir()
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    for name in ("python.exe", "python3.dll", version + ".dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        source = source_directory / name
        if source.is_file():
            shutil.copy2(source, directory / name)
    for source in (source_directory / "DLLs").iterdir():
        if source.is_file() and source.suffix.lower() in {".pyd", ".dll"} and not source.name.startswith(("_tkinter", "tcl", "tk")):
            shutil.copy2(source, directory / "DLLs" / source.name)
    excluded = {"site-packages", "__pycache__", "test", "tests", "ensurepip", "idlelib", "tkinter", "turtledemo", "venv"}
    with zipfile.ZipFile(directory / (version + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(library.rglob("*.py")):
            relative = source.relative_to(library)
            if not excluded.intersection(relative.parts):
                archive.write(source, relative.as_posix())
    (directory / (version + "._pth")).write_text(version + ".zip\nDLLs\n.\n", encoding="ascii")
    shutil.copy2(PROJECT_ROOT / "src" / "isolation_worker.py", directory / "worker.py")
    shutil.copy2(PROJECT_ROOT / "src" / "six_calculator.py", directory / "six_calculator.py")
    hashes = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.rglob("*")) if path.is_file()}
    config = {"policy_version": "windows-lpac-job-v1", "package_name": "FinTechathon.Worker." + uuid.uuid4().hex,
              "profile_created": False, "created_at_shanghai": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "python_version": sys.version.split()[0], "files_sha256": hashes}
    (directory / "isolation-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def apply_permissions(directory):
    """不创建profile，不修改网络；仅给新的SID专用运行时RX权限。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.isolation import checked_runtime
    from src.windows_isolation import derive_sid_string
    directory, config = checked_runtime(directory, preparing_profile=True)
    sid = derive_sid_string(config["package_name"])
    command = ["icacls", str(directory), "/grant", "*" + sid + ":(OI)(CI)(RX)", "/T", "/Q"]
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode:
        raise ValueError("专用运行时ACL配置失败，未准备普通进程替代。")
    return {"package_name": config["package_name"], "sid": sid, "permission": "read_execute", "profile_created": config["profile_created"]}


def create_read_only_profile(directory):
    """显式登记专用身份，收紧其文件目录；不授予网络能力或例外。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.isolation import checked_runtime
    from src.windows_isolation import derive_sid_string, query_profile_folder
    directory, config = checked_runtime(directory, preparing_profile=True)
    package_name = config["package_name"]
    sid_text = derive_sid_string(package_name)
    userenv = ctypes.WinDLL("userenv")
    create = userenv.CreateAppContainerProfile
    create.restype = ctypes.c_int32
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    sid_pointer = ctypes.c_void_p()
    status = create(package_name, "FinTechathon restricted worker", "Dedicated simulated-tool worker; no network capabilities", None, 0, ctypes.byref(sid_pointer))
    if status < 0 and (status & 0xFFFFFFFF) != 0x800700B7:
        raise ValueError("专用profile登记失败，HRESULT=" + hex(status & 0xFFFFFFFF))
    if sid_pointer.value:
        advapi = ctypes.WinDLL("advapi32")
        advapi.FreeSid.argtypes = [ctypes.c_void_p]
        advapi.FreeSid.restype = ctypes.c_void_p
        advapi.FreeSid(sid_pointer)
    folder = query_profile_folder(package_name)
    if not folder:
        raise ValueError("已登记身份未返回文件目录，停止配置。")
    profile_directory = Path(folder).resolve()
    local_packages = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Packages").resolve()
    relative_profile = profile_directory.relative_to(local_packages) if profile_directory.is_relative_to(local_packages) else None
    if not relative_profile or not relative_profile.parts or relative_profile.parts[0].lower() != package_name.lower():
        raise ValueError("profile路径不属于本次明确登记的专用目录，未改ACL。")
    profile_root = local_packages / relative_profile.parts[0]
    config.update(profile_created=True, profile_directory=str(profile_directory), profile_files_read_only=False)
    config_path = directory / "isolation-config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    commands = [
        ["icacls", str(profile_root), "/grant:r", "*" + sid_text + ":(OI)(CI)(RX)", "/T", "/Q"],
        ["icacls", str(profile_root), "/deny", "*" + sid_text + ":(OI)(CI)(WD,AD,WEA,WA,DE,DC,WDAC,WO)", "/T", "/Q"],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True)
        if completed.returncode:
            raise ValueError("专用profile文件ACL收紧失败；配置标记未就绪，拒绝运行。")
    config["profile_files_read_only"] = True
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return {"profile_created": True, "profile_directory": str(profile_directory), "profile_files_read_only": True, "network_capabilities": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=PROJECT_ROOT / ".isolation" / "runtime")
    parser.add_argument("--apply-permissions", action="store_true", help="显式修改专用runtime ACL；须经实际权限流程授权")
    parser.add_argument("--permissions-only", action="store_true", help="对已准备且指纹有效目录仅配置RX权限")
    parser.add_argument("--create-profile", action="store_true", help="显式登记专用AppContainer身份并把它的文件目录设为只读；须经权限流程")
    arguments = parser.parse_args()
    directory = arguments.runtime_dir.absolute()
    if not directory.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        print("运行时须位于当前项目内的专用目录。", file=sys.stderr)
        return 1
    try:
        if not arguments.permissions_only:
            config = prepare_runtime(directory)
            print(json.dumps({"prepared": True, "runtime_directory": str(directory), "files": len(config["files_sha256"]), "profile_created": False}))
        if arguments.apply_permissions or arguments.permissions_only:
            print(json.dumps(apply_permissions(directory)))
        else:
            print("运行时已准备，尚未授权LPAC读取；下一步显式配置该目录只读/执行ACL。")
        if arguments.create_profile:
            print(json.dumps(create_read_only_profile(directory)))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

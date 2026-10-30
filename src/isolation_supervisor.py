"""容器内可信PID1：只启动一个固定worker，并在墙钟到期时收回它。"""

import argparse
import ctypes
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--wall", type=float, required=True)
    parser.add_argument("--script", required=True)
    arguments = parser.parse_args()
    child = None
    try:
        runtime = Path("/runtime").resolve(strict=True)
        script = Path(arguments.script).resolve(strict=True)
        if (os.getpid() != 1 or os.geteuid() != 65534 or os.getegid() != 65534
                or not math.isfinite(arguments.wall) or not 0.2 <= arguments.wall <= 5
                or not script.is_file() or not script.is_relative_to(runtime)
                or script == Path(__file__).resolve()
                or resource.getrlimit(resource.RLIMIT_CPU) != (1, 1)):
            return 125
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
        if (int(status["CapEff"].strip(), 16) != 0 or status["NoNewPrivs"].strip() != "1"
                or status["Seccomp"].strip() != "2"):
            return 125
        # 同UID的worker也不能用ptrace或process_vm_writev改动监督者的定时状态。
        library = ctypes.CDLL(None, use_errno=True)
        library.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.c_ulong, ctypes.c_ulong]
        library.prctl.restype = ctypes.c_int
        if library.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE=0
            return 125
        deadline = time.monotonic() + arguments.wall
        child = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(script)],
                                 stdin=None, stdout=None, stderr=None, close_fds=True)
        while True:
            code = child.poll()
            if code is not None:
                # worker自己exit124不能伪造可信监督者的timeout结果。
                return 0 if code == 0 else 1
            if time.monotonic() >= deadline:
                child.kill()
                child.wait(timeout=0.5)
                return 124
            time.sleep(0.01)
    except BaseException:
        # 路径与异常正文可能含业务数据，不输出任意异常文本。
        return 125
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass


if __name__ == "__main__":
    raise SystemExit(main())

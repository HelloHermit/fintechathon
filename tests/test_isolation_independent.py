"""Independent LPAC/Job acceptance, authored from the frozen public contracts only.

No implementation sources are read. All probes, secrets, and databases belong to
this test run. Run explicitly only after the owner authorizes runtime ACL setup:
  python tests/test_isolation_independent.py --runtime-dir <prepared runtime>
Without that option/environment the unittest suite records a skip, never an OS
isolation pass. Evidence filenames are unique and are never overwritten.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME_ARGUMENT = None
CASE_SPECS = {}
OBSERVATIONS = {}
RUN_DIRECTORY = None
FAKE_SECRETS = []
PROBE_ACKNOWLEDGEMENT = "\n \t \n"


def specification(test_input, expected, method, uncertainty="Only the named local boundary is covered."):
    """Attach the independently chosen expected result before execution."""
    def decorate(function):
        CASE_SPECS[function.__name__] = {
            "input": test_input, "expected": expected, "method": method,
            "uncertainty": uncertainty,
        }
        return function
    return decorate


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def safe_value(value):
    """Keep bounded receipts, booleans and hashes; redact even fake secret values."""
    if isinstance(value, dict):
        return {str(key): safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value[:100]]
    if isinstance(value, str):
        for secret in FAKE_SECRETS:
            value = value.replace(secret, "[FAKE_SECRET_REDACTED]")
        return value[:1600]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {"type": type(value).__name__}


def receipt_summary(receipt):
    return safe_value({key: receipt.get(key) for key in
                       ("task_id", "request_id", "status", "reason", "metadata", "data")})


PROBE_SOURCE = r'''
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

payload = json.load(sys.stdin)
mode = payload["mode"]
# JSON whitespace is harmless before a successful result. Its trusted hash proves
# this independently authored probe reached its body before a failed/limited run.
sys.stdout.write("\n \t \n"); sys.stdout.flush()

def attempt(operation):
    try:
        operation()
        return True
    except BaseException:
        return False

def identity():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    security.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    security.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    security.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8 | 2, ctypes.byref(token)):
        return {"token_query_ok": False}
    def info(info_class):
        needed = wintypes.DWORD()
        security.GetTokenInformation(token, info_class, None, 0, ctypes.byref(needed))
        storage = ctypes.create_string_buffer(needed.value)
        if not security.GetTokenInformation(token, info_class, storage, needed.value, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return storage
    def access_checks():
        # Independently chosen disjoint bits differ from the trusted host's 1/2 mapping.
        class GENERIC_MAPPING(ctypes.Structure):
            _fields_ = [("read", wintypes.DWORD), ("write", wintypes.DWORD),
                        ("execute", wintypes.DWORD), ("all", wintypes.DWORD)]
        security.DuplicateToken.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
        security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                                                                 ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        security.AccessCheck.argtypes = [ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.POINTER(GENERIC_MAPPING), ctypes.c_void_p,
                                         ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                         ctypes.POINTER(wintypes.BOOL)]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        impersonation = wintypes.HANDLE()
        if not security.DuplicateToken(token, 2, ctypes.byref(impersonation)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_information = info(31)
        sid_string = wintypes.LPWSTR()
        if not security.ConvertSidToStringSidW(ctypes.c_void_p.from_buffer(sid_information).value, ctypes.byref(sid_string)):
            kernel.CloseHandle(impersonation)
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            package = sid_string.value
            everyone = "(A;;0x70;;;WD)"
            package_ace = "(A;;0x50;;;" + package + ")"
            aap = "(A;;0x10;;;S-1-15-2-1)"
            arap = "(A;;0x20;;;S-1-15-2-2)"
            descriptors = {"everyone_only": everyone, "package_positive": everyone + package_ace,
                           "aap_only": everyone + aap, "restricted_package_only": everyone + arap,
                           "distinct_package_bits": everyone + aap + arap, "empty_dacl": ""}
            answers = {}
            for label, entries in descriptors.items():
                descriptor = ctypes.c_void_p()
                if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW("O:SYG:SYD:" + entries, 1,
                                                                                      ctypes.byref(descriptor), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    mapping = GENERIC_MAPPING(0x10, 0x20, 0x40, 0x70)
                    privileges = ctypes.create_string_buffer(4096); length = wintypes.DWORD(len(privileges))
                    granted = wintypes.DWORD(); allowed = wintypes.BOOL()
                    ctypes.set_last_error(0)
                    api_ok = security.AccessCheck(descriptor, impersonation, 0x02000000, ctypes.byref(mapping), privileges,
                                                  ctypes.byref(length), ctypes.byref(granted), ctypes.byref(allowed))
                    answers[label] = {"api_ok": bool(api_ok), "allowed": bool(allowed.value),
                                      "granted": granted.value, "error": ctypes.get_last_error()}
                finally:
                    kernel.LocalFree(descriptor)
            return answers
        finally:
            kernel.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p)); kernel.CloseHandle(impersonation)
    try:
        integrity = info(25)
        sid = ctypes.c_void_p.from_buffer(integrity).value
        count = security.GetSidSubAuthorityCount(sid).contents.value
        checks = access_checks()
        expected = {"everyone_only": 0, "package_positive": 0x50, "aap_only": 0,
                    "restricted_package_only": 0x20, "distinct_package_bits": 0x20, "empty_dacl": 0}
        return {"token_query_ok": True, "pid": os.getpid(),
                "is_appcontainer": bool(wintypes.DWORD.from_buffer(info(29)).value),
                "is_lpac": all(checks[label]["api_ok"] and checks[label]["granted"] == mask
                               and checks[label]["allowed"] == bool(mask) for label, mask in expected.items()),
                "independent_access_checks": checks,
                "capability_count": wintypes.DWORD.from_buffer(info(30)).value,
                "integrity_rid": security.GetSidSubAuthority(sid, count - 1).contents.value}
    finally:
        kernel.CloseHandle(token)

result = {}
if mode == "identity":
    result = identity()
elif mode == "ping":
    result = {"probe_ran": True, "pid": os.getpid()}
elif mode == "profile_writes":
    for item in payload["targets"]:
        def create_file():
            with open(item["file_path"], "xb") as output:
                output.write(b"INDEPENDENT_PROFILE_WRITE")
        result[item["label"]] = {"create_file": attempt(create_file),
                                  "create_directory": attempt(lambda: os.mkdir(item["directory_path"]))}
elif mode == "files":
    for item in payload["targets"]:
        path = item["path"]
        def read():
            with open(path, "rb") as source:
                source.read(64)
        def write():
            with open(path, "ab") as output:
                output.write(b"INDEPENDENT_ATTACK_WRITE")
        result[item["label"]] = {"read": attempt(read), "write": attempt(write),
                                 "delete": attempt(lambda: os.remove(path))}
    for item in payload["create_targets"]:
        def create():
            with open(item["path"], "xb") as output:
                output.write(b"INDEPENDENT_ATTACK_CREATE")
        result[item["label"]] = {"create": attempt(create)}
elif mode == "read_only":
    def read_path(path):
        with open(path, "rb") as source:
            source.read(16)
    result = {"script_read": attempt(lambda: read_path(__file__)),
              "interpreter_read": attempt(lambda: read_path(sys.executable)),
              "script_write": attempt(lambda: open(__file__, "ab").close()),
              "runtime_create": attempt(lambda: open(str(Path(sys.executable).parent / "probe-must-not-create.txt"), "xb").close())}
elif mode == "read_paths":
    for item in payload["targets"]:
        def read():
            with open(item["path"], "rb") as source:
                source.read(32)
        result[item["label"]] = attempt(read)
elif mode == "environment_handles":
    result = {"secret_environment_present": payload["environment_name"] in os.environ,
              "environment_names": sorted(os.environ.keys()),
              "runtime_environment_paths_match": all(Path(os.environ.get(name, "")).resolve() == Path(sys.executable).parent.resolve()
                                                     for name in ("PYTHONHOME", "TEMP", "TMP"))}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    file_handle = wintypes.HANDLE(payload["file_handle"])
    read = wintypes.DWORD()
    buffer = ctypes.create_string_buffer(128)
    # A numeric handle can collide with a pipe handle. Never read a pipe here.
    disk = kernel.GetFileType(file_handle) == 1
    okay = disk and bool(kernel.ReadFile(file_handle, buffer, 128, ctypes.byref(read), None))
    result["secret_file_read"] = okay
    result["secret_file_hash"] = hashlib.sha256(buffer.raw[:read.value]).hexdigest() if okay else None
    result["parent_process_handle_usable"] = bool(kernel.GetProcessId(wintypes.HANDLE(payload["process_handle"])))
    try:
        inherited_socket = socket.socket(fileno=payload["listener_handle"])
        inherited_socket.getsockname()
        result["listener_handle_usable"] = True
        inherited_socket.detach()
    except BaseException:
        result["listener_handle_usable"] = False
elif mode == "network":
    family = socket.AF_INET6 if payload["family"] == 6 else socket.AF_INET
    kind = socket.SOCK_DGRAM if payload["udp"] else socket.SOCK_STREAM
    with socket.socket(family, kind) as connection:
        connection.settimeout(0.4)
        def contact():
            address = (payload["address"], payload["port"])
            if payload["udp"]:
                connection.sendto(b"INDEPENDENT_WORKER_ATTEMPT", address)
            else:
                connection.connect(address)
                connection.sendall(b"INDEPENDENT_WORKER_ATTEMPT")
        result = {"network_call_succeeded": attempt(contact)}
elif mode == "child":
    try:
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(1)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result["subprocess_created"] = True
        result["subprocess_pid"] = child.pid
        child.wait(timeout=2)
    except BaseException:
        result["subprocess_created"] = False
    class STARTUPINFO(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
                    ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("xs", wintypes.DWORD), ("ys", wintypes.DWORD), ("xc", wintypes.DWORD), ("yc", wintypes.DWORD),
                    ("fill", wintypes.DWORD), ("flags", wintypes.DWORD), ("show", wintypes.WORD),
                    ("reserved_size", wintypes.WORD), ("reserved_bytes", ctypes.c_void_p),
                    ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]
    class PROCESSINFO(ctypes.Structure):
        _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                    ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                     ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESSINFO)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    start = STARTUPINFO(); start.cb = ctypes.sizeof(start)
    information = PROCESSINFO()
    command = ctypes.create_unicode_buffer('"' + sys.executable + '" -I -c "import time; time.sleep(1)"')
    created = kernel.CreateProcessW(sys.executable, command, None, None, False, 0x01000000,
                                    None, None, ctypes.byref(start), ctypes.byref(information))
    result["native_breakaway_created"] = bool(created)
    if created:
        kernel.CloseHandle(information.thread); kernel.CloseHandle(information.process)
elif mode == "sleep":
    time.sleep(20)
elif mode == "cpu":
    while True:
        pass
elif mode == "memory":
    blocks = []
    while True:
        blocks.append(bytearray(1024 * 1024))
elif mode == "output":
    stream = sys.stderr if payload.get("stderr") else sys.stdout
    stream.write("Q" * 200000); stream.flush()
elif mode == "invalid_output":
    sys.stdout.buffer.write(payload["bytes_text"].encode("utf-8")); sys.stdout.flush(); sys.exit(0)
elif mode == "nonzero":
    sys.stderr.write(payload["fake_secret"]); sys.stderr.flush(); sys.exit(7)
else:
    raise RuntimeError("unknown independent probe mode")
print(json.dumps(result, allow_nan=False))
'''


class WindowsProcesses:
    """Observe runtime image and process exit through independent public Win32 APIs."""
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

    def exited(self, process_id):
        handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 87  # No such PID, not merely access denied.
        try:
            return self.kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            self.kernel.CloseHandle(handle)

    def user_cpu_started(self, process_id):
        handle = self.kernel.OpenProcess(0x1000, False, process_id)
        if not handle: return False
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                               ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                                               ctypes.POINTER(wintypes.FILETIME)]
        creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        try:
            queried = self.kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                                  ctypes.byref(kernel_time), ctypes.byref(user_time))
            return bool(queried and ((user_time.dwHighDateTime << 32) | user_time.dwLowDateTime) > 0)
        finally:
            self.kernel.CloseHandle(handle)

    def runtime_processes(self, runtime):
        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError("process snapshot unavailable")
        matches = set()
        target = os.path.normcase(str(Path(runtime) / "python.exe"))
        try:
            entry = PROCESSENTRY32W(); entry.dwSize = ctypes.sizeof(entry)
            present = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while present:
                process = self.kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        length = wintypes.DWORD(len(buffer))
                        if self.kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
                            if os.path.normcase(buffer.value) == target:
                                matches.add(entry.th32ProcessID)
                    finally:
                        self.kernel.CloseHandle(process)
                present = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        return matches


class IsolationIndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global RUN_DIRECTORY
        runtime = RUNTIME_ARGUMENT or os.environ.get("ISOLATION_TEST_RUNTIME")
        if not runtime:
            raise unittest.SkipTest("No prepared runtime supplied; no OS isolation claim.")
        if os.name != "nt":
            raise unittest.SkipTest("Real Windows LPAC/Job required; no subprocess replacement.")
        from src.isolation import IsolatedExecutor, IsolationError
        from src.bank import BankService
        cls.Executor, cls.IsolationError, cls.BankService = IsolatedExecutor, IsolationError, BankService
        cls.runtime = Path(runtime).resolve()
        RUN_DIRECTORY = ROOT / "tests" / ".runs" / ("isolation-independent-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8])
        RUN_DIRECTORY.mkdir(parents=True, exist_ok=False)
        cls.directory = RUN_DIRECTORY
        cls.probe = RUN_DIRECTORY / "independent_attack_probe.py"
        cls.probe.write_text(PROBE_SOURCE, encoding="utf-8")
        cls.windows = WindowsProcesses()
        cls.clock = staticmethod(lambda: datetime(2026, 10, 12, 12, 0, tzinfo=timezone(timedelta(hours=8))))

    def setUp(self):
        self.case_directory = self.directory / self._testMethodName
        self.case_directory.mkdir(exist_ok=False)
        self.executors = []
        self.services = []
        OBSERVATIONS[self._testMethodName] = []

    def tearDown(self):
        for service in self.services:
            service.close()
        for executor in self.executors:
            executor.close()

    def observe(self, value):
        OBSERVATIONS[self._testMethodName].append(safe_value(value))

    def executor(self, *, name="monitor", limits=None, audit_hook=None):
        instance = self.Executor(self.runtime, self.case_directory / (name + ".sqlite3"), limits=limits, audit_hook=audit_hook)
        self.executors.append(instance)
        return instance

    def service(self, executor=None, *, name="bank", audit_hook=None):
        instance = self.BankService(self.case_directory / (name + ".sqlite3"), clock=self.clock, executor=executor, audit_hook=audit_hook)
        self.services.append(instance)
        return instance

    def run_probe(self, executor, mode, **values):
        start = time.monotonic()
        try:
            receipt = executor.run_probe(self.probe, {"mode": mode, **values}, request_id=self._testMethodName)
        except self.IsolationError:
            receipt = executor.last_receipt
        if not isinstance(receipt, dict):
            self.observe({"last_receipt_type": type(receipt).__name__})
        self.assertIsInstance(receipt, dict, "Public last_receipt must be a dictionary.")
        self.observe({"receipt": receipt_summary(receipt), "observed_wall_ms": round((time.monotonic() - start) * 1000)})
        return receipt

    def successful(self, receipt):
        self.assertEqual(receipt.get("status"), "success")
        self.assertEqual(receipt.get("reason"), "ok")
        self.assertIsInstance(receipt.get("data"), dict)
        self.no_active_process(receipt)
        return receipt["data"]

    def no_active_process(self, receipt):
        metadata = receipt.get("metadata", {})
        self.assertEqual(metadata.get("active_processes_after"), 0)
        process_id = metadata.get("pid")
        if process_id:
            exited = self.windows.exited(process_id)
            self.observe({"os_wait_exited": exited, "pid": process_id})
            self.assertTrue(exited, "The actual worker must have exited before result delivery.")

    def failed(self, receipt, reasons):
        self.assertIn(receipt.get("status"), {"failed", "cancelled"})
        self.assertIn(receipt.get("reason"), set(reasons))
        self.assertIsNone(receipt.get("data"), "A failed task must not deliver data.")
        self.no_active_process(receipt)

    def probe_body_reached(self, receipt):
        reached = receipt.get("metadata", {}).get("stdout_sha256") == digest(PROBE_ACKNOWLEDGEMENT.encode("utf-8"))
        self.observe({"independent_probe_body_reached": reached})
        self.assertTrue(reached, "Startup failure or suspended termination cannot count as an attack reaching its limit.")

    def balances(self, database):
        with sqlite3.connect(database) as connection:
            return dict(connection.execute("SELECT account_id,balance_cents FROM accounts"))

    def readable_roots(self, executor):
        roots = [Path(path).resolve() for path in executor.readable_directories]
        self.assertIn(self.runtime, roots, "Runtime must be explicitly listed as readable.")
        profiles = [path for path in roots if path != self.runtime]
        self.assertEqual(len(profiles), 1, "Contract exposes the entire dedicated profile root.")
        self.assertTrue(profiles[0].is_dir())
        self.assertNotIn(profiles[0], self.runtime.parents)
        self.assertNotIn(self.runtime, profiles[0].parents)
        return roots, profiles[0]

    def execute_failure(self, executor, task, payload, request_id, reasons):
        with self.assertRaises(self.IsolationError):
            executor.execute(task, payload, request_id=request_id)
        receipt = executor.last_receipt
        self.assertIsInstance(receipt, dict)
        self.observe({"receipt": receipt_summary(receipt)})
        self.failed(receipt, reasons)
        self.assertEqual(receipt.get("request_id"), request_id)
        return receipt

    @specification("Missing runtime config", "Constructor rejects and starts no ordinary fallback worker.", "Empty independent directory; compare OS runtime process set before/after.")
    def test_missing_configuration_refuses(self):
        empty = self.case_directory / "empty-runtime"; empty.mkdir()
        before = self.windows.runtime_processes(empty)
        with self.assertRaises(self.IsolationError):
            self.Executor(empty, self.case_directory / "monitor.sqlite3")
        self.assertEqual(before, self.windows.runtime_processes(empty))
        self.observe({"constructor_rejected": True, "worker_started": False})

    @specification("Defaults expanded, unknown limits key, process_count=2 and below-minimum limits", "Each invalid limit is rejected without worker creation.", "Only frozen public limits are used; independently compare process images.")
    def test_limits_cannot_be_weakened(self):
        invalid = [{"wall_seconds": 6}, {"cpu_seconds": 2}, {"memory_bytes": 129 * 1024 * 1024},
                   {"output_bytes": 65537}, {"process_count": 2}, {"cpu_rate_percent": 21},
                   {"wall_seconds": 0.19}, {"cpu_seconds": 0.09}, {"memory_bytes": 31 * 1024 * 1024},
                   {"output_bytes": 1023}, {"cpu_rate_percent": 0}, {"input_bytes": 65536}]
        before = self.windows.runtime_processes(self.runtime)
        for index, limits in enumerate(invalid):
            with self.subTest(limits=limits):
                with self.assertRaises(self.IsolationError):
                    self.Executor(self.runtime, self.case_directory / ("invalid-" + str(index) + ".sqlite3"), limits=limits)
        self.assertEqual(before, self.windows.runtime_processes(self.runtime))
        self.observe({"invalid_limits_count": len(invalid), "ordinary_fallback": False})

    @specification("Independent token query and six AccessCheck DACL controls using disjoint 0x10/0x20/0x40 bits", "AAP grant ignored, actual package positive and ARAP exact bits preserved; zero capabilities, low integrity and host six-control proof agree.", "Own ctypes GetTokenInformation(25/29/30/31), DuplicateToken and AccessCheck; compare independently frozen masks with host metadata and OS PID wait.", "Behavior proof replaces unavailable Token46 only after public v1.1 adaptation; original failure stays failed.")
    def test_identity_and_host_receipt_agree(self):
        receipt = self.run_probe(self.executor(), "identity")
        data = self.successful(receipt); metadata = receipt["metadata"]
        self.assertTrue(data.get("token_query_ok"))
        for key in ("is_appcontainer", "is_lpac"):
            self.assertIs(data.get(key), True); self.assertIs(metadata.get(key), True)
        independent_expected = {"everyone_only": 0, "package_positive": 0x50, "aap_only": 0,
                                "restricted_package_only": 0x20, "distinct_package_bits": 0x20, "empty_dacl": 0}
        host_expected = {"everyone_only": 0, "package_positive": 3, "aap_only": 0,
                         "restricted_package_only": 2, "distinct_package_bits": 2, "empty_dacl": 0}
        self.assertEqual(metadata.get("lpac_verification_method"), "accesscheck_aap_optout_v1")
        for checks, expected in ((data.get("independent_access_checks"), independent_expected),
                                 (metadata.get("lpac_access_checks"), host_expected)):
            self.assertIsInstance(checks, dict); self.assertEqual(set(checks), set(expected))
            for label, mask in expected.items():
                with self.subTest(identity_control=label, expected_mask=mask):
                    self.assertIs(checks[label].get("api_ok"), True)
                    self.assertIs(checks[label].get("allowed"), bool(mask))
                    self.assertEqual(checks[label].get("granted"), mask)
        self.assertEqual(data.get("capability_count"), 0); self.assertEqual(metadata.get("capability_count"), 0)
        self.assertEqual(data.get("pid"), metadata.get("pid"))
        self.assertEqual(data.get("integrity_rid"), 4096)
        self.assertIn(metadata.get("integrity"), (4096, "low", "Low", "S-1-16-4096", "0x1000"))
        flags = metadata.get("job_limit_flags", 0)
        self.assertEqual(flags & (0x2000 | 0x8 | 0x100 | 0x200), 0x2000 | 0x8 | 0x100 | 0x200)
        self.assertTrue(flags & (0x2 | 0x4), "A kernel CPU time limit is required.")
        self.assertIs(metadata.get("child_restricted"), True)
        self.assertIs(metadata.get("loopback_exempt"), False)
        for key in ("wall_ms", "cpu_ms", "peak_job_memory_bytes"):
            self.assertIsInstance(metadata.get(key), (int, float)); self.assertGreaterEqual(metadata[key], 0)

    @specification("Read own copied probe/interpreter; append to probe and create runtime file", "Allowed read succeeds; both writes fail.", "Actual file I/O inside LPAC; result booleans only. Runtime is the explicitly allowed area.")
    def test_allowed_runtime_is_read_only(self):
        data = self.successful(self.run_probe(self.executor(), "read_only"))
        self.assertIs(data.get("script_read"), True); self.assertIs(data.get("interpreter_read"), True)
        self.assertIs(data.get("script_write"), False); self.assertIs(data.get("runtime_create"), False)
        self.assertFalse((self.runtime / "probe-must-not-create.txt").exists())

    @specification("Create unique files and directories throughout the public dedicated profile root", "Every attempted create fails, including root and existing subdirectories; no marker exists afterward.", "Only enumerate directory metadata, never existing profile file contents; run real I/O inside the isolated probe.", "Covers the enumerated directories at test time; registry and disk quotas remain outside the claim.")
    def test_entire_profile_root_refuses_new_files_and_directories(self):
        executor = self.executor(); roots, profile = self.readable_roots(executor)
        self.assertNotEqual(profile, Path.home().resolve(), "Dedicated profile cannot be the real user profile.")
        directories = []
        def traversal_error(error): raise error
        for directory, child_names, _ in os.walk(profile, followlinks=False, onerror=traversal_error):
            current = Path(directory)
            self.assertTrue(current.resolve().is_relative_to(profile))
            child_names[:] = [name for name in child_names if not (current / name).is_symlink()
                              and not (os.lstat(current / name).st_file_attributes & 0x400)]
            directories.append(current)
            self.assertLessEqual(len(directories), 256, "Unexpected profile size; inspect metadata before broadening the probe.")
        self.assertTrue(directories)
        marker = "independent-denied-" + uuid.uuid4().hex
        targets = [{"label": str(index), "file_path": str(path / (marker + ".txt")),
                    "directory_path": str(path / (marker + "-dir"))} for index, path in enumerate(directories)]
        for offset in range(0, len(targets), 8):
            batch = targets[offset:offset + 8]
            data = self.successful(self.run_probe(executor, "profile_writes", targets=batch))
            for item in batch:
                self.assertEqual(data.get(item["label"]), {"create_file": False, "create_directory": False})
        absent = [not Path(item[key]).exists() for item in targets for key in ("file_path", "directory_path")]
        self.observe({"profile_directory_count": len(directories), "all_unique_markers_absent": all(absent)})
        self.assertTrue(all(absent))

    @specification("monitor_database paths inside runtime and public dedicated profile root", "Constructor rejects before opening a database; no file or fallback worker is created.", "Use only unique nonexistent paths under the two public readable roots; inspect existence and OS PID sets.")
    def test_monitor_database_cannot_be_inside_readable_roots(self):
        first = self.executor(); roots, _ = self.readable_roots(first)
        first.close(); self.executors.remove(first)
        before = self.windows.runtime_processes(self.runtime)
        for index, directory in enumerate(roots):
            path = directory / ("independent-denied-monitor-" + uuid.uuid4().hex + ".sqlite3")
            with self.subTest(root=index):
                self.assertFalse(path.exists())
                with self.assertRaises(self.IsolationError) as rejection: self.Executor(self.runtime, path)
                self.assertEqual(rejection.exception.reason, "invalid_input")
                self.assertFalse(path.exists(), "Forbidden monitor must be rejected before opening it.")
        self.assertEqual(before, self.windows.runtime_processes(self.runtime))
        self.observe({"readable_roots_checked": len(roots), "forbidden_database_files_absent": True})

    @specification("Existing independent monitor SQLite has a second hard link", "Executor rejects without changing either name or starting a worker.", "Create and close own valid monitor, create local hard link, compare SHA256 before and after constructor refusal.")
    def test_monitor_database_with_hard_link_refuses(self):
        executor = self.executor(); database = Path(executor.database_path)
        executor.close(); self.executors.remove(executor)
        alias = self.case_directory / "monitor-alias.sqlite3"; os.link(database, alias)
        self.assertGreaterEqual(database.stat().st_nlink, 2)
        original = digest(database.read_bytes()); before = self.windows.runtime_processes(self.runtime)
        with self.assertRaises(self.IsolationError) as rejection: self.Executor(self.runtime, database)
        self.assertEqual(rejection.exception.reason, "invalid_input")
        self.assertEqual(digest(database.read_bytes()), original); self.assertEqual(digest(alias.read_bytes()), original)
        self.assertEqual(before, self.windows.runtime_processes(self.runtime))
        self.observe({"hard_link_count": database.stat().st_nlink, "constructor_rejected": True, "original_unchanged": True})

    @specification("BankService database paths inside runtime/profile or identical to monitoring SQLite", "ValueError before opening the business database, no new forbidden files or business tables.", "Use public readable_directories/database_path; inspect only own monitor schema and path existence.")
    def test_business_database_cannot_overlap_readable_or_monitor_paths(self):
        executor = self.executor(); roots, _ = self.readable_roots(executor)
        for index, directory in enumerate(roots):
            forbidden = directory / ("independent-denied-bank-" + uuid.uuid4().hex + ".sqlite3")
            with self.subTest(root=index):
                self.assertFalse(forbidden.exists())
                with self.assertRaises(ValueError): self.BankService(forbidden, clock=self.clock, executor=executor)
                self.assertFalse(forbidden.exists())
        monitor = Path(executor.database_path)
        with sqlite3.connect(monitor) as connection:
            before = list(connection.execute("SELECT name,type,sql FROM sqlite_master ORDER BY name"))
        with self.assertRaises(ValueError): self.BankService(monitor, clock=self.clock, executor=executor)
        with sqlite3.connect(monitor) as connection:
            after = list(connection.execute("SELECT name,type,sql FROM sqlite_master ORDER BY name"))
        self.assertEqual(after, before)
        self.observe({"readable_roots_checked": len(roots), "monitor_schema_unchanged": True, "forbidden_files_absent": True})

    @specification("An independent initialized business database has a second hard link", "BankService refuses with ValueError before modifying the existing fixture.", "Initialize own simulated database without executor, close it, create hard link; check both SHA256 and balances.")
    def test_business_database_with_hard_link_refuses(self):
        fixture = self.service(name="hardlink-bank"); database = self.case_directory / "hardlink-bank.sqlite3"
        fixture.close(); self.services.remove(fixture)
        alias = self.case_directory / "bank-alias.sqlite3"; os.link(database, alias)
        original = digest(database.read_bytes()); before = self.balances(database)
        executor = self.executor()
        with self.assertRaises(ValueError): self.BankService(database, clock=self.clock, executor=executor)
        self.assertEqual(digest(database.read_bytes()), original); self.assertEqual(digest(alias.read_bytes()), original)
        self.assertEqual(self.balances(database), before)
        self.observe({"hard_link_count": database.stat().st_nlink, "constructor_rejected": True, "database_unchanged": True})

    @specification("The public monitor lock file has a second hard link", "Executor rejects invalid_input before opening or modifying the monitoring database.", "Close own initialized executor, hard-link str(database_path)+'.lock', compare original database and lock hashes.")
    def test_monitor_lock_with_hard_link_refuses(self):
        database = self.case_directory / "monitor-with-linked-lock.sqlite3"; lock = Path(str(database) + ".lock")
        lock.write_bytes(b"INDEPENDENT_EXISTING_LOCK")
        alias = self.case_directory / "monitor-lock-alias"; os.link(lock, alias)
        original_lock = digest(lock.read_bytes())
        with self.assertRaises(self.IsolationError) as rejection: self.Executor(self.runtime, database)
        self.assertEqual(rejection.exception.reason, "invalid_input")
        self.assertFalse(database.exists(), "Hard-linked existing lock must be refused before the monitor opens.")
        self.assertEqual(digest(lock.read_bytes()), original_lock); self.assertEqual(digest(alias.read_bytes()), original_lock)
        self.observe({"lock_link_count": lock.stat().st_nlink, "constructor_rejected": True, "database_and_lock_unchanged": True})

    @specification("One runtime identity is requested simultaneously with two distinct monitor databases", "Second owner refuses even with another monitor path; first close allows a new owner.", "Public constructors with same runtime and distinct own monitor paths; successful real probe after release.")
    def test_runtime_identity_is_exclusive_across_monitor_databases(self):
        first = self.executor(name="first-monitor")
        with self.assertRaises(self.IsolationError): self.Executor(self.runtime, self.case_directory / "second-monitor.sqlite3")
        first.close(); self.executors.remove(first)
        second = self.executor(name="second-monitor")
        data = self.successful(self.run_probe(second, "ping")); self.assertIs(data.get("probe_ran"), True)
        self.observe({"simultaneous_identity_refused": True, "new_owner_after_close_ran": True})

    @specification("Fake .env, synthetic bank/factors files via absolute, case, slash, dot/parent and extended paths", "Every external read/write/delete/create fails; host files retain original hashes.", "Probe performs real OS I/O; host independently checks bytes, existence and newly created paths.")
    def test_external_files_and_path_variants(self):
        fake_directory = self.case_directory / "fake-protected-data"; fake_directory.mkdir()
        variants = ["absolute", "case", "slash", "dot", "parent", "extended"]
        targets, originals, creates = [], {}, []
        for index, variant in enumerate(variants):
            path = fake_directory / (variant + (".env" if index == 0 else ".sqlite3" if index == 1 else ".factor"))
            contents = ("FAKE_ONLY_ISOLATION_SECRET_" + uuid.uuid4().hex).encode()
            FAKE_SECRETS.append(contents.decode()); path.write_bytes(contents); originals[path] = digest(contents)
            text = str(path)
            if variant == "case": text = text.swapcase()
            elif variant == "slash": text = text.replace("\\", "/")
            elif variant == "dot": text = str(fake_directory) + "\\.\\" + path.name
            elif variant == "parent": text = str(fake_directory) + "\\..\\" + fake_directory.name + "\\" + path.name
            elif variant == "extended": text = "\\\\?\\" + text
            targets.append({"label": variant, "path": text})
            creates.append({"label": variant + "_new", "path": str(fake_directory / (variant + "-must-not-exist"))})
        data = self.successful(self.run_probe(self.executor(), "files", targets=targets, create_targets=creates))
        intact = {path.name: path.exists() and digest(path.read_bytes()) == original for path, original in originals.items()}
        self.observe({"host_originals_intact": intact, "host_create_absent": [not Path(item["path"]).exists() for item in creates]})
        for item in targets:
            self.assertEqual(data.get(item["label"]), {"read": False, "write": False, "delete": False})
        self.assertTrue(all(intact.values()))
        for item in creates:
            self.assertEqual(data.get(item["label"]), {"create": False}); self.assertFalse(Path(item["path"]).exists())

    @specification("Read the actual independent monitoring database", "LPAC cannot read host monitoring SQLite.", "Probe open attempt while trusted executor owns monitor; no modification attack on audit evidence.")
    def test_monitor_database_is_not_worker_readable(self):
        executor = self.executor()
        data = self.successful(self.run_probe(executor, "read_paths", targets=[{"label": "monitor", "path": str(self.case_directory / "monitor.sqlite3")}]))
        self.assertIs(data.get("monitor"), False)

    @specification("A local directory junction resolves to the fake secret directory", "Read through reparse path fails; original fake file unchanged.", "Create own .runs junction without ACL/profile edits; host confirms junction target and real file.", "If local junction creation is unavailable this case is skipped, and full acceptance is not claimed.")
    def test_reparse_path_cannot_expand_access(self):
        target = self.case_directory / "junction-target"; target.mkdir()
        secret = target / "fake.factor"; original = b"FAKE_REPARSE_SECRET"; secret.write_bytes(original)
        link = self.case_directory / "junction-link"
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if result.returncode or not (link / secret.name).exists():
            self.observe({"junction_created": False, "setup_returncode": result.returncode})
            self.skipTest("Local reparse setup unavailable; no reparse boundary pass.")
        self.observe({"junction_created": True, "host_positive_read": (link / secret.name).read_bytes() == original})
        data = self.successful(self.run_probe(self.executor(), "read_paths", targets=[{"label": "junction", "path": str(link / secret.name)}]))
        self.assertIs(data.get("junction"), False); self.assertEqual(secret.read_bytes(), original)

    @specification("Parent exports fake secret env and marks file/socket/process handles inheritable", "Secret env absent; all three non-stdio handles unusable in worker; only allowed environment names.", "Parent verifies its own file read and socket/process handles; worker calls ReadFile/socket/GetProcessId, reports booleans and hash.")
    def test_environment_and_inherited_handles(self):
        import msvcrt
        fake = "FAKE_ENV_HANDLE_SECRET_" + uuid.uuid4().hex; FAKE_SECRETS.append(fake)
        path = self.case_directory / "fake-inherited-secret"; path.write_text(fake, encoding="ascii")
        environment_name = "FTH_INDEPENDENT_FAKE_SECRET"
        old = os.environ.get(environment_name); os.environ[environment_name] = fake
        descriptor = os.open(path, os.O_RDONLY); os.set_inheritable(descriptor, True)
        listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(2); listener.set_inheritable(True)
        kernel = self.windows.kernel
        parent_handle = kernel.OpenProcess(0x1000, True, os.getpid())
        self.assertTrue(parent_handle)
        try:
            parent_read = os.read(descriptor, 128); os.lseek(descriptor, 0, 0)
            self.assertEqual(digest(parent_read), digest(fake.encode("ascii")))
            self.observe({"parent_read_positive": True, "parent_listener_positive": bool(listener.getsockname()), "parent_process_handle_positive": bool(parent_handle)})
            data = self.successful(self.run_probe(self.executor(), "environment_handles", environment_name=environment_name,
                                                  file_handle=msvcrt.get_osfhandle(descriptor), listener_handle=listener.fileno(), process_handle=int(parent_handle)))
            for key in ("secret_environment_present", "secret_file_read", "listener_handle_usable", "parent_process_handle_usable"):
                self.assertIs(data.get(key), False)
            self.assertIs(data.get("runtime_environment_paths_match"), True)
            # Public 13-key adaptation; the original four-key contract remains a recorded failure.
            allowed = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
                       "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PUBLIC", "PYTHONHOME", "TEMP", "TMP"}
            self.assertTrue(set(name.upper() for name in data.get("environment_names", [])) <= allowed)
        finally:
            os.close(descriptor); listener.close(); kernel.CloseHandle(parent_handle)
            if old is None: os.environ.pop(environment_name, None)
            else: os.environ[environment_name] = old

    def network_case(self, family, udp=False):
        network_family = socket.AF_INET6 if family == 6 else socket.AF_INET
        address = "::1" if family == 6 else "127.0.0.1"
        kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
        try:
            listener = socket.socket(network_family, kind); listener.settimeout(0.35); listener.bind((address, 0))
        except OSError:
            self.skipTest("Host positive local listener unavailable; network type unverified.")
        received = []
        stop = threading.Event()
        if not udp: listener.listen(4)
        def receive():
            while not stop.is_set():
                try:
                    if udp:
                        packet, _ = listener.recvfrom(128)
                    else:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(0.3); packet = connection.recv(128)
                    received.append(digest(packet))
                except socket.timeout:
                    continue
                except OSError:
                    return
        thread = threading.Thread(target=receive, daemon=True); thread.start()
        try:
            with socket.socket(network_family, kind) as positive:
                positive.settimeout(0.5)
                if udp: positive.sendto(b"INDEPENDENT_PARENT_POSITIVE", listener.getsockname())
                else: positive.connect(listener.getsockname()); positive.sendall(b"INDEPENDENT_PARENT_POSITIVE")
            deadline = time.monotonic() + 1
            while not received and time.monotonic() < deadline: time.sleep(0.01)
            self.assertEqual(len(received), 1, "Same-target host positive control required.")
            data = self.successful(self.run_probe(self.executor(), "network", family=family, udp=udp, address=address, port=listener.getsockname()[1]))
            time.sleep(0.4)
            self.observe({"family": family, "udp": udp, "parent_positive_packets": 1, "total_host_received": len(received)})
            self.assertIs(data.get("network_call_succeeded"), False); self.assertEqual(len(received), 1)
        finally:
            stop.set(); listener.close(); thread.join(timeout=1)

    @specification("IPv4 loopback TCP same-target parent/worker", "Parent connects; worker connect denied; listener receives only parent.", "Real host socket listener, packet hashes and LPAC socket API.")
    def test_network_ipv4_tcp(self): self.network_case(4)

    @specification("IPv6 loopback TCP same-target parent/worker", "Parent connects; worker denied; listener receives only parent.", "Real IPv6 loopback listener and independent connection counts.", "Host IPv6 unavailable means skipped, never network pass.")
    def test_network_ipv6_tcp(self): self.network_case(6)

    @specification("IPv4 UDP same-target parent/worker", "Parent sends; worker send denied; no worker datagram received.", "Real host UDP listener and independent packet counts.")
    def test_network_ipv4_udp(self): self.network_case(4, udp=True)

    @specification("Allowed runtime interpreter invoked by subprocess and native CreateProcess with breakaway", "Neither creates a child process.", "Two real creation APIs; native path bypasses Python-level subprocess wrappers. Job/token receipt still required.")
    def test_child_process_and_breakaway_refused(self):
        data = self.successful(self.run_probe(self.executor(), "child"))
        self.assertIs(data.get("subprocess_created"), False); self.assertIs(data.get("native_breakaway_created"), False)

    @specification("20-second sleep; wall limit 1 second, independent stdout acknowledgement before sleeping", "timeout after probe entry; whole job stopped within declared cleanup allowance.", "Trusted stdout prefix hash, wall measurement, metadata and external PID wait; no data delivered.", "Attack budget changed from original 0.2s to 1s so 20% CPU startup can reach the probe; original first-run failure remains failed.")
    def test_wall_budget(self):
        start = time.monotonic(); receipt = self.run_probe(self.executor(limits={"wall_seconds": 1}), "sleep")
        self.failed(receipt, {"timeout"}); self.probe_body_reached(receipt)
        self.assertLess(time.monotonic() - start, 3.5)
        self.assertLessEqual(receipt["metadata"].get("wall_ms", 999999), 3100)

    @specification("Infinite busy loop; CPU limit 0.1 seconds and hard rate 20%", "cpu_limit; kernel CPU accounting bounded, job stops before wall timeout.", "Trusted host CPU and wall counters plus external process wait.", "Counter timing may be rounded by the OS; tolerance is 0.3 seconds total user CPU.")
    def test_cpu_budget(self):
        receipt = self.run_probe(self.executor(limits={"cpu_seconds": 0.1}), "cpu")
        self.failed(receipt, {"cpu_limit"}); self.probe_body_reached(receipt)
        self.assertLessEqual(receipt["metadata"].get("cpu_ms", 999999), 300)

    @specification("Repeated 1MiB allocations; memory budget 32MiB", "No success; memory_limit or honest nonzero_exit; peak bounded by kernel.", "Real allocation pressure; trusted peak Job memory, no OOM self-report accepted.")
    def test_memory_budget(self):
        receipt = self.run_probe(self.executor(limits={"memory_bytes": 32 * 1024 * 1024}), "memory")
        self.failed(receipt, {"memory_limit", "nonzero_exit"}); self.probe_body_reached(receipt)
        self.assertLessEqual(receipt["metadata"].get("peak_job_memory_bytes", 10**12), 32 * 1024 * 1024)

    @specification("200000 stdout bytes; output budget 1024", "output_limit; no data delivered; worker gone.", "Actual pipe pressure and external process wait.")
    def test_stdout_budget(self):
        receipt = self.run_probe(self.executor(limits={"output_bytes": 1024}), "output"); self.failed(receipt, {"output_limit"})
        count = receipt.get("metadata", {}).get("output_bytes", 0)
        self.assertGreater(count, len(PROBE_ACKNOWLEDGEMENT)); self.assertLessEqual(count, 1024)
        expected = (PROBE_ACKNOWLEDGEMENT.encode() + b"Q" * 200000)[:count]
        self.assertEqual(receipt.get("metadata", {}).get("stdout_sha256"), digest(expected))
        self.observe({"independent_output_prefix_confirmed": True, "bounded_retained_bytes": count})

    @specification("200000 stderr bytes; combined output budget 1024", "output_limit; stderr also counts, no raw stderr logged.", "Actual stderr pipe pressure and host audit metadata inspection.")
    def test_stderr_budget(self):
        receipt = self.run_probe(self.executor(limits={"output_bytes": 1024}), "output", stderr=True)
        self.failed(receipt, {"output_limit"}); self.probe_body_reached(receipt)
        self.assertLessEqual(receipt.get("metadata", {}).get("output_bytes", 999999), 1024)

    @specification("Cancel event is set during a real sleeping worker", "cancelled; at most 100ms detection plus 2s cleanup; no live process remains.", "Timer/event, host elapsed measurement, receipt and independent OS wait.")
    def test_cancellation_stops_real_worker(self):
        executor = self.executor(); event = threading.Event(); cancelled_at = []
        def cancel(): cancelled_at.append(time.monotonic()); event.set()
        timer = threading.Timer(1.0, cancel); timer.start()
        try:
            try: receipt = executor.run_probe(self.probe, {"mode": "sleep"}, cancel_event=event, request_id=self._testMethodName)
            except self.IsolationError: receipt = executor.last_receipt
            self.observe(receipt_summary(receipt)); self.failed(receipt, {"cancelled"}); self.probe_body_reached(receipt)
            self.assertEqual(receipt.get("status"), "cancelled")
            self.assertTrue(cancelled_at); self.assertLess(time.monotonic() - cancelled_at[0], 2.3)
        finally: timer.cancel()

    @specification("Worker exits 7 with fake secret written to stderr", "nonzero_exit, data withheld, fake secret absent from receipt and monitor.", "Real abnormal exit and serialized safety scans; fake secret body never printed.")
    def test_nonzero_exit_does_not_leak_stderr(self):
        secret = "FAKE_STDERR_SECRET_" + uuid.uuid4().hex; FAKE_SECRETS.append(secret)
        executor = self.executor(); receipt = self.run_probe(executor, "nonzero", fake_secret=secret)
        self.failed(receipt, {"nonzero_exit"}); self.probe_body_reached(receipt)
        self.assertEqual(receipt.get("metadata", {}).get("exit_code"), 7)
        absent = secret not in json.dumps(receipt, ensure_ascii=False) and secret not in json.dumps(executor.audit_events(), ensure_ascii=False)
        self.observe({"fake_secret_absent_from_receipt_and_audit": absent}); self.assertTrue(absent)

    @specification("Probe emits malformed JSON, duplicate keys, NaN, array, multiple objects or depth13", "Each invalid_output; raw output never reaches result or monitor.", "Own probe emits known invalid byte streams; last_receipt inspected after rejection.")
    def test_invalid_worker_results(self):
        outputs = ["bad-json", '{"a":1,"a":2}', '{"a":NaN}', "[]", "{}{}", '{"a":' * 13 + "0" + "}" * 13]
        executor = self.executor()
        for index, output in enumerate(outputs):
            with self.subTest(variant=index):
                receipt = self.run_probe(executor, "invalid_output", bytes_text=output)
                self.failed(receipt, {"invalid_output"})
                self.assertEqual(receipt.get("metadata", {}).get("stdout_sha256"),
                                 digest(PROBE_ACKNOWLEDGEMENT.encode() + output.encode("utf-8")))

    @specification("parse_candidate valid object followed by duplicates/nonfinite/depth/overlength; unknown task; >65536 JSON input", "Valid candidate parsed only as data; invalid_task/invalid_input reject, no fallback parsing.", "Only public execute and last_receipt; observe started count for rejected-before-launch inputs.")
    def test_candidate_parser_and_input_validation(self):
        executor = self.executor()
        valid = {"intent": "query_balance", "params": {}}
        try:
            parsed = executor.execute("parse_candidate", {"text": json.dumps(valid)})
        except self.IsolationError:
            self.observe({"receipt": receipt_summary(executor.last_receipt) if isinstance(executor.last_receipt, dict) else None})
            raise
        self.assertEqual(parsed, valid)
        self.successful(executor.last_receipt); self.observe(receipt_summary(executor.last_receipt))
        bad = [("parse_candidate", {"text": '{"a":1,"a":2}'}), ("parse_candidate", {"text": '{"a":Infinity}'}),
               ("parse_candidate", {"text": '{"a":' * 13 + "0" + "}" * 13}), ("parse_candidate", {"text": " " * 16001}),
               ("unlisted_tool", {}), ("parse_candidate", {"text": "x" * 70000}),
               ("compute_tool", {"intent": "query_balance", "params": {"bad": float("nan")}})]
        for index, (task, payload) in enumerate(bad):
            with self.subTest(variant=index):
                with self.assertRaises(self.IsolationError): executor.execute(task, payload)
                receipt = executor.last_receipt; self.observe(receipt_summary(receipt))
                self.failed(receipt, {"invalid_task"} if task == "unlisted_tool" else {"invalid_input", "invalid_output"})

    @specification("Unknown task, non-dict payload, missing/extra fields, NaN/Infinity and exponent overflow", "Each rejected attempt has its own failed last_receipt and exactly started/finished audit pair; no original secret in evidence; unknown/non-dict input starts no PID.", "Public execute and isolation_audit lifecycle; separate wrapper validation from real-worker JSON content validation.")
    def test_invalid_tasks_and_payloads_have_complete_lifecycle(self):
        executor = self.executor()
        secret = "FAKE_INVALID_INPUT_" + uuid.uuid4().hex; FAKE_SECRETS.append(secret)
        full = {"intent": "query_balance", "params": {}, "records": [], "now": self.clock().isoformat(),
                "daily_total_cents": 0, "target_account_id": "alice-main"}
        cases = [("unlisted_tool", {}, {"invalid_task"}, True),
                 ("parse_candidate", [], {"invalid_input"}, True),
                 ("parse_candidate", {}, {"invalid_input"}, False),
                 ("parse_candidate", {"text": "{}", "extra": secret}, {"invalid_input"}, False),
                 ("parse_candidate", {"text": 1}, {"invalid_input"}, False),
                 ("compute_tool", {key: value for key, value in full.items() if key != "records"}, {"invalid_input"}, False),
                 ("compute_tool", {**full, "extra": secret}, {"invalid_input"}, False),
                 ("compute_tool", {**full, "daily_total_cents": float("nan")}, {"invalid_input"}, False),
                 ("compute_tool", {**full, "daily_total_cents": float("inf")}, {"invalid_input"}, False),
                 ("parse_candidate", {"text": '{"amount":1e9999}'}, {"invalid_input", "invalid_output"}, False),
                 ("parse_candidate", {"text": '{"amount":NaN}'}, {"invalid_input", "invalid_output"}, False)]
        task_ids = set()
        for index, (task, payload, reasons, host_rejection) in enumerate(cases):
            with self.subTest(variant=index):
                request_id = "invalid-case-" + str(index) + "-" + uuid.uuid4().hex
                before = executor.audit_events()
                receipt = self.execute_failure(executor, task, payload, request_id, reasons)
                self.assertNotIn(receipt.get("task_id"), task_ids); task_ids.add(receipt.get("task_id"))
                after = executor.audit_events(); self.assertEqual(after[:len(before)], before)
                current = after[len(before):]
                self.assertEqual([row.get("event") for row in current], ["started", "finished"])
                self.assertTrue(all(row.get("task_id") == receipt["task_id"] for row in current))
                self.assertTrue(all(row.get("request_id") == request_id for row in current))
                self.assertEqual(current[-1].get("status"), "failed"); self.assertEqual(current[-1].get("reason"), receipt["reason"])
                if host_rejection: self.assertIsNone(receipt.get("metadata", {}).get("pid"))
                leaked = secret in json.dumps({"receipt": receipt, "events": current}, ensure_ascii=False)
                self.observe({"variant": index, "lifecycle_event_count": len(current), "fake_secret_leaked": leaked,
                              "host_rejection_expected": host_rejection})
                self.assertFalse(leaked)

    @specification("A preexisting unrelated SQLite file is selected as monitor", "Constructor refuses without replacing schema or content.", "Own unrelated schema, byte fingerprint and table inspection; no business/normal database accessed.")
    def test_unknown_monitor_schema_is_not_overwritten(self):
        database = self.case_directory / "unknown-monitor.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE independent_marker (value TEXT)")
            connection.execute("INSERT INTO independent_marker VALUES ('do-not-overwrite')")
        original = digest(database.read_bytes())
        with self.assertRaises(self.IsolationError): self.Executor(self.runtime, database)
        self.assertEqual(digest(database.read_bytes()), original)
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT value FROM independent_marker").fetchall(), [("do-not-overwrite",)])
        self.observe({"unknown_database_rejected": True, "original_unchanged": True})

    @specification("Two tasks plus attempted SQLite UPDATE/DELETE of monitoring audit", "started/finished persisted per task; old rows unchanged; both mutations rejected.", "Read public isolation_audit table with sqlite3; direct mutation attempts exercise append-only triggers.")
    def test_monitor_append_only_and_task_lifecycle(self):
        executor = self.executor(); self.successful(self.run_probe(executor, "identity"))
        before = executor.audit_events(); self.successful(self.run_probe(executor, "identity")); after = executor.audit_events()
        self.assertEqual(after[:len(before)], before); self.assertGreater(len(after), len(before))
        events = [row.get("event") for row in after]
        self.assertEqual(events.count("started"), 2); self.assertEqual(events.count("finished"), 2)
        with sqlite3.connect(self.case_directory / "monitor.sqlite3") as connection:
            for statement in ("UPDATE isolation_audit SET reason='ATTACK'", "DELETE FROM isolation_audit"):
                with self.assertRaises(sqlite3.DatabaseError): connection.execute(statement)
        self.assertEqual(executor.audit_events(), after)
        self.observe({"old_rows_unchanged": True, "started_count": 2, "finished_count": 2, "update_delete_rejected": True})

    @specification("Host audit_hook raises before started INSERT", "audit_unavailable, no worker starts; later tasks stay halted.", "Injected public audit failure plus independent runtime PID snapshots.")
    def test_audit_failure_before_start_halts(self):
        def fail(event): raise RuntimeError("synthetic audit unavailable")
        executor = self.executor(audit_hook=fail); before = self.windows.runtime_processes(self.runtime)
        task_ids = set()
        for _ in range(2):
            receipt = self.run_probe(executor, "identity"); self.failed(receipt, {"audit_unavailable"})
            self.assertNotIn(receipt.get("task_id"), task_ids); task_ids.add(receipt.get("task_id"))
            self.assertIsNone(receipt.get("metadata", {}).get("pid"))
        self.assertEqual(before, self.windows.runtime_processes(self.runtime))
        self.assertEqual(executor.audit_events(), [])

    @specification("After a real successful probe, started audit INSERT fails, followed by a halted new attempt", "Both new last_receipts are failed/audit_unavailable with fresh task IDs and no PID/data; prior success cannot be reused.", "Mutable public audit_hook fault, real initial probe, audit prefix snapshots and independent process enumeration.")
    def test_started_audit_failure_replaces_prior_success_receipt(self):
        gate = {"fail": False}
        def fail_started(event):
            if gate["fail"] and event.get("event") == "started": raise RuntimeError("synthetic later started failure")
        executor = self.executor(audit_hook=fail_started)
        self.successful(self.run_probe(executor, "ping")); previous = executor.last_receipt
        old_rows = executor.audit_events(); before = self.windows.runtime_processes(self.runtime)
        gate["fail"] = True; task_ids = {previous["task_id"]}
        for _ in range(2):
            receipt = self.run_probe(executor, "ping"); self.failed(receipt, {"audit_unavailable"})
            self.assertNotIn(receipt.get("task_id"), task_ids); task_ids.add(receipt.get("task_id"))
            self.assertIsNone(receipt.get("metadata", {}).get("pid"))
            self.assertEqual(executor.audit_events(), old_rows)
        self.assertEqual(before, self.windows.runtime_processes(self.runtime))
        self.observe({"stale_success_not_reused": True, "new_failed_task_ids": len(task_ids) - 1,
                      "old_audit_unchanged": True, "new_worker_absent": True})

    @specification("Host hook raises on finished INSERT after a real successful worker", "Result withheld, audit_unavailable and halted; reopening appends abandoned without changing old rows.", "Real LPAC execution, failing audit commit, external process exit, independent monitor reopen.")
    def test_finished_audit_failure_and_recovery(self):
        finishing = []
        def fail_finished(event):
            if event.get("event") == "finished":
                finishing.append({"status": event.get("status"), "reason": event.get("reason")})
                raise RuntimeError("synthetic finished audit failure")
        executor = self.executor(audit_hook=fail_finished)
        receipt = self.run_probe(executor, "identity"); self.failed(receipt, {"audit_unavailable"})
        self.observe({"result_before_failed_finished_insert": finishing})
        self.assertEqual(finishing, [{"status": "success", "reason": "ok"}])
        old_rows = executor.audit_events(); self.assertEqual([row.get("event") for row in old_rows], ["started"])
        self.failed(self.run_probe(executor, "identity"), {"audit_unavailable"})
        executor.close(); self.executors.remove(executor)
        reopened = self.executor()
        after = reopened.audit_events(); self.assertEqual(after[:len(old_rows)], old_rows)
        self.assertEqual(after[len(old_rows)].get("event"), "abandoned")
        self.successful(self.run_probe(reopened, "identity"))

    @specification("Second executor attempts the same monitoring database", "Exclusive owner rejects second monitor; close releases lock.", "Public constructor/close; no business database is touched.")
    def test_monitor_exclusive_lock(self):
        first = self.executor()
        with self.assertRaises(self.IsolationError): self.Executor(self.runtime, self.case_directory / "monitor.sqlite3")
        first.close(); self.executors.remove(first)
        self.successful(self.run_probe(self.executor(), "identity"))

    @specification("Kill an ordinary host while its real isolated worker sleeps", "Worker with independently observed user CPU exits after host death; monitor lock releases and new owner appends abandoned.", "Dedicated child host, Toolhelp/image-path PID discovery, GetProcessTimes user CPU, OS terminate/wait and monitor recovery.", "Dedicated runtime must not be shared; positive user CPU proves execution beyond suspended creation, not universal filesystem/network coverage.")
    def test_parent_exit_kills_job_and_recovers(self):
        monitor = self.case_directory / "crashed-monitor.sqlite3"
        ready = self.case_directory / "child-ready.json"
        before = self.windows.runtime_processes(self.runtime)
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child-host", "--runtime-dir", str(self.runtime),
                                  "--child-monitor", str(monitor), "--child-probe", str(self.probe), "--child-ready", str(ready)],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        observed = set()
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and child.poll() is None:
                candidates = self.windows.runtime_processes(self.runtime) - before
                observed = {process_id for process_id in candidates if self.windows.user_cpu_started(process_id)
                            and not self.windows.exited(process_id)}
                if observed: break
                time.sleep(0.03)
            self.observe({"worker_pids_before_parent_kill": sorted(observed), "worker_user_cpu_observed": bool(observed),
                          "parent_ready": ready.exists()})
            self.assertTrue(observed, "Must observe a live runtime worker with actual user CPU before host termination.")
            child.terminate(); child.wait(timeout=3)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not all(self.windows.exited(pid) for pid in observed): time.sleep(0.03)
            self.assertTrue(all(self.windows.exited(pid) for pid in observed))
            with sqlite3.connect(monitor) as connection:
                old = list(connection.execute("SELECT id,timestamp,task_id,request_id,event,status,reason,metadata_json FROM isolation_audit ORDER BY id"))
            self.assertTrue(any(row[4] == "started" for row in old)); self.assertFalse(any(row[4] == "finished" for row in old))
            restored = self.Executor(self.runtime, monitor); self.executors.append(restored)
            with sqlite3.connect(monitor) as connection:
                after = list(connection.execute("SELECT id,timestamp,task_id,request_id,event,status,reason,metadata_json FROM isolation_audit ORDER BY id"))
            self.assertEqual(after[:len(old)], old); self.assertEqual(after[len(old)][4], "abandoned")
            self.successful(self.run_probe(restored, "identity"))
            self.observe({"workers_exited_after_parent_kill": True, "old_rows_unchanged": True, "abandoned_appended": True})
        finally:
            if child.poll() is None: child.terminate(); child.wait(timeout=3)
            if child.stdout: child.stdout.close()
            if child.stderr: child.stderr.close()

    @specification("Normal isolated bill analysis, subscription query/cancel, 10000-cent transfer", "All three directions use real compute_tool tasks; fixed fixture amounts and balances correct; historical bills retained.", "BankService public calls, monitor started counts, independent SQLite balance/history inspection.")
    def test_bank_three_directions_through_real_executor(self):
        executor = self.executor(); service = self.service(executor); database = self.case_directory / "bank.sqlite3"
        before = self.balances(database)
        bill = service.propose({"intent": "analyze_bills", "params": {}})
        self.observe({"stage": "initial_bill", "status": bill.get("status"), "reason": bill.get("reason"),
                      "receipt": receipt_summary(executor.last_receipt) if isinstance(executor.last_receipt, dict) else None})
        self.assertEqual(bill.get("status"), "success"); self.assertEqual(bill.get("data", {}).get("actual_expense_cents"), 5970)
        pending = service.propose({"intent": "query_subscriptions", "params": {}})
        self.assertEqual(pending.get("status"), "pending"); self.assertNotIn("data", pending)
        subscriptions = service.confirm(pending["request_id"], pending["confirmation_code"])
        self.assertEqual(subscriptions.get("status"), "success"); self.assertEqual(subscriptions.get("data", {}).get("future_expected_cents"), 5970)
        pending = service.propose({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}})
        self.assertEqual(pending.get("status"), "pending")
        self.assertEqual(service.confirm(pending["request_id"], pending["confirmation_code"]).get("status"), "success")
        bill_after = service.propose({"intent": "analyze_bills", "params": {}})
        self.assertEqual(bill_after.get("data", {}).get("actual_expense_cents"), 5970)
        pending = service.propose({"intent": "transfer", "params": {"account_id": "alice-main", "contact_id": "wang", "amount_cents": 10000}})
        self.assertEqual(pending.get("tier"), "yellow")
        transferred = service.confirm(pending["request_id"], pending["confirmation_code"])
        self.assertEqual(transferred.get("status"), "success"); self.assertEqual(transferred.get("data", {}).get("amount_cents"), 10000)
        after = self.balances(database)
        self.assertEqual(after, {**before, "alice-main": 990000, "bob-main": 110000})
        events = executor.audit_events(); self.assertGreaterEqual(sum(row.get("event") == "started" for row in events), 5)
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT status FROM subscriptions WHERE subscription_id='sub-video'").fetchone()[0], "cancelled")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0], 1)
        self.observe({"bill_before_cents": 5970, "bill_after_cents": 5970, "balances": after, "actual_started_tasks": sum(row.get("event") == "started" for row in events)})

    @specification("Isolated execution ending audit fails during yellow transfer confirmation", "Bank failed/isolation_failed; balances, transfers and subscription state unchanged; isolation_failed bank audit; no later tool success.", "Real executor with public finished audit fault; independent business SQLite and public bank audit.")
    def test_bank_isolation_failure_does_not_change_accounts(self):
        finishing = []
        def fail_finished(event):
            if event.get("event") == "finished":
                finishing.append({"status": event.get("status"), "reason": event.get("reason")})
                raise RuntimeError("synthetic isolated audit failure")
        executor = self.executor(audit_hook=fail_finished); service = self.service(executor); database = self.case_directory / "bank.sqlite3"
        before = self.balances(database)
        pending = service.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}})
        response = service.confirm(pending["request_id"], pending["confirmation_code"])
        self.observe({"status": response.get("status"), "reason": response.get("reason"), "balances_unchanged": before == self.balances(database),
                      "result_before_failed_finished_insert": finishing})
        self.assertEqual(finishing, [{"status": "success", "reason": "ok"}])
        self.assertEqual(response.get("status"), "failed"); self.assertEqual(response.get("reason"), "isolation_failed")
        self.assertEqual(self.balances(database), before)
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0], 0)
        self.assertTrue(any(row.get("event") == "isolation_failed" for row in service.audit_events()))

    @specification("Host business executed audit fails after real isolated transfer calculation", "audit_unavailable; both simulated balances/transfers roll back; subsequent business stops.", "Bank audit_hook public fault with real LPAC executor and independent table snapshots.")
    def test_bank_business_audit_failure_rolls_back(self):
        def fail_executed(event):
            if event.get("event") == "executed": raise RuntimeError("synthetic bank audit failure")
        executor = self.executor(); service = self.service(executor, audit_hook=fail_executed); database = self.case_directory / "bank.sqlite3"
        before = self.balances(database)
        pending = service.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}})
        response = service.confirm(pending["request_id"], pending["confirmation_code"])
        self.assertEqual(response.get("status"), "failed"); self.assertEqual(response.get("reason"), "audit_unavailable")
        self.assertEqual(self.balances(database), before)
        self.assertEqual(service.propose({"intent": "query_balance", "params": {}}).get("reason"), "audit_unavailable")
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0], 0)
        self.observe({"business_rolled_back": True, "later_business_halted": True})

    @specification("A first isolated plan node fails; dependent subscription and transfer nodes follow", "Plan failed; no later node succeeds or executes; account balances unchanged.", "Real finished-audit failure, public plan contract, independent monitor task count and SQLite state.")
    def test_isolation_failure_stops_dependent_plan(self):
        def fail_finished(event):
            if event.get("event") == "finished": raise RuntimeError("synthetic isolated plan failure")
        executor = self.executor(audit_hook=fail_finished); service = self.service(executor); database = self.case_directory / "bank.sqlite3"
        before = self.balances(database)
        response = service.propose({"steps": [{"id": "bill", "intent": "analyze_bills", "params": {}, "depends_on": []},
                                              {"id": "subs", "intent": "query_subscriptions", "params": {}, "depends_on": ["bill"]},
                                              {"id": "pay", "intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}, "depends_on": ["subs"]}]})
        self.assertEqual(response.get("status"), "failed"); self.assertEqual(self.balances(database), before)
        steps = response.get("plan", {}).get("steps", [])
        self.assertEqual(len(steps), 3); self.assertFalse(any(step.get("status") == "success" for step in steps))
        self.assertEqual(sum(row.get("event") == "started" for row in executor.audit_events()), 1)
        self.observe({"status": response.get("status"), "step_statuses": [step.get("status") for step in steps], "balances_unchanged": True})

    @specification("100001-cent red transfer with a real isolated executor but no registered factors", "rejected/strong_verification_unavailable; no transfer or worker execution; isolation alone cannot authorize red.", "Public BankService fixture, code-tier response, independent SQLite and monitor event counts.")
    def test_red_transfer_stays_refused(self):
        executor = self.executor(); service = self.service(executor); database = self.case_directory / "bank.sqlite3"
        before = self.balances(database)
        response = service.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100001}})
        self.assertEqual(response.get("status"), "rejected"); self.assertEqual(response.get("tier"), "red")
        self.assertEqual(response.get("reason"), "strong_verification_unavailable"); self.assertEqual(self.balances(database), before)
        self.assertFalse(any(row.get("event") == "started" for row in executor.audit_events()))
        self.observe({"red_refused": True, "balances_unchanged": True, "worker_not_invoked": True})


class EvidenceResult(unittest.TextTestResult):
    """Save results without stdout/stderr/exception text that could carry secrets."""
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords); self.case_results = []

    def record(self, test, outcome, exception_type=None, failure_traceback=None):
        name = getattr(test, "_testMethodName", str(test))
        failure_lines = []
        while failure_traceback is not None:
            if Path(failure_traceback.tb_frame.f_code.co_filename).resolve() == Path(__file__).resolve():
                failure_lines.append(failure_traceback.tb_lineno)
            failure_traceback = failure_traceback.tb_next
        self.case_results.append({"name": name, "outcome": outcome, "ran": outcome != "skipped", "exception_type": exception_type,
                                  "test_failure_lines": failure_lines,
                                  **CASE_SPECS.get(name, {}), "actual": OBSERVATIONS.get(name, [])})

    def addSuccess(self, test): super().addSuccess(test); self.record(test, "passed")
    def addFailure(self, test, error): super().addFailure(test, error); self.record(test, "failed", error[0].__name__, error[2])
    def addError(self, test, error): super().addError(test, error); self.record(test, "error", error[0].__name__, error[2])
    def addSkip(self, test, reason): super().addSkip(test, reason); self.record(test, "skipped")
    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error: self.record(test, "subtest_failed", error[0].__name__, error[2])
    def printErrors(self):
        # Do not print standard unittest tracebacks containing untrusted data.
        for entry in self.case_results:
            if entry["outcome"] in {"failed", "error", "subtest_failed"}:
                self.stream.writeln(entry["name"] + ": " + entry["outcome"] + " (" + str(entry["exception_type"]) + ")")


def child_host(arguments):
    from src.isolation import IsolatedExecutor
    executor = IsolatedExecutor(arguments.runtime_dir, arguments.child_monitor)
    Path(arguments.child_ready).write_text(json.dumps({"host_pid": os.getpid(), "constructor_ready": True}), encoding="utf-8")
    executor.run_probe(arguments.child_probe, {"mode": "sleep"}, request_id="independent-parent-exit")


def main():
    global RUNTIME_ARGUMENT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir")
    parser.add_argument("--child-host", action="store_true")
    parser.add_argument("--child-monitor"); parser.add_argument("--child-probe"); parser.add_argument("--child-ready")
    parser.add_argument("--phase", default="initial", help="Label only, never overwrites earlier evidence.")
    arguments = parser.parse_args()
    if arguments.child_host:
        child_host(arguments); return 0
    RUNTIME_ARGUMENT = arguments.runtime_dir
    started = datetime.now(timezone(timedelta(hours=8)))
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(IsolationIndependentTests))
    finished = datetime.now(timezone(timedelta(hours=8)))
    all_passed = result.wasSuccessful() and not result.skipped and result.testsRun == len(CASE_SPECS)
    priority = {"not_run": 0, "passed": 1, "skipped": 2, "subtest_failed": 3, "failed": 4, "error": 5}
    top_level = {name: "not_run" for name in CASE_SPECS}
    for entry in result.case_results:
        name = entry["name"]
        if name in top_level and priority[entry["outcome"]] > priority[top_level[name]]:
            top_level[name] = entry["outcome"]
    summary = {outcome: sum(value == outcome for value in top_level.values()) for outcome in priority}
    evidence = {"author_basis": ["AGENTS.md", "docs/27-isolation-boundary.md", "src/ISOLATION_API.md", "src/PUBLIC_API.md", "docs/01-permission-tiers.md", "docs/02-user-stories.md", "docs/05-audit-log-spec.md"],
                "implementation_sources_read": False, "fake_secrets_only": True, "runtime": str(arguments.runtime_dir) if arguments.runtime_dir else None,
                "test_source_sha256": digest(Path(__file__).read_bytes()),
                "isolation_contract_sha256": digest((ROOT / "src" / "ISOLATION_API.md").read_bytes()),
                "independent_identity_method": "AccessCheck masks 0x10/0x20/0x40; six real worker-token controls",
                "contract_adaptations": ["Explicit dedicated read-only profile", "13 system path environment keys", "Behavioral LPAC proof replaces unsupported Token46", "Wall attack budget 1s to reach real probe; original 0.2s failure retained"],
                "phase": arguments.phase, "started_at": started.isoformat(), "finished_at": finished.isoformat(),
                "run_directory": str(RUN_DIRECTORY) if RUN_DIRECTORY else None,
                "tests_run": result.testsRun, "planned_cases": len(CASE_SPECS), "failures": len(result.failures), "errors": len(result.errors),
                "skipped": len(result.skipped), "top_level_summary": summary, "top_level_outcomes": top_level,
                "all_planned_cases_passed": all_passed, "cases": result.case_results,
                "unverified_boundaries": ["Internet TCP/HTTP", "Internet DNS with positive control", "IPv6 UDP", "disk total quota", "registry", "GUI and every system object", "real-person MFA", "official submission"]}
    destination = ROOT / "evidence" / ("isolation-independent-" + started.strftime("%Y%m%d-%H%M%S-%f") + "-" + uuid.uuid4().hex[:8] + ".json")
    with destination.open("x", encoding="utf-8") as output:
        json.dump(safe_value(evidence), output, ensure_ascii=False, indent=2)
    print("Independent evidence: " + str(destination))
    print("All planned real-OS cases passed: " + str(all_passed))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

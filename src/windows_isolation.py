"""Windows LPAC worker launcher; this module never creates profiles or changes ACLs.

The trusted caller must prepare a dedicated, read-only Python runtime directory.
Win32 calls are made through ctypes, so no third-party package is needed. A failed
security setup is returned as a failure, never retried as an ordinary process.
"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone


DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
PVOID = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t
LARGE_INTEGER = ctypes.c_int64
LPWSTR = ctypes.c_wchar_p

SHANGHAI = timezone(timedelta(hours=8))
JOB_FLAGS = 0x2000 | 0x0008 | 0x0200 | 0x0100 | 0x0004
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_SUPPORTED = 50
ERROR_NOT_ENOUGH_QUOTA = 1816


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", PVOID),
                ("bInheritHandle", BOOL)]


class _Guid(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_text(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", PVOID), ("Attributes", DWORD)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [("AppContainerSid", PVOID), ("Capabilities", PVOID),
                ("CapabilityCount", DWORD), ("Reserved", DWORD)]


class _GenericMapping(ctypes.Structure):
    _fields_ = [(name, DWORD) for name in
                ("GenericRead", "GenericWrite", "GenericExecute", "GenericAll")]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD), ("lpReserved", LPWSTR), ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR), ("dwX", DWORD), ("dwY", DWORD),
        ("dwXSize", DWORD), ("dwYSize", DWORD), ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD), ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD), ("wShowWindow", WORD), ("cbReserved2", WORD),
        ("lpReserved2", PVOID), ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE), ("hStdError", HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", PVOID)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE),
                ("dwProcessId", DWORD), ("dwThreadId", DWORD)]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", LARGE_INTEGER),
        ("PerJobUserTimeLimit", LARGE_INTEGER), ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T), ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD), ("Affinity", ULONG_PTR),
        ("PriorityClass", DWORD), ("SchedulingClass", DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", SIZE_T), ("JobMemoryLimit", SIZE_T),
                ("PeakProcessMemoryUsed", SIZE_T), ("PeakJobMemoryUsed", SIZE_T)]


class _CpuRate(ctypes.Structure):
    _fields_ = [("ControlFlags", DWORD), ("CpuRate", DWORD)]


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", LARGE_INTEGER), ("TotalKernelTime", LARGE_INTEGER),
                ("ThisPeriodTotalUserTime", LARGE_INTEGER),
                ("ThisPeriodTotalKernelTime", LARGE_INTEGER),
                ("TotalPageFaultCount", DWORD), ("TotalProcesses", DWORD),
                ("ActiveProcesses", DWORD), ("TotalTerminatedProcesses", DWORD)]


class _CompletionAssociation(ctypes.Structure):
    _fields_ = [("CompletionKey", PVOID), ("CompletionPort", HANDLE)]


class _ApiFailure(Exception):
    """Carries a numeric OS error only; never includes input or a command line."""

    def __init__(self, number: int):
        self.number = int(number)
        super().__init__(self.number)


class _WinApi:
    """Typed Win32 declarations. Construction only loads system DLLs."""

    def __init__(self):
        if os.name != "nt":
            raise _ApiFailure(ERROR_NOT_SUPPORTED)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)
        self.firewall = ctypes.WinDLL("FirewallAPI", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.ole = ctypes.WinDLL("ole32", use_last_error=True)
        declarations = {
            "CloseHandle": (BOOL, [HANDLE]),
            "CreateJobObjectW": (HANDLE, [PVOID, LPWSTR]),
            "SetInformationJobObject": (BOOL, [HANDLE, ctypes.c_int, PVOID, DWORD]),
            "QueryInformationJobObject": (BOOL, [HANDLE, ctypes.c_int, PVOID, DWORD, PVOID]),
            "IsProcessInJob": (BOOL, [HANDLE, HANDLE, ctypes.POINTER(BOOL)]),
            "TerminateJobObject": (BOOL, [HANDLE, DWORD]),
            "TerminateProcess": (BOOL, [HANDLE, DWORD]),
            "CreatePipe": (BOOL, [ctypes.POINTER(HANDLE), ctypes.POINTER(HANDLE), PVOID, DWORD]),
            "SetHandleInformation": (BOOL, [HANDLE, DWORD, DWORD]),
            "ReadFile": (BOOL, [HANDLE, PVOID, DWORD, ctypes.POINTER(DWORD), PVOID]),
            "WriteFile": (BOOL, [HANDLE, PVOID, DWORD, ctypes.POINTER(DWORD), PVOID]),
            "InitializeProcThreadAttributeList": (BOOL, [PVOID, DWORD, DWORD, ctypes.POINTER(SIZE_T)]),
            "UpdateProcThreadAttribute": (BOOL, [PVOID, DWORD, SIZE_T, PVOID, SIZE_T, PVOID, PVOID]),
            "DeleteProcThreadAttributeList": (None, [PVOID]),
            "CreateProcessW": (BOOL, [LPWSTR, PVOID, PVOID, PVOID, BOOL, DWORD,
                                       PVOID, LPWSTR, PVOID, ctypes.POINTER(_ProcessInformation)]),
            "ResumeThread": (DWORD, [HANDLE]),
            "WaitForSingleObject": (DWORD, [HANDLE, DWORD]),
            "GetExitCodeProcess": (BOOL, [HANDLE, ctypes.POINTER(DWORD)]),
            "GetProcessMitigationPolicy": (BOOL, [HANDLE, ctypes.c_int, PVOID, SIZE_T]),
            "GetWindowsDirectoryW": (DWORD, [PVOID, DWORD]),
            "GetCurrentProcess": (HANDLE, []),
            "GetProcessHeap": (HANDLE, []),
            "HeapFree": (BOOL, [HANDLE, DWORD, PVOID]),
            "LocalFree": (PVOID, [PVOID]),
            "CreateIoCompletionPort": (HANDLE, [HANDLE, HANDLE, ULONG_PTR, DWORD]),
            "GetQueuedCompletionStatus": (BOOL, [HANDLE, ctypes.POINTER(DWORD),
                                                  ctypes.POINTER(ULONG_PTR), ctypes.POINTER(PVOID), DWORD]),
            "OpenThread": (HANDLE, [DWORD, BOOL, DWORD]),
            "CancelSynchronousIo": (BOOL, [HANDLE]),
        }
        for name, (restype, argtypes) in declarations.items():
            self._declare(self.kernel, name, restype, argtypes)
        for name, restype, argtypes in (
            ("OpenProcessToken", BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]),
            ("GetTokenInformation", BOOL, [HANDLE, ctypes.c_int, PVOID, DWORD, ctypes.POINTER(DWORD)]),
            ("DuplicateToken", BOOL, [HANDLE, ctypes.c_int, ctypes.POINTER(HANDLE)]),
            ("AccessCheck", BOOL, [PVOID, HANDLE, DWORD, ctypes.POINTER(_GenericMapping),
                                   PVOID, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD),
                                   ctypes.POINTER(BOOL)]),
            ("ConvertStringSecurityDescriptorToSecurityDescriptorW", BOOL,
             [LPWSTR, DWORD, ctypes.POINTER(PVOID), ctypes.POINTER(DWORD)]),
            ("FreeSid", PVOID, [PVOID]),
            ("ConvertSidToStringSidW", BOOL, [PVOID, ctypes.POINTER(LPWSTR)]),
            ("EqualSid", BOOL, [PVOID, PVOID]),
            ("GetSidSubAuthorityCount", ctypes.POINTER(ctypes.c_ubyte), [PVOID]),
            ("GetSidSubAuthority", ctypes.POINTER(DWORD), [PVOID, DWORD]),
        ):
            self._declare(self.advapi, name, restype, argtypes)
        self._declare(self.userenv, "DeriveAppContainerSidFromAppContainerName",
                      ctypes.c_int32, [LPWSTR, ctypes.POINTER(PVOID)])
        self._declare(self.userenv, "GetAppContainerFolderPath",
                      ctypes.c_int32, [LPWSTR, ctypes.POINTER(LPWSTR)])
        self._declare(self.userenv, "GetUserProfileDirectoryW", BOOL,
                      [HANDLE, PVOID, ctypes.POINTER(DWORD)])
        self._declare(self.shell, "SHGetKnownFolderPath", ctypes.c_int32,
                      [ctypes.POINTER(_Guid), DWORD, HANDLE, ctypes.POINTER(LPWSTR)])
        self._declare(self.ole, "CoTaskMemFree", None, [PVOID])
        self._declare(self.firewall, "NetworkIsolationGetAppContainerConfig", DWORD,
                      [ctypes.POINTER(DWORD), ctypes.POINTER(ctypes.POINTER(_SidAndAttributes))])

    def _declare(self, library, name, restype, argtypes):
        function = getattr(library, name)
        function.restype = restype
        function.argtypes = argtypes
        setattr(self, name, function)

    @staticmethod
    def require(result):
        if not result:
            raise _ApiFailure(ctypes.get_last_error())
        return result

    def derive_sid(self, package_name):
        _validate_package_name(package_name)
        sid = PVOID()
        result = self.DeriveAppContainerSidFromAppContainerName(package_name, ctypes.byref(sid))
        if result < 0 or not sid.value:
            raise _ApiFailure(result & 0xFFFFFFFF)
        return sid

    def sid_string(self, sid):
        value = LPWSTR()
        self.require(self.ConvertSidToStringSidW(sid, ctypes.byref(value)))
        try:
            return value.value
        finally:
            self.LocalFree(ctypes.cast(value, PVOID))

    def loopback_exempt(self, sid):
        count = DWORD()
        entries = ctypes.POINTER(_SidAndAttributes)()
        result = self.NetworkIsolationGetAppContainerConfig(ctypes.byref(count), ctypes.byref(entries))
        if result != 0:
            raise _ApiFailure(result)
        try:
            return any(self.EqualSid(sid, entries[index].Sid) for index in range(count.value))
        finally:
            heap = self.GetProcessHeap()
            for index in range(count.value):
                self.HeapFree(heap, 0, entries[index].Sid)
            if entries:
                self.HeapFree(heap, 0, ctypes.cast(entries, PVOID))

    def token_info(self, token, information_class):
        length = DWORD()
        self.GetTokenInformation(token, information_class, None, 0, ctypes.byref(length))
        if not length.value or length.value > 1024 * 1024:
            raise _ApiFailure(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(length.value)
        self.require(self.GetTokenInformation(token, information_class, buffer,
                                             length.value, ctypes.byref(length)))
        return buffer

    def query_job(self, job, information_class, structure):
        value = structure()
        self.require(self.QueryInformationJobObject(job, information_class, ctypes.byref(value),
                                                   ctypes.sizeof(value), None))
        return value

    def verify_lpac(self, token, metadata):
        """Verify the suspended token's AAP opt-out through six real access checks.

        Microsoft defines LPAC as AppContainer access that disregards the
        ALL_APPLICATION_PACKAGES SID. Class 46 is unavailable on some builds;
        unsupported is recorded, never interpreted as a successful identity
        check. AccessCheck, using an impersonation duplicate, checks the actual
        token against private in-memory descriptors. Every positive/negative
        control must match before the token is accepted as LPAC.

        Sources: TOKEN_INFORMATION_CLASS, AccessCheck and DuplicateToken in
        Microsoft Learn. This is a composition of those documented primitives,
        not a claimed dedicated Microsoft IsLPAC API or a creation-flag check.
        """
        direct_lpac = None
        try:
            direct_lpac = int(DWORD.from_buffer(self.token_info(token, 46)).value)
            metadata["lpac_class46_value"] = direct_lpac
        except _ApiFailure as error:
            metadata["lpac_class46_error"] = error.number
            if error.number not in (ERROR_INVALID_PARAMETER, ERROR_NOT_SUPPORTED):
                raise
        metadata["lpac_verification_method"] = "accesscheck_aap_optout_v1"
        checks = {}
        metadata["lpac_access_checks"] = checks
        # Also reject an identification-level impersonation source explicitly.
        if int(DWORD.from_buffer(self.token_info(token, 8)).value) != 1:
            return False
        package_buffer = self.token_info(token, 31)
        package_sid = self.sid_string(PVOID.from_buffer(package_buffer).value)
        duplicate = HANDLE()
        self.require(self.DuplicateToken(token, 2, ctypes.byref(duplicate)))
        try:
            descriptors = {
                "everyone_only": ("O:SYG:SYD:(A;;0x3;;;WD)", False, 0),
                "package_positive": (
                    f"O:SYG:SYD:(A;;0x3;;;WD)(A;;0x3;;;{package_sid})", True, 3),
                "aap_only": ("O:SYG:SYD:(A;;0x3;;;WD)(A;;0x1;;;S-1-15-2-1)", False, 0),
                "restricted_package_only": (
                    "O:SYG:SYD:(A;;0x3;;;WD)(A;;0x2;;;S-1-15-2-2)", True, 2),
                "distinct_package_bits": (
                    "O:SYG:SYD:(A;;0x3;;;WD)(A;;0x1;;;S-1-15-2-1)"
                    "(A;;0x2;;;S-1-15-2-2)", True, 2),
                "empty_dacl": ("O:SYG:SYD:", False, 0),
            }
            matches = []
            for name, (descriptor_text, expected_allowed, expected_granted) in descriptors.items():
                descriptor = PVOID()
                descriptor_size = DWORD()
                try:
                    self.require(self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                        descriptor_text, 1, ctypes.byref(descriptor), ctypes.byref(descriptor_size)))
                    privileges = ctypes.create_string_buffer(4096)
                    privilege_size = DWORD(len(privileges))
                    granted = DWORD()
                    allowed = BOOL()
                    mapping = _GenericMapping(1, 2, 0, 3)
                    ctypes.set_last_error(0)
                    api_ok = self.AccessCheck(descriptor, duplicate, 0x02000000,
                                              ctypes.byref(mapping), privileges,
                                              ctypes.byref(privilege_size), ctypes.byref(granted),
                                              ctypes.byref(allowed))
                    error_number = ctypes.get_last_error()
                    checks[name] = {"api_ok": bool(api_ok), "allowed": bool(allowed.value),
                                    "granted": int(granted.value), "error": int(error_number)}
                    if not api_ok:
                        raise _ApiFailure(error_number or ERROR_INVALID_PARAMETER)
                    matches.append(bool(allowed.value) == expected_allowed and
                                   granted.value == expected_granted)
                finally:
                    if descriptor:
                        self.LocalFree(descriptor)
            return direct_lpac in (None, 1) and all(matches)
        finally:
            self.CloseHandle(duplicate)

    def known_folder(self, identifier):
        """Read one known path without inspecting user environment variables."""
        folder = LPWSTR()
        guid = _Guid.from_text(identifier)
        # DONT_VERIFY avoids filesystem changes or attempts to create a missing folder.
        result = self.SHGetKnownFolderPath(ctypes.byref(guid), 0x4000, None,
                                          ctypes.byref(folder))
        if result < 0 or not folder.value:
            raise _ApiFailure(result & 0xFFFFFFFF)
        try:
            return folder.value
        finally:
            self.CoTaskMemFree(ctypes.cast(folder, PVOID))

    def explicit_environment(self, runtime):
        """Build a fixed path-only environment, not a copy of the broker's environment.

        Windows' AppContainer startup expands user-profile path variables. These
        paths are obtained from token/known-folder APIs; model API keys, proxy
        credentials, user-defined variables and the broker's PATH are never read.
        Supplying a path grants no file permission: LPAC ACL checks still apply.
        """
        windows_directory = ctypes.create_unicode_buffer(32768)
        length = self.GetWindowsDirectoryW(windows_directory, len(windows_directory))
        if not length or length >= len(windows_directory):
            raise _ApiFailure(ctypes.get_last_error())
        token = HANDLE()
        self.require(self.OpenProcessToken(self.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)))
        try:
            profile_length = DWORD(32768)
            profile_directory = ctypes.create_unicode_buffer(profile_length.value)
            self.require(self.GetUserProfileDirectoryW(token, profile_directory,
                                                       ctypes.byref(profile_length)))
            user_profile = profile_directory.value
        finally:
            self.CloseHandle(token)
        environment = {
            "SystemRoot": windows_directory.value,
            "windir": windows_directory.value,
            "SystemDrive": Path(windows_directory.value).drive,
            "USERPROFILE": user_profile,
            "HOMEDRIVE": Path(user_profile).drive,
            "HOMEPATH": str(Path(user_profile)).removeprefix(Path(user_profile).drive),
            "LOCALAPPDATA": self.known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091"),
            "APPDATA": self.known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D"),
            "ProgramData": self.known_folder("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97"),
            "PUBLIC": self.known_folder("DFDF76A2-C82A-4D63-906A-5644AC457385"),
            "TEMP": str(runtime), "TMP": str(runtime), "PYTHONHOME": str(runtime),
        }
        if any(not value or "\0" in value for value in environment.values()):
            raise _ApiFailure(ERROR_INVALID_PARAMETER)
        return environment


def _validate_package_name(package_name):
    if not isinstance(package_name, str) or not re.fullmatch(r"[-_. A-Za-z0-9]{1,64}", package_name):
        raise _ApiFailure(ERROR_INVALID_PARAMETER)


def derive_sid_string(package_name: str) -> str:
    """Derive a SID only. This does not create a profile, folder, ACL, or process."""
    try:
        api = _WinApi()
        sid = api.derive_sid(package_name)
        try:
            return api.sid_string(sid)
        finally:
            api.FreeSid(sid)
    except _ApiFailure as error:
        raise OSError(error.number, "Windows isolation API failed") from None
    except (OSError, AttributeError) as error:
        raise OSError(getattr(error, "winerror", None) or ERROR_NOT_SUPPORTED,
                      "Windows isolation API failed") from None


def query_profile_folder(package_name: str) -> str | None:
    """Read the OS-reported profile location, without creating or changing it."""
    sid_text = derive_sid_string(package_name)
    api = _WinApi()
    folder = LPWSTR()
    result = api.GetAppContainerFolderPath(sid_text, ctypes.byref(folder))
    if result < 0:
        return None
    try:
        return folder.value
    finally:
        if folder:
            # Userenv allocates this string using CoTaskMemAlloc.
            ole = ctypes.WinDLL("ole32")
            ole.CoTaskMemFree.argtypes = [PVOID]
            ole.CoTaskMemFree.restype = None
            ole.CoTaskMemFree(ctypes.cast(folder, PVOID))


class _PipeHandle:
    """A pipe endpoint with a single close operation across reader/writer threads."""

    def __init__(self, api, value):
        self.api = api
        self.value = value
        self.lock = threading.Lock()

    def close(self):
        with self.lock:
            if self.value:
                self.api.CloseHandle(self.value)
                self.value = None


class _Capture:
    def __init__(self, maximum_bytes):
        self.maximum_bytes = maximum_bytes
        self.total_bytes = 0
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.lock = threading.Lock()
        self.overflow = threading.Event()
        self.io_error = threading.Event()
        self.io_error_number = None

    def add(self, stream_name, data):
        with self.lock:
            available = max(0, self.maximum_bytes - self.total_bytes)
            getattr(self, stream_name).extend(data[:available])
            self.total_bytes += len(data)
            if self.total_bytes >= self.maximum_bytes:
                self.overflow.set()

    def fail(self, error_number):
        with self.lock:
            self.io_error_number = int(error_number)
            self.io_error.set()


def _read_pipe(api, endpoint, stream_name, capture):
    try:
        buffer = ctypes.create_string_buffer(4096)
        while True:
            count = DWORD()
            if not api.ReadFile(endpoint.value, buffer, len(buffer), ctypes.byref(count), None):
                number = ctypes.get_last_error()
                if number not in (109, 232, 995):  # EOF, no-data, cancelled synchronous IO
                    capture.fail(number)
                break
            if count.value == 0:
                break
            capture.add(stream_name, buffer.raw[:count.value])
    except Exception:
        capture.fail(ERROR_INVALID_PARAMETER)
    finally:
        endpoint.close()


def _write_pipe(api, endpoint, input_bytes, capture):
    try:
        position = 0
        while position < len(input_bytes):
            chunk = input_bytes[position:position + 4096]
            buffer = ctypes.create_string_buffer(chunk)
            count = DWORD()
            if not api.WriteFile(endpoint.value, buffer, len(chunk), ctypes.byref(count), None):
                number = ctypes.get_last_error()
                if number not in (109, 232, 995):
                    capture.fail(number)
                break
            if count.value == 0:
                capture.fail(ERROR_INVALID_PARAMETER)
                break
            position += count.value
    except Exception:
        capture.fail(ERROR_INVALID_PARAMETER)
    finally:
        endpoint.close()


def _now_shanghai():
    return datetime.now(SHANGHAI).isoformat(timespec="milliseconds")


def _checked_limits(limits):
    defaults = {"wall_seconds": 5.0, "cpu_seconds": 1.0, "cpu_rate_percent": 20,
                "memory_bytes": 134217728, "output_bytes": 65536, "process_count": 1}
    if not isinstance(limits, dict) or set(limits) - set(defaults):
        raise _ApiFailure(ERROR_INVALID_PARAMETER)
    values = defaults | limits
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _ApiFailure(ERROR_INVALID_PARAMETER)
        if value <= 0:
            raise _ApiFailure(ERROR_INVALID_PARAMETER)
    minimums = {"wall_seconds": 0.2, "cpu_seconds": 0.1, "cpu_rate_percent": 1,
                "memory_bytes": 33554432, "output_bytes": 1024, "process_count": 1}
    if any(values[key] < minimums[key] or values[key] > defaults[key] for key in values):
        raise _ApiFailure(ERROR_INVALID_PARAMETER)
    for key in ("memory_bytes", "output_bytes", "process_count"):
        if values[key] != int(values[key]) or values[key] > 0x7FFFFFFF:
            raise _ApiFailure(ERROR_INVALID_PARAMETER)
        values[key] = int(values[key])
    return values


class WindowsBackend:
    """Launch only a prepared runtime's script inside a verified Windows LPAC."""

    def __init__(self, runtime_directory: Path, package_name: str):
        self.runtime_directory = Path(runtime_directory)
        self.package_name = package_name

    def run(self, script_path: Path, input_bytes: bytes, limits: dict,
            cancel_event=None) -> dict:
        metadata = {
            "pid": None, "is_appcontainer": None, "is_lpac": None,
            "capability_count": None, "integrity": None, "job_limit_flags": None,
            "child_restricted": None, "start": _now_shanghai(), "end": None,
            "wall_ms": 0, "cpu_ms": None, "peak_job_memory_bytes": None,
            "active_processes_after": None, "termination": "not_started",
            "loopback_exempt": None, "job_events": [],
            "startup_stage": "validating_input", "cleanup_complete": True,
        }
        started_at = time.monotonic()
        result = {"status": "failed", "reason": "isolation_unavailable", "stdout": b"",
                  "stderr": b"", "exit_code": None, "metadata": metadata}
        api = None
        sid = None
        job = completion = token = None
        process = _ProcessInformation()
        attribute_buffer = None
        attribute_initialized = False
        child_handles = []
        endpoints = []
        threads = []
        capture = None
        resumed = False
        job_assigned = False
        security_verified = False
        cleanup_deadline = None

        def cleanup_remaining():
            return max(0.0, cleanup_deadline - time.monotonic())

        def cleanup_wait_milliseconds():
            # Every wait and join consumes the same two-second cleanup budget.
            return max(0, int(cleanup_remaining() * 1000))
        try:
            values = _checked_limits(limits)
            if not isinstance(input_bytes, bytes) or len(input_bytes) > 65536:
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            if cancel_event is not None and cancel_event.is_set():
                result.update(status="cancelled", reason="cancelled")
                metadata["termination"] = "cancelled_before_start"
                return result
            runtime = self.runtime_directory.resolve(strict=True)
            script = Path(script_path).resolve(strict=True)
            interpreter = (runtime / "python.exe").resolve(strict=True)
            if (not runtime.is_dir() or not script.is_file() or
                    not script.is_relative_to(runtime) or not interpreter.is_relative_to(runtime)):
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            api = _WinApi()
            metadata["startup_stage"] = "checking_network_policy"
            sid = api.derive_sid(self.package_name)
            metadata["loopback_exempt"] = api.loopback_exempt(sid)
            if metadata["loopback_exempt"]:
                raise _ApiFailure(ERROR_INVALID_PARAMETER)

            metadata["startup_stage"] = "configuring_job"
            job = api.require(api.CreateJobObjectW(None, None))
            job_limit = _ExtendedLimit()
            job_limit.BasicLimitInformation.LimitFlags = JOB_FLAGS
            job_limit.BasicLimitInformation.ActiveProcessLimit = 1
            job_limit.BasicLimitInformation.PerJobUserTimeLimit = int(values["cpu_seconds"] * 10000000)
            job_limit.ProcessMemoryLimit = values["memory_bytes"]
            job_limit.JobMemoryLimit = values["memory_bytes"]
            api.require(api.SetInformationJobObject(job, 9, ctypes.byref(job_limit), ctypes.sizeof(job_limit)))
            cpu_rate = _CpuRate(0x1 | 0x4, max(1, round(values["cpu_rate_percent"] * 100)))
            api.require(api.SetInformationJobObject(job, 15, ctypes.byref(cpu_rate), ctypes.sizeof(cpu_rate)))
            completion = api.require(api.CreateIoCompletionPort(HANDLE(-1), None, 0, 1))
            association = _CompletionAssociation(PVOID(1), completion)
            api.require(api.SetInformationJobObject(job, 7, ctypes.byref(association), ctypes.sizeof(association)))

            def make_pipe(parent_reads):
                read_handle, write_handle = HANDLE(), HANDLE()
                attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
                api.require(api.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle),
                                          ctypes.byref(attributes), 4096))
                parent = read_handle.value if parent_reads else write_handle.value
                child = write_handle.value if parent_reads else read_handle.value
                endpoint = _PipeHandle(api, parent)
                endpoints.append(endpoint)
                child_handles.append(child)
                api.require(api.SetHandleInformation(parent, 0x1, 0))
                return endpoint, child

            metadata["startup_stage"] = "configuring_process_attributes"
            stdin_endpoint, child_stdin = make_pipe(False)
            stdout_endpoint, child_stdout = make_pipe(True)
            stderr_endpoint, child_stderr = make_pipe(True)
            attribute_length = SIZE_T()
            api.InitializeProcThreadAttributeList(None, 6, 0, ctypes.byref(attribute_length))
            if ctypes.get_last_error() != 122 or not attribute_length.value:
                raise _ApiFailure(ctypes.get_last_error())
            attribute_buffer = ctypes.create_string_buffer(attribute_length.value)
            api.require(api.InitializeProcThreadAttributeList(attribute_buffer, 6, 0,
                                                             ctypes.byref(attribute_length)))
            attribute_initialized = True
            capabilities = _SecurityCapabilities(sid, None, 0, 0)
            lpac_policy = DWORD(1)
            child_policy = DWORD(1)
            mitigation_policy = ctypes.c_uint64(1 << 28)  # Deny Win32k calls for this headless worker.
            inherited_handles = (HANDLE * 3)(child_stdin, child_stdout, child_stderr)
            job_handles = (HANDLE * 1)(job)
            for attribute, value in (
                (0x00020009, capabilities), (0x0002000E, child_policy),
                (0x0002000F, lpac_policy), (0x00020007, mitigation_policy),
                (0x00020002, inherited_handles), (0x0002000D, job_handles),
            ):
                api.require(api.UpdateProcThreadAttribute(attribute_buffer, 0, attribute,
                                                         ctypes.byref(value), ctypes.sizeof(value), None, None))
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = child_stdin
            startup.StartupInfo.hStdOutput = child_stdout
            startup.StartupInfo.hStdError = child_stderr
            startup.lpAttributeList = ctypes.cast(attribute_buffer, PVOID)
            metadata["startup_stage"] = "constructing_explicit_environment"
            environment = api.explicit_environment(runtime)
            metadata["environment_keys"] = sorted(environment)
            environment_buffer = ctypes.create_unicode_buffer(
                "\0".join(f"{name}={value}" for name, value in sorted(environment.items(),
                                                                     key=lambda item: item[0].upper())) + "\0\0")
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([str(interpreter), "-I", "-S", "-B", str(script)]))
            result["reason"] = "start_failed"
            metadata["startup_stage"] = "creating_suspended_process"
            api.require(api.CreateProcessW(str(interpreter), command_line, None, None, True,
                                          0x00080000 | 0x00000004 | 0x00000400 | 0x08000000,
                                          environment_buffer, str(runtime), ctypes.byref(startup),
                                          ctypes.byref(process)))
            result["reason"] = "isolation_unavailable"
            metadata["pid"] = int(process.dwProcessId)
            metadata["cleanup_complete"] = False
            metadata["termination"] = "suspended"
            for handle in child_handles:
                api.CloseHandle(handle)
            child_handles.clear()
            metadata["startup_stage"] = "verifying_job_membership"
            in_job = BOOL()
            api.require(api.IsProcessInJob(process.hProcess, job, ctypes.byref(in_job)))
            job_assigned = bool(in_job.value)
            if not job_assigned:
                result["reason"] = "identity_mismatch"
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            token = HANDLE()
            metadata["startup_stage"] = "verifying_appcontainer_token"
            api.require(api.OpenProcessToken(process.hProcess, TOKEN_QUERY | TOKEN_DUPLICATE,
                                            ctypes.byref(token)))
            metadata["is_appcontainer"] = bool(DWORD.from_buffer(api.token_info(token, 29)).value)
            metadata["startup_stage"] = "verifying_lpac_token"
            metadata["is_lpac"] = api.verify_lpac(token, metadata)
            metadata["startup_stage"] = "verifying_remaining_token_properties"
            metadata["capability_count"] = int(DWORD.from_buffer(api.token_info(token, 30)).value)
            appcontainer_sid_buffer = api.token_info(token, 31)
            token_sid = PVOID.from_buffer(appcontainer_sid_buffer).value
            sid_matches = bool(api.EqualSid(sid, token_sid))
            integrity_buffer = api.token_info(token, 25)
            integrity_sid = _SidAndAttributes.from_buffer(integrity_buffer).Sid
            authority_count = api.GetSidSubAuthorityCount(integrity_sid).contents.value
            if not authority_count:
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            integrity_level = api.GetSidSubAuthority(integrity_sid, authority_count - 1).contents.value
            metadata["integrity"] = int(integrity_level)
            policy_flags = DWORD()
            metadata["startup_stage"] = "verifying_process_mitigations"
            api.require(api.GetProcessMitigationPolicy(process.hProcess, 13, ctypes.byref(policy_flags),
                                                      ctypes.sizeof(policy_flags)))
            metadata["child_restricted"] = bool(policy_flags.value & 1)
            metadata["child_process_policy_flags"] = int(policy_flags.value)
            system_call_policy = DWORD()
            api.require(api.GetProcessMitigationPolicy(process.hProcess, 4,
                                                      ctypes.byref(system_call_policy), ctypes.sizeof(system_call_policy)))
            metadata["win32k_disabled"] = bool(system_call_policy.value & 1)
            metadata["system_call_disable_policy_flags"] = int(system_call_policy.value)
            metadata["startup_stage"] = "verifying_job_limits"
            actual_limit = api.query_job(job, 9, _ExtendedLimit)
            actual_rate = api.query_job(job, 15, _CpuRate)
            metadata["job_limit_flags"] = int(actual_limit.BasicLimitInformation.LimitFlags)
            metadata["job_active_process_limit"] = int(actual_limit.BasicLimitInformation.ActiveProcessLimit)
            metadata["job_process_memory_limit_bytes"] = int(actual_limit.ProcessMemoryLimit)
            metadata["job_memory_limit_bytes"] = int(actual_limit.JobMemoryLimit)
            metadata["job_cpu_user_time_limit_ms"] = (
                actual_limit.BasicLimitInformation.PerJobUserTimeLimit / 10000)
            metadata["job_cpu_rate_control_flags"] = int(actual_rate.ControlFlags)
            metadata["job_cpu_rate"] = int(actual_rate.CpuRate)
            metadata["appcontainer_sid_matches"] = sid_matches
            if not (metadata["is_appcontainer"] and metadata["is_lpac"] and
                    metadata["capability_count"] == 0 and sid_matches and integrity_level <= 0x1000 and
                    metadata["child_restricted"] and metadata["win32k_disabled"] and
                    actual_limit.BasicLimitInformation.LimitFlags == JOB_FLAGS and
                    actual_limit.BasicLimitInformation.ActiveProcessLimit == 1 and
                    actual_limit.ProcessMemoryLimit == values["memory_bytes"] and
                    actual_limit.JobMemoryLimit == values["memory_bytes"] and
                    actual_limit.BasicLimitInformation.PerJobUserTimeLimit ==
                    job_limit.BasicLimitInformation.PerJobUserTimeLimit and
                    actual_rate.ControlFlags == cpu_rate.ControlFlags and actual_rate.CpuRate == cpu_rate.CpuRate):
                result["reason"] = "identity_mismatch"
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            security_verified = True
            api.CloseHandle(token)
            token = None
            capture = _Capture(values["output_bytes"])
            worker_threads = [
                threading.Thread(target=_read_pipe, args=(api, stdout_endpoint, "stdout", capture), daemon=True),
                threading.Thread(target=_read_pipe, args=(api, stderr_endpoint, "stderr", capture), daemon=True),
                threading.Thread(target=_write_pipe, args=(api, stdin_endpoint, input_bytes, capture), daemon=True),
            ]
            for thread in worker_threads:
                thread.start()
                threads.append(thread)
            metadata["startup_stage"] = "resuming_verified_process"
            if api.ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise _ApiFailure(ctypes.get_last_error())
            resumed = True
            metadata["termination"] = "running"
            metadata["startup_stage"] = "running"
            run_started = time.monotonic()
            stop_reason = None
            while True:
                events = self._drain_events(api, completion)
                metadata["job_events"].extend(events)
                accounting = api.query_job(job, 1, _Accounting)
                if cancel_event is not None and cancel_event.is_set():
                    stop_reason = "cancelled"
                elif capture.overflow.is_set():
                    stop_reason = "output_limit"
                elif capture.io_error.is_set():
                    stop_reason = "isolation_unavailable"
                    metadata["win32_error"] = capture.io_error_number
                elif 9 in events or 10 in events:
                    stop_reason = "memory_limit"
                elif 1 in events or accounting.TotalUserTime >= job_limit.BasicLimitInformation.PerJobUserTimeLimit:
                    stop_reason = "cpu_limit"
                elif time.monotonic() - run_started >= values["wall_seconds"]:
                    stop_reason = "timeout"
                wait_result = api.WaitForSingleObject(process.hProcess, 0)
                if wait_result == WAIT_FAILED:
                    raise _ApiFailure(ctypes.get_last_error())
                if stop_reason is not None:
                    cleanup_deadline = time.monotonic() + 2.0
                    api.require(api.TerminateJobObject(job, ERROR_NOT_ENOUGH_QUOTA))
                    metadata["termination"] = "job_terminated"
                    if api.WaitForSingleObject(process.hProcess, cleanup_wait_milliseconds()) != WAIT_OBJECT_0:
                        raise _ApiFailure(ctypes.get_last_error() or WAIT_TIMEOUT)
                    break
                if wait_result == WAIT_OBJECT_0:
                    cleanup_deadline = time.monotonic() + 2.0
                    metadata["termination"] = "exited"
                    break
                time.sleep(0.02)
            exit_code = DWORD()
            api.require(api.GetExitCodeProcess(process.hProcess, ctypes.byref(exit_code)))
            result["exit_code"] = int(exit_code.value)
            metadata["process_exit_confirmed"] = True
            # Retain the handle until its exit code is captured, then release all process references.
            api.CloseHandle(process.hThread)
            process.hThread = None
            api.CloseHandle(process.hProcess)
            process.hProcess = None
            for thread in threads:
                thread.join(cleanup_remaining())
            final_events = self._drain_events(api, completion)
            metadata["job_events"].extend(final_events)
            if stop_reason is None and capture.overflow.is_set():
                stop_reason = "output_limit"
            elif stop_reason is None and any(event in (9, 10) for event in final_events):
                stop_reason = "memory_limit"
            final_accounting = api.query_job(job, 1, _Accounting)
            if (stop_reason is None and final_accounting.TotalUserTime >=
                    job_limit.BasicLimitInformation.PerJobUserTimeLimit):
                stop_reason = "cpu_limit"
            self._record_job(api, job, metadata)
            if metadata["active_processes_after"] != 0 or any(thread.is_alive() for thread in threads):
                raise _ApiFailure(ERROR_INVALID_PARAMETER)
            if stop_reason == "cancelled":
                result.update(status="cancelled", reason="cancelled")
            elif stop_reason is not None:
                result["reason"] = stop_reason
            elif capture.io_error.is_set():
                result["reason"] = "isolation_unavailable"
                metadata["win32_error"] = capture.io_error_number
            elif exit_code.value != 0:
                result["reason"] = "nonzero_exit"
            else:
                result.update(status="success", reason="ok")
        except _ApiFailure as error:
            metadata["win32_error"] = error.number
            if resumed or security_verified:
                result["reason"] = "isolation_unavailable"
        except OSError as error:
            metadata["win32_error"] = getattr(error, "winerror", None) or ERROR_INVALID_PARAMETER
        except (AttributeError, TypeError, ValueError, OverflowError):
            metadata["win32_error"] = ERROR_INVALID_PARAMETER
        except Exception:
            # Worker inputs, command lines and exception messages must never enter audit metadata.
            metadata["win32_error"] = ERROR_INVALID_PARAMETER
            result["reason"] = "isolation_unavailable"
        finally:
            if cleanup_deadline is None:
                cleanup_deadline = time.monotonic() + 2.0
            cleanup_started = cleanup_deadline - 2.0
            if api is not None:
                if process.hProcess:
                    if job and job_assigned:
                        api.TerminateJobObject(job, ERROR_NOT_ENOUGH_QUOTA)
                        metadata["termination"] = "job_terminated"
                    else:
                        # A process that failed job verification has never been resumed.
                        api.TerminateProcess(process.hProcess, ERROR_NOT_ENOUGH_QUOTA)
                        metadata["termination"] = "suspended_process_terminated"
                    process_wait = api.WaitForSingleObject(process.hProcess, cleanup_wait_milliseconds())
                    metadata["process_exit_confirmed"] = process_wait == WAIT_OBJECT_0
                    code = DWORD()
                    if api.GetExitCodeProcess(process.hProcess, ctypes.byref(code)) and code.value != 259:
                        result["exit_code"] = int(code.value)
                    api.CloseHandle(process.hProcess)
                    process.hProcess = None
                if process.hThread:
                    api.CloseHandle(process.hThread)
                if token:
                    api.CloseHandle(token)
                for handle in child_handles:
                    api.CloseHandle(handle)
                # The child has exited; its pipe endpoints are closed. Cancel any remaining host IO.
                for thread in threads:
                    if thread.is_alive() and thread.native_id:
                        thread_handle = api.OpenThread(0x1, False, thread.native_id)
                        if thread_handle:
                            api.CancelSynchronousIo(thread_handle)
                            api.CloseHandle(thread_handle)
                    thread.join(cleanup_remaining())
                for endpoint in endpoints:
                    endpoint.close()
                if job:
                    try:
                        self._record_job(api, job, metadata)
                    except _ApiFailure as error:
                        metadata["win32_error"] = error.number
                        result.update(status="failed", reason="isolation_unavailable")
                    api.CloseHandle(job)  # KILL_ON_JOB_CLOSE remains the final backstop.
                if completion:
                    api.CloseHandle(completion)
                if attribute_initialized:
                    api.DeleteProcThreadAttributeList(attribute_buffer)
                if sid:
                    api.FreeSid(sid)
            metadata["cleanup_complete"] = (
                not any(thread.is_alive() for thread in threads) and
                (metadata["pid"] is None or
                 (metadata.get("process_exit_confirmed", result["exit_code"] is not None) and
                  metadata["active_processes_after"] == 0)))
            if not metadata["cleanup_complete"]:
                result.update(status="failed", reason="isolation_unavailable")
            metadata["cleanup_ms"] = round((time.monotonic() - cleanup_started) * 1000, 3)
            if capture is not None:
                with capture.lock:
                    result["stdout"] = bytes(capture.stdout)
                    result["stderr"] = bytes(capture.stderr)
            metadata["end"] = _now_shanghai()
            metadata["wall_ms"] = round((time.monotonic() - started_at) * 1000, 3)
        return result

    @staticmethod
    def _drain_events(api, completion):
        events = []
        for _ in range(64):
            message = DWORD()
            key = ULONG_PTR()
            detail = PVOID()
            if not api.GetQueuedCompletionStatus(completion, ctypes.byref(message), ctypes.byref(key),
                                                  ctypes.byref(detail), 0):
                if ctypes.get_last_error() == WAIT_TIMEOUT:
                    break
                raise _ApiFailure(ctypes.get_last_error())
            if key.value == 1:
                events.append(int(message.value))
        return events

    @staticmethod
    def _record_job(api, job, metadata):
        accounting = api.query_job(job, 1, _Accounting)
        extended_limit = api.query_job(job, 9, _ExtendedLimit)
        metadata["cpu_ms"] = round((accounting.TotalUserTime + accounting.TotalKernelTime) / 10000, 3)
        metadata["cpu_user_ms"] = round(accounting.TotalUserTime / 10000, 3)
        metadata["peak_job_memory_bytes"] = int(extended_limit.PeakJobMemoryUsed)
        metadata["active_processes_after"] = int(accounting.ActiveProcesses)


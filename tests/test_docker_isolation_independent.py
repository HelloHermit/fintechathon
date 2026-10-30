"""Independent black-box acceptance of the public Linux Docker contract.

The author has not read the banking, isolation backend, monitor, worker or
supervisor implementations. Expected behavior comes from the public API and
business specifications listed in docs/29a. This file intentionally uses only
the standard library and the public src.isolation / src.bank interfaces.

Real execution requires FINTECH_DOCKER_RUNTIME and a working, authorized Docker
daemon. Missing prerequisites are errors, never passing skips. Run this module
directly to preserve a fresh JSON evidence file for every attempt.
"""

from __future__ import annotations

import datetime as datetime_module
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import struct
import sys
import tempfile
import threading
import time
import unittest
import ctypes
from ctypes import wintypes


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
RUN_DIRECTORY: Path | None = None
OBSERVATIONS: list[dict] = []
PROBE_MARKER = b" \n" * 19


def record_observation(case: str, expectation: str, actual: object, **details):
    """Keep public observations without raw secret, model input or stderr."""
    OBSERVATIONS.append({
        "case": case,
        "expectation": expectation,
        "actual": actual,
        **details,
    })


def new_run_directory() -> Path:
    global RUN_DIRECTORY
    if RUN_DIRECTORY is None:
        runs_directory = PROJECT_DIRECTORY / "tests" / ".runs"
        runs_directory.mkdir(parents=True, exist_ok=True)
        RUN_DIRECTORY = Path(tempfile.mkdtemp(
            prefix="docker-isolation-independent-", dir=runs_directory
        ))
    return RUN_DIRECTORY


class EvidenceResult(unittest.TextTestResult):
    """Preserve original failures instead of replacing their evidence."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_results = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.case_results.append({"test": str(test), "status": "passed"})

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.case_results.append({
            "test": str(test), "status": "failed",
            "detail": self._exc_info_to_string(error, test),
        })

    def addError(self, test, error):
        super().addError(test, error)
        self.case_results.append({
            "test": str(test), "status": "error",
            "detail": self._exc_info_to_string(error, test),
        })

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        self.case_results.append({
            "test": str(subtest),
            "status": "passed" if error is None else "failed",
            "detail": "" if error is None else self._exc_info_to_string(error, test),
        })


class DockerIndependentAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(PROJECT_DIRECTORY) not in sys.path:
            sys.path.insert(0, str(PROJECT_DIRECTORY))
        from src.isolation import IsolatedExecutor, IsolationError
        cls.executor_class = IsolatedExecutor
        cls.isolation_error = IsolationError
        configured_runtime = os.environ.get("FINTECH_DOCKER_RUNTIME")
        if not configured_runtime:
            raise RuntimeError("FINTECH_DOCKER_RUNTIME is required; no skip or ordinary-process fallback")
        cls.runtime = Path(configured_runtime).resolve()
        if not (PROJECT_DIRECTORY / "src" / "DOCKER_ISOLATION_API.md").is_file():
            raise RuntimeError("Linux Docker contract is not yet frozen")
        cls.run_directory = new_run_directory()
        cls.config = json.loads((cls.runtime / "isolation-config.json").read_text(encoding="utf-8"))
    def setUp(self):
        self.monitor_path = self.run_directory / f"{self._testMethodName}-monitor.sqlite3"
        self.executor = self.executor_class(self.runtime, self.monitor_path)

    def tearDown(self):
        self.executor.close()

    @classmethod
    def tearDownClass(cls):
        executor = getattr(cls, "executor", None)
        if executor is not None:
            executor.close()

    def execute(self, name, payload, *, executor=None, **kwargs):
        selected_executor = executor or self.executor
        try:
            value = selected_executor.execute(name, payload, **kwargs)
        except self.isolation_error:
            receipt = selected_executor.last_receipt
            record_observation(self.id(), "public executor failure receipt", receipt)
            raise
        record_observation(self.id(), "public executor success receipt", selected_executor.last_receipt)
        return value

    def expect_failure(self, name, payload, *, reasons=None, executor=None, **kwargs):
        selected_executor = executor or self.executor
        with self.assertRaises(self.isolation_error):
            self.execute(name, payload, executor=selected_executor, **kwargs)
        receipt = selected_executor.last_receipt
        self.assertEqual(receipt["status"], "failed")
        self.assertNotIn("data", {key: value for key, value in receipt.items() if value is not None})
        if reasons is not None:
            self.assertIn(receipt["reason"], reasons)
        return receipt

    def probe(self, source, payload=None, *, executor=None, **kwargs):
        script_path = self.run_directory / f"probe-{time.time_ns()}.py"
        script_path.write_text(source, encoding="utf-8")
        selected_executor = executor or self.executor
        receipt = selected_executor.run_probe(script_path, payload, **kwargs)
        record_observation(self.id(), "trusted independent attack probe receipt", receipt)
        return receipt

    def assert_probe_success(self, receipt):
        self.assertEqual(receipt["status"], "success", receipt)
        self.assertEqual(receipt["reason"], "ok", receipt)
        self.assertIn("data", receipt)
        return receipt["data"]

    def assert_clean_receipt(self, receipt):
        metadata = receipt["metadata"]
        self.assertTrue(metadata["cleanup_complete"], metadata)
        self.assertFalse(metadata["container_running_after"], metadata)
        self.assertEqual(metadata["container_pid_after"], 0, metadata)
        self.assertTrue(metadata["container_removed"], metadata)
        self.assertIsNone(metadata["pid"])

    def docker(self, *arguments, timeout=8, check=True):
        command = [self.config["docker_executable"], "--host", self.config["docker_host"],
                   "--config", self.config["docker_config_directory"], *arguments]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check and result.returncode != 0:
            self.fail(f"Own Docker observation failed, exit={result.returncode}, stderr_bytes={len(result.stderr)}")
        return result

    def inspect_owned(self, container_id):
        self.assertRegex(container_id, r"^[0-9a-f]{64}$")
        result = self.docker("inspect", container_id, check=False)
        if result.returncode:
            # A missing container and a lost daemon are different outcomes.
            # ps must itself succeed before this ID can be treated as gone.
            self.assertNotIn(container_id, self.owned_ids(), "inspect failed while the owned ID still exists")
            return None
        document = json.loads(result.stdout)[0]
        self.assertEqual(document["Id"], container_id)
        name = document["Name"].lstrip("/")
        self.assertRegex(name, r"^fintech-worker-[0-9a-f]{32}$")
        labels = document["Config"]["Labels"]
        self.assertEqual(labels["com.fintechathon.isolation"], "docker-linux-readonly-v2")
        self.assertEqual(labels["com.fintechathon.package"], self.config["package_name"])
        self.assertEqual(labels["com.fintechathon.task"], name.removeprefix("fintech-worker-"))
        return document

    def owned_ids(self):
        result = self.docker("ps", "-aq", "--no-trunc", "--filter", "label=com.fintechathon.isolation=docker-linux-readonly-v2",
                             "--filter", "label=com.fintechathon.package=" + self.config["package_name"])
        return {line.strip() for line in result.stdout.decode("ascii").splitlines() if line.strip()}

    def clean_owned(self, container_id):
        document = self.inspect_owned(container_id)
        if document is None:
            return
        if document["State"]["Running"]:
            self.docker("kill", container_id, check=False)
            document = self.inspect_owned(container_id)
        self.assertFalse(document and document["State"]["Running"], "own test container would remain live")
        if document is not None:
            self.docker("rm", container_id)

    def discover_live_ack(self, before_ids):
        deadline = time.monotonic() + 15
        selected_id = None
        while time.monotonic() < deadline:
            candidates = self.owned_ids() - before_ids
            self.assertLessEqual(len(candidates), 1, "another same-package task appeared; unsafe to select an owner")
            if candidates:
                selected_id = next(iter(candidates))
                document = self.inspect_owned(selected_id)
                if document is not None and document["State"]["Running"]:
                    break
            time.sleep(0.02)
        else:
            self.fail("no own live container was observed")
        arguments = [self.config["docker_executable"], "--host", self.config["docker_host"],
                     "--config", self.config["docker_config_directory"], "attach", "--no-stdin", "--sig-proxy=false", selected_id]
        observer = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        acknowledgement = threading.Event()
        observed_prefix = bytearray()

        def read_ack():
            while len(observed_prefix) < 512:
                value = observer.stdout.read(1)
                if not value:
                    return
                observed_prefix.extend(value)
                if b" \n \n" in observed_prefix:
                    acknowledgement.set()

        reader = threading.Thread(target=read_ack, daemon=True)
        reader.start()
        if not acknowledgement.wait(timeout=3):
            self.stop_observer(observer, reader)
            self.fail("independent attach did not observe the probe's repeated whitespace ACK")
        return selected_id, observer, reader

    @staticmethod
    def stop_observer(observer, reader):
        if observer.poll() is None:
            observer.terminate()
        try:
            observer.wait(timeout=2)
        except subprocess.TimeoutExpired:
            observer.kill()
            observer.wait(timeout=2)
        reader.join(timeout=1)
        if observer.stdout:
            observer.stdout.close()

    def start_live_probe(self, source, *, cancel_event=None):
        before_ids = self.owned_ids()
        box = {}
        script = self.run_directory / f"live-probe-{time.time_ns()}.py"
        script.write_text(source, encoding="utf-8")

        def run():
            try:
                box["receipt"] = self.executor.run_probe(script, cancel_event=cancel_event)
            except BaseException as error:
                box["error"] = type(error).__name__

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        container_id, observer, reader = self.discover_live_ack(before_ids)
        return thread, box, container_id, observer, reader

    @staticmethod
    def host_descendants(parent_pid):
        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "cannot observe own descendants")
        processes = []
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while present:
                processes.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
                present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        owned = {parent_pid}
        while True:
            children = {pid for pid, parent, _ in processes if parent in owned}
            expanded = owned | children
            if expanded == owned:
                return [(pid, name) for pid, _, name in processes if pid in owned and pid != parent_pid]
            owned = expanded

    @staticmethod
    def host_pid_is_alive(pid):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return False
            raise OSError(ctypes.get_last_error(), "cannot observe own former child")
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)

    def test_20_linux_policy_and_actual_proc_cgroup_boundaries(self):
        source = '''import json,os,resource
with open("/proc/self/status") as handle:
    status=dict(line.split(":",1) for line in handle if ":" in line)
selected={key:status[key].strip() for key in ["Uid","Gid","CapInh","CapPrm","CapEff","CapBnd","CapAmb","NoNewPrivs","Seccomp"]}
cgroup={}
for name in ["pids.max","pids.current","memory.max","memory.swap.max","cpu.max"]:
    with open("/sys/fs/cgroup/"+name) as handle: cgroup[name]=handle.read().strip()
mounts={}
with open("/proc/self/mountinfo") as handle:
    for line in handle:
        fields=line.split()
        if fields[4] in ["/","/runtime","/tmp"]:
            separator=fields.index("-")
            mounts[fields[4]]={"options":fields[5].split(","),"filesystem":fields[separator+1],"super_options":fields[separator+3].split(",")}
print(json.dumps({"status":selected,"cgroup":cgroup,"mounts":mounts,"cpu_rlimit":resource.getrlimit(resource.RLIMIT_CPU),"file_rlimit":resource.getrlimit(resource.RLIMIT_FSIZE)}))
'''
        receipt = self.probe(source)
        data = self.assert_probe_success(receipt)
        self.assert_clean_receipt(receipt)
        metadata = receipt["metadata"]
        required_checks = set("owned_identity pinned_image not_started non_root fixed_entrypoint fixed_arguments no_host_environment fixed_workdir no_network read_only_root no_capabilities no_new_privileges no_privileged one_supervisor_one_worker memory cpu_rate cpu_seconds file_size private_namespaces no_host_cgroup no_extra_resources no_published_ports no_logs tmpfs no_healthcheck no_automatic_restart stdin_only runtime_mount requested_mount default_linux_runtime no_supplementary_groups oom_kill_enabled no_automatic_remove".split())
        self.assertTrue(required_checks.issubset(metadata["policy_checks"]))
        self.assertTrue(all(value is True for value in metadata["policy_checks"].values()))
        self.assertTrue(metadata["daemon_policy_verified"])
        self.assertEqual(metadata["daemon_image_id"], self.config["image_id"])
        self.assertTrue(metadata["watchdog_armed"])
        self.assertTrue(metadata["container_started"])
        self.assertIsNone(metadata["pid"])
        if metadata.get("linux_pid") is not None:
            self.assertGreater(metadata["linux_pid"], 0)
        self.assertEqual(metadata["scope"], "docker_desktop_linux_vm")
        self.assertEqual(metadata["linux_pid_scope"], "docker_desktop_linux_vm")
        for field in ["cpu_ms", "peak_job_memory_bytes"]:
            self.assertTrue(metadata[field] is None or metadata[field] >= 0)
        for field in ["setup_ms", "execution_ms", "cleanup_ms", "wall_ms"]:
            self.assertGreaterEqual(metadata[field], 0)
        status = data["status"]
        self.assertEqual([int(value) for value in status["Uid"].split()], [65534] * 4)
        self.assertEqual([int(value) for value in status["Gid"].split()], [65534] * 4)
        for name in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]:
            self.assertEqual(int(status[name], 16), 0)
        self.assertEqual(status["NoNewPrivs"], "1")
        self.assertEqual(status["Seccomp"], "2")
        self.assertEqual(data["cpu_rlimit"], [1, 1])
        self.assertEqual(data["file_rlimit"], [16777216, 16777216])
        cgroup = data["cgroup"]
        self.assertEqual(int(cgroup["pids.max"]), 2)
        self.assertEqual(int(cgroup["pids.current"]), 2)
        self.assertEqual(int(cgroup["memory.max"]), 134217728)
        self.assertEqual(int(cgroup["memory.swap.max"]), 0)
        quota, period = map(int, cgroup["cpu.max"].split())
        self.assertLessEqual(quota / period, 0.2)
        self.assertGreater(quota, 0)
        self.assertIn("ro", data["mounts"]["/"]["options"])
        self.assertIn("ro", data["mounts"]["/runtime"]["options"])
        temporary_mount = data["mounts"]["/tmp"]
        self.assertEqual(temporary_mount["filesystem"], "tmpfs")
        self.assertTrue({"rw", "noexec", "nosuid", "nodev"}.issubset(set(temporary_mount["options"] + temporary_mount["super_options"])))
        self.assertEqual([Path(path).resolve() for path in self.executor.readable_directories], [self.runtime])

    def test_21_supervisor_cannot_be_frozen_or_modified_by_same_uid_worker(self):
        source = '''import json,os,signal,ctypes,resource
results={}
for name,number in [("sigstop",signal.SIGSTOP),("sigkill",signal.SIGKILL)]:
    try:
        os.kill(1,number)
        results[name+"_call_refused"]=False
    except OSError: results[name+"_call_refused"]=True
    with open("/proc/1/status") as handle:
        state=next(line for line in handle if line.startswith("State:"))
    results[name+"_ineffective"]="T (" not in state and "t (" not in state
try:
    handle=os.open("/proc/1/mem",os.O_RDWR)
    os.close(handle)
    results["memory_denied"]=False
except OSError: results["memory_denied"]=True
try:
    resource.prlimit(1,resource.RLIMIT_CPU,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    results["parent_rlimit_change_denied"]=False
except (OSError,ValueError): results["parent_rlimit_change_denied"]=True
libc=ctypes.CDLL(None,use_errno=True)
results["ptrace_denied"]=libc.ptrace(16,1,None,None)==-1
print(json.dumps(results))
'''
        receipt = self.probe(source)
        data = self.assert_probe_success(receipt)
        self.assert_clean_receipt(receipt)
        for key, value in data.items():
            if not key.endswith("_call_refused"):
                self.assertTrue(value, data)

    def test_22_wall_deadline_stops_body_and_removes_container(self):
        source = 'import os,time\nos.write(1,' + repr(PROBE_MARKER) + ')\ntime.sleep(60)\n'
        receipt = self.probe(source)
        self.assertEqual((receipt["status"], receipt["reason"]), ("failed", "timeout"), receipt)
        self.assertEqual(receipt["metadata"]["stdout_sha256"], hashlib.sha256(PROBE_MARKER).hexdigest(), "probe body must execute before the timeout")
        self.assertLessEqual(receipt["metadata"]["execution_ms"], 7100)
        self.assert_clean_receipt(receipt)

    def test_23_cpu_busy_loop_stops_without_invented_cpu_attribution(self):
        source = 'import os\nos.write(1,' + repr(PROBE_MARKER) + ')\nwhile True: pass\n'
        receipt = self.probe(source)
        self.assertEqual(receipt["status"], "failed", receipt)
        self.assertIn(receipt["reason"], {"timeout", "nonzero_exit", "cpu_limit"})
        self.assertEqual(receipt["metadata"]["stdout_sha256"], hashlib.sha256(PROBE_MARKER).hexdigest())
        self.assertFalse(receipt["metadata"]["oom_killed"])
        self.assertLessEqual(receipt["metadata"]["execution_ms"], 7100)
        self.assert_clean_receipt(receipt)
        record_observation(self.id(), "CPU busy worker safely terminates; only proc/cgroup prove configured CPU bounds", {
            "actual_reason": receipt["reason"], "cpu_ms": receipt["metadata"]["cpu_ms"],
            "cpu_kill_causality_proven": receipt["reason"] == "cpu_limit",
        })

    def test_24_memory_growth_oom_is_proven_only_by_daemon(self):
        source = 'import os\nos.write(1,' + repr(PROBE_MARKER) + ')\nitems=[]\nwhile True: items.append(bytearray(4*1024*1024))\n'
        receipt = self.probe(source)
        self.assertEqual(receipt["status"], "failed", receipt)
        self.assertEqual(receipt["metadata"]["stdout_sha256"], hashlib.sha256(PROBE_MARKER).hexdigest())
        self.assertTrue(receipt["metadata"]["oom_killed"], "unknown SIGKILL or wall expiry cannot prove memory enforcement")
        self.assertEqual(receipt["reason"], "memory_limit")
        self.assert_clean_receipt(receipt)

    def test_25_stdout_and_stderr_floods_are_bounded(self):
        for descriptor in [1, 2]:
            with self.subTest(descriptor=descriptor):
                source = f'import os\nwhile True: os.write({descriptor}, b"X"*4096)\n'
                receipt = self.probe(source)
                self.assertEqual((receipt["status"], receipt["reason"]), ("failed", "output_limit"), receipt)
                self.assertLessEqual(receipt["metadata"]["output_bytes"], 65536)
                self.assertGreater(receipt["metadata"]["output_bytes"], 0)
                self.assert_clean_receipt(receipt)

    def test_26_cancelled_body_cannot_deliver_early_success(self):
        cancellation = threading.Event()
        source = 'import os,time\nos.write(1,b"{}\\n")\nwhile True:\n os.write(1,b" \\n \\n")\n time.sleep(0.02)\n'
        thread, box, container_id, observer, reader = self.start_live_probe(source, cancel_event=cancellation)
        try:
            cancelled_at = time.monotonic()
            cancellation.set()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive(), "cancellation did not finish cleanup")
            self.assertNotIn("error", box)
            receipt = box["receipt"]
            record_observation(self.id(), "cancel only after independent body ACK; no early success data", receipt,
                               elapsed_after_cancel_seconds=round(time.monotonic() - cancelled_at, 3))
            self.assertEqual((receipt["status"], receipt["reason"]), ("cancelled", "cancelled"), receipt)
            self.assertGreater(receipt["metadata"]["output_bytes"], 3)
            self.assertFalse(receipt.get("data"))
            self.assert_clean_receipt(receipt)
        finally:
            cancellation.set()
            self.stop_observer(observer, reader)
            thread.join(timeout=8)
            self.clean_owned(container_id)

    def test_27_missing_config_and_sensitive_database_paths_fail_closed(self):
        from src.bank import BankService
        empty_runtime = self.run_directory / "missing-runtime"
        empty_runtime.mkdir()
        with self.assertRaises(self.isolation_error):
            self.executor_class(empty_runtime, self.run_directory / "missing-config-monitor.sqlite3")
        with self.assertRaises(ValueError):
            BankService(self.monitor_path, executor=self.executor)
        forbidden_path = self.runtime / "independent-business-must-not-be-created.sqlite3"
        self.assertFalse(forbidden_path.exists())
        with self.assertRaises(ValueError):
            BankService(forbidden_path, executor=self.executor)
        self.assertFalse(forbidden_path.exists())
        alias_path = self.run_directory / "monitor-hardlink.sqlite3"
        os.link(self.monitor_path, alias_path)
        try:
            with self.assertRaises(self.isolation_error):
                self.executor_class(self.runtime, alias_path)
        finally:
            alias_path.unlink()

    def test_28_live_daemon_inspect_cross_checks_privileges_mounts_and_namespaces(self):
        source = 'import os,time\nwhile True:\n os.write(1,b" \\n \\n")\n time.sleep(0.02)\n'
        thread, box, container_id, observer, reader = self.start_live_probe(source)
        try:
            document = self.inspect_owned(container_id)
            self.assertIsNotNone(document)
            self.assertTrue(document["State"]["Running"])
            self.assertGreater(document["State"]["Pid"], 0)
            self.assertEqual(document["Image"], self.config["image_id"])
            configuration = document["Config"]
            host = document["HostConfig"]
            self.assertEqual(configuration["User"], "65534:65534")
            self.assertFalse(host["Privileged"])
            self.assertTrue(host["ReadonlyRootfs"])
            self.assertEqual(host["NetworkMode"], "none")
            self.assertEqual(host["IpcMode"], "none")
            self.assertIn(host["PidMode"], ["", "private"])
            self.assertIn(host["UTSMode"], ["", "private"])
            self.assertEqual(host["CgroupnsMode"], "private")
            self.assertFalse(host.get("CgroupParent"))
            self.assertEqual(host["PidsLimit"], 2)
            self.assertEqual(host["Memory"], 134217728)
            self.assertEqual(host["MemorySwap"], 134217728)
            self.assertEqual(host["NanoCpus"], 200000000)
            self.assertEqual({item.upper() for item in host["CapDrop"]}, {"ALL"})
            self.assertFalse(host["CapAdd"])
            self.assertTrue(any(item.startswith("no-new-privileges") for item in host["SecurityOpt"]))
            self.assertFalse(any("unconfined" in item.lower() for item in host["SecurityOpt"]))
            self.assertFalse(host["Devices"])
            self.assertFalse(host["DeviceRequests"])
            self.assertFalse(host["PortBindings"])
            self.assertFalse(host["PublishAllPorts"])
            self.assertEqual(host["RestartPolicy"]["Name"], "no")
            self.assertEqual(host["LogConfig"]["Type"], "none")
            self.assertFalse(host["AutoRemove"])
            self.assertFalse(host["OomKillDisable"])
            healthcheck = configuration.get("Healthcheck")
            # Docker's explicit NONE disables checks; an empty Test inherits.
            # https://github.com/moby/docker-image-spec/blob/main/spec.md
            self.assertTrue(not healthcheck or healthcheck.get("Test") == ["NONE"], healthcheck)
            self.assertTrue(configuration["OpenStdin"])
            self.assertFalse(configuration["Tty"])
            self.assertEqual(set(item.split("=", 1)[0] for item in configuration["Env"]), {
                "PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
            })
            binds = [mount for mount in document["Mounts"] if mount["Type"] == "bind"]
            self.assertEqual(len(binds), 1)
            self.assertEqual(binds[0]["Destination"], "/runtime")
            self.assertFalse(binds[0]["RW"])
            self.assertEqual(binds[0]["Propagation"], "rprivate")
            self.assertTrue(all(mount["Destination"] in {"/runtime", "/tmp"} for mount in document["Mounts"]))
            record_observation(self.id(), "actual live daemon fields cross-check policy; observed own immutable ID", {
                "container_id": container_id, "linux_vm_pid": document["State"]["Pid"],
                "image": document["Image"], "host_config": {key: host[key] for key in [
                    "Privileged", "ReadonlyRootfs", "NetworkMode", "IpcMode", "PidMode", "UTSMode", "CgroupnsMode", "PidsLimit", "Memory", "MemorySwap", "NanoCpus", "CapDrop", "CapAdd", "SecurityOpt", "RestartPolicy", "LogConfig", "AutoRemove", "OomKillDisable",
                ]}, "mounts": [{key: mount.get(key) for key in ["Type", "Destination", "RW", "Propagation"]} for mount in document["Mounts"]],
            })
            thread.join(timeout=8)
            self.assertFalse(thread.is_alive())
            self.assertNotIn("error", box)
            self.assertEqual(box["receipt"]["reason"], "timeout")
            self.assert_clean_receipt(box["receipt"])
        finally:
            self.stop_observer(observer, reader)
            thread.join(timeout=8)
            self.clean_owned(container_id)

    def parent_death_boundary(self, kill_watchdogs):
        self.assertEqual(os.name, "nt", "this experiment targets the documented Windows DockerDesktop host")
        self.executor.close()
        script_path = self.run_directory / f"parent-death-probe-{kill_watchdogs}.py"
        script_path.write_text('import os,time\nwhile True:\n os.write(1,b" \\n \\n")\n time.sleep(0.02)\n', encoding="utf-8")
        child_monitor = self.run_directory / f"parent-death-{kill_watchdogs}-monitor.sqlite3"
        child_source = '''import sys
from src.isolation import IsolatedExecutor
with IsolatedExecutor(sys.argv[1],sys.argv[2]) as executor:
    executor.run_probe(sys.argv[3],request_id="independent-parent-death")
'''
        before_ids = self.owned_ids()
        child = subprocess.Popen([sys.executable, "-c", child_source, str(self.runtime), str(child_monitor), str(script_path)],
                                 cwd=PROJECT_DIRECTORY, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        container_id = None
        observer = reader = None
        try:
            container_id, observer, reader = self.discover_live_ack(before_ids)
            descendants = self.host_descendants(child.pid)
            python_watchdogs = [pid for pid, name in descendants if name.lower() == Path(sys.executable).name.lower()]
            self.assertTrue(python_watchdogs, "must observe actual own external Python watchdog before removing it")
            killed_at = time.monotonic()
            if kill_watchdogs:
                taskkill = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
                killed = subprocess.run([str(taskkill), "/PID", str(child.pid), "/T", "/F"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(killed.returncode, 0, f"cannot terminate owned process tree; exit={killed.returncode}")
            else:
                child.kill()
            child.wait(timeout=3)
            if kill_watchdogs:
                for pid in python_watchdogs:
                    self.assertFalse(self.host_pid_is_alive(pid), "external watchdog still live; inner deadline causality unproven")
            deadline = killed_at + 7
            final_document = self.inspect_owned(container_id)
            while final_document is not None and final_document["State"]["Running"] and time.monotonic() < deadline:
                time.sleep(0.05)
                final_document = self.inspect_owned(container_id)
            self.assertFalse(final_document is not None and final_document["State"]["Running"], "worker survived parent/watchdog loss beyond inner deadline plus cleanup allowance")
            if final_document is not None:
                self.assertEqual(final_document["State"]["Pid"], 0)
            record_observation(self.id(), "body ACK observed before parent exit; no live worker after independent deadline", {
                "container_id": container_id, "parent_pid": child.pid,
                "external_watchdog_pids_observed": python_watchdogs,
                "external_watchdogs_killed_and_verified": kill_watchdogs,
                "elapsed_after_kill_seconds": round(time.monotonic() - killed_at, 3),
                "container_removed": final_document is None,
                "container_running": False,
                "stopped_forensic_object_allowed_after_abrupt_death": final_document is not None,
            })
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)
            if observer is not None:
                self.stop_observer(observer, reader)
            if container_id is not None:
                self.clean_owned(container_id)
            else:
                remaining = self.owned_ids() - before_ids
                if len(remaining) == 1:
                    self.clean_owned(next(iter(remaining)))

    def test_29_parent_death_external_watchdog_stops_worker(self):
        self.parent_death_boundary(kill_watchdogs=False)

    def test_30_parent_and_external_watchdog_death_inner_supervisor_stops_worker(self):
        self.parent_death_boundary(kill_watchdogs=True)

    def test_31_secret_style_stderr_and_invalid_output_are_not_exposed(self):
        fake_secret = "fake-stdout-stderr-secret-" + os.urandom(16).hex()
        source = 'import os\nos.write(1,' + repr(PROBE_MARKER) + ')\nos.write(2,' + repr(fake_secret.encode("ascii")) + ')\nraise RuntimeError(' + repr(fake_secret) + ')\n'
        receipt = self.probe(source)
        self.assertEqual(receipt["status"], "failed", receipt)
        self.assertIn(receipt["reason"], {"nonzero_exit", "invalid_output"})
        self.assertEqual(receipt["metadata"]["stdout_sha256"], hashlib.sha256(PROBE_MARKER).hexdigest())
        self.assertNotIn(fake_secret, json.dumps(receipt, ensure_ascii=False))
        self.assertNotIn(fake_secret, json.dumps(self.executor.audit_events(), ensure_ascii=False))
        self.assert_clean_receipt(receipt)

    def test_32_invalid_limits_never_create_monitor_or_start(self):
        cases = [
            ("unknown", {"unknown_budget": 1}),
            ("wall above maximum", {"wall_seconds": 5.01}),
            ("wall below minimum", {"wall_seconds": 0.19}),
            ("cpu fractional", {"cpu_seconds": 0.5}),
            ("cpu above maximum", {"cpu_seconds": 2}),
            ("memory above maximum", {"memory_bytes": 134217729}),
            ("memory below minimum", {"memory_bytes": 33554431}),
            ("output above maximum", {"output_bytes": 65537}),
            ("output below minimum", {"output_bytes": 1023}),
            ("extra worker", {"process_count": 2}),
            ("cpu rate above maximum", {"cpu_rate_percent": 21}),
            ("cpu rate below minimum", {"cpu_rate_percent": 0}),
            ("fractional bytes", {"memory_bytes": 67108864.0}),
            ("fractional process count", {"process_count": 1.0}),
            ("fractional cpu rate", {"cpu_rate_percent": 10.0}),
        ]
        for field in ["wall_seconds", "cpu_seconds", "memory_bytes", "output_bytes", "process_count", "cpu_rate_percent"]:
            cases.append(("bool " + field, {field: True}))
        for field in ["wall_seconds", "cpu_seconds"]:
            for value in [float("nan"), float("inf"), -float("inf")]:
                cases.append(("nonfinite " + field + " " + str(value), {field: value}))
        for index, (label, limits) in enumerate(cases):
            with self.subTest(label=label):
                path = self.run_directory / f"invalid-limits-{index}-monitor.sqlite3"
                with self.assertRaises(self.isolation_error) as context:
                    self.executor_class(self.runtime, path, limits=limits)
                self.assertEqual(context.exception.reason, "invalid_input")
                self.assertFalse(path.exists())

    def test_33_tightened_limits_have_actual_cgroup_and_output_enforcement(self):
        self.executor.close()
        path = self.run_directory / "tightened-limits-monitor.sqlite3"
        limits = {"cpu_seconds": 1.0, "cpu_rate_percent": 19, "memory_bytes": 67108864, "output_bytes": 4096}
        with self.executor_class(self.runtime, path, limits=limits) as executor:
            source = '''import json
result={}
for name in ["memory.max","memory.swap.max","cpu.max"]:
    with open("/sys/fs/cgroup/"+name) as handle: result[name]=handle.read().strip()
print(json.dumps(result))
'''
            receipt = self.probe(source, executor=executor)
            data = self.assert_probe_success(receipt)
            self.assertEqual(int(data["memory.max"]), 67108864)
            self.assertEqual(int(data["memory.swap.max"]), 0)
            quota, period = map(int, data["cpu.max"].split())
            self.assertLessEqual(quota / period, 0.19)
            self.assert_clean_receipt(receipt)
            receipt = self.probe('import os\nwhile True: os.write(1,b"X"*4096)\n', executor=executor)
            self.assertEqual(receipt["reason"], "output_limit", receipt)
            self.assertGreater(receipt["metadata"]["output_bytes"], 0)
            self.assertLessEqual(receipt["metadata"]["output_bytes"], 4096)
            self.assert_clean_receipt(receipt)

    def test_01_fixed_parser_runs_real_json(self):
        candidate = {"intent": "query_balance", "params": {}}
        self.assertEqual(self.execute("parse_candidate", {"text": json.dumps(candidate)}), candidate)

    def test_02_strict_json_rejects_ambiguous_and_nonfinite_values(self):
        cases = {
            "duplicate top-level key": '{"a":1,"a":2}',
            "duplicate nested key": '{"a":{"b":1,"b":2}}',
            "nan": '{"amount":NaN}',
            "positive infinity": '{"amount":Infinity}',
            "negative infinity": '{"amount":-Infinity}',
            "exponent overflow": '{"amount":1e10000}',
            "array instead of object": '[]',
            "string instead of object": '"hello"',
            "multiple objects": '{}{}',
            "trailing source code": '{};__import__("os")',
            "excessive nesting": '{"a":' * 14 + '0' + '}' * 14,
            "over 16000 characters": '{"a":"' + ('x' * 16001) + '"}',
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                self.expect_failure("parse_candidate", {"text": text}, reasons={"invalid_input", "invalid_output"})

    def test_03_host_rejects_invalid_tasks_and_payload_shapes(self):
        for label, name, payload, reasons in [
            ("unknown task", "arbitrary_shell", {}, {"invalid_task"}),
            ("list payload", "parse_candidate", [], {"invalid_input"}),
            ("missing field", "parse_candidate", {}, {"invalid_input"}),
            ("extra field", "parse_candidate", {"text": "{}", "code": "print(1)"}, {"invalid_input"}),
            ("invalid text type", "parse_candidate", {"text": True}, {"invalid_input"}),
            ("nonfinite payload", "parse_candidate", {"text": "{}", "extra": float("nan")}, {"invalid_input"}),
            ("oversized input", "parse_candidate", {"text": "x" * 70000}, {"invalid_input"}),
        ]:
            with self.subTest(label=label):
                before = len(self.executor.audit_events())
                self.expect_failure(name, payload, reasons=reasons)
                after = self.executor.audit_events()
                self.assertGreaterEqual(len(after), before + 2)
                self.assertEqual([row["event"] for row in after[-2:]], ["started", "finished"])

    def test_04_probe_body_executes_and_env_does_not_inherit_fake_secret(self):
        variable_name = "DOCKER_INDEPENDENT_FAKE_SECRET"
        fake_secret = "fake-" + os.urandom(16).hex()
        previous = os.environ.get(variable_name)
        os.environ[variable_name] = fake_secret
        try:
            self.assertEqual(os.environ[variable_name], fake_secret)
            receipt = self.probe(
                'import os,json\n'
                'print(json.dumps({"body_executed":True,"fake_secret_absent":'
                '"DOCKER_INDEPENDENT_FAKE_SECRET" not in os.environ,'
                '"no_proxy_inherited":not any(k.lower().endswith("proxy") for k in os.environ)}))\n'
            )
        finally:
            if previous is None:
                os.environ.pop(variable_name, None)
            else:
                os.environ[variable_name] = previous
        data = self.assert_probe_success(receipt)
        self.assertTrue(data["body_executed"])
        self.assertTrue(data["fake_secret_absent"])
        self.assertTrue(data["no_proxy_inherited"])
        serialized_events = json.dumps(self.executor.audit_events(), ensure_ascii=False)
        self.assertNotIn(fake_secret, serialized_events)

    def test_05_invalid_probe_output_is_safe_failure(self):
        for label, source in [
            ("not JSON", 'print("not-a-json-result")\n'),
            ("multiple JSON values", 'print("{}{}")\n'),
            ("nonfinite JSON", 'print(\'{"x":NaN}\')\n'),
            ("duplicate JSON keys", 'print(\'{"x":1,"x":2}\')\n'),
            ("nonzero exit", 'import sys\nsys.exit(7)\n'),
        ]:
            with self.subTest(label=label):
                receipt = self.probe(source)
                self.assertEqual(receipt["status"], "failed", receipt)
                self.assertIn(receipt["reason"], {"invalid_output", "nonzero_exit"})
                self.assertFalse(receipt.get("data"))

    def test_06_host_files_have_positive_control_and_no_worker_access(self):
        fake_files = []
        for filename in ["fake-secret.txt", "fake-business.sqlite3", "fake-monitor.sqlite3"]:
            path = self.run_directory / filename
            path.write_bytes(b"independent-fake-only-" + os.urandom(12).hex().encode("ascii"))
            original = path.read_bytes()
            self.assertTrue(original)
            with path.open("ab") as handle:
                handle.write(b"-host-write-positive")
            self.assertEqual(path.read_bytes(), original + b"-host-write-positive")
            fake_files.append(path)
        candidate_paths = []
        for path in fake_files:
            candidate_paths.append(str(path))
            if path.drive:
                drive_letter = path.drive[0].lower()
                tail = path.as_posix().split(":", 1)[1]
                candidate_paths.extend([
                    f"/host_mnt/{drive_letter}{tail}",
                    f"/mnt/host/{drive_letter}{tail}",
                    f"/mnt/{drive_letter}{tail}",
                ])
        source = '''import json,sys,os
payload=json.load(sys.stdin)
results=[]
for path in payload["paths"]:
    read_allowed=False
    write_allowed=False
    try:
        with open(path,"rb") as handle: handle.read(1)
        read_allowed=True
    except OSError: pass
    try:
        with open(path,"ab") as handle: handle.write(b"worker-cross-boundary-write")
        write_allowed=True
    except OSError: pass
    results.append({"read_allowed":read_allowed,"write_allowed":write_allowed})
print(json.dumps({"body_executed":True,"results":results}))
'''
        snapshots = {path: path.read_bytes() for path in fake_files}
        data = self.assert_probe_success(self.probe(source, {"paths": candidate_paths}))
        self.assertTrue(data["body_executed"])
        self.assertEqual(len(data["results"]), len(candidate_paths))
        self.assertTrue(all(not item["read_allowed"] and not item["write_allowed"] for item in data["results"]))
        for path, snapshot in snapshots.items():
            self.assertEqual(path.read_bytes(), snapshot)
        record_observation(self.id(), "same host files readable/writable only on host", {
            "host_positive_controls": len(fake_files), "worker_attempts": len(candidate_paths),
            "host_files_unchanged": True,
        })

    def test_07_rootfs_and_runtime_write_denied_tmp_small_write_allowed(self):
        source = '''import json,os
results={}
for label,path in [("rootfs","/independent-root-write"),("runtime",__file__+".write")]:
    try:
        with open(path,"wb") as handle: handle.write(b"fake")
        results[label]=False
    except OSError: results[label]=True
temporary="/tmp/independent-small-write"
with open(temporary,"wb") as handle: handle.write(b"private bounded tmpfs positive")
with open(temporary,"rb") as handle: results["tmp_positive"]=handle.read()==b"private bounded tmpfs positive"
os.unlink(temporary)
print(json.dumps(results))
'''
        data = self.assert_probe_success(self.probe(source))
        self.assertTrue(data["rootfs"])
        self.assertTrue(data["runtime"])
        self.assertTrue(data["tmp_positive"])

    def test_08_tmpfs_hard_capacity_and_recovery(self):
        source = '''import json,os,errno
paths=["/tmp/independent-fill-"+str(index) for index in range(3)]
stat=os.statvfs("/tmp")
written=0
full=False
for path in paths:
    try:
        with open(path,"wb",buffering=0) as handle:
            for block in range(128): written+=handle.write(b"0"*65536)
    except OSError as error:
        full=error.errno==errno.ENOSPC
        break
for path in paths:
    try: os.unlink(path)
    except FileNotFoundError: pass
with open(paths[0],"wb") as handle: handle.write(b"recovered")
with open(paths[0],"rb") as handle: recovered=handle.read()==b"recovered"
os.unlink(paths[0])
print(json.dumps({"capacity_bytes":stat.f_blocks*stat.f_frsize,"written_bytes":written,"enospc":full,"recovered":recovered}))
'''
        data = self.assert_probe_success(self.probe(source))
        self.assertEqual(data["capacity_bytes"], 16 * 1024 * 1024)
        self.assertTrue(data["enospc"], data)
        self.assertLessEqual(data["written_bytes"], 16 * 1024 * 1024)
        self.assertTrue(data["recovered"])

    def test_09_tmpfs_exec_is_denied_without_forking(self):
        source = '''import json,os,errno
path="/tmp/independent-exec"
with open(path,"w") as handle: handle.write("#!/bin/sh\\nexit 42\\n")
os.chmod(path,0o700)
try:
    os.execv(path,[path])
except OSError as error:
    print(json.dumps({"exec_denied":error.errno in [errno.EACCES,errno.EPERM],"errno":error.errno}))
'''
        data = self.assert_probe_success(self.probe(source))
        self.assertTrue(data["exec_denied"])

    def test_10_worker_cannot_fork_spawn_thread_or_become_root(self):
        source = '''import json,os,subprocess,_thread,ctypes
results={"uid":os.getuid(),"gid":os.getgid()}
try:
    child=os.fork()
    if child==0: os._exit(99)
    os.waitpid(child,0)
    results["fork_denied"]=False
except OSError: results["fork_denied"]=True
try:
    subprocess.run(["/bin/true"],check=False,timeout=1)
    results["spawn_denied"]=False
except (OSError,RuntimeError): results["spawn_denied"]=True
try:
    _thread.start_new_thread(lambda:None,())
    results["thread_denied"]=False
except RuntimeError: results["thread_denied"]=True
try:
    os.setuid(0)
    results["setuid_denied"]=False
except OSError: results["setuid_denied"]=True
libc=ctypes.CDLL(None,use_errno=True)
results["new_user_namespace_denied"]=libc.unshare(0x10000000)!=0
print(json.dumps(results))
'''
        data = self.assert_probe_success(self.probe(source))
        self.assertEqual((data["uid"], data["gid"]), (65534, 65534))
        for key in ["fork_denied", "spawn_denied", "thread_denied", "setuid_denied", "new_user_namespace_denied"]:
            self.assertTrue(data[key], data)

    def network_boundary(self, family, host_address):
        tcp_listener = socket.socket(family, socket.SOCK_STREAM)
        udp_listener = socket.socket(family, socket.SOCK_DGRAM)
        stop_event = threading.Event()
        udp_thread = None
        try:
            tcp_listener.bind((host_address, 0))
            tcp_listener.listen(8)
            udp_listener.bind((host_address, 0))
            udp_listener.settimeout(0.1)
            tcp_port = tcp_listener.getsockname()[1]
            udp_port = udp_listener.getsockname()[1]

            def echo_udp():
                while not stop_event.is_set():
                    try:
                        packet, address = udp_listener.recvfrom(64)
                        udp_listener.sendto(packet, address)
                    except socket.timeout:
                        continue
                    except OSError:
                        return

            udp_thread = threading.Thread(target=echo_udp, daemon=True)
            udp_thread.start()
            with socket.socket(family, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect((host_address, tcp_port))
            accepted, _ = tcp_listener.accept()
            accepted.close()
            with socket.socket(family, socket.SOCK_DGRAM) as client:
                client.settimeout(1)
                client.sendto(b"independent-host-positive", (host_address, udp_port))
                self.assertEqual(client.recvfrom(64)[0], b"independent-host-positive")
            source = '''import json,sys,socket,os
payload=json.load(sys.stdin)
family=socket.AF_INET6 if payload["ipv6"] else socket.AF_INET
results={"body_executed":True,"interfaces":sorted(os.listdir("/sys/class/net"))}
with socket.socket(family,socket.SOCK_STREAM) as client:
    client.settimeout(0.3)
    try:
        client.connect((payload["host"],payload["tcp_port"]))
        results["host_tcp_denied"]=False
    except OSError: results["host_tcp_denied"]=True
with socket.socket(family,socket.SOCK_DGRAM) as client:
    client.settimeout(0.3)
    try:
        client.sendto(b"worker-private-loopback",(payload["host"],payload["udp_port"]))
        client.recvfrom(64)
        results["host_udp_denied"]=False
    except OSError: results["host_udp_denied"]=True
with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1",0))
    listener.listen(1)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as client:
        client.settimeout(0.3)
        client.connect(listener.getsockname())
        accepted,_=listener.accept()
        accepted.close()
        results["private_loopback_positive"]=True
with open("/proc/net/route") as handle:
    routes=[line.split() for line in handle.read().splitlines()[1:] if line.strip()]
results["no_external_ipv4_route"]=all(row[0]=="lo" for row in routes)
print(json.dumps(results))
'''
            data = self.assert_probe_success(self.probe(source, {
                "ipv6": family == socket.AF_INET6, "host": host_address,
                "tcp_port": tcp_port, "udp_port": udp_port,
            }))
            self.assertTrue(data["body_executed"])
            self.assertTrue(data["host_tcp_denied"], data)
            self.assertTrue(data["host_udp_denied"], data)
            self.assertTrue(data["private_loopback_positive"])
            self.assertEqual(data["interfaces"], ["lo"])
            self.assertTrue(data["no_external_ipv4_route"])
            record_observation(self.id(), "same TCP and UDP host targets positive on host, inaccessible from worker", {
                "family": "IPv6" if family == socket.AF_INET6 else "IPv4",
                "host_tcp_positive": True, "host_udp_positive": True,
                "worker_private_loopback_positive": True,
            })
        finally:
            stop_event.set()
            tcp_listener.close()
            udp_listener.close()
            if udp_thread is not None:
                udp_thread.join(timeout=1)

    def test_11_network_ipv4_host_tcp_udp_denied_private_loopback_allowed(self):
        self.network_boundary(socket.AF_INET, "127.0.0.1")

    def test_12_network_ipv6_host_tcp_udp_denied(self):
        self.network_boundary(socket.AF_INET6, "::1")

    def test_13_monitor_history_is_append_only(self):
        before = self.executor.audit_events()
        self.execute("parse_candidate", {"text": '{"safe":true}'})
        after = self.executor.audit_events()
        self.assertEqual(after[:len(before)], before)
        self.assertGreater(len(after), len(before))
        with sqlite3.connect(self.monitor_path) as connection:
            for operation in ["UPDATE isolation_audit SET reason='changed'", "DELETE FROM isolation_audit"]:
                with self.subTest(operation=operation.split()[0]):
                    with self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(operation)
                    connection.rollback()
        self.assertEqual(self.executor.audit_events(), after)

    def test_14_monitor_started_failure_prevents_execution_and_halts(self):
        def fail_started(event):
            if event.get("event") == "started":
                raise OSError("independent synthetic audit unavailable")

        path = self.run_directory / "started-audit-failure.sqlite3"
        self.executor.close()
        with self.executor_class(self.runtime, path, audit_hook=fail_started) as executor:
            first = self.expect_failure("parse_candidate", {"text": "{}"}, executor=executor, reasons={"audit_unavailable"})
            self.assertEqual(executor.audit_events(), [])
            second = self.expect_failure("parse_candidate", {"text": "{}"}, executor=executor, reasons={"audit_unavailable"})
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertEqual(executor.audit_events(), [])

    def test_15_monitor_finished_failure_withholds_result_and_halts(self):
        def fail_finished(event):
            if event.get("event") == "finished":
                raise OSError("independent synthetic audit unavailable")

        path = self.run_directory / "finished-audit-failure.sqlite3"
        self.executor.close()
        with self.executor_class(self.runtime, path, audit_hook=fail_finished) as executor:
            first = self.expect_failure("parse_candidate", {"text": "{}"}, executor=executor, reasons={"audit_unavailable"})
            events = executor.audit_events()
            self.assertEqual([event["event"] for event in events], ["started"])
            second = self.expect_failure("parse_candidate", {"text": "{}"}, executor=executor, reasons={"audit_unavailable"})
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertEqual(executor.audit_events(), events)

    def test_16_six_bank_tools_use_actual_executor_and_keep_business_facts(self):
        from src.bank import BankService

        class CallRecorder:
            def __init__(self, executor):
                self.delegate = executor
                self.calls = []

            def __getattr__(self, name):
                return getattr(self.delegate, name)

            def execute(self, task_name, payload, **kwargs):
                self.calls.append({"task": task_name, "intent": payload.get("intent")})
                return self.delegate.execute(task_name, payload, **kwargs)

        recorder = CallRecorder(self.executor)
        bank_path = self.run_directory / "six-tools-bank.sqlite3"
        bank = BankService(bank_path, executor=recorder)
        try:
            with sqlite3.connect(bank_path) as connection:
                original_transactions = list(connection.execute(
                    "SELECT transaction_id,user_id,account_id,amount_cents,category,occurred_at,status,kind FROM transactions ORDER BY transaction_id"
                ))
            balance = bank.propose({"intent": "query_balance", "params": {}})
            self.assertEqual(balance["status"], "success", balance)
            self.assertEqual(sum(row["balance_cents"] for row in balance["data"]["accounts"]), 1500000)
            transactions = bank.propose({"intent": "query_transactions", "params": {}})
            self.assertEqual(transactions["status"], "success", transactions)
            self.assertTrue(all(row["user_id"] == "alice" for row in transactions["data"]["transactions"]))
            bills = bank.propose({"intent": "analyze_bills", "params": {}})
            self.assertEqual(bills["status"], "success", bills)
            self.assertEqual(bills["data"]["actual_expense_cents"], 5970)

            subscriptions = bank.propose({"intent": "query_subscriptions", "params": {}})
            self.assertEqual(subscriptions["status"], "pending", subscriptions)
            self.assertNotIn("data", subscriptions)
            subscriptions = bank.confirm(subscriptions["request_id"], subscriptions["confirmation_code"])
            self.assertEqual(subscriptions["status"], "success", subscriptions)
            self.assertEqual(subscriptions["data"]["future_expected_cents"], 5970)

            cancellation = bank.propose({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}})
            self.assertEqual(cancellation["status"], "pending", cancellation)
            cancellation = bank.confirm(cancellation["request_id"], cancellation["confirmation_code"])
            self.assertEqual(cancellation["status"], "success", cancellation)

            transfer = bank.propose({"intent": "transfer", "params": {"account_id": "alice-main", "contact_id": "wang", "amount_cents": 10000}})
            self.assertEqual(transfer["status"], "pending", transfer)
            transfer = bank.confirm(transfer["request_id"], transfer["confirmation_code"])
            self.assertEqual(transfer["status"], "success", transfer)
            self.assertEqual(transfer["data"]["amount_cents"], 10000)
            self.assertEqual(transfer["data"]["daily_outgoing_cents"], 10000)
            self.assertEqual({call["intent"] for call in recorder.calls if call["task"] == "compute_tool"}, {
                "query_balance", "query_transactions", "analyze_bills", "query_subscriptions", "cancel_subscription", "transfer",
            })
            with sqlite3.connect(bank_path) as connection:
                balances = dict(connection.execute("SELECT account_id,balance_cents FROM accounts"))
                self.assertEqual(balances, {"alice-main": 990000, "alice-savings": 500000, "bob-main": 110000})
                self.assertEqual(connection.execute("SELECT status FROM subscriptions WHERE subscription_id='sub-video'").fetchone()[0], "cancelled")
                current_transactions = list(connection.execute(
                    "SELECT transaction_id,user_id,account_id,amount_cents,category,occurred_at,status,kind FROM transactions ORDER BY transaction_id"
                ))
                self.assertTrue(all(row in current_transactions for row in original_transactions))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers WHERE status='success'").fetchone()[0], 1)
            repeated = bank.confirm(transfer["request_id"], "000000")
            self.assertNotEqual(repeated["status"], "success")
            record_observation(self.id(), "six public tools delegated to actual isolated execution", recorder.calls)
        finally:
            bank.close()

    def test_18_bank_isolation_failure_keeps_mutations_and_dependencies_stopped(self):
        from src.bank import BankService

        def fail_started(event):
            if event.get("event") == "started":
                raise OSError("independent unavailable monitor")

        self.executor.close()
        for operation in ["cancel_subscription", "transfer", "dependent_plan"]:
            with self.subTest(operation=operation):
                monitor_path = self.run_directory / f"bank-failure-{operation}-monitor.sqlite3"
                bank_path = self.run_directory / f"isolation-failure-{operation}-bank.sqlite3"
                with self.executor_class(self.runtime, monitor_path, audit_hook=fail_started) as executor:
                    bank = BankService(bank_path, executor=executor)
                    try:
                        if operation == "dependent_plan":
                            failed = bank.propose({"steps": [
                                {"id": "bill", "intent": "analyze_bills", "params": {}, "depends_on": []},
                                {"id": "pay", "intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}, "depends_on": ["bill"]},
                            ]})
                            self.assertEqual(failed["plan"]["status"], "failed", failed)
                            steps = {step["id"]: step for step in failed["plan"]["steps"]}
                            self.assertEqual(steps["bill"]["status"], "failed")
                            self.assertNotIn(steps["pay"]["status"], {"success", "pending"})
                        else:
                            parameters = {"subscription_id": "sub-video"} if operation == "cancel_subscription" else {"contact_id": "wang", "amount_cents": 10000}
                            pending = bank.propose({"intent": operation, "params": parameters})
                            self.assertEqual(pending["status"], "pending", pending)
                            failed = bank.confirm(pending["request_id"], pending["confirmation_code"])
                        self.assertEqual(failed["status"], "failed", failed)
                        if operation != "dependent_plan":
                            self.assertEqual(failed["reason"], "isolation_failed", failed)
                        stopped = bank.propose({"intent": "query_balance", "params": {}})
                        self.assertEqual((stopped["status"], stopped["reason"]), ("failed", "audit_unavailable"), stopped)
                        with sqlite3.connect(bank_path) as connection:
                            self.assertEqual(dict(connection.execute("SELECT account_id,balance_cents FROM accounts")), {
                                "alice-main": 1000000, "alice-savings": 500000, "bob-main": 100000,
                            })
                            self.assertEqual(connection.execute("SELECT status FROM subscriptions WHERE subscription_id='sub-video'").fetchone()[0], "active")
                            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0], 0)
                            persisted_failures = connection.execute(
                                "SELECT request_id,user_id,intent,tier,event,result,reason FROM audit_log WHERE event='isolation_failed' ORDER BY id"
                            ).fetchall()
                            self.assertEqual(len(persisted_failures), 1)
                            request_id, user_id, intent, tier, event, result, reason = persisted_failures[0]
                            self.assertTrue(request_id)
                            self.assertEqual(user_id, "alice")
                            self.assertEqual(intent, "analyze_bills" if operation == "dependent_plan" else operation)
                            self.assertEqual(tier, "green" if operation == "dependent_plan" else "yellow")
                            self.assertEqual((event, result, reason), ("isolation_failed", "failed", "audit_unavailable"))
                            if operation != "dependent_plan":
                                self.assertEqual(request_id, failed["request_id"])
                            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_log WHERE event='executed' AND result='success'").fetchone()[0], 0)
                        # A halted Bank deliberately does not read audit storage.
                        # Its empty public receipt is not evidence of an empty DB.
                        self.assertEqual(bank.audit_events(), [])
                        record_observation(self.id(), "separate fresh failure fixture; business unchanged and later authorization stopped", {
                            "operation": operation, "initial_failure_status": failed["status"],
                            "initial_failure_reason": failed["reason"], "later_request_status": stopped["status"],
                            "later_request_reason": stopped["reason"], "business_unchanged": True,
                            "persistent_failure_log": {"event": event, "result": result, "reason": reason,
                                                       "intent": intent, "user_id": user_id, "request_id_present": bool(request_id)},
                            "successful_execution_log_count": 0,
                        })
                    finally:
                        bank.close()

    def test_19_business_audit_failure_rolls_back_real_isolated_transfer(self):
        from src.bank import BankService

        def fail_executed(event):
            if event.get("event") == "executed":
                raise OSError("independent business audit unavailable")

        bank_path = self.run_directory / "business-audit-failure-bank.sqlite3"
        bank = BankService(bank_path, executor=self.executor, audit_hook=fail_executed)
        try:
            pending = bank.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 10000}})
            self.assertEqual(pending["status"], "pending", pending)
            response = bank.confirm(pending["request_id"], pending["confirmation_code"])
            self.assertEqual((response["status"], response["reason"]), ("failed", "audit_unavailable"), response)
            with sqlite3.connect(bank_path) as connection:
                self.assertEqual(dict(connection.execute("SELECT account_id,balance_cents FROM accounts")), {
                    "alice-main": 1000000, "alice-savings": 500000, "bob-main": 100000,
                })
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_log WHERE event='executed' AND result='success'").fetchone()[0], 0)
            stopped = bank.propose({"intent": "query_balance", "params": {}})
            self.assertEqual((stopped["status"], stopped["reason"]), ("failed", "audit_unavailable"), stopped)
        finally:
            bank.close()

    def test_17_red_tier_remains_refused_after_synthetic_two_factors(self):
        from src.bank import BankService

        current_time = [datetime_module.datetime(2026, 10, 23, 12, 0, 0, tzinfo=datetime_module.timezone(datetime_module.timedelta(hours=8)))]
        bank_path = self.run_directory / "red-stays-refused-bank.sqlite3"
        bank = BankService(bank_path, clock=lambda: current_time[0], executor=self.executor)
        password = "Independent-Fake-Password-Only"
        secret_bytes = os.urandom(20)
        secret = base64.b32encode(secret_bytes).decode("ascii")

        def code_now():
            step = int(current_time[0].timestamp()) // 30
            digest = hmac.new(secret_bytes, struct.pack(">Q", step), hashlib.sha1).digest()
            offset = digest[-1] & 15
            binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
            return f"{binary % 1000000:06d}"

        try:
            enrollment = bank.enroll_strong_auth(password, secret, code_now())
            self.assertEqual(enrollment["status"], "success", enrollment)
            current_time[0] += datetime_module.timedelta(seconds=30)
            pending = bank.propose({"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100001}})
            self.assertEqual(pending["status"], "pending", pending)
            self.assertEqual(pending["tier"], "red")
            self.assertNotIn("confirmation_code", pending)
            response = bank.strong_verify(pending["request_id"], password, code_now(), confirmed=True)
            self.assertEqual(response["status"], "rejected", response)
            self.assertEqual(response["reason"], "isolation_unavailable", response)
            self.assertEqual(response["strong_verification"], "passed")
            with sqlite3.connect(bank_path) as connection:
                self.assertEqual(dict(connection.execute("SELECT account_id,balance_cents FROM accounts")), {
                    "alice-main": 1000000, "alice-savings": 500000, "bob-main": 100000,
                })
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0], 0)
            serialized = json.dumps(bank.audit_events(), ensure_ascii=False)
            self.assertNotIn(password, serialized)
            self.assertNotIn(secret, serialized)
        finally:
            bank.close()


# Linux-specific boundary tests are added after the new public contract is
# frozen. No Linux metadata names are inferred from backend implementation.


def main() -> int:
    started_at = datetime_module.datetime.now(datetime_module.timezone.utc)
    started_monotonic = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult)
    result = runner.run(suite)
    evidence_directory = PROJECT_DIRECTORY / "evidence"
    evidence_directory.mkdir(parents=True, exist_ok=True)
    timestamp = started_at.strftime("%Y%m%d-%H%M%S-%f")
    evidence_path = evidence_directory / f"docker-isolation-independent-{timestamp}.json"
    evidence = {
        "test_revision": 3,
        "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "public_docker_contract_sha256": hashlib.sha256((PROJECT_DIRECTORY / "src" / "DOCKER_ISOLATION_API.md").read_bytes()).hexdigest(),
        "first_round_evidence": "evidence/docker-isolation-independent-20261024-045404-972771.json",
        "previous_round_evidence": ["evidence/docker-isolation-independent-20261024-045404-972771.json", "evidence/docker-isolation-independent-20261024-050142-394790.json"],
        "revision_reason": "Public contract clarifies that stopped Bank.audit_events returns an empty receipt; verify real failure event/result/underlying reason directly in the public audit_log table, including user, intent, tier and request binding, while requiring no successful execution log and preserved audit-stop behavior. Earlier fixture, Docker NONE semantics and daemon reachability corrections remain in place.",
        "author": "independent acceptance sub-agent; no implementation read",
        "executor": "implementation/root agent in authorized host environment",
        "scope": "new Linux Docker contract, not a repair of Windows evidence",
        "started_at_utc": started_at.isoformat(),
        "ended_at_utc": datetime_module.datetime.now(datetime_module.timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful() and result.testsRun > 0,
        "failure_count": len(result.failures),
        "error_count": len(result.errors),
        "skip_count": len(result.skipped),
        "run_directory": str(RUN_DIRECTORY) if RUN_DIRECTORY else None,
        "case_results": result.case_results,
        "observations": OBSERVATIONS,
        "limitations": [
            "No real bank, real funds, real model call or real MFA device used.",
            "Human phone/terminal and teammate acceptance remain separate.",
            "Passing Docker checks never authorizes red-tier execution.",
        ],
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Independent evidence: {evidence_path}")
    return 0 if evidence["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

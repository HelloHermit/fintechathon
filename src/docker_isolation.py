"""Pinned Linux Docker worker with a read-back policy and independent watchdog.

Only the trusted host imports this module. Nothing here accepts a shell command,
model program, SQL, credentials, or a Docker context from worker input. Docker
Desktop and its local daemon remain trusted; this is not Windows LPAC.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid


MECHANISM = "docker-linux-readonly-v2"
NAMESPACE_LABEL = "com.fintechathon.isolation"
IDENTITY_LABEL = "com.fintechathon.package"
TASK_LABEL = "com.fintechathon.task"
LOCAL_HOST = "npipe:////./pipe/dockerDesktopLinuxEngine"
DEFAULT_LIMITS = {"wall_seconds": 5.0, "cpu_seconds": 1.0,
                  "cpu_rate_percent": 20, "memory_bytes": 128 * 1024 * 1024,
                  "output_bytes": 65536, "process_count": 1}
MINIMUM_LIMITS = {"wall_seconds": .2, "cpu_seconds": 1.0,
                  "cpu_rate_percent": 1, "memory_bytes": 32 * 1024 * 1024,
                  "output_bytes": 1024, "process_count": 1}
CLI_TIMEOUT = 4.0
SETUP_LEASE = 25.0
SHANGHAI = timezone(timedelta(hours=8))


class _PolicyFailure(Exception):
    """A fixed reason only, never arbitrary daemon output or exception text."""

    def __init__(self, reason="isolation_unavailable"):
        self.reason = reason
        super().__init__(reason)


def _now():
    return datetime.now(SHANGHAI).isoformat()


def _limits(values):
    if type(values) is not dict or set(values) != set(DEFAULT_LIMITS):
        raise _PolicyFailure("invalid_input")
    for name, value in values.items():
        types = (int, float) if name.endswith("seconds") else (int,)
        if (type(value) not in types or not math.isfinite(value) or
                not MINIMUM_LIMITS[name] <= value <= DEFAULT_LIMITS[name]):
            raise _PolicyFailure("invalid_input")
    return dict(values)


def _safe_environment(config_directory):
    # No PATH, proxy, model key, Docker context or caller's HOME is inherited.
    environment = {name: os.environ[name] for name in ("SystemRoot", "windir", "SystemDrive")
                   if name in os.environ}
    environment.update(HOME=str(config_directory), USERPROFILE=str(config_directory),
                       TEMP=str(config_directory), TMP=str(config_directory))
    return environment


def _hidden_flags():
    return (getattr(subprocess, "CREATE_NO_WINDOW", 0) |
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


class _Capture:
    """Retain at most the shared cap, including stderr, while pipes drain."""

    def __init__(self, maximum):
        self.maximum = maximum
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.lock = threading.Lock()
        self.full = threading.Event()
        self.failed = threading.Event()

    def reader(self, pipe, stream):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    break
                with self.lock:
                    available = self.maximum - len(self.stdout) - len(self.stderr)
                    stream.extend(chunk[:available])
                    if len(chunk) >= available:
                        self.full.set()
        except (OSError, ValueError):
            self.failed.set()

    def threads(self, process):
        result = []
        for pipe, destination in ((process.stdout, self.stdout), (process.stderr, self.stderr)):
            thread = threading.Thread(target=self.reader, args=(pipe, destination), daemon=True)
            thread.start()
            result.append(thread)
        return result


class DockerBackend:
    """One new, immutable, non-root, offline container per trusted task."""

    def __init__(self, runtime_directory, config):
        self.runtime_directory = Path(runtime_directory).resolve()
        self.config = dict(config)
        self.executable = Path(self.config["docker_executable"])
        self.config_directory = Path(self.config["docker_config_directory"]).resolve()
        self.host = self.config["docker_host"]
        self.image = self.config["image_id"]
        self.package_name = self.config["package_name"]
        if (os.name != "nt" or not self.executable.is_absolute() or not self.executable.is_file() or
                self.host != LOCAL_HOST or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image) or
                not re.fullmatch(r"(?:FinTechathon\.Worker\.)?[0-9a-f]{32}", self.package_name) or
                not self.runtime_directory.is_dir() or not self.config_directory.is_dir() or
                self.config_directory.is_relative_to(self.runtime_directory) or
                self.runtime_directory.is_relative_to(self.config_directory) or
                any(character in str(self.runtime_directory) for character in ",\r\n\x00")):
            raise ValueError("unavailable Docker policy")
        self._check_config_directory()
        self.environment = _safe_environment(self.config_directory)

    def _check_config_directory(self):
        # Even a harmless existing config could select credential/plugin hooks.
        if any(self.config_directory.iterdir()):
            raise _PolicyFailure()

    def _argv(self, arguments):
        return [str(self.executable), "--host", self.host,
                "--config", str(self.config_directory), *arguments]

    def _popen(self, arguments, *, stdin=subprocess.DEVNULL):
        self._check_config_directory()
        return subprocess.Popen(self._argv(arguments), stdin=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=self.environment, shell=False,
                                close_fds=True, creationflags=_hidden_flags())

    def _command(self, arguments, timeout=CLI_TIMEOUT, maximum=262144, cancel_event=None):
        """Bound CLI wall time and bytes too; communicate() would be unbounded."""
        if timeout <= 0:
            raise _PolicyFailure()
        process = self._popen(arguments)
        capture = _Capture(maximum)
        threads = capture.threads(process)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    raise _PolicyFailure("cancelled")
                if time.monotonic() >= deadline or capture.full.is_set():
                    process.kill()
                    raise _PolicyFailure()
                time.sleep(.01)
            for thread in threads:
                thread.join(max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads) or capture.full.is_set() or capture.failed.is_set():
                raise _PolicyFailure()
            return process.returncode, bytes(capture.stdout), bytes(capture.stderr)
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=max(0, min(.1, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            process.stdout.close()
            process.stderr.close()

    def _inspect(self, name, timeout=CLI_TIMEOUT, cancel_event=None):
        code, output, _ = self._command(["inspect", "--type", "container", name], timeout,
                                        cancel_event=cancel_event)
        if code:
            raise _PolicyFailure()
        try:
            value = json.loads(output)
        except (ValueError, UnicodeError):
            raise _PolicyFailure() from None
        if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
            raise _PolicyFailure()
        return value[0]

    def _own(self, value, name):
        labels = value.get("Config", {}).get("Labels", {})
        return (value.get("Name") == "/" + name and type(labels) is dict and
                labels.get(NAMESPACE_LABEL) == MECHANISM and
                labels.get(IDENTITY_LABEL) == self.package_name and
                labels.get(TASK_LABEL) == name.removeprefix("fintech-worker-"))

    def _owned_id(self, value, name):
        identifier = value.get("Id")
        if not self._own(value, name) or type(identifier) is not str or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise _PolicyFailure()
        return identifier

    def _source_matches(self, source):
        if type(source) is not str:
            return False
        normal = source.replace("\\", "/").rstrip("/")
        expected = self.runtime_directory.as_posix().rstrip("/")
        mapped = "/run/desktop/mnt/host/" + expected[0].lower() + expected[2:]
        return normal.casefold() in {expected.casefold(), mapped.casefold()}

    def _verify(self, value, name, script, limits, image_environment):
        """Reject unexpected privileges before any worker instruction executes."""
        host = value.get("HostConfig", {})
        config = value.get("Config", {})
        state = value.get("State", {})
        expected_command = ["-I", "-S", "-B", "/runtime/supervisor.py", "--wall",
                            str(float(limits["wall_seconds"])), "--script", script]
        ulimits = {row.get("Name"): (row.get("Soft"), row.get("Hard"))
                   for row in host.get("Ulimits", []) if type(row) is dict}
        mounts = value.get("Mounts", [])
        host_mounts = host.get("Mounts", [])
        checks = {
            "owned_identity": self._own(value, name),
            "pinned_image": value.get("Image") == self.image and config.get("Image") == self.image,
            "not_started": state.get("Running") is False and state.get("Pid") == 0,
            "non_root": config.get("User") == "65534:65534",
            "fixed_entrypoint": config.get("Entrypoint") == ["/usr/local/bin/python3"],
            "fixed_arguments": config.get("Cmd") == expected_command,
            "no_host_environment": config.get("Env") == image_environment,
            "fixed_workdir": config.get("WorkingDir") == "/",
            "no_network": host.get("NetworkMode") == "none",
            "read_only_root": host.get("ReadonlyRootfs") is True,
            "no_capabilities": host.get("CapDrop") == ["ALL"] and not host.get("CapAdd"),
            "no_new_privileges": host.get("SecurityOpt") == ["no-new-privileges=true"],
            "no_privileged": host.get("Privileged") is False,
            "one_supervisor_one_worker": host.get("PidsLimit") == 2,
            "memory": host.get("Memory") == limits["memory_bytes"] == host.get("MemorySwap"),
            "cpu_rate": host.get("NanoCpus") == limits["cpu_rate_percent"] * 10000000,
            "cpu_seconds": ulimits.get("cpu") == (1, 1),
            "file_size": ulimits.get("fsize") == (16777216, 16777216) and len(ulimits) == 2,
            "private_namespaces": host.get("IpcMode") == "none" and
                host.get("PidMode") == "" and host.get("UTSMode") == "" and
                host.get("UsernsMode") == "" and host.get("CgroupnsMode") == "private",
            "no_host_cgroup": not host.get("CgroupParent"),
            "default_linux_runtime": host.get("Runtime") == "runc" and host.get("Isolation") == "",
            "no_supplementary_groups": not host.get("GroupAdd"),
            "oom_kill_enabled": host.get("OomKillDisable") is False,
            "no_extra_resources": not any(host.get(key) for key in
                ("Binds", "VolumesFrom", "Devices", "DeviceRequests", "DeviceCgroupRules",
                 "ExtraHosts", "PortBindings", "Links", "Dns", "DnsOptions", "DnsSearch")),
            "no_published_ports": host.get("PublishAllPorts") is False and not config.get("ExposedPorts"),
            "no_logs": host.get("LogConfig") == {"Type": "none", "Config": {}},
            "tmpfs": host.get("Tmpfs") == {"/tmp": "rw,noexec,nosuid,nodev,size=16m,mode=1777"},
            "no_healthcheck": config.get("Healthcheck") == {"Test": ["NONE"]},
            "no_automatic_restart": host.get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0},
            "no_automatic_remove": host.get("AutoRemove") is False,
            "stdin_only": config.get("OpenStdin") is True and config.get("Tty") is False,
            "runtime_mount": len(mounts) == 1 and mounts[0].get("Type") == "bind" and
                mounts[0].get("Destination") == "/runtime" and mounts[0].get("RW") is False and
                mounts[0].get("Propagation") == "rprivate" and self._source_matches(mounts[0].get("Source")),
            "requested_mount": len(host_mounts) == 1 and host_mounts[0].get("Type") == "bind" and
                host_mounts[0].get("Target") == "/runtime" and host_mounts[0].get("ReadOnly") is True and
                self._source_matches(host_mounts[0].get("Source")),
        }
        if not all(checks.values()):
            failure = _PolicyFailure("identity_mismatch")
            failure.checks = checks
            raise failure
        return checks

    def _create_arguments(self, name, script, limits):
        return ["create", "--name", name, "--label", NAMESPACE_LABEL + "=" + MECHANISM,
                "--label", IDENTITY_LABEL + "=" + self.package_name,
                "--label", TASK_LABEL + "=" + name.removeprefix("fintech-worker-"),
                "--pull", "never", "-i", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges=true",
                "--user", "65534:65534", "--pids-limit", "2",
                "--memory", str(limits["memory_bytes"]), "--memory-swap", str(limits["memory_bytes"]),
                "--cpus", str(limits["cpu_rate_percent"] / 100), "--ulimit", "cpu=1:1",
                "--ulimit", "fsize=16777216:16777216", "--ipc", "none", "--cgroupns", "private",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                "--log-driver", "none", "--no-healthcheck", "--workdir", "/",
                "--mount", "type=bind,source=" + str(self.runtime_directory) + ",target=/runtime,readonly",
                "--entrypoint", "/usr/local/bin/python3", self.image, "-I", "-S", "-B",
                "/runtime/supervisor.py", "--wall", str(float(limits["wall_seconds"])), "--script", script]

    def _watchdog(self, name, wall_seconds, cancel_event=None):
        data = {key: self.config[key] for key in ("docker_executable", "docker_config_directory",
                "docker_host", "image_id", "package_name")}
        data.update(runtime_directory=str(self.runtime_directory), name=name, wall_seconds=wall_seconds)
        encoded = base64.urlsafe_b64encode(json.dumps(data).encode("ascii")).decode("ascii")
        process = subprocess.Popen([str(Path(sys.executable).resolve()), "-I", "-S", "-B",
                                    str(Path(__file__).resolve()), "--watchdog", encoded],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, close_fds=True, shell=False,
                                   env=self.environment, creationflags=_hidden_flags())
        messages = queue.Queue(maxsize=16)
        def read_messages():
            try:
                while True:
                    line = process.stdout.readline(80)
                    if not line:
                        break
                    messages.put_nowait(line.strip())
            except (OSError, ValueError, queue.Full):
                pass
        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 2
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise _PolicyFailure("cancelled")
                if time.monotonic() >= deadline:
                    raise _PolicyFailure()
                try:
                    message = messages.get(timeout=.02)
                except queue.Empty:
                    continue
                if message != b"READY":
                    raise _PolicyFailure()
                break
        except _PolicyFailure:
            process.stdin.close()
            # No create has been issued yet, so terminating this failed
            # handshake cannot remove the only backstop for a container.
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
            process.stdout.close()
            raise
        return process, messages, reader

    def run(self, script_path, input_bytes, limits, cancel_event=None):
        started = time.monotonic()
        metadata = {"mechanism": MECHANISM, "pid": None, "linux_pid": None,
                    "scope": "docker_desktop_linux_vm", "linux_pid_scope": "docker_desktop_linux_vm",
                    "host_attach_pid": None, "watchdog_pid": None, "start": _now(), "end": None,
                    "wall_ms": 0, "setup_ms": 0, "execution_ms": 0, "cleanup_ms": 0,
                    "cpu_ms": None, "peak_job_memory_bytes": None, "worker_started": False,
                    "active_processes_after": 0, "cleanup_complete": True,
                    "termination": "not_started", "startup_stage": "validating_input",
                    "watchdog_armed": False, "daemon_policy_verified": False}
        result = {"status": "failed", "reason": "isolation_unavailable", "stdout": b"",
                  "stderr": b"", "exit_code": None, "metadata": metadata}
        name = "fintech-worker-" + uuid.uuid4().hex
        watchdog = messages = watchdog_reader = attach = capture = None
        sampler = None
        io_threads = []
        created = attempted_create = False
        execution_started = None
        last_state = None
        try:
            limits = _limits(limits)
            if cancel_event is not None and cancel_event.is_set():
                raise _PolicyFailure("cancelled")
            if type(input_bytes) is not bytes or len(input_bytes) > 65536:
                raise _PolicyFailure("invalid_input")
            path = Path(script_path).resolve()
            relative = path.relative_to(self.runtime_directory).as_posix()
            if (relative != "worker.py" and not re.fullmatch(r"tasks/[0-9a-f]{32}\.py", relative)) or not path.is_file():
                raise _PolicyFailure("invalid_input")
            script = "/runtime/" + relative
            metadata["limits"] = dict(limits)
            metadata["container_name"] = name
            metadata["startup_stage"] = "checking_image"
            code, output, _ = self._command(["image", "inspect", self.image], cancel_event=cancel_event)
            image = json.loads(output) if code == 0 else None
            if (type(image) is not list or len(image) != 1 or image[0].get("Id") != self.image or
                    image[0].get("Os") != "linux" or image[0].get("Architecture") != "amd64"):
                raise _PolicyFailure()
            image_environment = image[0].get("Config", {}).get("Env")
            if type(image_environment) is not list or any(type(value) is not str for value in image_environment):
                raise _PolicyFailure()
            watchdog, messages, watchdog_reader = self._watchdog(name, limits["wall_seconds"], cancel_event)
            metadata["watchdog_pid"] = watchdog.pid
            metadata["startup_stage"] = "creating_container"
            attempted_create = True
            code, output, _ = self._command(self._create_arguments(name, script, limits), cancel_event=cancel_event)
            if code or not re.fullmatch(rb"[0-9a-f]{64}\s*", output):
                raise _PolicyFailure("start_failed")
            created = True
            metadata["container_id"] = output.strip().decode("ascii")
            metadata["startup_stage"] = "verifying_daemon_policy"
            value = self._inspect(name, cancel_event=cancel_event)
            if self._owned_id(value, name) != metadata["container_id"]:
                raise _PolicyFailure("identity_mismatch")
            metadata["policy_checks"] = self._verify(value, name, script, limits, image_environment)
            metadata["daemon_policy_verified"] = True
            metadata["daemon_image_id"] = value["Image"]
            if cancel_event is not None and cancel_event.is_set():
                raise _PolicyFailure("cancelled")
            watchdog.stdin.write(b"A")
            watchdog.stdin.flush()
            handshake_deadline = time.monotonic() + 1
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise _PolicyFailure("cancelled")
                if time.monotonic() >= handshake_deadline:
                    raise _PolicyFailure()
                try:
                    message = messages.get(timeout=.02)
                except queue.Empty:
                    continue
                if message != b"ARMED":
                    raise _PolicyFailure()
                break
            metadata["watchdog_armed"] = True
            execution_started = time.monotonic()
            metadata["setup_ms"] = round((execution_started - started) * 1000, 3)
            metadata["startup_stage"] = "starting_container"
            attach = self._popen(["start", "--attach", "--interactive", name], stdin=subprocess.PIPE)
            metadata["host_attach_pid"] = attach.pid
            capture = _Capture(limits["output_bytes"])
            io_threads = capture.threads(attach)
            def feed_input():
                try:
                    attach.stdin.write(input_bytes)
                    attach.stdin.close()
                except (OSError, ValueError):
                    pass
            feeder = threading.Thread(target=feed_input, daemon=True)
            feeder.start()
            io_threads.append(feeder)
            def sample_running_state():
                try:
                    current = self._inspect(name, min(.6, limits["wall_seconds"]))
                    if self._own(current, name):
                        current_state = current.get("State", {})
                        actual_pid = current_state.get("Pid")
                        if current_state.get("Running") is True and type(actual_pid) is int and actual_pid > 0:
                            metadata["linux_pid"] = actual_pid
                            metadata["linux_pid_scope"] = "docker_desktop_linux_vm"
                            metadata["container_started"] = True
                except (_PolicyFailure, OSError, ValueError, TypeError):
                    pass  # Optional observation; pre-start policy was mandatory.
            sampler = threading.Thread(target=sample_running_state, daemon=True)
            sampler.start()
            deadline = execution_started + limits["wall_seconds"]
            reason = "ok"
            while attach.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    reason = "cancelled"
                    break
                if capture.full.is_set():
                    reason = "output_limit"
                    break
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                if watchdog.poll() is not None:
                    reason = "isolation_unavailable"
                    break
                time.sleep(.01)
            if capture.full.is_set():
                reason = "output_limit"
            metadata["termination"] = reason
            result.update(status="cancelled" if reason == "cancelled" else "failed", reason=reason)
        except _PolicyFailure as error:
            result.update(status="cancelled" if error.reason == "cancelled" else "failed", reason=error.reason)
            if hasattr(error, "checks"):
                metadata["policy_checks"] = error.checks
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            result.update(status="failed", reason="isolation_unavailable")
        finally:
            cleanup_started = time.monotonic()
            cleanup_deadline = cleanup_started + 2.0
            def remaining_cleanup():
                remaining = cleanup_deadline - time.monotonic()
                if remaining <= 0:
                    raise _PolicyFailure()
                return remaining
            if execution_started is not None:
                metadata["execution_ms"] = round((cleanup_started - execution_started) * 1000, 3)
            # The watchdog's original independent lease remains active until we
            # prove the container is stopped and removed. Closing stdin early
            # also causes it to kill a surviving owned container.
            if watchdog is not None and watchdog.stdin and not watchdog.stdin.closed:
                try:
                    watchdog.stdin.close()
                except OSError:
                    pass
            if attempted_create:
                try:
                    value = self._inspect(metadata.get("container_id", name), remaining_cleanup())
                    identifier = self._owned_id(value, name)
                    if metadata.get("container_id", identifier) != identifier:
                        raise _PolicyFailure()
                    if value.get("State", {}).get("Running") is True:
                        self._command(["kill", "--signal", "KILL", identifier],
                                      remaining_cleanup())
                        value = self._inspect(identifier, remaining_cleanup())
                        if self._owned_id(value, name) != identifier:
                            raise _PolicyFailure()
                    state = value.get("State", {})
                    last_state = state
                    stopped = state.get("Running") is False and state.get("Pid") == 0
                    metadata["active_processes_after"] = 0 if stopped else None
                    metadata["container_running_after"] = state.get("Running")
                    metadata["container_pid_after"] = state.get("Pid")
                    metadata["oom_killed"] = state.get("OOMKilled")
                    metadata["daemon_exit_code"] = state.get("ExitCode")
                    result["exit_code"] = state.get("ExitCode")
                    started_at = state.get("StartedAt")
                    if type(started_at) is str and started_at and not started_at.startswith("0001-"):
                        metadata["worker_started"] = True
                        metadata["container_started"] = True
                    if not stopped:
                        raise _PolicyFailure()
                    code, _, _ = self._command(["rm", identifier], remaining_cleanup())
                    if code:
                        raise _PolicyFailure()
                    # Successful daemon removal itself confirms this ID is gone.
                    metadata["container_removed"] = True
                    metadata["cleanup_complete"] = True
                except (_PolicyFailure, OSError, ValueError, TypeError):
                    metadata["cleanup_complete"] = False
                    metadata["active_processes_after"] = None
            if attach is not None:
                if attach.poll() is None:
                    attach.kill()
                try:
                    attach.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    metadata["cleanup_complete"] = False
                for thread in io_threads:
                    thread.join(max(0, cleanup_deadline - time.monotonic()))
                if any(thread.is_alive() for thread in io_threads):
                    metadata["cleanup_complete"] = False
                for pipe in (attach.stdin, attach.stdout, attach.stderr):
                    if pipe is not None:
                        try:
                            pipe.close()
                        except OSError:
                            pass
            if watchdog is not None:
                try:
                    watchdog.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    # A watchdog still checking the daemon is retained, never
                    # killed here, because it is the orphan backstop.
                    metadata["cleanup_complete"] = False
                if watchdog_reader is not None:
                    watchdog_reader.join(max(0, cleanup_deadline - time.monotonic()))
                if watchdog.poll() is not None:
                    watchdog.stdout.close()
                metadata["watchdog_exit_code"] = watchdog.poll()
            if sampler is not None:
                sampler.join(max(0, cleanup_deadline - time.monotonic()))
                if sampler.is_alive():
                    metadata["cleanup_complete"] = False
            if capture is not None:
                with capture.lock:
                    result["stdout"], result["stderr"] = bytes(capture.stdout), bytes(capture.stderr)
                if capture.full.is_set():
                    result.update(status="failed", reason="output_limit")
                elif capture.failed.is_set():
                    result.update(status="failed", reason="isolation_unavailable")
            if not metadata["cleanup_complete"]:
                result.update(status="failed", reason="isolation_unavailable")
            elif execution_started is not None and result["reason"] == "ok" and last_state is not None:
                exit_code = last_state.get("ExitCode")
                if last_state.get("OOMKilled") is True:
                    result.update(status="failed", reason="memory_limit")
                elif exit_code == 0:
                    result.update(status="success", reason="ok")
                elif exit_code == 124:
                    result.update(status="failed", reason="timeout")
                else:
                    result.update(status="failed", reason="nonzero_exit")
            metadata["cleanup_ms"] = round((time.monotonic() - cleanup_started) * 1000, 3)
            metadata["wall_ms"] = round((time.monotonic() - started) * 1000, 3)
            metadata["end"] = _now()
        return result


def _watchdog_main(encoded):
    """Separate trusted process: an EOF or fixed deadline kills only our name."""
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded))
        backend = DockerBackend(data["runtime_directory"], data)
        name = data["name"]
        wall = data["wall_seconds"]
        if not re.fullmatch(r"fintech-worker-[0-9a-f]{32}", name) or not .2 <= wall <= 5:
            return 2
        commands = queue.Queue(maxsize=4)
        def read_commands():
            try:
                while True:
                    value = sys.stdin.buffer.read(1)
                    commands.put(value)
                    if not value:
                        break
            except (OSError, ValueError):
                commands.put(b"")
        threading.Thread(target=read_commands, daemon=True).start()
        print("READY", flush=True)
        deadline = time.monotonic() + SETUP_LEASE
        armed = False
        while time.monotonic() < deadline:
            try:
                command = commands.get(timeout=min(.02, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if command == b"A" and not armed:
                armed = True
                deadline = time.monotonic() + wall
                print("ARMED", flush=True)
            else:
                break
        # Inspection is essential: never kill an unrelated container merely
        # because its name happens to match. The UUID and three labels bind it.
        try:
            value = backend._inspect(name, 1.0)
            identifier = backend._owned_id(value, name)
            if value.get("State", {}).get("Running"):
                backend._command(["kill", "--signal", "KILL", identifier], 1.0)
            return 0
        except (_PolicyFailure, OSError):
            # Parent may already have removed it. This is not a cleanup claim;
            # parent separately requires stopped read-back and daemon rm success.
            return 4
    except (OSError, ValueError, TypeError, KeyError):
        return 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--watchdog":
        raise SystemExit(_watchdog_main(sys.argv[2]))
    raise SystemExit(2)

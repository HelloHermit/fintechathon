"""可信监控器：持久化回执、验证配置、调用真实Windows隔离后端。"""

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from .windows_isolation import WindowsBackend, query_profile_folder


SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_LIMITS = {"wall_seconds": 5.0, "cpu_seconds": 1.0, "cpu_rate_percent": 20,
                  "memory_bytes": 128 * 1024 * 1024, "output_bytes": 65536, "process_count": 1}
MINIMUM_LIMITS = {"wall_seconds": 0.2, "cpu_seconds": 0.1, "cpu_rate_percent": 1,
                  "memory_bytes": 32 * 1024 * 1024, "output_bytes": 1024, "process_count": 1}
SAFE_REASONS = {"ok", "invalid_task", "invalid_input", "isolation_unavailable", "start_failed", "identity_mismatch",
                "nonzero_exit", "timeout", "cpu_limit", "memory_limit", "output_limit", "invalid_output",
                "cancelled", "audit_unavailable", "result_mismatch"}
AUDIT_TRIGGERS = {
    "isolation_no_update": "CREATE TRIGGER isolation_no_update BEFORE UPDATE ON isolation_audit BEGIN SELECT RAISE(ABORT,'append only'); END",
    "isolation_no_delete": "CREATE TRIGGER isolation_no_delete BEFORE DELETE ON isolation_audit BEGIN SELECT RAISE(ABORT,'append only'); END",
}


def checked_monitor_schema(connection):
    """旧监控库必须保持完整追加约束，未知表或被替换的触发器不自动修补。"""
    columns = connection.execute("PRAGMA table_info(isolation_audit)").fetchall()
    expected = [("id", "INTEGER", 0, 1)] + [(name, "TEXT", 1, 0) for name in
                ("timestamp", "task_id", "request_id", "event", "status", "reason", "metadata_json")]
    if [(row[1], row[2].upper(), row[3], row[5]) for row in columns] != expected:
        raise IsolationError("isolation_unavailable")
    triggers = {row[0]: row[1] for row in connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='isolation_audit'")}
    normalize = lambda sql: re.sub(r"\s+", "", sql).casefold().replace("ifnotexists", "")
    if set(triggers) != set(AUDIT_TRIGGERS) or any(
            normalize(triggers[name]) != normalize(definition)
            for name, definition in AUDIT_TRIGGERS.items()):
        raise IsolationError("isolation_unavailable")


class IsolationError(RuntimeError):
    """只携带固定原因和安全元数据；不展示输入、输出或任意异常文本。"""
    def __init__(self, reason="isolation_unavailable", metadata=None):
        self.reason = reason if reason in SAFE_REASONS else "isolation_unavailable"
        self.code = "isolation_failed"
        self.metadata = metadata or {}
        super().__init__("受限执行未完成，未授权办理业务。")


def strict_json(raw_text):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError("non-finite number")
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return value
    return json.loads(raw_text, object_pairs_hook=unique_object, parse_constant=reject_constant,
                      parse_float=finite_float)


def checked_limits(supplied):
    values = dict(DEFAULT_LIMITS)
    if supplied is None:
        return values
    if type(supplied) is not dict or set(supplied) - set(values):
        raise IsolationError("invalid_input")
    for name, value in supplied.items():
        expected_type = (int, float) if name.endswith("seconds") else (int,)
        if type(value) not in expected_type or not MINIMUM_LIMITS[name] <= value <= DEFAULT_LIMITS[name]:
            raise IsolationError("invalid_input")
        values[name] = value
    return values


def checked_runtime(directory, *, preparing_profile=False):
    """验证受信配置与固定运行时字节；不相信worker自报的环境。"""
    try:
        if os.name != "nt":
            raise ValueError("unsupported OS")
        directory = Path(directory).absolute()
        for ancestor in (directory, *directory.parents):
            if ancestor.is_symlink() or ancestor.stat().st_file_attributes & 0x400:
                raise ValueError("reparse directory")
        config_path = directory / "isolation-config.json"
        if config_path.is_symlink() or config_path.stat().st_file_attributes & 0x400 or config_path.stat().st_size > 65536:
            raise ValueError("config too large")
        config = strict_json(config_path.read_text(encoding="utf-8"))
        policy = config.get("policy_version")
        if policy not in {"windows-lpac-job-v1", "docker-linux-readonly-v2"}:
            raise ValueError("unknown policy")
        if not re.fullmatch(r"FinTechathon\.Worker\.[0-9a-f]{32}", config["package_name"]):
            raise ValueError("invalid moniker")
        if policy == "windows-lpac-job-v1" and type(config.get("profile_created")) is not bool:
            raise ValueError("invalid profile policy")
        if policy == "windows-lpac-job-v1" and config["profile_created"]:
            if not preparing_profile and config.get("profile_files_read_only") is not True:
                raise ValueError("unrestricted profile files")
            actual_profile = query_profile_folder(config["package_name"])
            if not actual_profile or Path(actual_profile).resolve() != Path(config["profile_directory"]).resolve():
                raise ValueError("profile belongs to another user or is missing")
        elif policy == "windows-lpac-job-v1" and not preparing_profile:
            raise ValueError("explicit read-only profile setup is required")
        hashes = config["files_sha256"]
        if policy == "windows-lpac-job-v1":
            version_match = re.fullmatch(r"(\d+)\.(\d+)\.\d+", config["python_version"])
            if not version_match:
                raise ValueError("unsupported Python version")
            version = "python" + version_match[1] + version_match[2]
            required = {"python.exe", "worker.py", version + ".dll", version + ".zip", version + "._pth"}
        else:
            required = {"worker.py", "supervisor.py"}
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", config["image_id"]):
                raise ValueError("unpinned image")
            if config["docker_host"] != "npipe:////./pipe/dockerDesktopLinuxEngine":
                raise ValueError("nonlocal daemon")
            executable = Path(config["docker_executable"])
            if (not executable.is_absolute() or executable.is_symlink()
                    or executable.stat().st_file_attributes & 0x400
                    or hashlib.sha256(executable.read_bytes()).hexdigest() != config["docker_executable_sha256"]):
                raise ValueError("docker client changed")
        if type(hashes) is not dict or not required <= set(hashes):
            raise ValueError("incomplete runtime")
        for name, expected in hashes.items():
            relative = Path(name)
            path = directory / relative
            if relative.is_absolute() or ".." in relative.parts or ":" in name or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("unsafe name")
            for ancestor in (path, *path.parents):
                if ancestor == directory:
                    break
                if ancestor.is_symlink() or ancestor.stat().st_file_attributes & 0x400:
                    raise ValueError("reparse file")
            if type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("invalid fingerprint")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("runtime changed")
        actual_files = set()
        for current, folders, files in os.walk(directory, followlinks=False):
            for name in folders + files:
                path = Path(current) / name
                if path.is_symlink() or path.stat().st_file_attributes & 0x400:
                    raise ValueError("reparse runtime entry")
            for name in files:
                relative = (Path(current) / name).relative_to(directory)
                if relative.parts[0] != "tasks":
                    actual_files.add(relative.as_posix())
        if actual_files != set(hashes) | {"isolation-config.json"}:
            raise ValueError("unknown runtime file")
        return directory, config
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise IsolationError("isolation_unavailable") from None


class IsolatedExecutor:
    """每次任务用新的受限进程；监控审计失败时停止，不回退普通执行。"""
    def __init__(self, runtime_directory, monitor_database, *, limits=None, audit_hook=None):
        self._runtime_directory, self.config = checked_runtime(runtime_directory)
        self._readable_directories = (self.runtime_directory,)
        if self.config.get("profile_created"):
            self._readable_directories += (Path(self.config["profile_directory"]).resolve().parent,)
        self.limits = checked_limits(limits)
        if self.config.get("policy_version") == "docker-linux-readonly-v2" and self.limits["cpu_seconds"] != 1:
            raise IsolationError("invalid_input")
        self.audit_hook = audit_hook
        self.halted = False
        self.closed = False
        self.quarantined = False
        self.retained_runtime_lease = None
        self.last_receipt = None
        self.current_cancel = threading.Event()
        self.execution_lock = threading.Lock()
        self.audit_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self._database_path = Path(monitor_database).absolute()
        self.connection = None
        self.lease_file = None
        if Path(str(self._runtime_lock_path()) + ".quarantine").exists():
            raise IsolationError("isolation_unavailable")
        if any(self.database_path.resolve().is_relative_to(directory.resolve())
               for directory in self.readable_directories):
            raise IsolationError("invalid_input")
        lock_path = Path(str(self.database_path) + ".lock")
        if any(path.exists() and path.stat().st_nlink > 1
               for path in (self.database_path, lock_path)):
            raise IsolationError("invalid_input")
        try:
            import msvcrt
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.lease_file = open(str(self.database_path) + ".lock", "a+b")
            if self.lease_file.tell() == 0:
                self.lease_file.write(b"0")
                self.lease_file.flush()
            self.lease_file.seek(0)
            msvcrt.locking(self.lease_file.fileno(), msvcrt.LK_NBLCK, 1)
            self.connection = sqlite3.connect(self.database_path, timeout=2, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {"isolation_audit", "sqlite_sequence"}:
                raise IsolationError("invalid_input")
            if "isolation_audit" in tables:
                checked_monitor_schema(self.connection)
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS isolation_audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    task_id TEXT NOT NULL, request_id TEXT NOT NULL, event TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT NOT NULL, metadata_json TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS isolation_no_update BEFORE UPDATE ON isolation_audit
                    BEGIN SELECT RAISE(ABORT,'append only'); END;
                CREATE TRIGGER IF NOT EXISTS isolation_no_delete BEFORE DELETE ON isolation_audit
                    BEGIN SELECT RAISE(ABORT,'append only'); END;
            """)
            checked_monitor_schema(self.connection)
            unfinished = self.connection.execute("SELECT task_id,request_id FROM isolation_audit a WHERE event='started' AND NOT EXISTS (SELECT 1 FROM isolation_audit b WHERE b.task_id=a.task_id AND b.event IN ('finished','abandoned'))").fetchall()
            for row in unfinished:
                self._append(row["task_id"], row["request_id"], "abandoned", "failed", "nonzero_exit", {"recovery": True})
            if self.config.get("policy_version") == "docker-linux-readonly-v2":
                from .docker_isolation import DockerBackend
                self.backend = DockerBackend(self.runtime_directory, self.config)
            else:
                self.backend = WindowsBackend(self.runtime_directory, self.config["package_name"])
        except Exception:
            self.close()
            raise IsolationError("isolation_unavailable") from None

    def __enter__(self):
        return self

    @property
    def runtime_directory(self):
        return self._runtime_directory

    @property
    def database_path(self):
        return self._database_path

    @property
    def readable_directories(self):
        return self._readable_directories

    def __exit__(self, exception_type, exception, traceback):
        self.close()

    def _append(self, task_id, request_id, event, status, reason, metadata):
        record = dict(timestamp=datetime.now(SHANGHAI).isoformat(), task_id=task_id,
                      request_id=request_id, event=event, status=status, reason=reason,
                      metadata_json=json.dumps(metadata, ensure_ascii=False, allow_nan=False))
        try:
            with self.audit_lock:
                if self.audit_hook:
                    self.audit_hook(dict(record))
                with self.connection:
                    self.connection.execute("INSERT INTO isolation_audit(timestamp,task_id,request_id,event,status,reason,metadata_json) VALUES(:timestamp,:task_id,:request_id,:event,:status,:reason,:metadata_json)", record)
        except Exception:
            self.halted = True
            self.current_cancel.set()
            raise IsolationError("audit_unavailable") from None

    def audit_events(self):
        if self.closed or self.connection is None:
            raise IsolationError("audit_unavailable")
        with self.audit_lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM isolation_audit ORDER BY id")]

    @contextmanager
    def _runtime_lease(self, cancel_event=None):
        """同一LPAC身份跨进程序列化，避免两个不同任务共享该身份同时运行。"""
        import msvcrt
        # 锁由注册身份定位，复制运行时目录不能让同一SID并行运行。
        path = self._runtime_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lease = open(path, "a+b")
        obtained = False
        try:
            if lease.tell() == 0:
                lease.write(b"0")
                lease.flush()
            deadline = time.monotonic() + self.limits["wall_seconds"]
            while True:
                lease.seek(0)
                try:
                    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
                    obtained = True
                    break
                except OSError:
                    if self.current_cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                        raise IsolationError("cancelled") from None
                    if time.monotonic() >= deadline:
                        raise IsolationError("isolation_unavailable") from None
                    time.sleep(0.02)
            if Path(str(path) + ".quarantine").exists():
                raise IsolationError("isolation_unavailable")
            yield
        finally:
            if self.quarantined:
                self.retained_runtime_lease = lease
            else:
                if obtained:
                    lease.seek(0)
                    msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
                lease.close()

    def _runtime_lock_path(self):
        return (Path(__file__).resolve().parents[1] / ".isolation" / "locks" /
                (self.config["package_name"] + ".lock"))

    def _quarantine_runtime(self):
        """OS退出未确认时停用该身份；不以释放锁/重启掩盖不完整清理。"""
        self.halted = True
        self.quarantined = True
        try:
            Path(str(self._runtime_lock_path()) + ".quarantine").write_text(
                "cleanup_unconfirmed; trusted operator must verify before reuse\n", encoding="ascii")
        except OSError:
            # 保留当前进程的身份锁与监控锁；不能为了写标记失败释放活跃任务的边界。
            pass

    def _run(self, script_path, payload, request_id, cancel_event, *, fixed=False, forced_reason=None):
        safe_request = request_id if type(request_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{0,80}", request_id) else ""
        task_id = uuid.uuid4().hex
        planned = {"mechanism": self.config.get("policy_version", "windows-lpac-job-v1"), "limits": dict(self.limits),
                   "pid": None, "worker_started": False, "active_processes_after": 0}
        def unavailable_receipt():
            self.last_receipt = dict(task_id=task_id, request_id=safe_request, status="failed",
                                     reason="audit_unavailable", metadata=planned)
        with self.state_lock:
            if self.halted or self.closed:
                unavailable_receipt()
                raise IsolationError("audit_unavailable", planned)
        with self.execution_lock:
            with self.state_lock:
                if self.closed or self.halted:
                    unavailable_receipt()
                    raise IsolationError("audit_unavailable", planned)
                self.current_cancel.clear()
            try:
                self._append(task_id, safe_request, "started", "pending", "ok", planned)
            except IsolationError:
                unavailable_receipt()
                raise IsolationError("audit_unavailable", planned) from None
            raw_output = b""
            probe_script = None
            try:
                if forced_reason:
                    raise IsolationError(forced_reason)
                if fixed:
                    script = self.runtime_directory / "worker.py"
                else:
                    source = Path(script_path)
                    if not source.is_file() or source.stat().st_size > 262144:
                        raise IsolationError("invalid_input")
                    task_directory = self.runtime_directory / "tasks"
                    task_directory.mkdir(exist_ok=True)
                    if task_directory.is_symlink() or task_directory.stat().st_file_attributes & 0x400:
                        raise IsolationError("isolation_unavailable")
                    script = task_directory / (task_id + ".py")
                    probe_script = script
                    script.write_bytes(source.read_bytes())
                raw_input = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if len(raw_input) > 65536:
                    raise IsolationError("invalid_input")
                class CancelSignal:
                    def is_set(inner_self):
                        return self.current_cancel.is_set() or (cancel_event is not None and cancel_event.is_set())
                with self._runtime_lease(cancel_event):
                    _, current_config = checked_runtime(self.runtime_directory)
                    if current_config != self.config:
                        raise IsolationError("isolation_unavailable")
                    native = self.backend.run(script, raw_input, self.limits, CancelSignal())
                    if native.get("metadata", {}).get("cleanup_complete") is False:
                        self._quarantine_runtime()
                        native.update(status="failed", reason="isolation_unavailable")
                metadata = dict(native.get("metadata", {}))
                metadata["limits"] = dict(self.limits)
                metadata["exit_code"] = native.get("exit_code")
                raw_output = native.get("stdout", b"")
                standard_error = native.get("stderr", b"")
                metadata["output_bytes"] = len(raw_output) + len(standard_error)
                metadata["stdout_sha256"] = hashlib.sha256(raw_output).hexdigest()
                reason = native.get("reason", "isolation_unavailable")
                if reason not in SAFE_REASONS:
                    reason = "isolation_unavailable"
                status = native.get("status", "failed")
                data = None
                if status == "success" and reason == "ok":
                    try:
                        data = strict_json(raw_output.decode("utf-8"))
                        if fixed:
                            if data == {"ok": False, "reason": "invalid_input"}:
                                raise IsolationError("invalid_input")
                            if type(data) is not dict or data.get("ok") is not True or set(data) != {"ok", "data"}:
                                raise ValueError("worker failed")
                            data = data["data"]
                        if standard_error:
                            raise ValueError("unexpected stderr")
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        status, reason = "failed", "invalid_output"
                    except IsolationError as error:
                        status, reason, data = "failed", error.reason, None
                if status not in {"success", "failed", "cancelled"}:
                    status, reason = "failed", "invalid_output"
                receipt = dict(task_id=task_id, request_id=safe_request, status=status, reason=reason, metadata=metadata)
                if status == "success":
                    receipt["data"] = data
            except IsolationError as error:
                receipt = dict(task_id=task_id, request_id=safe_request,
                               status="cancelled" if error.reason == "cancelled" else "failed",
                               reason=error.reason, metadata=planned)
            except (OSError, ValueError, TypeError, OverflowError, RecursionError):
                receipt = dict(task_id=task_id, request_id=safe_request, status="failed", reason="invalid_input", metadata=planned)
            finally:
                if probe_script is not None:
                    try:
                        probe_script.unlink(missing_ok=True)
                    except OSError:
                        receipt = dict(task_id=task_id, request_id=safe_request, status="failed",
                                       reason="isolation_unavailable", metadata=planned)
            with self.state_lock:
                if self.current_cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                    receipt.pop("data", None)
                    receipt.update(status="cancelled", reason="cancelled")
                self.last_receipt = {key: value for key, value in receipt.items() if key != "data"}
                try:
                    self._append(task_id, safe_request, "finished", receipt["status"], receipt["reason"], receipt["metadata"])
                except IsolationError:
                    self.last_receipt.update(status="failed", reason="audit_unavailable")
                    raise IsolationError("audit_unavailable", receipt["metadata"]) from None
                return receipt

    def execute(self, task_name, payload, *, request_id="", cancel_event=None):
        if type(task_name) is not str or task_name not in {"parse_candidate", "compute_tool"}:
            receipt = self._run(None, {}, request_id, cancel_event, fixed=True, forced_reason="invalid_task")
            raise IsolationError("invalid_task", receipt["metadata"])
        if type(payload) is not dict:
            receipt = self._run(None, {}, request_id, cancel_event, fixed=True, forced_reason="invalid_input")
            raise IsolationError("invalid_input", receipt["metadata"])
        receipt = self._run(None, {"task": task_name, "payload": payload}, request_id, cancel_event, fixed=True)
        if receipt["status"] != "success":
            raise IsolationError(receipt["reason"], receipt["metadata"])
        return receipt["data"]

    def run_probe(self, script_path, payload=None, *, request_id="", cancel_event=None):
        return self._run(script_path, {} if payload is None else payload, request_id, cancel_event)

    def close(self):
        with self.state_lock:
            self.closed = True
            self.current_cancel.set()
        obtained = self.execution_lock.acquire(timeout=2.5)
        if not obtained:
            # 保留独占锁和审计连接，不能让未终结任务的监控库被另一宿主接管。
            self.halted = True
            raise IsolationError("isolation_unavailable")
        try:
            if self.quarantined:
                raise IsolationError("isolation_unavailable")
            with self.audit_lock:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None
                if self.lease_file is not None:
                    self.lease_file.close()
                    self.lease_file = None
        finally:
            if obtained:
                self.execution_lock.release()

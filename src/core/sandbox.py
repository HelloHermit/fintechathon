"""沙箱分析（PLAN 3.11）：模型写的分析代码只能在这里运行。

三道关：
1. 运行前 AST 白名单：只许 `from math|statistics|collections|datetime|itertools import …`；禁止下划线属性、
   eval/exec/open/compile/__import__/getattr 等；代码 ≤ 2000 字符；必须定义 analyze(transactions)。
2. 运行时隔离：有 Docker 用 Docker（--network none --read-only --cap-drop ALL …）；否则子进程
   （python -I -S、空环境变量、临时目录、resource 限制 CPU 2 秒 / 内存 256MB / 文件数、5 秒超时）；
   系统支持时再套一层 `unshare -rn`（无网络的网络命名空间），不支持时如实标注“网络隔离降级”。
3. 受限内置函数：执行器里只给一组安全的内置函数，import 也只放行白名单模块。
数据只给本人交易的只读 JSON 快照（经标准输入传入），没有数据库、没有密钥。输出 ≤ 64KB 的 JSON。
"""

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

MAX_CODE = 2000
MAX_OUTPUT = 65536
TIMEOUT = 5
CPU_SECONDS = 2
MEMORY_MB = 256
ALLOWED_MODULES = {"math", "statistics", "collections", "datetime", "itertools"}
FORBIDDEN_NAMES = {"eval", "exec", "open", "compile", "__import__", "getattr", "setattr", "delattr", "globals", "locals",
                   "vars", "input", "breakpoint", "help", "dir", "memoryview", "exit", "quit", "classmethod", "staticmethod",
                   "property", "super", "type", "object", "os", "sys", "subprocess", "socket", "builtins", "importlib"}
ALLOWED_NODES = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign, ast.AnnAssign,
                 ast.For, ast.While, ast.If, ast.Break, ast.Continue, ast.Pass, ast.Expr, ast.ImportFrom, ast.alias,
                 ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Lambda, ast.IfExp, ast.Dict, ast.Set, ast.ListComp, ast.SetComp,
                 ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.Compare, ast.Call, ast.keyword, ast.Constant,
                 ast.Attribute, ast.Subscript, ast.Slice, ast.Name, ast.List, ast.Tuple, ast.Load, ast.Store, ast.Del,
                 ast.And, ast.Or, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
                 ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
                 ast.JoinedStr, ast.FormattedValue, ast.Starred)

RUNNER = r'''
import json, sys
SAFE = ["abs","all","any","bool","dict","divmod","enumerate","filter","float","int","isinstance","len","list","map","max",
        "min","pow","range","reversed","round","set","sorted","str","sum","tuple","zip","Exception","ValueError",
        "KeyError","ZeroDivisionError","TypeError","IndexError","StopIteration","print"]
import builtins as _b
ALLOWED = {"math", "statistics", "collections", "datetime", "itertools"}
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name not in ALLOWED or level != 0:
        raise ImportError("module not allowed: " + str(name))
    return _b.__import__(name, globals, locals, fromlist, level)
safe = {k: getattr(_b, k) for k in SAFE}
safe["__import__"] = _guarded_import
payload = json.loads(sys.stdin.read())
scope = {"__builtins__": safe, "__name__": "analysis"}
try:
    exec(compile(payload["code"], "<analysis>", "exec"), scope)
    result = scope["analyze"](payload["transactions"])
    out = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
except Exception as error:
    out = json.dumps({"ok": False, "error": type(error).__name__ + ": " + str(error)[:200]}, ensure_ascii=False)
sys.stdout.write(out[:70000])
'''


class SandboxRejected(Exception):
    pass


def check_code(code):
    """运行前静态检查。返回 None 表示通过，否则返回拒绝原因。"""
    if not isinstance(code, str) or not code.strip():
        return "没有代码"
    if len(code) > MAX_CODE:
        return f"代码超过 {MAX_CODE} 字符"
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return f"语法错误：{error.msg}"
    has_analyze = False
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return f"不允许的语法：{type(node).__name__}"
        if isinstance(node, ast.ImportFrom):
            if node.module not in ALLOWED_MODULES or node.level:
                return f"不允许导入模块：{node.module}"
            if any(alias.name == "*" or alias.name.startswith("_") for alias in node.names):
                return "不允许导入下划线名称或 *"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return f"不允许访问下划线属性：{node.attr}"
        if isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            return f"不允许使用：{node.id}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            return "字符串里不允许出现双下划线"
        if isinstance(node, ast.FunctionDef) and node.name == "analyze" and node in tree.body:
            has_analyze = True
    if not has_analyze:
        return "必须定义 analyze(transactions) 函数"
    return None


_ENGINE_CACHE = {}


def detect_engine():
    """docker（守护进程可用时）> subprocess+unshare（可建无网络命名空间时）> subprocess（网络隔离降级）。"""
    if "engine" in _ENGINE_CACHE:
        return _ENGINE_CACHE["engine"]
    engine = "subprocess"
    if os.environ.get("FINTECH_SANDBOX_DOCKER") == "1" and shutil.which("docker"):
        try:
            if subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0:
                engine = "docker"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if engine == "subprocess" and sys.platform.startswith("linux") and shutil.which("unshare"):
        try:
            if subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0:
                engine = "subprocess+netns"
        except (OSError, subprocess.TimeoutExpired):
            pass
    _ENGINE_CACHE["engine"] = engine
    return engine


def _limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_MB * 1024 * 1024, MEMORY_MB * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except (ValueError, OSError):
        pass
    os.setsid()


def run(code, transactions):
    """返回 code_analysis 卡片的数据。被拒绝时 status=rejected（代码从未运行）。"""
    started = time.monotonic()
    engine = detect_engine()
    limits = {"timeout_s": TIMEOUT, "cpu_s": CPU_SECONDS, "memory_mb": MEMORY_MB,
              "network": False if engine in ("docker", "subprocess+netns") else "未隔离（降级）"}
    code_hash = hashlib.sha256((code or "").encode()).hexdigest()
    reason = check_code(code)
    base = {"code": code, "code_hash": code_hash, "engine": engine, "limits": limits}
    if reason:
        return dict(base, status="rejected", reason=reason, duration_ms=0, result=None)
    payload = json.dumps({"code": code, "transactions": transactions}, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="sbx-") as workdir:
        if engine == "docker":
            command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL",
                       "--security-opt", "no-new-privileges", "--memory", "128m", "--cpus", "0.5", "--pids-limit", "64",
                       "--user", "65534", "python:3.12-slim", "python", "-I", "-S", "-c", RUNNER]
            preexec = None
        else:
            command = [sys.executable, "-I", "-S", "-c", RUNNER]
            if engine == "subprocess+netns":
                command = ["unshare", "-rn"] + command
            preexec = _limits if sys.platform.startswith("linux") else None
        try:
            proc = subprocess.run(command, input=payload.encode("utf-8"), capture_output=True, timeout=TIMEOUT,
                                  cwd=workdir, env={}, preexec_fn=preexec)
            exit_code, stdout = proc.returncode, proc.stdout[:MAX_OUTPUT + 1]
        except subprocess.TimeoutExpired:
            return dict(base, status="error", reason=f"超过 {TIMEOUT} 秒被终止", duration_ms=int((time.monotonic() - started) * 1000),
                        result=None, exit="timeout")
    duration = int((time.monotonic() - started) * 1000)
    if len(stdout) > MAX_OUTPUT:
        return dict(base, status="error", reason="输出超过 64KB", duration_ms=duration, result=None, exit=exit_code)
    if exit_code and exit_code < 0 and not stdout:
        return dict(base, status="error", reason="CPU 时间或内存超限，被系统终止", duration_ms=duration, result=None, exit=exit_code)
    try:
        data = json.loads(stdout.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        reason = "CPU 时间或内存超限被终止" if exit_code and exit_code < 0 else "输出不是合法 JSON"
        return dict(base, status="error", reason=reason, duration_ms=duration, result=None, exit=exit_code)
    if not data.get("ok"):
        return dict(base, status="error", reason=data.get("error", "运行出错"), duration_ms=duration, result=None, exit=exit_code)
    result = data["result"]
    if isinstance(result, dict):
        shaped = {"type": "table" if all(isinstance(v, (int, float, str)) for v in result.values()) else "value", "value": result}
    elif isinstance(result, list):
        shaped = {"type": "series", "value": result[:200]}
    else:
        shaped = {"type": "value", "value": result}
    return dict(base, status="ok", duration_ms=duration, result=shaped, exit=exit_code)


def snapshot(kernel, user_id, days=400):
    """本人交易的只读快照（只含分析需要的字段）。"""
    from datetime import timedelta
    from .util import iso, parse_iso
    since = iso(kernel.now() - timedelta(days=days))
    rows = kernel.db.execute("""SELECT time, merchant, category, amount_cents FROM transactions WHERE user_id=? AND time>=?
        AND status='success' ORDER BY time""", (user_id, since)).fetchall()
    result = []
    for r in rows:
        t = parse_iso(r["time"])
        result.append({"time": r["time"], "date": r["time"][:10], "weekday": t.weekday(), "hour": t.hour, "merchant": r["merchant"],
                       "category": r["category"], "amount": r["amount_cents"] / 100, "amount_cents": r["amount_cents"]})
    return result

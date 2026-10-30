"""DeepSeek（OpenAI 兼容）工具调用客户端：超时重试一次、录制/回放（cassette）。

密钥只从环境变量读取，不写日志、不进决策链。模型输出只是候选。
"""

import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class ModelUnavailable(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def load_dotenv(path=".env"):
    """读取 .env（不覆盖已有环境变量）。只认 KEY=VALUE 行。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class LLMClient:
    """mode: live（真实调用）、record（真实调用并录制）、replay（只回放录制，不联网）。"""

    def __init__(self, mode=None, cassette_dir=None, timeout=25):
        self.base_url = os.environ.get("FINTECH_MODEL_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.model = os.environ.get("FINTECH_MODEL_NAME", DEFAULT_MODEL)
        self._api_key = os.environ.get("FINTECH_MODEL_API_KEY", "")
        self.thinking = os.environ.get("FINTECH_MODEL_THINKING", "disabled")
        self.mode = mode or os.environ.get("FINTECH_MODEL_MODE", "live")
        self.cassette_dir = Path(cassette_dir or os.environ.get("FINTECH_CASSETTE_DIR", "cassettes"))
        self.timeout = timeout
        if self.mode not in ("live", "record", "replay"):
            self.mode = "live"

    @property
    def configured(self):
        return self.mode == "replay" or bool(self._api_key)

    @property
    def status(self):
        if self.mode == "replay":
            return "replay"
        return "live" if self._api_key else "unavailable"

    def _key(self, payload):
        stable = {k: payload[k] for k in ("model", "messages", "tools") if k in payload}
        return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def chat(self, messages, tools=None, temperature=0):
        """返回 {"content", "tool_calls":[{"id","name","arguments"(str)}], "usage", "ms", "model"}。"""
        payload = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": 800}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.thinking == "disabled":
            payload["thinking"] = {"type": "disabled"}
        key = self._key(payload)
        if self.mode == "replay":
            path = self.cassette_dir / (key + ".json")
            if not path.exists():
                raise ModelUnavailable("model_unavailable", "回放模式下没有这句话的录制结果。")
            return json.loads(path.read_text(encoding="utf-8"))
        if not self._api_key:
            raise ModelUnavailable("model_unavailable", "没有配置模型密钥（FINTECH_MODEL_API_KEY）。")
        started = time.monotonic()
        data = None
        last_error = None
        for attempt in range(2):  # 超时或 5xx 自动重试一次
            try:
                data = self._post(payload)
                break
            except ModelUnavailable as error:
                last_error = error
                if error.code not in ("model_timeout", "model_unavailable") or attempt == 1:
                    raise
                time.sleep(0.5)
        if data is None:
            raise last_error
        result = self._parse(data)
        result["ms"] = int((time.monotonic() - started) * 1000)
        if self.mode == "record":
            self.cassette_dir.mkdir(parents=True, exist_ok=True)
            (self.cassette_dir / (key + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    def _post(self, payload):
        request = urllib.request.Request(self.base_url + "/chat/completions",
                                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": "Bearer " + self._api_key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(2_000_000)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise ModelUnavailable("rate_limited", "模型服务繁忙，请稍后再试。")
            if error.code >= 500:
                raise ModelUnavailable("model_unavailable", "模型服务暂时不可用。")
            raise ModelUnavailable("model_unavailable", f"模型服务拒绝了请求（HTTP {error.code}）。")
        except (socket.timeout, TimeoutError):
            raise ModelUnavailable("model_timeout", "模型响应超时。")
        except urllib.error.URLError as error:
            if isinstance(getattr(error, "reason", None), (socket.timeout, TimeoutError)):
                raise ModelUnavailable("model_timeout", "模型响应超时。")
            raise ModelUnavailable("model_unavailable", "连不上模型服务。")
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            raise ModelUnavailable("model_unavailable", "模型返回了无法解析的内容。")

    def _parse(self, data):
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelUnavailable("model_unavailable", "模型返回格式异常。")
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name"):
                calls.append({"id": call.get("id") or ("call_" + str(len(calls))), "name": function["name"],
                              "arguments": function.get("arguments") or "{}"})
        content = message.get("content") or ""
        if not calls and content.strip().startswith("{") and '"tool"' in content:
            # JSON 回退：个别情况下模型把工具调用写进正文
            try:
                obj = json.loads(content)
                if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
                    calls.append({"id": "call_json", "name": obj["tool"], "arguments": json.dumps(obj.get("arguments") or {}, ensure_ascii=False)})
                    content = ""
            except ValueError:
                pass
        usage = data.get("usage") or {}
        return {"content": content, "tool_calls": calls, "model": data.get("model", self.model),
                "usage": {"prompt": usage.get("prompt_tokens", 0), "completion": usage.get("completion_tokens", 0)}}

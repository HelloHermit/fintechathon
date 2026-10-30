"""标准库密码散列与 RFC 6238 动态码；输入不合法时验证拒绝。

密码使用 PBKDF2-HMAC-SHA256，随机盐与恒定时间比较。
认证器秘密只供本机登记和校验，不传模型或写入日志。
"""

import base64
import binascii
import hashlib
import hmac
import math
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

KDF_ALGORITHM = "sha256"
KDF_ITERATIONS = 200000
MAX_KDF_ITERATIONS = 2000000
SALT_BYTES = 16
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
SECRET_BYTES = 20


def _password_bytes(password):
    """只接受规定长度、可编码的文字口令；不把错误内容写入异常。"""
    if type(password) is not str or not 8 <= len(password) <= 128:
        return None
    try:
        return password.encode("utf-8")
    except UnicodeError:
        return None


def _hex_bytes(value, byte_count):
    """严格校验固定长度的十六进制存储字段。"""
    if type(value) is not str or re.fullmatch(r"[0-9a-fA-F]{" + str(byte_count * 2) + r"}", value) is None:
        return None
    return bytes.fromhex(value)


def _valid_iterations(iterations):
    return type(iterations) is int and KDF_ITERATIONS <= iterations <= MAX_KDF_ITERATIONS


def hash_password(password, salt_hex=None, iterations=KDF_ITERATIONS):
    """返回 (hash_hex, salt_hex, iterations)；非法登记输入抛无秘密的格式异常。"""
    encoded_password = _password_bytes(password)
    if encoded_password is None or not _valid_iterations(iterations):
        raise ValueError("invalid password format or KDF iterations")
    salt = secrets.token_bytes(SALT_BYTES) if salt_hex is None else _hex_bytes(salt_hex, SALT_BYTES)
    if salt is None:
        raise ValueError("invalid password salt format")
    digest = hashlib.pbkdf2_hmac(KDF_ALGORITHM, encoded_password, salt, iterations)
    return digest.hex(), salt.hex(), iterations


def verify_password(password, stored_hash_hex, salt_hex, iterations):
    """损坏字段、非法口令或危险迭代数都拒绝；不抛出存储内容。"""
    encoded_password = _password_bytes(password)
    stored_hash = _hex_bytes(stored_hash_hex, 32)
    salt = _hex_bytes(salt_hex, SALT_BYTES)
    if encoded_password is None or stored_hash is None or salt is None or not _valid_iterations(iterations):
        return False
    try:
        candidate = hashlib.pbkdf2_hmac(KDF_ALGORITHM, encoded_password, salt, iterations)
        return hmac.compare_digest(candidate, stored_hash)
    except (ValueError, TypeError, OverflowError):
        return False


def generate_totp_secret():
    """生成 160 位随机秘密，返回不带填充的 base32 文字。"""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def normalize_totp_secret(secret_base32):
    """规范化大小写与空格；有效 base32 解码后须至少 20 字节。"""
    if type(secret_base32) is not str or not secret_base32.isascii():
        return None
    compact = secret_base32.replace(" ", "").upper()
    if re.fullmatch(r"[A-Z2-7]+={0,6}", compact) is None:
        return None
    unpadded = compact.rstrip("=")
    padding = "=" * (-len(unpadded) % 8)
    if compact != unpadded and compact != unpadded + padding:
        return None
    try:
        raw = base64.b32decode(unpadded + padding)
    except (binascii.Error, ValueError, TypeError):
        return None
    if len(raw) < SECRET_BYTES:
        return None
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def totp_code(secret_base32, unix_time=None, step_offset=0):
    """计算 30 秒步长、6 位 TOTP；非法秘密、时间或计数器返回 None。"""
    normalized = normalize_totp_secret(secret_base32)
    if normalized is None or type(step_offset) is not int:
        return None
    current_time = time.time() if unix_time is None else unix_time
    if type(current_time) not in (int, float):
        return None
    try:
        if not math.isfinite(current_time) or current_time < 0:
            return None
        counter = int(current_time // TOTP_STEP_SECONDS) + step_offset
        if not 0 <= counter <= 0xFFFFFFFFFFFFFFFF:
            return None
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(binary % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)
    except (ValueError, TypeError, OverflowError, binascii.Error, struct.error):
        return None


def match_totp(secret_base32, presented_code, unix_time, drift_steps=1):
    """仅接收六位 ASCII 数字，在当前时间步±1 内匹配；返回相对偏移。"""
    if type(presented_code) is not str or re.fullmatch(r"[0-9]{6}", presented_code) is None:
        return None
    if type(drift_steps) is not int or not 0 <= drift_steps <= 1:
        return None
    current_time = time.time() if unix_time is None else unix_time
    offsets = [0] if drift_steps == 0 else [0, -1, 1]
    for offset in offsets:
        expected = totp_code(secret_base32, current_time, offset)
        if expected is not None and hmac.compare_digest(expected, presented_code):
            return offset
    return None


def otpauth_uri(secret_base32, user_id, issuer="FinTechathonMockBank"):
    """正确转义本机登记链接；调用者仅在登记当场显示一次。"""
    normalized = normalize_totp_secret(secret_base32)
    if normalized is None or type(user_id) is not str or type(issuer) is not str or not user_id or not issuer:
        return None
    try:
        label = quote(issuer, safe="") + ":" + quote(user_id, safe="")
        query = urlencode({"secret": normalized, "issuer": issuer, "algorithm": "SHA1", "digits": TOTP_DIGITS, "period": TOTP_STEP_SECONDS})
        return "otpauth://totp/" + label + "?" + query
    except (UnicodeError, ValueError, TypeError):
        return None

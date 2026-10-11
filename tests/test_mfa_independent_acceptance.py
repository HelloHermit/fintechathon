"""Independent synthetic MFA acceptance; expectations come from public contracts.

Do not import src.strong_auth or inspect application implementation.  Running this
file directly appends a sanitized attempt to the assigned evidence JSON.  Every
bank is disposable; no normal ledger, real model, or human credential is used.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import io
import json
import re
import runpy
import secrets
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bank import BankService


EVIDENCE = ROOT / "evidence" / "mfa-independent-acceptance.json"
SHANGHAI = timezone(timedelta(hours=8))
SECRET_VALUES: set[str] = set()


def remember(value):
    """Keep disclosure probes only in memory, including generated OTPs."""
    if isinstance(value, str) and value:
        SECRET_VALUES.add(value)
    return value


def sanitized(value):
    text = str(value)
    for secret_value in sorted(SECRET_VALUES, key=len, reverse=True):
        text = text.replace(secret_value, "[synthetic credential redacted]")
    return re.sub(r"otpauth://\S+", "[enrollment URI redacted]", text)


def oracle_totp(secret, timestamp, digits=6):
    """RFC 6238 SHA1/30s with RFC 4226 dynamic truncation, independently built."""
    encoded_secret = secret.upper()
    key = base64.b32decode(encoded_secret + "=" * (-len(encoded_secret) % 8))
    step = int(timestamp) // 30
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    result = f"{number % (10 ** digits):0{digits}d}"
    return remember(result)


def random_password(length=32):
    return remember("".join(secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(length)))


def case(topic, inputs, expected, verification, uncertainty="合成离线接口，不证明真人设备或生产身份"):
    def decorate(method):
        method.acceptance_metadata = {
            "topic": topic,
            "input": inputs,
            "expected": expected,
            "verification": verification,
            "uncertainty": uncertainty,
        }
        return method
    return decorate


class MutableClock:
    def __init__(self, value=None):
        self.value = value or datetime(2026, 10, 11, 12, 0, 15, tzinfo=SHANGHAI)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class AuditFault:
    def __init__(self):
        self.event = None
        self.on_event = None

    def __call__(self, event):
        if self.on_event is not None:
            self.on_event(event)
        if event.get("event") == self.event:
            raise OSError("synthetic audit storage unavailable")


class RecordingModel:
    def __init__(self, candidate=None):
        self.calls = []
        self.candidate = candidate or {"intent": "query_balance", "params": {}}

    def propose(self, text, context):
        self.calls.append({"text": text, "context": context})
        return self.candidate


class TemporaryBank:
    """Use only documented interfaces and public SQLite tables."""
    def __init__(self, clock=None):
        self.directory = tempfile.TemporaryDirectory(prefix="fintech-mfa-independent-")
        self.path = Path(self.directory.name) / "acceptance.sqlite"
        self.clock = clock or MutableClock()
        self.audit_fault = AuditFault()
        self.services = []
        self.bank = self.open("alice")
        self.credentials = {}

    def open(self, user_id):
        bank = BankService(str(self.path), user_id=user_id, clock=self.clock, audit_hook=self.audit_fault)
        self.services.append(bank)
        return bank

    def close(self):
        for bank in self.services:
            with contextlib.suppress(Exception):
                bank.close()
        self.directory.cleanup()

    def rows(self, sql, parameters=()):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    def write(self, sql, parameters=()):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(sql, parameters)

    def business(self):
        return {
            table: self.rows(f"SELECT * FROM {table} ORDER BY {order}")
            for table, order in (
                ("accounts", "account_id"),
                ("subscriptions", "subscription_id"),
                ("transactions", "transaction_id"),
                ("transfers", "request_id"),
            )
        }

    def state(self, user_id="alice", intent="transfer"):
        rows = self.rows("SELECT failures, locked_until FROM verification_state WHERE user_id=? AND intent=?", (user_id, intent))
        return rows[0] if rows else {"failures": 0, "locked_until": None}

    def replay(self):
        return self.rows("SELECT user_id, step, used_at FROM strong_auth_replay ORDER BY user_id, step")

    def request(self, request_id):
        rows = self.rows("SELECT * FROM requests WHERE request_id=?", (request_id,))
        return rows[0] if rows else None

    def credential(self, user_id="alice", length=32, iterations=200000):
        password = random_password(length)
        # Exclude accidental OTP collisions from +/-2 test fixtures.
        while True:
            secret = remember(base64.b32encode(secrets.token_bytes(20)).decode("ascii"))
            timestamp = self.clock().timestamp()
            codes = {oracle_totp(secret, timestamp + offset * 30) for offset in range(-2, 3)}
            if len(codes) == 5:
                break
        salt = secrets.token_bytes(16)
        password_hash = remember(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex())
        password_salt = remember(salt.hex())
        self.credentials[user_id] = (password, secret)
        return password, secret, password_hash, password_salt, iterations

    def seed_auth(self, user_id="alice", iterations=200000):
        password, secret, password_hash, salt, count = self.credential(user_id, iterations=iterations)
        self.write(
            "INSERT INTO strong_auth(user_id,password_hash,password_salt,kdf_iterations,totp_secret,enrolled_at) VALUES(?,?,?,?,?,?)",
            (user_id, password_hash, salt, count, secret, self.clock().isoformat()),
        )
        return password, secret

    def otp(self, user_id="alice", offset=0):
        return oracle_totp(self.credentials[user_id][1], self.clock().timestamp() + offset * 30)

    def wrong_otp(self, user_id="alice"):
        accepted = {self.otp(user_id, offset) for offset in (-1, 0, 1)}
        while True:
            candidate = remember(f"{secrets.randbelow(1000000):06d}")
            if candidate not in accepted:
                return candidate

    def red(self, bank=None, amount=100100, contact="wang", account="alice-main"):
        return (bank or self.bank).propose({"intent": "transfer", "params": {"account_id": account, "contact_id": contact, "amount_cents": amount}})

    def yellow(self, bank=None, user_id="alice", amount=10000):
        return (bank or self.bank).propose({"intent": "transfer", "params": {"account_id": user_id + "-main", "contact_id": "wang" if user_id == "alice" else "alice-contact", "amount_cents": amount}})

    def verify(self, pending, bank=None, password=None, code=None, **kwargs):
        user_id = "bob" if bank is not None and bank is not self.bank else "alice"
        factors = self.credentials[user_id]
        return (bank or self.bank).strong_verify(pending["request_id"], password if password is not None else factors[0], code if code is not None else self.otp(user_id), **kwargs)


class IndependentMfaAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixtures = []

    def tearDown(self):
        for fixture in self.fixtures:
            fixture.close()

    def fixture(self, registered=True, clock=None):
        fixture = TemporaryBank(clock)
        self.fixtures.append(fixture)
        if registered:
            fixture.seed_auth()
        return fixture

    def outcome(self, response, status, reason=None):
        self.assertEqual(response.get("status"), status, "public status differs")
        if reason is not None:
            self.assertEqual(response.get("reason"), reason, "public reason differs")

    def passed(self, response):
        self.outcome(response, "rejected", "isolation_unavailable")
        self.assertEqual(response.get("strong_verification"), "passed", "two factors must pass only this request")

    def no_secrets(self, payload, values):
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        self.assertFalse(any(value and value in serialized for value in values), "synthetic credential disclosure detected; value withheld")

    def fail_once(self, fixture, pending=None):
        pending = pending or fixture.red()
        self.outcome(pending, "pending")
        response = fixture.verify(pending, password=random_password(), confirmed=True)
        return pending, response

    def lock(self, fixture):
        pending = fixture.red()
        self.outcome(pending, "pending")
        for attempt in range(3):
            response = fixture.verify(pending, password=random_password(), confirmed=True)
            self.outcome(response, "rejected", "locked" if attempt == 2 else "verification_failed")
            self.assertEqual(fixture.state()["failures"], attempt + 1, "failure count must persist")
        return pending

    def assert_locked_proposal(self, fixture, yellow=False):
        pending = fixture.yellow() if yellow else fixture.red()
        if pending.get("status") == "pending":
            response = fixture.bank.confirm(pending["request_id"], pending.get("confirmation_code", "")) if yellow else fixture.verify(pending, confirmed=True)
        else:
            response = pending
        self.outcome(response, "rejected", "locked")
        return pending

    @case("oracle", "RFC6238官方SHA1历史测试向量", "独立oracle匹配六个8位标准向量", "独立HMAC/截断/步长算法")
    def test_01_independent_totp_oracle_matches_rfc_vectors(self):
        secret = base64.b32encode(b"12345678901234567890").decode("ascii")
        vectors = ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"))
        for index, (timestamp, expected) in enumerate(vectors):
            with self.subTest(vector=index):
                self.assertEqual(oracle_totp(secret, timestamp, digits=8), expected, "RFC oracle vector differs")

    @case("MFA-01", "未登记用户合法红档候选", "拒绝strong_verification_unavailable且不建请求或改变业务", "requests及四张业务表前后快照")
    def test_02_unenrolled_red_retains_previous_refusal(self):
        fixture = self.fixture(False)
        before = fixture.business()
        response = fixture.red()
        self.outcome(response, "rejected", "strong_verification_unavailable")
        self.assertEqual(fixture.rows("SELECT * FROM requests"), [], "unenrolled red request must not be created")
        self.assertEqual(fixture.business(), before, "unenrolled refusal changed business")
        self.assertTrue(fixture.bank.audit_events(), "unenrolled refusal needs audit")

    @case("MFA-01", "已登记用户合法红档候选", "本人/源/实际目标/金额/影响/期限展示且无屏显确认码", "pending响应和公开请求行")
    def test_03_registered_red_pending_displays_bound_operation(self):
        fixture = self.fixture()
        before = fixture.business()
        response = fixture.red()
        self.outcome(response, "pending")
        self.assertEqual(response.get("tier"), "red", "red tier must come from code")
        self.assertNotIn("confirmation_code", response, "red must not expose a screen confirmation code")
        operation = response.get("operation")
        self.assertIsInstance(operation, dict, "operation must be reviewable")
        serialized = json.dumps(operation, ensure_ascii=False)
        for required in ("alice", "alice-main", "bob-main", "100100"):
            self.assertIn(required, serialized, "display omitted a bound operation fact")
        self.assertTrue(any(word in serialized.lower() for word in ("impact", "影响", "模拟", "simulation")), "display omitted operation impact")
        row = fixture.request(response["request_id"])
        self.assertEqual(row["status"], "pending", "red request not persisted pending")
        self.assertEqual(datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"]), timedelta(minutes=5), "deadline must be five minutes")
        self.assertEqual(fixture.business(), before, "pending changed business")

    @case("MFA-02", "无持有码和错误持有码的代码登记", "invalid_totp_code、无登记/无replay且transfer计数保留", "公开登记API及公开安全表")
    def test_04_enrollment_requires_possession_proof(self):
        for variant in ("missing", "wrong"):
            with self.subTest(variant=variant):
                fixture = self.fixture(False)
                password, secret, *_ = fixture.credential()
                fixture.write("INSERT INTO verification_state(user_id,intent,failures,locked_until) VALUES(?,?,?,?)", ("alice", "transfer", 2, None))
                state_before = fixture.state()
                response = fixture.bank.enroll_strong_auth(password, secret) if variant == "missing" else fixture.bank.enroll_strong_auth(password, secret, fixture.wrong_otp())
                self.outcome(response, "rejected", "invalid_totp_code")
                self.assertEqual(fixture.rows("SELECT user_id FROM strong_auth"), [], "possession failure saved credentials")
                self.assertEqual(fixture.replay(), [], "possession failure consumed a step")
                self.assertEqual(fixture.state(), state_before, "enrollment failure changed transfer state")
                self.assertTrue(fixture.bank.audit_events(), "enrollment failure needs audit")

    @case("MFA-02", "密码7/8/128/129字符及非法类型、过短/非法base32", "只允许8至128字符及至少20解码字节秘密", "公开登记返回和登记存在性")
    def test_05_enrollment_password_and_secret_boundaries(self):
        variants = (("length7", 7, True, False), ("length8", 8, True, True), ("length128", 128, True, True), ("length129", 129, True, False), ("short_secret", 32, False, False))
        for label, length, valid_secret, accepted in variants:
            with self.subTest(variant=label):
                fixture = self.fixture(False)
                password, secret, *_ = fixture.credential(length=length)
                if not valid_secret:
                    secret = remember(base64.b32encode(secrets.token_bytes(19)).decode("ascii"))
                response = fixture.bank.enroll_strong_auth(password, secret, oracle_totp(secret, fixture.clock().timestamp()))
                self.outcome(response, "success" if accepted else "rejected")
                self.assertEqual(len(fixture.rows("SELECT user_id FROM strong_auth")), int(accepted), "length boundary saved wrong credential count")
        for label, password_factory, secret_factory in (
            ("password_none", lambda: None, lambda original: original),
            ("password_bool", lambda: True, lambda original: original),
            ("password_bytes", lambda: random_password().encode(), lambda original: original),
            ("secret_bad_alphabet", random_password, lambda original: remember("!" + original[1:])),
            ("secret_nonstring", random_password, lambda original: 1),
        ):
            with self.subTest(variant=label):
                fixture = self.fixture(False)
                _, secret, *_ = fixture.credential()
                response = fixture.bank.enroll_strong_auth(password_factory(), secret_factory(secret), fixture.otp())
                self.outcome(response, "rejected")
                self.assertEqual(fixture.rows("SELECT user_id FROM strong_auth"), [], "invalid format saved credentials")

    @case("MFA-02", "正确持有证明登记两个用户", "随机16字节盐、PBKDF2-SHA256/200000、成功步被消费", "自行PBKDF2复算及只检查形态/相等的内存断言")
    def test_06_enrollment_kdf_and_used_step(self):
        fixture = self.fixture(False)
        salts = []
        for user_id in ("alice", "bob"):
            bank = fixture.bank if user_id == "alice" else fixture.open(user_id)
            password, secret, *_ = fixture.credential(user_id)
            response = bank.enroll_strong_auth(password, secret, fixture.otp(user_id))
            self.outcome(response, "success")
            row = fixture.rows("SELECT * FROM strong_auth WHERE user_id=?", (user_id,))[0]
            self.assertEqual(row["kdf_iterations"], 200000, "enrollment KDF iterations differ")
            self.assertTrue(re.fullmatch(r"[0-9a-fA-F]{32}", row["password_salt"]), "salt must be sixteen hex bytes")
            self.assertTrue(re.fullmatch(r"[0-9a-fA-F]{64}", row["password_hash"]), "hash must be SHA256 hex")
            derived = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(row["password_salt"]), 200000).hex()
            self.assertTrue(hmac.compare_digest(derived, row["password_hash"]), "independent password derivation differs")
            self.assertNotEqual(row["password_hash"], password, "plaintext password persisted")
            salts.append(row["password_salt"])
            self.assertEqual(len(base64.b32decode(row["totp_secret"])), 20, "generated secret must have sufficient entropy bytes")
        self.assertNotEqual(salts[0], salts[1], "separate enrollments reused salt")
        self.assertEqual({(row["user_id"], row["step"]) for row in fixture.replay()}, {(user, int(fixture.clock().timestamp()) // 30) for user in ("alice", "bob")}, "enrollment steps not consumed")
        response = fixture.verify(fixture.red(), confirmed=True)
        self.outcome(response, "rejected", "verification_failed")
        self.assertEqual(fixture.state()["failures"], 1, "just-enrolled step must not authorize a request")

    @case("MFA-02", "已登记用户再次登记", "already_enrolled，原凭据和已用步不被替换", "登记前后私有表仅内存比较")
    def test_07_duplicate_enrollment_cannot_replace_credentials(self):
        fixture = self.fixture()
        before = fixture.rows("SELECT * FROM strong_auth")
        replay_before = fixture.replay()
        replacement, secret, *_ = fixture.credential()
        response = fixture.bank.enroll_strong_auth(replacement, secret, fixture.otp())
        self.outcome(response, "rejected", "already_enrolled")
        self.assertTrue(fixture.rows("SELECT * FROM strong_auth") == before, "duplicate replaced original credential")
        self.assertEqual(fixture.replay(), replay_before, "duplicate changed replay ledger")

    @case("MFA-02/14", "成功MFA后两错、pending期间本机reset", "删登记并作废pending，保留失败计数、锁定及replay", "公开reset及同库持久安全状态")
    def test_08_reset_preserves_protection_and_invalidates_pending(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                fixture = self.fixture()
                self.passed(fixture.verify(fixture.red(), confirmed=True))
                fixture.clock.advance(30)
                pending = fixture.red()
                for attempt in range(3 if locked else 2):
                    fixture.verify(pending, password=random_password(), confirmed=True)
                state_before = fixture.state()
                replay_before = fixture.replay()
                response = fixture.bank.unenroll_strong_auth()
                self.outcome(response, "success")
                self.assertEqual(fixture.rows("SELECT user_id FROM strong_auth WHERE user_id='alice'"), [], "reset left registration")
                self.assertEqual(fixture.state(), state_before, "reset cleared failure protection")
                self.assertEqual(fixture.replay(), replay_before, "reset cleared used steps")
                self.assertNotEqual(fixture.request(pending["request_id"])["status"], "pending", "reset left old authorization pending")
                response = fixture.bank.strong_verify(pending["request_id"], random_password(), fixture.otp(), confirmed=True)
                self.outcome(response, "rejected", "invalid_confirmation")
                self.assertEqual(fixture.state(), state_before, "old reset request increased factors failures")

    @case("MFA-03/15", "有效pending两次失败后正确两因素+明确同意", "MFA passed但隔离拒绝，计数清零/步消费/请求终结/审计同存", "业务/请求/安全状态及审计交叉核对")
    def test_09_success_clears_failures_but_never_executes_red(self):
        fixture = self.fixture()
        pending = fixture.red()
        before = fixture.business()
        for _ in range(2):
            self.outcome(fixture.verify(pending, password=random_password(), confirmed=True), "rejected", "verification_failed")
        self.passed(fixture.verify(pending, confirmed=True))
        self.assertEqual(fixture.state()["failures"], 0, "complete MFA did not clear failures")
        self.assertIsNone(fixture.state()["locked_until"], "unlocked success retained lock")
        self.assertEqual(fixture.business(), before, "MFA success executed red business")
        self.assertNotEqual(fixture.request(pending["request_id"])["status"], "pending", "MFA success left reusable request")
        self.assertEqual([(row["user_id"], row["step"]) for row in fixture.replay()], [("alice", int(fixture.clock().timestamp()) // 30)], "MFA success did not consume exact matched step")
        events = [event for event in fixture.bank.audit_events() if event.get("request_id") == pending["request_id"]]
        self.assertTrue(any(event.get("event") == "strong_verified" for event in events), "MFA success audit absent")
        self.assertTrue(any(event.get("reason") == "isolation_unavailable" for event in events), "isolation refusal audit absent")
        self.assertTrue(any(event.get("event") == "confirmed" for event in events), "explicit consent audit absent")
        self.no_secrets(events, [*fixture.credentials["alice"], fixture.otp()])

    @case("MFA-06", "confirmed省略/False/1/字符串/None，再传True", "仅bool True校验；其他不计失败、不消费步、不终结", "同一有效pending安全状态精确比较")
    def test_10_explicit_consent_is_required_and_strict_boolean(self):
        fixture = self.fixture()
        pending, _ = self.fail_once(fixture)
        before_state = fixture.state()
        before_request = fixture.request(pending["request_id"])
        for label, arguments in (("omitted", {}), ("false", {"confirmed": False}), ("integer", {"confirmed": 1}), ("string", {"confirmed": "True"}), ("none", {"confirmed": None})):
            with self.subTest(consent=label):
                self.outcome(fixture.verify(pending, **arguments), "rejected", "explicit_confirmation_required")
                self.assertEqual(fixture.state(), before_state, "missing consent counted as factor failure")
                self.assertEqual(fixture.replay(), [], "missing consent consumed step")
                self.assertEqual(fixture.request(pending["request_id"]), before_request, "missing consent changed request")
        self.passed(fixture.verify(pending, confirmed=True))

    @case("MFA-04/05", "分别错误密码/错误动态码及OTP类型/ASCII/长度/空白变体", "统一verification_failed、不区分因素；不消费正确时间步", "独立fresh前置与失败计数")
    def test_11_factor_failures_and_strict_ascii_otp_format(self):
        variants = ("wrong_password", "wrong_code", "code_none", "code_int", "code_bytes", "empty", "five", "seven", "fullwidth", "arabic", "leading_space", "newline")
        for label in variants:
            with self.subTest(variant=label):
                fixture = self.fixture()
                pending = fixture.red()
                password = fixture.credentials["alice"][0]
                code = fixture.otp()
                if label == "wrong_password": password = random_password()
                elif label == "wrong_code": code = fixture.wrong_otp()
                elif label == "code_none": code = None
                elif label == "code_int": code = int(code)
                elif label == "code_bytes": code = code.encode()
                elif label == "empty": code = ""
                elif label == "five": code = code[:5]
                elif label == "seven": code += "0"
                elif label == "fullwidth": code = "".join(chr(0xFF10 + int(digit)) for digit in code)
                elif label == "arabic": code = "".join(chr(0x0660 + int(digit)) for digit in code)
                elif label == "leading_space": code = " " + code
                elif label == "newline": code += "\n"
                remember(code)
                response = fixture.bank.strong_verify(pending["request_id"], password, code, confirmed=True)
                self.outcome(response, "rejected", "verification_failed")
                self.assertNotIn("strong_verification", response, "failed factor received passed assertion")
                self.assertEqual(fixture.state()["failures"], 1, "factor failure did not count once")
                self.assertEqual(fixture.replay(), [], "failed factor consumed a step")
                self.passed(fixture.verify(pending, confirmed=True))
                self.no_secrets([response, fixture.bank.audit_events()], [password, code] if isinstance(code, str) else [password])

    @case("MFA-05", "当前码及前后各1步、前后2步", "±1通过且消费匹配步，±2统一失败", "独立oracle与replay步比较")
    def test_12_totp_window_uses_exact_matching_step(self):
        for offset in (-2, -1, 0, 1, 2):
            with self.subTest(offset=offset):
                fixture = self.fixture()
                pending = fixture.red()
                response = fixture.verify(pending, code=fixture.otp(offset=offset), confirmed=True)
                if abs(offset) <= 1:
                    self.passed(response)
                    self.assertEqual([row["step"] for row in fixture.replay()], [int(fixture.clock().timestamp()) // 30 + offset], "wrong step consumed")
                else:
                    self.outcome(response, "rejected", "verification_failed")
                    self.assertEqual(fixture.replay(), [], "outside-window code consumed a step")

    @case("MFA-06/07", "黄档confirm打红档、strong_verify打黄档", "分别strong_verification_required/invalid_confirmation且不计失败", "请求仍pending及同用户失败状态")
    def test_13_wrong_verification_channels_do_not_count(self):
        fixture = self.fixture()
        pending = fixture.red()
        state = fixture.state()
        self.outcome(fixture.bank.confirm(pending["request_id"], fixture.wrong_otp()), "rejected", "strong_verification_required")
        self.assertEqual(fixture.state(), state, "wrong red channel counted failure")
        self.assertEqual(fixture.request(pending["request_id"])["status"], "pending", "wrong red channel consumed request")
        yellow = fixture.yellow()
        self.outcome(fixture.verify(yellow, confirmed=True), "rejected", "invalid_confirmation")
        self.assertEqual(fixture.state(), state, "wrong yellow channel counted failure")
        self.assertEqual(fixture.replay(), [], "wrong channel consumed a step")

    @case("MFA-07", "bob用自己的正确因素验证alice红档请求", "invalid_confirmation；不改变双方安全状态和alice pending", "同库可信身份双实例")
    def test_14_wrong_user_cannot_verify_another_request(self):
        fixture = self.fixture()
        fixture.seed_auth("bob")
        pending = fixture.red()
        bob = fixture.open("bob")
        before = fixture.business()
        states = (fixture.state(), fixture.state("bob"))
        response = bob.strong_verify(pending["request_id"], fixture.credentials["bob"][0], fixture.otp("bob"), confirmed=True)
        self.outcome(response, "rejected", "invalid_confirmation")
        self.assertEqual((fixture.state(), fixture.state("bob")), states, "foreign request changed factor state")
        self.assertEqual(fixture.request(pending["request_id"])["status"], "pending", "foreign request consumed owner's pending")
        self.assertEqual(fixture.business(), before, "foreign request changed business")

    @case("MFA-07", "不存在ID及None/bool/int/list/dict/空串等非法ID", "invalid_confirmation、不校验因素或增计数", "公开方法输入边界及安全状态")
    def test_15_invalid_request_ids_never_count_factors(self):
        fixture = self.fixture()
        pending = fixture.red()
        before = fixture.state()
        for label, request_id in (("missing", secrets.token_hex(16)), ("none", None), ("bool", True), ("integer", 1), ("list", []), ("object", {}), ("empty", "")):
            with self.subTest(variant=label):
                response = fixture.bank.strong_verify(request_id, random_password(), fixture.wrong_otp(), confirmed=True)
                self.outcome(response, "rejected", "invalid_confirmation")
                self.assertEqual(fixture.state(), before, "invalid ID counted as factor failure")
                self.assertEqual(fixture.replay(), [], "invalid ID consumed step")
        self.assertEqual(fixture.request(pending["request_id"])["status"], "pending", "invalid ID consumed live request")

    @case("MFA-09", "旧pending后通过propose换金额/联系人/源账户/绿档/黄档任务", "旧请求立即失效且正确因素不能复活", "五种独立公开新任务及请求状态")
    def test_16_new_parameters_or_task_invalidate_old_authorization(self):
        candidates = (
            ("amount", {"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100200}}),
            ("contact", {"intent": "transfer", "params": {"contact_id": "li", "amount_cents": 100100}}),
            ("source", {"intent": "transfer", "params": {"account_id": "alice-savings", "contact_id": "wang", "amount_cents": 100100}}),
            ("green", {"intent": "query_balance", "params": {}}),
            ("yellow", {"intent": "query_subscriptions", "params": {}}),
        )
        for label, candidate in candidates:
            with self.subTest(variant=label):
                fixture = self.fixture()
                old = fixture.red()
                before = fixture.business()
                newer = fixture.bank.propose(candidate)
                self.assertIn(newer.get("status"), ("pending", "success"), "replacement legitimate task not accepted")
                self.outcome(fixture.verify(old, confirmed=True), "rejected", "invalid_confirmation")
                self.assertNotEqual(fixture.request(old["request_id"])["status"], "pending", "old request remains pending")
                self.assertEqual(fixture.state()["failures"], 0, "changed parameters counted factors")
                self.assertEqual(fixture.replay(), [], "changed parameters consumed step")
                self.assertEqual(fixture.business(), before, "replacement waiting/read task changed business")

    @case("MFA-08", "临时库管理员把wang实际账户从bob-main改为alice-savings", "旧绑定invalid_confirmation并终结，不消费步/计失败/转账", "公开contacts列和binding_json、业务快照")
    def test_17_real_contact_mapping_change_invalidates_binding(self):
        fixture = self.fixture()
        pending = fixture.red()
        self.assertIn("bob-main", fixture.request(pending["request_id"])["binding_json"], "real destination missing from persistent binding")
        before = fixture.business()
        fixture.write("UPDATE contacts SET account_id=? WHERE user_id=? AND contact_id=?", ("alice-savings", "alice", "wang"))
        self.outcome(fixture.verify(pending, confirmed=True), "rejected", "invalid_confirmation")
        self.assertNotEqual(fixture.request(pending["request_id"])["status"], "pending", "changed real destination retained authorization")
        self.assertEqual(fixture.state()["failures"], 0, "binding failure counted as factor failure")
        self.assertEqual(fixture.replay(), [], "binding failure consumed step")
        self.assertEqual(fixture.business(), before, "changed mapping redirected funds")

    @case("MFA-10/14", "一次因素失败后取消或close重建同一账本", "旧请求失效，原失败持久保留", "同库重建实例和公开cancel")
    def test_18_cancel_and_restart_preserve_failures_not_authorization(self):
        for action in ("cancel", "restart"):
            with self.subTest(action=action):
                fixture = self.fixture()
                pending, _ = self.fail_once(fixture)
                before = fixture.state()
                old_events = fixture.rows("SELECT * FROM audit_log ORDER BY id")
                if action == "cancel":
                    self.outcome(fixture.bank.cancel(pending["request_id"]), "cancelled")
                else:
                    fixture.bank.close()
                    fixture.bank = fixture.open("alice")
                self.outcome(fixture.verify(pending, confirmed=True), "rejected", "invalid_confirmation")
                self.assertEqual(fixture.state(), before, "cancel/restart cleared persisted failure")
                events = fixture.rows("SELECT * FROM audit_log ORDER BY id")
                self.assertEqual(events[: len(old_events)], old_events, "cancel/restart altered existing audit")
                if action == "restart":
                    self.assertTrue(any(event.get("reason") == "restart" or event.get("event") == "restart" for event in events[len(old_events):]), "restart invalidation missing audit")

    @case("MFA-11", "expires_at前1微秒、恰好期限、后1微秒", "前可MFA，等于或超过即expired且不计失败", "可控带时区时钟精确边界")
    def test_19_exact_five_minute_deadline(self):
        for offset in (-1, 0, 1):
            with self.subTest(microseconds=offset):
                fixture = self.fixture()
                pending = fixture.red()
                fixture.clock.value = datetime.fromisoformat(pending["expires_at"]) + timedelta(microseconds=offset)
                response = fixture.verify(pending, confirmed=True)
                if offset < 0:
                    self.passed(response)
                else:
                    self.outcome(response, "expired")
                    self.assertEqual(fixture.request(pending["request_id"])["status"], "expired", "deadline did not terminate pending")
                    self.assertEqual(fixture.state()["failures"], 0, "expiry counted as factor failure")
                    self.assertEqual(fixture.replay(), [], "expiry consumed step")
                    self.outcome(fixture.verify(pending, confirmed=True), "rejected", "invalid_confirmation")

    @case("MFA-12", "已用步在旧终结/新pending/重启后新pending再次提交", "旧invalid_confirmation不计，新两次分别失败1和2，replay持久", "同一码在内存、同库会话重建")
    def test_20_replay_across_requests_and_sessions(self):
        fixture = self.fixture()
        old = fixture.red()
        used_code = fixture.otp()
        self.passed(fixture.verify(old, code=used_code, confirmed=True))
        self.outcome(fixture.verify(old, code=used_code, confirmed=True), "rejected", "invalid_confirmation")
        self.assertEqual(fixture.state()["failures"], 0, "terminal request replay counted factors")
        for index in (1, 2):
            if index == 2:
                fixture.bank.close()
                fixture.bank = fixture.open("alice")
            pending = fixture.red()
            self.outcome(fixture.verify(pending, code=used_code, confirmed=True), "rejected", "verification_failed")
            self.assertEqual(fixture.state()["failures"], index, "new request replay did not count")
            self.assertEqual(len(fixture.replay()), 1, "replay attempt changed used-step ledger")
        next_pending = fixture.red()
        self.passed(fixture.verify(next_pending, code=fixture.otp(offset=1), confirmed=True))
        self.assertEqual(fixture.state()["failures"], 0, "unused in-window step did not clear failure count")
        self.assertEqual({row["step"] for row in fixture.replay()}, {int(fixture.clock().timestamp()) // 30, int(fixture.clock().timestamp()) // 30 + 1}, "replay protection rejected an unused matching step")

    @case("MFA-13/14", "换目标/金额/账户、取消、新请求、重启过程中三次有效失败", "累计三错十分钟；更换与取消重启不能清零或绕锁", "每动作前后verification_state及锁内黄/红执行拒绝")
    def test_21_lock_survives_parameter_cancel_and_session_changes(self):
        fixture = self.fixture()
        pending, _ = self.fail_once(fixture)
        self.assertEqual(fixture.state()["failures"], 1, "first failure missing")
        fixture.bank.cancel(pending["request_id"])
        pending = fixture.red(amount=100200, contact="li", account="alice-savings")
        self.outcome(fixture.verify(pending, code=fixture.wrong_otp(), confirmed=True), "rejected", "verification_failed")
        self.assertEqual(fixture.state()["failures"], 2, "changed target cleared count")
        fixture.bank.close()
        fixture.bank = fixture.open("alice")
        pending = fixture.red()
        self.outcome(fixture.verify(pending, password=random_password(), confirmed=True), "rejected", "locked")
        state = fixture.state()
        self.assertEqual(state["failures"], 3, "third failure missing")
        self.assertEqual(datetime.fromisoformat(state["locked_until"]), fixture.clock() + timedelta(minutes=10), "lock duration differs")
        self.assert_locked_proposal(fixture, yellow=True)
        self.assert_locked_proposal(fixture)
        fixture.bank.cancel()
        self.assertEqual(fixture.state(), state, "locked cancellation cleared lock")
        fixture.bank.close()
        fixture.bank = fixture.open("alice")
        self.assert_locked_proposal(fixture, yellow=True)
        self.assertEqual(fixture.state(), state, "restart changed lock deadline")

    @case("MFA-13", "黄档错误确认→红档因素错→黄档错误确认", "共用transfer计数1→2→3并锁定，不靠低金额绕过", "同一公开verification_state行")
    def test_22_yellow_and_red_failures_share_operation_counter(self):
        fixture = self.fixture()
        yellow = fixture.yellow()
        wrong = fixture.wrong_otp()
        if wrong == yellow["confirmation_code"]:
            wrong = remember(f"{(int(wrong) + 1) % 1000000:06d}")
        self.outcome(fixture.bank.confirm(yellow["request_id"], wrong), "rejected", "verification_failed")
        self.assertEqual(fixture.state()["failures"], 1, "yellow failure missing")
        red = fixture.red()
        self.outcome(fixture.verify(red, password=random_password(), confirmed=True), "rejected", "verification_failed")
        self.assertEqual(fixture.state()["failures"], 2, "red did not share yellow counter")
        yellow = fixture.yellow()
        bad_code = remember("0" * 6 if yellow["confirmation_code"] != "0" * 6 else "1" * 6)
        self.outcome(fixture.bank.confirm(yellow["request_id"], bad_code), "rejected", "locked")
        self.assertEqual(fixture.state()["failures"], 3, "mixed failures did not lock")
        self.assert_locked_proposal(fixture, yellow=True)

    @case("MFA-15", "锁截止前1微秒、到期和到期后新有效请求错误一次", "锁前拒绝，满十分钟重新计数为1", "可控精确时钟及解锁审计")
    def test_23_ten_minute_lock_expiry_starts_new_counter(self):
        for offset in (0, 1):
            with self.subTest(seconds_after_expiry=offset):
                fixture = self.fixture()
                self.lock(fixture)
                locked_until = datetime.fromisoformat(fixture.state()["locked_until"])
                fixture.clock.value = locked_until - timedelta(microseconds=1)
                self.assert_locked_proposal(fixture, yellow=True)
                self.assertEqual(fixture.state()["failures"], 3, "locked correct attempt cleared count")
                fixture.clock.value = locked_until + timedelta(seconds=offset)
                pending = fixture.red()
                self.outcome(pending, "pending")
                self.outcome(fixture.verify(pending, password=random_password(), confirmed=True), "rejected", "verification_failed")
                self.assertEqual(fixture.state()["failures"], 1, "expired lock did not restart count")
                self.assertIsNone(fixture.state()["locked_until"], "expired lock retained deadline")
                self.assertTrue(any(event.get("event") == "unlocked" for event in fixture.bank.audit_events()), "unlock audit missing")

    @case("MFA-16", "alice transfer锁定后bob小额转账、alice查询/订阅读取及取消", "其他用户和其他操作可按权限成功，不解除alice transfer锁", "双用户金额核对及不同intent安全状态")
    def test_24_lock_scope_is_user_and_operation(self):
        fixture = self.fixture()
        self.lock(fixture)
        alice_state = fixture.state()
        bob = fixture.open("bob")
        pending = fixture.yellow(bob, user_id="bob")
        self.outcome(bob.confirm(pending["request_id"], pending["confirmation_code"]), "success")
        self.outcome(fixture.bank.propose({"intent": "query_balance", "params": {}}), "success")
        for candidate in ({"intent": "query_subscriptions", "params": {}}, {"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}}):
            pending = fixture.bank.propose(candidate)
            self.outcome(pending, "pending")
            self.outcome(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]), "success")
        self.assertEqual(fixture.state(), alice_state, "other intent/user cleared transfer lock")
        balances = {row["account_id"]: row["balance_cents"] for row in fixture.rows("SELECT * FROM accounts")}
        self.assertEqual(balances["alice-main"], 1010000, "bob transfer target amount differs")
        self.assertEqual(balances["bob-main"], 90000, "bob transfer source amount differs")
        self.assertEqual(fixture.state("bob")["failures"], 0, "alice lock blocked bob")

    @case("MFA-15", "未锁定两次红档因素失败后黄档确认成功", "同用户transfer计数清零且只扣本次整数分", "公开黄档通道与余额/失败状态")
    def test_25_unlocked_yellow_success_clears_shared_failures(self):
        fixture = self.fixture()
        pending = fixture.red()
        for _ in range(2):
            fixture.verify(pending, password=random_password(), confirmed=True)
        yellow = fixture.yellow()
        self.outcome(fixture.bank.confirm(yellow["request_id"], yellow["confirmation_code"]), "success")
        self.assertEqual(fixture.state()["failures"], 0, "yellow success did not clear shared failures")
        self.assertIsNone(fixture.state()["locked_until"], "yellow success left lock")

    @case("MFA-17", "合成认证标记原话/额外认证字段/有效码藏目标/带确认pending的模型context", "模型text/context、审计、请求、响应和API输出无秘密", "离线记录器和内存匹配，只报是否匹配", "有限已声明认证格式探针，不证明所有秘密文字识别；无真实模型")
    def test_26_credentials_are_redacted_before_model_and_logs(self):
        fixture = self.fixture()
        password, secret = fixture.credentials["alice"]
        code = fixture.otp()
        api_key = remember("sk-synthetic-" + secrets.token_hex(24))
        yellow = fixture.bank.propose({"intent": "query_subscriptions", "params": {}})
        confirmation = remember(yellow["confirmation_code"])
        model = RecordingModel()
        raw = f"password={password} totp_secret={secret} totp_code={code} api_key={api_key} 查询我的余额"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            response = fixture.bank.handle_text(raw, model)
        sensitive = [password, secret, code, api_key, confirmation]
        self.no_secrets([response, model.calls, fixture.bank.audit_events(), fixture.rows("SELECT * FROM requests"), output.getvalue()], sensitive)
        responses = []
        for candidate in (
            {"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100100}, "password": password, "totp_code": code, "totp_secret": secret, "confirmed": True},
            {"intent": "cancel_subscription", "params": {"subscription_name": code}},
            {"intent": "cancel_subscription", "params": {"subscription_name": "password=" + password}},
        ):
            responses.append(fixture.bank.propose(candidate, raw_input=raw))
        self.assertTrue(all(response.get("status") == "rejected" for response in responses), "untrusted credential-bearing candidate accepted")
        self.no_secrets([responses, fixture.bank.audit_events(), fixture.rows("SELECT * FROM requests")], sensitive)

    @case("MFA-18", "追加多种流程后同库重建；管理员尝试UPDATE/DELETE审计", "已有回执内容不变，必要字段齐全，删改被数据库规则阻止", "公开audit_events与audit_log触发器")
    def test_27_audit_is_append_only_and_correlated(self):
        fixture = self.fixture()
        initial = fixture.rows("SELECT * FROM audit_log ORDER BY id")
        pending, _ = self.fail_once(fixture)
        fixture.bank.cancel(pending["request_id"])
        expired = fixture.red()
        fixture.clock.advance(300)
        self.outcome(fixture.verify(expired, confirmed=True), "expired")
        passed = fixture.red()
        self.passed(fixture.verify(passed, confirmed=True))
        events = fixture.rows("SELECT * FROM audit_log ORDER BY id")
        self.assertEqual(events[: len(initial)], initial, "existing audit changed")
        self.assertEqual([event["id"] for event in events], sorted({event["id"] for event in events}), "audit IDs not unique/increasing")
        required = {"id", "timestamp", "request_id", "step_id", "user_id", "raw_input_redacted", "intent", "tier", "params_redacted", "event", "result", "reason"}
        for event in events:
            self.assertTrue(required.issubset(event), "audit public fields missing")
            self.assertEqual(event["user_id"], "alice", "audit exposed another user")
        for request in (pending, expired, passed):
            self.assertTrue(any(event.get("request_id") == request["request_id"] for event in events), "flow lacks request-correlated receipt")
        with contextlib.closing(sqlite3.connect(fixture.path)) as connection:
            for operation in ("UPDATE audit_log SET reason='synthetic' WHERE id=(SELECT MIN(id) FROM audit_log)", "DELETE FROM audit_log WHERE id=(SELECT MIN(id) FROM audit_log)"):
                with self.assertRaises(sqlite3.DatabaseError, msg="audit mutation must be rejected"):
                    connection.execute(operation)
        self.assertEqual(fixture.rows("SELECT * FROM audit_log ORDER BY id"), events, "audit mutation altered rows")
        fixture.bank.close()
        fixture.bank = fixture.open("alice")
        self.assertEqual(fixture.rows("SELECT * FROM audit_log ORDER BY id")[: len(events)], events, "restart changed saved audit")

    @case("MFA-18", "两错后对strong_verified注入audit_hook故障", "failed/audit_unavailable；步/清零/终结/新日志全部回滚并停后续业务", "MFA元数据、审计与四张业务表前后精确比较")
    def test_28_success_audit_failure_rolls_back_all_mfa_metadata(self):
        fixture = self.fixture()
        pending = fixture.red()
        for _ in range(2):
            fixture.verify(pending, password=random_password(), confirmed=True)
        before = (fixture.business(), fixture.state(), fixture.replay(), fixture.request(pending["request_id"]), fixture.rows("SELECT * FROM audit_log ORDER BY id"))
        fixture.audit_fault.event = "strong_verified"
        self.outcome(fixture.verify(pending, confirmed=True), "failed", "audit_unavailable")
        after = (fixture.business(), fixture.state(), fixture.replay(), fixture.request(pending["request_id"]), fixture.rows("SELECT * FROM audit_log ORDER BY id"))
        self.assertEqual(after[:4], before[:4], "MFA metadata was partially committed despite audit fault")
        self.assertEqual(after[4], before[4], "MFA audit prefix partially committed")
        fixture.audit_fault.event = None
        self.outcome(fixture.bank.propose({"intent": "query_balance", "params": {}}), "failed", "audit_unavailable")
        self.assertEqual(fixture.business(), before[0], "halted service continued business")

    @case("MFA-18", "verification_failed或第三错locked日志故障", "失败计数/锁定/请求/日志一起回滚，后续halt", "故障前0或2次失败的精确安全状态")
    def test_29_failure_counter_audit_fault_is_atomic(self):
        for fault_event, prior_failures in (("verification_failed", 0), ("locked", 2)):
            with self.subTest(fault=fault_event):
                fixture = self.fixture()
                pending = fixture.red()
                for _ in range(prior_failures):
                    fixture.verify(pending, password=random_password(), confirmed=True)
                before = (fixture.state(), fixture.replay(), fixture.request(pending["request_id"]), fixture.rows("SELECT * FROM audit_log ORDER BY id"), fixture.business())
                fixture.audit_fault.event = fault_event
                self.outcome(fixture.verify(pending, password=random_password(), confirmed=True), "failed", "audit_unavailable")
                after = (fixture.state(), fixture.replay(), fixture.request(pending["request_id"]), fixture.rows("SELECT * FROM audit_log ORDER BY id"), fixture.business())
                self.assertEqual(after, before, "failed verification metadata partially committed")
                fixture.audit_fault.event = None
                self.outcome(fixture.bank.propose({"intent": "query_balance", "params": {}}), "failed", "audit_unavailable")

    @case("MFA-18/20", "黄档转账executed审计故障", "双方余额/流水/转账和成功确认全回滚，后续halt", "合法黄档金额和业务前后快照")
    def test_30_yellow_transfer_audit_fault_never_leaves_partial_money(self):
        fixture = self.fixture()
        pending = fixture.yellow()
        before = fixture.business()
        fixture.audit_fault.event = "executed"
        self.outcome(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]), "failed", "audit_unavailable")
        self.assertEqual(fixture.business(), before, "yellow audit failure partially moved money")
        fixture.audit_fault.event = None
        self.outcome(fixture.bank.propose({"intent": "query_balance", "params": {}}), "failed", "audit_unavailable")

    @case("MFA-02/04", "管理员构造损坏hash/盐/迭代/secret及KDF上下界", "损坏fail closed无内部异常，20万和200万均可独立验证", "公开strong_auth行及独立PBKDF2 oracle")
    def test_31_credential_corruption_fails_closed_and_kdf_bounds_work(self):
        variants = (("hash_short", "password_hash", "a" * 63), ("hash_bad_hex", "password_hash", "z" * 64), ("salt_short", "password_salt", "a" * 30), ("salt_long", "password_salt", "a" * 34), ("salt_bad_hex", "password_salt", "z" * 32), ("iterations_low", "kdf_iterations", 199999), ("iterations_high", "kdf_iterations", 2000001), ("iterations_bad_type", "kdf_iterations", "not-an-integer"), ("secret_short", "totp_secret", base64.b32encode(b"x" * 19).decode()), ("secret_bad_alphabet", "totp_secret", "!" * 32))
        for label, field, replacement in variants:
            with self.subTest(variant=label):
                fixture = self.fixture()
                pending = fixture.red()
                before = fixture.business()
                try:
                    fixture.write(f"UPDATE strong_auth SET {field}=? WHERE user_id='alice'", (replacement,))
                except sqlite3.IntegrityError:
                    # A database constraint is an acceptable earlier fail-closed boundary.
                    continue
                response = fixture.verify(pending, confirmed=True)
                self.outcome(response, "rejected", "verification_failed")
                self.assertNotIn("strong_verification", response, "damaged credential passed")
                self.assertEqual(fixture.business(), before, "damaged credential executed money")
                self.assertEqual(fixture.replay(), [], "damaged credential consumed step")
        for count in (200000, 2000000):
            with self.subTest(valid_iterations=count):
                fixture = self.fixture(False)
                fixture.seed_auth(iterations=count)
                self.passed(fixture.verify(fixture.red(), confirmed=True))

    @case("MFA-12/18", "临时库旧replay含code/重复同用户步，重新初始化", "移除code保留用户+步、业务/审计/verification_state不清", "公开旧表合成夹具与迁移前后快照", "正常旧表迁移；未提供迁移写故障注入接口，不声称故障迁移已测")
    def test_32_legacy_replay_migration_keeps_used_steps_and_ledger(self):
        fixture = self.fixture()
        fixture.seed_auth("bob")
        fixture.write("INSERT INTO verification_state(user_id,intent,failures,locked_until) VALUES(?,?,?,?)", ("alice", "transfer", 1, None))
        fixture.bank.propose({"intent": "query_balance", "params": {}})
        before_business = fixture.business()
        before_state = fixture.state()
        before_events = fixture.rows("SELECT * FROM audit_log ORDER BY id")
        fixture.bank.close()
        step = int(fixture.clock().timestamp()) // 30
        with contextlib.closing(sqlite3.connect(fixture.path)) as connection:
            connection.execute("DROP TABLE strong_auth_replay")
            connection.execute("CREATE TABLE strong_auth_replay(user_id TEXT NOT NULL,step INTEGER NOT NULL,code TEXT NOT NULL,used_at TEXT NOT NULL,PRIMARY KEY(user_id,step,code))")
            connection.executemany("INSERT INTO strong_auth_replay VALUES(?,?,?,?)", (("alice", step, fixture.otp(), fixture.clock().isoformat()), ("alice", step, fixture.wrong_otp(), fixture.clock().isoformat()), ("alice", step - 1, fixture.otp(offset=-1), fixture.clock().isoformat()), ("bob", step, fixture.otp("bob"), fixture.clock().isoformat())))
            connection.commit()
        fixture.bank = fixture.open("alice")
        columns = {row["name"] for row in fixture.rows("PRAGMA table_info(strong_auth_replay)")}
        self.assertEqual(columns, {"user_id", "step", "used_at"}, "migration retained code or lost public fields")
        self.assertEqual({(row["user_id"], row["step"]) for row in fixture.replay()}, {("alice", step), ("alice", step - 1), ("bob", step)}, "migration lost used user steps")
        self.assertEqual(fixture.business(), before_business, "migration cleared business ledger")
        self.assertEqual(fixture.state(), before_state, "migration cleared verification state")
        self.assertEqual(fixture.rows("SELECT * FROM audit_log ORDER BY id")[: len(before_events)], before_events, "migration changed audit history")
        self.outcome(fixture.verify(fixture.red(), confirmed=True), "rejected", "verification_failed")
        self.assertEqual(fixture.state()["failures"], 2, "migrated used step did not block replay")

    @case("MFA-19", "计划红档前置正确MFA后resume依赖取消订阅", "红档仍拒绝且后续依赖不执行", "公开plan.steps回执及业务状态")
    def test_33_refused_red_plan_cannot_release_dependency(self):
        fixture = self.fixture()
        before = fixture.business()
        response = fixture.bank.propose({"steps": [{"id": "pay", "intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100100}, "depends_on": []}, {"id": "cancel", "intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}, "depends_on": ["pay"]}]})
        self.outcome(response, "pending")
        self.passed(fixture.verify(response, confirmed=True))
        resumed = fixture.bank.resume_plan(response["plan_id"])
        steps = resumed.get("plan", {}).get("steps", [])
        self.assertTrue(steps, "plan refusal must retain reviewable steps")
        self.assertEqual(resumed.get("plan", {}).get("status"), "failed", "refused prerequisite did not stop plan")
        self.assertTrue(all(step.get("status") not in ("pending", "success") for step in steps if step.get("id") == "cancel"), "dependent task advanced despite refusal")
        self.assertEqual(fixture.business(), before, "refused plan changed business")

    @case("MFA-02/19", "存在未完成订阅计划时本机reset", "旧pending和未完成计划授权全部失效", "公开confirm/resume、订阅状态")
    def test_34_reset_invalidates_unfinished_plan(self):
        fixture = self.fixture()
        response = fixture.bank.propose({"steps": [{"id": "subs", "intent": "query_subscriptions", "params": {}, "depends_on": []}, {"id": "cancel", "intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}, "depends_on": ["subs"]}]})
        self.outcome(response, "pending")
        self.outcome(fixture.bank.unenroll_strong_auth(), "success")
        self.outcome(fixture.bank.confirm(response["request_id"], response["confirmation_code"]), "rejected", "invalid_confirmation")
        resumed = fixture.bank.resume_plan(response["plan_id"])
        stopped_plan = resumed.get("plan", {}).get("status") in ("failed", "interrupted", "human_takeover")
        self.assertTrue(stopped_plan or resumed.get("status") in ("rejected", "failed", "cancelled", "expired"), "reset did not invalidate incomplete plan")
        self.assertEqual(fixture.rows("SELECT status FROM subscriptions WHERE subscription_id='sub-video'")[0]["status"], "active", "reset continued dependent cancellation")

    @case("MFA-20", "账单、订阅查询/取消、小额转账/重复/累计1000元边界", "原三方向事实与整数分正确；累计恰阈黄、超过红不执行", "初始公开夹具和数据库金额/历史对照", "本文件只做核心新回归；既有完整套件由root原样执行并另存证据")
    def test_35_three_original_scenarios_and_daily_boundary(self):
        fixture = self.fixture()
        bills = fixture.bank.propose({"intent": "analyze_bills", "params": {}})
        self.outcome(bills, "success")
        self.assertEqual(bills["data"]["actual_expense_cents"], 5970, "actual bills differ")
        history = fixture.rows("SELECT * FROM transactions ORDER BY transaction_id")
        pending = fixture.bank.propose({"intent": "query_subscriptions", "params": {}})
        self.assertNotIn("subscriptions", pending.get("data", {}), "subscriptions disclosed before consent")
        listed = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
        self.outcome(listed, "success")
        self.assertEqual(len(listed["data"]["subscriptions"]), 3, "subscription fixture differs")
        pending = fixture.bank.propose({"intent": "cancel_subscription", "params": {"subscription_id": "sub-video"}})
        self.outcome(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]), "success")
        self.assertEqual(fixture.rows("SELECT * FROM transactions ORDER BY transaction_id"), history, "cancel erased actual expense history")
        pending = fixture.bank.propose({"intent": "query_subscriptions", "params": {}})
        after_cancel = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
        self.assertEqual(after_cancel["data"]["future_expected_cents"], 2980, "future subscription expense differs")
        pending = fixture.yellow()
        response = fixture.bank.confirm(pending["request_id"], pending["confirmation_code"])
        self.outcome(response, "success")
        self.outcome(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]), "rejected", "invalid_confirmation")
        balances = {row["account_id"]: row["balance_cents"] for row in fixture.rows("SELECT * FROM accounts")}
        self.assertEqual((balances["alice-main"], balances["bob-main"]), (990000, 110000), "small transfer or duplicate amount differs")
        pending = fixture.yellow(amount=90000)
        self.assertEqual(pending.get("tier"), "yellow", "exact daily threshold must be yellow")
        self.outcome(fixture.bank.confirm(pending["request_id"], pending["confirmation_code"]), "success")
        pending = fixture.red(amount=1)
        self.assertEqual(pending.get("tier"), "red", "daily threshold crossing must be red")
        before = fixture.business()
        self.passed(fixture.verify(pending, confirmed=True))
        self.assertEqual(fixture.business(), before, "threshold red request executed")

    @case("MFA-06/19", "模型声称passed/confirmed/green，额外认证字段/未知意图/他人源账户", "固定白名单和归属拒绝，声明不授予MFA或权限", "候选公开API与业务快照")
    def test_36_untrusted_model_claims_cannot_authorize(self):
        fixture = self.fixture()
        before = fixture.business()
        normal = {"intent": "transfer", "params": {"contact_id": "wang", "amount_cents": 100100}}
        candidates = (
            ("passed", {**normal, "strong_verification": "passed"}),
            ("confirmed", {**normal, "confirmed": True}),
            ("tier", {**normal, "tier": "green"}),
            ("credentials", {**normal, "password": fixture.credentials["alice"][0], "totp_code": fixture.otp()}),
            ("foreign_source", {"intent": "transfer", "params": {"account_id": "bob-main", "contact_id": "wang", "amount_cents": 100100}}),
            ("unsupported", {"intent": "strong_verify", "params": {"confirmed": True}}),
        )
        for label, candidate in candidates:
            with self.subTest(claim=label):
                response = fixture.bank.propose(candidate)
                self.outcome(response, "rejected")
                self.assertNotIn("strong_verification", response, "untrusted claim received authentication")
                self.assertEqual(fixture.business(), before, "untrusted model claim changed business")

    @case("CLI", "两个公开CLI的--help子进程", "入口可运行并公开db/user及reset或amount参数", "独立Python-B子进程退出码和帮助字段")
    def test_37_public_cli_help_is_runnable(self):
        for filename, required in (("mfa_enroll.py", ("--db", "--user", "--reset")), ("mfa_verify.py", ("--db", "--user", "--amount"))):
            with self.subTest(cli=filename):
                process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts" / filename), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, 0, "public CLI help failed")
                self.assertIsInstance(process.stdout, str, "public CLI help capture must return text")
                for parameter in required:
                    self.assertIn(parameter, process.stdout, "public CLI help parameter missing")

    def run_verify_cli(self, fixture, consent, password, code):
        arguments = [str(ROOT / "scripts" / "mfa_verify.py"), "--db", str(fixture.path), "--user", "alice", "--amount", "1001"]
        output = io.StringIO()
        passwords = [password, code]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with patch.object(sys, "argv", arguments), patch.object(sys.stdin, "isatty", return_value=True), patch.object(sys.stdout, "isatty", return_value=True), patch.object(sys.stderr, "isatty", return_value=True), patch("builtins.input", return_value=consent) as approval, patch("getpass.getpass", side_effect=passwords) as hidden:
                try:
                    runpy.run_path(arguments[0], run_name="__main__")
                except SystemExit as exit_result:
                    exit_code = exit_result.code
                else:
                    exit_code = 0
        return output.getvalue(), approval.call_count, hidden.call_count, exit_code

    @case("CLI/MFA-06", "仅mock标准库终端输入，固定同意后两个getpass因素", "展示当前操作/期限，验证passed但隔离拒绝，秘密不输出", "执行公开CLI主入口、调用次数和公开表", "自动模拟终端；真人无回显及独立手机仍未运行")
    def test_38_cli_verification_explicit_consent_and_hidden_factors(self):
        fixture = self.fixture(clock=MutableClock(datetime.now(SHANGHAI)))
        before = fixture.business()
        output, approvals, hidden_inputs, _ = self.run_verify_cli(fixture, "确认本次操作", fixture.credentials["alice"][0], fixture.otp())
        self.assertEqual(approvals, 1, "CLI must ask once for exact operation approval")
        self.assertEqual(hidden_inputs, 2, "CLI factors must use getpass twice")
        self.no_secrets(output, [*fixture.credentials["alice"], fixture.otp()])
        for fact in ("alice-main", "bob-main"):
            self.assertIn(fact, output, "CLI omitted bound operation fact")
        self.assertTrue("1001" in output or "100100" in output, "CLI omitted reviewed amount")
        request = fixture.rows("SELECT * FROM requests ORDER BY created_at DESC")[0]
        self.assertIn(request["expires_at"][:19], output, "CLI omitted exact operation deadline")
        self.assertTrue(any(event.get("event") == "strong_verified" for event in fixture.rows("SELECT * FROM audit_log")), "CLI did not complete factors validation")
        self.assertTrue(any(event.get("reason") == "isolation_unavailable" for event in fixture.rows("SELECT * FROM audit_log")), "CLI factors bypassed isolation")
        self.assertEqual(fixture.business(), before, "CLI executed red business")

    @case("CLI/MFA-06", "公开CLI固定同意不匹配或明确拒绝", "取消pending且完全不读取因素/消费步", "只mock标准库input/getpass，公开请求和replay")
    def test_39_cli_refusing_consent_never_reads_factors(self):
        for consent in ("不要执行", "确认"):
            with self.subTest(consent_variant=consent):
                fixture = self.fixture(clock=MutableClock(datetime.now(SHANGHAI)))
                before = fixture.business()
                output, approvals, hidden_inputs, _ = self.run_verify_cli(fixture, consent, fixture.credentials["alice"][0], fixture.otp())
                self.assertEqual(approvals, 1, "CLI did not ask operation approval")
                self.assertEqual(hidden_inputs, 0, "CLI read factors without exact consent")
                self.assertEqual(fixture.replay(), [], "CLI refused consent consumed step")
                self.assertEqual(fixture.rows("SELECT status FROM requests")[0]["status"], "cancelled", "CLI refusal did not cancel pending")
                self.assertEqual(fixture.business(), before, "CLI refusal changed business")
                self.no_secrets(output, [*fixture.credentials["alice"], fixture.otp()])

    @case("MFA-11/18", "审计公开hook推进clock至expires_at", "成功验证尚未完成提交前过期：expired、零步消费、保留失败计数", "在confirmed/strong_verified事件推进公开时钟、检查事务元数据")
    def test_40_deadline_crossed_during_success_path_is_not_authorized(self):
        for event_name in ("confirmed", "strong_verified"):
            with self.subTest(clock_advanced_at=event_name):
                fixture = self.fixture()
                pending, _ = self.fail_once(fixture)
                code_before_deadline = fixture.otp()
                state_before = fixture.state()
                business_before = fixture.business()
                audit_before = fixture.rows("SELECT * FROM audit_log ORDER BY id")
                deadline = datetime.fromisoformat(pending["expires_at"])
                def advance_clock(event):
                    if event.get("event") == event_name:
                        fixture.clock.value = deadline
                fixture.audit_fault.on_event = advance_clock
                response = fixture.verify(pending, code=code_before_deadline, confirmed=True)
                self.outcome(response, "expired")
                self.assertEqual(fixture.state(), state_before, "cross-deadline success cleared failures")
                self.assertEqual(fixture.replay(), [], "cross-deadline success consumed step")
                self.assertEqual(fixture.business(), business_before, "cross-deadline success changed business")
                self.assertEqual(fixture.request(pending["request_id"])["status"], "expired", "cross-deadline request not expired")
                new_events = fixture.rows("SELECT * FROM audit_log ORDER BY id")[len(audit_before):]
                self.assertFalse(any(event.get("event") == "strong_verified" for event in new_events), "expired success log partially committed")

    @case("MFA-17", "普通聊天误贴整段/strip后口令、已登记secret大小写/空白变体和六位数字", "已知因素secret_input且不调模型；六位数字不进入模型", "只用公开handle_text和离线模型记录器", "只覆盖新公布的有限误粘贴规则，不要求识别任意混杂/编码无标签口令")
    def test_41_known_credentials_pasted_to_chat_never_reach_model(self):
        fixture = self.fixture()
        password, secret = fixture.credentials["alice"]
        code = fixture.otp()
        lower_secret = remember(secret.lower())
        spaced_secret = remember(" ".join(secret.lower()))
        variants = (("whole_password", password), ("stripped_password", " \t" + password + " \n"), ("whole_secret", secret), ("lower_secret_in_text", "认证器 " + lower_secret + " 查询余额"), ("spaced_secret_in_text", "认证器 " + spaced_secret + " 查询余额"), ("tagged_password", "password=" + password))
        before = fixture.business()
        for label, text in variants:
            with self.subTest(variant=label):
                model = RecordingModel()
                response = fixture.bank.handle_text(text, model)
                self.outcome(response, "rejected", "secret_input")
                self.assertEqual(model.calls, [], "known credential reached model invocation")
                self.no_secrets([response, fixture.bank.audit_events(), fixture.rows("SELECT * FROM requests")], [password, secret, lower_secret, spaced_secret, code])
                self.assertEqual(fixture.business(), before, "credential paste changed business")
        model = RecordingModel()
        response = fixture.bank.handle_text("查询余额 " + code, model)
        self.no_secrets([model.calls, response, fixture.bank.audit_events()], [code, password, secret])

    @case("MFA-17", "已知本人口令/secret误填候选白名单字符串及confirm/strong_verify编号", "拒绝不回显、不落审计/请求、不计因素失败或消费步", "公开候选与固定接口的内存输出匹配")
    def test_42_known_credentials_in_audit_parameters_and_invalid_ids_are_redacted(self):
        fixture = self.fixture()
        password, secret = fixture.credentials["alice"]
        code = fixture.otp()
        responses = []
        for value in (password, secret, remember(secret.lower()), remember(" ".join(secret.lower()))):
            responses.append(fixture.bank.propose({"intent": "cancel_subscription", "params": {"subscription_name": value}}))
        for request_id in (password, secret):
            responses.append(fixture.bank.confirm(request_id, fixture.wrong_otp()))
            responses.append(fixture.bank.strong_verify(request_id, password, code, confirmed=True))
        self.assertTrue(all(response.get("status") == "rejected" for response in responses), "known credential input authorized an operation")
        self.no_secrets([responses, fixture.bank.audit_events(), fixture.rows("SELECT * FROM requests")], [password, secret, secret.lower(), " ".join(secret.lower()), code])
        self.assertEqual(fixture.state()["failures"], 0, "invalid credential ID counted factor failure")
        self.assertEqual(fixture.replay(), [], "invalid credential ID consumed step")

    @case("CLI", "两个公开CLI的stdin/stdout/stderr分别非TTY", "拒绝且不开数据库、不调用input/getpass", "仅标准库三流isatty模拟及新路径不存在性", "模拟重定向边界，不证明真人终端无回显")
    def test_43_cli_requires_all_three_streams_to_be_interactive(self):
        for filename in ("mfa_enroll.py", "mfa_verify.py"):
            for stream in ("stdin", "stdout", "stderr"):
                with self.subTest(cli=filename, noninteractive=stream):
                    with tempfile.TemporaryDirectory(prefix="fintech-mfa-cli-independent-") as directory:
                        path = Path(directory) / "must-not-open.sqlite"
                        arguments = [str(ROOT / "scripts" / filename), "--db", str(path), "--user", "alice"]
                        if filename == "mfa_verify.py":
                            arguments.extend(["--amount", "1001"])
                        stdout, stderr = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            with patch.object(sys, "argv", arguments), patch.object(sys.stdin, "isatty", return_value=stream != "stdin"), patch.object(sys.stdout, "isatty", return_value=stream != "stdout"), patch.object(sys.stderr, "isatty", return_value=stream != "stderr"), patch("builtins.input") as approval, patch("getpass.getpass") as hidden:
                                try:
                                    runpy.run_path(arguments[0], run_name="__main__")
                                except SystemExit:
                                    pass
                        self.assertEqual(approval.call_count, 0, "non-TTY CLI asked interactive approval")
                        self.assertEqual(hidden.call_count, 0, "non-TTY CLI read factors")
                        self.assertFalse(path.exists(), "non-TTY CLI opened bank ledger")


class EvidenceResult(unittest.TestResult):
    """Avoid traceback source or sensitive repr; evidence contains safe outcomes."""
    def __init__(self):
        super().__init__()
        self.records = []
        self.subtests = []
        self.active = {}

    def startTest(self, test):
        super().startTest(test)
        method = getattr(test, test._testMethodName)
        self.active[test.id()] = {"test": test._testMethodName, **getattr(method, "acceptance_metadata", {}), "run": True, "status": "passed", "actual": "全部公开断言通过", "started": time.perf_counter()}
        self.active[test.id()]["problems"] = []

    def _exc_info_to_string(self, error, test):
        return sanitized(f"{error[0].__name__}: {error[1]}")

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.active[test.id()].update(status="failed", actual=self._exc_info_to_string(error, test))
        self.active[test.id()]["problems"].append(self._exc_info_to_string(error, test))

    def addError(self, test, error):
        super().addError(test, error)
        self.active[test.id()].update(status="error", actual=self._exc_info_to_string(error, test))
        self.active[test.id()]["problems"].append(self._exc_info_to_string(error, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.active[test.id()].update(status="skipped", actual=sanitized(reason))

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        record = {"test": test._testMethodName, "case": sanitized(subtest._subDescription()), "status": "passed" if error is None else "failed", "actual": "公开子断言通过" if error is None else self._exc_info_to_string(error, subtest)}
        self.subtests.append(record)
        if error is not None:
            self.active[test.id()].update(status="failed", actual=record["actual"])
            self.active[test.id()]["problems"].append(record["actual"])

    def stopTest(self, test):
        record = self.active.pop(test.id())
        record["duration_seconds"] = round(time.perf_counter() - record.pop("started"), 3)
        self.records.append(record)
        super().stopTest(test)


def source_hashes():
    """Hash bytes only; never decode or display implementation contents."""
    paths = [ROOT / "src" / "bank.py", ROOT / "src" / "strong_auth.py", ROOT / "scripts" / "mfa_enroll.py", ROOT / "scripts" / "mfa_verify.py", Path(__file__), ROOT / "src" / "PUBLIC_API.md", ROOT / "docs" / "22-mfa-strong-verification.md"]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}


def main():
    started = datetime.now(timezone.utc).isoformat()
    initial_hashes = source_hashes()
    cli_probe = "--cli-probe" in sys.argv
    if cli_probe:
        names = ["test_37_public_cli_help_is_runnable", "test_38_cli_verification_explicit_consent_and_hidden_factors", "test_39_cli_refusing_consent_never_reads_factors", "test_43_cli_requires_all_three_streams_to_be_interactive"]
        suite = unittest.TestSuite(IndependentMfaAcceptance(name) for name in names)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(IndependentMfaAcceptance)
    result = EvidenceResult()
    begin = time.perf_counter()
    incidental_output = io.StringIO()
    with contextlib.redirect_stdout(incidental_output), contextlib.redirect_stderr(incidental_output):
        suite.run(result)
    duration = round(time.perf_counter() - begin, 3)
    output_disclosure = any(value and value in incidental_output.getvalue() for value in SECRET_VALUES)
    exit_code = 0 if result.wasSuccessful() and not output_disclosure else 1
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {"schema_version": 1, "attempts": []}
    attempt = {
        "attempt": len(evidence["attempts"]) + 1,
        "scope": "cli_scaffold_probe" if cli_probe else "full_new_mfa_suite",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python -B -X utf8 tests/test_mfa_independent_acceptance.py" + (" --cli-probe" if cli_probe else ""),
        "exit_code": exit_code,
        "duration_seconds": duration,
        "source_hashes_sha256_before": initial_hashes,
        "source_hashes_sha256_after": source_hashes(),
        "test_methods_run": result.testsRun,
        "method_outcomes": {outcome: sum(record["status"] == outcome for record in result.records) for outcome in ("passed", "failed", "error", "skipped")},
        "subtests_run": len(result.subtests),
        "subtest_outcomes": {outcome: sum(record["status"] == outcome for record in result.subtests) for outcome in ("passed", "failed")},
        "incidental_stdout_stderr_credential_match": output_disclosure,
        "methods": result.records,
        "subtests": result.subtests,
        "limitations": ["合成离线因素与临时账本；无真人登记或独立手机证据", "CLI无回显只验证getpass调用；实际终端无回显待真人", "无真实模型、MFA HTTP入口、正式受限隔离或完整补偿验证", "完整既有测试由root另运行；旧测试期望未读未改", "正常旧replay迁移已纳入；迁移存储失败没有公开注入接口"],
    }
    final_status = ("probe_passed_awaiting_full_run" if cli_probe else "passed") if exit_code == 0 else "failed"
    evidence.update({"status": final_status, "planned_methods": len(unittest.defaultTestLoader.getTestCaseNames(IndependentMfaAcceptance)), "test_methods_run": result.testsRun, "subtests_run": len(result.subtests), "latest_attempt_summary": {"attempt": attempt["attempt"], "scope": attempt["scope"], "exit_code": exit_code, "duration_seconds": duration, "method_outcomes": attempt["method_outcomes"], "subtest_outcomes": attempt["subtest_outcomes"]}, "independence": "仅公开契约及RFC6238确定期望；未读实现或旧测试；实现仅作字节hash", "credential_policy": "全部凭据动态合成，秘密和有效OTP仅在临时库/内存；证据不记录其值", "human_enrollment": "not_run", "human_independent_device": "not_run", "human_terminal_no_echo": "not_run"})
    evidence["attempts"].append(attempt)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for record in result.records:
        print(f"{record['test']}: {record['status']}")
    print(f"methods={result.testsRun}; subtests={len(result.subtests)}; exit_code={exit_code}; evidence=evidence/mfa-independent-acceptance.json")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

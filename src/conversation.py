"""当前会话的安全草稿；文字可补参数，不能补授权。"""

import copy
import re
import uuid
from datetime import date, datetime

from .recovery_state import PARAMETERS
from .six_conversation import (
    NEW_PARAMETERS, REQUIRED_PARAMETERS, NEW_MISSING_FIELDS,
    check_draft_parameter, extract_new_facts, new_human_intents, redact_unlabeled_six_digits,
    requests_unsupported_automation,
)


MISSING_ORDER = ("intent", "contact", "amount_cents", "subscription", "account_id") + NEW_MISSING_FIELDS
MONEY_NUMBER = r"负?-?\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+|[A-Za-z]+"
MONEY_WITH_UNIT = re.compile(r"(?<![A-Za-z0-9_.])(" + MONEY_NUMBER + r")\s*(?:元|块)")
CHINESE_DIGITS = {character: value for value, characters in enumerate(("零〇", "一", "二两", "三", "四", "五", "六", "七", "八", "九")) for character in characters}


def chinese_integer(text):
    """只接受位值明确的中文整数，避免把“一百一”猜作另一金额。"""
    if not text or any(character not in CHINESE_DIGITS and character not in "十百千万" for character in text):
        return None
    if text in CHINESE_DIGITS:
        return CHINESE_DIGITS[text]
    if text.count("万") > 1:
        return None
    if "万" in text:
        high, low = text.split("万")
        high_value = chinese_integer(high)
        low_value = chinese_integer(low.lstrip("零〇")) if low.lstrip("零〇") else 0
        if high_value is None or low_value is None or not 0 < high_value < 10000 or low_value >= 10000:
            return None
        return high_value * 10000 + low_value
    total, digit, previous_unit, zero_separator = 0, None, 10000, False
    for index, character in enumerate(text):
        if character in CHINESE_DIGITS:
            value = CHINESE_DIGITS[character]
            if value == 0:
                if digit is not None or index == 0 or index == len(text) - 1:
                    return None
                zero_separator = True
                continue
            if digit is not None:
                return None
            digit = value
            if index == len(text) - 1 and previous_unit > 10 and not zero_separator:
                return None
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[character]
            if unit >= previous_unit or (digit is None and not (index == 0 and unit == 10)):
                return None
            total += (digit if digit is not None else 1) * unit
            digit, previous_unit, zero_separator = None, unit, False
    return total + (digit or 0)


def exact_cents(number):
    """十进制文字直接换算整数分，不经过浮点。"""
    if re.fullmatch(r"-?\d+(?:\.\d+)?", number):
        if number.startswith("-"):
            raise ValueError("invalid_amount")
        whole, separator, fraction = number.partition(".")
        if separator and len(fraction) > 2:
            raise ValueError("invalid_amount")
        amount = int(whole) * 100 + int((fraction + "00")[:2])
    elif number.startswith("负") or re.fullmatch(r"[A-Za-z]+", number):
        raise ValueError("invalid_amount")
    else:
        value = chinese_integer(number)
        if value is None:
            return None
        amount = value * 100
    if not 0 < amount <= 10 ** 12:
        raise ValueError("invalid_amount")
    return amount


def valid_chat_text(text):
    return (type(text) is str and 1 <= len(text) <= 2000 and bool(text.strip())
            and not any(ord(character) == 127 or ord(character) < 32 and character not in "\t\r\n" for character in text))


def unquoted_text(text):
    """引述的外部内容不能当作本人选择收款目标。"""
    return re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"|`[^`]*`', "", text)


class ConversationMixin:
    def _initialize_conversation_memory(self):
        self._conversation_task = None
        self._conversation_messages = []
        self._conversation_request_id = None
        self._conversation_submitting = False

    def _clear_conversation(self, reason, request_id=None, *, audit=True):
        task = self._conversation_task
        had_context = task is not None or bool(self._conversation_messages)
        self._conversation_task = None
        self._conversation_messages = []
        self._conversation_request_id = None
        if had_context and audit:
            self._audit(request_id or uuid.uuid4().hex, task["intent"] if task else "unknown", "none",
                        "context_cleared", "success", reason, task["params"] if task else {})

    def _conversation_terminal_event(self, request_id, associated):
        if (self._conversation_request_id == request_id and associated is not None
                and associated["status"] in {"success", "failed", "rejected", "cancelled", "expired"}):
            self._clear_conversation("task_" + associated["status"], request_id)

    def _conversation_previous(self):
        if self._conversation_request_id:
            row = self.connection.execute("SELECT status,expires_at FROM requests WHERE request_id=? AND user_id=?",
                                          (self._conversation_request_id, self.user_id)).fetchone()
            if not row or row["status"] != "pending" or self._now() >= datetime.fromisoformat(row["expires_at"]):
                self._clear_conversation("task_ended_or_expired")
        return copy.deepcopy(self._conversation_task)

    def _chat_failure(self, request_id, reason, message, intent="unknown", params=None):
        self._clear_conversation(reason, request_id)
        self._audit(request_id, intent, "none", "rejected", "rejected", reason, params)
        return self._response("rejected", request_id, intent, reason=reason, message=message)

    def _draft_schema(self, candidate):
        """先检查候选形状；缺参不会放宽额外字段、类型和金额限制。"""
        from .bank import RuleError
        if type(candidate) is not dict:
            raise RuleError("invalid_candidate", "模型候选必须是允许的对象。")
        if set(candidate) == {"clarification"}:
            clarification = candidate["clarification"]
            if type(clarification) is str and len(clarification) <= 200:
                return None
            if type(clarification) is not dict or set(clarification) != {"draft"}:
                raise RuleError("invalid_candidate", "澄清候选格式不合法。")
            draft = clarification["draft"]
            if draft is None:
                return None
            self._partial_schema(draft)
            return draft
        if set(candidate) == {"steps"}:
            # 原计划入口整体检查结构、类型、依赖和环；这里不执行任何前缀。
            steps = candidate["steps"]
            if type(steps) is not list or not 1 <= len(steps) <= 8:
                raise RuleError("invalid_plan", "计划必须包含1至8步。")
            for step in steps:
                if type(step) is not dict or set(step) != {"id", "intent", "params", "depends_on"}:
                    raise RuleError("invalid_plan", "计划字段不合法。")
                self._partial_schema({"intent": step["intent"], "params": step["params"]})
            return None
        self._partial_schema(candidate)
        return candidate

    def _partial_schema(self, draft):
        from .bank import RuleError
        if type(draft) is not dict or set(draft) != {"intent", "params"}:
            raise RuleError("invalid_candidate", "模型候选含未允许字段。")
        intent, params = draft["intent"], draft["params"]
        allowed = {**PARAMETERS, **NEW_PARAMETERS}
        if type(intent) is not str or intent not in allowed:
            raise RuleError("unsupported_intent", "该操作不在固定工具白名单中。")
        if type(params) is not dict or set(params) - allowed[intent]:
            raise RuleError("invalid_parameters", "模型参数含未允许字段。")
        for key, value in params.items():
            if not check_draft_parameter(key, value):
                reason = "invalid_amount" if key in {"amount_cents", "daily_limit_cents"} else "invalid_parameters"
                raise RuleError(reason, "参数类型、范围或日期不符合固定规则；金额须为正整数分。")
        if params.get("start_date", "") > params.get("end_date", "9999-12-31"):
            raise RuleError("invalid_parameters", "开始日期不能晚于结束日期。")

    def _human_intents(self, text):
        intents = new_human_intents(text)
        checks = (("transfer", r"转账|转钱|汇款|打款|转\s*(?:负|-?\d|[A-Za-z]+(?=\s*(?:元|块))|[一二两三四五六七八九十百千万])|给.+?转|^\s*给\s*[^，。！？,!?；;]+[。！!]?\s*$|^\s*联系人(?:编号|ID|id)\s*[:：]?\s*[A-Za-z0-9_-]+[。！!]?\s*$"),
                  ("analyze_bills", r"账单|花费|支出|花了多少"),
                  ("query_balance", r"余额|有多少钱"),
                  ("query_transactions", r"流水|交易记录"),
                  ("cancel_subscription", r"(?:取消|退订|停止续费).*(?:会员|订阅|云存储|sub-)"),
                  ("query_subscriptions", r"(?:查|看|列|有哪些).*(?:订阅|代扣|自动扣款|会员)|未来预计"))
        for intent, pattern in checks:
            if re.search(pattern, text):
                if intent == "query_balance" and re.search(r"预算|卡限额", text) and not re.search(r"账户余额|主账户余额|可用余额|(?:查|看|核对|和|及|、|，|,|然后|再)余额|余额[、，,和及]", text):
                    continue
                intents.append(intent)
        return intents

    def _human_transfer(self, text):
        """返回本人本轮明确参数及缺项原因；没有模型或外部数据来源。"""
        from .bank import RuleError
        params, problems = {}, {}
        if re.search(r"备注|网页|外部|模型说|指令|引文|账单里|联系人名", text):
            return params, {"contact": "source_unproven", "amount_cents": "source_unproven"}
        amount_matches = list(MONEY_WITH_UNIT.finditer(text))
        amounts = []
        try:
            for match in amount_matches:
                amount = exact_cents(match.group(1))
                if amount is not None:
                    amounts.append(amount)
            # 单位省略的近似／范围仍不是确定金额。
            uncertain = bool(re.search(r"左右|大约|大概|差不多|上下|约莫|约(?=\s*[0-9一二两三四五六七八九十百千万])|那个数|\d\s*(?:到|至|~|～|—|–|-)\s*\d|[一二两三四五六七八九十百千万]+(?:到|至)[一二两三四五六七八九十百千万]+|(?:元|块)\s*[,，、/和及]?\s*\d|[0-9零〇一二两三四五六七八九十百千万]+\s*[角分]|(?:再|另|各|分别)\s*(?:转|汇|打)\s*\d", text))
            if not uncertain and len(amount_matches) == 1 and len(amounts) == 1:
                params["amount_cents"] = amounts[0]
            elif amount_matches or uncertain:
                problems["amount_cents"] = "amount_not_unique"
        except ValueError:
            raise RuleError("invalid_amount", "金额须为明确、正数且最多两位小数；不能取整或猜测。") from None
        id_match = re.search(r"联系人(?:编号|ID|id)\s*[:：]?\s*([A-Za-z0-9_-]+)", text)
        names = re.findall(r"给\s*(?:[（(]?已登记的?[）)]?\s*)?(?:联系人)?\s*([^，。！？,!?；;]+?)(?=转|[，。！？,!?；;]|$)", text)
        names = [name.strip() for name in names if name.strip()]
        if id_match:
            field, value = "contact_id", id_match.group(1)
        elif len(names) == 1:
            field, value = "name", names[0]
        elif not names and re.fullmatch(r"\s*改(?:成|为)\s*[^，。！？,!?；;]+[。！!]?\s*", text) and not amount_matches:
            field, value = "name", re.sub(r"^\s*改(?:成|为)\s*", "", text).strip().rstrip("。！!")
        else:
            field, value = None, None
            if names:
                problems["contact"] = "ambiguous"
        if field:
            rows = self.connection.execute(f"SELECT contact_id FROM contacts WHERE user_id=? AND {field}=?", (self.user_id, value)).fetchall()
            if len(rows) == 1:
                params["contact_id"] = rows[0][0]
            else:
                problems["contact"] = "not_found" if not rows else "ambiguous"
        accounts = re.findall(r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]*-(?:main|savings))(?![A-Za-z0-9_-])", text)
        if len(accounts) == 1:
            self._account(accounts[0])
            params["account_id"] = accounts[0]
        elif len(accounts) > 1 or re.search(r"两个本人账户|两个账户|各转", text):
            problems["account_id"] = "account_not_unique"
        elif "我的主账户" in text or "本人主账户" in text:
            params["account_id"] = self.user_id + "-main"
        return params, problems

    def _human_subscription(self, text, *, selection=False):
        match = re.search(r"(?:取消|退订|停止续费)\s*(?:我的|本人)?\s*([^，。！？,!?；;]+)", text)
        if not match:
            if not selection:
                return {}, {"subscription": "missing_target"}
            name = re.sub(r"^\s*改(?:成|为)\s*", "", text).strip().rstrip("。！!？?")
        else:
            name = match.group(1).strip().rstrip("。！!？?")
        field = "subscription_id" if re.fullmatch(r"[A-Za-z0-9_-]+", name) else "name"
        rows = self.connection.execute(f"SELECT subscription_id FROM subscriptions WHERE user_id=? AND {field}=?", (self.user_id, name)).fetchall()
        if len(rows) == 1:
            return {"subscription_id": rows[0][0]}, {}
        return {}, {"subscription": "not_found" if not rows else "ambiguous"}

    def _is_supplement(self, text, previous, facts, problems):
        if previous is None:
            return False
        current_intents = self._human_intents(text)
        if current_intents and set(current_intents) != {previous["intent"]}:
            return False
        if previous["intent"] in NEW_PARAMETERS:
            return bool(facts or problems) and (bool(previous["missing_fields"]) or bool(re.match(r"\s*改(?:成|为)", text)))
        if previous["intent"] == "cancel_subscription":
            if re.match(r"\s*改(?:成|为)", text):
                return True
            if "subscription" in previous["missing_fields"]:
                value = text.strip().rstrip("。！!？?")
                rows = self.connection.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND (subscription_id=? OR name=?)", (self.user_id, value, value)).fetchall()
                return bool(rows)
            return False
        if previous["intent"] != "transfer":
            return False
        if re.match(r"\s*改(?:成|为)", text):
            return bool(facts or problems)
        missing = previous["missing_fields"]
        if missing and "contact_id" in facts and re.fullmatch(r"\s*(?:给.+|联系人(?:编号|ID|id).+)[。！!]?\s*", text):
            return True
        if "amount_cents" in missing and "amount_cents" in facts:
            remainder = MONEY_WITH_UNIT.sub("", text)
            remainder = re.sub(r"[，,。\s]|从我的主账户|从本人主账户", "", remainder)
            return not remainder
        return False

    def _safe_task(self, intent, params, problems=None):
        if intent not in PARAMETERS and intent not in NEW_PARAMETERS:
            return None
        # 编号由本人选择映射得到，但数据库文本也不能把秘密带入模型上下文。
        safe = self._audit_parameters(intent, params)
        params = {key: copy.deepcopy(value) for key, value in params.items() if safe.get(key) == value}
        missing = []
        if intent == "transfer":
            if not set(params) & {"contact_id", "contact_name"}:
                missing.append("contact")
            if "amount_cents" not in params:
                missing.append("amount_cents")
        elif intent == "cancel_subscription" and not set(params) & {"subscription_id", "subscription_name"}:
            missing.append("subscription")
        elif intent in NEW_PARAMETERS:
            missing.extend(key for key in REQUIRED_PARAMETERS.get(intent, ()) if key not in params)
        missing.extend((problems or {}).keys())
        return dict(intent=intent, params=params, missing_fields=[field for field in MISSING_ORDER if field in missing])

    def _clarify(self, request_id, task, problems=None):
        missing = ["intent"] if task is None else task["missing_fields"]
        prompts = []
        if "intent" in missing:
            prompts.append("请明确本次要办理的操作")
        if "contact" in missing:
            cause = (problems or {}).get("contact")
            prompts.append("联系人有歧义，请提供本人登记的精确编号" if cause == "ambiguous" else "未找到唯一联系人，请明确收款联系人的精确名称或编号" if cause == "not_found" else "请明确收款联系人")
        if "amount_cents" in missing:
            prompts.append("请明确本次金额（单一、准确的元金额）")
        if "subscription" in missing:
            prompts.append("请明确本人模拟订阅的精确名称或编号")
        if "account_id" in missing:
            prompts.append("请明确一个本人来源账户编号，或明确说主账户")
        new_prompts = {
            "product_id": "请明确一个固定模拟产品的精确名称或编号",
            "product_ids": "请明确要对比的2至4个不同固定模拟产品名称或编号",
            "risk_level": "请明确风险等级（低、中或高）",
            "horizon_days": "请明确持有期限（1至3650天）",
            "liquidity": "请明确流动性要求（即时可用、灵活或接受锁定）",
            "card_id": "请明确本人模拟卡的精确编号",
            "daily_limit_cents": "请明确模拟卡每日限额（准确元金额，最多1000元）",
            "budget_id": "请明确预算ID（英文字母开头，可含数字、下划线或连字符）",
            "service_id": "请明确固定服务的精确名称或编号（模拟鲜花或模拟蛋糕）",
            "event_date": "请明确有效的活动日期（YYYY-MM-DD），不会猜测明天或生日日期",
            "order_id": "请明确本人订单的精确编号",
        }
        prompts.extend(new_prompts[field] for field in NEW_MISSING_FIELDS if field in missing)
        message = "；".join(prompts) + "。" if prompts else "识别参数与本人本轮请求不一致，请重新明确本次操作的目标和参数。"
        self._conversation_task = copy.deepcopy(task)
        self._conversation_request_id = None
        self._audit(request_id, task["intent"] if task else "unknown", "none", "clarification", "rejected", "clarification", task["params"] if task else {})
        self._remember_message("assistant", message)
        return self._response("rejected", request_id, task["intent"] if task else "unknown", reason="clarification", message=message,
                              clarification=dict(draft=None if task is None else {"intent": task["intent"], "params": copy.deepcopy(task["params"])}, missing_fields=list(missing)))

    def _remember_message(self, role, content):
        if len(content) <= 512:
            self._conversation_messages.append(dict(role=role, content=content))
            self._conversation_messages = self._conversation_messages[-4:]

    def _candidate_matches_transfer(self, params, task):
        """联系人名字可映射同一个登记ID，但映射不能代替本人给出目标。"""
        source = task["params"]
        if params.get("amount_cents") != source.get("amount_cents"):
            return False
        account = source.get("account_id", self.user_id + "-main")
        if params.get("account_id", self.user_id + "-main") != account:
            return False
        if set(params) & {"contact_id", "contact_name"} == {"contact_id"}:
            return params["contact_id"] == source.get("contact_id")
        if set(params) & {"contact_id", "contact_name"} == {"contact_name"}:
            rows = self.connection.execute("SELECT contact_id FROM contacts WHERE user_id=? AND name=?", (self.user_id, params["contact_name"])).fetchall()
            return len(rows) == 1 and rows[0][0] == source.get("contact_id")
        return False

    def _new_human_task(self, intent, text, previous=None):
        """合并同一未终结任务的本人明确补充；失败字段先移除旧值。"""
        facts, problems = extract_new_facts(intent, text, self.user_id, exact_cents, MONEY_WITH_UNIT)
        params = copy.deepcopy(previous["params"]) if previous is not None else {}
        for field in problems:
            params.pop(field, None)
        params.update(facts)
        return self._safe_task(intent, params, problems), problems

    def _candidate_matches_new(self, params, task):
        # 可选目标也不能凭模型补齐；选卡、选预算、日期、金额均须由本人明确给出。
        return task is not None and not task["missing_fields"] and params == task["params"]

    def _context_model_error(self, error, request_id):
        if getattr(error, "code", None) == "isolation_failed":
            with self._transaction():
                self._clear_conversation("model_failed", request_id)
                return self._isolation_failure(request_id, "unknown", "none", {}, getattr(error, "isolation_reason", "isolation_unavailable"))
        safe_codes = {"model_not_configured", "model_http_error", "model_timeout", "model_network_error", "invalid_model_json", "invalid_model_response", "model_incomplete_output", "model_redirect_blocked", "sensitive_model_input", "invalid_model_configuration", "invalid_model_context"}
        supplied = getattr(error, "code", None)
        code = supplied if type(supplied) is str and supplied in safe_codes else "model_failed"
        status = getattr(error, "http_status", None)
        status = status if type(status) is int and 400 <= status <= 599 else None
        with self._transaction():
            self._clear_conversation("model_failed", request_id)
            self._audit(request_id, "unknown", "none", "model_failed", "failed", code)
        return self._response("failed", request_id, reason="model_unavailable", message="模型未配置或调用失败，未执行任何业务；请检查本机模型配置。", model_error_code=code, http_status=status)

    def _handle_conversation(self, text, model):
        from .bank import INJECTION, NEGATIONS, SECRET_PATTERN, RuleError
        request_id = uuid.uuid4().hex
        # 格式错误不消费健康确认；不能先截断、取消或交模型。
        if not valid_chat_text(text):
            with self._transaction():
                self._audit(request_id, "unknown", "none", "rejected", "rejected", "invalid_input")
            return self._response("rejected", request_id, reason="invalid_input", message="输入须为1至2000字符的非空文本，且不能含控制字符。")
        with self._transaction():
            previous = self._conversation_previous()
            codes = list(self.confirmation_secrets.values()) + [review.get("code") for review in self.recovery_reviews.values() if not review.get("invalidated")]
            has_secret = (SECRET_PATTERN.search(text) or re.search(r"口令|passwd|secret|token|确认码|恢复码|认证码", text, re.I) or self._contains_enrolled_secret(text)
                          or any(type(code) is str and code and code in text for code in codes))
            sanitized = redact_unlabeled_six_digits(text)
            human_text = unquoted_text(sanitized)
            negative = (text.strip() == "取消" or any(word in text for word in NEGATIONS if word != "取消")
                        or any(word in text for word in ("取消当前", "取消操作", "取消请求", "我还没想好", "还是先等等", "先等等", "先别", "不要转", "不要取消", "不想转")))
            if negative and not has_secret:
                self._clear_conversation("user_cancelled", request_id)
                # _cancel自行管理事务，在下面退出本事务后调用。
                cancel_requested = True
                facts, problems, supplemental, human_intents = {}, {}, False, []
            else:
                cancel_requested = False
                self._invalidate_pending()
                self._invalidate_plans()
                self._audit(request_id, "unknown", "none", "received", "pending")
                if has_secret:
                    return self._chat_failure(request_id, "secret_input", "输入含认证秘密或当前有效码，未发送模型；旧确认已失效。")
                if any(word in text.lower() for word in INJECTION):
                    return self._chat_failure(request_id, "injection_blocked", "输入含明显越过规则指令，未发送模型，未执行。")
                if requests_unsupported_automation(human_text):
                    return self._chat_failure(request_id, "unsupported_automation", "当前不支持后台定时、届时付款或自动联系商户；未发送模型，也未改成立即办理。请明确本次立即办理的操作。")
                if text.strip().rstrip("。！!，,") in {"按刚才那个办", "就那个"}:
                    self._clear_conversation("ambiguous_reference", request_id)
                    return self._clarify(request_id, None)
                if text.strip().rstrip("。！!，,") in {"嗯", "随便", "你看着办", "确认", "执行", "继续", "继续刚才的", "确认上一笔"}:
                    return self._chat_failure(request_id, "explicit_confirmation_required", "请明确选择本次操作并使用固定确认入口；历史任务须重新审核。")
                claimed_user = re.search(r"我是\s*([A-Za-z][A-Za-z0-9_-]*)", human_text)
                if (claimed_user and claimed_user.group(1) != self.user_id
                        and self.connection.execute("SELECT 1 FROM users WHERE user_id=?", (claimed_user.group(1),)).fetchone()
                        or re.search(r"(?:查|看).*(?:他的|她的|别人的).*(?:账户|余额|流水|账单)", human_text)):
                    return self._chat_failure(request_id, "ownership", "聊天不能更改可信身份；只能查询本人记录或从本人账户转出。")
                human_intents = self._human_intents(human_text)
                extraction_intent = (human_intents[0] if len(human_intents) == 1 else
                                     previous["intent"] if not human_intents and previous is not None else None)
                try:
                    if extraction_intent in NEW_PARAMETERS:
                        facts, problems = extract_new_facts(extraction_intent, human_text, self.user_id, exact_cents, MONEY_WITH_UNIT)
                    elif extraction_intent == "transfer" or "transfer" in human_intents:
                        facts, problems = self._human_transfer(human_text)
                    else:
                        facts, problems = {}, {}
                except RuleError as error:
                    return self._chat_failure(request_id, error.reason, error.message)
                except ValueError:
                    return self._chat_failure(request_id, "invalid_amount", "金额须为明确、正数且最多两位小数；不能取整或猜测。")
                supplemental = self._is_supplement(human_text, previous, facts, problems)
                if supplemental:
                    self._conversation_task = previous
                else:
                    self._clear_conversation("new_task", request_id)
        if cancel_requested:
            return self._cancel(None)
        context = dict(user_id=self.user_id, today=self._now().date().isoformat(),
                       current_task=copy.deepcopy(self._conversation_task), recent_messages=copy.deepcopy(self._conversation_messages))
        try:
            candidate = model.propose(sanitized, context)
        except Exception as error:
            return self._context_model_error(error, request_id)
        try:
            draft = self._draft_schema(candidate)
            task = None
            intent = previous["intent"] if supplemental else human_intents[0] if len(human_intents) == 1 else None
            if intent == "transfer":
                params = copy.deepcopy(previous["params"]) if supplemental else {}
                if "contact" in problems:
                    params.pop("contact_id", None)
                    params.pop("contact_name", None)
                if "amount_cents" in problems:
                    params.pop("amount_cents", None)
                params.update(facts)
                task = self._safe_task(intent, params, problems)
            elif intent == "cancel_subscription":
                params, problems = self._human_subscription(human_text, selection=supplemental)
                task = self._safe_task(intent, params, problems)
            elif intent in NEW_PARAMETERS:
                task, problems = self._new_human_task(intent, human_text, previous if supplemental else None)
            elif intent:
                task = self._safe_task(intent, {})
            with self._transaction():
                self._remember_message("user", sanitized)
                if set(candidate) == {"clarification"} or task is not None and task["missing_fields"]:
                    return self._clarify(request_id, task, problems)
                if set(candidate) == {"steps"}:
                    # 一次转账的来源不能分给多个节点；逐项明确的多个转账另行办理。
                    transfer_steps = [step for step in candidate["steps"] if step["intent"] == "transfer"]
                    transfer_task = self._safe_task("transfer", facts, problems) if "transfer" in human_intents else None
                    new_step_counts = {name: sum(step["intent"] == name for step in candidate["steps"]) for name in NEW_PARAMETERS}
                    for step in candidate["steps"]:
                        if step["intent"] not in human_intents:
                            return self._clarify(request_id, None)
                        if step["intent"] == "transfer" and (len(transfer_steps) != 1 or transfer_task is None or transfer_task["missing_fields"] or not self._candidate_matches_transfer(step["params"], transfer_task)):
                            return self._clarify(request_id, transfer_task)
                        if step["intent"] == "cancel_subscription":
                            sub_params, sub_problems = self._human_subscription(human_text)
                            if sub_problems or not self._candidate_matches_subscription(step["params"], sub_params):
                                return self._clarify(request_id, self._safe_task("cancel_subscription", sub_params, sub_problems), sub_problems)
                        if step["intent"] in NEW_PARAMETERS:
                            new_task, new_problems = self._new_human_task(step["intent"], human_text)
                            if new_step_counts[step["intent"]] != 1 or not self._candidate_matches_new(step["params"], new_task):
                                return self._clarify(request_id, new_task, new_problems)
                elif task is None or draft["intent"] != task["intent"]:
                    return self._clarify(request_id, task)
                elif task["intent"] == "transfer" and not self._candidate_matches_transfer(draft["params"], task):
                    return self._clarify(request_id, task)
                elif task["intent"] == "cancel_subscription" and not self._candidate_matches_subscription(draft["params"], task["params"]):
                    return self._clarify(request_id, task)
                elif task["intent"] in NEW_PARAMETERS and not self._candidate_matches_new(draft["params"], task):
                    return self._clarify(request_id, task)
            self._conversation_submitting = True
            try:
                response = self._propose(candidate, request_id)
                if response.get("plan_id"):
                    response = self._resume_plan(response["plan_id"])
            finally:
                self._conversation_submitting = False
            if response["status"] == "pending" and response.get("operation"):
                # 待确认上下文是参数回顾，绝不是授权；码只在原固定入口。
                operation = response["operation"]
                self._conversation_task = self._safe_task(response["intent"], operation.get("params", {}))
                self._conversation_request_id = response["request_id"]
            else:
                with self._transaction():
                    self._clear_conversation("task_" + response["status"], request_id)
            return response
        except RuleError as error:
            with self._transaction():
                return self._chat_failure(request_id, error.reason, error.message)
        except ValueError:
            with self._transaction():
                return self._chat_failure(request_id, "invalid_amount", "金额须为明确、正数且最多两位小数；不能取整或猜测。")

    def _candidate_matches_subscription(self, params, source):
        if set(params) == {"subscription_id"}:
            return params["subscription_id"] == source.get("subscription_id")
        if set(params) == {"subscription_name"}:
            rows = self.connection.execute("SELECT subscription_id FROM subscriptions WHERE user_id=? AND name=?", (self.user_id, params["subscription_name"])).fetchall()
            return len(rows) == 1 and rows[0][0] == source.get("subscription_id")
        return False

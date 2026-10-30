"""六场景新增工具的严格草稿字段与人类文字来源；不执行业务或生成授权。"""

import re
from datetime import date


NEW_PARAMETERS = {
    "query_investments": set(),
    "compare_investments": {"product_ids"},
    "match_investments": {"risk_level", "horizon_days", "liquidity"},
    "query_cards": {"card_id"},
    "apply_virtual_card": {"account_id"},
    "set_card_limit": {"card_id", "daily_limit_cents"},
    "query_services": set(),
    "query_budgets": {"budget_id"},
    "query_orders": {"budget_id", "order_id"},
    "reserve_budget": {"budget_id", "account_id", "event_date", "amount_cents"},
    "release_budget": {"budget_id"},
    "place_order": {"budget_id", "service_id", "event_date", "card_id"},
    "purchase_investment": {"product_id", "account_id", "amount_cents"},
    "redeem_investment": {"product_id", "account_id", "amount_cents"},
    "report_card_lost": {"card_id"},
    "restore_card": {"card_id"},
}
REQUIRED_PARAMETERS = {
    "compare_investments": ("product_ids",),
    "match_investments": ("risk_level", "horizon_days", "liquidity"),
    "apply_virtual_card": ("account_id",),
    "set_card_limit": ("card_id", "daily_limit_cents"),
    "reserve_budget": ("budget_id", "account_id", "event_date", "amount_cents"),
    "release_budget": ("budget_id",),
    "place_order": ("budget_id", "service_id", "event_date"),
    "purchase_investment": ("product_id", "account_id", "amount_cents"),
    "redeem_investment": ("product_id", "account_id", "amount_cents"),
    "report_card_lost": ("card_id",),
    "restore_card": ("card_id",),
}
NEW_MISSING_FIELDS = (
    "product_id", "product_ids", "risk_level", "horizon_days", "liquidity", "card_id",
    "daily_limit_cents", "budget_id", "service_id", "event_date", "order_id",
)
PRODUCT_NAMES = {"p-cash": "模拟活期A", "p-flex": "模拟灵活B", "p-steady": "模拟稳健C", "p-growth": "模拟成长D"}
SERVICE_NAMES = {"flower-basic": "模拟鲜花", "cake-basic": "模拟蛋糕"}
DATE_FIELDS = {"start_date", "end_date", "event_date"}
INTEGER_FIELDS = {"amount_cents": 10 ** 12, "daily_limit_cents": 100000, "horizon_days": 3650}
LABELED_BUSINESS_ID = re.compile(
    r"(?:(?:budget_id|预算(?:编号|ID))\s*[:：=]?\s*(?P<budget>[A-Za-z][A-Za-z0-9_-]{0,31})(?![A-Za-z0-9_-])"
    r"|(?:order_id|订单(?:编号|ID))\s*[:：=]?\s*(?P<order>[0-9a-f]{32})(?![A-Za-z0-9_-]))",
    re.IGNORECASE,
)


def business_id_check_text(text):
    """仅在敏感检测时遮住明确带标签的合法公开ID内数字；秘密词仍保留。"""
    def mask(match):
        group = "budget" if match.group("budget") is not None else "order"
        start, end = match.span(group)
        local_start, local_end = start - match.start(), end - match.start()
        return match.group(0)[:local_start] + re.sub(r"[0-9]", "x", match.group(group)) + match.group(0)[local_end:]
    return LABELED_BUSINESS_ID.sub(mask, text)


def redact_unlabeled_six_digits(text):
    """脱敏孤立六位数字，保留明确预算/订单ID；不放宽任何当前有效码检查。"""
    safe_spans = [match.span("budget" if match.group("budget") is not None else "order") for match in LABELED_BUSINESS_ID.finditer(text)]
    return re.sub(r"(?<!\d)[0-9]{6}(?!\d)", lambda match: match.group(0) if any(start <= match.start() and match.end() <= end for start, end in safe_spans) else "[REDACTED]", text)


def public_id_parameter_check_text(name, value):
    if (name == "budget_id" and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value)
            or name == "order_id" and re.fullmatch(r"[0-9a-f]{32}", value)):
        return re.sub(r"[0-9]", "x", value)
    return value


def requests_unsupported_automation(text):
    """只拦截明确后台办理语义；活动日期和自动扣款查询不表示定时授权。"""
    patterns = (
        r"(?:定时|预约|自动|后台)\s*(?:自动|执行|进行)?\s*(?:下单|付款|支付|订购|购买)",
        r"(?:届时|到时|到时候)\s*(?:再|自动)?\s*(?:下单|付款|支付|订购|购买)",
        r"自动\s*(?:联系|联络|通知|呼叫)\s*(?:商户|商家|店家|客服)",
        r"(?:于|在|到)\s*\d{4}-\d{2}-\d{2}\s*(?:时|当天)?\s*(?:再|自动)\s*(?:下单|付款|支付|订购|购买)",
    )
    for clause in re.split(r"[，。！？,!?；;\n]", text):
        for pattern in patterns:
            for match in re.finditer(pattern, clause):
                # “不需要定时下单”不是请求后台能力；取消仍由会话固定入口处理。
                if not re.search(r"(?:不要|无需|不需要|不必|不准|禁止|别|不支持|没有)\s*$", clause[:match.start()]):
                    return True
    return False


def check_draft_parameter(name, value):
    """返回字段值是否符合公开类型；bool不能冒充整数，列表仅用于产品对比。"""
    if name in INTEGER_FIELDS:
        return type(value) is int and 0 < value <= INTEGER_FIELDS[name]
    if name == "product_ids":
        return (type(value) is list and 2 <= len(value) <= 4
                and all(type(item) is str and item in PRODUCT_NAMES for item in value)
                and len(set(value)) == len(value))
    if type(value) is not str or not value or len(value) > 80 or any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    if name in DATE_FIELDS:
        try:
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))
        except ValueError:
            return False
    if name == "risk_level":
        return value in {"low", "medium", "high"}
    if name == "liquidity":
        return value in {"immediate", "flexible", "locked"}
    if name == "budget_id":
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value))
    return True


def new_human_intents(text):
    """仅识别本人文字的固定动作；不以候选模型输出决定用户意图。"""
    intents = []
    checks = (
        ("query_investments", r"(?:查|看|列).{0,10}(?:理财|投资)(?:产品|目录|列表)?|有哪些(?:理财|投资)产品"),
        ("compare_investments", r"对比|比较"),
        ("match_investments", r"(?:匹配|筛选|适合).{0,12}(?:理财|投资|产品)|(?:理财|投资|产品).{0,12}(?:匹配|筛选)"),
        ("query_cards", r"(?:查|看|列).{0,8}(?:卡片|银行卡|模拟卡|我的卡|本人卡)|有哪些卡"),
        ("apply_virtual_card", r"(?:申请|开通|新建).{0,6}(?:虚拟卡|模拟卡)"),
        ("set_card_limit", r"(?:修改|设置|调整|改成|改为).{0,18}(?:卡.{0,8})?(?:日(?:交易)?限额|每日(?:交易)?限额|卡限额)|(?:卡限额|日(?:交易)?限额|每日(?:交易)?限额).{0,8}(?:改|设|调)"),
        ("query_services", r"(?:查|看|列).{0,8}(?:服务|鲜花|蛋糕)(?:目录|列表)?|有哪些.{0,4}服务"),
        ("query_budgets", r"(?:查|看|核对).{0,80}预算|预算(?:状态|记录|列表)"),
        ("query_orders", r"(?:查|看|核对).{0,80}订单|订单(?:状态|记录|列表)"),
        ("reserve_budget", r"(?:保留|预留|建立|创建|新建).{0,8}预算|预算.{0,5}(?:保留|预留)"),
        ("release_budget", r"(?:释放|解除保留).{0,8}预算|预算.{0,8}(?:释放|解除保留)"),
        ("place_order", r"下单|订购|买服务|购买服务|(?:购买|买).{0,6}(?:鲜花|蛋糕|flower-basic|cake-basic)"),
        ("purchase_investment", r"(?:购买|申购).{0,12}(?:理财|投资|p-cash|p-flex|p-steady|p-growth|模拟活期A|模拟灵活B|模拟稳健C|模拟成长D)"),
        ("redeem_investment", r"赎回"),
        ("report_card_lost", r"挂失"),
        ("restore_card", r"(?:恢复|解挂).{0,8}(?:卡|card)|(?:卡|card).{0,8}(?:恢复|解挂)"),
    )
    clauses = re.split(r"[，。！？,!?；;\n]", text)
    for intent, pattern in checks:
        literal = bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(intent) + r"(?![A-Za-z0-9_])", text))
        matched = any(re.search(pattern, clause, re.I) for clause in clauses)
        if intent == "compare_investments":
            matched = matched and any(identifier in text or name in text for identifier, name in PRODUCT_NAMES.items()) or matched and bool(re.search(r"理财|投资|产品", text))
        if literal or matched:
            intents.append(intent)
    return intents


def _catalog_choices(text, catalog):
    found = []
    for identifier, name in catalog.items():
        for match in re.finditer(r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])|" + re.escape(name), text):
            found.append((match.start(), identifier))
    return list(dict.fromkeys(identifier for _, identifier in sorted(found)))


def extract_new_facts(intent, text, user_id, exact_cents, money_pattern):
    """仅从未引述的人类文字提取固定目录与显式字段，不读结果、不补默认目标。"""
    params, problems = {}, {}
    allowed = NEW_PARAMETERS[intent]
    if re.search(r"备注|网页|外部|模型说|指令|引文|账单里|联系人名", text):
        return {}, {key: "source_unproven" for key in REQUIRED_PARAMETERS.get(intent, ("intent",))}

    def unique(key, values):
        values = list(dict.fromkeys(values))
        if len(values) == 1:
            params[key] = values[0]
        elif values:
            problems[key] = "ambiguous"

    if "account_id" in allowed:
        accounts = re.findall(r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]*-(?:main|savings))(?![A-Za-z0-9_-])", text)
        if re.search(r"主账户", text):
            accounts.append(user_id + "-main")
        unique("account_id", accounts)
    if "product_id" in allowed or "product_ids" in allowed:
        products = _catalog_choices(text, PRODUCT_NAMES)
        if "product_ids" in allowed:
            if 2 <= len(products) <= 4:
                params["product_ids"] = products
            elif products:
                problems["product_ids"] = "ambiguous"
        else:
            unique("product_id", products)
    if "service_id" in allowed:
        unique("service_id", _catalog_choices(text, SERVICE_NAMES))
    if "card_id" in allowed:
        cards = re.findall(r"(?<![A-Za-z0-9_-])((?:sim-card-|card-)[A-Za-z0-9_-]+)(?![A-Za-z0-9_-])", text)
        cards.extend(re.findall(r"(?:card_id|卡(?:片)?(?:编号|ID|id))\s*[:：=]?\s*([A-Za-z][A-Za-z0-9_-]{0,79})", text))
        unique("card_id", cards)
    for key, label in (("budget_id", r"budget_id|预算(?:编号|ID|id)?"), ("order_id", r"order_id|订单(?:编号|ID|id)")):
        if key in allowed:
            pattern = r"[A-Za-z][A-Za-z0-9_-]{0,31}" if key == "budget_id" else r"[0-9a-f]{32}"
            unique(key, re.findall(r"(?:" + label + r")\s*[:：=]?\s*(" + pattern + r")(?![A-Za-z0-9_-])", text))
            strict_label = r"budget_id|预算(?:编号|ID|id)" if key == "budget_id" else label
            if key not in params and re.search(r"(?:" + strict_label + r")", text):
                problems[key] = "missing_or_invalid_target"
    if "event_date" in allowed:
        dates = re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text)
        unique("event_date", dates)
        if "event_date" in params and not check_draft_parameter("event_date", params["event_date"]):
            params.pop("event_date")
            problems["event_date"] = "invalid_date"
    money_key = "daily_limit_cents" if "daily_limit_cents" in allowed else "amount_cents" if "amount_cents" in allowed else None
    if money_key:
        matches = list(money_pattern.finditer(text))
        amounts = [exact_cents(match.group(1)) for match in matches]
        if (len(matches) == 1 and len(amounts) == 1 and amounts[0] is not None
                and not re.search(r"左右|大约|大概|差不多|上下|约莫|约\s*\d|\d\s*(?:到|至|~|～)\s*\d|[角分]", text)):
            params[money_key] = amounts[0]
        elif matches:
            problems[money_key] = "amount_not_unique"
    if "risk_level" in allowed:
        risk_words = {"low": r"低风险|风险(?:等级|偏好|承受)?\s*[:：=]?\s*(?:低|low)|risk_level\s*[:：=]?\s*low", "medium": r"中风险|风险(?:等级|偏好|承受)?\s*[:：=]?\s*(?:中|medium)|risk_level\s*[:：=]?\s*medium", "high": r"(?<!最)高风险|风险(?:等级|偏好|承受)?\s*[:：=]?\s*(?:高|high)|risk_level\s*[:：=]?\s*high"}
        unique("risk_level", [key for key, pattern in risk_words.items() if re.search(pattern, text, re.I)])
    if "horizon_days" in allowed:
        days = re.findall(r"(?:期限|持有|投资期|horizon_days)\s*[:：=]?\s*(\d+)\s*(?:天|日)?", text, re.I)
        if not days:
            days = re.findall(r"(?<!\d)(\d+)\s*天", text)
        unique("horizon_days", [int(value) for value in days])
    if "liquidity" in allowed:
        liquid_words = {"immediate": r"即时可用|立即可用|随时可取|即时流动性|(?:流动性|liquidity)(?:要求|需求|偏好)?\s*[:：=]?\s*(?:即时|立即|immediate)", "flexible": r"灵活(?:流动性|取用)|(?:流动性|liquidity)(?:要求|需求|偏好)?\s*[:：=]?\s*(?:灵活|flexible)", "locked": r"接受锁定|可以锁定|锁定流动性|(?:流动性|liquidity)(?:要求|需求|偏好)?\s*[:：=]?\s*(?:锁定|locked)"}
        unique("liquidity", [key for key, pattern in liquid_words.items() if re.search(pattern, text, re.I)])
    return params, problems

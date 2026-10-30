"""事实校验（幻觉防护，PLAN 3.8）：回复里的金额、百分比、日期、笔数必须能在本轮工具结果、
待确认单或用户原话里找到；没有成功回执时不许出现完成语。对不上就用代码模板重写。"""

import json
import re

NUMBER = re.compile(r"(?<![0-9A-Za-z])[0-9][0-9,]*(?:\.[0-9]+)?")
COMPLETION = re.compile(r"已(经)?(成功)?(转账|转出|转给|完成|购买|申购|赎回|取消|冻结|解冻|挂失|解挂|办理|开通|提交|支付|下单|撤回|执行)|转账成功|办理成功|购买成功|支付成功")


def _numbers(text):
    values = set()
    for token in NUMBER.findall(text or ""):
        raw = token.replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        values.add(round(value, 2))
    return values


def _date_parts(text):
    """把 2026-10-31、10月31日 等都拆成月、日数字，便于比较。"""
    parts = set()
    for y, m, d in re.findall(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})", text or ""):
        parts.update({float(int(y)), float(int(m)), float(int(d))})
    for m, d in re.findall(r"([0-9]{1,2})-([0-9]{1,2})", text or ""):
        parts.update({float(int(m)), float(int(d))})
    for h, mi in re.findall(r"([0-9]{1,2}):([0-9]{2})", text or ""):
        parts.update({float(int(h)), float(int(mi))})
    return parts


PENDING_CLAIM = re.compile(r"(确认单|待确认).{0,6}(已生成|生成了|已经生成|已创建)|已(为你|帮你)?生成.{0,12}(确认单|待确认)|请(你)?(在|到)?(界面|确认单)上?(点|点击)确认")


def check(reply, evidence_texts, *, completed=False, cancelled=False, pending_created=True):
    """返回 (ok, problems)。evidence_texts：工具结果、确认单、用户原话等的文本。"""
    problems = []
    evidence = "\n".join(evidence_texts)
    allowed = _numbers(evidence) | _date_parts(evidence)
    # 允许元/分换算：工具里 ¥200.00 与回复里 200 一致；百分比 39% 与 0.39
    for value in list(allowed):
        allowed.add(round(value * 100, 2))
        allowed.add(round(value / 100, 4))
        allowed.add(float(int(value)))       # 模型把 ¥4,732.21 说成 4,732
        allowed.add(float(round(value)))
        allowed.add(round(value / 10000, 2))  # “1.5 万”
        allowed.add(round(value / 10000, 1))
    body = re.sub(r"(?m)^\s*[0-9]{1,2}[.、)）]\s*", "", reply or "")  # 列表序号“1. 2. 3.”不是事实数字
    body = re.sub(r"第\s*[0-9]{1,2}|[0-9]{1,2}\s*(?:号|条|笔)?(?=[、和与及或])|P[0-9]{1,2}", "", body)  # “第2笔”“P1”是指代
    for value in _numbers(body):
        if value in allowed or (value <= 1 and value == int(value)):
            continue
        problems.append(f"数字 {value:g} 在工具结果里找不到")
    match = COMPLETION.search(reply or "")
    if match and not completed:
        word = match.group(0)
        if not (cancelled and "取消" in word):
            problems.append(f"没有成功回执却出现完成语“{word}”")
    if not pending_created and PENDING_CLAIM.search(reply or ""):
        problems.append("本轮没有生成待确认单，回复却说已生成")
    return not problems, problems


def evidence_from(obj):
    return json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj

"""输入守卫：在调用模型之前用代码规则识别注入、信息套取、越权与“文字确认”。

高置信命中直接礼貌拒绝、不调用模型，并计入可疑行为熔断。诈骗话术只做提示（交给反诈评分）。
"""

import re

INJECTION_RULES = [
    (r"(忽略|无视|忘记|忘掉|不要管|跳过)(之前|以上|前面|上面|所有|全部|一切)?的?(所有)?(规则|指令|设定|限制|提示|约束|要求)", "要求忽略系统规则"),
    (r"(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|the)?\s*(instructions|rules|prompts?)", "ignore previous instructions"),
    (r"你(现在)?(是|扮演|变成|当)(一个|一名)?(管理员|开发者|系统|超级用户|root|admin|没有限制)", "要求切换身份"),
    (r"(开发者|调试|上帝|越狱|DAN)\s*模式|developer\s*mode|jailbreak", "要求进入特殊模式"),
    (r"以(管理员|系统|银行|超级用户)的?(身份|权限)", "冒用管理员身份"),
    (r"(跳过|绕过|免除|不用|不需要|无需|省掉|取消)(确认|验证|强验证|密码|动态码|风控|审核|审计)", "要求跳过确认或验证"),
    (r"(免|不用)(验证|确认)(直接)?(转|执行|办)", "要求跳过确认或验证"),
    (r"(改|调|设|降)(成|为|到)?(绿档|绿色|低风险档|免确认)|档位(改|调|降)", "要求修改档位"),
    (r"(system|系统)\s*(prompt|提示词)\s*[:：=]", "伪造系统提示"),
    (r"</?\s*(system|external_data|tool)\s*>", "伪造系统标记"),
    (r"(执行|运行)(这段|以下)?\s*(sql|shell|命令|脚本|代码)|drop\s+table|rm\s+-rf|delete\s+from", "要求执行命令或 SQL"),
    (r"[A-Za-z0-9+/]{120,}={0,2}", "超长编码串"),
]

EXTRACTION_RULES = [
    (r"(告诉|发|给|说|报|念|看看|显示|透露|提供).{0,8}(验证码|动态码|确认码|交易密码|支付密码|取款密码|密码)", "secret", "验证码、动态码、确认码和交易密码只有你本人能看到，我看不到，也不会透露或代收。任何人向你索要这些信息都要警惕。"),
    (r"(验证码|动态码|确认码|交易密码|密码)(是|是多少|多少|告诉我)", "secret", "验证码、动态码、确认码和交易密码只有你本人能看到，我看不到，也不会透露或代收。任何人向你索要这些信息都要警惕。"),
    (r"cvv|安全码|完整(的)?卡号|卡号全部|卡背面", "card", "系统里不保存完整卡号和 CVV 安全码，我只能显示卡号后四位。请不要把卡片信息告诉任何人。"),
    (r"(系统|内部)(提示词|prompt|指令|配置)|system\s*prompt|你的(提示词|指令|规则原文)|api\s*key|密钥", "system", "系统提示词、配置和密钥属于内部信息，不能提供。我可以帮你办理转账、账单、理财、卡片、订阅等业务。"),
    (r"(所有|全部|其他|别的)(用户|客户|人)的?(余额|账户|流水|信息|资料|数据)", "others", "我只能查看和办理你本人名下的业务，不能提供其他用户的数据。"),
    (r"(王磊|刘芳|周屿|李建国|李明|李娜|张伟|小王|小张|小李|我妈|妈妈|老婆|老公|房东|他|她|对方)(的)?(卡里|账户|账上|银行卡)?(还)?有多少钱|(查|看|查看|查询)(一下)?(王磊|刘芳|周屿|李建国|李明|李娜|张伟|小王|小张|小李|他|她|对方)的(余额|流水|账户|交易|账单)", "others", "我只能查看你本人名下的账户和流水，不能查询他人的账户信息。"),
    (r"从(王磊|刘芳|周屿|李建国|李明|李娜|张伟|小王|小张|小李|别人|他|她)的?(账户|卡|账上)(里)?(转|扣|划)", "others", "只能从你本人名下的账户转出，不能动用他人的账户。"),
]

TEXT_CONFIRM = re.compile(r"^(我)?(已经)?(确认|同意|批准|授权)(了)?[，,。!！\s]*(直接|马上|立刻)?(执行|转|办|付|买)?(吧|了|就行)?[。!！]*$|"
                          r"(我)?确认了.{0,6}(直接|马上)?(执行|转账|办理)|^(就这样|没问题|好的?|可以|行|执行吧|转吧|ok|OK)[，,。!！]*$")

CANCEL_WORDS = re.compile(r"^(算了|不要了|不转了|不用了|取消|取消吧|先不了|不买了|先别|别转了|撤销|不办了|不弄了)[吧啊了。！!]*$")


def check_input(text):
    """返回 {"verdict": "pass"|"blocked", "category", "rule", "reply"}。"""
    lowered = text.lower()
    for pattern, rule in INJECTION_RULES:
        if re.search(pattern, lowered if pattern.isascii() else text, re.I):
            return {"verdict": "blocked", "category": "injection", "rule": rule,
                    "reply": "这条消息里包含要求我改变规则或跳过安全步骤的内容，我不能照做。所有转账、申购等操作都必须由你本人在确认单上点确认，大额操作还要交易密码和短信动态码。需要办理什么业务，可以直接告诉我。"}
    for pattern, kind, reply in EXTRACTION_RULES:
        if re.search(pattern, lowered, re.I):
            return {"verdict": "blocked", "category": "extraction", "rule": kind, "reply": reply}
    return {"verdict": "pass", "category": None, "rule": None, "reply": None}


def is_text_confirmation(text):
    return bool(TEXT_CONFIRM.search(text.strip()))


def is_cancel(text):
    return bool(CANCEL_WORDS.match(text.strip()))


def wrap_external(text, limit=120):
    """外部文本（交易备注、商户名、产品说明）交给模型前包进标记并截断：这是数据，不是指令。"""
    if text is None:
        return None
    clean = str(text).replace("<", "‹").replace(">", "›")[:limit]
    return "<external_data>" + clean + "</external_data>"

"""出境游场景（PLAN 11.2.8，对标 Revolut AIR 的旅行规划）：卡片境外交易开关、模拟汇率、旅行预算、模拟换汇。

风险对称：开通境外交易增加风险 → 红档；关闭 → 黄档。换汇是本人资金互换 → 黄档，不计入对外转账累计。
汇率是固定的模拟值，不代表真实行情。
"""

from .kernel import RuleError
from .ops import Handler
from .util import iso, new_id, plain_yuan, yuan

# 1 单位外币 = 多少分人民币（模拟，固定）；以及外币最小单位换算（日元、韩元没有“分”）
RATES = {"USD": ("美元", 718, 100), "EUR": ("欧元", 776, 100), "JPY": ("日元", 5, 1), "HKD": ("港币", 92, 100),
         "GBP": ("英镑", 915, 100), "THB": ("泰铢", 20, 100), "KRW": ("韩元", 1, 1), "SGD": ("新加坡元", 534, 100)}
RATE_NOTE = "模拟汇率（固定值，仅供演示，不代表真实行情）"
CURRENCY_WORDS = {"美元": "USD", "美金": "USD", "刀": "USD", "欧元": "EUR", "日元": "JPY", "日币": "JPY", "港币": "HKD", "港元": "HKD",
                  "英镑": "GBP", "泰铢": "THB", "韩元": "KRW", "新币": "SGD", "新加坡元": "SGD"}
DEST_CURRENCY = {"日本": "JPY", "东京": "JPY", "大阪": "JPY", "美国": "USD", "香港": "HKD", "泰国": "THB", "曼谷": "THB",
                 "韩国": "KRW", "首尔": "KRW", "英国": "GBP", "伦敦": "GBP", "新加坡": "SGD", "法国": "EUR", "巴黎": "EUR",
                 "德国": "EUR", "意大利": "EUR", "欧洲": "EUR", "西班牙": "EUR"}


def rates_view():
    return [{"currency": code, "name": name, "cny_per_unit": f"{per_unit / 100:.2f}" if minor == 100 else f"{per_unit / 100:.4f}",
             "note": RATE_NOTE} for code, (name, per_unit, minor) in RATES.items()]


def foreign_amount_text(currency, minor):
    name, _, scale = RATES[currency]
    return f"{minor / scale:,.2f} {name}" if scale == 100 else f"{minor:,} {name}"


def cny_cost(currency, minor):
    """外币最小单位 → 人民币分（向上取整，银行卖出价按模拟汇率）。"""
    _, per_unit, scale = RATES[currency]
    return -(-minor * per_unit // scale)


def wallets(k, user_id):
    rows = k.db.execute("SELECT currency, amount_minor FROM fx_wallets WHERE user_id=? AND amount_minor>0", (user_id,)).fetchall()
    return [{"currency": r[0], "name": RATES[r[0]][0], "amount_minor": r[1], "amount_text": foreign_amount_text(r[0], r[1])} for r in rows]


class ForeignToggle(Handler):
    target = 1

    def subject(self, p):
        return "foreign:" + p.get("card_id", "")

    def card(self, user_id, p):
        row = self.db.execute("SELECT * FROM cards WHERE card_id=? AND user_id=?", (p.get("card_id"), user_id)).fetchone()
        if row is None:
            raise RuleError("forbidden", "只能操作你本人名下的卡。")
        return row

    def prepare(self, user_id, p, recheck=False):
        row = self.card(user_id, p)
        if row["status"] != "active":
            raise RuleError("invalid_request", "这张卡当前不是正常状态，不能修改境外交易设置。")
        if not recheck and row["foreign_enabled"] == self.target:
            raise RuleError("invalid_request", "这张卡的境外交易已经是" + ("开通" if self.target else "关闭") + "状态了。")
        return p

    def view(self, user_id, p, tier):
        row = self.card(user_id, p)
        return {"title": f"{'开通' if self.target else '关闭'}境外交易 · {row['name']} **** {row['tail']}",
                "lines": [{"label": "卡片", "value": f"{row['name']} **** {row['tail']}"},
                          {"label": "境外交易", "value": ("关闭 → 开通" if self.target else "开通 → 关闭"), "emphasis": True}],
                "impact": "开通后可以在境外商户和境外网站消费，回国后建议关闭。" if self.target else "关闭后境外消费会被拒绝，降低盗刷风险。"}

    def sms_text(self, user_id, p):
        row = self.card(user_id, p)
        return f"开通{row['name']} **** {row['tail']} 的境外交易"

    def execute(self, user_id, p, request_row):
        row = self.card(user_id, p)
        self.db.execute("UPDATE cards SET foreign_enabled=? WHERE card_id=?", (self.target, row["card_id"]))
        return {"status": "success", "title": "境外交易已" + ("开通" if self.target else "关闭"),
                "lines": [{"label": "卡片", "value": f"{row['name']} **** {row['tail']}"}],
                "summary": f"{row['name']} **** {row['tail']} 的境外交易已" + ("开通" if self.target else "关闭")}


class EnableForeign(ForeignToggle):
    intent, target = "enable_foreign", 1

    def tier(self, user_id, p):
        return "red", "代码判档：红档（开通境外交易增加风险，风险对称原则：需要强验证）"


class DisableForeign(ForeignToggle):
    intent, target = "disable_foreign", 0

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（关闭境外交易降低风险）"


class ExchangeCurrency(Handler):
    """模拟换汇：从活期扣人民币，存入本人外币钱包。本人资金互换，黄档，不计入对外累计。"""
    intent = "exchange_currency"

    def subject(self, p):
        return "fx:" + p.get("currency", "")

    def prepare(self, user_id, p, recheck=False):
        currency, minor = p.get("currency"), p.get("amount_minor")
        if currency not in RATES:
            raise RuleError("invalid_request", "暂不支持这种外币。")
        if type(minor) is not int or minor <= 0:
            raise RuleError("invalid_amount", "换汇金额必须大于 0。")
        cost = cny_cost(currency, minor)
        if cost > 5000000:
            raise RuleError("invalid_amount", "单次换汇不超过等值 ¥50,000.00（模拟个人便利化额度）。")
        account = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (user_id + "-main",)).fetchone()
        if account["balance_cents"] - account["reserved_cents"] < cost:
            raise RuleError("insufficient_funds", f"活期可用余额不足（需要 {yuan(cost)}）。")
        p["cny_cents"] = cost
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（本人人民币换外币，不计入对外转账累计）"

    def view(self, user_id, p, tier):
        name, per_unit, scale = RATES[p["currency"]]
        return {"title": f"换汇 · {foreign_amount_text(p['currency'], p['amount_minor'])}",
                "lines": [{"label": "买入", "value": foreign_amount_text(p["currency"], p["amount_minor"]), "emphasis": True},
                          {"label": "汇率", "value": f"1 {name} = ¥{per_unit / 100:.2f}（{RATE_NOTE}）"},
                          {"label": "需支付", "value": yuan(p["cny_cents"])},
                          {"label": "付款账户", "value": "储蓄卡（活期）"}],
                "impact": "确认后人民币从活期扣出，外币存入你的模拟外币钱包。"}

    def execute(self, user_id, p, request_row):
        db, now = self.db, self.k.now()
        db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (p["cny_cents"], user_id + "-main"))
        db.execute("""INSERT INTO fx_wallets VALUES(?,?,?) ON CONFLICT(user_id,currency)
            DO UPDATE SET amount_minor=amount_minor+excluded.amount_minor""", (user_id, p["currency"], p["amount_minor"]))
        db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                   (new_id("txn"), user_id, user_id + "-main", iso(now), "换汇 " + RATES[p["currency"]][0], "换汇", -p["cny_cents"],
                    "success", None, None, None, p["currency"]))
        text = foreign_amount_text(p["currency"], p["amount_minor"])
        return {"status": "success", "title": "换汇成功", "lines": [{"label": "买入", "value": text}, {"label": "支付", "value": yuan(p["cny_cents"])}],
                "summary": f"已换入 {text}，支付 {yuan(p['cny_cents'])}"}


def register(ops):
    for cls in (EnableForeign, DisableForeign, ExchangeCurrency):
        ops.register(cls(ops))

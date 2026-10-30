"""其余写操作处理器（卡片、订阅、理财、AA、预算/订单、计划）。由 Operations 注册。"""


def register_all(ops):
    ops.tick_hooks = []

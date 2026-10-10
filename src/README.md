# 启动、模型与公开接口

2026-10-10 已实现：SQLite 模拟账本、六项固定工具、确认与持久熔断、追加审计与事务、候选依赖图控制、标准库真实模型适配器、CLI。北京时间20:35:58开始运行 `scripts/live_demo.py`，退出0，5次真实 DeepSeek 请求完成三个方向的模拟业务；20:36主实现另按 `start.ps1` 输入自然语言账单查询，得到59.70元并退出0。完整脱敏集成证据见[real-model-integration.json](../evidence/real-model-integration.json)。20:39运行两条真实模型依赖计划样例也退出0，见[计划回执](../evidence/real-model-plans.json)；通用复杂规划与队友人工验收仍未完成。

## 启动

```powershell
Set-Location C:\fintechathon
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

也可用任一 Python 3.10+：`python -m src.main --db data/bank.db --user alice`。队长电脑默认 python 是 Windows 商店占位入口，脚本优先检查Codex捆绑运行时，再检查可用系统Python。当前实跑为 Python 3.12.14。仅Python标准库，SQLite/urllib/unittest 随Python提供，无业务依赖安装。

启动不清空数据库、历史日志或锁定；旧待确认在会话重启时失效。当前身份由可信启动 `--user alice` 或 `--user bob` 固定，聊天自称其他人无效。这是模拟身份，不是生产登录系统。

## 模型在本机配置

队长已选DeepSeek V4.1 Flash，官方API名 `deepseek-flash`、基础地址 `https://api.deepseek.com`，本轮允许最多一亿token。本机密钥修正后已真实调用成功，具体见[模型配置说明](../docs/model-configuration.md)。环境变量：`FINTECH_MODEL_BASE_URL`、`FINTECH_MODEL_NAME`、`FINTECH_MODEL_API_KEY`。密钥只在本机输入，不把 `.env` 打入交付包。无配置 / 超时 / 坏JSON失败且不执行业务；未实现账户级预算强制控制，不把用户上限误写成已实测计费保护。

配置后运行 `& $Python scripts/live_demo.py`，在全新模拟数据库中最多5次真实请求检查三个方向。测试脚本只对事先写定的用户 / 目标 / 金额模拟明确确认，输出 `evidence/real-model-integration.json`（不含有效确认码或密钥）；它没有给生产用户自动确认，也不能代替人工验收。

本次账单查询返回5970分；订阅查询、取消视频会员和转账10000分都先pending，再经测试确认success；取消后的第二次账单查询仍5970分。5次响应的 `total_tokens` 合计3526，不代表整个账户或后续调用用量。该次检查未覆盖取消后的未来预计额、红档、异常攻击或DAG生成；未来预计2980分、红档拒绝等证据来自[离线演示](../evidence/three-scenario-demo.json)和[独立63项验收](../docs/09-independent-acceptance.md)。此前[网络失败](../evidence/real-model-network-failure.json)与[HTTP401失败](../evidence/real-model-auth-failure.json)保留，不覆盖。

另运行 `& $Python scripts/live_plan_demo.py`，两次真实自然语言请求在独立模拟库中提出带依赖的计划，合计1583 token。第一条账单节点success、订阅节点pending，`takeover_plan` 后订阅cancelled且旧确认rejected；第二条先读取主账户1000000分，转10000分时后置查询仍not_started，固定测试确认和 `resume_plan` 后读到990000分。公开SQLite快照确认双方990000 / 110000分、储蓄500000分和一条成功转账，重放拒绝。这只证明两条指定计划样例，不证明任意复杂DAG或自动补偿。

## CLI 用法

自然语言如“这个月已经花了多少？”、“我有哪些自动扣款？”、“取消视频会员”、“给小王转100元”经真实模型提出候选，再由代码审查。未配置模型时这些请求失败，不做固定回答。

- `/confirm 请求编号 六位码`：核对屏显完整参数后精确确认本次请求；屏显码只是同意，不是MFA。
- `/cancel [请求编号]`：取消当前待确认，旧授权失效；“不要执行”“算了”等明确否定也由代码取消。
- `/audit`：读取本人脱敏回执；日志原话省略，秘密不保存。
- `/plan 计划编号`：当前节点已确认成功后继续计划。
- `/interrupt 计划编号`、`/takeover 计划编号`：停止未完成节点，回执列出已完成状态。
- `/quit`：退出。
- `/candidate {JSON}`：**离线候选调试**，无需模型，仅检验权限和工具，CLI明确标注模式。

可演示离线输入（金额为整数分）：

```text
/candidate {"intent":"analyze_bills","params":{}}
/candidate {"intent":"query_subscriptions","params":{}}
/candidate {"intent":"cancel_subscription","params":{"subscription_name":"视频会员"}}
/candidate {"intent":"transfer","params":{"contact_name":"小王","amount_cents":10000}}
```

每个黄档新请求都需要当前回执中的编号和确认码；不要把截图/有效码导出到材料。新请求使上一个pending失效。

## 公开接口、夹具和测试

[PUBLIC_API.md](PUBLIC_API.md) 公布 BankService 接口、两名用户及全部夹具、日期、SQLite表、测试时钟和审计故障注入约定。独立测试作者只看该文档和业务规格，不读业务实现确定期望。

```powershell
& $Python scripts/demo.py
& $Python -m unittest discover -s tests -p 'test_*.py' -v
```

`$Python` 指可用Python路径；根README列本机已实跑路径。测试数据放 `tests/.runs`（忽略），不会重置日常 `data/bank.db`。固定候选/模型替身用于复现攻击，真实模型验收另做。[独立报告](../docs/09-independent-acceptance.md) 保存实际结果。

## 边界

日累计含同用户全部源账户的成功转出，以执行时上海日期复检；≤100000分黄档，超过红档。红档的真实MFA和隔离未就绪，保持拒绝。审计失败回滚当前事务，并停止当前会话后续业务；日志整体不可写时无法保证失败记录落盘。管理员持有数据库文件仍可篡改，不宣称绝对防篡改。

候选依赖图、逐节点确认与中断 / 人工接管控制已实现，并已运行两条真实模型依赖计划样例；任意复杂任务规划、完整补偿回退、独立设备MFA、受限可监控隔离、浏览器 / APP / IM正式渠道和队友人工验收尚缺。计划仅在会话内存中，重启不恢复旧授权。已成功转账不自动反转，已取消订阅恢复目前交人工另行处理。

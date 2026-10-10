# FinTechathon · 模拟银行 AI 助手

2026-10-10：Python + SQLite 原型已实现。北京时间20:35:58开始的 `scripts/live_demo.py` 运行退出0，**5次真实 DeepSeek 请求完成账单分析、订阅查询 / 取消和100元模拟转账**，脱敏证据见[真实模型集成回执](evidence/real-model-integration.json)。所有账户、资金和平台操作仍是模拟。

队长选择 DeepSeek V4.1 Flash（API模型名 `deepseek-flash`），密钥仅在本机配置；本轮授权最多一亿token，尚无账户级硬预算控制。20:39又运行两条[真实模型依赖计划样例](evidence/real-model-plans.json)：账单后订阅等待确认并接管停止；查询余额、确认转账、再查询新余额。测试脚本核对预先指定的模拟用户、目标和金额后调用固定确认接口，这不代表生产自动授权或队友人工验收。通用复杂规划、MFA、隔离、完整补偿回退及正式渠道仍有缺项。

## 在本机启动

```powershell
Set-Location C:\fintechathon
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

脚本会找到可用 Python 3.10+。无需安装第三方业务依赖。模型缺配置时明确报错，仍可使用 CLI 的离线候选调试入口。详细[启动与接口说明](src/README.md)、[本机模型配置](docs/model-configuration.md)、[独立测试约定](src/PUBLIC_API.md)。密钥在本机输入，不发聊天、不提交仓库。

```powershell
# 使用任一可用 Python 3.10+；队长本机捆绑路径如下
$Python = 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python scripts/demo.py
& $Python scripts/live_demo.py
& $Python scripts/live_plan_demo.py
& $Python -m unittest discover -s tests -p 'test_*.py' -v
```

`demo.py` 创建独立模拟数据库，不重置日常运行数据，输出到 [脱敏复演回执](evidence/three-scenario-demo.json)。它直接提交候选，不调用真实模型，不可把这段演示说成 AI 接入成功。

`live_demo.py` 使用另一个全新模拟库，在本机模型配置有效时发起5次真实请求；本次记录合计3526 token，仅代表这5次响应的公开计量，不是账户全部消耗。此前[受限网络失败](evidence/real-model-network-failure.json)和[HTTP401认证失败](evidence/real-model-auth-failure.json)保留为历史；修正本机密钥后的成功不覆盖这些失败记录。

## 当前可核对的结果

| 项目 | 实际状态 |
|---|---|
| 实际账单 | 990+1990+2990=5970 分，即59.70元；与未来预计分开 |
| 订阅查询与取消 | 查询黄档，未确认不披露列表；取消视频后历史5970分保留、未来预计2980分 |
| 模拟转账 | 100元明确确认后一次执行，双方余额/流水/成功日志同事务；重放拒绝 |
| 安全边界 | 固定白名单/严格参数/归属/上海日累计/五分钟确认/持久化三错锁十分钟 |
| 任务依赖图 | 固定候选图控制已验；两条真实模型依赖计划样例完成暂停 / 接管和确认后续跑，未证明通用复杂规划 |
| 独立验收 | 隔离子代理只读规格和公开接口编写，结果见[独立报告](docs/09-independent-acceptance.md) |
| 真实模型 | 5次真实请求完成三方向模拟业务；订阅和转账先pending，经预置测试确认后success；本次3526 token |
| 红档MFA与隔离 | 尚未完成，红档拒绝；Docker引擎未连通，见[可行性证据](docs/10-feasibility-evidence.md) |
| 补偿回退、正式渠道、人工验收 | 尚未完成；CLI用于原型调试，已成功转账不自动撤回 |

## 规则与交付

[AGENTS.md](AGENTS.md) 是当前项目契约；[权限v3](docs/01-permission-tiers.md)、[用户故事](docs/02-user-stories.md) 是业务验收依据。[技术说明](docs/11-technical-note.md)、[校内展示草稿](docs/12-school-demo-draft.md)、[执行记录](接下来怎么做.md)、[核对清单](今日核对清单.md) 按实际证据更新。

内部验收仍为北京时间2026-10-11 20:00，19:00冻结新增功能；校内通知未知。赛事提交节点沿用[需求来源记录](spec/competition-requirements.md)，正式提交前复核。v2曾三人确认，v3尚未取得队友同步/人工验收证据。未经另行授权不公开仓库、不push、不部署、不发消息。

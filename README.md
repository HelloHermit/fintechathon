# FinTechathon · 模拟银行 AI 助手

**2026-10-28六场景交付**：保留task1～3，已实现理财数据比较/匹配、模拟卡申请与限额、预算保留及固定服务下单，并接入自然语言、网页、持久计划/恢复和Docker。当前版本`05f3035fed4463db211b6d2a9361fcae2d3af09d2b84854e5a1efb5381044f77`；[支持范围与证据](docs/41-six-delivery.md)、[独立报告](docs/40-six-independent-acceptance.md)、[启动及逐方向复现](docs/38-six-reproduce.md)。真实九组经三批完成，共30次/64338 tokens，首失败完整保留；网页最后版本实测通过，真实模型与离线候选、移动尺寸与真人手机分别记录。源码包含完整代码和逐文件校验，包外解包报告/交付封印给出ZIP SHA和最终复验结果。全部模拟，红档继续拒绝，无后台定时、自动退款或真实银行业务。下方旧数字及阶段约束为历史。

**2026-10-25续接**：task1～3已完成本轮覆盖范围内的实现与验证。task1 Docker独立33项及159项通过，见[29](docs/29-task1-isolation-delivery.md)；task2持久计划/恢复/接管独立37项及159项通过，见[32](docs/32-recovery-delivery.md)。task3多轮澄清、改目标/金额、上下文失效和依赖规划的独立45项、恢复37项、原159项及复用Docker接入4项通过；真实模型首轮15组通过/3组失败保留，只修提示后同18组全部通过，见[35 · 本轮交付与证据](docs/35-context-delivery.md)。网页已实测缺参→补齐→改金额→固定确认、外部文字与桌面/移动尺寸，不能推导任意复杂中文可靠。历史任务可查看，重启须重新核对恢复，黄档逐项确认，已成功业务不自动撤回。隔离须[显式选择专用runtime](src/DOCKER_ISOLATION_API.md)，默认启动不等于隔离，Windows仍失败。真人核验延期，红档继续拒绝。下文10月11—12日为历史。

**2026-10-12当前安排**：队长确认此前技术收尾已完成，最终版本`working-tree-8085df6684d1`、工作区与解包版各159项通过及源码包见[26 · 最终交付](docs/26-closeout-delivery.md)。原10-11 19:00冻结、20:00内部验收约束作废，按队长确认的2026-11-02实际截止推进。真人手机/终端和队友人工核验等本人有空再做，不替填通过。下方旧阶段时间、141项及收尾范围为历史记录，后续任务按新安排执行；红档继续拒绝。

更新：2026-10-11。Python + SQLite 模拟银行原型已有本机浏览器界面与CLI。**真实模型三方向及主实现桌面QA已通过各自覆盖的流程**，账本、确认和拒绝有回执；独立离线93项通过，6条真实异常经独立审核通过。所有账户、资金、联系人和平台操作均为模拟，不连接真实银行。移动端按用户要求待云端后再测，不计通过或失败；计划GUI控制及队友人工验收未计通过。

**本次技术收尾（20:00后）**：已复现并修复红档待验证网页显示/取消、计划取消审计档位、黄档确认跨期三个问题。新增独立18项先9失败、修后全部通过；20:17:54—20:20:07完整**159项通过，131.811秒、退出0、0失败/错误/跳过**，源码/测试、正常账本和两个旧包在该运行区间的指纹均未变，见[本轮回归证据](evidence/closeout-regression-20261011-201754-935091.json)。23时恢复后继续封包，本轮未按20:00节点完成，不新增功能或准备演示。最终源码包、逐文件指纹、解包复验及缺项见[技术收尾报告](docs/25-technical-closeout.md)；下文141项是15:42历史记录。红档仍不执行，本轮没有新增真实模型调用。

队长选择 DeepSeek V4.1 Flash（API模型名 `deepseek-flash`），密钥仅在本机后端配置；本轮授权最多一亿token，尚无账户级硬预算控制。昨天20:39另有两条[真实依赖计划样例](evidence/real-model-plans.json)：账单后订阅等待确认并接管停止；查询余额、确认转账、再查询新余额。测试脚本按预设用户、目标和金额调用固定确认接口，浏览器实际操作由用户核对后点击确认；这些记录不代表生产自动授权或队友人工验收。

接管后的[MFA模块](docs/22-mfa-strong-verification.md)已通过[43项独立合成验收、99个子用例](docs/23-mfa-independent-acceptance.md)，包含登记持有证明、明确同意、时间步防重放、持久锁定、跨期与审计故障回滚、凭据脱敏及CLI边界；首轮脚手架失败和复测保留。**真人手机登记与终端无回显仍待验收，隔离未实测，红档继续拒绝执行**。完整补偿及正式渠道仍缺。本人下一步操作见[src/README.md](src/README.md)，队友按[今天怎么分工](今天怎么分工.md)补实际结果。

当前完整回归为**141项通过，87.947秒，退出0，0失败/错误/跳过**：原93项＋V1四项＋V2一项（10轮）＋MFA43项；[原始输出](evidence/combined-regression-20261011-154218-477873.txt)及[版本/保护快照](evidence/combined-regression-20261011-154218-477873.json)保留。源码和测试前后哈希一致，旧阶段ZIP未变。日常库在此期间被队长同时使用而新增启动/拒绝记录；保护快照如实为变化，不声称全程未变，说明见[核对记录](evidence/normal-database-observation-20261011-1545.json)。本回归由实现方原样运行独立作者的测试，不证明真人设备、真实模型新调用、隔离或完整补偿。

## 在本机启动

```powershell
Set-Location C:\fintechathon
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Web
```

保持服务终端运行，在浏览器打开 [本机演示界面](http://127.0.0.1:8765)。默认可信模拟用户为alice；网页不能切换身份、提交任意候选或取得模型密钥。示例按钮只填入输入，黄档操作先显示目标、金额、影响与期限，核对后才能点击确认。

脚本会找到可用Python 3.10+，后端与业务均只用标准库，页面用HTML/CSS/JS，无需安装框架。模型缺配置时明确失败。CLI调试用不带 `-Web` 的同一启动命令，离线候选只在CLI开放。详细[启动说明](src/README.md)、[模型配置](docs/model-configuration.md)、[业务接口](src/PUBLIC_API.md)和[本机HTTP接口](src/WEB_API.md)。密钥在本机输入，不发聊天、不提交仓库。

```powershell
# 使用任一可用 Python 3.10+；队长本机捆绑路径如下
$Python = 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python scripts/demo.py
& $Python scripts/live_demo.py
& $Python scripts/live_plan_demo.py
& $Python -m unittest discover -s tests -p 'test_*.py' -v
```

`demo.py` 创建独立模拟数据库，不重置日常运行数据，输出到 [脱敏复演回执](evidence/three-scenario-demo.json)。它直接提交候选，不调用真实模型，不可把这段演示说成 AI 接入成功。

`live_demo.py` 使用另一个全新模拟库，在本机模型配置有效时最多发起5次真实请求，失败立即停止，并保存业务状态与审计。今天这5次响应合计3960 token，仅覆盖该次脚本收到的公开计量，不是账户全部消耗。此前[受限网络失败](evidence/real-model-network-failure.json)和[HTTP401认证失败](evidence/real-model-auth-failure.json)保留为历史；它们不再表示当前密钥持续阻塞。

[真实异常报告](docs/13-real-model-acceptance.md)独立审核6条设计用例，其中5条获得真实模型JSON返回、共4007 token，1条明显注入在输入层阻断且没有调用模型。此前[订阅误判](evidence/real-model-clarification-failure.json)、[拒绝审计缺项](evidence/real-model-acceptance-before-audit-fix.json)及[HTTP首轮失败](evidence/independent-web-acceptance.txt)保留，不用最终通过覆盖发现过程。

[桌面QA回执](evidence/browser-ui-validation.json)记录真实页面的三方向、审计及红档拒绝，SQLite核对余额990000 / 500000 / 110000分、视频取消、未来2980分、9条交易和仅一笔10000分转账；控制台错误 / 警告查询两次为空，1536×1024视口无横向溢出。本轮使用8766端口和独立演示库，默认启动仍为8765。这是主实现复演，计划控制触发主体未单独核对，不据此声称按钮验收或队友人工验收。浏览器调用用量未导出，不能并入脚本用量或推算账户总量。

## 当前可核对的结果

| 项目 | 实际状态 |
|---|---|
| 实际账单 | 990+1990+2990=5970 分，即59.70元；与未来预计分开 |
| 订阅查询与取消 | 查询黄档，未确认不披露列表；取消视频后历史5970分保留、未来预计2980分 |
| 模拟转账 | 100元明确确认后一次执行，双方余额/流水/成功日志同事务；重放拒绝 |
| 安全边界 | 固定白名单/严格参数/归属/上海日累计/五分钟确认/持久化三错锁十分钟 |
| 任务依赖图 | 固定候选图控制已验；两条真实模型依赖计划样例完成暂停 / 接管和确认后续跑，未证明通用复杂规划 |
| 独立离线验收 | 原66业务＋27 HTTP的93项历史报告保留；后补V1独立4项、V2独立双进程1项（内部10轮）、MFA独立43项（99子用例），分别见[09](docs/09-independent-acceptance.md)、[16](docs/16-v1-independent-acceptance.md)、[20](docs/20-v2-process-independent-acceptance.md)、[23](docs/23-mfa-independent-acceptance.md)；当前完整回归另记 |
| 真实异常验收 | 6条自动检查与独立证据审核通过；5条真实返回共4007 token，1条输入阻断无调用，见[报告](docs/13-real-model-acceptance.md) |
| 真实模型 | 今天5请求退出0，黄档先pending经预设测试确认后success；SQLite核对未来2980分、双方990000 / 110000分及一笔转账；3960 token |
| 本机浏览器 | 主实现覆盖的桌面三场景、确认 / 红档拒绝、审计与SQLite核对通过，控制台两次为空，见[回执](evidence/browser-ui-validation.json)；计划GUI控制未计通过 |
| 移动端 | 按用户要求待云端后再测，本轮不计通过或失败 |
| 红档MFA与隔离 | MFA合成代码验收43项通过；真人独立手机/终端待验，隔离未实测，红档仍拒绝；见[可行性证据](docs/10-feasibility-evidence.md)及[23](docs/23-mfa-independent-acceptance.md) |
| 补偿回退、正式渠道、人工验收 | 尚未完成；本机Web不是正式银行渠道，已成功转账不自动撤回 |

## 规则与交付

[AGENTS.md](AGENTS.md) 是当前项目契约；[权限v3](docs/01-permission-tiers.md)、[用户故事](docs/02-user-stories.md) 是业务验收依据。[技术说明](docs/11-technical-note.md)、[校内展示草稿](docs/12-school-demo-draft.md)、[执行记录](接下来怎么做.md)、[核对清单](今日核对清单.md) 按实际证据更新。

当前是原型阶段证据与旧快照，不能代替19—20点的技术收尾与新包；今天按队长要求不安排演示准备。内部验收仍为北京时间2026-10-11 20:00，19:00冻结新增功能；校内通知未知。赛事节点沿用[需求来源记录](spec/competition-requirements.md)，正式提交前复核。v2曾三人确认，v3尚未取得完整队友同步/人工记录。未经另行授权不公开仓库、不push、不部署、不发消息。

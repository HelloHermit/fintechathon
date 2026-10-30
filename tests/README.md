# 独立验收测试

**2026-10-25任务续接**：task1 Docker独立33项、task2独立37项及各阶段159项通过，见[29](../docs/29-task1-isolation-delivery.md)、[32](../docs/32-recovery-delivery.md)。task3独立45项、恢复37项、原159项及复用Docker接入4项通过；真实18组首轮15过/3失败保留，只修提示后全18通过，源码版本差异和原始证据见[35](../docs/35-context-delivery.md)，原作者审核见[34](../docs/34-context-independent-acceptance.md)。离线、实际浏览器、真实模型、真人核验分别记录。专项缺环境记失败，不能skip当通过。Windows原31项失败、后续41项未运行；下文为历史。不要把未配runtime的全目录discover当全部实测命令。

当前各套件分别运行，保存新证据且不覆盖历史：

```powershell
python scripts/isolation_check.py
python scripts/stage_check.py --stage recovery
python scripts/stage_check.py --stage context
python scripts/docker_isolation_check.py --runtime .isolation/docker-runtime-20261023
```

前三条不调用真实模型；Docker专项要求显式本机受测runtime和可用Linux引擎。所有套件使用新模拟库，只对正常账本及旧包做文件指纹核对。当前工作树的新增能力须以其自身版本复测，不能直接继承task1/2的旧通过结论。

task3真实18组另行显式运行（使用现有配置与额度，最多40次，无自动重试）：`python tests/run_context_live_acceptance.py --run-live --max-api-calls 40`。不带显式开关或`--help`不读取配置；确认只限预定模拟目标、金额与代码回执严格匹配者，真实失败及用量单独保存。

**20:00后修复复验**：新增`test_closeout_independent.py`由未读实现的独立作者按规则/公开接口编写，18项首轮9失败、修后全部通过；原141项未删除或降低。本轮统一159项通过，131.811秒、exit0、0失败/错误/跳过，见[本轮回归](../evidence/closeout-regression-20261011-201754-935091.json)及[独立收尾报告](../docs/24-closeout-independent-acceptance.md)。下文141项是15:42历史记录。可运行`python scripts/closeout_check.py`自动保存带时间/版本的原始日志；`python scripts/closeout_check.py --archive <新包路径>`另核对包内逐文件指纹、解包回归和公开启动脚本两次重启。全部使用独立模拟库，没有真实模型调用，不证明真人手机/终端或隔离。

更新：2026-10-11。`test_acceptance.py`和`test_web_acceptance.py`由与实现隔离的验收子代理编写。业务作者首次设计只读`AGENTS.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`spec/test-plan.md`和`src/PUBLIC_API.md`；HTTP作者另读公开`src/WEB_API.md`。作者未读取业务、模型或Web实现确定期望。验收通过公开`BankService`及HTTP接口执行，SQLite只访问公开表以核对事实、设置前置条件。

当前统一复跑：**141项通过，0失败/错误/跳过，87.947秒、退出码0**，记录为[evidence/combined-regression-20261011-154218-477873.txt](../evidence/combined-regression-20261011-154218-477873.txt)及[版本快照](../evidence/combined-regression-20261011-154218-477873.json)，源码和测试运行前后哈希一致。组成是原66业务＋27本机HTTP的93项、V1独立4项、V2独立1项（内部10轮）、MFA独立43项（其独立专项99子用例通过）。新增作者也只读规格/公开接口、未读实现确定期望，报告分别为docs/16、20、23；实现方负责这次全套运行。原93项历史报告与失败保留，不代表真人MFA、正式隔离或完整人工验收。

在仓库根目录用 Python 3.10+ 运行，不需安装第三方依赖：

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

本机已找到的运行器：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

业务测试使用独立临时 SQLite 数据库（原套件在`tests/.runs`，新增专项也用临时目录），结束时显式关闭连接并清理自己的目录，不清空正常库。两个MFA `--help`检查未传--db，但参数帮助在打开库前退出。此次正常库保护快照变化与队长同时使用的反馈/启动拒绝日志吻合，见[核对记录](../evidence/normal-database-observation-20261011-1545.json)，不能写成哈希未变。原固定时钟是上海时间2026-10-10 12:00；跨日、过期与锁定明确推进各自测试时钟。

66项业务覆盖三场景、整数分金额、累计边界、执行前复检、归属、确认绑定/否定/超时/重放、联系人真实收款账户绑定、非法取消参数不误停账本、持久化熔断、审计只追加/原子回滚/故障停办、输入与异常脱敏，以及候选依赖计划逐节点确认、失败停止、中断和人工接管。原63条设计与期望保留，真实LA-06审计目标缺项发现后新增64–66三项回归：拒绝也保留安全目标，额外认证字段与有效码不持久化。

27项本机HTTP检查固定资源/端点、可信身份、Host/Origin/CSRF、严格JSON/正文长度/方法、无任意候选/SQL/Shell入口、秘密保护、非法请求保留原pending、确认一次和重放拒绝、计划中断/接管。每次测试使用新库和本机临时端口，模型为离线可重复替身，不访问真实服务。

详细输入/期望/实际/运行状态与历史失败见`docs/09-independent-acceptance.md`。`evidence/independent-acceptance.txt`按运行顺序保留旧失败、修复后复跑、原63条、新增后的66项及最终93项输出；最终结果以文件末尾为准。`evidence/independent-web-acceptance.txt`保留HTTP首轮25通过/2失败（六个失败子场景）及修复后27项通过输出。无需为阅读这些结果再次联网。

`FixedCandidateModel`、`BrokenModel` 都是离线测试替身，只为稳定复现不可信模型输出和异常；它们不调用真实模型服务。`audit_hook` 只注入测试故障，不能关闭权限检查。管理员直接插入/修改测试表只是建立竞争条件或异常前置，不代表应用允许用户直接改库。

真实异常运行器`run_live_acceptance.py`及用例`live-acceptance-cases.json`不被上述unittest发现；只有本机模型已配置、允许联网与相应模型费用时才单独运行：

```powershell
python tests/run_live_acceptance.py --provider-label DeepSeek --model-label deepseek-flash
```

该入口读取本机配置但不打印密钥；不要把API密钥作为命令行参数或发到聊天。默认六用例每条新库，输出脱敏`evidence/real-model-acceptance.json`；退出0表示自动断言通过，语义及证据边界仍须独立复核。当前六异常复核通过，其中五真返回4007 tokens，LA-05输入层预阻断未调用模型；正常三方向五请求3960 tokens和两图1583 tokens另存真实集成证据。真实结果与旧401/网络/过度澄清及审计目标缺项历史见`docs/13-real-model-acceptance.md`。

93项离线结果不能代替真实模型完整对话、浏览器DOM点击与人工演示、两位队友的独立人工验收、并发压力、真实多因素认证或文件/网络/进程隔离实测；这些缺项必须另外记录。测试不设置跳过条件，任何失败或错误都会令命令非零退出。不得为了通过实现而修改业务期望。

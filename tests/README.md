# 独立验收测试

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

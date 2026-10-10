# 独立验收测试

`test_acceptance.py` 由隔离验收子代理编写。首次设计只读 `AGENTS.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`spec/test-plan.md`、`src/PUBLIC_API.md`；未读取业务或模型 Python 实现。验收通过公开 `BankService` 接口执行，SQLite 只访问公开表以核对事实、设置前置条件。

在仓库根目录用 Python 3.10+ 运行，不需安装第三方依赖：

```powershell
python -m unittest discover -s tests -p test_acceptance.py -v
```

本机已找到的运行器：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p test_acceptance.py -v
```

每条测试创建 `tests/.runs` 下独立 SQLite 数据库，结束时关闭所有连接并清理这一条测试创建的临时目录。正式/演示数据库不会被测试重置。固定时钟是上海时间 2026-10-10 12:00；跨日、过期与锁定测试明确推进这个测试时钟。

测试覆盖三场景、整数分金额、累计边界、执行前复检、归属、确认绑定/否定/超时/重放、联系人真实收款账户绑定、非法取消参数不误停账本、持久化熔断、审计只追加/原子回滚/故障停办、输入与异常脱敏，以及候选依赖计划逐节点确认、失败停止、中断和人工接管。详细输入/期望/实际/运行状态与历史失败见 `docs/09-independent-acceptance.md`。`evidence/independent-acceptance.txt` 按运行顺序保留失败、修复后复跑和最终63条原始输出；最终结果以文件末尾为准。

`FixedCandidateModel`、`BrokenModel` 都是离线测试替身，只为稳定复现不可信模型输出和异常；它们不调用真实模型服务。`audit_hook` 只注入测试故障，不能关闭权限检查。管理员直接插入/修改测试表只是建立竞争条件或异常前置，不代表应用允许用户直接改库。

结果不能代替真实模型完整对话、浏览器人工演示、两位队友的独立人工验收、真实多因素认证或文件/网络/进程隔离实测；这些缺项必须另外记录。测试不设置跳过条件，任何失败或错误都会令命令非零退出。不得为了通过实现而修改业务期望。

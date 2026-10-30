# 受限执行公开接口 · v1.1（续接实测）

2026-10-23续接：下文Windows LPAC机制仍未成功运行worker，详细失败见[27a](../docs/27a-windows-isolation-development.md)。新增Docker Linux机制有独立配置与[公开契约v2](DOCKER_ISOLATION_API.md)，共用本文件的监控器/任务/银行接入接口；不能把Docker结果记到Windows机制。显式选择Docker runtime后才使用该后端，没有自动切换。

这是本阶段冻结的验收契约，不是已经通过的声明。独立测试作者只读本文件、docs/27及业务公开契约，不读任何实现。所有攻击目标使用自己的临时目录、模拟库和假秘密，不碰日常账本、真实配置或真实因素。

## 信任边界和启动

Windows 11 x64：LPAC（退出ALL_APPLICATION_PACKAGES默认权限）、零capabilities、禁止子进程策略、Job Object联合使用。Job负责资源和进程组，不能单独称沙箱。不自动创建profile、安装软件或授予网络例外。最初profileless启动在本机失败，当前启动要求可信调用者显式完成下面的专用只读profile配置；失败拒绝，不降级普通进程。

**本机适配补充（首次启动失败后，原始失败保留）**：profileless在当前用户下CreateProcess错误2、没有PID。可由可信调用者显式执行setup的`--permissions-only --create-profile`，走真实权限流程，登记该随机moniker的专用profile并把它的文件目录授权为RX/拒绝写入。不能在worker失败后自动登记或自动降级。配置记录profile_created/profile_files_read_only/profile_directory；setup与run须同一真实用户。文件目录限制仍须实测；该机制不承诺私有注册表容量或磁盘总配额。后续若此适配仍失败，结果仍为未完成，不能改成普通进程通过。

`python scripts/isolation_setup.py --runtime-dir <独立运行时目录>`准备标准库运行时和固定worker；配置仅在该专用目录授予此SID只读/执行ACL，不授权整个项目。目录含python.exe、标准库、必要DLL、worker.py、isolation-config.json及逐文件指纹。首次设置走真实权限流程；重用现有目录不能覆盖未知配置或改变账本。

可信启动器、BankService权限/事务、MFA与审计、模型HTTP客户端留在宿主。真实模型网络和密钥不进入worker。worker只收到最少任务数据，解析模型JSON或计算六固定工具结果；返回值不可信，宿主复核后才按固定SQL改账，worker不决定身份、档位、确认或资金授权。红档继续拒绝。

生产入口通过`start.ps1 -IsolatedTools`或Python入口`--isolated-tools`明确选择隔离模式。模式选中而配置/运行失败，相关操作失败；不默默回退普通执行。未选择此选项的历史入口仍是原可信执行模式，不能称已隔离。

## Python接口

`from src.isolation import IsolatedExecutor, IsolationError`

`IsolatedExecutor(runtime_directory, monitor_database, *, limits=None, audit_hook=None)`：路径均来自可信调用者。monitor_database是独立监控SQLite，不能与业务库同路径。目录配置缺失/不安全、非Windows或任何OS限制不支持时抛`IsolationError`，不启动普通替身。一个监控库同时只允许一个监控器，独占锁在宿主退出后由OS释放；构造时未终结旧task追加abandoned记录，不改旧日志。`close()`停止当前执行并释放锁；支持with。

公开只读路径属性runtime_directory（运行时）、database_path（监控库）、readable_directories（运行时及整个专用profile根）。监控库与业务库均不能位于这些可读目录内；已存在的敏感数据库或监控锁文件若有多个硬链接也拒绝。BankService在开库前另检查不与监控库同文件。同一仓库内，身份按注册moniker定位宿主锁，复制运行时目录也不能共用该SID并行。不同仓库副本的协调未实测，不作跨仓库承诺。

`execute(task_name, payload, *, request_id="", cancel_event=None)`：只接受`parse_candidate`、`compute_tool`，返回任务数据；失败抛`IsolationError(reason, metadata)`。最后的安全回执在`last_receipt`；不含原输入、原stdout/stderr或秘密。明确未知任务为invalid_task。公开固定任务输入：

- parse_candidate：`{"text": "模型JSON正文"}`，严格JSON单对象、重复字段/非有限数字/深度>12拒绝，<=16000字符；输出只是候选，由宿主再次校验业务。
- compute_tool：`{"intent": 六固定意图, "params": 已验证参数, "records": 本人已授权行列表, "now": 带时区ISO时间, "daily_total_cents": 可信已成功累计, "target_account_id": 可信实际目标}`。余额用accounts行，流水/账单用transactions行，订阅用subscriptions行；修改工具输出固定参数的结果而不持库改账。业务数据结构和计算规则以PUBLIC_API/docs01/02为准；宿主必须复核结果一致才提交。

两种payload只允许以上字段集合，缺失或额外字段拒绝；未知/非法任务也记录started/finished。非有限数包括指数溢出。管理员探针复制文件在执行结束后删除，删除失败不交付成功结果。

`run_probe(script_path, payload=None, *, request_id="", cancel_event=None)`：仅可信本机管理员测试入口。独立作者编写自己的Python攻击探针，运行器复制到专用只读runtime下、用与固定worker完全相同的LPAC/Job策略运行；payload经标准输入JSON传递。返回安全结构化receipt，成功JSON输出在data。此入口绝不提供给HTTP、聊天、模型或候选工具。不运行模型生成程序/SQL/shell。

`audit_events()`返回监控表追加记录。`audit_hook(event_dict)`只在宿主测试注入，在每次日志INSERT前可抛异常；不能关闭OS边界。审计故障使执行器halted，未启动则不启动，已结束结果不交付，后续任务拒绝。监控数据与业务事务日志分开；两者不能冒称一个跨库原子事务。

## 权限与预算

- 显式只读/执行允许区：专用runtime目录及新任务脚本。LPAC依然可读Windows授权的部分系统资源；不是路径命名空间虚拟化，不声称整个系统不可读。不得借新文件或reparse point扩大授权。
- 无业务库、监控库、模型配置、MFA因素、宿主环境秘密访问权限。只继承匿名stdin/stdout/stderr三句柄；Job、数据库、文件、监听器和父进程句柄不继承。
- 2026-10-12适配：四变量环境在登记profile后仍启动错误203；增加固定系统路径allowlist后已创建真实PID，仍须完成身份校验才能恢复运行。环境仅有SystemRoot、windir、SystemDrive、USERPROFILE、HOMEDRIVE、HOMEPATH、LOCALAPPDATA、APPDATA、ProgramData、PUBLIC、专用PYTHONHOME及指向只读runtime的TEMP/TMP；路径由Windows token/known-folder API取得，不复制宿主环境、PATH、proxy或模型变量。提供路径不授予文件访问权；所有文件期望及假秘密/句柄不泄露要求保持不变。此变更单独记录，不能称原四变量契约已通过。
- 无网络capabilities，无此SID的loopback豁免；网络必须用同目标宿主阳性对照和worker拒绝验证。未实际验证的网络种类逐项列缺项。
- 进程数1；禁止创建子进程、禁止breakaway；启动挂起时先施加并复核全部限制，再恢复。
- 默认墙钟5秒、用户态CPU累计1秒、CPU硬占比20%、Job和单进程提交内存128MiB、stdout+stderr总和65536字节、输入UTF-8 JSON65536字节。输入JSON不准NaN/Infinity。limits只可缩紧上述值；wall_seconds最低0.2、cpu_seconds最低0.1、memory_bytes最低32MiB、output_bytes最低1024、process_count固定1、cpu_rate_percent最低1。
- 达到墙钟预算立即终止整个Job，额外允许最多2秒等待清理；取消event设置后按最多100ms检测，再终止等待。输出达上限拒绝并终止，不能无限积累宿主内存。CPU/内存由OS强制限制，统计来自可信宿主查询，不能信worker自报。
- 无可写业务/输入目录。**不宣称磁盘总容量、注册表、全部GUI/所有系统对象已建立硬上限**；若profileless机制无法实现或发现额外可写区，必须列出且不能预填全部文件隔离通过。Job没有磁盘总量配额。

## 回执、监控和失败

receipt含task_id、request_id、status(success/failed/cancelled)、reason、metadata、data（仅成功JSON）。reason包括ok/invalid_task/invalid_input/isolation_unavailable/start_failed/identity_mismatch/nonzero_exit/timeout/cpu_limit/memory_limit/output_limit/invalid_output/cancelled/audit_unavailable/result_mismatch。没有任意异常文本或原标准错误；非法输出仅记长度/摘要。

metadata来自宿主：真实PID、is_appcontainer、is_lpac、capability_count、integrity、job_limit_flags、child_restricted、loopback_exempt、实际预算、开始/结束北京时间、wall_ms、cpu_ms、peak_job_memory_bytes、active_processes_after、退出码/终止原因。任何身份或限制不符时终止，不能返回success。以Job查询、token检查及进程等待为主；异步资源通知可能不完整，限制原因不够明确时用nonzero_exit而不虚构精确OOM。

监控SQLite公开表`isolation_audit(id,timestamp,task_id,request_id,event,status,reason,metadata_json)`，禁止UPDATE/DELETE。已有库的表结构及追加触发器须完整符合契约，否则拒绝，不覆盖未知库。event started/finished/abandoned；先持久化started才能运行，结束持久化finished才能交付结果。started元数据只含计划预算/机制标记，finished含安全实际统计；原输入、路径内容、stdout/stderr、因素不入日志。close与结果交付串行；取消后的结果不交付业务，清理未结束时不释放监控锁给新宿主。

选中隔离的BankService增加可选构造参数`executor=None`（既有参数保持）。每个真正执行的工具经过compute_tool；异常返回failed/isolation_failed并记录isolation_failed，无业务成功或修改、后置依赖停止；审计故障仍回滚停办。成功返回不改变旧工具结果。ModelClient可注入candidate_parser用于同一执行器处理原模型JSON；HTTP密钥仍只在宿主。选中隔离模式的模型JSON解析失败不能回退宿主解析。

字段明确：业务失败响应的reason=`isolation_failed`，另有isolation_reason为固定底层原因。持久业务日志为event=`isolation_failed`、result=`failed`，reason保存底层固定原因（例如audit_unavailable）；不能把响应reason与日志reason当同一字段。Bank停办后audit_events不再发起读取，返回空列表，HTTP按停办状态返回failed；空列表不表示账本日志为空。独立可信核对者可在自己的模拟库通过PUBLIC_API公开的audit_log表检查实际已追加事件及无成功修改，不能据停办后的空回执预填日志未保存或已通过。

本接口的通过范围限于独立原始证据；不代表真人因素、正式渠道或生产安全，也不授权解除红档拒绝。

## 本机LPAC核验适配（v1.1）

原Token46查询在本机Win32返回87、Nt查询返回0xc0000003，原失败保留，不能改填通过。恢复worker前，可信宿主读取真实token的AppContainer、零capabilities、SID及完整性，另外将此token用DuplicateToken复制为impersonation token，以AccessCheck对六个受控的内存DACL进行核验。所有DACL有owner/group；DesiredAccess为MAXIMUM_ALLOWED，GenericMapping为read=1/write=2/execute=0/all=3。O:SY/G:SY；除空DACL外均先给Everyone掩码3；其余ACE和期望如下：

| label | 附加允许ACE | 必须得到的授权结果 |
|---|---|---|
| everyone_only | 无 | allowed=false, granted=0 |
| package_positive | 本次实际AppContainer SID，mask3 | true, 3 |
| aap_only | S-1-15-2-1，mask1 | false, 0 |
| restricted_package_only | S-1-15-2-2，mask2 | true, 2 |
| distinct_package_bits | 上面两条package组ACE | true, 2 |
| empty_dacl | 整个DACL为空，无Everyone ACE | false, 0 |

每次AccessCheck本身必须成功，不能把API失败当权限拒绝。API成功但拒绝时error=5是诊断值，不是API失败。任一对照不符或任一API失败，都不恢复进程。metadata的`lpac_verification_method="accesscheck_aap_optout_v1"`及`lpac_access_checks`保存上述六项的api_ok/allowed/granted/error；`is_lpac`在本接口中表示通过此实际权限行为核验，不能只从启动flag设置。独立作者应以自己的token/AccessCheck或受控文件哨兵再次核对AAP授权确被忽略，并与宿主回执对应。

`lpac_access_checks`是label到记录的字典，例如`{"aap_only":{"api_ok":true,"allowed":false,"granted":0,"error":5}}`。`metadata.stdout_sha256`是宿主保留的stdout字节SHA-256；未超输出预算时覆盖全部stdout，超限时只覆盖有界前缀。`output_bytes`是保留的stdout+stderr长度，不能用它声称测得洪流总写入量。独立失败探针可以先输出预先约定的JSON空白标记，再用此摘要确认探针主体确已执行；解释器初始化失败不能当作内存/CPU/网络攻击已被拦截。

若真实后端回报`cleanup_complete=false`，监控器失败并停办，保留身份锁和监控锁，并在身份锁旁写`.quarantine`持久拒用标记。新实例拒绝该身份；close不会通过释放锁冒称清理成功。只有可信操作员核验OS退出后才能处理该标记，本阶段无自动解封入口。该极端失败路径需单独验证，不因正常退出通过而自动记通过。

这是依据[微软LPAC语义](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)组合[AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)和[DuplicateToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetoken)的本项目行为核验，不宣称微软提供了专用IsLPAC getter或保证此组合覆盖所有系统对象。ARAP保留与精确mask是本机受控观察，须由独立实测确认。原身份限制、文件/网络/进程/资源期望不降低。

`readable_directories`的非runtime项为整个专用profile根，可从中定位profile拒写实验，不能枚举用户其他目录或读取已有profile文件内容。监控独占锁的公开路径是`str(database_path)+".lock"`。Executor路径或多硬链接参数在开库前抛`IsolationError(reason="invalid_input")`；BankService的同类构造错误抛`ValueError`且不开业务库、不创建该路径。

started审计失败时，本次`last_receipt`必须是failed/audit_unavailable、带新的task_id、pid=null及active_processes_after=0；finished审计失败时保留本次实际安全统计但改为failed/audit_unavailable，不可残留success。停办后的新尝试仍产生新的内存失败回执，不能在不可写审计库中伪造持久记录。非法任务或非dict payload在宿主拒绝且记录started/finished；模型JSON内容是否合法由真实固定worker解析，所以非法候选内容可以启动worker，但不得交付data或办理业务。

# 28 · 受限执行独立验收

更新：2026-10-12。作者为独立验收子代理，未阅读任何业务、隔离、worker、模型或CLI实现 `.py`；依据仅为 `AGENTS.md`、[27 · 边界](27-isolation-boundary.md)、[隔离公开接口](../src/ISOLATION_API.md)、[业务公开接口](../src/PUBLIC_API.md)、[01 · 权限](01-permission-tiers.md)、[02 · 用户故事](02-user-stories.md)、[05 · 审计](05-audit-log-spec.md)。

当前已取得并由独立作者复核首轮真实运行证据，**隔离验收未通过**。作者先前的运行调用曾等待审批后被中断，返回 `aborted by user after 1727.3s`；该中断本身没有验收结果。随后主代理/root在真实用户上下文运行原作者冻结的31项测试，独立作者只复核原始报告，未阅读实现。后续真实用户命令仍由root执行，作者不重复发起权限申请。

## 已运行的首轮结果

原始证据：[isolation-independent-20261012-014134-818662-736ddb1b.json](../evidence/isolation-independent-20261012-014134-818662-736ddb1b.json)，phase=`initial-before-lpac-api-adaptation`。保留原文件，不覆写、不回填为通过。首轮原JSON的起止时间为 `2026-10-11T11:41:34.818662-06:00` 至 `11:41:41.515162-06:00`，换算北京时间为 **2026-10-12 01:41:34.818662—01:41:41.515162**，约6.697秒。

| 统计口径 | 原始结果 |
|---|---|
| 顶层用例 | 31项实际运行，4项通过，27项未通过，无跳过 |
| 27项未通过的组成 | 25项顶层failure、1项顶层error、1项含6个失败子例的顶层用例 |
| unittest条目 | `failures=31`（25个顶层failure加6个子failure）、`errors=1`；不能误写成31个顶层失败加1错误 |
| 全部计划通过 | `all_planned_cases_passed=false` |

4个通过项只有：缺配置拒绝、非法预算拒绝、隔离失败停止后置计划、未登记因素的红档转账仍拒绝。后两项证明所测故障下业务未继续，不证明worker已完成受限执行。业务隔离故障用例虽然观察到 `failed/isolation_failed` 和余额不变，整项仍失败；不能据局部观察提升为通过。

多条回执已有真实PID、`is_appcontainer=true`、`active_processes_after=0`，但 `is_lpac`、capability、integrity及Job证明为空，`reason=isolation_unavailable`、Win32错误87、输出0字节。当前进程在挂起身份检查阶段即被终止，没有恢复运行。文件、网络、进程创建、资源预算、非法输出和正常三方向因此均未形成成功运行探针的证据；**不能把未运行攻击视为被隔离机制拦截**。父退出用例明确观察到worker PID集合为空，也不计清理通过。首轮审计故障用例失败，原报告未保留异常正文，不能只凭空observations臆测失败位置。

## 原始记录与运行约定

测试文件：[tests/test_isolation_independent.py](../tests/test_isolation_independent.py)。首轮31项；续轮已补充为**41个顶层用例**，含12组非法预算、6组路径变体、11组非法任务/输入生命周期、多个非法JSON、两种创建子进程API等子例。续轮测试源码与自写探针已通过语法检查，尚未进行续轮真实OS执行。测试只新建自己的 `tests/.runs/isolation-independent-<时间>-<随机后缀>` 和 `evidence/isolation-independent-<时间>-<随机后缀>.json`；profile拒写探针仅在公开专用根内尝试创建唯一标记，期望全部失败，不读取已有profile文件。不打开日常 `data/bank.db`、真实 `.env` 或真人因素。

输出只保留布尔、状态、哈希、计数和预算统计；异常及标准错误正文不打印。即使测试使用假秘密，证据仍再次脱敏。每次运行独立命名，首轮失败与复测不会互相覆盖。无runtime配置或非Windows时跳过，整体 `all_planned_cases_passed` 为false，退出1；不能把跳过写成通过。

续轮冻结测试源码SHA256为`986b41f932f064e30e5765459b91d67f2cfa230411dfb6753800fb08aff2b1f0`，其中自写probe字符串SHA256为`d06289776e210fe73b8c2345547e62926b571d7d3558ecc7cd4ec8e8cb73b9b8`。新证据分别记录顶层汇总与unittest条目，另留自身测试失败行号帮助定位，不输出异常正文。

主执行者使用捆绑标准库Python，在完成真实权限流程后运行：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tests/test_isolation_independent.py --runtime-dir C:/fintechathon/.isolation/runtime-20261012 --phase initial-before-lpac-api-adaptation
```

以上命令已由root用于取得上述首轮证据，结果未通过。不新增模型调用、不访问真实互联网；联网实验限于测试自己创建的本机IPv4/IPv6 TCP或UDP监听器，父进程先对同一目标成功连接/发送作为阳性对照。

## 独立输入、期望与方法

实际结果、是否运行、最没把握处由每次原始JSON逐项保存。本表在首轮运行前确定期望；实现失败不得通过降低文件、网络、权限、资源或业务期望修成通过。

| 测试输入 | 期望 | 独立验证方法 | 当前实际／是否运行 | 最没把握处 |
|---|---|---|---|---|
| 缺配置目录；放宽预算、低于下限或未知键 | 拒绝、无普通进程回退 | 自建空目录、12组参数，外部枚举runtime镜像PID | 首轮已运行，2项通过 | 构造失败元数据的边界 |
| 真实worker身份 | AppContainer及LPAC、零能力、low完整性；宿主回执相符 | 作者自己的Win32 ctypes读取token，宿主metadata及进程等待 | 首轮失败；续轮采用下述独立6对照，未运行 | Token46不支持，原失败保留；不能直接设LPAC标记true |
| 已授予runtime读文件、写文件与创建 | 读允许，写和创建拒绝 | 实际文件I/O布尔，宿主检查新文件不存在 | 首轮失败，探针未恢复运行 | profile根测试已另补，待真实执行 |
| 假模型配置、模拟库与因素文件 | 外部读／写／删除／创建全部拒绝，原件哈希保留 | 绝对、大小写、斜杠、点、父路径、扩展路径；宿主再检查 | 首轮失败，探针未恢复运行 | 只证明这些真实路径形式，不推断所有系统文件不可读 |
| 监控库路径；自建目录junction | worker不能读监控库，也不能通过reparse扩大访问 | 真正open与宿主阳性read/原件检查 | 首轮失败；junction宿主阳性已建立，worker未运行 | junction不可创建时跳过且不宣称该边界通过 |
| 假秘密环境及可继承文件／监听器／父进程句柄 | 秘密环境与非stdio句柄均不可用 | 父进程阳性读取；worker直接ReadFile、socket、GetProcessId | 首轮失败；四键检查已独立适配为13键及runtime路径一致性，待执行 | 13键是公开新适配，不能写成原四键通过 |
| 同目标IPv4 TCP、IPv6 TCP、IPv4 UDP | 父进程成功；worker网络API失败；监听端没有worker包 | 实际监听与接收计数／哈希 | 首轮3项均失败，worker未运行 | IPv6无宿主阳性则不填通过；外网/DNS另列缺项 |
| runtime解释器经subprocess与native CreateProcess breakaway | 两种方式均不能创建子进程 | native API绕过Python函数；host Job事实和PID终结 | 首轮失败，worker未运行 | 只能证明已试API／目标，不推断所有GUI对象 |
| sleep、忙循环、内存增长、stdout／stderr洪流 | 墙钟／CPU／内存／输出预算拦截并清理Job，不交付结果 | 独立空白标记的宿主stdout哈希、资源统计、墙钟、外部PID等待 | 首轮5项均失败；已加强可达性断言，续轮未运行 | 解释器启动非零退出不得算内存限制通过；无法精确归因时可诚实记nonzero_exit |
| 执行时取消；worker退出7；杀自建宿主 | 取消/异常无活worker；父退出Job清理；恢复追加abandoned | 标记哈希、事件计时、外部镜像枚举/GetProcessTimes用户CPU/等待、前后SQLite旧行一致 | 首轮均失败；父退出前worker集合为空 | 杀宿主前须有仍存活且已有用户CPU的真实worker，不能把仅挂起创建算清理通过 |
| 非法worker JSON及非法候选/超长输入 | 拒绝，无原stdout/stderr、无宿主解析回退 | 自写探针输出重复键/NaN/数组/多对象/深度13等并核对确切输出哈希 | 首轮1项error，另1项含6个子failure | 内容非法JSON可由真实worker解析；未知任务和非dict payload须在宿主拒绝 |
| 监控UPDATE/DELETE、两个owner、started或finished审计故障 | 只追加/独占；故障停办；结束结果扣留；重启追加abandoned | 公开audit_hook注入、SQLite表与trigger真实约束 | 首轮相关项均失败 | 跨库监控与业务不是一个原子事务；不宣称抵抗电脑管理员 |
| 三方向正常业务：账单、订阅查询/取消、100元转账 | 实际账单5970分不因退订删除；黄档确认后执行；双方余额正确 | BankService公开接口、真正compute_tool监控记录、独立SQLite核对 | 首轮失败，正常计算未完成 | 返回应与历史接口一致，runtime未运行则不算业务隔离通过 |
| 隔离结束审计失败／业务成功审计失败／前置计划失败 | 不改账；isolation_failed或audit_unavailable；后置停止 | 真实executor+公开hook，余额/转账表/日志前后比对 | 前置失败停止计划1项通过；另2项整体失败 | 隔离故障用例的余额未变只是局部观察，不把整项提升通过 |
| 未登记因素的1000.01元转账 | 红档仍拒绝，不启动资金工具，不改账 | 档位/拒绝原因、余额与monitor记录 | 首轮已运行通过，worker未调用 | 不替代真人密码/独立认证器/终端实测 |

## 续轮新增10项的冻结预期

以下均已写入测试，完成自身语法检查，尚未真实运行。每项实际结果仍由后续独立命名JSON记录。

| 输入 | 固定期望与验证方法 | 最没把握处 |
|---|---|---|
| 公开专用profile根及其既有子目录 | 只枚举目录元数据，逐目录尝试创建唯一文件/目录；全部拒绝，宿主标记均不存在 | 只覆盖当时枚举目录；reparse子树不跟随，注册表另缺 |
| monitor_database指向runtime/profile内部 | 构造invalid_input，在开库前拒绝、不创建文件、无worker | 不能把OS拒写而未进行代码路径检查冒充构造成功 |
| 已初始化monitor数据库新增第二硬链接 | 构造invalid_input、原件/别名哈希相同且不变、无worker | 只验证本机NTFS硬链接 |
| BankService数据库位于runtime/profile或与monitor同文件 | ValueError、无新文件、monitor schema不变 | 不读取真实账本，仅自有监控库 |
| 自有业务库新增第二硬链接 | ValueError、原件/别名哈希及余额不变 | 此为管理员异常夹具，不等于应用授权 |
| 公开`.lock`路径预置多硬链接 | Executor invalid_input、不开监控库、锁原件/别名内容不变 | 不假定正常close后锁文件必须保留 |
| 同runtime、不同monitor同时构造 | 同一身份第二owner拒绝；第一close后新owner能真实运行probe | 不扩大为跨仓库副本协调声明 |
| 11组未知任务/非法payload/非有限候选 | 每次新的失败回执与started/finished一对、原日志前缀不变、假秘密不泄露；未知任务/非dict无PID | 字段/内容拒绝层次分开；非法JSON正文可以有worker PID |
| 已有无关SQLite schema作monitor | 拒绝且原文件哈希、原表内容不变 | 不推断管理员不能修改数据库 |
| 真实success之后注入started审计故障，再尝试新任务 | 每次failed/audit_unavailable、新task_id、pid=null、无data；旧success不复用，旧日志不变，无新worker | 不要求在不可写库伪造故障持久记录 |

## 公共契约适配与尚未验证的范围

最初的profileless与四变量环境启动契约发生了公开适配：主执行者报告本机profileless错误2、随后四变量错误203；目前只允许通过显式权限流程登记专用profile，并收紧整个专用profile目录为只读。增加的13个键只传入系统路径，不复制PATH、proxy、模型秘密或宿主任意环境。**适配前的失败保持失败，不能将新机制称为原机制通过。** 首轮回执确实记录这13个环境键，但worker尚未恢复运行，不能据此证明worker实际环境内容或秘密未继承；测试原四键检查将按新公开集合单独适配并注明。

续轮依据公开v1.1固定：Executor路径/硬链接拒绝为IsolationError/invalid_input，业务构造拒绝为ValueError，锁路径为`str(database_path)+".lock"`。started审计失败时必须有新的内存failed/audit_unavailable回执、pid=null、active_processes_after=0；finished审计失败须扣留结果并保存实际安全统计。上述新增预期在实跑前确定，不按实现结果倒改。

身份续轮使用独立作者自己的ctypes代码：读真实token25/29/30/31，DuplicateToken为impersonation token，AccessCheck使用另一组不重叠位，GenericMapping为`0x10/0x20/0x40/0x70`。所有SD均有owner/group，除空DACL外先给Everyone `0x70`，实际package阳性ACE为`0x50`，AAP为`0x10`、ARAP为`0x20`；DesiredAccess为MAXIMUM_ALLOWED。冻结期望如下，每条API自身均须成功，不能把API调用错误当权限拒绝。

| 对照 | 独立worker granted期望 | 宿主公开granted期望 |
|---|---|---|
| everyone_only | 0，拒绝 | 0，拒绝 |
| package_positive | 0x50，允许 | 3，允许 |
| aap_only | 0，拒绝 | 0，拒绝 |
| restricted_package_only | 0x20，允许 | 2，允许 |
| distinct_package_bits | 0x20，允许 | 2，允许 |
| empty_dacl | 0，拒绝 | 0，拒绝 |

同时要求真实PID与宿主相符、AppContainer、capability=0、low完整性、Job/子进程限制和`lpac_verification_method="accesscheck_aap_optout_v1"`；各独立实测值与宿主六项各自核对。此适配证明所测AAP退出行为，不宣称实现专用IsLPAC getter或所有系统对象均隔离。只读取专用profile根的目录元数据，不访问真实用户其他目录或已有profile文件内容。

为防止“解释器未启动却被误算为攻击拒绝”，自写探针在解析payload后向stdout写固定JSON空白前缀，随后才进入攻击分支。sleep/CPU/内存/非零退出/取消须核对可信宿主stdout_sha256恰为该前缀哈希；非法输出及stdout洪流核对已知完整输出或有界前缀哈希。内存压力即便返回nonzero_exit，也须先有此到达证明。墙钟攻击由原0.2秒改为1秒，取消触发由0.3秒改为1秒，以容纳20%CPU下解释器启动；仍检查所选预算和契约清理时间，不把原0.2秒用例填通过。输出预算仍为1024字节，CPU仍0.1秒，内存仍32MiB。

finished审计注入用例还要求公开hook确实接到原本`success/ok`的结束事件，再故意使其INSERT失败，避免把启动失败冒充成功结果被扣留。父退出用例在杀宿主前独立查询目标PID已有非零用户态CPU且仍存活；该查询只证明执行超出挂起创建阶段，不扩大文件/网络测试结论。

不证明互联网TCP/HTTP、互联网DNS、IPv6 UDP、磁盘总量配额、注册表容量、全部GUI/系统对象、真人MFA或正式赛事渠道。LPAC可能可读Windows明确授予的部分系统资源，因此外部模拟文件拒绝不等于路径命名空间虚拟化。红档解除拒绝不在本轮授权或验收范围内。

技术依据采用Microsoft公开Win32接口说明：[TOKEN_INFORMATION_CLASS](https://learn.microsoft.com/windows/win32/api/winnt/ne-winnt-token_information_class)、[AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)、[DuplicateToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetoken)、[Tool Help Functions](https://learn.microsoft.com/en-us/windows/win32/toolhelp/tool-help-functions)。证明依赖实际操作与宿主观察，不依赖worker自称被隔离。

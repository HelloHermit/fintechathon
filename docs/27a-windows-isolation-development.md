# 27a · Windows LPAC 开发记录与未完成边界

记录日期：北京时间2026-10-24。执行主体为实现方与主对话的真实用户权限流程；本文件不是独立验收报告。当前Windows源码已冻结，后续主交付转向另行实现、另行验收的Docker路线；不能把另一机制的成功记为Windows通过。

**当前结论：Windows LPAC身份及Job配置已取得真实挂起进程核验，但最小Python任务和Windows系统程序均在加载器阶段以`0xC0000142 / STATUS_DLL_INIT_FAILED`结束，未取得一个成功的Windows worker任务。Windows隔离交付未完成，不能称“Windows沙箱已通过”。** 实际业务结果、越界攻击、网络拒绝及资源攻击的成功验收均不能从身份元数据推导。

## 已实现和已观察到的内容

`src/windows_isolation.py`保留LPAC、零capabilities、子进程禁止策略、Win32k禁止策略、匿名标准输入输出三句柄白名单与Job联合约束。未降级普通AppContainer或普通进程；未放宽只读profile，未修改真人桌面ACL。模型密钥、业务库与真实因素未交给这些诊断程序。

本轮完成的代码修复：

- 对真实挂起token增加`accesscheck_aap_optout_v1`核验。`TokenIsLessPrivilegedAppContainer`（class 46）在本机仍返回错误87；代码记录该失败，不将其写成查询成功。源token须为primary token，复制为impersonation token后，对六个内存安全描述符逐一调用真实`AccessCheck(MAXIMUM_ALLOWED)`。六个阳性、阴性对照必须全部匹配；API失败、结果不符或支持的class46明确返回0均不接受该身份。
- `lpac_verification_method`、`lpac_access_checks`记录方法和安全数码；`startup_stage`记录固定阶段标签。元数据不含任意异常文字、输入、环境值、验证码或原始标准错误。
- 更正`0x2000E`（child policy）与`0x2000F`（ALL_APPLICATION_PACKAGES opt-out）的变量对应名称；两者原值均为1，此项修正没有降低策略。
- 原生后端自身也只允许收紧默认预算：墙钟5秒、用户态CPU累计1秒、CPU硬占比20%、单进程/Job内存128MiB、进程数1、输入及合计输出65536字节。输出**达到**上限即拒绝，并保持缓存有界。
- 终止后的进程等待及所有宿主IO线程`join`共用同一个2秒清理deadline。`process_exit_confirmed`、`active_processes_after`及`cleanup_complete`分别记录确认情况；未清理完成不能交付成功。真实正常失败路径已观察到进程退出、Job进程数0；最坏清理异常和连续攻击情形未做独立实测，不能称全部清理故障已通过。
- 增加子进程/Win32k策略、Job进程数、CPU时间/占比、内存及SID一致性的实际readback字段。设置值和查询值必须匹配才能恢复线程。

真实六对照观测如下。全部`api_ok=true`；`allowed=false`时错误5是授权拒绝，不是`AccessCheck`调用失败。

| 对照 | allowed | granted |
|---|---:|---:|
| everyone_only | false | 0 |
| package_positive | true | 3 |
| aap_only | false | 0 |
| restricted_package_only | true | 2 |
| distinct_package_bits | true | 2 |
| empty_dacl | false | 0 |

`distinct_package_bits`分别给ALL_APPLICATION_PACKAGES位1、ALL_RESTRICTED_APPLICATION_PACKAGES位2；实际只得到位2。代码同时要求本人包SID阳性对照成立、Everyone及空DACL阴性对照成立。这里使用的是文档API与LPAC语义的组合，并非宣称Microsoft另有一个完整记载此组合的专用`IsLPAC`接口，也不是依据创建flag直接填写`is_lpac=true`。

真实readback曾记录：`is_appcontainer=true`、`is_lpac=true`、`capability_count=0`、完整性4096（Low）、Job flags 8972、child policy 1、CPU控制flags 5/rate 2000、单进程及Job内存134217728、Job用户态CPU1000ms、进程上限1、loopback exemption=false。**这些事实只说明相应身份/配置核验完成；随后进程仍失败。** `startup_stage=running`仅表示已调用`ResumeThread`，不表示Python脚本已进入或业务任务已成功。

## 加载器故障及受控对照

1. 最小候选解析经完整身份/限制核验后恢复，退出码3221225794（`0xC0000142`），stdout/stderr均为0；宿主监控追加started及failed/finished，未返回候选结果。
2. 只读PE导入表查看未发现`python.exe/python312.dll`直接导入USER32；这没有排除传递依赖或系统初始化问题。PE检查使用标准库解析，不安装额外工具，结果在当次工具输出，重现helper见下。
3. 单次Win32k对照在内存副本中只取消该额外位并要求**真实readback为false**，仍以同一码失败。因此没有据此移除生产Win32k策略。诊断副本不是生产实现或验收替身。
4. `DEBUG_ONLY_THIS_PROCESS`诊断只记录DLL basename及退出/异常数码，不读取debug字符串、远程内存或桌面内容。仅观察到`python.exe → ntdll.dll → kernel32.dll → KernelBase.dll`，随后同码退出，未观察到`python312.dll`载入。debug会改变启动条件，该结果只作定位。诊断中宿主system-call-disable flags为0；子进程为5，不能把其额外FSCTL限制归因于宿主工具继承。
5. 从受信`Windows/System32/sort.exe`复制一个临时文件到专用runtime/tasks，在相同LPAC/Win32k/零cap/child/Job策略下输入固定无秘密JSON行，同样在启动阶段失败。临时副本已删除；这支持故障不是Python脚本或Python库独有的问题，未证明具体根因。
6. 挂起token通过六对照后，宿主短暂impersonate，仅对明确运行时及系统文件open/close，**未读取内容，也未恢复worker**。`python.exe`、`python312.dll`、zip、worker及三个系统DLL均可打开；runtime目录可打开，父目录/project/盘根的遍历+属性打开被拒绝。恢复宿主线程身份已确认。前述文件可开不能证明加载器所需的所有权限均已满足。
7. 仅增加固定`ALLUSERSPROFILE=KnownFolder ProgramData`别名，以及仅令`lpDesktop=""`的两个独立对照，仍以同一码失败；均未复制完整宿主环境。生产仍保留原13项路径环境及原桌面选择。

Windows站/桌面权限是尚未确认的假设。只读`GetUserObjectSecurity + AccessCheck`helper已写并通过语法检查，**尚未实际运行**；没有该权限检查结果，没有创建私有station/desktop，也没有改真人桌面ACL。原生Windows排查在此冻结，不继续扩张权限。

## 原始证据索引

各记录保留原始成功/失败事实；不存在后续成功覆盖此前失败的处理。

| 阶段 | 原始文件 | 实际范围 |
|---|---|---|
| 原profileless首次失败 | [011011](../evidence/isolation-development-20261012-011011-445757.json)、[011025](../evidence/isolation-development-20261012-011025-884660.json) | 错误2，无PID |
| profile登记后环境启动失败 | [011808](../evidence/isolation-development-20261012-011808-107967.json) | 错误203，无PID |
| 增加固定路径环境后 | [013517](../evidence/isolation-development-20261012-013517-119105.json) | 有PID，class46错误87，未核验后恢复 |
| 续作保护基线 | [resume-baseline](../evidence/isolation-resume-baseline-20261023-163447-251615.json) | 原账本/旧包及源码指纹；不是业务运行 |
| 挂起token六AccessCheck初次诊断 | [lpac-accesscheck](../tests/.runs/native-development-lpac-accesscheck-20261023.json) | 六对照数码；诊断故意抛50，不Resume，Job0 |
| 最小Python任务 | [003533](../evidence/isolation-development-20261024-003533-093010.json) | 身份/配置已核验，恢复后加载器失败；监控失败日志 |
| 五组纯开发检查 | [003729](../evidence/isolation-native-development-contract-20261024-003729-716152.json) | 边界组合检查通过，模拟API只用于开发，不作OS证据 |
| Win32k单变量对照 | [003857](../evidence/isolation-native-development-win32k-contrast-20261024-003857-363890.json) | 实际false仍加载器失败，生产策略未改 |
| Loader debug | [004307](../evidence/isolation-native-development-loader-debug-20261024-004307-642386.json) | 模块basename、退出数字、宿主flags0；不是验收 |
| 系统sort对照 | [004715](../evidence/isolation-native-development-system-startup-20261024-004715-313504.json) | 同码失败，临时copy删除确认 |
| 挂起token实际文件open/close | [005707-file](../evidence/isolation-native-development-token-file-open-20261024-005707-430358.json) | 不读内容、不Resume；宿主身份恢复true |
| 固定环境别名对照 | [005707-env](../evidence/isolation-native-development-environment-alias-20261024-005707-689559.json) | 同码失败 |
| 空desktop字符串对照 | [005708](../evidence/isolation-native-development-empty-desktop-20261024-005708-035678.json) | 同码失败；未调用显式桌面创建/修改API |

相邻的宿主封装开发记录由主对话维护，不能当作Windows worker成功证据：[004910](../evidence/isolation-wrapper-development-20261024-004910-265304.json)、[004948](../evidence/isolation-wrapper-development-20261024-004948-952956.json)、[005105](../evidence/isolation-wrapper-development-20261024-005105-419286.json)。独立历史/当前状态另见[28 · 隔离独立验收](28-isolation-independent-acceptance.md)，本文件不改其期望或原始结果。

## 重现与开发检查

在项目根目录使用既有Windows CPython运行。诊断需要与配置profile相同的真实用户；本轮实际权限运行由主对话完成。不得将这些可信本机诊断入口提供给HTTP、聊天或模型。

```powershell
$nativePython = 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$nativeDevelopmentFiles = (Get-ChildItem -LiteralPath tests/.runs -Filter 'native-development-*.py').FullName
& $nativePython -m py_compile src/windows_isolation.py $nativeDevelopmentFiles
& $nativePython tests/.runs/native-development-contract-20261023.py
& $nativePython tests/.runs/native-development-pe-imports-20261023.py .isolation/runtime-20261012
```

实际语法检查使用捆绑Python，对后端及10个helper逐项列入命令，exit0。上述路径是本机捆绑运行时；其他机器须换成其既有Windows CPython路径。纯开发检查有5组：输出恰好达限及有界存储、六预算拒绝放宽、class46不支持时必须六对照、每一对照结果单独不符均拒绝、支持的class46明确false不可覆盖。初次开发helper自身的ctypes缓冲区构造曾报TypeError；修正的是helper构造方式，此后5组通过，未将该错误伪称业务漏洞或独立失败用例。

其余已运行helper分别为：

- `native-development-lpac-accesscheck-20261023.py`（第三参数指定安全JSON报告路径）。
- `native-development-win32k-contrast-20261023.py`。
- `native-development-loader-debug-20261023.py`。
- `native-development-system-startup-20261023.py`。
- `native-development-token-file-open-20261023.py`。
- `native-development-environment-alias-20261023.py`。
- `native-development-empty-desktop-20261023.py`。

上述均在`tests/.runs/`，除注明者均以`.isolation/runtime-20261012`为唯一参数。`native-development-user-object-access-20261023.py`只完成编译，未运行。

冻结的`src/windows_isolation.py` SHA256：

```text
c5ce270339bc872839c9608ac0d4c21c6da8903735f8db810c499eb15269c948
```

## 当前缺项

没有成功的Windows候选解析或compute_tool，没有恢复并通过Windows攻击脚本，没有隔离状态下的真实三场景业务成功，也没有Windows网络、文件越界、CPU/内存/输出攻击、取消/父退出等完整独立验收。正常失败路径的PID退出/Job0观测不替代这些缺项。不可把配置、token核验、模拟开发检查或另一路线的成果写成Windows沙箱通过；红档仍拒绝。

## 本轮核对的Microsoft主资料

- [TOKEN_INFORMATION_CLASS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)：LPAC忽略ALL_APPLICATION_PACKAGES；TokenIsAppContainer的DWORD语义。
- [DoNotAddAllApplicationPackagesToRestrictions](https://learn.microsoft.com/en-us/windows/win32/com/donotaddallapplicationpackagestorestrictions)：AAP向AppContainer授予默认资源访问。
- [AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)：impersonation token、MAXIMUM_ALLOWED、API返回与AccessStatus区别、owner/group条件。
- [DuplicateToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-duplicatetoken)：源TOKEN_DUPLICATE及结果impersonation token权限。
- [WebView2分发](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution)：AAP/ARAP与`S-1-15-2-1`/`S-1-15-2-2`对应。
- [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)：创建缓解及禁止子进程策略。
- [SYSTEM_CALL_DISABLE_POLICY](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-process_mitigation_system_call_disable_policy)：Win32k、FSCTL位定义。
- [NTSTATUS值](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)：`0xC0000142`为DLL初始化失败，不能单凭此码认定具体模块或根因。
- [Kernel32/User32初始化失败](https://learn.microsoft.com/en-us/troubleshoot/windows/win32/user32-kernel32-not-initialize)：站/桌面安全访问是可能原因；本机尚未证实。
- [GetUserObjectSecurity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getuserobjectsecurity)、[窗口站权限](https://learn.microsoft.com/en-us/windows/win32/winstation/window-station-security-and-access-rights)、[桌面权限](https://learn.microsoft.com/en-us/windows/win32/winstation/desktop-security-and-access-rights)：未运行的只读诊断依据。
- [CreateWindowStationW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createwindowstationw)：命名权限及CREATE_ONLY注意事项；本轮未据此创建对象。

资料支持概念和API用法；实际能力仍以本机原始证据和独立验收为准。

# 29a · Linux Docker 隔离独立验收

状态：第三轮真实验收 33/33 方法通过，0 失败、0 错误、0 skip，262.313 秒。首轮 30/33、第二轮 32/33 及两轮失败原因原样保留。通过范围是本文列明的 Linux Docker 实测，不能改写 Windows 或真人验收状态。

本轮独立作者为单独的验收子代理，只依据 `AGENTS.md`、`src/ISOLATION_API.md`、`src/PUBLIC_API.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`src/DOCKER_ISOLATION_API.md` v2 与队长原任务设计期望；未阅读银行、隔离后端、监控器、worker 或 supervisor 的实现。最初仓库相对 `task1/未命名.md` 不存在；随后已收到并读取实际来源 `C:/Kind_Hermit/Kind_Hermit/task1/未命名.md`。实际 Docker 运行由实现方在获准环境执行，独立作者负责测试与证据判读；这不能替代两位真人队友的人工核验。

旧 Windows LPAC loader 失败、原始 31/41 等证据保持原样。Docker 是新机制，允许容器私有 `/tmp` 的 16 MiB 有界写入，并不是旧 Windows 契约通过。红档仍拒绝执行，不因新隔离验收通过解除。

## 最终结果与复现

第三轮北京时间 2026-10-24 13:09:28.458266 至 13:13:50.767614，真实执行 33 方法及 58 个参数子用例，全通过，0 skip。JSON 中的 91 条 case_result 同时包括方法与参数记录，不能计成 91 个独立方法。原始结果：[第三轮验收 JSON](../evidence/docker-isolation-independent-20261024-050928-458266.json)；外层执行与保护核对：[第三轮 run JSON](../evidence/docker-isolation-run-20261024-050927-718632.json)。外层 exit=0，源码与受保护文件前后均一致；该次版本指纹为 `05b1336afa8cb847d4660ba3a5a404d6d740a0cf841741c86d1128944b7e90cf`。

| 轮次 | 实际方法结果 | 证据耗时 | 原始证据 |
|---|---|---|---|
| 首轮 | 30 通过、2 失败、1 错误；0 skip | 248.625 秒 | [045404-972771](../evidence/docker-isolation-independent-20261024-045404-972771.json) |
| 第二轮 | 32 方法通过；第 18 方法的 3 个子用例失败；0 错误、0 skip | 269.453 秒 | [050142-394790](../evidence/docker-isolation-independent-20261024-050142-394790.json) |
| 第三轮 | 33 方法全通过；0 失败、0 错误、0 skip | 262.313 秒 | [050928-458266](../evidence/docker-isolation-independent-20261024-050928-458266.json) |

最终测试 SHA256：`291a58f283c74dcc2163b3b80e4f33e590d0dcf7825b0c3ea63c84aedfd122fa`；本次 Docker 公开契约 SHA256：`808829fbd41be77bc4ae264d601e71bc14d80017815db06b27d8280dff96f65f`。仅按公开接口调用，作者始终没有阅读业务或隔离实现。既有 159 项业务/MFA/HTTP 等回归由 root 另存证据，不混入这套 33 方法计数，也不将作者身份改写为真人队友验收。

在本机已由可信 setup 准备好 runtime 与本地镜像、具备 Docker 运行权限时，从 `C:/fintechathon` 执行：

```powershell
$env:FINTECH_DOCKER_RUNTIME = 'C:/fintechathon/.isolation/docker-runtime-20261023'
& 'C:/Users/KindHermit/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' 'C:/fintechathon/tests/test_docker_isolation_independent.py'
```

实际是 root 在获准宿主环境执行，独立作者设计测试并检查原始 JSON、公开数据库与外层校验结果。测试只用标准库和公开接口，无真实模型调用、不连真实银行、不动真实资金。

## 最终实测覆盖

| 矩阵组 | 方法 | 本轮真实覆盖 |
|---|---|---|
| D01 | 01、04、20、28 | 固定解析和探针真实启动；proc/cgroup 与 live daemon 交叉核对，33 个必需 policy 检查均 true |
| D02 | 04、06、31 | 宿主假文件读写阳性、worker 越界读写拒绝、假环境秘密与 proxy 不继承、原 stdout/stderr/异常秘密不入回执与监控 |
| D03 | 06、07、20、28 | 宿主路径不可达；rootfs/runtime 拒写；只有专用 runtime 只读/rprivate bind，无业务库或 Docker socket 挂载 |
| D04 | 07–09、20 | `/tmp` 小写入阳性、跨多个文件填满硬 16 MiB 后 ENOSPC、删除后恢复、直接 exec 拒绝，实际 noexec/nosuid/nodev |
| D05 | 11、12、28 | 同目标宿主 IPv4/IPv6 TCP 与 UDP 阳性；worker 不可达；私有 IPv4 loopback 阳性，仅 lo、无外网路由、network none |
| D06 | 10、20、28 | 实际 UID/GID65534、全 caps=0、NoNewPrivs=1、Seccomp=2、私有 namespace/IPC、cgroup/挂载及 daemon 字段 |
| D07 | 10、20 | 总 pids=2/current=2；fork、子进程、线程、提权和新 user namespace 拒绝 |
| D08 | 22、26、29、30 | ACK 后超时、取消不交付早发成功；父死及父死同时终止真实外部 watchdog 后均无 live worker；正常返回删除容器 |
| D09 | 21、30 | PID1 不被同 UID 信号冻结/终止，内存/ptrace/提高其 rlimit 拒绝；内层 deadline 仍工作 |
| D10 | 20、23–25、33 | 实际 CPU 配额/RLIMIT、128 MiB 内存/无额外 swap、daemon OOMKilled、64 KiB 双流限制，及缩紧 64 MiB/19%/4 KiB 实测 |
| D11 | 02、03、32 | 严格 JSON 12 类、输入/任务 7 类、超长输入及非法 limits 27 类均拒绝，不创建非法预算监控库 |
| D12 | 05、31 | 非零、非 JSON、多对象、非有限数、重复键与秘密样式 stderr/异常只交付安全失败回执 |
| D13 | 13–15、18、19 | 日志只追加、禁止 UPDATE/DELETE、started/finished 故障停办不交付、业务故障日志持久化与成功事务回滚 |
| D14 | 16、18、19 | 六工具调用真实 executor，金额与历史正确；未确认不披露/改账，失败不改账、依赖停止、无伪成功日志 |
| D15 | 17 | 合成两因素实际成功后红档仍 rejected/isolation_unavailable，余额、转账不变 |
| D16 | 27、32、33 | 缺配置、业务/监控同库、可读区内业务库、监控硬链接与非法预算 fail closed；实际缩紧预算有效 |

最终 18 的三个新夹具均核对到唯一失败持久日志，包含 alice、非空请求号、对应意图与绿/黄档，event=isolation_failed/result=failed/reason=audit_unavailable；无 executed/success，且后续 failed/audit_unavailable。20 实际观测为 pids 2/2、memory.max=134217728、memory.swap.max=0、cpu.max=20000/100000、RLIMITCPU=1/1；两个 PID scope 都明确为 DockerDesktop Linux VM。28 已完成原失败点之后的环境、挂载与正常清理断言，不只检查布尔标志。

第三轮 sleep 和 CPU 忙循环均在 execution=5000 ms 停止，CPU 单独致死先后仍未证明；内存增长的 `oom_killed=true` 由 daemon 给出，非根据 137 猜测。stdout 与 stderr 各保留有界 65536 字节；提前输出 JSON 后取消仍不交付 data。父死后观察停止为 0.593 秒，父死且外部 watchdog 已确认被杀后为 5.000 秒；stopped 元数据不是 live 进程，随后按已核对名称与三个 label 的不可变 ID 清理。

## 首轮实际结果及问题分类

实际执行者：root 在本人 Windows 用户与真实 DockerDesktop Linux 环境运行独立作者的冻结测试。开始北京时间 2026-10-24 12:54:04.972771，结束 12:58:13.595870；证据总耗时 248.625 秒。原始结果见 [首轮 JSON](../evidence/docker-isolation-independent-20261024-045404-972771.json)，33 方法 30 通过、2 失败、1 错误，未 skip。首轮测试 SHA256：`c0ddf3a6bbcb0d454aa4e4dfda46c0f6b77dd33262560ac32999c678b7894d7a`；原测试另存于 `tests/.runs/docker-isolation-independent-3iagtbei/test-source-first-round-c0ddf3a6.py`，不覆盖其失败。

| 问题 | 输入 / 原期望 | 实际及是否运行 | 独立分类与修订依据 | 验证方法 / 最没把握处 |
|---|---|---|---|---|
| 18 | 同一个 Bank/故障执行器先使取消失败，再期望新转账进入 pending | 真实运行；首个失败后新请求为 failed/audit_unavailable，已停办 | 测试期望冲突。AGENTS 第五节要求审计失败后停止后续业务，不能要求实现恢复生成授权。修订用三个新 Bank/monitor 分别在取消、转账、依赖图的实际执行入口触发故障，随后断言停办 | 每份独立库查余额、订阅、transfers、成功日志与依赖状态；首轮未进入后两个故障入口，因此须复测 |
| 20 | 依公开文档用 `metadata.scope` 核对 Linux PID 范围 | 真实探针成功，原回执只有 `linux_pid_scope`，测试 KeyError scope | 公开接口与回执命名不一致。实现方明确公开别名并补 `scope`；独立测试不猜字段、不将 ERROR 改填通过 | 首轮 probe 的 UID、caps、NoNewPrivs、seccomp、cgroup 与挂载观测已保存，但 ERROR 后未执行的断言仍须重跑 |
| 28 | 将 Healthcheck 整体非空当成仍启用健康检查 | live 容器确实运行并收到独立 ACK；Config.Healthcheck 为 `{"Test":["NONE"]}` | 测试 Docker 语义错误。官方规范中 `["NONE"]` 禁用，空数组才是继承；修订接受显式 NONE，不能为通过删除 `--no-healthcheck` | 再查真实 inspect，继续检查实际环境、挂载、权限与清理。首轮失败处之后的断言未完成，须重跑 |

28 的依据是 [Docker 官方 HEALTHCHECK 文档](https://docs.docker.com/reference/dockerfile/#healthcheck)、[官方容器运行参数](https://docs.docker.com/reference/cli/docker/container/run/) 与 [Moby 官方镜像规范](https://github.com/moby/docker-image-spec/blob/main/spec.md)。它们说明 NONE / `--no-healthcheck` 用于禁用检查；修改测试符合机制语义，不是降低安全要求。

另一个独立测试加严项：首轮辅助函数把 `docker inspect` 非零直接视为对象已删除。修订版要求随后本地 daemon 的 `ps` 查询必须成功且该不可变 ID 确实不存在；daemon 无法查询不能当作已停止。这是验收工具的极端断连判读缺口，首轮没有故意令 daemon 失联，因此不把这一极端路径计为通过。

首轮已保存的实测包括：宿主文件读写阳性与 worker 拒绝、runtime/rootfs 拒写、私有 `/tmp` 16 MiB 多文件填满及恢复/noexec、宿主 IPv4/IPv6 TCP/UDP 阳性与 worker 拒绝、fork/进程/线程/提权拒绝、严格 JSON、追加监控、started/finished 审计失败停办、六工具实际隔离调用、合成双因素后红档仍拒绝，以及业务成功日志故障回滚。六工具结果与公开模拟夹具一致，未用真实银行或真实资金。

资源实验有固定空白 ACK 的摘要，证明不是解释器启动失败：sleep 在 execution=5000 ms 超时；CPU 忙循环同样 timeout，CPU 致死先后**未证实**；内存增长由 daemon `oom_killed=true` 证实且 reason=memory_limit；stdout/stderr 洪流、提前输出成功 JSON 后取消均没有交付成功业务。CPU 累计和峰值内存为 null，未填预算冒充实测。

同 UID 监督者实验中 SIGSTOP/SIGKILL 调用返回成功但信号无效，监督者仍正常，内存、ptrace 和提高其 CPU 限制均被拒绝；不能把系统调用返回成功误当成监督者已被破坏。父进程被杀后 0.625 秒内观察到 worker 停止；父进程和真实外部 Python watchdog 都被终止后，由容器内监督者在 5.000 秒后停止 worker。两次均留下 stopped 元数据而非 live 进程，符合异常退出的公开约定，随后仅清理自己核对标签的容器。上述结果仍受 daemon 可查询的首轮条件限制。

## 修订版冻结

仍为 33 方法；18 增加三个独立故障夹具子用例，28 采用官方禁用语义，20 同时检查公开 `scope` 与 `linux_pid_scope`，33 项 policy 名称作为必需子集，inspect 删除判读加严。修订测试 SHA256：`87697bfb23fc9a262ef8b680ecb8a66f756e31b89f9429d16f549acacf84b891`；自身 Python 语法及 17 个内嵌探针脚本语法检查均通过。这只是准备完成，不能代替真实复测。

## 第二轮与第三版

第二轮原始证据：[20261024-050142-394790 JSON](../evidence/docker-isolation-independent-20261024-050142-394790.json)。真实运行 269.453 秒，33 方法中 32 方法通过；第 18 方法三个子用例均在同一个日志断言失败，unittest 记 3 failures、0 errors、0 skip。第 20 和 28 方法已真实通过，不能只凭对首轮的文字解释替代这一复跑。

18 的余额、订阅、零转账、依赖停止及后续审计停办断言已通过，失败点是测试试图在已停办 Bank 的 `audit_events()` 返回值中查找 `reason=isolation_failed`。独立作者随后只读三份本轮模拟 SQLite 公开表，实际均已追加：`event=isolation_failed, result=failed, reason=audit_unavailable`，分别绑定 alice 的取消、转账和计划首步账单分析，没有 executed/success 日志。这些持久事实未因公开回执为空而消失。

这属于公开回执与持久业务日志语义未明确时的测试假设错误，不能删除持久日志要求来求通过。`src/ISOLATION_API.md` 已明确：失败响应的 reason 为 isolation_failed；业务失败日志的 event 为 isolation_failed、result 为 failed，reason 保存固定底层原因。已停办 Bank 不再读审计存储，`audit_events()` 返回空列表。第三版改为经公开 `audit_log` 表检查事件、结果、底层原因、用户、意图、档位、请求号，以及不存在成功执行日志；仍断言下一请求 failed/audit_unavailable 和停办回执为空。

第三版测试 SHA256：`291a58f283c74dcc2163b3b80e4f33e590d0dcf7825b0c3ea63c84aedfd122fa`，仍为 33 方法，17 个内嵌探针及自身语法检查通过。第二版源码另存于 `tests/.runs/docker-isolation-independent-gjr__2yv/test-source-second-round-87697bfb.py`，前两轮结果均保留。第三版只修必要日志核对和证据版本标记，没有要求生产程序放宽停办条件。

## 冻结前独立期望矩阵

所有文件、数据库、环境值和网络服务均为本轮在 `tests/.runs/docker-isolation-independent-*` 下创建的假数据，不读取日常库或真实模型配置，不发起外网攻击。阳性对照必须先证明相同宿主目标确实可读、可写或可连接；解释器未启动不算攻击被拦截。

| 组 | 独立输入与目标 | 期望与核验方法 |
|---|---|---|
| D01 | 正常固定 JSON 解析及只返回受限探针 JSON | 真实 Linux worker 成功；宿主取得实际身份、预算与退出统计；不能用实现自报的常量替代 Docker/OS 核验 |
| D02 | 宿主假秘密、假账本、假监控库及继承环境/句柄 | 宿主对照可访问，worker 不得读取、改写或继承；日志无原文秘密 |
| D03 | runtime、根文件系统、挂载点、常见宿主路径写入 | runtime/rootfs 只读，只有声明的私有有界区可写；Docker 只挂专用 runtime，不挂整个项目、Docker socket、业务库或宿主 profile |
| D04 | `/tmp` 写小文件、填充超过 16 MiB、删除后重用、执行临时文件 | 小文件成功；容量有硬上限；写满不得影响宿主或下次新容器；noexec/nosuid/nodev 由实际挂载标志和执行拒绝核对 |
| D05 | 宿主 IPv4/IPv6 TCP 监听与 UDP 回显，worker 同目标连接；worker 自己的 loopback | 宿主同目标阳性；worker 不得到达宿主服务；network none 仅私有 loopback，无外网接口/路由；私有 loopback 正常不算漏洞 |
| D06 | uid/gid、能力、no-new-privileges、seccomp、IPC/PID namespace、rootfs/cgroup | 实际身份为 65534，capabilities 全无，安全参数满足冻结契约；以 inspect/容器 OS 数据交叉核对，不信业务回执单一来源 |
| D07 | fork、subprocess、线程和新 namespace | supervisor+worker 已占两 PID 槽，额外任务创建失败；容器不允许从 worker 增权、逃离限制或新增进程 |
| D08 | 正常 sleep、超墙钟、取消、父宿主和外部 watchdog 同时消失 | wall 最多 5 秒加最多 2 秒清理；取消不交付成功；父死后容器可信 deadline 仍终结，无残留 worker；观察真实容器状态 |
| D09 | worker 向 PID1 发信号、改资源限制、访问 PID1 的 proc 文件、企图 ptrace | 同 UID 也不得破坏监督者；其 deadline 和限额仍生效；单独记录信号/ptrace/配置篡改的实际拒绝证据 |
| D10 | CPU 忙循环、内存递增、stdout/stderr 洪流 | CPU 配额 20% 和整秒 1 秒 CPU 限制、内存 128 MiB 且 swap 同值、输出 64 KiB 硬限制；必须先有脚本执行标记，结束后无活动 worker |
| D11 | 输入超 64 KiB、非 dict、额外/缺失字段、非法任务、严格 JSON 边界 | fail closed；重复键、NaN/Infinity、指数溢出、尾随正文、深度超 12 和多对象均拒绝；不执行其他代码、不返回非法数据 |
| D12 | 非零退出、非 JSON、超深 JSON、秘密样式异常/标准错误 | 仅安全回执；无原输入/原 stdout/stderr 或原异常；探针已实际启动的证据保留摘要/标记 |
| D13 | success、失败、取消、未知任务、重启、UPDATE/DELETE、started/finished 注入审计失败 | started 先持久化、finished 后交付；只追加；审计故障停办，started 失败不启动；finished 失败不交付结果；旧记录不改写 |
| D14 | BankService 六工具真实隔离执行、黄档确认前后、失败工具与依赖计划、业务审计失败 | 正常金额/历史符合公开夹具；每个真正执行工具均有 compute_tool 监控；失败无变更、无成功日志、依赖停止；未确认不披露/改账 |
| D15 | 已登记合成 MFA 的红档及黄档并发跨阈值 | 不能凭隔离、屏显码或模型声明执行红档；余额、交易和转账不变，拒绝/失败可追溯 |
| D16 | 配置缺失/不安全、Docker 不可用、监控/业务同文件及容器残留 | 不能降级普通进程；安全参数不满足则拒绝；不能把缺环境 skip 写成通过；无法证明清理时停办并如实列缺项 |

## 首轮范围与未验证边界

公开契约现已明确配置、`/runtime`、33 项 policy 检查、同 package 发现标签、父死停止与正常删除的区别，以及普通 dict 的 limits 约定。首轮实际测试覆盖矩阵中的正常/拒绝、文件和假秘密、私有临时区、IPv4/IPv6 宿主阳性对照、fork/线程/提权、proc/cgroup 与 live inspect 交叉检查、监督者篡改、墙钟/CPU 忙循环/内存/输出、取消、父死及父死同时终止外部 watchdog、严格 JSON、监控与业务两类审计故障、六工具真实 BankService 路径及红档拒绝。探针主体由固定空白 ACK 的摘要或独立 attach 观察验证，不能把 startup 失败记为成功拦截。

CPU 忙循环只按实际 reason 记录安全停止；默认 5 秒执行墙钟包括 start/attach，不能从 timeout 或未知 SIGKILL 推断 RLIMITCPU 先触发。监督者与 worker 各自继承整秒 1 秒限制，容器总 CPU 率由 cgroup 控制。可信 CPU 累计和峰值内存若为空，保持为空。IPv6 对照仅覆盖本机提供的地址族能力，不宣称所有 IPv6 环境均验。

未主动停止整个 Docker daemon，也未篡改专用 runtime 的受信 worker、supervisor 或配置。公开 `run_probe` 由可信宿主把自有探针复制到专用 runtime/tasks，正常返回后删除；这项可信复制确实会写专用 tasks，不能说完全未写 runtime。异常父死留下的测试副本已由 root 以三轮独立 monitor 任务、原探针 SHA 和精确路径双重核对，仅删除 6 个自有副本；独立作者核对[最终清理证据](../evidence/task1-delivery-20261024-051532-259239.json)，剩余探针 0、该 package 容器 0，受保护文件与基线一致，未按通配名清理或碰受信文件、日常库。

daemon 突然完全不可达、清理失败后持久 quarantine 的极端路径仍未实测，不能据正常退出自动勾选。可信 cpu_ms 和 peak_job_memory_bytes 仍为 null；CPU 单独致死因果未证明。初始矩阵还列了宿主原生句柄继承、重启 abandoned、Docker 组合的并发跨阈值等子类；本套未新增对应独立实验，不能把矩阵的设计条目全部当作自动已测。测试不宣称宿主全盘容量、内核漏洞、管理员防篡改、所有系统对象或生产环境已验证。真人手机、真实终端、队友人工验收、正式赛事渠道仍另验，Windows 实验仍未完成，红档继续拒绝。

运行环境由 root 提供：`FINTECH_DOCKER_RUNTIME=C:/fintechathon/.isolation/docker-runtime-20261023`。精确运行入口为捆绑 Python 执行 `tests/test_docker_isolation_independent.py`，每次写入新的 `evidence/docker-isolation-independent-<UTC时间>.json`，不覆盖首次失败。脚本无 skip；缺必要环境或零用例均不能成功退出。

## 结果记录要求

每个用例保存输入类别、期望、实际、安全回执、是否真实运行、宿主阳性对照、验证方法及最没把握处。首轮失败原样保留；修复后另建新证据，不能覆盖失败。只有实际完成的 Docker/OS 实验可写通过，单元替身和配置检查各自标注。

# Docker受限执行公开契约 · v2

**六场景v4接入（2026-10-25）**：系统边界与限制保持v2；新增工具经同一compute_tool受限任务执行，固定纯计算模块six_calculator.py与worker.py/supervisor.py一同复制并列入files_sha256。setup始终新建目录，不覆盖旧runtime；本轮目录`.isolation/docker-runtime-six-20261025-a1`。模块缺失、指纹不符、工具计算失败或结果不符均停止，不回退宿主执行。此处不是新增OS边界全部通过声明，实际验收另存。

这是task1新增可用机制的独立验收依据，不是通过声明。Windows LPAC实验保持未完成，旧31/41项及失败不改写。此机制通过专用runtime配置显式选择，不因另一机制失败而自动切换。

## 入口与信任

共用[src/ISOLATION_API.md](ISOLATION_API.md)的IsolatedExecutor、IsolationError、execute、run_probe、last_receipt、audit_events和BankService接入。白名单、严格JSON、失败不交付data、监控审计、业务核对、取消、硬链接与目录保护继续有效。Docker机制没有AppContainer/profile目录；readable_directories只含专用runtime。Linux进程号不得冒称Windows进程号。

任务来源为`C:/Kind_Hermit/Kind_Hermit/task1/未命名.md`。启动先运行`scripts/docker_isolation_setup.py --runtime-dir .isolation/docker-runtime-20261023 --image python:3.12-slim --docker-executable <本机CLI绝对路径>`。setup只检查本地已下载镜像、复制受信worker与监督者，不自动安装、拉取、登录或更改Docker设置。运行模式仍为`start.ps1 -IsolatedTools -IsolationRuntime .isolation/docker-runtime-20261023 -IsolationMonitor <独立监控库>`。缺本地引擎、镜像或不符限制时失败，不回退普通进程。

runtime内isolation-config.json：policy_version=`docker-linux-readonly-v2`，package_name=`FinTechathon.Worker.<32位hex>`（不表示Windows SID），docker_executable绝对路径及其SHA256，docker_host固定本地`npipe:////./pipe/dockerDesktopLinuxEngine`，docker_config_directory为runtime之外专用空客户端目录，image_id为不可变`sha256:<64hex>`，files_sha256至少包括worker.py/supervisor.py。复制来源是仓库受信固定代码，禁止把模型代码写进去。模型HTTP、密钥、账本、确认、MFA、权限、SQL事务留在Windows宿主，容器不挂载这些内容或Docker控制接口。

execute两任务与payload字段、probe管理员专用、输入/输出预算和审计约定与v1.1相同。固定worker在`/runtime/worker.py`，作者probe在`/runtime/tasks/<32hex>.py`，宿主复制后删除；rootfs与runtime均只读。假秘密及账本放在独立宿主测试目录，不能为了测越界把它们挂入容器。

## 系统强制边界

- 固定镜像ID，`--pull never`。DockerDesktop、Linux内核/daemon、受信镜像及PID1监督者属于可信边界，不宣称抵抗宿主管理员或内核漏洞。
- Docker daemon在start前inspect核对：非特权UID/GID65534:65534，cap-drop ALL且无cap-add，no-new-privileges，默认seccomp，私有PID/UTS/cgroup namespace、IPC none，无host namespaces、额外设备、网络、端口、卷、Docker socket或重启策略。
- 网络为none，仅有容器私有IPv4 loopback。允许进程在自己的loopback通信，不能据此判越界；应验证无法到达宿主及外部网络，并有同目标宿主阳性对照。无IPv6 loopback时如实记录，不推导所有IPv6环境均已验证。[Docker说明](https://docs.docker.com/engine/network/drivers/none/)
- rootfs只读，唯一host bind为整个专用runtime到/runtime，readonly/rprivate。`/tmp`是独立16MiB内存文件系统，rw/noexec/nosuid/nodev，mode1777；允许写隔离临时文件，不能写宿主。每文件fsize软/硬16MiB，IPC none不建立可共享宿主内存。不承诺全虚拟机或宿主磁盘总配额。
- 容器总pids=2：受信Python PID1监督者和唯一不可信worker。公开limits.process_count=1指worker；两个槽占满时，worker不能再fork/thread/创建程序。exec替换自身不增加进程，仍受同一全部边界，不能将exec本身当逃逸。
- 监督者先核对UID/GID、caps=0、NoNewPrivs=1、Seccomp=2、RLIMITCPU=1/1并设置PR_SET_DUMPABLE=0；按固定单调时钟截止时间杀worker。worker不持监督者句柄/秘密、不准改其内存或冻结其计时。PID namespace的init信号规则与独立篡改实验共同验证，不只相信标记。
- 镜像环境只有固定公开默认项（PATH/LANG/GPG_KEY/PYTHON_VERSION/PYTHON_SHA256；GPG_KEY为镜像公开签名指纹），没有宿主模型或用户环境。宿主Docker客户端使用独立空配置和固定本地管道。模型、API密钥、代理凭据、认证器及原始日志不传容器。

## 预算与停止

默认wall_seconds=5，cpu_seconds=1，cpu_rate_percent=20，memory_bytes=134217728（监督者与worker合计）、output_bytes=65536，process_count=1。wall最低0.2，rate最低1，memory最低32MiB，output最低1024，只能缩紧；Linux RLIMITCPU仅整秒，因此cpu_seconds固定1，其他值拒绝。输入UTF8 JSON最多65536字节。

limits是普通Python `dict`或None。可只给需要缩紧的字段，其余取默认。例如`IsolatedExecutor(runtime, monitor, limits={"wall_seconds": 3.0, "memory_bytes": 67108864, "output_bytes": 4096})`。两个seconds字段接受int/float但拒绝bool与非有限数；其余字段只接受int（也拒bool）。Docker的cpu_seconds只接受数值1或1.0，0.5等均拒绝；process_count只能1。未知字段、错类型、越界在构造时抛`IsolationError(reason="invalid_input")`，不开监控库、不启动任务。

CPU率由cgroup硬配额，内存/总swap相同限额由cgroup。RLIMITCPU软硬1秒由监督者及worker分别继承，约束各进程累计CPU，不表示整个容器合计CPU最多1秒；容器总CPU率由cgroup控制。[Docker资源机制](https://docs.docker.com/engine/containers/resource_constraints/) 默认5秒wall和20%配额可能先触发wall；单独的CPU致死原因若未测清，不得由137或wall结果推成已证明CPU先触发。

setup（本地image检查/create/inspect/watchdog握手）有单次命令4秒和setup lease25秒界限，单独记录setup_ms。执行wall从可信外部watchdog ARM、启动attach前计，含start/attach开销；容器内PID1另有自己的同长硬截止。取消约20ms轮询，停止和回收额外最多2秒。达到stdout+stderr上限立即停止，宿主只保留有界前缀。运行完成前不交付早发的成功JSON。

父宿主退出时外部租约watchdog只尝试停止本次标签容器，不与正常清理竞争删除；可能留下已停止的容器元数据供核查，不能声称异常父进程退出后已经删除。即使外部watchdog也消失，容器内PID1仍须在截止后终止worker。daemon不可达不能假称回收完成。正常返回须inspect确认Running=false/Pid=0、attach/收集器退出、删除本次容器；cleanup_complete=false使监控器停办、保留锁并持久隔离该身份，不能继续办理业务。

## 公开监控与独立发现

metadata来自可信daemon与宿主：mechanism，container_name/id、daemon_image_id、daemon_policy_verified、policy_checks，watchdog_armed，container_started、container_running_after、container_pid_after、container_removed、oom_killed、daemon_exit_code、cleanup_complete，setup_ms/execution_ms/cleanup_ms/wall_ms及start/end。CPU累计/峰值尚未从可信daemon取得时cpu_ms和peak_job_memory_bytes为null，不能用预算冒充实测。

pid=null；linux_pid只有运行中inspect实际取得正数时才记录，否则null。metadata.scope及metadata.linux_pid_scope均固定为`docker_desktop_linux_vm`，明确该进程号的范围，不表示实际采到了PID；host_attach_pid和watchdog_pid才是Windows PID。worker_started表示容器已启动，不单独证明probe主体已执行；独立探针用预先约定JSON空白ACK及stdout_sha256确认本体。stdout_sha256/output_bytes与v1.1的有界保留定义相同。

禁用镜像健康检查使用`--no-healthcheck`；daemon的`Config.Healthcheck.Test=["NONE"]`表示禁用，不能因该非空对象误判正在运行健康检查，也不能接受任意非空CMD。[Docker运行选项](https://docs.docker.com/reference/cli/docker/container/run/)、[HEALTHCHECK NONE](https://docs.docker.com/reference/dockerfile/#healthcheck)

容器名`fintech-worker-<32hex>`。三个labels：`com.fintechathon.isolation=docker-linux-readonly-v2`、`com.fintechathon.package=<runtime package_name>`、`com.fintechathon.task=<容器名hex后缀>`。可信测试者可用本地CLI ps/inspect/top/attach --no-stdin --sig-proxy=false发现自己的正在运行任务，不访问其他标签容器。所有kill/rm须先核对名称及三个label，再用不可变64hex ID，不能按通配名清理。

policy_checks为字段到布尔映射，全部为true才能start：owned_identity、pinned_image、not_started、non_root、fixed_entrypoint、fixed_arguments、no_host_environment、fixed_workdir、no_network、read_only_root、no_capabilities、no_new_privileges、no_privileged、one_supervisor_one_worker、memory、cpu_rate、cpu_seconds、file_size、private_namespaces、no_host_cgroup、no_extra_resources、no_published_ports、no_logs、tmpfs、no_healthcheck、no_automatic_restart、stdin_only、runtime_mount、requested_mount、default_linux_runtime、no_supplementary_groups、oom_kill_enabled、no_automatic_remove。独立作者须另查真实token/proc/cgroup或daemon字段/实际攻击，不能只信这些布尔。

reason延用固定集合：ok、invalid_task/input/output、isolation_unavailable、start_failed、identity_mismatch、timeout、memory_limit、output_limit、cancelled、nonzero_exit、audit_unavailable等。只有daemon OOMKilled才归因memory_limit；可信PID1超时退出124可归因timeout，worker自己的任何非零退出由监督者映射1，不能伪造124。未知SIGKILL不捏造CPU/OOM原因。

首轮、新机制复测、离线开发检查、独立证据分别保留。不代表Windows LPAC、真人MFA、正式渠道或全部系统对象通过；红档继续拒绝。不部署、不公开、不接真实银行或真实资金。

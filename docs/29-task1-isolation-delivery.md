# 29 · task1受限执行阶段交付记录

更新：2026-10-23（会话日期，America/Denver）。原始证据自带UTC或北京时间`+08:00`，部分文件日期已为10月24日。**task1在本机Docker机制及下述明确边界内完成：独立33方法通过，原159项回归通过，红档仍拒绝。** Windows、极端daemon失联及真人缺项未因此改为通过。

封存源码指纹：`05b1336afa8cb847d4660ba3a5a404d6d740a0cf841741c86d1128944b7e90cf`；[逐文件版本、保护指纹和环境](../evidence/task1-delivery-20261024-051532-259239.json)。后续task2会继续修改工作区，应按该证据查看task1受测版本，不能把旧结果冒称新版本已验。

任务依据：`C:/Kind_Hermit/Kind_Hermit/task1/未命名.md`、当前AGENTS、业务规则与[公开接口](../src/DOCKER_ISOLATION_API.md)。旧docs/24—26及旧源码包保留，没有重新封包。全部银行操作使用新建模拟库，没有连接真实银行、转移真实资金、解锁红档、部署或公开仓库；本阶段尚未新增真实模型调用。

## 实际运行能力与边界

宿主保留模型HTTP与本机密钥、账本、权限、确认、MFA、固定SQL事务和审计。固定worker只接收本次最少数据，解析候选JSON或计算六个工具结果；宿主重新核对输出，才能提交业务。模型或worker输出不能授权。

Docker机制显式选择`docker-linux-readonly-v2`。使用本机Docker Desktop Linux引擎、固定官方Python镜像ID；容器非root、所有capabilities移除、no-new-privileges、默认seccomp、私有命名空间、无网络。根文件系统与专用runtime只读；独立`/tmp`最多16MiB，noexec/nosuid/nodev。只有监督者与唯一worker两个进程槽。资源预算由真实cgroup/rlimit及宿主、容器内双重截止实施，启动前从daemon核对33项设置。精确预算、允许范围及失效处理见公开契约。

正常返回须确认进程停止并删除本次容器，才交付结果。父宿主异常退出时，外部watchdog尝试停止容器，可能保留已停止元数据；容器内监督者仍有硬截止。不能确认清理时停办并隔离该runtime身份，不能靠重启掩盖。监控审计先started、后finished，日志失败不交付成功结果；业务修改及成功日志在宿主同事务。

不承诺内核漏洞、宿主管理员、全虚拟机磁盘总配额、所有系统对象或生产级银行安全。CPU累计与峰值内存没有可信实测值时保持null；不能把预算当实测值，也不能由137退出猜测CPU或OOM原因。Windows PID与Docker虚拟机内Linux PID分开标明。

## 本机配置与启动

已准备的本机专用runtime：`C:/fintechathon/.isolation/docker-runtime-20261023`，其客户端配置目录独立且为空。配置内记录Docker客户端逐字节指纹、worker/监督者指纹与不可变镜像ID：

`sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`

新机器先自行安装、启动Docker Desktop Linux引擎并下载官方`python:3.12-slim`，再执行以下准备命令。脚本只检查本地镜像、生成新专用目录，不安装、拉取、登录或改变Docker设置。新机器所得镜像指纹须另行记录，不冒称复现了上述本机版本。

```powershell
Set-Location C:\fintechathon
$Python = 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$Docker = 'C:\Users\KindHermit\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
# 已存在的已准备目录不用重复创建；为新环境选择不存在的专用目录。
& $Python scripts/docker_isolation_setup.py --runtime-dir .isolation/docker-runtime-new --docker-executable $Docker --image python:3.12-slim
# 使用本机已准备runtime，在新的模拟账本启动；去掉-Web可运行CLI。
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Web -DatabasePath tests/.runs/isolated-demo.db -IsolatedTools -IsolationRuntime .isolation/docker-runtime-20261023 -IsolationMonitor .isolation/demo-monitor.db
```

需以能访问本机Docker管道的本人用户运行。选择隔离模式而配置不符或引擎不可用时拒绝，不自动回退；不带`-IsolatedTools`的历史入口仍是原可信宿主执行方式，不能称已隔离。演示库与监控库须分离，均不能放在worker可读runtime内。

## 已运行证据与待验收

| 类型 | 实际结果 | 原始证据 |
|---|---|---|
| Windows开发与原31项独立首轮 | worker初始化失败；0个成功worker。旧失败保留，后续41项尚未运行 | [27a](27a-windows-isolation-development.md)、[28](28-isolation-independent-acceptance.md) |
| Docker实际daemon配置检查 | 创建后未启动，查看真实配置后删除 | [原始inspect](../evidence/docker-development-backend-inspect-bb72b3cdfcff48a69a37b7c45cc5c6d4.json) |
| Docker最小解析 | 真实worker成功、清理完整；实现方检查 | [parse](../evidence/docker-development-backend-parse-7fd83f9b549a48d8bf990e982889af82.json) |
| Docker六工具、确认及账本 | 7次worker任务成功：解析及六个工具；14条监控事件。账单5970分，取消视频保留历史，模拟转账10000分一次，余额990000/500000/110000分 | [六工具原始回执](../evidence/docker-bank-development-12ec60e70efd4b76b45c616c9370edca.json) |
| 监控器开发检查 | 本人用户21项通过；使用替身和真实SQLite/锁/线程/硬链接，不是OS攻击证据。此前夹具重用21错误与受限用户2权限错误另存，未覆盖 | [21项](../evidence/isolation-wrapper-development-20261024-005105-419286.json) |
| CLI隔离入口 | 实际Docker工具成功；缺runtime退出1且未创建业务库。模型构造被测试替身禁用，未读本机模型配置，不是自然语言/真实模型证据 | [入口开发检查](../evidence/docker-entry-development-d747acc2e0b5479d920b6c493c545e68.json) |
| Docker独立首轮 | 33方法，30通过、2失败、1错误、0skip，248.625秒。故障后停办与禁用健康检查两项为独立作者确认的测试问题；scope字段不一致已补兼容，原始失败保留 | [首轮](../evidence/docker-isolation-independent-20261024-045404-972771.json)、[独立报告29a](29a-docker-isolation-independent-acceptance.md) |
| Docker独立第二轮 | 33方法，32通过、1方法含3个子用例失败，0错误/skip。剩余断言误把响应reason当日志reason、从停办的在线接口读日志；独立作者直接核对公开模拟表，日志实际已保存，业务未变化 | [第二轮](../evidence/docker-isolation-independent-20261024-050142-394790.json) |
| Docker独立最终复测 | **33方法通过，0失败/错误/skip，262.313秒**。另58个参数子用例不混计为方法。实际proc/cgroup、live inspect、攻击主体ACK、故障后持久日志及资金/历史核对均完成 | [原始独立结果](../evidence/docker-isolation-independent-20261024-050928-458266.json)、[输出/版本/保护快照](../evidence/docker-isolation-run-20261024-050927-718632.json) |
| 原159项回归 | **全部通过，0失败/错误/skip**，运行前后源码与保护文件指纹相同。与最终Docker受测版本只差新增Docker测试18的断言修订，全部生产源码及原159用例相同，封存记录已逐文件核对 | [最终回归](../evidence/isolation-regression-20261024-130142-276526.json)、[先前通过](../evidence/isolation-regression-20261024-125525-774099.json)、[首轮临时目录权限错误](../evidence/isolation-regression-20261024-125416-012346.json) |

复测命令：`python scripts/docker_isolation_check.py --runtime .isolation/docker-runtime-20261023`与`python scripts/isolation_check.py`。两种专项分别记录，不合并成“192项均证明OS隔离”。监控/业务日志分库，不冒称跨库原子事务。异常父死留下的6个探针副本已按独立监控task_id及原探针SHA双重核对删除，最终该身份容器数0、runtime/tasks探针数0；没有按通配方式清理其他容器或文件。

仍未主动令整个daemon失联，不能声称极端清理失败后的持久quarantine已经OS实测。CPU忙循环安全停止已测，默认预算下常先触发wall；单独CPU累计致死因果与可信CPU/峰值数值没有完成采集。镜像、Docker/WSL内核及监督者仍属于可信边界；安装/配置变化须重新准备配置及验收。

真人手机、真实终端、队友人工验收继续延期；红档继续拒绝。task2持久计划/恢复与task3复杂上下文仍待按序实现，不能因本文件的Docker开发检查改为完成。

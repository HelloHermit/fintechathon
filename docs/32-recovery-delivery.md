# 32 · task2 状态保存、恢复与本地接管交付

本阶段已完成公开规则内的持久任务、重新授权、故障恢复轨迹及本地接管登记。最终独立 37 项、既有功能 159 项、复用的真实 Docker 银行接入 4 项均通过。**已提交业务不会自动撤销；登记或关闭接管事项不代表退款、订阅恢复或银行人工处理完成。红档继续拒绝。**

记录日期为 2026-10-23（America/Denver）；原始证据分别使用 UTC 的 2026-10-24 或北京时间 `+08:00`。任务依据为 `C:/Kind_Hermit/Kind_Hermit/task2/未命名.md`、当前 AGENTS、业务规则及[公开恢复契约](../src/RECOVERY_API.md)。本文由实现方汇总；独立作者的范围、判读与失败历史见 [31 · 独立验收](31-recovery-independent-acceptance.md)。同目录 GEO／博文杯历史材料没有作为本项目开发指令。

## 1. 冻结版本及保护文件

task2 阶段源码／测试指纹为：

`f0c0b2ac42e7643d20602ecb84d0c196390dd68b78283c3ce9f9946543ffcb68`

[最终阶段清单](../evidence/task2-delivery-20261024-054946-227517.json)于 `2026-10-24T05:49:46.227517+00:00` 保存逐文件 SHA-256、各份报告指纹及保护文件指纹。37 项、159 项和 Docker 4 项各自运行前后源码指纹相同，且与该清单严格一致。此指纹描述本阶段工作区快照；后续 task3 修改属于新版本，不能把本报告的结果当成未经复测的新版本结论。

日常账本没有被连接、查询或重置，仅比较文件 SHA-256。`data/bank.db` 及三份旧 ZIP 与继续开发前的基线一致，详见清单的 `protected_hashes` 和 `protected_equal_continuation_baseline`。本阶段未重新封包、提交 Git、push、部署或公开仓库，真实模型调用为 0。

CLI 和浏览器开发报告没有内嵌源码指纹，依据是在同一 task2 生产代码冻结期间执行；最终清单保存其文件指纹并明确标为 `execution during frozen task2 production interval`。它们不能冒充各自独立采集了源码前后指纹的证据。

## 2. 实际实现与数据边界

| 能力 | 本阶段实际行为 |
|---|---|
| 保存计划 | 合法的最多 8 步依赖图先可靠保存，再运行首节点；保留节点顺序、依赖、明确参数、每次请求尝试及实际结果。 |
| 历史读取 | `list_plans/get_plan` 只读本人安全快照；历史查询结果标明没有重新查询。查看未执行的订阅节点不会读取订阅列表。 |
| 重启停办 | 已成功结果保留；旧 pending 请求作废，保留尝试历史和重启关联审计；不自动补跑未执行节点。验证失败计数和锁定保持。 |
| 恢复核对 | `prepare_recovery` 重新读取当前归属、余额、真实联系人映射、上海执行日累计、订阅状态、依赖及红档条件，展示目标、金额、影响和期限。历史计划自身不是授权。 |
| 固定同意 | `confirm_recovery` 只保存本次恢复许可，不执行业务。必须再显式 `resume_plan`；黄档节点产生新 request_id 和自己的新确认，恢复码不能代替节点确认。 |
| 失效与竞争 | 审核绑定可信用户、计划版本和展示事实，5 分钟有效；新任务、取消、中断、接管、重启、到期或绑定变化会失效。事务内复检版本，指定竞争下只允许一份有效办理。 |
| 取消 | 没有节点 pending 时也能取消当前恢复审核、已同意许可或 ready 余项；计划变为 blocked，旧许可不能续办。已提交结果保留，以后办理须另建任务。 |
| 本地接管 | `takeover_plan` 实际创建持久事项；列表、详情和 `record_handover` 能追加处置、关闭本地登记，重启后仍可查。处理者取可信会话的任务所有者，不是银行员工身份。 |
| 损坏隔离 | 坏 JSON、缺节点、错误类型、环或错用户记录拒绝执行并标为 corrupt；保留原记录，其他健康计划和账本可用。不声称自动修复任意损坏数据库。 |

实现位于 `src/bank.py`、`src/storage.py`、`src/recovery_state.py`。新增 `recovery_plans` 保存当前安全快照，`recovery_handovers` 保存事项，`recovery_handover_entries` 保存只追加处置。原 `requests` 增加 plan／step 关联及实际结果，`audit_log` 增加可空 plan_id；审计及处置历史仍有禁止更新／删除的触发器。快照可更新当前状态，但不能删掉旧 attempts 或处置历史。

确认码、恢复码只留在当前会话内存和当次 pending 展示中，不存入数据库、审计或历史响应。备注含认证标记、已知秘密或验证码形态时整体省略；不交给模型解释或执行。所有账户、联系人、订阅及资金行为均为模拟数据。

业务提交、请求终结、节点成功结果和成功审计在同一 SQLite 事务保存。提交前故障整体回滚；提交后即使响应未送达，也保留真实成功事实，不能再次扣款。审计不可用时停办，不声称未可靠保存的许可、取消或处置已经完成。公开测试故障点仅供可信 Python 注入，不开放到 CLI 或 HTTP。

## 3. 故障恢复及补偿的实际轨迹

独立夹具使用上海 `2026-10-23T10:00:00+08:00` 时钟；alice-main／alice-savings／bob-main 初始分别为 1000000／500000／100000 分，本月实际账单为 5970 分。指定图为 `bill -> pay(10000分) -> subs`。每组使用自己的临时库，不共享日常账本。

| 实际故障／动作 | 已观察到的结果 |
|---|---|
| pay 提交前真实 `os._exit(71)` | 父进程重开同库后余额仍为初始值，成功转账 0、流水 7 条；未提交业务、确认消费、成功日志及节点成功一起回滚。 |
| pay 提交后、响应前真实 `os._exit(72)` | 重启读到 990000／500000／110000 分，原 10000 分成功一次、流水 9 条；恢复不会重做该 pay。 |
| 新恢复同意、尚未继续 | 资金和流水不变；只有显式继续后才建立新黄档请求，新节点确认后才转账。 |
| 提交前回调正常返回时恰好到期／超期 | expired；业务及 confirmed／executed 记录回滚，request／step／attempt 一致过期，原 2 次验证失败保留。 |
| 准备后、同意后或已恢复 pay 成功后取消 | 计划 interrupted／blocked／user_cancelled，无未决请求；旧审核不能续办，未执行后继保持未执行。已成功 pay 只保留一次，没有反向流水。 |
| 接管、登记、刷新、关闭登记 | 事项和两条追加处置保留；成功资金不变。closed_record 只表示本地记录关闭。 |

上述提交前／后进程结果来自独立 R-09／R-10，不是用 close 后重建对象代替真实退出。独立 R-13 两个竞争者中一个被拒绝，另一个获新许可并完成唯一一次转账；这证明该指定竞争下的幂等，不代表生产并发吞吐量已经验证。

成功转账不能自动反向划款；已取消订阅不能自动恢复；历史账单不能删除。取消 sub-video 后仍保留本月已发生 5970 分，未来预计为 2980 分。处置只允许 `manual_follow_up` 或 `no_compensation_needed`，不执行金融工具。恢复订阅、退款等新业务的权限、确认、审计、幂等和费用／平台影响尚未定规则，仍拒绝，六项工具白名单未扩大。

## 4. 独立测试、首轮问题及复测

独立作者先读需求和公开契约、冻结 37 组期望后编写测试，未读业务实现。根执行原测试，独立作者读取原始结果判读。每轮保留新报告及当时测试源码，没有覆盖首轮失败或降低安全期望。

| 轮次 | 实际结果 | 原始执行证据 |
|---|---|---|
| 首轮 | 37 方法；1 failure、36 errors、0 skip；外层 26.656 秒，exit 1。不记为 36 项通过。 | [执行记录](../evidence/recovery-run-20261024-051840-665038.json)、[独立原件](../evidence/recovery-independent-20261024T051841529277Z-9d6c47ef10.json) |
| 第二轮 | 37 全通过，失败／错误／skip 均 0；独立脚本 23.235 秒，外层 24.500 秒，exit 0。 | [执行记录](../evidence/recovery-run-20261024-052123-584424.json)、[独立原件](../evidence/recovery-independent-20261024T052124383310Z-90cb5b1cb4.json) |
| 第三轮 | 加 R-05 提交前恰好到期及超过 1 秒两个子例；37 全通过，脚本 25.672 秒，外层 27.172 秒，exit 0。 | [执行记录](../evidence/recovery-run-20261024-052837-361981.json)、[独立原件](../evidence/recovery-independent-20261024T052838249618Z-157bc82534.json) |
| 第四轮／最终 | 加 R-14 三阶段 × 固定取消／自然语言取消共 6 子例；37 全通过，失败／错误／skip 均 0，脚本 27.953 秒，外层 29.703 秒，exit 0。 | [执行记录](../evidence/recovery-run-20261024-053651-049133.json)、[独立原件](../evidence/recovery-independent-20261024T053651853018Z-9078e8549c.json) |

首轮 36 errors 来自独立测试观察／夹具连接未及时关闭：`with sqlite3.connect` 只结束事务，Windows 清理临时库遇到 WinError 32。原作者改为显式关闭连接，保留原断言。R-18 另有真实接口差异：bob 对 alice 的恢复审核被拒绝，但原因码是 invalid_recovery_confirmation，公开规则要求对未知／他人统一 not_found_or_not_owned。实现已统一回执；首轮不支持宣称发生资金越权或信息泄漏。

第二轮后，开发者使用公开 `node_before_commit` 和注入时钟发现回调结束后缺少最后期限复检；修前观察在 `tests/.runs/task2-backend-stage/expiry-checkpoint-2zu7m_7p/observation.json`，原样保留。修后开发者对转账、订阅查询、取消订阅分别测试期限前 1 微秒／相等／后 1 微秒，[9 例开发检查通过](../evidence/recovery-expiry-development-20261024-052633-076791.json)。随后原独立作者增加 R-05 子例并实际通过。**该缺陷由开发者发现，不能写成独立作者修前已复现。**

第三轮后，开发者发现无业务节点 pending 时，cancel 返回 no_pending，但旧恢复审核仍能授权；修前原件为 `tests/.runs/task2-backend-stage/recovery-cancel-s_ky54wu/observation.json`。按原契约“取消使恢复许可失效”修复，[9 例取消开发检查通过](../evidence/recovery-cancel-development-20261024-053316-064904.json)，涵盖审核、许可、原／恢复后 ready、自然取消、显式节点、未知编号及审计回滚。原独立作者另加 R-14 六子例，第四轮通过；这同样不是独立作者修前发现或复现的失败。

最终测试源码 SHA-256 为 `e34ef950537004795e63dd16c3e8d074e59367656d935738ed6e741b8119a265`。37 方法覆盖真实进程退出、竞争、旧码和到期、锁定、归属／余额／累计变化、依赖失败、审计故障、损坏记录、秘密脱敏、接管及七条新 HTTP 路由的来源／CSRF／字段守卫；子例不额外算成新的方法数。

## 5. 同版本回归及真实入口核对

| 验证 | 实际结果及范围 | 证据 |
|---|---|---|
| 原有功能回归 | 159 方法全部通过，失败／错误／skip 均 0，exit 0；unittest 234.176 秒，外层耗时 235.610 秒。源码及保护文件前后相同。 | [最终 159 记录](../evidence/isolation-regression-20261024-133649-442891.json)及同名 txt |
| 真实 Docker 银行接入复测 | 复用原独立作者的 4 个方法，0 失败／错误／skip，35.844 秒；六工具实际调用执行器、合成两因素后红档仍拒绝、执行监控失败停办／依赖停止、业务审计故障回滚。 | [4 项原始记录](../evidence/recovery-docker-integration-20261024-054252-282366.json) |
| CLI 实际进程 | 管道输入驱动同一个 BankService 的历史／恢复／新确认／接管登记关闭，exit 0；10000 分转账一次，余额 990000／500000／110000，事项 closed_record、两条处置；模型调用 0，证据未保存码。 | [CLI 开发记录](../evidence/recovery-cli-development-20261024-054213-919360.json) |
| 浏览器全流程 | 已安装 Chrome 的 Playwright 实际打开本机页；核对、保存恢复同意、显式继续、新黄档确认后才转账一次，接管登记、刷新及关闭仍保留资金；1440×1000 和 390×844 视口检查通过。 | [全流程报告](C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44/recovery-ui-2026-10-24T05-43-10-183Z/recovery-ui-report.json) |
| 浏览器取消专项 | 点击无业务 pending 时的取消恢复控件，资金／流水不变；刷新后仍 blocked。 | [取消专项报告](C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44/recovery-ui-2026-10-24T05-38-04-807Z/recovery-ui-report.json) |

Docker 4 项是接入子集复用，不是对全部 OS 隔离边界重跑的新结论；完整 task1 范围及未证边界继续引用 [29 · task1 交付](29-task1-isolation-delivery.md)。本阶段没有把 Windows 失败机制改写为通过。

浏览器测试使用离线模型依赖和新模拟库。Browser 插件当时不可用，实际采用随附 Playwright 和已安装 Chrome；报告无 pageErrors，唯一 console error 是未提供 favicon 的 404。它是实现方页面核对，不是独立浏览器作者或真人验收。390 视口不代表真人手机。CLI 管道输入不证明真实终端无回显或手机 MFA。三张页面证据为[恢复核对](C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44/recovery-ui-2026-10-24T05-43-10-183Z/recovery-ui-review.png)、[办理后记录](C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44/recovery-ui-2026-10-24T05-43-10-183Z/recovery-ui-after.png)、[窄视口](C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44/recovery-ui-2026-10-24T05-43-10-183Z/recovery-ui-mobile.png)，位于本机可视化目录，未另行打包。

## 6. 启动与操作

选择自己的专用模拟库。CLI 管理已保存任务；新建空库显示空历史是正常现象，不能据此声称已经有可恢复任务。不要用下面的示例覆盖日常账本。

```powershell
Set-Location C:\fintechathon
$Python = 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -B -X utf8 scripts/recovery.py --help
& $Python -B -X utf8 scripts/recovery.py --db tests/.runs/recovery-demo.db --user alice
```

同一进程输入：`历史`、`查看 <任务编号>`、`核对恢复 <任务编号>`；核对完整展示后用固定格式 `确认恢复 <核对编号> <本次屏显码>` 保存同意，再输入 `继续 <任务编号>`。黄档仍需 `确认 <新操作编号> <新屏显码>`。`取消` 停当前恢复轮次或待继续余项；`接管 <任务编号>`、`事项`、`查看事项 <事项编号>`、`登记 <事项编号> 仍需人工 [备注]`、`关闭事项 <事项编号> 仍需人工 [备注]` 提供实际本地处置入口。重新启动会使旧许可失效。CLI 不构造模型、不需要模型密钥，没有密码或动态码输入入口。

网页使用同一专用库：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Web -DatabasePath tests/.runs/recovery-demo.db
```

页面提供历史任务／详情、恢复核对、固定同意、继续、新黄档确认，以及接管队列／登记／关闭和取消控件；没有自动点击同意或继续。新 HTTP 路由沿用来源、Host、CSRF、重复键和额外字段检查；非法网络请求不会消费当前确认。模型只影响新增自然语言候选，历史办理使用固定接口。网页的自然语言部分如需真实模型，仍须另有合法本机模型配置，本阶段没有调用它。

使用已准备的真实 Docker 模式时，CLI 完整示例为：

```powershell
& $Python -B -X utf8 scripts/recovery.py --db tests/.runs/recovery-demo.db --user alice --isolated-tools --isolation-runtime .isolation/docker-runtime-20261023 --isolation-monitor .isolation/recovery-demo-monitor.db
```

需本人可访问本机 Docker Linux 管道；runtime、业务库与监控库分离，不能把账本放进 worker 可读目录。没有显式选择隔离的历史模式不能称为受限执行；隔离配置失败不会回退普通执行。配置及精确边界见 [Docker 公开接口](../src/DOCKER_ISOLATION_API.md)。

可用以下命令在当前工作区生成新验收证据；后续代码有变化时应按新指纹解释，不替换本阶段原件：

```powershell
& $Python -B -X utf8 scripts/stage_check.py --stage recovery
& $Python -B -X utf8 scripts/isolation_check.py
```

## 7. 明确保留的缺项

本阶段交付的是可运行的持久任务、受控恢复和本人本地事项登记。没有自动逆向转账、退款、恢复订阅、完整可逆补偿或真实银行／平台员工身份及渠道。没有把所有者关闭登记写成已经完成线下处理。

真人手机、真实终端、两位队友人工核验及正式赛事／渠道认可继续延期，按队长有空再做，不替填通过。task1 的 daemon 失联／隔离身份 quarantine 等尚未实测边界、CPU 单独致死原因和 Windows 运行失败状态不因本阶段接入测试而消失。task3 复杂上下文及通用规划属于下一阶段，本报告不预填它的实现或真实模型结果。

截止仍按队长确认的 2026-11-02 推进；旧 10-11 冻结／内部验收节点不是本阶段期限。红档整体条件（含真人因素、终端及正式核验）未全部满足，本轮继续拒绝，包括合成身份因素代码校验通过的情形。

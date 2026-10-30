# 任务保存、恢复与接管公开契约（task2）

**六场景v4扩展（2026-10-25）**：[SIX_SCENARIO_API.md](SIX_SCENARIO_API.md)新增16意图进入同一静态计划、请求与恢复流程，原最多8步、真实事务、恢复三动作及新黄档确认均保留。恢复核对新增预算剩余/日期、服务固定价、卡状态/限额、来源可用余额和统一日累计；已提交的卡申请/限额、预算/订单进入committed_effects。取消不会退款/反转或自动释放预算；释放剩余须另建黄档请求。仅支持计划接纳时已存在的预算/卡，不支持$ref或尚未创建对象。

冻结日期：2026-10-23（会话日期）。**本文件是待实现的接口设计，不是完成报告；本文件作者未读业务实现、未运行测试。** 独立期望来自 `docs/30-recovery-acceptance-matrix.md`，不得按实现结果倒改期望。按 2026-11-02 推进；真人手机、真实终端及队友人工核验仍延期，红档继续拒绝，包括合成 MFA 验证通过的情形。

依据：任务 2 原文 `C:/Kind_Hermit/Kind_Hermit/task2/未命名.md`、`AGENTS.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`src/PUBLIC_API.md`、`src/WEB_API.md`。只补齐本阶段缺项；其余业务规则、六项意图白名单、原有方法签名及响应主字段继续有效。此处“接管”是当前可信任务所有者可操作的本地事项登记，不宣称已有银行人工渠道、客服身份认证或真人处理完成。

## 1. 必须保留的事实和边界

1. 合法计划首次可靠保存后才能执行首节点。业务提交、请求终结、节点成功结果和成功审计必须在同一 SQLite 事务保存。提交前失败全部回滚；提交后即使没有发回响应，成功结果仍保留且不能重做。
2. 重启只使该用户未完成授权失效并保存重启事件，不推进任何节点。已完成结果、失败原因、未执行节点、全部依赖、锁定计数和原审计保留。查看历史不重新运行查询或业务。
3. 历史计划不构成授权。重新办理先展示当前事实，再通过固定恢复同意入口；黄档业务还须新请求的 `confirm`。保存过的 MFA 元数据、旧确认码、模型的“继续”均不能代替新授权。
4. 本阶段不新增恢复订阅、退款、逆向转账或日志修改工具。已成功转账保持原资金及流水；已取消订阅保持取消、历史账单保持。补偿记录只允许 `manual_follow_up` 或 `no_compensation_needed`，都不改变银行业务状态。
5. 审计或任务保存不可用时停止办理。不能报告未保存的恢复许可、中断或接管已可靠完成，也不能因故障写不进日志而继续业务。先前已提交结果仍须如实说明。

## 2. 持久计划与只读响应

新增方法均在 `BankService`，身份只取构造时的可信 `user_id`，不接受调用参数／JSON／模型声明的身份。现有 `propose`、`confirm`、`resume_plan`、`interrupt_plan`、`takeover_plan`、`cancel` 保持调用方式。

| 方法 | 行为 |
|---|---|
| `list_plans()` | 只列本人历史计划，按创建时间、plan_id 稳定排序；返回 `status=success,data.plans`。不返回确认码，不推进节点。 |
| `get_plan(plan_id)` | 返回本人完整安全快照，`status=success,plan_id,plan`；读取也追加查看审计，审计不可用返回 failed。 |
| `prepare_recovery(plan_id)` | 见第 3 节；只准备核对内容，不执行业务。 |
| `confirm_recovery(review_id, recovery_code)` | 固定恢复同意入口；只保存许可，不执行节点，之后显式调用 `resume_plan`。 |
| `list_handovers()` / `get_handover(handover_id)` | 本人接管事项列表／详情，返回 `data.handovers`／`data.handover`；不办理业务。 |
| `record_handover(handover_id, disposition, compensation, note="")` | 追加本人处置，规则见第 4 节；不执行金融工具。 |

公开 ID 均为 1～128 个 ASCII 字母、数字、`-`、`_`；bool、null、数字、空字符串及其他格式拒绝。对不存在及他人的 ID 统一 `rejected/not_found_or_not_owned`，不返回归属、节点、参数或结果。正常终态重放可返回明确幂等回执，不生成新的可执行请求。新接口不接收文件路径、SQL、工具名或任意执行代码。

`plan` 至少含：

| 字段 | 约定 |
|---|---|
| `plan_id,user_id,created_at,updated_at,revision` | ID、可信所有者、带时区时间及正整数版本；只读查看不改 revision。 |
| `status` | 沿用 `ready/waiting_confirmation/success/failed/interrupted/human_takeover`。损坏项见下方独立字段，不冒充成功。 |
| `recovery_status` | `none/required/review_pending/authorized/blocked/corrupt`；不替代真实节点状态。 |
| `stop_reason` | 如 `session_restarted/user_interrupted/dependency_failed/superseded_by_new_task/audit_unavailable`，不存在时为 null。 |
| `steps` | 原顺序列表；每项有 `id,intent,params,depends_on,request_id,status,result,reason,attempts`。原节点状态枚举保留。 |
| `attempts` | 每次尝试的 `request_id,status,reason,created_at,finished_at,result`；失败／失效尝试保留，新尝试不能覆盖旧事实。尚无请求时为 []。 |
| `completed_steps,remaining_steps` | 步骤 ID 列表；仅实际 success 属于 completed，剩余不表示一定可自动恢复。 |
| `committed_effects,manual_actions` | 安全事实摘要；转账含原请求、整数分金额、目标及已提交；退订含订阅 ID 及本地状态。不写“全部撤销”。 |
| `handover_id` | 无事项时 null；存在时关联第 4 节。 |

安全 `result` 只保留已有白名单工具的脱敏实际结果，成功时为该工具响应中的 `data`（例如 bill 的 `result.actual_expense_cents=5970`）；未执行订阅查询的节点不得因预览／查看而读取或返回订阅列表。已经合法完成的本人查询可显示当时结果快照，并标为“历史结果，未重新查询”。默认日期等关键参数须在实际请求建立／恢复展示时解析为明确值；不能把保存的 `{}` 当作跨期执行的固定事实。计划已可靠保存而后续节点失败时，失败响应仍带原 plan_id，便于查询真实轨迹。

重启时原 pending 请求终结为 `cancelled/reason=session_restarted`；相应节点显示 `cancelled`，attempts 保留它曾 pending 及失效原因。历史失败／过期保留原状态；成功节点保持 success；未开始节点保持 not_started。未完成计划进入 `interrupted/recovery_status=required`，已接管、已作废、成功或损坏计划不改成可执行计划。旧 `confirm` 一律拒绝，不计一次新的有效验证失败。重启事件关联原 plan／step／request。

新用户任务使旧计划剩余步骤停止，`stop_reason=superseded_by_new_task,recovery_status=blocked`；以后只能查看、接管，不能以恢复接口复活。用户主动取消的节点也不能借恢复撤销取消。需要重新办理时用 `propose` 建全新计划并全新授权，公开关联旧计划仅作历史依据。显式中断、进程中断、到期和可重试故障可经第 3 节重新核对；依赖必须重新实际成功后，后继才能推进。

### 最小公开保存表和损坏隔离

新增公开表 `recovery_plans(plan_id,user_id,snapshot_json,revision,created_at,updated_at)`；`plan_id` 唯一，`snapshot_json` 为上述安全 plan 快照（不含确认／恢复码或其他凭据）。表可更新当前快照；只追加要求针对审计与处置事件历史，不能用更新快照删掉 attempts／旧处置。无额外业务表名假设，独立作者可通过上述读接口核对节点事实。

读取先校验快照结构、枚举、最多 8 步、唯一节点 ID、参数类型、意图白名单、依赖存在及无环、用户与行一致、请求绑定与终态一致。损坏项只隔离该 plan：`recovery_status=corrupt`、不推进、给出安全原因，保留原记录；其他健康计划／账本不清空。列表可显示不含损坏内容的 `plan_id,status=failed,recovery_status=corrupt` 摘要。缺失节点不能从模型或相邻记录猜回。独立管理员损坏夹具只改自己临时库的该行 snapshot_json，不对日常库动手。

## 3. 恢复展示、固定同意和幂等

恢复分为三个动作：`prepare_recovery` 展示 → `confirm_recovery` 保存本次同意 → `resume_plan` 推进。无新同意调用历史 `resume_plan` 返回 `rejected/recovery_authorization_required`，业务不变，不偷偷创建确认请求。

`prepare_recovery` 必须重新读取当前账户／归属、联系人真实映射、余额、上海执行日累计、锁定、依赖、订阅状态及红档条件；它不执行查询订阅或其他节点。合法可恢复时返回：

```text
status=pending, intent=recover_plan, tier=none,
review_id, recovery_code, expires_at,
operation={user_id,plan_id,plan_revision,completed_steps,remaining_steps,
           operations,committed_effects,manual_actions,impact,expires_at}
```

`operations` 为本轮将办理的尚未成功步骤及其明确意图、完整关键参数、真实目标绑定、当前档位／已知影响；金额用整数分。只允许保持原计划语义的未完成动作，不代替用户改目标／金额。恢复审核只授权这些确切动作；不授予之后改参、其他计划、新工具或红档能力。缺信息、失败依赖不能补齐、取消／作废／损坏／人工接管终态返回拒绝及可采取的接管／新建入口。

恢复码是新生成的一次性六位 ASCII 数字字符串，拒绝非字符串、bool、非 ASCII 数字或长度不符；**只是明确同意，不是身份因素**。只在当前会话内存和本次 pending 响应中存在。5 分钟有效，`now >= expires_at` 失效。绑定可信 user、review_id、plan_id、revision、全部展示操作、真实目标、金额及到期时间；数据库／审计／模型／历史接口不得含码。重复准备同一未变化、未到期审核返回同一 review_id／期限，不延长倒计时、不生成新业务请求。

`confirm_recovery` 成功必须原子保存 `recovery_authorized` 事件和绑定后的许可，返回 `status=success,reason=recovery_authorized`；此时余额、流水、订阅及节点执行结果仍不变。许可仅当前会话有效，未启动本轮前最多至上述期限；`resume_plan` 再核对绑定并创建未完成节点的**新 request_id**。下一黄档仍返回 pending、完整 operation、自己的 5 分钟期限，必须用新 `confirm`；旧编号永不复活。后续依赖节点按原公开规则逐步推进，不能把恢复码用作节点确认码。

两调用者／两实例竞争时，在数据库事务内用 revision 与绑定复检：只允许一个有效审核被消费、同一节点最多一个活动尝试，旧许可返回 `rejected/revision_conflict` 或明确已办理回执。重复恢复确认返回已消费回执，不增加许可／请求；重复 resume 在同一 pending 上仍返回原待确认事实，不新建请求、不延期；重复业务 confirm 不再执行。每个成功 request 最多一条成功 transfers，累计只增加一次。

新任务、中断、接管、取消、重启、超时、目标／参数／联系人映射变化或 plan revision 冲突使恢复许可立即失效。控制同意失败不能清除原 transfer 验证失败计数；节点 confirm 的失败、三错锁十分钟及到期规则完全沿用原契约。跨上海午夜重新展示当前日期与期限；提交前再次复检所有业务条件。累计变化变红一律拒绝，本轮不因恢复或合成 MFA 结果放行。

`cancel(None)` 取消当前恢复审核／许可并停止本轮未完成步骤，**即使没有节点 pending**：包括只准备尚未同意、已同意尚未 resume、已开始恢复且某节点成功后处于 ready 的阶段。`handle_text("取消", model)` 由代码直接执行相同取消，不调用模型。存在当前恢复轮次时返回 cancelled，原子保存计划关联取消审计，旧未消费 review／码不得再授权，旧已消费回执也不得重新给予执行许可；旧计划不能再 resume 或 prepare_recovery 复活，须另建任务重新授权。已成功节点及其结果保持，不自动反向处理；没有任何待确认请求或当前恢复轮次时保留原 no_pending 语义。这是既有取消控制的范围说明，不新增业务动作。

## 4. 中断、接管及实际处置入口

`interrupt_plan` 原子保存中断、停止未完成步骤、作废节点／恢复确认和相应审计。重复中断返回同一停止事实；已提交步骤保留。

`takeover_plan` 同样停办，并原子创建／复用该计划的 `handover_id`，返回可实际访问的事项；`status=human_takeover` 只表示进入本地待处理事项。重启后仍能从队列／详情找到，不能只返回一句提示语。

事项至少有 `handover_id,plan_id,user_id,status(open/closed_record),created_at,updated_at,completed_steps,remaining_steps,committed_effects,manual_actions,entries`。每项处置追加 `entry_id,actor_user_id,actor_role=task_owner,recorded_at,disposition,compensation,note_redacted`。处理者来自当前可信会话，不能由请求写 actor；当前未建立独立员工／客服身份，不显示为银行已处理。

`record_handover` 精确规则：

- `disposition` 仅 `record` 或 `close_record`：前者追加处置，后者关闭**本地登记事项**。重复 close 不增加一项资金行为、不篡改旧记录，返回原关闭事实；closed_record 不再追加普通处置。
- `compensation` 仅 `manual_follow_up` 或 `no_compensation_needed`。前者标注仍需人工另行处理；后者是所有者选择“无需补偿”的登记，不声称发生退款／订阅恢复。保留原 committed_effects 与未执行步骤，不能把它们改为 success。
- `note` 为最多 500 字符的可选文本；不作为指令、不交模型，不支持凭据。使用既有审计脱敏规范；持久备注以 `note_redacted` 保存，含认证标记／已知秘密的内容整体省略，不回显。处置不允许输入任意业务结果、退款编号、真实员工身份或文件路径。
- 保存事项状态、追加 entry 与审计同事务。故障回滚后不能称已记录／关闭；该会话停止后续业务。接管计划不会因记录或关闭自动恢复；以后办理须新建计划、重新展示确认。仍需银行／平台联系的缺口一直保留。

## 5. 审计、公开故障点及进程证据

现有日志字段保留，新增可空 `plan_id`；`step_id` 对应公开节点 ID，`request_id` 对应本次节点请求，控制审核可用 review_id 作为请求关联值。事件至少包含 `plan_saved,plan_viewed,plan_restarted,recovery_prepared,recovery_authorized,recovery_expired,plan_interrupted,plan_takeover,handover_recorded,handover_closed`；原业务 `pending/confirmed/executed/failed/rejected/cancelled/expired` 事件不替换。模型候选与真实节点执行分开，成功与每轮尝试可一一核对。读取并追加事件不改旧记录；不得在字段、异常说明或持久快照藏凭据。

原 `audit_hook(event_dict)` 继续在审计 INSERT 前调用，可对 `executed` 或上方特定控制 event 抛异常。不改成可关闭审计的开关。

仅供可信 Python 测试的构造关键字扩展：`BankService(..., checkpoint_hook=None)`；不改变原位置参数。hook 接收只含 `point,plan_id,step_id,request_id` 的安全字典，返回值无效；不能改参数、权限或事务结果。未传时无效果，不进正式 CLI／HTTP 配置，不开放网络测试路由。最小同步点：

| point | 触发时刻／故障预期 |
|---|---|
| `plan_save_before_commit` | 首次完整计划和对应审计已准备、首节点尚未执行、保存事务提交前；抛异常返回 failed/state_unavailable，不准后续业务。 |
| `node_before_commit` | 节点业务、请求终结、节点结果、成功审计已在同事务准备，COMMIT 前；测试可抛异常或 `os._exit(71)`。进程退出后这些未提交变化一起回滚。 |
| `node_after_commit` | 上述事务已提交，响应／调用返回之前；测试可 `os._exit(72)`。重启后同一请求仍只有一次已提交成功，不能重试或反向处理。 |

hook 抛普通异常时必须回滚当前未提交业务并可靠记录失败（审计可写时），停止任务及依赖；不能吞掉异常继续节点。真正进程退出由测试子进程自行调用，生产代码不暴露退出工具。单纯 close／重建实例只算对象重建证据，不替代退出码 71／72 与父进程重开同临时库的证据。

## 6. 本机网页和 CLI 实际入口契约

新 HTTP 路由全部为 POST，沿用 `WEB_API.md` 的同源／Host／CSRF／Content-Length／JSON 重复键与类型／额外字段检查；非法网络请求只追加拒绝，不使现有确认失效、不推进业务。以下是精确字段，全部响应 `Cache-Control:no-store`，不返回凭据或完整模型配置。

| 路由 | JSON 字段 | 方法 |
|---|---|---|
| `/api/plan/list` | 空对象 | list_plans |
| `/api/plan/get` | plan_id | get_plan |
| `/api/plan/recovery/prepare` | plan_id | prepare_recovery |
| `/api/plan/recovery/confirm` | review_id、recovery_code | confirm_recovery |
| `/api/handover/list` | 空对象 | list_handovers |
| `/api/handover/get` | handover_id | get_handover |
| `/api/handover/record` | handover_id、disposition、compensation；可选 note | record_handover |

已有 resume／interrupt／takeover 路由保持。页面须提供“历史任务”列表／详情、核对恢复内容后的独立同意控件、继续办理按钮、接管队列／详情及实际处置表单；并显示已完成／未执行／不可自动补偿事项。恢复码只留页面内存，页面不使用 localStorage，不自行调用确认／继续，不设密码或动态码输入。渲染安全文本用 textContent。

新增本机交互入口约定 `python scripts/recovery.py --db <独立模拟库路径> --user alice`，**一次进程内**保持同一 BankService，提供历史列表／详情、准备恢复、固定输入确认恢复、resume、中断、接管、接管队列／详情与登记／关闭；重新启动入口即重新开始会话并使旧许可失效。固定输入格式为 `确认恢复 <review_id> <recovery_code>`；展示完整 operation 后才接受，不由模型判断同意。黄档节点仍使用原固定确认。`--help` 只打印帮助且不打开库；无 MFA、改时钟、故障 hook 或任意工具参数。CLI 能操作本地记录不等于真人、真实设备或银行人工验收已通过。

## 7. 独立模拟夹具与 R-01～R-37 对照

每条使用全新临时 SQLite 文件，禁止连接／清空 `data/bank.db`；默认注入 `2026-10-23T10:00:00+08:00` 时钟、可信 alice，另开 bob 检查归属。数据沿用 PUBLIC_API：alice-main=1000000、alice-savings=500000、bob-main=100000 分；wang、li 均登记到 bob-main；本月账单 5970 分，订阅 990/1990/2990 分且 active。

`T100={intent:transfer,params:{account_id:alice-main,contact_id:wang,amount_cents:10000}}`；`P=bill(analyze_bills,{}) -> pay(T100) -> subs(query_subscriptions,{})`。`A` 表示提出 P 到 bill 成功、pay pending；`B` 表示 A 后合法确认 pay，但尚未 resume subs。`B` 必为 alice-main=990000、bob-main=110000 分，本笔成功 transfers 仅一条、当日成功累计只增加 10000 分。每行的前置独立建立，不能依赖上一行留下的数据。

管理员前置仅限自己的临时库、PUBLIC_API 已公开表与本文件 recovery_plans：可改账户余额／归属、contacts 映射、插入 transfers 建立当日累计、定向损坏 snapshot_json。它们不作为应用授权。比较前后账户、流水、成功累计、requests、verification_state、审计快照和持久 plan，不只断言文字或 status。下表全部**未运行**。

| 编号 | 确定输入／公开入口 | 确定期望与核对 |
|---|---|---|
| R-01 | A；子进程退出；同库重启 list/get | 同 plan、全部依赖和 bill=5970 历史成功仍在；pay 旧 pending 已失效，subs 未执行；无资金增量。 |
| R-02 | P 的 bill 在 node_before_commit 仅一次抛异常；重启 get/resume | bill failed 与原因保留，pay/subs 未执行；resume 要新恢复同意，不能直接跳到 pay。 |
| R-03 | P首个bill的node_before_commit中os._exit(71)；重启重复list/get | 初次计划已提交而bill事务回滚；原三节点ID、顺序、参数、依赖及尚未成功事实可查，读取无执行。 |
| R-04 | A 保存原 request/code；未满5分钟重启 confirm 原值 | rejected，旧请求 session_restarted 终结；资金／流水／累计不变，追加失效与拒绝。 |
| R-05 | A；时钟到 expires_at（含等号）；重启 prepare/旧confirm | 原请求不可复活；必须新审核、新期限及新请求；未授权前无转账。 |
| R-06 | A 重启；直接 resume／prepare | resume 拒绝；prepare 只展示当前完整 operation、已完成与剩余，无业务请求执行。 |
| R-07 | A 重启；prepare→confirm_recovery→resume→新confirm | 控制同意本身不转账；新pay请求不同于旧请求；最终只成功 T100 一次，余额符合 B。 |
| R-08 | propose P 时 plan_save_before_commit 抛异常 | failed/state_unavailable；不得声称可靠保存／执行 bill 或放行 pay；余额及订阅原样。 |
| R-09 | A；confirm pay 在 node_before_commit os._exit(71) | 父进程核实退出71后重开同库：本笔双方余额／流水／成功日志／节点成功均无；不自动重试。 |
| R-10 | A；confirm pay 在 node_after_commit os._exit(72) | 父进程核实退出72；重开得 B 已提交事实，pay success，恢复不重做、不逆向。 |
| R-11 | B 重启；重复 prepare／恢复／resume；重放 pay confirm | pay 始终成功一次；无可执行pay副本；未授权subs不读；明确重复回执。 |
| R-12 | A 同会话反复 resume | 保持同一pay请求与期限、不执行、不新建code；金额增量0。 |
| R-13 | A 重启；两同用户调用者竞争审核及confirm/resume | revision／绑定防并发；至多一个活动pay尝试，成功T100最多一次；旧竞争者拒绝或已办理回执。 |
| R-14 | A interrupt；重复interrupt；重启get及旧confirm | bill保留；pay终结、subs未执行；中断持久，原确认拒绝，无恢复执行。 |
| R-15 | B interrupt/get | 明确已转10000分、subs未查询；余额保持B，不称全撤销。 |
| R-16 | 分别在bill未完成故障点、A、B takeover | 停未完成节点，原许可失效；每次有可list/get的handover及已提交／待处理项，可实际record。 |
| R-17 | R16新夹具；record及close_record，重启查询 | actor=可信alice/task_owner、时间/事项/处置可查；旧entry保留；关闭不伪造资金或订阅结果。 |
| R-18 | alice建A／handover；bob调用所有新读取/控制/处置 | not_found_or_not_owned，无alice参数/结果；两用户业务无变更。 |
| R-19 | 分别构造bill失败、pay取消/到期/拒绝后resume | 不跳过失败前置；后继不成功；已提交前序保留；重试必须先新审核并实际完成前置。 |
| R-20 | A的pay错误confirm两次；重启新恢复/新pay再错一次 | verification_state transfer累计3次并锁10分钟；换码/恢复/取消/重启不清，锁中可cancel。 |
| R-21 | transfer锁定后重启；低金额/另一本人账户；时钟推进至锁截止 | 截止前不执行、不改变locked_until；到达截止才按原规则复位新计数。 |
| R-22 | A重启前后分别改alice-main=9999或user_id=bob；prepare/confirm/resume | 当前事实拒绝；旧快照不能扣款，无部分入账；在新pay待确认后再改也须提交前拒绝。 |
| R-23 | A后临时库insert本人savings当日success=95000；恢复 | T100合计105000分重定red，拒绝；本笔余额/流水增量0，不沿用黄档。 |
| R-24 | A在上海23:59建立；重启时钟次日00:01；新审核 | 新日期/期限明确，按实际执行日累计；旧code不复活，成功仍恰好一次。 |
| R-25 | A后改wang映射到alice-savings，或改为li／金额20000 | 原绑定作废；相同实际账户也不能将wang授权移作li；改参必须新propose、新展示。 |
| R-26 | A；propose本人余额新任务；重启恢复旧P | 原P stop_reason=superseded_by_new_task；只读／接管可用，恢复拒绝；新办另建计划。 |
| R-27 | A；audit_hook在pay executed仅一次抛异常；resume/恢复 | 本笔业务、确认消费、成功日志、节点成功一起回滚；当前会话停办；不能借恢复绕过故障。 |
| R-28 | 在recovery_authorized/plan_interrupted/plan_takeover审计各抛异常 | 控制事务不授予未审计许可、不谎报已保存；会话停办，先前B结果如实保留；不可写时不要求凭空有故障日志。 |
| R-29 | 各自成功/失败/取消/中断/接管；旧audit逐字段快照后重启 | 旧条目不变，仅追加；plan/step/request/user和原因可关联，候选与执行有别。 |
| R-30 | 合成认证标记放入候选/处置note；检查所有安全快照及响应 | 不落密码/密钥/认证secret/有效code/确认code；仅当次pending允许所需屏显确认码，历史及持久表无。 |
| R-31 | B后要求“恢复到执行前/撤销转账”；takeover/record | 原B不变；无反向流水；manual_follow_up仅登记人工另行处理，不退款。 |
| R-32 | 合法确认cancel sub-video；后继失败/重启 | sub-video仍cancelled；actual=5970，future=2980；无自动恢复、无删历史。 |
| R-33 | propose restore_subscription/退款/改删日志，或把这些塞入恢复/处置字段 | 非白名单/额外字段拒绝，业务不变；处置不扩模型工具。 |
| R-34 | 累计红档或模型声称MFA/隔离已完成；恢复/强验证 | 红档始终不执行；合成验证通过元数据不能授权新请求；真人缺项如实保留。 |
| R-35 | 分别改临时recovery_plans.snapshot_json为坏JSON/缺节点/错类型/环 | 仅该plan corrupt，不执行、不猜参数；健康plan可读，正常账本不清空。 |
| R-36 | 新接口以bool/null/过长/路径式/他人ID及终态重复调用 | 格式拒绝或明确幂等，无任意文件打开／他人信息，无健康任务破坏；审计可写则有定位回执。 |
| R-37 | 独立本机HTTP新路由：旧CSRF/跨源/重复键/额外JSON字段 | 403或400且原有效pending不失效，无新业务；正常会话能完成历史查看与处置，no-store且无凭据。 |

R-03 使用首个 bill 的 `node_before_commit`：此前完整计划已提交，进程退出使 bill 的未提交结果回滚。不能把 `plan_save_before_commit` 中退出后不存在的未提交记录冒充持久保存。

## 8. 实现范围与仍待规则决定的事项

可直接实现：一张安全快照表及原子节点提交；历史读取；重启失效和新恢复同意；既有六项工具的受控重试；中断／本地接管记录及网页和CLI入口；公开故障点；独立模拟进程／并发测试及受影响回归。首次失败证据须保留，修后另记复测，不能把本设计计为测试通过。

真正未定义、不能自行扩权的规则只有新增补偿业务：例如恢复订阅的适用状态、档位、确认绑定、是否产生新收费／新平台影响、审计、重复请求以及并发幂等。正式银行人工处理者身份、渠道与核验方式也尚无条件。本阶段以可实际访问的本地事项登记交付，列清这些缺口；不以“已交人工”代替真人办理。

实现者可在不降低上述业务期望的前提下调整安全拒绝代码或内部表结构；涉及独立作者调用的签名、路由、公开表和故障点必须先更新本契约及变更依据，再冻结测试，不能运行失败后悄改期望。

# 40 · 六场景独立验收判读

日期：2026-10-28。作者为未读业务实现的独立规格/测试作者，依据公开规则与根执行者实际输出判读；没有运行验收测试、真实模型或提权，没有读取业务 .py/.js、真实配置、正常演示库。**已核对52方法成功、Docker33冻结批次成功，真实模型三批累计30次并分别覆盖九组；第三批L-09已完成真实进程重开、恢复、新确认付款与账本/审计/监控核对。** 这不是一次同版本九组全过；52轮因期间新增脚本而整树摘要变化，最终同版本解包复验另记。全部首失败及脚手架修订保留。

## 一、规格与冻结依据

范围见 docs/36；52方法独立输入/期望见 docs/37；真实模型九组见 docs/39。业务依据为 src/SIX_SCENARIO_API v4及原 PUBLIC_API、CONTEXT_API、RECOVERY_API、DOCKER_ISOLATION_API。v4是本轮工程规则，不宣称全队或赛事正式确认。预算占用可用余额，转账/已付订单共用上海日累计和失败锁桶，卡限额实际约束显式选卡订单；红档拒绝、不定时、不动态结果引用、不自动补偿保持。

首轮测试原版另存 `tests/.runs/test_six_independent-first-20261028-003626.py`，原/副本SHA256：`CB1E10B37253A6BC1515D176678AC10D38EC248F0F1F0D4CE4AF2F9F0B29FF5F`。修脚手架后测试SHA256：`11887CFDFF0B714D196482E8F4EB52F1CEE1A8541F6420BDDA33887434F0D37E`。两版全部测试方法、输入和断言相同；只改两个SQLite辅助方法的连接关闭与一行标准库导入。

真实模型脚本最初冻结为 `tests/run_six_live_acceptance.py`，SHA256：`63A6D590BADE9AE67DAF36FCFC08F7FC7CCA7164F890AFE8ABAC7B63A5832444`；最初矩阵 docs/39 SHA256：`0C8F2390033364E016C6A785B8F2A0708F2B785BBDEC4115113A2A870C137A16`。作者未运行，实际两批及后续仅快照门修订见第六节。九组一遍至多26次propose机会，绝对30次总预算，不自动重试；运行者需按此前实际用量扣减剩余额度。

## 二、首轮实测事实

证据：`evidence/six-independent-run-20261028-003626-968617.json` 与同名 `.txt`。由根执行者在新临时库、显式真实Docker runtime下运行 `python -B -X utf8 tests/test_six_independent.py`；开始UTC `2026-10-28T00:36:26.968617+00:00`，结束UTC `00:38:26.134915`。包装器耗时117.109秒，unittest记录115.539秒，退出1；52方法，`failures=1, errors=49`。源与保护摘要首尾未变，包装器版本摘要 `f731782c185087c806f28464d1f0bf63127f9759e4cb2acdcd5a587a28853864`。其中51方法离线，S-50为真实Docker组合；本轮无真实模型或真人验收。

2方法显示ok；49个ERROR不能记为通过。S-50虽已走到业务断言末尾，其tearDown仍错误，整个方法仍是ERROR，不能删去清理错误改写通过。旧的45、159或其他通过数量也不进入本轮新增能力的通过数。

## 三、问题单及修订判读

### SI-01：测试读取连接未关闭导致Windows清理失败

- 输入：各方法在自己的新临时库调用rows/change辅助方法，最终tearDown删除TemporaryDirectory。
- 期望：辅助读取/改库结束后关闭连接，所有已关闭资源可以正常删除；不能以忽略清理错误结束。
- 实际：49个ERROR在tearDown的temporary.cleanup触发WinError32，临时 `.sqlite` 文件仍被占用。辅助方法使用SQLite连接自身的with；它管理提交/回滚，但不保证关闭连接。
- 是否运行：首轮已由根执行者运行；作者读取首轮原始输出判读，未自行运行。
- 修订：只增加`contextlib.closing`；rows在closing内读取；change在closing内保留原连接事务with，结束后显式关闭。没有改业务输入、期望、断言、方法数量，不隐藏错误或依赖垃圾回收。
- 验证方法：修改前复制原文件并核对相同SHA；原/新版no-index差异只有上述三个位置。下一轮由根执行者重跑，检查49个清理错误是否消失，且仍执行全部52方法。
- 最没把握处：只依据公共测试辅助代码与Windows错误栈认定该资源缺陷；修后是否还有其他句柄占用只能由实际复测证明，不能预写已修好。

### SI-02：明确“买服务…鲜花”的新订单动作被判unknown

- 输入：S-44先通过多轮明确生日预算20000分、来源主账户、活动日期2026-11-01并确认保留，再输入“从预算birthday为2026-11-01活动买服务flower-basic鲜花”，离线模型候选为明确place_order参数。
- 期望：已有ID、服务和日期均明确，应返回黄档pending；此时仍不付款，另用固定confirm后才有订单。
- 实际：返回rejected/clarification、intent=unknown、draft=null、missing_fields=[intent]，提示明确操作；与冻结期望不符。
- 是否运行：首轮已运行，原始txt保留FAIL及安全响应。
- 验证方法：实现作者修动作识别，再用完全相同S-44输入、候选与断言复测；不通过换句或降低期望消失问题。
- 最没把握处：独立作者未读实现，只能定位公开行为的动作识别缺口，不能判断内部具体分支。该问题由实现侧处理，测试不改。

## 四、待实际证据后的记录

修脚手架后的52方法复测、原45等回归、真实模型九组、浏览器/新交付包检查均尚未由本报告独立读取到结果。根执行者提供新批次输出后追加实际数、退出码、版本和首尾摘要，不覆盖首轮文件或本节历史。

真实模型重点核对L-09：自然语言→隔离候选解析→代码来源/权限→先保留预算→已有ID静态DAG到pay pending→真实准备子进程结束→父进程重开→恢复同意不付款→新请求重新确认→一次12900分订单→余额987100/保留7100/可用980000/账单18870及节点、审计、Docker回执一致。没有这条实际成功证据，不能用单步测试通过宣称整个链条完成。

真人手机、真实终端因素、队友人工核验、真实银行/投资、自动定时、完整自动补偿和正式赛事渠道均不由自动测试推导通过。当前所有账户、卡、产品、订单及资金仍为模拟。

## 五、修后52方法与原45方法复测

根执行者提供 `evidence/six-independent-run-20261028-165300-526411.json` / `.txt`，作者只读原始结果与摘要核对。unittest为`Ran 52 tests in 126.032s`、`OK`，退出0，无失败、错误或跳过；包装器耗时128.454秒。包装器开始时间值为`2026-10-28T10:53:00.526411-06:00`，结束`10:55:12.945303-06:00`。S-44及S-50明确显示ok：前者用未改的固定原句通过，后者实际Docker并完成清理；SI-01、SI-02在该轮冻结期望下均得到修后验证。此次52方法仍为51离线方法加1个真实Docker组合，不包含真实模型或真人。

相邻回归 `evidence/six-context-run-20261028-165301-123859.json` / `.txt` 显示原上下文45方法、failures=0/errors=0/skipped=0，退出0，包装器50.313秒；它不增加本轮新增52方法数量。

两轮包装器版本摘要均为`d45e458187283944b6e8ba207a5f0c9daba0c1b218ca99e5db5a8d3a18486746`，`protected_unchanged=true`，但`source_unchanged=false,passed=false`。作者独立逐键比较52轮source_hashes_before/after，唯一差异为新增`tests/run_six_live_acceptance.py`，after摘要为`63a6d590bade9ae67daf36fcfc08f7fc7cca7164f890afe8abac7b63a5832444`，无业务实现文件摘要变化。此后测试文件仍为`11887CFDFF0B714D196482E8F4EB52F1CEE1A8541F6420BDDA33887434F0D37E`，真实runner仍为前述冻结摘要。这里只比较摘要，不读取实现内容。

因此可以陈述“修后52方法与原45方法实际零失败，首轮问题已按原期望复验”，不能把包装器false改成true或宣称最终整树/解包源码已通过。根执行者还需在全部源文件停写后，对同一最终版本及实际解包副本统一复验。真实Docker33、真实模型九组和网页QA正在由根执行者另行运行，本作者尚未读取它们的实际结果，不预填通过。

## 六、真实Docker33与真实模型两批判读

### Docker33冻结批次

作者已读取`evidence/docker-isolation-run-20261028-165949-501172.json`及独立原始`evidence/docker-isolation-independent-20261028-165950-846131.json`。33方法、0失败/错误/跳过，successful=true，包装器退出0、passed=true、source_unchanged=true、protected_unchanged=true，耗时286.719秒。该版本摘要为`8d4ce415ce6d9097d21b98f2b2f0d5b5fe77da8c21e23f4da4faa119bcab7825`，独立Docker测试文件摘要`291a58f283c74dcc2163b3b80e4f33e590d0dcf7825b0c3ea63c84aedfd122fa`。

此结论仅为该版本Linux Docker契约33方法通过，不是Windows机制修复、真人因素或正式赛事认可。后续prompt与验收脚手架变化产生新版本，最终同版本/解包回归仍需另记。

### SL-01：首批模型没有提出订单，不能算卡限额生效

- 证据：`evidence/six-live-run-20261028-165953-422354.json`与`evidence/six-live-20261028-165953-422354/events.jsonl`、`report.json`。版本同前述`8d4ce415...`，source/protected均不变，包装器退出1、passed=false。
- 输入：原L-08先明确保留budgetLimit40000分并改本人卡日限额10000分，再明确从该预算为2026-11-01活动用card-alice-main购买flower-basic鲜花。
- 期望：模型提出明确place_order，代码因实际12900超过卡限额拒绝；必须到达真实工具边界，不能以模型自行拒绝代替。
- 实际：该句模型候选为`intent=unsupported,params={}`，验收正确以`card_limit_rejection_did_not_reach_order`失败停办。L-01—07通过，L-08未过，L-09未到；无新增订单不能证明卡限额检查生效。
- 是否运行/用量：已实际21次propose、21次报告传输；逐调用usage.total_tokens合计42277。无自动重试。reported_model/alias为服务自报记录，不据此鉴定权重，费用unknown。
- 验证方法与不确定处：独立只读安全候选/响应和报告；词句/冻结期望保留。根执行者随后只改模型提示文字再人工选原L-08/09，不改测试；作者未读提示实现，不能判断内部原因或泛化自然语言可靠性。

### 第二批L-08实际通过；SL-02为L-09快照门错误

第二批证据`evidence/six-live-run-20261028-171541-238824.json`与同批目录events/report；版本`a78bca15b3d7cec4e62abceeb4c1fd81f834a769dd8896e432c481987f8cb6ea`，source/protected均不变，退出1、passed=false。人工仅选原L-08/09，7次propose/7次传输，逐调用total_tokens合计17024；L-08通过，L-09准备子进程失败、尚未付款。

- 输入：L-09原模型静态六节点候选，bill.params仍为空对象，节点ID、依赖及其他参数均为原冻结值。
- 期望：候选保持原静态语义；持久快照依据**原RECOVERY_API第46行**把默认日期解析成明确值。固定时钟2026-10-27意味着bill.params只能为`{start_date:'2026-10-01',end_date:'2026-10-27'}`，同时原`bill.input_params={}`；不能接受任意范围。
- 实际：作者独立读取第二批events，确认模型候选与原PLAN六节点完全一致，公开response.plan唯一差别是bill.params规范化为上述两日期，input_params仍{}。原runner把持久params也错误要求成输入的{}，以`plan_static_parameters_or_dependencies`停；父进程安全报`prepare_child_failed_see_safe_journal`。这是验收快照门遗漏已公开规范化，不应要求产品删除日期绑定。
- 修订：完整原runner保存`tests/.runs/run_six_live_acceptance-first-20261028-171541.py`，与原正式文件SHA均`63A6D590BADE9AE67DAF36FCFC08F7FC7CCA7164F890AFE8ABAC7B63A5832444`。仅plan_gate的bill持久快照改为精确两日期，并增加input_params必须{}；原PLAN/输入、其他节点/参数/依赖、确认、资金与审计期望不改。修后runner摘要`E4E9F81D3C691C0572504366F0516821A9246E0BF992DED269C774CA56FAB939`，docs/39修订后摘要`5EF11960EB17223D6C02BCD9F10221CB51610A111B6A1C19754AB5FA486E4716`。
- 验证方法与不确定处：no-index差异仅该快照门；原失败保留。作者未执行修后脚本，L-09尚未证明付款/恢复全链成功，不能用第二批正确模型候选代替完整实测。

两批已用28次propose/28次传输、合计59301个报告total_tokens；本轮30次总上限只剩2次。根执行者可显式仅跑原L-09、`--groups 9 --max-calls 2`，不自动重试；结果待实际证据后追加。网页首轮helper条件关窗导致超时是根执行者提供的消息，作者尚未独立读取网页原始证据，暂不作网页通过结论。

## 七、第三批L-09完整成功与本轮可证实结论

第三批证据为`evidence/six-live-run-20261028-171955-229821.json`及`evidence/six-live-20261028-171955-229821/events.jsonl`、`report.json`。作者已独立读取这些公开证据，并仅以SQLite只读模式核对该批**新模拟证据库**中的公开请求、审计、支出和监控字段；没有实例化业务服务、发起测试或读取正常库。

该批只选原L-09、上限2次，实际2次propose/2次传输、5037个报告total_tokens；退出0、passed=true、无未通过组，包装器50.594秒。版本`05f3035fed4463db211b6d2a9361fcae2d3af09d2b84854e5a1efb5381044f77`，source_unchanged/protected_unchanged均true。

### 逐段实际核对

1. 真实模型提出20000分预算与原六节点静态候选，真实Docker解析，代码确认门接受后保留预算；此时cash1000000、reserved20000、available980000、0订单、实际账单5970、资金日累计0。
2. 图先执行catalog，到pay等待。`child_prepare_completed`为prepared_not_paid，随后有`child_prepare_exit.exit_code=0`，父进程才重新打开同库。这是真实准备子进程正常退出后重开，不冒称异常强杀；强杀提交前后另由S-40/41覆盖。
3. 旧pay请求`321b08d2effc4e1bac4e93839f0c4f39`持久状态cancelled，对应session_closed取消审计；重开后无付款。直接resume得到recovery_authorization_required。prepare与固定confirm_recovery前后仍cash1000000、reserved20000、0订单，控制同意没有代替业务支付。
4. resume产生新请求`64826dc2dc1e4a8e9b004daf346114fb`，区别于旧请求，新的完整黄档确认门通过后才付款。实际paid订单ID等于新request_id，service=flower-basic、budget=birthday、source=alice-main、card=card-alice-main、event_date=2026-11-01、amount=12900、执行上海日2026-10-27，恰一单。
5. 付款后cash987100、spent12900、remaining7100、released0、reserved7100、available980000；20000=12900+7100+0，资金日累计12900，实际账单18870。savings500000、bob100000保持。数据库有且仅一条12900分success/expense支出；本组无转账。
6. 后续budget/orders/balance/bill节点按依赖成功，六节点均success，bill结果18870；plan`2dbb9f75caea4d53bf92d643ef2a1577`的committed_effects含此订单和已提交request。新请求状态success，只有一条对应executed/success审计，step=pay、plan与请求一致；旧请求只有取消，无成功订单。
7. 该新request在独立monitor中有专属finished/success/ok回执，mechanism=docker-linux-readonly-v2，daemon_policy_verified=true、cleanup_complete=true、container_removed=true、container_running_after=false、container_pid_after=0。业务审计与独立monitor分别核对，不能说成跨库原子事务。重放及取消没有退款或释放剩余预算；有效确认/恢复码不写入报告。

### 总调用与结论边界

三批为21+7+2=**30次propose、30次报告传输**，token合计42277+17024+5037=**64338**，费用unknown。没有自动retry、额外真实调用或换句补候选；第二、三批是根执行者明确选组的人工复测。预算已用尽，不再发真实请求。

九组覆盖分别来自：L-01—07首批、L-08第二批、L-09第三批，期间有模型提示修订和runner快照门脚手架修订。可陈述“预定九组分别取得实际成功，其中L-09全链已核对”，不能写“一轮九组全过”“同一最终版本九组全过”“30次均成功”。首批模型unsupported与第二批脚手架失败仍是失败历史，不能删除或改作成功。

## 八、网页QA证据的分类核对

已独立读取视觉目录`six-ui-20261025/run-744ab7beea544a2098da22a71acf2055/six-ui-report.json`及`server-final.json`（根路径为`C:/Users/KindHermit/.codex/visualizations/2026/10/11/01a12adb-9c8e-79c1-ac78-e90b97c13b44`），没有阅读UI源码，也没有亲自操作浏览器。本节是对实现侧网页QA报告的独立分类复核，不把它变成独立操作者的网页验收。

该报告passed=true，17个列明阶段均passed，包括历史恢复分离同意、新卡/限额实际状态、六方向入口、产品比较/匹配、先保留后静态订单核账、订阅取消、外部标记作为安全文本，以及窄视口释放与回执。模型为**离线精确短句候选依赖**，实际网页走真实Docker；报告中的24次dependency调用不是网络模型调用，不加到上述30次真实模型预算。390×844为浏览器窄视口，不是真人手机证据。

server-final记source_unchanged=true、failure_type=null、cleanup_error_types=[]。该网页独立夹具有10000分转账和12900分订单，因此最终主账户977100、bob110000；预算spent12900/released7100/remaining0，paid订单保留。它与仅鲜花付款的L-09夹具不同，不能把两者余额混用。独立monitor汇总54个finished、0失败、全部docker-linux-readonly-v2、cleanup/policy均true。首轮helper窗口条件导致的超时应与此修后批次分开留档，详细网页交付由docs/41登记。

当前可封入报告的是上述分批、分证据结论。最终新包及解包同版本全套结果尚未由作者读取，不在本轮预填；真人手机/终端/队友、真实银行/投资、后台定时、自动补偿和赛事正式认可继续按缺项保留。

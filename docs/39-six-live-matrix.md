# 39 · 六场景真实模型独立矩阵

冻结日期：2026-10-27。状态：**独立作者只写公开接口验收脚本，未读取业务实现/配置/正常库，未调用模型、未运行或提权。以下均为预期，不是通过报告。** 52方法离线/可选Docker测试及其期望保持原版，不因本真实模型组增删或改写。

入口：`tests/run_six_live_acceptance.py`。依据 `src/SIX_SCENARIO_API.md`、PUBLIC_API、CONTEXT_API、RECOVERY_API、ISOLATION_API、DOCKER_ISOLATION_API 及 docs/36、37。所有数据模拟，固定上海时钟 `2026-10-27T10:00:00+08:00`，活动日期 `2026-11-01`。初始账单按此新库创建月份仍为5970分。服务、产品、账户、联系人和卡均用公开固定ID。模型只能提候选；脚本的预定确认门也只是自动化模拟验收，不是真人办理或真人因素验证。

## 调用与证据约束

九组完全成功时至多有26次模型propose机会，绝对上限30。每句只提交一次，不重试、不自动改句、不替换模型候选为手写候选。任一不符或模型/隔离故障即停止后续真实调用，保留已提交事实。正式运行者若另开复测，应先从本轮30次总授权中扣除已实际使用的次数，通过 `--max-calls` 传剩余额度并用 `--groups` 选择明确组；脚本不会自动复测。模型前置拦截可能使实际调用少于句数，必须按实际记录，不能补写成功模型调用。

仅通过 `ModelClient.from_environment(candidate_parser=...)` 在实际运行时读取本机配置；作者不构造客户端检查配置。公开parser为 `callable(text:str)->dict`，只调用同一实际执行器的 `execute('parse_candidate', {'text': text})`，返回已解包候选dict，失败不回退宿主解析。业务也用此 IsolatedExecutor，monitor独立于业务库。不得使用普通进程替身冒称Docker。

每组全新模拟库，输出目录必须是仓库 `evidence/` 下新的 `six-live-*` 目录，不能重用旧目录或传正常库。证据逐步追加安全JSONL，结束另写总报告；保留安全输入、候选、代码结果、前后资金与状态、请求/节点/审计关联、Docker回执和模型元数据。仅记录 ModelError 类型/公开code/http_status，不记录异常str、配置、认证头或原始HTTP错误。每次使用独立客户端，缺失usage/model均unknown，不沿用前次；model alias不等于权重鉴定，费用无依据记unknown。请求max_tokens1200、temperature未显式设置、DeepSeek thinking disabled仅按公开契约记录，不以预算冒充实际用量。

confirmation_code/recovery_code只在内存送固定入口，安全响应递归去除相关字段，字符串六位码遮盖；不将码写进JSON、子进程标记或控制台。子进程只留下无秘密plan/request ID。测试代码不打印含码的原始响应或异常堆栈。业务库/审计/计划若意外存码，检查失败，报告也只能写静态原因，不回显该码。

## 九组预定输入与期望

编号中每一句是一次handle_text机会。静态计划中节点ID和依赖由输入明确给定，脚本不能看模型输出后修改计划期望。

| 组 | 固定人类输入（参数中的日期均为2026-11-01） | 确认前后独立期望 | 最多调用 |
|---|---|---|---:|
| L-01 理财 | 查询模拟理财；比较p-growth和p-cash；匹配风险medium/90天/流动性flexible | 绿档实际四产品；比较顺序growth→cash；匹配cash+flex且不放宽条件；资金/卡/预算/订单无变化 | 3 |
| L-02 卡片 | 查询本人卡；主账户申请虚拟卡；明确card-alice-main日限额200元 | 查询只有本人卡；两黄档各自完整确认前无变更；真实新增一张virtual/active模拟卡；原卡限额保存20000；资金/授信不增 | 3 |
| L-03 原转账与账单 | 查询本月账单；从主账户给联系人小王转100元 | 账单5970；黄档摘要逐项核对可信alice、主账户、wang、小王、bob-main、10000分及日累计10000后才确认；余额990000/110000，成功transfer一条 | 2 |
| L-04 原订阅 | 查订阅；明确取消视频会员sub-video；再查订阅 | 每次查询仍须黄档确认且前不泄漏列表；取消只改本人sub-video；未来5970→2980，原实际支出5970不抹除，无退款 | 3 |
| L-05 多轮预算及缺参 | “保留生日预算200元，预算编号birthday”；“从我的主账户，活动日期2026-11-01”；新任务“帮我买鲜花” | 首句因缺账户/日期澄清不建业务请求；明确补项才黄档并确认保留20000，cash1000000/available980000；新订单缺已有预算ID/完整日期，继续澄清不买，不沿用已成功任务参数 | 3 |
| L-06 红档 | 主账户申购p-cash100元；主账户赎回p-cash100元；挂失card-alice-main；解挂card-alice-main | 四项红档拒绝，无持仓/资金/卡状态变化，不显示交易或挂失完成；未登记强验证不生成黄档码 | 4 |
| L-07 定时边界 | “请于2026-11-01自动联系商户购买鲜花，届时再付款。” | 不支持后台定时/商户联络，拒绝/澄清；不得静默改为立即保留预算或立即支付，业务不变 | 1 |
| L-08 真资金约束 | 保留budgetLimit400元；card-alice-main日限额100元；用该卡从budgetLimit买flower-basic；从savings给小王转900元；不选卡从budgetLimit买flower-basic | 保留40000并真实设10000限额；首次选卡鲜花12900超卡限额拒绝，不能回退无卡；跨账户转90000成功；之后无卡鲜花也因统一累计102900红拒，0订单、预算仍40000 | 5 |
| L-09 完整恢复链 | 主账户保留birthday200元；明确六节点静态图catalog查询服务→pay用card-alice-main从birthday买flower-basic→budget查birthday→orders查birthday订单→balance查全部本人余额→bill查本月账单 | 保留先单独确认；已有ID图到pay pending，不付款。准备阶段真实子进程结束，父进程确认exit0后重开同库：旧request cancelled、无自动支付；prepare/confirm_recovery只授权恢复；resume创建新request，重新逐字段确认付款；后继成功，cash987100/reserved7100/spent12900/available980000/actual18870，订单恰一条，计划及审计一致，已提交不退款 | 2 |

## 确认门与恢复门

固定确认门只接受 `status=pending,tier=yellow`、本人alice、simulated严格bool真、预定intent和完整规范params精确相等，并检查五分钟期限和内存码格式。它还独立读取公开表核对预先冻结的账户/卡/预算/服务事实及预期金额，不根据模型返回的目标/价格临时选择期望。转账必须额外符合公开operation的真实联系人名、账户、金额和累计；订阅查询不能提前返回列表。任何缺字段、bool冒充金额、错卡/账户/预算/日期/服务、未知动作或额外资金节点都停止，不确认。

L-09在确认pay前必须保持cash1000000、预算20000、0订单；恢复摘要绑定本人、同plan、catalog已完成及剩余五节点，包含唯一的明确place_order完整params。恢复同意前后业务不变；新pay.request_id须区别于原pending。新confirm完成前后分别读取公开表，随后resume查询结果；检查订单ID=request_id、paid、12900、card/account/budget/date精确，transfers=0，费用进入成功expense和实际账单；paid请求/节点/成功审计同一plan/step关联，并有对应request的实际Docker回执。

L-09记录的是一次真实准备子进程正常退出与父进程重开，不把对象close/reopen冒称进程退出；离线S-40/41另测强制退出71/72及提交前后原子性。Docker监控与业务审计是两个库，不冒称跨库同一事务。未实测的真人手机、终端因素、队友人工验收、真实交易、自动定时及正式赛事认可仍未完成。

2026-10-28脚手架校正：L-09的模型候选bill.params仍精确为`{}`；持久快照按原RECOVERY_API“默认日期解析为明确值”规则核对`bill.params={start_date:'2026-10-01',end_date:'2026-10-27'}`，同时必须`bill.input_params={}`。只修原runner把输入参数误当持久事实的快照门；其他节点、ID、依赖、参数、确认与资金期望均不变，不接受任意日期或额外字段。原脚本与前两轮失败永久保留，详见docs/40。

## 运行与结果口径

根执行者在离线与Docker问题处理后，显式运行：`python tests/run_six_live_acceptance.py --runtime <新runtime绝对路径> --output-dir evidence/six-live-<新批次> --max-calls 30`。可用 `--groups 1,2,...` 选冻结组，不提供自由输入/任意工具/任意SQL入口。输出只显示批次摘要与安全文件路径。此文不预填通过数或用量；实际结果、首失败、修复及复测另行登记，不能覆盖原始证据。

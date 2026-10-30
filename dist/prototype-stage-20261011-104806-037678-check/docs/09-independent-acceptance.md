# 09 · 隔离独立验收记录

日期：首次验收2026-10-10，最近原样复跑2026-10-11。版本：本轮工作区代码与2026-10-10 `src/PUBLIC_API.md` 公开契约；未记录提交号，不将这一结果归属于尚未核对的提交版本。

最终总复跑结果：**93 个 unittest 测试通过（66项业务＋27项本机HTTP），0失败、0错误、0跳过，退出码0，耗时11.702s**。2026-10-11隔离复核者先原样复跑原63项一次（5.460s通过），随后从真实证据发现拒绝审计目标缺项，新增64–66三项独立回归；原63项设计与期望未改。66业务单独运行5.825s通过，27项独立HTTP修复后单独运行5.957s通过，最后一次统一discover核对93项全部通过。历史失败保留于下文。真实模型接入、人工验收或正式赛题全部完成均未由这些离线测试证明。

## 作者隔离与证据范围

测试由独立验收子代理编写，未参与业务实现，未读取业务或模型 Python 源码。设计依据仅为 `AGENTS.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`spec/test-plan.md` 和公开的 `src/PUBLIC_API.md`。后续接口控制约定更新后，只读取该公开文档，再通过接口观察脱敏响应字段；不依据业务实现猜期望。

业务测试文件：`tests/test_acceptance.py`。运行方法：`tests/README.md`。首次验收作者写测试与记录，业务修复由实现者完成；后续复核仍遵守文件分工和作者隔离。

2026-10-11复核者继续与实现隔离，只读业务规格、公开接口、测试工具及脱敏证据；未读取业务/模型源码或本机密钥配置。复核者原样执行63条、修正真实用例运行器的调用统计，并依据真实审计缺项新增三条拒绝日志回归，原63条保持不变。实际联网及业务修复仍由根代理负责；真实异常用例的独立证据审核另见 `docs/13-real-model-acceptance.md`。

每条测试从独立模拟数据库开始，可信用户默认 alice；数据库放在 `tests/.runs` 下，不清空演示数据。夹具金额为 alice-main 1000000、alice-savings 500000、bob-main 100000 分。固定初始时钟为 2026-10-10 12:00（UTC+08:00），各用例明确调整测试时间。SQL 只访问公开表核对余额、历史、累计、请求、锁定和审计；插入 transfers 或修改账户/订阅是异常前置条件，不代表应用授权用户改库。

`FixedCandidateModel` 与 `BrokenModel` 是**离线测试替身**，没有真实模型调用。`audit_hook` 是公开测试故障注入。测试没有跳过机制；不把未测能力算入66条业务测试。

## 实际运行

在 `C:\fintechathon` 运行：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p 'test_*.py' -v
```

最终原始输出结尾：

```text
----------------------------------------------------------------------
Ran 93 tests in 11.702s

OK
```

退出码：0。原始逐项输出保存为 `evidence/independent-acceptance.txt`，并保存在本次工具调用记录；证据文件顺序保留9.160s失败运行、9.418s成功复跑、补用例时的导入错误、10.511s新增用例后63条成功输出、10.797s原样复跑、2026-10-11的5.460s原63项复跑、5.825s的66项业务输出，以及11.702s的93项业务＋HTTP总复跑。HTTP首轮失败与修复后27项专门输出另存 `evidence/independent-web-acceptance.txt`，均不覆盖失败。本报告列明全部用例的输入、期望、实际和验证方法。

## 66项业务逐项结果

下表每行对应一个 unittest 方法；同一方法中的多个非法类型或表达属于子用例。所有行均已实际运行并通过；32行曾失败，修复后的原样复跑通过，历史单独保留。未运行项另列在后文。公开接口响应断言、公开表前后快照、审计检查均在 `test_acceptance.py` 中可复现。

| 编号 | 输入 / 前置 | 期望 | 实际 | 验证方法 | 最没把握处 |
|---|---|---|---|---|---|
| 01 | 查询 alice 全部余额 | 绿档，只有本人两个账户，金额符合夹具 | success；1000000 / 500000 分，无 bob-main | 响应账户集合与金额 | 浏览器显示未验 |
| 02 | 默认分析本月账单；含上月/失败/未来干扰 | 5970 整数分，历史不变 | 5970 分，历史快照相同 | 响应类型、金额与 transactions 快照 | 真实模型措辞未验 |
| 03 | 10-01 至 10-01，及 10-02 单日 | 两端包含；首日5970、空日0 | 分别5970与0 | 固定日期参数与总额 | 大量日期组合未遍历 |
| 04 | 查询10-01交易 | 绿档，三条本人记录合计5970 | 三条 alice-main，本人记录 | 响应条数、归属、金额 | 浏览器时间展示未验 |
| 05 | 查询本人订阅但未确认，再固定接口确认 | 黄档先不披露列表，确认后仅本人三条 | pending无列表/记录ID；确认后三条，未来5970 | pending全文检查与成功数据 | 自然语言完整对话未验 |
| 06 | 将测试库 alice 订阅设为空，再确认查询 | 空列表、预计0，有可读消息 | 空列表与0，message非空 | 公开表前置与响应 | 空列表文案人工未评 |
| 07 | 新增同用户同名视频订阅，用名字取消 | 歧义拒绝，不猜目标 | rejected，无变更 | 公开订阅表与业务快照 | 联系人重名夹具未验 |
| 08 | 确认取消 sub-video，重查账单/未来，再取消 | 历史5970保留；未来2980；不重复扣款 | cancelled；历史不变；未来2980；余额不变 | 状态、交易快照、账单与订阅数据 | 真实平台行为不在范围 |
| 09 | 给已登记小王转10000分并确认 | 双方余额各减/加10000，两条流水、一笔成功转账和日志 | alice-main990000，bob-main110000，账/流水/日志一致 | 公开表与executed审计 | 同时到达的并发未验 |
| 10 | 前置成功90000，再转10000 | 累计等于100000仍黄档 | 黄档success，累计100000 | transfers前置与响应 | 并发多请求未验 |
| 11 | 前置成功90000，再转10001 | 红档，缺强验证拒绝，无变更 | red/rejected，无确认码、无业务变更 | 档位、业务快照与日志增长 | 强验证成功路径未实现 |
| 12 | 前置99999，先转1，再转1 | 第一笔到100000黄，第二笔到100001红拒绝 | 精确一分边界符合期望 | 整数金额、累计与快照 | 并发边界未验 |
| 13 | main转60000后savings转60000 | 同用户跨账户累计，第二笔红拒绝 | 第一笔success，第二笔red/rejected | 两账户与累计响应 | 多进程未验 |
| 14 | 前置失败/取消各99999、昨日成功99999；今日转100000 | 干扰不计入今日成功累计 | success，今日累计100000 | transfers状态/日期前置与响应 | 未枚举所有业务状态 |
| 15 | clock为UTC 10-09 16:01；夹具含上海昨日/今日成功 | 按上海10-10累计 | success，累计100000，日期10-10 | UTC时钟与shanghai_date | 时区数据库迁移未验 |
| 16 | 上海23:59生成确认，00:01执行 | 用实际执行日累计 | success，新日累计10000 | 推进两分钟与成功响应 | 夏令时不适用于上海 |
| 17 | 黄档60000待确认期间另账户插入成功60000 | 执行前变红，旧授权失效，拒绝 | red/rejected；重复旧确认也拒绝，余额不变 | 前置插入、两次确认与快照 | 真实竞争时序未并发验证 |
| 18 | 待确认后源余额改0或归属改bob | 执行前复检余额与归属 | 两种均rejected，无新增业务变更 | 公开账户表异常前置与快照 | 收款账户变动场景未单测 |
| 19 | 金额bool、0、负、浮点、字符串、None、list、dict | 直接拒绝，不发码不改业务 | 全部rejected，业务相同且审计增加 | 参数子用例与快照 | 最大整数资源边界未遍历 |
| 20 | 未知/删日志/保险意图，tier、confirmed、身份、SQL、command额外字段 | 白名单和字段检查拒绝 | 全部rejected；有intent=unknown审计 | 候选参数与审计 | 任意代码未做执行沙箱测试 |
| 21 | 候选None/字符串/列表/空对象；参数类型、日期、双目标非法 | 直接拒绝，不猜参数 | 全部rejected，无业务变更 | 多种格式子用例 | 尚未做随机模糊测试 |
| 22 | alice查bob余额/交易/账单、取消bob-video、从bob-main转出 | 归属拒绝 | 全部rejected，无披露/变更 | 公开接口与业务快照 | 可信登录正式绑定未验 |
| 23 | 不存在的联系人、账户、订阅编号或名字 | 拒绝并不猜目标 | 全部rejected，无业务变更 | 缺失目标子用例 | 真实模型是否编造日期未验 |
| 24 | 源余额5000，请求10000 | 发码前拒绝余额不足 | rejected，无业务变更 | 公开账户前置与快照 | 并发消费未验 |
| 25 | savings向li转12345待确认 | 展示绑定用户、账户、联系人、金额、影响 | operation含上述参数，未转账 | operation与公开业务表 | 人工可读性未评分 |
| 26 | 待确认时“嗯”“随便”“你看着办”，模型附confirmed/tier | 不作授权、不执行 | 非success，业务不变 | 文本/模型替身与快照 | 中文同义表达未穷举 |
| 27 | “不要执行”“算了”“取消”“等一下”“确认但不要执行” | 取消；旧授权无效 | cancelled，旧码rejected，无业务变更 | handle_text与旧码重试 | 自然语言分词组合未穷举 |
| 28 | cancel接口取消待确认，再重用码 | 取消事件审计，旧码拒绝 | cancelled；旧码rejected；有取消回执 | 状态、快照与audit_events | 无pending取消文案未验 |
| 29 | 待确认后更改金额/联系人/账户或提出另一操作 | 新请求使旧请求失效 | 新响应pending或success，旧确认均rejected | 新旧请求与快照 | 多窗口交互未验 |
| 30 | bob实例确认alice请求，alice随后确认 | 跨人拒绝，不损坏alice合法流程 | bob rejected；alice success | 两个可信用户接口与快照 | 正式认证接入未验 |
| 31 | 五分钟整提交原确认，再提交 | 到期拒绝，旧码不复活，记录expired | expired/rejected，后续rejected，无变更 | 固定时钟与超时审计 | 真实墙钟误差未验 |
| 32 | pending后关闭并重开同用户实例 | 请求失效、旧日志保留、restart追加 | 最终通过：旧码rejected，旧审计前缀相同，restart追加；曾缺事件详IA-004 | 前后审计快照与重启接口 | 进程被强杀场景未验 |
| 33 | 错码→取消换目标金额→错码→重启→错码，再换目标/重启 | 计数1/2/3保留，十分钟锁定不清零 | failures1/2/3；锁定准确10分钟；重启后仍拒绝 | verification_state与业务快照 | 墙钟倒退未验 |
| 34 | 同类三错锁定后取消，改为订阅查询，再小额转账 | 可取消/操作另一类型，同类仍拒绝 | cancel成功；订阅确认成功；transfer拒绝 | 分类接口与持久状态 | 红档独立因素失败未实现 |
| 35 | 三错锁定后推进10分钟，先用旧码再申请新请求 | 旧码失效；新验证成功，清零且记解锁 | 旧码不成功；新success，failures0，解锁记录存在 | 时钟、状态与审计 | 精确锁期前最后一秒未单测 |
| 36 | 一次错码后正确确认 | 未锁定完整成功清零 | failures1→0，success | verification_state与确认接口 | 不同身份因素未实现 |
| 37 | 同一请求成功后再次确认 | 不可再次转账 | 第二次rejected，业务完整快照不变 | transfers唯一笔与前后快照 | 同时执行未验 |
| 38 | 查询后保存旧审计，再转账、拒绝删日志 | 只追加，字段齐全，带时区和可信用户 | 旧前缀相同，ID递增，必需字段存在 | audit_log公开列快照 | 不能证明防管理员篡改 |
| 39 | 通过SQLite尝试UPDATE/DELETE audit_log | 禁止触发器拒绝，旧记录不变 | 两种均DatabaseError，原日志保留 | 数据库规则与快照 | 不抵抗管理员修改触发器 |
| 40 | alice和bob分别查询/取audit_events | 仅返回本人日志 | 两方回执都非空且只含本人 | 用户字段集合 | 真实登录会话未验 |
| 41 | transfer executed审计hook抛异常，再尝试新转账 | 双方/流水/累计回滚并停办后续 | failed，业务快照不变，无成功executed；后续不接办 | 故障hook与全业务快照 | 底层断电提交失败未验 |
| 42 | cancel_subscription executed审计hook抛异常 | 订阅取消与成功日志同事务回滚 | failed，所有业务表不变 | 故障hook与快照 | 磁盘层故障未验 |
| 43 | 审计整体不可用，先查询，恢复hook后再转账 | 失败不披露数据，当前实例停止后续业务 | 查询failed无data，后续failed/rejected，业务不变 | 所有事件hook失败与状态 | 整盘不可写未实测 |
| 44 | 待确认后验证审计全失败，再输错码 | 计数/锁定更新与失败日志原子保存 | failed，verification_state与业务均回滚 | hook、计数快照 | 多进程验证竞争未验 |
| 45 | 正确确认后扫描持久请求/审计/锁定表 | 有效确认码不入库 | 确认码字符串未出现在被测持久表 | 公开表序列化查漏 | 未扫描进程内存 |
| 46 | 无敏感原话，模型异常含模拟密码/密钥/验证码 | failed，异常/日志/模型输入不泄漏秘密，不露堆栈 | failed，秘密与Traceback均不出现，业务不变 | BrokenModel、响应、日志与捕获输入 | 其他秘密格式未穷举 |
| 47 | 原话含模拟password/API key/验证码 | 输入拒绝或脱敏，秘密不进模型/日志/响应 | 安全拒绝或失败；秘密均不出现，业务不变 | 捕获模型输入与审计序列化 | 正式凭据格式待接入确认 |
| 48 | 模型超时、损坏JSON、None、列表 | 失败/拒绝，不猜候选不发码 | 全部failed/rejected；无业务变化；有新审计 | 四种离线故障替身 | 实际网络故障未验 |
| 49 | 注入改档、自称bob、模型tier/confirmed、run_shell | 直接拒绝，身份/权限不受模型控制 | 全部rejected，不发码，业务不变 | handle_text不可信候选子用例 | 无法据关键词证明完整注入防御 |
| 50 | 空白、50000字、SQL样文本 | 不崩溃、不改业务/删表 | failed/rejected，业务与审计表在 | 文本子用例与公开表 | 更大资源压力未验 |
| 51 | 逆序列出bill→subs→cancel；重复resume；逐节点确认 | 依赖顺序正确；重复resume同码；两黄节点独立确认 | bill先success，subs pending同码同ID；cancel另ID；全部最终success | steps、原码重用拒绝、业务快照与step_id审计 | 本项只测固定候选；真实模型计划另有独立证据文件 |
| 52 | 空计划、重复ID、未知依赖、自环/循环、非法工具、假completed、依赖类型、9步、额外confirmed | 非法计划拒绝，不授权/改业务 | 全部rejected，无确认码 | 候选图子用例与快照 | 更复杂图随机生成未验 |
| 53 | bill之后节点使用bob源账户/bob订阅/额外tier | 不让非法节点进入授权执行 | rejected，无确认码/转账/余额改变 | 图节点参数与公开表 | 此项不要求绿色前置查询一定未读 |
| 54 | subs→pay，取消subs待确认 | 前置取消停止pay | resume停止，不发码，无转账 | cancel、resume、steps与快照 | 多依赖合并图未单测 |
| 55 | first transfer→later transfer；首笔执行前累计变红 | 首笔拒绝，后继停止 | confirm rejected；resume停止，无后继变更 | transfers前置、steps与业务快照 | 真实竞争未并发验证 |
| 56 | subs→pay，五分钟后confirm首节点再resume | 前置过期停止pay | 到期拒绝/过期，resume停止无新码 | 时钟与业务快照 | 无confirm路径另列57 |
| 57 | subs→pay，五分钟后直接resume | resume自身检查到期，清旧授权，停止后继 | 停止响应，无确认码；旧confirm rejected；expired审计存在 | 推时钟、resume、旧码与快照 | 实际计时器调度未验 |
| 58 | subs→pay，在subs pending时interrupt_plan | 停止未完成节点，旧授权失效，审计interrupted | 旧confirm rejected，resume不再pending/success，业务不变 | plan回执、快照与审计 | 补偿回退未实现 |
| 59 | pay成功→cancel pending时takeover_plan | 保留已完成转账，停止取消，旧授权失效 | pay success保留；cancel未成功；余额990000/110000不反转 | plan逐项回执与业务快照 | 人工处理渠道未验 |
| 60 | subs→pay pending时重启，再确认/resume | 内存计划与旧授权均不可恢复 | 旧confirm rejected，resume旧plan rejected，无业务变更 | 新实例与快照 | 未提供持久计划恢复能力 |
| 61 | subs确认成功但未resume时，提出余额查询新任务，再resume旧plan | 新任务停止旧plan后续取消，不能续用旧授权 | 新查询success；旧resume rejected无码；sub-video仍active | 公开新任务、旧plan回执与业务快照 | 多窗口同时发起未验 |
| 62 | wang转10000展示bob-main后，SQL将联系人映射改alice-savings；提交并重用旧确认；模型额外提供binding | 真实目标绑定变化使旧授权立即失效；不转到新账户；模型不得指定绑定 | 两次confirm均rejected，全部业务快照相同；额外binding字段在顶层/params均rejected | 公开contacts前置、operation目标、原授权重试及业务快照 | 真实并发映射更新未验 |
| 63 | cancel传入list、123、dict、bool、float、空串后查询余额 | 非法ID拒绝并审计，健康存储不停办，后续合法查询成功 | 全部rejected；审计新增；随后查询success且只含本人账户，业务不变 | cancel参数子用例、审计条数和后续公开查询 | 未对所有ID格式做随机生成 |
| 64 | 请求取消不存在的银河影院会员 | not_found/rejected，拒绝审计保留非秘密subscription_name；业务不变 | 同请求rejected日志包含银河影院会员；四表相同 | 公开propose、request_id关联、解析params_redacted | 修复前问题直接来自真实证据，未再跑旧实现 |
| 65 | transfer候选顶层/params额外提供password、api_key、authorization、otp、authenticator_secret | 非法额外字段拒绝，秘密不进入响应/audit/requests | 10个子用例全部rejected，模拟秘密值均未持久化，四表相同 | 公开候选、审计与requests全文串行化查漏 | 未穷举所有认证字段拼写与未知秘密格式 |
| 66 | 有效转账确认码塞进新候选顶层、params、无标签订阅目标或验证码标签目标 | 新非法任务拒绝并使旧确认失效，确认秘密不进审计/requests | 4个子用例rejected，旧确认重放rejected，有效码未持久化，无转账 | 先公开pending，记录码仅在测试内存；拒绝后快照、重放与持久记录检查 | 无标签六位文本按公开脱敏规则处理；更复杂编码形式未验 |

## 本轮曾出现的失败与修复

以下记录保留，不能只展示最后一次绿色输出。

### IA-001 · 测试连接未关闭导致Windows清理失败（测试工具问题）

- 输入：第一版47条测试，每条结束后清理临时SQLite文件。
- 期望：连接关闭后删除该条测试创建的目录。
- 实际：`Ran 47 tests in 7.526s; FAILED (failures=1, errors=40)`；40个ERROR涉及 `WinError 32` 文件被本进程打开。Python SQLite连接的 `with` 管理事务，不负责关闭连接，测试作者误用造成占用。
- 是否运行：是。不是业务安全失败，也没有把这些ERROR计为通过。
- 验证方法：测试代码改用 `contextlib.closing`，写前置时显式commit；再次48条实际运行全部通过（7.873s）。没有修改业务预期。
- 最没把握处：首次工具输出很长，工具截断了部分重复堆栈；保留原始总计与根因，未虚构每份完整堆栈。

### IA-002 · 敏感输入的测试状态假设需要规格澄清（测试设计问题）

- 输入：包含模拟password/API key/验证码的原话，模型替身准备抛异常。
- 期望：敏感内容不得进入模型、审计或响应。原测试额外假设必须走到模型并返回failed，这不是规格要求。
- 实际：输入层直接 `rejected`，reason=`secret_input`，没有调用模型。首次因此产生1个FAIL，但没有出现秘密泄漏或业务变更。
- 是否运行：是。
- 验证方法：作者向实现者报告并说明依据后，将两种需求分成独立用例：敏感原话允许安全拒绝或脱敏后失败；普通原话触发模型异常仍必须failed且脱敏。最终两条均通过。未放宽秘密保护或执行权限要求。
- 最没把握处：需继续用真实模型服务的错误格式检查脱敏完整性。

### IA-003 · 重复resume回执缺少原确认码（公开契约缺陷，已修复）

- 输入：提交bill→subs→cancel依赖图（节点逆序排列），到subs pending后重复 `resume_plan(plan_id)`。
- 期望：公开契约规定pending含confirmation_code；重复resume不得生成新确认，应返回相同request_id和原内存确认码。
- 实际：初次DAG验收 `Ran 59 tests in 10.076s; FAILED (errors=1)`。58条通过；这一条返回pending和原request_id，但缺confirmation_code，触发 `KeyError`。
- 是否运行：是。
- 验证方法：原验收者将KeyError写成明确的字段存在断言，业务期望不变；实现者修复后原59条复跑通过（8.230s），再加入直接resume检查到期的回归用例，60条通过（9.611s）。公开契约进一步明确新任务停止旧计划未完成节点，新增对应用例后61条通过（7.778s）。
- 最没把握处：只能证明本次公开接口回执，不替代浏览器刷新/重提的人工检查。

### IA-004 · 关闭后重新构造缺少restart回执（最后复跑发现，已修复）

- 输入：本人转账pending后保存audit快照；调用close；构造相同用户的新实例。
- 期望：历史日志内容不变，旧请求失效，公开约定的restart事件追加。
- 实际：原样61条复跑，60通过、1FAIL。历史前缀相同，但新增日志不含 `event='restart'`，失败于 `test_acceptance.py:551`。最近业务调整将close也记录会话结束并使pending失效，但独立测试不读取实现，不推断其内部原因。
- 是否运行：是；首次 `Ran 61 tests in 9.160s; FAILED (failures=1)`，退出码1。实现者补齐每次构造会话的restart回执后，原作者再次运行：`Ran 61 tests in 9.418s; OK`，退出码0。
- 验证方法：两次原始输出按运行顺序保存于 `evidence/independent-acceptance.txt`。原61条设计与预期未改；关闭会话的session_closed记录保留，重启断言重新通过。
- 最没把握处：当前测试检查公开会话接口重开可追溯，不证明进程被强杀时一定存在session_closed日志。

### IA-005 · 联系人真实收款账户变化仍使用旧授权（同行发现，修复后独立通过）

- 输入：transfer从alice-main给wang转10000，等待回执展示真实目标bob-main；测试SQL将contacts的account_id改为仍合法的alice-savings；再提交旧confirm。
- 期望：确认绑定真实收款账户；目标改变使旧授权立即失效并rejected，所有余额与转账记录不变。模型不能提供binding来改写代码解析的目标。
- 原实际：**同行评审报告**旧版返回success并转到新target alice-savings。本作者没有运行修复前旧版，不把转述记为本人复现；该报告由实现者传递。
- 是否运行：同行报告旧版已复现；本作者实际运行修复后的新增第62条，并在最终63条全量运行中通过。
- 验证方法：只读更新PUBLIC_API，通过公开接口和允许的contacts异常前置检查：待确认operation显示bob-main，换映射后旧确认/重复旧确认都rejected，accounts/subscriptions/transactions/transfers快照不变；模型提供顶层/params的binding_json字段都拒绝。
- 最没把握处：SQL前置验证了目标变化时复检，未证明多进程并发映射更新的所有竞争时序。

### IA-006 · 非法cancel ID误报存储故障并停办（同行发现，修复后独立通过）

- 输入：cancel([])、cancel(123)、cancel({})，再调用合法本人余额查询。
- 期望：非法类型直接rejected并审计，不能熔停健康账本；合法查询仍success。
- 原实际：**同行评审报告**旧版返回failed，reason=`storage_unavailable`并halted。本作者未运行旧版，不将转述称为自己的实测。
- 是否运行：同行报告旧版已复现；本作者实际运行修复后新增第63条。进一步加入bool、float、空串子用例，全部通过。
- 验证方法：每次非法cancel后检查rejected、审计条数增加、业务快照相同；随后余额查询success且只有alice两个账户。最终63条全量运行通过。
- 最没把握处：没有随机生成所有ID格式，但规范中的非法类型边界已覆盖。

### IA-007 · 新增测试补丁插入位置错误（测试工具问题，已修复）

- 输入：加入62/63两条方法后首次导入测试模块。
- 期望：原61条方法保持原逻辑，新方法正常加载。
- 实际：补丁误插到原方法中间，`IndentationError: unexpected indent`；unittest仅运行加载错误占位 `Ran 1 test in 0.000s; FAILED (errors=1)`。这一输出不计任何业务验收通过。
- 是否运行：是，原始加载错误保存在evidence文件。
- 验证方法：测试作者恢复原方法完整结构，不改变其断言与业务期望，再运行全部63条，10.511s全部通过。
- 最没把握处：该错误只涉及测试文件加载，不能用于推断业务行为。

### IA-008 · 不存在订阅的拒绝审计丢失目标（真实证据发现，离线修复通过）

- 输入：真实LA-06“请取消我的银河影院会员”，模型明确提出subscription_name=银河影院会员。
- 期望：not_found/rejected且不改业务；拒绝日志依docs/01第7节与US-30保留非秘密目标和关键参数，同时认证秘密不入库。
- 原实际：2026-10-11 10:15首轮脱敏证据中，同请求拒绝日志params_redacted={}，原话也整体省略；四表不变，但仅靠审计无法复查目标。复核者直接读取该证据，未读取业务源码。
- 是否运行：真实首轮由根代理运行；复核者独立审阅并报告。实现者修复后，复核者新增64–66并实际运行66项全量（5.825s、OK、退出0）；原63项不改。
- 验证方法：只按更新PUBLIC_API安全目标字段契约检查：非秘密subscription_name保留，额外认证字段值不写入；有效确认码进入候选或目标文本时仍脱敏，旧授权重放拒绝，四张业务表无变化。2026-10-11 10:23修复后真实六条复跑也已独立复审通过，LA-06审计保留目标；完整旧证据另存real-model-acceptance-before-audit-fix.json，最新结论详见docs/13。
- 最没把握处：当前独立离线回归覆盖指定字段/四种码位置，未知编码和所有秘密格式未穷举。

## 独立本机HTTP验收（27项修复后通过，首轮失败保留）

另一个隔离HTTP测试作者只依据AGENTS、权限表、用户故事、PUBLIC_API与WEB_API编写 `tests/test_web_acceptance.py`，没有阅读src/web.py或业务/模型实现，也没有读取.env或请求真实模型。每个主测试新建tests/.runs临时模拟库；SQLite服务在服务线程构造和关闭，客户端通过真实127.0.0.1 HTTP交互。model_configured=True仅标记注入的离线固定候选替身可用，不是真实服务配置/接通证据。

最终单独复跑：**27/27主测试通过，5.957s，退出码0，0失败/错误/跳过**。其后统一93项总复跑再次通过。原始输出保存在 `evidence/independent-web-acceptance.txt`，保留首轮27个主测试中25通过、2失败、6个失败子场景（5.983s，退出1，FAILED (failures=6)）。固定/app.js资源200与未知POST资源404的公开期望保持不变；修复后原作者原样复跑，没有放宽已明确的期望。

运行命令：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p test_web_acceptance.py -v
```

下表每项均实际运行；编号按测试输出名称顺序归档，和66项业务测试分开计数。首次实际用于保留问题，最后一列为修复后原样27项复跑与统一93项复跑的共同最终结果。

| 编号 | 输入 / 前置 | 期望 | 首轮实际 | 最终实际 |
|---|---|---|---|---|
| HTTP-01 | Content-Length缺失、0、-1、非数字、8193 | 400，保留pending，审计追加，业务不变 | 通过 | 通过 |
| HTTP-02 | 账单查询→订阅查询/确认→视频退订/确认 | 实际5970整数分；订阅先pending后只列本人；退订保留历史 | 通过 | 通过 |
| HTTP-03 | transfer pending后cancel {}或request_id:null | cancelled，旧confirm rejected，无转账 | 通过 | 通过 |
| HTTP-04 | 额外password/api_key/authenticator_secret/otp→有效确认→查询/审计 | 400；有效码/CSRF/合成凭据不进requests、audit、模型输入、服务输出及审计响应 | 通过 | 通过 |
| HTTP-05 | Origin:null/远端/https同host/localhost与127.0.0.1混用 | 403，原pending可继续确认 | 通过 | 通过 |
| HTTP-06 | Sec-Fetch-Site cross-site/same-site | 403，审计追加，业务/pending不变 | 通过 | 通过 |
| HTTP-07 | JSON顶层text重复或嵌套id重复 | 400，不调用模型 | 通过 | 通过 |
| HTTP-08 | 重复Host/Origin/X-CSRF-Token/Content-Length | 400或403拒绝，保留pending | 通过 | 通过 |
| HTTP-09 | 合法JSON加空白至8192字节，同体8193 | 8192可办理，8193为400，保留pending | 通过 | 通过 |
| HTTP-10 | 七个POST端点额外user_id:bob或confirmed:true | 400，身份/授权不被请求覆盖 | 通过 | 通过 |
| HTTP-11 | Host为localhost:端口、同源Origin、same-origin fetch | 200业务success，只列alice两个账户 | 通过 | 通过 |
| HTTP-12 | 缺失或错误CSRF | 403，有效pending仍可确认 | 通过 | 通过 |
| HTTP-13 | JSON NaN/Infinity/-Infinity | 400，不调用模型，不改业务 | 通过 | 通过 |
| HTTP-14 | 数组/null/字符串/数字/bool/损坏JSON/非法UTF-8 | 400，保留pending | 通过 | 通过 |
| HTTP-15 | bill→subs计划，重复resume、interrupt、旧confirm、再resume | 重复resume保持同码/编号，中断后旧确认与续办不可执行 | 通过 | 通过 |
| HTTP-16 | 计划takeover→旧confirm→resume | 接管后剩余授权停止 | 通过 | 通过 |
| HTTP-17 | GET /api/session | 固定alice，只返回user_id/csrf_token/model_configured/simulated；无配置/账本/业务变更 | 通过 | 通过 |
| HTTP-18 | GET /、/app.css、/app.js | 200、正确类型、安全头，静态不嵌CSRF | /与CSS通过；/app.js实际503，失败 | 通过 |
| HTTP-19 | 合法10000分转账→confirm一次→同编号同码重放 | 只成功一次，双方990000/110000，储蓄500000；两流水、一转账、一次成功审计；重放rejected | 通过 | 通过 |
| HTTP-20 | Transfer-Encoding chunked/identity，含或无Content-Length | 400，保留pending | 通过 | 通过 |
| HTTP-21 | 未知GET、.env、源文件、库文件、明文/编码路径遍历 | 404，追加拒绝审计，pending/业务不变 | 通过 | 通过 |
| HTTP-22 | 合法POST {}至/candidate、/api/candidate、/api/sql、/api/shell、/api/unknown | 404，无任意候选/SQL/shell入口 | 五项实际400，失败；组末原有效confirm仍success | 通过 |
| HTTP-23 | PUT/PATCH/DELETE/OPTIONS/HEAD/TRACE | 405、安全头、拒绝审计，保留pending | 通过 | 通过 |
| HTTP-24 | Host缺失/远端/无端口/端口不匹配 | 403，保留pending | 通过 | 通过 |
| HTTP-25 | Content-Type缺失/text/plain/form | 400，保留pending | 通过 | 通过 |
| HTTP-26 | message缺text或text为null/bool/整数/list/object | 400，保留pending | 通过 | 通过 |
| HTTP-27 | 三个计划端点plan_id为null/bool/整数/list/object | 400，保留pending | 通过 | 通过 |

验证方法：边界拒绝用完整accounts/subscriptions/transactions/transfers快照、原requests行、审计旧前缀/新增rejected及模型调用计数检查；一组边界后原合法确认仍能成功。HTTP-22首轮在状态码断言处失败，其每次审计/快照后续断言当时未执行；修复后五路径均404，后续审计/业务/pending/模型调用断言全部执行通过。安全头核对no-store、nosniff、DENY、本站CSP且无CDN/CORS许可；资金核对双方余额、两条流水、一笔成功转账及关联成功日志；秘密检查仅使用内存有效码/CSRF和合成凭据，不导出本机秘密。

最没把握处：首轮/app.js可能仍处界面开发中的临时缺文件；完成后才据实际复跑确认三个静态资源均200。重复安全头契约未指定400/403的优先级，因此该项允许两者，但未知路径明确要求404。离线HTTP不能证明真实模型理解、浏览器DOM点击/XSS执行、人工演示、远程登录、真实银行、MFA或沙箱。首轮失败仍保留，不把后来通过说成从未出现问题。

## 尚未完成的验收与能力边界

1. **66条离线不证明真实模型；真实证据已另审核。** 本报告的66条仍使用离线替身，不能算真实模型调用。2026-10-11根代理另运行正常三方向五请求及六条独立异常用例；隔离复核者已检查脱敏公开结果、候选（异常用例）、usage、四表与审计。10:23修复后六异常均符合设计，其中5条真实返回共4007 tokens，LA-05输入层阻断；LA-02携带bob-main候选实际触发代码归属拒绝；LA-06初始拒绝日志目标缺项已由新增离线回归和最新真实复跑验证修复。正常复跑、初始较窄结果、旧401/网络失败及过度澄清历史均见docs/13，不再将旧认证失败写成当前尚未接通。
2. **队友人工未验收。** 本报告不是队友1/Codex API或队友2/DeepSeek Harness的人类验收结果，未声称他们已跑测试；三场景演示、截图/录屏与解释追问需另做。
3. **并发验收未完成。** 已验证串行重复执行及公开SQLite前置建立的执行前状态变化；没有两个同时执行请求的线程/进程压力证据，不能据此声称并发彻底解决。
4. **真实多因素认证和隔离未实测。** 红档拒绝路径已测；未测试两个不同身份因素成功后执行，也未做文件/网络/进程/资源越界尝试。屏显六位码仅为操作确认。
5. **候选依赖执行通过，完整任务规划/补偿回退未完成。** 本报告的固定候选图结构校验、逐节点确认、失败停止、中断、接管与重启失效已测。另有evidence/real-model-plans.json真实模型计划集成记录，不能据66条离线本身证明自动规划已完成；既有短计划证据不覆盖任意复杂任务或完整补偿。已成功转账保留，已取消订阅不能自动恢复。
6. **审计故障证据限定于公开hook。** 已验证成功日志失败回滚、计数与失败日志原子性及实例停办；未模拟真实断电、硬盘损坏或数据库提交底层故障。只追加规则也不抵抗管理员直接改文件/触发器。
7. **本机HTTP独立27项通过，交互渠道人工另验。** JS固定资源/未知POST状态码初次失败后修复，原样27项与统一93项全部通过，历史保留。真实浏览器的确认、刷新、重复点击、过期显示、图状态与可读性不由离线HTTP/Python测试证明；根代理另做真实浏览器复演，不自动变成两位队友人工验收。正式APP/IM渠道认可需另外核实。

未运行项不得列为“通过”，未实现项不得写成“已满足正式赛题要求”。后续业务改动需用同一命令复跑并记录新版本；规格澄清才允许调整期望。

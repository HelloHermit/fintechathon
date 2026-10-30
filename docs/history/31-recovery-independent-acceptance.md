# 31 · 任务保存、恢复与接管独立验收设计

日期：2026-10-23（会话日期）；执行证据 UTC 日期为 2026-10-24。最终独立判读：**第四轮 37 个方法全部通过，0 失败／错误／skip，27.953 秒；包括 R-05 两个提交前到期子例及 R-14 六个恢复取消子例。** 本结论限于本套公开契约自动验收，不替代整体 task2 交付、既有 159 项最终回归、task1 隔离交付、真人手机／真实终端／队友人工核验或正式赛事验收。第 3 节的“未运行”列保留为最初设计时状态，实际执行以第 6、7 节为准。

独立作者只依据 `AGENTS.md`、任务 2 原文 `C:/Kind_Hermit/Kind_Hermit/task2/未命名.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`docs/30-recovery-acceptance-matrix.md`、`src/PUBLIC_API.md`、`src/WEB_API.md` 和先于测试冻结的 `src/RECOVERY_API.md` 确定期望。未阅读 `src/bank.py`、`src/web.py` 或其他业务实现，未接触日常数据库、真实凭据或真实模型配置。执行由根实现者完成；本作者阅读原始 JSON 独立判读，不以阅读实现解释结果。

## 1. 交付文件及执行边界

- 正式文件：`tests/test_recovery_independent.py`。在 task1 旧回归结束、task2 公开接口冻结后发布。原草稿及三轮源码分别保留在 `tests/.runs/recovery-independent-draft.py`、`tests/.runs/recovery-independent-source-first-ee62f3f8a013.py`、`tests/.runs/recovery-independent-source-second-6fd3141e7e1d.py`、`tests/.runs/recovery-independent-source-third-762fe0e2b317.py`；第四轮发布前草稿为 `tests/.runs/recovery-cancel-independent-draft-v4.py`。
- 37 个固定测试方法 `test_r_01_...`～`test_r_37_...`，对应 docs/30 的每条期望；参数、阶段及故障类型使用子用例。没有 skip、预填通过、调用实现私有函数或对失败降低期望的分支。
- 测试采用 Python 标准库。每次运行、每条测试都在 `tests/.runs` 内新建独立工作目录及模拟 SQLite 库；明确指定目录，不依赖系统临时目录权限，不使用 `data/bank.db`。
- Python 入口只使用公开 `BankService`；HTTP 只使用公开 `LocalServer/BrowserHandler` 依赖注入和离线固定候选模型。离线模型不证明真实模型接通。
- 根实现者负责执行并生成唯一新证据 JSON；作者不自行运行或修改业务实现。R-05 新子例第三轮起实际通过，R-14 新取消子例第四轮实际通过，不将修后通过改写为独立作者修前复现过开发失败。

冻结执行命令（匹配实现就绪后）：

```powershell
<本机可用Python> -B -X utf8 tests/test_recovery_independent.py
```

实际 Python 为 `C:/Users/KindHermit/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。脚本不需要联网、安装、提权或真实因素；不要向它传入日常库或凭据。

## 2. 输入与观察方法

基础时钟固定上海 `2026-10-23T10:00:00+08:00`，跨午夜与到期用例由测试自己的可注入时钟推进。基础账户、联系人、三项订阅、本月账单 5970 分完全沿用公开夹具。

`P=bill -> pay(T100) -> subs`；T100 为 alice-main 向 wang 转 10000 分。正常一次提交后必须是 alice-main=990000 分、alice-savings=500000 分、bob-main=110000 分；本笔成功 transfers 仅一条、累计只增加 10000 分。未确认时保持初始资金。

观察来源：公开响应、历史计划与接管接口，及公开表 accounts、subscriptions、transactions、transfers、requests、verification_state、audit_log、recovery_plans。只改独立临时库中的公开管理员异常夹具；不能把直接改库当成应用授权。检查资金、流水、请求、节点实际结果、追加审计及原记录保持，不只看 status 或提示文字。

公开新增契约中的节点 `result` 按实际成功工具的 `data` 保存；例如 bill 的历史结果为 `result.actual_expense_cents=5970`。重启旧 pending 对应请求与节点终结为 cancelled、原因 session_restarted，原 pending 事实留在 attempts。

## 3. 37 组固定测试与参数范围

| 编号 | 测试覆盖 | 当前实际 |
|---|---|---|
| R-01 | 待确认计划在独立子进程退出后，父进程重开同库并核对全图与历史 | 未运行 |
| R-02 | bill 提交前注入异常，失败原因及依赖阻断跨重启保留 | 未运行 |
| R-03 | 首节点提交前真实退出，已保存整图仍可反复只读查看 | 未运行 |
| R-04 | 原 5 分钟内重启，旧节点确认仍拒绝，且有重启关联审计 | 未运行 |
| R-05 | 业务与恢复同意各在 300 秒、301 秒边界失效；新审核不得复活旧编号 | 未运行 |
| R-06 | 无新同意的 resume 拒绝；反复 prepare 不延期、不执行、不泄露订阅 | 未运行 |
| R-07 | 新恢复同意不动业务；新节点 ID 与单独确认后仅成功一次，旧尝试保留 | 未运行 |
| R-08 | 首次持久计划保存失败，首节点及后续都不执行、不冒称可靠保存 | 未运行 |
| R-09 | pay 提交前 `os._exit(71)`；父进程核对扣入账、流水、成功审计及节点结果一并回滚 | 未运行 |
| R-10 | pay 提交后响应前 `os._exit(72)`；父进程辨认真实已提交结果，恢复不重做 | 未运行 |
| R-11 | 已成功 pay 的重复恢复、推进与旧确认，不产生第二笔；subs 仍需新确认 | 未运行 |
| R-12 | 同会话多次 resume 保留同一请求和期限 | 未运行 |
| R-13 | 两线程分别持有公开服务，屏障同步竞争恢复审核与推进；重复确认仍至多成功一次 | 未运行 |
| R-14 | 中断、重复中断、重启、旧确认拒绝，成功前序保留 | 未运行 |
| R-15 | pay 已提交后中断，明确保留 10000 分实际结果及未执行后继 | 未运行 |
| R-16 | bill 故障、pay 待确认、pay 已提交三个阶段均有真实接管队列／详情／登记入口 | 未运行 |
| R-17 | 可信所有者身份、时间、处置追加历史及关闭跨重启保留；关闭不伪造金融结果 | 未运行 |
| R-18 | bob 的所有读取、恢复、中断、接管、处置均不能取得 alice 权限；列表按用户过滤 | 未运行 |
| R-19 | 失败、取消、过期、拒绝四种前置均不能跳过并执行后继 | 未运行 |
| R-20 | 两次 transfer 失败跨重启及恢复保留；新请求第三错锁十分钟，取消不清零 | 未运行 |
| R-21 | 锁定跨重启／换账户／降金额保持；599 秒拒绝，600 秒到期可新申请 | 未运行 |
| R-22 | 余额不足／账户归属变化，分别发生于恢复展示前和新确认提交前 | 未运行 |
| R-23 | 其他本人账户当日累计 95000 分，使 T100 变为 105000 分红档并拒绝 | 未运行 |
| R-24 | 上海 23:59 到次日 00:01，使用新日期、期限和授权 | 未运行 |
| R-25 | 联系人映射、联系人 ID、金额、恢复绑定或 plan revision 变化使旧同意失效 | 未运行 |
| R-26 | 新用户任务作废旧剩余计划；重启后只能查询／接管，不能恢复复活 | 未运行 |
| R-27 | 成功审计故障回滚本笔业务、成功节点与确认消费；同会话停止后续业务 | 未运行 |
| R-28 | 恢复许可／中断／接管／处置审计故障，不授予未审计许可、不谎报已可靠保存 | 未运行 |
| R-29 | 旧审计逐字段不变，只追加且可关联 plan/step/request/user；公开防删改约定保留 | 未运行 |
| R-30 | 历史响应、快照、请求和审计不保存／返回码；认证标记备注整体脱敏 | 未运行 |
| R-31 | 已提交转账后请求撤销／退款／反转仍拒绝，本地跟进登记不产生逆向流水 | 未运行 |
| R-32 | 取消 sub-video 后失败／重启仍 cancelled；实际 5970、预计 2980，不自动恢复 | 未运行 |
| R-33 | 新补偿意图及伪造“退款完成／银行已确认”等处置枚举均拒绝 | 未运行 |
| R-34 | 未登记红档拒绝；独立临时合成两因素验证通过后红档业务仍拒绝 | 未运行 |
| R-35 | 坏 JSON、缺节点、错误金额类型、环、错误用户五类损坏只隔离该计划，健康计划保持 | 未运行 |
| R-36 | ID 类型／长度／路径形式、恢复码类型／Unicode／长度、重复关闭，均安全拒绝或明确幂等 | 未运行 |
| R-37 | 七条新 HTTP 路由严格守卫；当前确认不被非法网络请求破坏；HTTP 重启恢复全链及实际处置 | 未运行 |

R-13 的两线程分别在线程内构造和关闭服务，不把单一 SQLite 连接跨线程当作并发能力。该测试能证明指定竞争用例中的资金幂等，不能证明生产并发吞吐量。

R-37 对每条新路由分别投递旧 CSRF、外源 Origin、cross-site Fetch 标志、额外 JSON 字段、重复 JSON 键、重复 CSRF 头。一般格式拒绝期望 400、来源／CSRF 拒绝 403；重复认证头可返回 400 或 403，前提是拒绝且无业务副作用。另建 HTTP 重启夹具，用真正前一会话的 CSRF 验证失效，然后完成恢复准备、固定恢复同意、新节点确认及一次性转账。全程只监听回环地址。

## 4. 进程、证据与失败历史

真实退出证据不是 close 后重建对象：父进程启动同一测试脚本的专用 child 模式；child 只调用公开接口、公开 checkpoint_hook，并在指定时刻自行 `os._exit(71/72)`。父进程检查实际退出码后，在同一独立临时库重新构造服务、读取持久计划并核账。不向正式 HTTP 或 CLI 添加故障、退出或绕权入口。

每次实际运行生成唯一 `evidence/recovery-independent-<UTC时间>-<随机ID>.json`，以排他新建模式保存，既有首轮失败与历史文件不会覆盖。报告包括：37 组实际执行数、失败／错误／skip 数、每组状态／时间／失败原因、进程退出观察、资金及任务关键轨迹、测试文件／公开契约／矩阵指纹。根执行者另附本轮实现源码指纹及运行命令，作者不通过读取实现来取得它。

测试日志和报告会脱敏当次已知确认／恢复码与合成因素。测试结束只清理自己 `tests/.runs` 下新建目录中的临时库；报告保留输入约定、预期、实际失败与关键观察。若执行者希望保留原始临时库作进一步核对，应在执行前由根实现者明确调整保存策略，并继续确保不接触日常库或真实秘密。

发生失败时先保留该次新报告，按输入／期望／实际／是否运行／验证方法／最没把握处交问题单；修后再生成新报告并关联首轮失败。最终通过数、运行耗时、实际文件及回归结果须由真实执行填入新交付，不能把本文“设计已写”改成“已通过”。

## 5. 最没把握与不能证明的范围

本轮公开契约范围内没有未解决的独立失败。控制接口的具体字段、表名及故障点以本次冻结指纹为准；以后若实现需要改变，先说明依据并更新契约，再由独立作者评估测试，不能因出现失败倒改安全标准。本报告不将自动用例扩展为未经运行的真人或正式渠道结论。

本套 Python／HTTP 自动用例不证明浏览器页面布局和控件流程、真人处理、手机强验证、真实终端无回显、银行客服渠道、正式竞赛提交或完整可逆业务补偿。红档继续拒绝；恢复订阅／退款等新增权限规则未冻结，本轮不得以测试便利扩工具白名单。

## 6. 实际执行历史与独立判读

| 轮次 | 测试源码 SHA256 | 实际结果 | 原始证据 |
|---|---|---|---|
| 首轮 | `ee62f3f8a0133def2fdcc8e84ee915021febe23b49d861c3fc8c9a5a8cf47cd0` | 37 方法运行，1 failure／36 errors／0 skip；不合格，不能写成 36 项通过 | `evidence/recovery-independent-20261024T051841529277Z-9d6c47ef10.json`；外层 `evidence/recovery-run-20261024-051840-665038.json` |
| 第二轮 | `6fd3141e7e1deb23a7811823805d84c178cce5643a5432ab6e5c61e6172b12d5` | 37 方法全部通过，0 failure／error／skip，脚本 23.235 秒 | `evidence/recovery-independent-20261024T052124383310Z-90cb5b1cb4.json`；外层 `evidence/recovery-run-20261024-052123-584424.json` |
| 新 R-05 子例首轮／全套第三轮 | `762fe0e2b317afb56e9e9c13f91293d66cc55761a1dfeaeb9761459cca319120` | 37 方法全部通过，0 failure／error／skip，脚本 25.672 秒 | `evidence/recovery-independent-20261024T052838249618Z-157bc82534.json`；外层 `evidence/recovery-run-20261024-052837-361981.json` |
| 新 R-14 取消子例首轮／全套第四轮 | `e34ef950537004795e63dd16c3e8d074e59367656d935738ed6e741b8119a265` | 37 方法全部通过，0 failure／error／skip，脚本 27.953 秒 | `evidence/recovery-independent-20261024T053651853018Z-9078e8549c.json`；外层 `evidence/recovery-run-20261024-053651-049133.json` |

首轮测试自身问题：`with sqlite3.connect(...)` 只提交／回滚事务，不保证关闭连接；5 处观察／管理员夹具连接未及时关闭，Windows 清理临时库出现 WinError 32。只改为 `contextlib.closing`，写夹具另保留连接事务上下文；清理断言、验收断言均未弱化，37 方法全部保留。首轮源码及 JSON 原样归档。R-18 另有真实接口回执差异：bob 对 alice 的 review 调用恢复确认，实际 rejected/invalid_recovery_confirmation，公开契约要求统一 not_found_or_not_owned；这是原因码不一致，首轮证据不支持宣称资金越权或泄漏。

第二轮逐项核对 37 个 R 编号齐全、每组 actually_run=true、status=passed、errors=[]。外层 exit_code=0，源码前后指纹字典相等，保护文件前后指纹字典相等；该轮版本指纹为 `6e9eef6ee11789cb7d359c4c65f9aec2134273e47e2ca2dbcb0cc76e71e72340`。作者只读取外层指纹结果，没有读取受保护日常库内容或业务源码。

关键实际轨迹：R-09 子进程确为退出 71，父进程重开后双方初始余额保持、成功转账 0、流水总数仍 7；R-10 确为退出 72，父进程读到 alice-main=990000、bob-main=110000、本笔 10000 分成功一次、流水总数 9。R-13 两个竞争者一个 rejected，另一个成功授权、新确认成功后重放 rejected，最终只有一笔 10000 分；没有线程异常。R-18 后端修后 bob 的相关拒绝日志统一 not_found_or_not_owned、初始资金保持。

第二轮后的补充发现来自开发者，原始观察为 `tests/.runs/task2-backend-stage/expiry-checkpoint-2zu7m_7p/observation.json`：公开 `node_before_commit` 回调正常返回，仅把注入时钟推进到 expires_at，响应仍 success、transfer_count=1。该文件是**开发发现，独立作者没有运行复现**，不能混成第二轮独立失败或宣称已独立复现。公开规则已要求 now>=expires_at 失效、提交前复检，因此新增 R-05 子例不改变业务期望或权限范围。

新增 R-05 子例分别在 node_before_commit 正常返回时把时钟推进到期限恰好到达／超过 1 秒；此前对该 transfer 产生两次有效确认失败。第三轮独立记录显示两种情况均 checkpoint_hits=1，响应 expired，资金和流水前后保持，verification 前后均 [2,null]；requests／节点／对应 attempt 一致 expired、无成功 executed 日志及后继执行的断言也实际通过。第三轮 37 个编号全齐，全部 actually_run=true、passed、无 errors，外层源码／保护文件指纹字典前后相等。开发者原失败仍保持开发证据，不能因修后独立例通过而改写成独立作者已复现过修前失败。

第三轮后的另一开发发现：`tests/.runs/task2-backend-stage/recovery-cancel-s_ky54wu/observation.json` 实际记录 cancel 返回 rejected/no_pending，之后旧 review 仍能 success/recovery_authorized。此为开发者运行，**独立作者没有运行复现**。公开契约早已规定取消使恢复许可立即失效，现明确 `cancel(None)` 涵盖当前恢复轮次，即无节点 pending 也不能留下许可；不新增业务工具、不取消已提交结果。

第四轮只给 R-14 追加三个阶段（准备未同意、已同意未 resume、已恢复且 pay 成功后 ready 无 pending）×两个入口（固定 cancel()、自然语言“取消”），共六种参数场景。旧 R-14 与其余 36 方法 AST 保持原样，方法数仍 37。实际六组均 cancelled/user_cancelled，model_calls=0，取消前后资金及流水相同；独立脚本中旧 review／码／许可不能继续、旧计划不能复活、取消后仍可新建合法查询的断言均通过。已消费 review 如返回真实历史回执也未重新授予执行能力。所有原始轮次与源码不覆盖。

| R-14 阶段 | 取消入口 | 取消后实际持久结果 |
|---|---|---|
| 准备未同意 | 固定 cancel() | interrupted／blocked／user_cancelled；bill 成功保留，pay cancelled，subs not_started，pending 请求 0 |
| 准备未同意 | 自然语言“取消” | 同上，无模型调用，无资金／流水变化 |
| 已同意未 resume | 固定 cancel() | interrupted／blocked／user_cancelled；bill 成功保留，pay cancelled，subs not_started，pending 请求 0 |
| 已同意未 resume | 自然语言“取消” | 同上，无模型调用，无资金／流水变化 |
| 已恢复且 pay 成功后 ready | 固定 cancel() | interrupted／blocked／user_cancelled；bill、pay 成功保留，subs not_started，pending 请求 0；仅原 10000 分成功一次 |
| 已恢复且 pay 成功后 ready | 自然语言“取消” | 同上，无模型调用，已提交资金保持，没有反向流水 |

作者另从六组结束快照独立读取上述状态和未决请求数，均存在 plan_id 关联的 cancelled 审计。第四轮 R-05 的两个 before-commit 正常回调均触发一次，恰好到期及超过一秒仍 expired，资金相同、失败计数维持 2、未锁定，提交前过期不会清零。

第四轮再次包含真实 R-09 退出 71、R-10 退出 72，分别保持初始账户／7 条流水及一次 T100／9 条流水；R-13 一名竞争者拒绝、另一名成功授权并完成唯一一次转账，旧请求重放拒绝，没有线程异常。R-37 实际通过七条新路由的来源／CSRF／额外字段／重复键与重复头断言、旧会话 CSRF 失效、HTTP 重启恢复链和本地接管登记／关闭；这只计公开 HTTP 自动验收，不计浏览器或真人验收。

## 7. 最终范围与证据指纹

第四轮 37 个 R 编号逐项齐全，全部 actually_run=true、status=passed、errors=[]；外层 exit_code=0，源码前后指纹字典及保护文件前后指纹字典均相等。冻结测试源码 SHA256 为 `e34ef950537004795e63dd16c3e8d074e59367656d935738ed6e741b8119a265`，契约 SHA256 为 `bbf88c7642d230161fae8136a2ff09121d9f2bb9e35aa17eabd9f62a439643ad`，该轮外层实现版本指纹为 `f0c0b2ac42e7643d20602ecb84d0c196390dd68b78283c3ce9f9946543ffcb68`。作者用原始 JSON 比较指纹，不读取日常库或业务实现；本轮只改报告，没有再改测试或契约。

本套证据支持持久计划和节点事实、重启失效及新授权、提交前回滚／提交后已成功事实保持、指定竞争下的幂等、失败／中断／取消／本地人工事项的持久轨迹。R-35 五类损坏夹具均隔离该计划、阻止自动执行并保留健康计划，不能把“隔离损坏项”写成自动修复任意损坏数据库。

补偿边界仍保留：已成功转账不反向划款，已取消订阅不自动恢复，历史账单不删除；manual_follow_up／no_compensation_needed 只记本地处置。真实员工身份、银行／平台人工渠道及实际线下处理没有验收条件，不能把 owner 关闭本地记录写成人工处理完成。R-34 含合成强因素通过后的红档拒绝，本轮没有放开红档。

根实现者另做的 1440／390 页面流程与取消按钮点击、刷新及资金读库属于实现方 UI 证据，本报告不冒称独立浏览器或真人核验。完整既有 159 项最终回归结果由根执行者另附实际证据，本报告不预填其结果。真人手机、真实终端、两位队友人工核验及正式赛事渠道状态继续按各自真实记录，不由本套 37 方法替填。

## 8. task3 人类来源核对后的兼容复验（发布，尚未运行）

本节是 task3 引入人类参数来源核对后的新增复验记录，不改变第 6、7 节 task2 冻结版 37 方法通过的历史。作者只阅读任务 3 原文、`src/CONTEXT_API.md`、原始回归 JSON、本作者的 recovery 测试，以及经根实现者指定的 web 测试公开模型夹具和两个计划用例；仍未读业务／网页／模型实现、真实配置或日常库，未自行执行测试。

### recovery R-37 的原始兼容失败

`evidence/recovery-independent-20261024T143539482443Z-860cf867f9.json` 实际运行 37 方法：36 passed、R-37 failed，1 failure／0 error／0 skip。外层 `evidence/recovery-run-20261024-143538-667281.json` 退出 1，源码及保护文件前后指纹字典相等，版本指纹 `522492b2ceafe12138fd6fde293d93c7dc22ab0f01bec69736c8a29183cb7efa`。旧源码仍为 `e34ef950537004795e63dd16c3e8d074e59367656d935738ed6e741b8119a265`。

该 R-37 输入曾为 `Independent offline fixture plan` 和 `Independent plan before HTTP restart`，固定离线模型却返回 `bill -> pay(T100) -> subs`。这两段文字只是测试标签，没有人类明确的转账目标／金额，不能因模型返回完整图就认定已有来源。CONTEXT_API 第 1、4、5 节要求 handle_text 先核对人类来源、静态图的金额与联系人也须逐项来自人类；HTTP 没有直接候选入口。因此旧夹具不再具备要求 pending 的前提，修订夹具符合 task3 规则，不能据此放松新来源限制。原始 JSON 只保留此处实际 rejected 与预期 pending 的差异，没有完整 HTTP reason；作者不臆造具体拒绝原因。

仅将上述两处 text 改为同一明确请求：“先分析我本月账单，再从我的主账户alice-main给已登记的联系人小王转100元，最后查询我的订阅。”原固定 PLAN、T100、37 个方法、全部断言、确认、CSRF、审计、资金及幂等期望一字不改。AST 对比证明除两处字符串常量外整棵语法树相同；主文件和 child 语法检查通过，没有运行业务。

原 task2 最终源码另封存为 `tests/.runs/recovery-independent-source-task2-final-e34ef9505370.py`；兼容草稿为 `tests/.runs/recovery-task3-human-source-draft.py`，根执行者解除源码冻结后已发布到正式文件，SHA256 为 `ae2b3f59f909456c2a34d546bb0a8c59756955dceeee6cf95d7cd1f30860b21e`。此次依据的 CONTEXT_API SHA256 为 `13b113951cd303581b2203898f701fb94d229ee7a0308d83e82b9358414fcb97`；RECOVERY_API 不变。新版本目前运行 0，不预填新的 37 方法结果。

### web 原计划夹具的兼容审阅（不同于原作者）

根实现者报告旧 159 项 task3 回归有 6 failure／0 error／0 skip，原始记录为 `evidence/isolation-regression-20261024-223538-105940.txt` 及同名 JSON。其中生产代码“查询自动扣款”同义词识别由根实现者修复；closeout 三项交其原作者处理，本作者不代判那些修复。这里只受托独立复核 `tests/test_web_acceptance.py` 的离线模型夹具及两个计划用例，**本作者不是该 web 套件原作者**。

两项 web 用例的实际原图只有 `bill(analyze_bills) -> subs(query_subscriptions)`，没有转账。旧输入和固定模型分派键“创建依赖计划”没有明确这两项人类动作。只把一处模型分派键和两个 HTTP 输入同步改为“先分析我本月账单，再查询我的订阅。”，保持原两节点图，不加入转账、不动其他分派、确认、资金／业务快照、安全头、CSRF 或任何断言。AST 对比证明只改这三处字符串，27 个方法保持不变；语法检查通过但未执行。

web 原源码 SHA256 为 `2aa7c4c5001bb088ea2c565d0f8d23ab9b38256c7ba5ec230c2dcf8e0a85a2e0`，封存于 `tests/.runs/web-acceptance-source-pre-context-2aa7c4c5001b.py`；兼容草稿 `tests/.runs/web-acceptance-context-human-source-draft.py` 已经授权发布正式文件，新 SHA256 为 `678de4da513106bc246ae25ca1cd6ae522d194efde3cf2b1764ab14cecc16058`。实际复验由根执行者生成新证据，保留本次兼容失败和历史原版，不把发布／语法通过写成业务验收通过。

# 公开接口与独立测试约定（2026-10-10）

Python 3.10+，仅标准库。全部银行数据及平台行为模拟；模型配置未完成前不算 AI 接入通过。本文件是实现契约，测试不能阅读业务实现确定期望。

`from src.bank import BankService`；`BankService(database_path, user_id="alice", clock=None, audit_hook=None)`。新数据库自动种入夹具；已有数据不重置。身份由构造参数固定（alice/bob），聊天不能改变。构造时该用户旧 pending 失效并记 restart 事件，锁定保留；一会话一实例。

- `propose(candidate, raw_input="")`：候选意图，不代表授权。新请求使旧 pending 失效。单步 `{"intent":"transfer","params":{"account_id":"alice-main","contact_id":"wang","amount_cents":10000}}`。额外字段、非法类型拒绝；金额必须是正整数分（拒绝 bool）。
- `confirm(request_id, confirmation_code)`：固定接口表达明确同意，不能修改目标/金额。确认码只返回 pending 响应，在内存保留，不进数据库、审计、模型。它不是 MFA。
- `strong_verify(request_id, password, totp_code, *, confirmed=False)`：红档固定入口（规则全文见 `docs/22-mfa-strong-verification.md`）。请求须本人red/pending、未过期且绑定参数/实际目标有效；无效请求`invalid_confirmation`、不计因素失败；期限到达`expires_at`即expired。用户核对operation后本人明确同意，可信调用者才能传`confirmed=True`；缺少/非bool真值`explicit_confirmation_required`，不校验因素、不计失败、不消费时间步。密码与动态码只在内存，不进数据库/审计/模型/响应。两因素成功：明确确认、消费时间步、清零计数、strong_verified及请求终结/隔离拒绝日志同事务保存，响应`rejected/isolation_unavailable`、`strong_verification="passed"`，业务不变；审计失败全部回滚、failed/audit_unavailable、停后续业务。失败统一verification_failed，连续3次locked十分钟；新有效请求重用已使用步按失败计，旧终结请求重提invalid_confirmation且不计数。对red调用黄档confirm返回strong_verification_required，不计失败。
- 红档 propose 分两种：用户**未登记**强验证（`strong_auth` 无行）时维持原样 `rejected/strong_verification_unavailable`、不建请求；**已登记**时建立 `pending/tier=red` 请求，**无六位确认码**，5 分钟有效期、新请求/取消/超时失效规则与黄档相同。
- 登记只经可信本机交互终端：`python scripts/mfa_enroll.py --db <账本路径> --user alice`。公开本地方法`enroll_strong_auth(password,totp_secret,totp_code=None)`验证密码8–128字、合法至少20字节base32秘密及当前持有码；无/错误码invalid_totp_code且无登记，登记成功消费对应时间步。每用户一份，重复already_enrolled；本地管理`unenroll_strong_auth()`或CLI `--reset`删除登记并作废本人pending/未完成计划，保留transfer失败锁定与replay步。登记失败不算有效transfer失败、不清已有计数。密码无回显，秘密只登记当场显示一次；模型、网页、聊天均无登记入口。
- 真人验证CLI：`python scripts/mfa_verify.py --db <账本路径> --user alice --amount 1001`。自己创建同一会话红档请求、展示完整operation和期限；固定输入“确认本次操作”后无回显输入密码和动态码，以confirmed=True调用固定入口。拒绝同意则cancel；不能跨进程复用网页pending。没有MFA HTTP路由，未登记或黄档按脚本说明退出，不绕过当前隔离拒绝。
- 两个MFA CLI均要求stdin/stdout/stderr为交互TTY，重定向或管道拒绝且不打开数据库、不读取因素；getpass不能安全无回显时停止，不能退化为明文input。`--help`在交互限制之前打印公开参数、退出0、不打开数据库，允许捕获帮助输出。自动mock交互仍不能证明真实终端无回显。
- MFA成功验证事务的公开审计event为`confirmed`（本次明确同意）、`strong_verified`（两因素通过）、`rejected`（reason为isolation_unavailable）；验证失败为`verification_failed`，第三次另有`locked`，过期为`expired`。因素计算或这些审计期间跨过expires_at时，成功元数据/日志回滚，只保留过期结果，不消费步或清已有计数。
- `cancel(request_id=None)`：取消本人 pending，锁定期间也可取消。
- `handle_text(text, model)`：输入检查后调用 `model.propose(text, context)`；明确否定取消；含糊输入不确认；不能由模型决定确认。认证标签、本人已登记secret出现在文本中（忽略大小写/空白）、整段或strip后等于当前口令均secret_input且不调用模型；审计字符串字段相同已知秘密脱敏，无效confirm/strong_verify的输入编号若是已知本人凭据则用新编号记录/回执，六位数字发送模型前移除。不保证识别任意混杂/编码文字中的无标签口令或未登记未知秘密。模型异常返回failed并审计，不猜意图。
- `audit_events()`：本人脱敏回执；`close()`：关闭连接。

响应字典含 `status`（success/pending/rejected/failed/cancelled/expired）、`request_id`、`intent`、`tier`、`reason`、`message`；success 含 `data`；pending 含 `confirmation_code`、`expires_at`、`operation`（用户、完整参数、影响）。红档 pending 不含 `confirmation_code`。`strong_verify` 成功响应另含 `strong_verification="passed"`。订阅查询确认前不含列表。

| intent | params |
|---|---|
| query_balance | 可选 account_id，空为本人全部账户 |
| query_transactions / analyze_bills | 可选 account_id、start_date、end_date；YYYY-MM-DD 含两端，默认本月到今天 |
| query_subscriptions | 空对象 |
| cancel_subscription | subscription_id 或 subscription_name，二选一，精确匹配，歧义拒绝并提示补充 |
| transfer | account_id（默认当前用户主账户）、contact_id 或 contact_name（二选一）、amount_cents |

结果：账单 `data.actual_expense_cents`、`data.categories`；余额 `data.accounts`；流水 `data.transactions`；订阅 `data.subscriptions`、`data.future_expected_cents`；转账 `data.amount_cents`、`data.daily_outgoing_cents`。未来预计与实际账单分别标注。

候选计划格式：`{"steps":[{"id":"bill","intent":"analyze_bills","params":{},"depends_on":[]},{"id":"subs","intent":"query_subscriptions","params":{},"depends_on":["bill"]}]}`，最多8步，校验唯一编号、依赖、环、白名单。控制接口完成后追加，不能预称完整 DAG 已实测。

现已实现控制接口：提交合法计划会按实际依赖推进至第一个黄档等待节点，响应含 `plan_id` 和 `plan.steps`，当前节点另有 request_id/confirmation_code。`confirm` 只确认这一节点；之后 `resume_plan(plan_id)` 才推进下一步。重复 resume 不生成新确认、不执行 pending 节点；取消/失败/超时的前置步骤使计划停止。`interrupt_plan(plan_id)` 和 `takeover_plan(plan_id)` 停止未完成节点并使旧确认失效；回执逐项列已完成/未完成。仅未提交的事务可回滚，已成功转账绝不自动反转；已取消订阅若要恢复需人工另行处理，目前无恢复白名单工具。计划保存在会话内存，重启不能恢复旧授权。候选依赖图运行不等于真实模型规划已接通，也不等于完整补偿回退能力。

`plan.steps` 是列表，每项有 id/intent/params/depends_on/request_id/status。节点状态 not_started/pending/success/rejected/failed/cancelled/expired；计划状态 ready/waiting_confirmation/success/failed/interrupted/human_takeover。新用户任务会停止旧计划剩余节点，即便刚完成前一个节点也不能再复用旧计划续办。停止回执保留实际已完成状态，不自动反转已提交的业务。

## 夹具

| 记录 | 初始状态 |
|---|---|
| alice-main / alice-savings | alice，1000000 / 500000 分 |
| bob-main | bob，100000 分 |
| wang / 小王、li / 小李 | alice 登记联系人，均收款 bob-main |
| alice-contact / 小阚 | bob 登记联系人，收款 alice-main |
| sub-cloud / 云存储 | alice，990 分，active |
| sub-music / 音乐会员 | alice，1990 分，active |
| sub-video / 视频会员 | alice，2990 分，active |
| bob-video / 视频会员 | bob，3990 分，active |
| 本月账单 | alice-main，当月1日，成功云存储990、音乐1990、视频2990分，共5970分 |
| 干扰账单 | 上月成功5000分，今天失败700分，次月1日 scheduled 800分，不计本月到今天实际支出 |

首次创建按 clock 定日期，上海 UTC+08:00。每日累计以实际执行日统计 transfers 中同用户全部源账户 status=success 金额。

测试 clock 是返回带时区 datetime 的可调用对象，可以推进；正式入口没有改时钟选项。audit_hook(event_dict) 在日志 INSERT 前调用，可在 event='executed' 抛异常检验回滚。hook 仅测试注入，不提供网络接口，不能关闭权限。

可用 sqlite3 检查公开表：`accounts(account_id,user_id,balance_cents)`、`subscriptions(subscription_id,user_id,name,amount_cents,status)`、`transactions(transaction_id,user_id,account_id,amount_cents,category,occurred_at,status,kind)`、`transfers(request_id,user_id,source_account_id,target_account_id,amount_cents,executed_at,shanghai_date,status)`、`requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at)`、`verification_state(user_id,intent,failures,locked_until)`、`strong_auth(user_id,password_hash,password_salt,kdf_iterations,totp_secret,enrolled_at)`、`strong_auth_replay(user_id,step,used_at)`、`audit_log`。`contacts(contact_id,user_id,name,account_id)`用于管理员异常夹具。审计 UPDATE/DELETE 有禁止触发器。测试可以插入transfers建立累计前置，或插入合成strong_auth（PBKDF2-HMAC-SHA256、散列hex64、盐hex32、迭代200000，验证只允许200000至2000000，秘密base32解码至少20字节）；TOTP为RFC6238 HMAC-SHA1/30秒/ASCII六位，窗口±1步。replay只存用户+已用步，不存原码；旧code表初始化事务迁移并保留已用步，不清业务/审计/锁定。均属测试管理员构造，不硬写真人秘密，管理员改库不等于应用授权。

日志字段按 docs/05：id、timestamp、request_id、step_id、user_id、raw_input_redacted、intent、tier、params_redacted、event、result、reason。构造重启旧请求失效；失败计数持久化。

requests另有binding_json列，保存代码解析的真实收款账户绑定；模型不能指定此字段。联系人映射在确认前改变则旧授权失效并拒绝，不转到新账户。测试可修改contacts映射作异常前置，期望双方余额不变。cancel非法ID类型/格式直接rejected并审计，不能熔停健康账本；随后合法查询仍可用。

拒绝候选也记录白名单中的非秘密目标/金额，例如不存在的subscription_name；这只是候选审计，不表示接受或授权。额外认证字段不入日志；含秘密标记、六位数字、控制字符或超过80字符的文本参数脱敏。未知意图不保存任意参数。既有成功事务/权限/確認规则不受此日志处理改变。

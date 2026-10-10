# 公开接口与独立测试约定（2026-10-10）

Python 3.10+，仅标准库。全部银行数据及平台行为模拟；模型配置未完成前不算 AI 接入通过。本文件是实现契约，测试不能阅读业务实现确定期望。

`from src.bank import BankService`；`BankService(database_path, user_id="alice", clock=None, audit_hook=None)`。新数据库自动种入夹具；已有数据不重置。身份由构造参数固定（alice/bob），聊天不能改变。构造时该用户旧 pending 失效并记 restart 事件，锁定保留；一会话一实例。

- `propose(candidate, raw_input="")`：候选意图，不代表授权。新请求使旧 pending 失效。单步 `{"intent":"transfer","params":{"account_id":"alice-main","contact_id":"wang","amount_cents":10000}}`。额外字段、非法类型拒绝；金额必须是正整数分（拒绝 bool）。
- `confirm(request_id, confirmation_code)`：固定接口表达明确同意，不能修改目标/金额。确认码只返回 pending 响应，在内存保留，不进数据库、审计、模型。它不是 MFA。
- `cancel(request_id=None)`：取消本人 pending，锁定期间也可取消。
- `handle_text(text, model)`：输入检查后调用 `model.propose(text, context)`；明确否定取消；含糊输入不确认；不能由模型决定确认。模型异常返回 failed 并审计，不猜意图。
- `audit_events()`：本人脱敏回执；`close()`：关闭连接。

响应字典含 `status`（success/pending/rejected/failed/cancelled/expired）、`request_id`、`intent`、`tier`、`reason`、`message`；success 含 `data`；pending 含 `confirmation_code`、`expires_at`、`operation`（用户、完整参数、影响）。订阅查询确认前不含列表。

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

可用 sqlite3 检查公开表：`accounts(account_id,user_id,balance_cents)`、`subscriptions(subscription_id,user_id,name,amount_cents,status)`、`transactions(transaction_id,user_id,account_id,amount_cents,category,occurred_at,status,kind)`、`transfers(request_id,user_id,source_account_id,target_account_id,amount_cents,executed_at,shanghai_date,status)`、`requests(request_id,user_id,intent,params_json,tier,status,created_at,expires_at)`、`verification_state(user_id,intent,failures,locked_until)`、`audit_log`。审计 UPDATE/DELETE 有禁止触发器。测试可以插入 transfers 建立日期/累计前置条件，管理员改库不等于应用授权。

日志字段按 docs/05：id、timestamp、request_id、step_id、user_id、raw_input_redacted、intent、tier、params_redacted、event、result、reason。构造重启旧请求失效；失败计数持久化。

requests另有binding_json列，保存代码解析的真实收款账户绑定；模型不能指定此字段。联系人映射在确认前改变则旧授权失效并拒绝，不转到新账户。测试可修改contacts映射作异常前置，期望双方余额不变。cancel非法ID类型/格式直接rejected并审计，不能熔停健康账本；随后合法查询仍可用。

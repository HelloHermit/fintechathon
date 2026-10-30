# 启动、模型与公开接口

**2026-10-28完成范围**：六场景源码、真实模型分批九组、最终网页与Docker专项已有实际证据，详见[交付41](../docs/41-six-delivery.md)。最终源码指纹`05f3035fed4463db211b6d2a9361fcae2d3af09d2b84854e5a1efb5381044f77`；完整新包及包外解包报告单独交付。以下“正在验收”和旧三场景数字为阶段历史；不把其预期状态当本轮最后结论。

**六场景v4正在验收**：当前源码包含原三方向与新理财比较/匹配、模拟卡状态、预算保留和固定服务订单，规则见[SIX_SCENARIO_API.md](SIX_SCENARIO_API.md)，逐方向输入及启动方式见[38](../docs/38-six-reproduce.md)。新工具须新runtime包含受信six_calculator.py，勿把旧runtime当新增能力已测；默认不指定隔离仍为可信工具模式。测试始终使用全新独立库，正式日常库不会重置。完成/缺项以最终交付报告为准。

**2026-10-25续接**：task1～3覆盖验收完成，分别见[29](../docs/29-task1-isolation-delivery.md)、[32](../docs/32-recovery-delivery.md)、[35](../docs/35-context-delivery.md)。task3独立45项、恢复37项、原159项及复用Docker4项通过；真实模型18组修提示后全部通过，首轮失败保留。多轮缺参会显示“请补充信息”，修改目标/金额使旧确认失效，确认仍使用独立按钮；精确语义见[CONTEXT_API](CONTEXT_API.md)。网页“历史任务与接管”查看持久历史，重启先核对恢复再明确继续，黄档逐项确认。无模型CLI：`python scripts/recovery.py --db <模拟库路径> --user alice`，输入“帮助”。恢复API与表见[RECOVERY_API](RECOVERY_API.md)。隔离须显式指定`-IsolatedTools -IsolationRuntime .isolation/docker-runtime-20261023`，业务库/监控库在runtime之外。Windows仍失败，默认启动不称隔离；真人核验延期，红档拒绝。下文为历史。

**20:00后技术收尾**：三处问题已复现并修复，新增独立18项修后通过；本次159项完整回归通过（131.811秒、exit0），下文141项为历史记录。[本轮报告](../docs/25-technical-closeout.md)及[原始证据](../evidence/closeout-regression-20261011-201754-935091.json)区分合成测试、网页操作和本人验证。红档继续拒绝。本机网页收到已登记用户红档pending时可展示和取消；请先取消网页请求，再按原手机说明在本机专用入口创建新请求，不复用网页编号，也不把因素填入聊天。

更新：2026-10-11。已实现SQLite模拟账本、六项固定工具、确认与持久熔断、追加审计与事务、候选依赖图控制、真实模型适配器、CLI及本机Web。5次真实正常请求、2条真实依赖计划及6条异常各有证据。当前全套141项通过，87.947秒、退出0，见[原始输出](../evidence/combined-regression-20261011-154218-477873.txt)；原93项报告为历史。主实现桌面QA通过三方向、确认 / 拒绝、审计和SQLite核对，控制台两次错误 / 警告查询为空；计划GUI控制未计通过。移动端按用户要求待云端后再测，不计通过或失败。MFA模块独立合成43项/99子用例通过，见docs/23；本人登记、独立手机与真实终端未验。隔离、完整补偿与完整人工记录仍缺，红档仍拒绝。

## 启动

```powershell
Set-Location C:\fintechathon
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Web
```

保持终端运行，在浏览器打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。服务只监听本机回环地址，默认可信用户alice，启动不会重置 `data/bank.db`；网页不能切换用户。这是预置模拟身份，没有生产登录或不同身份因素验证。

CLI调试入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
# 或任一可用Python 3.10+
python -m src.main --db data/bank.db --user alice
```

队长电脑默认python是Windows商店占位入口，脚本优先检查Codex捆绑运行时，再检查系统Python。当前实跑Python 3.12.14；SQLite、urllib、HTTPServer、unittest随Python提供。静态页面为 `src/web_assets/index.html`、`app.css`、`app.js`，不加载第三方框架、字体或CDN，无新增安装依赖。

启动不清空数据库、历史日志或锁定；旧待确认在会话重启时失效。当前身份由可信启动 `--user alice` 或 `--user bob` 固定，聊天自称其他人无效。这是模拟身份，不是生产登录系统。

## 本机Web用法与边界

输入自然语言并点击发送，示例按钮只填入文本。账单结果来自工具；订阅查询、取消及黄档转账先显示完整参数、目标、金额、影响与有效期，用户核对后通过固定确认按钮授权本次请求。屏显六位码只用于确认，不是MFA，不发送给模型。取消、新任务、超时后旧确认失效。

页面还提供本人脱敏审计与计划继续 / 中断 / 人工接管。计划的每个黄档节点分别确认；中断或接管停止未完成节点，已成功业务不自动撤回。网络失败不自动重试，是否已执行须核对账本和审计。

后端复用相同 `BankService`，密钥只在后端本机配置。浏览器没有身份切换、任意候选、SQL、shell或文件读取接口；固定三份静态资源，POST校验同源、会话令牌和JSON字段。详细契约见[WEB_API.md](WEB_API.md)。这些本机防护不证明生产认证或沙箱；离线27项HTTP与实际浏览器交互分别验收。

## 本人试一次“密码加手机验证码”（MFA）

MFA在这个项目里，就是同时核对你设置的密码和你手机上生成的六位验证码。程序的自动检查已通过；你本人拿手机操作这一步还没有完成。

**具体操作请看[手机验证操作说明](../手机验证操作说明.md)。** 它按“打开哪里、输入什么、看到什么算成功”分步写好了，并解释了PowerShell、登记、密钥等必须用到的词。安卓手机还没安装验证器时，先从安装应用开始，不要直接运行登记命令。

当前没有网页验证按钮，需要本人在电脑的PowerShell窗口操作。程序只显示手机配对文字，没有二维码。登记成功后，要等手机数字换一组再验证；密码和验证码输入时屏幕不显示字符，这是正常的。

验证成功后，高额模拟转账仍会被拒绝，因为限制工具活动范围的保护还没有完成验证。预期是“密码和手机验证码都通过，钱没有转出”。只发送结果文字，密码、配对密钥和验证码不发聊天；测试账本不交付。

本人实际结果记入[人工记录M1～M3](../docs/17-manual-acceptance-record.md)，不由自动测试替填。技术规则、重置边界及已知限制见[22 · MFA规则](../docs/22-mfa-strong-verification.md)。

[主实现桌面QA](../evidence/browser-ui-validation.json)已实际运行：初始账单59.70元；订阅未确认不披露，确认后三条；取消视频后历史59.70元、未来29.80元；转100元前余额1000000 / 500000 / 100000分且无转账，确认后990000 / 500000 / 110000分，仅一笔10000分转账、共9条交易；后续累计1100元红档拒绝。审计打开 / 展开 / 关闭、最新JS重载后的订阅确认均通过，两次控制台错误 / 警告查询为空。实测桌面1536×1024、scrollWidth1536，临时视口已恢复。该次隔离库位于 `tests/.runs`，端口8766，默认启动端口仍8765。

GUI曾观察到账单→订阅计划，转账后账单159.70元、订阅等待后变中断；触发中断的主体未单独核对，不计本轮计划控制按钮通过。现有两条真实脚本图和离线控制证据不变。以上是主实现复演，不代替队友人工验收；移动端按用户要求待云端后再测。浏览器用量未导出，不拼入脚本token计量。

## 模型在本机配置

队长已选DeepSeek V4.1 Flash，官方API名 `deepseek-flash`、基础地址 `https://api.deepseek.com`，本轮允许最多一亿token。本机密钥修正后已真实调用成功，具体见[模型配置说明](../docs/model-configuration.md)。环境变量：`FINTECH_MODEL_BASE_URL`、`FINTECH_MODEL_NAME`、`FINTECH_MODEL_API_KEY`。密钥只在本机输入，不把 `.env` 打入交付包。无配置 / 超时 / 坏JSON失败且不执行业务；未实现账户级预算强制控制，不把用户上限误写成已实测计费保护。

配置后运行 `& $Python scripts/live_demo.py`，在全新模拟数据库中最多5次真实请求检查三个方向。测试脚本只对事先写定的用户 / 目标 / 金额模拟明确确认，输出 `evidence/real-model-integration.json`（不含有效确认码或密钥）；它没有给生产用户自动确认，也不能代替人工验收。

今天10:14的[5次正常响应](../evidence/real-model-integration.json)合计3960 token，账单为5970分；订阅查询、取消视频会员和转账10000分均先pending，经固定测试确认后success，取消后历史仍5970分。SQLite核对仅sub-video变cancelled，未来预计2980分；余额为990000 / 500000 / 110000分，仅一条成功转账，原7条历史交易保持并新增双方2条流水。未来预计来自账本复查，没有额外第六次模型请求；该次5请求未包含红档、攻击或DAG生成。[网络失败](../evidence/real-model-network-failure.json)、[HTTP401失败](../evidence/real-model-auth-failure.json)与[意图误判](../evidence/real-model-clarification-failure.json)保留为历史，当前并非仍在等待密钥。

另运行 `& $Python scripts/live_plan_demo.py`，两次真实自然语言请求在独立模拟库中提出带依赖的计划，合计1583 token。第一条账单节点success、订阅节点pending，`takeover_plan` 后订阅cancelled且旧确认rejected；第二条先读取主账户1000000分，转10000分时后置查询仍not_started，固定测试确认和 `resume_plan` 后读到990000分。公开SQLite快照确认双方990000 / 110000分、储蓄500000分和一条成功转账，重放拒绝。这只证明两条指定计划样例，不证明任意复杂DAG或自动补偿。

[6条真实异常报告](../docs/13-real-model-acceptance.md)已由独立作者审核通过，证据为[real-model-acceptance.json](../evidence/real-model-acceptance.json)：5条得到真实JSON返回、共4007 token；1条明显注入在输入层阻断，无模型调用。涵盖否定取消及旧确认、代码归属拒绝、红档拒绝、缺失联系人澄清和不存在订阅，不能据单例声明完整攻击防御。证据JSON保留运行时待审核标记，最终独立结论以docs/13为准。

## CLI 用法

自然语言如“这个月已经花了多少？”、“我有哪些自动扣款？”、“取消视频会员”、“给小王转100元”经真实模型提出候选，再由代码审查。未配置模型时这些请求失败，不做固定回答。

- `/confirm 请求编号 六位码`：核对屏显完整参数后精确确认本次请求；屏显码只是同意，不是MFA。
- `/cancel [请求编号]`：取消当前待确认，旧授权失效；“不要执行”“算了”等明确否定也由代码取消。
- `/audit`：读取本人脱敏回执；日志原话省略，秘密不保存。
- `/plan 计划编号`：当前节点已确认成功后继续计划。
- `/interrupt 计划编号`、`/takeover 计划编号`：停止未完成节点，回执列出已完成状态。
- `/quit`：退出。
- `/candidate {JSON}`：**离线候选调试**，无需模型，仅检验权限和工具，CLI明确标注模式。

可演示离线输入（金额为整数分）：

```text
/candidate {"intent":"analyze_bills","params":{}}
/candidate {"intent":"query_subscriptions","params":{}}
/candidate {"intent":"cancel_subscription","params":{"subscription_name":"视频会员"}}
/candidate {"intent":"transfer","params":{"contact_name":"小王","amount_cents":10000}}
```

每个黄档新请求都需要当前回执中的编号和确认码；演示截图和材料不能包含有效确认码。新请求使上一个pending失效。

## 公开接口、夹具和测试

[PUBLIC_API.md](PUBLIC_API.md) 公布 BankService 接口、两名用户及全部夹具、日期、SQLite表、测试时钟和审计故障注入约定。独立测试作者只看该文档和业务规格，不读业务实现确定期望。

```powershell
& $Python scripts/demo.py
& $Python -m unittest discover -s tests -p 'test_*.py' -v
```

`$Python` 指可用Python路径；根README列本机实跑路径。测试数据库放 `tests/.runs`（忽略），不重置日常 `data/bank.db`。原63项加3项拒绝审计回归，共66业务；另27项本机HTTP；原统一discover **93项通过，11.702s、退出0**（历史），见[独立报告](../docs/09-independent-acceptance.md)。它们使用固定候选 / 模型替身，不调用真实模型；桌面点击与控制台另见[主实现QA](../evidence/browser-ui-validation.json)，移动端按用户要求延期，队友人工复演仍待完成。HTTP首轮静态JS缺失及未知POST状态码错误保留在[原始输出](../evidence/independent-web-acceptance.txt)，修复后原样27项均通过。

## 边界

日累计含同用户全部源账户的成功转出，以执行时上海日期复检；≤100000分黄档，超过红档。红档的真实MFA和隔离未就绪，保持拒绝。审计失败回滚当前事务，并停止当前会话后续业务；日志整体不可写时无法保证失败记录落盘。管理员持有数据库文件仍可篡改，不宣称绝对防篡改。

候选依赖图、逐节点确认与中断 / 人工接管控制已实现，两条真实计划样例已运行；任意复杂规划、完整补偿回退、独立设备MFA、受限可监控隔离、正式APP / IM渠道及队友人工验收仍缺。本机Web不等同正式渠道，桌面QA只证明回执列明的覆盖范围；计划GUI控制未计通过，移动端按用户要求待云端后再测。计划只在会话内存中，重启不恢复旧授权。已成功转账不自动反转，已取消订阅恢复需人工另行处理。当前阶段快照不代替19—20点终验与打包。

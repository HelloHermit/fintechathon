# 本机模型配置与真实调用验收

更新：2026-10-11。适配器使用Python标准库 `urllib`，本机Web后端使用标准库HTTPServer；没有额外安装依赖。密钥只在本机后端配置，页面不能获取密钥或改变可信身份；全部银行数据和工具仍是模拟。

队长已选择 **DeepSeek V4.1 Flash**，授权本轮最多1亿 token；官方 API 基础地址 `https://api.deepseek.com`，模型 ID `deepseek-flash`。选择依据见 [DeepSeek API 官方说明](https://api-docs.deepseek.com/)与 [V4.1 官方发布说明](https://api-docs.deepseek.com/news/news260910/)。密钥仅由队长在本机隐藏输入。**2026-10-11 10:14开始的5次真实请求完成三个方向，SQLite状态断言通过、脚本退出0**，见[最新集成回执](../evidence/real-model-integration.json)。此前明确的视频会员取消被模型误判clarification、未改业务的[失败回执](../evidence/real-model-clarification-failure.json)保留；修复后通过不覆盖失败历史。`/candidate` 与本机响应替身仍只是离线代码检查。

本轮授权上限不是强制预算限制：程序只保存最近一次响应中公开的非负整数 `prompt_tokens`、`completion_tokens`、`total_tokens`；未实现全账户计量或硬上限，费用与总用量仍须核对服务商控制台。程序不会自动充值、换模型或把失败改成固定回答。

## 队长需要提供的信息

地址、模型名、本轮额度授权和有效本机密钥已经提供，今日真实集成成功；此前HTTP401认证失败不再是持续阻塞。后续密钥失效、额度不足或更换服务商时仍需在本机配置，不能把秘密发聊天。更换服务商时可以在聊天里提供这三项非秘密信息：

1. 已有哪家服务商的 API 账户，以及它提供的 OpenAI 兼容 API 基础地址。
2. 该账户可调用的准确模型名。
3. 是否有可用测试额度，以及本轮愿意使用的费用上限；费用和套餐以该服务商控制台为准。

**密钥不用发聊天。** 当前实现要求服务商支持 `POST /chat/completions` 和 `response_format: {"type":"json_object"}`。基础地址填服务商给出的地址（通常类似 `https://主机/v1`）；程序追加 `/chat/completions`，也接受已含完整终点的地址。

接口形状已按 [OpenAI Chat Completions 官方参考](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) 和 [JSON 模式官方说明](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)核对。JSON 模式保证的格式有限，不能代替业务参数校验；本程序仍严格解析 JSON 并由代码核对意图、参数及权限。其他服务商是否完全兼容，必须在收到其信息后单独验证。

## 在本机安全输入

在 PowerShell 中进入项目并运行：

```powershell
Set-Location C:\fintechathon
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-model.ps1
```

按提示依次填入 `https://api.deepseek.com`、`deepseek-flash`，然后隐藏输入 API 密钥。不要把密钥写入命令参数、聊天或截图。脚本把配置写入项目根目录 `.env`，不会调用模型；`.env` 已被 `.gitignore` 排除。文件在本机以明文保存，由这台电脑的文件权限保护，不是秘密管理服务。

两份 PowerShell 脚本已保存为 UTF-8 BOM；已用本机 Windows PowerShell 5.1.26100.9444 的 `Parser.ParseFile` 检查，两份语法错误均为0。早先无 BOM 版本被5.1按 ANSI 读取导致中文解析错误，现已修复；用户可直接重跑上述命令。

环境变量 `FINTECH_MODEL_BASE_URL`、`FINTECH_MODEL_NAME`、`FINTECH_MODEL_API_KEY` 优先于 `.env`。如以前配置过同名环境变量，需在本机清理旧值，避免覆盖新文件。程序只读取这三个值，不执行 `.env` 中的内容，不展示密钥。

远端只能 HTTPS，保留系统 TLS 证书校验，不接受关闭校验的开关。仅明确的回环地址（例如 `127.0.0.1`、`localhost`、`::1`）允许 HTTP，供本机服务或接口测试使用。任何 HTTP 跳转都拒绝，避免认证头被带到其他地址。地址不得含用户名、密码、查询参数或片段。

## 启动和验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Web
```

保持服务终端运行，在浏览器打开 [本机演示界面](http://127.0.0.1:8765)，默认模拟用户alice。示例只填入输入，点击发送才请求模型；模型配置已读取不等于调用成功。黄档回执显示用户、动作、目标、金额、影响和期限，核对后点击本次确认；屏显码只用于代码确认，不是MFA、不发给模型。取消或新任务使旧确认失效，审计及计划控制使用固定接口。页面不接受身份切换或任意候选，详细见[本机HTTP契约](../src/WEB_API.md)。

本机[主实现桌面QA](../evidence/browser-ui-validation.json)已通过覆盖的三方向、确认 / 红档拒绝、审计、SQLite核对与控制台检查；本轮用独立库和8766端口，默认启动仍为8765。计划GUI控制未计通过，移动端按用户要求待云端后再测，不计通过或失败。启动脚本优先使用Codex捆绑Python，再找系统Python 3.10+，不会安装依赖或重置已有数据库。CLI调试用不带 `-Web` 的同一脚本，原始入口也可运行：

```powershell
python -m src.main --db data/bank.db --user alice
```

如果系统 `python` 是不可用的 Windows 商店别名，使用 `start.ps1`。启动时“配置已读取”只是配置格式检查；输入“这个月已经花了多少？”并得到模型生成候选后的实际账单回执，才算一次真实调用。

在CLI中输入“我有哪些自动扣款？”和“给小王转100元”，核对代码展示的动作、完整参数、用户、金额和有效期。明确同意时用固定 `/confirm <请求编号> <六位码>`；这六位码只是本次确认，不是强验证，不发送给模型。用 `/cancel` 取消、`/audit` 查看本人脱敏回执、`/quit` 结束。

计划在需要确认的步骤暂停；确认后用 `/plan <计划编号>` 继续。`/interrupt <计划编号>` 中断，`/takeover <计划编号>` 标记需要人工接管。只有实际模型生成并由程序执行的计划，才可作为真实模型规划链路证据。

没有配置时，CLI仍可通过 `/candidate {"intent":"query_balance","params":{}}` 运行明确标注的离线代码检查；网页不开放此入口。自然语言请求会失败并记录审计，不猜意图。不能把离线模式写成真实模型接入证据。

## 错误处理和数据边界

单次调用的网络连接与读取超时为25秒；这不是全过程硬时限。输入最多4000字符，候选最多16000字符，响应读取最多128 KiB。模型输出不完整、出现重复键、NaN/Infinity、Markdown 包装或不是 JSON 对象时失败；不自动重试，以免重复调用和增加费用。

仅对 `api.deepseek.com` 发送 `thinking: {"type":"disabled"}`；本轮只识别候选意图和计划，关闭推理以减少延迟和输出截断风险。该字段与默认推理模式依据 [DeepSeek 官方 Chat Completions 接口](https://api-docs.deepseek.com/api/create-chat-completion/)；不会向其他服务商发送专属参数。

HTTP 认证、额度、兼容性、网络及超时错误只展示固定说明和状态码，不展示供应商原始错误、响应正文、请求认证头或异常 traceback。可根据错误提示在本机核对配置。模型提供代码、SQL、命令或未知字段时不会执行，最终权限仍由 `BankService` 复核。

模型接收当前自然语言，以及本人用户编号、本人账户编号、登记联系人编号和名称、上海日期。程序重新构造字段白名单，不把订阅列表、账单备注、余额、确认码、密码或密钥放入模型上下文；含疑似秘密的自然语言拒绝发送。有效确认使用固定命令进入代码层，不经过模型。

日志与独立验收记录应写明真实调用是否发生、是否得到候选、实际结果和缺项。真实模型调用失败时应检查银行状态未变，并在审计中找到失败事件；不要用本机替身补成“真实模型通过”。

## 实际调用记录

北京时间2026-10-10，受限网络首次尝试失败；获准联网后的旧密钥请求返回 `model_http_error` / HTTP401，在第一条账单请求处停止。[网络失败](../evidence/real-model-network-failure.json)与[认证失败](../evidence/real-model-auth-failure.json)作为历史保留。重配密钥后20:35首次5条三方向检查退出0，20:36又通过实际启动脚本完成账单查询5970分并退出0，后者有独立的[start-natural.json](../evidence/start-natural.json)。当前密钥不是持续阻塞项。

2026-10-10 20:41:13增加SQLite前后状态断言的复跑在第三请求失败，[误判回执](../evidence/real-model-clarification-failure.json)保留：

| 实际发出的请求 | 代码结果 | total_tokens |
|---|---|---|
| “这个月已经花了多少？” | analyze_bills，绿档success，5970分 | 700 |
| “我有哪些自动扣款？” | query_subscriptions，先pending，固定测试确认后success | 699 |
| “请取消我的视频会员。” | unknown / clarification，rejected；未取消，停止后续检查 | 710 |

这次失败实际3个响应合计2109 token，第四、五条没有调用；前后SQLite全部余额、订阅、历史交易及转账表一致。模型误判造成正常任务未完成，安全停止避免误取消。

修正候选提示后，2026-10-11 10:14:36开始的 `scripts/live_demo.py` 退出0；[当前集成回执](../evidence/real-model-integration.json)记录5次真实请求及状态断言：

| 真实请求 | 实际代码结果 | total_tokens |
|---|---|---|
| “这个月已经花了多少？” | analyze_bills，绿档success，5970分 | 783 |
| “我有哪些自动扣款？” | query_subscriptions，先pending，固定测试确认后success | 782 |
| “请取消我的视频会员。” | cancel_subscription，先pending，固定测试确认后仅sub-video变cancelled | 788 |
| “这个月实际已经花了多少？” | analyze_bills，仍5970分，历史保留 | 803 |
| “从我的主账户给已经登记的小王转100元。” | transfer，先pending，固定测试确认后转10000分，当日累计10000分 | 804 |

这次5个响应合计3960 token。SQLite复查取消后未来预计2980分，余额为alice-main990000分、alice-savings500000分、bob-main110000分；成功转账仅一条，原7条历史交易保持并新增双方2条转账流水。未来预计是代码读账本得到，没有额外第六次模型请求。回执不输出或保存有效确认码、密钥和供应商原始错误。

黄档测试确认只在脚本核对预先指定的模拟用户、目标和金额后调用固定接口；这是集成测试授权，不是生产自动确认或队友人工验收。CLI的单次账单查询未导出token用量，不能把它编进上述计量或据此推算整个账户。

20:39:38另运行 `scripts/live_plan_demo.py`，两次真实请求合计1583 token、退出0，证据见[real-model-plans.json](../evidence/real-model-plans.json)。第一条完成账单5970分后等待订阅确认，接管停止未完成节点并使旧确认失效。第二条先读主账户1000000分，转10000分前暂停，后置查询未开始；固定测试确认并续跑后读到990000分。SQLite快照中双方余额990000 / 110000分、储蓄500000分，转账仅一条，重放拒绝。

2026-10-11 10:23:54开始运行独立设计的6条异常用例，退出0，证据见[real-model-acceptance.json](../evidence/real-model-acceptance.json)。[独立报告](13-real-model-acceptance.md)已完成审核：5条取得真实JSON返回，合计4007 token；LA-05明显注入在输入层阻断，没有模型调用；LA-01第二轮否定取消也由代码办理。全部业务表前后不变，等待、取消和各类拒绝可关联审计。越权候选实际保留bob-main并触发代码归属拒绝，红档100001分因强验证 / 隔离未就绪拒绝；缺失联系人先补充，不存在订阅不猜目标。JSON保留运行时待审核标记，最终审核结论以报告为准。

首轮真实异常曾发现拒绝日志未保存不存在订阅目标，[原始问题](../evidence/real-model-acceptance-before-audit-fix.json)保留。修复后新增3项独立审计回归，原63项设计和期望保持不变，共66业务；另27项本机HTTP修复后均通过，统一93项11.702s、退出0，见[离线报告](09-independent-acceptance.md)。HTTP首轮失败另保留[输出](../evidence/independent-web-acceptance.txt)。离线HTTP使用替身，不能并入上述真实调用量。

桌面QA实得初始账单59.70元、取消后历史不变及未来29.80元；确认前无转账，确认后SQLite余额990000 / 500000 / 110000分，共9条交易且仅一笔10000分转账，累计1100元红档拒绝可关联审计。审计对话框及最新JS确认复查通过，控制台两次错误 / 警告查询为空，1536×1024无横向溢出。浏览器模型用量未导出，不能与3960 / 4007 / 1583 token脚本回执混算。

上述桌面QA由主实现操作；计划图出现等待后中断的触发主体未单独核对，不计GUI控制按钮通过。两条脚本依赖图和6条异常只证明报告列明的样例；MFA模块合成证据见docs/23；真人MFA、隔离、通用复杂规划、完整补偿、正式APP / IM渠道及完整人工记录仍缺。移动端按用户要求待云端后再测，阶段证据与快照不代替19—20点终验。

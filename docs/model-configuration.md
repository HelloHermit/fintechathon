# 本机模型配置与真实调用验收

更新：2026-10-10。适配器使用 Python 标准库 `urllib`，没有额外安装依赖；全部银行数据和工具仍是模拟。

队长已选择 **DeepSeek V4.1 Flash**，授权本轮最多1亿 token；官方 API 基础地址 `https://api.deepseek.com`，模型 ID `deepseek-flash`。选择依据见 [DeepSeek API 官方说明](https://api-docs.deepseek.com/)与 [V4.1 官方发布说明](https://api-docs.deepseek.com/news/news260910/)。密钥仅由队长在本机隐藏输入。**修正本机密钥后，北京时间2026-10-10 20:35:58开始的5次真实请求完成三个方向的模拟业务，脚本退出0**；[脱敏集成回执](../evidence/real-model-integration.json)保存实际模型候选后的代码结果和审计。`/candidate` 与本机响应替身仍只是离线代码检查。

本轮授权上限不是强制预算限制：程序只保存最近一次响应中公开的非负整数 `prompt_tokens`、`completion_tokens`、`total_tokens`；未实现全账户计量或硬上限，费用与总用量仍须核对服务商控制台。程序不会自动充值、换模型或把失败改成固定回答。

## 队长需要提供的信息

地址、模型名、本轮额度授权和有效本机密钥已经提供并验证一次真实集成成功。后续密钥失效、额度不足或更换服务商时仍需在本机配置，不能把秘密发聊天。更换服务商时可以在聊天里提供这三项非秘密信息：

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
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

启动脚本优先使用本机 Codex 捆绑 Python，再寻找可用的系统 Python 3.10+；不会安装依赖或重置已有数据库。原始入口也可运行：

```powershell
python -m src.main --db data/bank.db --user alice
```

如果系统 `python` 是不可用的 Windows 商店别名，使用 `start.ps1`。启动时“配置已读取”只是配置格式检查；输入“这个月已经花了多少？”并得到模型生成候选后的实际账单回执，才算一次真实调用。

随后输入“我有哪些自动扣款？”和“给小王转100元”，核对代码展示的动作、完整参数、用户、金额和有效期。明确同意时复制屏幕给出的固定 `/confirm <请求编号> <六位码>`；这六位码只是本次确认，不是强验证，不发送给模型。使用 `/cancel` 取消、`/audit` 查看本人脱敏回执、`/quit` 结束。

计划在需要确认的步骤暂停；确认后用 `/plan <计划编号>` 继续。`/interrupt <计划编号>` 中断，`/takeover <计划编号>` 标记需要人工接管。只有实际模型生成并由程序执行的计划，才可作为真实模型规划链路证据。

没有配置时，CLI 仍可通过 `/candidate {"intent":"query_balance","params":{}}` 运行明确标注的离线代码检查。自然语言请求会失败并记录审计，绝不会猜意图。不要将此模式写成已完成真实模型接入。

## 错误处理和数据边界

单次调用的网络连接与读取超时为25秒；这不是全过程硬时限。输入最多4000字符，候选最多16000字符，响应读取最多128 KiB。模型输出不完整、出现重复键、NaN/Infinity、Markdown 包装或不是 JSON 对象时失败；不自动重试，以免重复调用和增加费用。

仅对 `api.deepseek.com` 发送 `thinking: {"type":"disabled"}`；本轮只识别候选意图和计划，关闭推理以减少延迟和输出截断风险。该字段与默认推理模式依据 [DeepSeek 官方 Chat Completions 接口](https://api-docs.deepseek.com/api/create-chat-completion/)；不会向其他服务商发送专属参数。

HTTP 认证、额度、兼容性、网络及超时错误只展示固定说明和状态码，不展示供应商原始错误、响应正文、请求认证头或异常 traceback。可根据错误提示在本机核对配置。模型提供代码、SQL、命令或未知字段时不会执行，最终权限仍由 `BankService` 复核。

模型接收当前自然语言，以及本人用户编号、本人账户编号、登记联系人编号和名称、上海日期。程序重新构造字段白名单，不把订阅列表、账单备注、余额、确认码、密码或密钥放入模型上下文；含疑似秘密的自然语言拒绝发送。有效确认使用固定命令进入代码层，不经过模型。

日志与独立验收记录应写明真实调用是否发生、是否得到候选、实际结果和缺项。真实模型调用失败时应检查银行状态未变，并在审计中找到失败事件；不要用本机替身补成“真实模型通过”。

## 实际调用记录

北京时间2026-10-10，受限网络首次尝试失败；获准联网后的旧密钥请求返回 `model_http_error` / HTTP401，在第一条账单请求处停止。历史分别保留为[网络失败回执](../evidence/real-model-network-failure.json)和[认证失败回执](../evidence/real-model-auth-failure.json)。本机修正密钥后，`scripts/live_demo.py` 重新运行退出0，成功回执单独保存在[real-model-integration.json](../evidence/real-model-integration.json)。不输出或保存有效确认码、密钥和供应商原始错误。

| 真实请求 | 实际代码结果 | total_tokens |
|---|---|---|
| “这个月已经花了多少？” | analyze_bills，绿档success，5970分 | 700 |
| “我有哪些自动扣款？” | query_subscriptions，先pending，测试确认后success，未来预计5970分 | 699 |
| “请取消我的视频会员。” | cancel_subscription，先pending，测试确认后sub-video为cancelled | 705 |
| “这个月实际已经花了多少？” | analyze_bills，仍5970分，历史保留 | 701 |
| “从我的主账户给已经登记的小王转100元。” | transfer，先pending，测试确认后转10000分，当日累计10000分 | 721 |

这5次响应合计3526 token。测试脚本只有核对预先指定的模拟用户、目标和金额后才调用固定确认接口；这是集成测试的明确授权，不是生产自动确认或队友人工验收。主实现20:36另用 `start.ps1` 自然语言查询账单，实得59.70元并退出0；该单次CLI调用不计入上表5次用量。

上述5次请求未生成DAG；20:39:38另运行 `scripts/live_plan_demo.py`，两次真实模型请求合计1583 token，退出0，证据见[real-model-plans.json](../evidence/real-model-plans.json)。第一条计划实际完成账单5970分后等待订阅确认，接管使未完成节点取消，旧确认拒绝。第二条计划先查主账户余额1000000分，转10000分前暂停且后置查询未开始；核对预设目标并固定测试确认后，续跑读到990000分。SQLite快照保存双方余额990000 / 110000分、储蓄500000分，一条成功转账，重放拒绝。

这只证明两条指定真实模型依赖计划样例。真实MFA、隔离、完整补偿回退和正式APP / IM渠道仍缺；真实模型异常与攻击需要独立记录。未来预计取消后2980分及红档拒绝在离线演示和独立业务验收中核对，上述5条三场景真实回执没有额外复查这些结果；不能由这些成功推导正式达标或队友人工验收完成。

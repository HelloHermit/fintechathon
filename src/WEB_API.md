# 本机浏览器公开接口

Python标准库HTTPServer，固定可信用户由 `scripts/start.ps1 -Web -User alice` 指定，网页不接受身份切换。只监听127.0.0.1，默认8765，启动不会重置data/bank.db。单线程顺序办理复用BankService，不是生产登录、银行渠道或经过实测的沙箱。

GET `/`、`/app.css`、`/app.js` 只返回这三份固定静态资源，不开放任意文件。GET `/api/session` 返回user_id、csrf_token、model_configured、simulated。model_configured仅表示配置已读取，真实接通看实际请求。密钥、完整模型配置不返回浏览器。

POST必须为application/json对象、Content-Length为1至8192、无Transfer-Encoding、无重复JSON字段、非有限数字或额外业务字段，带 `X-CSRF-Token` 为本次session返回值。Host只允许 `127.0.0.1:实际端口` 或 `localhost:实际端口`；有Origin时必须与Host同源，拒绝Sec-Fetch-Site为cross-site/same-site。无CORS许可。非法来源/CSRF返回403，格式错误400，未知资源404；拒绝追加审计而不更改已有确认或业务。

| 路径 | 精确JSON字段 | 实际操作 |
|---|---|---|
| /api/message | text字符串 | 真实模型识别，BankService固定规则复查 |
| /api/confirm | request_id、confirmation_code | 代码绑定确认，不发模型 |
| /api/cancel | 可选request_id，可null | 取消当前本人请求 |
| /api/plan/resume | plan_id字符串 | 前置真实成功后推进 |
| /api/plan/interrupt | plan_id字符串 | 中断计划 |
| /api/plan/takeover | plan_id字符串 | 停止并交人工 |
| /api/audit | 空对象 | 本人脱敏回执 |

业务响应与PUBLIC_API一致。pending含屏显确认码，只留页面内存，不进localStorage/日志；确认后再次提交同请求必须rejected。新自然语言使旧授权失效。没有 `/candidate` HTTP接口或任意SQL/Shell工具。页面示例只填写输入，不自动发送或确认；渲染不可信文字用textContent。

所有响应Cache-Control:no-store，nosniff，frame拒绝，CSP限定本站脚本/样式/连接，不加载CDN；HTTP服务不打印请求正文或认证头。仅回环防护不能抵抗本机管理员/恶意进程，也不证明正式渠道或完整认证能力。

独立HTTP验收可启动新进程/新工作区数据库、用公开BankService接口及自定候选响应模型来保持离线可重复，但不可阅读业务实现确定期望；真实浏览器自然语言另外记录。测试不能清空正常data/bank.db。

离线测试启动约定：`from src.web import LocalServer, BrowserHandler`，在线程内部创建`BankService`与`LocalServer(("127.0.0.1", 0), BrowserHandler)`（测试端口0由系统分配）。为server赋公开依赖`bank`、`csrf_token`（ASCII字符串）、`model`（公开propose接口响应模型）、`model_configured`（布尔），随后`serve_forever()`，用server.server_port读取实际端口。`shutdown()`可从其他线程调用，`server_close()`、`bank.close()`在服务线程finally完成。

POST `/api/audit`的JSON为`{"status":"success","data":[事件对象],"simulated":true}`；审计故障时status为failed。未提供PUT、DELETE、PATCH、TRACE、HEAD、OPTIONS功能，返回405并追加来源/格式拒绝审计，不办理业务。HEAD无响应正文。重复Host、Origin、X-CSRF-Token、Content-Length头拒绝。测试不得把模拟模型路径误称真实服务。

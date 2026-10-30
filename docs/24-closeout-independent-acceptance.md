# 24 · 技术收尾独立验收

更新：2026-10-11。本轮发生在北京时间20:00内部原型验收节点之后，**不能写成按时完成**。

## 1. 已运行结论与独立性

新增独立专项 **18项**：修复前9通过、9失败、0错误、0跳过；修复后18通过、0失败/错误/跳过，9.685秒、退出码0。另按独立作者预先制定的步骤完成受控网页red等待→取消→yellow确认对照，并通过公开SQLite核对资金、交易和审计。原141项测试文件与期望没有修改；全套汇总由实现方另行保存。

作者只依据AGENTS.md、docs/01、docs/02、docs/22、src/PUBLIC_API.md、src/WEB_API.md、tests/README.md及已有独立测试设计期望。**未阅读业务、模型、Web、MFA CLI或web_assets实现**。通过公开BankService及HTTP入口运行，SQLite只访问公开表核对事实、写入合成登记前置。

所有库均为tests/.runs内新建临时库；不清空、不打开日常data/bank.db，不调用真实模型，不索取或输入真人密码、认证器秘密或动态码。测试中的登记是随机合成管理员夹具，不能作为真人已经登记或持有独立设备的证据。

## 2. 首轮发现与证据

完整stdout/stderr及时间：

- [修复前输出](../evidence/closeout-independent-20261011-201429-191141.txt)、[修复前清单](../evidence/closeout-independent-20261011-201429-191141.json)：20:14:29开始，18项运行9.828秒、退出1。
- [修复后输出](../evidence/closeout-independent-20261011-201654-709639.txt)、[修复后清单与安全实际观察](../evidence/closeout-independent-20261011-201654-709639.json)：20:16:54开始，18项运行9.685秒、退出0。

问题一：登记用户创建红档转账等待节点，再interrupt_plan/takeover_plan。期望取消日志保留节点red档位；实际首轮两项均在取消档位断言失败，黄档对照通过。首轮断言没有序列化实际错误档位，故独立证据能确认“至少一条取消日志不是red”，不从实现反推其字面值。修后观察清单明确记录两条cancelled/tier=red，业务快照不变；黄档cancelled/tier=yellow对照也通过。

问题二：黄档确认初检时在expires_at前1微秒，公开audit_hook在confirmed或executed事件INSERT前将clock推进到expires_at。期望当场expired，回滚业务及成功日志，只追加过期结果；实际首轮transfer、cancel_subscription、query_subscriptions两个阶段共6项全部返回success而失败。另一个同类用例先保留1次验证失败，再于executed审计跨期，也错误返回success。首轮断言在错误响应处停止，未逐一打印业务差异，不能把“有部分扣款”等未经保存的细节写成已观察事实。修后6条安全实际观察均为expired、业务四表完全不变、只追加expired；失败计数对照仍保留1。

修复前到修复后，仅给新测试增加安全实际观察及受控UI服务器模式；**18项期望和断言没有删除、放宽或改成配合实现**。测试清单保存各次文件SHA256，首轮和复测文件不同是上述记录能力的增加，不应声称两次测试文件字节完全相同。

## 3. 输入、期望、实际与验证方法

下表每项均已运行。`通过`表示检查公开响应、公开数据库及追加审计均满足相应断言，不代表真人、生产登录或隔离已经通过。

| 项 | 输入 / 初始前置 | 独立期望与验证方法 | 首轮实际 | 修后实际 | 最没把握处 |
|---|---|---|---|---|---|
| 01 | 合成登记；计划pay转100100分，later依赖pay；interrupt_plan | 节点cancelled、日志tier=red、旧验证无效、后续不执行、业务不变 | 取消日志档位不为red，失败 | 通过；cancelled/red | 首轮未输出错误档位字面值 |
| 02 | 同01；takeover_plan | 保留red取消审计、human_takeover、旧验证无效、业务不变 | 取消日志档位不为red，失败 | 通过；cancelled/red | 不证明已完成人工系统接入 |
| 03 | 黄档10000分等待计划；interrupt_plan | cancelled/yellow、interrupted、旧确认无效、后续不执行 | 通过 | 通过 | 仅内存候选计划 |
| 04 | 同03；takeover_plan | cancelled/yellow、human_takeover、旧确认无效 | 通过 | 通过 | 不证明补偿已提交事务 |
| 05 | 黄档transfer；confirmed审计跨期 | expired，无data，业务快照不变，无executed/success，过期追加 | 返回success，失败 | 通过 | 受控时钟，不是现实并发延迟 |
| 06 | 黄档transfer；executed审计跨期 | 同05；不能留下单边余额、流水或转账 | 返回success，失败 | 通过 | 相同 |
| 07 | sub-video取消；confirmed审计跨期 | expired，订阅/历史完全不变，无成功审计 | 返回success，失败 | 通过 | 相同 |
| 08 | sub-video取消；executed审计跨期 | 同07 | 返回success，失败 | 通过 | 相同 |
| 09 | 订阅查询；confirmed审计跨期 | expired，不披露列表，无成功审计 | 返回success，失败 | 通过 | 相同 |
| 10 | 订阅查询；executed审计跨期 | 同09 | 返回success，失败 | 通过 | 相同 |
| 11 | 三种黄档各自期限前1微秒；稳定clock | 三种正常确认均success，不误拒有效请求 | 通过 | 通过 | 期限内正常对照 |
| 12 | 三种黄档初次确认即expires_at | 均expired，不进入confirmed/executed审计，业务不变 | 通过 | 通过 | 相等边界已覆盖 |
| 13 | 先错1次transfer确认；新请求executed审计跨期 | expired且原failures=1，不按成功清零，业务不变 | 返回success，失败 | 通过 | 只检查一种操作的计数 |
| 14 | 成功转10000分、成功取消订阅，再等待转账；关闭重开原库 | 全部余额/订阅/交易/transfer保持，旧审计前缀保持并追加restart，旧pending无效 | 通过 | 通过 | 公开服务重启，不单独证明所有启动脚本参数 |
| 15 | 黄档错1次→取消；换目标/金额错第2次→重启；红档错第3次 | 黄红共用transfer计数；3次锁10分钟；可取消；重启锁定不变；599秒仍拒，600秒重新计1；业务不变 | 通过 | 通过 | 全为合成失败，不证明真人动态码输入 |
| 16 | HTTP受控模型给已登记用户red pending | 完整operation/期限，无confirmation_code；HTTP可取消且cancelled/red，业务不变 | 通过 | 通过 | HTTP通过不等于DOM控件正确 |
| 17 | red pending调黄档confirm；访问三个MFA候选路由 | strong_verification_required、不计失败、不执行；MFA路由404；原pending可取消 | 通过 | 通过 | 测了公开禁止入口与三个候选路径，不枚举全部URL |
| 18 | HTTP受控yellow pending并固定确认，再重放 | success一次，再次rejected且业务不再变 | 通过 | 通过 | 离线模型不是真实AI接通 |

## 4. 运行命令与受控网页复现

在仓库根目录运行，无第三方安装：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tests/test_closeout_independent.py
```

直接运行每次新建带时间的closeout-independent-*.txt/.json，不覆盖历史。通过全套unittest发现时也会纳入这18项，完整输出由全套运行器保存。

受控界面服务器只调用公开接口、新建临时库、随机合成登记、离线模型；使用当前上海时间以免浏览器Date.now把固定中午夹具误判过期：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tests/test_closeout_independent.py --serve-controlled-ui
```

服务器输出本次回环URL；`受控红档请求`固定返回100100分转账候选，其他文本固定返回10000分黄档候选。这两句话只是测试输入，不代表真实模型能解析这些请求。只保存安全运行记录，不打印、返回或截图登记秘密。

黑盒期望：主页→发送`受控红档请求`→等待卡片显示alice、transfer、alice-main、wang/bob-main、100100分对应金额、影响、red和expires_at；黄档确认控件隐藏并不可用；可见本机专用验证说明引导，并明确要新建本机请求、网页不收凭据、隔离未就绪仍拒绝。点击取消后卡片消失，追加cancelled/red且余额不变。再发送受控黄档输入，黄档确认恢复；确认只产生一条10000分成功转账；审计与双方余额一致。

## 5. 受控网页的独立判定与执行分工

**受控red等待→取消→yellow确认对照满足本轮公开行为契约。** 作者先制定输入、期望、固定控件动作与脱敏要求；因本子代理Browser环境不可用，根作为工具执行器仅执行作者指定动作、保存原始DOM/控件事实/console，不设计或判断独立期望。作者随后读取这些原始记录，并亲自只读公开SQLite进行独立断言。**不能声称这些DOM点击由本作者的Browser工具直接完成**；这与前端实现作者按自身实现做的网页自验分别记录。

环境：Codex IAB，http://127.0.0.1:57340/，标题“银行 AI 助手 · 模拟原型”，桌面受控新库、随机合成登记、离线模型。23:20–23:22北京时间运行。未获取独立截图或固定视口尺寸；本结论限于DOM行为和数据库事实，不据此宣称布局、手机视口或真人设备通过。

| 检查 | 原始观察与独立判定 |
|---|---|
| 页面身份 / 非空 | URL、标题一致；完整导航、对话与操作卡片存在，通过 |
| 框架错误 / console | DOM没有错误覆盖层；red、取消、最终success的error/warn均为空，通过 |
| 合法red pending | 显示“等待本机强验证”，不是格式错误；alice、red、小王、alice-main、wang、1001元、bob-main、日累计1001元、影响和北京时间有效期齐全，通过 |
| 网页权限边界 | confirm-button隐藏、不可见且disabled；cancel-button可见可用；只有聊天textarea，没有password/OTP input，通过 |
| 本机入口引导 | scripts/mfa_verify.py与《手机验证操作说明.md》；先取消网页请求，再本机新建重新核对；编号不能跨会话复用；隔离未实测仍拒绝，符合期望 |
| 取消 | red“已取消”、原操作卡片清空；公开请求cancelled，cancelled审计red，无executed，通过 |
| yellow对照 | 等待时只返回布尔结构：确认和取消可见且可用，yellow/operation/expiry存在，password/OTP字段0；未输出有效屏显码、pending全DOM或截图。立即点“确认这次操作”后观察最终“已完成”100元及alice-main→bob-main，不能把中间busy状态当成功，通过 |
| 资金、流水、审计 | alice-main=990000、alice-savings=500000、bob-main=110000分；仅一笔yellow成功10000分；对应alice转出/bob转入交易各10000分；yellow confirmed与executed/success，red cancelled/red，无红档执行，通过 |
| 独立截图 / 手机 | 未完成；实现侧截图另有证据，不能替代本报告独立DOM/资金判定，也不作为真人手机证据 |

原始浏览器记录：[red完整DOM与控件事实](../evidence/closeout-independent-ui-tool-red-dom.txt)、[取消、yellow等待安全布尔与最终成功DOM](../evidence/closeout-independent-ui-tool-cancel-success-dom.txt)。独立事实核对：[新库动作前检查点](../evidence/closeout-independent-ui-facts-before-20261011-2320.json)、[动作后资金/交易/请求/审计及独立断言](../evidence/closeout-independent-ui-facts-after-20261011-2324.json)；各文件实际记录时间以内容为准。

最终受控服务：[23:18启动记录](../evidence/closeout-independent-ui-server-20261011-231836-551203.txt)。此前20:16固定中午时钟服务未用于界面结论；20:17当前时钟服务曾返回正常首页，后来中断过程中进程结束，根访问旧URL得到连接拒绝。子代理fresh reset后仍Browser unavailable，而根Browser环境可用，故采用上述“独立作者设计与判定、根仅执行工具”的分工。环境过程另存[工具恢复记录](../evidence/closeout-independent-ui-runtime-20261011-2319.txt)，历史记录保留，不把连接故障解释成应用权限失败。

本专项不证明真人登记、独立手机、终端无回显、真实模型完整对话、生产身份认证、校内选拔提交、正式隔离、并发压力或完整补偿。红档仍没有执行许可。20:00以后的收尾和实际时间应如实保留。

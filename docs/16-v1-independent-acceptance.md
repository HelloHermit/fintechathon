# 16 · V1 订阅权限边界独立离线回归

2026-10-11 北京时间 14:16，新增四项全部通过：4 tests、0 failures、0 errors、0 skipped，0.528 秒，退出码 0。只运行本次新增文件，未复跑原 93 项。

## 规格依据与作者隔离

作者仅阅读 `AGENTS.md`、`docs/01-permission-tiers.md`、`docs/02-user-stories.md`、`docs/05-audit-log-spec.md`、`src/PUBLIC_API.md`、`tests/README.md`。未阅读业务 Python 实现、旧测试或 `scripts/v1_disclosure_check.py`，未调用模型；通过公开 `BankService` 执行，SQLite 仅访问公开表设置前置和核对事实。三个交付文件写入前均检查不存在，本作者独占写入。

权限表第 2、4、7 节允许绿档读取本人历史流水、统计实际账单，黄档订阅查询须先确认；实际支出和未来安排分开。US-02/03/04/05/29 分别规定历史流水、整数分账单、未确认不披露订阅列表、确认取消和取消不改历史。公开接口将 `actual_expense_cents/categories` 列为账单结果，`transactions` 列为流水结果，`subscriptions/future_expected_cents` 列为订阅结果，并公布精确 `confirm` 接口和可核对的表。

## 输入、预期与实际

固定 alice 和上海时间 2026-10-11 12:00；对照库从同一夹具复制，账户及全部历史流水先核对相同，只改变 `sub-video` 的指定字段。所有数据库放在测试创建的系统临时目录，正式 `data/bank.db` 未访问。

| 用例 | 输入 / 前置 | 预期 | 实际 / 是否运行 |
|---|---|---|---|
| 订阅状态与绿档 | 两库仅视频订阅 active / cancelled；分别查询本月账单和流水 | 实际支出均 5970 分，categories 及全部 data 业务结果相同；绿 data 不含订阅列表、未来合计字段 | 已运行，通过 |
| 未来金额与绿档 | 状态均 active，仅视频未来金额 2990 / 3990 分；历史支付不变 | 绿结果仍一致；确认查询订阅后未来合计分别 5970 / 6970 分、订阅结果不同 | 已运行，通过 |
| 黄档查询确认边界 | active / cancelled 对照；先 propose，再使用各自的精确 confirm | pending/yellow；未确认无订阅列表、未来合计，去除流程字段后的确认说明一致；确认后合计 5970 / 2980 分、订阅结果不同 | 已运行，通过 |
| 公开取消与历史 | 查询历史，再申请并确认取消视频订阅，再查历史及订阅 | 确认前 active，确认后 cancelled；账户、原始历史表和绿 data 不变；确认订阅查询后未来合计 2980 分 | 已运行，通过 |

比较保留正常历史支付的商户、分类、金额和交易状态，不把“历史上有订阅付款”判为泄露；也不根据历史周期性推断当前订阅仍有效。请求编号、有效期及确认码不参与业务数据对照；确认码仅在内存使用，没有写入证据。

## 实际运行与失败历史

实际在仓库根目录运行两次同一命令：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B tests/test_v1_permission_boundary.py
```

首轮 4 tests、0 failures、4 errors、0 skipped，0.517 秒，退出码 1。四个错误均为临时库清理时的 Windows 文件占用：测试作者使用 SQLite 连接上下文后没有显式关闭连接。仅修正新增测试的资源释放和证据追加方式，业务断言未降低、业务实现未修改；随后得到上述 4 项通过结果。两轮原始输出均按顺序保留在 `evidence/v1-independent-acceptance.txt`，首轮脚手架故障不记为业务失败，也不当作首轮通过。

以后可以原样使用上述入口，证据每次追加；也可只发现此新增文件，以下命令本轮未另行运行：

```powershell
& 'C:\Users\KindHermit\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -p 'test_v1_permission_boundary.py' -v
```

## 版本证据与限制

每轮在首次导入公开业务接口前和运行结束后，对全部 6 个 `src` Python 文件计算 SHA256，仅输出哈希，不读取内容决定期望。两轮各自前后均无变化，完整清单在原始证据中。通过轮 `src/bank.py` SHA256 为 `2d896fd8983b25abfca8dc704ad7d3cf680542eac303328a96b57a098f5a375f`；新增测试 SHA256 为 `7ba7bac4588922becc8694f10fe43be41fa30a2cd86f52810f4e064d901b292b`。

最没把握处：规格没有完整定义所有间接披露路径，本次只验证公开业务接口这四组对照，不能证明模型上下文、审计回执、Web 界面或所有输入组合不存在泄露。源码前后哈希一致也不能排除期间短暂变更后恢复。结果属于独立离线回归，不代表真实模型对话、队友人工验收、并发专项、真实 MFA 或隔离已经通过。

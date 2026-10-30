# 38 · 六方向本机复现

2026-10-25，全部为模拟数据。接口规则见[六场景契约](../src/SIX_SCENARIO_API.md)，测试通过与缺项须看本轮最终交付，以下是可重复步骤。真人手机、终端和队友人工核验继续延期。

## 启动

使用Python 3.10+标准库；不新增业务依赖。真实自然语言识别使用现有本机模型配置，密钥不填写在聊天、命令行或仓库。运行前确保Docker Desktop已运行及既有Python3.12镜像在本机；下列准备只使用本地镜像，不安装或联网拉取。

```powershell
Set-Location C:\fintechathon
$Python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Docker = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
# 已有本轮a1目录则直接启动；新机器请以不存在的目录名建立，再将下两处路径同步替换。
& $Python scripts/docker_isolation_setup.py --runtime-dir .isolation/docker-runtime-six-20261025-a1 --image python:3.12-slim --docker-executable $Docker
# 示例使用自己新选的库名；已有库永不重置，不能假定其金额是初始值。
& $Python -m src.web --db data/six-personal-demo.db --user alice --port 8765 --isolated-tools --isolation-runtime .isolation/docker-runtime-six-20261025-a1 --isolation-monitor .isolation/six-personal-monitor.db
```

打开[本机网站](http://127.0.0.1:8765)。默认alice是预设模拟身份，不是生产登录。网页展示操作后本人核对，点击固定确认按钮；在聊天打“确认”不能授权，屏显码不是MFA。想无模型查看历史可用`python scripts/recovery.py --db <同一模拟库> --user alice`；另开实例会使该用户旧授权失效，不要与网站同时操作同一库。

## 每个方向的输入和预期

以下每行可在独立全新库复现，旧动作先前产生的账单会影响后续合计。所有金额以分存储，网页以元显示。

| 方向 | 人类输入 | 确认及预期 |
|---|---|---|
| 转账 | 给小王转100元，从我的主账户。 | 未确认资金不变；确认后主账户990000分、小王110000分，双向流水各一条，同请求不能重复执行 |
| 账单 | 查看我本月已经花了多少。 | 绿档；全新库实际5970分，失败/未来记录不计；已有转账/订单后按成功记录更新 |
| 订阅 | 查询我的自动扣款。随后另发：取消视频会员。 | 两次分别黄档确认；初始未来5970分，退视频后未来2980分，实际旧账单不删 |
| 理财 | 查询模拟理财产品。比较p-cash和p-steady。匹配理财产品，低风险，期限30天，流动性即时。 | 分别发三次；绿档返回固定数据，比较顺序保持；匹配仅p-cash，无真实收益承诺 |
| 卡片 | 查询我的模拟卡。为我的主账户申请模拟虚拟卡。设置卡片card-alice-main的日限额为100元。 | 查询绿档，后两次分别黄档；确认才新增virtual卡/把限额写为10000分；鲜花12900分显式选这张卡即超卡限额而拒绝 |
| 生活任务 | 为2026-11-01从我的主账户保留预算birthday，金额200元。 | 日期须仍在今日至366天内，过期后自行明确新ISO日期；确认后账面1000000、保留20000、可用980000分，不计消费 |

生活任务接着发送：`用预算birthday，在2026-11-01选择flower-basic模拟鲜花下单。` 核对固定129元及预算来源后确认；账面987100、预算spent12900/remaining7100、可用980000，本月实际18870分。再订cake-basic蛋糕99元因预算不足拒绝。发送`释放预算birthday。`并另行确认，只释放剩余7100分；已付订单、账面987100和实际18870分不回退。

预算先单独办理，然后可明确组合：`先查询模拟服务，再用预算birthday在2026-11-01选择flower-basic模拟鲜花下单，然后查询预算birthday，查询预算birthday的订单，查询我的主账户余额和本月账单。` 计划停在订单黄档等固定确认，后续核对节点依赖付款成功。卡片申请后的新ID不能靠“刚才那个”自动授予修改权限，需明确ID另办。计划最多8步，所有目标须接纳时已存在，不支持$ref和后台定时。

## 重启恢复与拒绝

订单等待确认时重启，旧码失效，预算仍保留但尚未付款。网页历史任务中选择计划，核对当前预算、服务价、日期、余额和累计，点击恢复同意，再点击继续；订单产生新请求并再次黄档确认。恢复同意不支付，重复查看/继续不重复扣款。取消剩余任务不退款、不自动释放预算；已经成功的模拟卡/预算/订单事实在历史保留。

申购、赎回、挂失、解挂及超过资金日累计阈值的付款仍为红档拒绝，不用拒绝路径声称交易已完成。转账和订单跨账户共同计入上海当天100000分黄档阈值，且共享资金确认失败计数，三错锁十分钟；换目标、工具或重启不清零。审计或隔离出错停止，不写入部分成功结果。

离线独立组：`python scripts/six_check.py --suite independent`；既有上下文/恢复分别用`--suite context/recovery`；实际Docker独立组用`--suite docker --runtime .isolation/docker-runtime-six-20261025-a1`。真实模型与网页验收另存原始证据，不能把离线替身当真实服务通过。

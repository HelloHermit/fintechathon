# 验收决策原型公开规格 v0.1

此规格描述一个只处理JSON记录的证据门控模块，不执行候选代码、测试代码或模型输出，不证明记录内容真实。注册表由独立控制端维护，须经过需求和测试判定依据的审核；模型输出无权自行注册oracle。原型不承担沙箱、代码检测或完整自动验收能力。

## 接口

Python文件：src/evidence_gate.py  
函数：decide(registry: dict, run: dict) -> dict

返回必含decision和reason_codes。decision只能是ACCEPT_UNDER_PROTOCOL、DEFECT_CONFIRMED、REVIEW_REQUIRED。其余统计字段可补充，测试不得依赖字典输出顺序。

## 注册表（可信控制端输入）

- schema_version：整数1（bool不算整数1）。
- task_id、spec_revision：非空字符串。
- constraints：非空列表，每项有唯一非空id和非空required_groups字符串列表；组名不能重复。
- oracles：非空列表，每项有唯一非空id、已知constraint_id、非空groups字符串列表；groups必须是该约束required_groups的子集，不能重复。

例：
{"schema_version":1,"task_id":"T1","spec_revision":"v1","constraints":[{"id":"C1","required_groups":["normal","edge"]}],"oracles":[{"id":"O1","constraint_id":"C1","groups":["normal","edge"]}]}

注册表格式不合法时直接REVIEW_REQUIRED，reason_codes包含invalid_registry。

## 单次记录

- task_id、spec_revision必须与注册表一致。
- program_sha256为64位十六进制字符串；按小写规范化，不验证真实程序内容。
- complete为bool；仅true代表该批计划已完成。
- pipeline_errors、unresolved_warnings为字符串列表，空列表表示无已登记问题。
- evidence为列表（允许空）。

任务或版本不一致、run结构不合法：REVIEW_REQUIRED，包含invalid_run。不得从无效整批中确认缺陷。

每条evidence有oracle_id、group、input_digest、program_sha256、spec_revision、outcome：
- oracle_id必须已注册，group必须在该oracle允许范围内。
- 两个digest字段为64位十六进制字符串。
- program_sha256和spec_revision必须匹配本次run。
- outcome只能pass/fail/error/unknown。

非法单条记录、未知oracle、越界group、陈旧版本或不同程序哈希进入需复核问题，不能充当通过或缺陷证据。

## 归并与冲突

按已注册oracle_id＋规范化input_digest归并有效记录。同一键多份相同group、相同outcome只算一个案例，不增加需求组覆盖。

同键outcome或group不同视为冲突，该键不提供通过/失败证据，reason_codes包含conflicting_evidence。

不同输入或不同oracle的正常pass/fail不自动视为冲突；有效fail代表一个已登记判定依据下的反例。

## 判定顺序

1. 注册表或整批身份无效 -> REVIEW_REQUIRED。
2. 归并后存在无冲突的有效fail -> DEFECT_CONFIRMED，包含validated_counterexample；它可以优先于其他单条错误、缺组、complete=false或pipeline_errors。
3. 若无第2种反例，存在非法单条、冲突、error/unknown、complete=false、pipeline_errors或unresolved_warnings -> REVIEW_REQUIRED。
4. 若无上述问题，但任一约束required_groups未被有效pass覆盖 -> REVIEW_REQUIRED，包含missing_required_groups。
5. 全部必需组有有效pass且批次完整、无问题 -> ACCEPT_UNDER_PROTOCOL，包含required_groups_checked。

空evidence不会通过；重复正常组记录不能补足edge组；静态分析或LLM的意见若未注册成已审核判定依据，不能自称反例。

## 统计字段建议

covered_groups、missing_groups：按constraint_id列组名；unique_cases：有效记录归并键数；duplicate_records：有效记录数减键数。冲突键可计入unique_cases，但不能计入覆盖。以上字段用于诊断，不用于认证正确性。

## 验证重点

- 关键组缺失、空记录、异常或警告不能自动通过。
- 重复证据、记录顺序和十六进制大小写不能改变决定。
- 陈旧版本或其他程序记录不能影响当前程序。
- 冲突不自动当作代码缺陷。
- 有效独立反例优先，格式错误/未审核意见不能假冒反例。
- 空注册表及bool版本号不能导致空条件自动通过。

演示输入只能标为synthetic fixture，不是AI代码实验数据。测试作者只依据此公开规格，不读取实现后设计测试。


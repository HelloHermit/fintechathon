# 第一阶段迭代与独立验收记录（历史资料）

这里保存的是 2026-10-30 之前第一阶段（Codex 时期）的范围、权限规则、独立验收与交付记录。

**它们不是当前规则。** 冲刺期（10-30 起）的规则以仓库根目录 `CLAUDE.md` 和 `docs/sprint/` 下的三份文件为准：

1. `docs/sprint/API_V2.md` —— 前后端接口契约
2. `docs/sprint/SEED.md` —— 演示数据规格
3. `docs/sprint/PLAN.md` —— 冲刺方案

和现在不同的旧规则举例：旧规则里“红档一律拒绝”，现在红档在通过交易密码 + 模拟短信动态码后可以真正执行；旧规则只覆盖三个场景，现在覆盖六个。

保留这些文件的原因：

- 它们记录了安全内核（确认绑定、只追加审计、失败锁定、整数分）是怎么一步步设计和独立验收的，新版本沿用了这个内核；
- 旧测试（`tests/`）的注释里引用了这些文档编号；
- 如实保留失败记录与修复过程，便于评委追溯。

`AGENTS-codex-era.md` 是第一阶段的项目契约，已被 `CLAUDE.md` 取代。旧的过程文件（任务清单、提示词、分工表等）已从 `main` 删除，仍可在 `evidence` 分支和 git 历史里查到。

## 文件列表

| 文件 | 标题 |
|---|---|
| [00-scope.md](00-scope.md) | 00 · 范围与交付计划（v3） |
| [01-permission-tiers.md](01-permission-tiers.md) | 01 · 权限与执行规范（v3） |
| [01b-review-response.md](01b-review-response.md) | 历史附录：订阅权限 v1 / v2 审查对账 |
| [02-user-stories.md](02-user-stories.md) | 02 · 用户故事与独立验收（v3） |
| [03-security-self-assessment.md](03-security-self-assessment.md) | 03 · 安全自评报告 |
| [04-known-risks.md](04-known-risks.md) | 04 · 已知风险与阶段缺项 |
| [05-audit-log-spec.md](05-audit-log-spec.md) | 05 · 审计日志规格 |
| [06-red-team-findings.md](06-red-team-findings.md) | 06 · 攻击测试与发现记录 |
| [07-defense-qa.md](07-defense-qa.md) | 07 · 答辩问题与回答要点 |
| [08-arch-task.md](08-arch-task.md) | 架构检查任务 · 当前执行版 |
| [08-minimal-architecture.md](08-minimal-architecture.md) | 08 · 原型架构与执行链路 |
| [09-independent-acceptance.md](09-independent-acceptance.md) | 09 · 隔离独立验收记录 |
| [10-feasibility-evidence.md](10-feasibility-evidence.md) | 10 · 强验证、任务依赖与隔离可行性记录 |
| [11-technical-note.md](11-technical-note.md) | 11 · 三场景模拟银行助手技术说明草稿 |
| [11b-technical-note-plain.md](11b-technical-note-plain.md) | 11b · 技术说明（同学能听懂版） |
| [12-school-demo-draft.md](12-school-demo-draft.md) | 12 · 校内展示草稿（约八分钟） |
| [12b-demo-script.md](12b-demo-script.md) | 12b · 校内演示口播稿（约 8 分钟） |
| [13-real-model-acceptance.md](13-real-model-acceptance.md) | 13 · 真实模型异常用例与独立证据审核 |
| [14-browser-design.md](14-browser-design.md) | 本机浏览器界面设计与核对 |
| [14-judge-pressure-review.md](14-judge-pressure-review.md) | 14 · 现场评委压力审查（红队） |
| [15-team-agent-handoff.md](15-team-agent-handoff.md) | 15 · 队友与额外 agent 的当前交接任务 |
| [16-v1-independent-acceptance.md](16-v1-independent-acceptance.md) | 16 · V1 订阅权限边界独立离线回归 |
| [17-manual-acceptance-record.md](17-manual-acceptance-record.md) | 17 · 队友人工验收记录表 |
| [18-v1-disclosure-policy.md](18-v1-disclosure-policy.md) | 18 · V1 披露边界与待补证据 |
| [19-mfa-independent-test-plan.md](19-mfa-independent-test-plan.md) | 19 · MFA 独立验收清单（设计与历史） |
| [20-v2-process-independent-acceptance.md](20-v2-process-independent-acceptance.md) | 20 · V2 真双进程独立专项验收 |
| [21-mfa-contract-review.md](21-mfa-contract-review.md) | 21 · MFA 公开契约独立审阅 |
| [22-mfa-strong-verification.md](22-mfa-strong-verification.md) | 22 · 红档强验证（MFA）规则与公开接口 |
| [23-mfa-independent-acceptance.md](23-mfa-independent-acceptance.md) | 23 · MFA 独立合成验收 |
| [24-closeout-independent-acceptance.md](24-closeout-independent-acceptance.md) | 24 · 技术收尾独立验收 |
| [25-technical-closeout.md](25-technical-closeout.md) | 25 · 2026-10-11技术收尾记录（封包前） |
| [26-closeout-delivery.md](26-closeout-delivery.md) | 26 · 技术收尾最终交付 |
| [27-isolation-boundary.md](27-isolation-boundary.md) | 27 · 受限执行环境边界与阶段记录 |
| [27a-windows-isolation-development.md](27a-windows-isolation-development.md) | 27a · Windows LPAC 开发记录与未完成边界 |
| [28-isolation-independent-acceptance.md](28-isolation-independent-acceptance.md) | 28 · 受限执行独立验收 |
| [29-task1-isolation-delivery.md](29-task1-isolation-delivery.md) | 29 · task1受限执行阶段交付记录 |
| [29a-docker-isolation-independent-acceptance.md](29a-docker-isolation-independent-acceptance.md) | 29a · Linux Docker 隔离独立验收 |
| [30-recovery-acceptance-matrix.md](30-recovery-acceptance-matrix.md) | 30 · 状态保存、故障恢复与人工接管独立验收矩阵 |
| [31-recovery-independent-acceptance.md](31-recovery-independent-acceptance.md) | 31 · 任务保存、恢复与接管独立验收设计 |
| [32-recovery-delivery.md](32-recovery-delivery.md) | 32 · task2 状态保存、恢复与本地接管交付 |
| [33-context-planning-acceptance-matrix.md](33-context-planning-acceptance-matrix.md) | 33 · 多轮上下文与依赖规划独立验收矩阵 |
| [34-context-independent-acceptance.md](34-context-independent-acceptance.md) | 34 · 多轮上下文与依赖规划独立验收设计 |
| [34a-context-live-matrix.md](34a-context-live-matrix.md) | 34a · task3真实模型固定输入与运行器设计 |
| [34b-context-live-runner-review.md](34b-context-live-runner-review.md) | 34b · task3真实模型运行器与原closeout专项复核 |
| [35-context-delivery.md](35-context-delivery.md) | 35 · task3 多轮澄清与复杂计划交付 |
| [36-six-scenario-scope.md](36-six-scenario-scope.md) | 36 · 六场景支持范围与新增规则提案 |
| [37-six-independent-matrix.md](37-six-independent-matrix.md) | 37 · 六场景独立输入与期望矩阵 |
| [38-six-reproduce.md](38-six-reproduce.md) | 38 · 六方向本机复现 |
| [39-six-live-matrix.md](39-six-live-matrix.md) | 39 · 六场景真实模型独立矩阵 |
| [40-six-independent-acceptance.md](40-six-independent-acceptance.md) | 40 · 六场景独立验收判读 |
| [41-six-delivery.md](41-six-delivery.md) | 41 · 六场景交付与验证 |
| [42-six-package-verification.md](42-six-package-verification.md) | 42 · 六场景完整包最终核验 |
| [model-configuration.md](model-configuration.md) | 本机模型配置与真实调用验收 |
| [AGENTS-codex-era.md](AGENTS-codex-era.md) | 第一阶段项目契约（已被 CLAUDE.md 取代） |
| [README-第一阶段.md](README-第一阶段.md) | 第一阶段的仓库首页说明 |

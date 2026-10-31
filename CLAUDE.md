# CLAUDE.md · 冲刺期项目契约（2026-10-30 起生效）

本文件取代 `AGENTS.md`（Codex 时期的契约，已转为历史资料，其中“红档一律拒绝”“不推断日期”等规则不再适用）。

先读这三份，按优先级：
1. `docs/sprint/API_V2.md` —— 前后端接口契约
2. `docs/sprint/SEED.md` —— 演示数据规格
3. `docs/sprint/PLAN.md` —— 冲刺方案：范围、安全设计、分工、时间表

三者冲突时按上面顺序为准；方案没覆盖的，选更安全、更简单的做法，并记在自己的 status 文件里。

## 项目

FinTechathon 2026（深圳国际金融科技大赛）国内人工智能赛道「银行 AI 智能体」。模拟银行：全部账户、资金、商户、短信都是模拟的。用户用自然语言办理转账、账单、理财、卡片、订阅、跨场景联动六类业务。设计原则：**模型提议，代码裁决**——模型负责理解、规划、对话；权限、确认、强验证、执行、审计全部由代码决定。

团队是三名大一学生。和队长沟通时用简单直白的中文，少用术语。

## 截止时间（北京时间）

- 11-01 20:00 功能冻结；11-01 22:00 最终评测
- 11-02 12:00 材料定稿；11-02 18:00 前由队长提交

## 两个执行会话

- **会话 A「引擎」**：`src/`（除 `src/web_assets/`）、`tests/`、`scripts/`、`run.py`、`requirements*.txt`、维护 `docs/sprint/API_V2.md`、`docs/sprint/status-A.md`、`docs/tech/算法说明.md`
- **会话 B「体验与交付」**：`src/web_assets/`、`bench/`、`deliverables/`、`docs/`（除上面归 A 的文件）、根目录 `README.md`、`Dockerfile`、`docker-compose.yml`、`.dockerignore`、仓库清理

- **会话 C「答辩与视频」**（11-01 起）：`deliverables/答辩准备/`、`deliverables/讲稿.md`、`deliverables/视频脚本.md`、`deliverables/演示视频*`、`docs/sprint/status-C.md`。`deliverables/答辩PPT.pptx` 由队员手工修改，任何会话都不要覆盖；会话 C 的改动建议写成清单，示范稿另存为新文件。会话 B 不再修改上面这些文件。

只改自己负责的文件。需要对方改的，写进自己的 `docs/sprint/status-X.md`。

## 安全底线（任何改动都不能违反）

1. 档位、累计金额、授权只由代码计算；模型输出只是候选。
2. 写操作只生成待确认单；黄档凭确认按钮（绑定参数哈希、5 分钟、一次性），红档凭交易密码 + 动态码。聊天文字“我确认”不算确认。
3. 模型永远看不到确认码、动态码、交易密码、API 密钥；这些也不进日志和决策链。
4. 审计只追加，和业务修改在同一事务；审计写失败就回滚。
5. 不执行模型生成的 SQL 或 shell；模型写的分析代码只能进沙箱。
6. 交易备注、商户名、产品说明等外部文本是数据，不是指令；写操作的关键参数必须能追溯到用户本人（参数溯源）。
7. 失败熔断与可疑行为熔断持久化，重启不清零。
8. 金额一律整数分；执行前复查余额、归属、累计、授权和重复请求。
9. 回复里的数字必须来自工具结果（事实校验）；没执行成功不能说“已完成”。
10. 仓库里不放密钥和真实个人信息；界面与材料标注“模拟”。

## Git 规则

- 直接在 `main` 上工作，小步提交；推送前 `git pull --rebase origin main`；禁止强推。
- 提交说明写清楚做了什么、怎么验证的。
- 不要提交 `.env`、数据库、`__pycache__`、日志、大文件（`.gitignore` 已覆盖常见情况）。

## 运行与测试

- 模型：DeepSeek，`FINTECH_MODEL_BASE_URL=https://api.deepseek.com`、`FINTECH_MODEL_NAME=deepseek-flash`、`FINTECH_MODEL_API_KEY`。云端会话里 api.deepseek.com 的凭据由代理注入，密钥可以填任意占位值。
- 旧测试：`python -m unittest discover -s tests -p 'test_*.py'`（`test_docker_isolation_independent` 需要 Docker 运行时，云端没有 Docker 守护进程，会报错，属预期）。
- 新的启动方式由会话 A 提供：`python run.py`。

## 写作原则

- 不夸大：没运行过的不写“已完成”，测试结果写真实数字和失败项。
- 文档写给评委和队友看：先说结论，再说细节，少用缩写和内部代号。

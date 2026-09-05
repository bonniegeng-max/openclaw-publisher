# 已发布 Skill 静态审计

状态：`observation-window-hold`

审计日期：`2026-09-05`

适用范围：当前仓库中的 7 个已发布 Skill、`.clawhub/skill-catalog.json`
和仓库说明文件。

本次只读取本地版本控制内容，没有访问 ClawHub、刷新指标、运行搜索、
安装 Skill、执行 dry-run 或触发发布。以下结论不能用于解释自然采用变化。

## 最高优先级修复

### Portfolio 示例违反决策闸门

涉及文件：

- `skills/skill-portfolio-growth-audit/SKILL.md`
- `skills/skill-portfolio-growth-audit/examples/portfolio_decision_example.md`

正文规定，只有以下条件全部满足，才允许输出加码、修复、合并、停更、
新建或重定位结论：

- `evidenceQuality.decisionReady: true`
- 前后快照采集方法一致
- 前后快照均为 `activeInstall: false`
- 观察间隔至少 7 天
- 搜索 query、limit 和完整 query set 一致

现有示例只提供单次横截面，没有上述闸门证据，却直接对 A、B、D 给出
“加码”“修复”“停更或重定位”。这是可由仓库内容直接证明的合同冲突，
不是增长效果假设。

观察窗结束后的唯一最高优先级动作：

> 重写该示例，使其展示前后两轮可比快照、五项闸门、污染排除和最终
> `decisionReady`；如果保留单次快照，则所有组合动作必须降级为
> “继续观察”或“修复数据质量”。

验收标准：

1. 示例显式给出两轮采集时间，间隔不少于 7 天。
2. 两轮采集方法相同且均明确 `activeInstall: false`。
3. 搜索 query、每条 query 的 limit 和 query set 完全一致。
4. 示例先逐项计算五个闸门，再输出组合动作。
5. 任一闸门失败的反例只能输出“继续观察”或“修复数据质量”。
6. 测试能够阻止示例再次缺失 `decisionReady`、双快照或污染字段。

已在 `research/skill-portfolio-growth-audit-vnext/` 准备未就绪场景的候选
替换示例和机器可验 fixture。它只使用当前仓库可以证明的观察策略、查询
配置和成对报告缺失状态，不填造采用或搜索数据。

## 候选池

### 纯文案 Skill 的依赖契约

涉及：

- `skills/skill-summary-rewriter/SKILL.md`
- `skills/skill-positioning-audit/SKILL.md`

两者的核心任务都是分析和改写用户提供的文本，但 frontmatter 同时声明
`macos`、`git`、`clawhub` 和 ClawHub CLI 安装步骤。正文没有说明这些
依赖参与哪一步。

这是“能力叙述与依赖声明不一致”的静态事实。平台是否据此过滤兼容性或
增加安装摩擦尚未验证，因此观察窗内不直接修改。后续应先确认当前
ClawHub schema 是否允许省略这些字段；若允许，在一次实质版本中删除
无用硬依赖，若不允许，则在首屏解释真实用途。

### 相邻产品首屏边界重叠

`skill-publish-readiness`、`skill-launch-checklist`、
`skill-positioning-audit` 和 `skill-summary-rewriter` 都涉及摘要、定位、
差异化或页面质量。根 README 已解释产品路径，但单个商店页首屏不一定
能看到这套分工。

后续首屏只强化现有边界，不扩张能力：

- Launch Checklist：快速 go/no-go。
- Publish Readiness：完整证据矩阵与发布阻塞项。
- Positioning Audit：受众、场景与差异化策略。
- Summary Rewriter：直接交付 3–5 版可替换摘要。

是否调整 metadata 或 topics，必须等待同口径搜索与采用证据，不根据本次
静态重叠直接改动。

### 示例没有兑现输出合同

除 `skill-publish-readiness` 的真实失败复盘外，多数示例更像提纲，
没有完整展示 Skill 正文承诺的输入、证据、判断与最终报告。优先候选包括：

- `skill-summary-rewriter/examples/weak_vs_strong_summaries.md`：
  应展示 3–5 版摘要、唯一推荐版和使用位置。
- `github-actions-clawhub-doctor/examples/pending_publication_false_failure.md`：
  应展示脱敏日志、状态判定和后续验证边界。
- `release-proof-builder/examples/green_action_missing_registry.md`：
  应展示 E0–E4 证据矩阵及未达等级。
- `skill-launch-checklist/examples/launch_ready_vs_rushed.md`：
  应展示实际检查输入和完整 go/no-go 输出。

补充示例必须来自真实或明确匿名化的失败记录，不制造平台结果。

### Positioning 示例标题自相矛盾

`skills/skill-positioning-audit/examples/weak_vs_strong_positioning.md`
把 `skill-positioning-audit` 作为“更强定位”的标题，但正文同时把
“标题像内部目录名”列为主要问题，catalog 的实际展示名也是
`Skill Positioning Audit`。

后续修复应把强示例标题改为人类可读产品名，并明确区分 display name 与
稳定 slug。

### `skills/README.md` 落后于发布契约

当前说明只要求 `SKILL.md`，示例缺少稳定 `slug`、`CHANGELOG.md`、
`.clawhubignore` 和 catalog 条目，与 `AGENTS.md` 及真实 workflow
合同不一致。这主要影响贡献者成功率，应与下一次文档维护一起修复，
不需要触发 Skill 发布。

## 执行边界

- 在 `2026-09-12 10:26:39`（北京时间）前不修改已发布 Skill。
- 不因本次静态审计声称下载、安装或搜索排名受到影响。
- 观察窗结束后只运行一次统一增长监控入口。
- 若组合闸门合格，先结合真实采用与搜索信号确认目标 Skill。
- 无论增长数据如何，Portfolio 示例的合同冲突都属于正确性修复候选；
  是否立即发布仍需评估对观察窗口和 E4 验收的影响。
- 一次只执行一个最高优先级动作，其余项目保留在候选池。

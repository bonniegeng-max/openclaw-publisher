# Skill Summary Rewriter 完整示例草案

状态：`observation-window-hold`

本目录保存已发布 `skill-summary-rewriter` 的下一版示例候选，不是新 Skill，
不进入 catalog，也不触发 ClawHub 发布。

## 修复目标

现有 `examples/weak_vs_strong_summaries.md` 提供 3 组“一弱一强”对照，但
没有完整兑现 `SKILL.md` 的输出合同：

1. 诊断当前问题。
2. 说明重写方向。
3. 给出 3–5 条可直接替换的摘要。
4. 标出唯一最推荐版本。
5. 说明每条适合放在 summary、标题下文案还是 README 首段。

## 真实输入

候选示例使用仓库历史中真实存在过的摘要，而不是为了展示效果临时编造。

- 来源提交：`77a4b1864655693b860f731dd2fd51e4c182cbd9`
- 来源文件：`skills/skill-publish-readiness/SKILL.md`
- 当时版本：`1.0.0`
- 字段：frontmatter `description`

原文：

> 在发布到 ClawHub 之前，帮你揪出那些“能过 dry-run，但其实还不该发”的
> 问题，包括文件缺失、版本不一致、环境声明脱节、安全风险和同质化定位。

这条摘要已经具备真实场景和记忆点，不属于“完全无效”。候选改写的目标是
缩短理解路径、减少功能枚举，并按不同页面位置提供可选版本，而不是抹掉原
有风格。

## 文件

- `source-and-output.json`：机器可验的历史来源、诊断、4 个候选和唯一推荐。
- `complete_summary_rewrite.md`：可直接替换现有示例的完整输出。

## 声明边界

- 这是文案输出合同修复，不证明当前摘要导致下载或搜索损失。
- 候选版本没有在 ClawHub 做 A/B 测试，不宣称转化提升。
- 是否进入正式 Skill，仍需等待自然观察窗口后的组合决策。
- 即使提升，也应与运行 metadata 修复合并为一次实质版本，避免无意义版本。

## 提升条件

1. 不早于 `2026-09-12T10:45:38+00:00` 运行一次统一增长监控。
2. 确认 Summary Rewriter 仍有独立采用或搜索信号。
3. 将候选示例与运行 metadata 修复合并审查，避免连续发布。
4. 更新正式版本与 changelog，通过本地回归和 dry-run。
5. 发布后只执行一次计划内 E4，并重建自然观察起点。

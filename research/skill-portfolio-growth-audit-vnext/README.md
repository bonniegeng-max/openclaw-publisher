# Skill Portfolio Growth Audit vNext

状态：`observation-window-hold`

此目录保存已发布 `skill-portfolio-growth-audit` 的下一版修复草案，不是新
Skill，不进入 `.clawhub/skill-catalog.json`，也不触发 ClawHub 发布。

## 修复目标

现有 `examples/portfolio_decision_example.md` 只展示一次横截面，却直接
输出加码、修复和停更结论，与 `SKILL.md` 的五项决策就绪闸门冲突。

候选替换示例 `portfolio_decision_example.md` 使用当前真实仓库状态：

- 已有观察策略
- 已有固定搜索查询配置
- 尚无合格成对决策报告
- 因此 `decisionReady: false`
- 唯一允许结论为“继续观察”

它不制造 downloads、installs、stars、排名或竞品数据。

## 文件

- `decision-not-ready.json`：机器可验的未就绪闸门 fixture
- `portfolio_decision_example.md`：候选替换示例

## 提升条件

只有在 `2026-09-12T02:26:39+00:00` 之后完成一次统一监控，且生成报告
通过全部五项闸门，才允许：

1. 用真实成对快照补充 `decisionReady: true` 分支。
2. 将候选示例复制到已发布 Skill。
3. 增加防回归测试并升级正式 Skill 版本。
4. 通过发布 workflow 后按 E0–E4 完成一次限定验收。

如果闸门未通过，草案继续保留在 `research/`，不得为了修正文档示例而
制造新的发布或安装流量。

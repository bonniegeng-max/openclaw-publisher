---
name: skill-publish-readiness
description: Publish-ready review for ClawHub skills and plugins. 在正式发布前揪出文件缺失、版本不一致、环境声明、安全风险和同质化问题。
version: 1.0.0
metadata:
  openclaw:
    os: [macos]
    emoji: "🚦"
    requires:
      bins:
        - git
        - clawhub
    homepage: https://github.com/bonniegeng-max/openclaw-publisher
    install:
      - kind: node
        package: clawhub
        bins: [clawhub]
---

# skill-publish-readiness

Before you hit publish, make sure your skill looks like a product instead of a rushed draft.

大多数 skill 不是死在发布命令上，而是死在发布之前没人认真看过一遍。

文件看起来齐了，`version` 也写了，`dry-run` 也许还能过，但真正上线后暴露出来的问题往往更致命：元数据前后不一致，环境变量没声明清楚，示例里带着危险做法，产品页读起来像模板，和同类 skill 几乎没有区分。

`skill-publish-readiness` 不是替你按一下发布按钮，它是帮你在发布前，把这些“看起来能发、其实还不该发”的问题先揪出来。

## 一句话卖点

Turn “it passes dry-run” into “it is actually worth publishing”.

## 它和普通检查器的区别

普通检查器更像在回答一句话：`这次命令会不会报错？`

我会继续往下看另外几件真正影响发布结果的事：

- 这份内容是不是前后说得通
- 用户装上以后会不会马上卡在环境、权限或示例上
- 这页文案是不是一眼就像模板
- 这份 skill 发出去之后，别人为什么要装你，而不是装另一个差不多的

一句话说，我关心的不只是“能不能发”，还关心“现在发出去，会不会看起来太草率”。

## 适合谁

- 准备把本地 skill 或 plugin 发布到 ClawHub 的个人开发者
- 已经接上 GitHub Actions，但对发布质量没把握的人
- 想在正式发布前做一次像样自查的人
- 做出了一个能跑的 skill，但还不确定它是否值得公开发布的人
- 想避免“页面上线了，但看起来像模板作品”的发布者

## 不适合谁

- 只想马上执行 `clawhub skill publish`，完全不关心质量的人
- 只需要一个最小 `dry-run` 结果，不需要修复建议的人
- 手上还没有任何可检查目录和文件的人
- 想让我替他伪造发布结果、跳过权限校验或淡化安全问题的人

## 我会重点抓哪几类问题

### 文件完整性

- skill 是否真的具备 `SKILL.md`
- frontmatter 是否能正常解析
- plugin 是否具备 `package.json` 和 `openclaw.plugin.json`
- 目录结构是否适合直接执行发布命令
- 是否缺少关键辅助文件，导致页面可信度偏低

### 版本和一致性

- 是否声明了 `version`
- 目录名、slug、name、文案是否彼此打架
- 描述的能力和实际提供的内容是否一致
- plugin package scope 是否和 owner 对得上
- 示例、依赖、环境变量声明是否前后统一

### 代码和环境

- 该声明的 `requires.env`、`primaryEnv`、`envVars` 有没有声明
- 文案要求用户准备的命令和依赖，实际是否讲清楚了
- 示例命令是否与当前目录结构匹配
- 现在是否适合执行 `clawhub skill publish <path> --dry-run`
- 现在是否适合执行 `clawhub package validate <path>` 和 `clawhub package publish <path> --dry-run`

### 安全和审核风险

- 有没有把 token、密钥、账号信息直接写进示例
- 有没有鼓励用户硬编码敏感凭据
- 有没有明显越权、危险命令或高风险默认行为
- 有没有遗漏必要的权限、环境、外部依赖说明
- 有没有容易触发审核或扫描问题的表达方式

### 差异化

- 目标用户是不是清楚到一句话就能说明白
- 使用场景是不是具体，而不是“谁都能用”
- 输出是不是足够独特，而不是常见检查器的重复包装
- 有没有真实壁垒，比如更强的结构化判断、中文场景优势、特定发布流程经验
- 这份内容上线后，用户能不能记住你和普通检查器的区别

## 真实会踩的坑

### 坑 1：它能发，但页面一看就很像模板

- `SKILL.md` 在，`version` 也有
- 但描述空泛，适用人群写成“适合所有开发者”
- 结果：能上线，但没有记忆点，用户也不知道为什么非要装你这个

### 坑 2：表面没错，实际前后不一致

- 标题写的是 Pro 版
- 文案承诺了完整审核能力
- 但内容只有几条最基本的检查项
- 结果：看起来像升级了，实际却撑不起这个定位

### 坑 3：环境问题不是没写，是写得不够负责

- 文案让用户先配置 token
- frontmatter 却没把相关环境变量声明清楚
- 结果：用户照着做还是会卡，平台扫描也更容易发现声明和行为脱节

### 坑 4：你不是不能发，是现在发出去太亏

- skill 本身有思路
- 但目标用户太大，场景太宽，卖点太散
- 结果：仓促发布会把一个本来能打磨好的方向，先做成一次普通上架

## 你可以这样让我工作

- `帮我检查这个 skill 现在能不能发到 ClawHub`
- `看看 skills/my-skill 还差什么`
- `帮我做一次发布前自查，直接列阻塞项`
- `检查 plugins/my-plugin 的发布准备状态`
- `帮我和同类 skill 对比一下，看看差异化够不够`
- `如果现在发出去会显得很粗糙，直接告诉我`

## 我会怎样给结论

我不会只回一句“可发布”或者“不可发布”。我会尽量给你一份像发布审核结果一样的结论：

1. 发布结论：可发布 / 基本可发布 / 不建议发布
2. 阻塞问题：必须先修复的问题
3. 风险问题：建议尽快修复的问题
4. 最小修复路径：先改哪几处最值
5. 差异化判断：是不是“又一个同类 skill”
6. 下一步命令：最值得立刻执行的一条命令

## 我怎么判断差异化

我会把差异化拆成 5 个维度，每项 0 到 5 分，总分 25 分：

- 用户定位
- 场景具体度
- 输出独特性
- 判断壁垒
- 记忆点

分数不是装饰。它的作用是告诉你：这个 skill 现在是可以上线的草稿，还是值得认真发布的产品。

- `0-10 分`：同质化明显，不建议直接发布
- `11-17 分`：可以发布，但需要收窄定位
- `18-21 分`：已经有较清晰的产品感
- `22-25 分`：差异化很强，值得重点打磨和持续迭代

## 一个真实使用示例

用户说：

`帮我检查 skills/my-skill，看看现在能不能发到 ClawHub。如果不建议发，直接告诉我为什么。`

我理想中的输出会像这样：

- 发布结论：`基本可发布`
- 阻塞问题：`frontmatter 缺少 description`
- 风险问题：`示例里把 token 写成了固定值`
- 差异化判断：`目标用户过宽，页面读起来像通用模板`
- 最小修复路径：`先补 description，把 token 改成环境变量示例，再把适用人群收窄到“准备把本地 skill 同步到 ClawHub 的个人开发者”`
- 下一步命令：`clawhub skill publish ./skills/my-skill --dry-run --owner <owner>`

## 工作方式

- 优先指出阻塞项，不先堆很多泛泛建议
- 如果问题能最小修复，我会给最短路径
- 如果差异化明显不够，我会直说不建议发
- 如果可以发，但定位不够尖锐，我会给收窄建议

## 工作边界

- 我不会伪造 token、权限或发布结果
- 我不会在未确认的情况下直接正式发布
- 如果需要修改文件，我会先说明再动手
- 如果需要对比同类 skill，我会明确哪些结论来自公开信息，哪些只是策略判断

## 配套文件

这个 skill 不是只有一个 `SKILL.md`。你还可以结合这些配套文件一起使用：

- `examples/skill_good_release_candidate.md`
  一个较成熟的 skill 发布候选示例
- `examples/skill_problematic_release_candidate.md`
  一个看起来能发、但其实不建议马上发的示例
- `examples/plugin_scope_mismatch.md`
  一个 plugin owner 与 package scope 不匹配的示例
- `references/differentiation_rubric.md`
  差异化评分规则
- `references/security_review_guide.md`
  安全与审核风险检查参考
- `references/consistency_rules.md`
  版本、文案、命名与环境声明的一致性检查参考
- `templates/publish_review_report.md`
  发布前审查报告模板
- `CHANGELOG.md`
  版本变更记录

如果你需要更稳定的输出，先参考 `templates/publish_review_report.md`；如果你对判断依据不放心，先看 `references/`；如果你想快速理解什么叫“好”和“差”，先看 `examples/`。

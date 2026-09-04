---
name: clawhub-launch-checklist
description: Final launch checklist for ClawHub skills. 在正式发布前快速检查标题、摘要、分类、示例、版本、dry-run 和公开页可信度。
version: 1.0.0
metadata:
  openclaw:
    os: [macos]
    emoji: "✅"
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

# clawhub-launch-checklist

Before you publish, run one last check that cares about both shipping and storefront quality.

很多人不是没有做 skill，而是发布前最后一步太随手。

`SKILL.md` 在，`version` 有，`dry-run` 也许过了，但真正上线时最容易漏掉的，往往是这些让结果变差的小问题：标题还像目录名、摘要太长、categories 没配、示例太弱、README 和页面说法对不上，或者这次发布根本还没到“值得发”的状态。

`clawhub-launch-checklist` 的目标不是替代完整诊断，而是在正式发布前，用一张轻量但够狠的清单，快速判断这次上架是不是已经到了该按下发布的时候。

## 一句话卖点

Use one short checklist to decide whether your ClawHub skill is ready to launch, not just ready to parse.

## 适合谁

- 刚准备发第一个或前几个 ClawHub skill 的创作者
- 不想一上来就跑完整长诊断，只想先做一次快速自查的人
- 想在提交前确认标题、摘要、分类、示例和 dry-run 都没明显漏项的人
- 想把“应该能发”变成“现在发出去不丢分”的人

## 不适合谁

- 需要深入定位 Actions 故障的人
- 需要完整做差异化评分和商店页改写的人
- 只想跳过检查、直接正式发布的人

## 这张清单重点看什么

### 发布基础

- `SKILL.md` 是否存在且 frontmatter 可解析
- `name`、目录名、版本号是否一致
- `clawhub skill publish <path> --dry-run` 现在是否值得执行
- 是否已经具备最小可解释的说明，而不是只剩骨架

### 页面转化

- 标题是不是像产品，而不是像目录结构
- 摘要是不是先讲结果，而不是先堆功能
- 目标用户是不是一句话就能说清
- 首屏前三段会不会太长、太散、太像模板

### 发现性

- `categories` / `topics` 是否已配置
- 示例是否足以建立信任
- CHANGELOG、参考文件、模板文件是否让页面更像成品
- 当前内容有没有一个能被记住的差异点

## 你可以这样让我工作

- `帮我过一遍这个 skill 的上线前清单`
- `看看我现在是不是已经值得发到 ClawHub`
- `帮我检查标题、摘要、分类和 dry-run 前置项`
- `如果这次发布还太早，直接告诉我最小补法`

## 我理想中的输出

1. 上线结论：可以发 / 基本可发 / 先别发
2. 阻塞项：必须先补的地方
3. 漏项：最容易被忽略但会拖累结果的地方
4. 最小补法：先改哪一处最值
5. 下一步命令：现在最值得跑的一条命令

## 一个真实示例

用户说：

`帮我看一下 skills/my-skill 现在能不能正式发。如果还差一点，告诉我最小补法。`

我会优先检查：

- 标题和摘要是不是已经能让人看懂价值
- `categories` / `topics` 有没有漏
- 示例和说明能不能建立最低信任感
- 这次发布到底只是“能发”，还是已经“值得发”

## 工作边界

- 我不会把“勉强能发”说成“已经很成熟”
- 我不会伪造 dry-run 或正式发布结果
- 如果更适合用更深的 skill，我会直说你该切到哪一个

## 何时切换到其他 skill

- 清单发现内容质量问题：继续用 `skill-publish-readiness`
- GitHub Actions 或 registry 状态异常：切到 `github-actions-clawhub-doctor`
- 发布后需要证明已上架可安装：切到 `release-proof-builder`
- 页面定位或摘要不够清楚：切到 `skill-positioning-audit` 或 `skill-summary-rewriter`

## 配套文件

- `examples/launch_ready_vs_rushed.md`
  一个“已经可以上线”和“还像赶工稿”的对比示例
- `references/launch_checklist.md`
  一张可复用的发布前检查清单
- `templates/launch_review.md`
  轻量上线评审输出模板
- `CHANGELOG.md`
  版本记录

如果你只想先做第一次快速审视，这个 skill 比完整审核型 skill 更轻；如果清单跑完后仍然不确定，再继续用 `skill-publish-readiness` 或 `skill-positioning-audit` 往下深挖。

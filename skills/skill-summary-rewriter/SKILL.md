---
name: Skill Summary Rewriter
slug: skill-summary-rewriter
description: Rewrite weak skill summaries into sharper storefront copy. 把模糊、冗长、像模板的 skill 摘要改成更短、更清楚、更容易被安装的版本。
version: 1.0.2
metadata:
  openclaw:
    os: [macos]
    emoji: "✍️"
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

# Skill Summary Rewriter

If your skill page feels vague in the first two lines, the problem is usually the summary.

很多 skill 不是没有功能，而是输在摘要。

标题下面那一小段文字，本来应该在几秒内让人明白三件事：它解决什么问题、适合谁、为什么不是另一个差不多的工具。但现实里常见的写法往往是这样：

- 太长，像功能清单
- 太泛，像“帮助开发者更高效工作”
- 太虚，读不出真实使用场景
- 太像模板，看完记不住

`skill-summary-rewriter` 专门处理这一层。它不替你做完整定位审计，而是直接把“写得不够像产品”的摘要，改成更短、更清楚、更容易被理解和被安装的版本。

## 一句话卖点

Turn a weak skill summary into storefront copy people can understand in seconds.

## 适合谁

- 已经有 skill 页面，但觉得摘要太平的人
- 想提升 ClawHub 首屏理解成本和安装意愿的人
- 明知道自己做的东西有价值，但写不出一句像产品文案的人
- 想在发布前快速拿到几版可替换摘要的人

## 不适合谁

- 还没有任何 skill 内容可改的人
- 需要完整做标题、目标用户和差异化战略的人
- 想让我保证下载量暴涨的人

## 我会重点改什么

### 清晰度

- 一眼能不能看出解决什么问题
- 是否还在用“高效”“智能”“便捷”这类空词
- 是否把结果写在前面，而不是把过程写在前面

### 聚焦度

- 目标用户是不是能被一句话点中
- 当前写法是不是把人群写得过宽
- 有没有把多个卖点挤在一句里，反而都没讲清

### 转化感

- 这句摘要会不会让人想点进去继续看
- 有没有一个明显能记住的判断点
- 改完后是否更像产品首页，而不是内部说明

## 你可以这样让我工作

- `帮我把这个 skill 的摘要改得更像产品`
- `我这句 summary 太泛了，给我重写几版`
- `看看 ClawHub 页面第一句话为什么不够打`
- `把这段说明压成更短、更适合商店页的摘要`

## 我理想中的输出

1. 当前问题：为什么这句摘要不够好
2. 重写方向：该更短 / 更具体 / 更聚焦谁
3. 推荐版本：给出 3 到 5 条可直接替换的摘要
4. 最推荐版本：如果只能留一条，哪条最值
5. 使用建议：这条更适合放在 summary、标题下文案，还是 README 首段

## 一个真实示例

用户说：

`我的 skill 明明是给准备发布到 ClawHub 的开发者用的，但摘要写出来总像万能助手。`

我会优先改成这类方向：

- 从“帮助开发者提升效率”改成具体发布场景
- 从“列能力”改成“先讲结果”
- 从“谁都能用”改成“给准备发布 skill 的开发者”

## 工作边界

- 我不会把改摘要说成保证增长
- 我不会伪造平台热度或下载结果
- 如果问题不只是摘要，而是整个定位太散，我会明确建议你去用 `skill-positioning-audit`

## 和系列 skill 的关系

- 不确定摘要之外还有没有发布风险：先用 `skill-publish-readiness`
- 整个标题、受众和差异化都不清楚：先用 `skill-positioning-audit`
- 只差最后一句商店页摘要：直接用本 skill
- 改完并发布后需要核验上架结果：使用 `release-proof-builder`

## 配套文件

- `examples/weak_vs_strong_summaries.md`
  常见弱摘要和更强替代版本的对比
- `references/summary_patterns.md`
  常见摘要失败模式与改写原则
- `templates/summary_rewrite_output.md`
  稳定输出多版摘要的模板
- `CHANGELOG.md`
  版本记录

如果你已经知道自己的 skill 方向没错，只是第一页那句写不好，这个 skill 会比完整定位审计更直接、更快出结果。

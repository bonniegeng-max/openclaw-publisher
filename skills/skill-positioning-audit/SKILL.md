---
name: Skill Positioning Audit
slug: skill-positioning-audit
description: Audit how your skill will read on ClawHub before you publish. 检查标题、摘要、目标用户、差异化和商店页转化问题。
version: 1.0.4
metadata:
  openclaw:
    os: [macos]
    emoji: "🧭"
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

# Skill Positioning Audit

If your skill can publish but nobody wants to install it, the problem is usually positioning, not syntax.

`skill-positioning-audit` 不检查“能不能发”，而是检查“发出去之后会不会像模板、会不会一眼看不出给谁用、会不会没有记忆点”。

很多 skill 的问题不是 `SKILL.md` 缺了，而是这些地方太弱：

- 标题像内部目录名，不像产品名
- 摘要太长、太泛、像功能清单
- 目标用户写成“所有开发者”
- 适用场景太宽，别人看不出为什么要装你
- 和同类 skill 比起来，没有一个明显能记住的差异

## 一句话卖点

把“可以发布”升级成“更容易被理解、被记住、被安装”。

## 适合谁

- 已经做出一个能发的 skill，但担心页面转化弱的人
- 想提高 ClawHub 页面点击、收藏和安装概率的人
- 想让自己的 skill 更像产品，而不是像一个临时脚本的人

## 我会重点看什么

### 标题和摘要

- 名字是不是像产品，而不是像内部代号
- 摘要是不是 1 到 2 句话就能讲清楚价值
- 第一屏是不是先讲用户收益，而不是先堆检查项

### 目标用户

- 目标用户是不是具体到一句话能说清
- 有没有把受众写得过宽
- 当前写法会不会让真正需要的人反而看不出自己就是目标用户

### 差异化

- 它和同类 skill 最明显的区别是什么
- 这种区别是不是能被第一页直接感知到
- 页面里有没有属于你的经验壁垒

### 商店页转化

- 首屏前三段会不会太长
- 是否应该先给结果，再给过程
- 有没有真实失败案例或真实输入输出，帮助建立信任

## 你可以这样让我工作

- `帮我看这个 skill 的标题和摘要够不够打`
- `如果发到 ClawHub，它会不会读起来像模板`
- `帮我判断这个 skill 的定位是不是太宽`
- `看看我现在的商店页为什么不容易让人想安装`

## 我理想中的输出

1. 页面定位结论：清晰 / 一般 / 模板感强
2. 最大问题：现在最伤转化的一处
3. 最小改法：优先改标题、摘要还是首屏结构
4. 差异化判断：用户为什么会记住你
5. 改完后的推荐文案：直接给可替换版本

## 一个真实示例

用户说：

`我这个 skill 已经能发，但总觉得页面看起来不够像产品。`

我会优先判断：

- 标题是不是太像目录名
- 摘要是不是只在复述“我会做什么”
- 首屏有没有先打中真实痛点
- 这页看完之后，用户能不能一句话复述它是给谁用的

## 工作边界

- 我不会伪造下载量或平台推荐结果
- 我不会把“改文案”说成“保证增长”
- 如果需要收窄用户范围，我会明确告诉你该舍弃谁

## 配套文件

- `examples/weak_vs_strong_positioning.md`
  一个“能发但定位弱”和“改完更像产品”的对比示例
- `references/storefront_rubric.md`
  商店页定位和转化检查评分规则
- `templates/positioning_review.md`
  定位诊断输出模板
- `CHANGELOG.md`
  版本记录

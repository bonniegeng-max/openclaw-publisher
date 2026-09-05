# 完整定位诊断：展示名不是 slug

本示例诊断仓库中真实存在的 Positioning Audit 示例，不使用虚构的下载、
安装或排名数据。机器可验输入见 `positioning-evidence.json`。

## 输入

当前“更强定位版本”：

- 标题：`skill-positioning-audit`
- 摘要：在发布到 ClawHub 前，检查标题、摘要、目标用户和差异化是否足够
  清晰，避免商店页看起来像模板
- 适合谁：已经做出能发的 skill，但担心页面转化弱的开发者

Catalog 权威身份：

- displayName：`Skill Positioning Audit`
- stable slug：`skill-positioning-audit`
- version：`1.0.4`

## 页面定位结论

`一般`

目标用户、任务和摘要已经清楚，但示例把内部路由 slug 当成可见标题，直接
违反本 Skill 自己的“标题应像产品，而不是目录名”规则。

## 最大问题

最大问题不是摘要，而是 displayName 与 slug 没有分层：

- `Skill Positioning Audit` 是用户应看到和记住的产品名。
- `skill-positioning-audit` 是发布、安装与路由使用的稳定标识。

把 slug 放在标题位置，会让“更强版本”仍像内部目录，并削弱示例作为标准
答案的可信度。

## 最小改法

只先修标题呈现，不修改稳定 slug：

```text
展示标题：Skill Positioning Audit
稳定 slug：skill-positioning-audit
```

这能消除合同冲突，又不会创建新的 registry ID 或破坏已有安装路径。

## 五维评估

这是依据仓库 rubric 的编辑评估，不是平台表现数据。

| 维度 | 当前示例 | 候选版本 | 变化依据 |
|---|---:|---:|---|
| 标题清晰度 | 2/5 | 5/5 | 从目录式 slug 改为人类可读 displayName |
| 摘要转化力 | 4/5 | 4/5 | 原摘要已具体，仅压缩表达 |
| 目标用户聚焦度 | 4/5 | 5/5 | 明确限定为已有可发布 Skill 的作者 |
| 差异化记忆点 | 3/5 | 4/5 | 强化“定位问题，不是语法问题” |
| 信任感 | 2/5 | 3/5 | 明确 rubric、示例和替换文案，但没有平台 A/B |
| 总分 | 15/25 | 21/25 | 从“能发但转化弱”提升到“已有明显产品感” |

## 差异化判断

用户应这样记住它：

> 它不检查发布语法，而是找出商店页为什么像模板，以及最该先改哪一处。

与相邻 Skill 的边界：

- `Skill Publish Readiness`：完整发布前审查。
- `Skill Summary Rewriter`：直接交付多版摘要。
- `Skill Positioning Audit`：诊断标题、受众、场景和差异化结构。

## 推荐替换文案

标题：

> Skill Positioning Audit

稳定 slug：

> `skill-positioning-audit`

摘要：

> Audit how your ClawHub skill reads before publishing. 找出标题、摘要、目标
> 用户和差异化中最伤转化的一处。

首屏第一段：

> 能发布不等于有人想安装。Skill Positioning Audit 会在上架前检查标题、
> 摘要、目标用户和差异化，指出当前最像模板、最该先改的一处。

## 使用边界

- 继续使用现有 slug，不因展示名修复创建新产品。
- rubric 分数只反映文档是否满足定义，不代表下载或安装提升。
- 候选文案尚未做平台 A/B 测试。
- 是否进入正式版本，等待自然观察窗口后的真实采用与搜索证据。

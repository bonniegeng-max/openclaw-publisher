# skills 目录说明

这里放所有准备发布到 ClawHub 的 skill。

## 规则

- 一个 skill 对应一个子目录
- 每个 skill 目录至少要有 `SKILL.md`
- 推荐目录名直接作为 skill slug 使用
- 目录名尽量使用小写字母、数字和连字符

## 示例

```text
skills/
└── my-skill/
    ├── SKILL.md
    ├── examples.md
    └── templates/
```

## 最小示例

```md
---
name: my-skill
description: 一个最小可发布 skill。
version: 1.0.0
metadata:
  openclaw:
    os: [macos]
---

# My Skill

这里写你的 skill 说明。
```

提交到 GitHub 后：

- PR 阶段会做 dry-run
- 合并到 `main` 后会自动发布到 ClawHub

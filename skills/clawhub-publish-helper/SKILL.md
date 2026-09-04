---
name: clawhub-publish-helper
description: 帮你检查本地 skill 或 plugin 是否适合发布到 GitHub 和 ClawHub，并给出最小修改建议。
version: 1.0.0
metadata:
  openclaw:
    os: [macos]
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

# clawhub-publish-helper

这个 skill 用来帮助你在发布前快速检查一个本地 skill 或 plugin 是否已经满足最基本的 GitHub 与 ClawHub 发布条件。

## 适用场景

- 你刚写完一个新的 `SKILL.md`
- 你刚做完一个新的 plugin
- 你准备把内容推到 GitHub，并由 Actions 自动发布到 ClawHub
- 你不确定目录结构、元数据、命名或发布命令是否正确

## 你可以这样让我工作

- 检查这个 skill 能不能发布到 ClawHub
- 看一下 `skills/my-skill` 还缺什么
- 帮我验证 `plugins/my-plugin` 的发布准备状态
- 如果不满足发布条件，直接告诉我最小改动

## 我会重点检查

### Skill

- 是否存在 `SKILL.md`
- frontmatter 是否包含 `name` 和 `description`
- 目录名、slug、命名是否适合发布
- 是否存在明显缺失的运行依赖声明
- 是否适合执行 `clawhub skill publish <path> --dry-run`

### Plugin

- 是否存在 `package.json`
- 是否存在 `openclaw.plugin.json`
- package scope 是否与发布 owner 一致
- 是否声明 `openclaw.compat.pluginApi`
- 是否声明 `openclaw.build.openclawVersion`
- 是否适合执行 `clawhub package validate <path>`
- 是否适合执行 `clawhub package publish <path> --dry-run`

## 输出方式

我会优先给出：

1. 当前是否可发布
2. 阻塞发布的最小问题
3. 最小修改建议
4. 下一条建议执行的命令

## 工作边界

- 我不会替你伪造凭据或 token
- 我不会在未确认的情况下直接发布
- 如果需要修改文件，我会先说明再动手

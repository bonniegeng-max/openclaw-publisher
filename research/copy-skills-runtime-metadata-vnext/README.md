# 纯文案 Skill 运行依赖修复草案

状态：`observation-window-hold`

目标：

- `skills/skill-summary-rewriter`
- `skills/skill-positioning-audit`

本目录只保存下一版候选修改，不修改已发布 Skill，不进入 catalog，也不触发
ClawHub 发布。

## 已确认事实

OpenClaw 官方 Skill format 说明：

- 基础 frontmatter 只需 `name`、`description`，`version` 可正常保留。
- `metadata.openclaw.requires.bins` 用于声明 Skill 运行时必须存在的二进制。
- `metadata.openclaw.os` 用于声明操作系统限制。
- `metadata.openclaw.install` 只应在 Skill 确实需要安装依赖时声明。

官方 Skills 文档同时说明，OpenClaw 会根据环境、配置和二进制是否存在，
在加载时过滤 Skill。因此不真实的 `os` 或 `requires.bins` 不是无害文案，
而是可能改变可用性的运行契约。

来源：

- https://docs.openclaw.ai/clawhub/skill-format
- https://docs.openclaw.ai/tools/skills

本地文件审计确认，两个目标目录只有 Markdown 与 `.clawhubignore`，没有
脚本、二进制、package manifest 或需要 Git/ClawHub CLI 才能执行的资源。
正文描述的任务也是对用户提供文本进行定位审查或摘要改写。

## 候选改动

两个 Skill 均删除：

```yaml
os: [macos]
requires:
  bins:
    - git
    - clawhub
install:
  - kind: node
    package: clawhub
    bins: [clawhub]
```

保留：

```yaml
emoji: "..."
homepage: https://github.com/bonniegeng-max/openclaw-publisher
```

不改变 Skill 名称、slug、能力边界、catalog 分类或 topics。

## 证据边界

已确认：

- 这些字段会参与运行资格过滤。
- 两个 Skill 的仓库内容不包含需要上述运行环境的可执行资源。
- 当前正文没有定义必须调用 Git 或 ClawHub CLI 的步骤。

尚未确认：

- 当前 ClawHub 搜索是否因这些字段降低曝光。
- 下载或安装是否已经受到影响。
- 删除依赖后会产生多少自然采用变化。

因此只能将其定义为兼容性合同修复，不能称为增长优化已经生效。

## 发布边界

1. 等待当前观察窗口结束。
2. 运行一次统一增长监控并保存原基线。
3. 对两个 Skill 做最终命令需求复核。
4. 在一次实质版本中更新 frontmatter、版本和 changelog。
5. 本地回归与 ClawHub dry-run 通过后再发布。
6. 每个变化版本只做一次 E4 验收，并重建自然观察起点。

机器可验计划见 `change-plan.json`。

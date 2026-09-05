# GitHub 同类产品预筛

检查日期：`2026-09-05`

## 查询

本轮只使用 GitHub 代码搜索，不访问 ClawHub registry：

- `"ClawHub Package Publish Doctor"`
- `"package-publish-doctor"`
- `"clawhub package publish" "SKILL.md"`
- `"npm pack did not return a tarball filename" "SKILL.md"`
- `"openclaw.plugin.json required" "SKILL.md"`

## 结果

- 精确展示名与精确 slug 均为 `0` 个结果。
- 宽泛查询主要命中 ClawHub 官方文档、CLI 源码、普通发布说明和零散插件作者指南。
- 最接近的可复用 Skill 是 [`tanaab-openclaw-plugin-author`](https://github.com/tanaabased/canon/blob/main/skills/openclaw-plugin-author/SKILL.md)，它覆盖插件创建、校验、打包和发布的完整生命周期。

## 差异判断

`package-publish-doctor` 不承担插件开发或架构设计，而是处理已经进入 Package 发布链路后的失败诊断：

| 维度 | Plugin Author | Package Publish Doctor |
|---|---|---|
| 触发时机 | 创建、修改或发布插件 | `validate / pack / publish / wait / verify` 失败 |
| 主要输入 | 源码、manifest、SDK 使用 | 日志、版本、artifact、family、权限和 registry 状态 |
| 主要输出 | 可构建、可发布的插件实现 | 失败层、证据、版本适用性和最小修复 |
| 安全边界 | 正确实现插件 | 不绕过 Inspector、不伪造 manifest、不依赖未发布 main |

两者存在“发布”关键词交集，但用户任务、输入和结果不同，暂不视为直接竞品。

## 证据限制

- GitHub 代码搜索不是 ClawHub catalog 搜索。
- `0` 个精确结果只表示公开 GitHub 代码中未发现同名产品，不能证明市场空白。
- 宽泛搜索是 lexical matching，结果数不能作为需求规模。
- 正式发布前仍需执行一次同口径 ClawHub 搜索，并记录 query、limit 和结果集合。

结论：GitHub 预筛通过；ClawHub 竞品门槛仍未完成。

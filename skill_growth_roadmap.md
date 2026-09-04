# Skill 增长路线图

## 当前状态

- 已完成并纳入仓库的 skill：
  - `skill-publish-readiness`
  - `github-actions-clawhub-doctor`
  - `skill-positioning-audit`
  - `clawhub-launch-checklist`
  - `skill-summary-rewriter`
- 已完成：GitHub 自动发布到 ClawHub、分类和 topics 自动同步、商店页摘要与首屏优化
- 当前定位：围绕 ClawHub 发布质量、发布前自查、GitHub Actions 同步链路和商店页转化

## 为什么这条线值得继续做

- 你已经有真实踩坑经历，能讲出别人发 skill 时最容易遇到的坑
- 已有第一个公开 skill，可以作为后续系列技能的入口页
- 当前账号最适合建立的 IP，不是“通用 AI 工具作者”，而是“ClawHub 发布与增长工具作者”

## 当前 skill 还可以继续优化的点

### 下载转化

- 增加更短的一句话英文副标题
- 在首屏更早放出 `适合谁`
- 用更具体的结果词替代泛化词，比如 `publish review`、`release audit`、`launch blocker`

### 页面信任感

- 增加一段 `Built from real publish failures`
- 增加一个真实的 Actions 报错样例
- 增加一个“发布前检查清单截图式”输出示例

### 系列化

- 当前 skill 更像入口
- 后面应连续发布 2 到 3 个同一主题下的 skill
- 这样下载量不一定立刻暴涨，但会明显提高账号辨识度

## 优先级最高的下一个 skill

### 1. `github-actions-clawhub-doctor`

定位：
专门诊断 GitHub Actions 到 ClawHub 的发布失败，不只告诉你红了，还告诉你到底卡在工作流引用、owner、slug、token、pending-publication 还是目录结构。

为什么优先：

- 直接来自这次真实问题
- 和已发布 skill 的受众高度重合
- 能和 `skill-publish-readiness` 形成上下游关系

适合主打的检查项：

- reusable workflow ref 是否有效
- `CLAWHUB_OWNER` / `CLAWHUB_TOKEN` 是否缺失
- skill 名称是否使用受保护前缀
- `pending-publication` 是否被错误当成失败
- 技能目录是否被正确发现

### 2. `skill-positioning-audit`

定位：
不检查能不能发，而是检查“发出去有没有记忆点”。

为什么值得做：

- 更偏增长，不只偏工程
- 可以直接承接 `skill-publish-readiness` 用户
- 适合中文创作者场景

### 3. `clawhub-launch-checklist`

定位：
在正式发布前，把文案、分类、topics、README、示例、安装路径和 dry-run 前置项做成一张清单。

为什么值得做：

- 使用门槛低
- 更容易被理解
- 适合作为轻量版入口技能

## 更远一点的 plugin 方向

### 1. GitHub / ClawHub 发布状态桥接插件

- 聚合仓库最新发布 run、ClawHub 上架状态、审查状态
- 更像插件，而不是 skill
- 适合后续做成长期工具

### 2. ClawHub catalog optimizer

- 专门改 categories、topics、summary、changelog
- 偏元数据管理
- 适合在你有 3 到 5 个 skill 后再做

## 当前组合建议

1. `clawhub-launch-checklist`
2. `skill-publish-readiness`
3. `github-actions-clawhub-doctor`
4. `skill-positioning-audit`

这套顺序更像一个用户真正会走的路径：

- 先用轻量清单判断值不值得发
- 再做更完整的发布前审查
- 如果链路出错，再看 Actions 排障
- 真要提升页面转化，再做定位与文案优化

## 下一个最值得做的题

### 1. `release-proof-builder`

- 价值：把发布完成后的公开页、workflow 状态和安装命令整理成证据包
- 理由：能承接“发完之后怎么确认结果”的高频问题

### 2. `topic-fit-audit`

- 价值：检查 `categories` / `topics` 是否真和内容匹配
- 理由：直接影响在 ClawHub 里的发现性

### 3. `skill-page-benchmark`

- 价值：把你的 skill 页面和同类项做结构化对比
- 理由：当你已有 5 个左右 skill 时，更适合开始做横向 benchmark

## 每个 skill 上线前都统一执行

1. `clawhub skill publish <path> --dry-run --owner <owner>`
2. 检查是否已设置 categories / topics
3. 检查首屏前三段是否够短、够具体
4. 检查是否能一句话说清楚目标用户
5. 检查是否有真实失败样例或真实输入输出

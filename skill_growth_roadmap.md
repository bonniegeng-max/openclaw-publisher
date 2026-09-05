# Skill 增长路线图

## 当前状态

- 已完成并纳入仓库的 skill：
  - `skill-publish-readiness`
  - `github-actions-clawhub-doctor`
  - `skill-positioning-audit`
  - `skill-launch-checklist`
  - `skill-summary-rewriter`
  - `release-proof-builder`
  - `skill-portfolio-growth-audit`
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

### 3. `skill-launch-checklist`

定位：
在正式发布前，把文案、分类、topics、README、示例、安装路径和 dry-run 前置项做成一张清单。

为什么值得做：

- 使用门槛低
- 更容易被理解
- 适合作为轻量版入口技能

## Plugin 候选

### `skill-catalog-governor`

- 集中检查稳定 slug、展示名、categories、topics、版本与 changelog
- 识别 `SKILL.md` 和 catalog metadata 的漂移
- 输出可审阅 diff，不默认自动发布
- 吸收原 `topic-fit-audit`，不再拆成多个薄 Skill

当前不进入开发。`clawhub package explore` 暂未返回公开 package 样本，既缺市场参照，也缺稳定消费路径。只有 package 生态可验证且出现至少 3 个独立维护案例后才启动。

## 下一 Skill 候选

### `package-publish-doctor`

GitHub issue 证据已经显示，ClawHub Package 发布不是 Skill 发布链路的简单变体：

- npm 12 会让旧版 CLI 误判 `npm pack` 没有生成 tarball
- `bundle-plugin` family 与 native manifest 要求可能出现合约冲突
- 中等体积 ClawPack 可能因 CLI/workflow 版本差异走错上传路径并返回 413
- reusable workflow 还需要 `actions: read`、`contents: read` 和 `id-token: write`

它应独立诊断 `validate / pack / publish / wait / verify`，并输出失败层、版本适用性、最小修复和 artifact hash 验证路径。它不吸收 catalog metadata 治理，也不重复现有 Skill 发布 Doctor。

当前状态：`research-ready`，暂不发布。先完成当前 7 天自然观察窗口，再复核最新 ClawHub release、直接竞品和离线 fixture；通过后可作为第 8 个 Skill 开发。

## 当前组合建议

1. `skill-launch-checklist`
2. `skill-publish-readiness`
3. `github-actions-clawhub-doctor`
4. `skill-positioning-audit`

这套顺序更像一个用户真正会走的路径：

- 先用轻量清单判断值不值得发
- 再做更完整的发布前审查
- 如果链路出错，再看 Actions 排障
- 真要提升页面转化，再做定位与文案优化

## 下一阶段

1. 观察 `Skill Publish Readiness 1.0.7` 至少 7 天，不再用主动安装制造增长信号。
2. 用验收前基线和新的自然观察起点判断主入口是否继续领先。
3. topic fit 与单页 benchmark 作为现有 Positioning / Portfolio Skill 的能力，不创建新 slug。
4. 为 `package-publish-doctor` 建立版本化失败映射和 3 个离线 fixture，但观察窗口结束前不发布。
5. 继续收集 catalog 漂移案例，为 `skill-catalog-governor` 判断真实需求。
6. package registry 出现可验证消费路径前，不发布第一个 Plugin。

## 当前增长判断

- `skill-publish-readiness` 已经形成最早的下载信号，仍是主力入口
- `skill-summary-rewriter` 已在搜索侧出现首次安装信号，值得继续观察
- 新发布 skill 尚未经过完整观察窗口，不应过早判定失败
- 通用更新安全和安装前审查已有成熟强者，不建议正面复制
- 下一阶段重点从“继续堆发布工具”转向“作品集证据、主题治理和搜索转化”

## 每个 skill 上线前都统一执行

1. `clawhub skill publish <path> --dry-run --owner <owner>`
2. 检查是否已设置 categories / topics
3. 检查首屏前三段是否够短、够具体
4. 检查是否能一句话说清楚目标用户
5. 检查是否有真实失败样例或真实输入输出

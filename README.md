# openclaw-publisher

围绕 ClawHub 发布、排障和增长的一组 skill，以及一条能自动同步到 GitHub 和 ClawHub 的发布链路。

这个仓库不只是“自动同步模板”，而是一个正在成型的系列产品：先帮创作者把 skill 发出去，再帮他们把发布质量、页面转化和后续增长一起做起来。

## 当前定位

这条线现在聚焦 3 件事：

- 发布前自查：避免“能过 dry-run，但不值得发”
- GitHub Actions 排障：定位 GitHub 到 ClawHub 的链路断点
- 商店页转化：减少模板感，增加被理解、被记住、被安装的概率

如果这三件事持续做深，你的账号会更像一个明确的角色，而不是零散地发几个工具。

## 已有 skill

### `skill-publish-readiness`

发布前审查 skill 和 plugin，重点看文件齐不齐、版本和文案是否一致、环境声明是否负责、安全风险是否可控，以及它和同类 skill 有没有真正区别。

适合在你准备正式发布前，做一次“现在发出去会不会太草率”的总检查。

### `github-actions-clawhub-doctor`

专门诊断 GitHub Actions 到 ClawHub 的发布失败，把问题拆到 workflow、owner、token、slug、目录发现或 registry 返回状态那一层。

适合在 Actions 红灯、发布结果真假难辨，或者 `pending-publication` 被误判时使用。

### `skill-positioning-audit`

不看“能不能发”，而看“发出去之后会不会像模板、会不会没有记忆点、会不会让人看不懂给谁用”。

适合在 skill 已经具备基础能力后，继续提升标题、摘要、目标用户和首屏转化。

### `skill-launch-checklist`

把正式发布前最容易漏掉的动作收成一张轻量清单，快速判断这次上架是不是已经到了“值得按下发布”的状态。

适合做轻量入口，也适合给还不想跑完整诊断的人先做第一次自查。

### `skill-summary-rewriter`

专门把模糊、冗长、像模板的 skill 摘要，改成更短、更清楚、更容易被理解和安装的商店页文案。

适合方向已经明确，但首页第一句话还不够有产品感的创作者。

### `release-proof-builder`

把 GitHub 提交、Actions、ClawHub registry 和独立安装结果整理成可核验的发布证据链。

适合解决“已经 push 了，但到底有没有真正上架、能不能下载”的发布后确认问题。

### `skill-portfolio-growth-audit`

读取整个 publisher 的真实下载、安装、版本、搜索竞争和仓库质量，决定哪些 skill 应该加码、修复、合并、观察或停更。

适合已经有多个公开 skill，希望建立系列心智并减少盲目开发的人。

## 为什么这条线有机会

- 题目来自真实踩坑，不是凭空拼出来的功能清单
- 每个 skill 都围绕同一条发布链路展开，天然适合系列化
- 工程问题和增长问题被放在同一个体系里，差异会比纯“工具集合”更明显

这意味着它既能服务当下的发布问题，也能慢慢长成一个更鲜明的个人 IP 方向：`ClawHub 发布与增长工具作者`。

## 仓库结构

```text
.
├── .clawhub/
│   └── skill-catalog.json
├── .github/workflows/
│   ├── clawhub-skill-publish.yml
│   ├── clawhub-skill-publish-local.yml
│   └── clawhub-plugin-publish.yml
├── skills/
│   ├── skill-publish-readiness/
│   ├── github-actions-clawhub-doctor/
│   ├── skill-positioning-audit/
│   ├── skill-launch-checklist/
│   ├── skill-summary-rewriter/
│   ├── release-proof-builder/
│   └── skill-portfolio-growth-audit/
└── plugins/
```

## 自动发布链路

### Skill

- `pull_request`：对 `skills/**` 做 dry-run
- `push` 到 `main`：自动发布 `skills/**`
- `workflow_dispatch`：支持手动重跑
- `.clawhub/skill-catalog.json`：统一管理 `categories` 和 `topics`

### Plugin

- `pull_request`：只 dry-run 改动过的 plugin
- `push` 到 `main`：只发布改动过的 plugin
- `workflow_dispatch`：可指定单个 plugin，也可扫描全部 plugin

## 需要的 GitHub 配置

在仓库的 `Settings -> Secrets and variables -> Actions` 中配置：

- `CLAWHUB_OWNER`
- `CLAWHUB_TOKEN`

其中 `CLAWHUB_OWNER` 用于 skill 与 plugin 的 owner 透传，`CLAWHUB_TOKEN` 用于正式 publish。

## 本地验证

先安装并登录 CLI：

```bash
npm i -g clawhub
clawhub login
clawhub whoami
```

验证某个 skill：

```bash
clawhub skill publish ./skills/<skill-slug> --dry-run --owner <your-owner>
```

验证某个 plugin：

```bash
clawhub package validate ./plugins/<plugin-name>
clawhub package publish ./plugins/<plugin-name> --dry-run --owner <your-owner>
```

## 适合继续做的方向

接下来优先继续沿着这几个方向扩：

- 轻量入口：`skill-launch-checklist`
- 页面转化：`skill-summary-rewriter`
- 元数据治理：`topic-fit-audit`
- 发布后核验：`release-proof-builder`
- 长线工具化：`clawhub-catalog-optimizer` plugin

这些题比“万能 AI 助手”更容易被记住，也更容易形成系列心智。

## 使用建议

如果你刚开始做 ClawHub skill：

1. 先用 `skill-launch-checklist`
2. 再用 `skill-publish-readiness`
3. 如果 Actions 红了，再用 `github-actions-clawhub-doctor`
4. 发布后用 `release-proof-builder` 核验是否真正可安装
5. 真要提高安装转化，再用 `skill-positioning-audit` 和 `skill-summary-rewriter`
6. skill 数量变多后，用 `skill-portfolio-growth-audit` 决定下一步押注

这套顺序覆盖了发布前、发布中、发布后和增长优化，而不是一组彼此孤立的工具。

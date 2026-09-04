# OpenClaw Publisher

![OpenClaw Publisher：从发布准备到增长验证的 ClawHub 产品线](assets/openclaw-publisher-hero.svg)

Ship ClawHub skills with evidence, not guesswork.

这里是一组围绕 ClawHub 发布、排障、验证和增长的 Skill，也是一条可复用的 GitHub → ClawHub 自动发布链路。每个产品都来自真实发布问题，并经过公开 registry 检查与独立安装验证。

[ClawHub Publisher](https://clawhub.ai/user/bonniegeng-max) · [Growth Monitor](skill_growth_monitor.md) · [Idea Backlog](skill_idea_backlog.md) · [Contributing](CONTRIBUTING.md)

## 当前状态

最后验证：`2026-09-05`

| 信号 | 状态 |
|---|---|
| 已发布 Skill | 7 |
| ClawHub moderation | 全部 `clean` |
| 安装验证 | 7 个 latest 版本均达到 `E4` |
| 自动发布 | GitHub `main` → ClawHub |
| 差分发布 | 只发布发生实质变化的 Skill |
| 主入口 | `Skill Publish Readiness 1.0.7` |

公开数据会变化，当前快照、口径限制和决策记录在 [`skill_growth_monitor.md`](skill_growth_monitor.md)。

## 从这里开始

如果只安装一个，先用主入口：

```bash
clawhub install skill-publish-readiness
```

它会审查文件、版本、slug、环境、安全风险和差异化，并给出阻塞项、证据矩阵与最小修复路径。

| 你正在面对的问题 | 推荐 Skill | 你会得到什么 |
|---|---|---|
| 第一次发布，不确定是否准备好 | [Skill Launch Checklist](https://clawhub.ai/bonniegeng-max/skills/skill-launch-checklist) | 一次轻量发布判断 |
| dry-run 能过，但担心发布质量 | [Skill Publish Readiness](https://clawhub.ai/bonniegeng-max/skills/skill-publish-readiness) | 完整发布前审查 |
| GitHub Actions 红了 | [GitHub Actions ClawHub Doctor](https://clawhub.ai/bonniegeng-max/skills/github-actions-clawhub-doctor) | 链路断点与最小修复 |
| 已经 push，不确定是否真能下载 | [Release Proof Builder](https://clawhub.ai/bonniegeng-max/skills/release-proof-builder) | `E0-E4` 发布证据 |
| 页面看起来像模板 | [Skill Positioning Audit](https://clawhub.ai/bonniegeng-max/skills/skill-positioning-audit) | 定位与商店页诊断 |
| 摘要太泛、太长 | [Skill Summary Rewriter](https://clawhub.ai/bonniegeng-max/skills/skill-summary-rewriter) | 可直接替换的摘要 |
| 已经发布多个 Skill，不知道该押注谁 | [Skill Portfolio Growth Audit](https://clawhub.ai/bonniegeng-max/skills/skill-portfolio-growth-audit) | 作品集决策与证据边界 |

## 产品路径

这 7 个 Skill 覆盖同一条发布旅程：

```text
Launch Checklist
      ↓
Publish Readiness
      ↓
GitHub Actions Doctor
      ↓
Release Proof Builder
      ↓
Positioning Audit / Summary Rewriter
      ↓
Portfolio Growth Audit
```

先判断是否值得发，再解决链路问题；发布完成后验证可安装性，最后才优化页面转化和作品集方向。

## 产品目录

| Skill | 角色 | 安装命令 | 验收前基线 |
|---|---|---|---|
| `skill-publish-readiness` | 主入口，完整发布审查 | `clawhub install skill-publish-readiness` | 43 downloads |
| `github-actions-clawhub-doctor` | CI/CD 发布排障 | `clawhub install github-actions-clawhub-doctor` | 11 downloads |
| `skill-launch-checklist` | 低门槛发布入口 | `clawhub install skill-launch-checklist` | 观察中 |
| `release-proof-builder` | 发布后证据核验 | `clawhub install release-proof-builder` | 观察中 |
| `skill-positioning-audit` | 商店页定位诊断 | `clawhub install skill-positioning-audit` | 观察中 |
| `skill-summary-rewriter` | 摘要改写 | `clawhub install skill-summary-rewriter` | 观察中 |
| `skill-portfolio-growth-audit` | 作品集增长决策 | `clawhub install skill-portfolio-growth-audit` | 观察中 |

下载数字是 `2026-09-05` 全量 E4 验收前的 ClawHub 基线，不等同于安装用户数。后续主动安装污染了平台计数，当前原始值和口径说明见增长报告。

## 真实失败来源

这套产品线源于实际发生过的发布事故：

- reusable workflow 引用不存在，Actions 无法启动真实发布
- slug 使用 ClawHub 受保护命名空间，首次上架失败
- `pending-publication` 被错误映射为失败
- 上传票据瞬时过期，需要有限退避重试
- 每次发布全部 Skill，制造无意义版本
- 展示名回退成 slug，降低搜索结果可读性
- GitHub 已推送，但 registry 或独立安装仍未证明成功

主入口中的 [`real_publish_failure_review.md`](skills/skill-publish-readiness/examples/real_publish_failure_review.md) 展示了证据、根因、修复和最终 E4 验收。

## 发布证据

仓库用 `E0-E4` 区分“做过动作”和“结果已成立”：

| 等级 | 含义 |
|---|---|
| `E0` | 只有本地文件 |
| `E1` | GitHub 远端包含目标提交 |
| `E2` | 发布 workflow 已执行 |
| `E3` | ClawHub registry 可读取正确版本与元数据 |
| `E4` | 指定版本可独立安装，核心文件与源码一致 |

只有达到 `E4`，才在这里标记为“已上线、可下载使用”。

## 自动发布

### Skill

- pull request：对改动过的 `skills/**` 执行 dry-run
- push 到 `main`：只发布改动过的 Skill
- workflow dispatch：支持手动重跑
- `.clawhub/skill-catalog.json`：统一管理展示名、categories 和 topics
- 发布命令显式传递稳定 slug，避免展示名变化创建错误 ID
- 瞬时上传错误最多退避重试 3 次，确定性错误直接失败

### Plugin

- pull request：只验证改动过的 plugin
- push 到 `main`：只发布改动过的 plugin
- workflow dispatch：可指定单个 plugin，也可扫描全部 plugin

## 复用这套仓库

先准备 ClawHub CLI：

```bash
npm i -g clawhub
clawhub login
clawhub whoami
```

在 GitHub 仓库的 `Settings → Secrets and variables → Actions` 中配置：

- `CLAWHUB_OWNER`
- `CLAWHUB_TOKEN`

新增 Skill 时至少包含：

```text
skills/<stable-slug>/
├── SKILL.md
├── CHANGELOG.md
├── .clawhubignore
├── examples/
├── references/
└── templates/
```

在 `.clawhub/skill-catalog.json` 中补充展示名、categories 和 topics，然后先执行：

```bash
clawhub skill publish ./skills/<stable-slug> \
  --slug <stable-slug> \
  --name "<Human Readable Name>" \
  --dry-run \
  --owner <owner>
```

push 到 `main` 后，自动发布只处理发生变化的目录。

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
│   └── 7 个已发布 Skill
├── plugins/
├── skill_growth_monitor.md
├── skill_growth_roadmap.md
└── skill_idea_backlog.md
```

## 增长原则

- 优先优化已有采用信号的产品
- 新版本必须包含可解释的实质变化
- downloads、installs、stars 和搜索结果分别记录
- 新 Skill 至少观察 7 天，不用短期零数据判定失败
- 竞品成熟且差异不足时，不复制同类产品
- 新方向必须强化“ClawHub 发布与增长工具作者”这条主线

当前处于 `Skill Publish Readiness 1.0.7` 的观察窗口。下一个产品或插件会由真实采用数据和竞争缺口决定。

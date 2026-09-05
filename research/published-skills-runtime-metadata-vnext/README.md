# 已发布 Skill 运行资格修复草案

状态：`observation-window-hold`

本目录保存 7 个已发布 Skill 的下一版运行 metadata 修复计划。它不包含
`SKILL.md`，不进入 catalog，也不会触发 ClawHub 发布。

## 已确认问题

当前 7 个 Skill 都声明：

```yaml
os: [macos]
```

OpenClaw 会在加载阶段按操作系统和必需二进制过滤 Skill，因此 `os` 是运行
资格合同，不是展示文案。错误地只声明 macOS，会让其他平台上的 Skill 在
模型选择前就被排除。

仓库审计没有在 7 个 Skill 中发现 macOS 专用命令或可执行资源。仓库自己的
Skill 发布 workflow 使用 `ubuntu-latest`，并在该环境中安装 Git、Bun 与
ClawHub CLI 后完成过真实发布 run。这直接证明 Git/ClawHub 发布工具链至少
支持 Linux，不应只标记为 macOS。

## 分组修复

### 纯文案 Skill

- `skill-summary-rewriter`
- `skill-positioning-audit`

两个目录只有 Markdown 和 `.clawhubignore`，正文任务是分析与改写输入文本。
它们不执行 Git 或 ClawHub 命令，因此删除：

- `metadata.openclaw.os`
- `metadata.openclaw.requires`
- `metadata.openclaw.install`

保留 `emoji` 与 `homepage`。

### 命令型 Skill

- `github-actions-clawhub-doctor`
- `release-proof-builder`
- `skill-launch-checklist`
- `skill-portfolio-growth-audit`
- `skill-publish-readiness`

这些 Skill 的任务会读取仓库、执行 dry-run、inspect、搜索或安装验证，因此
继续保留 `git`、`clawhub` 和 Node 安装声明，只把：

```yaml
os: [macos]
```

替换为：

```yaml
os: [macos, linux]
```

Linux 有本仓库 workflow 证据；Windows 尚未验证，本草案不放开 Windows。

## 证据来源

- OpenClaw Skills：
  `https://docs.openclaw.ai/tools/skills`
- ClawHub Skill format：
  `https://docs.openclaw.ai/clawhub/skill-format`
- 本仓库 Linux workflow：
  `.github/workflows/clawhub-skill-publish-local.yml`
- Ubuntu 发布成功 run：`33871495707`

机器可验计划见 `change-plan.json`。

## 离线审计

只读审计器会核对计划、观察策略、正式 catalog、7 个当前
`SKILL.md` 基线、Linux workflow 证据、声明边界和发布策略：

```bash
python3 research/published-skills-runtime-metadata-vnext/check_runtime_plan.py
```

默认模式只在计划或仓库事实失效时返回非零：

- `0`：计划有效；输出中的 `readyForFreshReview` 表示时间闸门状态。
- `2`：计划、证据或当前正式 metadata 已漂移，不能据此继续。

需要把“观察窗口已经到期”作为调用方前置条件时使用：

```bash
python3 research/published-skills-runtime-metadata-vnext/check_runtime_plan.py \
  --require-review-window
```

此模式在计划有效但尚未到期时返回 `1`，到期后返回 `0`。无论日期是否到达，
`readyToApply` 都固定为 `false`，且 `fresh-need-review` 始终保留；审计器不会
修改正式 Skill、catalog、版本或发布状态，也不会调用网络、ClawHub 或安装命令。

## 声明边界

已确认：

- `os` 与 `requires.bins` 会参与运行资格过滤。
- 7 个 Skill 当前都被限制为 macOS。
- 7 个目录均无 macOS 专用可执行资源或命令。
- Git/ClawHub 发布链路已在 Ubuntu 上成功运行。

尚未确认：

- 当前限制是否已经造成下载、安装或搜索损失。
- Windows 上的完整 Git/ClawHub 操作面是否通过验证。
- metadata 修复后会带来多少自然采用变化。

因此这是运行资格正确性修复候选，不是已经生效的增长结论。

## 发布边界

1. 等待当前自然观察窗口结束。
2. 只运行一次统一增长监控，保存变更前基线。
3. 再复核各 Skill 的真实命令需求和当时官方 metadata 合同。
4. 按采用信号与修复优先级选择目标，不默认一次发布 7 个版本。
5. 每个变化版本只做一次 E4，并重新建立自然观察起点。

# 参与 OpenClaw Publisher

这里欢迎真实的发布故障、可验证的增长问题，以及能强化 ClawHub 发布与增长主线的贡献。

## 适合提交的内容

- GitHub Actions → ClawHub 链路中的可复现故障
- 已发布 Skill 的内容、定位、示例或文档改进
- 有真实用户场景和竞争缺口的 Skill / Plugin 提案
- 发布工作流的可靠性、差分发布和证据核验改进
- 下载、安装、搜索可见性等公开数据的口径修正

以下内容通常不会直接进入开发：

- 没有目标用户和真实任务的“万能助手”
- 与现有 Skill 高度重叠、只换名字的提案
- 仅凭单次快照得出的增长结论
- 把 downloads 当作 installs 的分析
- 需要绕过权限、审核或安全边界的实现

## 提交 Issue

### 发布故障

使用 `发布故障 / Publish failure` 模板。请提供：

- 目标目录、slug 和预期版本
- 本地、GitHub、Actions、ClawHub 各层的实际状态
- 已脱敏的错误日志
- 可以稳定复现的最短步骤

不要粘贴 token、cookie、密钥或组织内部地址。

### Skill 或 Plugin 提案

使用 `Skill / Plugin 提案` 模板。高质量提案需要说明：

- 谁会遇到这个问题
- 他们现在如何解决
- 已有产品为什么不足
- 它如何加强当前产品线，而不是稀释主题
- 什么证据会证明这个方向值得继续

## 提交 Pull Request

一个 Skill 至少包含：

```text
skills/<stable-slug>/
├── SKILL.md
├── CHANGELOG.md
├── .clawhubignore
├── examples/
├── references/
└── templates/
```

命名规则：

- 目录名使用稳定 slug
- slug 不能以 `clawhub-` 开头，也不能以 `-clawhub` 结尾
- `SKILL.md` 使用人类可读 `name`
- frontmatter 显式声明与目录一致的 `slug`
- 新版本必须包含可解释的实质变化

元数据规则：

- 在 `.clawhub/skill-catalog.json` 中配置 `displayName`
- 设置与真实任务匹配的 `categories` 和 `topics`
- 不为了搜索覆盖堆砌无关关键词

## 本地验证

安装并登录 ClawHub CLI：

```bash
npm i -g clawhub
clawhub login
clawhub whoami
```

对目标 Skill 执行：

```bash
clawhub skill publish ./skills/<stable-slug> \
  --slug <stable-slug> \
  --name "<Human Readable Name>" \
  --dry-run \
  --owner <owner>
```

dry-run 应返回：

- 预期 slug
- 人类可读展示名
- 高于 registry latest 的版本
- `would-publish` 或合理的同步状态

## PR 需要证明什么

PR 描述应区分以下证据：

| 证据 | 能证明什么 |
|---|---|
| 文件 diff | 修改内容真实存在 |
| 结构校验 | 必需文件与元数据完整 |
| dry-run | ClawHub CLI 可以解析目标版本 |
| GitHub Actions | 自动发布链路已执行 |
| `clawhub inspect` | registry 可读取目标版本 |
| 隔离安装 | 目标版本达到 E4，可下载使用 |

PR 阶段通常只能证明到 dry-run。合并后的 registry 与安装结果由维护者继续验收。

## 安全边界

- 所有示例使用占位符，不提交真实凭据
- 不通过日志或截图暴露 token
- 不降低审核、权限或 owner 校验来换取发布成功
- 不对未知错误无限重试
- 不伪造下载、安装、星标或搜索排名

## 决策原则

维护者优先合并能解决真实失败、提高可验证性或强化系列定位的贡献。新方向需要同时满足三点：任务清楚、差异存在、证据可收集。

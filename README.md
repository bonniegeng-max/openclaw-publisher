# ClawHub 自动同步模板

这个目录已经按「GitHub 作为源码仓库，ClawHub 作为发布仓库」的思路做好了基础结构。

后续你只需要：

1. 把 skill 放到 `skills/<skill-slug>/SKILL.md`
2. 把 plugin 放到 `plugins/<plugin-name>/`
3. 把整个目录推到 GitHub
4. 在 GitHub 仓库里配置变量和密钥
5. 以后新增或修改 skill / plugin，提交到 GitHub 后会自动触发对应工作流

## 目录约定

```text
.
├── .github/workflows/
│   ├── clawhub-skill-publish.yml
│   └── clawhub-plugin-publish.yml
├── skills/
│   └── ...
└── plugins/
    └── ...
```

## GitHub 需要配置的内容

### 1. Repository Variables

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions -> Variables` 里新增：

- `CLAWHUB_OWNER`
  - 你的 ClawHub 发布 owner
  - skill 发布时会传给 `--owner`
  - plugin 发布时也会作为 owner 传入

### 2. Repository Secrets

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions -> Secrets` 里新增：

- `CLAWHUB_TOKEN`
  - 用 `clawhub login` 登录后，可通过 `clawhub token` 拿到
  - skill 自动发布目前建议直接用这个 token
  - plugin 也可以先用这个 token；后续再升级到 trusted publishing

## Skill 放法

每个 skill 一个文件夹，至少包含一个 `SKILL.md`：

```text
skills/
└── my-skill/
    ├── SKILL.md
    └── 其他辅助文件
```

一个最小的 `SKILL.md` 例子：

```md
---
name: my-skill
description: 这是一个示例 skill。
version: 1.0.0
metadata:
  openclaw:
    os: [macos]
---

# My Skill

这里写 skill 的说明、使用方式和约束。
```

## Plugin 放法

每个 plugin 一个文件夹，至少建议包含：

```text
plugins/
└── my-plugin/
    ├── package.json
    ├── openclaw.plugin.json
    └── 代码文件
```

其中：

- `package.json` 里需要带 `openclaw.compat.pluginApi` 和 `openclaw.build.openclawVersion`
- `package.json` 的包名 scope 要和 `CLAWHUB_OWNER` 对应
- `openclaw.plugin.json` 里要有插件清单

## 工作流行为

### Skill 工作流

- `pull_request`：对 `skills/**` 做 dry-run 检查
- `push` 到 `main`：自动发布 `skills/**`
- `workflow_dispatch`：可手动触发重新发布

### Plugin 工作流

- `pull_request`：只对改动过的 plugin 目录做 dry-run
- `push` 到 `main`：只发布改动过的 plugin 目录
- `workflow_dispatch`：可指定单个 plugin 目录，也可发布所有 plugin

## 推荐发布方式

### Skill

推荐把 skill 放在这个仓库下统一管理，合并到 `main` 后自动发到 ClawHub。

### Plugin

如果 plugin 还在早期阶段，先用 `CLAWHUB_TOKEN` 即可。

如果 plugin 已经稳定，建议后续再补 `trusted publishing`，这样可以减少长期 token 依赖。

## 本地验证

在本地先装 CLI：

```bash
npm i -g clawhub
clawhub login
clawhub whoami
```

### 本地验证 skill

```bash
clawhub skill publish ./skills/my-skill --dry-run --owner <your-owner>
```

### 本地验证 plugin

```bash
clawhub package validate ./plugins/my-plugin
clawhub package publish ./plugins/my-plugin --dry-run --owner <your-owner>
```

## 推到 GitHub

如果你还没初始化 git，可以在这个目录执行：

```bash
git init
git add .
git commit -m "init clawhub sync template"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

推上去以后，GitHub 本身就已经保存了源码；而 `main` 分支合并后，Actions 会继续把内容发布到 ClawHub。

## 你接下来要做的事

1. 把这个目录建成 GitHub 仓库
2. 配置 `CLAWHUB_OWNER`
3. 配置 `CLAWHUB_TOKEN`
4. 新增第一个 `skills/<slug>/SKILL.md` 或 `plugins/<name>/`
5. 提交并推送

完成后，这套模板就能开始工作。

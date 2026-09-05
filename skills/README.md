# `skills/` 目录说明

这里存放已经进入正式发布链路的 ClawHub Skill。研究草案、候选方向和
尚未完成验收的内容必须放在 `research/`，不能提前加入本目录。

## 目录合同

每个 Skill 对应一个一级子目录，并至少包含：

```text
skills/
└── my-skill/
    ├── SKILL.md
    ├── CHANGELOG.md
    ├── .clawhubignore
    ├── examples/
    ├── references/
    └── templates/
```

其中：

- 目录名是稳定 slug，只使用小写字母、数字和连字符。
- slug 不得以 `clawhub-` 开头或以 `-clawhub` 结尾。
- `SKILL.md`、`CHANGELOG.md` 和 `.clawhubignore` 是仓库级必需文件。
- `examples/`、`references/` 和 `templates/` 按产品需要提供，但不得在
  `SKILL.md` 中引用不存在的文件。
- `.clawhub/skill-catalog.json` 是展示名、categories 和 topics 的唯一
  仓库级来源。

## Frontmatter

仓库中的最小 frontmatter：

```yaml
---
name: my-skill
slug: my-skill
description: 用一句具体的话说明任务、目标用户和结果。
version: 1.0.0
metadata:
  openclaw:
    emoji: "🧰"
    homepage: https://github.com/OWNER/REPOSITORY
---
```

要求：

- `slug` 与目录名保持一致；新 Skill 的 `name` 优先遵循可移植格式并与
  目录名一致。
- 既有 Skill 不为格式整齐而改名。发布路由继续使用显式 `--slug`，
  商店展示名继续只从 catalog 的 `displayName` 读取。
- `version` 使用语义化版本，并与 `CHANGELOG.md` 同步。
- 不要复制模板化运行依赖。只有 Skill 实际需要时，才声明
  `metadata.openclaw.os`、`requires`、`envVars` 或 `install`。
- 不在 Skill、示例、日志或提交中写入 token、Cookie、Authorization
  header 或私有地址。

## Catalog

每个正式 Skill 必须在 `.clawhub/skill-catalog.json` 中有唯一条目：

```json
{
  "skills/my-skill": {
    "displayName": "My Skill",
    "categories": ["development"],
    "topics": ["specific-task", "expected-result"]
  }
}
```

发布 workflow 会显式使用目录 slug 和 catalog 中的人类可读展示名。不要
依赖 CLI 从标题猜测 slug，也不要在 `SKILL.md`、workflow 和 catalog
分别维护互相冲突的展示 metadata。

## 发布行为

- Pull Request：只对发生实质变化的 Skill 运行 dry-run。
- 合并到 `main`：只发布发生实质变化的 Skill 目录。
- 只修改 `skills/README.md` 不会形成可发布 Skill 目标。
- 确定性错误立即失败；只有已识别的瞬时上传错误允许有限重试。
- 不为制造活跃度发布无实质变化的版本。

等价的显式命令必须同时包含稳定 slug 和展示名：

```bash
clawhub skill publish skills/my-skill \
  --dry-run \
  --owner <owner> \
  --slug my-skill \
  --name "My Skill"
```

真实发布不能只因 dry-run 通过就宣称成功。

## 提交前检查

至少运行：

```bash
python3 -m unittest discover -s tests
python3 -m py_compile scripts/*.py tests/*.py
git diff --check
```

涉及 workflow 时还要确认所有 YAML 可解析。

## 上线证据

- `E0`：仅有本地文件。
- `E1`：GitHub 远端包含目标提交。
- `E2`：对应发布 workflow 成功。
- `E3`：ClawHub registry 返回正确版本、展示名、topics 和 `clean`
  moderation。
- `E4`：指定版本完成一次隔离安装，核心文件与对应 GitHub 提交一致。

只有达到 `E4` 才能声明“已上线、可下载使用”。每个变化版本最多进行一次
计划内 E4 验收；验收产生的 downloads 或 installs 不得归因为自然用户。

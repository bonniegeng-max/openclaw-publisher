# plugins 目录说明

这里放所有准备发布到 ClawHub 的 plugin。

## 规则

- 一个 plugin 对应一个子目录
- 每个 plugin 目录至少应包含：
  - `package.json`
  - `openclaw.plugin.json`
- `package.json` 的包名 scope 需要和 ClawHub owner 对齐
- 建议先本地通过 dry-run，再提交到 GitHub

## 示例

```text
plugins/
└── my-plugin/
    ├── package.json
    ├── openclaw.plugin.json
    └── src/
```

## 本地验证

```bash
clawhub package validate ./plugins/my-plugin
clawhub package publish ./plugins/my-plugin --dry-run --owner <your-owner>
```

提交到 GitHub 后：

- PR 阶段只会检查改动过的 plugin 目录
- 合并到 `main` 后只会发布改动过的 plugin 目录
- 手动触发工作流时，可以指定单个 `plugin_path`

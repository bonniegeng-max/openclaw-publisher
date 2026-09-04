# 发布后核验命令

## Git 远端一致性

```bash
git rev-parse HEAD
git ls-remote origin HEAD
```

只有两个提交哈希一致，才能证明当前本地提交已经进入远端默认分支。

## ClawHub Registry

```bash
clawhub inspect @<owner>/<slug> --json
```

重点检查：

- `displayName`
- `summary`
- `tags.latest`
- `topics`
- `moderation`

## 版本历史

```bash
clawhub inspect @<owner>/<slug> --versions --limit 10 --json
```

用于确认最新版本是否更新，以及是否出现了无意义的重复版本。

## 隔离目录安装

```bash
clawhub --workdir <temporary-directory> install @<owner>/<slug>
```

安装后检查目标目录中的 `SKILL.md` 和关键配套文件。临时目录应在验证后删除。

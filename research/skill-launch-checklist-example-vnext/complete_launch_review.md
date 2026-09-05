# 上线前快速评审：文件齐全，但 slug 不能发布

本例来自仓库真实历史，不执行 dry-run 或正式发布。机器可验输入见
`launch-review-evidence.json`。

## 输入

- 提交：`e806aec8cd69a4a885a065ac41fab59596664fda`
- 目录：`skills/clawhub-launch-checklist`
- name：`clawhub-launch-checklist`
- 版本：`1.0.0`
- catalog displayName：`ClawHub Launch Checklist`

候选包包含：

- `SKILL.md`
- `CHANGELOG.md`
- `.clawhubignore`
- `examples/launch_ready_vs_rushed.md`
- `references/launch_checklist.md`
- `templates/launch_review.md`

## 上线结论

`先别发`

文件和商店页材料已经接近完整，但 slug 使用受保护前缀 `clawhub-`。这是
确定性发布阻塞项，不能用“其他检查都通过”抵消。

## 检查矩阵

| 类别 | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 基础结构 | `SKILL.md` | 通过 | 目标提交包含文件 |
| 基础结构 | `CHANGELOG.md` | 通过 | 目标提交包含文件 |
| 基础结构 | `.clawhubignore` | 通过 | 目标提交包含文件 |
| 配套内容 | example / reference / template | 通过 | 三类文件均存在 |
| 版本 | frontmatter version | 通过 | `1.0.0` |
| 发现性 | categories / topics | 通过 | catalog 条目已配置 |
| 命名 | slug 不使用受保护命名空间 | 阻塞 | `clawhub-launch-checklist` 以 `clawhub-` 开头 |
| 展示 | 标题像人类可读产品名 | 漏项 | name 与目录名相同，像内部路由 |
| dry-run | 指定修复后的 slug/name | 未执行 | 本草案不访问 ClawHub |

## 阻塞项

唯一发布阻塞项：

```text
clawhub-launch-checklist
```

违反规则：

```text
slug 不得以 clawhub- 开头，也不得以 -clawhub 结尾
```

因此当前不能给出“可以发”，也不应重试同一个 slug。

## 漏项

可见标题仍是目录式名称 `clawhub-launch-checklist`。这不是本轮最先修的
阻塞项，但会降低页面可读性，应在同一次修改中使用人类可读展示名
`Skill Launch Checklist`。

## 最小补法

1. 将目录从 `skills/clawhub-launch-checklist` 改为
   `skills/skill-launch-checklist`。
2. 固定 stable slug 为 `skill-launch-checklist`。
3. 将 catalog key 同步为 `skills/skill-launch-checklist`。
4. 将 displayName 设为 `Skill Launch Checklist`。
5. 更新仓库中引用旧路径或旧 slug 的位置。
6. 在 workflow 中对 `clawhub-*` 和 `*-clawhub` 增加发布前失败规则。

仓库提交 `33ead75f52ec36da2adf89f542425f2ed3cbd67b` 已执行目录/catalog
重命名并增加 workflow 前置保护，为上述判断提供真实修复证据。

## 修复后状态

完成静态修复后，结论只能升级为：

`基本可发，等待 dry-run`

不能在 dry-run 尚未执行时声明“可以正式发布”，更不能声明已上架或可安装。

## 下一步命令

```bash
clawhub skill publish ./skills/skill-launch-checklist \
  --slug skill-launch-checklist \
  --name "Skill Launch Checklist" \
  --dry-run \
  --owner <owner>
```

dry-run 通过只证明候选可解析。正式发布后仍需按 E1–E4 验证 GitHub、
workflow、registry、moderation 和指定版本隔离安装。

## 证据边界

- 本例没有执行 dry-run、publish、inspect 或 install。
- 文件齐全不等于 slug 合法。
- 修复 commit 存在不等于新版本已经达到 E4。
- 本例证明的是上线前正确性问题，不证明下载或搜索影响。

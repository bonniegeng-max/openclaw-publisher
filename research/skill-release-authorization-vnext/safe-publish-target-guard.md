# 安全 Skill 发布目标守卫（研究草案）

状态：`research-only-not-wired`

`safe_publish_target_guard.py` 只在本地读取 Git 历史和工作树，输出结构化的目标选择
结果。它未接入 `.github/workflows`，不会访问网络、读取凭据、安装包运行时、调用
ClawHub 或改变 registry 状态。机器可读约束见
`safe-publish-target-contract.json`。

合同离线审计入口：

```bash
python3 research/skill-release-authorization-vnext/check_safe_publish_target_contract.py
```

当前预期退出码为 `1`：合同与固定 Git blob 一致，但草案未接线且不可部署。退出码
`2` 表示合同、策略、guard 或正式 workflow 基线失配。

## 目标选择规则

- `workflow_dispatch` 只允许 `dry_run: true`；手动触发真实发布一律拒绝。
- `pull_request` 同样只允许 dry-run；真实 mutation 只可能来自
  `push` 且 ref 精确等于 `refs/heads/main`。
- 真实 mutation 必须提供完整 base，并证明显式目标是该区间内唯一变化的 Skill；
  不允许重复发布未变化目标。
- 真实 push 的 base、完整 head 与 ref 必须分别等于可信调用层提供的事件 before、
  SHA 与 ref；guard 只比较这些值，不能自行认证字符串确实来自 GitHub。
- `changed_only: true` 且既无有效 `base` 又无显式 `skill_path` 时 fail-closed。
- 不允许无边界扫描整个 `skills/`；每次最多选择一个 Skill。
- Git diff 中没有现存 Skill 时返回成功的 no-op，不把零目标解释为错误。
- Git diff 中存在多个现存 Skill 时拒绝，不自动任选其一。
- 显式路径必须严格等于 `skills/<valid-slug>`，不能是绝对路径、规范化前后不同的
  路径、反斜杠路径、受保护 slug、符号链接或缺少必需文件的目录。
- Skill 目录必须包含普通文件 `SKILL.md`、`CHANGELOG.md` 和 `.clawhubignore`。
- Git 固定使用 `/usr/bin/git`，不从继承的 `PATH` 发现可执行文件。
- `head` 必须等于当前 checkout 的真实 HEAD，且工作树不得有 tracked 或
  untracked 变化。

显式 `skill_path` 是人工限定的单目标选择；若同时提供 base，diff 中不得存在
目标之外的其他 Skill。未提供显式路径时，
`base` 必须是完整小写 commit，且必须是解析后 head 的祖先。删除 Skill 后没有
现存目标属于 no-op；一个删除与另一个新增仍属于多目标并整体拒绝。无效的现存
Skill 目录属于错误。

## 本地使用

按变更选择：

```bash
python3 research/skill-release-authorization-vnext/safe_publish_target_guard.py \
  --event-name push \
  --ref refs/heads/main \
  --dry-run true \
  --changed-only true \
  --base <完整 base commit> \
  --head HEAD
```

显式限定单一目标：

```bash
python3 research/skill-release-authorization-vnext/safe_publish_target_guard.py \
  --event-name workflow_dispatch \
  --dry-run true \
  --changed-only true \
  --skill-path skills/<slug>
```

退出码 `0` 表示选择成功或安全 no-op，退出码 `2` 表示输入、Git 边界或目标合同
无效。`authorizationEligible: true` 只表示事件、ref 与单目标边界允许进入后续
授权层，不构成 E1-E4；研究阶段 `authorized` 与 `mutationAllowed` 永远为
`false`。任何正式
接线必须在观察窗口结束后另行评审，并由固定 SHA launcher 绑定可信 GitHub 事件，
再原子地让所有联网、凭据和发布步骤依赖授权成功；本草案自身不能提供该保证。

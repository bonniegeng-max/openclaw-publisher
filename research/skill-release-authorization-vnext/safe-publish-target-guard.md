# 安全 Skill 发布目标守卫（研究草案）

状态：`research-only-not-wired`

`safe_publish_target_guard.py` 只在本地读取 Git 历史和工作树，输出结构化的目标选择
结果。它未接入 `.github/workflows`，不会访问网络、读取凭据、安装包运行时、调用
ClawHub 或改变 registry 状态。机器可读约束见
`safe-publish-target-contract.json`。

当前输出为 schema v2。只有有效的 `single-target` 结果携带
`packageSnapshot`；`no-op` 和所有 `blocked` 结果的该字段均为 `null`。

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
- Git diff 中没有 Skill 路径变化时返回成功的 no-op，不把零目标解释为错误。
- Git diff 中存在多个 Skill 路径变化时拒绝，不论这些目标在 HEAD 中是否仍存在；
  不自动任选其一。
- 显式路径必须严格等于 `skills/<valid-slug>`，不能是绝对路径、规范化前后不同的
  路径、反斜杠路径、受保护 slug、符号链接或缺少必需文件的目录。
- Skill 目录必须包含普通文件 `SKILL.md`、`CHANGELOG.md` 和 `.clawhubignore`。
- 包快照只从已解析的 HEAD commit tree 读取，不以工作树内容构造证据。快照包含
  目标 tree OID，以及 tree 中每个文件的包内相对路径、Git mode、blob OID 和
  `sha256:` 内容摘要；Git symlink、submodule 和其他非普通 blob mode 一律拒绝。
- `packageDigest` 是以下对象的规范 JSON（UTF-8、对象键排序、无多余空白、
  `ensure_ascii=false`）的 SHA-256，前缀为 `sha256:`：
  `{"files": <按 UTF-8 路径字节排序的完整文件数组>, "format":
  "safe-publish-package-v1", "skillPath": <规范目标路径>, "treeOid":
  <tree OID>}`。格式、目标路径、tree OID 及每个文件的路径、mode、blob OID 和
  SHA-256 任一变化都会改变摘要。
- 工作树使用 no-follow 文件描述符递归遍历，逐项与 HEAD 快照的路径、mode 和
  SHA-256 精确匹配。额外文件（包括被 Git 忽略的文件）、额外目录、缺失项、
  symlink、hardlink 和特殊文件均拒绝；平台缺少 `O_NOFOLLOW` 或
  `O_DIRECTORY` 时不降级，直接拒绝。仓库根、`skills` 与 slug 目录均从已打开
  的父目录 FD 逐级 no-follow 打开，不在检查后重新解析完整包路径。
- 包最多包含 1024 个文件，单文件最多 10 MiB，总内容最多 50 MiB；超限时在读取
  blob 内容前 fail-closed，避免无界内存与进程开销。
- Git 固定使用 `/usr/bin/git`，不从继承的 `PATH` 发现可执行文件。
- `.git/objects` 及其完整目录树必须由本地真实目录和普通文件构成，不能在
  `pack`、`info` 或 loose-object fan-out 等子路径使用 symlink；alternates、
  外部或共享 Git 目录同样拒绝。
- `head` 必须等于当前 checkout 的真实 HEAD，且工作树不得有 tracked 或
  untracked 变化；每次 clean 检查还会确认 `git status` 前后的 HEAD 未变化。
- 返回成功前再次验证 HEAD、全仓 clean 状态，并再次无跟随遍历和比对目标工作
  树；两次包快照必须一致，第二次包比对完成后还要执行最终 HEAD、clean 与
  repository layout 校验。

显式 `skill_path` 是人工限定的单目标选择；若同时提供 base，diff 中不得存在
目标之外的其他 Skill。未提供显式路径时，
`base` 必须是完整小写 commit，且必须是解析后 head 的祖先。删除 Skill 后没有
现存目标仅在该 diff 只涉及一个 Skill 路径时属于 no-op；删除两个 Skill，或一个
删除与另一个新增，仍属于多目标并整体拒绝。无效的现存 Skill 目录属于错误。

## 原子交付边界

本 guard 返回的是离散时刻的验证证据，不是已冻结的发布包。多次 HEAD、clean、
对象库与包内容复核只能缩小检查时竞态，不能保证 guard 返回后另一个进程按普通
工作树路径读取到相同字节。正式发布器不得仅消费 `skillPath` 后重新打包；必须在
不可并发写入的隔离 checkout 中直接从已验证的 `headCommit`、tree/blob OID 构造
不可变 staging 包，或消费等价的已验证文件描述符快照，并再次绑定
`headCommit + skillPath + treeOid + packageDigest`。未实现该原子交付前，本结果
不得解释为可安全发布授权。

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

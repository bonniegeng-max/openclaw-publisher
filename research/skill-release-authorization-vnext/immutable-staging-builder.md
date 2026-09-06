# Immutable staging builder 研究合同

状态：`research-only-not-wired`

`immutable_staging_builder.py` 是纯离线、未接线的研究原型。它不再从工作树
动态 import guard；模块加载时必须收到受信任 launcher 注入的 `GUARD` 快照和
`_TRUSTED_GUARD_INJECTED` 标志，否则立即失败。它不接收拆散的 commit、Skill
路径或 package digest，而只消费 `safe_publish_target_guard.py`
输出的完整 schema v2 JSON。缺字段、多字段、重复 JSON key、非单目标结果、
非 `valid` 结果、非空阻断原因、`authorized != false`、
`mutationAllowed != false` 或字段间语义不一致都会 fail-closed。builder 还会从
固定 commit 重新计算完整 `packageSnapshot` 并要求与 guard JSON 精确一致。
guard JSON 文件必须由当前用户拥有、没有 group/world 权限位，且从文件系统根
逐组件 no-follow 打开；symlink、非普通文件和读取期间变化均拒绝。

## 两阶段锚定

第一阶段把完整 guard JSON 的规范 JSON 字节绑定为 `guardResultDigest`。第二阶段
以 `immutable-skill-staging-v2` payload 绑定 schema、研究状态、格式、
`guardResultDigest`、commit、Skill 路径、tree OID、package digest、固定
`package/` 目录、每个文件的路径/Git mode/只读 artifact mode/blob OID/SHA-256，
以及 `worktreeRead: false`、`authorizationGranted: false`，再计算
`artifactDigest`。除 `artifactDigest` 自身外，manifest 的所有安全声明均受该摘要
保护；manifest 只是本地 artifact 证据，不是发布授权。

机器合同的 `builderEvidence` 与 `launcherEvidence` 另行绑定控制面源码本身。
首阶段只记录工作树 draft；提交推送并从 GitHub 外部确认后，第二阶段必须用该
提交的真实 mode、blob OID 与 SHA-256 替换为强制 baseline，不能预先猜测 commit
或 blob。仓内本地 tracking ref 只能做一致性检查，不能单独证明 GitHub 远端状态。

## 受信任 staging launcher

`trusted_staging_launcher.py` 要求 candidate 与 control 是两个独立、无路径
symlink、各自使用本地 `.git` 目录的 checkout。它只使用固定
`/usr/bin/git`，要求 control checkout 的 HEAD 精确等于调用方提供的完整
control commit，并从该同一 commit 读取 guard 与 builder 两个 blob；不会从
candidate 或当前 control 工作树 import 代码。
两个 checkout 的 origin 必须精确匹配
`github.com/bonniegeng-max/openclaw-publisher`，禁止共享 Git/common
directory、object alternates，以及对象库 symlink 与 hardlink；control commit
必须可从本地 `origin/main` 到达，candidate HEAD 必须等于本地 `origin/main`。
这些都是可由本地仓库所有者改写的一致性条件，不是远端真实性证据；正式调用者
必须是受保护、固定完整 SHA 的 workflow，并从其可信上下文提供 control commit。
两个 checkout 的 `.git` 与 objects identity 分别比较，任一共享都拒绝；对象库
条目必须归当前用户所有、不可由 group/world 写入，目录 `stat` 与实际打开 FD 的
inode 必须一致。

launcher 用带 magic 和 64 位长度的内存 frame 分两次传递控制源码与规范请求
JSON。第一个固定 Python `-I` 子进程只执行 guard；父进程严格验证完整 guard
JSON、复核 candidate tree，并计算规范 `guardResultDigest`。第二个独立子进程才
加载同一 control commit 的 builder 与 guard blob，通过 namespace 注入 guard
module，并消费父进程冻结的 guard JSON。builder 顶层代码不能先于原始 guard
决策执行；manifest 摘要不匹配父进程冻结值时拒绝。中间结果只走内存 frame，
不落盘为可替换 JSON。两个 child 都使用仅含 locale、固定 PATH 和 Python 隔离
开关的 allowlist 环境。

launcher 对 child JSON、退出码、结果字段、manifest 字段、摘要和跨字段语义做
严格验证。成功后，它从已验证 output parent FD 独立重新打开 artifact，要求根
目录、package、manifest 与所有子目录/文件均为约定类型和 mode，文件集合、
SHA-256、规范 manifest 字节及 `artifactDigest` 全部一致，并重新证明
`candidate commit → skillPath → treeOid → path/mode/blobOid` 完整关系。
candidate HEAD、本地 tracking ref 与 control sources 在 child 前后必须不变。
child 从进程启动起限时 180 秒，stdin 非阻塞写入也包含在期限内；stdout/stderr
合计限制 2 MiB。launcher 增量读取输出，达到上限或超时时终止整个子进程组。
任何 stderr、超限或不一致均 fail-closed。

异常后 launcher 不采信 child 自报的 `created`，而是从已验证 output parent FD
探测父进程从冻结 guard 结果独立计算的规范内容寻址名称：目录不存在返回
`absent`，目录存在但未通过完整复核返回 `present-unverified`，完整复核通过但
launcher 整体因 child 输出或 tracking ref 等原因失败时返回
`present-verified-snapshot`，无法安全解析名称或 parent 身份漂移时返回
`unknown`。

成功路径会在所有 Git/control 终态检查后再次完整验证 artifact，并只声明
`present-verified-snapshot`。这不是稳定路径交接：同 UID 仍可在函数返回后改写
父目录。正式消费者必须继承或重新打开同一已验证 FD 树，重复验证 manifest 与
文件内容后直接消费，不能仅凭 `outputName` 信任路径。当前实现未提供 OS 级网络
sandbox；源码 token 检查只作 lint，不能替代固定 Git blob 与行为故障注入证据。

## FD/no-follow 文件系统边界

output parent 必须是仓库外、已存在、当前用户所有、精确 `0700` 的规范绝对目录。
从文件系统根开始，每个路径组件都通过 `openat`/`dir_fd` 与 `O_NOFOLLOW` 打开；
是否位于仓库内按已打开目录的 device/inode 身份判断。后续创建、遍历、复核、
清理和 rename 全部相对已验证 parent FD 或其后代 FD 执行。

临时目录使用随机名称和 `mkdirat` 创建，不使用 `tempfile`。实现不使用
`shutil` 或 `os.walk`。普通文件及 manifest 最终为 `0444`，Git 可执行文件为
`0555`，全部目录封存为 `0555`。写入使用 `O_EXCL|O_NOFOLLOW`，逐文件复核
mode/SHA-256，拒绝 symlink、hardlink、特殊文件及集合漂移，并再次计算固定 Git
snapshot。提交前还会重新验证仓库布局及 checkout HEAD 仍等于 guard 的完整
`headCommit`。文件、目录和 parent 都执行规定的 `fsync`。

## 原子交接与结果

最终名称绑定 slug、commit 前缀与 `artifactDigest` 前缀。交接只调用：

- macOS：`renameatx_np(parent_fd, src, parent_fd, dst, RENAME_EXCL)`；
- Linux：`renameat2(parent_fd, src, parent_fd, dst, RENAME_NOREPLACE)`。

源名和目标名必须使用同一个已验证 parent FD；没有普通 rename fallback。rename
前失败返回 `status: failed` 并通过 FD 清理随机临时树。rename 成功后若 parent
`fsync` 失败，返回 `status: commit-uncertain`、`created: true` 并保留最终目标，
避免把已经可能持久化的提交误报为未发生。成功状态为 `committed`。所有结构化
结果均固定 `authorizationGranted: false`，只返回内容寻址的 `outputName`，不
返回机器绝对路径。

staging 根 FD 会跨越 rename 保持打开；rename 后从同一 FD 再次复核 package 和
manifest，并确认最终目录项 inode 与该 FD 一致，同时重新打开 output parent 路径
核对 device/inode。任一 post-commit 复核失败均返回 `commit-uncertain` 并保留
目标。rename 前清理若不完整则返回 `failed-with-residue` 和随机
`residueName`，不会静默声称已清理。

这里的“不可变”指内容寻址、no-replace 提交、无 owner write bit 和可重复验证，
不是内核级 immutable flag。同 UID 或 root 仍可能在 builder 返回后改权限或替换
产物，因此任何消费者在使用前必须重新验证 manifest 与两级摘要。

## 离线审计

```bash
python3 research/skill-release-authorization-vnext/check_immutable_staging_contract.py
```

- `1`：合同有效，但仍不可部署；
- `2`：合同、safe guard、正式 workflow 基线或实现边界不一致。

builder 的底层 CLI 仅接受 `--repo-root`、`--output-parent` 和
`--guard-result`，但不能直接启动，必须由受信任 bootstrap 注入 guard。正式
研究入口是 `trusted_staging_launcher.py`，且 launcher 自身也必须以 `python -I`
启动。成功返回 `0`，失败或 commit-uncertain 返回 `2`。它不读取目标 Skill
工作树，不访问网络、
不接收凭据、不运行包代码、不调用 registry，也不修改正式 workflow。当前证据仅
为 E0，不构成 E1-E4。

## 正式消费边界

当前正式 ClawHub publisher 仍从 checkout 工作树路径打包，因此本 builder 明确
禁止接线。观察期结束后的原子改造必须让 publisher 只消费重新验证过的 staging
artifact，并在同一已打开 FD 树上完成验证与使用；不得先验证 staging，再回到
`workspace/skills/<slug>` 发布。builder、guard 和 verifier 也必须由固定 Git
blob 的受信任 launcher 加载，不能把当前工作树动态 import 当作信任根。

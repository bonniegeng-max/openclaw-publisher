# Immutable staging builder 研究合同

状态：`research-only-not-wired`

`immutable_staging_builder.py` 是纯离线、未接线的研究原型。它不接收拆散的
commit、Skill 路径或 package digest，而只消费 `safe_publish_target_guard.py`
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

机器合同的 `builderEvidence` 另行绑定 builder 源码本身。首阶段只记录工作树
draft；提交推送后，第二阶段必须用远端可达提交的真实 mode、blob OID 与 SHA-256
替换为强制 baseline，不能预先猜测 commit 或 blob。

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

builder CLI 仅接受 `--repo-root`、`--output-parent` 和 `--guard-result`。成功返回
`0`，失败或 commit-uncertain 返回 `2`。它不读取目标 Skill 工作树，不访问网络、
不接收凭据、不运行包代码、不调用 registry，也不修改正式 workflow。当前证据仅
为 E0，不构成 E1-E4。

## 正式消费边界

当前正式 ClawHub publisher 仍从 checkout 工作树路径打包，因此本 builder 明确
禁止接线。观察期结束后的原子改造必须让 publisher 只消费重新验证过的 staging
artifact，并在同一已打开 FD 树上完成验证与使用；不得先验证 staging，再回到
`workspace/skills/<slug>` 发布。builder、guard 和 verifier 也必须由固定 Git
blob 的受信任 launcher 加载，不能把当前工作树动态 import 当作信任根。

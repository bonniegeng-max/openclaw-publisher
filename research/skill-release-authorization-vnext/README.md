# Skill 发布授权门禁草案

状态：`offline-contract-ready-not-wired`

本目录记录正式 Skill 发布链路的 fail-closed 授权设计。实现位于：

```text
scripts/check_skill_release_authorization.py
```

当前不会修改或调用两个 ClawHub 发布 workflow。观察窗口结束前，只在
`Metrics Tools CI` 中编译并通过离线测试；不能把本草案解释为已授权发布。
GitHub environment、受信任 workflow SHA 和 secret 迁移方案见
`workflow-integration-plan.md`。

机器可读的当前接线状态位于
`workflow-integration-contract.json`，离线检查入口为：

```bash
python3 research/skill-release-authorization-vnext/check_workflow_integration_contract.py
```

当前合同使用 schema v2。相较初始 v1，它强制要求 caller Git blob 基线、
trusted control 文件的 mode/blob 证据，以及 launcher draft 的固定提交证据；
旧 v1 或未知未来版本均 fail-closed。

当前预期退出码为 `1`：合同本身有效，但 `deploymentReady` 必须保持
`false`。该检查器只核验独立本地 Git 数据库、提交、mode、blob OID 与摘要的一致
性，不解析 YAML，也不把本地 `origin`、remote-tracking ref、environment 名称、
仓内布尔值或示例文本解释为 GitHub 远端或审批证据。Git 调用禁用 replace refs、
lazy fetch 和候选环境注入，因此不会为补齐缺失对象访问远端。正式 reusable
workflow SHA、ClawHub CLI commit、两个 environment 配置和受控演练证据缺少
任一项时，都不能切换为可发布状态。

观察期内的正式 caller workflow 由 `formalWorkflows.callerBaseline` 绑定到固定
commit 的 Git blob、文件模式与 SHA-256；检查器还要求当前工作树字节和执行位与
该基线一致。单独更新摘要，或同时修改 caller 与合同中的摘要，都不能继续证明
观察期冻结状态完好。

## 已确认断点

当前 `ClawHub Skill Publish` 与 `Metrics Tools CI` 是彼此独立的 workflow。
catalog 预检、观察策略、Package Doctor 提升合同和 runtime metadata 计划即使
在只读 CI 中失败，也不能阻止另一个 workflow 先执行 dry-run 或真实 publish。

因此，观察期结束后的发布链路必须在安装 ClawHub CLI、访问 registry 或执行
dry-run 之前完成一次发布内联授权检查。

## 授权合同

一次变更授权必须绑定：

- 本次 diff 的完整 base commit。
- 授权前的唯一 candidate commit。
- 恰好一个实际变化的正式 Skill。
- 高于 base 版本的正式三段式版本。
- catalog 是否发生有效条目变化。
- 目标 Skill 全部文件及对应 catalog 条目的 SHA-256 摘要。
- 除授权文件外完整 changed-path 集合及每个文件内容的 SHA-256 摘要。
- 明确允许的 `dry-run` / `publish` 模式。
- 不早于观察窗口、且不超过 72 小时的 fresh review 时间。
- 每个 review 证据文件的独立 SHA-256 摘要。
- review 证据文件必须出现在同一 release diff 中。
- 最长 72 小时的授权有效期。

授权文件本身必须出现在同一 diff 中。后续提交若只修改 Skill 而复用旧授权，
将同时因以下条件失败：

- 授权文件未随本次变更更新。
- base commit 不匹配。
- Skill 内容摘要或完整变更集摘要不匹配。

`releaseId` 必须精确等于 `<slug>-<version>`。最终 HEAD 必须只比 candidate
多一个提交，且该提交只能修改授权 JSON；额外提交即使不改变文件树也会失败。

观察策略、授权检查器、catalog 预检器及任意发布 workflow 不允许与 Skill
发布处于同一个 diff；这些控制面必须先独立合并并验证。生产 CLI 不提供
`--now` 或自定义 policy 路径，避免调用方伪造时钟或替换观察策略。

模板见 `authorization-template.json`。模板保持 `status: pending`，并把
`issuedAt`、`expiresAt`、`reviewedAt` 留为 `null`，不能直接用于发布。

## 本地调用

先把 Skill 变更和 review 证据提交到本地候选 commit，再自动生成 pending 草稿：

```bash
python3 scripts/prepare_skill_release_authorization.py \
  --base <变更前完整提交> \
  --release-id <本次发布标识> \
  --mode dry-run \
  --change-class correctness-fix \
  --reason "<已验证的变更原因>" \
  --evidence <本次 diff 中的 review 证据>
```

准备器要求显式选择模式，不会默认附带 `publish` 权限。它自动计算目标、版本、
catalog 状态、候选提交、Skill 内容摘要、完整变更集摘要和证据摘要，但不会填写
审批时间或把状态改为 approved。若仓库已经保留上一轮授权文件，必须显式传入
`--force` 才会原子替换，避免静默覆盖。

完成仓外 fresh review 后，填写审批字段并提交授权文件，再执行：

```bash
python3 -I <control-root>/scripts/check_skill_release_authorization.py \
  --repo-root <candidate-root> \
  --base <变更前完整提交> \
  --head HEAD \
  --mode dry-run \
  --control-root <control-root> \
  --control-commit <受信任完整提交>
```

`control-root` 与 candidate 必须是独立 clone；control checkout 的 HEAD、origin、
Git common directory、checker/validator mode、blob OID 和磁盘字节都会校验。
`python -I`、固定解释器/Git 路径以及 `control-commit` 的仓外可信来源仍必须由
受保护 launcher 提供，checker 自身不能用路径自检证明自己最初就是可信代码。

研究版 launcher 位于：

```text
research/skill-release-authorization-vnext/trusted_preflight_launcher.py
```

它先把 control commit 中的 checker blob、磁盘字节和执行模式绑定，再以隔离
Python 从该字节快照执行 checker；随后验证严格 JSON、退出码、slug、semver、
releaseId、base/candidate/head、单目标以及 trusted-control 证据是否一致。它不
接收 token、registry 或发布参数，也不执行 Bun、ClawHub、dry-run 或 publish。
launcher 不从继承的 `PATH` 发现 Git，而只使用固定系统入口 `/usr/bin/git`；
入口缺失、目标不是可执行普通文件时立即失败，防止候选环境把伪 Git 提升为证据
信任根。可信 Python 解释器仍必须由未来 fixed-SHA workflow 在仓外固定。
正式接线后必须从固定完整 SHA 的 reusable workflow 调用该逻辑；仅存在研究文件
不能把 `trusted-control-execution` 改为已验证。
workflow 还必须保证 control 与 candidate checkout 在整个 preflight 期间不被
其他 job 或进程写入；静态路径检查不能独立消除同主机并发替换风险。

退出码：

- `0`：合同有效，且当前模式已获本次变更授权。
- `1`：合同结构有效，但被观察期、fresh review、模式或时效阻断。
- `2`：合同、diff、版本、catalog、证据或内容摘要不一致。

输出字段 `authorized: true` 是未来 workflow 可以消费的仓内完整性条件，但
不是批准者身份凭据。

review evidence 只提供与候选提交绑定的支持材料，不能证明 reviewer 身份。
`status`、`modes` 和时间字段最终必须由受保护环境绑定的审批步骤确认；提交者
自行把 pending 改成 approved 不构成可信批准。

## 计划接入顺序

观察窗口结束并完成统一增长监控后：

1. fresh review 只选择一个最高优先级正式变更。
2. 生成与该候选 commit 绑定的 `.clawhub/skill-release-authorization.json`。
   最终 HEAD 只能在候选 commit 后增加一个仅修改授权 JSON 的提交。
3. 在可复用发布 workflow 的首次 checkout 后执行 catalog 预检和本门禁。
4. 使用 GitHub protected environment 或等价的仓外审批绑定最终 head SHA；
   仓内 JSON 只证明变更完整性，不能单独证明批准者身份。
5. 从受信任 base 版本执行 checker，不能使用待发布提交修改后的门禁给自身放行。
6. 让 Bun、ClawHub 源码 checkout、dry-run 与 publish 全部依赖授权成功。
7. 增加 workflow 合同测试，证明授权失败时所有联网和发布步骤不可达。
8. 发布后按 E0-E4 验证；每个变化版本最多执行一次隔离安装。

checker 与 validator 已绑定到同一 control commit，并从已验证 validator blob
快照加载，不再执行 candidate 中的 validator 副本。该能力目前只证明本地封闭
执行机制可用；正式 workflow 尚未用固定完整 SHA、`python -I` 和受保护 launcher
调用它，因此 `trusted-control-execution` 仍必须保持阻塞。

在完成上述原子接入前，不能声称正式发布链路已经具备 fail-closed 授权能力。
即使接入后，仓内合同也不能提供真正的一次性消费记录；同一 head 的重复运行
需要由 GitHub environment/deployment 状态或等价仓外系统阻止。

# Skill 发布授权门禁草案

状态：`offline-ready-not-wired`

本目录记录正式 Skill 发布链路的 fail-closed 授权设计。实现位于：

```text
scripts/check_skill_release_authorization.py
```

当前不会修改或调用两个 ClawHub 发布 workflow。观察窗口结束前，只在
`Metrics Tools CI` 中编译并通过离线测试；不能把本草案解释为已授权发布。

## 已确认断点

当前 `ClawHub Skill Publish` 与 `Metrics Tools CI` 是彼此独立的 workflow。
catalog 预检、观察策略、Package Doctor 提升合同和 runtime metadata 计划即使
在只读 CI 中失败，也不能阻止另一个 workflow 先执行 dry-run 或真实 publish。

因此，观察期结束后的发布链路必须在安装 ClawHub CLI、访问 registry 或执行
dry-run 之前完成一次发布内联授权检查。

## 授权合同

一次变更授权必须绑定：

- 本次 diff 的完整 base commit。
- 本次实际变化的正式 Skill 集合。
- 每个目标的正式三段式版本。
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

观察策略、授权检查器、catalog 预检器及任意发布 workflow 不允许与 Skill
发布处于同一个 diff；这些控制面必须先独立合并并验证。生产 CLI 不提供
`--now` 或自定义 policy 路径，避免调用方伪造时钟或替换观察策略。

模板见 `authorization-template.json`。模板保持 `status: pending`，不能直接用于
发布。

## 本地调用

准备好一次真实变更及其授权文件后：

```bash
python3 scripts/check_skill_release_authorization.py \
  --base <变更前完整提交> \
  --head HEAD \
  --mode dry-run
```

退出码：

- `0`：合同有效，且当前模式已获一次性授权。
- `1`：合同结构有效，但被观察期、fresh review、模式或时效阻断。
- `2`：合同、diff、版本、catalog、证据或内容摘要不一致。

输出字段 `authorized: true` 是未来 workflow 可以消费的仓内完整性条件，但
不是批准者身份凭据。

## 计划接入顺序

观察窗口结束并完成统一增长监控后：

1. fresh review 只选择一个最高优先级正式变更。
2. 生成与该 diff 绑定的 `.clawhub/skill-release-authorization.json`。
3. 在可复用发布 workflow 的首次 checkout 后执行 catalog 预检和本门禁。
4. 使用 GitHub protected environment 或等价的仓外审批绑定最终 head SHA；
   仓内 JSON 只证明变更完整性，不能单独证明批准者身份。
5. 从受信任 base 版本执行 checker，不能使用待发布提交修改后的门禁给自身放行。
6. 让 Bun、ClawHub 源码 checkout、dry-run 与 publish 全部依赖授权成功。
7. 增加 workflow 合同测试，证明授权失败时所有联网和发布步骤不可达。
8. 发布后按 E0-E4 验证；每个变化版本最多执行一次隔离安装。

在完成上述原子接入前，不能声称正式发布链路已经具备 fail-closed 授权能力。
即使接入后，仓内合同也不能提供真正的一次性消费记录；同一 head 的重复运行
需要由 GitHub environment/deployment 状态或等价仓外系统阻止。

# ClawHub Package 发布诊断

## 结论

- 状态（`conclusion`）：`blocked | partial | published-unverified`
- 失败层：`workflow-permission | source-resolution | pack | family-detection | inspector | upload | moderation | index | verification | unknown`
- 诊断代码（`diagnosis`）：
- 置信度：`high | low`

确定性映射：

- 前置失败：`blocked`
- `PACKAGE_RELEASE_SCAN_STALLED`：`partial`
- `PACKAGE_SECURITY_AUDIT_FIELDS_MISSING`：`published-unverified`
- `UNKNOWN`：`partial`，且必须给出一个最小补证项

## 观测上下文

已知诊断的 `observedContext` 只能列出该规则实际使用、且通过格式校验的
`clawhubVersion`、`npmVersion`、`workflowRef`、`family`、
`sourceValidatorCommit`、`sourceCommit`。`workflowRef` 必须剥离 owner
和 repository；`UNKNOWN` 必须为空。不得加入错误正文、token、仓库、
账号、URL、release ID、artifact hash、无效值或任意透传字段。

## 直接证据

| 证据 | 观察结果 | 支持或排除 |
|---|---|---|
| 命令或 workflow ref |  |  |
| CLI / Node / npm 版本 |  |  |
| family 与 manifest |  |  |
| artifact 大小与 hash |  |  |
| Inspector / 本地验证状态与 artifact hash |  |  |
| 错误与退出状态 |  |  |
| 多层信号的 `failureSequence` |  |  |
| publication / verify 状态 |  |  |

## 版本适用性

- 当前正式 release：
- 使用中的 workflow ref：
- 已知修复位置：
- 分类：`current-release | fixed-in-release | main-only-fix | current-server | fix-merged-deployment-unverified | product-decision | unknown`

## 最小修复

只列一个优先修复：

```text
<最小、可逆、不会绕过安全门的修改>
```

## 拒绝的捷径

逐项抄录 `rejectedShortcuts`：

- `<rejected shortcut>`

## 验证步骤

按顺序抄录该诊断代码的 `verificationSteps`，不要补写未执行的在线动作：

1. `<verification step>`

## 不得声称

逐项抄录 `doNotClaim`：

- `<unsupported claim>`

## 缺失证据 / 最小补证

- `missingEvidence`：
- 对 `UNKNOWN`，这里只能保留一个最小补证项，且必须与
  `verificationSteps[0]` 一致。

# Reusable workflow 缺少 `actions: read`

这个例子来自仓库真实的 GitHub Actions startup failure：

```text
https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33932029001
```

失败发生在任何 job 创建之前，不是 package 内容、Inspector、上传或 registry
故障。

## 输入

```text
surface: package
workflow: openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3
event: push
jobs created: 0
effective permissions:
  actions: none
  contents: read
  id-token: write
错误：The nested job 'publish' is requesting 'actions: read',
      but is only allowed 'actions: none'.
```

## 结论

```text
diagnosis: REUSABLE_WORKFLOW_ACTIONS_PERMISSION
conclusion: blocked
layer: workflow-permission
confidence: high
versionStatus: current-release
observedContext: {workflowRef: package-publish.yml@v0.23.3}
```

直接证据同时满足：

- workflow 在 job 创建前被 GitHub 拒绝。
- 被调用的固定版本 workflow 明确请求 `actions: read`。
- 调用方 effective permissions 明确为 `actions: none`。

因此不能把它描述成 package 发布失败；package 发布逻辑尚未开始执行。

## 最小修复

在调用方 workflow 顶层只增加缺失权限：

```yaml
permissions:
  actions: read
  contents: read
  id-token: write
```

不要扩大为 `actions: write`，也不要绕过官方 reusable workflow。

## 验证步骤

1. 提交仅增加 `actions: read` 的权限修复。
2. 确认 reusable workflow 能创建 discover、dry-run 或 publish jobs。
3. 再按后续层分别核验 publish、publication state 与 `package verify`。

job 能创建只证明 workflow 权限阻塞已解除，不证明 package 已发布、可见或
通过 artifact verification。

## 反例

以下情况必须保持 `UNKNOWN` 或转入其他失败层：

- effective permissions 未被完整观测。
- `actions` 已是 `read` 或更高权限。
- job 已创建，实际失败发生在 pack、Inspector、upload 或 verification。
- 错误没有明确指出 nested job 请求 `actions: read`。

## 证据边界

- 本例不重放失败 workflow，不发布 package，也不访问 registry。
- 诊断来源只证明指定 run 的权限故障，不代表所有 package workflow 都需要
  相同修复。
- 权限修复后的成功运行仍需独立核验，不能从本次失败记录推断。

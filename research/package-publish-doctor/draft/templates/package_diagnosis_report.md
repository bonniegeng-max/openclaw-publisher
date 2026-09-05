# ClawHub Package 发布诊断

## 结论

- 状态：`blocked | partial | published-unverified | verified`
- 失败层：`workflow-permission | source-resolution | pack | family-detection | inspector | upload | moderation | index | verification | unknown`
- 诊断代码：
- 置信度：`high | medium | low`

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

- 不执行：
- 原因：

## 验证步骤

1. 本地结构与 manifest：
2. `package validate`：
3. `package publish --dry-run`：
4. 经明确授权后的真实 publish：
5. definitive publication state：
6. `package verify`：
7. artifact hash：

## 缺失证据

- 尚缺：
- 未确认前不得声称：

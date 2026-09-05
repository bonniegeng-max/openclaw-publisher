# Package 发布故障映射

先确认版本和证据，再套用规则。相同错误文本在不同版本、family 或上传路径中可能有不同根因。规则适用版本、修复版本和已确认源码事实由规则内置；CLI、npm、workflow、family 和 source-validator commit 必须作为观测输入提供，调用方填写的 `affected` 元数据不参与命中。

当前高置信规则覆盖 `workflow-permission`、`source-resolution`、`pack`、`family-detection`、`upload`、`moderation` 和 `verification`。`inspector` 与 `index` 仅用于失败层分类；在补齐真实来源、正例与负例之前，不得输出对应的高置信诊断代码。

## 高置信度规则

### `REUSABLE_WORKFLOW_ACTIONS_PERMISSION`

必须同时满足：

- GitHub 在创建 job 前拒绝 workflow
- 错误明确包含 nested job 请求 `actions: read`
- 调用方顶层没有 `actions: read`

最小修复：

```yaml
permissions:
  actions: read
  contents: read
  id-token: write
```

不要授予 `actions: write`。修复后确认 discover job 能创建；如果没有变更目标，publish job 正常跳过不算失败。

### `TRUSTED_PUBLISH_TAG_REF_REGRESSION`

必须同时满足：

- 证据来自 package trusted publishing
- ordinary token 不含 `candidateSha`
- `source.commit` 等于 token SHA
- `source.ref` 等于 token 中已验证的 tag ref
- tag ref 与 commit SHA 字符串不同，服务端仍直接比较两者并拒绝
- 输入包含 source-validator commit `845c6d3bdb1a36573d8d28be2a8fb85a3c476720`
- 该 commit 的源码比较证据明确为 `source.ref !== (candidateSha ?? token.sha)`

当前分类：`source-reproduced-at-commit`。这只证明回归可在指定源码 commit 重现，不推断当前部署。

最小修复：保留 ordinary token 的 tag ref 与 commit 语义，等待受安全审查的服务端修复。不要把 ordinary 模式伪装成 split-candidate，也不要放宽 candidate provenance。

### `NPM_PACK_JSON_SHAPE`

必须同时满足：

- `npm pack` 已生成 tarball
- 输入的 ClawHub CLI 为 `0.23.1`
- 输入的 npm 为 12.x
- CLI 报 `npm pack did not return a tarball filename`
- npm JSON 输出为包名到结果对象的映射，而不是旧数组
- npm 11 数组与 npm 12 对象各自恰有一条结果
- 两条结果都包含非空 `filename`，且值完全相同

最小修复：

- 优先升级到已确认兼容 npm 12 的正式 ClawHub CLI。
- 如果正式版本尚未确认，只在发布 job 内临时固定 npm 11。

空输出、缺失/空白 `filename`、错误 entry 类型、多条结果或两侧
`filename` 不一致都必须保持 `UNKNOWN`。不要声称 npm 没有生成
tarball，也不要全局降级开发机的 npm。

### `BUNDLE_NATIVE_MANIFEST_CONTRACT`

必须同时满足：

- family 为 `bundle-plugin`
- 输入的 ClawHub CLI 为 `0.23.3`
- 至少存在一个兼容 bundle marker
- 根目录不存在 `openclaw.plugin.json`
- CLI 报 `openclaw.plugin.json required`

当前分类：`product-decision`。

不要创建虚假的 native manifest。该 workaround 可能改变 family 检测优先级、运行时含义和安全边界。

### `CLAWPACK_STAGING_GAP`

必须同时满足：

- 输入的 workflow ref 为 `openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3`
- 预构建 ClawPack 超过公共边缘预算
- artifact 仍低于旧 staging 阈值
- 公共 registry 返回 `413 Request Entity Too Large`
- 同一 artifact 的 Inspector 或本地验证明确成功
- 成功验证记录中的 artifact hash 与上传失败 artifact 的 hash 完全一致

当前版本事实：

- `v0.23.3` 是 `2026-09-05` 查询到的最新正式 release。
- 修复已经进入后续 `main`，但 `v0.23.3` 不包含。

最小修复：等待并升级到包含 staging 修复的正式 release。不要把未发布 `main` 当作长期生产依赖。

### `PACKAGE_RELEASE_SCAN_STALLED`

必须同时满足：

- 证据明确来自 `package` surface，而不是普通 Skill 发布
- family 为 `bundle-plugin`
- `clawhub@0.23.1` publish 已返回 release ID
- package scan 持续 pending 至少 24 小时
- `latestRelease` 为空，指定版本无法 inspect
- 同版本重新发布被 duplicate guard 拒绝

当前分类：`fixed-in-release`，修复随 `v0.23.2` 发布。

最小修复：升级到包含修复的正式 CLI，再核验原 release 的 scan、latest 与 inspect 状态。不要连续 bump 版本；这只会保留更多不可见 release。

### `PACKAGE_SECURITY_AUDIT_FIELDS_MISSING`

必须同时满足：

- 证据来自精确版本的 code-plugin security endpoint
- trust verdict 为 clean，且 `blockedFromDownload`、`pending`、`stale` 均为 false
- reasons 为空
- `overview` 与 `securityAuditUrl` 均应为非空字符串，其中至少一个缺失、空白或类型错误
- 安装器的 malformed-response 错误明确指向其中一个无效字段并要求非空字符串
- 对应修复已合并，但部署状态尚未独立验证

当前分类：`fix-merged-deployment-unverified`。

最小修复：保持 fail-closed。部署后先只读核验精确版本 endpoint 返回非空审计字段，再重试支持的安装流程；不要在客户端伪造审计文本或绕过信任策略。

## 冲突状态

### Publish 成功但 index 缺失

检查：

- publish 是否返回 `published`、版本和 release/version ID
- 指定版本是否能按文件或下载端点读取
- version list、latest 和 tags 是否仍指向旧版本
- moderation 是否已 clean

若内容存在但公开投影缺失，结论是 registry/index 一致性故障，不是客户端可通过重复发布或盲目 bump 修复的问题。

### `CLEAN` 但仍为 `pending.publication`

检查：

- moderation verdict 与 publication status 是否来自同一版本
- owner rescan 是否只更新分析结果，而未重放原 publication gate
- owner 是否有明确、版本级的恢复或申诉路径

结论应标记为需要维护者处理。不要把单独 CLEAN rescan 等同于完成原始发布安全门。

## UNKNOWN 条件

以下情况保持 `UNKNOWN`：

- 只有错误关键词，没有版本、命令或上下文
- 普通 413，但 artifact 没有落在已知阈值区间
- `code-plugin` 缺少 native manifest
- tarball 实际不存在
- 调用方已经授予 `actions: read`
- package scan 卡住案例使用 `v0.23.2+`，或 pending 未满 24 小时
- trusted publisher 使用 split-candidate 模式，或 source commit/ref 本身与 token 不一致
- trusted publisher 只有 `rejected: true`，缺少指定 source-validator commit 或精确源码比较证据
- package trust 状态为 blocked、pending 或 stale
- security endpoint 已返回非空 overview 与 audit URL
- 输入未明确标记 `surface: package`
- `CLAWPACK_STAGING_GAP` 缺少 Inspector/本地验证成功记录、验证失败，或验证 hash 与上传 artifact 不同
- source、Inspector、moderation 和 upload 多层同时匹配，但没有覆盖全部匹配层的 `failureSequence` 时间顺序

输出最小缺失证据，不要推荐多个互相冲突的修复。

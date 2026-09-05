# Package 发布故障映射

先确认版本和证据，再套用规则。相同错误文本在不同版本、family 或上传路径中可能有不同根因。

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

### `NPM_PACK_JSON_SHAPE`

必须同时满足：

- `npm pack` 已生成 tarball
- npm 为 12.x
- CLI 报 `npm pack did not return a tarball filename`
- npm JSON 输出为包名到结果对象的映射，而不是旧数组

最小修复：

- 优先升级到已确认兼容 npm 12 的正式 ClawHub CLI。
- 如果正式版本尚未确认，只在发布 job 内临时固定 npm 11。

不要声称 npm 没有生成 tarball，也不要全局降级开发机的 npm。

### `BUNDLE_NATIVE_MANIFEST_CONTRACT`

必须同时满足：

- family 为 `bundle-plugin`
- 至少存在一个兼容 bundle marker
- 根目录不存在 `openclaw.plugin.json`
- CLI 报 `openclaw.plugin.json required`

当前分类：`product-decision`。

不要创建虚假的 native manifest。该 workaround 可能改变 family 检测优先级、运行时含义和安全边界。

### `CLAWPACK_STAGING_GAP`

必须同时满足：

- 使用不包含修复的正式 CLI 或 `package-publish.yml` ref
- 预构建 ClawPack 超过公共边缘预算
- artifact 仍低于旧 staging 阈值
- 公共 registry 返回 `413 Request Entity Too Large`
- 同一 artifact 的 Inspector 或本地验证没有证明内容本身无效

当前版本事实：

- `v0.23.3` 是 `2026-09-05` 查询到的最新正式 release。
- 修复已经进入后续 `main`，但 `v0.23.3` 不包含。

最小修复：等待并升级到包含 staging 修复的正式 release。不要把未发布 `main` 当作长期生产依赖。

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
- source、Inspector、moderation 和 upload 多层同时失败，无法确认首个失败点

输出最小缺失证据，不要推荐多个互相冲突的修复。

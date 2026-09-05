# 三类相似失败，不同修复

这些例子说明为什么不能只看最后一行错误。

## 例一：tarball 存在

输入：

```text
clawhub 0.23.1
npm 12.x
错误：npm pack did not return a tarball filename
输出目录中存在 my-plugin-0.4.0.tgz
```

结论：

```text
diagnosis: NPM_PACK_JSON_SHAPE
layer: pack
confidence: high
```

理由：打包动作成功，失败发生在旧 CLI 对 npm 12 JSON 对象结构的解析。不能把它报告成“npm 没有生成 tarball”。

最小修复：使用已确认兼容的正式 CLI；如果尚无正式修复版本，只在发布 job 内临时固定 npm 11。

## 例二：bundle marker 存在

输入：

```text
family: bundle-plugin
.codex-plugin/plugin.json: present
.claude-plugin/plugin.json: present
openclaw.plugin.json: absent
错误：openclaw.plugin.json required
```

结论：

```text
diagnosis: BUNDLE_NATIVE_MANIFEST_CONTRACT
layer: family-detection
confidence: high
versionStatus: product-decision
```

理由：CLI 已识别兼容 bundle marker，但发布合约仍要求 native manifest。不能伪造 `openclaw.plugin.json`，因为这可能改变 family 和运行时语义。

最小修复：等待维护者明确 pure compatible bundle 的支持合约。

## 例三：Inspector 成功但上传 413

输入：

```text
workflow: package-publish.yml@v0.23.3
artifact: 8,032,797 bytes
public edge budget: 4,194,304 bytes
legacy staging threshold: 18,874,368 bytes
Inspector: success
upload: 413 Request Entity Too Large
```

结论：

```text
diagnosis: CLAWPACK_STAGING_GAP
layer: upload
confidence: high
versionStatus: main-only-fix
```

理由：artifact 超过公共边缘预算，但低于旧 staging 阈值，因此旧版会错误地走直接 multipart 上传。内容验证成功并不能证明传输路径可用。

最小修复：等待并升级到包含修复的正式 release；不要把未发布 `main` 当生产依赖。

## 反例：只有 413

输入：

```text
错误：413 Request Entity Too Large
artifact size: unknown
workflow ref: unknown
```

结论：

```text
diagnosis: UNKNOWN
confidence: low
```

还需要 artifact 字节数、registry URL 和 workflow/CLI 版本。此时不能直接建议升级、压缩或改 registry。

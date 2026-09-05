# Source 与 verification 故障

这两个案例都发生在 package/plugin 链路，但一个阻断可信来源校验，另一个阻断发布后的安全验证，不能使用同一 workaround。
以下结论块是完整 canonical CLI JSON 报告的可读摘录。

## Ordinary tag ref 被拒绝

输入：

```text
surface: package
publish mode: trusted-github-actions
candidateSha: absent
source-validator commit: 845c6d3bdb1a36573d8d28be2a8fb85a3c476720
source comparison: source.ref !== (candidateSha ?? token.sha)
token sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
token ref: refs/tags/v1.2.3
source commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
source ref: refs/tags/v1.2.3
result: rejected
rejection stage: source-validation
source validation outcome: source-ref-mismatch
```

结论：

```text
diagnosis: TRUSTED_PUBLISH_TAG_REF_REGRESSION
conclusion: blocked
layer: source-resolution
confidence: high
versionStatus: source-reproduced-at-commit
observedContext: {sourceValidatorCommit: 845c6d3bdb1a36573d8d28be2a8fb85a3c476720, sourceCommit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}
```

ordinary token 的 commit 与 tag ref 都与已验证 token 一致，且指定 source-validator commit 的源码明确把 `source.ref` 与 `candidateSha ?? token.sha` 比较。ordinary 模式没有 candidate SHA，因此有效 tag ref 被错误地与 token SHA 比较。这个证据只证明回归可在该 commit 重现，不证明它当前已部署。修复必须保留 ordinary 与 split-candidate 两种模式的不同 provenance 约束。

拒绝的捷径：

- 不把 tag ref 随意替换成 SHA 来掩盖服务端回归
- 不让 split-candidate 接受 ordinary token ref
- 不关闭 trusted publishing 校验

## Clean package 缺少审计字段

输入：

```text
surface: package
stage: install-verification
family: code-plugin
release version: 2.1.4
security release version: 2.1.4
publication status: published
trust.scanStatus: clean
trust.blockedFromDownload: false
trust.pending: false
trust.stale: false
overview: null
securityAuditUrl: null
installer: malformed response, expected non-empty overview
```

结论：

```text
diagnosis: PACKAGE_SECURITY_AUDIT_FIELDS_MISSING
conclusion: published-unverified
layer: verification
confidence: high
versionStatus: fix-merged-deployment-unverified
observedContext: {family: code-plugin}
```

release 的 trust verdict 是 clean，但公开响应缺少安装器要求的审计字段。修复 PR 已合并不等于部署完成，因此应先核验精确版本 endpoint，再重试安装。

拒绝的捷径：

- 不在客户端伪造 overview 或 audit URL
- 不因为 release clean 就绕过 fail-closed
- 不把 `--force` 解释为可以跳过信任检查

## 共同反例

以下情况保持 `UNKNOWN`：

- 输入来自普通 Skill 发布
- source commit 或 ref 本身与 token 不一致
- token 使用 split-candidate 模式
- 只有发布被拒绝，没有指定 commit 的源码比较证据
- trust 为 blocked、pending 或 stale
- security endpoint 已返回完整审计字段

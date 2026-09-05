# Source 与 verification 故障

这两个案例都发生在 package/plugin 链路，但一个阻断可信来源校验，另一个阻断发布后的安全验证，不能使用同一 workaround。

## Ordinary tag ref 被拒绝

输入：

```text
surface: package
publish mode: trusted-github-actions
candidateSha: absent
token sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
token ref: refs/tags/v1.2.3
source commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
source ref: refs/tags/v1.2.3
result: rejected
```

结论：

```text
diagnosis: TRUSTED_PUBLISH_TAG_REF_REGRESSION
layer: source-resolution
confidence: high
versionStatus: current-server
```

ordinary token 的 commit 与 tag ref 都与已验证 token 一致，服务端却把 tag ref 与 commit SHA 比较。修复必须保留 ordinary 与 split-candidate 两种模式的不同 provenance 约束。

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
layer: verification
confidence: high
versionStatus: fix-merged-deployment-unverified
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
- trust 为 blocked、pending 或 stale
- security endpoint 已返回完整审计字段

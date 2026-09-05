# ClawHub Package Publish Doctor 研究包

状态：`draft-ready`（隔离研究包，未发布）
更新时间：`2026-09-05`

这里保存 `package-publish-doctor` 的发布前研究证据和离线 fixture。它不是可发布 Skill，不在 `.clawhub/skill-catalog.json` 中，也不会触发 ClawHub Skill 发布。

## 产品边界

目标任务是诊断 ClawHub package/plugin artifact 的发布链路：

```text
source
  → package validate
  → npm pack / ClawPack
  → family 与 manifest 判定
  → Plugin Inspector
  → upload
  → publication wait
  → package verify
  → artifact hash
```

不处理：

- 普通 Skill 的内容质量与差异化
- Skill catalog metadata 批量治理
- GitHub Actions → Skill 发布的常规故障
- 绕过 Inspector、moderation 或可信发布边界

## 版本故障矩阵

| Case | 受影响证据 | 当前状态 | 诊断信号 | 安全建议 |
|---|---|---|---|---|
| `npm-pack-json-shape` | `clawhub@0.23.1` + npm 12 | Issue 已关闭，修复落在哪个正式 release 尚未确认 | tarball 已生成，但 CLI 报 `npm pack did not return a tarball filename` | 判断 stdout 是数组还是对象；必要时在 job 内临时固定 npm 11 |
| `bundle-native-manifest-contract` | `clawhub@0.23.3`，且 issue 声明 current main 仍可复现 | 等待产品与安全决策 | 检测到兼容 bundle markers，但缺少根目录 `openclaw.plugin.json` | 不伪造 native manifest；明确这是合约阻塞，不是目录缺失 |
| `clawpack-staging-gap` | `package-publish.yml@v0.23.3` / 对应 CLI | main 已修复，最新 release `v0.23.3` 尚未包含 | 同 hash artifact 已通过 Inspector 或本地验证，大小大于约 4 MiB、低于旧 18 MiB 阈值，通过公共边缘上传返回 413 | 优先升级到包含修复的正式版本；发布前不要依赖未发布的 main |
| `reusable-workflow-actions-read` | 调用官方 `package-publish.yml@v0.23.3` | 本仓库已修复 | workflow 在创建 job 前报 nested job 请求 `actions: read` | 调用方显式授予 `actions: read`，保留最小权限 |
| `package-release-scan-stalled` | `clawhub@0.23.1` bundle package | 已在 `v0.23.2` 修复 | publish 返回 release ID，但扫描超过 24 小时仍 pending、latest 为空、inspect 不可见且同版本已被保留 | 升级正式 CLI 后核验原 release；不连续 bump 制造更多孤立版本 |
| `trusted-publish-tag-ref-regression` | ordinary GitHub Actions trusted publisher，source-validator commit `845c6d3bdb1a36573d8d28be2a8fb85a3c476720` | `source-reproduced-at-commit`，不据此推断当前部署 | token 的 tag ref 与 source ref 一致，且该 commit 的源码明确比较 `source.ref !== (candidateSha ?? token.sha)` | 保留 tag 与 commit 语义，等待安全审查后的服务端修复 |
| `package-security-audit-fields-missing` | exact code-plugin release security endpoint | 修复 PR `#3550` 已合并，部署状态未独立验证 | trust 为 clean，但 `overview` / `securityAuditUrl` 至少一个不是非空字符串，安装器按 fail-closed 拒绝 | 不伪造审计文本、不绕过信任检查；部署后核验精确版本 endpoint |

九层失败模型用于定位证据边界；当前离线诊断器只有
`workflow-permission`、`source-resolution`、`pack`、`family-detection`、
`upload`、`moderation` 和 `verification` 七层具备真实案例支持的高置信规则。
`inspector` 与 `index` 目前仅用于分类，没有独立正例和负例前必须返回
`UNKNOWN`，不得把框架覆盖误写成可执行规则覆盖。

## 证据来源

- [npm 12 pack 输出结构变化](https://github.com/openclaw/clawhub/issues/3275)
- [bundle-plugin 与 native manifest 合约冲突](https://github.com/openclaw/clawhub/issues/3513)
- [ClawPack 公共边缘 413](https://github.com/openclaw/clawhub/issues/3577)
- [bundle package release 扫描卡住](https://github.com/openclaw/clawhub/issues/3288)
- [trusted publisher tag ref 校验回归](https://github.com/openclaw/clawhub/issues/3507)
- [package security endpoint 缺少审计字段](https://github.com/openclaw/clawhub/issues/3546)
- [官方 Package Publish workflow v0.23.3](https://github.com/openclaw/clawhub/blob/v0.23.3/.github/workflows/package-publish.yml)
- [ClawHub 最新 release v0.23.3](https://github.com/openclaw/clawhub/releases/tag/v0.23.3)
- [本仓库权限修复后的成功运行](https://github.com/bonniegeng-max/openclaw-publisher/actions/runs/33932342586)

## 离线 fixture

`fixtures/` 中的 JSON 只保存判定所需的最小输入，不访问 registry、不执行安装、不生成大型二进制。每个 fixture 必须显式声明 `surface: package`，并把实际 CLI、npm、workflow ref、family 或 source-validator commit 放入 `input`，防止把普通 Skill 发布故障或调用方自报的 `affected` 元数据套进 Package 规则：

- `npm-pack-json-shape.json`：同一 tarball 在 npm 11/12 下的输出形状差异
- `bundle-native-manifest-contract.json`：兼容 bundle markers 存在但 native manifest 缺失
- `clawpack-staging-gap.json`：真实案例中的 artifact hash、Inspector 成功证据、大小与两个上传阈值
- `reusable-workflow-actions-read.json`：调用方权限不足导致 workflow 启动失败
- `package-release-scan-stalled.json`：旧版 bundle package release 被保留但扫描与公开投影长期未完成
- `trusted-publish-tag-ref-regression.json`：普通 trusted publisher 的 tag ref 被 commit `845c6d3bdb1a36573d8d28be2a8fb85a3c476720` 中的源码错误地与 commit SHA 比较
- `package-security-audit-fields-missing.json`：clean package release 因审计字段缺失而无法通过安装信任检查

这些 fixture 的目标不是模拟 ClawHub 服务端，而是固定诊断器必须识别的观测证据边界。规则适用版本、修复版本和固定源码事实内置在 `draft/scripts/diagnose.py`，`case.affected` 不参与命中。fixture 集合可以扩展，测试只要求基线案例继续存在、ID 唯一，不限制总数。诊断器会先收集全部匹配信号，再输出结构化诊断；若不同失败层同时匹配且 `input.failureSequence` 未给出覆盖所有匹配层的时间顺序，则返回 `UNKNOWN`。每个 fixture 还固定预期 `conclusion`：前置失败为 `blocked`，scan stalled 为 `partial`，security audit 字段缺失为 `published-unverified`。`tests/test_package_publish_doctor_research.py` 会验证完整输出 schema、确定性结论、严格的 `observedContext` allowlist、`UNKNOWN` 最小补证以及避免误判的负例。

本地运行：

```bash
python3 research/package-publish-doctor/draft/scripts/diagnose.py \
  research/package-publish-doctor/fixtures/clawpack-staging-gap.json
```

`draft/scripts/diagnose.py` 是唯一诊断实现；根目录 `diagnose.py` 仅为旧命令和导入路径提供兼容转发。输入/输出与脱敏要求见 `draft/references/input-contract.md`，可运行匿名输入见 `draft/examples/anonymous-input.json`。

输出包含诊断层、确定性 `conclusion`、证据、建议、`rejectedShortcuts`、`verificationSteps`、`doNotClaim`、来源和严格脱敏的 `observedContext`，不执行网络请求或修复动作。已知诊断只输出该规则实际使用且通过格式校验的 CLI/npm 版本、规范化 workflow ref、family 和 source commit；workflow owner/repository 会被移除，`UNKNOWN` 的 `observedContext` 恒为空，不透传错误、token、URL、release ID 或 artifact hash。无法满足完整判定条件时必须返回同结构的 `UNKNOWN`，其 `conclusion` 为 `partial`，并只指出一个最小补证，不能根据单个错误关键词猜测根因。`CLAWPACK_STAGING_GAP` 还要求 Inspector 或本地验证成功，且验证记录中的 artifact hash 必须与上传失败的 artifact hash 相同；验证失败、缺失或 hash 不同都不能高置信命中。`TRUSTED_PUBLISH_TAG_REF_REGRESSION` 必须同时拿到指定 source-validator commit 与 `source.ref !== (candidateSha ?? token.sha)` 的源码比较证据；只有 `rejected: true` 必须保持 `UNKNOWN`。`PACKAGE_SECURITY_AUDIT_FIELDS_MISSING` 把 `overview` 与 `securityAuditUrl` 都视为必需的非空字符串，并要求错误正文明确指向实际无效字段。

## 草案包

`draft/` 已按正式 Skill 的结构准备：

- `SKILL.md`
- `CHANGELOG.md`
- `.clawhubignore`
- `references/failure-map.md`
- `references/input-contract.md`
- `scripts/diagnose.py`
- `templates/package_diagnosis_report.md`
- `examples/anonymous-input.json`
- `examples/three_layer_diagnosis.md`
- `examples/package_release_scan_stalled.md`
- `examples/source_and_verification_failures.md`

草案不在 `skills/` 目录，也没有 catalog 条目，因此不会被发布 workflow 发现。GitHub 侧同类产品预筛见 `competitor-screen.md`；该预筛不能替代正式发布前的 ClawHub 站内检索。

## 启动门槛

只有同时满足以下条件，才把研究包升级为正式 Skill：

1. 当前 7 天自然增长观察窗口结束。
2. 重新确认最新 ClawHub release 与官方 workflow ref。
3. 完成一次同口径竞品搜索，确认没有直接同任务产品。
4. 保留全部基线离线 fixture，并为新增规则同时提供正例和负例；fixture 总数不设固定上限。
5. 输出必须区分“已修复但未发布”“当前仍可复现”“需要维护者决策”。
6. 本地测试与 ClawHub dry-run 通过后，才允许加入 catalog 和发布。

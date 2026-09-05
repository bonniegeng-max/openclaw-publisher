# Changelog

## 0.1.2 - 2026-09-05

- 增加 ordinary trusted publisher tag ref 的 source-validation 回归诊断。
- 增加 clean code-plugin security response 缺少审计字段的 verification 诊断。
- 区分 `current-server` 与 `fix-merged-deployment-unverified`，不把合并状态误写成线上恢复。
- 增加 candidate provenance、trust fail-closed 和完整审计响应反例。

## 0.1.1 - 2026-09-05

- 为所有离线规则增加显式 `surface: package` 边界，拒绝套用普通 Skill 发布故障。
- 增加 `PACKAGE_RELEASE_SCAN_STALLED`，覆盖 `clawhub@0.23.1` bundle release 长时间 pending 且不可见的历史故障。
- 将该规则限定在修复版本 `v0.23.2` 之前，并增加当前版本、短等待时间和 Skill surface 反例。
- 为诊断输出补齐 `versionStatus` 与 `missingEvidence`。

## 0.1.0 - 2026-09-05

- 建立 Package 发布的九层故障分类。
- 纳入 workflow 权限、npm 12 pack 输出、bundle manifest 合约和 ClawPack staging gap。
- 增加版本适用性标签，区分正式 release、main-only fix 和产品决策。
- 明确不绕过 Inspector、不伪造 manifest、不盲目 bump 版本等安全边界。
- 增加结构化诊断报告模板和三类真实失败示例。

此版本仅为研究草案，未加入 catalog，未发布到 ClawHub。

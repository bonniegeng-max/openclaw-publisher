# Changelog

## 0.1.4 - 2026-09-05

- 将规则适用 CLI、npm、workflow、修复版本与固定源码事实内置到离线诊断器，不再使用 `case.affected` 决定命中。
- fixtures 将实际 CLI、npm、workflow ref、family 与 source-validator commit 迁入 `input`。
- 收紧 trusted publisher 规则：必须提供 commit `845c6d3bdb1a36573d8d28be2a8fb85a3c476720` 的 `source.ref !== (candidateSha ?? token.sha)` 源码比较证据；只有 `rejected: true` 返回 `UNKNOWN`。
- 将该规则的 `versionStatus` 改为 `source-reproduced-at-commit`，避免把源码重现误写成当前部署事实。
- 增加版本边界、错误 workflow ref、缺失/错误源码比较证据和 `affected` 污染的负例测试。

## 0.1.3 - 2026-09-05

- 诊断器改为先收集全部匹配信号；不同失败层冲突且缺少完整 `failureSequence` 时返回 `UNKNOWN`。
- 收紧 `CLAWPACK_STAGING_GAP`：只有 Inspector 或本地验证成功且 artifact hash 相同才高置信命中。
- 增加验证缺失、验证失败、hash 不同以及多层冲突的反例测试。
- fixture 测试改为校验可扩展基线，不再固定总数为 7。
- 明确九层调查框架中只有七层具备可执行高置信规则；`inspector` 与 `index` 暂为分类层。
- 将研究目录加入 Metrics Tools CI 的路径触发范围。

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

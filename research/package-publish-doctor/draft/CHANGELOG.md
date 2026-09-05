# Changelog

## 0.1.15 - 2026-09-05

- 增加真实 GitHub Actions startup failure 的完整权限诊断示例。
- 明确 `actions: none` 阻塞发生在 job 创建前，不能误报为 package 发布失败。
- 将 Markdown 示例同步门禁扩展到全部七条高置信诊断规则。

## 0.1.14 - 2026-09-05

- 修正 bundle manifest 示例遗漏 `clawhubVersion` 的输出漂移。
- 增加由真实 fixtures 和 canonical 诊断器反向校验三个 Markdown 示例的合同测试。
- 对示例中的 diagnosis、conclusion、layer、confidence、versionStatus 和完整 `observedContext` 建立同步门禁。

## 0.1.13 - 2026-09-05

- 删除与离线诊断任务无关的 macOS 限制、Git/ClawHub 二进制要求和 ClawHub CLI 安装声明。
- 只保留 bundled `scripts/diagnose.py` 实际执行所需的 `python3` 资格条件，避免在 Linux 或仅分析现有日志时被错误过滤。
- 以仓库 `ubuntu-latest` CI 的 Python 3.11 编译与全量离线测试作为 Linux 可运行证据。
- 增加 frontmatter 运行资格回归测试，防止草案重新引入与任务不符的依赖。

## 0.1.12 - 2026-09-05

- 将必要证据目录升级为可声明多个完整字段结构的 variant 合同。
- 为 `CLAWPACK_STAGING_GAP` 分别建模 Inspector 与本地验证两条合法证据路径，不再把 Inspector 误写为唯一必需来源。
- 缺字段提示按“诊断代码 + 证据变体”消歧；同一规则的替代路径不会互相制造假歧义。
- 增加本地验证分支缺少错误文本或 artifact hash 时的精确补证测试。

## 0.1.11 - 2026-09-05

- 将输出中的 `source` 从调用者自担脱敏改为 fail-closed 安全归一化。
- 只保留固定脱敏标签、ClawHub 官方公开 issue 和本仓库公开 Actions run 的规范 HTTPS 引用。
- 带 userinfo、query、fragment、非 HTTPS、私有或未知 host/repository、任意文本和非法 Unicode 的来源统一输出为 `null`。
- 增加安全来源保留与潜在秘密来源拒绝测试，诊断匹配逻辑保持不变。

## 0.1.10 - 2026-09-05

- 为七条高置信规则增加运行时必要字段目录，使规则实现与 mutation 合同共享同一组可审计证据路径。
- 当且仅当一个已知规则只缺少一个声明字段时，`UNKNOWN.missingEvidence` 返回该字段的精确 `input` 路径。
- 多个规则同时只差一项时继续返回通用补证请求，不猜测候选根因。
- 字段存在但值无效或相互矛盾时不误报为“缺失”，仍保持保守 `UNKNOWN`。

## 0.1.9 - 2026-09-05

- 为七条高置信规则增加声明式 required-evidence deletion matrix，任一必要证据缺失都必须返回 `UNKNOWN`。
- 将 ClawPack 4 MiB/18 MiB 阈值内置，要求 `clawhub.ai` 公共上传目标和标准 `sha256:` digest，不再信任调用方自报阈值。
- trusted source 规则要求 source-validation 阶段、tag ref 与 `source-ref-mismatch` 源码复现结果；普通拒绝不得命中。
- workflow 权限规则改用规范化 effective permissions，不再从部分 YAML map 推断。
- npm 规则绑定 package command、两侧 package ID/filename 和实际 artifact filename，并记录 `v0.23.3` 已修复。
- bundle 规则要求完整文件观测且 manifest 布尔值与清单一致。
- scan stalled 精确限定已证实的 `0.23.1`，并区分显式 `latestRelease: null` 与字段缺失。
- security audit 规则要求同一已发布 release，并使用字段名边界匹配错误文本。
- 版本解析只允许零个或一个 `v` 前缀，拒绝 `vv...` 与冗余前导零等非规范值。

## 0.1.8 - 2026-09-05

- 为不可读文件、无效 UTF-8/JSON、非对象顶层、缺失或非对象 `input` 增加稳定的 `INPUT_CONTRACT_ERROR` stderr JSON 与退出码 `2`。
- 保持证据不足为退出码 `0` 的完整 `UNKNOWN` 结果，区分调用错误和诊断不确定性。
- 畸形规则字段、嵌套对象、布尔型数值和数字型版本不再触发 traceback 或误命中，而是安全降级为 `UNKNOWN`。
- 严格拒绝非标准 JSON `NaN`/infinity，并过滤无法 UTF-8 编码的 `id`/`source`，避免序列化 traceback。
- `callerPermissions.actions` 只有缺失或规范字符串 `none` 才能作为权限不足证据，falsy 畸形值不得命中。
- 收紧 `NPM_PACK_JSON_SHAPE`：npm 11/12 两侧必须各有一条非空且相同的 tarball `filename`。
- 兼容导入入口同步导出 `InputContractError`。
- 增加空对象、缺失/空白 filename、错误 entry 类型、多条结果、名称不一致、畸形嵌套字段、无效编码和 wrapper 错误等价性测试。

## 0.1.7 - 2026-09-05

- 为每个诊断代码增加确定性的 `conclusion`、`rejectedShortcuts`、`verificationSteps` 和 `doNotClaim`。
- 固定结论映射：前置失败为 `blocked`，scan stalled 为 `partial`，security audit 字段缺失为 `published-unverified`。
- 让 `UNKNOWN` 返回同一完整结构，并只指出一个与首个验证步骤完全一致的最小补证项。
- 增加按诊断收窄且规范化值的 `observedContext`；workflow ref 会移除 owner/repository，npm 版本只保留 major，`UNKNOWN` 恒为空。
- 非字符串 `id` 与 `source` 统一输出为 `null`，固定完整 schema 的字段类型。
- 更新输入契约、报告模板、Skill、研究 README、fixtures 和测试，覆盖完整输出 schema。

## 0.1.6 - 2026-09-05

- 将唯一诊断实现迁入 `scripts/diagnose.py`，根研究脚本仅保留兼容转发。
- 新增离线输入/输出契约和可直接运行的匿名 JSON 示例。
- 明确 CLI 命令、`UNKNOWN` 退出语义、脱敏要求和无网络、无发布、无修复副作用边界。
- 增加 canonical CLI 独立运行、资源存在及兼容 wrapper 一致性测试。

## 0.1.5 - 2026-09-05

- 将 `overview` 与 `securityAuditUrl` 统一校验为必需的非空字符串。
- 任一字段缺失、空白或类型错误，且 fail-closed 错误明确指向该字段时，均可匹配 security audit 响应故障。
- 增加单字段失败矩阵、错误文本不匹配、非空 reasons 与非精确版本 endpoint 的负例。

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

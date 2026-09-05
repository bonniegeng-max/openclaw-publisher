#!/usr/bin/env python3
"""Offline, deterministic diagnosis for normalized Package Doctor JSON input."""

import argparse
import json
import math
import re
import sys
from pathlib import Path


BUNDLE_MARKERS = {
    ".codex-plugin/plugin.json",
    ".claude-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
}
TRUSTED_SOURCE_VALIDATOR_COMMIT = "845c6d3bdb1a36573d8d28be2a8fb85a3c476720"
TRUSTED_SOURCE_COMPARISON = {
    "left": "source.ref",
    "operator": "!==",
    "right": "candidateSha ?? token.sha",
}
TRUSTED_SOURCE_VALIDATION_OUTCOME = "source-ref-mismatch"
TAG_REF_PATTERN = re.compile(r"^refs/tags/[^\s]+$")
NPM_PACK_JSON_SHAPE_CLI_VERSION = (0, 23, 1)
NPM_PACK_JSON_SHAPE_NPM_MAJOR = 12
NPM_PACK_COMMAND = "clawhub package publish"
NPM_PACK_JSON_SHAPE_FIXED_VERSION = (0, 23, 3)
BUNDLE_NATIVE_MANIFEST_CLI_VERSION = (0, 23, 3)
PACKAGE_PUBLISH_WORKFLOW_REF = (
    "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3"
)
CLAWPACK_UPLOAD_TARGET = "clawhub-public-edge"
CLAWPACK_PUBLIC_REGISTRY = "https://clawhub.ai"
PUBLIC_EDGE_BUDGET_BYTES = 4 * 1024 * 1024
LEGACY_STAGING_THRESHOLD_BYTES = 18 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
VERSION_NUMBER_PATTERN = r"(?:0|[1-9]\d*)"
PACKAGE_RELEASE_SCAN_AFFECTED_VERSION = (0, 23, 1)
PACKAGE_RELEASE_SCAN_FIXED_VERSION = (0, 23, 2)
PACKAGE_SECURITY_PUBLICATION_STATUS = "published"
FAILURE_LAYERS = frozenset(
    {
        "workflow-permission",
        "source-resolution",
        "pack",
        "family-detection",
        "inspector",
        "upload",
        "moderation",
        "index",
        "verification",
    }
)
EXECUTABLE_RULE_LAYERS = FAILURE_LAYERS - {"inspector", "index"}
CLASSIFICATION_ONLY_LAYERS = FAILURE_LAYERS - EXECUTABLE_RULE_LAYERS
OBSERVED_CONTEXT_FIELDS = (
    "clawhubVersion",
    "npmVersion",
    "workflowRef",
    "family",
    "sourceValidatorCommit",
    "sourceCommit",
)
OBSERVED_FAMILIES = frozenset(
    {"skill", "plugin", "code-plugin", "bundle-plugin"}
)
COMMIT_CONTEXT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SAFE_WORKFLOW_CONTEXT = {
    PACKAGE_PUBLISH_WORKFLOW_REF: "package-publish.yml@v0.23.3",
}
OBSERVED_CONTEXT_BY_DIAGNOSIS = {
    "TRUSTED_PUBLISH_TAG_REF_REGRESSION": {
        "sourceValidatorCommit",
        "sourceCommit",
    },
    "REUSABLE_WORKFLOW_ACTIONS_PERMISSION": {"workflowRef"},
    "NPM_PACK_JSON_SHAPE": {"clawhubVersion", "npmVersion"},
    "BUNDLE_NATIVE_MANIFEST_CONTRACT": {"clawhubVersion", "family"},
    "CLAWPACK_STAGING_GAP": {"workflowRef"},
    "PACKAGE_RELEASE_SCAN_STALLED": {"clawhubVersion", "family"},
    "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING": {"family"},
}
DIAGNOSIS_GUIDANCE = {
    "TRUSTED_PUBLISH_TAG_REF_REGRESSION": {
        "conclusion": "blocked",
        "rejectedShortcuts": [
            "不要把 ordinary trusted publishing 改写成 split-candidate 模式。",
            "不要放宽 source ref 与 commit 的可信发布校验。",
        ],
        "verificationSteps": [
            "确认 ordinary token 的 tag ref、commit SHA 与输入记录一致。",
            "在受安全审查的正式服务端修复后重试同一可信发布路径。",
            "核验 definitive publication state 与发布来源仍对应原 tag 和 commit。",
        ],
        "doNotClaim": [
            "不得声称指定 source-validator commit 当前已部署。",
            "不得声称 package 已发布或已验证。",
        ],
    },
    "REUSABLE_WORKFLOW_ACTIONS_PERMISSION": {
        "conclusion": "blocked",
        "rejectedShortcuts": [
            "不要授予 actions: write 或其他无关写权限。",
            "不要绕过官方 reusable workflow。",
        ],
        "verificationSteps": [
            "在调用方 workflow 顶层仅加入 actions: read。",
            "重新验证 reusable workflow 能创建 jobs。",
            "继续按后续层检查 publish、publication state 与 package verify。",
        ],
        "doNotClaim": [
            "不得把 workflow 尚未创建 job 描述为 package 发布失败。",
            "不得声称 package 已发布或已验证。",
        ],
    },
    "NPM_PACK_JSON_SHAPE": {
        "conclusion": "blocked",
        "rejectedShortcuts": [
            "不要删除已生成的 tarball 来迎合错误解析结果。",
            "不要把长期降级 npm 当作正式修复。",
        ],
        "verificationSteps": [
            "确认 npm pack 输出形状与 tarball filename 可被当前 CLI 解析。",
            "使用包含兼容解析的正式 CLI 重新执行 package validate 或 dry-run。",
            "核对后续使用的 artifact hash 与本次生成的 tarball 一致。",
        ],
        "doNotClaim": [
            "不得声称 tarball 未生成。",
            "不得声称 package 已发布或已验证。",
        ],
    },
    "BUNDLE_NATIVE_MANIFEST_CONTRACT": {
        "conclusion": "blocked",
        "rejectedShortcuts": [
            "不要伪造 openclaw.plugin.json。",
            "不要把 bundle-plugin 强制改报为另一 package family。",
        ],
        "verificationSteps": [
            "记录 bundle markers、family 与 native manifest 的实际组合。",
            "等待维护者给出经安全审查的产品合约决定。",
            "按正式合约重新执行 package validate，再检查 Inspector。",
        ],
        "doNotClaim": [
            "不得声称缺少 native manifest 只是普通目录错误。",
            "不得声称该 bundle 已通过 Inspector 或已发布。",
        ],
    },
    "CLAWPACK_STAGING_GAP": {
        "conclusion": "blocked",
        "rejectedShortcuts": [
            "不要把未发布的 main commit 作为生产依赖。",
            "不要绕过 Inspector 或降低 artifact 完整性要求。",
        ],
        "verificationSteps": [
            "确认收到 413 的 artifact hash 与已通过验证的 artifact hash 相同。",
            "升级到包含 staging 修复的正式 release 后重试上传。",
            "核验 definitive publication state、package verify 与 artifact hash。",
        ],
        "doNotClaim": [
            "不得把 Inspector 或本地验证成功描述为上传成功。",
            "不得声称 main-only fix 已发布或 package 已上线。",
        ],
    },
    "PACKAGE_RELEASE_SCAN_STALLED": {
        "conclusion": "partial",
        "rejectedShortcuts": [
            "不要连续 bump 版本来绕过 stalled release。",
            "不要重复发布已被 duplicate guard 保留的同版本。",
        ],
        "verificationSteps": [
            "升级到包含修复的正式 CLI。",
            "只读核验原 release ID 的最终 scan 与 publication state。",
            "仅在版本可 inspect 后执行 package verify 并核对 artifact hash。",
        ],
        "doNotClaim": [
            "不得把 release ID 或版本占用描述为公开可用。",
            "不得声称 stalled release 已通过 moderation 或 verification。",
        ],
    },
    "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING": {
        "conclusion": "published-unverified",
        "rejectedShortcuts": [
            "不要伪造 overview 或 securityAuditUrl。",
            "不要绕过 fail-closed trust policy。",
        ],
        "verificationSteps": [
            "部署后只读核验精确版本 security endpoint 的必填审计字段均为非空字符串。",
            "确认 trust verdict 仍为 clean，且 blocked、pending、stale 均为 false。",
            "重试受支持的安装验证并核对精确 release 与 artifact provenance。",
        ],
        "doNotClaim": [
            "不得把 clean verdict 单独描述为安装验证完成。",
            "不得声称已合并修复已经部署。",
        ],
    },
}


class InputContractError(ValueError):
    """Raised when the CLI input cannot satisfy the offline input contract."""


def _optional_string(value):
    if not _is_non_empty_string(value):
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def _normalized_context_value(field, value):
    if not _is_non_empty_string(value):
        return None
    if field == "clawhubVersion":
        version = _version_tuple(value)
        return ".".join(map(str, version)) if version is not None else None
    if field == "npmVersion":
        major = _version_major(value)
        return f"{major}.x" if major is not None else None
    if field == "workflowRef":
        return SAFE_WORKFLOW_CONTEXT.get(value)
    if field == "family":
        return value if value in OBSERVED_FAMILIES else None
    if field in {"sourceValidatorCommit", "sourceCommit"}:
        return value.lower() if COMMIT_CONTEXT_PATTERN.fullmatch(value) else None
    return None


def _observed_context(case, diagnosis=None):
    inputs = case.get("input") if isinstance(case, dict) else None
    allowed_fields = OBSERVED_CONTEXT_BY_DIAGNOSIS.get(diagnosis, set())
    if not isinstance(inputs, dict) or not allowed_fields:
        return {}
    context = {}
    for field in OBSERVED_CONTEXT_FIELDS:
        if field not in allowed_fields:
            continue
        value = _normalized_context_value(field, inputs.get(field))
        if value is not None:
            context[field] = value
    return context


def _result(case, diagnosis, layer, evidence, recommendation, version_status):
    guidance = DIAGNOSIS_GUIDANCE[diagnosis]
    return {
        "matched": True,
        "caseId": _optional_string(case.get("id")),
        "diagnosis": diagnosis,
        "conclusion": guidance["conclusion"],
        "layer": layer,
        "confidence": "high",
        "versionStatus": version_status,
        "observedContext": _observed_context(case, diagnosis),
        "evidence": evidence,
        "recommendation": recommendation,
        "rejectedShortcuts": list(guidance["rejectedShortcuts"]),
        "verificationSteps": list(guidance["verificationSteps"]),
        "doNotClaim": list(guidance["doNotClaim"]),
        "missingEvidence": [],
        "source": _optional_string(case.get("source")),
    }


def _unknown(case, missing_evidence, evidence=None):
    minimum_evidence = missing_evidence[:1]
    return {
        "matched": False,
        "caseId": _optional_string(case.get("id")),
        "diagnosis": "UNKNOWN",
        "conclusion": "partial",
        "layer": "unknown",
        "confidence": "low",
        "versionStatus": "unknown",
        "observedContext": _observed_context(case),
        "evidence": evidence or [],
        "recommendation": "证据不足；保留原始日志并继续定位，不要套用已知 workaround。",
        "rejectedShortcuts": [
            "不要根据单个错误关键词套用已知 workaround。",
            "不要通过发布、安装、下载或扩大权限来试探根因。",
        ],
        "verificationSteps": [
            minimum_evidence[0],
            "使用同一输入重新运行离线 canonical CLI。",
            "仅在得到唯一诊断后执行该诊断限定的验证步骤。",
        ],
        "doNotClaim": [
            "不得声称已确定根因、修复状态或版本适用性。",
            "不得声称 package 已发布、可安装或已验证。",
        ],
        "missingEvidence": minimum_evidence,
        "source": _optional_string(case.get("source")),
    }


def _version_tuple(value):
    if not _is_non_empty_string(value):
        return None
    match = re.fullmatch(
        rf"v?({VERSION_NUMBER_PATTERN})\.({VERSION_NUMBER_PATTERN})\."
        rf"({VERSION_NUMBER_PATTERN})",
        value,
    )
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _version_major(value):
    if not _is_non_empty_string(value):
        return None
    match = re.fullmatch(
        rf"v?({VERSION_NUMBER_PATTERN})"
        rf"(?:\.(?:{VERSION_NUMBER_PATTERN}|x)){{1,2}}",
        value,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match is not None else None


def _is_non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _is_commit(value):
    return _is_non_empty_string(value) and bool(
        COMMIT_CONTEXT_PATTERN.fullmatch(value)
    )


def _is_sha256(value):
    return _is_non_empty_string(value) and bool(SHA256_PATTERN.fullmatch(value))


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _single_pack_entry(value, expected_type):
    if not isinstance(value, expected_type) or not value:
        return None
    entries = list(value.values()) if isinstance(value, dict) else value
    if len(entries) != 1 or not isinstance(entries[0], dict):
        return None
    package_id = entries[0].get("id")
    filename = entries[0].get("filename")
    if not _is_non_empty_string(package_id) or not _is_non_empty_string(filename):
        return None
    return package_id, filename


def _same_artifact_validation(inputs):
    artifact_hash = inputs.get("artifactHash")
    if not _is_sha256(artifact_hash):
        return None
    for name, label in (("inspector", "Inspector"), ("localValidation", "本地验证")):
        validation = inputs.get(name)
        if not isinstance(validation, dict):
            continue
        if (
            _is_non_empty_string(validation.get("status"))
            and validation.get("status").lower() in {"success", "passed"}
            and validation.get("artifactHash") == artifact_hash
            and _is_sha256(validation.get("artifactHash"))
        ):
            return f"同一 artifact（{artifact_hash}）的 {label} 已成功"
    return None


def _resolve_matches(case, matches):
    if not matches:
        return _unknown(
            case,
            ["可同时证明首个失败层和对应 CLI/workflow 版本的最小状态组合"],
        )
    if len(matches) == 1:
        return matches[0]
    layers = {match["layer"] for match in matches}
    codes = [match["diagnosis"] for match in matches]
    if len(layers) == 1:
        return _unknown(
            case,
            ["能够排除同层多个诊断信号的直接证据"],
            [f"同层同时匹配：{', '.join(codes)}"],
        )
    sequence = (case.get("input") or {}).get("failureSequence")
    if not isinstance(sequence, list) or any(layer not in sequence for layer in layers):
        return _unknown(
            case,
            ["覆盖所有匹配层的 input.failureSequence 时间顺序"],
            [f"多层同时匹配：{', '.join(codes)}"],
        )
    first_position = min(sequence.index(layer) for layer in layers)
    first_layers = [layer for layer in layers if sequence.index(layer) == first_position]
    if len(first_layers) != 1:
        return _unknown(
            case,
            ["能够唯一确定首个失败层的 input.failureSequence"],
            [f"多层同时匹配：{', '.join(codes)}"],
        )
    first_matches = [match for match in matches if match["layer"] == first_layers[0]]
    if len(first_matches) != 1:
        return _unknown(
            case,
            ["能够排除首个失败层内多个诊断信号的直接证据"],
            [f"首个失败层 {first_layers[0]} 同时匹配多个规则"],
        )
    result = first_matches[0]
    result["evidence"].append(
        f"failureSequence 证明 {first_layers[0]} 是首个匹配失败层"
    )
    return result


def diagnose(case):
    """Return one conservative diagnosis for one normalized input object."""
    if not isinstance(case, dict):
        raise InputContractError("top-level JSON value must be an object")
    if "input" not in case:
        raise InputContractError("required field 'input' is missing")
    inputs = case["input"]
    if not isinstance(inputs, dict):
        raise InputContractError("field 'input' must be an object")
    if inputs.get("surface") != "package":
        return _unknown(case, ["input.surface=package"])

    reported_error = inputs.get("reportedError")
    error_lower = reported_error.lower() if _is_non_empty_string(reported_error) else ""
    matches = []

    if (
        inputs.get("publishMode") == "trusted-github-actions"
        and inputs.get("candidateShaPresent") is False
        and inputs.get("rejected") is True
        and inputs.get("rejectionStage") == "source-validation"
        and inputs.get("sourceValidationOutcome")
        == TRUSTED_SOURCE_VALIDATION_OUTCOME
        and inputs.get("sourceValidatorCommit") == TRUSTED_SOURCE_VALIDATOR_COMMIT
        and inputs.get("sourceValidationComparison") == TRUSTED_SOURCE_COMPARISON
        and _is_commit(inputs.get("tokenSha"))
        and _is_non_empty_string(inputs.get("tokenRef"))
        and TAG_REF_PATTERN.fullmatch(inputs.get("tokenRef"))
        and inputs.get("sourceCommit") == inputs.get("tokenSha")
        and inputs.get("sourceRef") == inputs.get("tokenRef")
        and inputs.get("sourceRef") != inputs.get("tokenSha")
    ):
        matches.append(
            _result(
                case,
                "TRUSTED_PUBLISH_TAG_REF_REGRESSION",
                "source-resolution",
                [
                    "ordinary trusted-publisher token 不含 candidateSha",
                    "source.commit 与 token SHA 一致",
                    "source.ref 与 token tag ref 一致",
                    f"源码 {TRUSTED_SOURCE_VALIDATOR_COMMIT} 明确比较 source.ref 与 candidateSha ?? token.sha",
                    "ordinary 模式下该比较拒绝了字符串不同的 tag ref 与 token SHA",
                ],
                "保留已验证的 tag ref 与 commit 语义，等待受安全审查的服务端修复；不要把普通模式改写成 split-candidate 模式。",
                "source-reproduced-at-commit",
            )
        )

    permissions_value = inputs.get("effectiveCallerPermissions")
    permissions = permissions_value if isinstance(permissions_value, dict) else {}
    actions_value = permissions.get("actions")
    actions_missing = (
        _is_non_empty_string(actions_value)
        and actions_value.strip().lower() == "none"
    )
    if (
        _is_integer(inputs.get("jobsCreated"))
        and inputs.get("jobsCreated") == 0
        and "requesting 'actions: read'" in error_lower
        and isinstance(permissions_value, dict)
        and actions_missing
        and inputs.get("workflowRef") == PACKAGE_PUBLISH_WORKFLOW_REF
    ):
        matches.append(
            _result(
                case,
                "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
                "workflow-permission",
                [
                    "GitHub 未创建任何 job",
                    f"调用固定版本 workflow {PACKAGE_PUBLISH_WORKFLOW_REF}",
                    "被调用 workflow 请求 actions: read",
                    "调用方未授予 actions 权限",
                ],
                "在调用方 workflow 顶层显式加入 actions: read；不要扩大为 write。",
                "current-release",
            )
        )

    npm11_entry = _single_pack_entry(inputs.get("npm11"), list)
    npm12_entry = _single_pack_entry(inputs.get("npm12"), dict)
    if (
        inputs.get("artifactExists") is True
        and inputs.get("command") == NPM_PACK_COMMAND
        and npm11_entry is not None
        and npm12_entry is not None
        and npm11_entry == npm12_entry
        and inputs.get("artifactFilename") == npm11_entry[1]
        and "npm pack did not return a tarball filename" in error_lower
        and _version_tuple(inputs.get("clawhubVersion"))
        == NPM_PACK_JSON_SHAPE_CLI_VERSION
        and _version_major(inputs.get("npmVersion")) == NPM_PACK_JSON_SHAPE_NPM_MAJOR
    ):
        matches.append(
            _result(
                case,
                "NPM_PACK_JSON_SHAPE",
                "pack",
                [
                    "npm pack 已生成 tarball",
                    "npm 12 的 JSON 输出是对象而不是数组",
                    "npm 11 与 npm 12 记录同一 package id 和 tarball filename",
                    "实际 artifact filename 与两侧 npm 输出一致",
                    "旧解析器仍按数组读取第一个 filename",
                    "正式修复版本为 "
                    f"{'.'.join(map(str, NPM_PACK_JSON_SHAPE_FIXED_VERSION))}",
                ],
                "升级到包含兼容解析的正式 CLI；临时方案只在发布 job 内固定 npm 11。",
                "fixed-in-release",
            )
        )

    files_value = inputs.get("files")
    files = (
        set(files_value)
        if isinstance(files_value, list)
        and all(isinstance(item, str) for item in files_value)
        else set()
    )
    if (
        inputs.get("family") == "bundle-plugin"
        and _version_tuple(inputs.get("clawhubVersion"))
        == BUNDLE_NATIVE_MANIFEST_CLI_VERSION
        and inputs.get("filesObservationComplete") is True
        and files.intersection(BUNDLE_MARKERS)
        and inputs.get("openclawPluginManifestPresent") is False
        and "openclaw.plugin.json" not in files
        and "openclaw.plugin.json required" in error_lower
    ):
        matches.append(
            _result(
                case,
                "BUNDLE_NATIVE_MANIFEST_CONTRACT",
                "family-detection",
                [
                    "存在兼容 bundle marker",
                    "发布 family 为 bundle-plugin",
                    "根目录不存在 openclaw.plugin.json",
                ],
                "标记为产品合约阻塞并等待维护者决策；不要伪造 native manifest。",
                "product-decision",
            )
        )

    artifact_bytes = inputs.get("artifactBytes")
    validation_evidence = _same_artifact_validation(inputs)
    if (
        inputs.get("reportedStatus") == 413
        and "request entity too large" in error_lower
        and _is_integer(artifact_bytes)
        and PUBLIC_EDGE_BUDGET_BYTES
        < artifact_bytes
        < LEGACY_STAGING_THRESHOLD_BYTES
        and inputs.get("workflowRef") == PACKAGE_PUBLISH_WORKFLOW_REF
        and inputs.get("uploadTarget") == CLAWPACK_UPLOAD_TARGET
        and inputs.get("registry") == CLAWPACK_PUBLIC_REGISTRY
        and validation_evidence
    ):
        matches.append(
            _result(
                case,
                "CLAWPACK_STAGING_GAP",
                "upload",
                [
                    f"artifact 为 {artifact_bytes} bytes",
                    f"超过内置公共边缘预算 {PUBLIC_EDGE_BUDGET_BYTES} bytes",
                    f"低于内置旧 staging 阈值 {LEGACY_STAGING_THRESHOLD_BYTES} bytes",
                    "上传目标明确为 ClawHub public edge",
                    validation_evidence,
                    "修复仅存在于 main，当前 release 未包含",
                ],
                "等待并升级到包含 staging 修复的正式 release；不要把未发布 main 当生产依赖。",
                "main-only-fix",
            )
        )

    installed_version = _version_tuple(inputs.get("clawhubVersion"))
    pending_hours = inputs.get("pendingHours")
    if (
        inputs.get("family") == "bundle-plugin"
        and inputs.get("publishAccepted") is True
        and _is_non_empty_string(inputs.get("releaseId"))
        and inputs.get("scanStatus") == "pending"
        and _is_number(pending_hours)
        and pending_hours >= 24
        and "latestRelease" in inputs
        and inputs.get("latestRelease") is None
        and inputs.get("inspectVisible") is False
        and inputs.get("duplicateOnRepublish") is True
        and installed_version == PACKAGE_RELEASE_SCAN_AFFECTED_VERSION
    ):
        matches.append(
            _result(
                case,
                "PACKAGE_RELEASE_SCAN_STALLED",
                "moderation",
                [
                    "package publish 已返回 release ID",
                    f"安全扫描持续 pending 至少 {pending_hours:g} 小时",
                    "latestRelease 仍为空且指定版本不可 inspect",
                    "同版本重发被 duplicate guard 拒绝",
                    "当前 CLI "
                    f"{inputs.get('clawhubVersion')} 是已证实受影响版本；修复版本为 "
                    f"{'.'.join(map(str, PACKAGE_RELEASE_SCAN_FIXED_VERSION))}",
                ],
                "升级到包含修复的正式 CLI 后核验原 release 的最终状态；不要通过连续 bump 版本制造更多孤立 release。",
                "fixed-in-release",
            )
        )

    trust_value = inputs.get("trust")
    trust = trust_value if isinstance(trust_value, dict) else {}
    invalid_fields = [
        name
        for name in ("overview", "securityAuditUrl")
        if not _is_non_empty_string(inputs.get(name))
    ]
    audit_error_matches = (
        "malformed clawhub security response" in error_lower
        and "non-empty string" in error_lower
        and any(
            re.search(
                rf"(?<![a-z0-9_]){re.escape(name.lower())}(?![a-z0-9_])",
                error_lower,
            )
            for name in invalid_fields
        )
    )
    release_version = inputs.get("releaseVersion")
    security_release_version = inputs.get("securityReleaseVersion")
    if (
        inputs.get("family") == "code-plugin"
        and inputs.get("stage") == "install-verification"
        and inputs.get("publicationStatus")
        == PACKAGE_SECURITY_PUBLICATION_STATUS
        and _version_tuple(release_version) is not None
        and security_release_version == release_version
        and inputs.get("exactReleaseSecurityEndpoint") is True
        and trust.get("scanStatus") == "clean"
        and trust.get("blockedFromDownload") is False
        and trust.get("pending") is False
        and trust.get("stale") is False
        and trust.get("reasons") == []
        and invalid_fields
        and audit_error_matches
    ):
        matches.append(
            _result(
                case,
                "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING",
                "verification",
                [
                    "精确 package release 的 trust verdict 为 clean",
                    "blocked、pending 与 stale 均为 false",
                    "security response 的必填字段无效：" + ", ".join(invalid_fields),
                    "安装器按 fail-closed 策略拒绝 malformed trust response",
                    "修复已合并，但当前证据未证明部署完成",
                ],
                "保持 fail-closed；部署后只读核验精确版本 security endpoint 返回非空审计字段，再重试受支持的安装流程。",
                "fix-merged-deployment-unverified",
            )
        )

    return _resolve_matches(case, matches)


def _load_case(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputContractError("input file must be valid UTF-8") from exc
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        raise InputContractError(f"unable to read input file: {reason}") from exc
    try:
        case = json.loads(raw, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise InputContractError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(case, dict):
        raise InputContractError("top-level JSON value must be an object")
    return case


def _reject_json_constant(value):
    raise InputContractError(f"invalid JSON constant: {value}")


def _serialize_json(value, indent=None):
    serialized = json.dumps(value, ensure_ascii=False, indent=indent)
    return serialized.encode("utf-8", errors="backslashreplace").decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline diagnosis of one normalized ClawHub package JSON file."
    )
    parser.add_argument("input_json", type=Path, help="Path to one UTF-8 JSON object")
    args = parser.parse_args(argv)
    try:
        result = diagnose(_load_case(args.input_json))
    except InputContractError as exc:
        error = {
            "error": "INPUT_CONTRACT_ERROR",
            "message": str(exc),
        }
        print(_serialize_json(error), file=sys.stderr)
        return 2
    print(_serialize_json(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

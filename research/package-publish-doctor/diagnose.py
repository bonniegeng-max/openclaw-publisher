#!/usr/bin/env python3
"""Offline rule prototype for ClawHub package publish failures."""

import argparse
import json
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
NPM_PACK_JSON_SHAPE_CLI_VERSION = (0, 23, 1)
NPM_PACK_JSON_SHAPE_NPM_MAJOR = 12
BUNDLE_NATIVE_MANIFEST_CLI_VERSION = (0, 23, 3)
PACKAGE_PUBLISH_WORKFLOW_REF = (
    "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3"
)
PACKAGE_RELEASE_SCAN_FIXED_VERSION = (0, 23, 2)
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
EXECUTABLE_RULE_LAYERS = frozenset(
    {
        "workflow-permission",
        "source-resolution",
        "pack",
        "family-detection",
        "upload",
        "moderation",
        "verification",
    }
)
CLASSIFICATION_ONLY_LAYERS = FAILURE_LAYERS - EXECUTABLE_RULE_LAYERS


def _result(
    case,
    diagnosis,
    layer,
    evidence,
    recommendation,
    version_status,
):
    return {
        "matched": True,
        "caseId": case.get("id"),
        "diagnosis": diagnosis,
        "layer": layer,
        "confidence": "high",
        "versionStatus": version_status,
        "evidence": evidence,
        "recommendation": recommendation,
        "missingEvidence": [],
        "source": case.get("source"),
    }


def _unknown(case, missing_evidence, evidence=None):
    return {
        "matched": False,
        "caseId": case.get("id"),
        "diagnosis": "UNKNOWN",
        "layer": "unknown",
        "confidence": "low",
        "versionStatus": "unknown",
        "evidence": evidence or [],
        "recommendation": "证据不足；保留原始日志并继续定位，不要套用已知 workaround。",
        "missingEvidence": missing_evidence,
        "source": case.get("source"),
    }


def _version_tuple(value):
    parts = str(value or "").lstrip("v").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _version_major(value):
    first = str(value or "").lstrip("v").split(".", 1)[0]
    return int(first) if first.isdigit() else None


def _same_artifact_validation(inputs):
    artifact_hash = inputs.get("artifactHash")
    if not isinstance(artifact_hash, str) or not artifact_hash.strip():
        return None

    for name, label in (
        ("inspector", "Inspector"),
        ("localValidation", "本地验证"),
    ):
        validation = inputs.get(name)
        if not isinstance(validation, dict):
            continue
        status = str(validation.get("status") or "").lower()
        validation_hash = validation.get("artifactHash")
        if status in {"success", "passed"} and validation_hash == artifact_hash:
            return f"同一 artifact（{artifact_hash}）的 {label} 已成功"
    return None


def _resolve_matches(case, matches):
    if not matches:
        return _unknown(
            case,
            [
                "可证明首个失败层的完整状态组合",
                "与已知规则对应的 CLI 或 workflow 版本",
            ],
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

    positions = {layer: sequence.index(layer) for layer in layers}
    first_position = min(positions.values())
    first_layers = [
        layer for layer, position in positions.items() if position == first_position
    ]
    if len(first_layers) != 1:
        return _unknown(
            case,
            ["能够唯一确定首个失败层的 input.failureSequence"],
            [f"多层同时匹配：{', '.join(codes)}"],
        )

    first_layer = first_layers[0]
    first_matches = [match for match in matches if match["layer"] == first_layer]
    if len(first_matches) != 1:
        return _unknown(
            case,
            ["能够排除首个失败层内多个诊断信号的直接证据"],
            [f"首个失败层 {first_layer} 同时匹配多个规则"],
        )

    result = first_matches[0]
    result["evidence"].append(
        f"failureSequence 证明 {first_layer} 是首个匹配失败层"
    )
    return result


def diagnose(case):
    """Return one conservative diagnosis for a normalized fixture."""
    inputs = case.get("input") or {}
    if inputs.get("surface") != "package":
        return _unknown(case, ["input.surface=package"])

    error = str(inputs.get("reportedError") or "")
    error_lower = error.lower()
    matches = []

    token_sha = inputs.get("tokenSha")
    token_ref = inputs.get("tokenRef")
    source_commit = inputs.get("sourceCommit")
    source_ref = inputs.get("sourceRef")
    source_comparison = inputs.get("sourceValidationComparison")
    if (
        inputs.get("publishMode") == "trusted-github-actions"
        and inputs.get("candidateShaPresent") is False
        and inputs.get("rejected") is True
        and inputs.get("sourceValidatorCommit")
        == TRUSTED_SOURCE_VALIDATOR_COMMIT
        and source_comparison == TRUSTED_SOURCE_COMPARISON
        and bool(token_sha)
        and bool(token_ref)
        and source_commit == token_sha
        and source_ref == token_ref
        and source_ref != token_sha
    ):
        matches.append(_result(
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
        ))

    permissions = inputs.get("callerPermissions") or {}
    actions_permission = str(permissions.get("actions") or "none").lower()
    if (
        inputs.get("jobsCreated") == 0
        and "requesting 'actions: read'" in error_lower
        and actions_permission == "none"
        and inputs.get("workflowRef") == PACKAGE_PUBLISH_WORKFLOW_REF
    ):
        matches.append(_result(
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
        ))

    npm12_output = inputs.get("npm12")
    if (
        inputs.get("artifactExists") is True
        and isinstance(npm12_output, dict)
        and "npm pack did not return a tarball filename" in error_lower
        and _version_tuple(inputs.get("clawhubVersion"))
        == NPM_PACK_JSON_SHAPE_CLI_VERSION
        and _version_major(inputs.get("npmVersion"))
        == NPM_PACK_JSON_SHAPE_NPM_MAJOR
    ):
        matches.append(_result(
            case,
            "NPM_PACK_JSON_SHAPE",
            "pack",
            [
                "npm pack 已生成 tarball",
                "npm 12 的 JSON 输出是对象而不是数组",
                "旧解析器仍按数组读取第一个 filename",
            ],
            "升级到包含兼容解析的正式 CLI；临时方案只在发布 job 内固定 npm 11。",
            "unknown",
        ))

    files = set(inputs.get("files") or [])
    if (
        inputs.get("family") == "bundle-plugin"
        and _version_tuple(inputs.get("clawhubVersion"))
        == BUNDLE_NATIVE_MANIFEST_CLI_VERSION
        and files.intersection(BUNDLE_MARKERS)
        and inputs.get("openclawPluginManifestPresent") is False
        and "openclaw.plugin.json required" in error_lower
    ):
        matches.append(_result(
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
        ))

    artifact_bytes = inputs.get("artifactBytes")
    edge_budget = inputs.get("publicEdgeBudgetBytes")
    legacy_threshold = inputs.get("legacyStagingThresholdBytes")
    validation_evidence = _same_artifact_validation(inputs)
    if (
        inputs.get("reportedStatus") == 413
        and "request entity too large" in error_lower
        and isinstance(artifact_bytes, int)
        and isinstance(edge_budget, int)
        and isinstance(legacy_threshold, int)
        and edge_budget < artifact_bytes < legacy_threshold
        and inputs.get("workflowRef") == PACKAGE_PUBLISH_WORKFLOW_REF
        and validation_evidence is not None
    ):
        matches.append(_result(
            case,
            "CLAWPACK_STAGING_GAP",
            "upload",
            [
                f"artifact 为 {artifact_bytes} bytes",
                f"超过公共边缘预算 {edge_budget} bytes",
                f"低于旧 staging 阈值 {legacy_threshold} bytes",
                validation_evidence,
                "修复仅存在于 main，当前 release 未包含",
            ],
            "等待并升级到包含 staging 修复的正式 release；不要把未发布 main 当生产依赖。",
            "main-only-fix",
        ))

    installed_version = _version_tuple(inputs.get("clawhubVersion"))
    pending_hours = inputs.get("pendingHours")
    if (
        inputs.get("family") == "bundle-plugin"
        and inputs.get("publishAccepted") is True
        and bool(inputs.get("releaseId"))
        and inputs.get("scanStatus") == "pending"
        and isinstance(pending_hours, (int, float))
        and pending_hours >= 24
        and inputs.get("latestRelease") is None
        and inputs.get("inspectVisible") is False
        and inputs.get("duplicateOnRepublish") is True
        and installed_version is not None
        and installed_version < PACKAGE_RELEASE_SCAN_FIXED_VERSION
    ):
        matches.append(_result(
            case,
            "PACKAGE_RELEASE_SCAN_STALLED",
            "moderation",
            [
                "package publish 已返回 release ID",
                f"安全扫描持续 pending 至少 {pending_hours:g} 小时",
                "latestRelease 仍为空且指定版本不可 inspect",
                "同版本重发被 duplicate guard 拒绝",
                "当前 CLI "
                f"{inputs.get('clawhubVersion')} 早于修复版本 "
                f"{'.'.join(map(str, PACKAGE_RELEASE_SCAN_FIXED_VERSION))}",
            ],
            "升级到包含修复的正式 CLI 后核验原 release 的最终状态；不要通过连续 bump 版本制造更多孤立 release。",
            "fixed-in-release",
        ))

    trust = inputs.get("trust") or {}
    if (
        inputs.get("family") == "code-plugin"
        and inputs.get("stage") == "install-verification"
        and inputs.get("exactReleaseSecurityEndpoint") is True
        and trust.get("scanStatus") == "clean"
        and trust.get("blockedFromDownload") is False
        and trust.get("pending") is False
        and trust.get("stale") is False
        and trust.get("reasons") == []
        and inputs.get("overview") is None
        and inputs.get("securityAuditUrl") is None
        and "expected overview to be a non-empty string" in error_lower
    ):
        matches.append(_result(
            case,
            "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING",
            "verification",
            [
                "精确 package release 的 trust verdict 为 clean",
                "blocked、pending 与 stale 均为 false",
                "security response 的 overview 与 securityAuditUrl 均为空",
                "安装器按 fail-closed 策略拒绝 malformed trust response",
                "修复已合并，但当前证据未证明部署完成",
            ],
            "保持 fail-closed；部署后只读核验精确版本 security endpoint 返回非空审计字段，再重试受支持的安装流程。",
            "fix-merged-deployment-unverified",
        ))

    return _resolve_matches(case, matches)


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose one normalized ClawHub package publish fixture."
    )
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()

    case = json.loads(args.fixture.read_text(encoding="utf-8"))
    print(json.dumps(diagnose(case), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

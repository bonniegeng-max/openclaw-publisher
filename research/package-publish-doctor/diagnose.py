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


def _result(case, diagnosis, layer, evidence, recommendation):
    return {
        "matched": True,
        "caseId": case.get("id"),
        "diagnosis": diagnosis,
        "layer": layer,
        "confidence": "high",
        "evidence": evidence,
        "recommendation": recommendation,
        "source": case.get("source"),
    }


def diagnose(case):
    """Return one conservative diagnosis for a normalized fixture."""
    inputs = case.get("input") or {}
    affected = case.get("affected") or {}
    error = str(inputs.get("reportedError") or "")
    error_lower = error.lower()

    permissions = inputs.get("callerPermissions") or {}
    actions_permission = str(permissions.get("actions") or "none").lower()
    if (
        inputs.get("jobsCreated") == 0
        and "requesting 'actions: read'" in error_lower
        and actions_permission == "none"
    ):
        return _result(
            case,
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
            "workflow-permission",
            [
                "GitHub 未创建任何 job",
                "被调用 workflow 请求 actions: read",
                "调用方未授予 actions 权限",
            ],
            "在调用方 workflow 顶层显式加入 actions: read；不要扩大为 write。",
        )

    npm12_output = inputs.get("npm12")
    if (
        inputs.get("artifactExists") is True
        and isinstance(npm12_output, dict)
        and "npm pack did not return a tarball filename" in error_lower
        and str(affected.get("npm") or "").startswith("12")
    ):
        return _result(
            case,
            "NPM_PACK_JSON_SHAPE",
            "pack",
            [
                "npm pack 已生成 tarball",
                "npm 12 的 JSON 输出是对象而不是数组",
                "旧解析器仍按数组读取第一个 filename",
            ],
            "升级到包含兼容解析的正式 CLI；临时方案只在发布 job 内固定 npm 11。",
        )

    files = set(inputs.get("files") or [])
    if (
        affected.get("family") == "bundle-plugin"
        and files.intersection(BUNDLE_MARKERS)
        and inputs.get("openclawPluginManifestPresent") is False
        and "openclaw.plugin.json required" in error_lower
    ):
        return _result(
            case,
            "BUNDLE_NATIVE_MANIFEST_CONTRACT",
            "family-detection",
            [
                "存在兼容 bundle marker",
                "发布 family 为 bundle-plugin",
                "根目录不存在 openclaw.plugin.json",
            ],
            "标记为产品合约阻塞并等待维护者决策；不要伪造 native manifest。",
        )

    artifact_bytes = inputs.get("artifactBytes")
    edge_budget = inputs.get("publicEdgeBudgetBytes")
    legacy_threshold = inputs.get("legacyStagingThresholdBytes")
    if (
        inputs.get("reportedStatus") == 413
        and "request entity too large" in error_lower
        and isinstance(artifact_bytes, int)
        and isinstance(edge_budget, int)
        and isinstance(legacy_threshold, int)
        and edge_budget < artifact_bytes < legacy_threshold
        and affected.get("releaseContainsFix") is False
        and affected.get("mainContainsFix") is True
    ):
        return _result(
            case,
            "CLAWPACK_STAGING_GAP",
            "upload",
            [
                f"artifact 为 {artifact_bytes} bytes",
                f"超过公共边缘预算 {edge_budget} bytes",
                f"低于旧 staging 阈值 {legacy_threshold} bytes",
                "修复仅存在于 main，当前 release 未包含",
            ],
            "等待并升级到包含 staging 修复的正式 release；不要把未发布 main 当生产依赖。",
        )

    return {
        "matched": False,
        "caseId": case.get("id"),
        "diagnosis": "UNKNOWN",
        "layer": "unknown",
        "confidence": "low",
        "evidence": [],
        "recommendation": "证据不足；保留原始日志并继续定位，不要套用已知 workaround。",
        "source": case.get("source"),
    }


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

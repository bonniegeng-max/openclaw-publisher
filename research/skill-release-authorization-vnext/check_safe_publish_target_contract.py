#!/usr/bin/env python3
"""严格验证 research-only 安全发布目标合同。"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


RESEARCH = Path(__file__).resolve().parent
WORKFLOW_CHECKER = RESEARCH / "check_workflow_integration_contract.py"
SPEC = importlib.util.spec_from_file_location(
    "workflow_integration_contract",
    WORKFLOW_CHECKER,
)
WORKFLOW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WORKFLOW)

SCHEMA_VERSION = 2
STATUS = "research-only-not-wired"
GUARD_PATH = (
    "research/skill-release-authorization-vnext/"
    "safe_publish_target_guard.py"
)
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "status",
    "guard",
    "guardBaseline",
    "guardDraft",
    "formalWorkflowModified",
    "knownFormalRisks",
    "formalBaselines",
    "executionBoundary",
    "selectionRules",
    "evidenceBoundary",
}
EXPECTED_RISKS = {
    "workflow-dispatch-can-request-real-publish",
    "changed-only-can-fall-back-to-root-scan",
    "multiple-targets-can-be-published",
}
EXPECTED_EXECUTION_BOUNDARY = {
    "allowedExecutables": ["python3", "/usr/bin/git"],
    "gitTimeoutSeconds": 30,
    "gitTerminationConfirmationTimeoutSeconds": 5,
    "maximumCombinedGitOutputBytes": 12582912,
    "gitOutputLimitEnforcement": "incremental-before-process-exit",
    "gitProcessGroupTermination": True,
    "objectStoreOwner": "current-user",
    "objectStoreGroupOrWorldWritable": False,
    "objectStoreSymlinksAllowed": False,
    "objectStoreHardlinksAllowed": False,
    "objectDirectoryEntryIdentityRevalidation": True,
    "objectFileFdIdentityRevalidation": True,
    "networkCallsPresent": False,
    "osNetworkSandboxPresent": False,
    "credentialsAccepted": False,
    "packageRuntimeAllowed": False,
    "registryMutationAllowed": False,
}
EXPECTED_SELECTION_RULES = {
    "maximumTargets": 1,
    "zeroTargets": "no-op",
    "multipleTargets": "reject",
    "supportedEvents": ["pull_request", "push", "workflow_dispatch"],
    "workflowDispatchRealPublish": "reject",
    "pullRequestRealPublish": "reject",
    "realPublishRef": "refs/heads/main",
    "realPublishRequiresBase": True,
    "realPublishRequiresFullHead": True,
    "realPublishRequiresChangedTarget": True,
    "realPublishRequiresChangedOnly": True,
    "trustedEventFields": ["eventBefore", "eventSha", "eventRef"],
    "authorizationEligibleIsNotAuthorization": True,
    "authorizedAlwaysFalse": True,
    "mutationAllowedAlwaysFalse": True,
    "changedOnlyWithoutBaseOrSkillPath": "reject",
    "unboundedDirectoryScan": "reject",
    "cleanWorktreeRequired": True,
    "headMustMatchCheckout": True,
    "explicitTargetMustCoverChangedSkillsWhenBaseProvided": True,
    "explicitSkillPathPattern": "skills/<valid-slug>",
    "requiredSkillFiles": ["SKILL.md", "CHANGELOG.md", ".clawhubignore"],
    "packageSnapshotSource": "HEAD-tree",
    "packageSnapshotFields": ["treeOid", "files", "packageDigest"],
    "packageFileFields": ["path", "mode", "blobOid", "sha256"],
    "packageDigestCanonicalJson": True,
    "packageDigestFormat": "safe-publish-package-v1",
    "packageDigestBinds": ["format", "skillPath", "treeOid", "files"],
    "packageLimits": {
        "maximumFiles": 1024,
        "maximumFileBytes": 10485760,
        "maximumPackageBytes": 52428800,
    },
    "worktreeTraversal": "no-follow",
    "requiredTraversalCapabilities": ["O_NOFOLLOW", "O_DIRECTORY"],
    "worktreeExactMatchRequired": True,
    "ignoredAndExtraEntries": "reject",
    "symlinks": "reject",
    "hardlinks": "reject",
    "localObjectStoreRequired": True,
    "objectStoreTraversal": "recursive-no-follow",
    "successRevalidation": [
        "head",
        "cleanWorktree",
        "packageWorktree",
        "repositoryLayout",
    ],
    "atomicVerifiedPackageHandoffRequired": True,
    "guardResultIsNotPackageHandoff": True,
    "nonTargetPackageSnapshot": None,
}
EXPECTED_EVIDENCE_BOUNDARY = {
    "currentLevel": "E0",
    "deploymentReady": False,
    "workflowSuccessCeiling": "E2",
    "downloadableClaimRequires": "E4",
}
EXPECTED_FORMAL_PATHS = {
    "caller": ".github/workflows/clawhub-skill-publish.yml",
    "local": ".github/workflows/clawhub-skill-publish-local.yml",
}
BASELINE_FIELDS = {"path", "commit", "mode", "blobOid", "sha256"}
GUARD_DRAFT_FIELDS = {"path", "mode", "sha256"}


def check_baseline(
    root: Path,
    value: Any,
    expected_path: str,
    *,
    require_worktree: bool = True,
) -> bool:
    if not isinstance(value, dict) or set(value) != BASELINE_FIELDS:
        return False
    if value["path"] != expected_path:
        return False
    if (
        not isinstance(value["commit"], str)
        or WORKFLOW.COMMIT_PATTERN.fullmatch(value["commit"]) is None
        or value["mode"] not in {"100644", "100755"}
        or not isinstance(value["blobOid"], str)
        or WORKFLOW.COMMIT_PATTERN.fullmatch(value["blobOid"]) is None
        or not isinstance(value["sha256"], str)
        or WORKFLOW.DIGEST_PATTERN.fullmatch(value["sha256"]) is None
    ):
        return False
    observed = {
        "commit": value["commit"],
        **WORKFLOW.git_blob_evidence(
            root,
            value["commit"],
            expected_path,
        ),
    }
    if observed != value:
        return False
    if require_worktree:
        working = WORKFLOW.working_file_evidence(
            root,
            expected_path,
            f"baseline file {expected_path}",
        )
        return working == {
            key: value[key]
            for key in ("path", "mode", "sha256")
        }
    return True


def evaluate(repo_root: Path, contract_path: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        contract = WORKFLOW.load_json_object(
            contract_path,
            "safe publish target contract",
        )
        WORKFLOW.verify_repository_layout(root)
    except ValueError as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "contractStatus": "invalid",
            "checks": {},
            "knownFormalRisks": [],
            "errors": [str(error)],
        }

    def add(name: str, passed: bool, message: str) -> None:
        checks[name] = bool(passed)
        if not passed:
            errors.append(message)

    add(
        "top-level-fields",
        set(contract) == TOP_LEVEL_FIELDS,
        "safe publish target contract fields are incomplete or unexpected",
    )
    add(
        "schema-version",
        type(contract.get("schemaVersion")) is int
        and contract.get("schemaVersion") == SCHEMA_VERSION,
        "schemaVersion must equal 2",
    )
    add(
        "research-status",
        contract.get("status") == STATUS,
        f"status must remain {STATUS}",
    )
    add(
        "guard-path",
        contract.get("guard") == GUARD_PATH,
        "guard path must remain fixed",
    )
    add(
        "formal-workflows-unmodified",
        contract.get("formalWorkflowModified") is False,
        "formal workflows must remain unmodified during observation",
    )
    risks = contract.get("knownFormalRisks")
    add(
        "known-risks",
        isinstance(risks, list)
        and len(risks) == len(EXPECTED_RISKS)
        and set(risks) == EXPECTED_RISKS,
        "known formal workflow risks are incomplete or unexpected",
    )
    add(
        "execution-boundary",
        contract.get("executionBoundary") == EXPECTED_EXECUTION_BOUNDARY,
        "execution boundary must remain offline and credential-free",
    )
    add(
        "selection-rules",
        contract.get("selectionRules") == EXPECTED_SELECTION_RULES,
        "selection rules must preserve fail-closed target boundaries",
    )
    add(
        "evidence-boundary",
        contract.get("evidenceBoundary") == EXPECTED_EVIDENCE_BOUNDARY,
        "evidence boundary must remain E0 and not deployment-ready",
    )

    try:
        guard_baseline_valid = check_baseline(
            root,
            contract.get("guardBaseline"),
            GUARD_PATH,
            require_worktree=False,
        )
    except ValueError as error:
        guard_baseline_valid = False
        errors.append(str(error))
    add(
        "guard-baseline",
        guard_baseline_valid,
        "guard predecessor baseline does not match its pinned Git blob",
    )
    guard_draft = contract.get("guardDraft")
    try:
        guard_draft_valid = (
            isinstance(guard_draft, dict)
            and set(guard_draft) == GUARD_DRAFT_FIELDS
            and guard_draft
            == WORKFLOW.working_file_evidence(
                root,
                GUARD_PATH,
                "safe publish target guard draft",
            )
        )
    except ValueError as error:
        guard_draft_valid = False
        errors.append(str(error))
    add(
        "guard-draft",
        guard_draft_valid,
        "guard draft does not match the documented worktree source",
    )

    formal = contract.get("formalBaselines")
    formal_shape = (
        isinstance(formal, dict)
        and set(formal) == set(EXPECTED_FORMAL_PATHS)
    )
    formal_valid = formal_shape
    if formal_shape:
        for name, expected_path in EXPECTED_FORMAL_PATHS.items():
            try:
                valid = check_baseline(root, formal[name], expected_path)
            except ValueError as error:
                valid = False
                errors.append(str(error))
            checks[f"formal-{name}-baseline"] = valid
            formal_valid = formal_valid and valid
    add(
        "formal-baselines",
        formal_valid,
        "formal workflow baselines are incomplete or inconsistent",
    )

    return {
        "valid": not errors,
        "deploymentReady": False,
        "contractStatus": contract.get("status", "invalid"),
        "checks": checks,
        "knownFormalRisks": risks if isinstance(risks, list) else [],
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=RESEARCH.parents[1])
    parser.add_argument(
        "--contract",
        type=Path,
        default=RESEARCH / "safe-publish-target-contract.json",
    )
    args = parser.parse_args(argv)
    result = evaluate(args.repo_root, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

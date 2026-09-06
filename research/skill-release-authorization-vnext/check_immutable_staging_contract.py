#!/usr/bin/env python3
"""严格审计两阶段锚定的 research-only immutable staging 合同。"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import stat
from pathlib import Path
from typing import Any


RESEARCH = Path(__file__).resolve().parent
ROOT = RESEARCH.parents[1]
SAFE_CHECKER_PATH = RESEARCH / "check_safe_publish_target_contract.py"
SAFE_SPEC = importlib.util.spec_from_file_location(
    "check_safe_publish_target_contract_for_staging", SAFE_CHECKER_PATH
)
SAFE_CHECKER = importlib.util.module_from_spec(SAFE_SPEC)
assert SAFE_SPEC.loader is not None
SAFE_SPEC.loader.exec_module(SAFE_CHECKER)
WORKFLOW = SAFE_CHECKER.WORKFLOW

SCHEMA_VERSION = 2
STATUS = "research-only-not-wired"
BUILDER = "research/skill-release-authorization-vnext/immutable_staging_builder.py"
LAUNCHER = "research/skill-release-authorization-vnext/trusted_staging_launcher.py"
AUDITOR = (
    "research/skill-release-authorization-vnext/"
    "check_immutable_staging_contract.py"
)
SAFE_GUARD = "research/skill-release-authorization-vnext/safe_publish_target_guard.py"
SAFE_CONTRACT = (
    "research/skill-release-authorization-vnext/safe-publish-target-contract.json"
)
TOP_LEVEL_FIELDS = {
    "schemaVersion", "status", "builder", "launcher", "auditor",
    "formalWorkflowModified", "builderEvidence", "launcherEvidence", "guardInput",
    "twoStageAnchoring", "filesystemBoundary", "sourceAndVerification",
    "durabilityAndHandoff", "outcomes",
    "consumerBoundary", "executionBoundary", "evidenceBoundary",
}
BUILDER_BASELINE_REQUIRED = True
BASELINE_FIELDS = {"path", "commit", "mode", "blobOid", "sha256"}
DRAFT_FIELDS = {"path", "mode", "sha256"}
EXPECTED_GUARD_INPUT = {
    "module": SAFE_GUARD,
    "contract": SAFE_CONTRACT,
    "schemaVersion": 2,
    "input": "complete-guard-result-json",
    "inputFileOwner": "current-user",
    "inputFileMode": "owner-only-no-group-or-world-bits",
    "inputFileSymlinks": "reject",
    "unknownOrMissingFields": "reject",
    "duplicateJsonKeys": "reject",
    "requiredDecision": "single-target",
    "requiredValid": True,
    "requiredTargetCount": 1,
    "authorizedMustRemainFalse": True,
    "mutationAllowedMustRemainFalse": True,
    "packageSnapshotExactRevalidation": True,
}
EXPECTED_TWO_STAGE = {
    "stageOne": {
        "name": "guard-result",
        "digest": "guardResultDigest",
        "canonicalization": "utf8-sorted-compact-json-without-newline",
        "bindsCompleteGuardJson": True,
    },
    "stageTwo": {
        "name": "immutable-artifact",
        "digest": "artifactDigest",
        "format": "immutable-skill-staging-v2",
        "canonicalization": "utf8-sorted-compact-json-without-newline",
        "binds": [
            "schemaVersion", "researchStatus", "format",
            "guardResultDigest", "commit", "skillPath", "treeOid",
            "packageDigest", "packageDirectory", "path", "sourceMode",
            "artifactMode", "blobOid", "sha256", "worktreeRead",
            "authorizationGranted",
        ],
    },
}
EXPECTED_FILESYSTEM = {
    "parentMustExist": True,
    "parentMustBeAbsoluteCanonical": True,
    "parentMustBeOwnedByCurrentUser": True,
    "parentMode": "0700",
    "parentInsideRepository": "reject-by-open-fd-identity",
    "pathTraversal": "component-openat-O_NOFOLLOW",
    "allStagingOperations": "dir-fd-relative",
    "temporaryCreation": "random-mkdirat",
    "temporaryDirectoryMode": "0700",
    "sealedDirectoryMode": "0555",
    "regularFileMode": "0444",
    "executableFileMode": "0555",
    "manifestMode": "0444",
    "symlinks": "reject",
    "hardlinks": "reject",
    "shutilAllowed": False,
    "osWalkAllowed": False,
}
EXPECTED_SOURCE = {
    "contentSource": "pinned-git-tree-and-blobs-only",
    "worktreeContentReadsAllowed": False,
    "lazyFetchAllowed": False,
    "replaceObjectsAllowed": False,
    "blobDigestBeforeWrite": True,
    "perFileFdReopenAndReview": True,
    "exactFileSetRequired": True,
    "secondTreeSnapshotRequired": True,
    "manifestByteReviewRequired": True,
    "manifestStrictValidationRequired": True,
    "headMustMatchCheckout": True,
    "finalRepositoryLayoutRevalidation": True,
    "finalHeadRevalidation": True,
    "stagingFdRetainedAcrossRename": True,
    "postRenameSameFdReview": True,
    "outputParentPathIdentityRevalidation": True,
}
EXPECTED_DURABILITY = {
    "fileFsyncRequired": True,
    "directoryFsyncRequired": True,
    "parentFsyncBeforeRename": True,
    "operation": "native-no-replace-rename",
    "darwinPrimitive": "renameatx_np(RENAME_EXCL)",
    "linuxPrimitive": "renameat2(RENAME_NOREPLACE)",
    "sourceAndDestinationUseSameParentFd": True,
    "precheckThenRenameFallbackAllowed": False,
    "existingDestination": "reject",
    "parentFsyncAfterRename": True,
}
EXPECTED_OUTCOMES = {
    "success": "committed",
    "preRenameFailure": "failed",
    "postRenameParentFsyncFailure": "commit-uncertain",
    "commitUncertainRetainsTarget": True,
    "temporaryTreeCleanupRequired": True,
    "cleanupFailure": "failed-with-residue",
    "cleanupFailureReturnsResidueName": True,
    "authorizationGrantedAlwaysFalse": True,
    "outputIdentifier": "content-addressed-name-only",
    "absoluteOutputPathReturned": False,
    "structuredResultRequired": True,
    "launcherFailureArtifactState": "probe-actual-parent-entry",
    "postChildVerificationFailureArtifactState": "probe-before-report",
    "successfulArtifactState": "present-verified-snapshot",
}
EXPECTED_CONSUMER = {
    "currentFormalPublisherConsumesWorktree": True,
    "formalWiringBlocked": True,
    "futurePublisherMustConsumeVerifiedArtifact": True,
    "futurePublisherMustRevalidateManifest": True,
    "futurePublisherMustConsumeSameVerifiedFdTree": True,
    "worktreePublishAfterStaging": "reject",
}
EXPECTED_EXECUTION = {
    "controlAndCandidateCheckouts": "independent-local-git-directories",
    "expectedRepository": "github.com/bonniegeng-max/openclaw-publisher",
    "remoteTrackingRef": "refs/remotes/origin/main",
    "localTrackingRefConsistencyOnly": True,
    "remoteAuthenticityClaimed": False,
    "controlCommitMustBeLocallyReachable": True,
    "candidateHeadMustEqualLocalTrackingMain": True,
    "formalTrustedControlCommitSource": "fixed-sha-protected-workflow-input",
    "sharedGitDirectoryAllowed": False,
    "objectAlternatesAllowed": False,
    "objectStoreSymlinksAllowed": False,
    "objectStoreHardlinksAllowed": False,
    "objectStoreOwner": "current-user",
    "objectStoreGroupOrWorldWritable": False,
    "objectDirectoryEntryIdentityRevalidation": True,
    "trustedGitEntry": "/usr/bin/git",
    "controlSources": [SAFE_GUARD, BUILDER],
    "controlSourcesFromSameCommit": True,
    "sourceTransport": "length-prefixed-in-memory-frame",
    "builderGuardInjection": "bootstrap-module-namespace",
    "guardAndBuilderSeparateProcesses": True,
    "frozenGuardDigestCheckedByParent": True,
    "pythonIsolatedMode": True,
    "childEnvironment": "allowlist-only",
    "strictChildResultValidation": True,
    "strictManifestValidation": True,
    "independentArtifactVerification": True,
    "candidateTreePathBindingRequired": True,
    "controlBlobSizeCheckedBeforeRead": True,
    "artifactBlobSizeCheckedBeforeRead": True,
    "gitCommandTimeoutSeconds": 30,
    "maximumCombinedGitOutputBytes": 8388608,
    "gitOutputLimitEnforcement": "incremental-before-process-exit",
    "childTimeoutSeconds": 180,
    "maximumChildOutputBytes": 2097152,
    "childOutputLimitScope": "combined-stdout-and-stderr",
    "childOutputLimitEnforcement": "incremental-before-process-exit",
    "stdinWriteIncludedInTimeout": True,
    "childProcessGroupTermination": True,
    "childTerminationConfirmationTimeoutSeconds": 5,
    "networkCallsPresent": False,
    "osNetworkSandboxPresent": False,
    "staticTokenChecksAreSecurityProof": False,
    "behavioralFaultInjectionRequired": True,
    "credentialsAccepted": False,
    "packageRuntimeAllowed": False,
    "registryMutationAllowed": False,
    "formalWorkflowWiringAllowed": False,
}
EXPECTED_EVIDENCE = {
    "currentLevel": "E0",
    "deploymentReady": False,
    "workflowSuccessCeiling": "E2",
    "downloadableClaimRequires": "E4",
}


def regular_research_file(root: Path, relative: str) -> bool:
    try:
        metadata = os.lstat(root / relative)
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == 0o644


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def evaluate(repo_root: Path, contract_path: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def add(name: str, passed: bool, message: str) -> None:
        checks[name] = bool(passed)
        if not passed:
            errors.append(message)

    try:
        WORKFLOW.verify_repository_layout(root)
        contract = WORKFLOW.load_json_object(
            contract_path, "immutable staging contract"
        )
    except ValueError as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "contractStatus": "invalid",
            "authorizationGranted": False,
            "checks": {},
            "errors": [str(error)],
        }

    add("top-level-fields", set(contract) == TOP_LEVEL_FIELDS,
        "contract fields are incomplete or unexpected")
    add("schema-version", contract.get("schemaVersion") == SCHEMA_VERSION,
        "schemaVersion must equal 2")
    add("research-status", contract.get("status") == STATUS,
        f"status must remain {STATUS}")
    add(
        "research-files",
        contract.get("builder") == BUILDER
        and contract.get("launcher") == LAUNCHER
        and contract.get("auditor") == AUDITOR
        and regular_research_file(root, BUILDER)
        and regular_research_file(root, LAUNCHER)
        and regular_research_file(root, AUDITOR),
        "builder, launcher, and auditor must remain regular mode-0644 research files",
    )
    evidence = contract.get("builderEvidence")
    evidence_shape = (
        isinstance(evidence, dict)
        and set(evidence) == {"baseline", "draft"}
    )
    draft_valid = False
    baseline_valid = not BUILDER_BASELINE_REQUIRED
    if evidence_shape:
        draft = evidence["draft"]
        try:
            draft_valid = (
                isinstance(draft, dict)
                and set(draft) == DRAFT_FIELDS
                and draft
                == WORKFLOW.working_file_evidence(
                    root,
                    BUILDER,
                    "immutable staging builder draft",
                )
            )
        except ValueError as error:
            errors.append(str(error))
        baseline = evidence["baseline"]
        if baseline is not None:
            try:
                baseline_valid = (
                    isinstance(baseline, dict)
                    and set(baseline) == BASELINE_FIELDS
                    and SAFE_CHECKER.check_baseline(
                        root,
                        baseline,
                        BUILDER,
                        require_worktree=False,
                    )
                )
            except ValueError as error:
                baseline_valid = False
                errors.append(str(error))
    add(
        "builder-draft",
        evidence_shape and draft_valid,
        "builder draft does not match the documented worktree source",
    )
    add(
        "builder-baseline",
        evidence_shape and baseline_valid,
        "builder baseline is missing or does not match its pinned Git blob",
    )
    launcher_evidence = contract.get("launcherEvidence")
    launcher_evidence_shape = (
        isinstance(launcher_evidence, dict)
        and set(launcher_evidence) == {"baseline", "draft"}
    )
    launcher_draft_valid = False
    launcher_baseline_valid = False
    if launcher_evidence_shape:
        launcher_draft = launcher_evidence["draft"]
        try:
            launcher_draft_valid = (
                isinstance(launcher_draft, dict)
                and set(launcher_draft) == DRAFT_FIELDS
                and launcher_draft
                == WORKFLOW.working_file_evidence(
                    root, LAUNCHER, "trusted staging launcher draft"
                )
            )
        except ValueError as error:
            errors.append(str(error))
        launcher_baseline = launcher_evidence["baseline"]
        try:
            launcher_baseline_valid = (
                isinstance(launcher_baseline, dict)
                and set(launcher_baseline) == BASELINE_FIELDS
                and SAFE_CHECKER.check_baseline(
                    root,
                    launcher_baseline,
                    LAUNCHER,
                    require_worktree=False,
                )
            )
        except ValueError as error:
            errors.append(str(error))
    add(
        "launcher-draft",
        launcher_evidence_shape and launcher_draft_valid,
        "trusted staging launcher draft does not match the worktree source",
    )
    add(
        "launcher-baseline",
        launcher_evidence_shape and launcher_baseline_valid,
        "trusted staging launcher baseline is malformed",
    )
    add("formal-workflows-unmodified",
        contract.get("formalWorkflowModified") is False,
        "formal workflows must remain unmodified")
    sections = (
        ("guard-input", "guardInput", EXPECTED_GUARD_INPUT),
        ("two-stage-anchoring", "twoStageAnchoring", EXPECTED_TWO_STAGE),
        ("filesystem-boundary", "filesystemBoundary", EXPECTED_FILESYSTEM),
        ("source-verification", "sourceAndVerification", EXPECTED_SOURCE),
        ("durability-handoff", "durabilityAndHandoff", EXPECTED_DURABILITY),
        ("outcomes", "outcomes", EXPECTED_OUTCOMES),
        ("consumer-boundary", "consumerBoundary", EXPECTED_CONSUMER),
        ("execution-boundary", "executionBoundary", EXPECTED_EXECUTION),
        ("evidence-boundary", "evidenceBoundary", EXPECTED_EVIDENCE),
    )
    for check_name, key, expected in sections:
        add(check_name, contract.get(key) == expected, f"{key} contract changed")

    try:
        safe_contract = WORKFLOW.load_json_object(
            root / SAFE_CONTRACT, "safe publish target contract"
        )
    except ValueError as error:
        safe_contract = {}
        errors.append(str(error))
    add(
        "safe-contract",
        safe_contract.get("schemaVersion") == 2
        and safe_contract.get("status") == STATUS
        and safe_contract.get("formalWorkflowModified") is False
        and safe_contract.get("guard") == SAFE_GUARD,
        "safe guard contract is missing, incompatible, or no longer research-only",
    )
    formal_valid = True
    formal = safe_contract.get("formalBaselines")
    if not isinstance(formal, dict):
        formal_valid = False
    else:
        for name, expected_path in SAFE_CHECKER.EXPECTED_FORMAL_PATHS.items():
            try:
                valid = SAFE_CHECKER.check_baseline(
                    root, formal.get(name), expected_path
                )
            except ValueError as error:
                valid = False
                errors.append(str(error))
            checks[f"formal-{name}-baseline"] = valid
            formal_valid = formal_valid and valid
    add("formal-baselines", formal_valid,
        "formal workflow baselines are incomplete or modified")

    try:
        source = (root / BUILDER).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeError, SyntaxError) as error:
        source = ""
        tree = ast.Module(body=[], type_ignores=[])
        errors.append(f"builder source cannot be parsed: {error}")
    required_tokens = (
        "validate_guard_result", "GUARD.head_package_snapshot",
        "guardResultDigest", "artifactDigest", "random_mkdirat",
        "validate_manifest", "require_same_directory_path",
        "dir_fd=parent_fd", "renameatx_np", "renameat2",
        "parent_fd, source_bytes, parent_fd, destination_bytes",
        "commit-uncertain", "failed-with-residue", "authorizationGranted",
        "remove_tree_at", "os.fsync",
    )
    forbidden_tokens = (
        "os.walk", "shutil", "tempfile", "os.rename(", "os.replace(",
        "requests", "urllib", "socket.", "shell=True", "clawhub ",
    )
    add("builder-required-primitives",
        all(token in source for token in required_tokens),
        "builder omits a complete-input, FD, digest, rename, or outcome primitive")
    add("builder-forbidden-surface",
        all(token not in source for token in forbidden_tokens),
        "builder contains forbidden traversal, mutation, network, or publish surface")
    add("builder-import-boundary",
        imported_modules(tree).isdisjoint(
            {"shutil", "tempfile", "requests", "urllib", "socket"}
        ),
        "builder imports a forbidden filesystem or network module")

    try:
        launcher_source = (root / LAUNCHER).read_text(encoding="utf-8")
        launcher_tree = ast.parse(launcher_source)
    except (OSError, UnicodeError, SyntaxError) as error:
        launcher_source = ""
        launcher_tree = ast.Module(body=[], type_ignores=[])
        errors.append(f"launcher source cannot be parsed: {error}")
    launcher_required = (
        'TRUSTED_GIT_ENTRY = Path("/usr/bin/git")',
        "CONTROL_FILES", "FRAME_MAGIC", "GUARD_BOOTSTRAP", "BUILDER_BOOTSTRAP",
        '"-I"', "child_environment", "snapshot_control",
        "validate_guard_result", "validate_child_result", "validate_manifest",
        "verify_artifact", "require_tracking_ref_consistency",
        "require_guard_tree_binding", "require_manifest_tree_binding",
        "run_bounded_child", "start_new_session=True", "os.killpg",
        "deadline = time.monotonic() + timeout_seconds",
        "total_output > maximum_output_bytes", "MAX_GIT_OUTPUT_BYTES",
        "selectors.EVENT_WRITE",
        "metadata.st_nlink != 1", "probe_artifact_state",
        "CHILD_REAP_TIMEOUT_SECONDS", "opened.st_ino",
        '"formalWorkflowWired": False',
    )
    launcher_forbidden = (
        "requests", "urllib", "socket.", "shell=True", "clawhub ",
        "importlib", "PYTHONPATH", "CLAWHUB_TOKEN",
    )
    add(
        "launcher-required-primitives",
        all(token in launcher_source for token in launcher_required),
        "launcher omits fixed Git, framing, isolation, validation, or limit primitives",
    )
    add(
        "launcher-forbidden-surface",
        all(token not in launcher_source for token in launcher_forbidden),
        "launcher contains forbidden import, secret, network, or publish surface",
    )
    add(
        "launcher-import-boundary",
        imported_modules(launcher_tree).isdisjoint(
            {"requests", "urllib", "socket", "importlib"}
        ),
        "launcher imports a forbidden dynamic-loading or network module",
    )

    return {
        "valid": not errors,
        "deploymentReady": False,
        "contractStatus": contract.get("status", "invalid"),
        "authorizationGranted": False,
        "checks": checks,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--contract",
        type=Path,
        default=RESEARCH / "immutable-staging-contract.json",
    )
    args = parser.parse_args(argv)
    result = evaluate(args.repo_root, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

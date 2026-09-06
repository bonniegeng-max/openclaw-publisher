#!/usr/bin/env python3
"""Offline auditor for the research-only trusted artifact consumer."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any


RESEARCH = Path(__file__).resolve().parent
ROOT = RESEARCH.parents[1]
CONSUMER = (
    "research/skill-release-authorization-vnext/"
    "trusted_artifact_publish_consumer.py"
)
AUDITOR = (
    "research/skill-release-authorization-vnext/"
    "check_trusted_artifact_publish_consumer_contract.py"
)
CONTRACT = (
    "research/skill-release-authorization-vnext/"
    "trusted-artifact-publish-consumer-contract.json"
)
TEST = "tests/test_trusted_artifact_publish_consumer.py"
TOP_LEVEL_FIELDS = {
    "schemaVersion", "status", "consumer", "auditor", "formalWorkflowModified",
    "inputBinding", "artifactBoundary", "cliBoundary", "failurePolicy",
    "repositoryBoundary", "evidenceBoundary", "consumerEvidence",
    "auditorEvidence", "twoStageAnchoring",
}
DRAFT_FIELDS = {"path", "mode", "sha256"}
BASELINE_FIELDS = {"path", "commit", "mode", "blobOid", "sha256"}
EXPECTED_TWO_STAGE_BASE = {
    "stageOne": "worktree-draft-sha256-audited",
    "stageTwo": "post-commit-baseline-commit-mode-blobOid-sha256-required",
    "deploymentBlockedUntilStageTwo": True,
    "deploymentRemainsBlockedAfterStageTwo": True,
    "remoteCommitVerified": False,
}
EXPECTED_INPUT = {
    "authorization": "complete-trusted-preflight-result",
    "staging": "complete-trusted-staging-result",
    "catalog": "strict-json-snapshot",
    "requiredMode": "dry-run",
    "requiredAuthorization": True,
    "requiredStagingStatus": "committed",
    "requiredArtifactState": "present-verified-snapshot",
    "singleTargetOnly": True,
    "expectedControlCommitRequired": True,
    "expectedHeadCommitRequired": True,
    "candidateRootRequired": True,
    "controlRootRequired": True,
    "independentCheckoutRequired": True,
    "independentGitCommonDirectoryRequired": True,
    "sharedObjectStoreAllowed": False,
    "objectAlternatesAllowed": False,
    "objectStoreComponentValidation": "owner-mode-symlink-hardlink-identity",
    "fixedGitExecutable": "/usr/bin/git",
    "gitWallClockTimeoutSeconds": 30,
    "gitMaximumCombinedOutputBytes": 12582912,
    "originHeadTrackingRefVerified": True,
    "authorizationCommitChainVerified": True,
    "manifestGitTreeFilesBlobsVerified": True,
    "preflightControlEvidenceVerified": True,
    "stagingControlEvidenceModeVerified": True,
    "commitMatch": "authorization.headCommit=manifest.source.commit",
    "slugMatch": "authorization.target.slug=manifest.source.skillPath-basename",
    "versionMatch": "authorization.target.version=verified-package-SKILL.md-version",
    "catalogMatch": "catalog.skills/slug supplies displayName/categories/topics",
    "authorizationEvaluatedAtType": "non-empty-string",
    "authorizationCatalogChangedType": "boolean",
    "contentDigestRecomputed":
        "target-catalog-entry-plus-all-verified-package-files",
    "trustedControlStrictValidation": True,
    "launcherObservationsStrictValidation": True,
    "authorizationMaximumAgeSeconds": 900,
    "authorizationMaximumFutureSkewSeconds": 300,
    "authorizationProvenance":
        "content-validated-self-asserted-input-not-launcher-attested",
    "authorizationProvenanceVerified": False,
    "oneTimeRunReplayProtection": False,
    "realMutationAllowed": False,
    "trustUpgradeRequired":
        "external-launcher-pinned-to-verified-control-blob",
}
EXPECTED_ARTIFACT = {
    "artifactParentMode": "0700",
    "artifactParentOwner": "current-user",
    "pathTraversal": "dir-fd-relative-O_NOFOLLOW",
    "manifestStrictValidation": True,
    "manifestDigestRevalidation": True,
    "packageDigestRevalidation": True,
    "exactFileSetRequired": True,
    "fileDigestRevalidation": True,
    "ownerModeNlinkInodeValidation": True,
    "beforeAfterReadFdValidation": True,
    "postConsumptionAllFdValidation": True,
    "postCheckPreventsPriorMutation": False,
    "postCheckLimitation":
        "detects-after-return-only-cannot-protect-against-already-performed-mutation",
    "pathIdentityRevalidation": True,
    "verifiedPackageFdRetained": True,
    "consumerInput": "same-verified-package-directory-fd",
    "pathReopenForConsumption": False,
    "symlinks": "reject",
    "hardlinks": "reject",
}
EXPECTED_CLI = {
    "default": "simulation-only",
    "realCliAllowed": False,
    "realCliPackageAccessRequirement": "fd-native-or-read-only-isolated-copy",
    "mutationCapableRealCliAllowed": False,
    "realMutationBlockedByUnverifiedAuthorizationProvenance": True,
    "realMutationBlockedByMissingOneTimeReplayProtection": True,
    "externalPinnedBlobLauncherRequired": True,
    "packageFdPassedExplicitly": True,
    "passFdsRequired": True,
    "pythonIsolatedMode": True,
    "childEnvironment": "allowlist-only",
    "stdin": "devnull",
    "childProcessGroup": True,
    "timeoutSeconds": 30,
    "maximumCombinedOutputBytes": 1048576,
    "stderrAllowed": False,
    "credentialsAccepted": False,
    "networkCallsPresent": False,
    "osNetworkSandboxPresent": False,
    "publicationAttempted": False,
}
EXPECTED_FAILURE = {
    "unknownOrMissingFields": "reject",
    "duplicateJsonKeys": "reject",
    "nonFiniteJsonNumbers": "reject",
    "invalidState": "reject",
    "mismatch": "reject",
    "timeout": "terminate-process-group-and-reject",
    "outputOverflow": "terminate-process-group-and-reject",
    "fastExitBeforeKillpg": "reap-without-retargeting-process-group",
    "terminationFailure": "structured-rejection",
    "leaderReapConfirmation": True,
    "exitCodeSuccess": 0,
    "exitCodeRejected": 2,
    "authorizationGrantedByConsumer": False,
    "forgedAuthorizationClaims": "simulation-only-never-authorize-mutation",
}
EXPECTED_REPOSITORY = {
    "formalWorkflows": "unchanged",
    "skillsDirectory": "unchanged",
    "catalog": "unchanged",
    "researchOnlyFiles": [CONSUMER, CONTRACT, AUDITOR, TEST],
}
EXPECTED_EVIDENCE_BASE = {
    "currentLevel": "E0",
    "deploymentReady": False,
    "consumerDeploymentAllowed": False,
    "formalWorkflowWired": False,
    "downloadableClaimAllowed": False,
    "oneTimeRunReplayProtection": False,
    "authorizationProvenanceVerified": False,
    "realMutationAllowed": False,
    "externalPinnedBlobLauncherRequired": True,
}


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def load_contract(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("consumer contract must not be a symlink")
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"consumer contract is not strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("consumer contract must be a JSON object")
    return value


def regular_mode_0644(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o644
    )


def working_file_evidence(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o644
    ):
        raise ValueError(f"draft evidence source is not regular mode-0644: {relative}")
    return {
        "path": relative,
        "mode": "100644",
        "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def baseline_evidence_matches(
    root: Path,
    value: Any,
    relative: str,
    draft: dict[str, str],
) -> bool:
    if value is None:
        return False
    if not isinstance(value, dict) or set(value) != BASELINE_FIELDS:
        return False
    if (
        value["path"] != relative
        or value["mode"] not in {"100644", "100755"}
        or not isinstance(value["commit"], str)
        or not isinstance(value["blobOid"], str)
        or value["mode"] != draft["mode"]
        or value["sha256"] != draft["sha256"]
    ):
        return False
    completed = subprocess.run(
        [
            "/usr/bin/git", "--no-replace-objects",
            "-c", "core.fsmonitor=false",
            "-c", f"core.hooksPath={os.devnull}",
            "ls-tree", "-z", value["commit"], "--", relative,
        ],
        cwd=root,
        env=git_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    records = [record for record in completed.stdout.split(b"\0") if record]
    if completed.returncode != 0 or len(records) != 1:
        return False
    try:
        metadata, observed = records[0].split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        observed_path = observed.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError):
        return False
    blob = subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", "cat-file", "blob", oid],
        cwd=root,
        env=git_environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return (
        kind == "blob"
        and observed_path == relative
        and mode == value["mode"]
        and oid == value["blobOid"]
        and blob.returncode == 0
        and "sha256:" + hashlib.sha256(blob.stdout).hexdigest() == value["sha256"]
    )


def evidence_matches(
    root: Path,
    value: Any,
    relative: str,
) -> tuple[bool, bool]:
    if not isinstance(value, dict) or set(value) != {"baseline", "draft"}:
        return False, False
    draft = working_file_evidence(root, relative)
    if (
        not isinstance(value["draft"], dict)
        or set(value["draft"]) != DRAFT_FIELDS
        or value["draft"] != draft
    ):
        return False, False
    if value["baseline"] is None:
        return True, False
    matched = baseline_evidence_matches(root, value["baseline"], relative, draft)
    return matched, matched


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def git_environment() -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def protected_paths_unchanged(root: Path) -> bool:
    completed = subprocess.run(
        [
            "/usr/bin/git", "--no-replace-objects",
            "-c", "core.fsmonitor=false",
            "-c", f"core.hooksPath={os.devnull}",
            "diff", "--quiet", "HEAD", "--",
            ".github/workflows", "skills", ".clawhub/skill-catalog.json",
        ],
        cwd=root,
        env=git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return False
    status = subprocess.run(
        [
            "/usr/bin/git", "--no-replace-objects",
            "-c", "core.fsmonitor=false",
            "-c", f"core.hooksPath={os.devnull}",
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--",
            ".github/workflows", "skills", ".clawhub/skill-catalog.json",
        ],
        cwd=root,
        env=git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    return status.returncode == 0 and not status.stdout


def evaluate(root: Path, contract_path: Path) -> dict[str, Any]:
    root = root.resolve()
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def add(name: str, passed: bool, message: str) -> None:
        checks[name] = bool(passed)
        if not passed:
            errors.append(message)

    try:
        contract = load_contract(contract_path)
    except ValueError as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "contractStatus": "invalid",
            "authorizationGranted": False,
            "checks": {},
            "errors": [str(error)],
        }

    add(
        "top-level-fields",
        set(contract) == TOP_LEVEL_FIELDS,
        "contract fields are incomplete or unexpected",
    )
    add("schema-version", contract.get("schemaVersion") == 2,
        "schemaVersion must equal 2")
    add(
        "research-status",
        contract.get("status") == "research-only-not-wired",
        "status must remain research-only-not-wired",
    )
    add(
        "research-files",
        contract.get("consumer") == CONSUMER
        and contract.get("auditor") == AUDITOR
        and regular_mode_0644(root / CONSUMER)
        and regular_mode_0644(root / AUDITOR)
        and regular_mode_0644(root / CONTRACT)
        and regular_mode_0644(root / TEST),
        "consumer, contract, auditor, and tests must be regular mode-0644 files",
    )
    add(
        "formal-workflow-flag",
        contract.get("formalWorkflowModified") is False,
        "formalWorkflowModified must remain false",
    )
    try:
        consumer_evidence_valid, consumer_pinned = evidence_matches(
            root, contract.get("consumerEvidence"), CONSUMER
        )
    except (OSError, ValueError):
        consumer_evidence_valid = False
        consumer_pinned = False
    add(
        "consumer-draft-evidence",
        consumer_evidence_valid,
        "consumer evidence must match the worktree and any pinned Git baseline",
    )
    try:
        auditor_evidence_valid, auditor_pinned = evidence_matches(
            root, contract.get("auditorEvidence"), AUDITOR
        )
    except (OSError, ValueError):
        auditor_evidence_valid = False
        auditor_pinned = False
    add(
        "auditor-draft-evidence",
        auditor_evidence_valid,
        "auditor evidence must match the worktree and any pinned Git baseline",
    )
    both_pinned = consumer_pinned and auditor_pinned
    expected_two_stage = {
        **EXPECTED_TWO_STAGE_BASE,
        "localIntegrityPinned": both_pinned,
    }
    add(
        "two-stage-anchoring",
        contract.get("twoStageAnchoring") == expected_two_stage,
        "two-stage anchoring does not match the actual pinned baseline state",
    )
    expected_evidence = {
        **EXPECTED_EVIDENCE_BASE,
        "consumerBaselinePinned": consumer_pinned,
        "auditorBaselinePinned": auditor_pinned,
    }
    for name, key, expected in (
        ("input-binding", "inputBinding", EXPECTED_INPUT),
        ("artifact-boundary", "artifactBoundary", EXPECTED_ARTIFACT),
        ("cli-boundary", "cliBoundary", EXPECTED_CLI),
        ("failure-policy", "failurePolicy", EXPECTED_FAILURE),
        ("repository-boundary", "repositoryBoundary", EXPECTED_REPOSITORY),
        ("evidence-boundary", "evidenceBoundary", expected_evidence),
    ):
        add(name, contract.get(key) == expected, f"{key} contract changed")

    try:
        source = (root / CONSUMER).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeError, SyntaxError) as error:
        source = ""
        tree = ast.Module(body=[], type_ignores=[])
        errors.append(f"consumer source cannot be parsed: {error}")
    required = (
        "open_verified_package", "validate_authorization", "validate_staging",
        "validate_manifest", "validate_catalog", "package_version",
        "recompute_content_digest", "verified.revalidate_all()",
        '"allManifestFilesVerified": True', '"categories": expected["categories"]',
        '"topics": expected["topics"]', 'type(value["catalogChanged"]) is not bool',
        'parse_timestamp(value["evaluatedAt"]',
        "--expected-control-commit", "--expected-head-commit",
        "--candidate-root", "--control-root", 'Path("/usr/bin/git")',
        "verify_git_bindings", "git_tree_files", "verify_control_evidence",
        "MAX_AUTHORIZATION_AGE", "MAX_GIT_OUTPUT_BYTES = 12 * 1024 * 1024",
        '"oneTimeRunReplayProtection": False',
        '"authorizationContentValidated": True',
        '"authorizationContentValidated": False',
        '"authorizationProvenanceVerified": False',
        '"realMutationAllowed": False',
        '"external-launcher-pinned-to-verified-control-blob"',
        '"leaderReaped": observed_returncode is not None', "process.poll()",
        "pass_fds=(package_fd,)", "start_new_session=True", "os.killpg",
        "validate_private_object_store", '"--git-common-dir"',
        '"--git-path", "objects"', '"alternates"',
        "selectors.DefaultSelector", "O_NOFOLLOW", "dir_fd=",
        '"publicationAttempted": False', '"networkUsed": False',
        '"credentialsAccepted": False', '"cliMode": "simulation-only"',
    )
    forbidden = (
        "requests", "urllib", "socket.", "http://", "https://",
        "CLAWHUB_TOKEN", "GITHUB_TOKEN", "shell=True", "clawhub ",
        ".github/workflows/", "skills/skill-", "skill-catalog.json",
    )
    add(
        "consumer-required-primitives",
        all(token in source for token in required),
        "consumer omits an FD, binding, limit, or simulation primitive",
    )
    add(
        "consumer-authorization-content-label",
        ("authorization" + "Validated") not in source,
        "consumer uses the ambiguous legacy authorization validation label",
    )
    add(
        "consumer-forbidden-surface",
        all(token not in source for token in forbidden),
        "consumer contains a network, token, real CLI, workflow, Skill, or catalog surface",
    )
    add(
        "consumer-import-boundary",
        imported_modules(tree).isdisjoint(
            {"requests", "urllib", "socket", "http", "ssl"}
        ),
        "consumer imports a network-capable module",
    )
    try:
        unchanged = protected_paths_unchanged(root)
    except (OSError, subprocess.TimeoutExpired):
        unchanged = False
    add(
        "protected-paths-unchanged",
        unchanged,
        "formal workflows, skills, or catalog differ from HEAD",
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
    parser.add_argument("--contract", type=Path, default=RESEARCH / Path(CONTRACT).name)
    args = parser.parse_args(argv)
    result = evaluate(args.repo_root, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

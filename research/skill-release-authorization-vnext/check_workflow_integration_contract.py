#!/usr/bin/env python3
"""Validate the offline-only release workflow integration contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_STATUS = "offline-contract-ready-not-wired"
EXPECTED_REPOSITORY = "bonniegeng-max/openclaw-publisher"
EXPECTED_CALLER = ".github/workflows/clawhub-skill-publish.yml"
EXPECTED_REUSABLE = (
    ".github/workflows/clawhub-skill-publish-authorized.yml"
)
EXPECTED_CONTROL_FILES = {
    "scripts/check_skill_release_authorization.py",
    "scripts/validate_skill_catalog.py",
}
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "status",
    "targetRepository",
    "formalWorkflows",
    "trustedControl",
    "trustedControlExecution",
    "trustedReusableWorkflow",
    "trustedClawHubCli",
    "environments",
    "controlledRun",
    "evidencePolicy",
}
REQUIRED_ENVIRONMENT_RULES = {
    "requiredReviewer": True,
    "preventSelfReview": True,
    "adminBypassDisabled": True,
    "protectedMainOnly": True,
    "environmentSecret": "CLAWHUB_TOKEN",
}
REQUIRED_EVIDENCE_POLICY = {
    "currentLevel": "E0",
    "workflowSuccessCeiling": "E2",
    "registryModerationRequiredFor": "E3",
    "isolatedInstallRequiredFor": "E4",
    "downloadableClaimRequires": "E4",
}


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"{label} contains invalid JSON constant: {value}")

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"{label} cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def safe_repo_path(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} must be a non-empty repository path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{label} must stay inside the repository")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes the repository") from error
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not contain symlinks")
    return resolved


def digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def git_bytes(root: Path, commit: str, relative: str) -> bytes:
    try:
        object_type = subprocess.run(
            ["git", "cat-file", "-t", commit],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "origin/main"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        entry = subprocess.run(
            ["git", "ls-tree", commit, "--", relative],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise ValueError(f"trusted control Git verification failed: {error}") from error
    if object_type.returncode != 0 or object_type.stdout.strip() != "commit":
        raise ValueError("trusted control anchor must identify a Git commit")
    if ancestor.returncode != 0:
        raise ValueError(
            "trusted control commit must be reachable from origin/main"
        )
    entry_parts = entry.stdout.strip().split(maxsplit=3)
    if (
        entry.returncode != 0
        or len(entry_parts) != 4
        or entry_parts[0] not in {"100644", "100755"}
        or entry_parts[1] != "blob"
        or entry_parts[3] != relative
    ):
        raise ValueError(
            f"trusted control path must be a regular Git blob: {relative}"
        )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"trusted control file is unavailable at {commit}:{relative}: "
            f"{message}"
        )
    return completed.stdout


def origin_repository(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ValueError(f"origin repository cannot be verified: {error}") from error
    if completed.returncode != 0:
        raise ValueError("origin repository cannot be verified")
    value = completed.stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)"
        r"([^/]+/[^/]+?)(?:\.git)?",
        value,
    )
    if match is None:
        raise ValueError("origin must be an explicit GitHub repository URL")
    return match.group(1)


def add_check(
    checks: dict[str, bool],
    errors: list[str],
    name: str,
    passed: bool,
    message: str,
) -> None:
    checks[name] = bool(passed)
    if not passed:
        errors.append(message)


def evaluate(repo_root: Path, contract_path: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    checks: dict[str, bool] = {}
    errors: list[str] = []
    blockers: list[str] = []
    local_evidence: dict[str, Any] = {}
    try:
        contract = load_json_object(contract_path, "workflow integration contract")
    except ValueError as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "contractStatus": "invalid",
            "checks": {},
            "localEvidence": {},
            "blockingGates": [],
            "errors": [str(error)],
        }

    add_check(
        checks,
        errors,
        "top-level-fields",
        set(contract) == TOP_LEVEL_FIELDS,
        "workflow integration contract fields are incomplete or unexpected",
    )
    add_check(
        checks,
        errors,
        "schema-version",
        type(contract.get("schemaVersion")) is int
        and contract.get("schemaVersion") == 1,
        "schemaVersion must equal 1",
    )
    add_check(
        checks,
        errors,
        "offline-status",
        contract.get("status") == EXPECTED_STATUS,
        f"status must remain {EXPECTED_STATUS} before formal wiring",
    )
    try:
        observed_repository = origin_repository(root)
    except ValueError as error:
        observed_repository = None
        errors.append(str(error))
    add_check(
        checks,
        errors,
        "target-repository",
        contract.get("targetRepository") == EXPECTED_REPOSITORY
        and observed_repository == EXPECTED_REPOSITORY,
        (
            f"targetRepository and origin must both equal "
            f"{EXPECTED_REPOSITORY}"
        ),
    )
    local_evidence["originRepository"] = observed_repository

    formal = contract.get("formalWorkflows")
    formal_valid = isinstance(formal, dict) and set(formal) == {
        "caller",
        "authorizedReusable",
        "wired",
        "callerSha256",
        "reusableSha256",
        "semanticReviewEvidence",
    }
    if formal_valid:
        formal_valid = (
            formal["caller"] == EXPECTED_CALLER
            and formal["authorizedReusable"] == EXPECTED_REUSABLE
            and formal["wired"] is False
            and isinstance(formal["callerSha256"], str)
            and DIGEST_PATTERN.fullmatch(formal["callerSha256"]) is not None
            and formal["reusableSha256"] is None
            and formal["semanticReviewEvidence"] is None
        )
    add_check(
        checks,
        errors,
        "formal-workflows-not-wired",
        formal_valid,
        "formal workflow state must remain explicitly unwired and unverified",
    )
    if formal_valid:
        try:
            caller_path = safe_repo_path(root, formal["caller"], "caller workflow")
            reusable_path = safe_repo_path(
                root,
                formal["authorizedReusable"],
                "authorized reusable workflow",
            )
            caller_content = caller_path.read_bytes()
            hold_intact = (
                not reusable_path.exists()
                and digest_bytes(caller_content) == formal["callerSha256"]
            )
        except (OSError, UnicodeError, ValueError):
            hold_intact = False
    else:
        hold_intact = False
    add_check(
        checks,
        errors,
        "observation-hold-intact",
        hold_intact,
        "formal publish workflows changed before the deferred integration review",
    )
    local_evidence["formalWorkflowWired"] = False
    blockers.append("formal-workflow-wiring")

    control = contract.get("trustedControl")
    control_shape = isinstance(control, dict) and set(control) == {
        "repository",
        "commit",
        "files",
    }
    control_anchor_verified = False
    if control_shape:
        files = control["files"]
        control_shape = (
            control["repository"] == EXPECTED_REPOSITORY
            and isinstance(files, list)
            and len(files) == len(EXPECTED_CONTROL_FILES)
            and all(
                isinstance(item, dict)
                and set(item) == {"path", "sha256"}
                for item in files
            )
            and all(
                isinstance(item["path"], str)
                and (
                    item["sha256"] is None
                    or isinstance(item["sha256"], str)
                )
                for item in files
            )
            and {item["path"] for item in files} == EXPECTED_CONTROL_FILES
        )
    add_check(
        checks,
        errors,
        "trusted-control-shape",
        control_shape,
        "trustedControl must describe the expected repository and control files",
    )
    if control_shape:
        commit = control["commit"]
        if commit is None:
            if any(item["sha256"] is not None for item in control["files"]):
                errors.append(
                    "trusted control digests must remain null until commit is pinned"
                )
        elif not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
            errors.append("trusted control commit must be a full lowercase SHA-1")
        else:
            try:
                observed = {
                    item["path"]: digest_bytes(
                        git_bytes(root, commit, item["path"])
                    )
                    for item in control["files"]
                }
                declared = {
                    item["path"]: item["sha256"]
                    for item in control["files"]
                }
                if any(
                    not isinstance(value, str)
                    or DIGEST_PATTERN.fullmatch(value) is None
                    for value in declared.values()
                ):
                    errors.append(
                        "trusted control file digests must be lowercase sha256 values"
                    )
                elif observed != declared:
                    errors.append(
                        "trusted control file digests do not match the pinned commit"
                    )
                else:
                    control_anchor_verified = True
            except ValueError as error:
                errors.append(str(error))
    checks["trusted-control-anchor"] = control_anchor_verified
    local_evidence["trustedControlAnchorVerified"] = control_anchor_verified
    if not control_anchor_verified:
        blockers.append("trusted-control-anchor")

    control_execution = contract.get("trustedControlExecution")
    control_execution_hold = control_execution == {
        "verified": False,
        "evidence": None,
    }
    add_check(
        checks,
        errors,
        "trusted-control-execution-not-claimed",
        control_execution_hold,
        "trusted control execution must remain unverified until atomic checker and validator binding exists",
    )
    blockers.append("trusted-control-execution")

    reusable = contract.get("trustedReusableWorkflow")
    reusable_hold = isinstance(reusable, dict) and reusable == {
        "repository": EXPECTED_REPOSITORY,
        "path": EXPECTED_REUSABLE,
        "commit": None,
        "verified": False,
    }
    add_check(
        checks,
        errors,
        "trusted-reusable-not-claimed",
        reusable_hold,
        "trusted reusable workflow must remain unverified until a real commit exists",
    )
    blockers.append("trusted-reusable-workflow")

    cli = contract.get("trustedClawHubCli")
    cli_hold = isinstance(cli, dict) and cli == {
        "repository": "openclaw/clawhub",
        "commit": None,
        "verified": False,
    }
    add_check(
        checks,
        errors,
        "trusted-clawhub-cli-not-claimed",
        cli_hold,
        "ClawHub CLI must remain unverified until a reviewed immutable commit is pinned",
    )
    blockers.append("trusted-clawhub-cli")

    environments = contract.get("environments")
    environments_valid = (
        isinstance(environments, dict)
        and set(environments) == {"validation", "production"}
    )
    if environments_valid:
        for key, expected_name in (
            ("validation", "clawhub-validation"),
            ("production", "clawhub-production"),
        ):
            value = environments[key]
            valid = (
                isinstance(value, dict)
                and set(value)
                == {
                    "name",
                    "configurationVerified",
                    "evidence",
                    "requirements",
                }
                and value["name"] == expected_name
                and value["configurationVerified"] is False
                and value["evidence"] is None
                and value["requirements"] == REQUIRED_ENVIRONMENT_RULES
            )
            checks[f"{key}-environment-not-claimed"] = valid
            if not valid:
                errors.append(
                    f"{expected_name} must remain unverified until external evidence exists"
                )
            blockers.append(f"{key}-environment")
    else:
        errors.append("environments must define validation and production")
    checks["environment-contract"] = environments_valid
    local_evidence["environmentConfigurationVerified"] = False

    controlled_run = contract.get("controlledRun")
    controlled_run_valid = controlled_run == {
        "verified": False,
        "evidence": None,
    }
    add_check(
        checks,
        errors,
        "controlled-run-not-claimed",
        controlled_run_valid,
        "controlled run must remain unverified until external evidence exists",
    )
    blockers.append("controlled-run")

    add_check(
        checks,
        errors,
        "evidence-policy",
        contract.get("evidencePolicy") == REQUIRED_EVIDENCE_POLICY,
        "evidence policy must preserve E0-E4 claim boundaries",
    )
    local_evidence["currentEvidenceLevel"] = "E0"

    return {
        "valid": not errors,
        "deploymentReady": False,
        "contractStatus": contract.get("status", "invalid"),
        "checks": checks,
        "localEvidence": local_evidence,
        "blockingGates": list(dict.fromkeys(blockers)),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    research = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=research.parents[1],
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=research / "workflow-integration-contract.json",
    )
    args = parser.parse_args(argv)
    result = evaluate(args.repo_root, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    return 0 if result["deploymentReady"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

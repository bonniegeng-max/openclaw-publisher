#!/usr/bin/env python3
"""Validate the offline-only release workflow integration contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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


def git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_EXTERNAL_DIFF": "",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def git_command(*args: str) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "diff.external=",
        *args,
    ]


def run_git(
    root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        git_command(*args),
        cwd=root,
        env=git_environment(),
        check=False,
        capture_output=True,
        text=text,
    )


def verify_repository_layout(root: Path) -> None:
    git_entry = root / ".git"
    objects = git_entry / "objects"
    try:
        git_entry_mode = os.lstat(git_entry).st_mode
    except OSError as error:
        raise ValueError(f"repository Git layout cannot be inspected: {error}") from error
    if not stat.S_ISDIR(git_entry_mode) or git_entry.is_symlink():
        raise ValueError("repository .git must be a local directory")
    try:
        objects_mode = os.lstat(objects).st_mode
    except OSError as error:
        raise ValueError(f"repository object store cannot be inspected: {error}") from error
    if not stat.S_ISDIR(objects_mode) or objects.is_symlink():
        raise ValueError("repository object store must be a local directory")

    try:
        top_level_result = run_git(
            root,
            "rev-parse",
            "--show-toplevel",
            text=True,
        )
        git_dir_result = run_git(
            root,
            "rev-parse",
            "--absolute-git-dir",
            text=True,
        )
        common_dir_result = run_git(
            root,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            text=True,
        )
    except OSError as error:
        raise ValueError(f"repository Git layout cannot be verified: {error}") from error
    for label, completed in (
        ("top-level", top_level_result),
        ("git-dir", git_dir_result),
        ("common-dir", common_dir_result),
    ):
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise ValueError(
                f"repository Git {label} cannot be verified: {message}"
            )
    if Path(top_level_result.stdout.strip()).resolve() != root:
        raise ValueError("repo-root must equal the Git top-level directory")
    expected_git_dir = git_entry.resolve()
    observed_git_dir = Path(git_dir_result.stdout.strip()).resolve()
    observed_common_dir = Path(common_dir_result.stdout.strip()).resolve()
    if observed_git_dir != expected_git_dir:
        raise ValueError("repository must use its own .git directory")
    if observed_common_dir != observed_git_dir:
        raise ValueError("repository must not use a shared Git common directory")

    alternates = objects / "info" / "alternates"
    if alternates.exists() or alternates.is_symlink():
        raise ValueError("repository object store must not use alternates")


def git_blob_evidence(
    root: Path,
    commit: str,
    relative: str,
) -> dict[str, str]:
    try:
        object_type = run_git(root, "cat-file", "-t", commit, text=True)
        ancestor = run_git(
            root,
            "merge-base",
            "--is-ancestor",
            commit,
            "origin/main",
            text=True,
        )
        entry = run_git(root, "ls-tree", "-z", commit, "--", relative)
    except OSError as error:
        raise ValueError(f"trusted control Git verification failed: {error}") from error
    if object_type.returncode != 0 or object_type.stdout.strip() != "commit":
        raise ValueError("trusted control anchor must identify a Git commit")
    if ancestor.returncode != 0:
        raise ValueError(
            "trusted control commit must be reachable from origin/main"
        )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError(
            f"trusted control path must be a regular Git blob: {relative}"
        )
    try:
        metadata, observed_path = records[0].split(b"\t", 1)
        mode, entry_type, object_id = metadata.split(b" ", 2)
        observed_relative = observed_path.decode("utf-8", errors="strict")
        mode_text = mode.decode("ascii")
        object_id_text = object_id.decode("ascii")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(
            f"trusted control path has malformed Git metadata: {relative}"
        ) from error
    if (
        mode_text not in {"100644", "100755"}
        or entry_type != b"blob"
        or observed_relative != relative
        or COMMIT_PATTERN.fullmatch(object_id_text) is None
    ):
        raise ValueError(
            f"trusted control path must be a regular Git blob: {relative}"
        )
    try:
        completed = run_git(root, "cat-file", "blob", object_id_text)
    except OSError as error:
        raise ValueError(f"trusted control Git verification failed: {error}") from error
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"trusted control blob is unavailable at {commit}:{relative}: "
            f"{message}"
        )
    return {
        "path": relative,
        "mode": mode_text,
        "blobOid": object_id_text,
        "sha256": digest_bytes(completed.stdout),
    }


def origin_repository(root: Path) -> str:
    try:
        completed = run_git(
            root,
            "config",
            "--local",
            "--no-includes",
            "--get-all",
            "remote.origin.url",
            text=True,
        )
    except OSError as error:
        raise ValueError(f"origin repository cannot be verified: {error}") from error
    if completed.returncode != 0:
        raise ValueError("origin repository cannot be verified")
    values = [value for value in completed.stdout.splitlines() if value]
    if len(values) != 1:
        raise ValueError("origin must define exactly one fetch URL")
    value = values[0]
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
    try:
        verify_repository_layout(root)
    except ValueError as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "contractStatus": contract.get("status", "invalid"),
            "checks": {"repository-layout": False},
            "localEvidence": {},
            "blockingGates": [],
            "errors": [str(error)],
        }
    checks["repository-layout"] = True

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
    control_anchor_consistent = False
    if control_shape:
        files = control["files"]
        control_shape = (
            control["repository"] == EXPECTED_REPOSITORY
            and isinstance(files, list)
            and len(files) == len(EXPECTED_CONTROL_FILES)
            and all(
                isinstance(item, dict)
                and set(item) == {"path", "mode", "blobOid", "sha256"}
                for item in files
            )
            and all(
                isinstance(item["path"], str)
                and (
                    item["mode"] is None
                    or (
                        isinstance(item["mode"], str)
                        and re.fullmatch(r"[0-9]{6}", item["mode"]) is not None
                    )
                )
                and (
                    item["blobOid"] is None
                    or (
                        isinstance(item["blobOid"], str)
                        and COMMIT_PATTERN.fullmatch(item["blobOid"]) is not None
                    )
                )
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
            if any(
                item["sha256"] is not None
                or item["blobOid"] is not None
                or item["mode"] is not None
                for item in control["files"]
            ):
                errors.append(
                    "trusted control file evidence must remain null until commit is pinned"
                )
        elif not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
            errors.append("trusted control commit must be a full lowercase SHA-1")
        else:
            try:
                observed = {
                    item["path"]: git_blob_evidence(
                        root,
                        commit,
                        item["path"],
                    )
                    for item in control["files"]
                }
                declared = {
                    item["path"]: item
                    for item in control["files"]
                }
                if any(
                    not isinstance(value, str)
                    or DIGEST_PATTERN.fullmatch(value) is None
                    for value in (
                        item["sha256"] for item in declared.values()
                    )
                ):
                    errors.append(
                        "trusted control file digests must be lowercase sha256 values"
                    )
                elif observed != declared:
                    errors.append(
                        "trusted control file evidence does not match the pinned commit"
                    )
                else:
                    control_anchor_consistent = True
            except ValueError as error:
                errors.append(str(error))
    checks["local-control-anchor"] = control_anchor_consistent
    local_evidence["controlAnchorLocallyConsistent"] = (
        control_anchor_consistent
    )
    if not control_anchor_consistent:
        blockers.append("local-control-anchor")

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

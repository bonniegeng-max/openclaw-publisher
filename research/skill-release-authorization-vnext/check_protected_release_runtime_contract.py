#!/usr/bin/env python3
"""Offline audit for the research-only protected release runtime contract."""

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


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
WORKFLOW_REF_PATTERN = re.compile(
    r"^[^/@\s]+/[^/@\s]+/\.github/workflows/[^@\s]+@([0-9a-f]{40})$"
)
TRUSTED_GIT = Path("/usr/bin/git")
AUDITOR_PATH = (
    "research/skill-release-authorization-vnext/"
    "check_protected_release_runtime_contract.py"
)
SUPPORTED_SCHEMA_VERSION = 1
EXPECTED_STATUS = "research-only-not-wired"
RUN_IDENTITY_FIELDS = (
    "repository_id",
    "workflow_ref",
    "workflow_sha",
    "run_id",
    "run_attempt",
    "job",
    "environment",
)
RESERVATION_KEY_FIELDS = (
    "repository_id",
    "environment",
    "release_id",
    "artifact_digest",
)
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "status",
    "realMutation",
    "runIdentity",
    "workflowTrust",
    "environmentAuthentication",
    "concurrency",
    "replayProtection",
    "currentImplementation",
    "auditorEvidence",
    "twoStageAnchoring",
    "evidenceBoundary",
}
EVIDENCE_FIELDS = {
    "releaseIdentity",
    "runIdentity",
    "environmentApproval",
    "workflowTrust",
    "concurrency",
    "ledgerReservation",
}


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"{label} has duplicate key: {key}")
            value[key] = item
        return value

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


def canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def repository_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or relative != AUDITOR_PATH:
        raise ValueError("auditor draft path is not the protected runtime auditor")
    candidate = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("auditor draft path must not contain symlinks")
    if not candidate.is_file():
        raise ValueError("auditor draft must be a regular file")
    return candidate


def file_mode(path: Path) -> str:
    value = os.lstat(path).st_mode
    if not stat.S_ISREG(value):
        raise ValueError("auditor draft must be a regular file")
    return "100755" if value & stat.S_IXUSR else "100644"


def git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        git_mode = os.lstat(TRUSTED_GIT).st_mode
    except OSError as error:
        raise ValueError(f"fixed Git entry cannot be inspected: {error}") from error
    if (
        not stat.S_ISREG(git_mode)
        or TRUSTED_GIT.is_symlink()
        or not os.access(TRUSTED_GIT, os.X_OK)
    ):
        raise ValueError("fixed Git entry must be an executable regular file")
    return subprocess.run(
        [
            str(TRUSTED_GIT),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            *args,
        ],
        cwd=root,
        env=git_environment(),
        check=False,
        capture_output=True,
    )


def validate_auditor_evidence(
    root: Path,
    evidence: Any,
    anchoring: Any,
) -> tuple[bool, str]:
    if not isinstance(anchoring, dict):
        return False, "twoStageAnchoring must be an object"
    if not isinstance(evidence, dict) or set(evidence) != {"baseline", "draft"}:
        return False, "auditorEvidence must contain only baseline and draft"
    draft = evidence["draft"]
    required = {"path", "commit", "mode", "blobOid", "sha256"}
    if (
        not isinstance(draft, dict)
        or set(draft) != required
        or draft.get("commit") is not None
        or draft.get("blobOid") is not None
        or draft.get("mode") not in {"100644", "100755"}
        or not isinstance(draft.get("sha256"), str)
        or DIGEST_PATTERN.fullmatch(draft["sha256"]) is None
    ):
        return False, "auditor draft evidence is malformed"
    try:
        path = repository_path(root, draft.get("path"))
        draft_matches = (
            file_mode(path) == draft["mode"]
            and digest_bytes(path.read_bytes()) == draft["sha256"]
        )
    except (OSError, UnicodeError, ValueError) as error:
        return False, str(error)
    if not draft_matches:
        return False, "auditor draft mode or SHA-256 does not match the working tree"

    baseline = evidence["baseline"]
    if baseline is None:
        if anchoring.get("local") is not False:
            return False, "unanchored auditor draft cannot claim local anchoring"
        return True, ""
    if (
        not isinstance(baseline, dict)
        or set(baseline) != required
        or baseline.get("path") != AUDITOR_PATH
        or not isinstance(baseline.get("commit"), str)
        or SHA_PATTERN.fullmatch(baseline["commit"]) is None
        or baseline.get("mode") not in {"100644", "100755"}
        or not isinstance(baseline.get("blobOid"), str)
        or OID_PATTERN.fullmatch(baseline["blobOid"]) is None
        or not isinstance(baseline.get("sha256"), str)
        or DIGEST_PATTERN.fullmatch(baseline["sha256"]) is None
    ):
        return False, "pinned auditor baseline is malformed"
    try:
        commit_type = run_git(root, "cat-file", "-t", baseline["commit"])
        entry = run_git(
            root,
            "ls-tree",
            "-z",
            baseline["commit"],
            "--",
            AUDITOR_PATH,
        )
        blob = run_git(root, "cat-file", "blob", baseline["blobOid"])
    except (OSError, ValueError) as error:
        return False, f"pinned auditor baseline cannot be verified: {error}"
    records = [record for record in entry.stdout.split(b"\0") if record]
    if commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit":
        return False, "pinned auditor baseline commit is not a local Git commit"
    if entry.returncode != 0 or len(records) != 1 or blob.returncode != 0:
        return False, "pinned auditor baseline path or blob is unavailable"
    try:
        metadata, observed_path = records[0].split(b"\t", 1)
        mode, entry_type, blob_oid = metadata.split(b" ", 2)
        observed_path_text = observed_path.decode("utf-8", errors="strict")
        mode_text = mode.decode("ascii")
        blob_oid_text = blob_oid.decode("ascii")
    except (UnicodeError, ValueError):
        return False, "pinned auditor baseline tree entry is malformed"
    pinned_matches = (
        observed_path_text == AUDITOR_PATH
        and entry_type == b"blob"
        and mode_text == baseline["mode"]
        and blob_oid_text == baseline["blobOid"]
        and digest_bytes(blob.stdout) == baseline["sha256"]
        and baseline["mode"] == draft["mode"]
        and baseline["sha256"] == draft["sha256"]
        and anchoring.get("local") is True
    )
    if not pinned_matches:
        return False, "pinned auditor commit, mode, blob, or SHA-256 is inconsistent"
    return True, ""


def run_identity_key(identity: dict[str, Any]) -> str:
    return canonical_digest({field: identity.get(field) for field in RUN_IDENTITY_FIELDS})


def release_reservation_key(
    release: dict[str, Any],
    identity: dict[str, Any],
) -> str:
    values = {
        "repository_id": identity.get("repository_id"),
        "environment": identity.get("environment"),
        "release_id": release.get("release_id"),
        "artifact_digest": release.get("artifact_digest"),
    }
    return canonical_digest(values)


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


def validate_contract(
    contract: dict[str, Any],
    repo_root: Path,
) -> tuple[dict[str, bool], list[str]]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    add_check(
        checks,
        errors,
        "top-level-fields",
        set(contract) == TOP_LEVEL_FIELDS,
        "contract fields are incomplete or unexpected",
    )
    add_check(
        checks,
        errors,
        "schema-version",
        type(contract.get("schemaVersion")) is int
        and contract.get("schemaVersion") == SUPPORTED_SCHEMA_VERSION,
        f"schemaVersion must equal {SUPPORTED_SCHEMA_VERSION}",
    )
    add_check(
        checks,
        errors,
        "research-only-status",
        contract.get("status") == EXPECTED_STATUS,
        f"status must equal {EXPECTED_STATUS}",
    )
    add_check(
        checks,
        errors,
        "real-mutation-disabled",
        contract.get("realMutation") is False,
        "realMutation must remain false while persistent replay protection is absent",
    )
    add_check(
        checks,
        errors,
        "run-identity-contract",
        contract.get("runIdentity")
        == {
            "requiredFields": list(RUN_IDENTITY_FIELDS),
            "rerunRule": (
                "same-run-id-different-run-attempt-is-distinct-execution"
            ),
        },
        "run identity must bind every required field and distinguish rerun attempts",
    )
    add_check(
        checks,
        errors,
        "fixed-workflow-sha",
        contract.get("workflowTrust")
        == {
            "fullCommitShaRequired": True,
            "workflowRefMustEndWithWorkflowSha": True,
        },
        "workflow trust must require a matching fixed full SHA",
    )
    add_check(
        checks,
        errors,
        "environment-secret-release-only",
        contract.get("environmentAuthentication")
        == {
            "requiredReviewers": True,
            "preventSelfReview": True,
            "purpose": "secret-release-only",
            "authenticates": ["secret-release"],
            "doesNotAuthorize": [
                "release-mutation",
                "replay-prevention",
                "ledger-reservation",
            ],
        },
        "environment review may authenticate only secret release",
    )
    add_check(
        checks,
        errors,
        "concurrency-serialization-only",
        contract.get("concurrency")
        == {
            "purpose": "serialization-only",
            "persistentReplayProtection": False,
            "authorizationEvidence": False,
        },
        "concurrency must not be treated as authorization or replay protection",
    )
    add_check(
        checks,
        errors,
        "independent-atomic-ledger-required",
        contract.get("replayProtection")
        == {
            "requiredForRealMutation": True,
            "reservationKeyFields": list(RESERVATION_KEY_FIELDS),
            "ledgerRequirements": {
                "independent": True,
                "durable": True,
                "atomicCheckAndReserve": True,
                "beforeSecretRelease": True,
                "beforeMutation": True,
            },
        },
        "real mutation must require an independent durable atomic reservation",
    )
    add_check(
        checks,
        errors,
        "ledger-not-implemented",
        contract.get("currentImplementation")
        == {
            "ledgerImplemented": False,
            "ledgerEvidence": None,
            "realMutationBlocker": (
                "independent-atomic-ledger-reservation-not-implemented"
            ),
        },
        "current implementation must honestly report missing ledger support",
    )
    anchoring = contract.get("twoStageAnchoring")
    anchoring_valid = (
        isinstance(anchoring, dict)
        and set(anchoring) == {"local", "remote", "deployment"}
        and type(anchoring.get("local")) is bool
        and anchoring.get("remote") is False
        and anchoring.get("deployment") == "blocked"
    )
    add_check(
        checks,
        errors,
        "two-stage-anchoring",
        anchoring_valid,
        "two-stage anchoring must keep remote verification false and deployment blocked",
    )
    add_check(
        checks,
        errors,
        "evidence-boundary",
        contract.get("evidenceBoundary")
        == {
            "level": "E0",
            "deployment": False,
            "mutation": False,
        },
        "source evidence must remain E0 and cannot prove deployment or mutation",
    )
    auditor_valid, auditor_error = validate_auditor_evidence(
        repo_root,
        contract.get("auditorEvidence"),
        anchoring,
    )
    add_check(
        checks,
        errors,
        "auditor-source-evidence",
        anchoring_valid and auditor_valid,
        auditor_error or "auditor source evidence is inconsistent",
    )
    return checks, errors


def valid_run_identity(identity: Any) -> bool:
    if not isinstance(identity, dict) or set(identity) != set(RUN_IDENTITY_FIELDS):
        return False
    workflow_ref = identity["workflow_ref"]
    match = (
        WORKFLOW_REF_PATTERN.fullmatch(workflow_ref)
        if isinstance(workflow_ref, str)
        else None
    )
    return (
        type(identity["repository_id"]) is int
        and identity["repository_id"] > 0
        and isinstance(identity["workflow_sha"], str)
        and SHA_PATTERN.fullmatch(identity["workflow_sha"]) is not None
        and match is not None
        and match.group(1) == identity["workflow_sha"]
        and type(identity["run_id"]) is int
        and identity["run_id"] > 0
        and type(identity["run_attempt"]) is int
        and identity["run_attempt"] > 0
        and isinstance(identity["job"], str)
        and bool(identity["job"])
        and isinstance(identity["environment"], str)
        and bool(identity["environment"])
    )


def audit_evidence(evidence: dict[str, Any]) -> tuple[dict[str, bool], list[str]]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    add_check(
        checks,
        errors,
        "evidence-fields",
        set(evidence) == EVIDENCE_FIELDS,
        "runtime evidence fields are incomplete or unexpected",
    )
    release = evidence.get("releaseIdentity")
    release_valid = (
        isinstance(release, dict)
        and set(release) == {"release_id", "artifact_digest"}
        and isinstance(release["release_id"], str)
        and bool(release["release_id"])
        and isinstance(release["artifact_digest"], str)
        and DIGEST_PATTERN.fullmatch(release["artifact_digest"]) is not None
    )
    add_check(
        checks,
        errors,
        "release-identity",
        release_valid,
        "release identity must bind release_id and artifact_digest",
    )
    identity = evidence.get("runIdentity")
    identity_valid = valid_run_identity(identity)
    add_check(
        checks,
        errors,
        "run-identity",
        identity_valid,
        "run identity is incomplete or workflow_ref is not bound to workflow_sha",
    )
    workflow = evidence.get("workflowTrust")
    workflow_valid = (
        identity_valid
        and isinstance(workflow, dict)
        and set(workflow) == {"pinnedFullSha", "verifiedWorkflowSha"}
        and workflow["pinnedFullSha"] is True
        and workflow["verifiedWorkflowSha"] == identity["workflow_sha"]
    )
    add_check(
        checks,
        errors,
        "workflow-trust",
        workflow_valid,
        "fixed workflow SHA evidence is missing or inconsistent",
    )
    approval = evidence.get("environmentApproval")
    approval_valid = (
        identity_valid
        and isinstance(approval, dict)
        and set(approval)
        == {
            "environment",
            "actorId",
            "approvedReviewerIds",
            "requiredReviewersSatisfied",
            "preventSelfReviewEnforced",
            "secretReleased",
        }
        and approval["environment"] == identity["environment"]
        and isinstance(approval["actorId"], int)
        and isinstance(approval["approvedReviewerIds"], list)
        and bool(approval["approvedReviewerIds"])
        and all(
            isinstance(reviewer, int)
            for reviewer in approval["approvedReviewerIds"]
        )
        and len(set(approval["approvedReviewerIds"]))
        == len(approval["approvedReviewerIds"])
        and approval["actorId"] not in approval["approvedReviewerIds"]
        and approval["requiredReviewersSatisfied"] is True
        and approval["preventSelfReviewEnforced"] is True
        and approval["secretReleased"] is True
    )
    add_check(
        checks,
        errors,
        "environment-approval",
        approval_valid,
        "required-reviewer or prevent-self-review secret-release evidence is missing",
    )
    concurrency = evidence.get("concurrency")
    concurrency_valid = (
        isinstance(concurrency, dict)
        and set(concurrency) == {"configured", "group", "cancelInProgress"}
        and isinstance(concurrency["configured"], bool)
        and isinstance(concurrency["group"], str)
        and isinstance(concurrency["cancelInProgress"], bool)
    )
    add_check(
        checks,
        errors,
        "concurrency-shape",
        concurrency_valid,
        "concurrency evidence is malformed",
    )
    ledger = evidence.get("ledgerReservation")
    expected_key = (
        release_reservation_key(release, identity)
        if release_valid and identity_valid
        else None
    )
    ledger_valid = (
        isinstance(ledger, dict)
        and set(ledger)
        == {
            "provider",
            "independent",
            "durable",
            "operation",
            "atomic",
            "reservedBeforeSecretRelease",
            "reservedBeforeMutation",
            "reservationKey",
            "reservationId",
            "status",
            "existingReservation",
            "reservedForRunIdentity",
        }
        and isinstance(ledger["provider"], str)
        and bool(ledger["provider"])
        and ledger["independent"] is True
        and ledger["durable"] is True
        and ledger["operation"] == "check-and-reserve"
        and ledger["atomic"] is True
        and ledger["reservedBeforeSecretRelease"] is True
        and ledger["reservedBeforeMutation"] is True
        and ledger["reservationKey"] == expected_key
        and isinstance(ledger["reservationId"], str)
        and bool(ledger["reservationId"])
        and ledger["status"] == "reserved"
        and ledger["existingReservation"] is False
        and identity_valid
        and ledger["reservedForRunIdentity"] == identity
    )
    add_check(
        checks,
        errors,
        "ledger-reservation",
        ledger_valid,
        "independent durable atomic ledger reservation evidence is missing, duplicate, or inconsistent",
    )
    return checks, errors


def evaluate(
    contract_path: Path,
    evidence_path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    try:
        contract = load_json_object(contract_path, "runtime contract")
    except ValueError as error:
        return {
            "valid": False,
            "contractValid": False,
            "evidenceValid": False,
            "realMutation": False,
            "mutationAllowed": False,
            "checks": {},
            "errors": [str(error)],
        }
    root = (
        repo_root.resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    contract_checks, errors = validate_contract(contract, root)
    checks = {f"contract:{key}": value for key, value in contract_checks.items()}
    evidence_valid = False
    if evidence_path is not None:
        try:
            evidence = load_json_object(evidence_path, "runtime evidence")
        except ValueError as error:
            errors.append(str(error))
        else:
            evidence_checks, evidence_errors = audit_evidence(evidence)
            checks.update(
                {f"evidence:{key}": value for key, value in evidence_checks.items()}
            )
            errors.extend(evidence_errors)
            evidence_valid = not evidence_errors
    contract_valid = all(contract_checks.values())
    real_mutation = contract.get("realMutation") is True
    return {
        "valid": contract_valid and (evidence_path is None or evidence_valid),
        "contractValid": contract_valid,
        "evidenceValid": evidence_valid,
        "realMutation": real_mutation,
        "mutationAllowed": False,
        "environmentAuthenticates": "secret-release-only",
        "concurrencyGuarantee": "serialization-only",
        "persistentReplayProtectionImplemented": False,
        "evidenceLevel": "E0",
        "deploymentEvidence": False,
        "mutationEvidence": False,
        "checks": checks,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    research = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=research / "protected-release-runtime-contract.json",
    )
    parser.add_argument("--evidence", type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=research.parents[1],
    )
    args = parser.parse_args(argv)
    result = evaluate(args.contract, args.evidence, args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    return 0 if result["mutationAllowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

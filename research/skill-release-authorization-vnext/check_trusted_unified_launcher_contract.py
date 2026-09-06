#!/usr/bin/env python3
"""Offline auditor for the research-only unified launcher contract."""

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
LAUNCHER = (
    "research/skill-release-authorization-vnext/trusted_unified_launcher.py"
)
CONSUMER = (
    "research/skill-release-authorization-vnext/"
    "trusted_artifact_publish_consumer.py"
)
AUDITOR = (
    "research/skill-release-authorization-vnext/"
    "check_trusted_unified_launcher_contract.py"
)
CONTRACT = (
    "research/skill-release-authorization-vnext/"
    "trusted-unified-launcher-contract.json"
)
TEST = "tests/test_trusted_unified_launcher.py"
TOP_LEVEL_FIELDS = {
    "schemaVersion", "status", "launcher", "consumer", "auditor", "test",
    "execution", "controlPlane", "attestation", "bindings", "limits",
    "repositoryBoundary", "evidenceBoundary", "launcherEvidence",
    "auditorEvidence", "consumerEvidence", "twoStageAnchoring",
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
EXPECTED_EXECUTION = {
    "operation": "dry-run-simulation",
    "formalWorkflowWired": False,
    "noNetworkCallsRequested": True,
    "networkIsolationEnforced": False,
    "credentialsAccepted": False,
    "publicationAttempted": False,
    "intermediateResultFiles": False,
    "fixedGitExecutable": "/usr/bin/git",
    "pythonIsolatedMode": True,
    "childEnvironment": "allowlist-only",
}
EXPECTED_CONTROL = {
    "singleControlCommit": True,
    "childExecutedBlobComponents": ["preflight", "staging", "consumer"],
    "parentExecutedControlBlob": False,
    "independentIsolatedPhaseProcesses": True,
    "worktreeControlSourceExecution": False,
    "controlBlobMaximumBytes": 2097152,
    "candidateAndControlIndependent": True,
}
EXPECTED_ATTESTATION = {
    "nonceBytes": 32,
    "nonceStorage": "memory-only",
    "nonceReuseAllowed": False,
    "canonicalInvocation": True,
    "phaseOrder": ["preflight", "staging", "consumer"],
    "envelopedPhaseOrder": ["preflight", "staging"],
    "consumerExecutionCompleted": True,
    "phaseResultDigests": True,
    "invocationDigest": "sha256",
    "pipeFrame": "unsigned-big-endian-64-bit-length-prefix",
    "frameMagic": "trusted-unified-phase-v1",
    "processLocalFrameBinding": True,
    "persistentReplayProtection": False,
    "crossProcessReplayAccepted": True,
    "authorizationProvenanceVerified": False,
    "controlCommitExternallyAuthenticated": False,
}
EXPECTED_BINDINGS = {
    "base": "invocation=preflight-result",
    "head": "candidate-HEAD=invocation=preflight-result=staging-manifest",
    "catalog": "candidate-HEAD-mode-100644-blobOid-sha256",
    "event": "workflow_dispatch-changed-only-canonical-fields",
    "artifact": "staging-result=consumer-verified-package-fd",
}
EXPECTED_LIMITS = {
    "gitTimeoutSeconds": 30,
    "gitCombinedOutputBytes": 8388608,
    "phaseTimeoutSeconds": 240,
    "phaseCombinedOutputBytes": 2097152,
    "timeoutPolicy": "terminate-process-group-and-reap",
    "overflowPolicy": "terminate-process-group-and-reap",
}
EXPECTED_FILES = [
    LAUNCHER,
    CONTRACT,
    AUDITOR,
    CONSUMER,
    (
        "research/skill-release-authorization-vnext/"
        "trusted-artifact-publish-consumer-contract.json"
    ),
    TEST,
    "tests/test_trusted_artifact_publish_consumer.py",
]
EXPECTED_REPOSITORY = {
    "formalWorkflows": "unchanged",
    "skillsDirectory": "unchanged",
    "catalogWorktree": "unchanged",
    "researchOnlyFiles": EXPECTED_FILES,
}
EXPECTED_EVIDENCE = {
    "currentLevel": "E0",
    "deploymentReady": False,
    "realMutationAllowed": False,
    "downloadableClaimAllowed": False,
    "launcherBaselinePinned": False,
    "auditorBaselinePinned": False,
    "consumerBaselinePinned": False,
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
        raise ValueError("unified launcher contract must not be a symlink")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("unified launcher contract must be a JSON object")
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
    if not regular_mode_0644(path):
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
        or value["mode"] != draft["mode"]
        or value["sha256"] != draft["sha256"]
        or not isinstance(value["commit"], str)
        or not isinstance(value["blobOid"], str)
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
        env={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        },
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


def imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split(".", 1)[0])
    return result


def protected_paths_unchanged(root: Path) -> bool:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    for command in (
        [
            "/usr/bin/git", "--no-replace-objects", "diff", "--quiet", "HEAD",
            "--", ".github/workflows", "skills", ".clawhub/skill-catalog.json",
        ],
        [
            "/usr/bin/git", "--no-replace-objects", "status", "--porcelain=v1",
            "-z", "--untracked-files=all", "--", ".github/workflows", "skills",
            ".clawhub/skill-catalog.json",
        ],
    ):
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0 or completed.stdout:
            return False
    return True


def evaluate(root: Path, contract_path: Path) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def add(name: str, passed: bool, message: str) -> None:
        checks[name] = bool(passed)
        if not passed:
            errors.append(message)

    try:
        contract = load_contract(contract_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return {
            "valid": False,
            "deploymentReady": False,
            "authorizationGranted": False,
            "checks": {},
            "errors": [str(error)],
        }
    add("fields", set(contract) == TOP_LEVEL_FIELDS, "contract fields changed")
    add("schema", contract.get("schemaVersion") == 1, "schemaVersion must be 1")
    add(
        "status",
        contract.get("status") == "research-only-not-wired",
        "status must remain research-only-not-wired",
    )
    add(
        "paths",
        contract.get("launcher") == LAUNCHER
        and contract.get("consumer") == CONSUMER
        and contract.get("auditor") == AUDITOR
        and contract.get("test") == TEST
        and all(regular_mode_0644(root / relative) for relative in EXPECTED_FILES),
        "research files or modes are invalid",
    )
    evidence_states: dict[str, bool] = {}
    for name, field, relative in (
        ("launcher", "launcherEvidence", LAUNCHER),
        ("auditor", "auditorEvidence", AUDITOR),
        ("consumer", "consumerEvidence", CONSUMER),
    ):
        try:
            valid_evidence, pinned = evidence_matches(
                root, contract.get(field), relative
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            valid_evidence, pinned = False, False
        evidence_states[name] = pinned
        add(
            f"{name}-draft-evidence",
            valid_evidence,
            f"{name} evidence must match the worktree and optional baseline",
        )
    all_pinned = all(evidence_states.values())
    add(
        "two-stage-anchoring",
        contract.get("twoStageAnchoring")
        == {**EXPECTED_TWO_STAGE_BASE, "localIntegrityPinned": all_pinned},
        "two-stage anchoring does not match the actual baseline state",
    )
    expected_evidence = {
        **EXPECTED_EVIDENCE,
        "launcherBaselinePinned": evidence_states["launcher"],
        "auditorBaselinePinned": evidence_states["auditor"],
        "consumerBaselinePinned": evidence_states["consumer"],
    }
    for name, key, expected in (
        ("execution", "execution", EXPECTED_EXECUTION),
        ("control", "controlPlane", EXPECTED_CONTROL),
        ("attestation", "attestation", EXPECTED_ATTESTATION),
        ("bindings", "bindings", EXPECTED_BINDINGS),
        ("limits", "limits", EXPECTED_LIMITS),
        ("repository", "repositoryBoundary", EXPECTED_REPOSITORY),
        ("evidence", "evidenceBoundary", expected_evidence),
    ):
        add(name, contract.get(key) == expected, f"{key} contract changed")
    try:
        launcher_source = (root / LAUNCHER).read_text(encoding="utf-8")
        consumer_source = (root / CONSUMER).read_text(encoding="utf-8")
        launcher_tree = ast.parse(launcher_source)
        consumer_tree = ast.parse(consumer_source)
    except (OSError, UnicodeError, SyntaxError) as error:
        launcher_source = consumer_source = ""
        launcher_tree = consumer_tree = ast.Module(body=[], type_ignores=[])
        errors.append(f"research source cannot be parsed: {error}")
    required_launcher = (
        "os.urandom(NONCE_BYTES)", "NONCE_BYTES = 32", "CONTROL_FILES",
        "read_control_blob", "read_candidate_catalog", "canonical_json_bytes",
        "phase_frame", "PREFLIGHT_BOOTSTRAP", "STAGING_BOOTSTRAP",
        "CONSUMER_BOOTSTRAP", "run_control_phase", "run_bounded",
        "terminate_and_reap", '"dry-run-simulation"',
        '"intermediateResultFiles": False',
        '"parentExecutedControlBlob": False',
        '"noNetworkCallsRequested": True',
        '"networkIsolationEnforced": False',
        'result.get("envelopedPhases") != ["preflight", "staging"]',
        'result.get("consumerExecutionCompleted") is not True',
    )
    required_consumer = (
        "consume_attested_frame", "encode_attested_frame",
        "ATTESTED_NONCE_BYTES = 32", "parse_frame_parts",
        "validate_attested_envelope", '"preflight"', '"staging"',
        '"processLocalFrameBinding": True',
        '"persistentReplayProtection": False',
        '"authorizationProvenanceVerified": False',
        '"controlCommitExternallyAuthenticated": False',
    )
    forbidden = (
        "requests", "urllib", "socket.", "http://", "https://",
        "CLAWHUB_TOKEN", "GITHUB_TOKEN", "clawhub ", "shell=True",
        ".github/workflows/",
    )
    add(
        "launcher-primitives",
        all(token in launcher_source for token in required_launcher),
        "launcher omits a required blob, nonce, frame, limit, or dry-run primitive",
    )
    parent_exec_calls = [
        node
        for node in ast.walk(launcher_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"exec", "eval", "compile"}
    ]
    parent_loaders = [
        node
        for node in ast.walk(launcher_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "load_module"
    ]
    add(
        "parent-does-not-execute-control-blob",
        not parent_exec_calls and not parent_loaders,
        "unified parent contains an executable control-blob loading path",
    )
    add(
        "consumer-entry",
        all(token in consumer_source for token in required_consumer),
        "consumer omits a required attested memory-frame primitive",
    )
    add(
        "forbidden-surface",
        all(
            token not in launcher_source and token not in consumer_source
            for token in forbidden
        )
        and imports(launcher_tree).isdisjoint(
            {"requests", "urllib", "socket", "http", "ssl"}
        )
        and imports(consumer_tree).isdisjoint(
            {"requests", "urllib", "socket", "http", "ssl"}
        ),
        "research code contains network, token, workflow, or real CLI surface",
    )
    try:
        unchanged = protected_paths_unchanged(root)
    except (OSError, subprocess.TimeoutExpired):
        unchanged = False
    add(
        "protected-paths",
        unchanged,
        "formal workflows, skills, or catalog differ from HEAD",
    )
    return {
        "valid": not errors,
        "deploymentReady": False,
        "authorizationGranted": False,
        "checks": checks,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=RESEARCH / Path(CONTRACT).name)
    args = parser.parse_args(argv)
    result = evaluate(args.repo_root.resolve(), args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

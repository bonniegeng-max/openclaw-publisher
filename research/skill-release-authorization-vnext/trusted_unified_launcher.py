#!/usr/bin/env python3
"""Research-only launcher for one attested preflight/staging/consumer run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


RESEARCH_STATUS = "research-only-not-wired"
TRUSTED_GIT_ENTRY = Path("/usr/bin/git")
CONTROL_FILES = {
    "preflight": (
        "research/skill-release-authorization-vnext/"
        "trusted_preflight_launcher.py"
    ),
    "staging": (
        "research/skill-release-authorization-vnext/"
        "trusted_staging_launcher.py"
    ),
    "consumer": (
        "research/skill-release-authorization-vnext/"
        "trusted_artifact_publish_consumer.py"
    ),
}
CATALOG_PATH = ".clawhub/skill-catalog.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PHASE_FRAME_MAGIC = b"trusted-unified-phase-v1\0"
NONCE_BYTES = 32
MAX_CONTROL_BLOB_BYTES = 2 * 1024 * 1024
MAX_OUTER_PART_BYTES = 8 * 1024 * 1024
CONSUMER_TIMEOUT_SECONDS = 240
GIT_TIMEOUT_SECONDS = 30
MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
REAP_TIMEOUT_SECONDS = 5


PREFLIGHT_BOOTSTRAP = r"""
import json
import pathlib
import struct
import sys
import types

MAGIC = b"trusted-unified-phase-v1\0"
raw = sys.stdin.buffer.read()
if not raw.startswith(MAGIC):
    raise RuntimeError("invalid unified phase frame magic")
offset = len(MAGIC)
parts = []
for _ in range(2):
    if len(raw) < offset + 8:
        raise RuntimeError("truncated unified phase frame")
    length = struct.unpack(">Q", raw[offset:offset + 8])[0]
    offset += 8
    if length == 0 or length > 8 * 1024 * 1024 or len(raw) < offset + length:
        raise RuntimeError("invalid unified phase frame length")
    parts.append(raw[offset:offset + length])
    offset += length
if offset != len(raw):
    raise RuntimeError("trailing unified phase frame bytes")
source, request_raw = parts
request = json.loads(request_raw.decode("utf-8"))
module = types.ModuleType("_trusted_unified_preflight")
module.__file__ = "<control-commit:trusted_preflight_launcher.py>"
module.__package__ = None
exec(compile(source, module.__file__, "exec"), module.__dict__)
returncode, result = module.run_preflight(
    pathlib.Path(request["candidateRoot"]),
    pathlib.Path(request["controlRoot"]),
    request["controlCommit"],
    request["baseCommit"],
    "dry-run",
)
sys.stdout.write(json.dumps(
    {"returncode": returncode, "result": result},
    ensure_ascii=False,
    sort_keys=True,
))
""".strip()

STAGING_BOOTSTRAP = r"""
import json
import pathlib
import struct
import sys
import types

MAGIC = b"trusted-unified-phase-v1\0"
raw = sys.stdin.buffer.read()
if not raw.startswith(MAGIC):
    raise RuntimeError("invalid unified phase frame magic")
offset = len(MAGIC)
parts = []
for _ in range(2):
    if len(raw) < offset + 8:
        raise RuntimeError("truncated unified phase frame")
    length = struct.unpack(">Q", raw[offset:offset + 8])[0]
    offset += 8
    if length == 0 or length > 8 * 1024 * 1024 or len(raw) < offset + length:
        raise RuntimeError("invalid unified phase frame length")
    parts.append(raw[offset:offset + length])
    offset += length
if offset != len(raw):
    raise RuntimeError("trailing unified phase frame bytes")
source, request_raw = parts
request = json.loads(request_raw.decode("utf-8"))
module = types.ModuleType("_trusted_unified_staging")
module.__file__ = "<control-commit:trusted_staging_launcher.py>"
module.__package__ = None
exec(compile(source, module.__file__, "exec"), module.__dict__)
returncode, result = module.run_staging(
    pathlib.Path(request["candidateRoot"]),
    pathlib.Path(request["controlRoot"]),
    request["controlCommit"],
    pathlib.Path(request["artifactParent"]),
    event_name=request["event"]["name"],
    dry_run=True,
    changed_only=request["event"]["changedOnly"],
    ref=request["event"]["ref"],
    base=request["baseCommit"],
    head=request["event"]["headArgument"],
    skill_path=request["event"]["skillPath"],
    event_before=request["event"]["before"],
    event_sha=request["event"]["sha"],
    event_ref=request["event"]["eventRef"],
)
sys.stdout.write(json.dumps(
    {"returncode": returncode, "result": result},
    ensure_ascii=False,
    sort_keys=True,
))
""".strip()

CONSUMER_BOOTSTRAP = r"""
import json
import struct
import sys
import types

MAGIC = b"trusted-unified-phase-v1\0"
raw = sys.stdin.buffer.read()
if not raw.startswith(MAGIC):
    raise RuntimeError("invalid unified phase frame magic")
offset = len(MAGIC)
parts = []
for _ in range(6):
    if len(raw) < offset + 8:
        raise RuntimeError("truncated unified phase frame")
    length = struct.unpack(">Q", raw[offset:offset + 8])[0]
    offset += 8
    if length == 0 or length > 8 * 1024 * 1024 or len(raw) < offset + length:
        raise RuntimeError("invalid unified phase frame length")
    parts.append(raw[offset:offset + length])
    offset += length
if offset != len(raw):
    raise RuntimeError("trailing unified phase frame bytes")
source, nonce, invocation_raw, preflight_raw, staging_raw, catalog_blob = parts
if len(nonce) != 32:
    raise RuntimeError("invalid unified run nonce length")
module = types.ModuleType("_trusted_unified_consumer")
module.__file__ = "<control-commit:trusted_artifact_publish_consumer.py>"
module.__package__ = None
exec(compile(source, module.__file__, "exec"), module.__dict__)
invocation = module.parse_strict_json(invocation_raw, "expected invocation")
preflight = module.parse_strict_json(preflight_raw, "preflight result")
staging = module.parse_strict_json(staging_raw, "staging result")
if invocation_raw != module.canonical_json_bytes(invocation):
    raise RuntimeError("expected invocation is not canonical")
attested_frame = module.encode_attested_frame(
    invocation, preflight, staging, catalog_blob, nonce
)
result = module.consume_attested_frame(attested_frame, nonce, invocation)
sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
""".strip()


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid unified launcher arguments: {message}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def failure(message: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "valid": False,
        "status": "rejected",
        "researchStatus": RESEARCH_STATUS,
        "phase": "trusted-unified-launcher",
        "authorizationGranted": False,
        "cliMode": "simulation-only",
        "noNetworkCallsRequested": True,
        "networkIsolationEnforced": False,
        "credentialsAccepted": False,
        "publicationAttempted": False,
        "realMutationAllowed": False,
        "processLocalFrameBinding": False,
        "persistentReplayProtection": False,
        "authorizationProvenanceVerified": False,
        "controlCommitExternallyAuthenticated": False,
        "errors": [message[:1024]],
    }


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def phase_frame(*parts: bytes) -> bytes:
    if not parts:
        raise ValueError("unified phase frame must contain at least one part")
    if any(not part or len(part) > MAX_OUTER_PART_BYTES for part in parts):
        raise ValueError("unified phase frame part is empty or too large")
    return PHASE_FRAME_MAGIC + b"".join(
        struct.pack(">Q", len(part)) + part for part in parts
    )


def parse_strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"{label} contains invalid constant: {value}")

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} is not strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def child_environment() -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(TRUSTED_GIT_ENTRY.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def git_environment() -> dict[str, str]:
    return {
        **child_environment(),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_EXTERNAL_DIFF": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }


def terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("child process-group leader could not be reaped") from error
    if process.poll() is None:
        raise RuntimeError("child process-group leader reap was not confirmed")


def run_bounded(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    payload: bytes = b"",
    timeout_seconds: float,
    maximum_output_bytes: int,
) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    streams = {
        process.stdout.fileno(): bytearray(),
        process.stderr.fileno(): bytearray(),
    }
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout_seconds
    payload_view = memoryview(payload)
    offset = 0
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ, "output")
        if payload:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin.fileno(), selectors.EVENT_WRITE, "input")
        else:
            process.stdin.close()
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_and_reap(process)
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in list(selector.get_map().values())
                    if key.data == "output"
                ]
            for key, _ in events:
                if key.data == "input":
                    try:
                        written = os.write(
                            key.fd, payload_view[offset:offset + 65536]
                        )
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        written = 0
                        offset = len(payload_view)
                    else:
                        offset += written
                    if offset == len(payload_view):
                        selector.unregister(key.fd)
                        process.stdin.close()
                    continue
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                streams[key.fd].extend(chunk)
                if sum(len(item) for item in streams.values()) > maximum_output_bytes:
                    terminate_and_reap(process)
                    raise ValueError("child combined output exceeds limit")
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        return subprocess.CompletedProcess(
            command,
            returncode,
            bytes(streams[process.stdout.fileno()]),
            bytes(streams[process.stderr.fileno()]),
        )
    except BaseException:
        if process.poll() is None:
            terminate_and_reap(process)
        raise
    finally:
        selector.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def run_git(root: Path, *args: str, text: bool = False) -> subprocess.CompletedProcess:
    completed = run_bounded(
        [
            str(TRUSTED_GIT_ENTRY),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "diff.external=",
            *args,
        ],
        cwd=root,
        environment=git_environment(),
        timeout_seconds=GIT_TIMEOUT_SECONDS,
        maximum_output_bytes=MAX_GIT_OUTPUT_BYTES,
    )
    if not text:
        return completed
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        completed.stdout.decode("utf-8", errors="strict"),
        completed.stderr.decode("utf-8", errors="strict"),
    )


def read_control_blob(
    control_root: Path,
    control_commit: str,
    relative: str,
) -> tuple[bytes, dict[str, str]]:
    entry = run_git(
        control_root, "ls-tree", "-z", control_commit, "--", relative
    )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError(f"control blob must exist exactly once: {relative}")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        observed = raw_path.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"control blob metadata is malformed: {relative}") from error
    if (
        mode != "100644"
        or kind != "blob"
        or observed != relative
        or OID_PATTERN.fullmatch(oid) is None
    ):
        raise ValueError(f"control source is not a mode-100644 blob: {relative}")
    size = run_git(control_root, "cat-file", "-s", oid, text=True)
    try:
        expected_size = int(size.stdout.strip())
    except ValueError as error:
        raise ValueError(f"control blob size is invalid: {relative}") from error
    if (
        size.returncode != 0
        or expected_size <= 0
        or expected_size > MAX_CONTROL_BLOB_BYTES
    ):
        raise ValueError(f"control blob is empty or too large: {relative}")
    blob = run_git(control_root, "cat-file", "blob", oid)
    if blob.returncode != 0 or len(blob.stdout) != expected_size:
        raise ValueError(f"control blob cannot be read completely: {relative}")
    return blob.stdout, {
        "path": relative,
        "mode": mode,
        "blobOid": oid,
        "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
    }


def read_control_sources(
    control_root: Path,
    control_commit: str,
) -> tuple[dict[str, bytes], dict[str, dict[str, str]]]:
    if COMMIT_PATTERN.fullmatch(control_commit) is None:
        raise ValueError("control commit must be a full lowercase SHA-1")
    head = run_git(control_root, "rev-parse", "HEAD", text=True)
    if head.returncode != 0 or head.stdout.strip() != control_commit:
        raise ValueError("control checkout HEAD does not match control commit")
    sources: dict[str, bytes] = {}
    evidence: dict[str, dict[str, str]] = {}
    for name, relative in CONTROL_FILES.items():
        source, item = read_control_blob(control_root, control_commit, relative)
        if len(source) > MAX_CONTROL_BLOB_BYTES:
            raise ValueError(f"{name} control blob exceeds size limit")
        sources[name] = source
        evidence[name] = item
    return sources, evidence


def candidate_head(candidate_root: Path) -> str:
    completed = run_git(
        candidate_root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        "HEAD^{commit}",
        text=True,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("candidate HEAD cannot be resolved")
    return commit


def read_candidate_catalog(
    candidate_root: Path,
    head_commit: str,
) -> tuple[bytes, dict[str, str]]:
    entry = run_git(
        candidate_root,
        "ls-tree",
        "-z",
        head_commit,
        "--",
        CATALOG_PATH,
    )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError("candidate HEAD catalog must exist exactly once")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        observed_path = raw_path.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise ValueError("candidate HEAD catalog metadata is malformed") from error
    if (
        mode != "100644"
        or kind != "blob"
        or observed_path != CATALOG_PATH
        or OID_PATTERN.fullmatch(oid) is None
    ):
        raise ValueError("candidate HEAD catalog is not a mode-100644 Git blob")
    size = run_git(candidate_root, "cat-file", "-s", oid, text=True)
    try:
        expected_size = int(size.stdout.strip())
    except ValueError as error:
        raise ValueError("candidate HEAD catalog size is invalid") from error
    if (
        size.returncode != 0
        or expected_size <= 0
        or expected_size > MAX_CONTROL_BLOB_BYTES
    ):
        raise ValueError("candidate HEAD catalog is empty or too large")
    blob = run_git(candidate_root, "cat-file", "blob", oid)
    if blob.returncode != 0 or len(blob.stdout) != expected_size:
        raise ValueError("candidate HEAD catalog blob cannot be read completely")
    return blob.stdout, {
        "path": CATALOG_PATH,
        "mode": mode,
        "blobOid": oid,
        "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
    }


def run_control_phase(
    python_path: Path,
    control_root: Path,
    bootstrap: str,
    payload: bytes,
    label: str,
) -> dict[str, Any]:
    completed = run_bounded(
        [str(python_path), "-I", "-c", bootstrap],
        cwd=control_root,
        environment=child_environment(),
        payload=payload,
        timeout_seconds=CONSUMER_TIMEOUT_SECONDS,
        maximum_output_bytes=2 * 1024 * 1024,
    )
    if completed.stderr:
        raise ValueError(f"{label} child wrote unexpected stderr")
    wrapper = parse_strict_json(completed.stdout, f"{label} child result")
    if set(wrapper) != {"returncode", "result"}:
        raise ValueError(f"{label} child result wrapper is invalid")
    phase_returncode = wrapper["returncode"]
    result = wrapper["result"]
    if type(phase_returncode) is not int or not isinstance(result, dict):
        raise ValueError(f"{label} child result types are invalid")
    if completed.returncode != 0 or phase_returncode != 0:
        raise ValueError(f"{label} did not complete successfully")
    return result


def make_invocation(
    candidate: Path,
    control: Path,
    output: Path,
    control_commit: str,
    base_commit: str,
    head_commit: str,
    catalog_evidence: dict[str, str],
    *,
    event_name: str,
    ref: str,
    changed_only: bool,
    skill_path: str,
    event_before: str,
    event_sha: str,
    event_ref: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "researchStatus": RESEARCH_STATUS,
        "operation": "dry-run-simulation",
        "candidateRoot": str(candidate),
        "controlRoot": str(control),
        "artifactParent": str(output),
        "controlCommit": control_commit,
        "baseCommit": base_commit,
        "headCommit": head_commit,
        "catalog": catalog_evidence,
        "event": {
            "name": event_name,
            "ref": ref,
            "changedOnly": changed_only,
            "headArgument": "HEAD",
            "skillPath": skill_path,
            "before": event_before,
            "sha": event_sha,
            "eventRef": event_ref,
        },
    }


def validate_final_result(result: dict[str, Any]) -> None:
    if (
        result.get("valid") is not True
        or result.get("status") != "simulated"
        or result.get("researchStatus") != RESEARCH_STATUS
        or result.get("authorizationProvenanceVerified") is not False
        or result.get("controlCommitExternallyAuthenticated") is not False
        or result.get("processLocalFrameBinding") is not True
        or result.get("persistentReplayProtection") is not False
        or result.get("envelopedPhases") != ["preflight", "staging"]
        or result.get("consumerExecutionCompleted") is not True
        or result.get("cliMode") != "simulation-only"
        or "networkUsed" in result
        or result.get("noNetworkCallsRequested") is not True
        or result.get("networkIsolationEnforced") is not False
        or result.get("credentialsAccepted") is not False
        or result.get("publicationAttempted") is not False
        or result.get("realMutationAllowed") is not False
    ):
        raise ValueError("attested consumer result violates simulation contract")


def run_unified(
    candidate_root: Path,
    control_root: Path,
    control_commit: str,
    base_commit: str,
    artifact_parent: Path,
    *,
    event_name: str = "workflow_dispatch",
    ref: str = "",
    changed_only: bool = True,
    skill_path: str = "",
    event_before: str = "",
    event_sha: str = "",
    event_ref: str = "",
) -> tuple[int, dict[str, Any]]:
    if event_name != "workflow_dispatch" or changed_only is not True:
        return 2, failure(
            "unified launcher permits only changed-only workflow_dispatch simulation"
        )
    if COMMIT_PATTERN.fullmatch(base_commit) is None:
        return 2, failure("base commit must be a full lowercase SHA-1")
    candidate = lexical_absolute(candidate_root)
    control = lexical_absolute(control_root)
    output = lexical_absolute(artifact_parent)
    try:
        if candidate == control:
            raise ValueError("candidate and control roots must be different")
        nonce = os.urandom(NONCE_BYTES)
        if type(nonce) is not bytes:
            raise ValueError("operating system nonce source returned invalid data")
        if len(nonce) != NONCE_BYTES:
            raise ValueError("operating system nonce must contain exactly 32 bytes")

        python_path = Path(sys.executable).resolve(strict=True)
        sources, control_evidence = read_control_sources(control, control_commit)
        head_commit = candidate_head(candidate)
        catalog_blob, catalog_evidence = read_candidate_catalog(
            candidate, head_commit
        )
        invocation = make_invocation(
            candidate,
            control,
            output,
            control_commit,
            base_commit,
            head_commit,
            catalog_evidence,
            event_name=event_name,
            ref=ref,
            changed_only=changed_only,
            skill_path=skill_path,
            event_before=event_before,
            event_sha=event_sha,
            event_ref=event_ref,
        )
        invocation_bytes = canonical_json_bytes(invocation)
        authorization = run_control_phase(
            python_path,
            control,
            PREFLIGHT_BOOTSTRAP,
            phase_frame(sources["preflight"], invocation_bytes),
            "preflight",
        )
        if authorization.get("authorized") is not True:
            raise ValueError("preflight did not authorize this dry-run simulation")
        staging_result = run_control_phase(
            python_path,
            control,
            STAGING_BOOTSTRAP,
            phase_frame(sources["staging"], invocation_bytes),
            "staging",
        )
        if staging_result.get("valid") is not True:
            raise ValueError("staging did not produce a verified snapshot")
        payload = phase_frame(
            sources["consumer"],
            nonce,
            invocation_bytes,
            canonical_json_bytes(authorization),
            canonical_json_bytes(staging_result),
            catalog_blob,
        )
        completed = run_bounded(
            [str(python_path), "-I", "-c", CONSUMER_BOOTSTRAP],
            cwd=control,
            environment=child_environment(),
            payload=payload,
            timeout_seconds=CONSUMER_TIMEOUT_SECONDS,
            maximum_output_bytes=2 * 1024 * 1024,
        )
        if completed.returncode != 0 or completed.stderr:
            detail = completed.stderr.decode(
                "utf-8", errors="replace"
            ).strip()[:512]
            raise ValueError(
                "attested consumer failed or wrote unexpected stderr"
                + (f": {detail}" if detail else "")
            )
        result = parse_strict_json(completed.stdout, "attested consumer result")
        validate_final_result(result)
        result["unifiedLauncher"] = {
            "sameControlCommit": True,
            "controlCommit": control_commit,
            "controlFiles": control_evidence,
            "nonceBytes": NONCE_BYTES,
            "canonicalInvocation": True,
            "lengthPrefixedPipeFrame": "trusted-unified-phase-v1",
            "independentIsolatedPhaseProcesses": [
                "preflight",
                "staging",
                "consumer",
            ],
            "parentExecutedControlBlob": False,
            "catalogFromCandidateHead": True,
            "intermediateResultFiles": False,
        }
        return 0, result
    except (
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as error:
        return 2, failure(str(error))


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated:
        print(json.dumps(failure("unified launcher requires Python isolated mode (-I)")))
        return 2
    parser = StructuredArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--artifact-parent", type=Path, required=True)
    parser.add_argument("--event-name", default="workflow_dispatch")
    parser.add_argument("--ref", default="")
    parser.add_argument("--changed-only", default="true")
    parser.add_argument("--skill-path", default="")
    parser.add_argument("--event-before", default="")
    parser.add_argument("--event-sha", default="")
    parser.add_argument("--event-ref", default="")
    try:
        args = parser.parse_args(argv)
        if args.changed_only not in {"true", "false"}:
            raise ValueError("--changed-only must be true or false")
        returncode, result = run_unified(
            args.candidate_root,
            args.control_root,
            args.control_commit,
            args.base,
            args.artifact_parent,
            event_name=args.event_name,
            ref=args.ref,
            changed_only=args.changed_only == "true",
            skill_path=args.skill_path,
            event_before=args.event_before,
            event_sha=args.event_sha,
            event_ref=args.event_ref,
        )
    except ValueError as error:
        returncode, result = 2, failure(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

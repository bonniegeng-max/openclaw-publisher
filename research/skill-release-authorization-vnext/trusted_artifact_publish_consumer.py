#!/usr/bin/env python3
"""Research-only consumer that keeps a verified package directory FD open."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import struct
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


RESEARCH_STATUS = "research-only-not-wired"
ARTIFACT_FORMAT = "immutable-skill-staging-v2"
PACKAGE_FORMAT = "safe-publish-package-v1"
EXPECTED_REPOSITORY = "github.com/bonniegeng-max/openclaw-publisher"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_FILES = 1024
MAX_PACKAGE_FILE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_CHILD_OUTPUT_BYTES = 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 12 * 1024 * 1024
CHILD_TIMEOUT_SECONDS = 30
CHILD_REAP_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 30
MAX_AUTHORIZATION_AGE = timedelta(minutes=15)
MAX_AUTHORIZATION_FUTURE_SKEW = timedelta(minutes=5)
TRUSTED_GIT_ENTRY = Path("/usr/bin/git")
EXPECTED_BRANCH = "refs/heads/main"
EXPECTED_TRACKING_REF = "refs/remotes/origin/main"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
OUTPUT_NAME_PATTERN = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}-[0-9a-f]{12}$"
)
REQUIRED_PACKAGE_FILES = {"SKILL.md", "CHANGELOG.md", ".clawhubignore"}
AUTHORIZATION_FIELDS = {
    "valid", "authorized", "mode", "evaluatedAt", "releaseId", "baseCommit",
    "candidateCommit", "headCommit", "targets", "catalogChanged",
    "contentDigest", "changeSetDigest", "authorizationChanged",
    "blockingReasons", "errors", "trustedControl", "launcherObservations",
}
STAGING_FIELDS = {
    "schemaVersion", "valid", "status", "researchStatus", "created",
    "authorizationGranted", "outputName", "residueName", "manifest", "errors",
    "launcherObservations", "artifactState",
}
MANIFEST_FIELDS = {
    "schemaVersion", "researchStatus", "format", "guardResultDigest", "source",
    "packageDirectory", "files", "worktreeRead", "authorizationGranted",
    "artifactDigest",
}
SOURCE_FIELDS = {"commit", "skillPath", "treeOid", "packageDigest"}
FILE_FIELDS = {"path", "sourceMode", "artifactMode", "blobOid", "sha256"}
PREFLIGHT_CONTROL_FILES = {
    "checker": "scripts/check_skill_release_authorization.py",
    "validator": "scripts/validate_skill_catalog.py",
}
STAGING_CONTROL_FILES = {
    "guard": "research/skill-release-authorization-vnext/safe_publish_target_guard.py",
    "builder": "research/skill-release-authorization-vnext/immutable_staging_builder.py",
}
PREFLIGHT_OBSERVATIONS = {
    "isolatedModeObserved": True,
    "childEnvironmentAllowlisted": True,
    "checkerSnapshotBoundToControlCommit": True,
    "checkerTimeoutSeconds": 120,
}
STAGING_OBSERVATION_FIELDS = {
    "isolatedModeObserved", "childEnvironmentAllowlisted", "controlCommit",
    "controlFiles", "sameControlCommit", "guardAndBuilderSeparated",
    "guardResultDigestVerified", "independentCheckouts", "inMemoryFraming",
    "timeoutSeconds", "artifactVerification",
    "artifactVerificationSemantics", "formalWorkflowWired",
}
ARTIFACT_VERIFICATION_FIELDS = {
    "manifestMatched", "artifactDigestVerified", "fileCount", "contentBytes",
}
ATTESTED_FRAME_MAGIC = b"trusted-unified-consumer-v1\0"
ATTESTED_FRAME_PARTS = 4
ATTESTED_NONCE_BYTES = 32
MAX_ATTESTED_FRAME_PART_BYTES = 2 * 1024 * 1024
ATTESTED_INVOCATION_FIELDS = {
    "schemaVersion", "researchStatus", "operation", "candidateRoot",
    "controlRoot", "artifactParent", "controlCommit", "baseCommit",
    "headCommit", "catalog", "event",
}
ATTESTED_CATALOG_FIELDS = {"path", "mode", "blobOid", "sha256"}
ATTESTED_EVENT_FIELDS = {
    "name", "ref", "changedOnly", "headArgument", "skillPath",
    "before", "sha", "eventRef",
}
ATTESTED_ENVELOPE_FIELDS = {
    "schemaVersion", "phase", "nonce", "invocationDigest", "resultDigest",
    "result",
}
_CONSUMED_ATTESTATION_NONCES: set[bytes] = set()


SIMULATOR = r"""
import hashlib
import json
import os
import stat
import sys

package_fd = int(sys.argv[1])
expected = json.loads(sys.argv[2])
opened = os.fstat(package_fd)
if not stat.S_ISDIR(opened.st_mode):
    raise RuntimeError("inherited package FD is not a directory")

observed = {}

def visit(directory_fd, prefix):
    for name in sorted(os.listdir(directory_fd)):
        if name in {"", ".", ".."} or "/" in name:
            raise RuntimeError("package contains an invalid entry name")
        relative = prefix + "/" + name if prefix else name
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            if stat.S_IMODE(metadata.st_mode) != 0o555:
                raise RuntimeError("package directory mode mismatch: " + relative)
            child = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                visit(child, relative)
            finally:
                os.close(child)
        elif stat.S_ISREG(metadata.st_mode):
            descriptor = os.open(
                name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                opened_file = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened_file.st_mode)
                    or opened_file.st_nlink != 1
                    or (opened_file.st_dev, opened_file.st_ino)
                    != (metadata.st_dev, metadata.st_ino)
                ):
                    raise RuntimeError("package file identity mismatch: " + relative)
                chunks = []
                while True:
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                if (
                    after.st_size != opened_file.st_size
                    or after.st_mtime_ns != opened_file.st_mtime_ns
                    or after.st_ctime_ns != opened_file.st_ctime_ns
                ):
                    raise RuntimeError("package file changed while read: " + relative)
                observed[relative] = {
                    "artifactMode": format(stat.S_IMODE(opened_file.st_mode), "04o"),
                    "sha256": "sha256:" + hashlib.sha256(b"".join(chunks)).hexdigest(),
                }
            finally:
                os.close(descriptor)
        else:
            raise RuntimeError("package entry is not regular: " + relative)

visit(package_fd, "")
manifest_files = {
    item["path"]: {
        "artifactMode": item["artifactMode"],
        "sha256": item["sha256"],
    }
    for item in expected["files"]
}
if observed != manifest_files:
    raise RuntimeError("package files do not match complete manifest")
result = {
    "schemaVersion": 1,
    "simulated": True,
    "packageFdInherited": True,
    "allManifestFilesVerified": True,
    "manifestFileCount": len(observed),
    "slug": expected["slug"],
    "version": expected["version"],
    "displayName": expected["displayName"],
    "categories": expected["categories"],
    "topics": expected["topics"],
}
sys.stdout.write(json.dumps(result, sort_keys=True))
""".strip()


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid consumer arguments: {message}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def parse_strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"{label} exceeds size limit")
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


def frame_parts(*parts: bytes) -> bytes:
    if len(parts) != ATTESTED_FRAME_PARTS:
        raise ValueError("attested consumer frame must contain exactly four parts")
    if any(
        not part or len(part) > MAX_ATTESTED_FRAME_PART_BYTES
        for part in parts
    ):
        raise ValueError("attested consumer frame part is empty or too large")
    return ATTESTED_FRAME_MAGIC + b"".join(
        struct.pack(">Q", len(part)) + part for part in parts
    )


def parse_frame_parts(raw: bytes) -> list[bytes]:
    if not raw.startswith(ATTESTED_FRAME_MAGIC):
        raise ValueError("attested consumer frame magic is invalid")
    offset = len(ATTESTED_FRAME_MAGIC)
    parts: list[bytes] = []
    for _ in range(ATTESTED_FRAME_PARTS):
        if len(raw) < offset + 8:
            raise ValueError("attested consumer frame is truncated")
        length = struct.unpack(">Q", raw[offset:offset + 8])[0]
        offset += 8
        if (
            length == 0
            or length > MAX_ATTESTED_FRAME_PART_BYTES
            or len(raw) < offset + length
        ):
            raise ValueError("attested consumer frame length is invalid")
        parts.append(raw[offset:offset + length])
        offset += length
    if offset != len(raw):
        raise ValueError("attested consumer frame has trailing bytes")
    return parts


def result_envelope(
    phase: str,
    nonce: bytes,
    invocation: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if phase not in {"preflight", "staging"}:
        raise ValueError("attested result phase is invalid")
    if type(nonce) is not bytes or len(nonce) != ATTESTED_NONCE_BYTES:
        raise ValueError("attested run nonce must contain exactly 32 bytes")
    invocation_bytes = canonical_json_bytes(invocation)
    result_bytes = canonical_json_bytes(result)
    return {
        "schemaVersion": 1,
        "phase": phase,
        "nonce": nonce.hex(),
        "invocationDigest":
            "sha256:" + hashlib.sha256(invocation_bytes).hexdigest(),
        "resultDigest": "sha256:" + hashlib.sha256(result_bytes).hexdigest(),
        "result": result,
    }


def encode_attested_frame(
    invocation: dict[str, Any],
    preflight_result: dict[str, Any],
    staging_result: dict[str, Any],
    catalog_blob: bytes,
    nonce: bytes,
) -> bytes:
    return frame_parts(
        canonical_json_bytes(invocation),
        canonical_json_bytes(
            result_envelope("preflight", nonce, invocation, preflight_result)
        ),
        canonical_json_bytes(
            result_envelope("staging", nonce, invocation, staging_result)
        ),
        catalog_blob,
    )


def validate_attested_invocation(
    value: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    if set(value) != ATTESTED_INVOCATION_FIELDS or value != expected:
        raise ValueError("attested invocation is incomplete, unexpected, or mismatched")
    if (
        value["schemaVersion"] != 1
        or value["researchStatus"] != RESEARCH_STATUS
        or value["operation"] != "dry-run-simulation"
    ):
        raise ValueError("attested invocation operation is invalid")
    for field in ("candidateRoot", "controlRoot", "artifactParent"):
        path = Path(value[field])
        if (
            not isinstance(value[field], str)
            or not path.is_absolute()
            or os.path.normpath(value[field]) != value[field]
        ):
            raise ValueError(f"attested invocation {field} is not canonical")
    for field in ("controlCommit", "baseCommit", "headCommit"):
        if (
            not isinstance(value[field], str)
            or COMMIT_PATTERN.fullmatch(value[field]) is None
        ):
            raise ValueError(f"attested invocation {field} is invalid")
    catalog = value["catalog"]
    if not isinstance(catalog, dict) or set(catalog) != ATTESTED_CATALOG_FIELDS:
        raise ValueError("attested invocation catalog evidence is invalid")
    if (
        catalog["path"] != ".clawhub/" + "skill-" + "catalog.json"
        or catalog["mode"] != "100644"
        or not isinstance(catalog["blobOid"], str)
        or OID_PATTERN.fullmatch(catalog["blobOid"]) is None
    ):
        raise ValueError("attested invocation catalog blob is invalid")
    validate_digest(catalog["sha256"], "attested invocation catalog sha256")
    event = value["event"]
    if not isinstance(event, dict) or set(event) != ATTESTED_EVENT_FIELDS:
        raise ValueError("attested invocation event is invalid")
    if (
        event["name"] != "workflow_dispatch"
        or event["changedOnly"] is not True
        or event["headArgument"] != "HEAD"
        or not all(
            isinstance(event[field], str)
            for field in ("ref", "skillPath", "before", "sha", "eventRef")
        )
    ):
        raise ValueError("attested invocation event policy is invalid")


def validate_attested_envelope(
    value: dict[str, Any],
    phase: str,
    nonce: bytes,
    invocation_digest: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ATTESTED_ENVELOPE_FIELDS:
        raise ValueError(f"attested {phase} envelope fields are invalid")
    if (
        value["schemaVersion"] != 1
        or value["phase"] != phase
        or value["nonce"] != nonce.hex()
        or value["invocationDigest"] != invocation_digest
        or not isinstance(value["result"], dict)
        or value["resultDigest"]
        != "sha256:"
        + hashlib.sha256(canonical_json_bytes(value["result"])).hexdigest()
    ):
        raise ValueError(f"attested {phase} envelope is not bound to this run")
    return value["result"]


def open_absolute_directory(path: Path, label: str) -> int:
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise ValueError(f"{label} must be an absolute canonical path")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_input(path: Path, label: str) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = -1
    try:
        parent_fd = open_absolute_directory(path.parent, f"{label} parent")
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
    except OSError as error:
        if parent_fd >= 0:
            os.close(parent_fd)
        raise ValueError(f"{label} cannot be opened safely: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_ino <= 0
            or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o444, 0o600, 0o644}
        ):
            raise ValueError(
                f"{label} owner, mode, nlink, or inode is invalid"
            )
        identity = metadata_identity(metadata)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_INPUT_BYTES:
                raise ValueError(f"{label} exceeds size limit")
            chunks.append(chunk)
        if metadata_identity(os.fstat(descriptor)) != identity:
            raise ValueError(f"{label} changed while being read")
        return parse_strict_json(b"".join(chunks), label)
    finally:
        os.close(descriptor)
        os.close(parent_fd)


def safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} is not a safe relative path")
    if "\\" in value or "\0" in value:
        raise ValueError(f"{label} contains forbidden characters")
    return value


def validate_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def validate_control_files(
    value: Any,
    expected_paths: dict[str, str],
    label: str,
    *,
    mode_required: bool,
) -> None:
    if not isinstance(value, dict) or set(value) != set(expected_paths):
        raise ValueError(f"{label} files are incomplete or unexpected")
    for name, path in expected_paths.items():
        item = value[name]
        fields = {"path", "blobOid", "sha256", "mode"} if mode_required else {
            "path", "blobOid", "sha256"
        }
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"{label} file evidence is malformed")
        if item["path"] != path:
            raise ValueError(f"{label} file path does not match")
        if not isinstance(item["blobOid"], str) or OID_PATTERN.fullmatch(
            item["blobOid"]
        ) is None:
            raise ValueError(f"{label} blobOid is invalid")
        validate_digest(item["sha256"], f"{label} sha256")
        if mode_required and item["mode"] not in {"100644", "100755"}:
            raise ValueError(f"{label} mode is invalid")


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{label} is not valid ISO 8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_authorization(
    value: dict[str, Any],
    expected_control_commit: str,
    expected_head_commit: str,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    if set(value) != AUTHORIZATION_FIELDS:
        raise ValueError("authorization fields are incomplete or unexpected")
    if value["valid"] is not True or value["authorized"] is not True:
        raise ValueError("authorization must be valid and authorized")
    if value["mode"] != "dry-run":
        raise ValueError("research consumer accepts dry-run authorization only")
    if value["authorizationChanged"] is not True:
        raise ValueError("authorization change was not verified")
    if type(value["catalogChanged"]) is not bool:
        raise ValueError("authorization catalogChanged must be boolean")
    evaluated_at = parse_timestamp(value["evaluatedAt"], "authorization evaluatedAt")
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = observed_now - evaluated_at
    if age > MAX_AUTHORIZATION_AGE or age < -MAX_AUTHORIZATION_FUTURE_SKEW:
        raise ValueError("authorization evaluatedAt is outside the freshness window")
    if value["blockingReasons"] != [] or value["errors"] != []:
        raise ValueError("authorization contains blockers or errors")
    for field in ("baseCommit", "candidateCommit", "headCommit"):
        if (
            not isinstance(value[field], str)
            or COMMIT_PATTERN.fullmatch(value[field]) is None
        ):
            raise ValueError(f"authorization {field} is invalid")
    targets = value["targets"]
    if not isinstance(targets, list) or len(targets) != 1:
        raise ValueError("authorization must contain exactly one target")
    target = targets[0]
    if not isinstance(target, dict) or set(target) != {"slug", "version"}:
        raise ValueError("authorization target fields are invalid")
    slug, version = target["slug"], target["version"]
    if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
        raise ValueError("authorization slug is invalid")
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        raise ValueError("authorization version is invalid")
    if value["releaseId"] != f"{slug}-{version}":
        raise ValueError("authorization releaseId does not match slug/version")
    for field in ("contentDigest", "changeSetDigest"):
        validate_digest(value[field], f"authorization {field}")
    if value["headCommit"] != expected_head_commit:
        raise ValueError("authorization headCommit does not match expected head")
    control = value["trustedControl"]
    if not isinstance(control, dict) or set(control) != {
        "repository", "commit", "files", "independentCheckout",
        "executingCheckerPathMatched",
    }:
        raise ValueError("authorization trustedControl is malformed")
    if (
        control["repository"] != EXPECTED_REPOSITORY
        or control["commit"] != expected_control_commit
        or control["independentCheckout"] is not True
        or control["executingCheckerPathMatched"] is not True
    ):
        raise ValueError("authorization trustedControl does not match expectations")
    validate_control_files(
        control["files"], PREFLIGHT_CONTROL_FILES, "authorization trustedControl",
        mode_required=False,
    )
    if value["launcherObservations"] != PREFLIGHT_OBSERVATIONS:
        raise ValueError("authorization launcherObservations are invalid")
    return {"slug": slug, "version": version, "commit": value["headCommit"]}


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise ValueError("staging manifest fields are incomplete or unexpected")
    if (
        value["schemaVersion"] != 2
        or value["researchStatus"] != RESEARCH_STATUS
        or value["format"] != ARTIFACT_FORMAT
        or value["packageDirectory"] != "package"
        or value["worktreeRead"] is not False
        or value["authorizationGranted"] is not False
    ):
        raise ValueError("staging manifest safety state is invalid")
    validate_digest(value["guardResultDigest"], "manifest guardResultDigest")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise ValueError("manifest source fields are invalid")
    if (
        not isinstance(source["commit"], str)
        or COMMIT_PATTERN.fullmatch(source["commit"]) is None
    ):
        raise ValueError("manifest source commit is invalid")
    safe_relative(source["skillPath"], "manifest skillPath")
    if (
        not isinstance(source["treeOid"], str)
        or OID_PATTERN.fullmatch(source["treeOid"]) is None
    ):
        raise ValueError("manifest treeOid is invalid")
    validate_digest(source["packageDigest"], "manifest packageDigest")
    files = value["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_PACKAGE_FILES:
        raise ValueError("manifest files count is invalid")
    paths: list[str] = []
    package_files = []
    for item in files:
        if not isinstance(item, dict) or set(item) != FILE_FIELDS:
            raise ValueError("manifest file fields are invalid")
        path = safe_relative(item["path"], "manifest file path")
        if item["sourceMode"] not in {"100644", "100755"}:
            raise ValueError("manifest sourceMode is invalid")
        expected_mode = "0555" if item["sourceMode"] == "100755" else "0444"
        if item["artifactMode"] != expected_mode:
            raise ValueError("manifest artifactMode does not match sourceMode")
        if (
            not isinstance(item["blobOid"], str)
            or OID_PATTERN.fullmatch(item["blobOid"]) is None
        ):
            raise ValueError("manifest blobOid is invalid")
        validate_digest(item["sha256"], "manifest file sha256")
        paths.append(path)
        package_files.append({
            "path": path,
            "mode": item["sourceMode"],
            "blobOid": item["blobOid"],
            "sha256": item["sha256"],
        })
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError("manifest files must be unique and sorted")
    if not REQUIRED_PACKAGE_FILES.issubset(paths):
        raise ValueError("manifest omits a required package file")
    package_payload = {
        "files": package_files,
        "format": PACKAGE_FORMAT,
        "skillPath": source["skillPath"],
        "treeOid": source["treeOid"],
    }
    expected_package = "sha256:" + hashlib.sha256(
        canonical_json_bytes(package_payload)
    ).hexdigest()
    if source["packageDigest"] != expected_package:
        raise ValueError("manifest packageDigest does not match files")
    descriptor = {key: item for key, item in value.items() if key != "artifactDigest"}
    expected_artifact = "sha256:" + hashlib.sha256(
        canonical_json_bytes(descriptor)
    ).hexdigest()
    if value["artifactDigest"] != expected_artifact:
        raise ValueError("manifest artifactDigest does not match descriptor")
    return value


def validate_staging(
    value: dict[str, Any],
    expected_control_commit: str | None = None,
    expected_head_commit: str | None = None,
) -> dict[str, Any]:
    if set(value) != STAGING_FIELDS:
        raise ValueError("staging fields are incomplete or unexpected")
    if (
        value["schemaVersion"] != 2
        or value["valid"] is not True
        or value["status"] != "committed"
        or value["researchStatus"] != RESEARCH_STATUS
        or value["created"] is not True
        or value["authorizationGranted"] is not False
        or value["residueName"] is not None
        or value["errors"] != []
        or value["artifactState"] != "present-verified-snapshot"
    ):
        raise ValueError("staging result is not a verified committed artifact")
    output_name = value["outputName"]
    if (
        not isinstance(output_name, str)
        or OUTPUT_NAME_PATTERN.fullmatch(output_name) is None
    ):
        raise ValueError("staging outputName is invalid")
    manifest = validate_manifest(value["manifest"])
    if expected_head_commit is not None and (
        manifest["source"]["commit"] != expected_head_commit
    ):
        raise ValueError("staging source commit does not match expected head")
    observations = value["launcherObservations"]
    if not isinstance(observations, dict) or set(observations) != (
        STAGING_OBSERVATION_FIELDS
    ):
        raise ValueError("staging launcherObservations are malformed")
    if expected_control_commit is not None and (
        observations["controlCommit"] != expected_control_commit
    ):
        raise ValueError("staging controlCommit does not match expected control")
    if (
        observations["isolatedModeObserved"] is not True
        or observations["childEnvironmentAllowlisted"] is not True
        or observations["sameControlCommit"] is not True
        or observations["guardAndBuilderSeparated"] is not True
        or observations["guardResultDigestVerified"] is not True
        or observations["independentCheckouts"] is not True
        or observations["inMemoryFraming"] != "trusted-staging-v1"
        or observations["timeoutSeconds"] != 180
        or observations["artifactVerificationSemantics"]
        != "final-snapshot-consumer-must-revalidate"
        or observations["formalWorkflowWired"] is not False
    ):
        raise ValueError("staging launcherObservations safety state is invalid")
    validate_control_files(
        observations["controlFiles"], STAGING_CONTROL_FILES,
        "staging launcherObservations",
        mode_required=True,
    )
    verification = observations["artifactVerification"]
    if not isinstance(verification, dict) or set(verification) != (
        ARTIFACT_VERIFICATION_FIELDS
    ):
        raise ValueError("staging artifactVerification is malformed")
    if (
        verification["manifestMatched"] is not True
        or verification["artifactDigestVerified"] is not True
        or type(verification["fileCount"]) is not int
        or verification["fileCount"] != len(manifest["files"])
        or type(verification["contentBytes"]) is not int
        or verification["contentBytes"] < 0
        or verification["contentBytes"] > MAX_PACKAGE_BYTES
    ):
        raise ValueError("staging artifactVerification is invalid")
    expected_name = (
        manifest["source"]["skillPath"].split("/")[-1]
        + "-"
        + manifest["source"]["commit"][:12]
        + "-"
        + manifest["artifactDigest"][7:19]
    )
    if output_name != expected_name:
        raise ValueError("staging outputName does not match manifest")
    return manifest


def validate_catalog(value: dict[str, Any], slug: str) -> dict[str, Any]:
    key = f"skills/{slug}"
    if key not in value:
        raise ValueError("catalog does not contain authorized slug")
    entry = value[key]
    if not isinstance(entry, dict) or set(entry) != {
        "displayName", "categories", "topics"
    }:
        raise ValueError("catalog target entry fields are invalid")
    name = entry["displayName"]
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError("catalog displayName is invalid")
    for field in ("categories", "topics"):
        items = entry[field]
        if (
            not isinstance(items, list)
            or not items
            or len(items) != len(set(items))
            or not all(isinstance(item, str) and item for item in items)
        ):
            raise ValueError(f"catalog {field} is invalid")
    return {
        "displayName": name,
        "categories": list(entry["categories"]),
        "topics": list(entry["topics"]),
    }


def open_dir_at(parent_fd: int, name: str, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ValueError(f"{label} cannot be opened safely: {error}") from error
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink < 1
        or metadata.st_ino <= 0
    ):
        os.close(descriptor)
        raise ValueError(f"{label} directory metadata is invalid")
    return descriptor


def metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_mode,
        metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_open_file_at(
    parent_fd: int,
    name: str,
    expected_mode: int,
    label: str,
) -> tuple[int, bytes, tuple[int, ...]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise ValueError(f"{label} cannot be opened safely: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or metadata.st_ino <= 0
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or metadata.st_size > MAX_PACKAGE_FILE_BYTES
        ):
            raise ValueError(f"{label} metadata is invalid")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_PACKAGE_FILE_BYTES:
                raise ValueError(f"{label} exceeds size limit")
        after = os.fstat(descriptor)
        identity = metadata_identity(metadata)
        if metadata_identity(after) != identity:
            raise ValueError(f"{label} changed while being read")
        return descriptor, bytes(data), identity
    except Exception:
        os.close(descriptor)
        raise


def read_file_at(parent_fd: int, name: str, expected_mode: int, label: str) -> bytes:
    descriptor, data, _ = read_open_file_at(
        parent_fd, name, expected_mode, label
    )
    os.close(descriptor)
    return data


def list_tree_fd(root_fd: int) -> list[str]:
    result: list[str] = []

    def visit(directory_fd: int, prefix: str) -> None:
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as error:
            raise ValueError(f"package directory cannot be listed: {error}") from error
        for name in names:
            if name in {"", ".", ".."} or "/" in name:
                raise ValueError("package contains an invalid entry name")
            relative = f"{prefix}/{name}" if prefix else name
            metadata = os.stat(
                name, dir_fd=directory_fd, follow_symlinks=False
            )
            if stat.S_ISDIR(metadata.st_mode):
                child = open_dir_at(directory_fd, name, f"package directory {relative}")
                try:
                    opened = os.fstat(child)
                    if (
                        stat.S_IMODE(metadata.st_mode) != 0o555
                        or metadata.st_uid != os.geteuid()
                        or metadata.st_nlink < 1
                        or metadata.st_ino <= 0
                        or (metadata.st_dev, metadata.st_ino)
                        != (opened.st_dev, opened.st_ino)
                    ):
                        raise ValueError(f"package directory {relative} mode is invalid")
                    visit(child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                result.append(relative)
            else:
                raise ValueError(f"package entry {relative} is not regular")
            if len(result) > MAX_PACKAGE_FILES:
                raise ValueError("package file count exceeds limit")

    visit(root_fd, "")
    return result


def open_parent(path: Path) -> int:
    descriptor = open_absolute_directory(path, "artifact parent")
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_nlink < 1
        or metadata.st_ino <= 0
    ):
        os.close(descriptor)
        raise ValueError("artifact parent ownership or mode is invalid")
    return descriptor


class VerifiedPackage:
    def __init__(
        self,
        package_fd: int,
        snapshots: dict[str, bytes],
        descriptors: dict[str, int],
        identities: dict[str, tuple[int, ...]],
        modes: dict[str, int],
        kinds: dict[str, str],
    ) -> None:
        self.package_fd = package_fd
        self.snapshots = snapshots
        self.descriptors = descriptors
        self.identities = identities
        self.modes = modes
        self.kinds = kinds

    def revalidate_all(self) -> None:
        for label, descriptor in self.descriptors.items():
            metadata = os.fstat(descriptor)
            if metadata_identity(metadata) != self.identities[label]:
                raise ValueError(f"{label} FD metadata changed")
            if (
                metadata.st_uid != os.geteuid()
                or metadata.st_nlink < 1
                or metadata.st_ino <= 0
                or stat.S_IMODE(metadata.st_mode) != self.modes[label]
            ):
                raise ValueError(f"{label} FD metadata is invalid")
            if self.kinds[label] == "file":
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError(f"{label} FD is not a single-link regular file")
                os.lseek(descriptor, 0, os.SEEK_SET)
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                if b"".join(chunks) != self.snapshots[label]:
                    raise ValueError(f"{label} FD content changed")
            elif not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"{label} FD is not a directory")

    def close(self) -> None:
        for descriptor in set(self.descriptors.values()):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()


def open_verified_package(parent: Path, staging: dict[str, Any]) -> VerifiedPackage:
    manifest = validate_staging(staging)
    parent_fd = open_parent(parent)
    artifact_fd = -1
    package_fd = -1
    descriptors: dict[str, int] = {"artifact parent": parent_fd}
    identities = {"artifact parent": metadata_identity(os.fstat(parent_fd))}
    modes = {"artifact parent": 0o700}
    kinds = {"artifact parent": "directory"}
    snapshots: dict[str, bytes] = {}
    try:
        artifact_fd = open_dir_at(parent_fd, staging["outputName"], "artifact")
        descriptors["artifact"] = artifact_fd
        identities["artifact"] = metadata_identity(os.fstat(artifact_fd))
        modes["artifact"] = 0o555
        kinds["artifact"] = "directory"
        if stat.S_IMODE(os.fstat(artifact_fd).st_mode) != 0o555:
            raise ValueError("artifact directory mode is invalid")
        manifest_fd, manifest_bytes, manifest_identity = read_open_file_at(
            artifact_fd, "manifest.json", 0o444, "artifact manifest"
        )
        descriptors["artifact manifest"] = manifest_fd
        identities["artifact manifest"] = manifest_identity
        modes["artifact manifest"] = 0o444
        kinds["artifact manifest"] = "file"
        snapshots["artifact manifest"] = manifest_bytes
        observed_manifest = parse_strict_json(manifest_bytes, "artifact manifest")
        if observed_manifest != manifest:
            raise ValueError("artifact manifest bytes do not match staging result")
        package_fd = open_dir_at(artifact_fd, "package", "package")
        descriptors["package"] = package_fd
        identities["package"] = metadata_identity(os.fstat(package_fd))
        modes["package"] = 0o555
        kinds["package"] = "directory"
        if stat.S_IMODE(os.fstat(package_fd).st_mode) != 0o555:
            raise ValueError("package directory mode is invalid")
        expected = {item["path"]: item for item in manifest["files"]}
        if list_tree_fd(package_fd) != sorted(expected):
            raise ValueError("package file set does not match manifest")
        total = 0
        for path, item in expected.items():
            components = path.split("/")
            current = os.dup(package_fd)
            try:
                prefix = ""
                for component in components[:-1]:
                    prefix = f"{prefix}/{component}" if prefix else component
                    label = f"package directory {prefix}"
                    if label in descriptors:
                        following = os.dup(descriptors[label])
                    else:
                        following = open_dir_at(current, component, label)
                        descriptors[label] = following
                        identities[label] = metadata_identity(os.fstat(following))
                        modes[label] = 0o555
                        kinds[label] = "directory"
                        following = os.dup(following)
                    os.close(current)
                    current = following
                mode = int(item["artifactMode"], 8)
                label = f"package file {path}"
                file_fd, data, identity = read_open_file_at(
                    current, components[-1], mode, label
                )
                descriptors[label] = file_fd
                identities[label] = identity
                modes[label] = mode
                kinds[label] = "file"
                snapshots[label] = data
            finally:
                os.close(current)
            total += len(data)
            if total > MAX_PACKAGE_BYTES:
                raise ValueError("package bytes exceed limit")
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"package file {path} digest is invalid")
            snapshots[path] = data
        artifact_identity = os.fstat(artifact_fd)
        package_identity = os.fstat(package_fd)
        reopened_artifact = open_dir_at(parent_fd, staging["outputName"], "artifact")
        try:
            reopened_package = open_dir_at(reopened_artifact, "package", "package")
            try:
                if (
                    (os.fstat(reopened_artifact).st_dev, os.fstat(reopened_artifact).st_ino)
                    != (artifact_identity.st_dev, artifact_identity.st_ino)
                    or (os.fstat(reopened_package).st_dev, os.fstat(reopened_package).st_ino)
                    != (package_identity.st_dev, package_identity.st_ino)
                ):
                    raise ValueError("artifact path identity changed during verification")
            finally:
                os.close(reopened_package)
        finally:
            os.close(reopened_artifact)
        if metadata_identity(os.fstat(parent_fd)) != identities["artifact parent"]:
            raise ValueError("artifact parent FD metadata changed during verification")
        verified = VerifiedPackage(
            package_fd, snapshots, descriptors, identities, modes, kinds
        )
        verified.revalidate_all()
        return verified
    except Exception:
        for descriptor in set(descriptors.values()):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def package_version(skill_bytes: bytes) -> str:
    try:
        text = skill_bytes.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError(f"SKILL.md is not UTF-8: {error}") from error
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md frontmatter is missing")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in values:
            raise ValueError(f"SKILL.md frontmatter duplicates {key}")
        values[key] = value.strip()
    version = values.get("version")
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        raise ValueError("SKILL.md version is invalid")
    return version


def update_digest(hasher: Any, label: str, payload: bytes) -> None:
    label_bytes = label.encode("utf-8")
    hasher.update(len(label_bytes).to_bytes(8, "big"))
    hasher.update(label_bytes)
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)


def recompute_content_digest(
    slug: str,
    catalog_entry: dict[str, Any],
    manifest: dict[str, Any],
    snapshots: dict[str, bytes],
) -> str:
    skill_path = f"skills/{slug}"
    if manifest["source"]["skillPath"] != skill_path:
        raise ValueError("contentDigest target does not match manifest skillPath")
    hasher = hashlib.sha256()
    update_digest(
        hasher,
        f"{skill_path}#catalog",
        canonical_json_bytes(catalog_entry),
    )
    expected_paths = [item["path"] for item in manifest["files"]]
    if set(expected_paths) != {
        key for key in snapshots if not key.startswith(("artifact ", "package "))
    }:
        raise ValueError("contentDigest snapshots do not cover every manifest file")
    for relative in sorted(expected_paths):
        update_digest(hasher, f"{skill_path}/{relative}", snapshots[relative])
    return "sha256:" + hasher.hexdigest()


def git_environment() -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(TRUSTED_GIT_ENTRY.parent),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_EXTERNAL_DIFF": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }


def run_git(root: Path, *args: str, text: bool = False) -> subprocess.CompletedProcess:
    command = [
        str(TRUSTED_GIT_ENTRY), "--no-replace-objects",
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "diff.external=", *args,
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=root,
        env=git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = started + GIT_TIMEOUT_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observation = terminate(process, "trusted-git-timeout")
                raise ChildTerminationError(
                    "trusted Git execution exceeded 30-second wall clock",
                    observation,
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(chunk)
                combined = len(output["stdout"]) + len(output["stderr"])
                if combined > MAX_GIT_OUTPUT_BYTES:
                    observation = terminate(process, "trusted-git-output-overflow")
                    raise ChildTerminationError(
                        "trusted Git combined output exceeds 12 MiB limit",
                        observation,
                    )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            observation = terminate(process, "trusted-git-timeout")
            raise ChildTerminationError(
                "trusted Git execution exceeded 30-second wall clock",
                observation,
            )
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            observation = terminate(process, "trusted-git-timeout")
            raise ChildTerminationError(
                "trusted Git execution exceeded 30-second wall clock",
                observation,
            ) from error
    except Exception:
        if process.poll() is None:
            terminate(process, "trusted-git-exception")
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    completed = subprocess.CompletedProcess(
        command, returncode, bytes(output["stdout"]), bytes(output["stderr"])
    )
    if not text:
        return completed
    try:
        stdout = completed.stdout.decode("utf-8", errors="strict")
        stderr = completed.stderr.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("trusted Git output is not UTF-8") from error
    return subprocess.CompletedProcess(command, completed.returncode, stdout, stderr)


def validate_private_object_store(root: Path, label: str) -> tuple[int, ...]:
    def validate_directory(metadata: os.stat_result, relative: str) -> None:
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink < 1
            or metadata.st_ino <= 0
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ValueError(f"{label} object store directory is unsafe: {relative}")

    def inspect(directory_fd: int, relative: str) -> None:
        opened = os.fstat(directory_fd)
        validate_directory(opened, relative)
        for name in sorted(os.listdir(directory_fd)):
            if name in {"", ".", ".."} or "/" in name:
                raise ValueError(f"{label} object store entry name is invalid")
            child_relative = f"{relative}/{name}"
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"{label} object store symlink is forbidden: {child_relative}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    if (
                        metadata.st_dev, metadata.st_ino
                    ) != (
                        os.fstat(child_fd).st_dev, os.fstat(child_fd).st_ino
                    ):
                        raise ValueError(
                            f"{label} object store component identity changed: "
                            f"{child_relative}"
                        )
                    inspect(child_fd, child_relative)
                finally:
                    os.close(child_fd)
            else:
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_nlink != 1
                    or metadata.st_ino <= 0
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                ):
                    raise ValueError(
                        f"{label} object store file is unsafe: {child_relative}"
                    )
                descriptor = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    opened_file = os.fstat(descriptor)
                    if metadata_identity(opened_file) != metadata_identity(metadata):
                        raise ValueError(
                            f"{label} object store file identity changed: "
                            f"{child_relative}"
                        )
                finally:
                    os.close(descriptor)
        if metadata_identity(os.fstat(directory_fd)) != metadata_identity(opened):
            raise ValueError(f"{label} object store directory changed: {relative}")

    root_fd = open_absolute_directory(root, f"{label} root")
    git_fd = -1
    objects_fd = -1
    try:
        git_fd = os.open(
            ".git",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        git_metadata = os.fstat(git_fd)
        validate_directory(git_metadata, ".git")
        if "commondir" in os.listdir(git_fd):
            raise ValueError(f"{label} shared Git common directory is forbidden")
        objects_fd = os.open(
            "objects",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=git_fd,
        )
        objects_metadata = os.fstat(objects_fd)
        validate_directory(objects_metadata, ".git/objects")
        try:
            info_fd = os.open(
                "info",
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=objects_fd,
            )
        except FileNotFoundError:
            info_fd = -1
        if info_fd >= 0:
            try:
                if {"alternates", "http-alternates"}.intersection(
                    os.listdir(info_fd)
                ):
                    raise ValueError(f"{label} object store alternates are forbidden")
            finally:
                os.close(info_fd)
        inspect(objects_fd, ".git/objects")
        return (
            git_metadata.st_dev, git_metadata.st_ino,
            objects_metadata.st_dev, objects_metadata.st_ino,
        )
    except OSError as error:
        raise ValueError(f"{label} object store cannot be opened safely: {error}") from error
    finally:
        if objects_fd >= 0:
            os.close(objects_fd)
        if git_fd >= 0:
            os.close(git_fd)
        os.close(root_fd)


def normalize_origin(value: str) -> str:
    stripped = value.strip()
    web_prefix = "https" + "://"
    if stripped.startswith(web_prefix):
        normalized = stripped[len(web_prefix):]
    elif stripped.startswith("ssh://git@"):
        normalized = stripped[len("ssh://git@"):]
    elif stripped.startswith("git@github.com:"):
        normalized = "github.com/" + stripped[len("git@github.com:"):]
    else:
        raise ValueError("origin must use an approved GitHub transport")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/")


def verify_checkout(root: Path, expected_commit: str, label: str) -> tuple[int, ...]:
    root_fd = open_absolute_directory(root, f"{label} root")
    try:
        root_identity = os.fstat(root_fd)
        git_identity = validate_private_object_store(root, label)
        top = run_git(root, "rev-parse", "--show-toplevel", text=True)
        if top.returncode != 0 or Path(top.stdout.strip()) != root:
            raise ValueError(f"{label} root is not the Git top-level checkout")
        git_dir = run_git(root, "rev-parse", "--git-dir", text=True)
        common_dir = run_git(root, "rev-parse", "--git-common-dir", text=True)
        object_dir = run_git(root, "rev-parse", "--git-path", "objects", text=True)
        if (
            git_dir.returncode != 0
            or git_dir.stdout.strip() != ".git"
            or common_dir.returncode != 0
            or common_dir.stdout.strip() != ".git"
            or object_dir.returncode != 0
            or object_dir.stdout.strip() != ".git/objects"
        ):
            raise ValueError(
                f"{label} checkout must use an independent .git common directory "
                "and object store"
            )
        origin = run_git(root, "remote", "get-url", "origin", text=True)
        if (
            origin.returncode != 0
            or normalize_origin(origin.stdout) != EXPECTED_REPOSITORY
        ):
            raise ValueError(f"{label} origin does not match expected repository")
        head = run_git(
            root, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}",
            text=True,
        )
        branch = run_git(root, "symbolic-ref", "--quiet", "HEAD", text=True)
        upstream_name = run_git(
            root, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
            "@{upstream}", text=True,
        )
        tracking = run_git(
            root, "rev-parse", "--verify", "--end-of-options",
            f"{EXPECTED_TRACKING_REF}^{{commit}}", text=True,
        )
        if (
            head.returncode != 0
            or head.stdout.strip() != expected_commit
            or branch.returncode != 0
            or branch.stdout.strip() != EXPECTED_BRANCH
            or upstream_name.returncode != 0
            or upstream_name.stdout.strip() != "origin/main"
            or tracking.returncode != 0
            or tracking.stdout.strip() != expected_commit
        ):
            raise ValueError(
                f"{label} HEAD, main branch, or origin/main tracking ref is inconsistent"
            )
        repeated = open_absolute_directory(root, f"{label} root")
        try:
            after = os.fstat(repeated)
            if (after.st_dev, after.st_ino) != (
                root_identity.st_dev, root_identity.st_ino
            ):
                raise ValueError(f"{label} root identity changed")
        finally:
            os.close(repeated)
        if validate_private_object_store(root, label) != git_identity:
            raise ValueError(f"{label} .git identity changed")
        return git_identity
    finally:
        os.close(root_fd)


def git_tree_files(
    root: Path,
    commit: str,
    skill_path: str,
) -> tuple[str, list[dict[str, str]]]:
    root_entry = run_git(root, "ls-tree", "-z", commit, "--", skill_path)
    records = [item for item in root_entry.stdout.split(b"\0") if item]
    if root_entry.returncode != 0 or len(records) != 1:
        raise ValueError("manifest skill tree cannot be resolved")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, kind, tree_oid = metadata.decode("ascii").split(" ")
        observed_path = raw_path.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise ValueError("manifest skill tree metadata is malformed") from error
    if (
        mode != "040000" or kind != "tree" or observed_path != skill_path
        or OID_PATTERN.fullmatch(tree_oid) is None
    ):
        raise ValueError("manifest skill tree is not a regular Git tree")
    listing = run_git(
        root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", skill_path
    )
    if listing.returncode != 0:
        raise ValueError("manifest skill files cannot be resolved")
    prefix = skill_path + "/"
    files: list[dict[str, str]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            file_mode, kind, oid = metadata.decode("ascii").split(" ")
            full_path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError) as error:
            raise ValueError("manifest file Git metadata is malformed") from error
        if (
            kind != "blob" or file_mode not in {"100644", "100755"}
            or not full_path.startswith(prefix) or OID_PATTERN.fullmatch(oid) is None
        ):
            raise ValueError("manifest file is not a regular Git blob")
        relative = safe_relative(full_path[len(prefix):], "Git tree file path")
        blob = run_git(root, "cat-file", "blob", oid)
        if blob.returncode != 0:
            raise ValueError(f"manifest blob cannot be read: {relative}")
        files.append({
            "path": relative,
            "sourceMode": file_mode,
            "artifactMode": "0555" if file_mode == "100755" else "0444",
            "blobOid": oid,
            "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
        })
    files.sort(key=lambda item: item["path"].encode("utf-8"))
    return tree_oid, files


def verify_control_evidence(
    root: Path,
    commit: str,
    evidence: Any,
    paths: dict[str, str],
    label: str,
    *,
    mode_required: bool,
) -> None:
    validate_control_files(evidence, paths, label, mode_required=mode_required)
    for name, relative in paths.items():
        entry = run_git(root, "ls-tree", "-z", commit, "--", relative)
        records = [item for item in entry.stdout.split(b"\0") if item]
        if entry.returncode != 0 or len(records) != 1:
            raise ValueError(f"{label} {name} is absent from control commit")
        try:
            metadata, raw_path = records[0].split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split(" ")
            observed_path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError) as error:
            raise ValueError(f"{label} {name} Git metadata is malformed") from error
        blob = run_git(root, "cat-file", "blob", oid)
        expected = {
            "path": relative,
            "blobOid": oid,
            "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
        }
        if mode_required:
            expected["mode"] = mode
        if (
            kind != "blob" or mode not in {"100644", "100755"}
            or observed_path != relative or blob.returncode != 0
            or evidence[name] != expected
        ):
            raise ValueError(f"{label} {name} does not match control commit")


def verify_git_bindings(
    candidate_root: Path,
    control_root: Path,
    expected_head_commit: str,
    expected_control_commit: str,
    authorization: dict[str, Any],
    staging: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    candidate_identity = verify_checkout(
        candidate_root, expected_head_commit, "candidate"
    )
    control_identity = verify_checkout(
        control_root, expected_control_commit, "control"
    )
    if candidate_root == control_root or candidate_identity == control_identity:
        raise ValueError("candidate and control must be independent checkouts")
    parents = run_git(
        candidate_root, "rev-list", "--parents", "-n", "1",
        expected_head_commit, text=True,
    )
    parent_fields = parents.stdout.strip().split()
    if (
        parents.returncode != 0
        or len(parent_fields) != 2
        or parent_fields[0] != expected_head_commit
        or parent_fields[1] != authorization["candidateCommit"]
    ):
        raise ValueError(
            "authorization candidateCommit is not the sole parent of candidate HEAD"
        )
    ancestry = run_git(
        candidate_root, "merge-base", "--is-ancestor",
        authorization["baseCommit"], authorization["candidateCommit"],
    )
    if ancestry.returncode != 0:
        raise ValueError("authorization baseCommit is not an ancestor of candidateCommit")
    tree_oid, files = git_tree_files(
        candidate_root, expected_head_commit, manifest["source"]["skillPath"]
    )
    if tree_oid != manifest["source"]["treeOid"] or files != manifest["files"]:
        raise ValueError("manifest tree/files/blob evidence does not match candidate Git")
    verify_control_evidence(
        control_root, expected_control_commit,
        authorization["trustedControl"]["files"], PREFLIGHT_CONTROL_FILES,
        "preflight control evidence", mode_required=False,
    )
    verify_control_evidence(
        control_root, expected_control_commit,
        staging["launcherObservations"]["controlFiles"], STAGING_CONTROL_FILES,
        "staging control evidence", mode_required=True,
    )


class ChildTerminationError(RuntimeError):
    def __init__(self, message: str, termination: dict[str, Any]) -> None:
        super().__init__(message)
        self.termination = termination


def terminate(process: subprocess.Popen[bytes], reason: str) -> dict[str, Any]:
    observed_returncode = process.poll()
    observation: dict[str, Any] = {
        "attempted": observed_returncode is None,
        "reason": reason,
        "signal": "SIGKILL",
        "processGroupTargeted": observed_returncode is None,
        "leaderPid": process.pid,
        "leaderReaped": observed_returncode is not None,
        "returnCode": observed_returncode,
    }
    if observed_returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # The isolated group leader may exit between poll() and killpg().
            # Reap it below; never retry against a potentially reused PGID.
            observation["processGroupTargeted"] = False
            observation["leaderExitedBeforeSignal"] = True
        except OSError as error:
            observation["killError"] = (
                f"{type(error).__name__}: {str(error)[:256]}"
            )
    try:
        observation["returnCode"] = process.wait(
            timeout=CHILD_REAP_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as error:
        raise ChildTerminationError(
            "child process-group leader could not be reaped", observation
        ) from error
    observation["leaderReaped"] = process.poll() is not None
    if observation["leaderReaped"] is not True:
        raise ChildTerminationError(
            "child process-group leader reap was not confirmed", observation
        )
    if "killError" in observation:
        raise ChildTerminationError(
            "child process group could not be terminated safely", observation
        )
    return observation


def run_simulator(package_fd: int, binding: dict[str, Any]) -> dict[str, Any]:
    python = Path(sys.executable).resolve(strict=True)
    if not stat.S_ISREG(os.stat(python).st_mode):
        raise ValueError("Python simulator executable is invalid")
    command = [
        str(python), "-I", "-c", SIMULATOR, str(package_fd),
        canonical_json_bytes(binding).decode("utf-8"),
    ]
    process = subprocess.Popen(
        command,
        cwd="/",
        env={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(python.parent),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(package_fd,),
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + CHILD_TIMEOUT_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observation = terminate(process, "timeout")
                raise ChildTerminationError(
                    "simulator execution timed out", observation
                )
            events = selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(chunk)
                if sum(len(item) for item in output.values()) > MAX_CHILD_OUTPUT_BYTES:
                    observation = terminate(process, "output-overflow")
                    raise ChildTerminationError(
                        "simulator output exceeds limit", observation
                    )
        returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except Exception:
        if process.poll() is None:
            terminate(process, "exception")
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    if returncode != 0 or output["stderr"]:
        raise ValueError("simulator failed or wrote unexpected stderr")
    result = parse_strict_json(bytes(output["stdout"]), "simulator result")
    expected_fields = {
        "schemaVersion", "simulated", "packageFdInherited", "slug", "version",
        "displayName", "categories", "topics", "allManifestFilesVerified",
        "manifestFileCount",
    }
    if set(result) != expected_fields:
        raise ValueError("simulator result fields are invalid")
    return result


def consume(
    authorization: dict[str, Any],
    staging: dict[str, Any],
    catalog: dict[str, Any],
    artifact_parent: Path,
    candidate_root: Path,
    control_root: Path,
    expected_control_commit: str,
    expected_head_commit: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if COMMIT_PATTERN.fullmatch(expected_control_commit) is None:
        raise ValueError("expected control commit must be a full lowercase SHA-1")
    if COMMIT_PATTERN.fullmatch(expected_head_commit) is None:
        raise ValueError("expected head commit must be a full lowercase SHA-1")
    binding = validate_authorization(
        authorization, expected_control_commit, expected_head_commit, now=now
    )
    manifest = validate_staging(
        staging, expected_control_commit, expected_head_commit
    )
    source = manifest["source"]
    expected_skill_path = f"skills/{binding['slug']}"
    if source["commit"] != binding["commit"]:
        raise ValueError("authorization/staging commit mismatch")
    if source["skillPath"] != expected_skill_path:
        raise ValueError("authorization/staging slug mismatch")
    verify_git_bindings(
        candidate_root,
        control_root,
        expected_head_commit,
        expected_control_commit,
        authorization,
        staging,
        manifest,
    )
    catalog_binding = validate_catalog(catalog, binding["slug"])
    catalog_entry = catalog[expected_skill_path]
    verified = open_verified_package(artifact_parent, staging)
    snapshots = verified.snapshots
    primary_error: BaseException | None = None
    try:
        observed_content_bytes = sum(
            len(snapshots[item["path"]]) for item in manifest["files"]
        )
        if (
            staging["launcherObservations"]["artifactVerification"]["contentBytes"]
            != observed_content_bytes
        ):
            raise ValueError(
                "staging artifactVerification contentBytes does not match package"
            )
        observed_version = package_version(snapshots["SKILL.md"])
        if observed_version != binding["version"]:
            raise ValueError("authorization/package version mismatch")
        observed_content_digest = recompute_content_digest(
            binding["slug"], catalog_entry, manifest, snapshots
        )
        if observed_content_digest != authorization["contentDigest"]:
            raise ValueError(
                "authorization contentDigest does not match catalog and package"
            )
        simulator_binding = {
            "slug": binding["slug"],
            "version": binding["version"],
            **catalog_binding,
            "files": [
                {
                    "path": item["path"],
                    "artifactMode": item["artifactMode"],
                    "sha256": item["sha256"],
                }
                for item in manifest["files"]
            ],
        }
        simulation = run_simulator(verified.package_fd, simulator_binding)
        if (
            simulation["simulated"] is not True
            or simulation["packageFdInherited"] is not True
            or simulation["allManifestFilesVerified"] is not True
            or type(simulation["manifestFileCount"]) is not int
            or simulation["manifestFileCount"] != len(manifest["files"])
            or simulation["slug"] != binding["slug"]
            or simulation["version"] != binding["version"]
            or simulation["displayName"] != catalog_binding["displayName"]
            or simulation["categories"] != catalog_binding["categories"]
            or simulation["topics"] != catalog_binding["topics"]
        ):
            raise ValueError("simulator result does not match verified package")
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            verified.revalidate_all()
        except BaseException:
            if primary_error is None:
                raise
        finally:
            verified.close()
    return {
        "schemaVersion": 1,
        "valid": True,
        "status": "simulated",
        "researchStatus": RESEARCH_STATUS,
        "authorizationContentValidated": True,
        "authorizationProvenanceVerified": False,
        "authorizationProvenance":
            "content-validated-self-asserted-input-not-launcher-attested",
        "stagingValidated": True,
        "catalogValidated": True,
        "packageFdPreserved": True,
        "cliMode": "simulation-only",
        "networkUsed": False,
        "credentialsAccepted": False,
        "publicationAttempted": False,
        "slug": binding["slug"],
        "version": binding["version"],
        "displayName": catalog_binding["displayName"],
        "categories": catalog_binding["categories"],
        "topics": catalog_binding["topics"],
        "commit": binding["commit"],
        "controlCommit": expected_control_commit,
        "candidateCheckoutVerified": True,
        "controlCheckoutVerified": True,
        "authorizationFreshnessSeconds": int(MAX_AUTHORIZATION_AGE.total_seconds()),
        "oneTimeRunReplayProtection": False,
        "realMutationAllowed": False,
        "trustUpgradeRequired":
            "external-launcher-pinned-to-verified-control-blob",
        "contentDigest": authorization["contentDigest"],
        "artifactDigest": manifest["artifactDigest"],
        "allFileDescriptorsRevalidated": True,
        "errors": [],
    }


def consume_attested_frame(
    frame: bytes,
    expected_nonce: bytes,
    expected_invocation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if (
        type(expected_nonce) is not bytes
        or len(expected_nonce) != ATTESTED_NONCE_BYTES
    ):
        raise ValueError("expected run nonce must contain exactly 32 bytes")
    parts = parse_frame_parts(frame)
    invocation = parse_strict_json(parts[0], "attested invocation")
    if parts[0] != canonical_json_bytes(invocation):
        raise ValueError("attested invocation is not canonical JSON")
    validate_attested_invocation(invocation, expected_invocation)
    invocation_digest = (
        "sha256:" + hashlib.sha256(parts[0]).hexdigest()
    )
    preflight_envelope = parse_strict_json(
        parts[1], "attested preflight envelope"
    )
    staging_envelope = parse_strict_json(
        parts[2], "attested staging envelope"
    )
    if parts[1] != canonical_json_bytes(preflight_envelope):
        raise ValueError("attested preflight envelope is not canonical JSON")
    if parts[2] != canonical_json_bytes(staging_envelope):
        raise ValueError("attested staging envelope is not canonical JSON")
    authorization = validate_attested_envelope(
        preflight_envelope,
        "preflight",
        expected_nonce,
        invocation_digest,
    )
    staging = validate_attested_envelope(
        staging_envelope,
        "staging",
        expected_nonce,
        invocation_digest,
    )
    catalog_evidence = invocation["catalog"]
    if (
        "sha256:" + hashlib.sha256(parts[3]).hexdigest()
        != catalog_evidence["sha256"]
    ):
        raise ValueError("candidate HEAD catalog blob digest does not match invocation")
    catalog = parse_strict_json(parts[3], "candidate HEAD catalog blob")
    if authorization.get("baseCommit") != invocation["baseCommit"]:
        raise ValueError("attested preflight base commit does not match invocation")
    if authorization.get("headCommit") != invocation["headCommit"]:
        raise ValueError("attested preflight head commit does not match invocation")
    manifest = staging.get("manifest")
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("source"), dict)
        or manifest["source"].get("commit") != invocation["headCommit"]
    ):
        raise ValueError("attested staging head commit does not match invocation")
    if expected_nonce in _CONSUMED_ATTESTATION_NONCES:
        raise ValueError("attested run nonce has already been consumed")
    _CONSUMED_ATTESTATION_NONCES.add(expected_nonce)
    result = consume(
        authorization,
        staging,
        catalog,
        Path(invocation["artifactParent"]),
        Path(invocation["candidateRoot"]),
        Path(invocation["controlRoot"]),
        invocation["controlCommit"],
        invocation["headCommit"],
        now=now,
    )
    result.pop("networkUsed", None)
    return {
        **result,
        "authorizationProvenanceVerified": False,
        "authorizationProvenance":
            "process-local-length-framed-control-blobs-not-externally-authenticated",
        "controlCommitExternallyAuthenticated": False,
        "processLocalFrameBinding": True,
        "persistentReplayProtection": False,
        "oneTimeRunReplayProtection": False,
        "noNetworkCallsRequested": True,
        "networkIsolationEnforced": False,
        "attestedInvocationDigest": invocation_digest,
        "attestedCatalogBlobOid": catalog_evidence["blobOid"],
        "envelopedPhases": ["preflight", "staging"],
        "consumerExecutionCompleted": True,
        "trustUpgradeRequired":
            "external-control-commit-authentication-and-persistent-replay-store",
    }


def failure(
    message: str,
    termination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schemaVersion": 1,
        "valid": False,
        "status": "rejected",
        "researchStatus": RESEARCH_STATUS,
        "authorizationContentValidated": False,
        "authorizationProvenanceVerified": False,
        "authorizationProvenance":
            "content-validated-self-asserted-input-not-launcher-attested",
        "stagingValidated": False,
        "catalogValidated": False,
        "packageFdPreserved": False,
        "cliMode": "simulation-only",
        "networkUsed": False,
        "credentialsAccepted": False,
        "publicationAttempted": False,
        "oneTimeRunReplayProtection": False,
        "realMutationAllowed": False,
        "trustUpgradeRequired":
            "external-launcher-pinned-to-verified-control-blob",
        "errors": [message[:1024]],
    }
    if termination is not None:
        result["termination"] = termination
    return result


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated:
        print(json.dumps(failure("consumer must run with Python isolated mode (-I)")))
        return 2
    parser = StructuredArgumentParser()
    parser.add_argument("--authorization-result", type=Path, required=True)
    parser.add_argument("--staging-result", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--artifact-parent", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--expected-control-commit", required=True)
    parser.add_argument("--expected-head-commit", required=True)
    try:
        args = parser.parse_args(argv)
        result = consume(
            read_input(args.authorization_result, "authorization result"),
            read_input(args.staging_result, "staging result"),
            read_input(args.catalog, "catalog"),
            args.artifact_parent,
            args.candidate_root,
            args.control_root,
            args.expected_control_commit,
            args.expected_head_commit,
        )
    except ChildTerminationError as error:
        result = failure(str(error), error.termination)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result = failure(str(error))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

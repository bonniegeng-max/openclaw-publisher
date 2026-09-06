#!/usr/bin/env python3
"""从同一 control commit 隔离执行 guard 与 immutable staging builder。"""

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
from pathlib import Path, PurePosixPath
from typing import Any


TRUSTED_GIT_ENTRY = Path("/usr/bin/git")
EXPECTED_REPOSITORY = "github.com/bonniegeng-max/openclaw-publisher"
CONTROL_FILES = {
    "guard": "research/skill-release-authorization-vnext/safe_publish_target_guard.py",
    "builder": "research/skill-release-authorization-vnext/immutable_staging_builder.py",
}
FRAME_MAGIC = b"trusted-staging-v1\0"
CHILD_TIMEOUT_SECONDS = 180
CHILD_REAP_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 30
MAX_CONTROL_FILE_BYTES = 2 * 1024 * 1024
MAX_CHILD_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_FILES = 1024
MAX_ARTIFACT_FILE_BYTES = 10 * 1024 * 1024
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
OUTPUT_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}-[0-9a-f]{12}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_SKILL_FILES = {"SKILL.md", "CHANGELOG.md", ".clawhubignore"}
RESULT_FIELDS = {
    "schemaVersion", "valid", "status", "researchStatus", "created",
    "authorizationGranted", "outputName", "residueName", "manifest", "errors",
}
GUARD_RESULT_FIELDS = {
    "schemaVersion", "valid", "decision", "eventName", "ref", "dryRun",
    "changedOnly", "authorizationEligible", "authorized", "mutationAllowed",
    "targetCount", "skillPath", "slug", "packageSnapshot", "baseCommit",
    "headCommit", "eventBefore", "eventSha", "eventRef", "blockingReasons",
}
GUARD_SNAPSHOT_FIELDS = {"treeOid", "files", "packageDigest"}
GUARD_FILE_FIELDS = {"path", "mode", "blobOid", "sha256"}
MANIFEST_FIELDS = {
    "schemaVersion", "researchStatus", "format", "guardResultDigest", "source",
    "packageDirectory", "files", "worktreeRead", "authorizationGranted",
    "artifactDigest",
}
SOURCE_FIELDS = {"commit", "skillPath", "treeOid", "packageDigest"}
MANIFEST_FILE_FIELDS = {
    "path", "sourceMode", "artifactMode", "blobOid", "sha256",
}


GUARD_BOOTSTRAP = r"""
import json
import struct
import sys
import types

MAGIC = b"trusted-staging-v1\0"
raw = sys.stdin.buffer.read()
if not raw.startswith(MAGIC):
    raise RuntimeError("invalid trusted staging frame magic")
offset = len(MAGIC)
parts = []
for _ in range(2):
    if len(raw) < offset + 8:
        raise RuntimeError("truncated trusted staging frame")
    length = struct.unpack(">Q", raw[offset:offset + 8])[0]
    offset += 8
    if length > 2 * 1024 * 1024 or len(raw) < offset + length:
        raise RuntimeError("invalid trusted staging frame length")
    parts.append(raw[offset:offset + length])
    offset += length
if offset != len(raw):
    raise RuntimeError("trailing trusted staging frame bytes")

guard_source, request_source = parts
request = json.loads(request_source.decode("utf-8"))
guard_path = request.pop("guardPath")
guard = types.ModuleType("_trusted_staging_guard")
guard.__file__ = guard_path
guard.__package__ = None
exec(compile(guard_source, guard_path, "exec"), guard.__dict__)
result = guard.evaluate(
    request["candidateRoot"],
    event_name=request["eventName"],
    dry_run=request["dryRun"],
    changed_only=request["changedOnly"],
    ref=request["ref"],
    base=request["base"],
    head=request["head"],
    skill_path=request["skillPath"],
    event_before=request["eventBefore"],
    event_sha=request["eventSha"],
    event_ref=request["eventRef"],
)
sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if result.get("valid") else 2)
""".strip()


BUILDER_BOOTSTRAP = r"""
import json
import pathlib
import struct
import sys
import types

MAGIC = b"trusted-staging-v1\0"
raw = sys.stdin.buffer.read()
if not raw.startswith(MAGIC):
    raise RuntimeError("invalid trusted staging frame magic")
offset = len(MAGIC)
parts = []
for _ in range(3):
    if len(raw) < offset + 8:
        raise RuntimeError("truncated trusted staging frame")
    length = struct.unpack(">Q", raw[offset:offset + 8])[0]
    offset += 8
    if length > 2 * 1024 * 1024 or len(raw) < offset + length:
        raise RuntimeError("invalid trusted staging frame length")
    parts.append(raw[offset:offset + length])
    offset += length
if offset != len(raw):
    raise RuntimeError("trailing trusted staging frame bytes")

guard_source, builder_source, request_source = parts
request = json.loads(request_source.decode("utf-8"))
guard_path = request.pop("guardPath")
builder_path = request.pop("builderPath")
guard_result = request.pop("guardResult")
guard = types.ModuleType("_trusted_staging_guard")
guard.__file__ = guard_path
guard.__package__ = None
exec(compile(guard_source, guard_path, "exec"), guard.__dict__)
builder_namespace = {
    "__name__": "_trusted_staging_builder",
    "__file__": builder_path,
    "__package__": None,
    "GUARD": guard,
    "_TRUSTED_GUARD_INJECTED": True,
}
exec(compile(builder_source, builder_path, "exec"), builder_namespace)
result = builder_namespace["build_staging"](
    pathlib.Path(request["candidateRoot"]),
    pathlib.Path(request["outputParent"]),
    guard_result=guard_result,
)
sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if result["valid"] else 2)
""".strip()


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid launcher arguments: {message}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"child JSON has duplicate key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> Any:
    raise ValueError(f"child JSON contains invalid constant: {value}")


def parse_strict_json(raw: bytes, label: str) -> dict[str, Any]:
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


def failure(
    message: str,
    child_exit_code: int | None = None,
    *,
    artifact_state: str = "unknown",
    created: bool | None = None,
    output_name: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": 1,
        "valid": False,
        "status": "launcher-failed",
        "researchStatus": "research-only-not-wired",
        "created": created,
        "authorizationGranted": False,
        "outputName": output_name,
        "residueName": None,
        "manifest": None,
        "errors": [message],
        "phase": "trusted-staging-launcher",
        "artifactState": artifact_state,
    }
    if child_exit_code is not None:
        value["childExitCode"] = child_exit_code
    return value


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def path_uses_symlink(path: Path) -> bool:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
    except OSError as error:
        raise ValueError(f"path cannot be inspected: {error}") from error
    return False


def resolve_executables() -> tuple[Path, Path]:
    python_path = lexical_absolute(Path(sys.executable)).resolve(strict=True)
    git_entry = TRUSTED_GIT_ENTRY
    git_path = git_entry.resolve(strict=True)
    for label, path in (("Python", python_path), ("Git", git_path)):
        metadata = os.stat(path)
        if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
            raise ValueError(f"trusted {label} executable is unusable")
    return python_path, git_entry


def child_environment(git_path: Path) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(git_path.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def git_environment(git_path: Path) -> dict[str, str]:
    return {
        **child_environment(git_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_EXTERNAL_DIFF": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }


def run_git(
    git_path: Path,
    root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess:
    command = [
        str(git_path), "--no-replace-objects",
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "diff.external=", *args,
    ]
    try:
        completed = run_bounded_child(
            command,
            cwd=root,
            environment=git_environment(git_path),
            payload=b"",
            timeout_seconds=GIT_TIMEOUT_SECONDS,
            maximum_output_bytes=MAX_GIT_OUTPUT_BYTES,
            label="trusted Git",
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("trusted Git command timed out") from error
    if not text:
        return completed
    try:
        stdout = completed.stdout.decode("utf-8", errors="strict")
        stderr = completed.stderr.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("trusted Git output is not valid UTF-8") from error
    return subprocess.CompletedProcess(
        args=completed.args,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_bounded_child(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    payload: bytes,
    timeout_seconds: float | None = None,
    maximum_output_bytes: int | None = None,
    label: str = "trusted staging child",
) -> subprocess.CompletedProcess:
    if timeout_seconds is None:
        timeout_seconds = CHILD_TIMEOUT_SECONDS
    if maximum_output_bytes is None:
        maximum_output_bytes = MAX_CHILD_OUTPUT_BYTES
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_seconds

    def terminate() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass

    def terminate_and_reap() -> None:
        terminate()
        try:
            process.wait(timeout=CHILD_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"{label} termination could not be confirmed"
            ) from error

    try:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        streams = {
            process.stdout.fileno(): ("stdout", bytearray()),
            process.stderr.fileno(): ("stderr", bytearray()),
        }
        stdin_fd = process.stdin.fileno()
        payload_view = memoryview(payload)
        payload_offset = 0
        total_output = 0
        selector = selectors.DefaultSelector()
        try:
            for descriptor in streams:
                os.set_blocking(descriptor, False)
                selector.register(descriptor, selectors.EVENT_READ, "output")
            if payload:
                os.set_blocking(stdin_fd, False)
                selector.register(stdin_fd, selectors.EVENT_WRITE, "input")
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    terminate_and_reap()
                    raise subprocess.TimeoutExpired(
                        command,
                        timeout_seconds,
                    )
                events = selector.select(timeout=min(remaining, 0.25))
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
                                key.fd,
                                payload_view[payload_offset : payload_offset + 65536],
                            )
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            written = 0
                            payload_offset = len(payload_view)
                        else:
                            payload_offset += written
                        if payload_offset == len(payload_view):
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
                    _, collected = streams[key.fd]
                    collected.extend(chunk)
                    total_output += len(chunk)
                    if total_output > maximum_output_bytes:
                        terminate_and_reap()
                        raise ValueError(
                            f"{label} output exceeds limit"
                        )
        finally:
            selector.close()
        remaining = max(0.0, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            terminate_and_reap()
            raise
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=bytes(streams[process.stdout.fileno()][1]),
            stderr=bytes(streams[process.stderr.fileno()][1]),
        )
    except BaseException:
        if process.poll() is None:
            terminate()
            try:
                process.wait(timeout=CHILD_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def repository_identity(
    git_path: Path,
    root: Path,
    label: str,
) -> tuple[int, int, int, int]:
    if path_uses_symlink(root):
        raise ValueError(f"{label} root path must not contain symlinks")
    top = run_git(git_path, root, "rev-parse", "--show-toplevel", text=True)
    if top.returncode != 0 or lexical_absolute(Path(top.stdout.strip())) != root:
        raise ValueError(f"{label} root must be a Git top-level checkout")
    git_dir = root / ".git"
    metadata = os.lstat(git_dir)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ValueError(f"{label} checkout must use a local .git directory")
    for args, expected, description in (
        (("rev-parse", "--absolute-git-dir"), git_dir, "Git directory"),
        (("rev-parse", "--git-common-dir"), git_dir, "common Git directory"),
        (
            ("rev-parse", "--git-path", "objects"),
            git_dir / "objects",
            "object store",
        ),
    ):
        completed = run_git(git_path, root, *args, text=True)
        observed = Path(completed.stdout.strip())
        if not observed.is_absolute():
            observed = root / observed
        if (
            completed.returncode != 0
            or lexical_absolute(observed).resolve()
            != expected.resolve()
        ):
            raise ValueError(f"{label} {description} must be local and unshared")
    objects = git_dir / "objects"
    objects_metadata = os.lstat(objects)
    if (
        not stat.S_ISDIR(objects_metadata.st_mode)
        or objects_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(objects_metadata.st_mode) & 0o022
    ):
        raise ValueError(f"{label} object store must be a local directory")
    alternates = objects / "info" / "alternates"
    if alternates.exists() or alternates.is_symlink():
        raise ValueError(f"{label} object alternates are forbidden")
    require_local_directory_tree(objects, f"{label} object store")
    require_expected_origin(git_path, root, label)
    return (
        metadata.st_dev,
        metadata.st_ino,
        objects_metadata.st_dev,
        objects_metadata.st_ino,
    )


def require_local_directory_tree(path: Path, label: str) -> None:
    flags = directory_flags()
    root_fd = os.open(path, flags)

    def visit(directory_fd: int, prefix: str) -> None:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError(f"{label} must not contain symlinks: {relative}")
                if (
                    metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                ):
                    raise ValueError(
                        f"{label} contains an untrusted writable entry: {relative}"
                    )
                if stat.S_ISDIR(metadata.st_mode):
                    child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                    try:
                        opened = os.fstat(child_fd)
                        if (
                            opened.st_dev,
                            opened.st_ino,
                        ) != (
                            metadata.st_dev,
                            metadata.st_ino,
                        ):
                            raise ValueError(
                                f"{label} entry changed while opening: {relative}"
                            )
                        visit(child_fd, relative)
                    finally:
                        os.close(child_fd)
                elif not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(
                        f"{label} may contain only directories and regular files"
                    )
                elif metadata.st_nlink != 1:
                    raise ValueError(
                        f"{label} must not contain hardlinked files: {relative}"
                    )

    try:
        visit(root_fd, "")
    finally:
        os.close(root_fd)


def normalize_origin(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("https://"):
        normalized = stripped[len("https://") :]
    elif stripped.startswith("ssh://git@"):
        normalized = stripped[len("ssh://git@") :]
    elif stripped.startswith("git@github.com:"):
        normalized = "github.com/" + stripped[len("git@github.com:") :]
    else:
        raise ValueError("origin must use an approved GitHub transport")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.rstrip("/")


def require_expected_origin(git_path: Path, root: Path, label: str) -> None:
    origin = run_git(
        git_path,
        root,
        "remote",
        "get-url",
        "origin",
        text=True,
    )
    if (
        origin.returncode != 0
        or normalize_origin(origin.stdout) != EXPECTED_REPOSITORY
    ):
        raise ValueError(f"{label} origin does not match the expected repository")
    remote_main = run_git(
        git_path,
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        "refs/remotes/origin/main^{commit}",
        text=True,
    )
    if (
        remote_main.returncode != 0
        or COMMIT_PATTERN.fullmatch(remote_main.stdout.strip()) is None
    ):
        raise ValueError(f"{label} origin/main cannot be verified locally")


def require_tracking_ref_consistency(
    git_path: Path,
    root: Path,
    commit: str,
    label: str,
    *,
    exact: bool,
) -> None:
    remote = run_git(
        git_path,
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        "refs/remotes/origin/main^{commit}",
        text=True,
    )
    remote_commit = remote.stdout.strip()
    if (
        remote.returncode != 0
        or COMMIT_PATTERN.fullmatch(remote_commit) is None
    ):
        raise ValueError(f"{label} origin/main cannot be resolved")
    if exact:
        if commit != remote_commit:
            raise ValueError(f"{label} HEAD must equal origin/main")
        return
    ancestry = run_git(
        git_path,
        root,
        "merge-base",
        "--is-ancestor",
        commit,
        remote_commit,
    )
    if ancestry.returncode != 0:
        raise ValueError(f"{label} commit must be reachable from origin/main")


def read_control_blob(
    git_path: Path,
    control_root: Path,
    control_commit: str,
    relative: str,
) -> tuple[bytes, dict[str, str]]:
    entry = run_git(
        git_path, control_root, "ls-tree", "-z", control_commit, "--", relative
    )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError(f"control file must exist once at control commit: {relative}")
    try:
        metadata, observed = records[0].split(b"\t", 1)
        mode, object_type, oid = metadata.decode("ascii").split(" ")
        observed_path = observed.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"control file metadata is malformed: {relative}") from error
    if (
        object_type != "blob"
        or mode != "100644"
        or observed_path != relative
        or OID_PATTERN.fullmatch(oid) is None
    ):
        raise ValueError(f"control file is not a regular Git blob: {relative}")
    size = run_git(
        git_path,
        control_root,
        "cat-file",
        "-s",
        oid,
        text=True,
    )
    try:
        blob_size = int(size.stdout.strip())
    except ValueError as error:
        raise ValueError(f"control blob size is invalid: {relative}") from error
    if (
        size.returncode != 0
        or blob_size <= 0
        or blob_size > MAX_CONTROL_FILE_BYTES
    ):
        raise ValueError(f"control blob is unreadable or too large: {relative}")
    blob = run_git(git_path, control_root, "cat-file", "blob", oid)
    if blob.returncode != 0 or len(blob.stdout) != blob_size:
        raise ValueError(f"control blob bytes are incomplete: {relative}")
    return blob.stdout, {
        "path": relative,
        "mode": mode,
        "blobOid": oid,
        "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
    }


def snapshot_control(
    git_path: Path,
    control_root: Path,
    control_commit: str,
) -> tuple[dict[str, bytes], dict[str, dict[str, str]]]:
    if COMMIT_PATTERN.fullmatch(control_commit) is None:
        raise ValueError("control commit must be a full lowercase SHA-1")
    head = run_git(git_path, control_root, "rev-parse", "HEAD", text=True)
    if head.returncode != 0 or head.stdout.strip() != control_commit:
        raise ValueError("control checkout HEAD does not match control commit")
    require_tracking_ref_consistency(
        git_path,
        control_root,
        control_commit,
        "control",
        exact=False,
    )
    sources: dict[str, bytes] = {}
    evidence: dict[str, dict[str, str]] = {}
    for name, relative in CONTROL_FILES.items():
        sources[name], evidence[name] = read_control_blob(
            git_path, control_root, control_commit, relative
        )
    return sources, evidence


def frame_parts(*parts: bytes) -> bytes:
    if any(not part or len(part) > MAX_CONTROL_FILE_BYTES for part in parts):
        raise ValueError("trusted staging frame part is empty or too large")
    return FRAME_MAGIC + b"".join(
        struct.pack(">Q", len(part)) + part for part in parts
    )


def frame_guard(guard_source: bytes, request: dict[str, Any]) -> bytes:
    return frame_parts(guard_source, canonical_json_bytes(request))


def frame_builder(
    guard_source: bytes,
    builder_source: bytes,
    request: dict[str, Any],
) -> bytes:
    return frame_parts(
        guard_source,
        builder_source,
        canonical_json_bytes(request),
    )


def validate_guard_result(
    result: dict[str, Any],
    returncode: int,
    expected_head: str,
) -> str:
    if set(result) != GUARD_RESULT_FIELDS:
        raise ValueError("guard result fields are incomplete or unexpected")
    if (
        returncode != 0
        or result["schemaVersion"] != 2
        or result["valid"] is not True
        or result["decision"] != "single-target"
        or result["authorized"] is not False
        or result["mutationAllowed"] is not False
        or result["targetCount"] != 1
        or result["headCommit"] != expected_head
        or result["blockingReasons"] != []
        or type(result["dryRun"]) is not bool
        or type(result["changedOnly"]) is not bool
        or type(result["authorizationEligible"]) is not bool
    ):
        raise ValueError("guard did not return one valid immutable staging target")
    if (
        type(result["skillPath"]) is not str
        or type(result["slug"]) is not str
        or result["skillPath"] != f"skills/{result['slug']}"
        or SLUG_PATTERN.fullmatch(result["slug"]) is None
    ):
        raise ValueError("guard target identity is invalid")
    snapshot = result["packageSnapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != GUARD_SNAPSHOT_FIELDS:
        raise ValueError("guard packageSnapshot fields are invalid")
    if (
        type(snapshot["treeOid"]) is not str
        or COMMIT_PATTERN.fullmatch(snapshot["treeOid"]) is None
        or type(snapshot["packageDigest"]) is not str
        or DIGEST_PATTERN.fullmatch(snapshot["packageDigest"]) is None
        or not isinstance(snapshot["files"], list)
        or not snapshot["files"]
        or len(snapshot["files"]) > MAX_ARTIFACT_FILES
    ):
        raise ValueError("guard packageSnapshot values are invalid")
    previous: bytes | None = None
    paths: set[str] = set()
    canonical_files: list[dict[str, str]] = []
    for item in snapshot["files"]:
        if not isinstance(item, dict) or set(item) != GUARD_FILE_FIELDS:
            raise ValueError("guard package file fields are invalid")
        if not all(type(item[key]) is str for key in GUARD_FILE_FIELDS):
            raise ValueError("guard package file values must be strings")
        path = item["path"]
        pure = PurePosixPath(path)
        try:
            encoded = path.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("guard package path must be valid UTF-8") from error
        if (
            not path
            or "\x00" in path
            or "\\" in path
            or pure.is_absolute()
            or pure.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure.parts)
            or item["mode"] not in {"100644", "100755"}
            or OID_PATTERN.fullmatch(item["blobOid"]) is None
            or DIGEST_PATTERN.fullmatch(item["sha256"]) is None
            or (previous is not None and encoded <= previous)
        ):
            raise ValueError("guard package contains an invalid file entry")
        previous = encoded
        paths.add(path)
        canonical_files.append(dict(item))
    if not REQUIRED_SKILL_FILES.issubset(paths):
        raise ValueError("guard package omits required Skill files")
    for path in paths:
        if any(parent.as_posix() in paths for parent in PurePosixPath(path).parents):
            raise ValueError("guard package contains a file/path prefix conflict")
    payload = {
        "files": canonical_files,
        "format": "safe-publish-package-v1",
        "skillPath": result["skillPath"],
        "treeOid": snapshot["treeOid"],
    }
    expected_package_digest = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    )
    if snapshot["packageDigest"] != expected_package_digest:
        raise ValueError("guard packageDigest is invalid")
    return "sha256:" + hashlib.sha256(canonical_json_bytes(result)).hexdigest()


def validate_manifest(manifest: Any, expected_head: str) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("child manifest fields are incomplete or unexpected")
    if (
        manifest["schemaVersion"] != 2
        or manifest["researchStatus"] != "research-only-not-wired"
        or manifest["format"] != "immutable-skill-staging-v2"
        or manifest["packageDirectory"] != "package"
        or manifest["worktreeRead"] is not False
        or manifest["authorizationGranted"] is not False
    ):
        raise ValueError("child manifest security declarations are invalid")
    for key in ("guardResultDigest", "artifactDigest"):
        if not isinstance(manifest[key], str) or DIGEST_PATTERN.fullmatch(manifest[key]) is None:
            raise ValueError(f"child manifest {key} is invalid")
    source = manifest["source"]
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise ValueError("child manifest source fields are invalid")
    if not all(type(source.get(key)) is str for key in SOURCE_FIELDS):
        raise ValueError("child manifest source values must be strings")
    skill_parts = PurePosixPath(source["skillPath"]).parts
    if (
        source["commit"] != expected_head
        or not isinstance(source["skillPath"], str)
        or len(skill_parts) != 2
        or skill_parts[0] != "skills"
        or SLUG_PATTERN.fullmatch(skill_parts[1]) is None
        or COMMIT_PATTERN.fullmatch(source["treeOid"]) is None
        or DIGEST_PATTERN.fullmatch(source["packageDigest"]) is None
    ):
        raise ValueError("child manifest source is invalid")
    files = manifest["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_ARTIFACT_FILES:
        raise ValueError("child manifest file list is invalid")
    previous: bytes | None = None
    for item in files:
        if not isinstance(item, dict) or set(item) != MANIFEST_FILE_FIELDS:
            raise ValueError("child manifest file fields are invalid")
        if not all(isinstance(item[key], str) for key in MANIFEST_FILE_FIELDS):
            raise ValueError("child manifest file values must be strings")
        path = item["path"]
        pure = PurePosixPath(path)
        try:
            encoded = path.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("child manifest path must be valid UTF-8") from error
        if (
            not path or "\x00" in path or "\\" in path or pure.is_absolute()
            or pure.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure.parts)
            or item["sourceMode"] not in {"100644", "100755"}
            or item["artifactMode"] != (
                "0555" if item["sourceMode"] == "100755" else "0444"
            )
            or OID_PATTERN.fullmatch(item["blobOid"]) is None
            or DIGEST_PATTERN.fullmatch(item["sha256"]) is None
            or (previous is not None and encoded <= previous)
        ):
            raise ValueError("child manifest contains an invalid file entry")
        previous = encoded
    file_paths = {item["path"] for item in files}
    if not REQUIRED_SKILL_FILES.issubset(file_paths):
        raise ValueError("child manifest omits required Skill files")
    for path in file_paths:
        if any(parent.as_posix() in file_paths for parent in PurePosixPath(path).parents):
            raise ValueError("child manifest contains a file/path prefix conflict")
    package_payload = {
        "files": [
            {
                "path": item["path"],
                "mode": item["sourceMode"],
                "blobOid": item["blobOid"],
                "sha256": item["sha256"],
            }
            for item in files
        ],
        "format": "safe-publish-package-v1",
        "skillPath": source["skillPath"],
        "treeOid": source["treeOid"],
    }
    package_digest = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(package_payload)).hexdigest()
    )
    if source["packageDigest"] != package_digest:
        raise ValueError("child manifest packageDigest is invalid")
    descriptor = {key: value for key, value in manifest.items() if key != "artifactDigest"}
    digest = "sha256:" + hashlib.sha256(canonical_json_bytes(descriptor)).hexdigest()
    if manifest["artifactDigest"] != digest:
        raise ValueError("child manifest artifactDigest is invalid")
    return manifest


def validate_child_result(
    result: dict[str, Any],
    returncode: int,
    expected_head: str,
    expected_guard_digest: str,
) -> dict[str, Any]:
    if set(result) != RESULT_FIELDS:
        raise ValueError("child result fields are incomplete or unexpected")
    if (
        type(result["valid"]) is not bool
        or type(result["created"]) is not bool
        or result["schemaVersion"] != 2
        or result["researchStatus"] != "research-only-not-wired"
        or result["authorizationGranted"] is not False
        or result["status"] not in {
            "committed", "failed", "failed-with-residue", "commit-uncertain"
        }
        or not isinstance(result["errors"], list)
        or len(result["errors"]) > 20
        or not all(isinstance(item, str) and len(item) <= 4096 for item in result["errors"])
    ):
        raise ValueError("child result types or declarations are invalid")
    expected_returncode = 0 if result["valid"] else 2
    if returncode != expected_returncode:
        raise ValueError("child exit code does not match result")
    if result["valid"]:
        if (
            result["status"] != "committed"
            or result["created"] is not True
            or result["errors"]
            or result["residueName"] is not None
            or not isinstance(result["outputName"], str)
            or OUTPUT_NAME_PATTERN.fullmatch(result["outputName"]) is None
        ):
            raise ValueError("successful child result is inconsistent")
        validate_manifest(result["manifest"], expected_head)
        if result["manifest"]["guardResultDigest"] != expected_guard_digest:
            raise ValueError("child manifest is not bound to frozen guard result")
        source = result["manifest"]["source"]
        expected_name = (
            f"{PurePosixPath(source['skillPath']).name}-{expected_head[:12]}-"
            f"{result['manifest']['artifactDigest'][7:19]}"
        )
        if result["outputName"] != expected_name:
            raise ValueError("child outputName is not bound to its manifest")
    else:
        if not result["errors"]:
            raise ValueError("failed child result must contain errors")
        if result["status"] == "failed":
            if (
                result["created"] is not False
                or result["manifest"] is not None
                or result["outputName"] is not None
                or result["residueName"] is not None
            ):
                raise ValueError("pre-commit child failure is inconsistent")
        elif result["status"] == "failed-with-residue":
            if (
                result["created"] is not False
                or result["manifest"] is not None
                or result["outputName"] is not None
                or not isinstance(result["residueName"], str)
                or re.fullmatch(
                    r"\.immutable-staging-[0-9a-f]{32}",
                    result["residueName"],
                ) is None
            ):
                raise ValueError("residual child failure is inconsistent")
        elif result["status"] == "commit-uncertain":
            if (
                result["created"] is not True
                or result["residueName"] is not None
                or not isinstance(result["outputName"], str)
                or OUTPUT_NAME_PATTERN.fullmatch(result["outputName"]) is None
            ):
                raise ValueError("commit-uncertain child result is inconsistent")
            validate_manifest(result["manifest"], expected_head)
            if result["manifest"]["guardResultDigest"] != expected_guard_digest:
                raise ValueError("child manifest is not bound to frozen guard result")
            source = result["manifest"]["source"]
            expected_name = (
                f"{PurePosixPath(source['skillPath']).name}-{expected_head[:12]}-"
                f"{result['manifest']['artifactDigest'][7:19]}"
            )
            if result["outputName"] != expected_name:
                raise ValueError("child outputName is not bound to its manifest")
        else:
            raise ValueError("failed child result has an impossible status")
    return result


def expected_artifact_from_guard(
    guard_result: dict[str, Any],
    guard_digest: str,
) -> tuple[str, dict[str, Any]]:
    snapshot = guard_result["packageSnapshot"]
    descriptor = {
        "schemaVersion": 2,
        "researchStatus": "research-only-not-wired",
        "format": "immutable-skill-staging-v2",
        "guardResultDigest": guard_digest,
        "source": {
            "commit": guard_result["headCommit"],
            "skillPath": guard_result["skillPath"],
            "treeOid": snapshot["treeOid"],
            "packageDigest": snapshot["packageDigest"],
        },
        "packageDirectory": "package",
        "files": [
            {
                "path": item["path"],
                "sourceMode": item["mode"],
                "artifactMode": (
                    "0555" if item["mode"] == "100755" else "0444"
                ),
                "blobOid": item["blobOid"],
                "sha256": item["sha256"],
            }
            for item in snapshot["files"]
        ],
        "worktreeRead": False,
        "authorizationGranted": False,
    }
    manifest = {
        **descriptor,
        "artifactDigest": (
            "sha256:" + hashlib.sha256(canonical_json_bytes(descriptor)).hexdigest()
        ),
    }
    validate_manifest(manifest, guard_result["headCommit"])
    output_name = (
        f"{guard_result['slug']}-{guard_result['headCommit'][:12]}-"
        f"{manifest['artifactDigest'][7:19]}"
    )
    return output_name, manifest


def directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if type(nofollow) is not int or type(directory) is not int:
        raise ValueError("platform lacks O_NOFOLLOW or O_DIRECTORY")
    return os.O_RDONLY | nofollow | directory


def open_absolute_directory(path: Path) -> int:
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise ValueError("artifact parent must be an absolute canonical path")
    descriptor = os.open(os.path.sep, directory_flags())
    try:
        for component in path.parts[1:]:
            child = os.open(component, directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def directory_path_identity(path: Path) -> tuple[int, int]:
    descriptor = open_absolute_directory(path)
    try:
        metadata = os.fstat(descriptor)
        return metadata.st_dev, metadata.st_ino
    finally:
        os.close(descriptor)


def probe_artifact_state(
    output_parent: Path,
    expected_parent_identity: tuple[int, int],
    output_name: str | None,
) -> tuple[str, bool | None]:
    if (
        not isinstance(output_name, str)
        or OUTPUT_NAME_PATTERN.fullmatch(output_name) is None
    ):
        return "unknown", None
    try:
        parent_fd = open_absolute_directory(output_parent)
    except (OSError, ValueError):
        return "unknown", None
    try:
        parent_metadata = os.fstat(parent_fd)
        if (
            parent_metadata.st_dev,
            parent_metadata.st_ino,
        ) != expected_parent_identity:
            return "unknown", None
        try:
            artifact_fd = os.open(
                output_name,
                directory_flags(),
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return "absent", False
        except OSError:
            return "unknown", None
        try:
            metadata = os.fstat(artifact_fd)
            if stat.S_ISDIR(metadata.st_mode):
                return "present-unverified", True
            return "unknown", None
        finally:
            os.close(artifact_fd)
    finally:
        os.close(parent_fd)


def read_artifact_file(
    directory_fd: int,
    name: str,
    *,
    expected_mode: int,
    maximum: int,
) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW"),
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_uid != os.geteuid()
        ):
            raise ValueError(f"artifact file metadata is invalid: {name}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ValueError(f"artifact file exceeds size limit: {name}")
        after = os.fstat(descriptor)
        identity = (
            before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
            before.st_size, before.st_mtime_ns, before.st_ctime_ns,
        )
        repeated = (
            after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        )
        if identity != repeated:
            raise ValueError(f"artifact file changed while being read: {name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def require_manifest_tree_binding(
    manifest: dict[str, Any],
    git_path: Path,
    candidate_root: Path,
) -> None:
    source = manifest["source"]
    direct = run_git(
        git_path,
        candidate_root,
        "ls-tree",
        "-z",
        source["commit"],
        "--",
        source["skillPath"],
    )
    records = [record for record in direct.stdout.split(b"\0") if record]
    if direct.returncode != 0 or len(records) != 1:
        raise ValueError("manifest Skill tree cannot be resolved from candidate commit")
    try:
        metadata, observed = records[0].split(b"\t", 1)
        mode, object_type, tree_oid = metadata.decode("ascii").split(" ")
        observed_path = observed.decode("utf-8", errors="strict")
    except (UnicodeError, ValueError) as error:
        raise ValueError("manifest Skill tree metadata is malformed") from error
    if (
        mode != "040000"
        or object_type != "tree"
        or tree_oid != source["treeOid"]
        or observed_path != source["skillPath"]
    ):
        raise ValueError("manifest treeOid is not bound to candidate commit and path")

    listing = run_git(
        git_path,
        candidate_root,
        "ls-tree",
        "-r",
        "-z",
        tree_oid,
    )
    if listing.returncode != 0:
        raise ValueError("manifest Skill tree cannot be enumerated")
    observed_files: list[dict[str, str]] = []
    for record in (item for item in listing.stdout.split(b"\0") if item):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            file_mode, file_type, blob_oid = metadata.decode("ascii").split(" ")
            file_path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeError, ValueError) as error:
            raise ValueError("manifest Skill tree contains malformed metadata") from error
        if (
            file_type != "blob"
            or file_mode not in {"100644", "100755"}
            or OID_PATTERN.fullmatch(blob_oid) is None
        ):
            raise ValueError("manifest Skill tree contains a forbidden entry")
        observed_files.append(
            {
                "path": file_path,
                "sourceMode": file_mode,
                "blobOid": blob_oid,
            }
        )
    expected_files = [
        {
            "path": item["path"],
            "sourceMode": item["sourceMode"],
            "blobOid": item["blobOid"],
        }
        for item in manifest["files"]
    ]
    if observed_files != expected_files:
        raise ValueError("manifest files are not exactly bound to candidate Skill tree")


def require_guard_tree_binding(
    guard_result: dict[str, Any],
    git_path: Path,
    candidate_root: Path,
) -> None:
    snapshot = guard_result["packageSnapshot"]
    require_manifest_tree_binding(
        {
            "source": {
                "commit": guard_result["headCommit"],
                "skillPath": guard_result["skillPath"],
                "treeOid": snapshot["treeOid"],
            },
            "files": [
                {
                    "path": item["path"],
                    "sourceMode": item["mode"],
                    "blobOid": item["blobOid"],
                }
                for item in snapshot["files"]
            ],
        },
        git_path,
        candidate_root,
    )


def verify_artifact(
    output_parent: Path,
    result: dict[str, Any],
    expected_head: str,
    git_path: Path,
    candidate_root: Path,
) -> dict[str, Any]:
    """Independently re-open and verify the committed artifact from its parent FD."""
    manifest = validate_manifest(result["manifest"], expected_head)
    require_manifest_tree_binding(
        manifest,
        git_path,
        candidate_root,
    )
    parent_fd = open_absolute_directory(output_parent)
    artifact_fd: int | None = None
    package_fd: int | None = None
    try:
        parent_metadata = os.fstat(parent_fd)
        if (
            parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ValueError("artifact parent metadata is invalid")
        artifact_fd = os.open(
            result["outputName"], directory_flags(), dir_fd=parent_fd
        )
        artifact_metadata = os.fstat(artifact_fd)
        if (
            artifact_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(artifact_metadata.st_mode) != 0o555
        ):
            raise ValueError("artifact root metadata is invalid")
        with os.scandir(artifact_fd) as entries:
            root_names = sorted(entry.name for entry in entries)
        if root_names != ["manifest.json", "package"]:
            raise ValueError("artifact root entries do not match manifest")
        manifest_bytes = read_artifact_file(
            artifact_fd,
            "manifest.json",
            expected_mode=0o444,
            maximum=MAX_ARTIFACT_FILE_BYTES,
        )
        disk_manifest = parse_strict_json(manifest_bytes, "artifact manifest")
        if disk_manifest != manifest:
            raise ValueError("artifact manifest does not match child result")
        if manifest_bytes != canonical_json_bytes(manifest) + b"\n":
            raise ValueError("artifact manifest bytes are not canonical")

        package_fd = os.open("package", directory_flags(), dir_fd=artifact_fd)
        package_metadata = os.fstat(package_fd)
        if (
            package_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(package_metadata.st_mode) != 0o555
        ):
            raise ValueError("artifact package directory mode is invalid")
        expected = {item["path"]: item for item in manifest["files"]}
        observed: set[str] = set()
        total = 0

        def visit(directory_fd: int, prefix: str) -> None:
            nonlocal total
            directory_metadata = os.fstat(directory_fd)
            if (
                directory_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(directory_metadata.st_mode) != 0o555
            ):
                raise ValueError("artifact subdirectory mode is invalid")
            with os.scandir(directory_fd) as entries:
                ordered = sorted(entry.name for entry in entries)
            for entry_name in ordered:
                relative = f"{prefix}/{entry_name}" if prefix else entry_name
                metadata = os.stat(
                    entry_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if stat.S_ISDIR(metadata.st_mode):
                    child_fd = os.open(
                        entry_name,
                        directory_flags(),
                        dir_fd=directory_fd,
                    )
                    try:
                        visit(child_fd, relative)
                    finally:
                        os.close(child_fd)
                    continue
                item = expected.get(relative)
                if item is None:
                    raise ValueError(f"artifact contains an unexpected file: {relative}")
                content = read_artifact_file(
                    directory_fd,
                    entry_name,
                    expected_mode=int(item["artifactMode"], 8),
                    maximum=MAX_ARTIFACT_FILE_BYTES,
                )
                total += len(content)
                if total > MAX_ARTIFACT_BYTES:
                    raise ValueError("artifact exceeds total size limit")
                digest = "sha256:" + hashlib.sha256(content).hexdigest()
                if digest != item["sha256"]:
                    raise ValueError(f"artifact file digest is invalid: {relative}")
                blob_size = run_git(
                    git_path,
                    candidate_root,
                    "cat-file",
                    "-s",
                    item["blobOid"],
                    text=True,
                )
                try:
                    expected_blob_size = int(blob_size.stdout.strip())
                except ValueError as error:
                    raise ValueError(
                        f"candidate Git blob size is invalid: {relative}"
                    ) from error
                if (
                    blob_size.returncode != 0
                    or expected_blob_size != len(content)
                    or expected_blob_size > MAX_ARTIFACT_FILE_BYTES
                ):
                    raise ValueError(
                        f"artifact file size does not match candidate Git blob: "
                        f"{relative}"
                    )
                blob = run_git(
                    git_path,
                    candidate_root,
                    "cat-file",
                    "blob",
                    item["blobOid"],
                )
                if blob.returncode != 0 or blob.stdout != content:
                    raise ValueError(
                        f"artifact file does not match candidate Git blob: {relative}"
                    )
                observed.add(relative)

        visit(package_fd, "")
        if observed != set(expected):
            raise ValueError("artifact file set does not match manifest")
    finally:
        if package_fd is not None:
            os.close(package_fd)
        if artifact_fd is not None:
            os.close(artifact_fd)
        os.close(parent_fd)
    return {
        "manifestMatched": True,
        "artifactDigestVerified": True,
        "fileCount": len(manifest["files"]),
        "contentBytes": total,
    }


def candidate_head(git_path: Path, candidate_root: Path) -> str:
    completed = run_git(
        git_path,
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


def parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("boolean inputs must be true or false")


def run_staging(
    candidate_root: Path,
    control_root: Path,
    control_commit: str,
    output_parent: Path,
    *,
    event_name: str,
    dry_run: bool,
    changed_only: bool,
    ref: str = "",
    base: str = "",
    head: str = "HEAD",
    skill_path: str = "",
    event_before: str = "",
    event_sha: str = "",
    event_ref: str = "",
) -> tuple[int, dict[str, Any]]:
    candidate = lexical_absolute(candidate_root)
    control = lexical_absolute(control_root)
    output = lexical_absolute(output_parent)
    child_result: dict[str, Any] | None = None
    try:
        python_path, git_path = resolve_executables()
        candidate_identity = repository_identity(
            git_path, candidate, "candidate"
        )
        control_identity = repository_identity(git_path, control, "control")
        if (
            candidate == control
            or candidate_identity[:2] == control_identity[:2]
            or candidate_identity[2:] == control_identity[2:]
        ):
            raise ValueError("control and candidate checkouts must be independent")
        resolved_output = output.resolve(strict=True)
        try:
            resolved_output.relative_to(control.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ValueError("output parent must be outside the control checkout")
        output_identity = directory_path_identity(output)
        expected_head = candidate_head(git_path, candidate)
        require_tracking_ref_consistency(
            git_path,
            candidate,
            expected_head,
            "candidate",
            exact=True,
        )
        sources, evidence = snapshot_control(
            git_path, control, control_commit
        )
        guard_request = {
            "guardPath": str(control / CONTROL_FILES["guard"]),
            "candidateRoot": str(candidate),
            "eventName": event_name,
            "dryRun": dry_run,
            "changedOnly": changed_only,
            "ref": ref,
            "base": base,
            "head": head,
            "skillPath": skill_path,
            "eventBefore": event_before,
            "eventSha": event_sha,
            "eventRef": event_ref,
        }
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return 2, failure(
            f"trusted staging prerequisites failed: {error}",
            artifact_state="absent",
            created=False,
        )

    try:
        guard_completed = run_bounded_child(
            [str(python_path), "-I", "-c", GUARD_BOOTSTRAP],
            cwd=control,
            environment=child_environment(git_path),
            payload=frame_guard(sources["guard"], guard_request),
        )
    except subprocess.TimeoutExpired:
        return 2, failure(
            "trusted guard child timed out",
            artifact_state="absent",
            created=False,
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return 2, failure(
            f"trusted guard child could not be launched: {error}",
            artifact_state="absent",
            created=False,
        )

    if (
        len(guard_completed.stdout) > MAX_CHILD_OUTPUT_BYTES
        or len(guard_completed.stderr) > MAX_CHILD_OUTPUT_BYTES
    ):
        return 2, failure(
            "trusted guard child output exceeds limit",
            guard_completed.returncode,
            artifact_state="absent",
            created=False,
        )
    if guard_completed.stderr:
        return 2, failure(
            "trusted guard child wrote unexpected stderr",
            guard_completed.returncode,
            artifact_state="absent",
            created=False,
        )
    try:
        guard_result = parse_strict_json(
            guard_completed.stdout,
            "guard result",
        )
        guard_digest = validate_guard_result(
            guard_result,
            guard_completed.returncode,
            expected_head,
        )
        require_guard_tree_binding(
            guard_result,
            git_path,
            candidate,
        )
        expected_output_name, expected_manifest = expected_artifact_from_guard(
            guard_result,
            guard_digest,
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return 2, failure(
            str(error),
            guard_completed.returncode,
            artifact_state="absent",
            created=False,
        )

    builder_request = {
        "guardPath": str(control / CONTROL_FILES["guard"]),
        "builderPath": str(control / CONTROL_FILES["builder"]),
        "candidateRoot": str(candidate),
        "outputParent": str(output),
        "guardResult": guard_result,
    }

    def fail_after_builder(
        message: str,
        child_exit_code: int | None = None,
    ) -> tuple[int, dict[str, Any]]:
        artifact_state, created = probe_artifact_state(
            output,
            output_identity,
            expected_output_name,
        )
        if artifact_state == "present-unverified":
            try:
                verify_artifact(
                    output,
                    {
                        "outputName": expected_output_name,
                        "manifest": expected_manifest,
                    },
                    expected_head,
                    git_path,
                    candidate,
                )
            except (OSError, TypeError, UnicodeError, ValueError):
                pass
            else:
                artifact_state = "present-verified-snapshot"
        return 2, failure(
            message,
            child_exit_code,
            artifact_state=artifact_state,
            created=created,
            output_name=expected_output_name,
        )

    try:
        completed = run_bounded_child(
            [str(python_path), "-I", "-c", BUILDER_BOOTSTRAP],
            cwd=control,
            environment=child_environment(git_path),
            payload=frame_builder(
                sources["guard"],
                sources["builder"],
                builder_request,
            ),
        )
    except subprocess.TimeoutExpired:
        return fail_after_builder("trusted builder child timed out")
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return fail_after_builder(
            f"trusted builder child could not be launched: {error}"
        )
    if (
        len(completed.stdout) > MAX_CHILD_OUTPUT_BYTES
        or len(completed.stderr) > MAX_CHILD_OUTPUT_BYTES
    ):
        return fail_after_builder(
            "trusted builder child output exceeds limit",
            completed.returncode,
        )
    if completed.stderr:
        return fail_after_builder(
            "trusted builder child wrote unexpected stderr",
            completed.returncode,
        )
    try:
        child_result = parse_strict_json(completed.stdout, "child result")
        validate_child_result(
            child_result,
            completed.returncode,
            expected_head,
            guard_digest,
        )
        if child_result["valid"] or child_result["status"] == "commit-uncertain":
            repeated_head = candidate_head(git_path, candidate)
            if repeated_head != expected_head:
                raise ValueError("candidate HEAD changed during trusted staging")
            artifact = verify_artifact(
                output, child_result, expected_head, git_path, candidate
            )
            if directory_path_identity(output) != output_identity:
                raise ValueError("output parent path changed during trusted staging")
            if repository_identity(
                git_path,
                candidate,
                "candidate",
            ) != candidate_identity:
                raise ValueError("candidate repository layout changed during staging")
            require_tracking_ref_consistency(
                git_path,
                candidate,
                expected_head,
                "candidate",
                exact=True,
            )
            if repository_identity(
                git_path,
                control,
                "control",
            ) != control_identity:
                raise ValueError("control repository layout changed during staging")
            repeated_sources, repeated_evidence = snapshot_control(
                git_path,
                control,
                control_commit,
            )
            if (
                repeated_sources != sources
                or repeated_evidence != evidence
            ):
                raise ValueError("trusted control sources changed during staging")
            final_artifact = verify_artifact(
                output, child_result, expected_head, git_path, candidate
            )
            if final_artifact != artifact:
                raise ValueError(
                    "artifact verification evidence changed before final return"
                )
        else:
            artifact = None
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        return fail_after_builder(str(error), completed.returncode)

    child_result["artifactState"] = (
        "present-verified-snapshot"
        if child_result["valid"] or child_result["status"] == "commit-uncertain"
        else "temporary-residue"
        if child_result["status"] == "failed-with-residue"
        else "absent"
    )
    child_result["launcherObservations"] = {
        "isolatedModeObserved": True,
        "childEnvironmentAllowlisted": True,
        "controlCommit": control_commit,
        "controlFiles": evidence,
        "sameControlCommit": True,
        "guardAndBuilderSeparated": True,
        "guardResultDigestVerified": True,
        "independentCheckouts": True,
        "inMemoryFraming": "trusted-staging-v1",
        "timeoutSeconds": CHILD_TIMEOUT_SECONDS,
        "artifactVerification": artifact,
        "artifactVerificationSemantics": "final-snapshot-consumer-must-revalidate",
        "formalWorkflowWired": False,
    }
    return completed.returncode, child_result


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated:
        print(json.dumps(failure("launcher must run with Python isolated mode (-I)")))
        return 2
    parser = StructuredArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--output-parent", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--changed-only", required=True)
    parser.add_argument("--ref", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--skill-path", default="")
    parser.add_argument("--event-before", default="")
    parser.add_argument("--event-sha", default="")
    parser.add_argument("--event-ref", default="")
    try:
        args = parser.parse_args(argv)
        returncode, result = run_staging(
            args.candidate_root,
            args.control_root,
            args.control_commit,
            args.output_parent,
            event_name=args.event_name,
            dry_run=parse_bool(args.dry_run),
            changed_only=parse_bool(args.changed_only),
            ref=args.ref,
            base=args.base,
            head=args.head,
            skill_path=args.skill_path,
            event_before=args.event_before,
            event_sha=args.event_sha,
            event_ref=args.event_ref,
        )
    except (TypeError, ValueError) as error:
        returncode, result = 2, failure(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

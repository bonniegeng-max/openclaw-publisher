#!/usr/bin/env python3
"""从完整 guard JSON 构造只读暂存；纯离线研究工具，不授予发布权限。"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import secrets
import stat
from pathlib import Path, PurePosixPath
from typing import Any


RESEARCH = Path(__file__).resolve().parent
GUARD_PATH = RESEARCH / "safe_publish_target_guard.py"
SPEC = importlib.util.spec_from_file_location("safe_publish_target_guard", GUARD_PATH)
GUARD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GUARD)

SCHEMA_VERSION = 2
RESEARCH_STATUS = "research-only-not-wired"
STAGING_FORMAT = "immutable-skill-staging-v2"
MANIFEST_NAME = "manifest.json"
PACKAGE_DIRECTORY = "package"
MAX_GUARD_RESULT_BYTES = 2 * 1024 * 1024
RENAME_NOREPLACE = 1
RENAME_EXCL = 0x00000004
GUARD_FIELDS = {
    "schemaVersion", "valid", "decision", "eventName", "ref", "dryRun",
    "changedOnly", "authorizationEligible", "authorized", "mutationAllowed",
    "targetCount", "skillPath", "slug", "packageSnapshot", "baseCommit",
    "headCommit", "eventBefore", "eventSha", "eventRef", "blockingReasons",
}
SNAPSHOT_FIELDS = {"treeOid", "files", "packageDigest"}
FILE_FIELDS = {"path", "mode", "blobOid", "sha256"}


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid arguments: {message}")


class CommitUncertainError(Exception):
    """The rename happened, but durability of its directory entry is unknown."""


def canonical_json_bytes(value: Any, *, newline: bool = False) -> bytes:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return rendered + (b"\n" if newline else b"")


def sha256_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def is_sha256(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"guard result contains duplicate key: {key}")
        result[key] = value
    return result


def _directory_flags() -> int:
    nofollow, directory = GUARD.require_nofollow_capabilities()
    return os.O_RDONLY | directory | nofollow


def open_absolute_directory(path: Path) -> tuple[int, list[tuple[int, int]]]:
    """Open every absolute-path component with openat and O_NOFOLLOW."""
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise ValueError("path must be absolute and lexically canonical")
    descriptor = os.open(os.path.sep, _directory_flags())
    identities = [(os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)]
    try:
        for component in path.parts[1:]:
            child = os.open(
                component, _directory_flags(), dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            identities.append((metadata.st_dev, metadata.st_ino))
        return descriptor, identities
    except BaseException:
        os.close(descriptor)
        raise


def open_absolute_regular(path: Path, maximum: int) -> bytes:
    """Read an absolute regular file through no-follow directory/file FDs."""
    parent_fd, _ = open_absolute_directory(path.parent)
    nofollow, _ = GUARD.require_nofollow_capabilities()
    try:
        descriptor = os.open(path.name, os.O_RDONLY | nofollow, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("guard result must be a private regular file")
            if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) & 0o077:
                raise ValueError(
                    "guard result must be owned by the current user and private"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    raise ValueError("guard result exceeds size limit")
            after = os.fstat(descriptor)
            if GUARD._stable_metadata(before) != GUARD._stable_metadata(after):
                raise ValueError("guard result changed while being read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def load_guard_result(path: Path) -> dict[str, Any]:
    try:
        raw = open_absolute_regular(path, MAX_GUARD_RESULT_BYTES)
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"guard result cannot be read as strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("guard result must be a JSON object")
    return value


def validate_guard_result(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete schema and all cross-field invariants."""
    if set(value) != GUARD_FIELDS:
        raise ValueError("guard result fields are incomplete or unexpected")
    scalar_expectations = {
        "schemaVersion": 2,
        "valid": True,
        "decision": "single-target",
        "authorized": False,
        "mutationAllowed": False,
        "targetCount": 1,
    }
    for key, expected in scalar_expectations.items():
        if type(value[key]) is not type(expected) or value[key] != expected:
            raise ValueError(f"guard result {key} is not the required value")
    for key in ("eventName", "ref", "skillPath", "slug", "headCommit"):
        if not isinstance(value[key], str):
            raise ValueError(f"guard result {key} must be a string")
    for key in ("dryRun", "changedOnly", "authorizationEligible"):
        if type(value[key]) is not bool:
            raise ValueError(f"guard result {key} must be a boolean")
    if value["eventName"] not in GUARD.SUPPORTED_EVENTS:
        raise ValueError("guard result eventName is unsupported")
    if value["eventName"] in {"workflow_dispatch", "pull_request"} and not value["dryRun"]:
        raise ValueError("guard result event cannot request a non-dry-run build")
    for key in ("baseCommit", "eventBefore", "eventSha", "eventRef"):
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError(f"guard result {key} must be a string or null")
    for key in ("baseCommit", "eventBefore", "eventSha"):
        if (
            value[key] is not None
            and GUARD.COMMIT_PATTERN.fullmatch(value[key]) is None
        ):
            raise ValueError(f"guard result {key} must be a full lowercase commit or null")
    if value["blockingReasons"] != []:
        raise ValueError("guard result must not contain blocking reasons")
    relative = GUARD.validate_explicit_path(value["skillPath"])
    if value["slug"] != PurePosixPath(relative).name:
        raise ValueError("guard result slug does not match skillPath")
    commit = value["headCommit"]
    if GUARD.COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("guard result headCommit must be a full lowercase commit")
    snapshot = value["packageSnapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise ValueError("guard result packageSnapshot fields are invalid")
    if (
        type(snapshot.get("treeOid")) is not str
        or GUARD.COMMIT_PATTERN.fullmatch(snapshot["treeOid"]) is None
        or not isinstance(snapshot.get("files"), list)
        or type(snapshot.get("packageDigest")) is not str
    ):
        raise ValueError("guard result packageSnapshot types are invalid")
    if len(snapshot["files"]) > GUARD.MAX_PACKAGE_FILES:
        raise ValueError("guard result packageSnapshot exceeds file limit")
    if not snapshot["files"]:
        raise ValueError("guard result packageSnapshot must contain files")
    previous: bytes | None = None
    file_paths: set[str] = set()
    for item in snapshot["files"]:
        if not isinstance(item, dict) or set(item) != FILE_FIELDS:
            raise ValueError("guard result package file fields are invalid")
        if not all(isinstance(item[key], str) for key in FILE_FIELDS):
            raise ValueError("guard result package file values must be strings")
        path = item["path"]
        try:
            encoded = path.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(
                "guard result package path must be valid UTF-8"
            ) from error
        pure_path = PurePosixPath(path)
        if (
            not path
            or "\x00" in path
            or "\\" in path
            or pure_path.is_absolute()
            or pure_path.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure_path.parts)
            or item["mode"] not in {"100644", "100755"}
            or GUARD.COMMIT_PATTERN.fullmatch(item["blobOid"]) is None
            or not is_sha256(item["sha256"])
        ):
            raise ValueError(f"guard result package file is invalid: {path!r}")
        if previous is not None and encoded <= previous:
            raise ValueError("guard result package files must be unique and byte-sorted")
        previous = encoded
        file_paths.add(path)
    if not set(GUARD.REQUIRED_FILES).issubset(file_paths):
        raise ValueError("guard result packageSnapshot is missing required files")
    for path in file_paths:
        for parent in PurePosixPath(path).parents:
            if parent.as_posix() in file_paths:
                raise ValueError(
                    "guard result packageSnapshot contains a file/path prefix conflict"
                )
    expected_digest = GUARD.canonical_package_digest(
        relative, snapshot["treeOid"], snapshot["files"]
    )
    if snapshot["packageDigest"] != expected_digest:
        raise ValueError("guard result packageDigest is not canonical")
    eligible = (
        value["eventName"] == "push"
        and value["ref"] == GUARD.PRODUCTION_REF
        and value["dryRun"] is False
        and value["changedOnly"] is True
        and value["baseCommit"] == value["eventBefore"]
        and value["headCommit"] == value["eventSha"]
        and value["ref"] == value["eventRef"]
    )
    if value["authorizationEligible"] is not eligible:
        raise ValueError("guard result authorizationEligible is inconsistent")
    if value["eventName"] == "push" and value["dryRun"] is False:
        if (
            value["ref"] != GUARD.PRODUCTION_REF
            or value["changedOnly"] is not True
            or value["baseCommit"] is None
            or value["eventBefore"] is None
            or value["eventSha"] is None
            or value["eventRef"] != GUARD.PRODUCTION_REF
            or value["baseCommit"] != value["eventBefore"]
            or value["headCommit"] != value["eventSha"]
        ):
            raise ValueError(
                "non-dry-run push guard result lacks complete trusted event boundaries"
            )
    return value


def require_safe_output_parent(repo_root: Path, supplied: Path) -> tuple[Path, int]:
    """Return a verified parent FD; callers must perform all mutations through it."""
    parent_fd: int | None = None
    try:
        parent_fd, parent_chain = open_absolute_directory(supplied)
        repo_fd, _ = open_absolute_directory(repo_root)
    except OSError as error:
        if parent_fd is not None:
            os.close(parent_fd)
        raise ValueError("output parent cannot be opened safely") from error
    try:
        parent = os.fstat(parent_fd)
        repository = os.fstat(repo_fd)
        repository_identity = (repository.st_dev, repository.st_ino)
        if repository_identity in parent_chain:
            raise ValueError("output parent must be outside the repository")
        if parent.st_uid != os.geteuid():
            raise ValueError("output parent must be owned by the current user")
        if stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError("output parent must be private (mode 0700)")
        return supplied, parent_fd
    except BaseException:
        os.close(parent_fd)
        raise
    finally:
        os.close(repo_fd)


def require_same_directory_path(path: Path, expected_fd: int) -> None:
    """Require a pathname to still resolve to the already-open directory."""
    observed_fd: int | None = None
    try:
        observed_fd, _ = open_absolute_directory(path)
        expected = os.fstat(expected_fd)
        observed = os.fstat(observed_fd)
        if (expected.st_dev, expected.st_ino) != (observed.st_dev, observed.st_ino):
            raise ValueError("output parent path changed during staging")
    except OSError as error:
        raise ValueError("output parent path cannot be revalidated") from error
    finally:
        if observed_fd is not None:
            os.close(observed_fd)


def random_mkdirat(parent_fd: int) -> tuple[str, int]:
    for _ in range(128):
        name = ".immutable-staging-" + secrets.token_hex(16)
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        try:
            descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
        except BaseException:
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            os.close(descriptor)
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise ValueError("temporary directory metadata is unsafe")
        return name, descriptor
    raise ValueError("cannot allocate a unique temporary directory")


def open_or_create_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(part, _directory_flags(), dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def write_file_at(root_fd: int, relative: str, content: bytes, mode: int) -> None:
    path = PurePosixPath(relative)
    parent_fd = open_or_create_directory(root_fd, path.parts[:-1])
    nofollow, _ = GUARD.require_nofollow_capabilities()
    try:
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def read_pinned_blob(repo_root: Path, entry: dict[str, str]) -> bytes:
    completed = GUARD.run_git(
        repo_root, "cat-file", "blob", entry["blobOid"], text=False
    )
    if completed.returncode != 0:
        raise ValueError(f"pinned Git blob cannot be read: {entry['path']}")
    content = completed.stdout
    if len(content) > GUARD.MAX_FILE_BYTES:
        raise ValueError(f"pinned Git blob exceeds file limit: {entry['path']}")
    if "sha256:" + hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ValueError(f"pinned Git blob digest changed: {entry['path']}")
    return content


def evidence_from_fd(root_fd: int) -> dict[str, dict[str, str]]:
    observed: dict[str, dict[str, str]] = {}
    nofollow, _ = GUARD.require_nofollow_capabilities()

    def visit(directory_fd: int, prefix: str) -> None:
        before = os.fstat(directory_fd)
        entries = sorted(os.scandir(directory_fd), key=lambda item: item.name.encode())
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(
                    entry.name, _directory_flags(), dir_fd=directory_fd
                )
                try:
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(f"staged entry is not a private regular file: {relative}")
            file_fd = os.open(
                entry.name, os.O_RDONLY | nofollow, dir_fd=directory_fd
            )
            digest = hashlib.sha256()
            try:
                opened = os.fstat(file_fd)
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                after = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            if (
                GUARD._stable_metadata(metadata) != GUARD._stable_metadata(opened)
                or GUARD._stable_metadata(opened) != GUARD._stable_metadata(after)
            ):
                raise ValueError(f"staged file changed while reviewing: {relative}")
            observed[relative] = {
                "mode": f"{stat.S_IMODE(opened.st_mode):04o}",
                "sha256": "sha256:" + digest.hexdigest(),
            }
        if GUARD._stable_metadata(before) != GUARD._stable_metadata(os.fstat(directory_fd)):
            raise ValueError("staged directory changed while reviewing")

    visit(root_fd, "")
    return observed


def artifact_files(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "path": item["path"],
            "sourceMode": item["mode"],
            "artifactMode": "0555" if item["mode"] == "100755" else "0444",
            "blobOid": item["blobOid"],
            "sha256": item["sha256"],
        }
        for item in snapshot["files"]
    ]


def artifact_descriptor(
    guard_digest: str,
    commit: str,
    relative: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "researchStatus": RESEARCH_STATUS,
        "format": STAGING_FORMAT,
        "guardResultDigest": guard_digest,
        "source": {
            "commit": commit,
            "skillPath": relative,
            "treeOid": snapshot["treeOid"],
            "packageDigest": snapshot["packageDigest"],
        },
        "packageDirectory": PACKAGE_DIRECTORY,
        "files": artifact_files(snapshot),
        "worktreeRead": False,
        "authorizationGranted": False,
    }


def manifest_for(
    guard_result: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    guard_digest = sha256_json(guard_result)
    descriptor = artifact_descriptor(
        guard_digest,
        guard_result["headCommit"],
        guard_result["skillPath"],
        snapshot,
    )
    return {**descriptor, "artifactDigest": sha256_json(descriptor)}


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "researchStatus",
        "format",
        "guardResultDigest",
        "source",
        "packageDirectory",
        "files",
        "worktreeRead",
        "authorizationGranted",
        "artifactDigest",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("staging manifest fields are incomplete or unexpected")
    if (
        type(manifest["schemaVersion"]) is not int
        or manifest["schemaVersion"] != SCHEMA_VERSION
        or manifest["researchStatus"] != RESEARCH_STATUS
        or manifest["format"] != STAGING_FORMAT
        or manifest["packageDirectory"] != PACKAGE_DIRECTORY
        or manifest["worktreeRead"] is not False
        or manifest["authorizationGranted"] is not False
        or not is_sha256(manifest["guardResultDigest"])
        or not is_sha256(manifest["artifactDigest"])
    ):
        raise ValueError("staging manifest security declarations are invalid")
    payload = {
        key: value
        for key, value in manifest.items()
        if key != "artifactDigest"
    }
    if sha256_json(payload) != manifest["artifactDigest"]:
        raise ValueError("staging manifest artifactDigest is invalid")
    return manifest


def review_package_fd(package_fd: int, files: list[dict[str, str]]) -> None:
    expected = {
        item["path"]: {
            "mode": "0555" if item["mode"] == "100755" else "0444",
            "sha256": item["sha256"],
        }
        for item in files
    }
    if evidence_from_fd(package_fd) != expected:
        raise ValueError("staged package does not exactly match its pinned manifest")


def read_file_at(root_fd: int, name: str) -> bytes:
    nofollow, _ = GUARD.require_nofollow_capabilities()
    descriptor = os.open(name, os.O_RDONLY | nofollow, dir_fd=root_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"staged file is not regular: {name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if GUARD._stable_metadata(before) != GUARD._stable_metadata(os.fstat(descriptor)):
            raise ValueError(f"staged file changed while reviewing: {name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def seal_tree_fd(root_fd: int) -> None:
    """Durably seal all directories as 0555, leaves before parents."""
    entries = sorted(os.scandir(root_fd), key=lambda item: item.name.encode())
    for entry in entries:
        metadata = entry.stat(follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(entry.name, _directory_flags(), dir_fd=root_fd)
            try:
                seal_tree_fd(child_fd)
            finally:
                os.close(child_fd)
        elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(f"staging contains unsupported entry: {entry.name}")
    os.fsync(root_fd)
    os.fchmod(root_fd, 0o555)
    os.fsync(root_fd)


def remove_tree_at(parent_fd: int, name: str) -> bool:
    """Recursively clean one child without following links; report completeness."""
    complete = True
    try:
        root_fd = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        return True
    except OSError:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                os.unlink(name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                return True
        except FileNotFoundError:
            return True
        except OSError:
            pass
        return False
    try:
        try:
            os.fchmod(root_fd, 0o700)
        except OSError:
            complete = False
        for entry in list(os.scandir(root_fd)):
            try:
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    complete = remove_tree_at(root_fd, entry.name) and complete
                else:
                    os.unlink(entry.name, dir_fd=root_fd)
            except OSError:
                complete = False
    finally:
        os.close(root_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        complete = False
    try:
        os.fsync(parent_fd)
    except OSError:
        complete = False
    return complete


def native_rename_noreplace(parent_fd: int, source: str, destination: str) -> None:
    """Rename two child names through the same verified parent FD."""
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if hasattr(library, "renameatx_np"):
        operation = library.renameatx_np
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        result = operation(
            parent_fd, source_bytes, parent_fd, destination_bytes, RENAME_EXCL
        )
    elif hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        operation.restype = ctypes.c_int
        result = operation(
            parent_fd, source_bytes, parent_fd, destination_bytes, RENAME_NOREPLACE
        )
    else:
        raise ValueError("platform lacks native no-replace rename support")
    if result != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), destination)


def result(
    *,
    valid: bool,
    outcome: str,
    created: bool,
    output_name: str | None,
    residue_name: str | None,
    manifest: dict[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "valid": valid,
        "status": outcome,
        "researchStatus": RESEARCH_STATUS,
        "created": created,
        "authorizationGranted": False,
        "outputName": output_name,
        "residueName": residue_name,
        "manifest": manifest,
        "errors": errors,
    }


def build_staging(
    repo_root: Path,
    output_parent: Path,
    *,
    guard_result: dict[str, Any],
) -> dict[str, Any]:
    """Build one artifact anchored first to guard JSON, then to artifactDigest."""
    parent_fd: int | None = None
    temporary_name: str | None = None
    final_name: str | None = None
    manifest: dict[str, Any] | None = None
    renamed = False
    staging_fd: int | None = None
    try:
        root = GUARD.require_repository_root(repo_root)
        guard = validate_guard_result(guard_result)
        commit = GUARD.resolve_commit(root, guard["headCommit"], "guard headCommit")
        if commit != guard["headCommit"]:
            raise ValueError("guard headCommit did not resolve exactly")
        actual_head = GUARD.resolve_commit(
            root, "HEAD", "repository HEAD", allow_head=True
        )
        if actual_head != commit:
            raise ValueError("guard headCommit must equal the checked-out HEAD")
        snapshot = GUARD.head_package_snapshot(root, commit, guard["skillPath"])
        if snapshot != guard["packageSnapshot"]:
            raise ValueError("complete guard packageSnapshot does not match pinned Git")
        parent, parent_fd = require_safe_output_parent(root, output_parent)
        manifest = validate_manifest(manifest_for(guard, snapshot))
        final_name = (
            f"{guard['slug']}-{commit[:12]}-"
            f"{manifest['artifactDigest'].removeprefix('sha256:')[:12]}"
        )
        temporary_name, staging_fd = random_mkdirat(parent_fd)
        try:
            os.mkdir(PACKAGE_DIRECTORY, 0o700, dir_fd=staging_fd)
            package_fd = os.open(
                PACKAGE_DIRECTORY, _directory_flags(), dir_fd=staging_fd
            )
            try:
                for entry in snapshot["files"]:
                    mode = 0o555 if entry["mode"] == "100755" else 0o444
                    write_file_at(
                        package_fd,
                        entry["path"],
                        read_pinned_blob(root, entry),
                        mode,
                    )
                review_package_fd(package_fd, snapshot["files"])
            finally:
                os.close(package_fd)
            write_file_at(
                staging_fd,
                MANIFEST_NAME,
                canonical_json_bytes(manifest, newline=True),
                0o444,
            )
            repeated = GUARD.head_package_snapshot(root, commit, guard["skillPath"])
            if repeated != snapshot:
                raise ValueError("pinned Git package changed during staging")
            package_fd = os.open(
                PACKAGE_DIRECTORY, _directory_flags(), dir_fd=staging_fd
            )
            try:
                review_package_fd(package_fd, snapshot["files"])
            finally:
                os.close(package_fd)
            if read_file_at(staging_fd, MANIFEST_NAME) != canonical_json_bytes(
                manifest, newline=True
            ):
                raise ValueError("staging manifest changed during review")
            seal_tree_fd(staging_fd)
            if stat.S_IMODE(os.fstat(staging_fd).st_mode) != 0o555:
                raise ValueError("sealed staging root mode is invalid")
            package_fd = os.open(
                PACKAGE_DIRECTORY, _directory_flags(), dir_fd=staging_fd
            )
            try:
                if stat.S_IMODE(os.fstat(package_fd).st_mode) != 0o555:
                    raise ValueError("sealed package directory mode is invalid")
                review_package_fd(package_fd, snapshot["files"])
            finally:
                os.close(package_fd)
            manifest_metadata = os.stat(
                MANIFEST_NAME,
                dir_fd=staging_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(manifest_metadata.st_mode)
                or manifest_metadata.st_nlink != 1
                or stat.S_IMODE(manifest_metadata.st_mode) != 0o444
            ):
                raise ValueError("sealed manifest metadata is invalid")
            verified_root = GUARD.require_repository_root(root)
            if verified_root != root:
                raise ValueError("repository root changed during staging")
            final_head = GUARD.resolve_commit(
                root, "HEAD", "repository HEAD after staging", allow_head=True
            )
            if final_head != commit:
                raise ValueError("repository HEAD changed during staging")
            os.fsync(parent_fd)
            native_rename_noreplace(parent_fd, temporary_name, final_name)
            renamed = True
            temporary_name = None
            try:
                require_same_directory_path(parent, parent_fd)
                final_metadata = os.stat(
                    final_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                staging_metadata = os.fstat(staging_fd)
                if (
                    not stat.S_ISDIR(final_metadata.st_mode)
                    or (final_metadata.st_dev, final_metadata.st_ino)
                    != (staging_metadata.st_dev, staging_metadata.st_ino)
                ):
                    raise ValueError(
                        "committed staging entry does not match its open directory"
                    )
                package_fd = os.open(
                    PACKAGE_DIRECTORY,
                    _directory_flags(),
                    dir_fd=staging_fd,
                )
                try:
                    review_package_fd(package_fd, snapshot["files"])
                finally:
                    os.close(package_fd)
                committed_manifest = read_file_at(staging_fd, MANIFEST_NAME)
                if committed_manifest != canonical_json_bytes(
                    manifest,
                    newline=True,
                ):
                    raise ValueError(
                        "committed staging manifest changed after rename"
                    )
                validate_manifest(
                    json.loads(
                        committed_manifest.decode("utf-8", errors="strict"),
                        object_pairs_hook=reject_duplicate_keys,
                        parse_constant=lambda token: (_ for _ in ()).throw(
                            ValueError(f"invalid JSON constant: {token}")
                        ),
                    )
                )
                os.fsync(parent_fd)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise CommitUncertainError(
                    f"rename committed but post-commit verification failed: {error}"
                ) from error
        finally:
            if staging_fd is not None:
                os.close(staging_fd)
                staging_fd = None
        return result(
            valid=True,
            outcome="committed",
            created=True,
            output_name=final_name,
            residue_name=None,
            manifest=manifest,
            errors=[],
        )
    except CommitUncertainError as error:
        return result(
            valid=False,
            outcome="commit-uncertain",
            created=True,
            output_name=final_name,
            residue_name=None,
            manifest=manifest,
            errors=[str(error)],
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        cleanup_complete = True
        residue_name: str | None = None
        if parent_fd is not None and temporary_name is not None:
            cleanup_complete = remove_tree_at(parent_fd, temporary_name)
            if not cleanup_complete:
                residue_name = temporary_name
        return result(
            valid=False,
            outcome="failed" if cleanup_complete else "failed-with-residue",
            created=renamed,
            output_name=final_name if renamed else None,
            residue_name=residue_name,
            manifest=manifest if renamed else None,
            errors=[
                str(error)
                if cleanup_complete
                else f"{error}; temporary staging cleanup was incomplete"
            ],
        )
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def main(argv: list[str] | None = None) -> int:
    parser = StructuredArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-parent", type=Path, required=True)
    parser.add_argument("--guard-result", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        guard = load_guard_result(args.guard_result)
        built = build_staging(
            args.repo_root, args.output_parent, guard_result=guard
        )
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        built = result(
            valid=False,
            outcome="failed",
            created=False,
            output_name=None,
            residue_name=None,
            manifest=None,
            errors=[str(error)],
        )
    print(json.dumps(built, ensure_ascii=False, indent=2))
    return 0 if built["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

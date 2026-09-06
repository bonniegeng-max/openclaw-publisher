#!/usr/bin/env python3
"""离线选择至多一个 Skill 发布目标；本研究工具不执行发布。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 2
PACKAGE_DIGEST_FORMAT = "safe-publish-package-v1"
SKILL_ROOT = "skills"
REQUIRED_FILES = ("SKILL.md", "CHANGELOG.md", ".clawhubignore")
MAX_PACKAGE_FILES = 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SUPPORTED_EVENTS = {"pull_request", "push", "workflow_dispatch"}
TRUSTED_GIT_ENTRY = Path("/usr/bin/git")
PRODUCTION_REF = "refs/heads/main"
GIT_TIMEOUT_SECONDS = 30
GIT_REAP_TIMEOUT_SECONDS = 5
MAX_GIT_OUTPUT_BYTES = 12 * 1024 * 1024


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid arguments: {message}")


def clean_git_environment() -> dict[str, str]:
    """Return a minimal environment that prevents implicit fetches and prompts."""
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


def run_git(
    repo_root: Path,
    *args: str,
    text: bool = True,
) -> subprocess.CompletedProcess:
    command = [
        str(TRUSTED_GIT_ENTRY),
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "diff.external=",
        *args,
    ]
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        env=clean_git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS

    def terminate_and_reap() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=GIT_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise ValueError(
                "Git process termination could not be confirmed"
            ) from error

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_fd = process.stdout.fileno()
    stderr_fd = process.stderr.fileno()
    streams = {
        stdout_fd: bytearray(),
        stderr_fd: bytearray(),
    }
    total_output = 0
    selector = selectors.DefaultSelector()
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_and_reap()
                raise ValueError("Git command timed out")
            events = selector.select(timeout=min(remaining, 0.25))
            if not events and process.poll() is not None:
                events = [
                    (selector.get_key(descriptor), selectors.EVENT_READ)
                    for descriptor in list(selector.get_map())
                ]
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                streams[key.fd].extend(chunk)
                total_output += len(chunk)
                if total_output > MAX_GIT_OUTPUT_BYTES:
                    terminate_and_reap()
                    raise ValueError("Git command output exceeds limit")
        remaining = max(0.0, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            terminate_and_reap()
            raise ValueError("Git command timed out") from error
    except BaseException:
        if process.poll() is None:
            try:
                terminate_and_reap()
            except ValueError:
                pass
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    stdout = bytes(streams[stdout_fd])
    stderr = bytes(streams[stderr_fd])
    if text:
        try:
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout.decode("utf-8", errors="strict"),
                stderr.decode("utf-8", errors="strict"),
            )
        except UnicodeError as error:
            raise ValueError("Git command output is not valid UTF-8") from error
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def decision_result(
    *,
    valid: bool,
    decision: str,
    event_name: str,
    ref: str,
    dry_run: bool,
    changed_only: bool,
    target: dict[str, Any] | None = None,
    base_commit: str | None = None,
    head_commit: str | None = None,
    event_before: str | None = None,
    event_sha: str | None = None,
    event_ref: str | None = None,
    blocking_reasons: list[str] | None = None,
) -> dict[str, Any]:
    authorization_eligible = (
        valid
        and target is not None
        and event_name == "push"
        and ref == PRODUCTION_REF
        and dry_run is False
        and changed_only is True
        and base_commit == event_before
        and head_commit == event_sha
        and ref == event_ref
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "valid": valid,
        "decision": decision,
        "eventName": event_name,
        "ref": ref,
        "dryRun": dry_run,
        "changedOnly": changed_only,
        "authorizationEligible": authorization_eligible,
        "authorized": False,
        "mutationAllowed": False,
        "targetCount": 1 if target is not None else 0,
        "skillPath": target["path"] if target is not None else None,
        "slug": target["slug"] if target is not None else None,
        "packageSnapshot": (
            target["packageSnapshot"] if target is not None else None
        ),
        "baseCommit": base_commit,
        "headCommit": head_commit,
        "eventBefore": event_before,
        "eventSha": event_sha,
        "eventRef": event_ref,
        "blockingReasons": blocking_reasons or [],
    }


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


def require_nofollow_capabilities() -> tuple[int, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if type(nofollow) is not int or type(directory) is not int:
        raise ValueError(
            "platform lacks required O_NOFOLLOW or O_DIRECTORY support"
        )
    return nofollow, directory


def require_local_directory_tree(path: Path, label: str) -> None:
    """Reject links and special files below a security-sensitive directory."""
    nofollow, directory = require_nofollow_capabilities()
    flags = os.O_RDONLY | directory | nofollow
    try:
        root_fd = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{label} cannot be opened safely") from error
    path_metadata = os.lstat(path)
    opened_root = os.fstat(root_fd)
    if (
        opened_root.st_dev,
        opened_root.st_ino,
    ) != (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ):
        os.close(root_fd)
        raise ValueError(f"{label} changed while being opened")

    def visit(directory_fd: int, prefix: str) -> None:
        before = os.fstat(directory_fd)
        try:
            with os.scandir(directory_fd) as iterator:
                entries = sorted(
                    (entry.name for entry in iterator),
                    key=lambda name: name.encode("utf-8"),
                )
        except (OSError, UnicodeEncodeError) as error:
            raise ValueError(f"{label} cannot be traversed safely") from error
        for entry_name in entries:
            relative = f"{prefix}/{entry_name}" if prefix else entry_name
            try:
                metadata = os.stat(
                    entry_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise ValueError(
                    f"{label} entry cannot be inspected: {relative}"
                ) from error
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
                try:
                    child_fd = os.open(
                        entry_name,
                        flags,
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    raise ValueError(
                        f"{label} directory cannot be opened safely: {relative}"
                    ) from error
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
                    f"{label} may contain only directories and regular files: "
                    f"{relative}"
                )
            else:
                try:
                    file_fd = os.open(
                        entry_name,
                        os.O_RDONLY | nofollow,
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    raise ValueError(
                        f"{label} file cannot be opened safely: {relative}"
                    ) from error
                try:
                    opened = os.fstat(file_fd)
                    observed = (
                        metadata.st_dev,
                        metadata.st_ino,
                        metadata.st_mode,
                        metadata.st_uid,
                        metadata.st_gid,
                        metadata.st_nlink,
                        metadata.st_size,
                        metadata.st_mtime_ns,
                        metadata.st_ctime_ns,
                    )
                    repeated = (
                        opened.st_dev,
                        opened.st_ino,
                        opened.st_mode,
                        opened.st_uid,
                        opened.st_gid,
                        opened.st_nlink,
                        opened.st_size,
                        opened.st_mtime_ns,
                        opened.st_ctime_ns,
                    )
                    if observed != repeated:
                        raise ValueError(
                            f"{label} file changed while opening: {relative}"
                        )
                    if opened.st_nlink != 1:
                        raise ValueError(
                            f"{label} must not contain hardlinked files: {relative}; "
                            "use git clone --no-hardlinks for isolated checkouts"
                        )
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or opened.st_uid != os.geteuid()
                        or stat.S_IMODE(opened.st_mode) & 0o022
                    ):
                        raise ValueError(
                            f"{label} contains an untrusted file: {relative}"
                        )
                    after_open = os.fstat(file_fd)
                    if repeated != (
                        after_open.st_dev,
                        after_open.st_ino,
                        after_open.st_mode,
                        after_open.st_uid,
                        after_open.st_gid,
                        after_open.st_nlink,
                        after_open.st_size,
                        after_open.st_mtime_ns,
                        after_open.st_ctime_ns,
                    ):
                        raise ValueError(
                            f"{label} file changed while inspecting: {relative}"
                        )
                finally:
                    os.close(file_fd)
        after = os.fstat(directory_fd)
        if _stable_metadata(before) != _stable_metadata(after):
            raise ValueError(f"{label} changed while being inspected")

    try:
        visit(root_fd, "")
    finally:
        os.close(root_fd)


def require_trusted_git() -> None:
    try:
        resolved = TRUSTED_GIT_ENTRY.resolve(strict=True)
        metadata = os.stat(resolved)
    except OSError as error:
        raise ValueError(
            f"trusted Git executable cannot be inspected: {error}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("trusted Git executable must be a regular file")
    if not os.access(resolved, os.X_OK):
        raise ValueError("trusted Git executable must be executable")


def require_repository_root(repo_root: Path) -> Path:
    require_trusted_git()
    supplied = lexical_absolute(repo_root)
    try:
        if stat.S_ISLNK(os.lstat(supplied).st_mode):
            raise ValueError("repo root must not be a symlink")
        root = supplied.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"repo root cannot be inspected: {error}") from error
    top = run_git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise ValueError("repo root must be a Git work tree")
    observed = lexical_absolute(Path(top.stdout.strip()))
    if observed != root:
        raise ValueError("repo root must be the Git top-level directory")
    git_entry = root / ".git"
    try:
        git_metadata = os.lstat(git_entry)
    except OSError as error:
        raise ValueError(f"repository .git cannot be inspected: {error}") from error
    if (
        not stat.S_ISDIR(git_metadata.st_mode)
        or git_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(git_metadata.st_mode) & 0o022
    ):
        raise ValueError("repository .git must be a local directory")
    for args, label in (
        (("rev-parse", "--absolute-git-dir"), "git-dir"),
        (
            ("rev-parse", "--path-format=absolute", "--git-common-dir"),
            "common-dir",
        ),
    ):
        completed = run_git(root, *args)
        if completed.returncode != 0:
            raise ValueError(f"repository {label} cannot be verified")
        if Path(completed.stdout.strip()).resolve() != git_entry.resolve():
            raise ValueError("repository must not use an external or shared Git directory")
    objects = git_entry / "objects"
    try:
        objects_metadata = os.lstat(objects)
    except OSError as error:
        raise ValueError(
            f"repository object store cannot be inspected: {error}"
        ) from error
    if (
        not stat.S_ISDIR(objects_metadata.st_mode)
        or objects_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(objects_metadata.st_mode) & 0o022
    ):
        raise ValueError("repository object store must be a local directory")
    require_local_directory_tree(objects, "repository object store")
    alternates = objects / "info" / "alternates"
    if alternates.exists() or alternates.is_symlink():
        raise ValueError("repository object store must not use alternates")
    return root


def require_clean_head(repo_root: Path, requested_head: str) -> str:
    actual_head = resolve_commit(
        repo_root,
        "HEAD",
        "repository HEAD",
        allow_head=True,
    )
    head_commit = resolve_commit(
        repo_root,
        requested_head,
        "head",
        allow_head=True,
    )
    if head_commit != actual_head:
        raise ValueError("head must resolve to the checked-out repository HEAD")
    status = run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        text=False,
    )
    if status.returncode != 0:
        raise ValueError("repository cleanliness cannot be verified")
    if status.stdout:
        raise ValueError("repository worktree must be clean")
    actual_head_after_status = resolve_commit(
        repo_root,
        "HEAD",
        "repository HEAD after status",
        allow_head=True,
    )
    if actual_head_after_status != actual_head:
        raise ValueError("repository HEAD changed while verifying cleanliness")
    return head_commit


def resolve_commit(
    repo_root: Path,
    value: str,
    label: str,
    *,
    allow_head: bool = False,
) -> str:
    if (
        (allow_head and value == "HEAD")
        or COMMIT_PATTERN.fullmatch(value) is not None
    ):
        pass
    else:
        suffix = "HEAD or a full lowercase commit" if allow_head else (
            "a full lowercase commit"
        )
        raise ValueError(f"{label} must be {suffix}")
    completed = run_git(
        repo_root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{value}^{{commit}}",
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError(f"{label} cannot be resolved to a commit")
    return commit


def validate_explicit_path(raw_path: str) -> str:
    if not raw_path or raw_path != raw_path.strip():
        raise ValueError("skill_path must be a non-empty canonical path")
    if "\\" in raw_path:
        raise ValueError("skill_path must use POSIX separators")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or path.as_posix() != raw_path:
        raise ValueError("skill_path must be a canonical repository-relative path")
    parts = path.parts
    if (
        len(parts) != 2
        or parts[0] != SKILL_ROOT
        or parts[1] in {".", ".."}
        or SLUG_PATTERN.fullmatch(parts[1]) is None
    ):
        raise ValueError("skill_path must equal skills/<valid-slug>")
    if parts[1].startswith("clawhub-") or parts[1].endswith("-clawhub"):
        raise ValueError("skill_path uses the protected ClawHub slug namespace")
    return path.as_posix()


def canonical_package_digest(
    skill_path: str,
    tree_oid: str,
    files: list[dict[str, str]],
) -> str:
    """Digest the documented canonical JSON package representation."""
    payload = json.dumps(
        {
            "files": files,
            "format": PACKAGE_DIGEST_FORMAT,
            "skillPath": skill_path,
            "treeOid": tree_oid,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def head_package_snapshot(
    repo_root: Path,
    head_commit: str,
    relative: str,
) -> dict[str, Any]:
    """Build a package manifest exclusively from the selected commit tree."""
    root_entry = run_git(
        repo_root,
        "ls-tree",
        "-z",
        head_commit,
        "--",
        relative,
        text=False,
    )
    if root_entry.returncode != 0:
        raise ValueError(f"skill target tree cannot be read: {relative}")
    entries = [entry for entry in root_entry.stdout.split(b"\0") if entry]
    if not entries:
        raise ValueError(f"skill target does not exist in HEAD tree: {relative}")
    if len(entries) != 1:
        raise ValueError(f"skill target tree is ambiguous: {relative}")
    try:
        metadata, observed_path = entries[0].split(b"\t", 1)
        mode, object_type, tree_oid = metadata.decode("ascii").split(" ")
        decoded_path = observed_path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("skill target tree entry is malformed") from error
    if mode == "120000":
        raise ValueError(f"skill target must not contain symlinks: {relative}")
    if (
        decoded_path != relative
        or mode != "040000"
        or object_type != "tree"
        or COMMIT_PATTERN.fullmatch(tree_oid) is None
    ):
        raise ValueError(f"skill target must be a directory in HEAD tree: {relative}")

    listing = run_git(
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        head_commit,
        "--",
        relative,
        text=False,
    )
    if listing.returncode != 0:
        raise ValueError(f"skill target files cannot be read: {relative}")
    prefix = relative + "/"
    files: list[dict[str, str]] = []
    package_bytes = 0
    for raw_entry in listing.stdout.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            file_mode, object_type, blob_oid = metadata.decode("ascii").split(" ")
            full_path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("skill target contains a malformed tree entry") from error
        if not full_path.startswith(prefix):
            raise ValueError("skill target tree escaped its package boundary")
        package_path = full_path[len(prefix):]
        package_parts = PurePosixPath(package_path).parts
        if (
            not package_path
            or PurePosixPath(package_path).as_posix() != package_path
            or any(part in {"", ".", ".."} for part in package_parts)
        ):
            raise ValueError("skill target contains a non-canonical file path")
        if object_type != "blob" or file_mode not in {"100644", "100755"}:
            raise ValueError(
                "skill target HEAD tree may contain only regular files: "
                f"{full_path}"
            )
        if COMMIT_PATTERN.fullmatch(blob_oid) is None:
            raise ValueError(f"skill target blob OID is invalid: {full_path}")
        if len(files) >= MAX_PACKAGE_FILES:
            raise ValueError(
                f"skill target exceeds maximum file count: {MAX_PACKAGE_FILES}"
            )
        size = run_git(
            repo_root,
            "cat-file",
            "-s",
            blob_oid,
        )
        try:
            blob_size = int(size.stdout.strip())
        except ValueError as error:
            raise ValueError(
                f"skill target blob size is invalid: {full_path}"
            ) from error
        if size.returncode != 0 or blob_size < 0:
            raise ValueError(f"skill target blob size cannot be read: {full_path}")
        if blob_size > MAX_FILE_BYTES:
            raise ValueError(
                f"skill target file exceeds maximum size: {full_path}"
            )
        package_bytes += blob_size
        if package_bytes > MAX_PACKAGE_BYTES:
            raise ValueError(
                f"skill target exceeds maximum package size: {MAX_PACKAGE_BYTES}"
            )
        blob = run_git(
            repo_root,
            "cat-file",
            "blob",
            blob_oid,
            text=False,
        )
        if blob.returncode != 0:
            raise ValueError(f"skill target blob cannot be read: {full_path}")
        files.append(
            {
                "path": package_path,
                "mode": file_mode,
                "blobOid": blob_oid,
                "sha256": "sha256:" + hashlib.sha256(blob.stdout).hexdigest(),
            }
        )
    files.sort(key=lambda item: item["path"].encode("utf-8"))
    file_paths = {item["path"] for item in files}
    for name in REQUIRED_FILES:
        if name not in file_paths:
            raise ValueError(
                f"skill target is missing required file {name}: {relative}"
            )
    return {
        "treeOid": tree_oid,
        "files": files,
        "packageDigest": canonical_package_digest(relative, tree_oid, files),
    }


def _stable_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def worktree_package_evidence(
    repo_root: Path,
    relative: str,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Walk without following links and hash every regular package file."""
    nofollow, directory = require_nofollow_capabilities()
    canonical = validate_explicit_path(relative)
    flags = os.O_RDONLY | directory | nofollow
    opened_directories: list[tuple[int, tuple[int, ...], str]] = []
    try:
        current_fd = os.open(repo_root, flags)
    except OSError as error:
        raise ValueError("repository root cannot be opened safely") from error
    opened_directories.append(
        (current_fd, _stable_metadata(os.fstat(current_fd)), ".")
    )
    try:
        for component in PurePosixPath(canonical).parts:
            try:
                child_fd = os.open(
                    component,
                    flags,
                    dir_fd=current_fd,
                )
            except OSError as error:
                raise ValueError(
                    f"skill target cannot be opened safely: {relative}"
                ) from error
            current_fd = child_fd
            opened_directories.append(
                (
                    current_fd,
                    _stable_metadata(os.fstat(current_fd)),
                    component,
                )
            )
        package_fd = current_fd
    except BaseException:
        for descriptor, _, _ in reversed(opened_directories):
            os.close(descriptor)
        raise
    files: dict[str, dict[str, str]] = {}
    directories: set[str] = set()
    package_bytes = 0

    def visit(directory_fd: int, prefix: str) -> None:
        nonlocal package_bytes
        before = os.fstat(directory_fd)
        try:
            entries = sorted(
                os.scandir(directory_fd),
                key=lambda entry: entry.name.encode("utf-8"),
            )
        except (OSError, UnicodeEncodeError) as error:
            raise ValueError("skill worktree cannot be traversed safely") from error
        for entry in entries:
            package_path = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ValueError(
                    f"skill worktree entry cannot be inspected: {package_path}"
                ) from error
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"skill target must not contain symlinks: {relative}/{package_path}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(package_path)
                try:
                    child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                except OSError as error:
                    raise ValueError(
                        f"skill directory cannot be opened safely: {package_path}"
                    ) from error
                try:
                    visit(child_fd, package_path)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(
                    f"skill target may contain only regular files: "
                    f"{relative}/{package_path}"
                )
            if metadata.st_nlink != 1:
                raise ValueError(
                    f"skill target must not contain hardlinked files: "
                    f"{relative}/{package_path}"
                )
            if len(files) >= MAX_PACKAGE_FILES:
                raise ValueError(
                    f"skill target exceeds maximum file count: {MAX_PACKAGE_FILES}"
                )
            if metadata.st_size > MAX_FILE_BYTES:
                raise ValueError(
                    f"skill target file exceeds maximum size: "
                    f"{relative}/{package_path}"
                )
            package_bytes += metadata.st_size
            if package_bytes > MAX_PACKAGE_BYTES:
                raise ValueError(
                    f"skill target exceeds maximum package size: "
                    f"{MAX_PACKAGE_BYTES}"
                )
            file_flags = os.O_RDONLY | nofollow
            try:
                file_fd = os.open(entry.name, file_flags, dir_fd=directory_fd)
            except OSError as error:
                raise ValueError(
                    f"skill file cannot be opened safely: {package_path}"
                ) from error
            digest = hashlib.sha256()
            try:
                opened = os.fstat(file_fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise ValueError(
                        f"skill file changed type while reading: {package_path}"
                    )
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                after = os.fstat(file_fd)
            finally:
                os.close(file_fd)
            if (
                _stable_metadata(metadata) != _stable_metadata(opened)
                or _stable_metadata(opened) != _stable_metadata(after)
            ):
                raise ValueError(
                    f"skill file changed while reading: {package_path}"
                )
            files[package_path] = {
                "mode": "100755" if opened.st_mode & 0o111 else "100644",
                "sha256": "sha256:" + digest.hexdigest(),
            }
        after = os.fstat(directory_fd)
        if _stable_metadata(before) != _stable_metadata(after):
            raise ValueError("skill directory changed while traversing")

    try:
        visit(package_fd, "")
        for descriptor, before, component in opened_directories:
            if _stable_metadata(os.fstat(descriptor)) != before:
                raise ValueError(
                    "skill path changed while traversing: "
                    f"{component}"
                )
    finally:
        for descriptor, _, _ in reversed(opened_directories):
            os.close(descriptor)
    return files, directories


def compare_worktree_to_snapshot(
    repo_root: Path,
    relative: str,
    snapshot: dict[str, Any],
) -> None:
    observed_files, observed_directories = worktree_package_evidence(
        repo_root,
        relative,
    )
    expected_files = {
        item["path"]: {"mode": item["mode"], "sha256": item["sha256"]}
        for item in snapshot["files"]
    }
    expected_directories = {
        parent.as_posix()
        for path in expected_files
        for parent in PurePosixPath(path).parents
        if parent.as_posix() != "."
    }
    extra_files = sorted(set(observed_files) - set(expected_files))
    missing_files = sorted(set(expected_files) - set(observed_files))
    extra_directories = sorted(observed_directories - expected_directories)
    missing_directories = sorted(expected_directories - observed_directories)
    if extra_files or extra_directories:
        extras = extra_files + [f"{path}/" for path in extra_directories]
        raise ValueError(
            "skill worktree contains extra or ignored entries: "
            + ", ".join(extras)
        )
    if missing_files or missing_directories:
        missing = missing_files + [f"{path}/" for path in missing_directories]
        raise ValueError(
            "skill worktree is missing HEAD tree entries: " + ", ".join(missing)
        )
    for path, expected in expected_files.items():
        if observed_files[path] != expected:
            raise ValueError(
                f"skill worktree file differs from HEAD tree: {relative}/{path}"
            )


def validate_skill_folder(
    repo_root: Path,
    head_commit: str,
    relative: str,
) -> dict[str, Any]:
    snapshot = head_package_snapshot(repo_root, head_commit, relative)
    compare_worktree_to_snapshot(repo_root, relative, snapshot)
    return {
        "slug": PurePosixPath(relative).name,
        "path": relative,
        "packageSnapshot": snapshot,
    }


def changed_skill_paths(repo_root: Path, base: str, head: str) -> list[str]:
    ancestry = run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        base,
        head,
    )
    if ancestry.returncode != 0:
        raise ValueError("base must be an ancestor of head")
    changed = run_git(
        repo_root,
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        base,
        head,
        "--",
        SKILL_ROOT,
        text=False,
    )
    if changed.returncode != 0:
        raise ValueError("changed paths cannot be read from Git")
    try:
        names = changed.stdout.decode("utf-8", errors="strict").split("\0")
    except UnicodeDecodeError as error:
        raise ValueError("changed paths are not valid UTF-8") from error
    candidates: set[str] = set()
    for name in names:
        if not name:
            continue
        parts = PurePosixPath(name).parts
        if len(parts) >= 2 and parts[0] == SKILL_ROOT:
            relative = f"{SKILL_ROOT}/{parts[1]}"
            validate_explicit_path(relative)
            candidates.add(relative)
    return sorted(candidates)


def head_tree_contains(
    repo_root: Path,
    head_commit: str,
    relative: str,
) -> bool:
    entry = run_git(
        repo_root,
        "ls-tree",
        "-z",
        head_commit,
        "--",
        relative,
        text=False,
    )
    if entry.returncode != 0:
        raise ValueError(f"HEAD tree path cannot be inspected: {relative}")
    return bool(entry.stdout)


def evaluate(
    repo_root: Path,
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
) -> dict[str, Any]:
    base_commit: str | None = None
    head_commit: str | None = None
    output_event = event_name if isinstance(event_name, str) else ""
    output_ref = ref if isinstance(ref, str) else ""
    output_dry_run = dry_run if type(dry_run) is bool else False
    output_changed_only = (
        changed_only if type(changed_only) is bool else False
    )
    output_event_before = (
        event_before if isinstance(event_before, str) and event_before else None
    )
    output_event_sha = (
        event_sha if isinstance(event_sha, str) and event_sha else None
    )
    output_event_ref = (
        event_ref if isinstance(event_ref, str) and event_ref else None
    )
    try:
        root = require_repository_root(repo_root)
        if not all(
            isinstance(value, str)
            for value in (
                event_name,
                ref,
                base,
                head,
                skill_path,
                event_before,
                event_sha,
                event_ref,
            )
        ):
            raise ValueError("event, Git boundary, and skill_path inputs must be strings")
        if event_name not in SUPPORTED_EVENTS:
            raise ValueError("event_name is not supported")
        if type(dry_run) is not bool or type(changed_only) is not bool:
            raise ValueError("dry_run and changed_only must be booleans")
        if event_name == "workflow_dispatch" and not dry_run:
            raise ValueError("workflow_dispatch is restricted to dry-run")
        if event_name == "pull_request" and not dry_run:
            raise ValueError("pull_request is restricted to dry-run")
        if event_name == "push" and not dry_run and ref != PRODUCTION_REF:
            raise ValueError("real publish requires a push to refs/heads/main")
        if event_name == "push" and not dry_run and not base:
            raise ValueError("real publish requires a full base commit")
        if event_name == "push" and not dry_run:
            if changed_only is not True:
                raise ValueError("real publish requires changed_only true")
            if head == "HEAD" or COMMIT_PATTERN.fullmatch(head) is None:
                raise ValueError("real publish head must be a full lowercase commit")
            if (
                COMMIT_PATTERN.fullmatch(event_before) is None
                or COMMIT_PATTERN.fullmatch(event_sha) is None
                or event_ref != PRODUCTION_REF
            ):
                raise ValueError(
                    "real publish requires complete trusted push event evidence"
                )
            if base != event_before or head != event_sha or ref != event_ref:
                raise ValueError(
                    "base, head, and ref must match trusted push event evidence"
                )
        if not changed_only and not skill_path:
            raise ValueError("unbounded Skill directory scans are forbidden")
        if changed_only and not base and not skill_path:
            raise ValueError(
                "changed_only requires a valid base or explicit skill_path"
            )

        head_commit = require_clean_head(root, head)
        changed_paths: list[str] | None = None
        if base:
            base_commit = resolve_commit(root, base, "base")
            changed_paths = changed_skill_paths(root, base_commit, head_commit)

        if skill_path:
            relative = validate_explicit_path(skill_path)
            target = validate_skill_folder(root, head_commit, relative)
            if changed_paths is not None:
                if relative not in changed_paths:
                    raise ValueError(
                        "explicit skill_path is not changed in the selected range"
                    )
                if any(candidate != relative for candidate in changed_paths):
                    raise ValueError(
                        "explicit skill_path does not cover all changed Skills"
                    )
        else:
            if changed_paths is None:
                raise ValueError("changed target selection requires a base")
            if len(changed_paths) > 1:
                raise ValueError("more than one changed Skill target is forbidden")
            existing = [
                relative
                for relative in changed_paths
                if head_tree_contains(root, head_commit, relative)
            ]
            target = (
                validate_skill_folder(root, head_commit, existing[0])
                if existing
                else None
            )
        require_clean_head(root, head_commit)
        if target is not None:
            repeated_target = validate_skill_folder(
                root,
                head_commit,
                target["path"],
            )
            if repeated_target["packageSnapshot"] != target["packageSnapshot"]:
                raise ValueError("skill package snapshot changed during validation")
        require_clean_head(root, head_commit)
        require_repository_root(root)
        return decision_result(
            valid=True,
            decision="single-target" if target is not None else "no-op",
            event_name=event_name,
            ref=ref,
            dry_run=dry_run,
            changed_only=changed_only,
            target=target,
            base_commit=base_commit,
            head_commit=head_commit,
            event_before=output_event_before,
            event_sha=output_event_sha,
            event_ref=output_event_ref,
        )
    except (OSError, ValueError) as error:
        return decision_result(
            valid=False,
            decision="blocked",
            event_name=output_event,
            ref=output_ref,
            dry_run=output_dry_run,
            changed_only=output_changed_only,
            base_commit=base_commit,
            head_commit=head_commit,
            event_before=output_event_before,
            event_sha=output_event_sha,
            event_ref=output_event_ref,
            blocking_reasons=[str(error)],
        )


def parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("boolean inputs must be true or false")


def main(argv: list[str] | None = None) -> int:
    parser = StructuredArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
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
        result = evaluate(
            args.repo_root,
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
    except ValueError as error:
        result = decision_result(
            valid=False,
            decision="blocked",
            event_name="",
            ref="",
            dry_run=False,
            changed_only=False,
            blocking_reasons=[str(error)],
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

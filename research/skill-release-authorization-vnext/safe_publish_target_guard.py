#!/usr/bin/env python3
"""离线选择至多一个 Skill 发布目标；本研究工具不执行发布。"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
SKILL_ROOT = "skills"
REQUIRED_FILES = ("SKILL.md", "CHANGELOG.md", ".clawhubignore")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SUPPORTED_EVENTS = {"pull_request", "push", "workflow_dispatch"}
TRUSTED_GIT_ENTRY = Path("/usr/bin/git")
PRODUCTION_REF = "refs/heads/main"
GIT_TIMEOUT_SECONDS = 30


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
    try:
        return subprocess.run(
            command,
            cwd=repo_root,
            env=clean_git_environment(),
            check=False,
            capture_output=True,
            text=text,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("Git command timed out") from error


def decision_result(
    *,
    valid: bool,
    decision: str,
    event_name: str,
    ref: str,
    dry_run: bool,
    changed_only: bool,
    target: dict[str, str] | None = None,
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
    if not stat.S_ISDIR(git_metadata.st_mode):
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
    alternates = git_entry / "objects" / "info" / "alternates"
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


def validate_skill_folder(repo_root: Path, relative: str) -> dict[str, str]:
    path = repo_root / relative
    if path_uses_symlink(path):
        raise ValueError(f"skill target must not contain symlinks: {relative}")
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError(f"skill target does not exist: {relative}") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"skill target must be a directory: {relative}")
    for name in REQUIRED_FILES:
        child = path / name
        try:
            child_metadata = os.lstat(child)
        except OSError as error:
            raise ValueError(
                f"skill target is missing required file {name}: {relative}"
            ) from error
        if not stat.S_ISREG(child_metadata.st_mode):
            raise ValueError(
                f"skill required path must be a regular file: {relative}/{name}"
            )
    return {"slug": path.name, "path": relative}


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
            target = validate_skill_folder(root, relative)
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
                if (root / relative).exists()
            ]
            target = (
                validate_skill_folder(root, existing[0])
                if existing
                else None
            )
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

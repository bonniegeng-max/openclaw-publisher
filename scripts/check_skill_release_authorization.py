#!/usr/bin/env python3
"""Fail-closed offline authorization check for formal Skill releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CATALOG_PATH = ".clawhub/skill-catalog.json"
DEFAULT_AUTHORIZATION_PATH = ".clawhub/skill-release-authorization.json"
MAX_AUTHORIZATION_LIFETIME = timedelta(hours=72)
MAX_REVIEW_AGE = timedelta(hours=72)
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
RELEASE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?")
ALLOWED_MODES = {"dry-run", "publish"}
ALLOWED_CHANGE_CLASSES = {
    "correctness-fix",
    "growth-improvement",
    "new-skill",
}
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "status",
    "releaseId",
    "issuedAt",
    "expiresAt",
    "observationNotBefore",
    "baseCommit",
    "candidateCommit",
    "modes",
    "targets",
    "catalogChanged",
    "contentDigest",
    "changeSetDigest",
    "review",
}
TARGET_FIELDS = {"slug", "version"}
REVIEW_FIELDS = {
    "completed",
    "reviewedAt",
    "changeClass",
    "reason",
    "evidence",
}
EVIDENCE_FIELDS = {"path", "sha256"}
PROTECTED_CONTROL_PATHS = {
    "metrics/observation-policy.json",
    "scripts/check_skill_release_authorization.py",
    "scripts/validate_skill_catalog.py",
}
TRUSTED_CONTROL_PATHS = {
    "checker": "scripts/check_skill_release_authorization.py",
    "validator": "scripts/validate_skill_catalog.py",
}
EXPECTED_CONTROL_ORIGIN = "github.com/bonniegeng-max/openclaw-publisher"


def reject_nonstandard_number(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_nonstandard_number,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} cannot be read as strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_json_object_text(value: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            value,
            parse_constant=reject_nonstandard_number,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} is not strict JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty ISO 8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{label} is not a valid ISO 8601 time") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def resolve_inside(repo_root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} must be a non-empty string")
    if Path(relative).is_absolute():
        raise ValueError(f"{label} must be repository-relative")
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes repository root") from error
    return candidate


def exact_string_list(value: Any, allowed: set[str] | None = None) -> bool:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        return False
    return allowed is None or set(value).issubset(allowed)


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path} cannot be read: {error}") from error
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path} frontmatter missing")
    result = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip()
        if normalized_key in result:
            raise ValueError(
                f"{path} frontmatter has duplicate key: {normalized_key}"
            )
        result[normalized_key] = value.strip()
    return result


def load_base_versions(
    repo_root: Path,
    base_commit: str,
    base_catalog: dict[str, Any],
    slugs: set[str],
) -> dict[str, str | None]:
    versions = {}
    for slug in slugs:
        catalog_key = f"skills/{slug}"
        if catalog_key not in base_catalog:
            versions[slug] = None
            continue
        try:
            skill_text = run_git(
                repo_root,
                "show",
                f"{base_commit}:{catalog_key}/SKILL.md",
            )
        except ValueError as error:
            raise ValueError(f"{slug}: cannot read base SKILL.md: {error}") from error
        match = re.match(r"\A---\n(.*?)\n---\n", skill_text, re.DOTALL)
        if not match:
            raise ValueError(f"{slug}: base SKILL.md frontmatter missing")
        observed = {}
        for line in match.group(1).splitlines():
            if ":" not in line or line.startswith(" "):
                continue
            key, value = line.split(":", 1)
            normalized_key = key.strip()
            if normalized_key in observed:
                raise ValueError(
                    f"{slug}: base frontmatter has duplicate key: {normalized_key}"
                )
            observed[normalized_key] = value.strip()
        version = observed.get("version")
        if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
            raise ValueError(f"{slug}: base version must use three-part semver")
        versions[slug] = version
    return versions


def semver_tuple(value: str) -> tuple[int, int, int]:
    if SEMVER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid three-part semver: {value}")
    return tuple(int(part) for part in value.split("."))


def load_catalog_validator(repo_root: Path):
    validator_path = repo_root / "scripts" / "validate_skill_catalog.py"
    if not validator_path.is_file():
        raise ValueError("catalog validator is missing")
    spec = importlib.util.spec_from_file_location(
        "_release_authorization_catalog_validator",
        validator_path,
    )
    if spec is None or spec.loader is None:
        raise ValueError("catalog validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def validate_catalog(
    repo_root: Path,
    catalog_path: Path,
    validator: Any | None = None,
) -> list[str]:
    try:
        if validator is None:
            validator = load_catalog_validator(repo_root)
        if not callable(getattr(validator, "validate", None)):
            raise ValueError("catalog validator must expose callable validate")
        result = validator.validate(repo_root, catalog_path)
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, GeneratorExit)):
            raise
        return [f"catalog preflight cannot run: {error}"]
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool):
        return ["catalog preflight returned an invalid result"]
    errors = result.get("errors", [])
    if not isinstance(errors, list):
        return ["catalog preflight returned malformed errors"]
    if result["valid"]:
        return []
    messages = []
    for item in errors:
        if isinstance(item, dict):
            code = item.get("code", "UNKNOWN")
            path = item.get("path", "$")
            message = item.get("message", "catalog validation failed")
            if not all(
                isinstance(value, str)
                for value in (code, path, message)
            ):
                messages.append("catalog preflight returned malformed errors")
            else:
                messages.append(
                    f"catalog preflight {code} at {path}: {message}"
                )
        else:
            messages.append("catalog preflight returned malformed errors")
    return messages or ["catalog preflight failed without an error"]


def normalize_changed_paths(changed_paths: Any) -> tuple[set[str], list[str]]:
    errors = []
    normalized = set()
    if not isinstance(changed_paths, list):
        return set(), ["changed paths must be an array"]
    for value in changed_paths:
        if not isinstance(value, str) or not value.strip():
            errors.append("every changed path must be a non-empty string")
            continue
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"changed path must stay inside repository: {value}")
            continue
        normalized.add(path.as_posix().removeprefix("./"))
    return normalized, errors


def catalog_changed_slugs(
    base_catalog: dict[str, Any],
    current_catalog: dict[str, Any],
) -> tuple[set[str], list[str]]:
    errors = []
    changed = set()
    missing = object()
    for key in set(base_catalog) | set(current_catalog):
        if base_catalog.get(key, missing) == current_catalog.get(key, missing):
            continue
        match = re.fullmatch(r"skills/([^/]+)", key) if isinstance(key, str) else None
        if match is None or SLUG_PATTERN.fullmatch(match.group(1)) is None:
            errors.append(f"changed catalog key is not skills/<slug>: {key!r}")
            continue
        changed.add(match.group(1))
    return changed, errors


def formal_changed_slugs(
    changed_paths: set[str],
    base_catalog: dict[str, Any],
    current_catalog: dict[str, Any],
) -> tuple[set[str], bool, list[str]]:
    errors = []
    skill_slugs = set()
    for path in changed_paths:
        if not path.startswith("skills/"):
            continue
        match = re.match(r"skills/([^/]+)(?:/|$)", path)
        if match is None or SLUG_PATTERN.fullmatch(match.group(1)) is None:
            errors.append(f"formal Skill path has an invalid slug: {path}")
            continue
        skill_slugs.add(match.group(1))

    catalog_changed = CATALOG_PATH in changed_paths
    catalog_slugs = set()
    if catalog_changed:
        catalog_slugs, catalog_errors = catalog_changed_slugs(
            base_catalog,
            current_catalog,
        )
        errors.extend(catalog_errors)
        if not catalog_slugs:
            errors.append("catalog is marked changed but has no effective entry changes")
    return skill_slugs | catalog_slugs, catalog_changed, errors


def update_digest(hasher: Any, label: str, payload: bytes) -> None:
    label_bytes = label.encode("utf-8")
    hasher.update(len(label_bytes).to_bytes(8, "big"))
    hasher.update(label_bytes)
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)


def path_uses_symlink(repo_root: Path, relative: str) -> bool:
    current = repo_root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def absolute_path_uses_symlink(path: Path) -> bool:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
    except OSError as error:
        raise ValueError(f"cannot inspect path {path}: {error}") from error
    return False


def normalize_origin(value: str) -> str:
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)"
        r"([^/]+/[^/]+?)(?:\.git)?",
        value.strip(),
    )
    if match is not None:
        return f"github.com/{match.group(1)}"
    path = Path(value).expanduser()
    if path.is_absolute() or value.startswith((".", "..")):
        return f"file://{lexical_absolute(path)}"
    raise ValueError("origin must be an explicit GitHub URL or absolute local path")


def file_sha256(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{path} cannot be read: {error}") from error
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def compute_content_digest(
    repo_root: Path,
    catalog: dict[str, Any],
    slugs: set[str],
) -> str:
    repo_root = repo_root.resolve()
    hasher = hashlib.sha256()
    for slug in sorted(slugs):
        if SLUG_PATTERN.fullmatch(slug) is None:
            raise ValueError(f"cannot digest invalid slug: {slug}")
        catalog_key = f"skills/{slug}"
        if catalog_key not in catalog:
            raise ValueError(f"{slug}: target is absent from current catalog")
        entry = catalog[catalog_key]
        entry_bytes = json.dumps(
            entry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        update_digest(hasher, f"{catalog_key}#catalog", entry_bytes)

        raw_skill_dir = repo_root / catalog_key
        if path_uses_symlink(repo_root, catalog_key):
            raise ValueError(f"{slug}: target path contains a symlink")
        skill_dir = raw_skill_dir.resolve()
        try:
            skill_dir.relative_to(repo_root.resolve())
        except ValueError as error:
            raise ValueError(f"{slug}: target path escapes repository") from error
        if not skill_dir.is_dir():
            raise ValueError(f"{slug}: target directory is missing")
        files = sorted(path for path in skill_dir.rglob("*") if path.is_file())
        if not files:
            raise ValueError(f"{slug}: target directory has no files")
        for path in files:
            if path.is_symlink():
                raise ValueError(f"{slug}: target contains a symlink")
            relative = path.relative_to(repo_root).as_posix()
            try:
                payload = path.read_bytes()
            except OSError as error:
                raise ValueError(f"{relative} cannot be read: {error}") from error
            update_digest(hasher, relative, payload)
    return f"sha256:{hasher.hexdigest()}"


def compute_change_set_digest(
    repo_root: Path,
    changed_paths: set[str],
    authorization_relative: str,
) -> str:
    repo_root = repo_root.resolve()
    hasher = hashlib.sha256()
    included = [
        path for path in sorted(changed_paths)
        if path != authorization_relative
    ]
    if not included:
        raise ValueError("change set contains only the authorization file")
    for relative in included:
        path = resolve_inside(repo_root, relative, "changed path")
        if path_uses_symlink(repo_root, relative):
            raise ValueError(f"changed path contains a symlink: {relative}")
        if not path.exists():
            update_digest(hasher, relative, b"deleted")
        elif path.is_file():
            update_digest(hasher, relative, b"file\0" + path.read_bytes())
        else:
            raise ValueError(f"changed path is not a regular file: {relative}")
    return f"sha256:{hasher.hexdigest()}"


def invalid_result(mode: str, now: datetime, error: Exception) -> dict[str, Any]:
    return {
        "valid": False,
        "authorized": False,
        "mode": mode,
        "evaluatedAt": now.astimezone(timezone.utc).isoformat(),
        "targets": [],
        "blockingReasons": [],
        "errors": [str(error)],
    }


def trusted_control_invalid_result(
    mode: str,
    now: datetime,
    error: Exception,
) -> dict[str, Any]:
    result = invalid_result(mode, now, error)
    result["phase"] = "trusted-control"
    return result


class TrustedControl:
    """Verified control-plane files from an independent trusted checkout."""

    def __init__(
        self,
        candidate_root: Path,
        control_root: Path,
        control_commit: str,
        expected_origin_identity: str,
    ) -> None:
        self.candidate_root = lexical_absolute(candidate_root)
        self.control_root = lexical_absolute(control_root)
        self.control_commit = control_commit
        self.expected_origin_identity = expected_origin_identity
        self.snapshots: dict[str, bytes] = {}
        self.file_evidence: dict[str, dict[str, str]] = {}
        self.origin_identity = ""
        self.executing_checker_path_matched = False
        self.candidate_checkout_verified = False
        self.control_git_dir: Path | None = None
        self.control_common_dir: Path | None = None
        self._verify_control()

    def _git(self, root: Path, *args: str) -> str:
        return run_git(root, *args).strip()

    def _verify_checkout(
        self,
        root: Path,
        label: str,
    ) -> tuple[Path, Path, Path]:
        top_level = Path(self._git(root, "rev-parse", "--show-toplevel")).resolve()
        if top_level != root.resolve():
            raise ValueError(f"{label} must be a Git checkout root")
        git_dir = Path(
            self._git(root, "rev-parse", "--absolute-git-dir")
        ).resolve()
        common_dir = Path(
            self._git(
                root,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
        ).resolve()
        git_entry = root / ".git"
        try:
            git_entry_mode = os.lstat(git_entry).st_mode
        except OSError as error:
            raise ValueError(f"{label} Git entry cannot be inspected: {error}") from error
        if not stat.S_ISDIR(git_entry_mode) or git_entry.is_symlink():
            raise ValueError(f"{label} must not be a linked Git worktree")
        if git_dir != git_entry.resolve() or common_dir != git_dir:
            raise ValueError(f"{label} must use an independent local Git directory")
        objects = git_dir / "objects"
        try:
            objects_mode = os.lstat(objects).st_mode
        except OSError as error:
            raise ValueError(
                f"{label} object store cannot be inspected: {error}"
            ) from error
        if not stat.S_ISDIR(objects_mode) or objects.is_symlink():
            raise ValueError(f"{label} object store must be a local directory")
        alternates = objects / "info" / "alternates"
        if alternates.exists() or alternates.is_symlink():
            raise ValueError(f"{label} object store must not use alternates")
        return top_level, git_dir, common_dir

    def _verify_blob(self, relative: str, label: str) -> bytes:
        if path_uses_symlink(self.control_root, relative):
            raise ValueError(f"trusted {label} path must not contain symlinks")
        disk_path = self.control_root / relative
        try:
            disk_mode = os.lstat(disk_path).st_mode
        except OSError as error:
            raise ValueError(f"trusted {label} cannot be inspected: {error}") from error
        if not stat.S_ISREG(disk_mode):
            raise ValueError(f"trusted {label} must be a regular file")
        if os.lstat(disk_path).st_nlink != 1:
            raise ValueError(f"trusted {label} must not have multiple hard links")

        entry = run_git_bytes(
            self.control_root,
            "ls-tree",
            "-z",
            self.control_commit,
            "--",
            relative,
        )
        records = [record for record in entry.split(b"\0") if record]
        if len(records) != 1:
            raise ValueError(f"trusted {label} must exist exactly once at control commit")
        try:
            metadata, observed_path = records[0].split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
        except ValueError as error:
            raise ValueError(f"trusted {label} has malformed Git tree metadata") from error
        try:
            tree_path = observed_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError(f"trusted {label} Git tree path is not UTF-8") from error
        if tree_path != relative:
            raise ValueError(f"trusted {label} Git tree path does not match")
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError(f"trusted {label} must be a regular blob")

        snapshot = run_git_bytes(
            self.control_root,
            "cat-file",
            "blob",
            object_id.decode("ascii"),
        )
        try:
            disk_bytes = disk_path.read_bytes()
        except OSError as error:
            raise ValueError(f"trusted {label} cannot be read: {error}") from error
        if disk_bytes != snapshot:
            raise ValueError(
                f"trusted {label} disk bytes do not match control commit"
            )
        self.file_evidence[label] = {
            "path": relative,
            "blobOid": object_id.decode("ascii"),
            "sha256": "sha256:" + hashlib.sha256(snapshot).hexdigest(),
        }
        return snapshot

    def _verify_control(self) -> None:
        if (
            not isinstance(self.control_commit, str)
            or COMMIT_PATTERN.fullmatch(self.control_commit) is None
        ):
            raise ValueError("control commit must be a full lowercase SHA-1")
        if absolute_path_uses_symlink(self.control_root):
            raise ValueError("control root path must not contain symlinks")
        _, self.control_git_dir, self.control_common_dir = self._verify_checkout(
            self.control_root,
            "control root",
        )
        if self.control_git_dir != self.control_common_dir:
            raise ValueError("control root must not be a linked Git worktree")
        control_origin = self._git(
            self.control_root,
            "remote",
            "get-url",
            "origin",
        )
        try:
            control_identity = normalize_origin(control_origin)
        except ValueError as error:
            raise ValueError(f"cannot verify repository origin: {error}") from error
        if control_identity != self.expected_origin_identity:
            raise ValueError(
                "control origin must match the expected repository"
            )
        self.origin_identity = control_identity

        object_type = self._git(
            self.control_root,
            "cat-file",
            "-t",
            self.control_commit,
        )
        if object_type != "commit":
            raise ValueError("control commit must name a commit object")
        control_head = self._git(self.control_root, "rev-parse", "HEAD")
        if control_head != self.control_commit:
            raise ValueError("control checkout HEAD must equal control commit")
        origin_main = self._git(
            self.control_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            "refs/remotes/origin/main^{commit}",
        )
        ancestry = run_git_process(
            self.control_root,
            "merge-base",
            "--is-ancestor",
            self.control_commit,
            origin_main,
            text=True,
        )
        if ancestry.returncode == 1:
            raise ValueError("control commit must be reachable from origin/main")
        if ancestry.returncode != 0:
            message = ancestry.stderr.strip() or ancestry.stdout.strip()
            raise ValueError(f"cannot verify control commit reachability: {message}")

        for label, relative in TRUSTED_CONTROL_PATHS.items():
            self.snapshots[label] = self._verify_blob(relative, label)

    def verify_executing_checker(self, executing_path: Path) -> None:
        if absolute_path_uses_symlink(executing_path):
            raise ValueError("executing checker path must not contain symlinks")
        expected = lexical_absolute(
            self.control_root / TRUSTED_CONTROL_PATHS["checker"]
        )
        observed = lexical_absolute(executing_path)
        if observed != expected:
            raise ValueError(
                "executing checker must use the trusted-control path"
            )
        try:
            same_file = observed.samefile(expected)
        except OSError as error:
            raise ValueError(f"cannot verify executing checker: {error}") from error
        if not same_file:
            raise ValueError(
                "executing checker must be the verified trusted-control checker"
            )
        self.executing_checker_path_matched = True

    def verify_candidate_checkout(self) -> None:
        if not self.executing_checker_path_matched:
            raise ValueError(
                "executing checker must be verified before candidate checkout"
            )
        if absolute_path_uses_symlink(self.candidate_root):
            raise ValueError("candidate root path must not contain symlinks")
        if self.candidate_root.resolve() == self.control_root.resolve():
            raise ValueError("control root must be an independent checkout")
        _, candidate_git_dir, candidate_common_dir = self._verify_checkout(
            self.candidate_root,
            "candidate root",
        )
        if candidate_git_dir == self.control_git_dir:
            raise ValueError("control root must use an independent Git checkout")
        if candidate_common_dir == self.control_common_dir:
            raise ValueError(
                "control root must not share a Git common directory"
            )
        candidate_origin = self._git(
            self.candidate_root,
            "remote",
            "get-url",
            "origin",
        )
        try:
            candidate_identity = normalize_origin(candidate_origin)
        except ValueError as error:
            raise ValueError(f"cannot verify repository origin: {error}") from error
        if candidate_identity != self.expected_origin_identity:
            raise ValueError(
                "candidate origin must match the expected repository"
            )
        self.candidate_checkout_verified = True

    def load_validator(self):
        if not (
            self.executing_checker_path_matched
            and self.candidate_checkout_verified
        ):
            raise ValueError(
                "trusted control must verify checker and candidate before loading validator"
            )
        source = self.snapshots["validator"]
        module = types.ModuleType("_trusted_release_authorization_catalog_validator")
        module.__file__ = (
            f"{self.control_commit}:{TRUSTED_CONTROL_PATHS['validator']}"
        )
        previous = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            code = compile(source, module.__file__, "exec")
            exec(code, module.__dict__)
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, GeneratorExit)):
                raise
            raise ValueError(f"trusted validator cannot be loaded: {error}") from error
        finally:
            sys.dont_write_bytecode = previous
        return module

    def evidence(self) -> dict[str, Any]:
        if not (
            self.executing_checker_path_matched
            and self.candidate_checkout_verified
        ):
            raise ValueError(
                "trusted control evidence requires completed verification"
            )
        return {
            "repository": self.origin_identity,
            "commit": self.control_commit,
            "files": dict(self.file_evidence),
            "independentCheckout": self.candidate_checkout_verified,
            "executingCheckerPathMatched": self.executing_checker_path_matched,
        }


def evaluate(
    repo_root: Path,
    authorization_path: Path,
    policy_path: Path,
    changed_paths: list[str],
    base_catalog: dict[str, Any],
    base_policy: dict[str, Any],
    base_versions: dict[str, str | None],
    base_commit: str,
    candidate_commit: str,
    mode: str,
    now: datetime,
    catalog_validator: Any | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    errors = []
    blockers = []
    try:
        expected_authorization_path = (
            repo_root / DEFAULT_AUTHORIZATION_PATH
        )
        expected_policy_path = repo_root / "metrics" / "observation-policy.json"
        catalog_path = repo_root / CATALOG_PATH
        if authorization_path.resolve() != expected_authorization_path.resolve():
            raise ValueError(
                f"authorization path must equal {DEFAULT_AUTHORIZATION_PATH}"
            )
        if policy_path.resolve() != expected_policy_path.resolve():
            raise ValueError(
                "policy path must equal metrics/observation-policy.json"
            )
        for relative, path, label in (
            (
                DEFAULT_AUTHORIZATION_PATH,
                expected_authorization_path,
                "release authorization",
            ),
            (
                "metrics/observation-policy.json",
                expected_policy_path,
                "observation policy",
            ),
            (CATALOG_PATH, catalog_path, "skill catalog"),
        ):
            if path_uses_symlink(repo_root, relative) or path.is_symlink():
                raise ValueError(f"{label} path must not contain symlinks")
        authorization = load_json_object(
            expected_authorization_path,
            "release authorization",
        )
        policy = load_json_object(expected_policy_path, "observation policy")
        current_catalog = load_json_object(catalog_path, "skill catalog")
        not_before = parse_time(policy.get("notBefore"), "policy notBefore")
        normalized_paths, path_errors = normalize_changed_paths(changed_paths)
        errors.extend(path_errors)
        auth_relative = DEFAULT_AUTHORIZATION_PATH
    except (KeyError, OSError, TypeError, ValueError) as error:
        return invalid_result(mode, now, error)

    if now.tzinfo is None:
        return invalid_result(mode, now.replace(tzinfo=timezone.utc), ValueError(
            "current time must include a timezone"
        ))
    now = now.astimezone(timezone.utc)

    if mode not in ALLOWED_MODES:
        errors.append("mode must be dry-run or publish")
    if type(policy.get("schemaVersion")) is not int or policy.get("schemaVersion") != 1:
        errors.append("observation policy schemaVersion must equal 1")
    if policy != base_policy:
        errors.append("observation policy must not change in a release commit range")
    if "metrics/observation-policy.json" in normalized_paths:
        errors.append("observation policy cannot change with a Skill release")
    reason = policy.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("observation policy reason must be non-empty")
    if set(authorization) != TOP_LEVEL_FIELDS:
        errors.append("release authorization fields are incomplete or unexpected")
    if (
        type(authorization.get("schemaVersion")) is not int
        or authorization.get("schemaVersion") != 1
    ):
        errors.append("release authorization schemaVersion must equal 1")
    authorization_status = authorization.get("status")
    if authorization_status not in {"pending", "approved"}:
        errors.append("release authorization status must be pending or approved")
    if authorization_status != "approved":
        blockers.append("authorization-not-approved")

    release_id = authorization.get("releaseId")
    if (
        not isinstance(release_id, str)
        or len(release_id) > 128
        or RELEASE_ID_PATTERN.fullmatch(release_id) is None
    ):
        errors.append("releaseId must be a lowercase token using dots or hyphens")

    try:
        authorization_not_before = parse_time(
            authorization.get("observationNotBefore"),
            "observationNotBefore",
        )
    except ValueError as error:
        errors.append(str(error))
        authorization_not_before = None
    issued_at = expires_at = None
    if authorization_status == "approved":
        try:
            issued_at = parse_time(authorization.get("issuedAt"), "issuedAt")
            expires_at = parse_time(authorization.get("expiresAt"), "expiresAt")
        except ValueError as error:
            errors.append(str(error))
    elif (
        authorization.get("issuedAt") is not None
        or authorization.get("expiresAt") is not None
    ):
        errors.append("pending authorization times must remain null")
    if authorization_not_before is not None and authorization_not_before != not_before:
        errors.append("authorization observationNotBefore must match policy")
    if issued_at is not None and issued_at < not_before:
        errors.append("authorization cannot be issued before observation window")
    if issued_at is not None and expires_at is not None:
        if expires_at <= issued_at:
            errors.append("expiresAt must be later than issuedAt")
        elif expires_at - issued_at > MAX_AUTHORIZATION_LIFETIME:
            errors.append("authorization lifetime cannot exceed 72 hours")
        if now < issued_at:
            blockers.append("authorization-not-yet-active")
        if now >= expires_at:
            blockers.append("authorization-expired")
    if now < not_before:
        blockers.append("observation-window")

    if not isinstance(base_commit, str) or COMMIT_PATTERN.fullmatch(base_commit) is None:
        errors.append("evaluated base commit must be a full lowercase SHA-1")
    if authorization.get("baseCommit") != base_commit:
        errors.append("authorization baseCommit does not match evaluated base")
    if (
        not isinstance(candidate_commit, str)
        or COMMIT_PATTERN.fullmatch(candidate_commit) is None
    ):
        errors.append("evaluated candidate commit must be a full lowercase SHA-1")
    if authorization.get("candidateCommit") != candidate_commit:
        errors.append(
            "authorization candidateCommit does not match evaluated candidate"
        )

    modes = authorization.get("modes")
    if not exact_string_list(modes, ALLOWED_MODES):
        errors.append("modes must be a unique non-empty subset of dry-run and publish")
        modes = []
    if mode not in modes:
        blockers.append("mode-not-approved")

    if auth_relative not in normalized_paths:
        errors.append("authorization file must change in the evaluated commit range")
    protected_control_changes = []
    for changed_path in sorted(normalized_paths):
        if (
            changed_path in PROTECTED_CONTROL_PATHS
            or changed_path.startswith(".github/workflows/")
        ):
            message = (
                f"release commit cannot modify protected control path: {changed_path}"
            )
            errors.append(message)
            protected_control_changes.append(message)
    target_slugs, catalog_changed, formal_errors = formal_changed_slugs(
        normalized_paths,
        base_catalog,
        current_catalog,
    )
    errors.extend(formal_errors)
    if not target_slugs:
        errors.append("evaluated commit range has no formal Skill changes")
    if len(target_slugs) != 1:
        errors.append("each release authorization must target exactly one Skill")
    if authorization.get("catalogChanged") is not catalog_changed:
        errors.append("catalogChanged does not match the evaluated commit range")

    targets = authorization.get("targets")
    authorized_versions = {}
    if not isinstance(targets, list) or not targets:
        errors.append("targets must be a non-empty array")
    else:
        for target in targets:
            if not isinstance(target, dict) or set(target) != TARGET_FIELDS:
                errors.append("every target must contain only slug and version")
                continue
            slug = target.get("slug")
            version = target.get("version")
            if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
                errors.append("target slug must use lowercase kebab-case")
                continue
            if (
                not isinstance(version, str)
                or SEMVER_PATTERN.fullmatch(version) is None
            ):
                errors.append(f"{slug}: target version must use three-part semver")
                continue
            if slug in authorized_versions:
                errors.append(f"{slug}: target is duplicated")
                continue
            authorized_versions[slug] = version
    if set(authorized_versions) != target_slugs:
        errors.append("authorized target set does not match formal changed targets")

    for slug, version in authorized_versions.items():
        try:
            frontmatter = parse_frontmatter(
                repo_root / "skills" / slug / "SKILL.md"
            )
        except ValueError as error:
            errors.append(f"{slug}: {error}")
            continue
        if frontmatter.get("slug") != slug:
            errors.append(f"{slug}: formal SKILL.md slug does not match authorization")
        if frontmatter.get("version") != version:
            errors.append(f"{slug}: formal SKILL.md version does not match authorization")
        base_version = base_versions.get(slug)
        is_new = f"skills/{slug}" not in base_catalog
        if is_new:
            if base_version is not None:
                errors.append(f"{slug}: new Skill must not have a base version")
        elif (
            not isinstance(base_version, str)
            or SEMVER_PATTERN.fullmatch(base_version) is None
        ):
            errors.append(f"{slug}: existing Skill base version is invalid")
        elif semver_tuple(version) <= semver_tuple(base_version):
            errors.append(f"{slug}: release version must increase from base version")
        if not any(
            path.startswith(f"skills/{slug}/")
            for path in normalized_paths
        ):
            errors.append(f"{slug}: release must change the formal Skill directory")
        expected_release_id = f"{slug}-{version}"
        if release_id != expected_release_id:
            errors.append(
                f"releaseId must equal target slug and version: {expected_release_id}"
            )

    if not protected_control_changes:
        errors.extend(
            validate_catalog(
                repo_root,
                catalog_path,
                validator=catalog_validator,
            )
        )
    try:
        observed_digest = compute_content_digest(
            repo_root,
            current_catalog,
            target_slugs,
        )
    except (OSError, TypeError, ValueError) as error:
        errors.append(str(error))
        observed_digest = None
    expected_digest = authorization.get("contentDigest")
    if (
        not isinstance(expected_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None
    ):
        errors.append("contentDigest must be a lowercase sha256 digest")
    elif observed_digest is not None and expected_digest != observed_digest:
        errors.append("contentDigest does not match authorized Skill content")
    try:
        observed_change_set_digest = compute_change_set_digest(
            repo_root,
            normalized_paths,
            auth_relative,
        )
    except (OSError, TypeError, ValueError) as error:
        errors.append(str(error))
        observed_change_set_digest = None
    expected_change_set_digest = authorization.get("changeSetDigest")
    if (
        not isinstance(expected_change_set_digest, str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            expected_change_set_digest,
        )
        is None
    ):
        errors.append("changeSetDigest must be a lowercase sha256 digest")
    elif (
        observed_change_set_digest is not None
        and expected_change_set_digest != observed_change_set_digest
    ):
        errors.append("changeSetDigest does not match the complete release diff")

    review = authorization.get("review")
    if not isinstance(review, dict) or set(review) != REVIEW_FIELDS:
        errors.append("review fields are incomplete or unexpected")
        review = {}
    review_completed = review.get("completed")
    if review_completed is not True:
        blockers.append("fresh-review")
    if authorization_status == "pending" and review_completed is not False:
        errors.append("pending review.completed must remain false")
    change_class = review.get("changeClass")
    if change_class not in ALLOWED_CHANGE_CLASSES:
        errors.append("review changeClass is invalid")
    if len(target_slugs) == 1:
        target_slug = next(iter(target_slugs))
        target_is_new = f"skills/{target_slug}" not in base_catalog
        if target_is_new and change_class != "new-skill":
            errors.append("new Skill must use changeClass new-skill")
        if not target_is_new and change_class == "new-skill":
            errors.append("existing Skill cannot use changeClass new-skill")
        if target_is_new and not catalog_changed:
            errors.append("new-skill authorization must include a catalog change")
    review_reason = review.get("reason")
    if not isinstance(review_reason, str) or not review_reason.strip():
        errors.append("review reason must be non-empty")
    reviewed_at = None
    if authorization_status == "approved":
        try:
            reviewed_at = parse_time(review.get("reviewedAt"), "reviewedAt")
        except ValueError as error:
            errors.append(str(error))
    elif review.get("reviewedAt") is not None:
        errors.append("pending review.reviewedAt must remain null")
    if reviewed_at is not None:
        if reviewed_at < not_before:
            errors.append("fresh review cannot predate observation window")
        if issued_at is not None and reviewed_at > issued_at:
            errors.append("fresh review cannot occur after authorization issuance")
        if (
            issued_at is not None
            and issued_at - reviewed_at > MAX_REVIEW_AGE
        ):
            errors.append("fresh review cannot be more than 72 hours old")
        if now - reviewed_at > MAX_REVIEW_AGE:
            errors.append("fresh review is older than 72 hours at evaluation time")

    evidence = review.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("review evidence must be a non-empty array")
    else:
        observed_evidence_paths = set()
        for index, item in enumerate(evidence):
            if not isinstance(item, dict) or set(item) != EVIDENCE_FIELDS:
                errors.append(
                    "every review evidence item must contain only path and sha256"
                )
                continue
            evidence_relative = item.get("path")
            expected_evidence_digest = item.get("sha256")
            if (
                not isinstance(evidence_relative, str)
                or not evidence_relative
                or evidence_relative in observed_evidence_paths
            ):
                errors.append("review evidence paths must be unique non-empty strings")
                continue
            observed_evidence_paths.add(evidence_relative)
            if evidence_relative not in normalized_paths:
                errors.append(
                    f"review evidence must change in the release diff: {evidence_relative}"
                )
            try:
                evidence_path = resolve_inside(
                    repo_root,
                    evidence_relative,
                    f"review evidence[{index}].path",
                )
            except ValueError as error:
                errors.append(str(error))
                continue
            if not evidence_path.is_file():
                errors.append(
                    f"review evidence file is missing: {evidence_relative}"
                )
                continue
            if path_uses_symlink(repo_root, evidence_relative):
                errors.append(
                    f"review evidence path contains a symlink: {evidence_relative}"
                )
                continue
            if evidence_path.resolve() == expected_authorization_path.resolve():
                errors.append("authorization file cannot be its own review evidence")
                continue
            if (
                not isinstance(expected_evidence_digest, str)
                or re.fullmatch(
                    r"sha256:[0-9a-f]{64}",
                    expected_evidence_digest,
                )
                is None
            ):
                errors.append(
                    f"review evidence digest is invalid: {evidence_relative}"
                )
                continue
            try:
                observed_evidence_digest = file_sha256(evidence_path)
            except ValueError as error:
                errors.append(str(error))
                continue
            if observed_evidence_digest != expected_evidence_digest:
                errors.append(
                    f"review evidence digest does not match: {evidence_relative}"
                )

    blockers = list(dict.fromkeys(blockers))
    valid = not errors
    authorized = valid and not blockers
    return {
        "valid": valid,
        "authorized": authorized,
        "mode": mode,
        "evaluatedAt": now.isoformat(),
        "releaseId": release_id,
        "baseCommit": base_commit,
        "targets": [
            {"slug": slug, "version": authorized_versions[slug]}
            for slug in sorted(authorized_versions)
        ],
        "catalogChanged": catalog_changed,
        "contentDigest": observed_digest,
        "changeSetDigest": observed_change_set_digest,
        "authorizationChanged": auth_relative in normalized_paths,
        "blockingReasons": blockers,
        "errors": errors,
    }


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


def run_git_process(
    repo_root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        git_command(*args),
        cwd=repo_root,
        env=git_environment(),
        check=False,
        capture_output=True,
        text=text,
    )


def run_git(repo_root: Path, *args: str) -> str:
    completed = run_git_process(repo_root, *args, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def run_git_bytes(repo_root: Path, *args: str) -> bytes:
    completed = run_git_process(repo_root, *args)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        if not message:
            message = completed.stdout.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def git_blob_oid(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def worktree_entries(repo_root: Path) -> dict[str, tuple[int, bytes]]:
    entries: dict[str, tuple[int, bytes]] = {}

    def fail_on_walk_error(error: OSError) -> None:
        raise ValueError(
            f"candidate working tree cannot be scanned: {error}"
        ) from error

    for current_root, directory_names, file_names in os.walk(
        repo_root,
        topdown=True,
        onerror=fail_on_walk_error,
        followlinks=False,
    ):
        current = Path(current_root)
        if current == repo_root:
            directory_names[:] = [
                name for name in directory_names if name != ".git"
            ]
            file_names = [name for name in file_names if name != ".git"]
        symlink_directories = []
        for name in directory_names:
            path = current / name
            if path.is_symlink():
                symlink_directories.append(name)
        directory_names[:] = [
            name for name in directory_names if name not in symlink_directories
        ]
        for name in [*file_names, *symlink_directories]:
            path = current / name
            relative = path.relative_to(repo_root).as_posix()
            try:
                metadata = os.lstat(path)
                if stat.S_ISLNK(metadata.st_mode):
                    payload = os.fsencode(os.readlink(path))
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_nlink != 1:
                        raise ValueError(
                            f"candidate file must not have multiple hard links: {relative}"
                        )
                    payload = path.read_bytes()
                else:
                    raise ValueError(
                        f"candidate path is not a regular file or symlink: {relative}"
                    )
            except OSError as error:
                raise ValueError(
                    f"candidate path cannot be inspected: {relative}: {error}"
                ) from error
            entries[relative] = (metadata.st_mode, payload)
    return entries


def verify_worktree_matches_commit(repo_root: Path, commit: str) -> None:
    tree_output = run_git_bytes(
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        commit,
        "--",
    )
    tree: dict[str, tuple[str, str]] = {}
    for record in (item for item in tree_output.split(b"\0") if item):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
            relative = raw_path.decode("utf-8", errors="strict")
            mode_text = mode.decode("ascii")
            object_id_text = object_id.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("checked-out Git tree has malformed metadata") from error
        if (
            object_type != b"blob"
            or mode_text not in {"100644", "100755", "120000"}
        ):
            raise ValueError(
                f"checked-out Git tree contains unsupported entry: {relative}"
            )
        tree[relative] = (mode_text, object_id_text)

    disk = worktree_entries(repo_root)
    missing = sorted(set(tree) - set(disk))
    extra = sorted(set(disk) - set(tree))
    if missing:
        raise ValueError(
            "working tree is missing committed paths: " + ", ".join(missing)
        )
    if extra:
        raise ValueError(
            "working tree contains uncommitted paths: " + ", ".join(extra)
        )

    for relative, (expected_mode, expected_oid) in tree.items():
        observed_mode, payload = disk[relative]
        if expected_mode == "120000":
            if not stat.S_ISLNK(observed_mode):
                raise ValueError(
                    f"working tree type does not match HEAD: {relative}"
                )
        else:
            if not stat.S_ISREG(observed_mode):
                raise ValueError(
                    f"working tree type does not match HEAD: {relative}"
                )
            expected_executable = expected_mode == "100755"
            observed_executable = bool(observed_mode & 0o111)
            if observed_executable != expected_executable:
                raise ValueError(
                    f"working tree executable mode does not match HEAD: {relative}"
                )
        if git_blob_oid(payload) != expected_oid:
            raise ValueError(
                f"working tree bytes do not match HEAD: {relative}"
            )


def collect_git_inputs(
    repo_root: Path,
    base_ref: str,
    head_ref: str,
    candidate_ref: str | None = None,
) -> tuple[str, list[str], dict[str, Any], dict[str, Any]]:
    base_commit = run_git(
        repo_root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base_ref}^{{commit}}",
    ).strip()
    head_commit = run_git(
        repo_root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{head_ref}^{{commit}}",
    ).strip()
    checked_out = run_git(repo_root, "rev-parse", "HEAD").strip()
    if head_commit != checked_out:
        raise ValueError("evaluated head must equal the checked-out HEAD")
    release_head = head_commit
    if candidate_ref is not None:
        candidate_commit = run_git(
            repo_root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{candidate_ref}^{{commit}}",
        ).strip()
        candidate_ancestor = run_git_process(
            repo_root,
            "merge-base",
            "--is-ancestor",
            candidate_commit,
            head_commit,
            text=True,
        )
        if candidate_ancestor.returncode == 1:
            raise ValueError("candidate commit must be an ancestor of head")
        if candidate_ancestor.returncode != 0:
            message = (
                candidate_ancestor.stderr.strip()
                or candidate_ancestor.stdout.strip()
            )
            raise ValueError(f"cannot verify candidate ancestry: {message}")
        authorization_commits = run_git(
            repo_root,
            "rev-list",
            "--count",
            f"{candidate_commit}..{head_commit}",
        ).strip()
        if authorization_commits != "1":
            raise ValueError(
                "head must contain exactly one authorization commit after candidate"
            )
        authorization_changes = run_git_bytes(
            repo_root,
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMRTD",
            candidate_commit,
            head_commit,
            "--",
        )
        try:
            authorization_paths = {
                item.decode("utf-8")
                for item in authorization_changes.split(b"\0")
                if item
            }
        except UnicodeDecodeError as error:
            raise ValueError(
                "authorization commit paths must be valid UTF-8"
            ) from error
        if authorization_paths != {DEFAULT_AUTHORIZATION_PATH}:
            raise ValueError(
                "authorization commit must change only the authorization file"
            )
        release_head = candidate_commit
    ancestor = run_git_process(
        repo_root,
        "merge-base",
        "--is-ancestor",
        base_commit,
        release_head,
        text=True,
    )
    if ancestor.returncode == 1:
        raise ValueError("evaluated base must be an ancestor of head")
    if ancestor.returncode != 0:
        message = ancestor.stderr.strip() or ancestor.stdout.strip()
        raise ValueError(f"cannot verify base ancestry: {message}")
    verify_worktree_matches_commit(repo_root, head_commit)
    changed_bytes = run_git_bytes(
        repo_root,
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMRTD",
        base_commit,
        release_head,
        "--",
    )
    try:
        changed_paths = [
            item.decode("utf-8")
            for item in changed_bytes.split(b"\0")
            if item
        ]
    except UnicodeDecodeError as error:
        raise ValueError("changed paths must be valid UTF-8") from error
    if candidate_ref is not None:
        changed_paths.append(DEFAULT_AUTHORIZATION_PATH)
    catalog_text = run_git(repo_root, "show", f"{base_commit}:{CATALOG_PATH}")
    base_catalog = parse_json_object_text(catalog_text, "base skill catalog")
    policy_text = run_git(
        repo_root,
        "show",
        f"{base_commit}:metrics/observation-policy.json",
    )
    base_policy = parse_json_object_text(policy_text, "base observation policy")
    return base_commit, changed_paths, base_catalog, base_policy


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument("--base", required=True, help="Base Git ref before this release.")
    parser.add_argument("--head", default="HEAD", help="Checked-out release head.")
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), required=True)
    parser.add_argument(
        "--control-root",
        type=Path,
        required=True,
        help="Independent checkout containing the trusted control plane.",
    )
    parser.add_argument(
        "--control-commit",
        required=True,
        help="Full trusted control-plane commit checked out at control-root.",
    )
    args = parser.parse_args(argv)

    repo_root = lexical_absolute(args.repo_root)
    now = datetime.now(timezone.utc)
    try:
        trusted_control = TrustedControl(
            repo_root,
            args.control_root,
            args.control_commit,
            EXPECTED_CONTROL_ORIGIN,
        )
        trusted_control.verify_executing_checker(Path(__file__))
        trusted_control.verify_candidate_checkout()
        catalog_validator = trusted_control.load_validator()
    except (OSError, TypeError, ValueError) as error:
        result = trusted_control_invalid_result(args.mode, now, error)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        authorization_path = repo_root / DEFAULT_AUTHORIZATION_PATH
        policy_path = repo_root / "metrics" / "observation-policy.json"
        authorization_preview = load_json_object(
            authorization_path,
            "release authorization",
        )
        candidate_commit = authorization_preview.get("candidateCommit")
        if (
            not isinstance(candidate_commit, str)
            or COMMIT_PATTERN.fullmatch(candidate_commit) is None
        ):
            raise ValueError(
                "release authorization candidateCommit must be a full SHA-1"
            )
        base_commit, changed_paths, base_catalog, base_policy = collect_git_inputs(
            repo_root,
            args.base,
            args.head,
            candidate_commit,
        )
        preview_targets = authorization_preview.get("targets")
        if not isinstance(preview_targets, list):
            raise ValueError("release authorization targets must be an array")
        preview_slugs = {
            target.get("slug")
            for target in preview_targets
            if isinstance(target, dict) and isinstance(target.get("slug"), str)
        }
        base_versions = load_base_versions(
            repo_root,
            base_commit,
            base_catalog,
            preview_slugs,
        )
        result = evaluate(
            repo_root,
            authorization_path.resolve(),
            policy_path.resolve(),
            changed_paths,
            base_catalog,
            base_policy,
            base_versions,
            base_commit,
            candidate_commit,
            args.mode,
            now,
            catalog_validator,
        )
        result["candidateCommit"] = candidate_commit
        result["headCommit"] = run_git(repo_root, "rev-parse", "HEAD").strip()
        result["trustedControl"] = trusted_control.evidence()
    except (OSError, TypeError, ValueError) as error:
        result = invalid_result(args.mode, now, error)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    if not result["authorized"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

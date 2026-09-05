#!/usr/bin/env python3
"""Fail-closed offline authorization check for formal Skill releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
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
    spec.loader.exec_module(module)
    return module


def validate_catalog(repo_root: Path, catalog_path: Path) -> list[str]:
    try:
        validator = load_catalog_validator(repo_root)
        result = validator.validate(repo_root, catalog_path)
    except (OSError, TypeError, ValueError) as error:
        return [f"catalog preflight cannot run: {error}"]
    if not isinstance(result, dict) or not isinstance(result.get("valid"), bool):
        return ["catalog preflight returned an invalid result"]
    if result["valid"]:
        return []
    messages = []
    for item in result.get("errors", []):
        if isinstance(item, dict):
            code = item.get("code", "UNKNOWN")
            path = item.get("path", "$")
            message = item.get("message", "catalog validation failed")
            messages.append(f"catalog preflight {code} at {path}: {message}")
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


def evaluate(
    repo_root: Path,
    authorization_path: Path,
    policy_path: Path,
    changed_paths: list[str],
    base_catalog: dict[str, Any],
    base_policy: dict[str, Any],
    base_commit: str,
    mode: str,
    now: datetime,
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
    if authorization.get("status") != "approved":
        blockers.append("authorization-not-approved")

    release_id = authorization.get("releaseId")
    if (
        not isinstance(release_id, str)
        or len(release_id) > 128
        or RELEASE_ID_PATTERN.fullmatch(release_id) is None
    ):
        errors.append("releaseId must be a lowercase token using dots or hyphens")

    try:
        issued_at = parse_time(authorization.get("issuedAt"), "issuedAt")
        expires_at = parse_time(authorization.get("expiresAt"), "expiresAt")
        authorization_not_before = parse_time(
            authorization.get("observationNotBefore"),
            "observationNotBefore",
        )
    except ValueError as error:
        errors.append(str(error))
        issued_at = expires_at = authorization_not_before = None
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

    modes = authorization.get("modes")
    if not exact_string_list(modes, ALLOWED_MODES):
        errors.append("modes must be a unique non-empty subset of dry-run and publish")
        modes = []
    if mode not in modes:
        blockers.append("mode-not-approved")

    if auth_relative not in normalized_paths:
        errors.append("authorization file must change in the evaluated commit range")
    for changed_path in sorted(normalized_paths):
        if (
            changed_path in PROTECTED_CONTROL_PATHS
            or changed_path.startswith(".github/workflows/")
        ):
            errors.append(
                f"release commit cannot modify protected control path: {changed_path}"
            )
    target_slugs, catalog_changed, formal_errors = formal_changed_slugs(
        normalized_paths,
        base_catalog,
        current_catalog,
    )
    errors.extend(formal_errors)
    if not target_slugs:
        errors.append("evaluated commit range has no formal Skill changes")
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

    errors.extend(validate_catalog(repo_root, catalog_path))
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
    if review.get("completed") is not True:
        blockers.append("fresh-review")
    change_class = review.get("changeClass")
    if change_class not in ALLOWED_CHANGE_CLASSES:
        errors.append("review changeClass is invalid")
    if change_class == "new-skill" and not catalog_changed:
        errors.append("new-skill authorization must include a catalog change")
    review_reason = review.get("reason")
    if not isinstance(review_reason, str) or not review_reason.strip():
        errors.append("review reason must be non-empty")
    try:
        reviewed_at = parse_time(review.get("reviewedAt"), "reviewedAt")
    except ValueError as error:
        errors.append(str(error))
        reviewed_at = None
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


def run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def run_git_bytes(repo_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        if not message:
            message = completed.stdout.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def collect_git_inputs(
    repo_root: Path,
    base_ref: str,
    head_ref: str,
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
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, head_commit],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode == 1:
        raise ValueError("evaluated base must be an ancestor of head")
    if ancestor.returncode != 0:
        message = ancestor.stderr.strip() or ancestor.stdout.strip()
        raise ValueError(f"cannot verify base ancestry: {message}")
    if run_git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
    ):
        raise ValueError("release authorization requires a clean working tree")
    changed_bytes = run_git_bytes(
        repo_root,
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMRTD",
        base_commit,
        head_commit,
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
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    now = datetime.now(timezone.utc)
    try:
        authorization_path = repo_root / DEFAULT_AUTHORIZATION_PATH
        policy_path = repo_root / "metrics" / "observation-policy.json"
        base_commit, changed_paths, base_catalog, base_policy = collect_git_inputs(
            repo_root,
            args.base,
            args.head,
        )
        result = evaluate(
            repo_root,
            authorization_path.resolve(),
            policy_path.resolve(),
            changed_paths,
            base_catalog,
            base_policy,
            base_commit,
            args.mode,
            now,
        )
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

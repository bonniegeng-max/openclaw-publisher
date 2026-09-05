#!/usr/bin/env python3
"""Prepare a pending Skill release authorization draft from a Git diff."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def load_gate_module():
    path = Path(__file__).with_name("check_skill_release_authorization.py")
    spec = importlib.util.spec_from_file_location(
        "_skill_release_authorization_gate",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("release authorization gate cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


GATE = load_gate_module()


def write_json_atomic(path: Path, value: dict[str, Any], force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        if force:
            os.replace(temporary, path)
            temporary = None
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise ValueError(
                    f"{GATE.DEFAULT_AUTHORIZATION_PATH} already exists; "
                    "use --force to replace it"
                ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare(
    repo_root: Path,
    base_ref: str,
    head_ref: str,
    release_id: str,
    modes: list[str],
    change_class: str,
    reason: str,
    evidence_paths: list[str],
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if (
        not isinstance(release_id, str)
        or len(release_id) > 128
        or GATE.RELEASE_ID_PATTERN.fullmatch(release_id) is None
    ):
        raise ValueError("releaseId must be a lowercase token using dots or hyphens")
    if not GATE.exact_string_list(modes, GATE.ALLOWED_MODES):
        raise ValueError(
            "modes must be a unique non-empty subset of dry-run and publish"
        )
    if change_class not in GATE.ALLOWED_CHANGE_CLASSES:
        raise ValueError("changeClass is invalid")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be non-empty")
    if not GATE.exact_string_list(evidence_paths):
        raise ValueError("evidence paths must be unique non-empty strings")

    base_commit, changed_paths, base_catalog, base_policy = (
        GATE.collect_git_inputs(repo_root, base_ref, head_ref)
    )
    candidate_commit = GATE.run_git(repo_root, "rev-parse", "HEAD").strip()
    policy_path = repo_root / "metrics" / "observation-policy.json"
    catalog_path = repo_root / GATE.CATALOG_PATH
    for relative, path, label in (
        (
            "metrics/observation-policy.json",
            policy_path,
            "observation policy",
        ),
        (GATE.CATALOG_PATH, catalog_path, "skill catalog"),
    ):
        if GATE.path_uses_symlink(repo_root, relative) or path.is_symlink():
            raise ValueError(f"{label} path must not contain symlinks")
    policy = GATE.load_json_object(policy_path, "observation policy")
    catalog = GATE.load_json_object(catalog_path, "skill catalog")
    if policy != base_policy:
        raise ValueError("observation policy must not change in a release commit range")
    if (
        type(policy.get("schemaVersion")) is not int
        or policy.get("schemaVersion") != 1
    ):
        raise ValueError("observation policy schemaVersion must equal 1")
    GATE.parse_time(policy.get("notBefore"), "policy notBefore")
    policy_reason = policy.get("reason")
    if not isinstance(policy_reason, str) or not policy_reason.strip():
        raise ValueError("observation policy reason must be non-empty")

    changed_set = set(changed_paths)
    for changed_path in sorted(changed_set):
        if (
            changed_path in GATE.PROTECTED_CONTROL_PATHS
            or changed_path.startswith(".github/workflows/")
        ):
            raise ValueError(
                f"release commit cannot modify protected control path: {changed_path}"
            )
    target_slugs, catalog_changed, formal_errors = GATE.formal_changed_slugs(
        changed_set,
        base_catalog,
        catalog,
    )
    if formal_errors:
        raise ValueError("; ".join(formal_errors))
    if not target_slugs:
        raise ValueError("evaluated commit range has no formal Skill changes")
    if len(target_slugs) != 1:
        raise ValueError("each release authorization must target exactly one Skill")

    catalog_errors = GATE.validate_catalog(repo_root, catalog_path)
    if catalog_errors:
        raise ValueError("; ".join(catalog_errors))

    targets = []
    base_versions = GATE.load_base_versions(
        repo_root,
        base_commit,
        base_catalog,
        target_slugs,
    )
    for slug in sorted(target_slugs):
        frontmatter = GATE.parse_frontmatter(
            repo_root / "skills" / slug / "SKILL.md"
        )
        if frontmatter.get("slug") != slug:
            raise ValueError(f"{slug}: formal SKILL.md slug is inconsistent")
        version = frontmatter.get("version")
        if (
            not isinstance(version, str)
            or GATE.SEMVER_PATTERN.fullmatch(version) is None
        ):
            raise ValueError(f"{slug}: formal version must use three-part semver")
        base_version = base_versions.get(slug)
        is_new = f"skills/{slug}" not in base_catalog
        if is_new:
            if change_class != "new-skill":
                raise ValueError("new Skill must use changeClass new-skill")
            if not catalog_changed:
                raise ValueError(
                    "new-skill authorization must include a catalog change"
                )
        else:
            if change_class == "new-skill":
                raise ValueError(
                    "existing Skill cannot use changeClass new-skill"
                )
            if (
                not isinstance(base_version, str)
                or GATE.semver_tuple(version)
                <= GATE.semver_tuple(base_version)
            ):
                raise ValueError(
                    f"{slug}: release version must increase from base version"
                )
        if not any(
            path.startswith(f"skills/{slug}/")
            for path in changed_set
        ):
            raise ValueError(
                f"{slug}: release must change the formal Skill directory"
            )
        targets.append({"slug": slug, "version": version})
    expected_release_id = f"{targets[0]['slug']}-{targets[0]['version']}"
    if release_id != expected_release_id:
        raise ValueError(
            f"releaseId must equal target slug and version: {expected_release_id}"
        )

    evidence = []
    for index, relative in enumerate(evidence_paths):
        if relative == GATE.DEFAULT_AUTHORIZATION_PATH:
            raise ValueError("authorization file cannot be its own review evidence")
        if relative not in changed_set:
            raise ValueError(
                f"review evidence must change in the release diff: {relative}"
            )
        path = GATE.resolve_inside(
            repo_root,
            relative,
            f"evidence[{index}]",
        )
        if GATE.path_uses_symlink(repo_root, relative):
            raise ValueError(f"review evidence path contains a symlink: {relative}")
        if not path.is_file():
            raise ValueError(f"review evidence file is missing: {relative}")
        evidence.append(
            {
                "path": relative,
                "sha256": GATE.file_sha256(path),
            }
        )

    authorization_relative = GATE.DEFAULT_AUTHORIZATION_PATH
    digest_paths = changed_set | {authorization_relative}
    return {
        "schemaVersion": 1,
        "status": "pending",
        "releaseId": release_id,
        "issuedAt": None,
        "expiresAt": None,
        "observationNotBefore": policy["notBefore"],
        "baseCommit": base_commit,
        "candidateCommit": candidate_commit,
        "modes": modes,
        "targets": targets,
        "catalogChanged": catalog_changed,
        "contentDigest": GATE.compute_content_digest(
            repo_root,
            catalog,
            target_slugs,
        ),
        "changeSetDigest": GATE.compute_change_set_digest(
            repo_root,
            digest_paths,
            authorization_relative,
        ),
        "review": {
            "completed": False,
            "reviewedAt": None,
            "changeClass": change_class,
            "reason": reason.strip(),
            "evidence": evidence,
        },
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument("--base", required=True, help="Base Git ref before this release.")
    parser.add_argument("--head", default="HEAD", help="Checked-out release head.")
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--mode",
        action="append",
        required=True,
        choices=sorted(GATE.ALLOWED_MODES),
        dest="modes",
    )
    parser.add_argument(
        "--change-class",
        required=True,
        choices=sorted(GATE.ALLOWED_CHANGE_CLASSES),
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        dest="evidence_paths",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output_path = repo_root / GATE.DEFAULT_AUTHORIZATION_PATH
    try:
        draft = prepare(
            repo_root=repo_root,
            base_ref=args.base,
            head_ref=args.head,
            release_id=args.release_id,
            modes=args.modes,
            change_class=args.change_class,
            reason=args.reason,
            evidence_paths=args.evidence_paths,
        )
        write_json_atomic(output_path, draft, args.force)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "prepared": False,
                    "approved": False,
                    "errors": [str(error)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "prepared": True,
                "approved": False,
                "status": "pending",
                "output": GATE.DEFAULT_AUTHORIZATION_PATH,
                "releaseId": draft["releaseId"],
                "targets": draft["targets"],
                "requiredNextStep": (
                    "Complete an external fresh review, then set status, review "
                    "completion, reviewedAt, issuedAt, and expiresAt."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the local ClawHub Skill catalog without network access."""

import argparse
import json
import re
from pathlib import Path


REQUIRED_SKILL_FILES = {
    "SKILL.md",
    "CHANGELOG.md",
    ".clawhubignore",
}
REQUIRED_ENTRY_FIELDS = {
    "displayName",
    "categories",
    "topics",
}
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "service-account.json",
}
SENSITIVE_SUFFIXES = {
    ".key",
    ".p12",
    ".pem",
    ".pfx",
}
SAFE_ENV_SUFFIXES = {
    ".example",
    ".sample",
    ".template",
}
FORBIDDEN_PACKAGE_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_PACKAGE_FILES = {
    ".DS_Store",
}


def reject_nonstandard_number(value):
    raise ValueError(f"non-standard JSON number: {value}")


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def issue(code, path, message):
    return {
        "code": code,
        "path": path,
        "message": message,
    }


def load_catalog(path):
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_nonstandard_number,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"catalog cannot be read as strict JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("catalog must be a JSON object")
    return value


def parse_frontmatter(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"SKILL.md cannot be read: {error}") from error
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md frontmatter missing")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip()
        if normalized_key in values:
            raise ValueError(
                f"SKILL.md frontmatter has duplicate key: {normalized_key}"
            )
        values[normalized_key] = value.strip()
    return values


def valid_metadata_tokens(value):
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, str)
            and TOKEN_PATTERN.fullmatch(item) is not None
            for item in value
        )
        and len(value) == len(set(value))
    )


def resolve_skill_directory(repo_root, catalog_key):
    match = re.fullmatch(r"skills/([^/]+)", catalog_key)
    if not match:
        return None, None
    slug = match.group(1)
    candidate = repo_root / catalog_key
    try:
        candidate.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None, None
    return candidate, slug


def inspect_package_hygiene(repo_root, skill_dir, catalog_key):
    errors = []
    current = skill_dir
    while current != repo_root:
        if current.is_symlink():
            errors.append(
                issue(
                    "SYMLINK_FORBIDDEN",
                    catalog_key,
                    "published skill source path must not contain symlinks",
                )
            )
            return errors
        current = current.parent
    for path in sorted(skill_dir.rglob("*")):
        relative = path.relative_to(skill_dir).as_posix()
        result_path = f"{catalog_key}/{relative}"
        if path.is_symlink():
            errors.append(
                issue(
                    "SYMLINK_FORBIDDEN",
                    result_path,
                    "published skill source must not contain symlinks",
                )
            )
            continue
        if path.is_dir() and path.name in FORBIDDEN_PACKAGE_DIRECTORIES:
            errors.append(
                issue(
                    "PACKAGE_DIRECTORY_FORBIDDEN",
                    result_path,
                    "published skill source contains a dependency or cache directory",
                )
            )
            continue
        if not path.is_file():
            continue
        if path.name in FORBIDDEN_PACKAGE_FILES:
            errors.append(
                issue(
                    "PACKAGE_FILE_FORBIDDEN",
                    result_path,
                    "published skill source contains an operating-system artifact",
                )
            )
        lower_name = path.name.lower()
        env_suffix = lower_name.removeprefix(".env")
        env_sensitive = (
            lower_name == ".env"
            or (
                lower_name.startswith(".env.")
                and env_suffix not in SAFE_ENV_SUFFIXES
            )
        )
        if (
            lower_name in SENSITIVE_FILENAMES
            or path.suffix.lower() in SENSITIVE_SUFFIXES
            or env_sensitive
        ):
            errors.append(
                issue(
                    "SENSITIVE_FILE_PRESENT",
                    result_path,
                    "published skill source contains a sensitive filename",
                )
            )
    return errors


def validate(repo_root, catalog_path):
    errors = []
    try:
        catalog = load_catalog(catalog_path)
    except ValueError as error:
        return {
            "valid": False,
            "catalog": str(catalog_path),
            "entryCount": 0,
            "errors": [issue("CATALOG_INPUT_INVALID", "$", str(error))],
        }

    catalog_keys = set()
    display_name_paths = {}
    for catalog_key, entry in catalog.items():
        if not isinstance(catalog_key, str):
            errors.append(
                issue(
                    "CATALOG_KEY_INVALID",
                    "$",
                    "every catalog key must be a string",
                )
            )
            continue
        catalog_keys.add(catalog_key)
        skill_dir, slug = resolve_skill_directory(repo_root, catalog_key)
        if skill_dir is None:
            errors.append(
                issue(
                    "CATALOG_KEY_INVALID",
                    catalog_key,
                    "catalog key must equal skills/<lowercase-kebab-slug>",
                )
            )
            continue
        if SLUG_PATTERN.fullmatch(slug) is None:
            errors.append(
                issue(
                    "SLUG_FORMAT_INVALID",
                    catalog_key,
                    "slug must use lowercase kebab-case",
                )
            )
        if slug.startswith("clawhub-") or slug.endswith("-clawhub"):
            errors.append(
                issue(
                    "SLUG_NAMESPACE_PROTECTED",
                    catalog_key,
                    "slug uses a protected ClawHub namespace",
                )
            )
        if not skill_dir.is_dir():
            errors.append(
                issue(
                    "SKILL_DIRECTORY_MISSING",
                    catalog_key,
                    "catalog entry has no matching skill directory",
                )
            )
            continue
        for filename in sorted(REQUIRED_SKILL_FILES):
            if not (skill_dir / filename).is_file():
                errors.append(
                    issue(
                        "REQUIRED_FILE_MISSING",
                        f"{catalog_key}/{filename}",
                        "published skill is missing a required file",
                    )
                )
        errors.extend(
            inspect_package_hygiene(repo_root, skill_dir, catalog_key)
        )

        if not isinstance(entry, dict):
            errors.append(
                issue(
                    "CATALOG_ENTRY_INVALID",
                    catalog_key,
                    "catalog entry must be a JSON object",
                )
            )
            continue
        observed_fields = set(entry)
        if observed_fields != REQUIRED_ENTRY_FIELDS:
            errors.append(
                issue(
                    "CATALOG_FIELDS_INVALID",
                    catalog_key,
                    "catalog entry must contain only displayName, categories, and topics",
                )
            )
        display_name = entry.get("displayName")
        if (
            not isinstance(display_name, str)
            or not display_name.strip()
            or display_name != display_name.strip()
        ):
            errors.append(
                issue(
                    "DISPLAY_NAME_INVALID",
                    f"{catalog_key}.displayName",
                    "displayName must be a trimmed non-empty string",
                )
            )
        else:
            display_name_paths.setdefault(display_name, []).append(
                catalog_key
            )
        for field in ("categories", "topics"):
            if not valid_metadata_tokens(entry.get(field)):
                errors.append(
                    issue(
                        "METADATA_TOKENS_INVALID",
                        f"{catalog_key}.{field}",
                        f"{field} must be a non-empty unique lowercase-kebab string array",
                    )
                )

        skill_path = skill_dir / "SKILL.md"
        if skill_path.is_file():
            try:
                frontmatter = parse_frontmatter(skill_path)
            except ValueError as error:
                errors.append(
                    issue(
                        "SKILL_FRONTMATTER_INVALID",
                        f"{catalog_key}/SKILL.md",
                        str(error),
                    )
                )
            else:
                if frontmatter.get("slug") != slug:
                    errors.append(
                        issue(
                            "SKILL_SLUG_MISMATCH",
                            f"{catalog_key}/SKILL.md",
                            "frontmatter slug does not match the catalog path",
                        )
                    )
                if frontmatter.get("name") != display_name:
                    errors.append(
                        issue(
                            "SKILL_NAME_MISMATCH",
                            f"{catalog_key}/SKILL.md",
                            "frontmatter name does not match catalog displayName",
                        )
                    )
                description = frontmatter.get("description")
                if (
                    not isinstance(description, str)
                    or not description.strip()
                ):
                    errors.append(
                        issue(
                            "SKILL_DESCRIPTION_INVALID",
                            f"{catalog_key}/SKILL.md",
                            "frontmatter description must be non-empty",
                        )
                    )
                version = frontmatter.get("version")
                if (
                    not isinstance(version, str)
                    or SEMVER_PATTERN.fullmatch(version) is None
                ):
                    errors.append(
                        issue(
                            "SKILL_VERSION_INVALID",
                            f"{catalog_key}/SKILL.md",
                            "frontmatter version must use three-part semver",
                        )
                    )
                else:
                    changelog_path = skill_dir / "CHANGELOG.md"
                    if changelog_path.is_file():
                        try:
                            changelog = changelog_path.read_text(
                                encoding="utf-8"
                            )
                        except (OSError, UnicodeError) as error:
                            errors.append(
                                issue(
                                    "CHANGELOG_INVALID",
                                    f"{catalog_key}/CHANGELOG.md",
                                    f"CHANGELOG cannot be read: {error}",
                                )
                            )
                        else:
                            version_heading = re.compile(
                                rf"^## {re.escape(version)}\s*$",
                                re.MULTILINE,
                            )
                            if version_heading.search(changelog) is None:
                                errors.append(
                                    issue(
                                        "CHANGELOG_VERSION_MISSING",
                                        f"{catalog_key}/CHANGELOG.md",
                                        (
                                            "CHANGELOG has no heading for "
                                            f"frontmatter version {version}"
                                        ),
                                    )
                                )

    skills_root = repo_root / "skills"
    discovered_keys = {
        path.parent.relative_to(repo_root).as_posix()
        for path in skills_root.glob("*/SKILL.md")
    } if skills_root.is_dir() else set()
    for missing_key in sorted(discovered_keys - catalog_keys):
        errors.append(
            issue(
                "CATALOG_ENTRY_MISSING",
                missing_key,
                "published skill directory is absent from the catalog",
            )
        )
    for display_name, paths in sorted(display_name_paths.items()):
        if len(paths) > 1:
            errors.append(
                issue(
                    "DISPLAY_NAME_DUPLICATE",
                    "$.displayName",
                    (
                        f"displayName {display_name!r} is reused by: "
                        + ", ".join(sorted(paths))
                    ),
                )
            )

    return {
        "valid": not errors,
        "catalog": str(catalog_path),
        "entryCount": len(catalog),
        "errors": errors,
    }


def main(argv=None):
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(".clawhub/skill-catalog.json"),
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    catalog_path = args.catalog
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    result = validate(repo_root, catalog_path.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

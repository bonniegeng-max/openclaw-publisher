#!/usr/bin/env python3
"""Validate the Package Publish Doctor promotion contract without side effects."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_DRAFT_FILES = {
    "SKILL.md",
    "CHANGELOG.md",
    ".clawhubignore",
    "scripts/diagnose.py",
    "references/input-contract.md",
    "references/failure-map.md",
    "templates/package_diagnosis_report.md",
}
ALLOWED_GATE_STATES = {
    "complete",
    "pending",
    "blocked-until-not-before",
}
ALLOWED_CONTRACT_STATUSES = {
    "observation-window-hold",
    "promotion-ready",
    "publication-pending",
    "verification-pending",
    "complete",
}
REQUIRED_GATE_IDS = frozenset(
    {
        "observation-window",
        "fresh-official-version-review",
        "same-method-clawhub-competitor-search",
        "local-tests",
        "explicit-slug-name-dry-run",
        "authorized-publish",
        "registry-moderation-check",
        "single-version-e4",
    }
)


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("observationNotBefore must be a string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("observationNotBefore must include a timezone")
    return parsed.astimezone(timezone.utc)


def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("draft SKILL.md frontmatter missing")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def load_object(path, label):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} cannot be read as JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def inside(root, relative):
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"path escapes repository root: {relative}") from error
    return candidate


def evaluate(repo_root, contract_path, now):
    errors = []
    local_evidence = {}
    try:
        contract = load_object(contract_path, "promotion contract")
        policy = load_object(
            repo_root / "metrics" / "observation-policy.json",
            "observation policy",
        )
        catalog = load_object(
            repo_root / ".clawhub" / "skill-catalog.json",
            "skill catalog",
        )
        candidate = contract["candidate"]
        source = inside(repo_root, candidate["sourceDirectory"])
        target = inside(repo_root, candidate["targetDirectory"])
        frontmatter = parse_frontmatter(source / "SKILL.md")
    except (KeyError, TypeError, ValueError) as error:
        return {
            "valid": False,
            "complete": False,
            "contractStatus": "invalid",
            "evaluatedAt": now.astimezone(timezone.utc).isoformat(),
            "blockingGates": [],
            "localEvidence": {},
            "errors": [str(error)],
        }

    required_present = all((source / path).is_file() for path in REQUIRED_DRAFT_FILES)
    local_evidence["requiredDraftFilesPresent"] = required_present
    if not required_present:
        errors.append("draft package is missing one or more required files")

    declared_status = contract.get("status")
    if declared_status not in ALLOWED_CONTRACT_STATUSES:
        errors.append("promotion contract has invalid status")

    identity_matches = (
        frontmatter.get("name") == candidate.get("displayName")
        and frontmatter.get("slug") == candidate.get("stableSlug")
        and frontmatter.get("version") == candidate.get("draftVersion")
    )
    local_evidence["draftIdentityMatchesContract"] = identity_matches
    if not identity_matches:
        errors.append("draft frontmatter does not match candidate identity")

    slug = candidate.get("stableSlug")
    safe_slug = (
        isinstance(slug, str)
        and bool(slug)
        and not slug.startswith("clawhub-")
        and not slug.endswith("-clawhub")
    )
    local_evidence["stableSlugAllowed"] = safe_slug
    if not safe_slug:
        errors.append("candidate stable slug uses a protected namespace")

    policy_matches = (
        contract.get("observationNotBefore") == policy.get("notBefore")
    )
    local_evidence["observationPolicyMatches"] = policy_matches
    if not policy_matches:
        errors.append("promotion contract observation time differs from policy")

    catalog_key = candidate.get("targetDirectory")
    catalog_entry = contract.get("catalogEntry")
    catalog_candidate_valid = (
        isinstance(catalog_entry, dict)
        and catalog_entry.get("displayName") == candidate.get("displayName")
        and isinstance(catalog_entry.get("categories"), list)
        and bool(catalog_entry["categories"])
        and len(catalog_entry["categories"]) == len(set(catalog_entry["categories"]))
        and all(
            isinstance(item, str) and item
            for item in catalog_entry["categories"]
        )
        and isinstance(catalog_entry.get("topics"), list)
        and bool(catalog_entry["topics"])
        and len(catalog_entry["topics"]) == len(set(catalog_entry["topics"]))
        and all(
            isinstance(item, str) and item
            for item in catalog_entry["topics"]
        )
    )
    local_evidence["catalogCandidateValid"] = catalog_candidate_valid
    if not catalog_candidate_valid:
        errors.append("candidate catalog entry is invalid or inconsistent")

    target_exists = target.is_dir()
    catalog_has_target = (
        isinstance(catalog_key, str) and catalog_key in catalog
    )
    local_evidence["formalTargetDirectoryPresent"] = target_exists
    local_evidence["formalCatalogEntryPresent"] = catalog_has_target
    if target_exists != catalog_has_target:
        errors.append(
            "formal skill directory and catalog entry must appear together"
        )

    pre_staging_state = declared_status in {
        "observation-window-hold",
        "promotion-ready",
    }
    absent_from_formal_surfaces = not target_exists and not catalog_has_target
    local_evidence["absentFromFormalSurfacesDuringHold"] = (
        absent_from_formal_surfaces
    )
    if pre_staging_state and not absent_from_formal_surfaces:
        errors.append(
            "pre-staging candidate already exists in skills or formal catalog"
        )
    if declared_status in {
        "publication-pending",
        "verification-pending",
        "complete",
    } and not (target_exists and catalog_has_target):
        errors.append(
            "post-staging candidate is missing from skills or formal catalog"
        )

    local_evidence["formalTargetIdentityMatches"] = None
    local_evidence["formalCatalogEntryMatches"] = None
    if target_exists and catalog_has_target:
        try:
            target_frontmatter = parse_frontmatter(target / "SKILL.md")
            target_identity_matches = (
                target_frontmatter.get("name") == candidate.get("displayName")
                and target_frontmatter.get("slug") == candidate.get("stableSlug")
                and target_frontmatter.get("version")
                == candidate.get("proposedFirstReleaseVersion")
            )
        except (OSError, UnicodeError, ValueError):
            target_identity_matches = False
        formal_catalog_matches = catalog.get(catalog_key) == catalog_entry
        local_evidence["formalTargetIdentityMatches"] = (
            target_identity_matches
        )
        local_evidence["formalCatalogEntryMatches"] = formal_catalog_matches
        if not target_identity_matches:
            errors.append(
                "formal SKILL.md identity does not match promotion contract"
            )
        if not formal_catalog_matches:
            errors.append(
                "formal catalog entry does not match promotion contract"
            )

    gates = contract.get("releaseGates")
    if not isinstance(gates, list):
        errors.append("releaseGates must be an array")
        gates = []
    gate_ids = []
    for gate in gates:
        if not isinstance(gate, dict):
            errors.append("every release gate must be an object")
            continue
        gate_id = gate.get("id")
        state = gate.get("state")
        if not isinstance(gate_id, str) or not gate_id:
            errors.append("every release gate must have a non-empty id")
            continue
        gate_ids.append(gate_id)
        if gate.get("required") is not True:
            errors.append(f"release gate {gate_id} must be required")
        if state not in ALLOWED_GATE_STATES:
            errors.append(f"release gate {gate_id} has invalid state")
    if len(gate_ids) != len(set(gate_ids)):
        errors.append("release gate ids must be unique")
    observed_gate_ids = set(gate_ids)
    missing_gate_ids = sorted(REQUIRED_GATE_IDS - observed_gate_ids)
    unexpected_gate_ids = sorted(observed_gate_ids - REQUIRED_GATE_IDS)
    if missing_gate_ids:
        errors.append(
            "required release gates missing: " + ", ".join(missing_gate_ids)
        )
    if unexpected_gate_ids:
        errors.append(
            "unexpected release gates present: "
            + ", ".join(unexpected_gate_ids)
        )
    for gate in gates:
        if (
            isinstance(gate, dict)
            and gate.get("state") == "blocked-until-not-before"
            and gate.get("id") != "observation-window"
        ):
            errors.append(
                "only observation-window may use blocked-until-not-before"
            )

    blocking_gates = [
        gate["id"]
        for gate in gates
        if isinstance(gate, dict)
        and isinstance(gate.get("id"), str)
        and gate.get("required") is True
        and gate.get("state") != "complete"
    ]

    try:
        not_before = parse_time(contract.get("observationNotBefore"))
        observation_elapsed = now >= not_before
        local_evidence["observationWindowElapsed"] = observation_elapsed
        observation_gate = next(
            (
                gate
                for gate in gates
                if isinstance(gate, dict)
                and gate.get("id") == "observation-window"
            ),
            None,
        )
        if (
            not observation_elapsed
            and observation_gate is not None
            and observation_gate.get("state") == "complete"
        ):
            errors.append(
                "observation-window cannot be complete before notBefore"
            )
    except ValueError as error:
        errors.append(str(error))
        local_evidence["observationWindowElapsed"] = False

    release_policy = contract.get("releasePolicy")
    release_policy_valid = (
        isinstance(release_policy, dict)
        and release_policy.get("addToFormalCatalogDuringObservationWindow")
        is False
        and release_policy.get("publishDuringObservationWindow") is False
        and release_policy.get("requireAllReleaseGatesComplete") is True
        and release_policy.get("maxPlannedE4InstallsPerChangedVersion") == 1
        and release_policy.get("resetObservationStartAfterE4") is True
    )
    local_evidence["releasePolicyValid"] = release_policy_valid
    if not release_policy_valid:
        errors.append("release policy does not preserve required safeguards")

    if not blocking_gates and declared_status != "complete":
        blocking_gates.append("contract-status")

    complete = (
        not errors
        and declared_status == "complete"
        and not blocking_gates
    )
    status = "invalid" if errors else ("complete" if complete else "blocked")
    return {
        "valid": not errors,
        "complete": complete,
        "contractStatus": status,
        "evaluatedAt": now.astimezone(timezone.utc).isoformat(),
        "blockingGates": blocking_gates,
        "localEvidence": local_evidence,
        "errors": errors,
    }


def main(argv=None):
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().with_name("promotion-contract.json"),
    )
    parser.add_argument("--now")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    try:
        now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as error:
        print(
            json.dumps(
                {"error": "INPUT_CONTRACT_ERROR", "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    result = evaluate(args.repo_root.resolve(), args.contract.resolve(), now)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    if args.require_complete and not result["complete"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

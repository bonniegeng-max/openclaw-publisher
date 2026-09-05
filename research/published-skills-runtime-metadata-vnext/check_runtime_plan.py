#!/usr/bin/env python3
"""Validate the published-Skill runtime metadata plan without side effects."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


TEXT_ONLY_REMOVE = {
    "metadata.openclaw.install",
    "metadata.openclaw.os",
    "metadata.openclaw.requires",
}
TEXT_ONLY_RETAIN = {
    "metadata.openclaw.emoji",
    "metadata.openclaw.homepage",
}
CLI_RETAIN = {
    "metadata.openclaw.emoji",
    "metadata.openclaw.homepage",
    "metadata.openclaw.install",
    "metadata.openclaw.requires",
}
MAC_SPECIFIC_MARKERS = (
    "osascript",
    "xattr",
    "plutil",
    "defaults ",
    "/applications",
    "mdfind",
    "pbcopy",
    "pbpaste",
    "brew ",
)
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def load_object(path, label):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} cannot be read as JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("observationNotBefore must be a string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("observationNotBefore must include a timezone")
    return parsed.astimezone(timezone.utc)


def parse_frontmatter(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path.name} cannot be read: {error}") from error
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path.name} frontmatter missing")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values, text


def inside(repo_root, relative, label):
    if not isinstance(relative, str):
        raise ValueError(f"{label} must be a string")
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes repository root") from error
    return candidate


def exact_string_set(value, expected):
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and set(value) == expected
    )


def invalid_result(now, error):
    return {
        "valid": False,
        "readyForFreshReview": False,
        "readyToApply": False,
        "evaluatedAt": now.astimezone(timezone.utc).isoformat(),
        "targetCount": 0,
        "blockingReasons": [],
        "localEvidence": {},
        "errors": [str(error)],
    }


def evaluate(repo_root, plan_path, policy_path, now):
    errors = []
    local_evidence = {}
    try:
        plan = load_object(plan_path, "runtime metadata plan")
        policy = load_object(policy_path, "observation policy")
        catalog = load_object(
            repo_root / ".clawhub" / "skill-catalog.json",
            "skill catalog",
        )
        not_before = parse_time(plan["observationNotBefore"])
        targets = plan["targets"]
        if not isinstance(targets, list):
            raise ValueError("targets must be an array")
    except (KeyError, TypeError, ValueError) as error:
        return invalid_result(now, error)

    if plan.get("schemaVersion") != 1:
        errors.append("runtime metadata plan schemaVersion must equal 1")
    if policy.get("schemaVersion") != 1:
        errors.append("observation policy schemaVersion must equal 1")
    if plan.get("status") != "observation-window-hold":
        errors.append("runtime metadata plan status must remain observation-window-hold")
    if plan.get("observationNotBefore") != policy.get("notBefore"):
        errors.append("runtime plan observation time must match observation policy")

    catalog_slugs = {
        key.removeprefix("skills/")
        for key in catalog
        if isinstance(key, str) and key.startswith("skills/")
    }
    target_slugs = []
    for target in targets:
        if isinstance(target, dict) and isinstance(target.get("slug"), str):
            target_slugs.append(target["slug"])
        else:
            errors.append("every runtime target must be an object with a string slug")
    unique_target_slugs = set(target_slugs)
    if len(target_slugs) != len(unique_target_slugs):
        errors.append("runtime target slugs must be unique")
    if unique_target_slugs != catalog_slugs:
        errors.append("runtime target set must equal the published catalog slug set")

    current_states_match = True
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("slug"), str):
            continue
        slug = target["slug"]
        if SLUG_PATTERN.fullmatch(slug) is None:
            errors.append(f"{slug}: target slug must use lowercase kebab-case")
            current_states_match = False
            continue
        skill_path = repo_root / "skills" / slug / "SKILL.md"
        try:
            frontmatter, skill_text = parse_frontmatter(skill_path)
        except ValueError as error:
            errors.append(f"{slug}: {error}")
            current_states_match = False
            continue
        if frontmatter.get("slug") != slug:
            errors.append(f"{slug}: frontmatter slug does not match target")
            current_states_match = False
        if frontmatter.get("version") != target.get("currentVersion"):
            errors.append(f"{slug}: currentVersion does not match formal SKILL.md")
            current_states_match = False
        if "os: [macos]" not in skill_text:
            errors.append(f"{slug}: expected current macOS-only metadata is absent")
            current_states_match = False
        matched_markers = [
            marker
            for marker in MAC_SPECIFIC_MARKERS
            if marker in skill_text.lower()
        ]
        if matched_markers:
            errors.append(
                f"{slug}: macOS-specific command markers found: "
                + ", ".join(matched_markers)
            )
            current_states_match = False

        profile = target.get("profile")
        if profile == "text-only":
            if not exact_string_set(
                target.get("remove"),
                TEXT_ONLY_REMOVE,
            ):
                errors.append(f"{slug}: text-only remove contract is invalid")
            if not exact_string_set(
                target.get("retain"),
                TEXT_ONLY_RETAIN,
            ):
                errors.append(f"{slug}: text-only retain contract is invalid")
        elif profile == "cli-backed":
            replace = target.get("replace")
            os_change = (
                replace.get("metadata.openclaw.os", {})
                if isinstance(replace, dict)
                else {}
            )
            if not isinstance(os_change, dict):
                os_change = {}
            if (
                os_change.get("from") != ["macos"]
                or os_change.get("to") != ["macos", "linux"]
            ):
                errors.append(f"{slug}: CLI operating-system change is invalid")
            if not exact_string_set(target.get("retain"), CLI_RETAIN):
                errors.append(f"{slug}: CLI retain contract is invalid")
        else:
            errors.append(f"{slug}: profile must be text-only or cli-backed")

    evidence = plan.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("runtime plan evidence must be an object")
        evidence = {}
    workflow_relative = evidence.get("linuxWorkflow")
    try:
        workflow_path = inside(
            repo_root,
            workflow_relative,
            "Linux workflow evidence path",
        )
    except ValueError as error:
        errors.append(str(error))
        workflow_path = None
    if workflow_path is None or not workflow_path.is_file():
        errors.append("Linux workflow evidence file is missing")
    else:
        try:
            workflow_text = workflow_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"Linux workflow evidence cannot be read: {error}")
        else:
            if evidence.get("linuxWorkflowRunner") != "ubuntu-latest":
                errors.append("Linux workflow runner evidence must equal ubuntu-latest")
            if "runs-on: ubuntu-latest" not in workflow_text:
                errors.append("Linux workflow no longer uses ubuntu-latest")
    if evidence.get("macSpecificCommandMatches") != []:
        errors.append("macSpecificCommandMatches must remain an empty array")

    claims = plan.get("claims")
    expected_claims = {
        "macOnlyRestrictionConfirmed": True,
        "linuxToolchainConfirmed": True,
        "textOnlyBinaryRequirementMismatchConfirmed": True,
        "windowsCompatibilityConfirmed": False,
        "downloadImpactConfirmed": False,
        "searchImpactConfirmed": False,
    }
    if claims != expected_claims:
        errors.append("runtime plan claims do not preserve evidence boundaries")

    release_policy = plan.get("releasePolicy")
    expected_release_policy = {
        "publishDuringObservationWindow": False,
        "publishAllTargetsByDefault": False,
        "requireFreshNeedReview": True,
        "maxPlannedE4InstallsPerChangedVersion": 1,
        "resetObservationStartAfterE4": True,
    }
    if release_policy != expected_release_policy:
        errors.append("runtime plan releasePolicy is invalid")

    observation_elapsed = now.astimezone(timezone.utc) >= not_before
    valid = not errors
    ready_for_review = valid and observation_elapsed
    blocking_reasons = []
    if not observation_elapsed:
        blocking_reasons.append("observation-window")
    blocking_reasons.append("fresh-need-review")
    local_evidence.update(
        {
            "observationWindowElapsed": observation_elapsed,
            "currentFormalMetadataMatchesPlanBaseline": current_states_match,
            "targetSetMatchesCatalog": unique_target_slugs == catalog_slugs,
            "formalTargetsUnchanged": current_states_match,
        }
    )
    return {
        "valid": valid,
        "readyForFreshReview": ready_for_review,
        "readyToApply": False,
        "evaluatedAt": now.astimezone(timezone.utc).isoformat(),
        "targetCount": len(targets),
        "blockingReasons": blocking_reasons,
        "localEvidence": local_evidence,
        "errors": errors,
    }


def main(argv=None):
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(
            "research/published-skills-runtime-metadata-vnext/change-plan.json"
        ),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("metrics/observation-policy.json"),
    )
    parser.add_argument("--now")
    parser.add_argument("--require-review-window", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    plan_path = args.plan if args.plan.is_absolute() else repo_root / args.plan
    policy_path = (
        args.policy if args.policy.is_absolute() else repo_root / args.policy
    )
    if args.now:
        try:
            now = parse_time(args.now)
        except (TypeError, ValueError) as error:
            parser.error(f"invalid --now value: {error}")
    else:
        now = datetime.now(timezone.utc)
    result = evaluate(repo_root, plan_path, policy_path, now)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["valid"]:
        return 2
    if args.require_review_window and not result["readyForFreshReview"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

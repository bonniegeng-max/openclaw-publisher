import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
CHECKER = ROOT / "scripts" / "check_skill_release_authorization.py"
PREPARER = ROOT / "scripts" / "prepare_skill_release_authorization.py"
CATALOG_VALIDATOR = ROOT / "scripts" / "validate_skill_catalog.py"
TEMPLATE = (
    ROOT
    / "research"
    / "skill-release-authorization-vnext"
    / "authorization-template.json"
)
INTEGRATION_PLAN = (
    ROOT
    / "research"
    / "skill-release-authorization-vnext"
    / "workflow-integration-plan.md"
)
METRICS_WORKFLOW = ROOT / ".github" / "workflows" / "metrics-tools-ci.yml"
PUBLISH_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "clawhub-skill-publish.yml",
    ROOT / ".github" / "workflows" / "clawhub-skill-publish-local.yml",
)
SPEC = importlib.util.spec_from_file_location(
    "skill_release_authorization",
    CHECKER,
)
CHECK_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_MODULE)
PREPARE_SPEC = importlib.util.spec_from_file_location(
    "prepare_skill_release_authorization",
    PREPARER,
)
PREPARE_MODULE = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_SPEC.loader.exec_module(PREPARE_MODULE)

BASE_COMMIT = "a" * 40
CANDIDATE_COMMIT = "b" * 40
NOT_BEFORE = "2026-09-12T10:45:38+00:00"
AUTHORIZED_NOW = datetime(2026, 9, 13, 1, tzinfo=timezone.utc)
BEFORE_WINDOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_skill(root, slug="demo-skill", version="1.0.1", name="Demo Skill"):
    skill_dir = root / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"slug: {slug}",
                f"version: {version}",
                "description: Demonstrate release authorization.",
                "---",
                "",
                "# Demo",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (skill_dir / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## {version}\n\n- Test release.\n",
        encoding="utf-8",
    )
    (skill_dir / ".clawhubignore").write_text(".git/\n", encoding="utf-8")


def make_repo(directory):
    root = Path(directory)
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(CATALOG_VALIDATOR, root / "scripts" / CATALOG_VALIDATOR.name)
    write_skill(root)
    catalog = {
        "skills/demo-skill": {
            "displayName": "Demo Skill",
            "categories": ["development"],
            "topics": ["release-automation"],
        }
    }
    write_json(root / ".clawhub" / "skill-catalog.json", catalog)
    write_json(
        root / "metrics" / "observation-policy.json",
        {
            "schemaVersion": 1,
            "notBefore": NOT_BEFORE,
            "reason": "Test observation window.",
        },
    )
    (root / "review.md").write_text("# Review\n", encoding="utf-8")
    return root, catalog


def make_authorization(root, base_catalog, changed_paths=None, **overrides):
    targets = {"demo-skill"}
    if changed_paths is None:
        changed_paths = [
            CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
            "skills/demo-skill/SKILL.md",
            "skills/demo-skill/CHANGELOG.md",
            "review.md",
        ]
    value = {
        "schemaVersion": 1,
        "status": "approved",
        "releaseId": "demo-skill-1.0.1",
        "issuedAt": "2026-09-13T00:00:00+00:00",
        "expiresAt": "2026-09-15T00:00:00+00:00",
        "observationNotBefore": NOT_BEFORE,
        "baseCommit": BASE_COMMIT,
        "candidateCommit": CANDIDATE_COMMIT,
        "modes": ["dry-run", "publish"],
        "targets": [{"slug": "demo-skill", "version": "1.0.1"}],
        "catalogChanged": False,
        "contentDigest": CHECK_MODULE.compute_content_digest(
            root,
            json.loads(
                (root / ".clawhub" / "skill-catalog.json").read_text(
                    encoding="utf-8"
                )
            ),
            targets,
        ),
        "changeSetDigest": CHECK_MODULE.compute_change_set_digest(
            root,
            set(changed_paths),
            CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
        ),
        "review": {
            "completed": True,
            "reviewedAt": "2026-09-12T23:00:00+00:00",
            "changeClass": "correctness-fix",
            "reason": "Fix a verified runtime metadata defect.",
            "evidence": [
                {
                    "path": "review.md",
                    "sha256": CHECK_MODULE.file_sha256(root / "review.md"),
                }
            ],
        },
    }
    for key, item in overrides.items():
        value[key] = item
    path = root / CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH
    write_json(path, value)
    return path, value


def evaluate(root, base_catalog, authorization_path, **overrides):
    values = {
        "changed_paths": [
            CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
            "skills/demo-skill/SKILL.md",
            "skills/demo-skill/CHANGELOG.md",
            "review.md",
        ],
        "base_catalog": base_catalog,
        "base_policy": json.loads(
            (root / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        ),
        "base_versions": {"demo-skill": "1.0.0"},
        "base_commit": BASE_COMMIT,
        "candidate_commit": CANDIDATE_COMMIT,
        "mode": "publish",
        "now": AUTHORIZED_NOW,
    }
    values.update(overrides)
    return CHECK_MODULE.evaluate(
        root,
        authorization_path,
        root / "metrics" / "observation-policy.json",
        values["changed_paths"],
        values["base_catalog"],
        values["base_policy"],
        values["base_versions"],
        values["base_commit"],
        values["candidate_commit"],
        values["mode"],
        values["now"],
    )


def initialize_git(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "baseline"],
        cwd=root,
        check=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def commit_release_candidate(root, change_evidence=True):
    skill_path = root / "skills" / "demo-skill" / "SKILL.md"
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace(
            "version: 1.0.1",
            "version: 1.0.2",
            1,
        )
        + "\nCandidate change.\n",
        encoding="utf-8",
    )
    changelog_path = root / "skills" / "demo-skill" / "CHANGELOG.md"
    changelog_path.write_text(
        changelog_path.read_text(encoding="utf-8").replace(
            "# Changelog\n",
            "# Changelog\n\n## 1.0.2\n\n- Candidate release.\n",
            1,
        ),
        encoding="utf-8",
    )
    if change_evidence:
        (root / "review.md").write_text(
            "# Review\n\nCandidate evidence.\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "release candidate"],
        cwd=root,
        check=True,
    )


class SkillReleaseAuthorizationTests(unittest.TestCase):
    def test_repository_template_is_safe_and_complete(self):
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))

        self.assertEqual(set(template), CHECK_MODULE.TOP_LEVEL_FIELDS)
        self.assertEqual(template["status"], "pending")
        self.assertEqual(template["modes"], ["dry-run"])
        self.assertIsNone(template["issuedAt"])
        self.assertIsNone(template["expiresAt"])
        self.assertFalse(template["review"]["completed"])
        self.assertIsNone(template["review"]["reviewedAt"])
        self.assertEqual(set(template["review"]), CHECK_MODULE.REVIEW_FIELDS)
        self.assertEqual(
            set(template["review"]["evidence"][0]),
            CHECK_MODULE.EVIDENCE_FIELDS,
        )
        self.assertEqual(
            set(template["targets"][0]),
            CHECK_MODULE.TARGET_FIELDS,
        )
        self.assertEqual(
            template["observationNotBefore"],
            NOT_BEFORE,
        )
        self.assertRegex(template["candidateCommit"], r"^[0-9a-f]{40}$")

    def test_gate_is_ci_tested_but_not_wired_during_observation(self):
        metrics_workflow = METRICS_WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(
            metrics_workflow.count(
                '"research/skill-release-authorization-vnext/**"'
            ),
            2,
        )
        self.assertIn("python -m py_compile scripts/*.py", metrics_workflow)
        for workflow_path in PUBLISH_WORKFLOWS:
            with self.subTest(workflow=workflow_path.name):
                workflow = workflow_path.read_text(encoding="utf-8")
                self.assertNotIn(
                    "check_skill_release_authorization.py",
                    workflow,
                )

    def test_integration_plan_preserves_trusted_approval_boundary(self):
        plan = INTEGRATION_PLAN.read_text(encoding="utf-8")

        for required in (
            "deferred-until-observation-review",
            "prevent_self_review: true",
            "environment: clawhub-production",
            "受信任完整 SHA",
            "CLAWHUB_TOKEN",
            "pull_request_target",
            "E3 moderation",
            "E4 隔离安装",
        ):
            with self.subTest(required=required):
                self.assertIn(required, plan)

    def test_matching_one_time_authorization_allows_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)

            for mode in ("dry-run", "publish"):
                with self.subTest(mode=mode):
                    result = evaluate(
                        root,
                        base_catalog,
                        authorization_path,
                        mode=mode,
                    )
                    self.assertTrue(result["valid"], result["errors"])
                    self.assertTrue(result["authorized"])
                    self.assertEqual(result["blockingReasons"], [])
                    self.assertEqual(
                        result["targets"],
                        [{"slug": "demo-skill", "version": "1.0.1"}],
                    )
                    self.assertTrue(result["authorizationChanged"])

    def test_observation_window_and_issue_time_block_early_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                now=BEFORE_WINDOW,
            )

        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["authorized"])
        self.assertIn("observation-window", result["blockingReasons"])
        self.assertIn(
            "authorization-not-yet-active",
            result["blockingReasons"],
        )

    def test_unapproved_mode_and_incomplete_review_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            authorization["modes"] = ["dry-run"]
            authorization["review"]["completed"] = False
            write_json(authorization_path, authorization)
            result = evaluate(root, base_catalog, authorization_path)

        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["authorized"])
        self.assertIn("mode-not-approved", result["blockingReasons"])
        self.assertIn("fresh-review", result["blockingReasons"])

    def test_authorization_must_change_with_release_to_prevent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=["skills/demo-skill/SKILL.md"],
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["authorized"])
        self.assertFalse(result["authorizationChanged"])
        self.assertIn(
            "authorization file must change in the evaluated commit range",
            result["errors"],
        )

    def test_complete_change_set_digest_rejects_appended_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            (root / "README.md").write_text("Changed after review.\n", encoding="utf-8")
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=[
                    CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                    "skills/demo-skill/SKILL.md",
                    "skills/demo-skill/CHANGELOG.md",
                    "README.md",
                    "review.md",
                ],
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "changeSetDigest does not match the complete release diff",
            result["errors"],
        )

    def test_release_commit_cannot_modify_protected_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            workflow = root / ".github" / "workflows" / "publish.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: Changed control\n", encoding="utf-8")
            changed_paths = [
                CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                "skills/demo-skill/SKILL.md",
                ".github/workflows/publish.yml",
                "review.md",
            ]
            authorization_path, _ = make_authorization(
                root,
                base_catalog,
                changed_paths=changed_paths,
            )
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=changed_paths,
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            (
                "release commit cannot modify protected control path: "
                ".github/workflows/publish.yml"
            ),
            result["errors"],
        )

    def test_changed_validator_is_rejected_without_loading_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            validator_path = root / "scripts" / "validate_skill_catalog.py"
            validator_path.write_text(
                "raise RuntimeError('must not execute')\n",
                encoding="utf-8",
            )
            changed_paths = [
                CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                "skills/demo-skill/SKILL.md",
                "scripts/validate_skill_catalog.py",
                "review.md",
            ]
            authorization_path, _ = make_authorization(
                root,
                base_catalog,
                changed_paths=changed_paths,
            )
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=changed_paths,
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            (
                "release commit cannot modify protected control path: "
                "scripts/validate_skill_catalog.py"
            ),
            result["errors"],
        )
        self.assertFalse(
            any("must not execute" in error for error in result["errors"])
        )

    def test_content_and_version_drift_invalidate_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            skill_path = root / "skills" / "demo-skill" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8") + "\nChanged.\n",
                encoding="utf-8",
            )
            digest_result = evaluate(root, base_catalog, authorization_path)
            self.assertFalse(digest_result["valid"])
            self.assertIn(
                "contentDigest does not match authorized Skill content",
                digest_result["errors"],
            )

            authorization = json.loads(
                authorization_path.read_text(encoding="utf-8")
            )
            authorization["targets"][0]["version"] = "1.0.2"
            authorization["contentDigest"] = CHECK_MODULE.compute_content_digest(
                root,
                json.loads(
                    (root / ".clawhub" / "skill-catalog.json").read_text(
                        encoding="utf-8"
                    )
                ),
                {"demo-skill"},
            )
            write_json(authorization_path, authorization)
            version_result = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(version_result["valid"])
        self.assertIn(
            "demo-skill: formal SKILL.md version does not match authorization",
            version_result["errors"],
        )

    def test_base_commit_and_target_set_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            wrong_base = evaluate(
                root,
                base_catalog,
                authorization_path,
                base_commit="b" * 40,
            )
            self.assertFalse(wrong_base["valid"])
            self.assertIn(
                "authorization baseCommit does not match evaluated base",
                wrong_base["errors"],
            )
            wrong_candidate = evaluate(
                root,
                base_catalog,
                authorization_path,
                candidate_commit="c" * 40,
            )
            self.assertFalse(wrong_candidate["valid"])
            self.assertIn(
                (
                    "authorization candidateCommit does not match "
                    "evaluated candidate"
                ),
                wrong_candidate["errors"],
            )

            authorization["targets"] = [
                {"slug": "another-skill", "version": "1.0.0"}
            ]
            write_json(authorization_path, authorization)
            wrong_targets = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(wrong_targets["valid"])
        self.assertIn(
            "authorized target set does not match formal changed targets",
            wrong_targets["errors"],
        )

    def test_catalog_change_is_detected_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root, current_catalog = make_repo(directory)
            base_catalog = copy.deepcopy(current_catalog)
            base_catalog["skills/demo-skill"]["topics"] = ["old-topic"]
            changed_paths = [
                CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                CHECK_MODULE.CATALOG_PATH,
                "skills/demo-skill/SKILL.md",
                "review.md",
            ]
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
                changed_paths=changed_paths,
            )

            mismatch = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=changed_paths,
            )
            self.assertFalse(mismatch["valid"])
            self.assertIn(
                "catalogChanged does not match the evaluated commit range",
                mismatch["errors"],
            )

            authorization["catalogChanged"] = True
            write_json(authorization_path, authorization)
            valid = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=changed_paths,
            )

        self.assertTrue(valid["valid"], valid["errors"])
        self.assertTrue(valid["authorized"])
        self.assertTrue(valid["catalogChanged"])

    def test_existing_skill_cannot_claim_new_skill_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            authorization["review"]["changeClass"] = "new-skill"
            write_json(authorization_path, authorization)
            result = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(result["valid"])
        self.assertIn(
            "existing Skill cannot use changeClass new-skill",
            result["errors"],
        )

    def test_expiry_lifetime_and_policy_timestamp_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            authorization["expiresAt"] = "2026-09-20T00:00:00+00:00"
            write_json(authorization_path, authorization)
            lifetime = evaluate(root, base_catalog, authorization_path)
            self.assertFalse(lifetime["valid"])
            self.assertIn(
                "authorization lifetime cannot exceed 72 hours",
                lifetime["errors"],
            )

            authorization["expiresAt"] = "2026-09-15T00:00:00+00:00"
            authorization["observationNotBefore"] = (
                "2026-09-11T10:45:38+00:00"
            )
            write_json(authorization_path, authorization)
            policy_drift = evaluate(root, base_catalog, authorization_path)
            self.assertFalse(policy_drift["valid"])
            self.assertIn(
                "authorization observationNotBefore must match policy",
                policy_drift["errors"],
            )

    def test_policy_must_match_the_trusted_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            base_policy = json.loads(
                (root / "metrics" / "observation-policy.json").read_text(
                    encoding="utf-8"
                )
            )
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            current_policy = copy.deepcopy(base_policy)
            current_policy["reason"] = "Relaxed in release commit."
            write_json(
                root / "metrics" / "observation-policy.json",
                current_policy,
            )
            authorization["changeSetDigest"] = (
                CHECK_MODULE.compute_change_set_digest(
                    root,
                    {
                        CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                        "skills/demo-skill/SKILL.md",
                        "skills/demo-skill/CHANGELOG.md",
                        "metrics/observation-policy.json",
                        "review.md",
                    },
                    CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                )
            )
            write_json(authorization_path, authorization)
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=[
                    CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                    "skills/demo-skill/SKILL.md",
                    "skills/demo-skill/CHANGELOG.md",
                    "metrics/observation-policy.json",
                    "review.md",
                ],
                base_policy=base_policy,
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "observation policy must not change in a release commit range",
            result["errors"],
        )
        self.assertIn(
            "observation policy cannot change with a Skill release",
            result["errors"],
        )

    def test_evidence_paths_are_required_and_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            authorization["review"]["evidence"] = [
                {
                    "path": "../outside.md",
                    "sha256": "sha256:" + "0" * 64,
                }
            ]
            write_json(authorization_path, authorization)
            escaped = evaluate(root, base_catalog, authorization_path)
            self.assertFalse(escaped["valid"])
            self.assertIn(
                "review evidence[0].path escapes repository root",
                escaped["errors"],
            )

            authorization["review"]["evidence"] = [
                {
                    "path": "missing.md",
                    "sha256": "sha256:" + "0" * 64,
                }
            ]
            write_json(authorization_path, authorization)
            missing = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(missing["valid"])
        self.assertIn(
            "review evidence file is missing: missing.md",
            missing["errors"],
        )

    def test_review_evidence_content_is_bound_by_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            (root / "review.md").write_text(
                "# Replaced after approval\n",
                encoding="utf-8",
            )
            result = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(result["valid"])
        self.assertIn(
            "review evidence digest does not match: review.md",
            result["errors"],
        )

    def test_review_evidence_must_change_with_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, _ = make_authorization(root, base_catalog)
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                changed_paths=[
                    CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                    "skills/demo-skill/SKILL.md",
                    "skills/demo-skill/CHANGELOG.md",
                ],
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "review evidence must change in the release diff: review.md",
            result["errors"],
        )

    def test_expiry_is_exclusive_and_review_must_be_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            result = evaluate(
                root,
                base_catalog,
                authorization_path,
                now=datetime(2026, 9, 15, tzinfo=timezone.utc),
            )
            self.assertTrue(result["valid"], result["errors"])
            self.assertFalse(result["authorized"])
            self.assertIn(
                "authorization-expired",
                result["blockingReasons"],
            )

            authorization["issuedAt"] = "2026-09-20T00:00:00+00:00"
            authorization["expiresAt"] = "2026-09-22T00:00:00+00:00"
            authorization["review"]["reviewedAt"] = (
                "2026-09-12T11:00:00+00:00"
            )
            write_json(authorization_path, authorization)
            stale = evaluate(
                root,
                base_catalog,
                authorization_path,
                now=datetime(2026, 9, 20, 1, tzinfo=timezone.utc),
            )

        self.assertFalse(stale["valid"])
        self.assertIn(
            "fresh review cannot be more than 72 hours old",
            stale["errors"],
        )

    def test_duplicate_keys_and_boolean_schema_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
            )
            raw = authorization_path.read_text(encoding="utf-8").replace(
                '"status": "approved"',
                '"status": "pending",\n  "status": "approved"',
                1,
            )
            authorization_path.write_text(raw, encoding="utf-8")
            duplicate = evaluate(root, base_catalog, authorization_path)
            self.assertFalse(duplicate["valid"])
            self.assertIn("duplicate JSON key: status", duplicate["errors"][0])

            authorization["schemaVersion"] = True
            write_json(authorization_path, authorization)
            boolean_schema = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(boolean_schema["valid"])
        self.assertIn(
            "release authorization schemaVersion must equal 1",
            boolean_schema["errors"],
        )

    def test_duplicate_skill_frontmatter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            skill_path = root / "skills" / "demo-skill" / "SKILL.md"
            text = skill_path.read_text(encoding="utf-8")
            skill_path.write_text(
                text.replace(
                    "version: 1.0.1",
                    "version: 9.9.9\nversion: 1.0.1",
                    1,
                ),
                encoding="utf-8",
            )
            authorization_path, _ = make_authorization(root, base_catalog)
            result = evaluate(root, base_catalog, authorization_path)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                "frontmatter has duplicate key: version" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_skill_root_symlink_is_rejected_by_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root, catalog = make_repo(directory)
            skill_dir = root / "skills" / "demo-skill"
            relocated = root / "relocated-skill"
            skill_dir.rename(relocated)
            skill_dir.symlink_to(relocated, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "target path contains a symlink",
            ):
                CHECK_MODULE.compute_content_digest(
                    root,
                    catalog,
                    {"demo-skill"},
                )

    def test_control_json_symlinks_are_rejected_before_use(self):
        cases = (
            (
                CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                "release authorization path must not contain symlinks",
            ),
            (
                "metrics/observation-policy.json",
                "observation policy path must not contain symlinks",
            ),
            (
                CHECK_MODULE.CATALOG_PATH,
                "skill catalog path must not contain symlinks",
            ),
        )

        for relative, expected_error in cases:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as directory:
                    root, base_catalog = make_repo(directory)
                    authorization_path, _ = make_authorization(
                        root,
                        base_catalog,
                    )
                    original = root / relative
                    relocated = root / f"{original.name}.relocated"
                    original.rename(relocated)
                    original.symlink_to(relocated)
                    result = evaluate(
                        root,
                        base_catalog,
                        authorization_path,
                    )

                self.assertFalse(result["valid"])
                self.assertEqual(result["errors"], [expected_error])

    def test_preparer_builds_pending_draft_compatible_with_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            policy = {
                "schemaVersion": 1,
                "notBefore": "2020-01-01T00:00:00+00:00",
                "reason": "Completed test observation window.",
            }
            write_json(
                root / "metrics" / "observation-policy.json",
                policy,
            )
            base_commit = initialize_git(root)
            commit_release_candidate(root)

            draft = PREPARE_MODULE.prepare(
                repo_root=root,
                base_ref=base_commit,
                head_ref="HEAD",
                release_id="demo-skill-1.0.2",
                modes=["dry-run", "publish"],
                change_class="correctness-fix",
                reason="Fix a verified defect.",
                evidence_paths=["review.md"],
            )

            self.assertEqual(draft["status"], "pending")
            self.assertIsNone(draft["issuedAt"])
            self.assertIsNone(draft["expiresAt"])
            self.assertFalse(draft["review"]["completed"])
            self.assertIsNone(draft["review"]["reviewedAt"])
            self.assertEqual(
                draft["targets"],
                [{"slug": "demo-skill", "version": "1.0.2"}],
            )
            self.assertRegex(draft["contentDigest"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(
                draft["changeSetDigest"],
                r"^sha256:[0-9a-f]{64}$",
            )

            authorization_path = (
                root / CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH
            )
            write_json(authorization_path, draft)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "pending authorization"],
                cwd=root,
                check=True,
            )
            (
                observed_base,
                changed_paths,
                base_catalog,
                base_policy,
            ) = CHECK_MODULE.collect_git_inputs(
                root,
                base_commit,
                "HEAD",
                draft["candidateCommit"],
            )
            base_versions = CHECK_MODULE.load_base_versions(
                root,
                observed_base,
                base_catalog,
                {"demo-skill"},
            )
            now = datetime.now(timezone.utc)
            pending_result = CHECK_MODULE.evaluate(
                root,
                authorization_path,
                root / "metrics" / "observation-policy.json",
                changed_paths,
                base_catalog,
                base_policy,
                base_versions,
                observed_base,
                draft["candidateCommit"],
                "publish",
                now,
            )
            self.assertTrue(
                pending_result["valid"],
                pending_result["errors"],
            )
            self.assertFalse(pending_result["authorized"])
            self.assertIn(
                "authorization-not-approved",
                pending_result["blockingReasons"],
            )
            self.assertIn(
                "fresh-review",
                pending_result["blockingReasons"],
            )

            draft["status"] = "approved"
            draft["issuedAt"] = (now - timedelta(minutes=30)).isoformat()
            draft["expiresAt"] = (now + timedelta(hours=1)).isoformat()
            draft["review"]["completed"] = True
            draft["review"]["reviewedAt"] = (
                now - timedelta(hours=1)
            ).isoformat()
            write_json(authorization_path, draft)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "--amend", "--no-edit", "-q"],
                cwd=root,
                check=True,
            )
            (
                observed_base,
                changed_paths,
                base_catalog,
                base_policy,
            ) = CHECK_MODULE.collect_git_inputs(
                root,
                base_commit,
                "HEAD",
                draft["candidateCommit"],
            )
            result = CHECK_MODULE.evaluate(
                root,
                authorization_path,
                root / "metrics" / "observation-policy.json",
                changed_paths,
                base_catalog,
                base_policy,
                base_versions,
                observed_base,
                draft["candidateCommit"],
                "publish",
                now,
            )

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["authorized"], result)

    def test_preparer_requires_changed_evidence_and_formal_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            commit_release_candidate(root, change_evidence=False)
            with self.assertRaisesRegex(
                ValueError,
                "review evidence must change in the release diff",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "demo-skill-1.0.2",
                    ["publish"],
                    "correctness-fix",
                    "Fix a defect.",
                    ["review.md"],
                )

    def test_preparer_requires_version_bump_and_bound_release_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            skill_path = root / "skills" / "demo-skill" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8") + "\nNo bump.\n",
                encoding="utf-8",
            )
            (root / "review.md").write_text(
                "# Review\n\nNo version bump.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "no version bump"],
                cwd=root,
                check=True,
            )
            with self.assertRaisesRegex(
                ValueError,
                "release version must increase from base version",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "demo-skill-1.0.1",
                    ["dry-run"],
                    "correctness-fix",
                    "Fix a defect.",
                    ["review.md"],
                )

        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            commit_release_candidate(root)
            with self.assertRaisesRegex(
                ValueError,
                "releaseId must equal target slug and version",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "wrong-skill-9.9.9",
                    ["dry-run"],
                    "correctness-fix",
                    "Fix a defect.",
                    ["review.md"],
                )

    def test_preparer_rejects_multi_target_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root, catalog = make_repo(directory)
            base_commit = initialize_git(root)
            commit_release_candidate(root)
            second = root / "skills" / "second-skill"
            shutil.copytree(root / "skills" / "demo-skill", second)
            second_skill = second / "SKILL.md"
            second_skill.write_text(
                second_skill.read_text(encoding="utf-8")
                .replace("name: Demo Skill", "name: Second Skill", 1)
                .replace("slug: demo-skill", "slug: second-skill", 1)
                .replace("version: 1.0.2", "version: 1.0.0", 1),
                encoding="utf-8",
            )
            second_changelog = second / "CHANGELOG.md"
            second_changelog.write_text(
                "# Changelog\n\n## 1.0.0\n\n- Initial release.\n",
                encoding="utf-8",
            )
            catalog["skills/second-skill"] = {
                "displayName": "Second Skill",
                "categories": ["development"],
                "topics": ["release-automation"],
            }
            write_json(root / CHECK_MODULE.CATALOG_PATH, catalog)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "second target"],
                cwd=root,
                check=True,
            )
            with self.assertRaisesRegex(
                ValueError,
                "must target exactly one Skill",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "multi-target-release",
                    ["dry-run"],
                    "new-skill",
                    "Mixed release.",
                    ["review.md"],
                )

        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            (root / "review.md").write_text(
                "# Review\n\nOnly evidence changed.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "evidence only"],
                cwd=root,
                check=True,
            )
            with self.assertRaisesRegex(
                ValueError,
                "no formal Skill changes",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "demo-skill-1.0.1",
                    ["publish"],
                    "correctness-fix",
                    "Fix a defect.",
                    ["review.md"],
                )

    def test_preparer_refuses_protected_control_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            commit_release_candidate(root)
            workflow = root / ".github" / "workflows" / "publish.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: Changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "change control"],
                cwd=root,
                check=True,
            )

            with self.assertRaisesRegex(
                ValueError,
                "cannot modify protected control path",
            ):
                PREPARE_MODULE.prepare(
                    root,
                    base_commit,
                    "HEAD",
                    "demo-skill-1.0.2",
                    ["publish"],
                    "correctness-fix",
                    "Fix a defect.",
                    ["review.md"],
                )

    def test_preparer_atomic_write_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorization.json"
            PREPARE_MODULE.write_json_atomic(
                path,
                {"status": "pending"},
                force=False,
            )
            with self.assertRaisesRegex(
                ValueError,
                "already exists",
            ):
                PREPARE_MODULE.write_json_atomic(
                    path,
                    {"status": "pending"},
                    force=False,
                )
            PREPARE_MODULE.write_json_atomic(
                path,
                {"status": "replaced"},
                force=True,
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "replaced"},
            )

    def test_preparer_cli_writes_pending_draft_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            base_commit = initialize_git(root)
            commit_release_candidate(root)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(PREPARER),
                    "--repo-root",
                    str(root),
                    "--base",
                    base_commit,
                    "--release-id",
                    "demo-skill-1.0.2",
                    "--mode",
                    "dry-run",
                    "--change-class",
                    "correctness-fix",
                    "--reason",
                    "Fix a verified defect.",
                    "--evidence",
                    "review.md",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
            draft = json.loads(
                (
                    root / CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(result["prepared"])
        self.assertFalse(result["approved"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(draft["status"], "pending")
        self.assertFalse(draft["review"]["completed"])
        self.assertIsNone(draft["issuedAt"])
        self.assertIsNone(draft["expiresAt"])
        self.assertIsNone(draft["review"]["reviewedAt"])

    def test_preparer_cli_requires_explicit_mode(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(PREPARER),
                "--base",
                BASE_COMMIT,
                "--release-id",
                "demo-skill-1.0.1",
                "--change-class",
                "correctness-fix",
                "--reason",
                "Fix a verified defect.",
                "--evidence",
                "review.md",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("--mode", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_malformed_nested_values_return_structured_errors(self):
        mutations = (
            ("targets", {"slug": "demo-skill"}),
            ("modes", [{"mode": "publish"}]),
            ("review", []),
        )

        for field, value in mutations:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root, base_catalog = make_repo(directory)
                    authorization_path, authorization = make_authorization(
                        root,
                        base_catalog,
                    )
                    authorization[field] = value
                    write_json(authorization_path, authorization)
                    result = evaluate(
                        root,
                        base_catalog,
                        authorization_path,
                    )
                self.assertFalse(result["valid"])
                self.assertFalse(result["authorized"])
                self.assertTrue(result["errors"])

    def test_cli_uses_git_diff_and_rejects_later_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base_catalog = make_repo(directory)
            policy = {
                "schemaVersion": 1,
                "notBefore": "2020-01-01T00:00:00+00:00",
                "reason": "Completed test observation window.",
            }
            write_json(
                root / "metrics" / "observation-policy.json",
                policy,
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"],
                cwd=root,
                check=True,
            )
            base_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()

            skill_path = root / "skills" / "demo-skill" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "version: 1.0.1",
                    "version: 1.0.2",
                    1,
                )
                + "\nAuthorized.\n",
                encoding="utf-8",
            )
            changelog_path = root / "skills" / "demo-skill" / "CHANGELOG.md"
            changelog_path.write_text(
                changelog_path.read_text(encoding="utf-8").replace(
                    "# Changelog\n",
                    "# Changelog\n\n## 1.0.2\n\n- Authorized release.\n",
                    1,
                ),
                encoding="utf-8",
            )
            (root / "review.md").write_text(
                "# Review\n\nApproved for this release.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "release candidate"],
                cwd=root,
                check=True,
            )
            candidate_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            changed_paths = [
                CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
                "skills/demo-skill/SKILL.md",
                "skills/demo-skill/CHANGELOG.md",
                "review.md",
            ]
            authorization_path, authorization = make_authorization(
                root,
                base_catalog,
                changed_paths=changed_paths,
                baseCommit=base_commit,
                candidateCommit=candidate_commit,
                observationNotBefore=policy["notBefore"],
            )
            now = datetime.now(timezone.utc)
            authorization["issuedAt"] = (now - timedelta(hours=1)).isoformat()
            authorization["expiresAt"] = (now + timedelta(hours=1)).isoformat()
            authorization["review"]["reviewedAt"] = (
                now - timedelta(hours=2)
            ).isoformat()
            authorization["releaseId"] = "demo-skill-1.0.2"
            authorization["targets"][0]["version"] = "1.0.2"
            authorization["contentDigest"] = CHECK_MODULE.compute_content_digest(
                root,
                base_catalog,
                {"demo-skill"},
            )
            write_json(authorization_path, authorization)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "authorized release"],
                cwd=root,
                check=True,
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--repo-root",
                    str(root),
                    "--base",
                    base_commit,
                    "--mode",
                    "publish",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(result["authorized"], result)

            subprocess.run(
                ["git", "commit", "--allow-empty", "-qm", "later empty commit"],
                cwd=root,
                check=True,
            )
            replay = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--repo-root",
                    str(root),
                    "--base",
                    base_commit,
                    "--mode",
                    "publish",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            replay_result = json.loads(replay.stdout)

        self.assertEqual(replay.returncode, 2)
        self.assertFalse(replay_result["authorized"])
        self.assertIn(
            "head must contain exactly one authorization commit after candidate",
            replay_result["errors"][0],
        )
        self.assertNotIn("Traceback", replay.stderr)

    def test_git_collection_includes_type_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"],
                cwd=root,
                check=True,
            )
            base_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            validator = root / "scripts" / "validate_skill_catalog.py"
            replacement = root / "scripts" / "replacement.py"
            replacement.write_text("# replacement\n", encoding="utf-8")
            validator.unlink()
            validator.symlink_to(replacement)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "type change"],
                cwd=root,
                check=True,
            )

            _, changed_paths, _, _ = CHECK_MODULE.collect_git_inputs(
                root,
                base_commit,
                "HEAD",
            )

        self.assertIn(
            "scripts/validate_skill_catalog.py",
            changed_paths,
        )

    def test_git_collection_rejects_non_ancestor_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"],
                cwd=root,
                check=True,
            )
            common = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()

            (root / "head.txt").write_text("head\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "head"],
                cwd=root,
                check=True,
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()

            subprocess.run(
                ["git", "checkout", "-q", "--detach", common],
                cwd=root,
                check=True,
            )
            (root / "sibling.txt").write_text("sibling\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "sibling"],
                cwd=root,
                check=True,
            )
            sibling = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            subprocess.run(
                ["git", "checkout", "-q", "--detach", head],
                cwd=root,
                check=True,
            )

            with self.assertRaisesRegex(
                ValueError,
                "evaluated base must be an ancestor of head",
            ):
                CHECK_MODULE.collect_git_inputs(root, sibling, "HEAD")

    def test_production_cli_does_not_expose_clock_override(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--base",
                BASE_COMMIT,
                "--mode",
                "publish",
                "--now",
                AUTHORIZED_NOW.isoformat(),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("unrecognized arguments: --now", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-launch-checklist-example-vnext"
FIXTURE = RESEARCH / "launch-review-evidence.json"


class LaunchChecklistExampleResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_source_identifies_real_candidate_and_repair_commits(self):
        source = self.fixture["source"]

        self.assertEqual(
            source["candidateCommit"],
            "e806aec8cd69a4a885a065ac41fab59596664fda",
        )
        self.assertEqual(
            source["candidatePath"],
            "skills/clawhub-launch-checklist",
        )
        self.assertEqual(
            source["candidateName"],
            "clawhub-launch-checklist",
        )
        self.assertEqual(source["candidateVersion"], "1.0.0")
        self.assertEqual(
            source["repairCommit"],
            "33ead75f52ec36da2adf89f542425f2ed3cbd67b",
        )

    def test_review_blocks_protected_slug_even_when_package_is_complete(self):
        review = self.fixture["review"]
        blockers = review["blockingItems"]

        self.assertEqual(review["conclusion"], "先别发")
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["id"], "protected-slug-prefix")
        self.assertEqual(blockers[0]["severity"], "blocking")
        self.assertTrue(
            blockers[0]["observed"].startswith("clawhub-")
        )
        self.assertGreaterEqual(len(review["passedChecks"]), 9)

    def test_minimum_fix_matches_current_catalog_identity(self):
        fix = self.fixture["minimumFix"]
        catalog = json.loads(
            (
                ROOT / ".clawhub" / "skill-catalog.json"
            ).read_text(encoding="utf-8")
        )
        entry = catalog["skills/skill-launch-checklist"]

        self.assertEqual(fix["stableSlug"], "skill-launch-checklist")
        self.assertEqual(
            fix["displayName"],
            entry["displayName"],
        )
        self.assertEqual(
            fix["directory"]["to"],
            "skills/skill-launch-checklist",
        )
        self.assertTrue(fix["workflowGuardAdded"])

    def test_workflow_has_protected_slug_preflight(self):
        workflow = (
            ROOT / ".github" / "workflows" / "clawhub-skill-publish-local.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('slug.startswith("clawhub-")', workflow)
        self.assertIn('slug.endswith("-clawhub")', workflow)
        self.assertIn("protected ClawHub slug namespace", workflow)

    def test_next_command_uses_explicit_stable_slug_and_display_name(self):
        command = self.fixture["nextCommand"]

        self.assertEqual(command[:3], ["clawhub", "skill", "publish"])
        self.assertIn("--slug", command)
        self.assertEqual(
            command[command.index("--slug") + 1],
            "skill-launch-checklist",
        )
        self.assertIn("--name", command)
        self.assertEqual(
            command[command.index("--name") + 1],
            "Skill Launch Checklist",
        )
        self.assertIn("--dry-run", command)
        self.assertIn("--owner", command)

    def test_post_fix_state_does_not_fabricate_execution(self):
        state = self.fixture["postFixState"]
        claims = self.fixture["claims"]

        self.assertEqual(
            state["conclusionBeforeDryRun"],
            "基本可发",
        )
        self.assertFalse(state["dryRunExecutedByThisFixture"])
        self.assertFalse(state["publishedByThisFixture"])
        self.assertFalse(state["e4ProvenByThisFixture"])
        self.assertTrue(claims["protectedSlugBlockerConfirmed"])
        self.assertFalse(claims["completePackageAloneWasSufficient"])
        self.assertFalse(claims["downloadImpactConfirmed"])
        self.assertFalse(claims["searchImpactConfirmed"])

    def test_report_fulfills_launch_review_contract(self):
        report = (RESEARCH / "complete_launch_review.md").read_text(
            encoding="utf-8"
        )
        required = (
            "## 上线结论",
            "## 检查矩阵",
            "## 阻塞项",
            "## 漏项",
            "## 最小补法",
            "## 修复后状态",
            "## 下一步命令",
            "## 证据边界",
            "`先别发`",
            "`基本可发，等待 dry-run`",
            "--slug skill-launch-checklist",
            '--name "Skill Launch Checklist"',
            "dry-run 通过只证明候选可解析",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, report)

    def test_observation_policy_and_non_publishable_boundary(self):
        policy = json.loads(
            (ROOT / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        )
        catalog = json.loads(
            (
                ROOT / ".clawhub" / "skill-catalog.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            self.fixture["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertNotIn(
            "research/skill-launch-checklist-example-vnext",
            catalog,
        )


if __name__ == "__main__":
    unittest.main()

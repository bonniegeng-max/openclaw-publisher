import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-portfolio-growth-audit-vnext"
FIXTURE = RESEARCH / "decision-not-ready.json"
EXAMPLE = RESEARCH / "portfolio_decision_example.md"
POLICY = ROOT / "metrics" / "observation-policy.json"


class PortfolioGrowthAuditResearchTests(unittest.TestCase):
    def test_vnext_stays_outside_published_skill_and_catalog(self):
        catalog = json.loads(
            (ROOT / ".clawhub" / "skill-catalog.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertTrue(RESEARCH.is_dir())
        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertNotIn(
            "skill-portfolio-growth-audit-vnext",
            json.dumps(catalog),
        )

    def test_not_ready_fixture_matches_observation_policy(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        policy = json.loads(POLICY.read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["evidenceState"]["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertFalse(fixture["evidenceState"]["pairedDecisionReportPresent"])
        self.assertTrue(fixture["evidenceState"]["queryContractPresent"])
        self.assertFalse(fixture["decisionReady"])
        self.assertEqual(fixture["allowedOutcome"], "继续观察")

    def test_not_ready_fixture_covers_all_five_gates(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["gates"],
            {
                "evidenceQualityDecisionReady": "unknown",
                "collectionMethodConsistent": "unknown",
                "bothSnapshotsActiveInstallFalse": "unknown",
                "observationWindowAtLeastSevenDays": "unknown",
                "searchQueryLimitAndSetConsistent": "unknown",
            },
        )
        self.assertEqual(
            set(fixture["forbiddenPortfolioActions"]),
            {
                "加码",
                "修复定位",
                "合并",
                "停更",
                "新建 Skill",
                "启动 Plugin",
            },
        )

    def test_not_ready_fixture_contains_no_invented_adoption_metrics(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        serialized = json.dumps(fixture).lower()

        for field in ("downloads", "installs", "stars", "searchrank"):
            with self.subTest(field=field):
                self.assertNotIn(field, serialized)

    def test_candidate_example_enforces_not_ready_outcome(self):
        text = EXAMPLE.read_text(encoding="utf-8")

        for required in (
            "最终 `decisionReady: false`",
            "**继续观察。**",
            "`evidenceQuality.decisionReady`",
            "`activeInstall: false`",
            "快照间隔至少 7 天",
            "query、limit、query set 一致",
            "python3 scripts/run_clawhub_growth_monitor.py",
            "不得用虚构数字填充",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertNotIn("--force", text)


if __name__ == "__main__":
    unittest.main()

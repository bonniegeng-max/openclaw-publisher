import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "github-actions-clawhub-doctor-example-vnext"


def read(name):
    return (RESEARCH / name).read_text(encoding="utf-8")


class GitHubActionsDoctorResearchTests(unittest.TestCase):
    def test_fixture_uses_verified_incident_chain(self):
        fixture = json.loads(read("incident-evidence.json"))
        incident = fixture["incident"]

        self.assertEqual(
            incident["failedSourceCommit"],
            "77a4b1864655693b860f731dd2fd51e4c182cbd9",
        )
        self.assertEqual(incident["failedRunId"], 33870318104)
        self.assertEqual(incident["failedRunConclusion"], "failure")
        self.assertEqual(incident["failedStep"], "Run skill publishes")
        self.assertEqual(
            incident["repairSourceCommit"],
            "0a6ca43cc0ae519b5a6db6c601c11589a3fd2b2f",
        )
        self.assertEqual(incident["repairRunId"], 33871495707)
        self.assertEqual(incident["repairRunConclusion"], "success")

    def test_fixture_preserves_unknown_e3_e4_boundaries(self):
        fixture = json.loads(read("incident-evidence.json"))
        limits = fixture["evidenceLimits"]

        for key in (
            "failedArtifactPayloadAvailableInRepository",
            "exactFailedCliPayloadProven",
            "registryLatestProvenByThisFixture",
            "moderationCleanProvenByThisFixture",
            "independentInstallProvenByThisFixture",
        ):
            with self.subTest(key=key):
                self.assertFalse(limits[key])
        self.assertEqual(
            fixture["diagnosis"]["releaseEvidenceLevel"],
            "E2-only-after-repair-run",
        )
        self.assertGreaterEqual(len(fixture["forbiddenClaims"]), 4)

    def test_fixture_matches_current_observation_policy(self):
        fixture = json.loads(read("incident-evidence.json"))
        policy = json.loads(
            (ROOT / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            fixture["observationNotBefore"],
            policy["notBefore"],
        )

    def test_candidate_example_fulfills_doctor_output_contract(self):
        example = read("pending_publication_false_failure.md")
        for phrase in (
            "## 问题层级",
            "## 直接原因",
            "## 证据判断",
            "## 最小修复",
            "## 修复后验证",
            "pending-publication",
            "`UNKNOWN`",
            "`E2`",
            "E3",
            "E4",
            "moderation.verdict",
            "主动 inspect/install",
            "不得把 Actions success",
            "已上线、可下载",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, example)

    def test_research_draft_is_not_a_catalog_skill(self):
        catalog = json.loads(
            (ROOT / ".clawhub" / "skill-catalog.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn(
            "research/github-actions-clawhub-doctor-example-vnext",
            catalog,
        )
        self.assertFalse((RESEARCH / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()

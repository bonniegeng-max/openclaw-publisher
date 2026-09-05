import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "release-proof-builder-example-vnext"
FIXTURE = RESEARCH / "e4-evidence.json"
SOURCE = (
    ROOT
    / "release_evidence"
    / "2026-09-05-skill-publish-readiness-1.0.9.md"
)


class ReleaseProofExampleResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_subject_and_workflow_match_source_evidence(self):
        subject = self.fixture["subject"]
        e2 = self.fixture["evidenceMatrix"][2]["evidence"]

        self.assertEqual(subject["slug"], "skill-publish-readiness")
        self.assertEqual(subject["version"], "1.0.9")
        self.assertEqual(
            subject["sourceCommit"],
            "2748f047c26c57f9aa85c00a640ed0f5ae45db16",
        )
        self.assertEqual(e2["runId"], 33960781848)
        self.assertEqual(e2["conclusion"], "success")
        for value in (
            subject["slug"],
            subject["version"],
            subject["sourceCommit"],
            str(e2["runId"]),
        ):
            with self.subTest(value=value):
                self.assertIn(value, self.source)

    def test_matrix_is_complete_ordered_and_reaches_e4(self):
        matrix = self.fixture["evidenceMatrix"]

        self.assertEqual(
            [entry["level"] for entry in matrix],
            ["E0", "E1", "E2", "E3", "E4"],
        )
        self.assertTrue(
            all(
                entry["status"] in {"passed", "satisfied-as-foundation"}
                for entry in matrix
            )
        )
        self.assertEqual(self.fixture["maximumProvenLevel"], "E4")
        self.assertEqual(
            self.fixture["publicClaimAllowed"],
            "已上线、可下载使用",
        )

    def test_e3_and_e4_hashes_match_source_evidence(self):
        e3 = self.fixture["evidenceMatrix"][3]["evidence"]
        e4 = self.fixture["evidenceMatrix"][4]["evidence"]
        expected = {
            "SKILL.md": (
                "7c58bfda06af8dd89665f74cada953b17d0b0eca90765b5e9"
                "fffb077447210ac"
            ),
            "CHANGELOG.md": (
                "9c7fd6d7bbc63b3c0ec6586d0b88f5fa9275de116d5de2d2"
                "4d4a3d2ebfd76550"
            ),
            "references/security_review_guide.md": (
                "1b0ac936c0505ff30e8e1752cb0b3172fc24a452c687878aa"
                "50eaaca2d344cf9"
            ),
        }

        self.assertEqual(e3["moderationVerdict"], "clean")
        self.assertEqual(
            e3["registrySkillSha256"],
            e3["sourceSkillSha256"],
        )
        self.assertEqual(e4["coreFiles"], expected)
        for digest in expected.values():
            with self.subTest(digest=digest):
                self.assertIn(digest, self.source)

    def test_pollution_boundary_matches_policy_and_forbids_attribution(self):
        pollution = self.fixture["pollutionBoundary"]
        policy = json.loads(
            (ROOT / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            pollution["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertTrue(pollution["activeInstall"])
        self.assertFalse(
            pollution["naturalAdoptionAttributionAllowed"]
        )
        self.assertEqual(
            pollution["preInstallRawCounts"],
            {"downloads": 150, "installs": 1, "stars": 0},
        )

    def test_counterfactuals_cap_incomplete_evidence(self):
        counterfactuals = self.fixture["counterfactuals"]

        self.assertEqual(len(counterfactuals), 4)
        self.assertEqual(
            {item["maximumLevel"] for item in counterfactuals},
            {"E2", "E3"},
        )
        self.assertTrue(
            any(
                "moderation.verdict: clean" in item["missing"]
                and item["maximumLevel"] == "E2"
                for item in counterfactuals
            )
        )
        self.assertTrue(
            any(
                "specified-version isolated install" in item["missing"]
                and item["maximumLevel"] == "E3"
                for item in counterfactuals
            )
        )

    def test_report_fulfills_release_proof_output_contract(self):
        report = (RESEARCH / "verified_e4_release_report.md").read_text(
            encoding="utf-8"
        )
        required = (
            "## 发布结论",
            "## 当前证据等级",
            "## 已验证证据",
            "## Registry 与源码一致性",
            "## 安装与核心文件",
            "## E4 安装污染记录",
            "## 冲突信号",
            "## 缺失证据",
            "## 反事实降级",
            "## 下一步动作",
            "不重复安装 `1.0.9`",
            "不得归因为",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, report)

    def test_claims_are_version_bounded_and_research_is_not_publishable(self):
        claims = self.fixture["claims"]
        catalog = json.loads(
            (
                ROOT / ".clawhub" / "skill-catalog.json"
            ).read_text(encoding="utf-8")
        )

        self.assertTrue(claims["e4ProvenForSpecifiedVersion"])
        self.assertFalse(
            claims["e4AutomaticallyTransfersToFutureVersions"]
        )
        self.assertFalse(claims["naturalGrowthProven"])
        self.assertFalse(claims["repeatInstallRequired"])
        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertNotIn(
            "research/release-proof-builder-example-vnext",
            catalog,
        )


if __name__ == "__main__":
    unittest.main()

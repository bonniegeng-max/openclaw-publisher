import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-summary-rewriter-example-vnext"
FIXTURE = RESEARCH / "source-and-output.json"
EXPECTED_SOURCE = (
    "在发布到 ClawHub 之前，帮你揪出那些“能过 dry-run，但其实还不该发”的"
    "问题，包括文件缺失、版本不一致、环境声明脱节、安全风险和同质化定位。"
)


class SummaryRewriterExampleResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_source_is_specific_verified_repository_history(self):
        source = self.fixture["source"]

        self.assertEqual(source["type"], "git-history")
        self.assertEqual(
            source["commit"],
            "77a4b1864655693b860f731dd2fd51e4c182cbd9",
        )
        self.assertEqual(
            source["path"],
            "skills/skill-publish-readiness/SKILL.md",
        )
        self.assertEqual(source["version"], "1.0.0")
        self.assertEqual(source["field"], "description")
        self.assertEqual(source["text"], EXPECTED_SOURCE)

    def test_fixture_matches_observation_policy(self):
        policy = json.loads(
            (ROOT / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            self.fixture["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertEqual(
            self.fixture["status"],
            "observation-window-hold",
        )

    def test_output_contains_four_distinct_usable_candidates(self):
        candidates = self.fixture["candidates"]
        candidate_ids = {candidate["id"] for candidate in candidates}
        candidate_texts = {candidate["text"] for candidate in candidates}

        self.assertEqual(len(candidates), 4)
        self.assertEqual(candidate_ids, {"A", "B", "C", "D"})
        self.assertEqual(len(candidate_texts), 4)
        self.assertNotIn(EXPECTED_SOURCE, candidate_texts)
        for candidate in candidates:
            with self.subTest(candidate=candidate["id"]):
                self.assertTrue(candidate["placement"].strip())
                self.assertTrue(candidate["tradeoff"].strip())
                self.assertLessEqual(len(candidate["text"]), 120)

    def test_recommendation_is_unique_and_references_a_candidate(self):
        recommendation = self.fixture["recommendation"]
        candidate_ids = {
            candidate["id"] for candidate in self.fixture["candidates"]
        }

        self.assertIn(recommendation["candidateId"], candidate_ids)
        self.assertEqual(recommendation["candidateId"], "A")
        self.assertTrue(recommendation["reason"].strip())
        self.assertTrue(
            self.fixture["claims"]["uniqueRecommendationPresent"]
        )

    def test_example_fulfills_published_output_contract(self):
        example = (RESEARCH / "complete_summary_rewrite.md").read_text(
            encoding="utf-8"
        )
        required = (
            "## 原始摘要",
            "## 当前问题",
            "## 改写方向",
            "## 推荐版本",
            "### 版本 A",
            "### 版本 B",
            "### 版本 C",
            "### 版本 D",
            "## 最推荐版本",
            "## 使用建议",
            "ClawHub summary",
            "README 首段",
            "不能宣称搜索排名、下载或安装转化已经提升",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, example)

    def test_claims_do_not_turn_copy_quality_into_growth_evidence(self):
        claims = self.fixture["claims"]

        self.assertTrue(claims["sourceTextVerifiedInGitHistory"])
        self.assertTrue(claims["candidateCountMeetsContract"])
        self.assertTrue(claims["uniqueRecommendationPresent"])
        self.assertFalse(claims["platformABTestCompleted"])
        self.assertFalse(claims["downloadImpactConfirmed"])
        self.assertFalse(claims["searchImpactConfirmed"])

    def test_research_draft_is_not_publishable(self):
        catalog = json.loads(
            (
                ROOT / ".clawhub" / "skill-catalog.json"
            ).read_text(encoding="utf-8")
        )

        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertTrue((RESEARCH / "README.md").is_file())
        self.assertTrue(FIXTURE.is_file())
        self.assertNotIn(
            "research/skill-summary-rewriter-example-vnext",
            catalog,
        )


if __name__ == "__main__":
    unittest.main()

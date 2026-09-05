import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-positioning-audit-example-vnext"
FIXTURE = RESEARCH / "positioning-evidence.json"
CATALOG = ROOT / ".clawhub" / "skill-catalog.json"
PUBLISHED_EXAMPLE = (
    ROOT
    / "skills"
    / "skill-positioning-audit"
    / "examples"
    / "weak_vs_strong_positioning.md"
)


class PositioningExampleResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_source_conflict_exists_in_published_example(self):
        source = self.fixture["source"]
        published = PUBLISHED_EXAMPLE.read_text(encoding="utf-8")

        self.assertEqual(
            source["commit"],
            "6ce6d6d3d93c818dc8bba29f13493147e565f62b",
        )
        self.assertEqual(
            source["strongExampleTitle"],
            "skill-positioning-audit",
        )
        self.assertIn(
            "- 标题：`skill-positioning-audit`",
            published,
        )

    def test_authoritative_identity_matches_catalog_and_current_version(self):
        identity = self.fixture["authoritativeIdentity"]
        catalog_entry = self.catalog[identity["catalogKey"]]
        skill = (
            ROOT
            / "skills"
            / identity["stableSlug"]
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            identity["displayName"],
            catalog_entry["displayName"],
        )
        self.assertEqual(
            identity["displayName"],
            "Skill Positioning Audit",
        )
        self.assertEqual(
            identity["stableSlug"],
            "skill-positioning-audit",
        )
        self.assertIn("version: 1.0.4", skill)

    def test_recommended_title_is_human_readable_and_slug_stays_stable(self):
        identity = self.fixture["authoritativeIdentity"]
        copy = self.fixture["recommendedCopy"]

        self.assertEqual(copy["displayTitle"], identity["displayName"])
        self.assertEqual(copy["stableSlug"], identity["stableSlug"])
        self.assertNotEqual(copy["displayTitle"], copy["stableSlug"])
        self.assertNotIn("-", copy["displayTitle"])

    def test_rubric_has_five_dimensions_and_valid_totals(self):
        rubric = self.fixture["rubric"]
        dimensions = {
            "titleClarity",
            "summaryConversion",
            "audienceFocus",
            "differentiation",
            "trust",
        }

        for state in ("before", "candidate"):
            scores = rubric[state]
            self.assertEqual(set(scores) - {"total"}, dimensions)
            self.assertEqual(
                scores["total"],
                sum(scores[key] for key in dimensions),
            )
            self.assertLessEqual(scores["total"], rubric["maximumScore"])
        self.assertEqual(
            rubric["interpretation"],
            "editorial rubric, not platform performance",
        )

    def test_report_fulfills_positioning_output_contract(self):
        report = (RESEARCH / "complete_positioning_review.md").read_text(
            encoding="utf-8"
        )
        required = (
            "## 页面定位结论",
            "## 最大问题",
            "## 最小改法",
            "## 五维评估",
            "## 差异化判断",
            "## 推荐替换文案",
            "## 使用边界",
            "展示标题：Skill Positioning Audit",
            "稳定 slug：skill-positioning-audit",
            "不因展示名修复创建新产品",
            "不代表下载或安装提升",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, report)

    def test_claims_keep_editorial_fix_separate_from_growth(self):
        claims = self.fixture["claims"]

        self.assertTrue(claims["displayNameSlugConflictConfirmed"])
        self.assertTrue(claims["catalogDisplayNameConfirmed"])
        self.assertFalse(claims["platformABTestCompleted"])
        self.assertFalse(claims["downloadImpactConfirmed"])
        self.assertFalse(claims["searchImpactConfirmed"])

    def test_observation_policy_and_non_publishable_boundary(self):
        policy = json.loads(
            (ROOT / "metrics" / "observation-policy.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            self.fixture["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertNotIn(
            "research/skill-positioning-audit-example-vnext",
            self.catalog,
        )


if __name__ == "__main__":
    unittest.main()

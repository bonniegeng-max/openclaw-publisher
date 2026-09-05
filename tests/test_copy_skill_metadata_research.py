import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "copy-skills-runtime-metadata-vnext"
PLAN = RESEARCH / "change-plan.json"
POLICY = ROOT / "metrics" / "observation-policy.json"
TARGETS = {
    "skill-summary-rewriter": "1.0.2",
    "skill-positioning-audit": "1.0.4",
}


class CopySkillMetadataResearchTests(unittest.TestCase):
    def test_change_plan_matches_observation_policy_and_targets(self):
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        policy = json.loads(POLICY.read_text(encoding="utf-8"))

        self.assertEqual(plan["status"], "observation-window-hold")
        self.assertEqual(plan["observationNotBefore"], policy["notBefore"])
        self.assertEqual(
            {target["slug"]: target["currentVersion"] for target in plan["targets"]},
            TARGETS,
        )

    def test_targets_are_markdown_only_and_currently_declare_constraints(self):
        for slug, version in TARGETS.items():
            with self.subTest(slug=slug):
                skill_dir = ROOT / "skills" / slug
                files = [path for path in skill_dir.rglob("*") if path.is_file()]
                self.assertTrue(files)
                self.assertTrue(
                    all(
                        path.suffix == ".md" or path.name == ".clawhubignore"
                        for path in files
                    )
                )
                text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                self.assertRegex(text, rf"(?m)^version:\s*{re.escape(version)}$")
                self.assertIn("os: [macos]", text)
                self.assertIn("- git", text)
                self.assertIn("- clawhub", text)
                self.assertIn("package: clawhub", text)

    def test_plan_removes_only_runtime_constraints(self):
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        expected_remove = {
            "metadata.openclaw.os",
            "metadata.openclaw.requires",
            "metadata.openclaw.install",
        }
        expected_retain = {
            "metadata.openclaw.emoji",
            "metadata.openclaw.homepage",
        }

        for target in plan["targets"]:
            with self.subTest(slug=target["slug"]):
                self.assertEqual(set(target["remove"]), expected_remove)
                self.assertEqual(set(target["retain"]), expected_retain)

    def test_plan_separates_compatibility_fact_from_growth_hypothesis(self):
        plan = json.loads(PLAN.read_text(encoding="utf-8"))

        self.assertTrue(plan["claims"]["compatibilityRestrictionConfirmed"])
        self.assertFalse(plan["claims"]["downloadImpactConfirmed"])
        self.assertFalse(plan["claims"]["searchImpactConfirmed"])

    def test_vnext_is_not_a_publishable_skill(self):
        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertTrue((RESEARCH / "README.md").is_file())
        self.assertTrue(PLAN.is_file())


if __name__ == "__main__":
    unittest.main()

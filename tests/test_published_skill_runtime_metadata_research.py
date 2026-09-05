import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "published-skills-runtime-metadata-vnext"
PLAN = RESEARCH / "change-plan.json"
POLICY = ROOT / "metrics" / "observation-policy.json"
TEXT_ONLY_TARGETS = {
    "skill-summary-rewriter": "1.0.2",
    "skill-positioning-audit": "1.0.4",
}
CLI_TARGETS = {
    "github-actions-clawhub-doctor": "1.0.5",
    "release-proof-builder": "1.0.3",
    "skill-launch-checklist": "1.0.3",
    "skill-portfolio-growth-audit": "1.0.2",
    "skill-publish-readiness": "1.0.9",
}
MAC_SPECIFIC_MARKERS = (
    "osascript",
    "xattr",
    "plutil",
    "defaults ",
    "/Applications",
    "mdfind",
    "pbcopy",
    "pbpaste",
    "brew ",
)


class PublishedSkillRuntimeMetadataResearchTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.targets = {
            target["slug"]: target for target in self.plan["targets"]
        }

    def test_plan_matches_observation_policy_and_all_published_targets(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        expected = {**TEXT_ONLY_TARGETS, **CLI_TARGETS}

        self.assertEqual(self.plan["status"], "observation-window-hold")
        self.assertEqual(
            self.plan["observationNotBefore"],
            policy["notBefore"],
        )
        self.assertEqual(
            {
                slug: target["currentVersion"]
                for slug, target in self.targets.items()
            },
            expected,
        )

    def test_current_targets_are_markdown_only_and_mac_restricted(self):
        for slug, version in {**TEXT_ONLY_TARGETS, **CLI_TARGETS}.items():
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
                combined = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in files
                    if path.suffix == ".md"
                )
                self.assertRegex(
                    combined,
                    rf"(?m)^version:\s*{re.escape(version)}$",
                )
                self.assertIn("os: [macos]", combined)
                for marker in MAC_SPECIFIC_MARKERS:
                    self.assertNotIn(marker.lower(), combined.lower())

    def test_text_only_targets_remove_all_runtime_constraints(self):
        expected_remove = {
            "metadata.openclaw.os",
            "metadata.openclaw.requires",
            "metadata.openclaw.install",
        }
        expected_retain = {
            "metadata.openclaw.emoji",
            "metadata.openclaw.homepage",
        }

        for slug in TEXT_ONLY_TARGETS:
            target = self.targets[slug]
            with self.subTest(slug=slug):
                self.assertEqual(target["profile"], "text-only")
                self.assertEqual(set(target["remove"]), expected_remove)
                self.assertEqual(set(target["retain"]), expected_retain)

    def test_cli_targets_add_only_verified_linux_eligibility(self):
        expected_retain = {
            "metadata.openclaw.requires",
            "metadata.openclaw.install",
            "metadata.openclaw.emoji",
            "metadata.openclaw.homepage",
        }

        for slug in CLI_TARGETS:
            target = self.targets[slug]
            os_change = target["replace"]["metadata.openclaw.os"]
            with self.subTest(slug=slug):
                self.assertEqual(target["profile"], "cli-backed")
                self.assertEqual(os_change["from"], ["macos"])
                self.assertEqual(os_change["to"], ["macos", "linux"])
                self.assertNotIn("windows", os_change["to"])
                self.assertEqual(set(target["retain"]), expected_retain)

    def test_linux_toolchain_evidence_matches_repository_workflow(self):
        workflow = (
            ROOT / ".github" / "workflows" / "clawhub-skill-publish-local.yml"
        ).read_text(encoding="utf-8")
        evidence = self.plan["evidence"]

        self.assertEqual(evidence["linuxWorkflowRunner"], "ubuntu-latest")
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("Install ClawHub CLI dependencies", workflow)
        self.assertIn('"git"', workflow)
        self.assertIn('"bun"', workflow)
        self.assertEqual(evidence["macSpecificCommandMatches"], [])

    def test_plan_separates_eligibility_facts_from_growth_claims(self):
        claims = self.plan["claims"]

        self.assertTrue(claims["macOnlyRestrictionConfirmed"])
        self.assertTrue(claims["linuxToolchainConfirmed"])
        self.assertTrue(
            claims["textOnlyBinaryRequirementMismatchConfirmed"]
        )
        self.assertFalse(claims["windowsCompatibilityConfirmed"])
        self.assertFalse(claims["downloadImpactConfirmed"])
        self.assertFalse(claims["searchImpactConfirmed"])

    def test_plan_keeps_release_and_e4_bounded(self):
        release_policy = self.plan["releasePolicy"]

        self.assertFalse(
            release_policy["publishDuringObservationWindow"]
        )
        self.assertFalse(release_policy["publishAllTargetsByDefault"])
        self.assertTrue(release_policy["requireFreshNeedReview"])
        self.assertEqual(
            release_policy["maxPlannedE4InstallsPerChangedVersion"],
            1,
        )
        self.assertTrue(release_policy["resetObservationStartAfterE4"])

    def test_vnext_is_not_publishable_and_old_subset_is_retired(self):
        audit = (
            ROOT / "research" / "published-skill-static-audit-2026-09-05.md"
        ).read_text(encoding="utf-8")

        self.assertFalse((RESEARCH / "SKILL.md").exists())
        self.assertTrue((RESEARCH / "README.md").is_file())
        self.assertTrue(PLAN.is_file())
        self.assertIn(
            "research/published-skills-runtime-metadata-vnext/",
            audit,
        )
        self.assertNotIn("copy-skills-runtime-metadata-vnext", audit)
        self.assertFalse(
            (
                ROOT
                / "research"
                / "copy-skills-runtime-metadata-vnext"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()

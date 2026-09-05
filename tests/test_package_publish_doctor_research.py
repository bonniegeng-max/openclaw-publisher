import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "research" / "package-publish-doctor" / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PackagePublishDoctorResearchTests(unittest.TestCase):
    def test_research_pack_has_three_distinct_cases(self):
        fixtures = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(FIXTURES.glob("*.json"))
        ]

        self.assertEqual(len(fixtures), 3)
        self.assertEqual(len({fixture["id"] for fixture in fixtures}), 3)
        self.assertEqual(
            {fixture["expected"]["layer"] for fixture in fixtures},
            {"pack", "family-detection", "upload"},
        )

    def test_npm_pack_fixture_preserves_both_output_shapes(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        npm11 = fixture["input"]["npm11"]
        npm12 = fixture["input"]["npm12"]

        self.assertIsInstance(npm11, list)
        self.assertIsInstance(npm12, dict)
        self.assertEqual(
            npm11[0]["filename"],
            next(iter(npm12.values()))["filename"],
        )
        self.assertTrue(fixture["input"]["artifactExists"])
        self.assertEqual(
            fixture["expected"]["diagnosis"],
            "NPM_PACK_JSON_SHAPE",
        )

    def test_bundle_fixture_has_markers_without_native_manifest(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        files = set(fixture["input"]["files"])

        self.assertIn(".codex-plugin/plugin.json", files)
        self.assertIn(".claude-plugin/plugin.json", files)
        self.assertFalse(fixture["input"]["openclawPluginManifestPresent"])
        self.assertTrue(fixture["expected"]["requiresMaintainerDecision"])
        self.assertEqual(
            fixture["expected"]["diagnosis"],
            "BUNDLE_NATIVE_MANIFEST_CONTRACT",
        )

    def test_clawpack_fixture_captures_staging_gap(self):
        fixture = load_fixture("clawpack-staging-gap.json")
        values = fixture["input"]

        self.assertGreater(
            values["artifactBytes"],
            values["publicEdgeBudgetBytes"],
        )
        self.assertLess(
            values["artifactBytes"],
            values["legacyStagingThresholdBytes"],
        )
        self.assertFalse(fixture["affected"]["releaseContainsFix"])
        self.assertTrue(fixture["affected"]["mainContainsFix"])
        self.assertEqual(
            fixture["expected"]["diagnosis"],
            "CLAWPACK_STAGING_GAP",
        )


if __name__ == "__main__":
    unittest.main()

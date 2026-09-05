import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "package-publish-doctor"
FIXTURES = RESEARCH / "fixtures"

SPEC = importlib.util.spec_from_file_location(
    "package_publish_doctor_diagnose",
    RESEARCH / "diagnose.py",
)
DIAGNOSE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSE_MODULE)
diagnose = DIAGNOSE_MODULE.diagnose


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PackagePublishDoctorResearchTests(unittest.TestCase):
    def test_research_pack_has_four_distinct_cases(self):
        fixtures = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(FIXTURES.glob("*.json"))
        ]

        self.assertEqual(len(fixtures), 4)
        self.assertEqual(len({fixture["id"] for fixture in fixtures}), 4)
        self.assertEqual(
            {fixture["expected"]["layer"] for fixture in fixtures},
            {"pack", "family-detection", "upload", "workflow-permission"},
        )

    def test_all_fixtures_match_their_expected_diagnosis(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                result = diagnose(fixture)
                self.assertTrue(result["matched"])
                self.assertEqual(
                    result["diagnosis"],
                    fixture["expected"]["diagnosis"],
                )
                self.assertEqual(
                    result["layer"],
                    fixture["expected"]["layer"],
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

    def test_permission_fixture_requires_missing_actions_read(self):
        fixture = load_fixture("reusable-workflow-actions-read.json")
        self.assertEqual(
            diagnose(fixture)["diagnosis"],
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
        )

        already_fixed = copy.deepcopy(fixture)
        already_fixed["input"]["callerPermissions"]["actions"] = "read"
        self.assertEqual(diagnose(already_fixed)["diagnosis"], "UNKNOWN")

    def test_generic_413_is_not_misclassified_as_staging_gap(self):
        fixture = load_fixture("clawpack-staging-gap.json")
        below_edge_limit = copy.deepcopy(fixture)
        below_edge_limit["input"]["artifactBytes"] = 1024

        self.assertEqual(diagnose(below_edge_limit)["diagnosis"], "UNKNOWN")

    def test_missing_manifest_for_code_plugin_is_not_bundle_contract_case(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        code_plugin = copy.deepcopy(fixture)
        code_plugin["affected"]["family"] = "code-plugin"

        self.assertEqual(diagnose(code_plugin)["diagnosis"], "UNKNOWN")

    def test_missing_tarball_does_not_match_json_shape_case(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        no_artifact = copy.deepcopy(fixture)
        no_artifact["input"]["artifactExists"] = False

        self.assertEqual(diagnose(no_artifact)["diagnosis"], "UNKNOWN")

    def test_unknown_case_stays_unknown(self):
        result = diagnose(
            {
                "id": "unrecognized",
                "input": {"reportedError": "unexpected failure"},
            }
        )

        self.assertFalse(result["matched"])
        self.assertEqual(result["diagnosis"], "UNKNOWN")
        self.assertEqual(result["confidence"], "low")


if __name__ == "__main__":
    unittest.main()

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
    def test_research_pack_has_distinct_extensible_package_cases(self):
        paths = sorted(FIXTURES.glob("*.json"))
        fixtures = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in paths
        ]
        baseline_names = {
            "npm-pack-json-shape.json",
            "bundle-native-manifest-contract.json",
            "clawpack-staging-gap.json",
            "reusable-workflow-actions-read.json",
            "package-release-scan-stalled.json",
            "trusted-publish-tag-ref-regression.json",
            "package-security-audit-fields-missing.json",
        }

        self.assertTrue(baseline_names.issubset({path.name for path in paths}))
        self.assertEqual(len({fixture["id"] for fixture in fixtures}), len(fixtures))
        self.assertTrue(
            all(fixture["input"]["surface"] == "package" for fixture in fixtures)
        )
        self.assertTrue(
            {
                "pack",
                "family-detection",
                "upload",
                "workflow-permission",
                "moderation",
                "source-resolution",
                "verification",
            }.issubset(
                {fixture["expected"]["layer"] for fixture in fixtures}
            )
        )
        self.assertTrue(
            {
                fixture["expected"]["layer"] for fixture in fixtures
            }.issubset(DIAGNOSE_MODULE.EXECUTABLE_RULE_LAYERS)
        )

    def test_rule_coverage_distinguishes_classification_only_layers(self):
        self.assertEqual(
            DIAGNOSE_MODULE.CLASSIFICATION_ONLY_LAYERS,
            {"inspector", "index"},
        )
        self.assertEqual(
            DIAGNOSE_MODULE.FAILURE_LAYERS,
            DIAGNOSE_MODULE.EXECUTABLE_RULE_LAYERS
            | DIAGNOSE_MODULE.CLASSIFICATION_ONLY_LAYERS,
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
                self.assertEqual(
                    result["versionStatus"],
                    fixture["expected"]["versionStatus"],
                )
                self.assertEqual(result["missingEvidence"], [])

    def test_npm_pack_fixture_preserves_both_output_shapes(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        npm11 = fixture["input"]["npm11"]
        npm12 = fixture["input"]["npm12"]

        self.assertEqual(fixture["input"]["clawhubVersion"], "0.23.1")
        self.assertEqual(fixture["input"]["npmVersion"], "12.x")
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

        self.assertEqual(fixture["input"]["clawhubVersion"], "0.23.3")
        self.assertEqual(fixture["input"]["family"], "bundle-plugin")
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
        self.assertEqual(
            values["workflowRef"],
            "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3",
        )
        self.assertEqual(
            values["artifactHash"],
            values["inspector"]["artifactHash"],
        )
        self.assertEqual(values["inspector"]["status"], "success")
        self.assertEqual(
            fixture["expected"]["diagnosis"],
            "CLAWPACK_STAGING_GAP",
        )

    def test_clawpack_staging_gap_requires_success_for_same_artifact(self):
        fixture = load_fixture("clawpack-staging-gap.json")

        missing = copy.deepcopy(fixture)
        del missing["input"]["inspector"]
        self.assertEqual(diagnose(missing)["diagnosis"], "UNKNOWN")

        failed = copy.deepcopy(fixture)
        failed["input"]["inspector"]["status"] = "failed"
        self.assertEqual(diagnose(failed)["diagnosis"], "UNKNOWN")

        mismatched = copy.deepcopy(fixture)
        mismatched["input"]["inspector"]["artifactHash"] = "sha256:different"
        self.assertEqual(diagnose(mismatched)["diagnosis"], "UNKNOWN")

        local_success = copy.deepcopy(missing)
        local_success["input"]["localValidation"] = {
            "status": "passed",
            "artifactHash": local_success["input"]["artifactHash"],
        }
        self.assertEqual(
            diagnose(local_success)["diagnosis"],
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

        wrong_workflow = copy.deepcopy(fixture)
        wrong_workflow["input"]["workflowRef"] = (
            "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.2"
        )
        self.assertEqual(diagnose(wrong_workflow)["diagnosis"], "UNKNOWN")

    def test_version_bounded_rules_reject_other_cli_versions(self):
        npm_fixture = load_fixture("npm-pack-json-shape.json")
        npm_fixture["input"]["clawhubVersion"] = "0.23.2"
        self.assertEqual(diagnose(npm_fixture)["diagnosis"], "UNKNOWN")

        npm_fixture = load_fixture("npm-pack-json-shape.json")
        npm_fixture["input"]["npmVersion"] = "11.6.2"
        self.assertEqual(diagnose(npm_fixture)["diagnosis"], "UNKNOWN")

        bundle_fixture = load_fixture("bundle-native-manifest-contract.json")
        bundle_fixture["input"]["clawhubVersion"] = "0.23.2"
        self.assertEqual(diagnose(bundle_fixture)["diagnosis"], "UNKNOWN")

    def test_stalled_release_only_matches_affected_package_version(self):
        fixture = load_fixture("package-release-scan-stalled.json")
        self.assertEqual(
            diagnose(fixture)["diagnosis"],
            "PACKAGE_RELEASE_SCAN_STALLED",
        )

        fixed_release = copy.deepcopy(fixture)
        fixed_release["input"]["clawhubVersion"] = "0.23.2"
        self.assertEqual(diagnose(fixed_release)["diagnosis"], "UNKNOWN")

        short_wait = copy.deepcopy(fixture)
        short_wait["input"]["pendingHours"] = 2
        self.assertEqual(diagnose(short_wait)["diagnosis"], "UNKNOWN")

    def test_skill_surface_is_never_classified_as_package_failure(self):
        fixture = load_fixture("package-release-scan-stalled.json")
        fixture["input"]["surface"] = "skill"

        result = diagnose(fixture)

        self.assertEqual(result["diagnosis"], "UNKNOWN")
        self.assertEqual(result["missingEvidence"], ["input.surface=package"])

    def test_trusted_tag_ref_rule_preserves_candidate_mode_boundary(self):
        fixture = load_fixture("trusted-publish-tag-ref-regression.json")
        result = diagnose(fixture)
        self.assertEqual(result["diagnosis"], "TRUSTED_PUBLISH_TAG_REF_REGRESSION")
        self.assertEqual(result["versionStatus"], "source-reproduced-at-commit")
        self.assertEqual(
            fixture["input"]["sourceValidatorCommit"],
            "845c6d3bdb1a36573d8d28be2a8fb85a3c476720",
        )

        candidate_mode = copy.deepcopy(fixture)
        candidate_mode["input"]["candidateShaPresent"] = True
        self.assertEqual(diagnose(candidate_mode)["diagnosis"], "UNKNOWN")

        mismatched_commit = copy.deepcopy(fixture)
        mismatched_commit["input"]["sourceCommit"] = "b" * 40
        self.assertEqual(diagnose(mismatched_commit)["diagnosis"], "UNKNOWN")

    def test_trusted_tag_ref_rule_requires_source_comparison_evidence(self):
        fixture = load_fixture("trusted-publish-tag-ref-regression.json")

        rejected_only = copy.deepcopy(fixture)
        del rejected_only["input"]["sourceValidatorCommit"]
        del rejected_only["input"]["sourceValidationComparison"]
        self.assertTrue(rejected_only["input"]["rejected"])
        self.assertEqual(diagnose(rejected_only)["diagnosis"], "UNKNOWN")

        wrong_commit = copy.deepcopy(fixture)
        wrong_commit["input"]["sourceValidatorCommit"] = "b" * 40
        self.assertEqual(diagnose(wrong_commit)["diagnosis"], "UNKNOWN")

        wrong_comparison = copy.deepcopy(fixture)
        wrong_comparison["input"]["sourceValidationComparison"]["right"] = (
            "source.commit"
        )
        self.assertEqual(diagnose(wrong_comparison)["diagnosis"], "UNKNOWN")

    def test_security_fields_rule_keeps_fail_closed_boundary(self):
        fixture = load_fixture("package-security-audit-fields-missing.json")
        self.assertEqual(
            diagnose(fixture)["diagnosis"],
            "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING",
        )

        blocked_release = copy.deepcopy(fixture)
        blocked_release["input"]["trust"]["blockedFromDownload"] = True
        self.assertEqual(diagnose(blocked_release)["diagnosis"], "UNKNOWN")

        complete_response = copy.deepcopy(fixture)
        complete_response["input"]["overview"] = "Clean package audit"
        complete_response["input"]["securityAuditUrl"] = (
            "https://clawhub.ai/example/plugins/example/security-audit"
        )
        self.assertEqual(diagnose(complete_response)["diagnosis"], "UNKNOWN")

    def test_generic_413_is_not_misclassified_as_staging_gap(self):
        fixture = load_fixture("clawpack-staging-gap.json")
        below_edge_limit = copy.deepcopy(fixture)
        below_edge_limit["input"]["artifactBytes"] = 1024

        self.assertEqual(diagnose(below_edge_limit)["diagnosis"], "UNKNOWN")

    def test_missing_manifest_for_code_plugin_is_not_bundle_contract_case(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        code_plugin = copy.deepcopy(fixture)
        code_plugin["input"]["family"] = "code-plugin"

        self.assertEqual(diagnose(code_plugin)["diagnosis"], "UNKNOWN")

    def test_missing_tarball_does_not_match_json_shape_case(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        no_artifact = copy.deepcopy(fixture)
        no_artifact["input"]["artifactExists"] = False

        self.assertEqual(diagnose(no_artifact)["diagnosis"], "UNKNOWN")

    def test_conflicting_layers_without_failure_sequence_are_unknown(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        fixture["input"].update(
            {
                "workflowRef": (
                    "openclaw/clawhub/.github/workflows/"
                    "package-publish.yml@v0.23.3"
                ),
                "jobsCreated": 0,
                "callerPermissions": {
                    "contents": "read",
                    "id-token": "write",
                },
                "reportedError": (
                    "openclaw.plugin.json required; "
                    "nested job is requesting 'actions: read'"
                ),
            }
        )

        result = diagnose(fixture)

        self.assertEqual(result["diagnosis"], "UNKNOWN")
        self.assertIn("input.failureSequence", result["missingEvidence"][0])
        self.assertIn(
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
            result["evidence"][0],
        )
        self.assertIn("BUNDLE_NATIVE_MANIFEST_CONTRACT", result["evidence"][0])

    def test_failure_sequence_selects_first_matching_layer(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        fixture["input"].update(
            {
                "workflowRef": (
                    "openclaw/clawhub/.github/workflows/"
                    "package-publish.yml@v0.23.3"
                ),
                "jobsCreated": 0,
                "callerPermissions": {
                    "contents": "read",
                    "id-token": "write",
                },
                "reportedError": (
                    "openclaw.plugin.json required; "
                    "nested job is requesting 'actions: read'"
                ),
                "failureSequence": [
                    "workflow-permission",
                    "family-detection",
                ],
            }
        )

        result = diagnose(fixture)

        self.assertEqual(
            result["diagnosis"],
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
        )
        self.assertEqual(result["layer"], "workflow-permission")

    def test_matching_never_depends_on_affected_metadata(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                poisoned = copy.deepcopy(fixture)
                poisoned["affected"] = {
                    "clawhub": "99.99.99",
                    "npm": "1.x",
                    "workflow": "wrong",
                    "family": "wrong",
                    "fixedIn": "0.0.0",
                    "serverCommit": "wrong",
                    "currentMainContainsRegression": False,
                    "fixMerged": False,
                    "deploymentVerified": True,
                }
                self.assertEqual(
                    diagnose(poisoned)["diagnosis"],
                    fixture["expected"]["diagnosis"],
                )

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
        self.assertEqual(result["versionStatus"], "unknown")
        self.assertTrue(result["missingEvidence"])


if __name__ == "__main__":
    unittest.main()

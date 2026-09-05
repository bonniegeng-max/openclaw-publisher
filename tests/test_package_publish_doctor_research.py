import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "package-publish-doctor"
FIXTURES = RESEARCH / "fixtures"
OUTPUT_FIELDS = {
    "matched",
    "caseId",
    "diagnosis",
    "conclusion",
    "layer",
    "confidence",
    "versionStatus",
    "observedContext",
    "evidence",
    "recommendation",
    "rejectedShortcuts",
    "verificationSteps",
    "doNotClaim",
    "missingEvidence",
    "source",
}
EXPECTED_CONCLUSIONS = {
    "TRUSTED_PUBLISH_TAG_REF_REGRESSION": "blocked",
    "REUSABLE_WORKFLOW_ACTIONS_PERMISSION": "blocked",
    "NPM_PACK_JSON_SHAPE": "blocked",
    "BUNDLE_NATIVE_MANIFEST_CONTRACT": "blocked",
    "CLAWPACK_STAGING_GAP": "blocked",
    "PACKAGE_RELEASE_SCAN_STALLED": "partial",
    "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING": "published-unverified",
}
OBSERVED_CONTEXT_FIELDS = {
    "clawhubVersion",
    "npmVersion",
    "workflowRef",
    "family",
    "sourceValidatorCommit",
    "sourceCommit",
}

SPEC = importlib.util.spec_from_file_location(
    "package_publish_doctor_diagnose",
    RESEARCH / "draft" / "scripts" / "diagnose.py",
)
DIAGNOSE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSE_MODULE)
diagnose = DIAGNOSE_MODULE.diagnose


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PackagePublishDoctorResearchTests(unittest.TestCase):
    def assert_output_schema(self, result):
        self.assertEqual(set(result), OUTPUT_FIELDS)
        self.assertIsInstance(result["matched"], bool)
        self.assertTrue(
            result["caseId"] is None or isinstance(result["caseId"], str)
        )
        self.assertTrue(
            result["source"] is None or isinstance(result["source"], str)
        )
        for field in (
            "diagnosis",
            "conclusion",
            "layer",
            "confidence",
            "versionStatus",
            "recommendation",
        ):
            self.assertIsInstance(result[field], str)
        self.assertIsInstance(result["observedContext"], dict)
        for field in (
            "evidence",
            "rejectedShortcuts",
            "verificationSteps",
            "doNotClaim",
            "missingEvidence",
        ):
            self.assertIsInstance(result[field], list)
            self.assertTrue(
                all(isinstance(item, str) for item in result[field])
            )

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
                self.assert_output_schema(result)
                self.assertEqual(
                    result["conclusion"],
                    fixture["expected"]["conclusion"],
                )
                self.assertEqual(
                    result["conclusion"],
                    EXPECTED_CONCLUSIONS[result["diagnosis"]],
                )
                self.assertTrue(result["rejectedShortcuts"])
                self.assertTrue(result["verificationSteps"])
                self.assertTrue(result["doNotClaim"])
                guidance = DIAGNOSE_MODULE.DIAGNOSIS_GUIDANCE[
                    result["diagnosis"]
                ]
                self.assertEqual(
                    result["rejectedShortcuts"],
                    guidance["rejectedShortcuts"],
                )
                self.assertEqual(
                    result["verificationSteps"],
                    guidance["verificationSteps"],
                )
                self.assertEqual(result["doNotClaim"], guidance["doNotClaim"])
                self.assertIsInstance(result["observedContext"], dict)
                self.assertTrue(
                    set(result["observedContext"]).issubset(
                        OBSERVED_CONTEXT_FIELDS
                    )
                )
                self.assertEqual(result["missingEvidence"], [])

    def test_observed_context_is_a_strict_non_sensitive_allowlist(self):
        fixture = load_fixture("trusted-publish-tag-ref-regression.json")
        fixture["input"].update(
            {
                "accessToken": "secret",
                "authorization": "Bearer secret",
                "repository": "private/repository",
                "privateUrl": "https://private.example.invalid/evidence",
            }
        )

        context = diagnose(fixture)["observedContext"]

        self.assertEqual(
            set(context),
            {"sourceValidatorCommit", "sourceCommit"},
        )
        self.assertNotIn("secret", json.dumps(context))

    def test_observed_context_rejects_sensitive_values_in_allowlisted_fields(self):
        result = diagnose(
            {
                "id": {"not": "a string"},
                "source": ["not", "a string"],
                "input": {
                    "surface": "package",
                    "clawhubVersion": "secret-token",
                    "npmVersion": "Bearer secret",
                    "workflowRef": "private/repository/.github/workflows/x.yml@main",
                    "family": "private-account",
                    "sourceValidatorCommit": "not-a-commit",
                    "sourceCommit": "authorization-secret",
                },
            }
        )

        self.assert_output_schema(result)
        self.assertEqual(result["observedContext"], {})
        self.assertIsNone(result["caseId"])
        self.assertIsNone(result["source"])

    def test_workflow_context_omits_owner_and_repository(self):
        fixture = load_fixture("reusable-workflow-actions-read.json")

        context = diagnose(fixture)["observedContext"]

        self.assertEqual(
            context,
            {"workflowRef": "package-publish.yml@v0.23.3"},
        )

    def test_version_context_is_normalized_instead_of_copied(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        fixture["input"]["npmVersion"] = "12.0.0+owner-private-repository"

        result = diagnose(fixture)

        self.assertTrue(result["matched"])
        self.assertEqual(
            result["observedContext"],
            {"clawhubVersion": "0.23.1", "npmVersion": "12.x"},
        )
        self.assertNotIn("private", json.dumps(result["observedContext"]))

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

    def test_security_fields_rule_matches_each_malformed_required_field(self):
        fixture = load_fixture("package-security-audit-fields-missing.json")
        valid_values = {
            "overview": "Clean package audit",
            "securityAuditUrl": (
                "https://clawhub.ai/example/plugins/example/security-audit"
            ),
        }
        for field in ("overview", "securityAuditUrl"):
            for invalid_value in (None, "", "   ", 123, []):
                with self.subTest(field=field, invalid_value=invalid_value):
                    candidate = copy.deepcopy(fixture)
                    candidate["input"].update(valid_values)
                    candidate["input"][field] = invalid_value
                    candidate["input"]["reportedError"] = (
                        "Malformed ClawHub security response: "
                        f"expected {field} to be a non-empty string."
                    )
                    self.assertEqual(
                        diagnose(candidate)["diagnosis"],
                        "PACKAGE_SECURITY_AUDIT_FIELDS_MISSING",
                    )

    def test_security_fields_rule_requires_matching_error_and_clean_trust(self):
        fixture = load_fixture("package-security-audit-fields-missing.json")

        unrelated_error = copy.deepcopy(fixture)
        unrelated_error["input"]["reportedError"] = "request timed out"
        self.assertEqual(diagnose(unrelated_error)["diagnosis"], "UNKNOWN")

        nonempty_reasons = copy.deepcopy(fixture)
        nonempty_reasons["input"]["trust"]["reasons"] = ["manual review"]
        self.assertEqual(diagnose(nonempty_reasons)["diagnosis"], "UNKNOWN")

        wrong_endpoint = copy.deepcopy(fixture)
        wrong_endpoint["input"]["exactReleaseSecurityEndpoint"] = False
        self.assertEqual(diagnose(wrong_endpoint)["diagnosis"], "UNKNOWN")

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

    def test_npm_pack_shape_requires_one_matching_nonempty_filename(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        mutations = {
            "empty npm11 array": ("npm11", []),
            "empty npm12 object": ("npm12", {}),
            "npm11 entry missing filename": (
                "npm11",
                [{"id": "my-plugin@0.4.0"}],
            ),
            "npm12 entry missing filename": (
                "npm12",
                {"my-plugin": {"id": "my-plugin@0.4.0"}},
            ),
            "npm12 filename blank": (
                "npm12",
                {"my-plugin": {"filename": "   "}},
            ),
            "npm12 entry wrong type": ("npm12", {"my-plugin": []}),
            "npm11 entry wrong type": ("npm11", [[]]),
            "npm11 filename blank": ("npm11", [{"filename": "   "}]),
            "multiple npm11 entries": (
                "npm11",
                [
                    {"filename": "first.tgz"},
                    {"filename": "second.tgz"},
                ],
            ),
            "multiple npm12 entries": (
                "npm12",
                {
                    "first": {"filename": "first.tgz"},
                    "second": {"filename": "second.tgz"},
                },
            ),
            "mismatched filename": (
                "npm12",
                {"my-plugin": {"filename": "different.tgz"}},
            ),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(fixture)
                candidate["input"][field] = value
                self.assertEqual(diagnose(candidate)["diagnosis"], "UNKNOWN")

    def test_diagnose_rejects_input_contract_errors(self):
        invalid_cases = [
            ([], "top-level JSON value must be an object"),
            ({}, "required field 'input' is missing"),
            ({"input": None}, "field 'input' must be an object"),
            ({"input": []}, "field 'input' must be an object"),
        ]
        for case, message in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    DIAGNOSE_MODULE.InputContractError,
                    message,
                ):
                    diagnose(case)

    def test_malformed_rule_fields_degrade_to_unknown_without_exceptions(self):
        candidates = []

        bundle = load_fixture("bundle-native-manifest-contract.json")
        bundle["input"]["files"] = [{}]
        candidates.append(bundle)

        permissions = load_fixture("reusable-workflow-actions-read.json")
        permissions["input"]["callerPermissions"] = ["actions: none"]
        candidates.append(permissions)

        for actions_value in (None, False, 0, [], {}):
            nested_permissions = load_fixture(
                "reusable-workflow-actions-read.json"
            )
            nested_permissions["input"]["callerPermissions"]["actions"] = (
                actions_value
            )
            candidates.append(nested_permissions)

        security = load_fixture("package-security-audit-fields-missing.json")
        security["input"]["trust"] = ["clean"]
        candidates.append(security)

        trusted = load_fixture("trusted-publish-tag-ref-regression.json")
        trusted["input"]["tokenSha"] = 123
        candidates.append(trusted)

        staging = load_fixture("clawpack-staging-gap.json")
        staging["input"]["artifactBytes"] = True
        candidates.append(staging)

        stalled = load_fixture("package-release-scan-stalled.json")
        stalled["input"]["pendingHours"] = True
        candidates.append(stalled)

        stalled_infinite = load_fixture("package-release-scan-stalled.json")
        stalled_infinite["input"]["pendingHours"] = float("inf")
        candidates.append(stalled_infinite)

        stalled_release_id = load_fixture("package-release-scan-stalled.json")
        stalled_release_id["input"]["releaseId"] = ["not", "a", "string"]
        candidates.append(stalled_release_id)

        numeric_version = load_fixture("npm-pack-json-shape.json")
        numeric_version["input"]["npmVersion"] = 12
        candidates.append(numeric_version)

        object_error = load_fixture("npm-pack-json-shape.json")
        object_error["input"]["reportedError"] = {
            "message": "npm pack did not return a tarball filename"
        }
        candidates.append(object_error)

        for candidate in candidates:
            with self.subTest(case_id=candidate["id"]):
                self.assertEqual(diagnose(candidate)["diagnosis"], "UNKNOWN")

    def test_rule_fields_are_total_over_json_value_types(self):
        replacements = [
            None,
            False,
            True,
            0,
            1,
            1.5,
            "",
            "unexpected",
            [],
            [{}],
            {},
        ]
        for path in sorted(FIXTURES.glob("*.json")):
            fixture = json.loads(path.read_text(encoding="utf-8"))
            for field in sorted(fixture["input"]):
                for replacement in replacements:
                    with self.subTest(
                        fixture=path.name,
                        field=field,
                        replacement=repr(replacement),
                    ):
                        candidate = copy.deepcopy(fixture)
                        candidate["input"][field] = replacement
                        self.assert_output_schema(diagnose(candidate))

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
        self.assert_output_schema(result)
        self.assertEqual(result["conclusion"], "partial")
        self.assertEqual(len(result["missingEvidence"]), 1)
        self.assertEqual(
            result["missingEvidence"][0],
            result["verificationSteps"][0],
        )
        self.assertTrue(result["rejectedShortcuts"])
        self.assertTrue(result["doNotClaim"])
        self.assertEqual(result["observedContext"], {})


if __name__ == "__main__":
    unittest.main()

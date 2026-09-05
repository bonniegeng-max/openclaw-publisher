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
RULE_REQUIRED_PATHS = {
    "trusted-publish-tag-ref-regression.json": [
        ("input", "surface"),
        ("input", "publishMode"),
        ("input", "candidateShaPresent"),
        ("input", "rejected"),
        ("input", "rejectionStage"),
        ("input", "sourceValidationOutcome"),
        ("input", "sourceValidatorCommit"),
        ("input", "sourceValidationComparison", "left"),
        ("input", "sourceValidationComparison", "operator"),
        ("input", "sourceValidationComparison", "right"),
        ("input", "tokenSha"),
        ("input", "tokenRef"),
        ("input", "sourceCommit"),
        ("input", "sourceRef"),
    ],
    "reusable-workflow-actions-read.json": [
        ("input", "surface"),
        ("input", "workflowRef"),
        ("input", "jobsCreated"),
        ("input", "effectiveCallerPermissions", "actions"),
        ("input", "reportedError"),
    ],
    "npm-pack-json-shape.json": [
        ("input", "surface"),
        ("input", "command"),
        ("input", "clawhubVersion"),
        ("input", "npmVersion"),
        ("input", "npm11", 0, "id"),
        ("input", "npm11", 0, "filename"),
        ("input", "npm12", "my-plugin", "id"),
        ("input", "npm12", "my-plugin", "filename"),
        ("input", "artifactExists"),
        ("input", "artifactFilename"),
        ("input", "reportedError"),
    ],
    "bundle-native-manifest-contract.json": [
        ("input", "surface"),
        ("input", "clawhubVersion"),
        ("input", "family"),
        ("input", "filesObservationComplete"),
        ("input", "files"),
        ("input", "openclawPluginManifestPresent"),
        ("input", "reportedError"),
    ],
    "clawpack-staging-gap.json": [
        ("input", "surface"),
        ("input", "workflowRef"),
        ("input", "uploadTarget"),
        ("input", "registry"),
        ("input", "artifactBytes"),
        ("input", "artifactHash"),
        ("input", "inspector", "status"),
        ("input", "inspector", "artifactHash"),
        ("input", "reportedStatus"),
        ("input", "reportedError"),
    ],
    "package-release-scan-stalled.json": [
        ("input", "surface"),
        ("input", "clawhubVersion"),
        ("input", "family"),
        ("input", "publishAccepted"),
        ("input", "releaseId"),
        ("input", "scanStatus"),
        ("input", "pendingHours"),
        ("input", "latestRelease"),
        ("input", "inspectVisible"),
        ("input", "duplicateOnRepublish"),
    ],
    "package-security-audit-fields-missing.json": [
        ("input", "surface"),
        ("input", "family"),
        ("input", "stage"),
        ("input", "releaseVersion"),
        ("input", "securityReleaseVersion"),
        ("input", "publicationStatus"),
        ("input", "exactReleaseSecurityEndpoint"),
        ("input", "trust", "blockedFromDownload"),
        ("input", "trust", "pending"),
        ("input", "trust", "stale"),
        ("input", "trust", "scanStatus"),
        ("input", "trust", "reasons"),
        ("input", "reportedError"),
    ],
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


def delete_path(value, path):
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    del cursor[path[-1]]


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

    def test_draft_runtime_metadata_matches_offline_python_entrypoint(self):
        skill = (
            RESEARCH / "draft" / "SKILL.md"
        ).read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1]
        metadata = frontmatter.split("metadata:", 1)[1]

        self.assertIn("version: 0.1.13", frontmatter)
        self.assertIn("        - python3", metadata)
        self.assertNotIn("    os:", metadata)
        self.assertNotIn("        - git", metadata)
        self.assertNotIn("        - clawhub", metadata)
        self.assertNotIn("    install:", metadata)

    def test_linux_ci_covers_the_offline_entrypoint(self):
        workflow = (
            ROOT / ".github" / "workflows" / "metrics-tools-ci.yml"
        ).read_text(encoding="utf-8")
        readme = (RESEARCH / "README.md").read_text(encoding="utf-8")

        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn('python-version: "3.11"', workflow)
        self.assertIn(
            "research/package-publish-doctor/draft/scripts/*.py",
            workflow,
        )
        self.assertIn("真实运行依赖只有", readme)
        self.assertIn("`python3`", readme)
        self.assertIn("不等于 Windows 已验证", readme)

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

    def test_runtime_required_field_catalog_matches_mutation_contract(self):
        fixture_by_diagnosis = {
            load_fixture(name)["expected"]["diagnosis"]: name
            for name in RULE_REQUIRED_PATHS
        }
        self.assertEqual(
            set(DIAGNOSE_MODULE.RULE_REQUIRED_INPUT_PATHS),
            set(fixture_by_diagnosis),
        )
        for diagnosis, fixture_name in fixture_by_diagnosis.items():
            expected_paths = set()
            for path in RULE_REQUIRED_PATHS[fixture_name]:
                if path == ("input", "surface"):
                    continue
                normalized = list(path[1:])
                if normalized[:1] == ["npm12"] and len(normalized) > 2:
                    normalized[1] = "*"
                expected_paths.add(tuple(normalized))
            self.assertEqual(
                set(DIAGNOSE_MODULE.RULE_REQUIRED_INPUT_PATHS[diagnosis]),
                expected_paths,
            )
            self.assertEqual(
                DIAGNOSE_MODULE.RULE_REQUIRED_INPUT_PATH_VARIANTS[diagnosis][0],
                DIAGNOSE_MODULE.RULE_REQUIRED_INPUT_PATHS[diagnosis],
            )

        staging_variants = (
            DIAGNOSE_MODULE.RULE_REQUIRED_INPUT_PATH_VARIANTS[
                "CLAWPACK_STAGING_GAP"
            ]
        )
        self.assertEqual(len(staging_variants), 2)
        self.assertIn(("inspector", "status"), staging_variants[0])
        self.assertIn(("inspector", "artifactHash"), staging_variants[0])
        self.assertNotIn(("localValidation", "status"), staging_variants[0])
        self.assertIn(("localValidation", "status"), staging_variants[1])
        self.assertIn(("localValidation", "artifactHash"), staging_variants[1])
        self.assertNotIn(("inspector", "status"), staging_variants[1])

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

    def test_known_public_sources_are_preserved(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    diagnose(fixture)["source"],
                    fixture["source"],
                )

    def test_unsafe_source_references_are_omitted(self):
        unsafe_sources = (
            "https://github.com/openclaw/clawhub/issues/3275?token=secret",
            "https://github.com/openclaw/clawhub/issues/3275#private",
            "https://user:secret@github.com/openclaw/clawhub/issues/3275",
            "http://github.com/openclaw/clawhub/issues/3275",
            "https://private.example.invalid/evidence",
            "https://github.com/private-owner/private-repo/issues/1",
            "Bearer secret",
            "redacted local observation secret",
        )
        for source in unsafe_sources:
            with self.subTest(source=source):
                fixture = load_fixture("reusable-workflow-actions-read.json")
                fixture["source"] = source
                self.assertIsNone(diagnose(fixture)["source"])

    def test_only_exact_safe_local_source_label_is_preserved(self):
        fixture = load_fixture("reusable-workflow-actions-read.json")
        fixture["source"] = "redacted local observation"

        self.assertEqual(
            diagnose(fixture)["source"],
            "redacted local observation",
        )

    def test_workflow_context_omits_owner_and_repository(self):
        fixture = load_fixture("reusable-workflow-actions-read.json")

        context = diagnose(fixture)["observedContext"]

        self.assertEqual(
            context,
            {"workflowRef": "package-publish.yml@v0.23.3"},
        )

    def test_version_context_is_normalized_instead_of_copied(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        fixture["input"]["npmVersion"] = "v12.0.0"

        result = diagnose(fixture)

        self.assertTrue(result["matched"])
        self.assertEqual(
            result["observedContext"],
            {"clawhubVersion": "0.23.1", "npmVersion": "12.x"},
        )

        metadata = load_fixture("npm-pack-json-shape.json")
        metadata["input"]["npmVersion"] = "12.0.0+owner-private-repository"
        self.assertEqual(diagnose(metadata)["diagnosis"], "UNKNOWN")

    def test_npm_pack_fixture_preserves_both_output_shapes(self):
        fixture = load_fixture("npm-pack-json-shape.json")
        npm11 = fixture["input"]["npm11"]
        npm12 = fixture["input"]["npm12"]

        self.assertEqual(fixture["input"]["clawhubVersion"], "0.23.1")
        self.assertEqual(fixture["input"]["npmVersion"], "12.x")
        self.assertEqual(
            fixture["input"]["command"],
            "clawhub package publish",
        )
        self.assertIsInstance(npm11, list)
        self.assertIsInstance(npm12, dict)
        self.assertEqual(
            npm11[0]["filename"],
            next(iter(npm12.values()))["filename"],
        )
        self.assertEqual(
            npm11[0]["id"],
            next(iter(npm12.values()))["id"],
        )
        self.assertEqual(
            fixture["input"]["artifactFilename"],
            npm11[0]["filename"],
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
        self.assertTrue(fixture["input"]["filesObservationComplete"])
        self.assertNotIn("openclaw.plugin.json", files)
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
            DIAGNOSE_MODULE.PUBLIC_EDGE_BUDGET_BYTES,
        )
        self.assertLess(
            values["artifactBytes"],
            DIAGNOSE_MODULE.LEGACY_STAGING_THRESHOLD_BYTES,
        )
        self.assertEqual(values["uploadTarget"], "clawhub-public-edge")
        self.assertEqual(values["registry"], "https://clawhub.ai")
        self.assertEqual(
            values["workflowRef"],
            "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.3",
        )
        self.assertEqual(
            values["artifactHash"],
            values["inspector"]["artifactHash"],
        )
        self.assertEqual(values["inspector"]["status"], "success")
        self.assertRegex(values["artifactHash"], r"^sha256:[0-9a-f]{64}$")
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

    def test_local_validation_variant_returns_exact_missing_evidence(self):
        candidate = load_fixture("clawpack-staging-gap.json")
        del candidate["input"]["inspector"]
        candidate["input"]["localValidation"] = {
            "status": "passed",
            "artifactHash": candidate["input"]["artifactHash"],
        }

        missing_error = copy.deepcopy(candidate)
        del missing_error["input"]["reportedError"]
        self.assertEqual(
            diagnose(missing_error)["missingEvidence"],
            [
                "补充并核验 input.reportedError；"
                "当前证据仍不足以确定根因"
            ],
        )

        missing_hash = copy.deepcopy(candidate)
        del missing_hash["input"]["localValidation"]["artifactHash"]
        self.assertEqual(
            diagnose(missing_hash)["missingEvidence"],
            [
                "补充并核验 input.localValidation.artifactHash；"
                "当前证据仍不足以确定根因"
            ],
        )

    def test_permission_fixture_requires_missing_actions_read(self):
        fixture = load_fixture("reusable-workflow-actions-read.json")
        self.assertEqual(
            diagnose(fixture)["diagnosis"],
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
        )

        already_fixed = copy.deepcopy(fixture)
        already_fixed["input"]["effectiveCallerPermissions"]["actions"] = "read"
        self.assertEqual(diagnose(already_fixed)["diagnosis"], "UNKNOWN")

        wrong_workflow = copy.deepcopy(fixture)
        wrong_workflow["input"]["workflowRef"] = (
            "openclaw/clawhub/.github/workflows/package-publish.yml@v0.23.2"
        )
        self.assertEqual(diagnose(wrong_workflow)["diagnosis"], "UNKNOWN")

        malformed_effective_permissions = copy.deepcopy(fixture)
        malformed_effective_permissions["input"][
            "effectiveCallerPermissions"
        ] = {"actions": False}
        self.assertEqual(
            diagnose(malformed_effective_permissions)["diagnosis"],
            "UNKNOWN",
        )

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

        unsupported_older_release = copy.deepcopy(fixture)
        unsupported_older_release["input"]["clawhubVersion"] = "0.23.0"
        self.assertEqual(
            diagnose(unsupported_older_release)["diagnosis"],
            "UNKNOWN",
        )

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

        wrong_outcome = copy.deepcopy(fixture)
        wrong_outcome["input"]["sourceValidationOutcome"] = (
            "authentication-failed"
        )
        self.assertEqual(diagnose(wrong_outcome)["diagnosis"], "UNKNOWN")

        wrong_stage = copy.deepcopy(fixture)
        wrong_stage["input"]["rejectionStage"] = "authentication"
        self.assertEqual(diagnose(wrong_stage)["diagnosis"], "UNKNOWN")

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

        unpublished = copy.deepcopy(fixture)
        unpublished["input"]["publicationStatus"] = "draft"
        self.assertEqual(diagnose(unpublished)["diagnosis"], "UNKNOWN")

    def test_generic_413_is_not_misclassified_as_staging_gap(self):
        fixture = load_fixture("clawpack-staging-gap.json")
        below_edge_limit = copy.deepcopy(fixture)
        below_edge_limit["input"]["artifactBytes"] = 1024

        self.assertEqual(diagnose(below_edge_limit)["diagnosis"], "UNKNOWN")

        caller_defined_thresholds = copy.deepcopy(fixture)
        caller_defined_thresholds["input"]["artifactBytes"] = 2
        caller_defined_thresholds["input"]["publicEdgeBudgetBytes"] = 1
        caller_defined_thresholds["input"]["legacyStagingThresholdBytes"] = 3
        self.assertEqual(
            diagnose(caller_defined_thresholds)["diagnosis"],
            "UNKNOWN",
        )

        invalid_hash = copy.deepcopy(fixture)
        invalid_hash["input"]["artifactHash"] = "same"
        invalid_hash["input"]["inspector"]["artifactHash"] = "same"
        self.assertEqual(diagnose(invalid_hash)["diagnosis"], "UNKNOWN")

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
        permissions["input"]["effectiveCallerPermissions"] = ["actions: none"]
        candidates.append(permissions)

        for actions_value in (None, False, 0, [], {}):
            nested_permissions = load_fixture(
                "reusable-workflow-actions-read.json"
            )
            nested_permissions["input"]["effectiveCallerPermissions"][
                "actions"
            ] = actions_value
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

    def test_deleting_any_declared_required_evidence_returns_unknown(self):
        self.assertEqual(
            set(RULE_REQUIRED_PATHS),
            {path.name for path in FIXTURES.glob("*.json")},
        )
        for fixture_name, required_paths in RULE_REQUIRED_PATHS.items():
            fixture = load_fixture(fixture_name)
            self.assertTrue(diagnose(fixture)["matched"])
            for required_path in required_paths:
                with self.subTest(
                    fixture=fixture_name,
                    required_path=required_path,
                ):
                    candidate = copy.deepcopy(fixture)
                    delete_path(candidate, required_path)
                    result = diagnose(candidate)
                    self.assertFalse(result["matched"])
                    self.assertEqual(result["diagnosis"], "UNKNOWN")

    def test_single_missing_required_field_returns_exact_next_evidence(self):
        for fixture_name, required_paths in RULE_REQUIRED_PATHS.items():
            fixture = load_fixture(fixture_name)
            for required_path in required_paths:
                if required_path == ("input", "surface"):
                    continue
                with self.subTest(
                    fixture=fixture_name,
                    required_path=required_path,
                ):
                    candidate = copy.deepcopy(fixture)
                    delete_path(candidate, required_path)
                    result = diagnose(candidate)
                    input_path = list(required_path[1:])
                    if input_path[:1] == ["npm12"] and len(input_path) > 2:
                        input_path[1] = "*"
                    expected_path = "input"
                    for key in input_path:
                        expected_path += (
                            f"[{key}]" if isinstance(key, int) else f".{key}"
                        )

                    self.assertEqual(result["diagnosis"], "UNKNOWN")
                    self.assertEqual(
                        result["missingEvidence"],
                        [
                            f"补充并核验 {expected_path}；"
                            "当前证据仍不足以确定根因"
                        ],
                    )
                    self.assertEqual(
                        result["verificationSteps"][0],
                        result["missingEvidence"][0],
                    )

    def test_ambiguous_near_matches_do_not_guess_one_missing_field(self):
        candidate = load_fixture("reusable-workflow-actions-read.json")
        del candidate["input"]["reportedError"]
        bundle = load_fixture("bundle-native-manifest-contract.json")
        for field, value in bundle["input"].items():
            if field not in {"surface", "reportedError"}:
                candidate["input"][field] = copy.deepcopy(value)

        result = diagnose(candidate)

        self.assertEqual(result["diagnosis"], "UNKNOWN")
        self.assertEqual(
            result["missingEvidence"],
            ["可同时证明首个失败层和对应 CLI/workflow 版本的最小状态组合"],
        )

    def test_invalid_present_value_is_not_reported_as_missing(self):
        candidate = load_fixture("reusable-workflow-actions-read.json")
        candidate["input"]["effectiveCallerPermissions"]["actions"] = "write"

        result = diagnose(candidate)

        self.assertEqual(result["diagnosis"], "UNKNOWN")
        self.assertEqual(
            result["missingEvidence"],
            ["可同时证明首个失败层和对应 CLI/workflow 版本的最小状态组合"],
        )

    def test_semantically_contradictory_evidence_returns_unknown(self):
        bundle = load_fixture("bundle-native-manifest-contract.json")
        bundle["input"]["files"].append("openclaw.plugin.json")
        self.assertEqual(diagnose(bundle)["diagnosis"], "UNKNOWN")

        trusted = load_fixture("trusted-publish-tag-ref-regression.json")
        trusted["input"]["tokenRef"] = "refs/heads/main"
        trusted["input"]["sourceRef"] = "refs/heads/main"
        self.assertEqual(diagnose(trusted)["diagnosis"], "UNKNOWN")

        staging = load_fixture("clawpack-staging-gap.json")
        staging["input"]["uploadTarget"] = "private-proxy"
        self.assertEqual(diagnose(staging)["diagnosis"], "UNKNOWN")

        staging = load_fixture("clawpack-staging-gap.json")
        staging["input"]["registry"] = "https://private-proxy.example"
        self.assertEqual(diagnose(staging)["diagnosis"], "UNKNOWN")

        security = load_fixture("package-security-audit-fields-missing.json")
        security["input"]["publicationStatus"] = "draft"
        self.assertEqual(diagnose(security)["diagnosis"], "UNKNOWN")

        security = load_fixture("package-security-audit-fields-missing.json")
        security["input"]["securityReleaseVersion"] = "2.1.3"
        self.assertEqual(diagnose(security)["diagnosis"], "UNKNOWN")

        npm = load_fixture("npm-pack-json-shape.json")
        npm["input"]["npm12"]["my-plugin"]["id"] = "other-plugin@9.9.9"
        self.assertEqual(diagnose(npm)["diagnosis"], "UNKNOWN")

        npm = load_fixture("npm-pack-json-shape.json")
        npm["input"]["artifactFilename"] = "stale-artifact.tgz"
        self.assertEqual(diagnose(npm)["diagnosis"], "UNKNOWN")

    def test_versions_require_one_optional_v_prefix_and_exact_scope(self):
        for fixture_name in (
            "npm-pack-json-shape.json",
            "bundle-native-manifest-contract.json",
            "package-release-scan-stalled.json",
        ):
            fixture = load_fixture(fixture_name)
            fixture["input"]["clawhubVersion"] = "vv0.23.1"
            self.assertEqual(diagnose(fixture)["diagnosis"], "UNKNOWN")

        stalled = load_fixture("package-release-scan-stalled.json")
        stalled["input"]["clawhubVersion"] = "0.1.0"
        self.assertEqual(diagnose(stalled)["diagnosis"], "UNKNOWN")

        for noncanonical in ("00.23.1", "0.023.01", "v00.23.001"):
            with self.subTest(clawhub_version=noncanonical):
                stalled = load_fixture("package-release-scan-stalled.json")
                stalled["input"]["clawhubVersion"] = noncanonical
                self.assertEqual(diagnose(stalled)["diagnosis"], "UNKNOWN")

        for noncanonical in ("012.x", "v012.0.0"):
            with self.subTest(npm_version=noncanonical):
                npm = load_fixture("npm-pack-json-shape.json")
                npm["input"]["npmVersion"] = noncanonical
                self.assertEqual(diagnose(npm)["diagnosis"], "UNKNOWN")

    def test_security_error_names_the_exact_invalid_field(self):
        fixture = load_fixture("package-security-audit-fields-missing.json")
        fixture["input"]["reportedError"] = (
            "Malformed ClawHub security response: expected overviewish "
            "to be a non-empty string."
        )
        self.assertEqual(diagnose(fixture)["diagnosis"], "UNKNOWN")

    def test_conflicting_layers_without_failure_sequence_are_unknown(self):
        fixture = load_fixture("bundle-native-manifest-contract.json")
        fixture["input"].update(
            {
                "workflowRef": (
                    "openclaw/clawhub/.github/workflows/"
                    "package-publish.yml@v0.23.3"
                ),
                "jobsCreated": 0,
                "effectiveCallerPermissions": {
                    "actions": "none",
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
                "effectiveCallerPermissions": {
                    "actions": "none",
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

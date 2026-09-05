import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "package-publish-doctor"
CONTRACT = RESEARCH / "promotion-contract.json"
CHECKER = RESEARCH / "check_promotion_contract.py"

SPEC = importlib.util.spec_from_file_location(
    "package_doctor_promotion_check",
    CHECKER,
)
CHECK_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_MODULE)


def make_staged_repo(directory, contract, target=True, catalog=True):
    root = Path(directory)
    (root / "metrics").mkdir(parents=True)
    (root / ".clawhub").mkdir(parents=True)
    shutil.copy2(
        ROOT / "metrics" / "observation-policy.json",
        root / "metrics" / "observation-policy.json",
    )

    source = root / contract["candidate"]["sourceDirectory"]
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(RESEARCH / "draft", source)

    catalog_value = {}
    if target:
        target_path = root / contract["candidate"]["targetDirectory"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(RESEARCH / "draft", target_path)
        skill_path = target_path / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(
            skill_text.replace(
                f"version: {contract['candidate']['draftVersion']}",
                (
                    "version: "
                    f"{contract['candidate']['proposedFirstReleaseVersion']}"
                ),
                1,
            ),
            encoding="utf-8",
        )
    if catalog:
        catalog_value[contract["candidate"]["targetDirectory"]] = copy.deepcopy(
            contract["catalogEntry"]
        )
    (root / ".clawhub" / "skill-catalog.json").write_text(
        json.dumps(catalog_value),
        encoding="utf-8",
    )
    contract_path = root / "promotion-contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return root, contract_path


def complete_release_gate_support(contract):
    for gate in contract["releaseGates"]:
        gate["state"] = "complete"
    contract["evidence"].update(
        {
            "latestOfficialReleaseReconfirmed": True,
            "clawhubCompetitorSearchComplete": True,
            "dryRunComplete": True,
            "registryModerationClean": True,
            "e4Complete": True,
        }
    )
    contract["claims"].update(
        {
            "publishedConfirmed": True,
            "downloadableConfirmed": True,
        }
    )


class PackageDoctorPromotionCheckTests(unittest.TestCase):
    def test_current_contract_is_valid_but_blocked(self):
        result = CHECK_MODULE.evaluate(
            ROOT,
            CONTRACT,
            datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["contractStatus"], "blocked")
        self.assertIn("observation-window", result["blockingGates"])
        self.assertIn(
            "same-method-clawhub-competitor-search",
            result["blockingGates"],
        )
        self.assertFalse(
            result["localEvidence"]["observationWindowElapsed"]
        )
        self.assertFalse(
            result["localEvidence"]["observationGateReleased"]
        )
        self.assertTrue(
            result["localEvidence"]["requiredDraftFilesPresent"]
        )
        self.assertTrue(
            result["localEvidence"]["draftIdentityMatchesContract"]
        )
        self.assertTrue(result["localEvidence"]["stableSlugAllowed"])
        self.assertTrue(
            result["localEvidence"]["firstReleaseVersionValid"]
        )
        self.assertTrue(result["localEvidence"]["dryRunCommandValid"])
        self.assertTrue(result["localEvidence"]["catalogCandidateValid"])
        self.assertFalse(
            result["localEvidence"]["formalTargetDirectoryPresent"]
        )
        self.assertFalse(
            result["localEvidence"]["formalCatalogEntryPresent"]
        )
        self.assertTrue(
            result["localEvidence"]["absentFromFormalSurfacesDuringHold"]
        )
        self.assertTrue(result["localEvidence"]["releasePolicyValid"])
        self.assertEqual(result["errors"], [])

    def test_elapsed_time_does_not_auto_complete_external_gates(self):
        result = CHECK_MODULE.evaluate(
            ROOT,
            CONTRACT,
            datetime(2026, 9, 13, tzinfo=timezone.utc),
        )

        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertTrue(
            result["localEvidence"]["observationWindowElapsed"]
        )
        self.assertFalse(
            result["localEvidence"]["observationGateReleased"]
        )
        self.assertIn("observation-window", result["blockingGates"])
        self.assertIn(
            "fresh-official-version-review",
            result["blockingGates"],
        )

    def test_default_cli_reports_blocked_without_failing(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--repo-root",
                str(ROOT),
                "--now",
                "2026-09-05T00:00:00+00:00",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(completed.stderr, "")

    def test_require_complete_returns_one_for_valid_blocked_contract(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--repo-root",
                str(ROOT),
                "--now",
                "2026-09-05T00:00:00+00:00",
                "--require-complete",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(completed.stderr, "")

    def test_all_complete_gates_cannot_bypass_declared_status(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        complete_release_gate_support(contract)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["blockingGates"], ["contract-status"])

    def test_complete_gates_require_corresponding_evidence_and_claims(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        original["status"] = "complete"
        complete_release_gate_support(original)
        mutations = (
            (
                "evidence",
                "latestOfficialReleaseReconfirmed",
                "fresh-official-version-review",
            ),
            (
                "evidence",
                "clawhubCompetitorSearchComplete",
                "same-method-clawhub-competitor-search",
            ),
            ("evidence", "completeDraftPackage", "local-tests"),
            ("evidence", "offlineExecutable", "local-tests"),
            ("evidence", "dryRunComplete", "explicit-slug-name-dry-run"),
            ("claims", "publishedConfirmed", "authorized-publish"),
            (
                "evidence",
                "registryModerationClean",
                "registry-moderation-check",
            ),
            ("evidence", "e4Complete", "single-version-e4"),
            ("claims", "downloadableConfirmed", "single-version-e4"),
        )

        for document, field, gate_id in mutations:
            with self.subTest(document=document, field=field, gate=gate_id):
                contract = copy.deepcopy(original)
                contract[document][field] = False
                with tempfile.TemporaryDirectory() as directory:
                    root, path = make_staged_repo(directory, contract)
                    result = CHECK_MODULE.evaluate(
                        root,
                        path,
                        datetime(2026, 9, 13, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertIn(
                    (
                        f"release gate {gate_id} is complete without "
                        f"{document}.{field}=true"
                    ),
                    result["errors"],
                )

    def test_evidence_and_claims_must_be_objects(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))

        for field, value in (("evidence", []), ("claims", "confirmed")):
            with self.subTest(field=field):
                contract = copy.deepcopy(original)
                contract[field] = value
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertIn(
                    f"{field} must be a JSON object",
                    result["errors"],
                )

    def test_missing_or_unexpected_gate_is_invalid(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = []

        missing = copy.deepcopy(original)
        missing["releaseGates"] = [
            gate
            for gate in missing["releaseGates"]
            if gate["id"] != "same-method-clawhub-competitor-search"
        ]
        mutations.append((missing, "required release gates missing"))

        unexpected = copy.deepcopy(original)
        unexpected["releaseGates"].append(
            {
                "id": "skip-verification",
                "state": "complete",
                "required": True,
            }
        )
        mutations.append((unexpected, "unexpected release gates present"))

        for contract, expected_error in mutations:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(
                        error.startswith(expected_error)
                        for error in result["errors"]
                    )
                )

    def test_observation_gate_cannot_complete_before_not_before(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        next(
            gate
            for gate in contract["releaseGates"]
            if gate["id"] == "observation-window"
        )["state"] = "complete"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(
            result["localEvidence"]["observationWindowElapsed"]
        )
        self.assertIn(
            "observation-window cannot be complete before notBefore",
            result["errors"],
        )

    def test_pre_observation_status_and_formal_surfaces_are_locked(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))

        promotion_ready = copy.deepcopy(original)
        promotion_ready["status"] = "promotion-ready"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(promotion_ready), encoding="utf-8")
            status_result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(status_result["valid"])
        self.assertIn(
            (
                "promotion status must remain observation-window-hold "
                "until observation-window is complete"
            ),
            status_result["errors"],
        )

        publication_pending = copy.deepcopy(original)
        publication_pending["status"] = "publication-pending"
        with tempfile.TemporaryDirectory() as directory:
            root, path = make_staged_repo(directory, publication_pending)
            surface_result = CHECK_MODULE.evaluate(
                root,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(surface_result["valid"])
        self.assertTrue(
            surface_result["localEvidence"]["formalTargetDirectoryPresent"]
        )
        self.assertTrue(
            surface_result["localEvidence"]["formalCatalogEntryPresent"]
        )
        self.assertIn(
            (
                "formal skill directory and catalog entry cannot exist "
                "until observation-window is complete"
            ),
            surface_result["errors"],
        )

    def test_date_alone_does_not_release_observation_gate(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "publication-pending"

        with tempfile.TemporaryDirectory() as directory:
            root, path = make_staged_repo(directory, contract)
            result = CHECK_MODULE.evaluate(
                root,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertTrue(
            result["localEvidence"]["observationWindowElapsed"]
        )
        self.assertFalse(
            result["localEvidence"]["observationGateReleased"]
        )
        self.assertIn(
            (
                "formal skill directory and catalog entry cannot exist "
                "until observation-window is complete"
            ),
            result["errors"],
        )

    def test_completed_observation_gate_releases_time_lock(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "promotion-ready"
        next(
            gate
            for gate in contract["releaseGates"]
            if gate["id"] == "observation-window"
        )["state"] = "complete"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertTrue(
            result["localEvidence"]["observationWindowElapsed"]
        )
        self.assertTrue(
            result["localEvidence"]["observationGateReleased"]
        )
        self.assertNotIn("observation-window", result["blockingGates"])

    def test_external_evidence_requires_completed_observation_gate(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = (
            ("evidence", "latestOfficialReleaseReconfirmed"),
            ("evidence", "clawhubCompetitorSearchComplete"),
            ("evidence", "dryRunComplete"),
            ("evidence", "registryModerationClean"),
            ("evidence", "e4Complete"),
            ("claims", "clawhubMarketGapConfirmed"),
            ("claims", "downloadImpactConfirmed"),
            ("claims", "publishedConfirmed"),
            ("claims", "downloadableConfirmed"),
        )

        for document, field in mutations:
            with self.subTest(document=document, field=field):
                contract = copy.deepcopy(original)
                contract[document][field] = True
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertIn(
                    (
                        f"{document}.{field} cannot be true "
                        "until observation-window is complete"
                    ),
                    result["errors"],
                )

    def test_release_policy_safeguards_are_mandatory(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["releasePolicy"]["maxPlannedE4InstallsPerChangedVersion"] = 2

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["localEvidence"]["releasePolicyValid"])
        self.assertIn(
            "release policy does not preserve required safeguards",
            result["errors"],
        )

    def test_first_release_version_is_fixed(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["candidate"]["proposedFirstReleaseVersion"] = "0.1.17"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["localEvidence"]["firstReleaseVersionValid"])
        self.assertIn(
            "candidate proposed first release version must be 1.0.0",
            result["errors"],
        )

    def test_dry_run_command_is_bound_to_candidate_identity(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = (
            ("missing-slug", lambda command: command.__delitem__(4)),
            (
                "wrong-target",
                lambda command: command.__setitem__(
                    3,
                    "./skills/another-skill",
                ),
            ),
            (
                "wrong-display-name",
                lambda command: command.__setitem__(7, "Wrong Name"),
            ),
            ("missing-dry-run", lambda command: command.remove("--dry-run")),
        )

        for label, mutate in mutations:
            with self.subTest(mutation=label):
                contract = copy.deepcopy(original)
                mutate(contract["dryRunCommand"])
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(
                    result["localEvidence"]["dryRunCommandValid"]
                )
                self.assertIn(
                    (
                        "dryRunCommand must bind the target, stable slug, "
                        "display name, dry-run flag, and owner placeholder"
                    ),
                    result["errors"],
                )

    def test_malformed_catalog_metadata_is_structured_invalid(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = (
            ("categories", "development"),
            ("topics", {"bad": True}),
            ("categories", [{"bad": True}]),
            ("topics", [["artifact-verification"]]),
            ("categories", ["development", ""]),
            ("topics", ["artifact-verification", "   "]),
            ("categories", ["development", "development"]),
            (
                "topics",
                ["artifact-verification", "artifact-verification"],
            ),
        )

        for field, value in mutations:
            with self.subTest(field=field, value=value):
                contract = copy.deepcopy(original)
                contract["catalogEntry"][field] = value
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertFalse(
                    result["localEvidence"]["catalogCandidateValid"]
                )
                self.assertIn(
                    "candidate catalog entry is invalid or inconsistent",
                    result["errors"],
                )

    def test_schema_versions_are_mandatory(self):
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract_mutations = (
            ("missing", None),
            ("wrong", 2),
        )
        for label, schema_version in contract_mutations:
            with self.subTest(document="contract", mutation=label):
                contract = copy.deepcopy(original)
                if schema_version is None:
                    contract.pop("schemaVersion")
                else:
                    contract["schemaVersion"] = schema_version
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "contract.json"
                    path.write_text(json.dumps(contract), encoding="utf-8")
                    result = CHECK_MODULE.evaluate(
                        ROOT,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertIn(
                    "promotion contract schemaVersion must equal 1",
                    result["errors"],
                )

        for label, schema_version in contract_mutations:
            with self.subTest(document="policy", mutation=label):
                with tempfile.TemporaryDirectory() as directory:
                    root, path = make_staged_repo(
                        directory,
                        original,
                        target=False,
                        catalog=False,
                    )
                    policy_path = root / "metrics" / "observation-policy.json"
                    policy = json.loads(
                        policy_path.read_text(encoding="utf-8")
                    )
                    if schema_version is None:
                        policy.pop("schemaVersion")
                    else:
                        policy["schemaVersion"] = schema_version
                    policy_path.write_text(
                        json.dumps(policy),
                        encoding="utf-8",
                    )
                    result = CHECK_MODULE.evaluate(
                        root,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertIn(
                    "observation policy schemaVersion must equal 1",
                    result["errors"],
                )

    def test_complete_status_requires_formal_surfaces(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "complete"
        complete_release_gate_support(contract)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["complete"])
        self.assertIn(
            "post-staging candidate is missing from skills or formal catalog",
            result["errors"],
        )

    def test_formal_directory_and_catalog_must_appear_together(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "publication-pending"

        for target, catalog in ((True, False), (False, True)):
            with self.subTest(target=target, catalog=catalog):
                with tempfile.TemporaryDirectory() as directory:
                    root, path = make_staged_repo(
                        directory,
                        contract,
                        target=target,
                        catalog=catalog,
                    )
                    result = CHECK_MODULE.evaluate(
                        root,
                        path,
                        datetime(2026, 9, 13, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertIn(
                    (
                        "formal skill directory and catalog entry "
                        "must appear together"
                    ),
                    result["errors"],
                )

    def test_staged_surfaces_must_match_contract_identity(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "publication-pending"
        next(
            gate
            for gate in contract["releaseGates"]
            if gate["id"] == "observation-window"
        )["state"] = "complete"

        with tempfile.TemporaryDirectory() as directory:
            root, path = make_staged_repo(directory, contract)
            result = CHECK_MODULE.evaluate(
                root,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

            self.assertTrue(result["valid"])
            self.assertTrue(
                result["localEvidence"]["formalTargetIdentityMatches"]
            )
            self.assertTrue(
                result["localEvidence"]["formalCatalogEntryMatches"]
            )

            catalog_path = root / ".clawhub" / "skill-catalog.json"
            catalog_value = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog_value[contract["candidate"]["targetDirectory"]][
                "displayName"
            ] = "Wrong Display Name"
            catalog_path.write_text(
                json.dumps(catalog_value),
                encoding="utf-8",
            )
            mismatched = CHECK_MODULE.evaluate(
                root,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertFalse(mismatched["valid"])
        self.assertFalse(
            mismatched["localEvidence"]["formalCatalogEntryMatches"]
        )
        self.assertIn(
            "formal catalog entry does not match promotion contract",
            mismatched["errors"],
        )

    def test_complete_status_requires_matching_surfaces_and_all_gates(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "complete"
        complete_release_gate_support(contract)

        with tempfile.TemporaryDirectory() as directory:
            root, path = make_staged_repo(directory, contract)
            result = CHECK_MODULE.evaluate(
                root,
                path,
                datetime(2026, 9, 13, tzinfo=timezone.utc),
            )

        self.assertTrue(result["valid"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["contractStatus"], "complete")
        self.assertEqual(result["blockingGates"], [])
        self.assertEqual(result["errors"], [])

    def test_missing_or_invalid_source_skill_is_structured_invalid(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

        for mutation in ("missing", "invalid-utf8"):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
                    root, path = make_staged_repo(
                        directory,
                        contract,
                        target=False,
                        catalog=False,
                    )
                    skill_path = (
                        root
                        / contract["candidate"]["sourceDirectory"]
                        / "SKILL.md"
                    )
                    if mutation == "missing":
                        skill_path.unlink()
                    else:
                        skill_path.write_bytes(b"\xff")
                    result = CHECK_MODULE.evaluate(
                        root,
                        path,
                        datetime(2026, 9, 5, tzinfo=timezone.utc),
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["complete"])
                self.assertEqual(result["contractStatus"], "invalid")
                self.assertEqual(result["localEvidence"], {})
                self.assertIn("SKILL.md cannot be read", result["errors"][0])

    def test_missing_source_skill_cli_returns_json_without_traceback(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["candidate"]["sourceDirectory"] = "research/missing"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--repo-root",
                    str(ROOT),
                    "--contract",
                    str(path),
                    "--now",
                    "2026-09-05T00:00:00+00:00",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        self.assertFalse(result["valid"])
        self.assertEqual(result["contractStatus"], "invalid")
        self.assertIn("SKILL.md cannot be read", result["errors"][0])

    def test_path_escape_is_a_contract_error(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["candidate"]["sourceDirectory"] = "../outside"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                path,
                datetime(2026, 9, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["contractStatus"], "invalid")
        self.assertIn("path escapes repository root", result["errors"][0])

    def test_checker_has_no_network_or_process_execution_imports(self):
        source = CHECKER.read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "import urllib.request",
            "import subprocess",
            "from subprocess",
            "socket.",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

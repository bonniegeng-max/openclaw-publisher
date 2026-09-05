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
        self.assertTrue(
            result["localEvidence"]["requiredDraftFilesPresent"]
        )
        self.assertTrue(
            result["localEvidence"]["draftIdentityMatchesContract"]
        )
        self.assertTrue(result["localEvidence"]["stableSlugAllowed"])
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
        for gate in contract["releaseGates"]:
            gate["state"] = "complete"

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

    def test_complete_status_requires_formal_surfaces(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["status"] = "complete"
        for gate in contract["releaseGates"]:
            gate["state"] = "complete"

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
        for gate in contract["releaseGates"]:
            gate["state"] = "complete"

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

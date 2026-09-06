import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
CHECKER = RESEARCH / "check_protected_release_runtime_contract.py"
CONTRACT = RESEARCH / "protected-release-runtime-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "protected_release_runtime_contract",
    CHECKER,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def load_contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def base_evidence():
    sha = "a" * 40
    identity = {
        "repository_id": 123456,
        "workflow_ref": (
            "bonniegeng-max/openclaw-publisher/"
            ".github/workflows/protected-release.yml@" + sha
        ),
        "workflow_sha": sha,
        "run_id": 9001,
        "run_attempt": 1,
        "job": "release",
        "environment": "clawhub-production",
    }
    release = {
        "release_id": "skill-publish-readiness-1.2.3",
        "artifact_digest": "sha256:" + "b" * 64,
    }
    return {
        "releaseIdentity": release,
        "runIdentity": identity,
        "environmentApproval": {
            "environment": "clawhub-production",
            "actorId": 100,
            "approvedReviewerIds": [200],
            "requiredReviewersSatisfied": True,
            "preventSelfReviewEnforced": True,
            "secretReleased": True,
        },
        "workflowTrust": {
            "pinnedFullSha": True,
            "verifiedWorkflowSha": sha,
        },
        "concurrency": {
            "configured": True,
            "group": "clawhub-production",
            "cancelInProgress": False,
        },
        "ledgerReservation": {
            "provider": "independent-release-ledger",
            "independent": True,
            "durable": True,
            "operation": "check-and-reserve",
            "atomic": True,
            "reservedBeforeSecretRelease": True,
            "reservedBeforeMutation": True,
            "reservationKey": MODULE.release_reservation_key(
                release,
                identity,
            ),
            "reservationId": "reservation-001",
            "status": "reserved",
            "existingReservation": False,
            "reservedForRunIdentity": copy.deepcopy(identity),
        },
    }


def write_json(directory, name, value):
    path = Path(directory) / name
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_pinned_auditor_repo(directory):
    root = Path(directory)
    target = root / MODULE.AUDITOR_PATH
    target.parent.mkdir(parents=True)
    shutil.copy2(CHECKER, target)
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["/usr/bin/git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["/usr/bin/git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(["/usr/bin/git", "add", MODULE.AUDITOR_PATH], cwd=root, check=True)
    subprocess.run(
        ["/usr/bin/git", "commit", "-qm", "pin auditor"],
        cwd=root,
        check=True,
    )
    commit = subprocess.check_output(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    entry = subprocess.check_output(
        ["/usr/bin/git", "ls-tree", commit, "--", MODULE.AUDITOR_PATH],
        cwd=root,
        text=True,
    ).strip().split(maxsplit=3)
    content = target.read_bytes()
    return root, {
        "path": MODULE.AUDITOR_PATH,
        "commit": commit,
        "mode": entry[0],
        "blobOid": entry[2],
        "sha256": MODULE.digest_bytes(content),
    }


class ProtectedReleaseRuntimeContractTests(unittest.TestCase):
    def test_repository_contract_is_valid_research_only_and_non_mutating(self):
        result = MODULE.evaluate(CONTRACT)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["contractValid"])
        self.assertFalse(result["evidenceValid"])
        self.assertFalse(result["realMutation"])
        self.assertFalse(result["mutationAllowed"])
        self.assertFalse(result["persistentReplayProtectionImplemented"])
        self.assertEqual(result["evidenceLevel"], "E0")
        self.assertFalse(result["deploymentEvidence"])
        self.assertFalse(result["mutationEvidence"])
        self.assertTrue(result["checks"]["contract:auditor-source-evidence"])
        self.assertEqual(
            result["environmentAuthenticates"],
            "secret-release-only",
        )
        self.assertEqual(
            result["concurrencyGuarantee"],
            "serialization-only",
        )

    def test_tampered_auditor_draft_sha_is_rejected(self):
        contract = load_contract()
        contract["auditorEvidence"]["draft"]["sha256"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = write_json(directory, "contract.json", contract)
            result = MODULE.evaluate(path, repo_root=ROOT)

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["contract:auditor-source-evidence"])
        self.assertTrue(any("SHA-256" in error for error in result["errors"]))

    def test_fabricated_pinned_baseline_is_rejected(self):
        contract = load_contract()
        draft = contract["auditorEvidence"]["draft"]
        contract["auditorEvidence"]["baseline"] = {
            "path": MODULE.AUDITOR_PATH,
            "commit": "f" * 40,
            "mode": draft["mode"],
            "blobOid": "e" * 40,
            "sha256": draft["sha256"],
        }
        contract["twoStageAnchoring"]["local"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = write_json(directory, "contract.json", contract)
            result = MODULE.evaluate(path, repo_root=ROOT)

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["contract:auditor-source-evidence"])
        self.assertTrue(any("local Git commit" in error for error in result["errors"]))

    def test_locally_pinned_auditor_still_remains_e0_and_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root, baseline = make_pinned_auditor_repo(directory)
            contract = load_contract()
            contract["auditorEvidence"]["draft"]["mode"] = baseline["mode"]
            contract["auditorEvidence"]["draft"]["sha256"] = baseline["sha256"]
            contract["auditorEvidence"]["baseline"] = baseline
            contract["twoStageAnchoring"]["local"] = True
            path = write_json(directory, "contract.json", contract)
            result = MODULE.evaluate(path, repo_root=root)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["checks"]["contract:auditor-source-evidence"])
        self.assertEqual(result["evidenceLevel"], "E0")
        self.assertFalse(result["deploymentEvidence"])
        self.assertFalse(result["mutationEvidence"])
        self.assertFalse(result["mutationAllowed"])

    def test_complete_hypothetical_evidence_still_cannot_enable_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = write_json(
                directory,
                "evidence.json",
                base_evidence(),
            )
            result = MODULE.evaluate(CONTRACT, evidence_path)

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["evidenceValid"])
        self.assertTrue(result["checks"]["evidence:environment-approval"])
        self.assertTrue(result["checks"]["evidence:workflow-trust"])
        self.assertTrue(result["checks"]["evidence:ledger-reservation"])
        self.assertFalse(result["realMutation"])
        self.assertFalse(result["mutationAllowed"])

    def test_rerun_attempt_is_distinct_but_keeps_same_release_reservation_key(self):
        first = base_evidence()
        rerun = copy.deepcopy(first)
        rerun["runIdentity"]["run_attempt"] = 2
        rerun["ledgerReservation"]["reservedForRunIdentity"]["run_attempt"] = 2

        self.assertEqual(
            first["runIdentity"]["run_id"],
            rerun["runIdentity"]["run_id"],
        )
        self.assertNotEqual(
            MODULE.run_identity_key(first["runIdentity"]),
            MODULE.run_identity_key(rerun["runIdentity"]),
        )
        self.assertEqual(
            MODULE.release_reservation_key(
                first["releaseIdentity"],
                first["runIdentity"],
            ),
            MODULE.release_reservation_key(
                rerun["releaseIdentity"],
                rerun["runIdentity"],
            ),
        )

    def test_rerun_cannot_reuse_the_already_reserved_release(self):
        evidence = base_evidence()
        evidence["runIdentity"]["run_attempt"] = 2
        ledger = evidence["ledgerReservation"]
        ledger["status"] = "duplicate"
        ledger["existingReservation"] = True

        checks, errors = MODULE.audit_evidence(evidence)

        self.assertFalse(checks["ledger-reservation"])
        self.assertTrue(any("duplicate" in error for error in errors))

    def test_duplicate_release_is_rejected_even_for_a_different_run(self):
        evidence = base_evidence()
        evidence["runIdentity"]["run_id"] = 9002
        ledger = evidence["ledgerReservation"]
        ledger["status"] = "duplicate"
        ledger["existingReservation"] = True
        ledger["reservedForRunIdentity"] = {
            **evidence["runIdentity"],
            "run_id": 9001,
        }

        checks, _ = MODULE.audit_evidence(evidence)

        self.assertFalse(checks["ledger-reservation"])

    def test_concurrency_alone_is_not_replay_or_authorization_evidence(self):
        evidence = {
            "releaseIdentity": None,
            "runIdentity": None,
            "environmentApproval": None,
            "workflowTrust": None,
            "concurrency": {
                "configured": True,
                "group": "clawhub-production",
                "cancelInProgress": False,
            },
            "ledgerReservation": None,
        }

        checks, _ = MODULE.audit_evidence(evidence)

        self.assertTrue(checks["concurrency-shape"])
        self.assertFalse(checks["run-identity"])
        self.assertFalse(checks["environment-approval"])
        self.assertFalse(checks["workflow-trust"])
        self.assertFalse(checks["ledger-reservation"])

    def test_missing_approval_fixed_sha_or_ledger_evidence_is_rejected(self):
        cases = (
            ("approval", "environmentApproval", None, "environment-approval"),
            (
                "fixed SHA",
                "workflowTrust",
                {
                    "pinnedFullSha": False,
                    "verifiedWorkflowSha": "a" * 40,
                },
                "workflow-trust",
            ),
            ("ledger", "ledgerReservation", None, "ledger-reservation"),
        )
        for label, field, replacement, failed_check in cases:
            with self.subTest(label=label):
                evidence = base_evidence()
                evidence[field] = replacement
                checks, errors = MODULE.audit_evidence(evidence)
                self.assertFalse(checks[failed_check])
                self.assertTrue(errors)

    def test_workflow_ref_and_sha_must_be_bound(self):
        evidence = base_evidence()
        evidence["runIdentity"]["workflow_ref"] = (
            "bonniegeng-max/openclaw-publisher/"
            ".github/workflows/protected-release.yml@" + "c" * 40
        )

        checks, _ = MODULE.audit_evidence(evidence)

        self.assertFalse(checks["run-identity"])
        self.assertFalse(checks["workflow-trust"])
        self.assertFalse(checks["ledger-reservation"])

    def test_every_run_identity_field_is_required(self):
        for field in MODULE.RUN_IDENTITY_FIELDS:
            with self.subTest(field=field):
                evidence = base_evidence()
                del evidence["runIdentity"][field]
                checks, _ = MODULE.audit_evidence(evidence)
                self.assertFalse(checks["run-identity"])
                self.assertFalse(checks["workflow-trust"])
                self.assertFalse(checks["ledger-reservation"])

    def test_environment_approval_only_authenticates_secret_release(self):
        contract = load_contract()
        authentication = contract["environmentAuthentication"]

        self.assertEqual(authentication["authenticates"], ["secret-release"])
        self.assertEqual(authentication["purpose"], "secret-release-only")
        self.assertIn("release-mutation", authentication["doesNotAuthorize"])
        self.assertIn("replay-prevention", authentication["doesNotAuthorize"])
        self.assertTrue(authentication["requiredReviewers"])
        self.assertTrue(authentication["preventSelfReview"])

    def test_contract_rejects_claimed_ledger_or_real_mutation(self):
        mutations = []
        mutation = load_contract()
        mutation["realMutation"] = True
        mutations.append(("real mutation", mutation, "real-mutation-disabled"))
        ledger = load_contract()
        ledger["currentImplementation"]["ledgerImplemented"] = True
        mutations.append(("ledger", ledger, "ledger-not-implemented"))
        concurrency = load_contract()
        concurrency["concurrency"]["persistentReplayProtection"] = True
        mutations.append(
            ("concurrency", concurrency, "concurrency-serialization-only")
        )

        for label, contract, failed_check in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = write_json(directory, "contract.json", contract)
                result = MODULE.evaluate(path)
                self.assertFalse(result["valid"])
                self.assertFalse(result["checks"][f"contract:{failed_check}"])
                self.assertFalse(result["mutationAllowed"])

    def test_cli_is_offline_and_reports_valid_but_blocked(self):
        completed = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["mutationAllowed"])
        source = CHECKER.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "from requests",
            "import urllib",
            "from urllib",
            "socket.",
            "curl ",
            "wget ",
            "gh ",
            "clawhub ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('TRUSTED_GIT = Path("/usr/bin/git")', source)
        self.assertIn('"--no-replace-objects"', source)
        self.assertIn('"GIT_NO_REPLACE_OBJECTS": "1"', source)


if __name__ == "__main__":
    unittest.main()

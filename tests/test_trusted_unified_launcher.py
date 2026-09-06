import copy
import builtins
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
LAUNCHER = RESEARCH / "trusted_unified_launcher.py"
CONSUMER = RESEARCH / "trusted_artifact_publish_consumer.py"
AUDITOR = RESEARCH / "check_trusted_unified_launcher_contract.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = load("trusted_unified_launcher", LAUNCHER)
CONSUMER_MODULE = load("attested_consumer", CONSUMER)
AUDITOR_MODULE = load("unified_auditor", AUDITOR)
CONSUMER_TESTS = load(
    "consumer_test_helpers", ROOT / "tests" / "test_trusted_artifact_publish_consumer.py"
)
AUTH_TESTS = load(
    "authorization_test_helpers", ROOT / "tests" / "test_skill_release_authorization.py"
)
HEAD = "a" * 40
BASE = "b" * 40
CONTROL = "c" * 40
NONCE = bytes(range(32))


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def catalog_blob():
    return canonical({
        "skills/demo-skill": {
            "displayName": "Demo Skill",
            "categories": ["development"],
            "topics": ["demo"],
        }
    })


def invocation(blob=None):
    blob = blob or catalog_blob()
    return {
        "schemaVersion": 1,
        "researchStatus": "research-only-not-wired",
        "operation": "dry-run-simulation",
        "candidateRoot": "/candidate",
        "controlRoot": "/control",
        "artifactParent": "/artifacts",
        "controlCommit": CONTROL,
        "baseCommit": BASE,
        "headCommit": HEAD,
        "catalog": {
            "path": ".clawhub/skill-catalog.json",
            "mode": "100644",
            "blobOid": "d" * 40,
            "sha256": "sha256:" + hashlib.sha256(blob).hexdigest(),
        },
        "event": {
            "name": "workflow_dispatch",
            "ref": "",
            "changedOnly": True,
            "headArgument": "HEAD",
            "skillPath": "skills/demo-skill",
            "before": "",
            "sha": "",
            "eventRef": "",
        },
    }


def phase_results():
    return (
        {"baseCommit": BASE, "headCommit": HEAD},
        {"manifest": {"source": {"commit": HEAD}}},
    )


def rebuild_frame(parts):
    return CONSUMER_MODULE.frame_parts(*parts)


def initialize_complete_fixture(workspace):
    candidate, base_catalog = AUTH_TESTS.make_repo(workspace / "candidate")
    AUTH_TESTS.write_json(
        candidate / "metrics" / "observation-policy.json",
        {
            "schemaVersion": 1,
            "notBefore": "2020-01-01T00:00:00+00:00",
            "reason": "Completed test observation window.",
        },
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=candidate, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=candidate,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=candidate, check=True
    )
    subprocess.run(["git", "add", "."], cwd=candidate, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=candidate, check=True)
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=candidate, text=True
    ).strip()
    AUTH_TESTS.commit_release_candidate(candidate)
    candidate_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=candidate, text=True
    ).strip()
    changed_paths = [
        AUTH_TESTS.CHECK_MODULE.DEFAULT_AUTHORIZATION_PATH,
        "skills/demo-skill/SKILL.md",
        "skills/demo-skill/CHANGELOG.md",
        "review.md",
    ]
    authorization_path, authorization = AUTH_TESTS.make_authorization(
        candidate,
        base_catalog,
        changed_paths=changed_paths,
        baseCommit=base,
        candidateCommit=candidate_commit,
        observationNotBefore="2020-01-01T00:00:00+00:00",
    )
    now = datetime.now(timezone.utc)
    authorization["issuedAt"] = (now - timedelta(hours=1)).isoformat()
    authorization["expiresAt"] = (now + timedelta(hours=1)).isoformat()
    authorization["review"]["reviewedAt"] = (now - timedelta(hours=2)).isoformat()
    authorization["releaseId"] = "demo-skill-1.0.2"
    authorization["targets"][0]["version"] = "1.0.2"
    authorization["contentDigest"] = AUTH_TESTS.CHECK_MODULE.compute_content_digest(
        candidate, base_catalog, {"demo-skill"}
    )
    AUTH_TESTS.write_json(authorization_path, authorization)
    subprocess.run(["git", "add", "."], cwd=candidate, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "authorized release"], cwd=candidate, check=True
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=candidate, text=True
    ).strip()
    subprocess.run(
        [
            "git", "remote", "add", "origin",
            "https://github.com/bonniegeng-max/openclaw-publisher.git",
        ],
        cwd=candidate,
        check=True,
    )
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", head],
        cwd=candidate,
        check=True,
    )
    subprocess.run(
        ["git", "branch", "--set-upstream-to", "origin/main", "main"],
        cwd=candidate,
        check=True,
        capture_output=True,
    )

    control = workspace / "control"
    control.mkdir()
    control_paths = {
        *MODULE.CONTROL_FILES.values(),
        *CONSUMER_MODULE.PREFLIGHT_CONTROL_FILES.values(),
        *CONSUMER_MODULE.STAGING_CONTROL_FILES.values(),
    }
    for relative in control_paths:
        target = control / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=control, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=control,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=control, check=True
    )
    subprocess.run(["git", "add", "."], cwd=control, check=True)
    subprocess.run(["git", "commit", "-qm", "control"], cwd=control, check=True)
    control_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=control, text=True
    ).strip()
    subprocess.run(
        [
            "git", "remote", "add", "origin",
            "https://github.com/bonniegeng-max/openclaw-publisher.git",
        ],
        cwd=control,
        check=True,
    )
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", control_commit],
        cwd=control,
        check=True,
    )
    subprocess.run(
        ["git", "branch", "--set-upstream-to", "origin/main", "main"],
        cwd=control,
        check=True,
        capture_output=True,
    )
    artifact_parent = workspace / "artifacts"
    artifact_parent.mkdir(mode=0o700)
    return candidate, control, control_commit, base, head, artifact_parent


class TrustedUnifiedLauncherTests(unittest.TestCase):
    def test_attested_frame_accepts_one_32_byte_nonce_and_canonical_invocation(self):
        blob = catalog_blob()
        call = invocation(blob)
        preflight, staging = phase_results()
        frame = CONSUMER_MODULE.encode_attested_frame(
            call, preflight, staging, blob, NONCE
        )
        simulated = {
            "valid": True,
            "status": "simulated",
            "oneTimeRunReplayProtection": False,
        }
        with mock.patch.object(
            CONSUMER_MODULE, "consume", return_value=simulated
        ) as consume:
            result = CONSUMER_MODULE.consume_attested_frame(
                frame, NONCE, call
            )
        consume.assert_called_once()
        self.assertFalse(result["authorizationProvenanceVerified"])
        self.assertFalse(result["controlCommitExternallyAuthenticated"])
        self.assertTrue(result["processLocalFrameBinding"])
        self.assertFalse(result["persistentReplayProtection"])
        self.assertFalse(result["oneTimeRunReplayProtection"])
        self.assertTrue(result["noNetworkCallsRequested"])
        self.assertFalse(result["networkIsolationEnforced"])
        self.assertNotIn("networkUsed", result)
        self.assertEqual(
            result["authorizationProvenance"],
            "process-local-length-framed-control-blobs-not-externally-authenticated",
        )
        self.assertEqual(
            result["envelopedPhases"], ["preflight", "staging"]
        )
        self.assertTrue(result["consumerExecutionCompleted"])
        self.assertEqual(len(NONCE), 32)
        with self.assertRaisesRegex(ValueError, "already been consumed"):
            CONSUMER_MODULE.consume_attested_frame(frame, NONCE, call)

    def test_nonce_length_and_cross_run_replay_fail_closed(self):
        blob = catalog_blob()
        call = invocation(blob)
        preflight, staging = phase_results()
        with self.assertRaisesRegex(ValueError, "32 bytes"):
            CONSUMER_MODULE.encode_attested_frame(
                call, preflight, staging, blob, b"x" * 31
            )
        frame = CONSUMER_MODULE.encode_attested_frame(
            call, preflight, staging, blob, NONCE
        )
        with self.assertRaisesRegex(ValueError, "bound to this run"):
            CONSUMER_MODULE.consume_attested_frame(
                frame, b"z" * 32, call
            )

    def test_phase_swap_and_result_tampering_fail_closed(self):
        blob = catalog_blob()
        call = invocation(blob)
        preflight, staging = phase_results()
        frame = CONSUMER_MODULE.encode_attested_frame(
            call, preflight, staging, blob, NONCE
        )
        parts = CONSUMER_MODULE.parse_frame_parts(frame)
        with self.assertRaisesRegex(ValueError, "preflight"):
            CONSUMER_MODULE.consume_attested_frame(
                rebuild_frame([parts[0], parts[2], parts[1], parts[3]]),
                NONCE,
                call,
            )
        envelope = json.loads(parts[1])
        envelope["result"]["headCommit"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "bound to this run"):
            CONSUMER_MODULE.consume_attested_frame(
                rebuild_frame(
                    [parts[0], canonical(envelope), parts[2], parts[3]]
                ),
                NONCE,
                call,
            )

    def test_catalog_head_base_and_event_bindings_fail_closed(self):
        blob = catalog_blob()
        call = invocation(blob)
        preflight, staging = phase_results()
        frame = CONSUMER_MODULE.encode_attested_frame(
            call, preflight, staging, blob, NONCE
        )
        parts = CONSUMER_MODULE.parse_frame_parts(frame)
        corrupt_catalog = bytearray(parts[3])
        corrupt_catalog[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "catalog blob digest"):
            CONSUMER_MODULE.consume_attested_frame(
                rebuild_frame([parts[0], parts[1], parts[2], bytes(corrupt_catalog)]),
                NONCE,
                call,
            )

        wrong_base = copy.deepcopy(preflight)
        wrong_base["baseCommit"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "base commit"):
            CONSUMER_MODULE.consume_attested_frame(
                CONSUMER_MODULE.encode_attested_frame(
                    call, wrong_base, staging, blob, NONCE
                ),
                NONCE,
                call,
            )
        wrong_head = copy.deepcopy(staging)
        wrong_head["manifest"]["source"]["commit"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "head commit"):
            CONSUMER_MODULE.consume_attested_frame(
                CONSUMER_MODULE.encode_attested_frame(
                    call, preflight, wrong_head, blob, NONCE
                ),
                NONCE,
                call,
            )
        wrong_event = copy.deepcopy(call)
        wrong_event["event"]["name"] = "push"
        with self.assertRaisesRegex(ValueError, "mismatched"):
            CONSUMER_MODULE.consume_attested_frame(
                frame, NONCE, wrong_event
            )

    def test_noncanonical_invocation_and_frame_lengths_are_rejected(self):
        blob = catalog_blob()
        call = invocation(blob)
        preflight, staging = phase_results()
        frame = CONSUMER_MODULE.encode_attested_frame(
            call, preflight, staging, blob, NONCE
        )
        parts = CONSUMER_MODULE.parse_frame_parts(frame)
        pretty = json.dumps(call, indent=2).encode()
        with self.assertRaisesRegex(ValueError, "not canonical"):
            CONSUMER_MODULE.consume_attested_frame(
                rebuild_frame([pretty, parts[1], parts[2], parts[3]]),
                NONCE,
                call,
            )
        for malformed in (
            frame[:-1],
            frame + b"x",
            b"wrong" + frame,
        ):
            with self.subTest(size=len(malformed)):
                with self.assertRaises(ValueError):
                    CONSUMER_MODULE.parse_frame_parts(malformed)

    def test_candidate_catalog_comes_from_head_blob_not_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "candidate"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=root, check=True
            )
            path = root / ".clawhub" / "skill-catalog.json"
            path.parent.mkdir()
            committed = catalog_blob()
            path.write_bytes(committed)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "catalog"], cwd=root, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            path.write_bytes(b'{"worktree":"tampered"}')
            observed, evidence = MODULE.read_candidate_catalog(root, head)
        self.assertEqual(observed, committed)
        self.assertEqual(
            evidence["sha256"], "sha256:" + hashlib.sha256(committed).hexdigest()
        )

    def test_preflight_staging_and_consumer_are_loaded_from_one_control_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "control"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=root, check=True
            )
            expected = {}
            for name, relative in MODULE.CONTROL_FILES.items():
                data = (ROOT / relative).read_bytes()
                expected[name] = data
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "control"], cwd=root, check=True)
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            sources, evidence = MODULE.read_control_sources(root, commit)
            (root / MODULE.CONTROL_FILES["consumer"]).write_text(
                "tampered worktree\n", encoding="utf-8"
            )
            repeated, _ = MODULE.read_control_sources(root, commit)
        self.assertEqual(sources, expected)
        self.assertEqual(repeated, expected)
        self.assertEqual(set(evidence), {"preflight", "staging", "consumer"})
        self.assertTrue(all(item["mode"] == "100644" for item in evidence.values()))

    def test_output_and_time_limits_terminate_and_reap_children(self):
        environment = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                MODULE, "terminate_and_reap", wraps=MODULE.terminate_and_reap
            ) as terminate:
                with self.assertRaisesRegex(ValueError, "output exceeds"):
                    MODULE.run_bounded(
                        [sys.executable, "-I", "-c", "import os;os.write(1,b'x'*4096)"],
                        cwd=root,
                        environment=environment,
                        timeout_seconds=2,
                        maximum_output_bytes=1024,
                    )
                self.assertTrue(terminate.called)
            with mock.patch.object(
                MODULE, "terminate_and_reap", wraps=MODULE.terminate_and_reap
            ) as terminate:
                with self.assertRaises(subprocess.TimeoutExpired):
                    MODULE.run_bounded(
                        [sys.executable, "-I", "-c", "import time;time.sleep(10)"],
                        cwd=root,
                        environment=environment,
                        timeout_seconds=0.05,
                        maximum_output_bytes=1024,
                    )
                self.assertTrue(terminate.called)

    def test_nonmock_complete_run_uses_three_isolated_phase_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            (
                candidate,
                control,
                control_commit,
                base,
                _,
                artifacts,
            ) = initialize_complete_fixture(workspace)
            returncode, result = MODULE.run_unified(
                candidate,
                control,
                control_commit,
                base,
                artifacts,
                skill_path="skills/demo-skill",
            )
        self.assertEqual(returncode, 0, result)
        self.assertTrue(result["valid"])
        self.assertTrue(result["processLocalFrameBinding"])
        self.assertFalse(result["persistentReplayProtection"])
        self.assertFalse(result["authorizationProvenanceVerified"])
        self.assertFalse(result["controlCommitExternallyAuthenticated"])
        self.assertTrue(result["noNetworkCallsRequested"])
        self.assertFalse(result["networkIsolationEnforced"])
        self.assertNotIn("networkUsed", result)
        self.assertEqual(result["envelopedPhases"], ["preflight", "staging"])
        self.assertTrue(result["consumerExecutionCompleted"])
        self.assertEqual(
            result["unifiedLauncher"]["independentIsolatedPhaseProcesses"],
            ["preflight", "staging", "consumer"],
        )
        self.assertFalse(
            result["unifiedLauncher"]["parentExecutedControlBlob"]
        )

    def test_control_blob_side_effect_does_not_reach_parent_process(self):
        attribute = "_trusted_unified_control_blob_side_effect"
        if hasattr(builtins, attribute):
            delattr(builtins, attribute)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate, control, _, base, _, artifacts = (
                initialize_complete_fixture(workspace)
            )
            preflight_path = control / MODULE.CONTROL_FILES["preflight"]
            preflight_path.write_text(
                "import builtins\n"
                f"builtins.{attribute} = True\n"
                "raise RuntimeError('child-only side effect')\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=control, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "malicious preflight"],
                cwd=control,
                check=True,
            )
            control_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=control, text=True
            ).strip()
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", control_commit],
                cwd=control,
                check=True,
            )
            returncode, result = MODULE.run_unified(
                candidate, control, control_commit, base, artifacts
            )
        self.assertEqual(returncode, 2)
        self.assertFalse(result["valid"])
        self.assertFalse(hasattr(builtins, attribute))

    def test_identical_attested_payload_replays_in_a_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = CONSUMER_TESTS.make_fixture(parent)
            blob = canonical(catalog)
            call = invocation(blob)
            call.update({
                "candidateRoot": str(parent / "candidate"),
                "controlRoot": str(parent / "control"),
                "artifactParent": str(parent),
                "controlCommit": authorization["trustedControl"]["commit"],
                "baseCommit": authorization["baseCommit"],
                "headCommit": authorization["headCommit"],
            })
            call["event"]["skillPath"] = "skills/demo-skill"
            payload = MODULE.phase_frame(
                CONSUMER.read_bytes(),
                NONCE,
                canonical(call),
                canonical(authorization),
                canonical(staging),
                blob,
            )
            completed = [
                MODULE.run_bounded(
                    [sys.executable, "-I", "-c", MODULE.CONSUMER_BOOTSTRAP],
                    cwd=parent / "control",
                    environment=MODULE.child_environment(),
                    payload=payload,
                    timeout_seconds=30,
                    maximum_output_bytes=2 * 1024 * 1024,
                )
                for _ in range(2)
            ]
        for observed in completed:
            self.assertEqual(observed.returncode, 0, observed.stderr)
            result = json.loads(observed.stdout)
            self.assertTrue(result["valid"])
            self.assertTrue(result["processLocalFrameBinding"])
            self.assertFalse(result["persistentReplayProtection"])

    def test_launcher_is_research_only_and_auditor_accepts_contract(self):
        completed = subprocess.run(
            [sys.executable, str(LAUNCHER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("isolated mode", json.loads(completed.stdout)["errors"][0])
        result = AUDITOR_MODULE.evaluate(
            ROOT, RESEARCH / "trusted-unified-launcher-contract.json"
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deploymentReady"])
        contract = json.loads(
            (RESEARCH / "trusted-unified-launcher-contract.json").read_text(
                encoding="utf-8"
            )
        )
        for field in ("launcherEvidence", "auditorEvidence", "consumerEvidence"):
            self.assertIsNotNone(contract[field]["baseline"])
            self.assertEqual(contract[field]["draft"]["mode"], "100644")
            self.assertTrue(contract[field]["draft"]["sha256"].startswith("sha256:"))
        self.assertTrue(contract["twoStageAnchoring"]["localIntegrityPinned"])
        self.assertEqual(contract["evidenceBoundary"]["currentLevel"], "E0")
        self.assertFalse(contract["twoStageAnchoring"]["remoteCommitVerified"])
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertNotIn("tempfile", source)
        tree = __import__("ast").parse(source)
        self.assertFalse(
            any(
                isinstance(node, __import__("ast").Call)
                and isinstance(node.func, __import__("ast").Name)
                and node.func.id in {"exec", "eval", "compile"}
                for node in __import__("ast").walk(tree)
            )
        )
        self.assertNotIn("def load_module(", source)
        self.assertNotIn("CLAWHUB_TOKEN", source)
        self.assertNotIn("clawhub ", source)


if __name__ == "__main__":
    unittest.main()

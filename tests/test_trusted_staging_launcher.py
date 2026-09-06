import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
LAUNCHER = RESEARCH / "trusted_staging_launcher.py"
SPEC = importlib.util.spec_from_file_location("trusted_staging_launcher", LAUNCHER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def init_repository(root):
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/bonniegeng-max/openclaw-publisher.git",
        ],
        cwd=root,
        check=True,
    )


def make_candidate(root):
    init_repository(root)
    skill = root / "skills" / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("body\n", encoding="utf-8")
    (skill / "CHANGELOG.md").write_text("# Changes\n", encoding="utf-8")
    (skill / ".clawhubignore").write_text(".DS_Store\n", encoding="utf-8")
    (skill / "references" / "note.md").write_text("note\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "candidate"], cwd=root, check=True)
    commit = git(root, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", commit],
        cwd=root,
        check=True,
    )
    return commit


def make_control(root):
    init_repository(root)
    for relative in MODULE.CONTROL_FILES.values():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "control"], cwd=root, check=True)
    commit = git(root, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", commit],
        cwd=root,
        check=True,
    )
    return commit


def valid_guard_result(head):
    files = [
        {
            "path": ".clawhubignore",
            "mode": "100644",
            "blobOid": "4" * 40,
            "sha256": "sha256:" + "5" * 64,
        },
        {
            "path": "CHANGELOG.md",
            "mode": "100644",
            "blobOid": "6" * 40,
            "sha256": "sha256:" + "7" * 64,
        },
        {
            "path": "SKILL.md",
            "mode": "100644",
            "blobOid": "8" * 40,
            "sha256": "sha256:" + "9" * 64,
        },
    ]
    package_payload = {
        "files": [
            {
                "path": item["path"],
                "mode": item["mode"],
                "blobOid": item["blobOid"],
                "sha256": item["sha256"],
            }
            for item in files
        ],
        "format": "safe-publish-package-v1",
        "skillPath": "skills/demo-skill",
        "treeOid": "2" * 40,
    }
    package_digest = (
        "sha256:"
        + MODULE.hashlib.sha256(
            MODULE.canonical_json_bytes(package_payload)
        ).hexdigest()
    )
    return {
        "schemaVersion": 2,
        "valid": True,
        "decision": "single-target",
        "eventName": "workflow_dispatch",
        "ref": "",
        "dryRun": True,
        "changedOnly": True,
        "authorizationEligible": False,
        "authorized": False,
        "mutationAllowed": False,
        "targetCount": 1,
        "skillPath": "skills/demo-skill",
        "slug": "demo-skill",
        "packageSnapshot": {
            "treeOid": "2" * 40,
            "files": files,
            "packageDigest": package_digest,
        },
        "baseCommit": None,
        "headCommit": head,
        "eventBefore": None,
        "eventSha": None,
        "eventRef": None,
        "blockingReasons": [],
    }


def valid_manifest(head, guard_digest=None):
    guard = valid_guard_result(head)
    files = [
        {
            "path": item["path"],
            "sourceMode": item["mode"],
            "artifactMode": "0555" if item["mode"] == "100755" else "0444",
            "blobOid": item["blobOid"],
            "sha256": item["sha256"],
        }
        for item in guard["packageSnapshot"]["files"]
    ]
    descriptor = {
        "schemaVersion": 2,
        "researchStatus": "research-only-not-wired",
        "format": "immutable-skill-staging-v2",
        "guardResultDigest": (
            guard_digest
            or "sha256:"
            + MODULE.hashlib.sha256(
                MODULE.canonical_json_bytes(guard)
            ).hexdigest()
        ),
        "source": {
            "commit": head,
            "skillPath": "skills/demo-skill",
            "treeOid": "2" * 40,
            "packageDigest": guard["packageSnapshot"]["packageDigest"],
        },
        "packageDirectory": "package",
        "files": files,
        "worktreeRead": False,
        "authorizationGranted": False,
    }
    return {
        **descriptor,
        "artifactDigest": (
            "sha256:"
            + MODULE.hashlib.sha256(MODULE.canonical_json_bytes(descriptor)).hexdigest()
        ),
    }


def valid_result(head, guard_digest=None):
    manifest = valid_manifest(head, guard_digest)
    return {
        "schemaVersion": 2,
        "valid": True,
        "status": "committed",
        "researchStatus": "research-only-not-wired",
        "created": True,
        "authorizationGranted": False,
        "outputName": (
            "demo-skill-" + head[:12] + "-" + manifest["artifactDigest"][7:19]
        ),
        "residueName": None,
        "manifest": manifest,
        "errors": [],
    }


class TrustedStagingLauncherTests(unittest.TestCase):
    def test_cli_requires_isolated_mode_before_argument_parsing(self):
        completed = subprocess.run(
            [sys.executable, str(LAUNCHER)],
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result["phase"], "trusted-staging-launcher")
        self.assertIn("isolated mode", result["errors"][0])
        self.assertEqual(completed.stderr, "")
        self.assertIsNone(result["created"])
        self.assertEqual(result["artifactState"], "unknown")

    def test_environment_is_allowlisted_and_git_is_fixed(self):
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/attacker",
                "CLAWHUB_TOKEN": "secret",
                "PYTHONPATH": "/attacker",
                "DYLD_INSERT_LIBRARIES": "/attacker.dylib",
            },
            clear=True,
        ):
            environment = MODULE.child_environment(Path("/usr/bin/git"))
        self.assertEqual(
            environment,
            {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )
        self.assertEqual(MODULE.TRUSTED_GIT_ENTRY, Path("/usr/bin/git"))

    def test_bounded_child_enforces_output_and_wall_clock_limits(self):
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with mock.patch.object(MODULE, "MAX_CHILD_OUTPUT_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "output exceeds"):
                    MODULE.run_bounded_child(
                        [
                            sys.executable,
                            "-I",
                            "-c",
                            "import os; os.write(1, b'x' * 2048)",
                        ],
                        cwd=root,
                        environment=environment,
                        payload=b"",
                    )
            with mock.patch.object(MODULE, "CHILD_TIMEOUT_SECONDS", 0.05):
                with self.assertRaises(subprocess.TimeoutExpired):
                    MODULE.run_bounded_child(
                        [
                            sys.executable,
                            "-I",
                            "-c",
                            "import time; time.sleep(10)",
                        ],
                        cwd=root,
                        environment=environment,
                        payload=b"",
                    )
                with self.assertRaises(subprocess.TimeoutExpired):
                    MODULE.run_bounded_child(
                        [
                            sys.executable,
                            "-I",
                            "-c",
                            "import time; time.sleep(10)",
                        ],
                        cwd=root,
                        environment=environment,
                        payload=b"x" * (2 * 1024 * 1024),
                    )
            with mock.patch.object(MODULE, "MAX_CHILD_OUTPUT_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "output exceeds"):
                    MODULE.run_bounded_child(
                        [
                            sys.executable,
                            "-I",
                            "-c",
                            (
                                "import os; "
                                "os.write(1, b'x' * 700); "
                                "os.write(2, b'y' * 700)"
                            ),
                        ],
                        cwd=root,
                        environment=environment,
                        payload=b"",
                    )

    def test_frame_is_length_prefixed_and_contains_no_temp_paths(self):
        request = {"candidateRoot": "/candidate", "dryRun": True}
        guard_frame = MODULE.frame_guard(b"guard", request)
        builder_frame = MODULE.frame_builder(b"guard", b"builder", request)
        for framed in (guard_frame, builder_frame):
            self.assertTrue(framed.startswith(MODULE.FRAME_MAGIC))
            self.assertIn(b"guard", framed)
            self.assertIn(MODULE.canonical_json_bytes(request), framed)
            self.assertEqual(framed.count(MODULE.FRAME_MAGIC), 1)
        self.assertNotIn(b"builder", guard_frame)
        self.assertIn(b"builder", builder_frame)

    def test_git_output_is_incrementally_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "repository"
            make_candidate(root)
            for index in range(100):
                (root / f"untracked-{index:03d}-with-long-name.txt").write_text(
                    "x\n",
                    encoding="utf-8",
                )
            with mock.patch.object(MODULE, "MAX_GIT_OUTPUT_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "trusted Git output exceeds"):
                    MODULE.run_git(
                        Path("/usr/bin/git"),
                        root,
                        "status",
                        "--porcelain=v1",
                        "-z",
                    )

    def test_strict_child_and_manifest_validation_rejects_ambiguity(self):
        head = "a" * 40
        expected_guard_digest = valid_result(head)["manifest"][
            "guardResultDigest"
        ]
        MODULE.validate_child_result(
            valid_result(head),
            0,
            head,
            expected_guard_digest,
        )
        for raw, expected in (
            (b'{"valid":true,"valid":false}', "duplicate key"),
            (b'{"valid":NaN}', "invalid constant"),
            (b"[]", "JSON object"),
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, expected):
                    MODULE.parse_strict_json(raw, "child result")
        wrong = valid_result(head)
        wrong["manifest"]["artifactDigest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "artifactDigest"):
            MODULE.validate_child_result(
                wrong,
                0,
                head,
                expected_guard_digest,
            )
        wrong_guard = valid_result(head, "sha256:" + "1" * 64)
        with self.assertRaisesRegex(ValueError, "frozen guard result"):
            MODULE.validate_child_result(
                wrong_guard,
                0,
                head,
                expected_guard_digest,
            )
        extra = valid_result(head)
        extra["secret"] = "not-allowed"
        with self.assertRaisesRegex(ValueError, "fields"):
            MODULE.validate_child_result(
                extra,
                0,
                head,
                expected_guard_digest,
            )

    def test_builder_bootstrap_consumes_parent_frozen_guard_result(self):
        head = "a" * 40
        guard_result = valid_guard_result(head)
        guard_digest = (
            "sha256:"
            + MODULE.hashlib.sha256(
                MODULE.canonical_json_bytes(guard_result)
            ).hexdigest()
        )
        result = valid_result(head, guard_digest)
        guard_source = (
            b"def evaluate(*args, **kwargs):\n"
            b"    raise RuntimeError('builder must not rerun guard')\n"
        )
        builder_source = (
            "import json\n"
            "GUARD.evaluate = lambda *args, **kwargs: {'forged': True}\n"
            "def build_staging(repo_root, output_parent, *, guard_result):\n"
            f"    assert guard_result['headCommit'] == {head!r}\n"
            f"    return json.loads({json.dumps(json.dumps(result))})\n"
        ).encode()
        request = {
            "guardPath": "/control/guard.py",
            "builderPath": "/control/builder.py",
            "candidateRoot": "/candidate",
            "outputParent": "/output",
            "guardResult": guard_result,
        }
        completed = MODULE.run_bounded_child(
            [sys.executable, "-I", "-c", MODULE.BUILDER_BOOTSTRAP],
            cwd=ROOT,
            environment=MODULE.child_environment(Path("/usr/bin/git")),
            payload=MODULE.frame_builder(
                guard_source,
                builder_source,
                request,
            ),
        )
        observed = MODULE.parse_strict_json(completed.stdout, "child result")
        MODULE.validate_child_result(observed, completed.returncode, head, guard_digest)

    def test_snapshot_reads_guard_and_builder_from_one_control_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory).resolve() / "control"
            commit = make_control(control)
            git_path = Path(shutil.which("git")).resolve()
            sources, evidence = MODULE.snapshot_control(
                git_path, control, commit
            )
            self.assertEqual(set(sources), {"guard", "builder"})
            self.assertEqual(
                evidence["guard"]["path"], MODULE.CONTROL_FILES["guard"]
            )
            self.assertEqual(
                evidence["builder"]["path"], MODULE.CONTROL_FILES["builder"]
            )
            (control / MODULE.CONTROL_FILES["builder"]).write_text(
                "tampered worktree bytes\n", encoding="utf-8"
            )
            repeated, _ = MODULE.snapshot_control(git_path, control, commit)
            self.assertEqual(repeated, sources)

    def test_control_origin_and_remote_reachability_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory).resolve() / "control"
            commit = make_control(control)
            git_path = Path("/usr/bin/git")
            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/attacker/repository.git",
                ],
                cwd=control,
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "expected repository"):
                MODULE.repository_identity(git_path, control, "control")

            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/bonniegeng-max/openclaw-publisher.git",
                ],
                cwd=control,
                check=True,
            )
            unrelated = subprocess.check_output(
                [
                    "git",
                    "commit-tree",
                    f"{commit}^{{tree}}",
                    "-m",
                    "unrelated",
                ],
                cwd=control,
                text=True,
            ).strip()
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", unrelated],
                cwd=control,
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "reachable"):
                MODULE.snapshot_control(git_path, control, commit)

    def test_repository_identity_rejects_hardlinked_object_files(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory).resolve() / "candidate"
            make_candidate(candidate)
            object_file = next(
                path
                for path in (candidate / ".git" / "objects").rglob("*")
                if path.is_file()
            )
            os.link(object_file, object_file.with_name(object_file.name + ".linked"))
            with self.assertRaisesRegex(ValueError, "hardlinked"):
                MODULE.repository_identity(
                    Path("/usr/bin/git"),
                    candidate,
                    "candidate",
                )

    def test_probe_reports_absent_when_child_claims_missing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve()
            os.chmod(output, 0o700)
            state, created = MODULE.probe_artifact_state(
                output,
                MODULE.directory_path_identity(output),
                "demo-skill-" + "a" * 12 + "-" + "b" * 12,
            )
            self.assertEqual(state, "absent")
            self.assertFalse(created)

    def test_run_staging_rejects_shared_object_store_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            candidate.mkdir()
            control.mkdir()
            output.mkdir()
            with mock.patch.object(
                MODULE,
                "resolve_executables",
                return_value=(Path(sys.executable), Path("/usr/bin/git")),
            ), mock.patch.object(
                MODULE,
                "repository_identity",
                side_effect=[
                    (1, 1, 9, 9),
                    (2, 2, 9, 9),
                ],
            ):
                code, result = MODULE.run_staging(
                    candidate,
                    control,
                    "d" * 40,
                    output,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )
            self.assertEqual(code, 2)
            self.assertIn("must be independent", result["errors"][0])
            self.assertEqual(result["artifactState"], "absent")

    def test_run_staging_uses_isolated_child_and_rejects_stderr_timeout_and_size(self):
        head = "a" * 40
        payload = valid_result(head)
        guard_completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(valid_guard_result(head)).encode(),
            stderr=b"",
        )
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(payload).encode(),
            stderr=b"",
        )
        sources = {"guard": b"guard", "builder": b"builder"}
        evidence = {
            name: {
                "path": path,
                "mode": "100644",
                "blobOid": "b" * 40,
                "sha256": "sha256:" + "c" * 64,
            }
            for name, path in MODULE.CONTROL_FILES.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            candidate.mkdir()
            control.mkdir()
            output.mkdir()
            patches = (
                mock.patch.object(
                    MODULE, "resolve_executables",
                    return_value=(Path(sys.executable), Path("/usr/bin/git")),
                ),
                mock.patch.object(
                    MODULE, "repository_identity",
                    side_effect=[
                        (1, 1, 1, 1),
                        (1, 2, 1, 2),
                        (1, 1, 1, 1),
                        (1, 2, 1, 2),
                    ],
                ),
                mock.patch.object(
                    MODULE, "candidate_head",
                    side_effect=[head, head],
                ),
                mock.patch.object(
                    MODULE, "require_tracking_ref_consistency",
                ),
                mock.patch.object(
                    MODULE, "require_guard_tree_binding",
                ),
                mock.patch.object(
                    MODULE, "snapshot_control",
                    return_value=(sources, evidence),
                ),
                mock.patch.object(
                    MODULE, "verify_artifact",
                    return_value={"manifestMatched": True},
                ),
                mock.patch.object(
                    MODULE,
                    "run_bounded_child",
                    side_effect=[guard_completed, completed],
                ),
            )
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patches[6],
                patches[7] as run,
            ):
                code, result = MODULE.run_staging(
                    candidate,
                    control,
                    "d" * 40,
                    output,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )
            self.assertEqual(code, 0)
            self.assertTrue(result["valid"])
            command = run.call_args.args[0]
            self.assertEqual(command[1:3], ["-I", "-c"])
            self.assertEqual(
                run.call_args.kwargs["environment"]["PATH"],
                "/usr/bin",
            )
            self.assertNotIn(
                "CLAWHUB_TOKEN",
                run.call_args.kwargs["environment"],
            )
            self.assertTrue(
                run.call_args.kwargs["payload"].startswith(MODULE.FRAME_MAGIC)
            )

            for label, replacement, expected in (
                (
                    "stderr",
                    subprocess.CompletedProcess(
                        args=[], returncode=0,
                        stdout=json.dumps(payload).encode(),
                        stderr=b"warning",
                    ),
                    "unexpected stderr",
                ),
                (
                    "size",
                    subprocess.CompletedProcess(
                        args=[], returncode=2,
                        stdout=b"x" * (MODULE.MAX_CHILD_OUTPUT_BYTES + 1),
                        stderr=b"",
                    ),
                    "exceeds limit",
                ),
            ):
                with self.subTest(label=label), mock.patch.object(
                    MODULE, "resolve_executables",
                    return_value=(Path(sys.executable), Path("/usr/bin/git")),
                ), mock.patch.object(
                    MODULE,
                    "repository_identity",
                    side_effect=[(1, 1, 2, 1), (1, 2, 2, 2)],
                ), mock.patch.object(
                    MODULE, "candidate_head", return_value=head
                ), mock.patch.object(
                    MODULE, "require_tracking_ref_consistency"
                ), mock.patch.object(
                    MODULE, "require_guard_tree_binding"
                ), mock.patch.object(
                    MODULE, "snapshot_control", return_value=(sources, evidence)
                ), mock.patch.object(
                    MODULE,
                    "run_bounded_child",
                    side_effect=[guard_completed, replacement],
                ):
                    code, result = MODULE.run_staging(
                        candidate, control, "d" * 40, output,
                        event_name="workflow_dispatch", dry_run=True,
                        changed_only=True, skill_path="skills/demo-skill",
                    )
                self.assertEqual(code, 2)
                self.assertIn(expected, result["errors"][0])

            with mock.patch.object(
                MODULE, "resolve_executables",
                return_value=(Path(sys.executable), Path("/usr/bin/git")),
            ), mock.patch.object(
                MODULE,
                "repository_identity",
                side_effect=[(1, 1, 2, 1), (1, 2, 2, 2)],
            ), mock.patch.object(
                MODULE, "candidate_head", return_value=head
            ), mock.patch.object(
                MODULE, "require_tracking_ref_consistency"
            ), mock.patch.object(
                MODULE, "require_guard_tree_binding"
            ), mock.patch.object(
                MODULE, "snapshot_control", return_value=(sources, evidence)
            ), mock.patch.object(
                MODULE,
                "run_bounded_child",
                side_effect=[
                    guard_completed,
                    subprocess.TimeoutExpired("child", 180),
                ],
            ):
                code, result = MODULE.run_staging(
                    candidate, control, "d" * 40, output,
                    event_name="workflow_dispatch", dry_run=True,
                    changed_only=True, skill_path="skills/demo-skill",
                )
            self.assertEqual(code, 2)
            self.assertIn("timed out", result["errors"][0])

    def test_end_to_end_uses_control_blobs_and_verifies_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            output.mkdir(mode=0o700)
            os.chmod(output, 0o700)
            candidate_head = make_candidate(candidate)
            control_commit = make_control(control)
            completed = subprocess.run(
                [
                    sys.executable, "-I", str(LAUNCHER),
                    "--candidate-root", str(candidate),
                    "--control-root", str(control),
                    "--control-commit", control_commit,
                    "--output-parent", str(output),
                    "--event-name", "workflow_dispatch",
                    "--dry-run", "true",
                    "--changed-only", "true",
                    "--skill-path", "skills/demo-skill",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            result = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0, result["errors"])
            self.assertTrue(result["valid"])
            self.assertEqual(result["manifest"]["source"]["commit"], candidate_head)
            observations = result["launcherObservations"]
            self.assertTrue(observations["sameControlCommit"])
            self.assertTrue(observations["independentCheckouts"])
            self.assertTrue(
                observations["artifactVerification"]["artifactDigestVerified"]
            )
            self.assertEqual(
                result["artifactState"],
                "present-verified-snapshot",
            )
            self.assertFalse(observations["formalWorkflowWired"])
            self.assertEqual(completed.stderr, "")
            staged_skill = (
                output / result["outputName"] / "package" / "SKILL.md"
            )
            staged_skill.chmod(0o644)
            staged_skill.write_text("tampered\n", encoding="utf-8")
            staged_skill.chmod(0o444)
            with self.assertRaisesRegex(ValueError, "digest is invalid"):
                MODULE.verify_artifact(
                    output,
                    {
                        key: value
                        for key, value in result.items()
                        if key != "launcherObservations"
                    },
                    candidate_head,
                    Path("/usr/bin/git"),
                    candidate,
                )

            forged = copy.deepcopy(result["manifest"])
            forged["source"]["treeOid"] = "0" * 40
            package_payload = {
                "files": [
                    {
                        "path": item["path"],
                        "mode": item["sourceMode"],
                        "blobOid": item["blobOid"],
                        "sha256": item["sha256"],
                    }
                    for item in forged["files"]
                ],
                "format": "safe-publish-package-v1",
                "skillPath": forged["source"]["skillPath"],
                "treeOid": forged["source"]["treeOid"],
            }
            forged["source"]["packageDigest"] = (
                "sha256:"
                + MODULE.hashlib.sha256(
                    MODULE.canonical_json_bytes(package_payload)
                ).hexdigest()
            )
            descriptor = {
                key: value
                for key, value in forged.items()
                if key != "artifactDigest"
            }
            forged["artifactDigest"] = (
                "sha256:"
                + MODULE.hashlib.sha256(
                    MODULE.canonical_json_bytes(descriptor)
                ).hexdigest()
            )
            with self.assertRaisesRegex(ValueError, "treeOid"):
                MODULE.require_manifest_tree_binding(
                    forged,
                    Path("/usr/bin/git"),
                    candidate,
                )

    def test_tracking_ref_move_after_builder_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            output.mkdir(mode=0o700)
            os.chmod(output, 0o700)
            candidate_head = make_candidate(candidate)
            control_commit = make_control(control)
            unrelated = subprocess.check_output(
                [
                    "git",
                    "commit-tree",
                    f"{candidate_head}^{{tree}}",
                    "-m",
                    "moved tracking ref",
                ],
                cwd=candidate,
                text=True,
            ).strip()
            original = MODULE.run_bounded_child
            child_count = 0

            def move_after_builder(*args, **kwargs):
                nonlocal child_count
                completed = original(*args, **kwargs)
                command = args[0]
                if MODULE.BUILDER_BOOTSTRAP in command:
                    child_count += 1
                if child_count == 1 and MODULE.BUILDER_BOOTSTRAP in command:
                    subprocess.run(
                        [
                            "git",
                            "update-ref",
                            "refs/remotes/origin/main",
                            unrelated,
                        ],
                        cwd=candidate,
                        check=True,
                    )
                    child_count += 1
                return completed

            with mock.patch.object(
                MODULE,
                "run_bounded_child",
                side_effect=move_after_builder,
            ):
                code, result = MODULE.run_staging(
                    candidate,
                    control,
                    control_commit,
                    output,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )
            self.assertEqual(code, 2)
            self.assertIn("HEAD must equal origin/main", result["errors"][0])
            self.assertEqual(
                result["artifactState"],
                "present-verified-snapshot",
            )
            self.assertTrue(result["created"])

    def test_artifact_path_swap_after_first_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            output.mkdir(mode=0o700)
            os.chmod(output, 0o700)
            make_candidate(candidate)
            control_commit = make_control(control)
            original = MODULE.verify_artifact
            verification_count = 0

            def swap_after_first_verification(*args, **kwargs):
                nonlocal verification_count
                evidence = original(*args, **kwargs)
                verification_count += 1
                if verification_count == 1:
                    result = args[1]
                    artifact = output / result["outputName"]
                    artifact.rename(output / ".verified-original")
                    artifact.mkdir(mode=0o555)
                    os.chmod(artifact, 0o555)
                return evidence

            with mock.patch.object(
                MODULE,
                "verify_artifact",
                side_effect=swap_after_first_verification,
            ):
                code, result = MODULE.run_staging(
                    candidate,
                    control,
                    control_commit,
                    output,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )
            self.assertEqual(code, 2)
            self.assertIn("root entries", result["errors"][0])
            self.assertEqual(result["artifactState"], "present-unverified")
            self.assertTrue(result["created"])

    def test_committed_artifact_is_probed_when_builder_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            output = workspace / "output"
            output.mkdir(mode=0o700)
            os.chmod(output, 0o700)
            make_candidate(candidate)
            init_repository(control)
            for name, relative in MODULE.CONTROL_FILES.items():
                destination = control / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = (ROOT / relative).read_text(encoding="utf-8")
                if name == "builder":
                    source += """

_trusted_original_build_staging = build_staging
def build_staging(repo_root, output_parent, *, guard_result):
    _trusted_original_build_staging(
        repo_root,
        output_parent,
        guard_result=guard_result,
    )
    return {"unserializable": {1}}
"""
                destination.write_text(source, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=control, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "faulty control"],
                cwd=control,
                check=True,
            )
            control_commit = git(control, "rev-parse", "HEAD")
            subprocess.run(
                [
                    "git",
                    "update-ref",
                    "refs/remotes/origin/main",
                    control_commit,
                ],
                cwd=control,
                check=True,
            )
            code, result = MODULE.run_staging(
                candidate,
                control,
                control_commit,
                output,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )
            self.assertEqual(code, 2)
            self.assertIn("unexpected stderr", result["errors"][0])
            self.assertEqual(
                result["artifactState"],
                "present-verified-snapshot",
            )
            self.assertTrue(result["created"])
            self.assertTrue(result["outputName"])

    def test_launcher_source_has_no_secret_network_or_workflow_surface(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        for forbidden in (
            "CLAWHUB_TOKEN", "PYTHONPATH", "requests", "urllib", "socket.",
            "shell=True", "clawhub ", ".github/workflows",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import hashlib
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
LAUNCHER = (
    ROOT
    / "research"
    / "skill-release-authorization-vnext"
    / "trusted_preflight_launcher.py"
)
SPEC = importlib.util.spec_from_file_location(
    "trusted_preflight_launcher",
    LAUNCHER,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

CONTROL_COMMIT = "a" * 40
BASE_COMMIT = "b" * 40
CANDIDATE_COMMIT = "1" * 40
HEAD_COMMIT = "2" * 40


def valid_checker_result(authorized=True):
    return {
        "valid": True,
        "authorized": authorized,
        "mode": "publish",
        "evaluatedAt": "2026-09-13T00:00:00+00:00",
        "releaseId": "demo-skill-1.0.1",
        "baseCommit": BASE_COMMIT,
        "candidateCommit": CANDIDATE_COMMIT,
        "headCommit": HEAD_COMMIT,
        "targets": [{"slug": "demo-skill", "version": "1.0.1"}],
        "catalogChanged": False,
        "contentDigest": "sha256:" + "3" * 64,
        "changeSetDigest": "sha256:" + "4" * 64,
        "authorizationChanged": True,
        "blockingReasons": [] if authorized else ["fresh-review"],
        "errors": [],
        "trustedControl": {
            "repository": MODULE.EXPECTED_REPOSITORY,
            "commit": CONTROL_COMMIT,
            "files": {
                "checker": {
                    "path": MODULE.TRUSTED_FILE_PATHS["checker"],
                    "blobOid": "c" * 40,
                    "sha256": "sha256:" + "d" * 64,
                },
                "validator": {
                    "path": MODULE.TRUSTED_FILE_PATHS["validator"],
                    "blobOid": "e" * 40,
                    "sha256": "sha256:" + "f" * 64,
                },
            },
            "independentCheckout": True,
            "executingCheckerPathMatched": True,
        },
    }


def invalid_checker_result():
    return {
        "valid": False,
        "authorized": False,
        "mode": "publish",
        "evaluatedAt": "2026-09-13T00:00:00+00:00",
        "targets": [],
        "blockingReasons": [],
        "errors": ["invalid"],
    }


class TrustedPreflightLauncherTests(unittest.TestCase):
    def expected_files(self):
        return valid_checker_result()["trustedControl"]["files"]

    def test_requires_python_isolated_mode_before_argument_parsing(self):
        completed = subprocess.run(
            [sys.executable, str(LAUNCHER)],
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result["phase"], "trusted-launcher")
        self.assertIn("isolated mode", result["errors"][0])
        self.assertEqual(completed.stderr, "")

    def test_isolated_cli_argument_errors_are_structured(self):
        completed = subprocess.run(
            [sys.executable, "-I", str(LAUNCHER)],
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(result["phase"], "trusted-launcher")
        self.assertIn("invalid launcher arguments", result["errors"][0])
        self.assertEqual(completed.stderr, "")

    def test_resolve_executables_ignores_inherited_path_for_git(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_git = Path(directory) / "git"
            fake_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_git.chmod(0o755)

            with mock.patch.dict(
                os.environ,
                {"PATH": str(fake_git.parent)},
                clear=False,
            ):
                _, git_path = MODULE.resolve_executables()

        self.assertEqual(git_path, MODULE.TRUSTED_GIT_ENTRY)
        self.assertNotEqual(git_path, fake_git)

    def test_resolve_executables_rejects_unusable_fixed_git(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for label, path, expected in (
                (
                    "missing",
                    workspace / "missing-git",
                    "cannot be resolved",
                ),
                (
                    "not-executable",
                    workspace / "non-executable-git",
                    "must be executable",
                ),
            ):
                with self.subTest(label=label):
                    if label == "not-executable":
                        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                        path.chmod(0o644)
                    with mock.patch.object(
                        MODULE,
                        "TRUSTED_GIT_ENTRY",
                        path,
                    ):
                        with self.assertRaisesRegex(ValueError, expected):
                            MODULE.resolve_executables()

    def test_child_environment_is_allowlisted(self):
        sensitive = {
            "CLAWHUB_TOKEN": "secret",
            "GH_TOKEN": "secret",
            "PYTHONPATH": "/attacker",
            "PYTHONHOME": "/attacker",
            "GIT_DIR": "/attacker",
            "LD_PRELOAD": "/attacker/library.so",
            "DYLD_INSERT_LIBRARIES": "/attacker/library.dylib",
            "PATH": "/attacker/bin",
            "HOME": "/trusted/home",
            "LANG": "C.UTF-8",
        }
        git_path = Path("/trusted/bin/git")

        with mock.patch.dict(os.environ, sensitive, clear=True):
            environment = MODULE.child_environment(git_path)

        self.assertEqual(
            environment,
            {
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/trusted/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )

    def test_strict_checker_json_rejects_ambiguous_values(self):
        for value, expected in (
            ('{"valid": true, "valid": false}', "duplicate key"),
            ('{"valid": NaN}', "invalid constant"),
            ("[]", "JSON object"),
            ("not-json", "strict JSON"),
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, expected):
                    MODULE.parse_checker_output(value)

    def test_checker_result_binds_status_mode_target_and_control(self):
        MODULE.validate_checker_result(
            valid_checker_result(),
            0,
            "publish",
            CONTROL_COMMIT,
            BASE_COMMIT,
            CANDIDATE_COMMIT,
            HEAD_COMMIT,
            self.expected_files(),
        )
        MODULE.validate_checker_result(
            valid_checker_result(authorized=False),
            1,
            "publish",
            CONTROL_COMMIT,
            BASE_COMMIT,
            CANDIDATE_COMMIT,
            HEAD_COMMIT,
            self.expected_files(),
        )
        MODULE.validate_checker_result(
            invalid_checker_result(),
            2,
            "publish",
            CONTROL_COMMIT,
            BASE_COMMIT,
            CANDIDATE_COMMIT,
            HEAD_COMMIT,
            self.expected_files(),
        )

        mutations = []
        wrong_mode = valid_checker_result()
        wrong_mode["mode"] = "dry-run"
        mutations.append(("mode does not match", wrong_mode, 0))

        wrong_commit = valid_checker_result()
        wrong_commit["trustedControl"]["commit"] = "0" * 40
        mutations.append(("commit does not match", wrong_commit, 0))

        wrong_repository = valid_checker_result()
        wrong_repository["trustedControl"]["repository"] = "github.com/attacker/repo"
        mutations.append(("repository does not match", wrong_repository, 0))

        wrong_base = valid_checker_result()
        wrong_base["baseCommit"] = "0" * 40
        mutations.append(("baseCommit does not match", wrong_base, 0))

        wrong_candidate = valid_checker_result()
        wrong_candidate["candidateCommit"] = "5" * 40
        mutations.append(
            ("candidateCommit does not match candidate parent", wrong_candidate, 0)
        )

        wrong_head = valid_checker_result()
        wrong_head["headCommit"] = "6" * 40
        mutations.append(("headCommit does not match candidate HEAD", wrong_head, 0))

        wrong_slug = valid_checker_result()
        wrong_slug["targets"][0]["slug"] = "../../other"
        wrong_slug["releaseId"] = "../../other-1.0.1"
        mutations.append(("slug or version is invalid", wrong_slug, 0))

        wrong_version = valid_checker_result()
        wrong_version["targets"][0]["version"] = "--help"
        wrong_version["releaseId"] = "demo-skill---help"
        mutations.append(("slug or version is invalid", wrong_version, 0))

        multiple_targets = valid_checker_result()
        multiple_targets["targets"].append(
            {"slug": "other-skill", "version": "1.0.0"}
        )
        mutations.append(("exactly one target", multiple_targets, 0))

        missing_path_match = valid_checker_result()
        missing_path_match["trustedControl"]["executingCheckerPathMatched"] = False
        mutations.append(("checker path did not match", missing_path_match, 0))

        forged_file = valid_checker_result()
        forged_file["trustedControl"]["files"]["checker"]["sha256"] = (
            "sha256:" + "0" * 64
        )
        mutations.append(("file evidence does not match", forged_file, 0))

        for expected, result, returncode in mutations:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    MODULE.validate_checker_result(
                        result,
                        returncode,
                        "publish",
                        CONTROL_COMMIT,
                        BASE_COMMIT,
                        CANDIDATE_COMMIT,
                        HEAD_COMMIT,
                        self.expected_files(),
                    )

        with self.assertRaisesRegex(ValueError, "exit code"):
            MODULE.validate_checker_result(
                valid_checker_result(),
                1,
                "publish",
                CONTROL_COMMIT,
                BASE_COMMIT,
                CANDIDATE_COMMIT,
                HEAD_COMMIT,
                self.expected_files(),
            )

    def test_run_preflight_uses_fixed_isolated_command_and_clean_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            candidate.mkdir()
            checker = control / MODULE.CHECKER_RELATIVE
            checker.parent.mkdir(parents=True)
            checker.write_text("# trusted checker fixture\n", encoding="utf-8")
            payload = valid_checker_result()
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(payload).encode(),
                stderr=b"",
            )

            with mock.patch.object(
                MODULE,
                "resolve_executables",
                return_value=(Path(sys.executable).resolve(), Path("/usr/bin/git")),
            ), mock.patch.object(
                MODULE,
                "candidate_commit_state",
                return_value=(CANDIDATE_COMMIT, HEAD_COMMIT),
            ), mock.patch.object(
                MODULE,
                "snapshot_control_files",
                return_value=(
                    b"# trusted checker fixture\n",
                    self.expected_files(),
                ),
            ), mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=completed,
            ) as run:
                returncode, result = MODULE.run_preflight(
                    candidate,
                    control,
                    CONTROL_COMMIT,
                    BASE_COMMIT,
                    "publish",
                )

        self.assertEqual(returncode, 0)
        self.assertTrue(result["authorized"])
        self.assertTrue(
            result["launcherObservations"]["isolatedModeObserved"]
        )
        self.assertNotIn("pythonExecutable", result["launcherObservations"])
        self.assertNotIn("gitExecutable", result["launcherObservations"])
        command = run.call_args.args[0]
        self.assertEqual(command[1], "-I")
        self.assertEqual(command[2], "-c")
        self.assertEqual(command[4], str(checker))
        self.assertIn("--repo-root", command)
        self.assertIn("--control-root", command)
        self.assertIn("--control-commit", command)
        self.assertNotIn("shell", run.call_args.kwargs)
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("CLAWHUB_TOKEN", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertEqual(
            run.call_args.kwargs["input"],
            b"# trusted checker fixture\n",
        )

    def test_control_snapshot_is_bound_to_commit_and_disk_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory).resolve() / "control"
            scripts = control / "scripts"
            scripts.mkdir(parents=True)
            for relative in MODULE.TRUSTED_FILE_PATHS.values():
                shutil.copy2(ROOT / relative, control / relative)
            subprocess.run(["git", "init", "-q"], cwd=control, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=control,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=control,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=control, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "control snapshot"],
                cwd=control,
                check=True,
            )
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=control,
                text=True,
            ).strip()
            git_path = Path(shutil.which("git")).resolve()

            checker_snapshot, evidence = MODULE.snapshot_control_files(
                git_path,
                control,
                commit,
            )
            self.assertEqual(
                checker_snapshot,
                (control / MODULE.CHECKER_RELATIVE).read_bytes(),
            )
            self.assertEqual(
                evidence["checker"]["sha256"],
                "sha256:" + hashlib.sha256(checker_snapshot).hexdigest(),
            )

            with (control / MODULE.CHECKER_RELATIVE).open("ab") as stream:
                stream.write(b"\n# tampered\n")
            with self.assertRaisesRegex(
                ValueError,
                "bytes do not match control commit",
            ):
                MODULE.snapshot_control_files(
                    git_path,
                    control,
                    commit,
                )

    def test_run_preflight_rejects_stderr_timeout_and_malformed_result(self):
        cases = (
            (
                "stderr",
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(valid_checker_result()).encode(),
                    stderr=b"unexpected warning",
                ),
                "unexpected stderr",
            ),
            (
                "malformed",
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=b"not-json",
                    stderr=b"",
                ),
                "strict JSON",
            ),
        )
        for label, completed, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory).resolve()
                control = workspace / "control"
                (workspace / "candidate").mkdir()
                checker = control / MODULE.CHECKER_RELATIVE
                checker.parent.mkdir(parents=True)
                checker.write_text("# fixture\n", encoding="utf-8")
                with mock.patch.object(
                    MODULE,
                    "resolve_executables",
                    return_value=(
                        Path(sys.executable).resolve(),
                        Path("/usr/bin/git"),
                    ),
                ), mock.patch.object(
                    MODULE,
                    "candidate_commit_state",
                    return_value=(CANDIDATE_COMMIT, HEAD_COMMIT),
                ), mock.patch.object(
                    MODULE,
                    "snapshot_control_files",
                    return_value=(
                        b"# fixture\n",
                        self.expected_files(),
                    ),
                ), mock.patch.object(
                    MODULE.subprocess,
                    "run",
                    return_value=completed,
                ):
                    returncode, result = MODULE.run_preflight(
                        workspace / "candidate",
                        control,
                        CONTROL_COMMIT,
                        BASE_COMMIT,
                        "publish",
                    )
            self.assertEqual(returncode, 2)
            self.assertEqual(result["phase"], "trusted-launcher")
            self.assertIn(expected, result["errors"][0])

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            control = workspace / "control"
            (workspace / "candidate").mkdir()
            checker = control / MODULE.CHECKER_RELATIVE
            checker.parent.mkdir(parents=True)
            checker.write_text("# fixture\n", encoding="utf-8")
            with mock.patch.object(
                MODULE,
                "resolve_executables",
                return_value=(
                    Path(sys.executable).resolve(),
                    Path("/usr/bin/git"),
                ),
            ), mock.patch.object(
                MODULE,
                "candidate_commit_state",
                return_value=(CANDIDATE_COMMIT, HEAD_COMMIT),
            ), mock.patch.object(
                MODULE,
                "snapshot_control_files",
                return_value=(
                    b"# fixture\n",
                    self.expected_files(),
                ),
            ), mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("checker", 120),
            ):
                returncode, result = MODULE.run_preflight(
                    workspace / "candidate",
                    control,
                    CONTROL_COMMIT,
                    BASE_COMMIT,
                    "publish",
                )

        self.assertEqual(returncode, 2)
        self.assertEqual(result["phase"], "trusted-launcher")
        self.assertIn("execution timed out", result["errors"][0])

    def test_checker_output_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            candidate = workspace / "candidate"
            control = workspace / "control"
            candidate.mkdir()
            checker = control / MODULE.CHECKER_RELATIVE
            checker.parent.mkdir(parents=True)
            checker.write_text("# fixture\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"x" * (MODULE.MAX_CHECKER_OUTPUT_BYTES + 1),
                stderr=b"",
            )
            with mock.patch.object(
                MODULE,
                "resolve_executables",
                return_value=(
                    Path(sys.executable).resolve(),
                    Path("/usr/bin/git"),
                ),
            ), mock.patch.object(
                MODULE,
                "candidate_commit_state",
                return_value=(CANDIDATE_COMMIT, HEAD_COMMIT),
            ), mock.patch.object(
                MODULE,
                "snapshot_control_files",
                return_value=(
                    b"# fixture\n",
                    self.expected_files(),
                ),
            ), mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=completed,
            ):
                returncode, result = MODULE.run_preflight(
                    candidate,
                    control,
                    CONTROL_COMMIT,
                    BASE_COMMIT,
                    "publish",
                )

        self.assertEqual(returncode, 2)
        self.assertEqual(result["phase"], "trusted-launcher")
        self.assertIn("output exceeds", result["errors"][0])

    def test_parent_symlink_is_rejected_before_checker_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            real_parent = workspace / "real"
            control = real_parent / "control"
            candidate = workspace / "candidate"
            checker = control / MODULE.CHECKER_RELATIVE
            checker.parent.mkdir(parents=True)
            checker.write_text("# fixture\n", encoding="utf-8")
            candidate.mkdir()
            alias = workspace / "alias"
            alias.symlink_to(real_parent, target_is_directory=True)

            with mock.patch.object(MODULE.subprocess, "run") as run:
                returncode, result = MODULE.run_preflight(
                    candidate,
                    alias / "control",
                    CONTROL_COMMIT,
                    BASE_COMMIT,
                    "publish",
                )

        self.assertEqual(returncode, 2)
        self.assertEqual(result["phase"], "trusted-launcher")
        self.assertIn("must not contain symlinks", result["errors"][0])
        run.assert_not_called()

    def test_extra_checker_fields_are_rejected_and_invalid_output_is_minimized(self):
        result = valid_checker_result()
        result["secret"] = "canary-secret"
        with self.assertRaisesRegex(ValueError, "fields are incomplete"):
            MODULE.validate_checker_result(
                result,
                0,
                "publish",
                CONTROL_COMMIT,
                BASE_COMMIT,
                CANDIDATE_COMMIT,
                HEAD_COMMIT,
                self.expected_files(),
            )

        for label, mutation, expected in (
            (
                "extra",
                lambda value: value.update({"secret": "canary-secret"}),
                "fields are incomplete",
            ),
            (
                "missing",
                lambda value: value.pop("evaluatedAt"),
                "fields are incomplete",
            ),
            (
                "bad-errors",
                lambda value: value.update({"errors": [1]}),
                "bounded non-empty string array",
            ),
        ):
            with self.subTest(invalid_schema=label):
                invalid = invalid_checker_result()
                mutation(invalid)
                with self.assertRaisesRegex(ValueError, expected):
                    MODULE.validate_checker_result(
                        invalid,
                        2,
                        "publish",
                        CONTROL_COMMIT,
                        BASE_COMMIT,
                        CANDIDATE_COMMIT,
                        HEAD_COMMIT,
                        self.expected_files(),
                    )

        minimized = MODULE.minimal_checker_result(
            {
                "valid": False,
                "authorized": False,
                "mode": "publish",
                "phase": "checker",
                "errors": ["safe failure"],
                "secret": "canary-secret",
            },
            2,
        )
        self.assertNotIn("secret", minimized)
        self.assertNotIn("canary-secret", json.dumps(minimized))
        self.assertEqual(minimized["phase"], "checker")

    def test_launcher_exposes_no_secret_or_network_parameters(self):
        source = LAUNCHER.read_text(encoding="utf-8")

        for forbidden in (
            "CLAWHUB_TOKEN",
            "--token",
            "--registry",
            "requests",
            "urllib",
            "socket.",
            "curl ",
            "wget ",
            "shell=True",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

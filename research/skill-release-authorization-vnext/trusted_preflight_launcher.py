#!/usr/bin/env python3
"""以隔离解释器启动受信任的 Skill 发布授权检查器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_REPOSITORY = "github.com/bonniegeng-max/openclaw-publisher"
CHECKER_RELATIVE = Path("scripts/check_skill_release_authorization.py")
ALLOWED_MODES = {"dry-run", "publish"}
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OID_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
CHECKER_TIMEOUT_SECONDS = 120
MAX_CHECKER_OUTPUT_BYTES = 1024 * 1024
TRUSTED_FILE_PATHS = {
    "checker": "scripts/check_skill_release_authorization.py",
    "validator": "scripts/validate_skill_catalog.py",
}
VALID_RESULT_FIELDS = {
    "valid",
    "authorized",
    "mode",
    "evaluatedAt",
    "releaseId",
    "baseCommit",
    "candidateCommit",
    "headCommit",
    "targets",
    "catalogChanged",
    "contentDigest",
    "changeSetDigest",
    "authorizationChanged",
    "blockingReasons",
    "errors",
    "trustedControl",
}
INVALID_RESULT_FIELDS = {
    "valid",
    "authorized",
    "mode",
    "evaluatedAt",
    "targets",
    "blockingReasons",
    "errors",
}
CHECKER_BOOTSTRAP = """
import sys
source = sys.stdin.buffer.read()
checker_path = sys.argv[1]
sys.argv = sys.argv[1:]
namespace = {
    "__name__": "__main__",
    "__file__": checker_path,
    "__package__": None,
}
exec(compile(source, checker_path, "exec"), namespace)
""".strip()


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid launcher arguments: {message}")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"checker JSON has duplicate key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> Any:
    raise ValueError(f"checker JSON contains invalid constant: {value}")


def parse_checker_output(value: str) -> dict[str, Any]:
    try:
        result = json.loads(
            value,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"checker stdout is not strict JSON: {error}") from error
    if not isinstance(result, dict):
        raise ValueError("checker stdout must be a JSON object")
    return result


def launcher_failure(message: str, checker_exit_code: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "valid": False,
        "authorized": False,
        "phase": "trusted-launcher",
        "errors": [message],
    }
    if checker_exit_code is not None:
        result["checkerExitCode"] = checker_exit_code
    return result


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def absolute_path_uses_symlink(path: Path) -> bool:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:]:
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
    except OSError as error:
        raise ValueError(f"path cannot be inspected: {error}") from error
    return False


def require_regular_file(
    path: Path,
    label: str,
    reject_hardlinks: bool = True,
) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError(f"{label} cannot be inspected: {error}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if reject_hardlinks and metadata.st_nlink != 1:
        raise ValueError(f"{label} must not have multiple hard links")


def resolve_executables() -> tuple[Path, Path]:
    python_entry = lexical_absolute(Path(sys.executable))
    python_path = python_entry.resolve()
    require_regular_file(
        python_path,
        "Python executable",
        reject_hardlinks=False,
    )
    observed_git = shutil.which("git")
    if observed_git is None:
        raise ValueError("Git executable is unavailable")
    git_entry = lexical_absolute(Path(observed_git))
    git_path = git_entry.resolve()
    require_regular_file(
        git_path,
        "Git executable",
        reject_hardlinks=False,
    )
    return python_path, git_path


def child_environment(git_path: Path) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": str(git_path.parent),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def git_command(git_path: Path, *args: str) -> list[str]:
    return [
        str(git_path),
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "diff.external=",
        *args,
    ]


def run_isolated_git(
    git_path: Path,
    repo_root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        git_command(git_path, *args),
        cwd=repo_root,
        env={
            **child_environment(git_path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_EXTERNAL_DIFF": "",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        },
        check=False,
        capture_output=True,
        text=text,
    )


def read_regular_file_snapshot(path: Path, label: str) -> tuple[bytes, int]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{label} cannot be opened safely: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if metadata.st_nlink != 1:
            raise ValueError(f"{label} must not have multiple hard links")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), metadata.st_mode
    finally:
        os.close(descriptor)


def control_file_snapshot(
    git_path: Path,
    control_root: Path,
    control_commit: str,
    label: str,
    relative: str,
) -> tuple[bytes, dict[str, str]]:
    path = control_root / relative
    if absolute_path_uses_symlink(path):
        raise ValueError(f"trusted {label} path must not contain symlinks")
    disk_bytes, disk_mode = read_regular_file_snapshot(path, f"trusted {label}")
    entry = run_isolated_git(
        git_path,
        control_root,
        "ls-tree",
        "-z",
        control_commit,
        "--",
        relative,
    )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError(f"trusted {label} must exist once at control commit")
    try:
        metadata, observed_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
        observed_relative = observed_path.decode("utf-8", errors="strict")
        mode_text = mode.decode("ascii")
        object_id_text = object_id.decode("ascii")
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"trusted {label} has malformed Git metadata") from error
    if (
        object_type != b"blob"
        or mode_text not in {"100644", "100755"}
        or observed_relative != relative
        or OID_PATTERN.fullmatch(object_id_text) is None
    ):
        raise ValueError(f"trusted {label} must be a regular Git blob")
    expected_executable = mode_text == "100755"
    if bool(disk_mode & 0o111) != expected_executable:
        raise ValueError(f"trusted {label} executable mode does not match")
    blob = run_isolated_git(
        git_path,
        control_root,
        "cat-file",
        "blob",
        object_id_text,
    )
    if blob.returncode != 0:
        raise ValueError(f"trusted {label} blob cannot be read")
    if blob.stdout != disk_bytes:
        raise ValueError(f"trusted {label} bytes do not match control commit")
    return disk_bytes, {
        "path": relative,
        "blobOid": object_id_text,
        "sha256": "sha256:" + hashlib.sha256(disk_bytes).hexdigest(),
    }


def snapshot_control_files(
    git_path: Path,
    control_root: Path,
    control_commit: str,
) -> tuple[bytes, dict[str, dict[str, str]]]:
    head = run_isolated_git(
        git_path,
        control_root,
        "rev-parse",
        "HEAD",
        text=True,
    )
    if head.returncode != 0 or head.stdout.strip() != control_commit:
        raise ValueError("control checkout HEAD does not match control commit")
    snapshots: dict[str, bytes] = {}
    evidence: dict[str, dict[str, str]] = {}
    for label, relative in TRUSTED_FILE_PATHS.items():
        snapshots[label], evidence[label] = control_file_snapshot(
            git_path,
            control_root,
            control_commit,
            label,
            relative,
        )
    return snapshots["checker"], evidence


def candidate_commit_state(
    git_path: Path,
    candidate_root: Path,
    base_commit: str,
) -> tuple[str, str]:
    head = run_isolated_git(
        git_path,
        candidate_root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        "HEAD^{commit}",
        text=True,
    )
    if head.returncode != 0:
        raise ValueError("candidate HEAD cannot be resolved")
    head_commit = head.stdout.strip()
    if COMMIT_PATTERN.fullmatch(head_commit) is None:
        raise ValueError("candidate HEAD is not a full SHA-1")

    parents = run_isolated_git(
        git_path,
        candidate_root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        head_commit,
        text=True,
    )
    parent_fields = parents.stdout.strip().split()
    if parents.returncode != 0 or len(parent_fields) != 2:
        raise ValueError(
            "candidate HEAD must be a single-parent authorization commit"
        )
    candidate_commit = parent_fields[1]
    if COMMIT_PATTERN.fullmatch(candidate_commit) is None:
        raise ValueError("candidate parent is not a full SHA-1")

    ancestry = run_isolated_git(
        git_path,
        candidate_root,
        "merge-base",
        "--is-ancestor",
        base_commit,
        candidate_commit,
    )
    if ancestry.returncode != 0:
        raise ValueError("base commit must be an ancestor of candidate commit")
    return candidate_commit, head_commit


def validate_file_evidence(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(TRUSTED_FILE_PATHS):
        raise ValueError("trustedControl.files must describe checker and validator")
    for label, expected_path in TRUSTED_FILE_PATHS.items():
        item = value[label]
        if not isinstance(item, dict) or set(item) != {
            "path",
            "blobOid",
            "sha256",
        }:
            raise ValueError(f"trustedControl.files.{label} has invalid fields")
        if item["path"] != expected_path:
            raise ValueError(f"trustedControl.files.{label}.path does not match")
        if (
            not isinstance(item["blobOid"], str)
            or OID_PATTERN.fullmatch(item["blobOid"]) is None
        ):
            raise ValueError(f"trustedControl.files.{label}.blobOid is invalid")
        if (
            not isinstance(item["sha256"], str)
            or DIGEST_PATTERN.fullmatch(item["sha256"]) is None
        ):
            raise ValueError(f"trustedControl.files.{label}.sha256 is invalid")


def validate_checker_result(
    result: dict[str, Any],
    returncode: int,
    expected_mode: str,
    expected_control_commit: str,
    expected_base_commit: str,
    expected_candidate_commit: str,
    expected_head_commit: str,
    expected_files: dict[str, dict[str, str]],
) -> None:
    valid = result.get("valid")
    authorized = result.get("authorized")
    if type(valid) is not bool or type(authorized) is not bool:
        raise ValueError("checker result must contain boolean valid and authorized")
    if result.get("mode") != expected_mode:
        raise ValueError("checker result mode does not match launcher mode")
    expected_returncode = 0 if authorized else 1 if valid else 2
    if returncode != expected_returncode:
        raise ValueError(
            "checker exit code does not match valid/authorized result"
        )
    if authorized and not valid:
        raise ValueError("checker cannot authorize an invalid result")
    if returncode == 2:
        expected_fields = set(INVALID_RESULT_FIELDS)
        if "phase" in result:
            expected_fields.add("phase")
            if result["phase"] != "trusted-control":
                raise ValueError("invalid checker phase is not recognized")
        if set(result) != expected_fields:
            raise ValueError(
                "invalid checker result fields are incomplete or unexpected"
            )
        if valid is not False or authorized is not False:
            raise ValueError("invalid checker result must deny authorization")
        if (
            not isinstance(result.get("evaluatedAt"), str)
            or not result["evaluatedAt"]
        ):
            raise ValueError("invalid checker evaluatedAt is missing")
        targets = result.get("targets")
        blockers = result.get("blockingReasons")
        errors = result.get("errors")
        if not isinstance(targets, list):
            raise ValueError("invalid checker targets must be an array")
        if (
            not isinstance(blockers, list)
            or not all(isinstance(item, str) for item in blockers)
        ):
            raise ValueError(
                "invalid checker blockingReasons must be an array of strings"
            )
        if (
            not isinstance(errors, list)
            or not errors
            or len(errors) > 100
            or not all(
                isinstance(item, str) and len(item) <= 4096
                for item in errors
            )
        ):
            raise ValueError(
                "invalid checker errors must be a bounded non-empty string array"
            )
        return
    if set(result) != VALID_RESULT_FIELDS:
        raise ValueError("valid checker result fields are incomplete or unexpected")
    if result.get("baseCommit") != expected_base_commit:
        raise ValueError("checker baseCommit does not match launcher base")
    candidate_commit = result.get("candidateCommit")
    head_commit = result.get("headCommit")
    if (
        not isinstance(candidate_commit, str)
        or COMMIT_PATTERN.fullmatch(candidate_commit) is None
    ):
        raise ValueError("checker candidateCommit is invalid")
    if (
        not isinstance(head_commit, str)
        or COMMIT_PATTERN.fullmatch(head_commit) is None
    ):
        raise ValueError("checker headCommit is invalid")
    if candidate_commit != expected_candidate_commit:
        raise ValueError("checker candidateCommit does not match candidate parent")
    if head_commit != expected_head_commit:
        raise ValueError("checker headCommit does not match candidate HEAD")

    targets = result.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise ValueError("valid checker result must contain exactly one target")
    target = targets[0]
    if (
        not isinstance(target, dict)
        or set(target) != {"slug", "version"}
        or not isinstance(target.get("slug"), str)
        or SLUG_PATTERN.fullmatch(target["slug"]) is None
        or len(target["slug"]) > 64
        or not isinstance(target.get("version"), str)
        or SEMVER_PATTERN.fullmatch(target["version"]) is None
    ):
        raise ValueError("checker target slug or version is invalid")
    if result.get("releaseId") != f"{target['slug']}-{target['version']}":
        raise ValueError("checker releaseId does not match target")
    if type(result.get("catalogChanged")) is not bool:
        raise ValueError("checker catalogChanged must be boolean")
    if type(result.get("authorizationChanged")) is not bool:
        raise ValueError("checker authorizationChanged must be boolean")
    if result["authorizationChanged"] is not True:
        raise ValueError("checker must verify an authorization-file change")
    for key in ("contentDigest", "changeSetDigest"):
        value = result.get(key)
        if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
            raise ValueError(f"checker {key} is invalid")
    if not isinstance(result.get("evaluatedAt"), str) or not result["evaluatedAt"]:
        raise ValueError("checker evaluatedAt is invalid")
    for key in ("blockingReasons", "errors"):
        value = result.get(key)
        if (
            not isinstance(value, list)
            or not all(isinstance(item, str) for item in value)
        ):
            raise ValueError(f"checker {key} must be an array of strings")
    if authorized and result["blockingReasons"]:
        raise ValueError("authorized checker result cannot contain blockers")
    if result["errors"]:
        raise ValueError("valid checker result cannot contain errors")

    control = result.get("trustedControl")
    if not isinstance(control, dict) or set(control) != {
        "repository",
        "commit",
        "files",
        "independentCheckout",
        "executingCheckerPathMatched",
    }:
        raise ValueError("checker trustedControl evidence is missing or malformed")
    if control["repository"] != EXPECTED_REPOSITORY:
        raise ValueError("checker trustedControl repository does not match")
    if control["commit"] != expected_control_commit:
        raise ValueError("checker trustedControl commit does not match")
    if control["independentCheckout"] is not True:
        raise ValueError("checker did not verify an independent checkout")
    if control["executingCheckerPathMatched"] is not True:
        raise ValueError("checker path did not match trusted control")
    validate_file_evidence(control["files"])
    if control["files"] != expected_files:
        raise ValueError("checker trustedControl file evidence does not match launcher")


def minimal_checker_result(result: dict[str, Any], returncode: int) -> dict[str, Any]:
    if returncode == 2:
        errors = result.get("errors")
        safe_errors = []
        if isinstance(errors, list):
            safe_errors = [
                item[:512]
                for item in errors[:20]
                if isinstance(item, str)
            ]
        return {
            "valid": False,
            "authorized": False,
            "mode": result.get("mode"),
            "phase": "checker",
            "checkerExitCode": 2,
            "errors": safe_errors or ["checker rejected release authorization"],
        }
    return {
        key: result[key]
        for key in (
            "valid",
            "authorized",
            "mode",
            "evaluatedAt",
            "releaseId",
            "baseCommit",
            "candidateCommit",
            "headCommit",
            "targets",
            "catalogChanged",
            "contentDigest",
            "changeSetDigest",
            "authorizationChanged",
            "blockingReasons",
            "errors",
            "trustedControl",
        )
    }


def run_preflight(
    candidate_root: Path,
    control_root: Path,
    control_commit: str,
    base_commit: str,
    mode: str,
) -> tuple[int, dict[str, Any]]:
    if COMMIT_PATTERN.fullmatch(control_commit) is None:
        return 2, launcher_failure(
            "control commit must be a full lowercase SHA-1"
        )
    if COMMIT_PATTERN.fullmatch(base_commit) is None:
        return 2, launcher_failure(
            "base commit must be a full lowercase SHA-1"
        )
    if mode not in ALLOWED_MODES:
        return 2, launcher_failure("mode must be dry-run or publish")

    candidate = lexical_absolute(candidate_root)
    control = lexical_absolute(control_root)
    checker = control / CHECKER_RELATIVE
    try:
        if absolute_path_uses_symlink(control):
            raise ValueError("control root path must not contain symlinks")
        if absolute_path_uses_symlink(candidate):
            raise ValueError("candidate root path must not contain symlinks")
        if control.resolve() == candidate.resolve():
            raise ValueError("control and candidate roots must be different")
        python_path, git_path = resolve_executables()
        expected_candidate_commit, expected_head_commit = candidate_commit_state(
            git_path,
            candidate,
            base_commit,
        )
        checker_snapshot, expected_files = snapshot_control_files(
            git_path,
            control,
            control_commit,
        )
        completed = subprocess.run(
            [
                str(python_path),
                "-I",
                "-c",
                CHECKER_BOOTSTRAP,
                str(checker),
                "--repo-root",
                str(candidate),
                "--base",
                base_commit,
                "--head",
                "HEAD",
                "--mode",
                mode,
                "--control-root",
                str(control),
                "--control-commit",
                control_commit,
            ],
            cwd=control,
            env=child_environment(git_path),
            check=False,
            capture_output=True,
            input=checker_snapshot,
            timeout=CHECKER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 2, launcher_failure("checker execution timed out")
    except (OSError, ValueError) as error:
        return 2, launcher_failure(f"checker could not be executed safely: {error}")

    if (
        len(completed.stdout) > MAX_CHECKER_OUTPUT_BYTES
        or len(completed.stderr) > MAX_CHECKER_OUTPUT_BYTES
    ):
        return 2, launcher_failure(
            "checker output exceeds the launcher limit",
            completed.returncode,
        )
    if completed.stderr:
        return 2, launcher_failure(
            "checker wrote unexpected stderr",
            completed.returncode,
        )
    try:
        stdout = completed.stdout.decode("utf-8", errors="strict")
        result = parse_checker_output(stdout)
        validate_checker_result(
            result,
            completed.returncode,
            mode,
            control_commit,
            base_commit,
            expected_candidate_commit,
            expected_head_commit,
            expected_files,
        )
    except (UnicodeDecodeError, ValueError) as error:
        return 2, launcher_failure(str(error), completed.returncode)

    result = minimal_checker_result(result, completed.returncode)
    result["launcherObservations"] = {
        "isolatedModeObserved": True,
        "childEnvironmentAllowlisted": True,
        "checkerSnapshotBoundToControlCommit": True,
        "checkerTimeoutSeconds": CHECKER_TIMEOUT_SECONDS,
    }
    return completed.returncode, result


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated:
        print(
            json.dumps(
                launcher_failure("launcher must run with Python isolated mode (-I)"),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    parser = StructuredArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--control-root", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), required=True)
    try:
        args = parser.parse_args(argv)
    except ValueError as error:
        print(
            json.dumps(
                launcher_failure(str(error)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    returncode, result = run_preflight(
        args.candidate_root,
        args.control_root,
        args.control_commit,
        args.base,
        args.mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

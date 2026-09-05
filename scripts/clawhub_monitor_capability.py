#!/usr/bin/env python3
"""统一增长监控入口为内部采集器签发的短时能力上下文。"""

from __future__ import annotations

import hmac
import json
import math
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Mapping


CAPABILITY_FILE_ENV = "OPENCLAW_MONITOR_CAPABILITY_FILE"
CAPABILITY_TOKEN_ENV = "OPENCLAW_MONITOR_CAPABILITY_TOKEN"
CAPABILITY_ENV_NAMES = (CAPABILITY_FILE_ENV, CAPABILITY_TOKEN_ENV)
DEFAULT_TTL_SECONDS = 600
_SESSION_SEAL = object()


class ValidatedCollectorSession:
    """仅能由成功的能力校验创建的进程内会话。"""

    __slots__ = ("_seal",)

    def __init__(self, seal: object) -> None:
        if seal is not _SESSION_SEAL:
            raise TypeError("采集会话只能由能力校验创建")
        self._seal = seal


def require_collector_session(
    session: ValidatedCollectorSession | None,
) -> None:
    if (
        not isinstance(session, ValidatedCollectorSession)
        or session._seal is not _SESSION_SEAL
    ):
        raise PermissionError("ClawHub 请求缺少已验证的采集会话")


def sanitized_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """复制环境并移除内部能力，供不受信任的子进程使用。"""
    environment = dict(os.environ if source is None else source)
    for name in CAPABILITY_ENV_NAMES:
        environment.pop(name, None)
    return environment


def _strict_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"能力上下文包含重复字段：{key}")
            payload[key] = value
        return payload

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(payload, dict):
        raise ValueError("能力上下文必须是 JSON 对象")
    return payload


def create_monitor_capability_env(
    capability_path: Path,
    parent_pid: int,
    bindings: Mapping[Path, tuple[Path, Path]],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now_epoch: float | None = None,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """创建本轮能力文件并返回只供采集器使用的环境。"""
    if (
        isinstance(parent_pid, bool)
        or not isinstance(parent_pid, int)
        or parent_pid <= 0
    ):
        raise ValueError("能力父进程 PID 必须是正整数")
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
        or ttl_seconds > DEFAULT_TTL_SECONDS
    ):
        raise ValueError(f"能力有效期必须为 1 到 {DEFAULT_TTL_SECONDS} 秒")
    if not bindings:
        raise ValueError("能力必须绑定至少一个采集器")

    issued_at = time.time() if now_epoch is None else now_epoch
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, (int, float))
        or not math.isfinite(issued_at)
    ):
        raise ValueError("能力签发时间必须是有限数值")
    token = secrets.token_urlsafe(32)
    collectors: dict[str, dict[str, str]] = {}
    for script_path, (output_path, previous_output_path) in bindings.items():
        if not isinstance(script_path, Path) or not script_path.name:
            raise ValueError("采集器必须使用 Path 绑定")
        script_name = script_path.name
        if script_name in collectors:
            raise ValueError(f"采集器文件名重复：{script_name}")
        collectors[script_name] = {
            "scriptPath": str(script_path.resolve()),
            "output": str(output_path.resolve()),
            "previousOutput": str(previous_output_path.resolve()),
        }

    payload = {
        "schemaVersion": 1,
        "parentPid": parent_pid,
        "issuedAtEpoch": issued_at,
        "expiresAtEpoch": issued_at + ttl_seconds,
        "token": token,
        "collectors": collectors,
    }
    capability_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        capability_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            handle.write("\n")
    except Exception:
        capability_path.unlink(missing_ok=True)
        raise

    environment = sanitized_environment(base_environment)
    environment[CAPABILITY_FILE_ENV] = str(capability_path.resolve())
    environment[CAPABILITY_TOKEN_ENV] = token
    return environment


def validate_collector_capability(
    script_path: Path,
    output_path: Path,
    previous_output_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
    parent_pid: int | None = None,
    now_epoch: float | None = None,
) -> ValidatedCollectorSession:
    """在采集器产生网络或文件副作用前验证入口能力。"""
    current_environment = os.environ if environment is None else environment
    raw_path = current_environment.get(CAPABILITY_FILE_ENV, "").strip()
    supplied_token = current_environment.get(CAPABILITY_TOKEN_ENV, "").strip()
    if not raw_path or not supplied_token:
        raise PermissionError("采集器只能由统一增长监控入口调用")

    capability_path = Path(raw_path)
    if capability_path.is_symlink() or not capability_path.is_file():
        raise PermissionError("增长监控能力文件无效")
    file_mode = stat.S_IMODE(capability_path.stat().st_mode)
    if file_mode & 0o077:
        raise PermissionError("增长监控能力文件权限过宽")

    payload = _strict_json_object(capability_path)
    if payload.get("schemaVersion") != 1:
        raise PermissionError("增长监控能力版本无效")
    expected_parent = os.getppid() if parent_pid is None else parent_pid
    if payload.get("parentPid") != expected_parent:
        raise PermissionError("增长监控能力与父进程不匹配")

    token = payload.get("token")
    if not isinstance(token, str) or not hmac.compare_digest(token, supplied_token):
        raise PermissionError("增长监控能力令牌无效")

    issued_at = payload.get("issuedAtEpoch")
    expires_at = payload.get("expiresAtEpoch")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, (int, float))
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or not math.isfinite(issued_at)
        or not math.isfinite(expires_at)
        or expires_at <= issued_at
        or expires_at - issued_at > DEFAULT_TTL_SECONDS
    ):
        raise PermissionError("增长监控能力有效期无效")
    current_time = time.time() if now_epoch is None else now_epoch
    if (
        isinstance(current_time, bool)
        or not isinstance(current_time, (int, float))
        or not math.isfinite(current_time)
    ):
        raise PermissionError("当前时间必须是有限数值")
    if current_time < issued_at or current_time > expires_at:
        raise PermissionError("增长监控能力尚未生效或已过期")

    collectors = payload.get("collectors")
    binding = (
        collectors.get(script_path.resolve().name)
        if isinstance(collectors, dict)
        else None
    )
    if not isinstance(binding, dict):
        raise PermissionError("当前采集器未获本轮授权")
    expected_script = binding.get("scriptPath")
    expected_output = binding.get("output")
    expected_previous = binding.get("previousOutput")
    if (
        expected_script != str(script_path.resolve())
        or expected_output != str(output_path.resolve())
        or expected_previous != str(previous_output_path.resolve())
    ):
        raise PermissionError("采集器身份或输出路径与本轮能力不匹配")

    staging_directory = capability_path.resolve().parent
    if (
        output_path.resolve().parent != staging_directory
        or previous_output_path.resolve().parent != staging_directory
    ):
        raise PermissionError("采集器输出必须位于本轮暂存目录")
    return ValidatedCollectorSession(_SESSION_SEAL)

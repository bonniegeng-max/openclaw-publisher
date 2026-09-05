#!/usr/bin/env python3
"""分阶段运行 ClawHub 被动指标与搜索可见性监控。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from clawhub_monitor_capability import create_monitor_capability_env
except ModuleNotFoundError:
    from scripts.clawhub_monitor_capability import create_monitor_capability_env


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
ReplaceFile = Callable[[Path, Path], None]
DEFAULT_MIN_INTERVAL_HOURS = 144
MAX_PAIR_SKEW_MINUTES = 15
TRANSACTION_JOURNAL_NAME = ".growth-output-transaction.json"
TRANSACTION_ROOT_NAME = ".growth-transactions"
MONITOR_LOCK_NAME = ".growth-monitor.lock"
MONITOR_OUTPUT_NAMES = frozenset(
    {
        "clawhub-latest.json",
        "clawhub-previous.json",
        "clawhub-change-report.md",
        "clawhub-change-report.json",
        "clawhub-search-latest.json",
        "clawhub-search-previous.json",
        "clawhub-search-change-report.md",
        "clawhub-search-change-report.json",
        "clawhub-growth-decision.json",
        "clawhub-growth-decision.md",
    }
)
_LOCK_OWNERS: dict[Path, int] = {}
_LOCK_STATE_GUARD = threading.Lock()


def run_child(
    command: list[str],
    timeout: int,
    runner: RunCommand,
    *,
    env: dict[str, str] | None = None,
) -> None:
    options: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if env is not None:
        options["env"] = env
    completed = runner(command, **options)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"子命令失败：{' '.join(command)}：{message}")


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}：必须是 JSON 对象")
    return payload


def read_required_report(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label}未生成约定的 Markdown 报告")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise RuntimeError(f"{label}生成了空 Markdown 报告")
    return content


def read_required_comparison(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label}未生成约定的 JSON 对比结果")
    return read_json_object(path)


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def replace_path(source: Path, target: Path) -> None:
    source.replace(target)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_transaction_journal(
    path: Path,
    payload: dict[str, Any],
) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    try:
        temporary_path.replace(path)
        sync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _safe_filename(directory: Path, name: Any, label: str) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or Path(name).name != name
    ):
        raise ValueError(f"事务日志中的 {label} 必须是安全文件名")
    return directory / name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_fsynced_file(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def require_monitor_lock(directory: Path) -> Path:
    directory = directory.resolve()
    with _LOCK_STATE_GUARD:
        owner = _LOCK_OWNERS.get(directory)
    if owner != threading.get_ident():
        raise RuntimeError("操作监控事务前，当前线程必须持有单实例锁")
    return directory


def remove_transaction_directory(
    directory: Path,
    transaction_directory: Path,
) -> None:
    transaction_root = directory / TRANSACTION_ROOT_NAME
    if transaction_directory.exists():
        shutil.rmtree(transaction_directory)
        sync_directory(transaction_root)
    if not transaction_root.exists():
        return
    try:
        transaction_root.rmdir()
    except OSError:
        return
    sync_directory(directory)


def remove_orphan_transactions(directory: Path) -> None:
    transaction_root = directory / TRANSACTION_ROOT_NAME
    if transaction_root.is_symlink():
        raise RuntimeError("监控事务根目录不能是 symlink")
    if not transaction_root.exists():
        return
    if not transaction_root.is_dir():
        raise RuntimeError("监控事务根路径必须是目录")

    removed = False
    for candidate in transaction_root.iterdir():
        name = candidate.name
        if (
            len(name) != 32
            or any(character not in "0123456789abcdef" for character in name)
        ):
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            raise RuntimeError(f"孤立监控事务目录类型无效：{name}")
        shutil.rmtree(candidate)
        removed = True
    if removed:
        sync_directory(transaction_root)
    try:
        transaction_root.rmdir()
    except OSError:
        return
    sync_directory(directory)


def _load_transaction(
    directory: Path,
) -> tuple[Path, str, list[dict[str, Any]]]:
    journal_path = directory / TRANSACTION_JOURNAL_NAME
    if journal_path.is_symlink() or not journal_path.is_file():
        raise RuntimeError("监控事务日志必须是普通文件")
    journal = read_json_object(journal_path)
    if journal.get("schemaVersion") != 1:
        raise ValueError("监控事务日志 schemaVersion 必须为 1")
    phase = journal.get("phase")
    if phase not in {"prepared", "committed"}:
        raise ValueError("监控事务日志 phase 必须为 prepared 或 committed")
    transaction_id = journal.get("transactionId")
    if (
        not isinstance(transaction_id, str)
        or len(transaction_id) != 32
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        raise ValueError("监控事务 ID 必须是 32 位小写十六进制")
    transaction_root = directory / TRANSACTION_ROOT_NAME
    transaction_directory = transaction_root / transaction_id
    if (
        transaction_root.is_symlink()
        or transaction_directory.is_symlink()
        or not transaction_directory.is_dir()
    ):
        raise RuntimeError("监控事务目录缺失或类型无效")

    raw_entries = journal.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("监控事务日志 entries 必须是非空数组")
    entries: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise ValueError("监控事务日志 entry 必须是 JSON 对象")
        target_name = raw_entry.get("target")
        if target_name not in MONITOR_OUTPUT_NAMES:
            raise ValueError(f"监控事务 target 不受支持：{target_name}")
        if target_name in seen_targets:
            raise ValueError("监控事务日志 target 不能重复")
        prepared = _safe_filename(
            transaction_directory,
            raw_entry.get("prepared"),
            "prepared",
        )
        raw_backup = raw_entry.get("backup")
        backup = (
            None
            if raw_backup is None
            else _safe_filename(transaction_directory, raw_backup, "backup")
        )
        existed = raw_entry.get("existed")
        backup_sha256 = raw_entry.get("backupSha256")
        if not isinstance(existed, bool):
            raise ValueError("监控事务日志 existed 必须是布尔值")
        if existed is not (backup is not None):
            raise ValueError("监控事务日志 existed 与 backup 不一致")
        if prepared.name != f"new--{target_name}":
            raise ValueError("监控事务 prepared 与 target 不匹配")
        if backup is not None and backup.name != f"old--{target_name}":
            raise ValueError("监控事务 backup 与 target 不匹配")
        if existed:
            if (
                not isinstance(backup_sha256, str)
                or len(backup_sha256) != 64
                or backup is None
                or backup.is_symlink()
                or not backup.is_file()
            ):
                raise ValueError("监控事务备份证据无效")
            if sha256_file(backup) != backup_sha256:
                raise ValueError("监控事务备份哈希不匹配")
        elif backup_sha256 is not None:
            raise ValueError("新建目标不能声明备份哈希")
        if prepared.is_symlink():
            raise ValueError("监控事务 prepared 不能是 symlink")
        seen_targets.add(target_name)
        entries.append(
            {
                "target": directory / target_name,
                "prepared": prepared,
                "backup": backup,
                "existed": existed,
            }
        )
    return transaction_directory, phase, entries


def recover_output_bundle(
    directory: Path,
    replace_file: ReplaceFile = replace_path,
) -> str | None:
    """恢复未完成事务，返回 rolled-back、committed 或 None。"""
    directory = require_monitor_lock(directory)
    journal_path = directory / TRANSACTION_JOURNAL_NAME
    if journal_path.is_symlink():
        raise RuntimeError("监控事务日志不能是 symlink")
    if not journal_path.exists():
        remove_orphan_transactions(directory)
        return None
    transaction_directory, phase, entries = _load_transaction(directory)
    if phase == "prepared":
        for entry in reversed(entries):
            target = entry["target"]
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise RuntimeError(f"{target.name} 不是可恢复的普通文件")
            if entry["existed"]:
                backup = entry["backup"]
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=transaction_directory,
                    prefix=f"restore-{target.name}-",
                    delete=False,
                ) as handle:
                    with backup.open("rb") as source:
                        shutil.copyfileobj(source, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                    restore_path = Path(handle.name)
                replace_file(restore_path, target)
            else:
                target.unlink(missing_ok=True)
        sync_directory(directory)
    journal_path.unlink()
    sync_directory(directory)
    remove_transaction_directory(directory, transaction_directory)
    return "rolled-back" if phase == "prepared" else "committed"


@contextmanager
def monitor_lock(directory: Path) -> Iterator[Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("metrics 必须是仓库内的普通目录")
    directory = directory.resolve()
    lock_path = directory / MONITOR_LOCK_NAME
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise RuntimeError("增长监控锁必须是普通文件")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("已有增长监控进程正在运行") from exc
        owner = threading.get_ident()
        with _LOCK_STATE_GUARD:
            if directory in _LOCK_OWNERS:
                raise RuntimeError("已有增长监控线程正在运行")
            _LOCK_OWNERS[directory] = owner
        try:
            yield directory
        finally:
            with _LOCK_STATE_GUARD:
                if _LOCK_OWNERS.get(directory) == owner:
                    del _LOCK_OWNERS[directory]
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def commit_output_bundle(
    outputs: list[tuple[Path, bytes]],
    replace_file: ReplaceFile = replace_path,
) -> None:
    if not outputs:
        raise ValueError("监控输出集合不能为空")
    resolved_targets = [target.resolve() for target, _ in outputs]
    if len(set(resolved_targets)) != len(resolved_targets):
        raise ValueError("监控输出目标路径不能重复")
    directories = {target.parent.resolve() for target, _ in outputs}
    if len(directories) != 1:
        raise ValueError("监控输出目标必须位于同一目录")
    directory = require_monitor_lock(directories.pop())
    recover_output_bundle(directory, replace_file)
    journal_path = directory / TRANSACTION_JOURNAL_NAME
    transaction_id = uuid.uuid4().hex
    transaction_root = directory / TRANSACTION_ROOT_NAME
    if transaction_root.is_symlink():
        raise RuntimeError("监控事务根目录不能是 symlink")
    transaction_root.mkdir(mode=0o700, exist_ok=True)
    sync_directory(directory)
    transaction_directory = transaction_root / transaction_id
    transaction_directory.mkdir(mode=0o700)

    entries: list[dict[str, Any]] = []
    journal_active = False
    cleanup_allowed = True
    commit_complete = False
    try:
        for target, content in outputs:
            if target.name not in MONITOR_OUTPUT_NAMES:
                raise ValueError(f"监控输出目标不受支持：{target.name}")
            canonical_target = directory / target.name
            if target.resolve() != canonical_target.resolve():
                raise ValueError("监控输出目标必须是事务目录中的直接子文件")
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ValueError(f"{target.name} 必须是普通文件")

            prepared_path = transaction_directory / f"new--{target.name}"
            write_fsynced_file(prepared_path, content)
            existed = target.exists()
            backup_path: Path | None = None
            backup_sha256: str | None = None
            if existed:
                backup_path = transaction_directory / f"old--{target.name}"
                write_fsynced_file(backup_path, target.read_bytes())
                backup_sha256 = sha256_file(backup_path)
            entries.append(
                {
                    "targetPath": target,
                    "preparedPath": prepared_path,
                    "backupPath": backup_path,
                    "backupSha256": backup_sha256,
                    "existed": existed,
                }
            )
        sync_directory(transaction_directory)
        sync_directory(transaction_root)

        journal_payload = {
            "schemaVersion": 1,
            "phase": "prepared",
            "transactionId": transaction_id,
            "entries": [
                {
                    "target": entry["targetPath"].name,
                    "prepared": entry["preparedPath"].name,
                    "backup": (
                        entry["backupPath"].name
                        if entry["backupPath"] is not None
                        else None
                    ),
                    "backupSha256": entry["backupSha256"],
                    "existed": entry["existed"],
                }
                for entry in entries
            ],
        }
        try:
            write_transaction_journal(
                journal_path,
                journal_payload,
            )
        finally:
            journal_active = journal_path.exists()

        for entry in entries:
            replace_file(entry["preparedPath"], entry["targetPath"])
        sync_directory(directory)
        committed_payload = dict(journal_payload)
        committed_payload["phase"] = "committed"
        try:
            write_transaction_journal(
                journal_path,
                committed_payload,
            )
        finally:
            journal_active = journal_path.exists()
        commit_complete = True
        try:
            journal_path.unlink()
            journal_active = False
            sync_directory(directory)
        except OSError as exc:
            if journal_path.exists():
                raise
            cleanup_allowed = False
            print(
                "警告：监控输出已通过 committed journal 确认，"
                f"但清理持久化失败；下次启动将安全完成清理：{exc}",
                file=sys.stderr,
            )
    except Exception as exc:
        if journal_active:
            try:
                recovery_outcome = recover_output_bundle(
                    directory,
                    replace_file,
                )
                journal_active = False
                if recovery_outcome == "committed":
                    commit_complete = True
                    return
            except (OSError, ValueError, RuntimeError) as recovery_exc:
                raise RuntimeError(
                    f"监控输出提交失败且回滚不完整：{recovery_exc}"
                ) from exc
        raise
    finally:
        if not journal_active and cleanup_allowed:
            try:
                remove_transaction_directory(directory, transaction_directory)
            except OSError as exc:
                if not commit_complete:
                    raise
                print(
                    "警告：监控输出已完整提交，但事务备份清理失败；"
                    f"下次启动将重试：{exc}",
                    file=sys.stderr,
                )


def load_existing_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json_object(path)


def load_observation_policy(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{path}：观察策略文件缺失，拒绝在线采集")
    payload = read_json_object(path)
    if payload.get("schemaVersion") != 1:
        raise ValueError(f"{path}：schemaVersion 必须为 1")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{path}：reason 必须是非空字符串")
    not_before = parse_collected_at(
        {"collectedAt": payload.get("notBefore")},
        f"{path} 的 notBefore",
    )
    return {
        "notBefore": not_before,
        "notBeforeText": payload["notBefore"],
        "reason": reason.strip(),
    }


def parse_collected_at(snapshot: dict[str, Any], source: str) -> datetime:
    value = snapshot.get("collectedAt")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source}：collectedAt 必须是非空 ISO 8601 字符串")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{source}：collectedAt 不是有效的 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{source}：collectedAt 必须包含时区")
    return parsed


def load_expected_monitor_inputs(
    catalog_path: Path,
    query_path: Path,
) -> tuple[set[str], dict[str, tuple[str, int]]]:
    catalog = read_json_object(catalog_path)
    if not catalog:
        raise ValueError("Skill catalog 不能为空")
    slugs: set[str] = set()
    for raw_path in catalog:
        parts = Path(raw_path).parts
        if len(parts) != 2 or parts[0] != "skills" or not parts[1]:
            raise ValueError(f"catalog 路径格式异常：{raw_path}")
        slugs.add(parts[1])

    query_payload = read_json_object(query_path)
    if query_payload.get("schemaVersion") != 1:
        raise ValueError("搜索查询配置 schemaVersion 必须为 1")
    raw_queries = query_payload.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError("搜索查询配置必须包含非空 queries")
    queries: dict[str, tuple[str, int]] = {}
    terms: set[str] = set()
    for item in raw_queries:
        if not isinstance(item, dict):
            raise ValueError("每条搜索查询配置必须是 JSON 对象")
        slug = item.get("slug")
        query = item.get("query")
        limit = item.get("limit")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("搜索查询 slug 必须是非空字符串")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{slug}：搜索 query 必须是非空字符串")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > 100
        ):
            raise ValueError(f"{slug}：搜索 limit 必须是 1 到 100 的整数")
        normalized_slug = slug.strip()
        normalized_query = " ".join(query.split())
        if normalized_slug in queries:
            raise ValueError(f"搜索查询 slug 重复：{normalized_slug}")
        if normalized_query.casefold() in terms:
            raise ValueError(f"搜索 query 重复：{normalized_query}")
        queries[normalized_slug] = (normalized_query, limit)
        terms.add(normalized_query.casefold())
    if set(queries) != slugs:
        raise ValueError("搜索查询 slug 集合必须与 Skill catalog 完全一致")
    return slugs, queries


def _validate_slug_rows(
    rows: Any,
    expected_slugs: set[str],
    source: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{source} 必须是数组")
    indexed: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError(f"{source} 每项必须是 JSON 对象")
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            raise ValueError(f"{source} slug 必须是非空字符串")
        if slug in indexed:
            raise ValueError(f"{source} slug 重复：{slug}")
        indexed[slug] = item
    if set(indexed) != expected_slugs:
        raise ValueError(f"{source} slug 集合与 catalog 不一致")
    return indexed


def validate_collected_snapshot_pair(
    metrics_snapshot: dict[str, Any],
    search_snapshot: dict[str, Any],
    expected_slugs: set[str],
    expected_queries: dict[str, tuple[str, int]],
) -> None:
    """在任何正式轮换前校验新采集事实的结构与同轮一致性。"""
    for snapshot, source, method in (
        (metrics_snapshot, "指标快照", "clawhub inspect --json"),
        (search_snapshot, "搜索快照", "clawhub search"),
    ):
        if snapshot.get("schemaVersion") != 1:
            raise ValueError(f"{source} schemaVersion 必须为 1")
        if snapshot.get("method") != method:
            raise ValueError(f"{source} method 必须为 {method}")
        if snapshot.get("activeInstall") is not False:
            raise ValueError(f"{source} activeInstall 必须明确为 false")

    metrics_time = parse_collected_at(metrics_snapshot, "新指标快照")
    search_time = parse_collected_at(search_snapshot, "新搜索快照")
    skew_minutes = abs((metrics_time - search_time).total_seconds()) / 60
    if skew_minutes > MAX_PAIR_SKEW_MINUTES:
        raise ValueError(
            "新指标与搜索快照必须来自同一轮采集；"
            f"当前相差 {skew_minutes:.2f} 分钟"
        )

    metrics_rows = _validate_slug_rows(
        metrics_snapshot.get("skills"),
        expected_slugs,
        "指标快照 skills",
    )
    for slug, item in metrics_rows.items():
        display_name = item.get("displayName")
        summary = item.get("summary")
        topics = item.get("topics")
        stats = item.get("stats")
        if not isinstance(display_name, str) or not display_name:
            raise ValueError(f"{slug}：displayName 必须是非空字符串")
        if not isinstance(summary, str) or not summary:
            raise ValueError(f"{slug}：summary 必须是非空字符串")
        if not isinstance(topics, list) or not all(
            isinstance(topic, str) for topic in topics
        ):
            raise ValueError(f"{slug}：topics 必须是字符串数组")
        latest_version = item.get("latestVersion")
        moderation = item.get("moderation")
        if not isinstance(latest_version, str) or not latest_version:
            raise ValueError(f"{slug}：latestVersion 必须是非空字符串")
        if not isinstance(moderation, str) or not moderation:
            raise ValueError(f"{slug}：moderation 必须是非空字符串")
        if not isinstance(stats, dict):
            raise ValueError(f"{slug}：stats 必须是 JSON 对象")
        for name in ("downloads", "installs", "stars", "versions"):
            if name not in stats:
                raise ValueError(f"{slug}：stats 缺少 {name}")
            value = stats.get(name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{slug}：stats.{name} 必须是非负整数或 null")

    search_rows = _validate_slug_rows(
        search_snapshot.get("queries"),
        expected_slugs,
        "搜索快照 queries",
    )
    cli_version = search_snapshot.get("cliVersion")
    if not isinstance(cli_version, str) or not cli_version:
        raise ValueError("搜索快照 cliVersion 必须是非空字符串")
    for slug, item in search_rows.items():
        expected_query, expected_limit = expected_queries[slug]
        if item.get("query") != expected_query or item.get("limit") != expected_limit:
            raise ValueError(f"{slug}：搜索 query 或 limit 与配置不一致")
        rank = item.get("rank")
        if rank is not None and (
            isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0
        ):
            raise ValueError(f"{slug}：rank 必须为正整数或 null")
        if item.get("visible") is not (rank is not None):
            raise ValueError(f"{slug}：visible 与 rank 不一致")
        results = item.get("results")
        result_count = item.get("resultCount")
        if not isinstance(results, list):
            raise ValueError(f"{slug}：results 必须是数组")
        if (
            isinstance(result_count, bool)
            or not isinstance(result_count, int)
            or result_count != len(results)
        ):
            raise ValueError(f"{slug}：resultCount 必须等于 results 数量")
        target_ranks: list[int] = []
        for expected_rank, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                raise ValueError(f"{slug}：每条搜索结果必须是 JSON 对象")
            result_rank = result.get("rank")
            result_slug = result.get("slug")
            metric = result.get("metric")
            if result_rank != expected_rank:
                raise ValueError(f"{slug}：搜索结果 rank 必须连续")
            if not isinstance(result_slug, str) or not result_slug:
                raise ValueError(f"{slug}：搜索结果 slug 必须是非空字符串")
            if not isinstance(metric, dict):
                raise ValueError(f"{slug}：搜索结果 metric 必须是 JSON 对象")
            if result_slug.casefold() == slug.casefold():
                target_ranks.append(result_rank)
        expected_rank = target_ranks[0] if target_ranks else None
        if rank != expected_rank:
            raise ValueError(f"{slug}：目标 rank 与 results 不一致")


def evaluate_run_guard(
    old_metrics: dict[str, Any] | None,
    old_search: dict[str, Any] | None,
    now: datetime,
    min_interval_hours: float,
    force: bool,
    observation_policy: dict[str, Any],
) -> dict[str, Any]:
    if min_interval_hours <= 0:
        raise ValueError("min-interval-hours 必须大于 0")
    if now.tzinfo is None:
        raise ValueError("当前时间必须包含时区")
    existing_times: list[datetime] = []
    for snapshot, source in (
        (old_metrics, "指标 latest"),
        (old_search, "搜索 latest"),
    ):
        if snapshot is None:
            continue
        collected_at = parse_collected_at(snapshot, source)
        if collected_at > now:
            raise ValueError(f"{source} 快照时间晚于当前时间")
        existing_times.append(collected_at)
    if (old_metrics is None) != (old_search is None):
        raise ValueError("指标与搜索 latest 必须同时存在或同时缺失")
    if force:
        return {
            "skip": False,
            "reason": "显式强制运行",
            "ageHours": None,
            "notBefore": observation_policy["notBeforeText"],
        }
    not_before = observation_policy["notBefore"]
    if now < not_before:
        return {
            "skip": True,
            "reason": (
                f"自然观察窗口尚未结束；最早采样时间为 "
                f"{observation_policy['notBeforeText']}；"
                f"原因：{observation_policy['reason']}"
            ),
            "ageHours": None,
            "notBefore": observation_policy["notBeforeText"],
        }
    if old_metrics is None:
        return {
            "skip": False,
            "reason": "尚无历史快照",
            "ageHours": None,
            "notBefore": observation_policy["notBeforeText"],
        }

    latest_time = max(existing_times)
    age_hours = (now - latest_time).total_seconds() / 3600
    if age_hours < min_interval_hours:
        return {
            "skip": True,
            "reason": (
                f"距最近成功采集仅 {age_hours:.2f} 小时，"
                f"小于默认门槛 {min_interval_hours:g} 小时"
            ),
            "ageHours": age_hours,
            "notBefore": observation_policy["notBeforeText"],
        }
    return {
        "skip": False,
        "reason": f"距最近成功采集 {age_hours:.2f} 小时",
        "ageHours": age_hours,
        "notBefore": observation_policy["notBeforeText"],
    }


def combine_decisions(
    metrics_comparison: dict[str, Any] | None,
    search_comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for name, label, comparison in (
        ("metrics", "指标", metrics_comparison),
        ("search", "搜索", search_comparison),
    ):
        evidence = (
            comparison.get("evidenceQuality")
            if isinstance(comparison, dict)
            else None
        )
        status = evidence.get("status") if isinstance(evidence, dict) else None
        decision_ready = (
            evidence.get("decisionReady")
            if isinstance(evidence, dict)
            else None
        )
        component_reasons = (
            evidence.get("reasons")
            if isinstance(evidence, dict)
            else None
        )
        valid_reasons = (
            isinstance(component_reasons, list)
            and all(isinstance(reason, str) for reason in component_reasons)
        )
        if (
            not isinstance(status, str)
            or not isinstance(decision_ready, bool)
            or not valid_reasons
        ):
            component = {
                "available": False,
                "status": "insufficient",
                "decisionReady": False,
                "reasons": ["缺少有效的可比较证据"],
            }
        else:
            component = {
                "available": True,
                "status": status,
                "decisionReady": decision_ready,
                "reasons": component_reasons,
            }
        components[name] = component
        reasons.extend(f"{label}：{reason}" for reason in component["reasons"])

    pairing = {
        "maximumSkewMinutes": MAX_PAIR_SKEW_MINUTES,
        "previousSkewMinutes": None,
        "currentSkewMinutes": None,
        "aligned": False,
    }
    pairing_valid = isinstance(metrics_comparison, dict) and isinstance(
        search_comparison,
        dict,
    )
    if pairing_valid:
        for key, output_key, label in (
            ("previousCollectedAt", "previousSkewMinutes", "前次"),
            ("currentCollectedAt", "currentSkewMinutes", "当前"),
        ):
            try:
                metrics_time = parse_collected_at(
                    {"collectedAt": metrics_comparison.get(key)},
                    f"指标{label}快照",
                )
                search_time = parse_collected_at(
                    {"collectedAt": search_comparison.get(key)},
                    f"搜索{label}快照",
                )
            except ValueError as exc:
                pairing_valid = False
                reasons.append(f"配对：{exc}")
                continue
            skew_minutes = abs(
                (metrics_time - search_time).total_seconds()
            ) / 60
            pairing[output_key] = skew_minutes
            if skew_minutes > MAX_PAIR_SKEW_MINUTES:
                pairing_valid = False
                reasons.append(
                    f"配对：{label}指标与搜索快照相差 "
                    f"{skew_minutes:.2f} 分钟，超过 "
                    f"{MAX_PAIR_SKEW_MINUTES} 分钟"
                )
    pairing["aligned"] = pairing_valid

    decision_ready = all(
        component["decisionReady"] for component in components.values()
    ) and pairing_valid
    statuses = {component["status"] for component in components.values()}
    data_quality_statuses = {"contaminated", "incomparable", "insufficient"}
    if decision_ready:
        status = "eligible"
        recommended_action = "review-growth-signals"
    elif statuses.intersection(data_quality_statuses) or not pairing_valid:
        status = "data-quality-blocked"
        recommended_action = "repair-data-quality"
    else:
        status = "observing"
        recommended_action = "continue-observation"

    return {
        "schemaVersion": 1,
        "status": status,
        "decisionReady": decision_ready,
        "recommendedAction": recommended_action,
        "components": components,
        "pairing": pairing,
        "reasons": reasons,
        "attribution": (
            "只有指标与搜索两侧同时通过证据门槛，才允许进入增长或产品组合决策。"
        ),
    }


def apply_observation_gate(
    decision: dict[str, Any],
    observation_policy: dict[str, Any],
    now: datetime,
    force: bool,
) -> dict[str, Any]:
    """让提前强制采集保留事实，但不能提前形成增长决策。"""
    if now.tzinfo is None:
        raise ValueError("当前时间必须包含时区")
    satisfied = now >= observation_policy["notBefore"]
    gated = {
        **decision,
        "reasons": list(decision["reasons"]),
        "observationGate": {
            "notBefore": observation_policy["notBeforeText"],
            "satisfied": satisfied,
            "forcedCollection": force,
        },
    }
    if satisfied:
        return gated

    gated["decisionReady"] = False
    gated["reasons"].append(
        "观察期：当前采集早于 "
        f"{observation_policy['notBeforeText']}，不得进入增长决策"
    )
    if gated["status"] != "data-quality-blocked":
        gated["status"] = "observing"
        gated["recommendedAction"] = "continue-observation"
    return gated


def render_combined_decision(decision: dict[str, Any]) -> str:
    metrics = decision["components"]["metrics"]
    search = decision["components"]["search"]
    lines = [
        "# ClawHub 组合决策闸门",
        "",
        f"- 状态：`{decision['status']}`",
        (
            "- 是否可进入增长决策："
            f"`{'true' if decision['decisionReady'] else 'false'}`"
        ),
        f"- 唯一下一步：`{decision['recommendedAction']}`",
        f"- 指标证据：`{metrics['status']}`",
        f"- 搜索证据：`{search['status']}`",
        (
            "- 观察轮次配对："
            f"`{'aligned' if decision['pairing']['aligned'] else 'misaligned'}`"
        ),
        (
            "- 自然观察门槛："
            f"`{'satisfied' if decision['observationGate']['satisfied'] else 'locked'}`"
        ),
        "",
        "> downloads、installs、stars 与搜索排名必须分开解释；"
        "单侧合格不能替代组合闸门。",
        "",
        "## 原因",
        "",
    ]
    lines.extend(f"- {reason}" for reason in decision["reasons"])
    return "\n".join(lines) + "\n"


def _run_monitor_locked(
    root: Path,
    python_bin: str,
    clawhub_bin: str,
    timeout: int,
    min_interval_hours: float = DEFAULT_MIN_INTERVAL_HOURS,
    force: bool = False,
    now: datetime | None = None,
    runner: RunCommand = subprocess.run,
    metrics_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    scripts = root / "scripts"
    metrics_dir = metrics_dir or root / "metrics"
    catalog = root / ".clawhub" / "skill-catalog.json"
    queries = metrics_dir / "search-queries.json"
    observation_policy = load_observation_policy(
        metrics_dir / "observation-policy.json"
    )

    metrics_latest = metrics_dir / "clawhub-latest.json"
    metrics_previous = metrics_dir / "clawhub-previous.json"
    metrics_report = metrics_dir / "clawhub-change-report.md"
    metrics_report_json = metrics_dir / "clawhub-change-report.json"
    search_latest = metrics_dir / "clawhub-search-latest.json"
    search_previous = metrics_dir / "clawhub-search-previous.json"
    search_report = metrics_dir / "clawhub-search-change-report.md"
    search_report_json = metrics_dir / "clawhub-search-change-report.json"
    decision_json = metrics_dir / "clawhub-growth-decision.json"
    decision_report = metrics_dir / "clawhub-growth-decision.md"

    old_metrics = load_existing_snapshot(metrics_latest)
    old_search = load_existing_snapshot(search_latest)
    if old_metrics is None and old_search is None:
        stale_outputs = [
            path
            for path in (
                metrics_previous,
                metrics_report,
                metrics_report_json,
                search_previous,
                search_report,
                search_report_json,
                decision_json,
                decision_report,
            )
            if path.exists()
        ]
        if stale_outputs:
            names = ", ".join(path.name for path in stale_outputs)
            raise ValueError(f"latest 均缺失但仍存在派生产物：{names}")
    current_time = now or datetime.now(timezone.utc)
    guard = evaluate_run_guard(
        old_metrics,
        old_search,
        current_time,
        min_interval_hours,
        force,
        observation_policy,
    )
    if guard["skip"]:
        return {
            "skipped": True,
            "skipReason": guard["reason"],
            "ageHours": guard["ageHours"],
            "notBefore": guard["notBefore"],
            "metricsCompared": False,
            "searchCompared": False,
            "decisionReady": None,
            "decisionStatus": "skipped",
            "recommendedAction": "wait-for-next-window",
        }
    expected_slugs, expected_queries = load_expected_monitor_inputs(
        catalog,
        queries,
    )
    metrics_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        dir=metrics_dir,
        prefix=".growth-run-",
    ) as directory:
        staging = Path(directory)
        staged_metrics = staging / "metrics.json"
        staged_search = staging / "search.json"
        staged_metrics_report = staging / "metrics-report.md"
        staged_search_report = staging / "search-report.md"
        staged_metrics_comparison = staging / "metrics-comparison.json"
        staged_search_comparison = staging / "search-comparison.json"
        collector_environment = create_monitor_capability_env(
            staging / ".collector-capability.json",
            os.getpid(),
            {
                scripts / "collect_clawhub_metrics.py": (
                    staged_metrics,
                    staging / "unused-metrics-previous.json",
                ),
                scripts / "collect_clawhub_search_visibility.py": (
                    staged_search,
                    staging / "unused-search-previous.json",
                ),
            },
        )

        run_child(
            [
                python_bin,
                str(scripts / "collect_clawhub_metrics.py"),
                "--catalog",
                str(catalog),
                "--output",
                str(staged_metrics),
                "--previous-output",
                str(staging / "unused-metrics-previous.json"),
                "--clawhub-bin",
                clawhub_bin,
                "--timeout",
                str(timeout),
            ],
            timeout * 10,
            runner,
            env=collector_environment,
        )
        run_child(
            [
                python_bin,
                str(scripts / "collect_clawhub_search_visibility.py"),
                "--queries",
                str(queries),
                "--catalog",
                str(catalog),
                "--output",
                str(staged_search),
                "--previous-output",
                str(staging / "unused-search-previous.json"),
                "--clawhub-bin",
                clawhub_bin,
                "--timeout",
                str(timeout),
            ],
            timeout * 10,
            runner,
            env=collector_environment,
        )

        new_metrics = read_json_object(staged_metrics)
        new_search = read_json_object(staged_search)
        validate_collected_snapshot_pair(
            new_metrics,
            new_search,
            expected_slugs,
            expected_queries,
        )

        if old_metrics is not None:
            run_child(
                [
                    python_bin,
                    str(scripts / "compare_clawhub_metrics.py"),
                    str(metrics_latest),
                    str(staged_metrics),
                    "--output",
                    str(staged_metrics_report),
                    "--json-output",
                    str(staged_metrics_comparison),
                ],
                timeout,
                runner,
            )
        if old_search is not None:
            run_child(
                [
                    python_bin,
                    str(scripts / "compare_clawhub_metrics.py"),
                    str(search_latest),
                    str(staged_search),
                    "--output",
                    str(staged_search_report),
                    "--json-output",
                    str(staged_search_comparison),
                ],
                timeout,
                runner,
            )

        metrics_report_text = None
        metrics_comparison = None
        if old_metrics is not None:
            metrics_report_text = read_required_report(
                staged_metrics_report,
                "指标比较器",
            )
            metrics_comparison = read_required_comparison(
                staged_metrics_comparison,
                "指标比较器",
            )

        search_report_text = None
        search_comparison = None
        if old_search is not None:
            search_report_text = read_required_report(
                staged_search_report,
                "搜索比较器",
            )
            search_comparison = read_required_comparison(
                staged_search_comparison,
                "搜索比较器",
            )
        combined_decision = apply_observation_gate(
            combine_decisions(
                metrics_comparison,
                search_comparison,
            ),
            observation_policy,
            current_time,
            force,
        )
        combined_report_text = render_combined_decision(combined_decision)

        outputs: list[tuple[Path, bytes]] = []
        if old_metrics is not None:
            outputs.append((metrics_previous, json_bytes(old_metrics)))
        outputs.append((metrics_latest, json_bytes(new_metrics)))
        if old_search is not None:
            outputs.append((search_previous, json_bytes(old_search)))
        outputs.append((search_latest, json_bytes(new_search)))
        if metrics_report_text is not None:
            outputs.append(
                (metrics_report, metrics_report_text.encode("utf-8"))
            )
        if metrics_comparison is not None:
            outputs.append(
                (metrics_report_json, json_bytes(metrics_comparison))
            )
        if search_report_text is not None:
            outputs.append(
                (search_report, search_report_text.encode("utf-8"))
            )
        if search_comparison is not None:
            outputs.append(
                (search_report_json, json_bytes(search_comparison))
            )
        outputs.extend(
            [
                (decision_json, json_bytes(combined_decision)),
                (decision_report, combined_report_text.encode("utf-8")),
            ]
        )
        commit_output_bundle(outputs)

    return {
        "skipped": False,
        "skipReason": None,
        "ageHours": guard["ageHours"],
        "notBefore": guard["notBefore"],
        "metricsCollectedAt": new_metrics.get("collectedAt"),
        "searchCollectedAt": new_search.get("collectedAt"),
        "metricsCompared": old_metrics is not None,
        "searchCompared": old_search is not None,
        "decisionReady": combined_decision["decisionReady"],
        "decisionStatus": combined_decision["status"],
        "recommendedAction": combined_decision["recommendedAction"],
    }


def run_monitor(
    root: Path,
    python_bin: str,
    clawhub_bin: str,
    timeout: int,
    min_interval_hours: float = DEFAULT_MIN_INTERVAL_HOURS,
    force: bool = False,
    now: datetime | None = None,
    runner: RunCommand = subprocess.run,
) -> dict[str, Any]:
    root = root.resolve()
    requested_metrics_dir = root / "metrics"
    if requested_metrics_dir.is_symlink():
        raise RuntimeError("metrics 目录不能是 symlink")
    requested_metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir = requested_metrics_dir.resolve()
    try:
        metrics_dir.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("metrics 目录必须位于仓库根目录内") from exc
    with monitor_lock(metrics_dir) as locked_metrics_dir:
        recover_output_bundle(locked_metrics_dir)
        return _run_monitor_locked(
            root,
            python_bin,
            clawhub_bin,
            timeout,
            min_interval_hours,
            force,
            now,
            runner,
            metrics_dir=locked_metrics_dir,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一次完成 ClawHub 被动指标与搜索可见性采集。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="openclaw-publisher 仓库根目录。",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="单个 ClawHub 请求的超时秒数。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "提前执行一次异常复核采集；"
            "不会绕过快照完整性或自然观察决策门槛。"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_monitor(
            root=args.root,
            python_bin=sys.executable,
            clawhub_bin="clawhub",
            timeout=args.timeout,
            force=args.force,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"被动监控失败，现有快照未更新：{exc}", file=sys.stderr)
        return 1

    if result["skipped"]:
        print(f"被动监控已跳过：{result['skipReason']}")
    else:
        print(
            "被动监控完成："
            f"指标对比={'是' if result['metricsCompared'] else '首次采集'}，"
            f"搜索对比={'是' if result['searchCompared'] else '首次采集'}，"
            f"组合闸门={result['decisionStatus']}，"
            f"下一步={result['recommendedAction']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

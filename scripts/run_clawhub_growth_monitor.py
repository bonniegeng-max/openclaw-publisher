#!/usr/bin/env python3
"""分阶段运行 ClawHub 被动指标与搜索可见性监控。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
DEFAULT_MIN_INTERVAL_HOURS = 144


def run_child(
    command: list[str],
    timeout: int,
    runner: RunCommand,
) -> None:
    completed = runner(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"子命令失败：{' '.join(command)}：{message}")


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}：必须是 JSON 对象")
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def load_existing_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json_object(path)


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


def evaluate_run_guard(
    old_metrics: dict[str, Any] | None,
    old_search: dict[str, Any] | None,
    now: datetime,
    min_interval_hours: float,
    force: bool,
) -> dict[str, Any]:
    if min_interval_hours <= 0:
        raise ValueError("min-interval-hours 必须大于 0")
    if now.tzinfo is None:
        raise ValueError("当前时间必须包含时区")
    if force:
        return {"skip": False, "reason": "显式强制运行", "ageHours": None}
    if old_metrics is None or old_search is None:
        return {"skip": False, "reason": "至少缺少一类历史快照", "ageHours": None}

    latest_time = max(
        parse_collected_at(old_metrics, "指标 latest"),
        parse_collected_at(old_search, "搜索 latest"),
    )
    age_hours = (now - latest_time).total_seconds() / 3600
    if age_hours < 0:
        raise ValueError("现有 latest 快照时间晚于当前时间")
    if age_hours < min_interval_hours:
        return {
            "skip": True,
            "reason": (
                f"距最近成功采集仅 {age_hours:.2f} 小时，"
                f"小于默认门槛 {min_interval_hours:g} 小时"
            ),
            "ageHours": age_hours,
        }
    return {
        "skip": False,
        "reason": f"距最近成功采集 {age_hours:.2f} 小时",
        "ageHours": age_hours,
    }


def promote_snapshot(
    staged_payload: dict[str, Any],
    existing_payload: dict[str, Any] | None,
    latest_path: Path,
    previous_path: Path,
) -> None:
    if latest_path.resolve() == previous_path.resolve():
        raise ValueError("latest 与 previous 不能是同一路径")
    if existing_payload is not None:
        write_json_atomic(previous_path, existing_payload)
    write_json_atomic(latest_path, staged_payload)


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
    scripts = root / "scripts"
    metrics_dir = root / "metrics"
    catalog = root / ".clawhub" / "skill-catalog.json"
    queries = metrics_dir / "search-queries.json"

    metrics_latest = metrics_dir / "clawhub-latest.json"
    metrics_previous = metrics_dir / "clawhub-previous.json"
    metrics_report = metrics_dir / "clawhub-change-report.md"
    search_latest = metrics_dir / "clawhub-search-latest.json"
    search_previous = metrics_dir / "clawhub-search-previous.json"
    search_report = metrics_dir / "clawhub-search-change-report.md"

    old_metrics = load_existing_snapshot(metrics_latest)
    old_search = load_existing_snapshot(search_latest)
    guard = evaluate_run_guard(
        old_metrics,
        old_search,
        now or datetime.now(timezone.utc),
        min_interval_hours,
        force,
    )
    if guard["skip"]:
        return {
            "skipped": True,
            "skipReason": guard["reason"],
            "ageHours": guard["ageHours"],
            "metricsCompared": False,
            "searchCompared": False,
        }
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
        )

        new_metrics = read_json_object(staged_metrics)
        new_search = read_json_object(staged_search)

        if old_metrics is not None:
            run_child(
                [
                    python_bin,
                    str(scripts / "compare_clawhub_metrics.py"),
                    str(metrics_latest),
                    str(staged_metrics),
                    "--output",
                    str(staged_metrics_report),
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
                ],
                timeout,
                runner,
            )

        metrics_report_text = (
            staged_metrics_report.read_text(encoding="utf-8")
            if staged_metrics_report.exists()
            else None
        )
        search_report_text = (
            staged_search_report.read_text(encoding="utf-8")
            if staged_search_report.exists()
            else None
        )

        promote_snapshot(
            new_metrics,
            old_metrics,
            metrics_latest,
            metrics_previous,
        )
        promote_snapshot(
            new_search,
            old_search,
            search_latest,
            search_previous,
        )
        if metrics_report_text is not None:
            write_text_atomic(metrics_report, metrics_report_text)
        if search_report_text is not None:
            write_text_atomic(search_report, search_report_text)

    return {
        "skipped": False,
        "skipReason": None,
        "ageHours": guard["ageHours"],
        "metricsCollectedAt": new_metrics.get("collectedAt"),
        "searchCollectedAt": new_search.get("collectedAt"),
        "metricsCompared": old_metrics is not None,
        "searchCompared": old_search is not None,
    }


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
        "--python-bin",
        default=sys.executable,
        help="运行子脚本的 Python 解释器。",
    )
    parser.add_argument("--clawhub-bin", default="clawhub", help="ClawHub CLI。")
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="单个 ClawHub 请求的超时秒数。",
    )
    parser.add_argument(
        "--min-interval-hours",
        type=float,
        default=DEFAULT_MIN_INTERVAL_HOURS,
        help="非强制运行之间的最短间隔小时数。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略最短间隔并立即执行一次采集。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_monitor(
            root=args.root,
            python_bin=args.python_bin,
            clawhub_bin=args.clawhub_bin,
            timeout=args.timeout,
            min_interval_hours=args.min_interval_hours,
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
            f"搜索对比={'是' if result['searchCompared'] else '首次采集'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

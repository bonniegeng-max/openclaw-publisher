#!/usr/bin/env python3
"""分阶段运行 ClawHub 被动指标与搜索可见性监控。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from clawhub_monitor_capability import create_monitor_capability_env
except ModuleNotFoundError:
    from scripts.clawhub_monitor_capability import create_monitor_capability_env


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
ReplaceFile = Callable[[Path, Path], None]
DEFAULT_MIN_INTERVAL_HOURS = 144
MAX_PAIR_SKEW_MINUTES = 15


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


def json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def replace_path(source: Path, target: Path) -> None:
    source.replace(target)


def commit_output_bundle(
    outputs: list[tuple[Path, bytes]],
    replace_file: ReplaceFile = replace_path,
) -> None:
    resolved_targets = [target.resolve() for target, _ in outputs]
    if len(set(resolved_targets)) != len(resolved_targets):
        raise ValueError("监控输出目标路径不能重复")

    prepared: list[tuple[Path, Path]] = []
    backups: list[tuple[Path, Path | None, bool]] = []
    try:
        for target, content in outputs:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.new.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                prepared.append((Path(handle.name), target))

        for prepared_path, target in prepared:
            existed = target.exists()
            backup_path: Path | None = None
            if existed:
                with tempfile.NamedTemporaryFile(
                    dir=target.parent,
                    prefix=f".{target.name}.backup.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    backup_path = Path(handle.name)
                replace_file(target, backup_path)
            backups.append((target, backup_path, existed))
            replace_file(prepared_path, target)
    except Exception as exc:
        rollback_errors: list[str] = []
        for target, backup_path, existed in reversed(backups):
            try:
                if target.exists():
                    target.unlink()
                if existed and backup_path is not None and backup_path.exists():
                    replace_file(backup_path, target)
            except OSError as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise RuntimeError(f"监控输出提交失败且回滚不完整：{details}") from exc
        raise
    finally:
        for prepared_path, _ in prepared:
            prepared_path.unlink(missing_ok=True)
        for _, backup_path, _ in backups:
            if backup_path is not None:
                backup_path.unlink(missing_ok=True)


def load_existing_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json_object(path)


def load_observation_policy(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
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


def evaluate_run_guard(
    old_metrics: dict[str, Any] | None,
    old_search: dict[str, Any] | None,
    now: datetime,
    min_interval_hours: float,
    force: bool,
    observation_policy: dict[str, Any] | None = None,
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
    if force:
        return {
            "skip": False,
            "reason": "显式强制运行",
            "ageHours": None,
            "notBefore": (
                observation_policy["notBeforeText"]
                if observation_policy is not None
                else None
            ),
        }
    if observation_policy is not None:
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
    if old_metrics is None or old_search is None:
        return {
            "skip": False,
            "reason": "至少缺少一类历史快照",
            "ageHours": None,
            "notBefore": (
                observation_policy["notBeforeText"]
                if observation_policy is not None
                else None
            ),
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
            "notBefore": (
                observation_policy["notBeforeText"]
                if observation_policy is not None
                else None
            ),
        }
    return {
        "skip": False,
        "reason": f"距最近成功采集 {age_hours:.2f} 小时",
        "ageHours": age_hours,
        "notBefore": (
            observation_policy["notBeforeText"]
            if observation_policy is not None
            else None
        ),
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
        "",
        "> downloads、installs、stars 与搜索排名必须分开解释；"
        "单侧合格不能替代组合闸门。",
        "",
        "## 原因",
        "",
    ]
    lines.extend(f"- {reason}" for reason in decision["reasons"])
    return "\n".join(lines) + "\n"


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
    observation_policy = load_observation_policy(
        metrics_dir / "observation-policy.json"
    )

    metrics_latest = metrics_dir / "clawhub-latest.json"
    metrics_previous = metrics_dir / "clawhub-previous.json"
    metrics_report = metrics_dir / "clawhub-change-report.md"
    search_latest = metrics_dir / "clawhub-search-latest.json"
    search_previous = metrics_dir / "clawhub-search-previous.json"
    search_report = metrics_dir / "clawhub-search-change-report.md"
    decision_json = metrics_dir / "clawhub-growth-decision.json"
    decision_report = metrics_dir / "clawhub-growth-decision.md"

    old_metrics = load_existing_snapshot(metrics_latest)
    old_search = load_existing_snapshot(search_latest)
    guard = evaluate_run_guard(
        old_metrics,
        old_search,
        now or datetime.now(timezone.utc),
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
        metrics_comparison = (
            read_json_object(staged_metrics_comparison)
            if staged_metrics_comparison.exists()
            else None
        )
        search_comparison = (
            read_json_object(staged_search_comparison)
            if staged_search_comparison.exists()
            else None
        )
        combined_decision = combine_decisions(
            metrics_comparison,
            search_comparison,
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
        if search_report_text is not None:
            outputs.append(
                (search_report, search_report_text.encode("utf-8"))
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
        help="忽略观察窗口与最短间隔并立即执行一次异常复核采集。",
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
            f"搜索对比={'是' if result['searchCompared'] else '首次采集'}，"
            f"组合闸门={result['decisionStatus']}，"
            f"下一步={result['recommendedAction']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

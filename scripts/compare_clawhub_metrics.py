#!/usr/bin/env python3
"""离线对比两个被动 ClawHub 指标快照。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


METRICS = ("downloads", "installs", "stars", "versions")
MIN_OBSERVATION_DAYS = 7


def load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}：快照根节点必须是 JSON 对象")
    if payload.get("schemaVersion") != 1:
        raise ValueError(f"{path}：不支持的 schemaVersion")
    if not isinstance(payload.get("skills"), list):
        raise ValueError(f"{path}：skills 必须是 JSON 数组")
    return payload


def index_skills(snapshot: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in snapshot["skills"]:
        if not isinstance(item, dict):
            raise ValueError(f"{source}：每个 Skill 都必须是 JSON 对象")
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            raise ValueError(f"{source}：每个 Skill 都必须包含非空 slug")
        if slug in indexed:
            raise ValueError(f"{source}：Skill slug 重复：{slug}")
        stats = item.get("stats")
        if stats is not None and not isinstance(stats, dict):
            raise ValueError(f"{source}：{slug}.stats 必须是 JSON 对象")
        indexed[slug] = item
    return indexed


def metric_delta(previous: Any, current: Any) -> int | float | None:
    if isinstance(previous, bool) or isinstance(current, bool):
        return None
    if not isinstance(previous, (int, float)):
        return None
    if not isinstance(current, (int, float)):
        return None
    return current - previous


def parse_timestamp(value: Any, source: str) -> datetime | None:
    if value is None:
        return None
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


def evaluate_evidence(
    previous: dict[str, Any],
    current: dict[str, Any],
    previous_source: str,
    current_source: str,
) -> dict[str, Any]:
    reasons: list[str] = []
    previous_time = parse_timestamp(previous.get("collectedAt"), previous_source)
    current_time = parse_timestamp(current.get("collectedAt"), current_source)
    elapsed_days: float | None = None
    if previous_time is not None and current_time is not None:
        elapsed_days = (current_time - previous_time).total_seconds() / 86400
        if elapsed_days < 0:
            raise ValueError("当前快照时间早于前次快照")

    previous_install = previous.get("activeInstall")
    current_install = current.get("activeInstall")
    same_method = (
        isinstance(previous.get("method"), str)
        and bool(previous.get("method"))
        and previous.get("method") == current.get("method")
    )

    if previous_install is True or current_install is True:
        status = "contaminated"
        reasons.append("至少一个快照声明执行过主动安装")
    elif not same_method:
        status = "incomparable"
        reasons.append("两个快照的采集方法缺失或不一致")
    elif not isinstance(previous_install, bool) or not isinstance(
        current_install, bool
    ):
        status = "insufficient"
        reasons.append("至少一个快照缺少 activeInstall 布尔声明")
    elif elapsed_days is None:
        status = "insufficient"
        reasons.append("至少一个快照缺少 collectedAt")
    elif elapsed_days < MIN_OBSERVATION_DAYS:
        status = "premature"
        reasons.append(
            f"观察窗口仅 {elapsed_days:.2f} 天，少于 {MIN_OBSERVATION_DAYS} 天"
        )
    else:
        status = "eligible"
        reasons.append(
            f"同口径、无主动安装声明，观察窗口为 {elapsed_days:.2f} 天"
        )

    return {
        "status": status,
        "decisionReady": status == "eligible",
        "minimumDays": MIN_OBSERVATION_DAYS,
        "elapsedDays": elapsed_days,
        "sameMethod": same_method,
        "previousActiveInstall": previous_install,
        "currentActiveInstall": current_install,
        "reasons": reasons,
    }


def compare_skill(
    slug: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    alerts: list[str] = []
    observed_signals: list[str] = []
    regressions: list[str] = []

    for field in ("displayName", "latestVersion", "moderation"):
        before = previous.get(field)
        after = current.get(field)
        if before != after:
            changes.append({"field": field, "before": before, "after": after})

    if previous.get("latestVersion") != current.get("latestVersion"):
        alerts.append("latest 版本发生变化；执行一次限定范围的 E4 验收")

    moderation = current.get("moderation")
    if moderation != "clean":
        alerts.append(f"moderation 为 {moderation!r}，预期为 'clean'")

    previous_stats = previous.get("stats") or {}
    current_stats = current.get("stats") or {}
    metrics: dict[str, dict[str, Any]] = {}
    for metric in METRICS:
        before = previous_stats.get(metric)
        after = current_stats.get(metric)
        delta = metric_delta(before, after)
        metrics[metric] = {"before": before, "after": after, "delta": delta}
        if delta is not None and delta > 0:
            observed_signals.append(f"{metric} +{delta:g}")
        elif delta is not None and delta < 0:
            regressions.append(f"{metric} {delta:g}")

    if regressions:
        alerts.append("一个或多个计数下降；检查 registry 口径修正或数据异常")

    if alerts:
        status = "verify"
    elif observed_signals or changes:
        status = "observe"
    else:
        status = "unchanged"

    return {
        "slug": slug,
        "status": status,
        "changes": changes,
        "metrics": metrics,
        "observedSignals": observed_signals,
        "regressions": regressions,
        "alerts": alerts,
    }


def compare_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
    previous_source: str = "previous",
    current_source: str = "current",
) -> dict[str, Any]:
    previous_skills = index_skills(previous, previous_source)
    current_skills = index_skills(current, current_source)
    evidence_quality = evaluate_evidence(
        previous,
        current,
        previous_source,
        current_source,
    )
    results: list[dict[str, Any]] = []

    for slug in sorted(previous_skills.keys() | current_skills.keys()):
        if slug not in previous_skills:
            results.append(
                {
                    "slug": slug,
                    "status": "verify",
                    "changes": [{"field": "catalog", "before": None, "after": "added"}],
                    "metrics": {},
                    "observedSignals": [],
                    "regressions": [],
                    "alerts": ["出现新 Skill；验证 metadata 与 latest artifact"],
                }
            )
        elif slug not in current_skills:
            results.append(
                {
                    "slug": slug,
                    "status": "verify",
                    "changes": [{"field": "catalog", "before": "present", "after": None}],
                    "metrics": {},
                    "observedSignals": [],
                    "regressions": [],
                    "alerts": ["Skill 从当前快照中消失"],
                }
            )
        else:
            results.append(
                compare_skill(slug, previous_skills[slug], current_skills[slug])
            )

    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("verify", "observe", "unchanged")
    }
    return {
        "schemaVersion": 1,
        "previousCollectedAt": previous.get("collectedAt"),
        "currentCollectedAt": current.get("collectedAt"),
        "evidenceQuality": evidence_quality,
        "attribution": (
            "观察到的计数变化不能证明自然采用。downloads 不是独立用户数，"
            "installs 可能包含维护者验收。"
        ),
        "summary": {"skills": len(results), **counts},
        "skills": results,
    }


def format_value(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|")


def render_markdown(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    evidence = comparison["evidenceQuality"]
    elapsed_days = evidence.get("elapsedDays")
    elapsed_label = "未知" if elapsed_days is None else f"{elapsed_days:.2f} 天"
    lines = [
        "# ClawHub 指标变化",
        "",
        f"- 前次快照：`{format_value(comparison['previousCollectedAt'])}`",
        f"- 当前快照：`{format_value(comparison['currentCollectedAt'])}`",
        f"- 观察窗口：{elapsed_label}",
        (
            f"- 证据质量：`{evidence['status']}`；"
            f"{'可进入增长决策' if evidence['decisionReady'] else '不可进入增长决策'}"
        ),
        (
            f"- 状态：{summary['verify']} 个需验证，"
            f"{summary['observe']} 个需观察，{summary['unchanged']} 个无变化"
        ),
        "",
        "> 指标变化只代表观察到的计数变化，不证明自然采用或独立用户增长。",
        f"> 证据门槛：{'; '.join(evidence['reasons'])}",
        "",
        "| Skill | 状态 | Downloads | Installs | Stars | Latest / Moderation |",
        "|---|---|---:|---:|---:|---|",
    ]

    for item in comparison["skills"]:
        metrics = item["metrics"]

        def metric_cell(name: str) -> str:
            metric = metrics.get(name)
            if not metric:
                return "—"
            delta = metric.get("delta")
            if delta is None:
                return format_value(metric.get("after"))
            sign = "+" if delta > 0 else ""
            return f"{format_value(metric.get('after'))} ({sign}{delta:g})"

        field_changes = {
            change["field"]: change for change in item.get("changes", [])
        }
        version_change = field_changes.get("latestVersion")
        moderation_change = field_changes.get("moderation")
        details: list[str] = []
        if version_change:
            details.append(
                f"{format_value(version_change['before'])} → "
                f"{format_value(version_change['after'])}"
            )
        if moderation_change:
            details.append(
                f"moderation {format_value(moderation_change['before'])} → "
                f"{format_value(moderation_change['after'])}"
            )
        if "catalog" in field_changes:
            details.append(
                f"catalog {format_value(field_changes['catalog']['before'])} → "
                f"{format_value(field_changes['catalog']['after'])}"
            )

        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{item['slug']}`",
                    item["status"],
                    metric_cell("downloads"),
                    metric_cell("installs"),
                    metric_cell("stars"),
                    "<br>".join(details) or "—",
                )
            )
            + " |"
        )

    alerts = [
        (item["slug"], alert)
        for item in comparison["skills"]
        for alert in item.get("alerts", [])
    ]
    if alerts:
        lines.extend(["", "## 需处理"])
        lines.extend(f"- `{slug}`：{alert}" for slug, alert in alerts)

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在不访问网络的情况下对比两个 ClawHub 指标快照。"
    )
    parser.add_argument("previous", type=Path, help="较早的快照 JSON。")
    parser.add_argument("current", type=Path, help="较新的快照 JSON。")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="输出格式。",
    )
    parser.add_argument("--output", type=Path, help="将结果写入指定文件。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        previous = load_snapshot(args.previous)
        current = load_snapshot(args.current)
        comparison = compare_snapshots(
            previous,
            current,
            previous_source=str(args.previous),
            current_source=str(args.current),
        )
        if args.format == "json":
            output = json.dumps(comparison, ensure_ascii=False, indent=2) + "\n"
        else:
            output = render_markdown(comparison)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"指标对比失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

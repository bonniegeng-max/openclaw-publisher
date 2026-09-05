#!/usr/bin/env python3
"""统一增长监控入口使用的内部 ClawHub 搜索采集器。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from clawhub_monitor_capability import (
        sanitized_environment,
        validate_collector_capability,
    )
except ModuleNotFoundError:
    from scripts.clawhub_monitor_capability import (
        sanitized_environment,
        validate_collector_capability,
    )


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
VERSION_SUFFIX = re.compile(r"^(?P<slug>.+) v\d+\.\d+\.\d+(?:[-+][^\s]+)?$")
METRIC_PATTERNS = (
    (re.compile(r"^(?P<value>[\d,]+) installs / 60d$"), "rolling60DayInstalls"),
    (
        re.compile(r"^(?P<value>[\d,]+) skills\.sh lifetime installs$"),
        "skillsShLifetimeInstalls",
    ),
    (re.compile(r"^(?P<value>[\d,]+) downloads?$"), "downloads"),
    (re.compile(r"^score (?P<value>-?\d+(?:\.\d+)?)$"), "score"),
)


def load_queries(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("查询配置必须是 schemaVersion 1 的 JSON 对象")
    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError("queries 必须是非空数组")

    queries: list[dict[str, Any]] = []
    slugs: set[str] = set()
    terms: set[str] = set()
    for item in raw_queries:
        if not isinstance(item, dict):
            raise ValueError("每条查询配置必须是 JSON 对象")
        slug = item.get("slug")
        query = item.get("query")
        limit = item.get("limit", 20)
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("每条查询必须包含非空 slug")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{slug}：query 必须是非空字符串")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(f"{slug}：limit 必须是 1 到 100 的整数")
        normalized_slug = slug.strip()
        normalized_query = " ".join(query.split())
        if normalized_slug in slugs:
            raise ValueError(f"slug 重复：{normalized_slug}")
        if normalized_query.casefold() in terms:
            raise ValueError(f"query 重复：{normalized_query}")
        slugs.add(normalized_slug)
        terms.add(normalized_query.casefold())
        queries.append(
            {
                "slug": normalized_slug,
                "query": normalized_query,
                "limit": limit,
            }
        )
    return queries


def load_catalog_slugs(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Skill catalog 必须是非空 JSON 对象")
    slugs: set[str] = set()
    for raw_path in payload:
        parts = Path(raw_path).parts
        if len(parts) != 2 or parts[0] != "skills":
            raise ValueError(f"catalog 路径格式异常：{raw_path}")
        slugs.add(parts[1])
    return slugs


def validate_query_coverage(
    queries: list[dict[str, Any]],
    catalog_slugs: set[str],
) -> None:
    query_slugs = {item["slug"] for item in queries}
    missing = sorted(catalog_slugs - query_slugs)
    extra = sorted(query_slugs - catalog_slugs)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"缺少：{', '.join(missing)}")
        if extra:
            details.append(f"多余：{', '.join(extra)}")
        raise ValueError(f"搜索查询与 catalog 不一致（{'；'.join(details)}）")


def parse_metric(text: str) -> dict[str, Any]:
    for pattern, metric_type in METRIC_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        raw_value = match.group("value").replace(",", "")
        value: int | float
        if metric_type == "score":
            value = float(raw_value)
        else:
            value = int(raw_value)
        return {"type": metric_type, "value": value, "label": text}
    raise ValueError(f"无法识别搜索指标：{text}")


def parse_search_output(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = ANSI_ESCAPE.sub("", raw_line).strip()
        if not line:
            continue
        if line == "No skills found.":
            if rows:
                raise ValueError("搜索输出同时包含结果和 No skills found")
            return []
        columns = re.split(r"\s{2,}", line)
        if len(columns) < 4:
            raise ValueError(f"无法解析搜索结果行：{line}")
        reference = columns[0]
        owner = columns[1]
        display_name = " ".join(columns[2:-1])
        metric_text = columns[-1]
        version_match = VERSION_SUFFIX.fullmatch(reference)
        slug = version_match.group("slug") if version_match else reference
        rows.append(
            {
                "rank": len(rows) + 1,
                "reference": reference,
                "slug": slug,
                "owner": owner,
                "displayName": display_name,
                "metric": parse_metric(metric_text),
            }
        )
    return rows


def run_cli(
    args: list[str],
    timeout: int,
    runner: RunCommand,
) -> subprocess.CompletedProcess[str]:
    env = {
        **sanitized_environment(),
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
    }
    completed = runner(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"命令失败：{' '.join(args)}：{message}")
    return completed


def collect_query(
    clawhub_bin: str,
    query: dict[str, Any],
    timeout: int,
    runner: RunCommand = subprocess.run,
) -> dict[str, Any]:
    completed = run_cli(
        [
            clawhub_bin,
            "search",
            query["query"],
            "--limit",
            str(query["limit"]),
        ],
        timeout,
        runner,
    )
    results = parse_search_output(completed.stdout)
    rank = next(
        (
            item["rank"]
            for item in results
            if item["slug"].casefold() == query["slug"].casefold()
        ),
        None,
    )
    return {
        **query,
        "rank": rank,
        "visible": rank is not None,
        "resultCount": len(results),
        "results": results,
    }


def build_snapshot(
    query_path: Path,
    catalog_path: Path,
    clawhub_bin: str,
    timeout: int,
    runner: RunCommand = subprocess.run,
) -> dict[str, Any]:
    queries_config = load_queries(query_path)
    validate_query_coverage(queries_config, load_catalog_slugs(catalog_path))
    version = run_cli([clawhub_bin, "--cli-version"], timeout, runner).stdout.strip()
    queries = [
        collect_query(clawhub_bin, query, timeout, runner)
        for query in queries_config
    ]
    return {
        "schemaVersion": 1,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "method": "clawhub search",
        "activeInstall": False,
        "cliVersion": version,
        "caveats": [
            "search rank is a point-in-time observation, not a stable position",
            "result metrics may use different sources and time windows",
            "search collection does not download or install skills",
        ],
        "queries": queries,
    }


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


def write_snapshot_with_previous(
    output_path: Path,
    previous_path: Path,
    payload: dict[str, Any],
) -> None:
    if output_path.resolve() == previous_path.resolve():
        raise ValueError("output 与 previous-output 不能是同一路径")
    if output_path.exists():
        previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(previous_payload, dict):
            raise ValueError("现有搜索快照必须是 JSON 对象")
        write_json_atomic(previous_path, previous_payload)
    write_json_atomic(output_path, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "统一增长监控入口使用的内部搜索采集器；"
            "请运行 run_clawhub_growth_monitor.py。"
        )
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("metrics/search-queries.json"),
        help="受版本控制的查询配置。",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(".clawhub/skill-catalog.json"),
        help="用于校验查询覆盖范围的 Skill catalog。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("metrics/clawhub-search-latest.json"),
        help="当前搜索快照输出路径。",
    )
    parser.add_argument(
        "--previous-output",
        type=Path,
        default=Path("metrics/clawhub-search-previous.json"),
        help="前次成功搜索快照的保留路径。",
    )
    parser.add_argument("--clawhub-bin", default="clawhub", help="ClawHub CLI。")
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="每条命令的超时秒数。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_collector_capability(
            Path(__file__),
            args.output,
            args.previous_output,
            environment=os.environ,
        )
        snapshot = build_snapshot(
            query_path=args.queries,
            catalog_path=args.catalog,
            clawhub_bin=args.clawhub_bin,
            timeout=args.timeout,
        )
        write_snapshot_with_previous(args.output, args.previous_output, snapshot)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"搜索可见性采集失败：{exc}", file=sys.stderr)
        return 1

    print(f"已写入 {len(snapshot['queries'])} 条搜索可见性记录：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

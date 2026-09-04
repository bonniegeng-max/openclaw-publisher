#!/usr/bin/env python3
"""Collect a passive ClawHub portfolio snapshot without installing skills."""

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


def load_slugs(catalog_path: Path) -> list[str]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError("catalog root must be a JSON object")

    slugs: list[str] = []
    for raw_path in catalog:
        path = Path(raw_path)
        if len(path.parts) != 2 or path.parts[0] != "skills":
            raise ValueError(f"unexpected catalog key: {raw_path}")
        slugs.append(path.name)

    if not slugs:
        raise ValueError("catalog does not contain any skills")
    return sorted(set(slugs))


def inspect_skill(
    clawhub_bin: str,
    slug: str,
    timeout: int,
    runner: RunCommand = subprocess.run,
) -> dict[str, Any]:
    completed = runner(
        [clawhub_bin, "inspect", slug, "--json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{slug}: inspect failed: {message}")

    payload = json.loads(completed.stdout)
    skill = payload.get("skill") or {}
    latest = payload.get("latestVersion") or {}
    moderation = payload.get("moderation") or {}
    stats = skill.get("stats") or {}

    return {
        "slug": skill.get("slug") or slug,
        "displayName": skill.get("displayName"),
        "summary": skill.get("summary"),
        "topics": skill.get("topics") or [],
        "latestVersion": latest.get("version"),
        "moderation": moderation.get("verdict"),
        "stats": {
            "downloads": stats.get("downloads"),
            "installs": stats.get("installs"),
            "stars": stats.get("stars"),
            "versions": stats.get("versions"),
        },
        "registryUpdatedAt": skill.get("updatedAt"),
    }


def build_snapshot(
    catalog_path: Path,
    clawhub_bin: str,
    timeout: int,
    runner: RunCommand = subprocess.run,
) -> dict[str, Any]:
    skills = [
        inspect_skill(clawhub_bin, slug, timeout, runner)
        for slug in load_slugs(catalog_path)
    ]
    return {
        "schemaVersion": 1,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "method": "clawhub inspect --json",
        "activeInstall": False,
        "caveats": [
            "downloads are not unique users",
            "installs may include maintainer verification",
            "this snapshot alone does not prove a trend",
            "do not run install for unchanged versions during routine collection",
        ],
        "skills": skills,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect ClawHub metrics without downloading or installing skills."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path(".clawhub/skill-catalog.json"),
        help="Catalog JSON used to discover skill slugs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("metrics/clawhub-latest.json"),
        help="Destination JSON snapshot.",
    )
    parser.add_argument(
        "--clawhub-bin",
        default="clawhub",
        help="ClawHub CLI executable.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for each inspect call.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        snapshot = build_snapshot(
            catalog_path=args.catalog,
            clawhub_bin=args.clawhub_bin,
            timeout=args.timeout,
        )
        write_json_atomic(args.output, snapshot)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"metrics collection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {len(snapshot['skills'])} passive metrics records to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

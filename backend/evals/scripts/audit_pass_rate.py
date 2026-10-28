#!/usr/bin/env python
"""Compute agent audit pass-rate metrics for inefficient-space / PostGIS runs.

Usage examples:

  # From live DB (requires DATABASE_URL / app config)
  poetry run python -m evals.scripts.audit_pass_rate --hours 168

  # From exported JSON dump of agent_runs (+ optional events)
  poetry run python -m evals.scripts.audit_pass_rate --from-json path/to/runs.json

JSON dump format:
{
  "runs": [
    {
      "id": "...",
      "query": "...",
      "status": "success",
      "conversation_id": "...",
      "metrics": {"error_count": 0, "tool_error_count": 0},
      "events": [
        {"event_type": "tool_start", "name": "list_postgis_layers"},
        {"event_type": "tool_end", "name": "list_postgis_layers", "output": {"status": "success"}}
      ]
    }
  ]
}
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


INEFFICIENT_QUERY_RE = re.compile(
    r"低效|闲置空地|容积率判别|工业低效|商业低效|居住低效|inefficient|vacant land",
    re.IGNORECASE,
)
POSTGIS_QUERY_RE = re.compile(
    r"postgis|数据库|空间表|数据表|postgres|加载.*表|查看数据库",
    re.IGNORECASE,
)

EXPECTED_INEFF_TOOLS = {
    "analyze_inefficient_space",
    "analyze_inefficient_space_tool",
    "infer_inefficient_field_mapping",
    "get_inefficient_presets",
}
EXPECTED_POSTGIS_TOOLS = {
    "list_postgis_layers",
    "load_postgis_layer",
}


def _normalize_status(status: Optional[str]) -> str:
    value = (status or "").lower()
    if value in {"success", "partial_success", "failed", "error", "cancelled", "running"}:
        if value == "error":
            return "failed"
        return value
    return value or "unknown"


def _tool_names_from_events(events: Sequence[Dict[str, Any]]) -> Set[str]:
    names: Set[str] = set()
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type not in {"tool_start", "tool_end", "tool_error"}:
            continue
        name = event.get("name")
        if name:
            names.add(str(name))
        payload = event.get("payload") or {}
        if isinstance(payload, dict) and payload.get("tool"):
            names.add(str(payload["tool"]))
        input_data = event.get("input") or event.get("input_json") or {}
        if isinstance(input_data, dict) and input_data.get("tool"):
            names.add(str(input_data["tool"]))
    return names


def _tool_error_count(events: Sequence[Dict[str, Any]], metrics: Optional[Dict[str, Any]]) -> int:
    if isinstance(metrics, dict) and metrics.get("tool_error_count") is not None:
        try:
            return int(metrics.get("tool_error_count") or 0)
        except (TypeError, ValueError):
            pass
    return sum(1 for event in events if event.get("event_type") == "tool_error")


def classify_bucket(query: Optional[str]) -> str:
    text = query or ""
    ineff = bool(INEFFICIENT_QUERY_RE.search(text))
    postgis = bool(POSTGIS_QUERY_RE.search(text))
    if ineff and postgis:
        return "combined"
    if ineff:
        return "inefficient_space"
    if postgis:
        return "postgis"
    return "other"


def score_run(run: Dict[str, Any]) -> Dict[str, Any]:
    status = _normalize_status(run.get("status"))
    query = run.get("query")
    events = run.get("events") or []
    metrics = run.get("metrics") or {}
    tools = _tool_names_from_events(events)
    bucket = classify_bucket(query)
    tool_errors = _tool_error_count(events, metrics)

    expected: Set[str] = set()
    if bucket in {"inefficient_space", "combined"}:
        expected |= EXPECTED_INEFF_TOOLS
    if bucket in {"postgis", "combined"}:
        expected |= EXPECTED_POSTGIS_TOOLS

    expected_hit = sorted(tools & expected) if expected else []
    expected_miss = sorted(expected - tools) if expected else []
    routing_ok = (not expected) or bool(expected_hit)
    run_ok = status in {"success", "partial_success"} and tool_errors == 0

    return {
        "id": run.get("id"),
        "query": query,
        "bucket": bucket,
        "status": status,
        "run_ok": run_ok,
        "routing_ok": routing_ok,
        "tool_errors": tool_errors,
        "tools": sorted(tools),
        "expected_hit": expected_hit,
        "expected_miss": expected_miss,
        "pass": bool(run_ok and routing_ok),
    }


def summarize(scored: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(scored)
    total = len(rows)
    passed = sum(1 for row in rows if row["pass"])
    by_bucket: Dict[str, Dict[str, Any]] = {}
    status_counter: Counter = Counter()
    for row in rows:
        status_counter[row["status"]] += 1
        bucket = row["bucket"]
        stats = by_bucket.setdefault(
            bucket, {"total": 0, "passed": 0, "run_ok": 0, "routing_ok": 0}
        )
        stats["total"] += 1
        if row["pass"]:
            stats["passed"] += 1
        if row["run_ok"]:
            stats["run_ok"] += 1
        if row["routing_ok"]:
            stats["routing_ok"] += 1

    for bucket, stats in by_bucket.items():
        total_b = stats["total"] or 1
        stats["pass_rate"] = round(stats["passed"] / total_b, 4)

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total) if total else 0.0, 4),
        "status_counts": dict(status_counter),
        "by_bucket": by_bucket,
        "runs": rows,
    }


def load_runs_from_json(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload.get("runs") or [])
    raise ValueError('JSON must be a list of runs or {"runs": [...]}')


async def load_runs_from_db(hours: int, limit: int) -> List[Dict[str, Any]]:
    from sqlalchemy import desc, select

    from db.models.agent_audit import AgentRun, AgentRunEvent
    from db.session import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise RuntimeError("Database session is not configured")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentRun)
            .where(AgentRun.created_at >= since)
            .order_by(desc(AgentRun.created_at))
            .limit(limit)
        )
        runs = list(result.scalars().all())
        output: List[Dict[str, Any]] = []
        for run in runs:
            events_result = await db.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.sequence.asc())
            )
            events = [
                {
                    "event_type": event.event_type,
                    "name": event.name,
                    "input": event.input_json or event.input,
                    "output": event.output_json or event.output,
                    "payload": event.payload_json or event.payload,
                }
                for event in events_result.scalars().all()
            ]
            output.append(
                {
                    "id": str(run.id),
                    "query": run.query,
                    "status": run.status,
                    "conversation_id": run.conversation_id,
                    "session_id": run.session_id,
                    "metrics": run.metrics or {},
                    "events": events,
                }
            )
        return output


def build_sample_report() -> Dict[str, Any]:
    """Offline demo sample so the script can be verified without DB."""
    sample_runs = [
        {
            "id": "sample-ineff-ok",
            "query": "识别工业低效用地",
            "status": "success",
            "metrics": {"tool_error_count": 0},
            "events": [
                {"event_type": "tool_start", "name": "infer_inefficient_field_mapping"},
                {"event_type": "tool_end", "name": "infer_inefficient_field_mapping"},
                {"event_type": "tool_start", "name": "analyze_inefficient_space"},
                {"event_type": "tool_end", "name": "analyze_inefficient_space"},
            ],
        },
        {
            "id": "sample-postgis-ok",
            "query": "查看数据库空间表",
            "status": "success",
            "metrics": {"tool_error_count": 0},
            "events": [
                {"event_type": "tool_start", "name": "list_postgis_layers"},
                {"event_type": "tool_end", "name": "list_postgis_layers"},
            ],
        },
        {
            "id": "sample-ineff-miss-tool",
            "query": "闲置空地判别",
            "status": "success",
            "metrics": {"tool_error_count": 0},
            "events": [
                {"event_type": "tool_start", "name": "attribute_tool2"},
                {"event_type": "tool_end", "name": "attribute_tool2"},
            ],
        },
        {
            "id": "sample-postgis-failed",
            "query": "加载 PostGIS public.parcels",
            "status": "failed",
            "metrics": {"tool_error_count": 1},
            "events": [
                {"event_type": "tool_start", "name": "load_postgis_layer"},
                {"event_type": "tool_error", "name": "load_postgis_layer"},
            ],
        },
    ]
    return summarize(score_run(run) for run in sample_runs)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent audit pass-rate for inefficient/PostGIS")
    parser.add_argument("--hours", type=int, default=168, help="Lookback window in hours")
    parser.add_argument("--limit", type=int, default=500, help="Max runs to load from DB")
    parser.add_argument("--from-json", type=Path, help="Load runs from JSON instead of DB")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Print demo metrics from built-in sample runs (no DB)",
    )
    parser.add_argument(
        "--bucket",
        choices=["all", "inefficient_space", "postgis", "combined", "other"],
        default="all",
        help="Filter scored output by query bucket",
    )
    parser.add_argument("--out", type=Path, help="Optional path to write JSON report")
    return parser.parse_args(argv)


async def _amain(args: argparse.Namespace) -> Dict[str, Any]:
    if args.sample:
        report = build_sample_report()
    elif args.from_json:
        runs = load_runs_from_json(args.from_json)
        report = summarize(score_run(run) for run in runs)
    else:
        runs = await load_runs_from_db(hours=args.hours, limit=args.limit)
        report = summarize(score_run(run) for run in runs)

    if args.bucket != "all":
        filtered = [row for row in report["runs"] if row["bucket"] == args.bucket]
        report = summarize(filtered)
        report["filter_bucket"] = args.bucket
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    import asyncio

    args = parse_args(argv)
    try:
        report = asyncio.run(_amain(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if report.get("total", 0) == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

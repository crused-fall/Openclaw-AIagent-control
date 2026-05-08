from __future__ import annotations

from typing import Any

USAGE_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "total")


def _empty_usage() -> dict[str, int]:
    return {field: 0 for field in USAGE_FIELDS}


def _usage_payload(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None

    payload = _empty_usage()
    derived_total = 0
    seen = False
    saw_total = False
    for field in USAGE_FIELDS:
        field_value = value.get(field)
        if isinstance(field_value, bool) or not isinstance(field_value, int):
            continue
        payload[field] += field_value
        if field != "total":
            derived_total += field_value
        else:
            saw_total = True
        seen = True
    if seen and not saw_total:
        payload["total"] = derived_total
    return payload if seen else None


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for field in USAGE_FIELDS:
        total[field] += usage[field]


def summarize_openclaw_usage(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results", [])
    if not isinstance(results, list):
        results = []

    result_count = 0
    usage_count = 0
    last_call_usage_count = 0
    usage_totals = _empty_usage()
    last_call_usage_totals = _empty_usage()

    for item in results:
        if not isinstance(item, dict):
            continue
        result_count += 1

        artifacts = item.get("artifacts", {})
        if not isinstance(artifacts, dict):
            continue

        usage = _usage_payload(artifacts.get("openclaw_usage"))
        if usage is not None:
            _add_usage(usage_totals, usage)
            usage_count += 1

        last_call_usage = _usage_payload(artifacts.get("openclaw_last_call_usage"))
        if last_call_usage is not None:
            _add_usage(last_call_usage_totals, last_call_usage)
            last_call_usage_count += 1

    return {
        "resultCount": result_count,
        "openclawUsageCount": usage_count,
        "openclawLastCallUsageCount": last_call_usage_count,
        "openclawUsage": usage_totals,
        "openclawLastCallUsage": last_call_usage_totals,
    }


def compare_openclaw_usage(left_usage: dict[str, Any], right_usage: dict[str, Any]) -> dict[str, Any]:
    left = left_usage if isinstance(left_usage, dict) else {}
    right = right_usage if isinstance(right_usage, dict) else {}
    left_totals = left.get("openclawUsage", {})
    right_totals = right.get("openclawUsage", {})
    left_last_call_totals = left.get("openclawLastCallUsage", {})
    right_last_call_totals = right.get("openclawLastCallUsage", {})
    left_result_count = left.get("resultCount", 0)
    right_result_count = right.get("resultCount", 0)
    left_usage_count = left.get("openclawUsageCount", 0)
    right_usage_count = right.get("openclawUsageCount", 0)
    left_last_call_count = left.get("openclawLastCallUsageCount", 0)
    right_last_call_count = right.get("openclawLastCallUsageCount", 0)

    return {
        "resultCountDelta": _int_value(right_result_count) - _int_value(left_result_count),
        "openclawUsageCountDelta": _int_value(right_usage_count) - _int_value(left_usage_count),
        "openclawLastCallUsageCountDelta": _int_value(right_last_call_count) - _int_value(left_last_call_count),
        "openclawUsageTotalDelta": _usage_total(right_totals) - _usage_total(left_totals),
        "openclawLastCallUsageTotalDelta": _usage_total(right_last_call_totals) - _usage_total(left_last_call_totals),
        "left": left,
        "right": right,
    }


def _int_value(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage_total(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    total = value.get("total")
    return total if isinstance(total, int) and not isinstance(total, bool) else 0

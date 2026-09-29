from __future__ import annotations

from math import ceil
from typing import Any


KNOWN_STATES = {"RUNNING", "QUEUED", "SUCCEEDED", "FAILED", "CANCELLED", "PENDING"}
ACTIVE_STATES = {"RUNNING", "QUEUED", "PENDING"}
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _state(row: dict[str, Any]) -> str:
    return str(row.get("state") or row.get("status") or "UNKNOWN").upper()


def _eta_seconds(row: dict[str, Any]) -> int | None:
    direct = _number(row.get("eta_seconds"))
    if direct is not None:
        return int(ceil(direct))

    remaining = _number(row.get("remaining_bytes"))
    throughput = _number(row.get("throughput_bytes_per_second"))
    if remaining is not None and throughput is not None and throughput > 0:
        return int(ceil(remaining / throughput))

    return None


def normalize_scope(raw: Any) -> dict[str, Any]:
    """Normalize an externally supplied active-migration scope.

    This function does not discover migrations and does not invent state. The
    caller must supply rows from an authoritative portal/control-plane adapter.
    """
    if not isinstance(raw, dict):
        return {"status": "UNKNOWN", "reason": "Scope provider returned no structured scope."}

    rows = raw.get("migrations")
    if not isinstance(rows, list):
        return {"status": "UNKNOWN", "reason": "Scope provider did not return a migrations list."}

    normalized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        migration_id = item.get("migration_id")
        if not migration_id:
            continue
        row = dict(item)
        row["migration_id"] = str(migration_id)
        row["state"] = _state(row)
        row["eta_seconds"] = _eta_seconds(row)
        normalized.append(row)

    return {
        "status": "KNOWN",
        "source": raw.get("source"),
        "observed_at": raw.get("observed_at"),
        "change_id": raw.get("change_id"),
        "wave_id": raw.get("wave_id"),
        "concurrency_limit": raw.get("concurrency_limit"),
        "migrations": normalized,
    }


def _window_remaining_seconds(state: dict[str, Any]) -> int | None:
    window = state.get("maintenance_window") or {}
    if window.get("remaining_seconds") is not None:
        return int(window["remaining_seconds"])
    minutes = window.get("remaining_minutes")
    if minutes is not None:
        try:
            return max(0, int(minutes) * 60)
        except (TypeError, ValueError):
            return None
    return None


def _estimate_queue_completion(rows: list[dict[str, Any]], concurrency_limit: int | None) -> int | None:
    """Estimate completion of the known workload using only supplied ETAs.

    Running jobs consume slots until their supplied ETA. Queued jobs are then
    assigned to the earliest available slot. Missing ETAs make the forecast
    UNKNOWN instead of being guessed from historical averages.
    """
    running = [r for r in rows if _state(r) == "RUNNING"]
    queued = [r for r in rows if _state(r) in {"QUEUED", "PENDING"}]

    if any(_eta_seconds(r) is None for r in running):
        return None
    if any(_eta_seconds(r) is None for r in queued):
        return None

    if concurrency_limit is None:
        # If every active row is explicitly RUNNING, concurrency is already
        # represented by the rows. Do not infer additional queue capacity.
        if queued:
            return None
        return max((_eta_seconds(r) or 0 for r in running), default=0)

    try:
        slots = max(1, int(concurrency_limit))
    except (TypeError, ValueError):
        return None

    # If the source reports more running jobs than its declared capacity, do
    # not silently correct it. That is inconsistent source data.
    if len(running) > slots:
        return None

    finish_times = sorted([_eta_seconds(r) or 0 for r in running])
    while len(finish_times) < slots:
        finish_times.append(0)

    for row in queued:
        duration = _eta_seconds(row)
        if duration is None:
            return None
        slot = min(range(slots), key=finish_times.__getitem__)
        finish_times[slot] += duration

    return max(finish_times, default=0)


def calculate_forecast(scope: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Calculate a deterministic workload forecast from current scope facts."""
    if scope.get("status") != "KNOWN":
        return {
            "status": "UNKNOWN",
            "reason": scope.get("reason", "Current migration scope is unavailable."),
            "confidence": "NONE",
        }

    rows = scope.get("migrations", [])
    if not isinstance(rows, list):
        return {"status": "UNKNOWN", "reason": "Migration scope is malformed.", "confidence": "NONE"}

    active = [r for r in rows if _state(r) in ACTIVE_STATES]
    running = [r for r in rows if _state(r) == "RUNNING"]
    queued = [r for r in rows if _state(r) in {"QUEUED", "PENDING"}]
    failed = [r for r in rows if _state(r) == "FAILED"]
    completed = [r for r in rows if _state(r) == "SUCCEEDED"]

    running_etas = [_eta_seconds(r) for r in running]
    # Do not pass None into max(). A newly-started migration may legitimately
    # have no ETA yet, even while another RUNNING migration has one.
    batch_eta = None if any(eta is None for eta in running_etas) else max(running_etas, default=0)

    try:
        concurrency = int(scope["concurrency_limit"]) if scope.get("concurrency_limit") is not None else None
    except (TypeError, ValueError):
        concurrency = None

    projected = _estimate_queue_completion(rows, concurrency)
    remaining = _window_remaining_seconds(state)
    within = None if projected is None or remaining is None else projected <= remaining

    if projected is None:
        status = "UNKNOWN"
        reason = "At least one active migration lacks a current ETA or usable throughput/remaining-bytes pair."
        confidence = "LOW"
    else:
        status = "KNOWN"
        reason = None
        confidence = "HIGH" if all(_eta_seconds(r) is not None for r in active) else "MEDIUM"

    return {
        "status": status,
        "reason": reason,
        "source": scope.get("source"),
        "observed_at": scope.get("observed_at"),
        "change_id": scope.get("change_id"),
        "wave_id": scope.get("wave_id"),
        "current_active": len(active),
        "current_running": len(running),
        "current_queued": len(queued),
        "current_failed": len(failed),
        "current_completed": len(completed),
        "current_batch_eta_seconds": batch_eta,
        "projected_wave_completion_seconds": projected,
        "window_remaining_seconds": remaining,
        "within_window": within,
        "confidence": confidence,
    }


def build_recovery_forecasts(
    base_scope: dict[str, Any],
    current_forecast: dict[str, Any],
    failed_migration_id: str | None,
    recovery_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project only options for which the option itself has a known duration.

    This intentionally does not manufacture a new migration row or alter the
    active scope. A failed migration is reintroduced only as a hypothetical
    scenario, and only with an explicit estimated duration from the option.
    """
    if current_forecast.get("status") != "KNOWN" or not failed_migration_id:
        return []

    rows = [dict(r) for r in base_scope.get("migrations", []) if isinstance(r, dict)]
    rows = [r for r in rows if r.get("migration_id") != str(failed_migration_id)]
    results = []

    for option in recovery_options:
        option_type = option.get("option_type")
        if option_type not in {"RETRY", "FIX_FORWARD", "ROLLBACK"}:
            continue
        if option.get("status") in {"NOT_READY", "NOT_FEASIBLE"}:
            results.append({
                "option_type": option_type,
                "status": option.get("status"),
                "projected_wave_completion_seconds": None,
                "within_window": None,
                "reason": "Recovery option is not currently feasible.",
            })
            continue

        duration = _number(option.get("estimated_minutes"))
        if duration is None:
            results.append({
                "option_type": option_type,
                "status": "UNKNOWN",
                "projected_wave_completion_seconds": None,
                "within_window": None,
                "reason": "No explicit recovery duration was supplied.",
            })
            continue

        hypothetical = dict(base_scope)
        hypothetical["migrations"] = rows + [{
            "migration_id": str(failed_migration_id),
            "state": "QUEUED",
            "eta_seconds": int(ceil(duration * 60)),
        }]
        projected = _estimate_queue_completion(hypothetical["migrations"], hypothetical.get("concurrency_limit"))
        remaining = current_forecast.get("window_remaining_seconds")
        within = None if projected is None or remaining is None else projected <= remaining
        results.append({
            "option_type": option_type,
            "status": "KNOWN" if projected is not None else "UNKNOWN",
            "projected_wave_completion_seconds": projected,
            "within_window": within,
            "estimated_recovery_seconds": int(ceil(duration * 60)),
            "reason": None if projected is not None else "Current scope lacks enough scheduling information.",
        })

    return results

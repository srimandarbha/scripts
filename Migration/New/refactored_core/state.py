from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    incident: dict[str, Any]
    goal: dict[str, Any]
    context: dict[str, Any]
    issue: dict[str, Any]

    evidence: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    rhokp: list[dict[str, Any]]
    sre_tracker: list[dict[str, Any]]

    missing_evidence: list[str]
    conflicts: list[dict[str, Any]]
    tool_history: list[dict[str, Any]]

    diagnosis: dict[str, Any] | None
    ownership: dict[str, Any] | None
    recommendation: dict[str, Any] | None
    timeline: list[dict[str, Any]]
    impact: dict[str, Any] | None
    retry_readiness: dict[str, Any] | None
    recovery_options: list[dict[str, Any]]
    maintenance_window: dict[str, Any]
    investigation_plan: dict[str, Any] | None
    migration_scope: dict[str, Any]
    migration_forecast: dict[str, Any] | None
    recovery_forecasts: list[dict[str, Any]]

    budget: dict[str, int | float]
    investigation_iteration: int
    status: str

    # Runtime injection is deliberately non-authoritative and never persisted.
    runtime: dict[str, Any]

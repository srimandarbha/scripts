"""Refactored Migration Failure Agent.

Architecture:
  Kafka incident -> context -> deterministic classification -> policy-driven
  evidence -> RHoKP + SRE Tracker -> hypotheses -> per-hypothesis evaluator ->
  diagnosis -> ownership -> recommendation.
  Current change/wave scope -> deterministic migration forecast -> recovery forecast.

The LLM is not the security boundary, confidence calculator, state machine, or
arbitrary tool router. Phase 1 remains read-only.
"""
from __future__ import annotations

from typing import Any, Literal

from migration_failure_agent_tool_gateway import build_production_runtime
from migration_failure_agent_production import (
    require_enabled,
    concurrency_limiter,
    record_run_version,
    notify_oncall,
    NotificationPayload,
)
from migration_failure_agent_routing import classify_owning_team, route_insufficient_evidence
from refactored_core.graph_nodes import (
    build_recommendation_node,
    build_timeline_node,
    build_impact_node,
    build_migration_scope_node,
    build_migration_forecast_node,
    build_retry_readiness_node,
    classify_issue,
    evaluate,
    build_ownership,
    generate_hypotheses,
    investigate,
    resolve_conflict_or_stop,
    resolve_context,
    retrieve_knowledge,
)
from refactored_core.local_runner import run_local
from refactored_core.state import AgentState

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # local test environments may not have LangGraph installed
    StateGraph = None
    END = "__END__"


INITIAL_BUDGET = {
    "tool_calls": 16,
    "knowledge_calls": 4,
    "llm_calls": 4,
    "max_iterations": 3,
}


def _route_after_evaluation(state: AgentState) -> Literal["diagnosis", "retry", "conflict", "end"]:
    status = state.get("status")
    if status == "DIAGNOSIS_READY":
        return "diagnosis"
    if status == "CONFLICTING_EVIDENCE":
        return "conflict"
    if status == "INSUFFICIENT_EVIDENCE":
        if state.get("investigation_iteration", 0) < int(state.get("budget", {}).get("max_iterations", 3)):
            return "retry"
        return "end"
    if state.get("investigation_iteration", 0) >= int(state.get("budget", {}).get("max_iterations", 3)):
        return "end"
    return "retry"


def build_graph():
    if StateGraph is None:
        raise RuntimeError(
            "LangGraph is not installed in this environment. Install the production "
            "dependency with 'pip install langgraph' before deploying the agent. "
            "Use run_local() for the deterministic simulation harness."
        )

    graph = StateGraph(AgentState)
    graph.add_node("resolve_context", resolve_context)
    graph.add_node("classify_issue", classify_issue)
    graph.add_node("investigate", investigate)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("generate_hypotheses", generate_hypotheses)
    graph.add_node("evaluate", evaluate)
    graph.add_node("resolve_conflict", resolve_conflict_or_stop)
    graph.add_node("build_diagnosis", lambda s: s)
    graph.add_node("build_ownership", build_ownership)
    graph.add_node("build_timeline", build_timeline_node)
    graph.add_node("build_impact", build_impact_node)
    graph.add_node("build_retry_readiness", build_retry_readiness_node)
    graph.add_node("resolve_migration_scope", build_migration_scope_node)
    graph.add_node("resolve_migration_forecast", build_migration_forecast_node)
    graph.add_node("refresh_migration_scope", build_migration_scope_node)
    graph.add_node("refresh_migration_forecast", build_migration_forecast_node)
    graph.add_node("build_recommendation", build_recommendation_node)

    graph.set_entry_point("resolve_context")
    graph.add_edge("resolve_context", "resolve_migration_scope")
    graph.add_edge("resolve_migration_scope", "resolve_migration_forecast")
    graph.add_edge("resolve_migration_forecast", "classify_issue")
    graph.add_edge("classify_issue", "investigate")
    graph.add_edge("investigate", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "generate_hypotheses")
    graph.add_edge("generate_hypotheses", "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluation,
        {
            "diagnosis": "build_diagnosis",
            "retry": "investigate",
            "conflict": "resolve_conflict",
            "end": END,
        },
    )

    graph.add_conditional_edges(
        "resolve_conflict",
        lambda s: "retry" if s.get("status") == "INVESTIGATING" else "end",
        {"retry": "investigate", "end": END},
    )
    graph.add_edge("build_diagnosis", "build_timeline")
    graph.add_edge("build_timeline", "build_impact")
    graph.add_edge("build_impact", "build_ownership")
    graph.add_edge("build_ownership", "build_retry_readiness")
    graph.add_edge("build_retry_readiness", "refresh_migration_scope")
    graph.add_edge("refresh_migration_scope", "refresh_migration_forecast")
    graph.add_edge("refresh_migration_forecast", "build_recommendation")
    graph.add_edge("build_recommendation", END)
    return graph.compile()


_compiled = None


def _get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def initialize_state(
    *,
    incident_id: str,
    trigger_payload: dict[str, Any],
    runtime: Any = None,
    budget: dict[str, int | float] | None = None,
    capability_adapters: dict[str, Any] | None = None,
    prompt_hashes: dict[str, str] | None = None,
) -> AgentState:
    from migration_failure_agent_llm import generate_hypotheses_llm
    effective_runtime = runtime or build_production_runtime(capability_adapters=capability_adapters)
    if runtime is None:
        # Production gets the structured LLM hypothesis adapter. The local
        # simulation passes its own ToolRuntime and intentionally omits it.
        pass
    return {
        "incident": {
            "incident_id": incident_id,
            **trigger_payload,
        },
        "goal": {
            "objective": "Determine the most likely technical cause of the migration failure, identify responsible ownership, and recommend the next safe troubleshooting step.",
            "success_conditions": [
                "failure_confirmed",
                "migration_context_resolved",
                "issue_classified",
                "current_evidence_collected",
                "RHoKP_checked",
                "SRE_Tracker_checked",
                "hypotheses_evaluated",
                "diagnosis_or_insufficient_evidence_recorded",
                "recommendation_generated_when_diagnosis_is_supported",
            ],
            "constraints": [
                "read_only",
                "no_direct_cluster_mutation",
                "current_evidence_must_correlate_with_knowledge",
                "human_review_required",
            ],
        },
        "context": {},
        "issue": {},
        "evidence": [],
        "hypotheses": [],
        "rhokp": [],
        "sre_tracker": [],
        "missing_evidence": [],
        "conflicts": [],
        "tool_history": [],
        "diagnosis": None,
        "ownership": None,
        "recommendation": None,
        "timeline": [],
        "impact": None,
        "retry_readiness": None,
        "recovery_options": [],
        "maintenance_window": {},
        "migration_scope": {"status": "UNKNOWN", "reason": "Not resolved yet."},
        "migration_forecast": None,
        "recovery_forecasts": [],
        "investigation_plan": None,
        "budget": budget or dict(INITIAL_BUDGET),
        "investigation_iteration": 0,
        "status": "NEW",
        "terminal_reason": "",
        "runtime": {
            "tool_runtime": effective_runtime,
            "hypothesis_generator": generate_hypotheses_llm if runtime is None else None,
            "prompt_hashes": dict(prompt_hashes or {}),
        },
    }


def _notify_result(state: AgentState) -> None:
    """Best-effort human-facing delivery after a terminal graph result.

    Notification failure must never mutate the diagnosis or make an otherwise
    completed read-only investigation fail. The actual channel dispatcher is
    injected/implemented by the production integration layer.
    """
    status = state.get("status", "UNKNOWN")
    if status not in {"DIAGNOSIS_READY", "INSUFFICIENT_EVIDENCE", "ESCALATED", "COMPLETED"}:
        return

    diagnosis = state.get("diagnosis") or {}
    if diagnosis:
        primary, teams, rationale = classify_owning_team(diagnosis, state.get("evidence", []))
        state.setdefault("ownership", {})
        state["ownership"]["primary"] = primary
        state["ownership"]["notify_teams"] = teams
        state["ownership"]["routing_rationale"] = rationale
    else:
        teams = route_insufficient_evidence(state.get("missing_evidence", []))

    payload = NotificationPayload(
        incident_id=str(state.get("incident", {}).get("incident_id", "UNKNOWN")),
        status=("DIAGNOSIS_READY" if diagnosis else status),
        summary=str((state.get("recommendation") or {}).get("summary") or diagnosis.get("root_cause") or "Migration investigation requires attention."),
        confidence_band=diagnosis.get("confidence_band"),
        dashboard_url=str(state.get("incident", {}).get("dashboard_url") or ""),
        notify_teams=teams,
    )
    notify_oncall(payload)


def run_agent(initial_state: AgentState) -> AgentState:
    """Production entry point with kill-switch, concurrency and audit guards."""
    require_enabled()
    incident_id = str(initial_state.get("incident", {}).get("incident_id", "UNKNOWN"))
    with concurrency_limiter.acquire(incident_id):
        # The current production module owns persistence/versioning. Keep this
        # call at the boundary so every run is attributable even if the graph
        # later changes internally. Prompt hashes are supplied by the prompt
        # layer when available; an empty map is explicit rather than fabricated.
        record_run_version(incident_id, dict(initial_state.get("runtime", {}).get("prompt_hashes", {})))
        result = _get_graph().invoke(initial_state)
        try:
            _notify_result(result)
        except Exception as exc:  # notification is best-effort by design
            result.setdefault("conflicts", []).append({
                "type": "NOTIFICATION_FAILURE",
                "error": str(exc),
            })
        return result


def run_simulation(trigger_payload: dict[str, Any], handlers: dict[str, Any]) -> AgentState:
    from refactored_core.tool_runtime import ToolRuntime

    state = initialize_state(
        incident_id=str(trigger_payload.get("incident_id", "SIM-0001")),
        trigger_payload=trigger_payload,
        runtime=ToolRuntime(handlers),
    )
    return run_local(state)


if __name__ == "__main__":
    print("Use run_agent() with LangGraph in production or run_simulation() for local tests.")

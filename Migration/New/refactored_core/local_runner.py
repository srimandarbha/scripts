from __future__ import annotations

from .graph_nodes import (
    build_recommendation_node,
    classify_issue,
    build_migration_scope_node,
    build_migration_forecast_node,
    evaluate,
    generate_hypotheses,
    investigate,
    resolve_conflict_or_stop,
    resolve_context,
    retrieve_knowledge,
)
from .state import AgentState


def run_local(state: AgentState) -> AgentState:
    state = resolve_context(state)
    if state["status"] == "BLOCKED":
        state["terminal_reason"] = "BLOCKED"
        return state

    state = build_migration_scope_node(state)
    state = build_migration_forecast_node(state)
    state = classify_issue(state)
    state = investigate(state)
    state = retrieve_knowledge(state)
    state = generate_hypotheses(state)
    state = evaluate(state)

    if state["status"] in {"CONFLICTING_EVIDENCE", "INSUFFICIENT_EVIDENCE"}:
        if state["status"] == "CONFLICTING_EVIDENCE":
            state = resolve_conflict_or_stop(state)
        if state["status"] == "INVESTIGATING" or (state["status"] == "INSUFFICIENT_EVIDENCE" and state.get("investigation_iteration", 0) < int(state.get("budget", {}).get("max_iterations", 3))):
            state["status"] = "INVESTIGATING"
            state = investigate(state)
            state = retrieve_knowledge(state)
            state = generate_hypotheses(state)
            state = evaluate(state)
            if state["status"] == "CONFLICTING_EVIDENCE":
                state = resolve_conflict_or_stop(state)

    if state.get("diagnosis"):
        from .graph_nodes import (build_ownership, build_timeline_node, build_impact_node, build_retry_readiness_node)
        state = build_timeline_node(state)
        state = build_impact_node(state)
        state = build_ownership(state)
        state = build_retry_readiness_node(state)
        state = build_migration_scope_node(state)
        state = build_migration_forecast_node(state)
        state = build_recommendation_node(state)
        state["terminal_reason"] = "DIAGNOSIS_READY"
    else:
        state["terminal_reason"] = state.get("status", "INSUFFICIENT_EVIDENCE")
    return state

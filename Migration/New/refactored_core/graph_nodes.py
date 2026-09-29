from __future__ import annotations

import uuid
from typing import Any, Callable

from .classification import classify
from .evaluator import evaluate_all
from .knowledge import build_signature, normalize_rhokp, normalize_sre_tracker
from .policies import DEFAULT_REQUIRED, INVESTIGATION_POLICIES
from .recommendation import build_recommendation
from .action_planner import build_impact, build_timeline, build_maintenance_window, evaluate_retry_readiness, next_best_investigation
from .scope_forecast import normalize_scope, calculate_forecast, build_recovery_forecasts
from .state import AgentState
from .tool_runtime import ToolRuntime


def _transition(state: AgentState, target: str) -> AgentState:
    allowed = {
        "NEW": {"CONTEXT_LOADING", "BLOCKED"},
        "CONTEXT_LOADING": {"CLASSIFYING", "BLOCKED"},
        "CLASSIFYING": {"INVESTIGATING", "BLOCKED"},
        "INVESTIGATING": {"KNOWLEDGE_RETRIEVAL", "BLOCKED", "INSUFFICIENT_EVIDENCE"},
        "KNOWLEDGE_RETRIEVAL": {"HYPOTHESIS_GENERATION", "BLOCKED"},
        "HYPOTHESIS_GENERATION": {"EVIDENCE_ASSESSMENT", "BLOCKED"},
        "EVIDENCE_ASSESSMENT": {"INVESTIGATING", "DIAGNOSIS_READY", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"},
        "CONFLICTING_EVIDENCE": {"INVESTIGATING", "ESCALATED"},
        "DIAGNOSIS_READY": {"RECOMMENDATION_READY", "ENRICHING", "COMPLETED"},
        "ENRICHING": {"RECOMMENDATION_READY", "COMPLETED"},
        "RECOMMENDATION_READY": {"COMPLETED"},
        "INSUFFICIENT_EVIDENCE": {"COMPLETED"},
        "BLOCKED": {"COMPLETED"},
        "ESCALATED": {"COMPLETED"},
    }
    current = state.get("status", "NEW")
    if target == current or target in allowed.get(current, set()):
        state["status"] = target
    else:
        state.setdefault("conflicts", []).append({"type": "INVALID_TRANSITION", "from": current, "to": target})
        state["status"] = "BLOCKED"
    return state


def resolve_context(state: AgentState) -> AgentState:
    _transition(state, "CONTEXT_LOADING")
    incident = state["incident"]
    runtime: ToolRuntime = state["runtime"]["tool_runtime"]
    result = runtime.call("get_migration_context", {
        "migration_id": incident.get("migration_id"),
        "vm_id": incident.get("vm_id"),
    }, correlation={
        "migration_id": str(incident.get("migration_id", "")),
        "cluster_id": str(incident.get("cluster_id", "")),
    })
    state.setdefault("tool_history", []).append(_tool_audit(result))
    state.setdefault("evidence", []).extend([e for e in result.evidence])
    if result.status == "SUCCESS":
        state["context"] = result.evidence[0].get("context", {}) if result.evidence else dict(incident)
        # Scenario handlers may return a context payload as a synthetic fact.
        if result.evidence:
            state["context"] = result.evidence[0].get("context", state["context"])
        _transition(state, "CLASSIFYING")
    else:
        state["context"] = dict(incident)
        _transition(state, "BLOCKED")
        state.setdefault("missing_evidence", []).append("migration_context")
    return state


def classify_issue(state: AgentState) -> AgentState:
    state["issue"] = classify(state["incident"], state.get("context", {}))
    _transition(state, "INVESTIGATING")
    return state


def _planned_tools(issue_tag: str, iteration: int) -> list[str]:
    policy = INVESTIGATION_POLICIES.get(issue_tag)
    if not policy:
        return list(DEFAULT_REQUIRED)
    required = list(policy["required"])
    optional = list(policy.get("optional", []))
    if iteration <= 1:
        return required
    return required + optional[: max(0, iteration - 1)]


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for e in items:
        key = (
            e.get("source_tool"),
            e.get("claim"),
            e.get("observed_at"),
            tuple(sorted((e.get("correlation") or {}).items())),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def investigate(state: AgentState) -> AgentState:
    issue_tag = state["issue"].get("issue_tag", "UNKNOWN")
    runtime: ToolRuntime = state["runtime"]["tool_runtime"]
    iteration = state.get("investigation_iteration", 0) + 1
    planned = _planned_tools(issue_tag, iteration)
    already = {x.get("tool_name") for x in state.get("tool_history", [])}
    budget = state.setdefault("budget", {})

    for tool_name in planned:
        if tool_name in already:
            continue
        if int(budget.get("tool_calls", 0)) <= 0:
            state.setdefault("missing_evidence", []).append("tool_budget_exhausted")
            break
        result = runtime.call(tool_name, _tool_args(tool_name, state), correlation=_correlation(state))
        budget["tool_calls"] = int(budget.get("tool_calls", 0)) - 1
        state.setdefault("tool_history", []).append(_tool_audit(result))
        state.setdefault("evidence", []).extend([_as_dict(e) for e in result.evidence])
        if result.status in {"ERROR", "TIMEOUT", "NO_DATA"}:
            state.setdefault("missing_evidence", []).append(tool_name)

    state["evidence"] = _dedupe_evidence(state.get("evidence", []))
    state["investigation_iteration"] = iteration
    _transition(state, "KNOWLEDGE_RETRIEVAL")
    return state


def retrieve_knowledge(state: AgentState) -> AgentState:
    runtime: ToolRuntime = state["runtime"]["tool_runtime"]
    signature = build_signature(state["issue"], state.get("context", {}), state.get("evidence", []))
    budget = state.setdefault("budget", {})
    if int(budget.get("knowledge_calls", 0)) < 2:
        state.setdefault("missing_evidence", []).append("knowledge_budget_exhausted")
        _transition(state, "HYPOTHESIS_GENERATION")
        return state

    rhokp_result = runtime.call("search_rhokp", {"signature": signature}, correlation=_correlation(state))
    budget["knowledge_calls"] = int(budget.get("knowledge_calls", 0)) - 1
    sre_result = runtime.call("search_sre_tracker", {"signature": signature}, correlation=_correlation(state))
    budget["knowledge_calls"] = int(budget.get("knowledge_calls", 0)) - 1

    state.setdefault("tool_history", []).extend([_tool_audit(rhokp_result), _tool_audit(sre_result)])
    state["rhokp"] = normalize_rhokp(_raw_knowledge(rhokp_result))
    state["sre_tracker"] = normalize_sre_tracker(_raw_knowledge(sre_result))
    _transition(state, "HYPOTHESIS_GENERATION")
    return state


def generate_hypotheses(state: AgentState) -> AgentState:
    tag = state["issue"]["issue_tag"]
    generator = state.get("runtime", {}).get("hypothesis_generator")
    if generator and int(state.get("budget", {}).get("llm_calls", 0)) > 0:
        state["budget"]["llm_calls"] = int(state.get("budget", {}).get("llm_calls", 0)) - 1
        try:
            model_candidates = generator(state) or []
        except Exception as exc:  # noqa: BLE001
            model_candidates = []
            state.setdefault("tool_history", []).append({
                "tool_name": "llm_hypothesis_generator",
                "status": "ERROR",
                "error": str(exc),
            })
        if model_candidates:
            state["hypotheses"] = [
                {
                    "hypothesis_id": str(uuid.uuid4()),
                    "statement": str(item["statement"]),
                    "category": state["issue"].get("category", "UNKNOWN"),
                    "issue_tag": str(item["issue_tag"]),
                    "expected_fact_codes": list(item.get("expected_fact_codes", [])),
                    "contradicting_fact_codes": list(item.get("contradicting_fact_codes", [])),
                    "required_fact_codes": list(item.get("required_fact_codes", [])),
                }
                for item in model_candidates
                if item.get("issue_tag") in {tag, state["issue"].get("issue_tag")}
            ][:8]
            if state["hypotheses"]:
                _transition(state, "EVIDENCE_ASSESSMENT")
                return state
    seeds = {
        "STORAGE.CSI.PROVISIONING_TIMEOUT": [
            ("CSI provisioning failure", ["CSI_PROVISIONING_TIMEOUT", "PVC_PENDING"], ["STORAGE_BACKEND_HEALTHY"]),
            ("Storage backend availability/capacity issue", ["BACKEND_PROVISIONING_FAILURE"], ["BACKEND_HEALTHY"]),
        ],
        "VMWARE.CBT": [
            ("VMware CBT/snapshot failure", ["CBT_SNAPSHOT_FAILURE", "WARM_IMPORT_RETRY_EXHAUSTED"], ["CBT_HEALTHY"]),
            ("vCenter connectivity/control-plane issue", ["VCENTER_EVENT_FAILURE", "VCENTER_CONNECTIVITY_FAILURE"], ["VCENTER_HEALTHY"]),
        ],
        "NETWORK.NAD.MISSING": [
            ("Target NAD is missing or unusable", ["NAD_MISSING", "NETWORK_ATTACHMENT_FAILURE"], ["NAD_VALID"]),
            ("NetworkMap points to an invalid target", ["NETWORKMAP_INVALID"], ["NETWORKMAP_VALID"]),
        ],
        "MTV.MIGRATION_TIMEOUT": [
            ("Migration data path stalled", ["TRANSFER_STALLED", "THROUGHPUT_DEGRADED"], ["TRANSFER_PROGRESSING"]),
            ("Cluster-wide capacity/resource contention", ["RESOURCE_PRESSURE", "SCHEDULING_DELAY"], ["CLUSTER_HEALTHY"]),
        ],
    }
    candidates = list(seeds.get(tag, [(f"{tag} failure", [tag], [])]))
    for row in state.get("rhokp", []):
        if row.get("issue_tag") == tag:
            candidates.extend((str(c), [], []) for c in row.get("possible_causes", []))
    for row in state.get("sre_tracker", []):
        if row.get("issue_tag") == tag and row.get("observed_cause"):
            candidates.append((str(row["observed_cause"]), [], []))

    unique = []
    seen = set()
    for statement, expected, contradicting in candidates:
        key = statement.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((statement, expected, contradicting))

    state["hypotheses"] = [
        {
            "hypothesis_id": str(uuid.uuid4()),
            "statement": statement,
            "category": state["issue"].get("category", "UNKNOWN"),
            "issue_tag": tag,
            "expected_fact_codes": expected,
            "contradicting_fact_codes": contradicting,
            "required_fact_codes": expected[:1],
        }
        for statement, expected, contradicting in unique[:8]
    ]
    _transition(state, "EVIDENCE_ASSESSMENT")
    return state


def evaluate(state: AgentState) -> AgentState:
    evaluated, assessment = evaluate_all(
        state.get("hypotheses", []),
        state.get("evidence", []),
        state.get("rhokp", []),
        state.get("sre_tracker", []),
    )
    state["hypotheses"] = evaluated
    state["conflicts"] = assessment["conflicts"]
    state["missing_evidence"].extend(assessment["missing"])
    state["missing_evidence"] = list(dict.fromkeys(state.get("missing_evidence", [])))
    state["investigation_plan"] = next_best_investigation(
        state.get("issue", {}).get("issue_tag", "UNKNOWN"),
        state.get("tool_history", []),
        state.get("missing_evidence", []),
        state.get("conflicts", []),
    )
    top = assessment["top"]
    if assessment["status"] == "DIAGNOSIS_READY" and top:
        state["diagnosis"] = {
            "diagnosis_type": "LIKELY_ROOT_CAUSE",
            "root_cause": top["statement"],
            "confidence": top["confidence"],
            "confidence_band": top["confidence_band"],
            "hypothesis_id": top["hypothesis_id"],
            "issue_tag": top["issue_tag"],
            "supporting_evidence": top["supporting_evidence"],
            "contradicting_evidence": top["contradicting_evidence"],
            "rhokp_refs": top["rhokp_refs"],
            "sre_tracker_refs": top["sre_tracker_refs"],
        }
        _transition(state, "DIAGNOSIS_READY")
    else:
        if assessment["status"] == "CONFLICTING_EVIDENCE":
            _transition(state, "CONFLICTING_EVIDENCE")
        else:
            _transition(state, "INSUFFICIENT_EVIDENCE")
    return state


def resolve_conflict_or_stop(state: AgentState) -> AgentState:
    if not state.get("conflicts"):
        return state
    # Bounded retry: gather one additional optional signal. Repeated cycles are
    # stopped deterministically by the budget/iteration gate.
    if state.get("investigation_iteration", 0) >= 2:
        _transition(state, "ESCALATED")
    else:
        _transition(state, "INVESTIGATING")
    return state


def build_diagnosis(state: AgentState) -> AgentState:
    return state



def build_migration_scope_node(state: AgentState) -> AgentState:
    """Resolve the current change/wave scope through an injected real adapter.

    No adapter means UNKNOWN. The agent never fabricates active migrations.
    If migration context already contains an authoritative migration_scope, it
    is used directly. Otherwise an explicitly registered runtime capability
    named ``get_active_migration_scope`` may supply it.
    """
    context = state.get("context", {})
    supplied = context.get("migration_scope")
    if supplied is not None:
        state["migration_scope"] = normalize_scope(supplied)
        return state

    runtime: ToolRuntime = state["runtime"]["tool_runtime"]
    if "get_active_migration_scope" not in runtime.handlers:
        state["migration_scope"] = {
            "status": "UNKNOWN",
            "reason": "No active-migration scope adapter is registered.",
        }
        return state

    incident = state["incident"]
    result = runtime.call("get_active_migration_scope", {
        "change_id": incident.get("change_id") or context.get("change_id"),
        "wave_id": incident.get("wave_id") or context.get("wave_id"),
        "migration_id": incident.get("migration_id"),
    }, correlation=_correlation(state))
    state.setdefault("tool_history", []).append(_tool_audit(result))
    if result.status != "SUCCESS":
        state["migration_scope"] = {
            "status": "UNKNOWN",
            "reason": result.error or f"Scope provider returned {result.status}.",
        }
        return state

    raw = result.facts[0].get("value") if result.facts else None
    state["migration_scope"] = normalize_scope(raw)
    return state


def build_migration_forecast_node(state: AgentState) -> AgentState:
    state["maintenance_window"] = build_maintenance_window(state)
    state["migration_forecast"] = calculate_forecast(
        state.get("migration_scope", {"status": "UNKNOWN"}),
        state,
    )
    return state

def build_timeline_node(state: AgentState) -> AgentState:
    state["timeline"] = build_timeline(state.get("evidence", []))
    return state


def build_impact_node(state: AgentState) -> AgentState:
    state["impact"] = build_impact(state)
    return state


def build_retry_readiness_node(state: AgentState) -> AgentState:
    state["retry_readiness"] = evaluate_retry_readiness(
        state.get("issue", {}).get("issue_tag", "UNKNOWN"),
        state.get("evidence", []),
    )
    return state


def build_ownership(state: AgentState) -> AgentState:
    # Canonical routing is evidence-driven and deterministic. Historical SRE
    # Tracker ownership is context, never the authority for current ownership.
    from migration_failure_agent_routing import classify_owning_team

    diagnosis = state.get("diagnosis") or {}
    if diagnosis:
        primary, notify_teams, rationale = classify_owning_team(diagnosis, state.get("evidence", []))
    else:
        primary = "sre_day2"
        notify_teams = ["sre_day2"]
        rationale = "No diagnosis is available; SRE remains the default investigation owner."

    state["ownership"] = {
        "primary": primary,
        "notify_teams": notify_teams,
        "confidence": 0.75 if diagnosis else 0.40,
        "basis": ["canonical evidence-layer routing"],
        "routing_rationale": rationale,
    }
    return state


def build_recommendation_node(state: AgentState) -> AgentState:
    if not state.get("diagnosis"):
        return state
    state["recommendation"] = build_recommendation(
        state["diagnosis"],
        ownership=state.get("ownership"),
        retry_readiness=state.get("retry_readiness"),
        missing_evidence=state.get("missing_evidence", []),
        conflicts=state.get("conflicts", []),
        evidence=state.get("evidence", []),
        state=state,
    )
    state["recovery_forecasts"] = build_recovery_forecasts(
        state.get("migration_scope", {"status": "UNKNOWN"}),
        state.get("migration_forecast", {"status": "UNKNOWN"}),
        str(state.get("incident", {}).get("migration_id")) if state.get("incident", {}).get("migration_id") else None,
        state["recommendation"].get("recovery_options", []),
    )
    state["recommendation"]["migration_forecast"] = state.get("migration_forecast")
    state["recommendation"]["recovery_forecasts"] = state.get("recovery_forecasts", [])
    _transition(state, "RECOMMENDATION_READY")
    _transition(state, "COMPLETED")
    return state


def _tool_args(tool_name: str, state: AgentState) -> dict[str, Any]:
    incident = state["incident"]
    context = state.get("context", {})
    args = {
        "migration_id": incident.get("migration_id"),
        "vm_id": incident.get("vm_id"),
        "cluster_id": incident.get("cluster_id"),
        "namespace": incident.get("namespace") or context.get("namespace"),
        "pvc_id": context.get("pvc_id"),
        "dv_id": context.get("datavolume_id"),
        "storageclass_id": context.get("storageclass"),
        "volumeattachment_id": context.get("volumeattachment_id"),
        "nad_id": context.get("nad_id"),
        "migration_uid": context.get("migration_uid") or incident.get("migration_id"),
        "time_range": context.get("time_range") or {"start": incident.get("failed_at"), "end": incident.get("failed_at")},
    }
    if tool_name in {"get_migration_context", "get_migration_metrics", "search_splunk_for_migration"}:
        return {k: v for k, v in args.items() if k in {"migration_id", "time_range", "vm_id"} and v}
    if tool_name == "get_datavolume":
        return {"dv_id": args.get("dv_id")}
    if tool_name == "get_pvc":
        return {"pvc_id": args.get("pvc_id")}
    if tool_name == "get_storageclass":
        return {"storageclass_id": args.get("storageclass_id")}
    if tool_name == "get_volumeattachment":
        return {"volumeattachment_id": args.get("volumeattachment_id")}
    if tool_name == "get_csi_logs":
        return {"driver": context.get("csi_driver"), "time_range": args["time_range"]}
    if tool_name == "get_storage_backend_status":
        return {"backend": context.get("storage_backend")}
    if tool_name == "get_vcenter_events":
        return {"vm_id": args.get("vm_id"), "time_range": args["time_range"]}
    if tool_name == "get_source_vm_state":
        return {"vm_id": args.get("vm_id")}
    if tool_name == "get_networkmap":
        return {"migration_id": args.get("migration_id")}
    if tool_name == "get_nad":
        return {"nad_id": args.get("nad_id")}
    if tool_name in {"get_multus_status", "get_ovn_status"}:
        return {"cluster_id": args.get("cluster_id")}
    if tool_name == "get_cluster_health":
        return {}
    if tool_name == "get_recent_cluster_changes":
        return {"time_range": args["time_range"]}
    if tool_name == "get_vmware_task_history":
        return {"vm_id": args.get("vm_id"), "time_range": args["time_range"]}
    return {k: v for k, v in args.items() if v is not None}


def _correlation(state: AgentState) -> dict[str, str]:
    incident = state["incident"]
    context = state.get("context", {})
    pairs = {
        "migration_id": incident.get("migration_id"),
        "migration_uid": context.get("migration_uid"),
        "vm_uid": context.get("vm_uid"),
        "pvc_uid": context.get("pvc_uid"),
        "cluster_id": incident.get("cluster_id") or context.get("cluster_id"),
    }
    return {k: str(v) for k, v in pairs.items() if v}


def _as_dict(e: Any) -> dict[str, Any]:
    if hasattr(e, "__dict__"):
        return dict(e.__dict__)
    return dict(e)


def _raw_knowledge(result: Any) -> list[dict[str, Any]]:
    # Knowledge test backends return raw rows via facts; production handlers can
    # populate the same field directly.
    return [f.get("value", f) if isinstance(f, dict) else f for f in getattr(result, "facts", [])]


def _tool_audit(result: Any) -> dict[str, Any]:
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "observed_at": result.observed_at,
        "retrieved_at": result.retrieved_at,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }

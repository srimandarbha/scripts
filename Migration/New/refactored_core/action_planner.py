from __future__ import annotations

from typing import Any

from .policies import RETRY_CHECKS


def _facts(evidence: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for item in evidence:
        if item.get("status") in (None, "SUCCESS"):
            out.update(item.get("fact_codes", []))
    return out


def evaluate_retry_readiness(issue_tag: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    checks = RETRY_CHECKS.get(issue_tag)
    if not checks:
        return {"status": "UNKNOWN", "checks": [], "blockers": ["No deterministic retry-readiness policy exists for this issue tag."]}

    facts = _facts(evidence)
    results = []
    blockers = []
    unknown = []
    for code, description, healthy_codes, bad_codes in checks:
        if facts.intersection(bad_codes):
            results.append({"check": code, "description": description, "status": "FAIL"})
            blockers.append(description)
        elif facts.intersection(healthy_codes):
            results.append({"check": code, "description": description, "status": "PASS"})
        else:
            results.append({"check": code, "description": description, "status": "UNKNOWN"})
            unknown.append(description)

    status = "NOT_READY" if blockers else "UNKNOWN" if unknown else "READY"
    return {"status": status, "checks": results, "blockers": blockers}


def build_timeline(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in evidence:
        rows.append({
            "timestamp": item.get("observed_at"),
            "event": item.get("claim", ""),
            "source": item.get("source_tool"),
            "evidence_ref": item.get("evidence_id"),
            "fact_codes": item.get("fact_codes", []),
        })
    return sorted(rows, key=lambda x: str(x.get("timestamp") or ""))


def build_impact(state: dict[str, Any]) -> dict[str, Any]:
    incident = state.get("incident", {})
    context = state.get("context", {})
    issue = state.get("issue", {})
    # The runtime may provide a current-failure correlator. Absence of that
    # capability is explicitly represented as UNKNOWN, never inferred as 1.
    correlated = context.get("similar_active_failures")
    if isinstance(correlated, list):
        count = len(correlated)
        scope = "SYSTEMIC" if count >= 3 else "LOCAL"
    else:
        count = None
        scope = "UNKNOWN"
    return {
        "scope": scope,
        "similar_active_failures": count,
        "common_factors": {
            "cluster_id": incident.get("cluster_id") or context.get("cluster_id"),
            "issue_tag": issue.get("issue_tag"),
            "storage_backend": context.get("storage_backend"),
        },
        "affected_migrations": correlated if isinstance(correlated, list) else [],
    }


def next_best_investigation(issue_tag: str, tool_history: list[dict[str, Any]], missing_evidence: list[str], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    from .policies import INVESTIGATION_POLICIES
    policy = INVESTIGATION_POLICIES.get(issue_tag, {})
    used = {x.get("tool_name") for x in tool_history}
    candidates = [x for x in policy.get("optional", []) if x not in used]
    if conflicts:
        objective = "Collect discriminating evidence between the competing hypotheses."
    elif missing_evidence:
        objective = "Collect the missing evidence before selecting a remediation path."
    else:
        objective = "Collect the highest-value optional signal before retrying when practical."
    return {
        "objective": objective,
        "priority": [
            {"tool": tool, "reason": "Policy-defined optional signal not yet collected."}
            for tool in candidates[:3]
        ],
        "stop_conditions": [
            "hypothesis_confirmed",
            "hypothesis_rejected",
            "evidence_budget_exhausted",
        ],
    }


def _parse_time(value: Any):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def build_maintenance_window(state: dict[str, Any]) -> dict[str, Any]:
    """Normalize maintenance-window information without guessing missing times."""
    incident = state.get("incident", {})
    context = state.get("context", {})
    source = {}
    source.update(context.get("maintenance_window") or {})
    source.update(incident.get("maintenance_window") or {})
    start = _parse_time(source.get("start"))
    end = _parse_time(source.get("end"))
    current = _parse_time(source.get("current_time"))
    if current is None:
        current = _parse_time(incident.get("current_time"))

    remaining = None
    if end and current:
        remaining = max(0, int((end - current).total_seconds() // 60))
    elif source.get("remaining_minutes") is not None:
        try:
            remaining = max(0, int(source["remaining_minutes"]))
        except (TypeError, ValueError):
            remaining = None

    return {
        "start": source.get("start"),
        "end": source.get("end"),
        "current_time": source.get("current_time") or incident.get("current_time"),
        "remaining_minutes": remaining,
        "buffer_minutes": source.get("buffer_minutes", 0),
        "status": "KNOWN" if remaining is not None else "UNKNOWN",
    }


def build_recovery_options(
    issue_tag: str,
    diagnosis: dict[str, Any],
    evidence: list[dict[str, Any]],
    retry_readiness: dict[str, Any],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build safe, non-executing recovery choices from declarative policy."""
    from .policies import RECOVERY_POLICIES

    policy = RECOVERY_POLICIES.get(issue_tag, {})
    window = build_maintenance_window(state)
    remaining = window.get("remaining_minutes")
    evidence_refs = diagnosis.get("supporting_evidence", [])
    options: list[dict[str, Any]] = []

    # Optional historical duration estimates can come from the portal/SRE Tracker.
    duration_map = state.get("context", {}).get("estimated_recovery_minutes", {}) or {}
    for index, template in enumerate(policy.get("options", []), 1):
        option_type = template["type"]
        status = "POSSIBLE"
        blockers: list[str] = []

        if option_type == "RETRY":
            if retry_readiness.get("status") == "READY":
                status = "READY"
            else:
                status = "NOT_READY"
                blockers.extend(retry_readiness.get("blockers", []))
                if retry_readiness.get("status") == "UNKNOWN":
                    blockers.append("Retry-readiness checks are not fully known.")

        if remaining is None:
            time_feasibility = "UNKNOWN"
        else:
            estimate = duration_map.get(option_type)
            try:
                estimate = int(estimate) if estimate is not None else None
            except (TypeError, ValueError):
                estimate = None
            if estimate is None:
                time_feasibility = "UNKNOWN"
            else:
                time_feasibility = "TIME_FEASIBLE" if estimate + int(window.get("buffer_minutes") or 0) <= remaining else "TIME_CONSTRAINED"
                if time_feasibility == "TIME_CONSTRAINED":
                    blockers.append(f"Estimated {option_type} duration ({estimate}m) exceeds available maintenance-window time after buffer.")

        rationale = [template.get("summary", "")] + [
            f"Diagnosis confidence: {diagnosis.get('confidence', 0.0):.2f}."
        ]
        # Historical SRE Tracker data can enrich a proposed fix-forward path,
        # but never changes live diagnosis or authorizes execution.
        historical = []
        for row in state.get("sre_tracker", []):
            if row.get("issue_tag") == issue_tag and (row.get("resolution") or row.get("successful_workaround")):
                historical.append(row)
        if historical and option_type == "FIX_FORWARD":
            best = historical[0]
            prior = best.get("successful_workaround") or best.get("resolution")
            rationale.append(f"SRE Tracker historical precedent: {prior}")
            if best.get("preconditions"):
                options_preconditions = list(template.get("preconditions", []))
                for condition in best.get("preconditions", []):
                    if condition not in options_preconditions:
                        options_preconditions.append(condition)
            else:
                options_preconditions = list(template.get("preconditions", []))
        else:
            options_preconditions = list(template.get("preconditions", []))
        if option_type == "RETRY" and retry_readiness.get("status") != "READY":
            rationale.append("Retry is gated by deterministic readiness checks.")
        if remaining is not None:
            rationale.append(f"Maintenance window remaining: {remaining} minutes.")

        options.append({
            "option_id": f"R{index}",
            "option_type": option_type,
            "summary": template.get("summary", ""),
            "status": "NOT_FEASIBLE" if blockers and time_feasibility == "TIME_CONSTRAINED" else status,
            "risk": template.get("risk", "UNKNOWN"),
            "rationale": rationale,
            "evidence_refs": evidence_refs,
            "preconditions": options_preconditions,
            "proposed_changes": template.get("changes", []),
            "validation": template.get("validation", []),
            "rollback_steps": template.get("rollback", []),
            "estimated_minutes": duration_map.get(option_type),
            "time_feasibility": time_feasibility,
            "blockers": list(dict.fromkeys(blockers)),
            "human_approval_required": True,
            "execution": "NOT_EXECUTED",
        })
    return options

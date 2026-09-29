from __future__ import annotations

from typing import Any

from .models import ActionStep
from .policies import RECOMMENDATION_POLICIES
from .action_planner import build_maintenance_window, build_recovery_options


def build_recommendation(
    diagnosis: dict[str, Any],
    ownership: dict[str, Any] | None = None,
    retry_readiness: dict[str, Any] | None = None,
    missing_evidence: list[str] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_tag = diagnosis.get("issue_tag")
    policy = RECOMMENDATION_POLICIES.get(issue_tag, {})
    missing = list(dict.fromkeys(missing_evidence or []))
    conflict_items = conflicts or []
    effective_state = state or {}
    effective_evidence = evidence or []
    maintenance_window = build_maintenance_window(effective_state)
    recovery_options = build_recovery_options(
        issue_tag or "UNKNOWN", diagnosis, effective_evidence, retry_readiness or {}, effective_state
    )

    steps = []
    for idx, item in enumerate(policy.get("steps", []), 1):
        if isinstance(item, dict):
            steps.append(item)
        else:
            steps.append({
                "order": idx,
                "action": item,
                "reason": "Policy-defined investigation/remediation step.",
                "evidence_refs": diagnosis.get("supporting_evidence", []),
                "blocking": False,
            })

    if missing:
        steps.insert(0, {
            "order": 1,
            "action": "Collect the missing evidence before selecting a retry, rollback, or fix-forward path.",
            "reason": "The current evidence is insufficient for a safe operational decision.",
            "evidence_refs": [],
            "blocking": True,
        })
        for i, step in enumerate(steps, 1):
            step["order"] = i

    do_not_do = list(policy.get("do_not_do", []))
    if retry_readiness and retry_readiness.get("status") == "NOT_READY":
        do_not_do.append("Do not retry while a retry-readiness blocker remains active.")
    do_not_do = list(dict.fromkeys(do_not_do))

    if conflict_items:
        action_type = "ESCALATE"
        summary = "Competing hypotheses remain; perform the discriminating checks before retrying or applying a fix."
        escalation_reason = "; ".join(c.get("summary", "Conflicting evidence") for c in conflict_items)
    elif retry_readiness and retry_readiness.get("status") == "NOT_READY":
        action_type = "INVESTIGATE"
        summary = "The failure is understood enough to direct investigation, but retry is blocked until the listed conditions are resolved."
        escalation_reason = None
    elif missing:
        action_type = "INVESTIGATE"
        summary = "Collect the missing current evidence before selecting a remediation path."
        escalation_reason = None
    else:
        action_type = policy.get("action_type", "INVESTIGATE")
        summary = policy.get("summary", "Follow the evidence-backed investigation steps and obtain human approval before action.")
        escalation_reason = None

    return {
        "next_action_type": action_type,
        "summary": summary,
        "steps": steps,
        "do_not_do": do_not_do,
        "owner": (ownership or {}).get("primary"),
        "owner_confidence": (ownership or {}).get("confidence", 0.0),
        "escalation_reason": escalation_reason,
        "retry_readiness": retry_readiness,
        "recovery_options": recovery_options,
        "maintenance_window": maintenance_window,
        "evidence_refs": diagnosis.get("supporting_evidence", []),
        "missing_evidence": missing,
        "human_review_required": True,
    }

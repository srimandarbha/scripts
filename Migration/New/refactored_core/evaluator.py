from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


LIVE_TIERS = {"LIVE_TELEMETRY", "CURRENT_HEALTH_API", "LOGS"}
HISTORICAL_TIERS = {"CONFIRMED_FIX", "VENDOR_ADVISORY", "HISTORICAL_RAG"}

# These are intentionally modest defaults. They are configuration, not a claim of
# calibrated probability. Production should recalibrate them against labelled cases.
WEIGHTS = {
    "LIVE_TELEMETRY": 0.34,
    "CURRENT_HEALTH_API": 0.25,
    "LOGS": 0.20,
    "CONFIRMED_FIX": 0.08,
    "VENDOR_ADVISORY": 0.05,
    "HISTORICAL_RAG": 0.04,
}


def _freshness_bonus(observed_at: str) -> float:
    try:
        dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return 0.0
    if age <= 120:
        return 0.05
    if age <= 900:
        return 0.03
    return 0.0


def _fact_codes(evidence: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for e in evidence:
        out.update(e.get("fact_codes", []))
    return out


def _supports(h: dict[str, Any], e: dict[str, Any]) -> bool:
    expected = set(h.get("expected_fact_codes", []))
    if expected and expected.intersection(e.get("fact_codes", [])):
        return True

    statement = h.get("statement", "").lower()
    claim = e.get("claim", "").lower()
    tokens = [t for t in statement.replace("/", " ").replace("-", " ").split() if len(t) > 4]
    return sum(1 for t in tokens if t in claim) >= 2


def _contradicts(h: dict[str, Any], e: dict[str, Any]) -> bool:
    contradictory_codes = set(h.get("contradicting_fact_codes", []))
    return bool(contradictory_codes.intersection(e.get("fact_codes", [])))


def evaluate_hypothesis(h: dict[str, Any], evidence: list[dict[str, Any]], rhokp: list[dict[str, Any]], sre: list[dict[str, Any]]) -> dict[str, Any]:
    supporting: list[str] = []
    contradicting: list[str] = []

    for e in evidence:
        if e.get("status") not in (None, "SUCCESS"):
            continue
        if _supports(h, e):
            supporting.append(e["evidence_id"])
        if _contradicts(h, e):
            contradicting.append(e["evidence_id"])

    live_supporting = [
        e for e in evidence
        if e.get("evidence_id") in supporting and e.get("reliability_tier") in LIVE_TIERS
    ]
    independent_live_tools = {e.get("source_tool") for e in live_supporting}

    rhokp_refs = [x.get("ref") or x.get("document_id") or x.get("knowledge_id") for x in rhokp if x]
    sre_refs = [x.get("case_id") or x.get("incident_id") or x.get("fix_id") for x in sre if x]

    # Historical/product knowledge is intentionally a bounded contribution.
    # It can reinforce a current diagnosis, but it cannot create one.
    historical_score = min(
        1.0,
        0.15 * len([r for r in sre_refs if r])
        + 0.10 * len([r for r in rhokp_refs if r]),
    )

    # Score supporting evidence per independent observing tool rather than by
    # reliability tier alone. Two independent live observations are materially
    # stronger than one live observation repeated twice.
    score = 0.0
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in live_supporting:
        by_tool[str(e.get("source_tool"))].append(e)

    live_tool_scores = [0.30, 0.22, 0.15]
    for idx, (_tool, tool_evidence) in enumerate(sorted(by_tool.items())):
        score += live_tool_scores[min(idx, len(live_tool_scores) - 1)]
        score += min(0.05, max(_freshness_bonus(x.get("observed_at", "")) for x in tool_evidence))

    # Non-live current health/log evidence may still add support when present.
    for e in evidence:
        if e.get("evidence_id") in supporting and e.get("reliability_tier") not in LIVE_TIERS:
            score += {"CONFIRMED_FIX": 0.08, "VENDOR_ADVISORY": 0.05, "HISTORICAL_RAG": 0.04}.get(e.get("reliability_tier"), 0.0)

    if len(independent_live_tools) >= 2:
        score += 0.10
    if len(independent_live_tools) >= 3:
        score += 0.05
    if historical_score:
        score += min(0.10, historical_score * 0.20)

    score -= min(0.45, 0.30 * len(set(contradicting)))
    score = max(0.0, min(1.0, score))

    if not live_supporting:
        # RHoKP/SRE Tracker can create a plausible lead but never a confirmed
        # diagnosis without current evidence.
        score = min(score, 0.39)
        status = "UNTESTED" if not supporting else "SUPPORTED"
    elif contradicting:
        status = "REJECTED" if score < 0.45 else "SUPPORTED"
    elif len(independent_live_tools) >= 2 and score >= 0.68:
        status = "CONFIRMED"
    elif score >= 0.45:
        status = "SUPPORTED"
    else:
        status = "UNTESTED"

    band = "HIGH" if score >= 0.75 and status == "CONFIRMED" else "MEDIUM" if score >= 0.45 else "LOW"

    return {
        **h,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "rhokp_refs": [r for r in rhokp_refs if r],
        "sre_tracker_refs": [r for r in sre_refs if r],
        "technical_match_score": round(score, 4),
        "historical_match_score": round(historical_score, 4),
        "confidence": round(score, 4),
        "confidence_band": band,
        "status": status,
    }


def evaluate_all(hypotheses: list[dict[str, Any]], evidence: list[dict[str, Any]], rhokp: list[dict[str, Any]], sre: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evaluated = [evaluate_hypothesis(h, evidence, rhokp, sre) for h in hypotheses]
    ranked = sorted(evaluated, key=lambda x: x["confidence"], reverse=True)

    confirmed = [h for h in ranked if h["status"] == "CONFIRMED"]
    supported = [h for h in ranked if h["status"] == "SUPPORTED"]

    conflicts = []
    eligible = [h for h in ranked if h["status"] in {"CONFIRMED", "SUPPORTED"}]
    if len(eligible) >= 2:
        leader = eligible[0]
        tied = [h for h in eligible if abs(leader["confidence"] - h["confidence"]) < 0.08]
        if len(tied) >= 2:
            ids = [h["hypothesis_id"] for h in tied]
            conflicts.append({
                "hypothesis_ids": ids,
                "hypothesis_a": ids[0],
                "hypothesis_b": ids[1],
                "summary": f"{len(tied)} hypotheses have materially similar evidence support; additional discriminating evidence is required.",
            })

    if confirmed:
        top = confirmed[0]
        status = "DIAGNOSIS_READY" if not conflicts else "CONFLICTING_EVIDENCE"
    elif supported:
        top = supported[0]
        status = "DIAGNOSIS_READY" if top["confidence"] >= 0.55 and not conflicts else "INSUFFICIENT_EVIDENCE"
    else:
        top = None
        status = "INSUFFICIENT_EVIDENCE"

    missing = []
    if top:
        required = set(top.get("required_fact_codes", []))
        present = _fact_codes([e for e in evidence if e.get("status") in (None, "SUCCESS")])
        missing = sorted(required - present)
        if missing and status == "DIAGNOSIS_READY":
            status = "INSUFFICIENT_EVIDENCE"

    return evaluated, {"status": status, "top": top, "conflicts": conflicts, "missing": missing}

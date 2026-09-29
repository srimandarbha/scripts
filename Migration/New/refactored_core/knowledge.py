from __future__ import annotations

from typing import Any


def build_signature(issue: dict[str, Any], context: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "issue_tag": issue.get("issue_tag"),
        "category": issue.get("category"),
        "phase": issue.get("phase"),
        "mtv_version": context.get("mtv_version"),
        "ocv_version": context.get("ocv_version"),
        "storage_backend": context.get("storage_backend"),
        "vm_os": context.get("vm_os"),
        "error_codes": sorted({c for e in evidence for c in e.get("fact_codes", [])}),
        "error_text": context.get("error_signature") or context.get("error_code"),
    }


def normalize_rhokp(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "knowledge_id": r.get("knowledge_id") or r.get("ref") or r.get("document_id"),
            "ref": r.get("ref") or r.get("document_id") or r.get("knowledge_id"),
            "issue_tag": r.get("issue_tag"),
            "meaning": r.get("meaning") or r.get("summary") or r.get("text"),
            "possible_causes": list(r.get("possible_causes", [])),
            "recommended_checks": list(r.get("recommended_checks", [])),
        }
        for r in rows
    ]


def normalize_sre_tracker(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": r.get("case_id") or r.get("incident_id") or r.get("fix_id"),
            "similarity": float(r.get("similarity", 0.0)),
            "issue_tag": r.get("issue_tag"),
            "observed_cause": r.get("observed_cause") or r.get("root_cause"),
            "resolution": r.get("resolution") or r.get("resolution_steps"),
            "owner": r.get("owner"),
            "evidence": list(r.get("evidence", [])),
            "outcome": r.get("outcome"),
        }
        for r in rows
    ]

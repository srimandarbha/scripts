from __future__ import annotations

import re
from typing import Any

from .policies import ISSUE_TAGS


PATTERNS = [
    (re.compile(r"warm import retry limit|cbt|snapshot", re.I), "VMWARE.CBT"),
    (re.compile(r"pvc.*pending|provisioning.*timeout|failed.*provision", re.I), "STORAGE.CSI.PROVISIONING_TIMEOUT"),
    (re.compile(r"network.*not found|nad.*missing|networkattachmentdefinition", re.I), "NETWORK.NAD.MISSING"),
    (re.compile(r"migration.*timeout|timed out", re.I), "MTV.MIGRATION_TIMEOUT"),
    (re.compile(r"unsupported.*device|unsupported.*disk", re.I), "VM_CONFIG.UNSUPPORTED_DEVICE"),
]


def classify(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(payload.get(k, "")) for k in ("error", "error_code", "message", "phase"))
    explicit = payload.get("issue_tag")
    if explicit in ISSUE_TAGS:
        tag = explicit
        confidence = 0.99
        reason = "explicit_issue_tag"
    else:
        tag = "UNKNOWN"
        confidence = 0.25
        reason = "no deterministic signature match"
        for pattern, candidate in PATTERNS:
            if pattern.search(text):
                tag = candidate
                confidence = 0.90
                reason = f"signature:{pattern.pattern}"
                break

    return {
        "category": ISSUE_TAGS.get(tag, "UNKNOWN"),
        "issue_tag": tag,
        "subsystem": context.get("storage_backend") or context.get("source_type"),
        "phase": context.get("phase") or payload.get("phase"),
        "classification_confidence": confidence,
        "classification_source": [reason],
    }

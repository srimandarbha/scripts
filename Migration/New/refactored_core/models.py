from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal[
    "LIVE_OBSERVATION", "PORTAL_CONTEXT", "RHOKP", "SRE_TRACKER", "LLM_INFERENCE",
]
ToolStatus = Literal["SUCCESS", "NO_DATA", "ERROR", "TIMEOUT"]
ReliabilityTier = Literal[
    "LIVE_TELEMETRY", "CURRENT_HEALTH_API", "LOGS", "CONFIRMED_FIX", "VENDOR_ADVISORY", "HISTORICAL_RAG",
]

@dataclass
class Evidence:
    evidence_id: str
    source_tool: str
    source_type: SourceType
    layer: str
    reliability_tier: ReliabilityTier
    observed_at: str
    retrieved_at: str
    claim: str
    fact_codes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    correlation: dict[str, str] = field(default_factory=dict)
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    reliability: float = 1.0

@dataclass
class ToolResult:
    tool_name: str
    status: ToolStatus
    observed_at: str
    retrieved_at: str
    source: str
    correlation: dict[str, str] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    error: str | None = None
    latency_ms: float = 0.0

@dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    category: str
    issue_tag: str
    expected_fact_codes: list[str] = field(default_factory=list)
    required_fact_codes: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    rhokp_refs: list[str] = field(default_factory=list)
    sre_tracker_refs: list[str] = field(default_factory=list)
    technical_match_score: float = 0.0
    historical_match_score: float = 0.0
    confidence: float = 0.0
    status: str = "UNTESTED"

@dataclass
class Diagnosis:
    diagnosis_type: str
    root_cause: str
    confidence: float
    confidence_band: str
    hypothesis_id: str
    issue_tag: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    competing_hypotheses: list[str] = field(default_factory=list)

@dataclass
class ActionStep:
    order: int
    action: str
    reason: str
    evidence_refs: list[str] = field(default_factory=list)
    blocking: bool = False

@dataclass
class RetryReadiness:
    status: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

@dataclass
class RecoveryOption:
    option_id: str
    option_type: str
    summary: str
    status: str
    risk: str
    rationale: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    rollback_steps: list[str] = field(default_factory=list)
    estimated_minutes: int | None = None
    time_feasibility: str = "UNKNOWN"
    human_approval_required: bool = True

@dataclass
class ActionPlan:
    next_action_type: str
    summary: str
    steps: list[ActionStep] = field(default_factory=list)
    do_not_do: list[str] = field(default_factory=list)
    owner: str | None = None
    owner_confidence: float = 0.0
    escalation_reason: str | None = None
    retry_readiness: RetryReadiness | None = None
    recovery_options: list[RecoveryOption] = field(default_factory=list)
    maintenance_window: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    human_review_required: bool = True

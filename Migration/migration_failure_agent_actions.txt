"""
Migration Failure Agent — action layer.

Two action types, deliberately treated differently:

  1. INFORMATIONAL  — "a diagnosis is ready" / "we couldn't diagnose this."
     Auto-sent. Extends notify_oncall(), already fail-soft. No new risk
     surface: it never claims to fix anything, only reports status.

  2. REMEDIATION_SUGGESTION — "here's what we think would fix it."
     Drafted, never sent by the agent. Requires explicit human approval.
     The approved send uses the exact drafted content — approval is not a
     trigger to regenerate; it's a trigger to release what was reviewed.

This is a fifth prompted role (Drafter), separate from compose_diagnosis —
see DRAFT_ACTION_PROMPT. It runs only after DIAGNOSIS_READY, and only when
recommended_action is non-trivial (not "no action needed").

Neither action type is ever bound to the LLM as a callable tool. The LLM
never has a send_email() function in its tool list — sending is a backend
action, triggered by code (auto-send) or by a human's approval click, never
by a model's own tool call. This mirrors the "LLM requests, backend
validates and executes" rule already governing remediation elsewhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal

from migration_failure_agent_production import (
    call_llm_with_schema,
    OutputValidationError,
)


# ---------------------------------------------------------------------------
# Action state — separate from the diagnosis state machine on purpose. An
# action being pending approval must never block or extend the bounded
# diagnosis run, and a completed diagnosis must never be blocked from
# COMPLETED just because a suggested action hasn't been approved yet.
# ---------------------------------------------------------------------------

ActionStatus = Literal["DRAFTED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SENT", "SEND_FAILED"]

ACTION_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DRAFTED": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"SENT", "SEND_FAILED"},
    "SEND_FAILED": {"APPROVED"},   # retry re-send, does not require re-approval of content
    "REJECTED": set(),
    "SENT": set(),
}


@dataclass
class ActionSuggestion:
    action_id: str
    incident_id: str
    action_type: Literal["REMEDIATION_SUGGESTION"]
    status: ActionStatus
    recipient: str                 # resolved deterministically, never LLM-supplied — see resolve_recipient
    subject: str
    body: str                      # exact content that will be sent; frozen once PENDING_APPROVAL
    evidence_refs: list[str]       # same citation discipline as the diagnosis itself
    created_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Recipient resolution — deterministic, never chosen by the model
# ---------------------------------------------------------------------------

def resolve_recipient(incident_id: str, purpose: Literal["informational", "remediation_suggestion"]) -> str:
    """Looks up the correct recipient from the migration portal DB / an
    on-call schedule — NEVER from anything the LLM outputs. This is the
    single most important guardrail on this whole feature: an email
    address is not evidence-derived data, and the drafting prompt is never
    given the ability to specify one. If this lookup fails, callers must
    not fall back to a default address — they should fail the action to
    SEND_FAILED and alert separately, not guess a recipient."""
    # TODO: SELECT owner_email FROM migrations WHERE migration_id = %s
    #       or an on-call-schedule lookup for `purpose == "informational"`
    ...
    return ""


# ---------------------------------------------------------------------------
# Prompt — fifth role: Drafter. Separate from compose_diagnosis's Writer
# role; drafts persuasive/actionable email content, not the diagnosis JSON.
# ---------------------------------------------------------------------------

DRAFT_ACTION_PROMPT = """You are drafting a REMEDIATION SUGGESTION email, not executing
anything. This draft will be reviewed by a human before it is ever sent —
you are proposing, not acting.

Confirmed diagnosis:
{diagnosis_summary}

Evidence backing it:
{evidence_summary}

Write a short email (subject + body) to the migration owner suggesting a
next step. Rules:
- Use advisory language only: "consider verifying...", "this may indicate...",
  "we recommend checking..." — never command language, never "I have..."
  or "this has been fixed."
- Cite the confidence band plainly (e.g. "medium confidence") so the
  recipient calibrates trust correctly.
- Do not include any claim that isn't traceable to the evidence provided.
- Do not include credentials, internal ticket contents beyond what's
  already in evidence_refs, or anything not directly about this incident.
- If recommended_action was "no action needed" or purely informational,
  output a null suggestion instead of inventing one — you are not required
  to produce an action every time.

Output strictly as JSON:
{{
  "subject": "string or null",
  "body": "string or null",
  "has_suggestion": true | false
}}"""


DRAFT_SCHEMA = {
    "type": "object",
    "required": ["has_suggestion"],
    "properties": {
        "has_suggestion": {"type": "boolean"},
        "subject": {"type": ["string", "null"]},
        "body": {"type": ["string", "null"]},
    },
}


# ---------------------------------------------------------------------------
# Drafting — runs after compose_diagnosis, outside the bounded graph loop.
# Consumes its own small LLM-call budget, separate from the diagnosis run's.
# ---------------------------------------------------------------------------

def draft_action_suggestion(incident_id: str, diagnosis: dict, evidence_summary: str) -> Optional[ActionSuggestion]:
    """Called once, right after a DIAGNOSIS_READY diagnosis is composed.
    Produces a DRAFTED ActionSuggestion if the model believes a concrete
    suggestion is warranted, else returns None. Never sends anything —
    this function has no side effects beyond persisting a draft."""
    if diagnosis.get("confidence_band") not in ("HIGH", "MEDIUM"):
        return None  # do not draft suggestions off a diagnosis that isn't itself trustworthy

    prompt = DRAFT_ACTION_PROMPT.format(
        diagnosis_summary=diagnosis.get("root_cause", ""),
        evidence_summary=evidence_summary,
    )
    try:
        draft = call_llm_with_schema(
            llm_call=lambda: "...",  # TODO: llm.invoke(prompt) -> raw JSON text
            schema=DRAFT_SCHEMA,
        )
    except OutputValidationError:
        return None  # fail closed — no suggestion rather than a malformed one

    if not draft.get("has_suggestion"):
        return None

    recipient = resolve_recipient(incident_id, purpose="remediation_suggestion")
    if not recipient:
        return None  # cannot resolve a safe recipient — do not draft toward nowhere

    suggestion = ActionSuggestion(
        action_id=str(uuid.uuid4()),
        incident_id=incident_id,
        action_type="REMEDIATION_SUGGESTION",
        status="DRAFTED",
        recipient=recipient,
        subject=draft["subject"],
        body=draft["body"],
        evidence_refs=diagnosis.get("evidence_refs", []),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    persist_action(suggestion)
    transition_action(suggestion, "PENDING_APPROVAL")
    notify_action_pending_review(suggestion)  # informational notification — this part auto-sends
    return suggestion


# ---------------------------------------------------------------------------
# Approval workflow — triggered by the portal UI, entirely outside the graph
# ---------------------------------------------------------------------------

class InvalidActionTransitionError(RuntimeError):
    pass


def transition_action(suggestion: ActionSuggestion, target: ActionStatus) -> None:
    if target not in ACTION_ALLOWED_TRANSITIONS.get(suggestion.status, set()):
        raise InvalidActionTransitionError(f"{suggestion.status} -> {target} not allowed")
    suggestion.status = target
    persist_action(suggestion)


def approve_action(action_id: str, approver: str) -> ActionSuggestion:
    """Called by the portal when a human clicks Approve. Sends the EXACT
    content that was drafted and reviewed — this function does not call
    the LLM again. If you want the model to reconsider, that's a new draft
    (reject this one, request a fresh draft), never a silent regeneration
    at send time."""
    suggestion = load_action(action_id)
    transition_action(suggestion, "APPROVED")
    suggestion.approved_by = approver
    suggestion.approved_at = datetime.now(timezone.utc).isoformat()
    persist_action(suggestion)

    try:
        send_email(suggestion.recipient, suggestion.subject, suggestion.body)
        transition_action(suggestion, "SENT")
    except Exception as exc:  # noqa: BLE001
        transition_action(suggestion, "SEND_FAILED")
        log_send_failure(action_id, str(exc))
    return suggestion


def reject_action(action_id: str, approver: str, reason: str) -> ActionSuggestion:
    suggestion = load_action(action_id)
    transition_action(suggestion, "REJECTED")
    suggestion.rejected_reason = f"{approver}: {reason}"
    persist_action(suggestion)
    return suggestion


# ---------------------------------------------------------------------------
# Send + notification primitives
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, body: str) -> None:
    """The only function in this whole codebase that actually sends an
    email. Called from exactly two places: approve_action() above (after
    human approval) and send_informational_email() below (auto-send,
    informational only). Never called directly from a drafting or
    reasoning function, and never exposed to the LLM as a bindable tool."""
    ...  # TODO: real email client call (SES, SMTP, whatever you use)


def send_informational_email(incident_id: str, status: str, summary: str) -> None:
    """Auto-sent, extends the existing notify_oncall() pattern — same
    fail-soft rule applies: a failed send here must never affect the
    incident's own COMPLETED status."""
    recipient = resolve_recipient(incident_id, purpose="informational")
    if not recipient:
        return
    try:
        send_email(recipient, f"Migration incident {incident_id}: {status}", summary)
    except Exception as exc:  # noqa: BLE001
        log_send_failure(incident_id, str(exc))


def notify_action_pending_review(suggestion: ActionSuggestion) -> None:
    """Informational — tells the on-call/reviewer a suggestion is waiting,
    auto-sent regardless of whether the suggestion itself later gets
    approved or rejected."""
    send_informational_email(
        suggestion.incident_id,
        status="ACTION_PENDING_REVIEW",
        summary=f"A suggested remediation email for incident {suggestion.incident_id} "
                f"is drafted and awaiting your approval before it's sent to {suggestion.recipient}.",
    )


# ---------------------------------------------------------------------------
# Persistence stubs
# ---------------------------------------------------------------------------

def persist_action(suggestion: ActionSuggestion) -> None:
    ...  # UPSERT INTO action_suggestions (...)


def load_action(action_id: str) -> ActionSuggestion:
    ...  # SELECT * FROM action_suggestions WHERE action_id = %s
    raise NotImplementedError


def log_send_failure(action_id: str, error: str) -> None:
    ...  # append-only audit write

"""
Migration Failure Agent — production guardrails.

Wires in the six "must fix before launch" items from the architecture
review: secrets management, concurrency control, structured-output
enforcement with retry, human-facing delivery, a kill switch, and
prompt/SKILL.md versioning tied to the audit trail.

Import this module from the graph's top-level run function — see
run_agent() in migration_failure_agent_graph.py for how it's wired in.
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import threading
import contextlib
from dataclasses import dataclass
from typing import Callable, Optional, Any

try:
    import jsonschema
except ImportError:  # pragma: no cover — degrade to a no-op validator if unavailable
    jsonschema = None


# ---------------------------------------------------------------------------
# 1. Secrets management
# ---------------------------------------------------------------------------
# Every tool client (Splunk, K8s, SRE tracker DB, vCenter) must obtain its
# credentials through get_secret(), never through hardcoded values or plain
# environment variables read ad hoc. Swap the body for your real Vault/K8s
# Secrets client — the signature is what the rest of the codebase depends on.

class SecretNotFoundError(RuntimeError):
    pass


def get_secret(name: str) -> str:
    """Fetch a credential by logical name (e.g. 'splunk_readonly_token',
    'sre_tracker_db_dsn', 'vcenter_readonly_password'). Backed by Vault or
    K8s Secrets in production. The AGENT_SECRET_* env var path below is for
    LOCAL DEV ONLY and is refused unless AGENT_ENV=dev is set explicitly —
    this makes it structurally impossible to accidentally run production
    against a stray .env file or leftover env vars. Every credential this
    returns MUST belong to a read-only, least-privilege service account —
    never a credential with write access."""
    if os.environ.get("AGENT_ENV", "").lower() == "dev":
        env_key = f"AGENT_SECRET_{name.upper()}"
        value = os.environ.get(env_key)
        if value is None:
            raise SecretNotFoundError(
                f"Secret '{name}' not found in dev env (expected {env_key})."
            )
        return value

    # TODO: production path — e.g.
    #   return vault_client.secrets.kv.v2.read_secret_version(
    #       path=f"migration-failure-agent/{name}"
    #   )["data"]["data"]["value"]
    raise SecretNotFoundError(
        f"Secret '{name}' requested outside dev mode (AGENT_ENV != 'dev') but no "
        f"production secrets backend is wired in yet. Refusing to fall back to "
        f"environment variables in this mode."
    )


# ---------------------------------------------------------------------------
# 2. Kill switch
# ---------------------------------------------------------------------------
# Single point of control to stop the agent from running at all, without a
# deploy. Checked once per incident, before any LLM/tool call is made.

class AgentDisabledError(RuntimeError):
    pass


def is_agent_enabled() -> bool:
    """Backed by a config row / feature-flag service in production (e.g. a
    `agent_config` table with a single `enabled` boolean, or LaunchDarkly).
    The env var fallback below is for local dev only — do not ship the
    fallback as the only mechanism."""
    # TODO: SELECT enabled FROM agent_config WHERE agent_name = 'migration_failure_agent'
    return os.environ.get("AGENT_KILL_SWITCH_DISABLED", "false").lower() != "true"


def require_enabled() -> None:
    if not is_agent_enabled():
        raise AgentDisabledError(
            "Migration Failure Agent is disabled via kill switch. "
            "Incident will remain NEW for manual triage."
        )


# ---------------------------------------------------------------------------
# 3. Concurrency control
# ---------------------------------------------------------------------------
# Bounds how many agent runs execute at once, so a burst of simultaneous
# migration failures (e.g. during a bad cluster upgrade) can't exhaust LLM
# rate limits or hammer Splunk/K8s all at once. Runs beyond the limit queue
# rather than fail — see acquire()'s blocking behavior.

class RunConcurrencyLimiter:
    """Process-local semaphore for a single agent worker. In a multi-worker
    deployment, back this with a distributed limiter instead (e.g. a
    Postgres advisory lock count, or a Redis-based semaphore) so the cap
    applies across the whole fleet, not per-process."""

    def __init__(self, max_concurrent_runs: int = 10):
        self._sem = threading.Semaphore(max_concurrent_runs)
        self.max_concurrent_runs = max_concurrent_runs

    @contextlib.contextmanager
    def acquire(self, incident_id: str, timeout_s: float = 30.0):
        acquired = self._sem.acquire(timeout=timeout_s)
        if not acquired:
            raise TimeoutError(
                f"Incident {incident_id} could not get a concurrency slot within "
                f"{timeout_s}s ({self.max_concurrent_runs} runs already in flight)."
            )
        try:
            yield
        finally:
            self._sem.release()


concurrency_limiter = RunConcurrencyLimiter(max_concurrent_runs=10)


# ---------------------------------------------------------------------------
# 4. Structured-output enforcement with retry
# ---------------------------------------------------------------------------
# Every LLM call that must return JSON (evaluator verdict, compose_diagnosis
# output) goes through this wrapper. Never pass unvalidated model output
# downstream.

class OutputValidationError(RuntimeError):
    pass


def call_llm_with_schema(
    llm_call: Callable[[], str],
    schema: dict,
    max_retries: int = 2,
) -> dict:
    """Calls llm_call() (a zero-arg function that returns the raw model
    text — bind your prompt/messages via closure before passing it in),
    parses it as JSON, and validates against `schema`. Retries up to
    max_retries times on parse or validation failure, re-invoking llm_call
    as-is (add a repair instruction to your prompt closure if you want the
    retry to actually tell the model what it got wrong). Raises
    OutputValidationError if still invalid after retries — callers must
    treat that as equivalent to INSUFFICIENT_EVIDENCE, never pass the raw
    text through."""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        raw = llm_call()
        try:
            parsed = json.loads(raw)
            if jsonschema is not None:
                jsonschema.validate(instance=parsed, schema=schema)
            return parsed
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise OutputValidationError(
        f"LLM output failed schema validation after {max_retries + 1} attempts: {last_error}"
    )


DIAGNOSIS_SCHEMA = {
    "type": "object",
    "required": ["root_cause", "evidence_refs", "recommended_action"],
    "properties": {
        "root_cause": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
        "known_issue_ref": {"type": ["string", "null"]},
    },
}

EVALUATOR_VERDICT_SCHEMA = {
    "type": "object",
    "required": ["sufficient", "missing", "conflicts"],
    "properties": {
        "sufficient": {"type": "boolean"},
        "missing": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array"},
    },
}


# ---------------------------------------------------------------------------
# 5. Human-facing delivery
# ---------------------------------------------------------------------------
# The agent's job ends at DIAGNOSIS_READY / INSUFFICIENT_EVIDENCE / ESCALATED
# — but none of that matters if no human sees it. This pushes to whatever
# on-call channel you use, in addition to the dashboard/Postgres write.

@dataclass
class NotificationPayload:
    incident_id: str
    status: str                    # DIAGNOSIS_READY | INSUFFICIENT_EVIDENCE | ESCALATED
    summary: str
    confidence_band: Optional[str]
    dashboard_url: str


def notify_oncall(payload: NotificationPayload) -> None:
    """Dispatch to your on-call channel. Wire this to Slack webhook /
    PagerDuty Events API / whatever you use — do not let this raise and
    take down the run if it fails; log and continue, since a failed
    notification should never roll back an already-completed diagnosis."""
    # TODO: requests.post(get_secret("slack_webhook_url"), json={...})
    try:
        _dispatch_notification(payload)
    except Exception as exc:  # noqa: BLE001 — notification failure must not fail the run
        _log_notification_failure(payload.incident_id, str(exc))


def _dispatch_notification(payload: NotificationPayload) -> None:
    ...  # TODO: real webhook/API call


def _log_notification_failure(incident_id: str, error: str) -> None:
    ...  # append to audit log; alert separately if notification failures spike


# ---------------------------------------------------------------------------
# 6. Prompt / SKILL.md versioning
# ---------------------------------------------------------------------------
# Every run records exactly which SKILL.md/prompt versions it ran under, so
# a bad diagnosis can be traced to a specific prompt change, and prompt
# changes get the same review discipline as code changes.

AGENT_VERSION = "1.0.0"          # bump on any graph/routing logic change
SKILL_MD_VERSION = "1.0.0"       # bump on any SKILL.md content change


def hash_prompt(prompt_text: str) -> str:
    """Content hash of a rendered prompt template, recorded per run so you
    can detect drift even if someone edits a prompt without bumping the
    version constant above."""
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]


def record_run_version(incident_id: str, prompt_hashes: dict[str, str]) -> None:
    """Write agent/skill version + per-prompt content hashes to the audit
    table at the start of every run. This is what makes 'which prompt
    version produced this diagnosis' an answerable question later."""
    # TODO: INSERT INTO run_versions (incident_id, agent_version, skill_md_version, prompt_hashes, ts)
    ...

"""Optional LLM adapters for interpretation-only stages.

The model may generate candidate hypotheses, but it cannot select tools, change
state, calculate confidence, or execute actions. All output is schema validated.
"""
from __future__ import annotations

from typing import Any

from migration_failure_agent_production import (
    HYPOTHESIS_OUTPUT_SCHEMA,
    OutputValidationError,
    call_llm,
    call_llm_with_schema,
)


HYPOTHESIS_PROMPT = """You are generating candidate explanations for a failed VM migration.
You are NOT deciding the root cause. You are NOT selecting tools. Current
observations, RHoKP product knowledge, and SRE Tracker history are evidence
or advisory context respectively.

Issue:\n{issue}

Current context:\n{context}

Current evidence:\n{evidence}

RHoKP knowledge:\n{rhokp}

SRE Tracker history:\n{sre_tracker}

Return up to five plausible hypotheses. For each hypothesis provide an issue_tag
from the supplied issue taxonomy and fact codes that would support or contradict
it. A hypothesis without current evidence is only a candidate.
"""


def generate_hypotheses_llm(state: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = HYPOTHESIS_PROMPT.format(
        issue=state.get("issue"),
        context=state.get("context"),
        evidence=state.get("evidence"),
        rhokp=state.get("rhokp"),
        sre_tracker=state.get("sre_tracker"),
    )
    try:
        result = call_llm_with_schema(
            llm_call=lambda: call_llm(prompt),
            schema=HYPOTHESIS_OUTPUT_SCHEMA,
            max_retries=2,
        )
    except Exception:
        # Fail closed. Deterministic hypothesis seeds remain available to the graph.
        return []
    return result.get("hypotheses", [])

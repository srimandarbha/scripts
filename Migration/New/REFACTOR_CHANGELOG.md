# Migration Failure Agent refactor

## What changed

- Replaced global evidence scoring with per-hypothesis evidence correlation.
- Separated product knowledge (RHoKP) from organizational history (SRE Tracker).
- Added a canonical bounded tool gateway; the LLM no longer selects arbitrary tool names/arguments.
- Added explicit tool results: SUCCESS, NO_DATA, ERROR, TIMEOUT.
- Added structured correlation identity and progressive evidence retrieval.
- Added deterministic issue taxonomy and investigation policies.
- Added deterministic diagnosis, ownership, and recommendation stages.
- Historical knowledge can generate or reinforce hypotheses but cannot confirm a root cause without current evidence.
- Unresolved competing hypotheses escalate after a bounded second investigation pass.
- Correlation short-circuit now fails closed until a real per-incident signature check is wired.
- Phase 1 remains recommendation-only. No remediation tool is invoked by the refactored graph.

## Local test limitation

The execution image does not contain `langgraph` or `anthropic`, and outbound package installation is unavailable. The production `build_graph()` therefore intentionally refuses to run without LangGraph. The supplied simulation harness executes the same node topology with injected deterministic handlers, allowing the evaluator and state transitions to be exercised now.

## 2026-09-29 SRE Action-Plan Upgrade

- Added `ActionStep`, `RetryReadiness`, and `ActionPlan` models.
- Extended `AgentState` with timeline, impact, retry readiness, and investigation plan.
- Added deterministic timeline construction from evidence provenance.
- Added deterministic retry-readiness checks for Storage/CSI, VMware CBT, and Network/NAD scenarios.
- Added active-impact structure that reports systemic scope only when a current correlated-failure list is actually supplied.
- Added next-best-investigation planning from issue policy, unused optional tools, evidence gaps, and conflicts.
- Changed recommendation generation to produce SRE-oriented next action, do-not-do guidance, ownership, evidence, blockers, and human-review requirement.
- Integrated timeline → impact → ownership → retry-readiness → action-plan stages into the LangGraph and local simulation path.
- Added regression tests for action-plan behavior and retry-readiness blocking.
- No remediation/execution capability was added; V1 remains recommendation/read-only.

## Recovery decision layer update
- Added `RecoveryOption` model and recovery options in `ActionPlan`.
- Added deterministic recovery policy templates for storage CSI, VMware CBT, missing NAD, and unsupported VM devices.
- Added maintenance-window normalization and time-feasibility evaluation.
- Added explicit FIX_FORWARD, RETRY, and ROLLBACK paths with preconditions, proposed changes, validation, rollback steps, risk, and human approval.
- VM-level workarounds are represented as proposed, reversible actions only; the agent never executes them.
- SRE Tracker historical resolutions can enrich FIX_FORWARD rationale/preconditions, but do not prove current cause or authorize execution.
- Added regression tests for recovery-option coverage, maintenance-window feasibility, historical precedent, and VM-level reversibility.

## 2026-09-29 Migration Scope + Forecast Wiring

- Added `refactored_core/scope_forecast.py` with deterministic current-workload and recovery-scenario forecasting.
- Added `migration_scope`, `migration_forecast`, and `recovery_forecasts` to `AgentState`.
- Added explicit runtime adapter boundary `get_active_migration_scope`; no backend implementation was fabricated.
- Scope can come from authoritative migration context or the registered runtime adapter.
- Missing scope capability produces `UNKNOWN`; it never invents active migrations.
- Forecast accepts explicit ETA or derives ETA only from supplied remaining-bytes/throughput pairs.
- Known concurrency schedules queued work against currently running migrations; unknown scheduling capacity does not get guessed.
- Recovery forecasts are hypothetical and do not mutate the live scope.
- Scope is refreshed immediately before recommendation/recovery forecasting.
- Added full local integration coverage proving current running/queued/failed/completed migrations enter the recommendation output.

## 2026-09-29 - production wiring and reliability fixes
- Fixed mixed-ETA `scope_forecast` crash for multiple RUNNING migrations.
- Wired production run guardrails into `run_agent`.
- Wired canonical evidence-driven team routing and terminal notification boundary.
- Added injectable active-scope and VolumeAttachment capability adapters; removed fake empty-success stubs.
- Added explicit `MTV.MIGRATION_TIMEOUT` recommendation policy.
- Expanded conflict detection to all materially tied hypotheses.
- Added regression and production-wiring tests.

# Migration Failure Agent - Refactor/Test Report

Date: 2026-09-29

## Refactor applied

The previous migration-failure graph was replaced with an evidence-driven architecture:

`Kafka incident -> context -> classification -> policy-driven investigation -> RHoKP + SRE Tracker -> hypotheses -> per-hypothesis evaluation -> diagnosis -> ownership -> recommendation`

### Recommended changes implemented

- Per-hypothesis evidence scoring instead of global evidence aggregation.
- Current evidence separated from RHoKP and SRE Tracker knowledge.
- RHoKP contributes product meaning, possible causes and diagnostic checks.
- SRE Tracker contributes historical causes, resolutions and ownership.
- Historical knowledge cannot confirm a diagnosis without current evidence.
- Canonical bounded capability gateway with 27 registered capabilities.
- The LLM no longer controls arbitrary tool names or arguments.
- Structured LLM hypothesis-generation adapter is available for production.
- Deterministic issue taxonomy and investigation policy.
- Progressive evidence retrieval on subsequent passes.
- Explicit tool execution states: SUCCESS, NO_DATA, ERROR, TIMEOUT.
- Structured correlation fields for migration/VM/PVC/cluster identity.
- Evidence deduplication preserves independent source corroboration.
- Contradictory evidence is retained and evaluated per hypothesis.
- Unresolved competing hypotheses escalate after a bounded second pass.
- Ownership is a separate stage combining technical ownership and historical SRE Tracker ownership.
- Recommendations are deterministic and recommendation-only in Phase 1.
- Removed automatic action-drafting/remediation execution from the refactored diagnosis graph.
- Correlation short-circuit now fails closed until an authoritative per-incident signature check is available.
- Prompt/schema definitions no longer require an LLM-generated tool call.
- Updated SKILL.md and added a canonical tool-reference document.

## Tests executed

1. Python compilation for all project and test modules: PASS
2. Module import/static guard test: PASS
3. Production dependency guard: PASS (LangGraph correctly refuses to start in this image because it is not installed)
4. Regression tests: 4/4 PASS
5. End-to-end injected scenario simulations: 5/5 PASS

## Scenario results

| Scenario | Classification | Diagnosis outcome | Confidence | Ownership | Recommendation |
|---|---|---|---:|---|---|
| Storage CSI provisioning | STORAGE.CSI.PROVISIONING_TIMEOUT | CSI provisioning failure | 0.77 HIGH | storage | FIX_FORWARD |
| VMware warm migration | VMWARE.CBT | VMware CBT/snapshot failure | 0.77 HIGH | vmware_admins | FIX_FORWARD |
| Network mapping | NETWORK.NAD.MISSING | Target NAD missing/unusable | 0.77 HIGH | network | FIX_FORWARD |
| Generic timeout | MTV.MIGRATION_TIMEOUT | No causal evidence | n/a | n/a | INSUFFICIENT_EVIDENCE |
| Competing timeout causes | MTV.MIGRATION_TIMEOUT | Two hypotheses remained tied | 0.74 each | n/a | ESCALATED |

## Important limitation

These are real local executions of the refactored code using injected deterministic scenario backends. They are not live OpenShift/VMware/Splunk/RHoKP/SRE Tracker calls. The original backend methods still contain integration TODOs, and the execution image has neither `langgraph` nor `anthropic`; outbound package installation also failed due unavailable package networking.

The production graph will run through real LangGraph once the production dependencies and backend adapters are installed/wired.

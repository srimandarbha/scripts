# SRE Action-Plan Upgrade

This release changes the migration-failure agent from a diagnosis-plus-canned-recommendation flow into an SRE investigation assistant.

## New outputs

- `timeline`: deterministic chronological evidence view.
- `impact`: current correlated-failure/blast-radius structure; unknown when no correlation source is available.
- `retry_readiness`: PASS/NOT_READY/UNKNOWN checks with explicit blockers.
- `investigation_plan`: next-best optional evidence sources from the issue policy.
- `recommendation`: structured SRE Action Plan with next action, ordered steps, do-not-do guidance, owner, evidence, blockers, and mandatory human review.

## Safety boundary

The changes remain recommendation-only. No Kubernetes, VMware, storage, network, AAP, or migration mutation is performed by the new components.

## Validation

- Python compileall: PASS
- Existing evaluator regressions: PASS
- Action-plan regression: PASS
- Retry-readiness regression: PASS
- Existing storage, VMware CBT, network, insufficient-evidence, and conflict simulations: PASS

## Remaining production work

Real adapters are still required for Kubernetes/MTV, Splunk, VMware, storage backends, RHoKP, and SRE Tracker. Runtime RBAC, persistence, Kafka idempotency/DLQ, tracing, and labelled evaluation are also still required before production deployment.

## Recovery Options / Maintenance Window
The SRE action plan now includes a `recovery_options` array and `maintenance_window` object.

Supported option types in the deterministic policy layer:
- `FIX_FORWARD`: approved VM/platform/configuration change followed by validation and retry.
- `RETRY`: available only when retry-readiness gates pass.
- `ROLLBACK`: stop/undo the migration attempt when recovery is unsafe or time-constrained.

Each option carries:
- status and risk
- evidence references
- preconditions
- proposed changes
- validation criteria
- rollback steps
- estimated duration when supplied by portal/context
- maintenance-window time feasibility
- `human_approval_required=true`
- `execution=NOT_EXECUTED`

The LLM may explain and contextualize these options, but it must not invent or execute arbitrary VM changes. Approved action catalogs plus EDA/AAP remain the execution boundary after human approval.

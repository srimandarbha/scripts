# Migration Failure Agent - Fixes Applied

## Fixed

1. **Forecast crash with mixed RUNNING ETA availability**
   - `scope_forecast.py` no longer passes `None` into `max()`.
   - Multiple RUNNING migrations where one has no ETA now fail closed to `UNKNOWN`.
   - Regression test added.

2. **Production run boundary guardrails are now wired**
   - `run_agent()` now invokes the existing kill switch.
   - Acquires the existing concurrency limiter.
   - Records run/version metadata through the existing audit hook.
   - Performs best-effort human notification after terminal graph results.
   - Local simulation remains separate and is not forced through production controls.

3. **Canonical evidence-driven ownership routing is now wired**
   - `build_ownership()` uses `classify_owning_team()`.
   - SRE Tracker ownership is not treated as authoritative current ownership.
   - Diagnosis routing accepts both `evidence_refs` and the current `supporting_evidence` field.

4. **Human notification routing is now connected**
   - Diagnosis results use canonical ownership routing and include SRE plus specialist teams as appropriate.
   - Insufficient-evidence results use `route_insufficient_evidence()`.
   - Notification failures do not fail the completed diagnosis.
   - The actual Slack/PagerDuty/etc. dispatcher remains a deployment adapter and is intentionally not fabricated.

5. **Active migration scope and VolumeAttachment are explicit injectable capabilities**
   - `build_production_runtime(capability_adapters=...)` accepts real read-only deployment adapters.
   - Missing adapters are not represented as successful empty results.
   - A missing VolumeAttachment adapter returns `ERROR` through the capability gateway.
   - No fake migration-portal or Kubernetes backend was added.

6. **MTV timeout has an explicit recommendation policy**
   - `MTV.MIGRATION_TIMEOUT` now produces a concrete investigation plan and safety preconditions rather than falling through to an empty generic policy.

7. **Conflict detection now considers the complete materially tied set**
   - Any confirmed/supported hypotheses within the configured confidence threshold of the leader are included in the conflict set.
   - Three-way and larger ties are no longer invisible.

## Verification

- Python compilation: PASS
- Existing regression/simulation scripts: PASS
- Pytest suite: **20 passed**
- Reproduced forecast crash case: now fails closed without exception
- Production routing/notification boundary tests: PASS
- Capability injection tests: PASS

## Deliberately not fabricated

The package still requires deployment-specific implementations for:

- migration-portal active scope provider
- Kubernetes VolumeAttachment provider
- real notification transport
- production Vault/audit persistence
- real Splunk/Kubernetes/VMware/storage adapters

Those are now explicit integration boundaries rather than silent fake-success stubs.

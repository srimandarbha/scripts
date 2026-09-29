# Migration Scope and Forecast Contract

## Purpose

The failure agent diagnoses one failed migration, but recovery timing must account for the entire migration change/wave currently in progress.

The refactored code therefore has two deterministic stages:

1. `build_migration_scope_node` resolves the current change/wave scope.
2. `build_migration_forecast_node` calculates the current workload forecast.

The code does **not** discover migrations itself and does **not** fabricate missing rows, durations, throughput, or concurrency.

## Authoritative scope input

The runtime may provide an explicit `get_active_migration_scope` capability. This is an adapter boundary, not a fake implementation.

The real adapter must return a `ToolResult(status="SUCCESS", facts=[{"value": {...}}])` where `value` contains:

```json
{
  "source": "migration_portal",
  "change_id": "CHG-123",
  "wave_id": "WAVE-42",
  "observed_at": "2026-09-29T03:00:00+00:00",
  "concurrency_limit": 3,
  "migrations": [
    {
      "migration_id": "M-101",
      "vm_id": "VM-101",
      "state": "RUNNING",
      "remaining_bytes": 40000000000,
      "throughput_bytes_per_second": 100000000
    },
    {
      "migration_id": "M-102",
      "vm_id": "VM-102",
      "state": "QUEUED",
      "eta_seconds": 900
    }
  ]
}
```

`state` values currently recognized are `RUNNING`, `QUEUED`, `PENDING`, `SUCCEEDED`, `FAILED`, and `CANCELLED`.

## ETA rules

For an active migration, ETA is accepted only when either:

- `eta_seconds` is supplied by the authoritative source, or
- both `remaining_bytes` and `throughput_bytes_per_second > 0` are supplied.

If a required active migration lacks a usable ETA, the workload forecast becomes `UNKNOWN`. The engine does not substitute historical averages or LLM estimates.

## Queue forecast

When `concurrency_limit` is known:

- running migrations occupy slots until their current ETA;
- queued migrations are assigned to the earliest available slot;
- projected wave completion is the maximum slot finish time.

If concurrency is unknown and queued work exists, the forecast is `UNKNOWN` rather than assuming unlimited or arbitrary parallelism.

## Recovery forecast

A failed migration is not changed in the live scope. For a recovery option, the engine creates a temporary in-memory scenario using only that option's explicit `estimated_minutes` value.

The resulting forecast answers:

> If this recovery option were approved and its supplied duration were achieved, what would the known change/wave completion forecast be?

It does **not** execute the recovery and does not alter authoritative migration state.

## Refresh behavior

The graph resolves scope once after migration context and refreshes it immediately before recovery forecasting. The local runner follows the same pattern.

For genuinely live behavior, the portal/control-plane adapter must return current observations on every invocation. Kafka progress events can also trigger a separate forecast refresh workflow without invoking the diagnosis path.

## Missing adapter behavior

If `get_active_migration_scope` is not registered, the forecast is explicitly:

```json
{
  "status": "UNKNOWN",
  "reason": "No active-migration scope adapter is registered.",
  "confidence": "NONE"
}
```

This is intentional. It prevents the agent from pretending it knows the currently running/queued migration workload.

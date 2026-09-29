# Refactored Tool Reference

The agent uses canonical bounded capability names. These names are selected
by investigation policy, not invented by the LLM.

## Context

- `get_migration_context(migration_id, vm_id)`
- `get_migration_metrics(migration_id, time_range)`
- `search_splunk_for_migration(migration_id, time_range)`

## Storage

- `get_datavolume(dv_id)`
- `get_pvc(pvc_id)`
- `get_storageclass(storageclass_id)`
- `get_volumeattachment(volumeattachment_id)`
- `get_csi_logs(driver, time_range)`
- `get_storage_backend_status(backend)`

## VMware

- `get_vcenter_events(vm_id, time_range)`
- `get_source_vm_state(vm_id)`
- `get_vmware_task_history(vm_id, time_range)`

## Network

- `get_networkmap(migration_id)`
- `get_nad(nad_id)`
- `get_multus_status(cluster_id)`
- `get_ovn_status(cluster_id)`

## Cluster/platform

- `get_cluster_health()`
- `get_node_health(node_id)`
- `get_recent_cluster_changes(time_range)`
- `get_namespace_events(namespace, time_range)`

## Knowledge

- `search_rhokp(signature)`
- `search_sre_tracker(signature)`

## Tool result contract

Every call returns:

```json
{
  "tool_name": "get_pvc",
  "status": "SUCCESS | NO_DATA | ERROR | TIMEOUT",
  "observed_at": "ISO8601",
  "retrieved_at": "ISO8601",
  "source": "kubernetes",
  "correlation": {},
  "facts": [],
  "evidence": [],
  "error": null,
  "latency_ms": 12.4
}
```

A backend failure is never converted to an empty successful evidence set.

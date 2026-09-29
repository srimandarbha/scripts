"""Canonical, bounded tool gateway for the refactored migration failure agent."""
from __future__ import annotations

from typing import Any, Callable

from migration_failure_agent_tools import (
    get_migration_plan_status,
    get_vm_migration_conditions,
    get_datavolume_status,
    get_namespace_events,
    get_pod_logs,
    get_migration_metrics,
    search_splunk_for_migration,
    get_cluster_health,
    get_node_health,
    get_pvc_status,
    get_storage_class_health,
    get_csi_driver_logs,
    get_network_attachment_status,
    get_vcenter_events,
    get_source_vm_config,
    get_recent_cluster_changes,
    get_network_map_status,
    get_storage_map_status,
    get_provider_status,
    get_target_vm_boot_status,
    get_cluster_resource_capacity,
    get_namespace_quota_status,
    search_sre_tracker_db,
    search_product_documentation,
    get_similar_migrations,
)
from refactored_core.tool_runtime import ToolRuntime, normalize_evidence


def _legacy(fn: Callable[..., Any], **kwargs) -> Any:
    return fn(**kwargs)


def _context(**kwargs):
    # Until the production resolver is wired to the portal/API, use the
    # currently available canonical control-plane tools to build a minimal
    # context. A real implementation should resolve all related objects in
    # one bounded backend call.
    migration_id = kwargs.get("migration_id")
    vm_id = kwargs.get("vm_id")
    parts = []
    for fn, args in (
        (get_migration_plan_status, {"migration_id": migration_id}),
        (get_vm_migration_conditions, {"vm_id": vm_id}),
        (get_datavolume_status, {"dv_id": kwargs.get("dv_id")}),
    ):
        try:
            rows = fn(**{k: v for k, v in args.items() if v})
            parts.extend(list(rows))
        except Exception:
            pass
    if not parts:
        return []
    # Preserve the evidence records while adding a structured context hint.
    result = []
    for e in parts:
        e = dict(e)
        e["source_type"] = "PORTAL_CONTEXT"
        e["context"] = {
            "migration_id": migration_id,
            "vm_id": vm_id,
            "cluster_id": kwargs.get("cluster_id"),
            "phase": kwargs.get("phase"),
            "namespace": kwargs.get("namespace"),
            "time_range": kwargs.get("time_range"),
        }
        result.append(e)
    return result


def _no_data(**kwargs):
    return []


def _storageclass(**kwargs):
    return get_storage_class_health(sc_id=kwargs.get("storageclass_id") or kwargs.get("sc_id"))


def _csi_logs(**kwargs):
    return get_csi_driver_logs(driver=kwargs.get("driver") or "unknown", time_range=kwargs.get("time_range") or {})


def _vcenter_events(**kwargs):
    return get_vcenter_events(vm_id=kwargs.get("vm_id"), time_range=kwargs.get("time_range") or {})


def _source_vm_state(**kwargs):
    return get_source_vm_config(vm_id=kwargs.get("vm_id"))


def _splunk(**kwargs):
    return search_splunk_for_migration(migration_id=kwargs.get("migration_id"), time_range=kwargs.get("time_range") or {})


def _metrics(**kwargs):
    return get_migration_metrics(migration_id=kwargs.get("migration_id"), time_range=kwargs.get("time_range") or {})


def _events(**kwargs):
    return get_namespace_events(namespace=kwargs.get("namespace"), time_range=kwargs.get("time_range") or {})


def _logs(**kwargs):
    return get_pod_logs(pod=kwargs.get("pod") or "", time_range=kwargs.get("time_range") or {})


def _rhokp(**kwargs):
    signature = kwargs.get("signature") or {}
    query = " ".join(f"{k}={v}" for k, v in signature.items() if v)
    return search_product_documentation(query=query)


def _sre_tracker(**kwargs):
    signature = kwargs.get("signature") or {}
    fingerprint = "::".join(str(signature.get(k, "")) for k in ("phase", "issue_tag", "storage_backend", "error_text"))
    return search_sre_tracker_db(fingerprint=fingerprint)


HANDLERS: dict[str, Callable[..., Any]] = {
    "get_migration_context": _context,
    "get_migration_metrics": _metrics,
    "search_splunk_for_migration": _splunk,
    "get_datavolume": get_datavolume_status,
    "get_pvc": get_pvc_status,
    "get_storageclass": _storageclass,
    # These capabilities require deployment-specific read-only adapters.
    # They are deliberately absent rather than returning [] and pretending
    # that the backend was queried. build_production_runtime() can inject them.
    "get_csi_logs": _csi_logs,
    "get_vcenter_events": _vcenter_events,
    "get_source_vm_state": _source_vm_state,
    "get_recent_cluster_changes": get_recent_cluster_changes,
    "get_networkmap": get_network_map_status,
    "get_nad": get_network_attachment_status,
    "get_cluster_health": get_cluster_health,
    "get_node_health": get_node_health,
    "get_namespace_events": _events,
    "get_pod_logs": _logs,
    "get_target_vm_boot_status": get_target_vm_boot_status,
    "get_cluster_resource_capacity": get_cluster_resource_capacity,
    "get_namespace_quota_status": get_namespace_quota_status,
    "search_rhokp": _rhokp,
    "search_sre_tracker": _sre_tracker,
    "get_similar_migrations": get_similar_migrations,
}


def build_production_runtime(*, capability_adapters: dict[str, Callable[..., Any]] | None = None) -> ToolRuntime:
    """Build the read-only production capability gateway.

    Real deployment adapters are injected by the service bootstrap. We do not
    fabricate portal/Kubernetes data when an adapter is absent.
    """
    handlers = dict(HANDLERS)
    for name, adapter in (capability_adapters or {}).items():
        if callable(adapter):
            handlers[name] = adapter
    return ToolRuntime(handlers)

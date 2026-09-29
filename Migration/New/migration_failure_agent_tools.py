"""
Migration Failure Agent — tool scripts.

Every function here is a TOOL the LLM can call via bind_tools(). Keep these
function names and signatures stable — the graph, prompts, and evaluator
logic reference them by name. Swap the internal query logic (Splunk SPL,
K8s API calls, SQL, MCP calls) for your real backends; the docstrings are
written for the LLM, not just for humans — that's what it reads to decide
when and how to call each tool, so keep them accurate if you change behavior.

All tools are READ-ONLY. None of them may write, patch, delete, or execute
anything. Enforcement lives in `read_only_tool` below, applied as a
decorator to every function — do not remove it.
"""

from __future__ import annotations

import functools
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, TypedDict, Optional

# --- Backend clients (wire these to your real infra) -----------------------
# import splunklib.client as splunk_client
# from kubernetes import client as k8s_client, config as k8s_config
# import psycopg2
# from mcp_client import McpClient  # your RAG-over-docs MCP connection
#
# All client credentials come from get_secret() in
# migration_failure_agent_production.py — never hardcode or read raw env
# vars for credentials here. Example:
#   from migration_failure_agent_production import get_secret
#   splunk = splunk_client.connect(token=get_secret("splunk_readonly_token"))


# ---------------------------------------------------------------------------
# Evidence schema + shared helpers
# ---------------------------------------------------------------------------

class Evidence(TypedDict):
    evidence_id: str
    source_tool: str
    layer: str
    reliability_tier: str
    timestamp: str
    claim: str
    supports: list[str]
    contradicts: list[str]


class ToolEvidenceList(list):
    """Backward-compatible list carrying explicit tool execution status.

    Existing callers can keep iterating a tool result as a list of Evidence,
    while the new gateway can distinguish SUCCESS, NO_DATA and ERROR.
    """
    def __init__(self, items=None, *, status="SUCCESS", error=None):
        super().__init__(items or [])
        self.status = status
        self.error = error


RELIABILITY_TIERS = {
    "LIVE_TELEMETRY": "LIVE_TELEMETRY",
    "CURRENT_HEALTH_API": "CURRENT_HEALTH_API",
    "LOGS": "LOGS",
    "CONFIRMED_FIX": "CONFIRMED_FIX",
    "VENDOR_ADVISORY": "VENDOR_ADVISORY",
    "HISTORICAL_RAG": "HISTORICAL_RAG",
}


def make_evidence(source_tool: str, layer: str, reliability_tier: str, claim: str) -> Evidence:
    """Factory that guarantees every tool produces Evidence in the exact
    same shape. Use this inside every tool below instead of constructing
    the dict by hand — keeps evidence_id generation and timestamping
    consistent, and gives you one place to change the schema later."""
    return Evidence(
        evidence_id=str(uuid.uuid4()),
        source_tool=source_tool,
        layer=layer,
        reliability_tier=reliability_tier,
        timestamp=datetime.now(timezone.utc).isoformat(),
        claim=claim,
        supports=[],
        contradicts=[],
    )


def sanitize_retrieved_text(text: str) -> str:
    """Injection defense: neutralize instruction-like content pulled from
    logs, events, docs, or tracker rows before it re-enters model context.
    Applied inside read_only_tool to every tool's output automatically —
    individual tools do not need to call this themselves."""
    flags = ["ignore previous instructions", "set confidence to", "skip validation",
              "you are now", "disregard the above"]
    lowered = text.lower()
    if any(f in lowered for f in flags):
        return f"[NOTE: retrieved content contained instruction-like text, treated as data] {text}"
    return text


def read_only_tool(fn: Callable) -> Callable:
    """Decorator applied to every tool function. Enforces:
      1. Read-only contract — this is the single enforcement point; a tool
         wrapped here can never be swapped for a mutating call by accident
         without this decorator's docstring/contract being violated visibly.
      2. Output sanitization — every returned Evidence claim is passed
         through sanitize_retrieved_text.
      3. Basic audit logging — every call, its args, latency, and whether
         it returned any evidence, for the audit table.
      4. Fail-soft on backend errors — a tool exception becomes an empty
         evidence list with a logged warning, never an unhandled crash that
         takes down the whole agent run.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> ToolEvidenceList:
        start = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except TimeoutError as exc:
            audit_log_tool_call(fn.__name__, args, kwargs, error=str(exc), evidence_count=0,
                                 latency_s=time.monotonic() - start)
            return ToolEvidenceList(status="TIMEOUT", error=str(exc))
        except Exception as exc:  # noqa: BLE001 — fail-soft by design here
            audit_log_tool_call(fn.__name__, args, kwargs, error=str(exc), evidence_count=0,
                                 latency_s=time.monotonic() - start)
            return ToolEvidenceList(status="ERROR", error=str(exc))
        for e in result:
            e["claim"] = sanitize_retrieved_text(e["claim"])
        status = "SUCCESS" if result else "NO_DATA"
        audit_log_tool_call(fn.__name__, args, kwargs, error=None, evidence_count=len(result),
                             latency_s=time.monotonic() - start)
        return ToolEvidenceList(result, status=status)
    return wrapper


def audit_log_tool_call(tool_name: str, args: tuple, kwargs: dict, error: Optional[str],
                         evidence_count: int, latency_s: float) -> None:
    """Append-only write to the Postgres audit table. Every tool call is
    logged here regardless of outcome — this is what makes a diagnosis
    traceable after the fact, and what the budget/circuit-breaker layer
    reads from to decide whether a tool is degraded."""
    ...  # INSERT INTO audit_log (...) VALUES (...)


# ---------------------------------------------------------------------------
# 1. Control plane — MTV/Forklift CR status
# ---------------------------------------------------------------------------

@read_only_tool
def get_migration_plan_status(migration_id: str) -> list[Evidence]:
    """Use FIRST for almost every incident. Returns the MTV/Forklift
    Migration/Plan custom resource's status.conditions for this
    migration_id — the phase it failed at and the controller's own
    stated reason string. This is often where the actual failure reason
    lives, distinct from any pod log. Does not return VM-level conditions
    (use get_vm_migration_conditions) or DataVolume status (use
    get_datavolume_status). Input source: trigger — migration_id comes
    directly from the migration.failed trigger payload.

    Pseudocode:
        cr = k8s.get_custom_object(group="forklift.konveyor.io", version="v1beta1",
                                    namespace=NS, plural="migrations", name=migration_id)
        for cond in cr["status"]["conditions"]:
            yield make_evidence(..., claim=f"{cond['type']}: {cond['reason']} - {cond['message']}")
    """
    # TODO: k8s_client.CustomObjectsApi().get_namespaced_custom_object(
    #     group="forklift.konveyor.io", version="v1beta1",
    #     namespace=..., plural="migrations", name=migration_id)
    conditions: list[dict] = []  # replace with real API call result
    return [
        make_evidence("get_migration_plan_status", "control_plane", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                       f"Migration {migration_id} condition: {c}")
        for c in conditions
    ]


@read_only_tool
def get_vm_migration_conditions(vm_id: str) -> list[Evidence]:
    """Use when the plan-level status doesn't explain a per-VM failure in a
    multi-VM migration plan. Returns per-VM migration CR conditions.
    Complements, does not replace, get_migration_plan_status. Input
    source: trigger — vm_id comes directly from the trigger payload.

    Pseudocode:
        cr = k8s.get_custom_object(group="forklift.konveyor.io", version="v1beta1",
                                    namespace=NS, plural="vms", name=vm_id)
        for cond in cr["status"]["conditions"]:
            yield make_evidence(..., claim=f"VM {vm_id}: {cond['type']} - {cond['message']}")
    """
    conditions: list[dict] = []  # TODO: real CR fetch
    return [
        make_evidence("get_vm_migration_conditions", "control_plane", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                       f"VM {vm_id} condition: {c}")
        for c in conditions
    ]


@read_only_tool
def get_datavolume_status(dv_id: str) -> list[Evidence]:
    """Use when control-plane evidence points at disk/import failure. Returns
    the CDI DataVolume's status/conditions (e.g. ImportFailed,
    CloneScheduling). This is the bridge between control-plane and storage
    evidence — check this before jumping straight to PVC/storage-class
    tools if the plan status mentions a DataVolume by name. Input source:
    evidence — dv_id is not in the trigger payload; it must be read from a
    DataVolume name mentioned in a prior get_migration_plan_status or
    get_vm_migration_conditions claim.

    Pseudocode:
        dv = k8s.get_custom_object(group="cdi.kubevirt.io", version="v1beta1",
                                    namespace=NS, plural="datavolumes", name=dv_id)
        for cond in dv["status"]["conditions"]:
            yield make_evidence(..., claim=f"DataVolume {dv_id}: {cond['type']} - {cond['message']}")
    """
    conditions: list[dict] = []  # TODO: real CR fetch
    return [
        make_evidence("get_datavolume_status", "control_plane", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                       f"DataVolume {dv_id} condition: {c}")
        for c in conditions
    ]


# ---------------------------------------------------------------------------
# 2. Events
# ---------------------------------------------------------------------------

@read_only_tool
def get_namespace_events(namespace: str, time_range: str) -> list[Evidence]:
    """Use early, alongside control-plane checks. Catches failures with no
    pod log at all — scheduling failures, admission-webhook rejections,
    quota denials — because the pod or resource never came up in the first
    place. If control-plane status is vague ("Failed" with no detail),
    check here before assuming you need deeper logs. Input source: trigger
    — namespace is derived from migration metadata in the trigger payload
    (typically the migration's target namespace), not discovered from
    evidence.

    Pseudocode:
        events = k8s.list_namespaced_event(namespace=namespace,
                                            field_selector=f"lastTimestamp>={time_range.start}")
        for e in events.items:
            yield make_evidence(..., claim=f"{e.reason}: {e.message} (involved: {e.involved_object.name})")
    """
    events: list[dict] = []  # TODO: k8s_client.CoreV1Api().list_namespaced_event(...)
    return [
        make_evidence("get_namespace_events", "events", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                       f"Event in {namespace}: {e}")
        for e in events
    ]


# ---------------------------------------------------------------------------
# 3. Compute — pod logs, metrics, Splunk aggregation
# ---------------------------------------------------------------------------

@read_only_tool
def get_pod_logs(pod: str, time_range: str) -> list[Evidence]:
    """Use when control-plane/events evidence points at a specific pod
    (importer, conversion, virt-launcher). Returns a small set of relevant
    log lines, NOT a raw dump — pre-filter to error/warn level lines plus
    immediate context. For broad error-pattern search across many pods,
    prefer search_splunk_for_migration instead of calling this repeatedly.
    Input source: evidence — pod is not in the trigger payload; it must be
    read from a pod name mentioned in a prior get_migration_plan_status,
    get_vm_migration_conditions, or get_namespace_events claim.

    Pseudocode:
        raw = k8s.read_namespaced_pod_log(name=pod, namespace=NS, since_seconds=time_range.seconds)
        error_lines = [l for l in raw.splitlines() if "ERROR" in l or "WARN" in l]
        for line in error_lines[:MAX_LINES]:
            yield make_evidence(..., claim=line)
    """
    lines: list[str] = []  # TODO: k8s_client.CoreV1Api().read_namespaced_pod_log(...)
    return [
        make_evidence("get_pod_logs", "compute", RELIABILITY_TIERS["LOGS"], line)
        for line in lines
    ]


@read_only_tool
def get_migration_metrics(migration_id: str, time_range: str) -> list[Evidence]:
    """Use to check throughput/latency shape around the failure time —
    confirms or rules out a stall/timeout hypothesis. Returns summary
    stats (avg/peak throughput, latency percentiles), not raw time series.
    Input source: trigger — migration_id and an approximate time_range are
    both derivable directly from the trigger payload's failed_at field.

    Pseudocode:
        stats = metrics_client.query_range(
            query=f'migration_throughput{{migration_id="{migration_id}"}}',
            start=time_range.start, end=time_range.end)
        summary = {"avg": mean(stats), "p95_latency": percentile(stats, 95)}
        yield make_evidence(..., claim=f"Throughput/latency summary: {summary}")
    """
    stats: dict = {}  # TODO: metrics backend query
    return [
        make_evidence("get_migration_metrics", "compute", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                       f"Metrics for {migration_id}: {stats}")
    ] if stats else []


@read_only_tool
def search_splunk_for_migration(migration_id: str, time_range: str) -> list[Evidence]:
    """Use for a broad error-signature sweep across all components involved
    in this migration, when you don't yet know which specific pod to check.
    Runs a scoped SPL query and returns PRE-AGGREGATED error signatures
    (error type + count + first/last seen), never raw log lines — do not
    modify this tool to return raw text, it will blow the context budget.
    Prefer get_pod_logs once you already know which pod to look at. Input
    source: trigger — migration_id and time_range both derivable directly
    from the trigger payload.

    Pseudocode:
        spl = (f'index=ocp_logs migration_id="{migration_id}" '
               f'earliest={time_range.start} latest={time_range.end} '
               f'| stats count by error_signature | sort -count | head 10')
        job = splunk.jobs.oneshot(spl)
        for row in job:
            yield make_evidence(..., claim=f"'{row.error_signature}' x{row.count}, first {row.first_seen}")
    """
    # TODO: spl = f'index=ocp_logs migration_id="{migration_id}" earliest={...} latest={...}
    #              | stats count by error_signature | sort -count'
    # results = splunk_client.jobs.oneshot(spl)
    aggregated: list[dict] = []  # [{"error_signature": ..., "count": ..., "first_seen": ...}]
    return [
        make_evidence("search_splunk_for_migration", "compute", RELIABILITY_TIERS["LOGS"],
                       f"Error signature '{r['error_signature']}' seen {r['count']}x, first at {r['first_seen']}")
        for r in aggregated
    ]


# ---------------------------------------------------------------------------
# 4. Cluster / node health (RHOKP)
# ---------------------------------------------------------------------------

@read_only_tool
def get_cluster_health() -> list[Evidence]:
    """Use to rule out (or confirm) a cluster-wide issue before assuming
    the failure is specific to this migration. Returns overall cluster
    health status from RHOKP — operator health, control-plane readiness.
    Input source: none — takes no incident-specific input; safe to call
    at any point in the loop.

    Pseudocode:
        status = rhokp_client.get_cluster_operators_summary()
        if status["degraded_operators"]:
            yield make_evidence(..., claim=f"Degraded operators: {status['degraded_operators']}")
    """
    status: dict = {}  # TODO: RHOKP API / Splunk query
    return [make_evidence("get_cluster_health", "cluster_health", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Cluster health: {status}")] if status else []


@read_only_tool
def get_node_health(node_id: str) -> list[Evidence]:
    """Use when evidence points at a specific node (e.g. the VM/pod was
    scheduled there). Returns that node's health — pressure conditions,
    readiness, recent restarts. Input source: evidence — node_id is not in
    the trigger payload; it must be read from a node name mentioned in a
    prior get_pod_logs, get_namespace_events, or get_vm_migration_conditions
    claim.

    Pseudocode:
        node = k8s.read_node(name=node_id)
        pressures = [c for c in node.status.conditions if c.status == "True" and "Pressure" in c.type]
        yield make_evidence(..., claim=f"Node {node_id} conditions: {pressures or 'nominal'}")
    """
    status: dict = {}  # TODO: RHOKP / K8s node status
    return [make_evidence("get_node_health", "cluster_health", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Node {node_id} health: {status}")] if status else []


# ---------------------------------------------------------------------------
# 5. Storage
# ---------------------------------------------------------------------------

@read_only_tool
def get_pvc_status(pvc_id: str) -> list[Evidence]:
    """Use when a migration is stuck or failed and control-plane evidence
    points at storage (e.g. a DataVolume in ImportFailed). Returns the
    PVC's bind status, pending duration, and last event reason. Does not
    return CSI driver logs — use get_csi_driver_logs for that. Input
    source: evidence — pvc_id is not in the trigger payload; it must be
    read from a PVC name mentioned in a prior get_datavolume_status claim.
    A healthy/Bound result here is itself meaningful — it rules out
    storage as the cause rather than being an inconclusive check.

    Pseudocode:
        pvc = k8s.read_namespaced_persistent_volume_claim(name=pvc_id, namespace=NS)
        pending_for = now() - pvc.metadata.creation_timestamp if pvc.status.phase == "Pending" else None
        yield make_evidence(..., claim=f"PVC {pvc_id}: {pvc.status.phase}, pending_for={pending_for}")
    """
    status: dict = {}  # TODO: k8s_client.CoreV1Api().read_namespaced_persistent_volume_claim(...)
    return [make_evidence("get_pvc_status", "storage", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"PVC {pvc_id} status: {status}")] if status else []


@read_only_tool
def get_storage_class_health(sc_id: str) -> list[Evidence]:
    """Use when get_pvc_status shows Pending with a provisioning reason.
    Returns the storage class's current capacity/availability status —
    confirms or rules out capacity exhaustion as the cause. Reads from
    Splunk (OTel-exported gauge metric, 1-5 min freshness), NOT a live
    storage backend call — capacity is a genuinely numeric, continuously
    changing value, which is exactly the case for an OTel gauge rather
    than a live query, same reasoning as get_cluster_topology_snapshot.
    Input source: evidence — sc_id is normally read from the
    storageClassName field in a prior get_pvc_status claim. Falls back to
    config only if this cluster has a single default storage class known
    ahead of time.

    Pseudocode:
        spl = f'index=cluster_metrics metric_name="ocv_storageclass_capacity_used_percent" '
              f'storage_class="{sc_id}" | tail 1'
        row = splunk.jobs.oneshot(spl)
        yield make_evidence(..., reliability_tier="CURRENT_HEALTH_API",
                             claim=f"Storage class {sc_id}: {row.value}% used, "
                                   f"last_sampled={row._time}")
    """
    row: dict = {}  # TODO: Splunk query against the OTel-exported capacity gauge
    if not row:
        return []
    return [make_evidence("get_storage_class_health", "storage", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Storage class {sc_id}: {row.get('value')}% used, "
                           f"last_sampled={row.get('_time')}")]


@read_only_tool
def get_csi_driver_logs(driver: str, time_range: str) -> list[Evidence]:
    """Use when PVC and storage-class evidence don't fully explain a
    provisioning failure — the CSI driver's own logs often carry the
    underlying array/backend error. Pre-filter to error-level lines. Input
    source: evidence — driver name is normally read from the provisioner
    field in a prior get_storage_class_health claim; falls back to config
    only if this cluster runs a single CSI driver known ahead of time.

    Pseudocode:
        pods = k8s.list_pods(label_selector=f"app={driver}")
        for pod in pods:
            raw = k8s.read_namespaced_pod_log(name=pod.name, since_seconds=time_range.seconds)
            for line in [l for l in raw.splitlines() if "ERROR" in l][:MAX_LINES]:
                yield make_evidence(..., claim=line)
    """
    lines: list[str] = []  # TODO: pod log fetch for the CSI driver's pods
    return [make_evidence("get_csi_driver_logs", "storage", RELIABILITY_TIERS["LOGS"], line) for line in lines]


# ---------------------------------------------------------------------------
# 6. Network
# ---------------------------------------------------------------------------

@read_only_tool
def get_network_attachment_status(nad_id: str) -> list[Evidence]:
    """Use when a network-mapping mismatch is a live hypothesis (e.g. a
    historical/tracker match suggested it, or metrics show zero throughput
    from the start rather than a mid-transfer stall). Returns the
    NetworkAttachmentDefinition's config and current status. Input source:
    evidence — nad_id is normally read from the network mapping named in a
    prior get_vm_migration_conditions claim; falls back to config only if
    this cluster/namespace has a single NAD known ahead of time.

    Pseudocode:
        nad = k8s.get_custom_object(group="k8s.cni.cncf.io", version="v1",
                                     namespace=NS, plural="network-attachment-definitions", name=nad_id)
        yield make_evidence(..., claim=f"NAD {nad_id} config: {nad['spec']['config']}")
    """
    status: dict = {}  # TODO: k8s_client.CustomObjectsApi() for Multus NAD
    return [make_evidence("get_network_attachment_status", "network", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"NAD {nad_id} status: {status}")] if status else []


# ---------------------------------------------------------------------------
# 7. Source side — pick ONE of the two blocks below depending on migration
#    source (VMware vCenter vs bare-metal). Keep both registered only if you
#    support both source types; otherwise delete the one you don't need.
# ---------------------------------------------------------------------------

@read_only_tool
def get_vcenter_events(vm_id: str, time_range: str) -> list[Evidence]:
    """Use when target-side evidence (control-plane, storage, network,
    compute) does not explain the failure — this checks whether the
    problem originated on the source (VMware) side instead: snapshot
    issues, permission errors, VM in an invalid state at the time of
    migration. This is the tool most likely to be missing early on; a
    target-side-only diagnosis should be treated as incomplete until this
    layer has also been checked or is confirmed unavailable. Input source:
    trigger — vm_id comes directly from the trigger payload.

    Pseudocode:
        events = vcenter_client.query_events(entity=vm_id, start=time_range.start, end=time_range.end)
        for e in events:
            yield make_evidence(..., claim=f"{e.eventTypeId}: {e.fullFormattedMessage}")
    """
    events: list[dict] = []  # TODO: vCenter API / govmomi-equivalent client
    return [make_evidence("get_vcenter_events", "source", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"vCenter event for VM {vm_id}: {e}") for e in events]


@read_only_tool
def get_source_vm_config(vm_id: str) -> list[Evidence]:
    """Use alongside get_vcenter_events when the failure might stem from
    the source VM's own configuration (unsupported disk type, snapshot
    present, guest tools state) rather than anything on the target side.
    Input source: trigger — vm_id comes directly from the trigger payload.

    Pseudocode:
        vm = vcenter_client.get_vm(vm_id)
        config = {"disk_type": vm.disk_type, "has_snapshot": vm.snapshot is not None,
                  "guest_tools_status": vm.guest.toolsStatus}
        yield make_evidence(..., claim=f"Source VM {vm_id} config: {config}")
    """
    config: dict = {}  # TODO: vCenter API
    return [make_evidence("get_source_vm_config", "source", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Source VM {vm_id} config: {config}")] if config else []


@read_only_tool
def get_bmc_events(host_id: str, time_range: str) -> list[Evidence]:
    """Bare-metal equivalent of get_vcenter_events — use in place of it when
    the migration source is a bare-metal host rather than VMware. Returns
    Redfish/iLO/iDRAC event log entries for the source host around the
    failure window. Input source: trigger — host_id comes directly from
    the trigger payload for bare-metal-sourced migrations.

    Pseudocode:
        events = redfish_client.get_event_log(host_id, start=time_range.start, end=time_range.end)
        for e in events:
            yield make_evidence(..., claim=f"{e.severity}: {e.message}")
    """
    events: list[dict] = []  # TODO: Redfish/iLO/iDRAC API client
    return [make_evidence("get_bmc_events", "source", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"BMC event for host {host_id}: {e}") for e in events]


# ---------------------------------------------------------------------------
# 8. Change correlation
# ---------------------------------------------------------------------------

@read_only_tool
def get_recent_cluster_changes(time_range: str) -> list[Evidence]:
    """Use when no single-layer root cause is emerging and the timing is
    suspicious — checks for cluster upgrades, node drains, or config
    changes around the failure window that could correlate. Input source:
    trigger — time_range is derived from the trigger payload's failed_at
    timestamp; takes no other incident-specific input.

    Pseudocode:
        changes = audit_log_client.query(kinds=["ClusterVersion", "MachineConfig", "Node"],
                                          verb="update", time_range=time_range)
        for c in changes:
            yield make_evidence(..., claim=f"{c.kind}/{c.name} changed at {c.timestamp} by {c.user}")
    """
    changes: list[dict] = []  # TODO: cluster audit log / GitOps deploy history
    return [make_evidence("get_recent_cluster_changes", "cluster_health", RELIABILITY_TIERS["LOGS"],
                           f"Cluster change: {c}") for c in changes]


# ---------------------------------------------------------------------------
# 8b. Third-party services and change management — new layers, added to
# support team routing (see migration_failure_agent_routing.py). Neither
# existed before; auth/registry failures and CHG-window mismatches were
# previously invisible, buried as unstructured text inside other tools'
# claims if visible at all.
# ---------------------------------------------------------------------------

@read_only_tool
def get_third_party_service_status(service: str, time_range: str) -> list[Evidence]:
    """Use when a failure looks like an auth, secrets, or image-pull problem
    rather than a migration-specific one — e.g. pod logs mention 401/403,
    token expiry, or 'ImagePullBackOff' against an internal registry.
    service must be one of: 'vault', 'entraid', 'nexus'. Tag
    layer=third_party so it routes to the third-party integrations team,
    not SRE or Build. Input source: derived — service is inferred by the
    reason node from the error text in other evidence (e.g. a 401 from
    Vault implies service='vault'), not from the trigger payload.

    Pseudocode:
        status = third_party_client.get_health(service, window=time_range)
        yield make_evidence(..., layer="third_party",
                             claim=f"{service}: {status.summary} (last_error={status.last_error})")
    """
    if service not in ("vault", "entraid", "nexus"):
        return []
    status: dict = {}  # TODO: per-service health/auth-log client call
    if not status:
        return []
    return [make_evidence("get_third_party_service_status", "third_party", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"{service}: {status.get('summary')} (last_error={status.get('last_error')})")]


@read_only_tool
def get_change_request_status(migration_id: str) -> list[Evidence]:
    """Use early, alongside control-plane checks — a migration executed
    outside its approved CHG window, or against an unapproved change, is a
    process-compliance root cause distinct from any technical layer, and
    nothing else checks for it. Returns the linked CHG's approval status
    and approved window. Input source: trigger — migration_id comes
    directly from the trigger payload.

    Pseudocode:
        chg = change_mgmt_client.get_linked_change(migration_id)
        in_window = chg.approved and chg.window_start <= now() <= chg.window_end
        yield make_evidence(..., claim=f"CHG {chg.id}: approved={chg.approved}, "
                                        f"in_window={in_window} ({chg.window_start}-{chg.window_end})")
    """
    chg: dict = {}  # TODO: change management system API call
    if not chg:
        return []
    return [make_evidence("get_change_request_status", "control_plane", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"CHG {chg.get('id')}: approved={chg.get('approved')}, "
                           f"in_window={chg.get('in_window')} ({chg.get('window_start')}-{chg.get('window_end')})")]


# ---------------------------------------------------------------------------
# 8c. Topology/config — network map, storage map, provider state. These are
# EXPORTED PERIODICALLY to Splunk via OpenTelemetry (a scheduled CronJob,
# decoupled from this agent's runtime), not fetched live per-call — that's
# what makes them fast. Storage class capacity is exported as an OTel
# gauge metric on a shorter cycle since it's genuinely numeric; the rest
# are structured log records refreshed every 5-15 minutes. Freshness here
# is "recent enough for config," never "must be this instant" — that's the
# dividing line from get_pvc_status/get_change_request_status above, which
# stay live API calls because staleness there could mislead an active
# investigation.
# ---------------------------------------------------------------------------

@read_only_tool
def get_network_map_status(migration_id: str) -> list[Evidence]:
    """Use when a network-mapping mismatch is a live hypothesis and you need
    the FULL source-network -> target-NAD mapping, not just one NAD's
    status (see get_network_attachment_status for that). Reads from Splunk
    (OTel-exported NetworkMap CR snapshot, ~5-15 min freshness), not a live
    K8s call — fast. Input source: trigger — migration_id comes directly
    from the trigger payload.

    Pseudocode:
        spl = f'index=cluster_config sourcetype=networkmap migration_id="{migration_id}"
               | head 1'
        row = splunk.jobs.oneshot(spl)
        yield make_evidence(..., reliability_tier="CURRENT_HEALTH_API",
                             claim=f"NetworkMap: {row.mappings}, valid={row.valid}, "
                                   f"last_synced={row.export_timestamp}")
    """
    row: dict = {}  # TODO: Splunk query against the OTel-exported networkmap index
    if not row:
        return []
    return [make_evidence("get_network_map_status", "network", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"NetworkMap: {row.get('mappings')}, valid={row.get('valid')}, "
                           f"last_synced={row.get('export_timestamp')}")]


@read_only_tool
def get_storage_map_status(migration_id: str) -> list[Evidence]:
    """Use when a storage-mapping mismatch is a live hypothesis — the FULL
    source-datastore -> target-storage-class mapping. Reads from Splunk
    (OTel-exported StorageMap CR snapshot), same freshness/speed profile
    as get_network_map_status. Input source: trigger — migration_id comes
    directly from the trigger payload.

    Pseudocode: same shape as get_network_map_status, sourcetype=storagemap.
    """
    row: dict = {}  # TODO: Splunk query against the OTel-exported storagemap index
    if not row:
        return []
    return [make_evidence("get_storage_map_status", "storage", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"StorageMap: {row.get('mappings')}, valid={row.get('valid')}, "
                           f"last_synced={row.get('export_timestamp')}")]


@read_only_tool
def get_provider_status(provider_id: str) -> list[Evidence]:
    """Use when you need to know which source provider (vCenter/oVirt/
    OpenStack/host) a migration is tied to, and whether that provider's
    connection is healthy — e.g. a burst of failures across many
    migrations might trace back to one degraded Provider connection
    rather than per-VM issues. Reads from Splunk (OTel-exported Provider
    CR snapshot). Input source: evidence — provider_id is normally read
    from a provider reference in a prior get_migration_plan_status claim,
    not from the trigger payload directly.

    Pseudocode:
        spl = f'index=cluster_config sourcetype=provider provider_id="{provider_id}" | head 1'
        row = splunk.jobs.oneshot(spl)
        yield make_evidence(..., claim=f"Provider {provider_id} ({row.type}): "
                                        f"connected={row.connected}, last_sync={row.last_sync}")
    """
    row: dict = {}  # TODO: Splunk query against the OTel-exported provider index
    if not row:
        return []
    return [make_evidence("get_provider_status", "control_plane", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Provider {provider_id} ({row.get('type')}): "
                           f"connected={row.get('connected')}, last_sync={row.get('last_sync')}")]


@read_only_tool
def get_cluster_topology_snapshot(cluster_id: str) -> list[Evidence]:
    """Use for a broad picture of what's available on this cluster —
    storage classes and their current capacity (OTel gauge metric,
    1-5 min freshness), CSI driver versions, NAD inventory, node counts.
    Useful early when a cluster-wide correlation burst is detected (see
    migration_failure_agent_correlation.py) and you want cluster context
    without querying each subsystem individually. Input source: trigger —
    cluster_id comes directly from the trigger payload.

    Pseudocode:
        spl = f'index=cluster_metrics cluster_id="{cluster_id}" earliest=-15m
               | stats latest(*) by metric_name'
        rows = splunk.jobs.oneshot(spl)
        yield make_evidence(..., claim=f"Cluster {cluster_id} topology: {rows}")
    """
    rows: list[dict] = []  # TODO: Splunk query against OTel-exported topology metrics/logs
    return [make_evidence("get_cluster_topology_snapshot", "cluster_health", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Topology signal: {r}") for r in rows]


# ---------------------------------------------------------------------------
# 8d. Post-migration validation, cluster/namespace capacity — the 3 gaps
# identified in review: nothing previously checked whether a "completed"
# migration actually produced a bootable VM, and no tool answered "does
# this cluster/namespace actually have room" beyond storage specifically.
# ---------------------------------------------------------------------------

@read_only_tool
def get_target_vm_boot_status(vm_id: str) -> list[Evidence]:
    """Use when a migration reports COMPLETED but the failure being
    investigated is actually "VM won't boot" — a distinct failure class
    from a failed migration itself, with no other tool covering it.
    Returns the target VMI's guest-agent connection status and last
    console state. Input source: trigger — vm_id comes directly from the
    trigger payload (this tool applies to the post-migration failure path,
    not the standard mid-migration one, so the triggering event for this
    case is a boot-failure report rather than migration.failed).

    Pseudocode:
        vmi = k8s.get_custom_object(group="kubevirt.io", version="v1",
                                     namespace=NS, plural="virtualmachineinstances", name=vm_id)
        guest_agent_connected = vmi["status"].get("conditions", [])
        yield make_evidence(..., claim=f"VMI {vm_id}: phase={vmi['status']['phase']}, "
                                        f"guest_agent={guest_agent_connected}")
    """
    vmi: dict = {}  # TODO: KubeVirt VMI status query
    if not vmi:
        return []
    return [make_evidence("get_target_vm_boot_status", "compute", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"VMI {vm_id}: phase={vmi.get('phase')}, guest_agent={vmi.get('guest_agent')}")]


@read_only_tool
def get_cluster_resource_capacity(cluster_id: str) -> list[Evidence]:
    """Use when a scheduling-related failure has no clear reason in events
    — checks whether the cluster actually has CPU/memory headroom to place
    the VM, distinct from get_storage_class_health (storage-specific) and
    get_cluster_health (operator/control-plane health, not capacity).
    Reads from Splunk (OTel-exported gauge, same pattern as storage
    capacity) rather than a live metrics-server call. Input source:
    trigger — cluster_id comes directly from the trigger payload.

    Pseudocode:
        spl = f'index=cluster_metrics metric_name IN ("cpu_allocatable_percent",
              "memory_allocatable_percent") cluster_id="{cluster_id}" | tail 1 by metric_name'
        rows = splunk.jobs.oneshot(spl)
        yield make_evidence(..., claim=f"Cluster {cluster_id} capacity: {rows}")
    """
    rows: list[dict] = []  # TODO: Splunk query against OTel-exported capacity gauges
    if not rows:
        return []
    return [make_evidence("get_cluster_resource_capacity", "cluster_health", RELIABILITY_TIERS["CURRENT_HEALTH_API"],
                           f"Cluster {cluster_id} capacity: {r}") for r in rows]


@read_only_tool
def get_namespace_quota_status(namespace: str) -> list[Evidence]:
    """Use alongside get_namespace_events when a scheduling/admission
    failure might be quota-related — states the actual headroom number
    directly rather than leaving the agent to infer it from an event
    message alone. Live K8s API call (ResourceQuota/LimitRange are cheap
    to query and change infrequently enough that freshness isn't the
    concern here — this is about getting the exact number, not speed).
    Input source: trigger — namespace comes from migration metadata in the
    trigger payload, same as get_namespace_events.

    Pseudocode:
        rq = k8s.list_namespaced_resource_quota(namespace=namespace)
        for item in rq.items:
            yield make_evidence(..., claim=f"ResourceQuota {item.metadata.name}: "
                                            f"used={item.status.used}, hard={item.status.hard}")
    """
    quotas: list[dict] = []  # TODO: K8s ResourceQuota/LimitRange query
    return [make_evidence("get_namespace_quota_status", "cluster_health", RELIABILITY_TIERS["LIVE_TELEMETRY"],
                           f"ResourceQuota {q.get('name')}: used={q.get('used')}, hard={q.get('hard')}")
            for q in quotas]


# ---------------------------------------------------------------------------
# 9. Knowledge & memory — advisory only, never proof on their own
# ---------------------------------------------------------------------------

@read_only_tool
def search_sre_tracker_db(fingerprint: str) -> list[Evidence]:
    """Query the SRE tracker's confirmed-fix table (sre_tracker_fixes) by
    symptom fingerprint. Use this EARLY among the advisory tools — a
    confirmed prior fix is the strongest non-live signal available. Returns
    only confirmed=true rows; tag reliability_tier=CONFIRMED_FIX and include
    fix_id/ticket_ref in the claim text. An empty result is a normal,
    common outcome — it means no team member has confirmed-fixed this exact
    fingerprint before, not that something is wrong. Never treat a match
    here as sufficient on its own — it must be corroborated by at least one
    live-layer tool before it can raise confidence.

    Input source: derived — fingerprint is built by build_symptom_fingerprint()
    from the trigger payload plus evidence gathered so far, not read
    directly from either.

    Pseudocode:
        rows = db.execute(
            "SELECT fix_id, root_cause, resolution_steps, ticket_ref "
            "FROM sre_tracker_fixes WHERE symptom_fingerprint = %s AND confirmed = true",
            (fingerprint,))
        for r in rows:
            yield make_evidence(..., reliability_tier="CONFIRMED_FIX",
                                 claim=f"Fix {r.fix_id}: {r.root_cause} - {r.resolution_steps}")
    """
    # TODO: SELECT fix_id, root_cause, resolution_steps, ticket_ref
    #       FROM sre_tracker_fixes WHERE symptom_fingerprint = %s AND confirmed = true
    rows: list[dict] = []
    return [
        make_evidence("search_sre_tracker_db", "known_issues", RELIABILITY_TIERS["CONFIRMED_FIX"],
                       f"Tracker fix {r['fix_id']}: {r['root_cause']} — {r['resolution_steps']} (ref {r['ticket_ref']})")
        for r in rows
    ]


@read_only_tool
def search_product_documentation(query: str) -> list[Evidence]:
    """Query the RHOKP offline knowledge portal (pgvector RAG over
    solutions, articles, product articles, errata, and CVEs) plus MTV/OCV/OCP
    docs. Results are NOT all equally trustworthy — tag by content_type:
    'errata' and 'cve' hits (official Red Hat published defect/security
    records) get reliability_tier=VENDOR_ADVISORY; 'solution', 'article',
    and 'product_article' hits get reliability_tier=HISTORICAL_RAG (generic
    guidance, weakest tier). Neither tier confirms a fix was applied in
    THIS environment before — that's what search_sre_tracker_db is for.
    An empty result is normal — fall back to live-layer evidence only.

    Input source: derived — query is composed by the reason node from the
    goal and current evidence, not a fixed field from the trigger payload.

    Pseudocode:
        query_vec = embed(query)
        results = pgvector_client.similarity_search(query_vec, top_k=5)
        for r in results:  # r.content_type in {solution, article, product_article, errata, cve}
            tier = "VENDOR_ADVISORY" if r.content_type in ("errata", "cve") else "HISTORICAL_RAG"
            yield make_evidence(..., reliability_tier=tier,
                                 claim=f"[{r.content_type}:{r.ref}] {r.text}")
    """
    # TODO: results = pgvector_client.similarity_search(query, top_k=5)
    #       each result expected to carry a content_type field:
    #       'solution' | 'article' | 'product_article' | 'errata' | 'cve'
    results: list[dict] = []  # [{"content_type": ..., "text": ..., "ref": ...}]
    evidence: list[Evidence] = []
    for r in results:
        tier = (RELIABILITY_TIERS["VENDOR_ADVISORY"]
                if r["content_type"] in ("errata", "cve")
                else RELIABILITY_TIERS["HISTORICAL_RAG"])
        claim = f"[{r['content_type']}:{r.get('ref', '')}] {r['text']}"
        evidence.append(make_evidence("search_product_documentation", "knowledge_docs", tier, claim))
    return evidence


@read_only_tool
def get_similar_migrations(fingerprint: str) -> list[Evidence]:
    """Query the organizational-memory vector store for past migration
    incidents with a similar symptom fingerprint, confirmed correct or
    corrected by a human after resolution. Advisory only, same as
    search_sre_tracker_db — a similar past incident can raise a hypothesis,
    never confirm one by itself.

    Input source: derived — same fingerprint as search_sre_tracker_db,
    built by build_symptom_fingerprint().

    Pseudocode:
        query_vec = embed(fingerprint)
        matches = vector_store.similarity_search(query_vec, top_k=5, min_score=0.75)
        for m in matches:
            yield make_evidence(..., claim=f"Similar incident {m.incident_id}: {m.root_cause} "
                                            f"(was_correct={m.was_correct})")
    """
    matches: list[dict] = []  # TODO: vector store similarity search, top-k with threshold
    return [
        make_evidence("get_similar_migrations", "historical", RELIABILITY_TIERS["HISTORICAL_RAG"],
                       f"Similar incident {m['incident_id']}: {m['root_cause']} (was_correct={m['was_correct']})")
        for m in matches
    ]


def get_previous_resolution(incident_id: str) -> Optional[dict]:
    """Not bound as an LLM tool — used internally by the memory write-back
    pipeline (Phase 6) to fetch a specific past incident's confirmed
    resolution by ID, not by similarity search. Read-only."""
    ...  # SELECT * FROM memory_resolutions WHERE incident_id = %s
    return None


def record_confirmed_resolution(incident_id: str, fingerprint: str, diagnosis: dict,
                                 was_correct: bool, actual_resolution: Optional[str] = None) -> None:
    """Not bound as an LLM tool — the write-back half of memory. Called
    exactly once per incident, only after a human confirms or corrects the
    diagnosis in the portal (never automatically on COMPLETED). This is
    what makes get_similar_migrations() and, indirectly, future SRE
    tracker entries useful — without this call, memory never grows.

    Input source: incident_id/diagnosis/fingerprint from this run's state;
    was_correct/actual_resolution from the human's confirmation action in
    the portal UI — never inferred by the agent itself.

    Pseudocode:
        embedding = embed(fingerprint + diagnosis["root_cause"])
        existing = vector_store.find_near_duplicate(embedding, threshold=0.92)
        if existing:
            existing.occurrence_count += 1
            vector_store.update(existing)
        else:
            vector_store.upsert({
                "incident_id": incident_id,
                "embedding": embedding,
                "root_cause": diagnosis["root_cause"],
                "evidence_refs": diagnosis["evidence_refs"],
                "confidence_at_time": diagnosis["confidence_band"],
                "was_correct": was_correct,
                "actual_resolution": actual_resolution or diagnosis["recommended_action"],
                "occurrence_count": 1,
                "timestamp": now(),
            })
        # was_correct=False entries are kept but excluded from get_known_fix-style
        # ranking — surfaced only as "previously ruled out", never as a lead.
    """
    ...  # embed + upsert per pseudocode above; dedup by near-duplicate check first


# ---------------------------------------------------------------------------
# Tool registry — single source of truth for what's bound to the LLM
# ---------------------------------------------------------------------------

TOOLS: list[Callable] = [
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
    get_vcenter_events,        # remove if bare-metal only
    get_source_vm_config,      # remove if bare-metal only
    get_bmc_events,            # remove if VMware only
    get_recent_cluster_changes,
    get_third_party_service_status,
    get_change_request_status,
    get_network_map_status,
    get_storage_map_status,
    get_provider_status,
    get_cluster_topology_snapshot,
    get_target_vm_boot_status,
    get_cluster_resource_capacity,
    get_namespace_quota_status,
    search_sre_tracker_db,
    search_product_documentation,
    get_similar_migrations,
]


def get_tool_by_name(name: str) -> Optional[Callable]:
    """Used by execute_tool in the graph to dispatch the tool call the
    `reason` node's LLM output named."""
    return next((t for t in TOOLS if t.__name__ == name), None)

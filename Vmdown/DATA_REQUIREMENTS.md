# DATA REQUIREMENTS: what the agent needs to see

A checklist of the metrics, logs, Kubernetes objects and events the VMDown agent needs, what you probably already have, and what to procure. Use it in **Phase 1 (data discovery)**: mark every row Present, Partial or Missing, then decide: procure, accept the gap, or work around it.

**You do not have to wait for everything.** Phases 0 to 3 can start today. The agent is designed to say "unverified" for anything it cannot see. Collect the missing data in parallel and add the matching tools as it arrives (Phase 4b).

**Priority**
- **P0**: needed for credible diagnoses of the four v1 scenarios.
- **P1**: large accuracy gain. Collect before shadow mode if possible.
- **P2**: later or optional.

**Caveat:** metric names change between versions and distributions. The names below are starting points from public docs. Verify each on your cluster.

---

## 1. Prometheus metrics

### 1.1 KubeVirt (VM and VMI state)
| Item (verify exact name) | Why it matters | Priority |
|---|---|---|
| `kubevirt_vmi_phase_count` (per phase and node) | VMI phase by node, shows how many VMIs are Pending, Scheduling, Running, Failed | P0 |
| `kubevirt_vm_*_status_last_transition_timestamp_seconds` (error, starting, migrating, non-running, running) | When a VM entered each state, and for how long | P0 |
| Migration counters (`kubevirt_vmi_migrations_pending / scheduling / running / succeeded / failed`; older versions used `kubevirt_migrate_vmi_*`) | Migration-related failures | P0 |
| `kubevirt_nodes_with_kvm` and per-node KVM resource | "Won't start: no KVM capable node" | P0 |
| virt-controller, virt-handler, virt-api, virt-operator up, leader and ready status | KubeVirt control-plane health | P0 |
| `kubevirt_memory_delta_from_requested_bytes` | Memory pressure and launcher overhead problems | P1 |
| `kubevirt_number_of_vms` | Denominator for "how many VMs exist" | P1 |
| VMI vCPU wait, memory and storage IOPS/latency metrics | Performance degradation vs outage | P1 |
| CDI/DataVolume metrics (pending DataVolumes, importer restarts) | Storage and import stuck | P1 |

### 1.2 kube-state-metrics (Kubernetes object state)
| Item | Why | Priority |
|---|---|---|
| Pod phase, container restarts, container waiting reason, last terminated reason (OOMKilled) | Launcher crashes, image pulls, OOM | P0 |
| Pod info with node name | VM to node mapping | P0 |
| Node conditions, node unschedulable, node taints | Node unresponsive, drains, cordons | P0 |
| PVC phase, PV phase, StorageClass info | Storage stuck | P0 |
| Node labels (zone, region, rack if labeled) | Topology fallback for correlation | P0 |
| Pod deletion timestamp | Stuck Terminating | P1 |
| VolumeAttachment metrics | Multi-Attach and stale attachment cases | P1 |
| **Custom-resource state** for VirtualMachine, VirtualMachineInstance, DataVolume (phase, conditions, run strategy) | Default kube-state-metrics does not expose these. Without them VM-level state is only inferred | P1 |

### 1.3 node-exporter (node health)
| Item | Why | Priority |
|---|---|---|
| CPU, memory, load, disk space and inodes, disk I/O | Node exhaustion | P0 |
| Network errors, drops, traffic per interface | Basic network health view | P0 |
| Boot time | Detect unexpected node reboots | P1 |
| OOM-kill counters, pressure stall information | Node-level memory pressure | P1 |

### 1.4 OpenShift platform and scrape health
| Item | Why | Priority |
|---|---|---|
| `up` and last scrape time for every target, per cluster | **Blind-spot detection**: a cluster that stopped reporting is itself evidence | P0 |
| Firing alerts (the `ALERTS` series) | Correlate with existing platform alerts | P0 |
| ClusterOperator and ClusterVersion status | Upgrades and degraded operators | P1 |
| MachineConfigPool status (updating, degraded) | Drains and node updates in progress | P1 |
| API server and etcd health | Cluster-wide control plane outages | P1 |
| Kubelet and container runtime metrics | Node agent health | P1 |

### 1.5 Storage (Dell CSM and Portworx)
**Dell CSM for Observability** is an OpenTelemetry agent that exposes array-level capacity and performance metrics (bandwidth, IOPS, response time) for Prometheus. Note that OpenShift's built-in monitoring does not accept external metrics, so it needs a separate Prometheus stack. Confirm yours is feeding the Prometheus your MCP reads.

| Item | Why | Priority |
|---|---|---|
| Dell: volume IOPS, bandwidth, latency; pool capacity; PV to array volume mapping | Storage latency and capacity; topology to backend | P0 |
| Dell CSM Resiliency status (if used) | Node-failure handling of stateful pods | P1 |
| Portworx: node status, cluster size and quorum, KVDB health | Node and cluster health | P0 |
| Portworx: pool status, pool write latency, pool available bytes, cluster disk available/total | Pool problems and capacity | P0 |
| Portworx: volume state/status, attached state, replication status, read/write latency | Per-volume problems | P0 |
| CSI sidecar operation durations and errors (provisioner, attacher, resizer) | Attach, mount and provisioning failures | P1 |

Portworx exposes its metrics endpoint on port 9001 (17001 on OpenShift). It exposes many metrics by default, so use an allowlist of the ones above to control volume.

### 1.6 Network
| Item | Why | Priority |
|---|---|---|
| OVN-Kubernetes and Multus health metrics | Pod and VM network failures | P1 |
| Synthetic probes (blackbox) to VM IP or port | Tells guest or network failure from platform failure | P2 |
| Switch or fabric metrics | Network domain outages | P2 |

### 1.7 Hardware
| Item | Why | Priority |
|---|---|---|
| BMC/Redfish exporter metrics (temperature, PSU, disk and memory health) | Explains node failures | P2 |

---

## 2. Logs (Splunk)

You have all container logs. Verify they actually cover these, with enough retention and with **previous-container logs** kept for crash loops.

| Item | Why | Priority |
|---|---|---|
| `virt-launcher` pods in all VM namespaces | VM start failures, QEMU and libvirt errors, migration errors | P0 |
| `openshift-cnv` namespace: virt-handler, virt-controller, virt-api, virt-operator, CDI pods | KubeVirt control plane | P0 |
| CSI driver pods (Dell, Portworx, sidecars) | Attach, mount, provisioning errors | P0 |
| Machine-config and other operator namespaces | Drains and upgrades (inferred signals today) | P1 |
| OVN-Kubernetes and Multus pods | Network faults | P1 |
| **Node journald: kubelet, CRI-O, kernel** (OOM, I/O errors, NIC link down) | Node unresponsive, stuck terminating, container runtime hangs | P1 |
| Storage array or Portworx alerts and events | Backend failures | P1 |
| Kubernetes API audit logs | Who stopped or deleted a VM | P2 |
| Hardware (iDRAC/BMC) logs | Hardware faults | P2 |
| Guest OS logs and guest-agent heartbeat | Guest hangs vs platform failures | P2 |
| Network device logs | Network domain outages | P2 |

**Checks:** logs carry consistent `cluster`, `namespace`, `pod`, `node` fields; timestamps are in sync; retention covers at least the shadow-mode period.

---

## 3. Kubernetes events and objects (OTel Kubernetes objects receiver to Splunk)

This is the biggest single gap. Events are short-lived on the cluster, so they must be streamed to keep history from before a failure. Run the receiver as a **single replica** to avoid duplicates.

### 3.1 Events
| Item | Why | Priority |
|---|---|---|
| All Kubernetes events, cluster-wide (watch mode) | Scheduling failures, attach and mount errors, evictions, node not ready, probe failures | P1 |

### 3.2 Objects (state and history)
| Object | Fields that matter | Priority |
|---|---|---|
| VirtualMachine | status, conditions, run strategy, printable status | P1 |
| VirtualMachineInstance | phase, conditions, node, migration state, guest agent connected | P1 |
| VirtualMachineInstanceMigration | phase, failure details | P1 |
| DataVolume | phase, conditions | P1 |
| PVC, PV, StorageClass, VolumeAttachment | phase, attach state, binding | P1 |
| Pod (virt-launcher, importer, CSI pods) | phase, deletion timestamp, finalizers, restart reasons | P1 |
| Node | conditions, taints, labels | P1 |
| KubeVirt / HyperConverged CR | Operator health | P1 |
| MachineConfigPool, ClusterOperator, ClusterVersion | Upgrade and drain state | P1 |
| Node Health Check and remediation resources (if used) | Whether automatic node recovery is configured and active | P2 |
| NetworkAttachmentDefinition | VM network config | P2 |

**Collection rules**
- **Never collect Secrets**, and avoid ConfigMaps unless needed.
- Strip noisy fields (for example managed fields). Filter namespaces where it makes sense.
- Use watch mode for events. For objects, watch or pull at a sensible interval, since volume grows fast.
- Custom resources (VM, VMI, DataVolume) need their API group set. Check that your collector version supports them.
- Send to a dedicated Splunk index with a defined retention.
- Needs list and watch permission on these resources, so get it security-reviewed.

---

## 4. Metadata and context (not telemetry, still needed)

| Item | Why | Priority |
|---|---|---|
| Topology map: cluster to datacenter, storage backend, network domain, rack | Correlation across VMs and clusters. Your existing app is partial, so measure coverage | P0 |
| `cluster` label on every metric and log | Without it cross-cluster correlation is unreliable | P0 |
| VM inventory with owner, application, criticality | Prioritization and blast radius | P1 |
| Change and maintenance records (Argo CD, ServiceNow changes, planned maintenance windows) | "What changed before the failure" | P1 |
| Historical incidents with real causes (ServiceNow tickets) | Seeds the incident history and evals | P1 |
| Known-issue and runbook documents | Seeds skills | P2 |

---

## 5. Collection hygiene

- **Consistent labels:** `cluster`, `namespace`, `node`, `pod`, `vm` named the same in metrics, logs and events.
- **Time sync:** NTP everywhere. Wrong clocks ruin timelines and correlation.
- **Scrape interval:** know your interval. Short events can fall between scrapes.
- **Retention:** keep enough history for baselines and shadow mode. Agree a number with the platform owner.
- **Cardinality and cost:** allowlist metrics, cap log volume, filter events. Measure before turning everything on.
- **Collector health:** monitor the collectors and receivers themselves, so a broken pipeline is not mistaken for a healthy cluster.

---

## 6. Status table (fill in during Phase 1)

| Item | Source | Priority | Status (Present / Partial / Missing) | Exact name or location found | Decision (Procure / Accept gap / Workaround) | Owner |
|---|---|---|---|---|---|---|
| | | | | | | |

**How to verify an item:** query it through the Prometheus or Splunk MCP for one known VM and one known node, and confirm the labels (cluster, namespace, node) are present and the data is recent.

## 7. Suggested order to procure

1. **Now (parallel to Phases 0 to 3):** scrape-health and `cluster` label consistency, kube-state custom-resource state for VM, VMI and DataVolume, Portworx and Dell metric allowlists, topology coverage check.
2. **Before shadow mode (Phase 4b):** Kubernetes events and object state through the OTel receiver, node journald logs, firing alerts, operator and machine-config logs.
3. **Later:** audit logs, hardware metrics and logs, synthetic probes, guest-level signals, network device data.

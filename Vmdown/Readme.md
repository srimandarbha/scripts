Biggest gaps to procure, in order
1. Kubernetes events and object state (P1). This is the largest gap. Events are short-lived on the cluster, so you need to stream them to Splunk through the OTel Kubernetes objects receiver. Collect:
Events: all events, cluster-wide, in watch mode.
Objects: VM, VMI, VMI migration, DataVolume, PVC, PV, VolumeAttachment, Pod, Node, MachineConfigPool and ClusterOperator.
Never collect Secrets.
2. VM-level state in Prometheus (P1). KubeVirt already gives you kubevirt_vmi_phase_count, kubevirt_nodes_with_kvm and kubevirt_memory_delta_from_requested_bytes. It also exposes last-transition timestamps for error, starting, migrating and running states, plus migration counters such as kubevirt_vmi_migrations_failed. Default kube-state-metrics does not expose VM, VMI or DataVolume state, so add its custom-resource state config.  (github.com +2)
3. Node journald logs (P1). kubelet, CRI-O and kernel logs aren't in container logs. You need them for node-unresponsive and stuck-terminating cases.
4. Scrape health, per cluster (P0). The agent must notice when a cluster stops reporting, because a datacenter or network outage can look like silence. Also make sure a consistent cluster label is on every metric and log.
5. Storage metrics (P0). Dell CSM Observability collects array-level metrics so they can be exported into a Prometheus database. One catch: OpenShift's monitoring forbids external metrics in its own Prometheus, so confirm Dell's metrics land in the Prometheus your MCP actually reads. For Portworx, allowlist the key metrics: the endpoint is on port 9001 (17001 on OpenShift) and it exposes a very large number of series by default. The ones to keep cover node status, KVDB health, pool status, pool write latency, and volume state and latency.  (title | linkTitle | weight | Description | +2)
6. Platform signals (P1). Firing alerts, ClusterOperator and MachineConfigPool status, and API server and etcd health. These explain drains and upgrades without guessing.
Later (P2)
Audit logs, hardware (iDRAC) metrics and logs, synthetic probes to VM IPs, guest-agent signals, and network device data.

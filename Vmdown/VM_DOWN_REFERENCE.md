# Reference: Common VM-down scenarios in OpenShift Virtualization / KubeVirt

Purpose: source material for writing the agent's skill files (Phase 5). Everything here is paraphrased from public Red Hat, KubeVirt and community sources (listed at the end).

**Caveats**
- Many Red Hat Knowledgebase articles are subscriber-only. For those I could only see the title and symptoms, not the full resolution. Treat the "typical fix" for such items as general practice and verify it before putting it in a skill.
- Fixes listed here are for the **engineer**. The v1 agent only recommends them and never performs them.
- Metric and log names must be verified on your cluster in Phase 1.

---

## 1. VM won't start / stuck Starting

**Symptoms**
- VM status Starting, Provisioning or ErrorUnschedulable. `virt-launcher` pod Pending, CrashLoopBackOff, ImagePullBackOff or ContainerCreating.
- KubeVirt alerts: VM stuck in starting state (>5 min); VM unhealthy with no VMI (>10 min); VM with a VMI stuck on a node (>5 min).

**Common causes**
- Scheduling: not enough `devices.kubevirt.io/kvm` (no KVM-capable node, nodes not labeled), node selector or affinity mismatch, taints not tolerated, insufficient CPU or memory, `kubevirt-node-labeller` pods not running.
- Configuration: a missing PriorityClass, missing or wrong network device or attachment, invalid vNIC model (tap device creation fails after changing the model).
- Image/pod: image pull problems, missing binary in the launcher image.
- Storage: PVC not found, DataVolume error or still importing, PVC Pending.
- Runtime on a specific node: QEMU/libvirt errors such as failing to create a native AIO context (resource limit on some nodes).
- Guest-level: "No bootable device" (bad or empty disk or import source). The VM runs but the OS cannot boot, so infrastructure looks healthy.

**What to check**
- VM and VMI conditions and phase, pod phase, scheduling messages, namespace events.
- `virt-launcher`, `virt-controller` and `virt-handler` logs.
- Node resources, taints, labels, KVM resource availability.
- PVC and DataVolume state.

**Typical fixes (engineer)**
- Correct the VM spec (priority class, network, resources, selectors).
- Add or label capable nodes, free resources, fix taints or tolerations.
- Fix storage or the image source.
- Only restart or recreate after the cause is understood.

**Agent can see via:** VMI phase metrics, pod phase and restart metrics, launcher/controller logs in Splunk, node metrics.
**Agent cannot see:** Kubernetes events and exact scheduler messages, unless they also appear in a log.

---

## 2. PVC / DataVolume / storage stuck

**Symptoms**
- PVC Pending, DataVolume Pending/PendingPopulation/ImportInProgress for long, importer pod Pending or Unschedulable, VM stuck Starting waiting on a disk.
- Pod events with FailedAttachVolume or Multi-Attach error.

**Common causes**
- No default StorageClass, or StorageClass issues. With WaitForFirstConsumer, population may wait until a consumer pod exists.
- Importer pod cannot be scheduled, import is very slow and times out, importer OOM-killed.
- Leftover temporary clone PVCs after failed clones.
- ReadWriteOnce volume still attached to a failed or crashed node, so it cannot attach elsewhere (Multi-Attach).
- Backend CSI or array problems (provisioning, attach or mount failures, latency).

**What to check**
- PVC, PV and DataVolume phase and conditions, StorageClass, volume attachments.
- Importer pod status and logs, CSI controller and node plugin logs.
- Backend health (here Dell CSM and Portworx metrics).
- Whether other VMs on the same backend are affected.

**Typical fixes (engineer)**
- Set or correct the StorageClass, resolve backend capacity or health, retry the import.
- For stale attachments: recover or remove the failed node, clear stale attachments carefully. Prefer ReadWriteMany for VMs that must migrate or fail over.

**Agent can see via:** PVC phase metrics, Dell CSM and Portworx metrics, CSI and CDI container logs.
**Agent cannot see:** VolumeAttachment objects and events directly.

---

## 3. Node unresponsive / VMs down because a node failed

**Symptoms**
- Node NotReady or Unknown, unreachable taint, `virt-handler` heartbeat stale, many VMIs on that node unhealthy or unreachable.

**Behavior worth knowing**
- By default Kubernetes marks a node Unknown and adds the unreachable taint after about 50 seconds without check-in.
- `virt-handler` updates a heartbeat on the node. If it is older than about 5 minutes, KubeVirt marks the node as not schedulable for VMs.
- If the whole node is unresponsive, simply deleting the VMI will not remove it.
- Without Node Health Check plus a remediation operator (Self Node Remediation or Fence Agents Remediation) and a suitable run strategy such as `Always`, VMs stay down until the node returns. Fencing must confirm the old node is truly off before restarting the VM elsewhere, to protect data.

**Common causes**
- Power outage or hardware failure, kubelet or CRI-O hung, network partition, kernel panic, resource exhaustion.

**What to check**
- Node conditions and taints, `virt-handler` pod and logs, node-exporter metrics (CPU, memory, disk, network), which VMIs ran there, whether remediation is configured.

**Typical fixes (engineer)**
- Restore or reboot the node (or fence it), verify storage detaches, then let VMs restart. Configure NHC plus SNR or FAR for future events.

**Agent can see via:** node condition metrics, node-exporter, `virt-handler` pod metrics and logs.
**Agent cannot see:** hardware logs (iDRAC), kernel/kubelet/CRI-O system logs.

---

## 4. VM stuck Stopping / Terminating

**Symptoms**
- VM shows Stopping or Terminating; `virt-launcher` pod stuck Terminating for a long time.

**Common causes**
- Long termination grace period (Windows templates have used up to an hour, Linux far less) when the guest does not shut down gracefully.
- Container runtime not responding (kill/stop calls time out), pod cannot be killed.
- Node unhealthy or just recovered from an outage.
- Block devices from inside the guest visible and active on the node (for example guest LVM), blocking teardown.
- Migration leftovers, where both source and target pods remain after a migration (seen in specific versions).
- Deleting a VM and recreating one with the same name while the old pod still terminates can attach the new VM to the old VMI.

**What to check**
- Pod deletion timestamp, grace period, finalizers, node health, runtime errors in pod kill events and logs, any recent migration.

**Typical fixes (engineer)**
- Wait out the grace period if the guest is shutting down, or force-delete the pod once safe. Restart CRI-O on the node if it is hung. Never force-delete before confirming the node and storage state, as it can risk data.

**Agent can see via:** pod phase and age metrics, launcher logs.
**Agent cannot see:** finalizers and deletion timestamps (object state).

---

## 5. VM crashes or restarts from memory pressure (OOM)

**Symptoms**
- VM suddenly powers off or restarts, `virt-launcher` OOMKilled, memory cgroup out-of-memory kernel messages.

**Common causes**
- The launcher pod's memory overhead (launcher, libvirt, QEMU) exceeds what was added to the pod's memory request/limit. Problem is worse with hard limits, large-memory guests and long uptime.
- Guest consuming all of its memory including cache, pushing the pod past its cgroup limit.
- Node-level memory pressure.
- Importer pods OOM-killed during provisioning (a separate case).

**Typical fixes (engineer)**
- Raise the pod memory request/limit headroom, review limits on the VM, relieve node pressure, update to a version that fixes the overhead calculation.

**Agent can see via:** container memory metrics, OOMKilled status, `kubevirt_memory_delta_from_requested_bytes`, node memory.

---

## 6. VM down after or during live migration, drain or upgrade

**Symptoms**
- VMIM objects Failed, VM down or stuck after a drain or workload update, node stuck draining on a VM, both pods remaining after migration.

**Common causes**
- libvirt migration errors (client socket closed, unknown error), CPU feature mismatch between nodes after an upgrade, configuration that blocks migration (for example certain CDROM/config volumes), target pod shut down mid-migration, storage or hotplug disk issues, version-specific bugs.
- Failure reasons are often only in the launcher logs, not in the migration object.
- Evictions stuck during drains, shown in machine-config-controller logs.
- Upgrades trigger workload-update migrations that can fail in bulk.

**What to check**
- Migration phase counts and timelines, source and target launcher logs, node CPU labels and capabilities, drain and machine-config logs.

**Typical fixes (engineer)**
- Resolve the blocking configuration, align node CPU models, retry migration, stop and start only if safe, apply the fixed version.

**Agent can see via:** migration metrics, launcher and `virt-controller` logs, machine-config-controller logs, node unschedulable metrics.

---

## 7. Multiple VMs down at once

Usually one shared cause:
- A node failure or drain, a storage backend problem or latency, a network problem on a node, an operator upgrade or workload update, a cluster component such as `virt-controller` or `virt-handler` failing, or a bad change applied to many VMs by a script or template.

What to check: group affected VMs by node, storage class or backend, namespace and start time. A single shared factor means one incident, not many.

---

## Tools support engineers typically use

| Tool | Used for |
|---|---|
| OpenShift web console (VM Overview, Metrics, Events, Diagnostics tabs) | Quick status, events, metrics, logs |
| `oc` / `kubectl` | get and describe VM, VMI, pod, VMIM, DataVolume, PVC, node, events |
| `oc logs` | `virt-launcher`, `virt-handler`, `virt-controller`, importer, CSI logs |
| `virtctl` | Console access, start/stop/restart, migrate |
| must-gather (OpenShift Virtualization image) | Collecting data for Red Hat support |
| `oc debug node` | Looking at node-level state, container runtime, kernel messages |
| Prometheus alerts and metrics | Phase counts, error status timestamps, migration counts, resource use |
| Splunk or log stack | Container logs over time |
| Storage vendor tools | Backend health (Dell, Portworx) |
| KubeVirt runbooks | Documented steps per alert |

Log verbosity for OpenShift Virtualization pods can be increased when more detail is needed.

---

## Notes for the agent design

- Several important root causes live in **Kubernetes events and object state** (scheduler messages, FailedAttachVolume, finalizers). They are not in your current data, so the agent should mark those as "unverified" or "requires engineer check".
- Distinguish **infrastructure failures** from **guest failures** (no bootable device, guest hang). The VM may be healthy at the platform level.
- Be explicit about **safety** in every skill: no restart, force-delete or VMI deletion before node and storage state are understood.
- Good extra skills after the first four: stuck Stopping/Terminating, VM OOM, migration/drain failure, post-upgrade failures.

---

## Sources

- KubeVirt runbooks: VirtualMachineStuckInUnhealthyState, VirtualMachineStuckOnNode, KubeVirtVMStuckInStartingState, KubeVirtVMStuckInErrorState (kubevirt.io/monitoring/runbooks)
- KubeVirt user guide: Unresponsive nodes (kubevirt.io/user-guide/cluster_admin/unresponsive_nodes)
- KubeVirt metrics list (kubevirt.io/monitoring/metrics.html)
- Red Hat OpenShift Virtualization documentation: Support and troubleshooting (docs.redhat.com)
- Red Hat OpenShift documentation: Virtual machine recovery from node failures; Troubleshooting storage issues (multi-attach)
- Red Hat Developer article: Protecting virtual machines from storage and secondary network node failures (Oct 2025)
- Red Hat Knowledgebase (titles and symptoms only, subscriber content): access.redhat.com/node/5106121, /solutions/7123356, /node/6974118, /solutions/6999757, /solutions/7005997, /solutions/7118238, /node/6996262, /node/7114706, /solutions/7074021
- Red Hat Jira (CNV): 17517, 32771, 15130, 29868, 21714, 69512, 67948, 25029, 16324, 20801, 28628, 32118, 81643, 35728, 74856, 71962
- IBM Support and community articles on RWO multi-attach errors

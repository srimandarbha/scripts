# Appendix: Data Sources, Metrics, Logs, and Commands for the Upgrade and Maintenance Skills

Companion to: upgrade-maintenance-skills-spec.md (section 13 coverage matrix)
Purpose: for every check, the exact object path, metric name, alert name, log search, and cluster command, so you can run each check by hand before coding it.

Verification codes:
- V: VERIFIED. Stated in Red Hat OpenShift Virtualization documentation or the KubeVirt metrics reference reviewed for this appendix
- S: SECONDARY. Standard Kubernetes or OpenShift API behaviour, or a field seen in a CRD or example, not quoted directly from the Virtualization docs. Confirm with the command.
- U: UNVERIFIED. Expected from design. Confirm before coding.

Rule for every check: run the command on a lab or non-production cluster first. Record the actual output in section 9. A missing series or object is "not determined", never healthy.

---

## 1. Global objects and fields

| Object | Field or condition | Command to check | Healthy value | Verification |
|---|---|---|---|---|
| ClusterVersion `version` | status.history[0].state, status.conditions (Progressing, Available, Failing) | `oc get clusterversion version -o yaml` | state Completed, Available True, Failing False | S |
| ClusterVersion update progress | Progressing condition message | `oc adm upgrade` | No stalled message | S |
| ClusterOperator | status.conditions (Available, Progressing, Degraded) | `oc get co` and `oc get co <name> -o yaml` | Available True, Progressing False, Degraded False | S |
| ClusterOperator metric | cluster_operator_up, cluster_operator_conditions | PromQL: `cluster_operator_conditions{condition="Degraded",status="True"} == 1` | Empty result | S |
| MachineConfigPool | status.conditions type Updating and Degraded; status.machineCount, updatedMachineCount, readyMachineCount, unavailableMachineCount, degradedMachineCount | `oc get mcp` and `oc get mcp <pool> -o yaml` | UPDATED True, UPDATING False, DEGRADED False; updatedMachineCount equals machineCount | S (field names from CRD description) |
| MachineConfigPool pause | spec.paused | `oc get mcp <pool> -o jsonpath='{.spec.paused}'` | Expected to be false outside an EUS step | S |
| Node | status.conditions Ready, MemoryPressure, DiskPressure; spec.unschedulable; spec.taints | `oc get nodes` and `oc describe node <name>` | Ready, no pressure, schedulable unless under maintenance | S |
| Node metric | kube_node_status_condition | PromQL: `kube_node_status_condition{condition="Ready",status="true"} == 0` | Empty result | S |
| Subscription (OLM) | spec.installPlanApproval | `oc get sub -n openshift-cnv -o yaml` | Automatic | V (approval recommended, docs) |
| ClusterServiceVersion | name and status.phase | `oc get csv -n openshift-cnv` | Name kubevirt-hyperconverged-operator.v<version>, phase Succeeded | V |
| InstallPlan | status.phase | `oc get installplan -n openshift-cnv` | Complete | S |
| HyperConverged `kubevirt-hyperconverged` | status.conditions (type and status); condition ReconcileComplete | `oc get hco kubevirt-hyperconverged -n openshift-cnv -o json \| jq -r '.status.conditions[] \| {type,status}'` | ReconcileComplete True | V (command and condition from docs) |
| HyperConverged versions | status.versions (name operator) | `oc get hco kubevirt-hyperconverged -n openshift-cnv -o json \| jq .status.versions` | version equals target | V |
| HyperConverged workload update | spec.workloadUpdateStrategy | `oc get hco kubevirt-hyperconverged -n openshift-cnv -o jsonpath='{.spec.workloadUpdateStrategy}'` | Matches approved setting | V |
| HyperConverged overcommit | spec.higherWorkloadDensity.memoryOvercommitPercentage | `oc get -n openshift-cnv HyperConverged kubevirt-hyperconverged -o jsonpath="{.spec.higherWorkloadDensity.memoryOvercommitPercentage}"` | Matches approved value | V |
| virt-handler DaemonSet | status.desiredNumberScheduled, numberReady | `oc get ds virt-handler -n openshift-cnv` | Equal | S (name from alert runbook list, V) |
| virt-controller and virt-operator Deployments | status.availableReplicas | `oc get deploy -n openshift-cnv` | Equal to spec.replicas | S |
| wasp-agent DaemonSet | status.numberReady | `oc get ds wasp-agent -n openshift-cnv` | Equal to desired | V (documented in the overcommit procedure) |

---

## 2. Virtualization metrics (Prometheus)

Metric names below are from the KubeVirt metrics reference reviewed. Labels can vary by version; confirm with the discovery command in section 10.

| Metric | Type | Meaning | Use | Verification |
|---|---|---|---|---|
| kubevirt_vmi_phase_count | Gauge | Sum of VMIs per phase and node (Pending, Scheduling, Scheduled, Running, Succeeded, Failed, Unknown) | Stuck-VMI counts; baseline B5 | V |
| kubevirt_vmi_number_of_outdated | Gauge | VMIs not running the newest virt-launcher version | Outdated count (R11, B6, V7, S7) | V |
| kubevirt_vmi_migrations_in_pending_phase | Gauge | Pending migrations | Triage B4 | V |
| kubevirt_vmi_migrations_in_scheduling_phase | Gauge | Scheduling migrations | Triage B4 | V |
| kubevirt_vmi_migrations_in_running_phase | Gauge | Running migrations | Progress tracking | V |
| kubevirt_vmi_migration_failed | Gauge | Indicates a failed migration | T5, I4 | V |
| kubevirt_vmi_migration_succeeded | Gauge | Indicates a successful migration | Validation V10 | V |
| kubevirt_vmi_migration_phase_transition_time_from_creation_seconds | Histogram | Migration phase durations | Migration duration baseline (open item) | V |
| kubevirt_vm_starting_status_last_transition_timestamp_seconds | Counter | Last transition to Starting | Stuck starts | V |
| kubevirt_vm_non_running_status_last_transition_timestamp_seconds | Counter | Last transition to paused or stopped | Unintended stops (V9) | V |
| kubevirt_vm_error_status_last_transition_timestamp_seconds | Counter | Last transition to error | V9 | V |
| kubevirt_hyperconverged_operator_health_status | Gauge | 0 healthy, 1 warning, 2 critical (recording rule) | R7, B2, V3 | V |
| kubevirt_hco_system_health_status | Gauge | Input to the health rule above | Triage B6 | S (referenced in the recording rule) |
| kubevirt_allocatable_nodes | Gauge | Allocatable nodes | Readiness R5 | V |
| kubevirt_virt_operator_ready | Gauge | Ready virt-operator pods | Validation V6 | V |
| kubevirt_virt_controller_ready_status | Gauge | Ready virt-controller | Validation | V |
| kubevirt_virt_api_ready_status | Gauge | Ready virt-api | Validation | V |
| kubevirt_info | Gauge | Version information | Version gate | V |
| kubevirt_vm_info | Gauge | VM information | Inventory | V |
| kube_poddisruptionbudget_status_pod_disruptions_allowed | Gauge | Disruptions allowed per PDB | R12, S5 | S (kube-state-metrics name; confirm). Earlier specs used a different name; correct it. |
| kube_node_status_condition | Gauge | Node conditions | R5, E-checks | S |
| kube_daemonset_status_number_ready | Gauge | DaemonSet ready pods | R8, V6 | S |
| kube_daemonset_status_desired_number_scheduled | Gauge | DaemonSet desired pods | R8, V6 | S |
| cluster_operator_up, cluster_operator_conditions | Gauge | ClusterOperator state | R4, S2, V4 | S |
| cluster_version | Gauge | ClusterVersion | Triage S1 | S |
| kubevirt_vmi_storage_flush_requests_total | Counter | Storage flush requests | Not used in upgrade checks | V (listed; not needed) |

Example PromQL (verify each returns data on the cluster before use):

```promql
kubevirt_vmi_number_of_outdated
sum by (phase) (kubevirt_vmi_phase_count)
sum(kubevirt_vmi_migrations_in_pending_phase) + sum(kubevirt_vmi_migrations_in_scheduling_phase)
kube_poddisruptionbudget_status_pod_disruptions_allowed == 0
kube_daemonset_status_desired_number_scheduled{namespace="openshift-cnv",daemonset="virt-handler"} - kube_daemonset_status_number_ready{namespace="openshift-cnv",daemonset="virt-handler"}
```

Note: the Red Hat metrics page warns that metric names may change between versions. Re-verify before each release.

---

## 3. Alerts (use as triggers, and as cross-checks)

Names are from the OpenShift Virtualization runbook index (V). Each runbook URL is in the openshift/runbooks repository on GitHub.

| Alert | Relevant to | Use |
|---|---|---|
| OutdatedVirtualMachineInstanceWorkloads | Tracker, validation | Outdated VMIs after update |
| VMCannotBeEvicted | Drain, tracker | Drain blocked by a VM |
| VirtualMachineStuckOnNode | Drain stall | VM stuck on a node |
| VirtLauncherPodsStuckFailed | Triage | Launcher failure during update |
| VirtualMachineStuckInUnhealthyState | Triage, validation | VM unhealthy after update |
| KubeVirtVMIExcessiveMigrations | Tracker | Repeated migrations of one VMI |
| VirtHandlerDaemonSetRolloutFailing | Readiness R8, triage | virt-handler rollout |
| HCOOperatorConditionsUnhealthy | Readiness R7, triage B6 | HCO conditions |
| HCOInstallationIncomplete | Validation V3 | HCO install incomplete |
| VirtOperatorDown, NoReadyVirtController, LowVirtControllersCount | Validation V6 | Control plane |
| KubeVirtNoAvailableNodesToRunVMs | Sequencing | No schedulable node |
| VMStorageClassWarning, CDINoDefaultStorageClass | Readiness R9 | Storage class problems |
| PersistentVolumeFillingUp | Readiness | Storage capacity |
| NodeSwapping, NodeHighSwapActivity | Overcommit checks | Swap pressure (alert names from the overcommit procedure, V) |

Alerts to suppress during a planned window must be decided with the owner. Silencing changes Alertmanager state, so it is out of scope for read-only skills.

---

## 4. Skill-by-skill appendix

Columns: ID, source type, exact name or path, command to run, healthy, trigger, verification.

### 4.1 upgrade-readiness

| ID | Source | Exact name or path | Command | Healthy | Trigger | V |
|---|---|---|---|---|---|---|
| R1 | Object | ClusterVersion version; CSV kubevirt-hyperconverged-operator.v<ver> | `oc get clusterversion; oc get csv -n openshift-cnv` | CNV minor matches OCP minor | Mismatch | V |
| R2 | Reference file | compatibility.yaml (reviewed) | Read file | Target pair listed | Not listed | V (requirement) |
| R3 | Object | Subscription spec.installPlanApproval | `oc get sub -n openshift-cnv -o jsonpath='{.items[*].spec.installPlanApproval}'` | Automatic | Manual | V |
| R4 | Object and metric | ClusterOperator conditions; cluster_operator_conditions | `oc get co` | No Degraded True | Degraded or unavailable | S |
| R5 | Object and metric | Node Ready; kube_node_status_condition | `oc get nodes` | All Ready | Any NotReady | S |
| R6 | Object | MCP conditions Updating, Degraded; machineCount fields | `oc get mcp` | UPDATING False, DEGRADED False | Degraded or already updating | S |
| R7 | Object and metric | HCO condition ReconcileComplete; kubevirt_hyperconverged_operator_health_status | Command in section 1 | ReconcileComplete True; health 0 | False or health 1 or 2 | V |
| R8 | Object and metric | DaemonSet virt-handler desired vs ready | `oc get ds virt-handler -n openshift-cnv` | Equal | Not equal | S |
| R9 | Object | VM spec evictionStrategy; PVC storageClassName; StorageClass provisioner | `oc get vm -A -o yaml`; `oc get sc` | No hostpath VM with LiveMigrate | Found | V (hostpath rule) |
| R10 | Object | VMI condition LiveMigratable reason; PVC accessModes | `oc get vmi -A -o yaml`; `oc get pvc -A` | Migratable | False with reason | V |
| R11 | Metric and label | kubevirt_vmi_number_of_outdated; label kubevirt.io/outdatedLauncherImage | `oc get vmi -A -l kubevirt.io/outdatedLauncherImage` | Count known | Information | V |
| R12 | Metric | kube_poddisruptionbudget_status_pod_disruptions_allowed | `oc get pdb -A` (status.disruptionsAllowed) | Greater than 0 on drain nodes | Zero | S |
| R13 | Object | HCO spec.workloadUpdateStrategy | Command in section 1 | Approved method set | Not approved | V |
| R14 | Object | MCP spec.paused | `oc get mcp -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.paused}{"\n"}{end}'` | Matches plan | Mismatch | S |
| R15 | Skill | node-failure-capacity result | Existing skill | PASS | FAIL | Existing |
| R16 | Object | VM spec machineType | `oc get vm -A -o jsonpath='{range .items[*]}...'` | Information | Information | V |
| R17 | Object | VolumeSnapshot, VirtualMachineRestore status | `oc get volumesnapshot -A; oc get vmrestore -A` | None in progress | In progress | U |
| R18 | External | Change record | Change system | Present | Missing | Gap |

### 4.2 baseline-capture

| ID | Source | Exact name or path | Command | Note |
|---|---|---|---|---|
| B1 | Object | ClusterVersion history; CSV version | `oc get clusterversion version -o json \| jq .status.history` | Store full history |
| B2 | Object | ClusterOperator conditions | `oc get co -o json` | Store all three conditions |
| B3 | Object | MCP status counts and conditions | `oc get mcp -o json` | Store counts and paused |
| B4 | Object | Node name, roles label, Ready, unschedulable, taints | `oc get nodes -o json` | Roles: node-role.kubernetes.io/* labels |
| B5 | Metric | kubevirt_vmi_phase_count by phase and node | PromQL in section 2 | Store as snapshot |
| B6 | Label | kubevirt.io/outdatedLauncherImage | `oc get vmi -A -l kubevirt.io/outdatedLauncherImage -o name` | List names |
| B7 | Object | LiveMigratable reason; PVC accessModes; hostpath | `oc get vmi -A -o json`; `oc get pvc -A -o json` | Reason field, not message |
| B8 | Object | VM runStrategy and machineType | `oc get vm -A -o json` | Store |
| B9 | Object | PDB disruptionsAllowed | `oc get pdb -A -o json` | Store |
| B10 | Object | HCO workloadUpdateStrategy and approval | Section 1 | Store |
| B11 | Object and metric | virt-handler desired and ready | `oc get ds virt-handler -n openshift-cnv -o json` | Store |
| B12 | Alerts | Firing alert names | Alertmanager API or console | Names only |
| B13 | Object | VolumeSnapshot, VirtualMachineRestore | `oc get volumesnapshot,vmrestore -A` | Store |

### 4.3 post-upgrade-validation

| ID | Source | Exact name or path | Command | Expected | V |
|---|---|---|---|---|---|
| V1 | Object | ClusterVersion version state | `oc get clusterversion` | Completed at target | S |
| V2 | Object | CSV phase | `oc get csv -n openshift-cnv` | Succeeded | V |
| V3 | Object | HCO ReconcileComplete | Section 1 command | True, message "Reconcile completed successfully" | V |
| V4 | Object and metric | ClusterOperator Degraded | `oc get co` | No Degraded | S |
| V5 | Object | Node Ready; MCP updated counts | `oc get nodes`; `oc get mcp` | All Ready; updatedMachineCount equals machineCount | S |
| V6 | Object and metric | virt-handler, virt-controller, virt-api ready | `oc get ds,deploy -n openshift-cnv` | Desired equals ready | S |
| V7 | Label and metric | kubevirt.io/outdatedLauncherImage list | `oc get vmi -A -l kubevirt.io/outdatedLauncherImage -o name` | Equals the R10 not-migratable list | V |
| V8 | Metric | kubevirt_vmi_phase_count | PromQL | Equals baseline B5, after planned changes | V |
| V9 | Metric and object | kubevirt_vm_non_running_status_last_transition_timestamp_seconds; VM printableStatus | PromQL; `oc get vm -A` | No unexpected stop | V |
| V10 | Metric | kubevirt_vmi_migration_succeeded | PromQL | Test migration succeeded (owner approved) | V |
| V11 | Alerts | Firing alert names | Alertmanager | Same names as B12 | U |
| V12 | Object | VM machineType | `oc get vm -A -o json` | Same as B8, or listed | V |

### 4.4 workload-update-tracker

| ID | Question | Source | Command | Expected | V |
|---|---|---|---|---|---|
| T1 | Live-migratable? | VMI condition LiveMigratable, reason | `oc get vmi <name> -o json \| jq '.status.conditions[] \| select(.type=="LiveMigratable")'` | status True | V |
| T2 | Eviction strategy | VM spec.template.spec.evictionStrategy; HCO spec | `oc get vm <name> -o jsonpath='{.spec.template.spec.evictionStrategy}'` | LiveMigrate or LiveMigrateIfPossible | V |
| T3 | Access mode | PVC accessModes | `oc get pvc <name> -o jsonpath='{.spec.accessModes}'` | ReadWriteMany for migration | V |
| T4 | Hostpath | StorageClass provisioner | `oc get sc <name> -o jsonpath='{.provisioner}'` | Not hostpath, or owner-approved | V |
| T5 | Migration state | VMIM phase | `oc get vmim -A -l kubevirt.io/vmi-name=<name>` (label verify) | Succeeded or none | U (label to verify) |
| T6 | Target capacity | Events for the migration | `oc get events -n <ns> --field-selector involvedObject.name=<name>` | No scheduling failure | S |
| T7 | Host device | VMI spec hostDevices | `oc get vmi <name> -o jsonpath='{.spec.domain.devices.hostDevices}'` | Empty | V (HostDevice blocks migration) |
| T8 | Update method | HCO workloadUpdateStrategy | Section 1 | Includes LiveMigrate | V |

Reason-to-check mapping: NOT_LIVE_MIGRATABLE_RWO (T1 false, T3 ReadWriteOnce), NOT_LIVE_MIGRATABLE_HOSTPATH (T1 false, T4 hostpath), EVICTION_STRATEGY_BLOCKS (T2 LiveMigrate, T1 false), MIGRATION_PENDING (T5 Pending or Scheduling, or metric kubevirt_vmi_migrations_in_pending_phase), MIGRATION_FAILED (T5 Failed or kubevirt_vmi_migration_failed = 1), UPDATE_METHOD_NOT_ENABLED (T8), HOST_DEVICE (T7).

### 4.5 upgrade-stall-triage

| ID | Source | Exact name or path | Command | Branch |
|---|---|---|---|---|
| S1 | Object | ClusterVersion conditions, history | `oc adm upgrade`; `oc get clusterversion -o yaml` | All |
| S2 | Object and metric | ClusterOperator conditions | `oc get co` | B1 |
| S3 | Object | MCP conditions and counts; node conditions | `oc get mcp -o yaml`; `oc get nodes` | B2 |
| S4 | Events | Node events for drain and reboot | `oc get events -A --field-selector reason=Drain...` | B3 (reason names: verify) |
| S5 | Object and metric | PDB disruptionsAllowed | `oc get pdb -A` | B3 |
| S6 | Object | VMIM list | `oc get vmim -A` | B4 |
| S7 | Metric | kubevirt_vmi_number_of_outdated over time | PromQL with range: `kubevirt_vmi_number_of_outdated[30m]` | B4, B7 |
| S8 | Object | HCO conditions | Section 1 | B6 |
| S9 | Object | Hostpath VMs | Section 4.4 T4 | B5 |
| S10 | Splunk | Error text, see section 5 | Splunk search | Confirm |

Note on S4: event reason names for drains are not in the sources reviewed. Find them on the cluster by reproducing a drain in a lab, then record them here.

### 4.6 drain-sequencing

| ID | Source | Command | Note |
|---|---|---|---|
| Input | Your existing drain readiness result | Read from its decision record | Do not re-run its checks |
| Capacity | node-failure-capacity | Existing skill | PASS required per step |
| Node VM list | VMI by node | `oc get vmi -A -o wide` (NODE column) | Use the NODE column; verify it on your version |
| Maintenance | NodeMaintenance (object name to verify) | `oc get nodemaintenance` | Verify the kind exists on your cluster |

### 4.7 eus-control

| ID | Source | Command | Expected |
|---|---|---|---|
| E1 | HCO spec.workloadUpdateStrategy | Section 1 | No automatic methods during the EUS step (V) |
| E2 | MCP spec.paused for worker pools | `oc get mcp worker -o jsonpath='{.spec.paused}'` | true during the step (V for the requirement; field S) |
| E3 | Reference path | compatibility.yaml | Intermediate version listed |
| E4 | Change record | Gap | Owner and unpause time recorded |
| E5 | Derived | From E1 and E2 | No migration or eviction during the step |

### 4.8 owner-decision-package

No cluster data of its own. It reads the decision records from other skills and the owner map. Options for each blocker come from the Red Hat update documentation (hostpath workaround, live migration method, PDB, paused pools).

### 4.9 change-package

No new checks. It collects the decision records, baseline ID, and approvals. Its checks are the same as the upstream skills.

---

## 5. Log searches (Splunk)

Field names are placeholders. Confirm them in the Splunk UI before use. The search returns error text; classification uses the pattern catalog in shared/log_patterns.yaml.

| Purpose | Scope | Search template | Notes |
|---|---|---|---|
| MCO errors | Upgrade window | `search index=<idx> cluster="<c>" namespace="openshift-machine-config-operator" (level="error" OR log_level="error") \| stats count by container, message` | Needs approved window |
| virt-handler errors on a node | Node | `search index=<idx> cluster="<c>" namespace="openshift-cnv" container="virt-handler" node="<n>" (level="error" OR log_level="error") \| stats count by message` | Same as the node-scope tool |
| virt-controller errors | Upgrade window | `search index=<idx> cluster="<c>" namespace="openshift-cnv" container="virt-controller" (level="error" OR log_level="error") \| stats count by message` | |
| virt-operator and HCO errors | Upgrade window | `search index=<idx> cluster="<c>" namespace="openshift-cnv" container IN ("virt-operator","hyperconverged-cluster-operator") (level="error" OR log_level="error") \| stats count by container, message` | Container names to verify |
| Migration errors | VM or window | `search index=<idx> cluster="<c>" namespace="<ns>" "<vmi>" (migration OR migrate) (level="error" OR log_level="error") \| stats count by message` | |

Pattern catalog entries to add after the first lab run: MCO drain errors, PDB eviction refusals, migration target errors. Each needs a verification status and a source.

---

## 6. Kubernetes and OpenShift reference links

- ClusterVersion and ClusterOperator: OpenShift Container Platform "Updating clusters" documentation for your release
- MachineConfigPool: OpenShift Container Platform "Machine configuration" documentation, section on pool status and pausing
- PodDisruptionBudget: Kubernetes documentation, "Pod Disruption Budgets" (kubernetes.io)
- Node drain: Kubernetes documentation, "Safely drain a node" (kubernetes.io)
- kube-state-metrics: github.com/kubernetes/kube-state-metrics, documentation folder, for exact metric names and labels

---

## 7. Corrections to the earlier specifications

| Item | Earlier text | Correct text |
|---|---|---|
| PDB metric | kube_poddisruptionbudget_status_disruptions_allowed (in the plan, appendix draft) | kube_poddisruptionbudget_status_pod_disruptions_allowed (S, confirm) |
| HCO namespace in community docs | `-n kubevirt` | Use `-n openshift-cnv` on OpenShift; the Red Hat command uses openshift-cnv |
| MCP fields | "status fields unverified" | status.conditions (Updating, Degraded) and count fields; verify with `oc get mcp -o yaml` |
| Outdated VMI check | Label only | Label kubevirt.io/outdatedLauncherImage plus metric kubevirt_vmi_number_of_outdated |
| Migration counts | Generic "migration status" | Metrics kubevirt_vmi_migrations_in_pending_phase, _in_scheduling_phase, _in_running_phase, kubevirt_vmi_migration_failed |

---

## 8. Sources

Verified
- KubeVirt metrics reference (metrics.md in kubevirt/kubevirt docs), for metric names and types
- KubeVirt monitoring documentation (kubevirt.io/monitoring/metrics.html)
- OpenShift Virtualization monitoring chapter (docs.redhat.com, virtualization monitoring, 4.x and OpenShift Dedicated)
- OpenShift Virtualization runbooks index (docs.redhat.com, virt-runbooks, 4.21 and 5.0 pages)
- HCOOperatorConditionsUnhealthy runbook (kubevirt.io/monitoring/runbooks)
- HyperConverged recording rule source (kubevirt/hyperconverged-cluster-operator, pkg/monitoring/rules/recordingrules/operator.go)
- OpenShift Virtualization installation verification (openshift-docs, CSV and HCO condition commands)
- OpenShift Virtualization overcommit procedure (openshift-docs, wasp-agent and HyperConverged setting)
- Bugzilla 2151170 (memory alert and HCO JSON patch method, for the patch path only)

Secondary
- MachineConfigPool CRD description and status fields (from the CRD published by the OpenShift release)
- OpenShift performance profile debugging docs (MCP degraded output format), for the oc get mcp column names

Not verified in this appendix
- Exact Splunk field names in your index
- Exact event reasons for node drain in OpenShift 4.x
- The label used to find VMIM objects for one VMI
- Any metric name not listed in section 2 as V
- OpenShift 5.0 metric and object names

---

## 9. Lab verification record (fill in)

| Item | Command or query used | Actual output (paste) | Matches this appendix? (Y/N) | Date | Tester |
|---|---|---|---|---|---|
| CSV phase | | | | | |
| HCO ReconcileComplete | | | | | |
| MCP fields | | | | | |
| ClusterOperator conditions | | | | | |
| kubevirt_vmi_number_of_outdated | | | | | |
| kube_poddisruptionbudget name | | | | | |
| virt-handler DaemonSet ready | | | | | |
| VMIM label for one VMI | | | | | |
| Drain event reasons | | | | | |
| Splunk field names | | | | | |

---

## 10. Discovery commands for the lab

Metric names (confirm the ones marked S or U):

```bash
PROM=$PROM_URL
curl -s -H "Authorization: Bearer $PROM_TOKEN" "$PROM/api/v1/label/__name__/values" \
  | tr ',' '\n' | grep -E "kubevirt_vmi_(number_of_outdated|migrations|phase_count)|kubevirt_hyperconverged|kube_poddisruptionbudget|cluster_operator|kube_daemonset"
```

Object fields (confirm each path you rely on):

```bash
oc get mcp worker -o yaml | sed -n '/status:/,$p'
oc get co kube-apiserver -o yaml | sed -n '/status:/,$p'
oc get hco kubevirt-hyperconverged -n openshift-cnv -o json | jq '.status.conditions, .spec.workloadUpdateStrategy'
oc get vmi -A -l kubevirt.io/outdatedLauncherImage -o name
oc get pdb -A -o json | jq '.items[] | {ns:.metadata.namespace, name:.metadata.name, allowed:.status.disruptionsAllowed}'
```

Log scope check:

```bash
oc get pods -n openshift-cnv -l kubevirt.io=virt-handler -o wide
oc logs -n openshift-cnv <virt-handler-pod> -c virt-handler --since=1h | grep -i error | head
```

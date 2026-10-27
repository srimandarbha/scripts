# SPEC: VMDown Triage Agent (v1)

## 1. Purpose

When a VM on an OpenShift Virtualization (OCV) cluster is reported down, the agent takes a JSON alert, gathers evidence from Prometheus and Splunk, and produces an evidence-backed diagnosis with a suggested next step. It saves every incident to Postgres so future incidents can be compared with past ones.

The agent **diagnoses only. It never changes anything on the cluster.**

**Related documents:** `PLAN.md` (build order), `DESIGN.md` (architecture, data contracts, decisions), `SECURITY.md` (threat model and controls), `EVALUATION.md` (evals, agent tests, shadow-mode rollout), `VM_DOWN_REFERENCE.md` (failure scenarios for writing skills), `DATA_REQUIREMENTS.md` (metrics, logs, Kubernetes objects and events to procure, with priorities).

## 2. Goals and non-goals

**Goals (v1)**
- Accept a pasted JSON alert with: VM name, namespace, cluster, severity, timestamp.
- Enrich it with VM details from Splunk (guest OS, recent errors).
- Handle four failure types: VM won't start, node unresponsive, PVC/storage stuck, multiple VMs down.
- Produce a structured report: probable cause, evidence, confidence, missing evidence, next step.
- Save every incident to Postgres.
- Look up similar past incidents and show them in the report.
- Group related alerts (same node, storage backend, network domain, cluster or datacenter) and investigate the shared cause once (Phase 8b).
- Let an engineer record whether the diagnosis was right.
- Run as a bounded agent: the LLM chooses which evidence tools to call, within code-enforced limits.
- Log every agent step (tool, arguments, result summary) with the incident.
- Track hypotheses: the agent keeps a list of candidate causes (open, supported, rejected) and updates it after each tool result.
- Cite evidence by ID: every tool result gets an ID (E1, E2, ...) and the diagnosis must cite IDs.
- Run a critic pass: a second LLM call reviews the draft diagnosis against the evidence before the report is shown.
- Keep the agent's role, rules and stop conditions in an editable prompt file (`prompts/agent_system.md`).

**Non-goals (v1)**
- No remediation, restarts or any write action on the cluster in v1. A controlled plan for later is in section 16.
- No Kafka trigger yet (later, it will feed the same JSON shape).
- No direct Kubernetes API or `oc` access.
- No web UI, no ServiceNow/Slack integration.
- No embeddings or pgvector (planned for later).
- No hardware-health or network-log tools. No Kubernetes-event, object-history or node-log tools until that data is collected (see "Planned data upgrade" and Phase 4b).
- No classes or design patterns. Plain functions and dictionaries only.

## 3. Environment and constraints

| Item | Detail |
|---|---|
| Language | Python 3 (functions and dicts, minimal dependencies) |
| LLM | Company LLM gateway, OpenAI-compatible API (`openai` package with custom `base_url`) |
| Metrics | Prometheus MCP server (HTTP, URL + token) |
| Logs | Splunk MCP server (HTTP, URL + token) |
| Storage | Postgres: new schema (e.g. `vmdown_agent`) in an existing database |
| Topology | Read-only copy (UAT) of the topology application's database, synced about 3 times (confirm schedule); data is partial and can be hours old |
| Test setup | Test cluster where failures can be reproduced on purpose |
| Run mode | Command line in v1. A service or worker in production (Phase P3) |

### Data actually available

| Source | Available | Not available |
|---|---|---|
| Prometheus | KubeVirt VM/VMI metrics, kube-state-metrics (pods, nodes, PVCs), node-exporter (CPU, disk, network), storage metrics from Dell CSM and Portworx | |
| Splunk | All container logs | Kubernetes events, hardware logs, network logs, maintenance/upgrade events |

**Key limitation:** VM/VMI state and cluster activity can only be inferred from metrics and container logs. The agent must say "insufficient evidence" when it cannot confirm something.

**Maintenance/upgrade signals** are inferred indirectly: node unschedulable metrics, node-not-ready transitions, and operator or node-agent container logs (drain, upgrade, machine-config activity). Reports must label these as "inferred".

### Planned data upgrade (recommended, outside the agent code)

Kubernetes events, object state and node system logs should come from your existing OTel pipeline, not from playbooks:
- **Events and object state:** add the Kubernetes objects receiver to the cluster collector. Watch events, and watch or pull VM, VMI, DataVolume, PVC and Node objects (custom resources need their API group set). Run it as a single replica to avoid duplicates, filter noisy fields and namespaces, and send it to a dedicated Splunk index through the existing OTel to Kafka to Splunk path.
- **Node system logs:** collect journald (kubelet, CRI-O, kernel) with the Splunk OTel Collector.
- Needs read (list/watch) permission on those resources, so get it security-reviewed.

Why this beats running `oc` through playbooks: it keeps history from *before* the failure (events are short-lived on the cluster), it works even if the node or AAP is down, it is fast and cheap to query, and it uses the same Splunk tool path as the logs.

Until this data exists, the agent marks conclusions that depend on events or object state as "unverified". Once it exists, add the tools `get_k8s_events`, `get_object_history` and `get_node_system_logs` (see section 6) and extend `get_vm_timeline`.

## 4. How a run works

1. Engineer runs `python main.py` and pastes the alert JSON.
2. `parse_alert` loads the JSON and checks all five fields exist (no LLM).
3. `enrich_vm_context` searches Splunk for VM details (guest OS, recent errors, launcher pod, node).
4. `get_topology` and `group_alert` tag the alert and look for an open group of related alerts (Phase 8b). If it joins an open group and nothing material has changed, it is attached to the group, the group's diagnosis is shown, and the run ends.
5. `find_similar_incidents` looks up past matches in Postgres (Phase 8).
6. `classify_failure` gives a skill hint (simple rules on metrics first).
7. `run_agent` runs the bounded loop: the LLM picks tools, code runs them and enforces limits, until the LLM is done or a limit is hit. (`--mode playbook` runs the chosen skill's required tools in fixed order, then calls `diagnose`.)
8. `validate_diagnosis` checks in code that every claimed cause cites real evidence, then `review_diagnosis` (the critic pass) reviews the draft.
9. The report is printed to the terminal and saved to Postgres with the steps, evidence, hypotheses and topology snapshot.
10. Later, the engineer runs `python feedback.py <incident_id>` to mark the diagnosis correct, wrong or partly correct, and add the real cause.

Steps 4 and 5 and the critic pass exist only once the phase that builds them is done. Earlier phases skip them.

**Alert input shape (JSON):**
```json
{
  "vm_name": "payments-db-01",
  "namespace": "payments-prod",
  "cluster": "ocv-prod-1",
  "severity": "critical",
  "timestamp": "2026-10-27T09:15:00Z"
}
```

## 5. Investigation approach

**The agent is a bounded tool-using loop.** The LLM sees the alert, the VM enrichment and the list of tools. It chooses a tool, reads the result, and decides the next tool or that it has enough evidence to stop. Code enforces the limits.

**Agent reasoning aids:**
- **System prompt file** `prompts/agent_system.md`: role, rules, stop conditions, output format. Editable without code changes.
- **Hypothesis list:** after each tool result the agent updates a short list of hypotheses with status (open / supported / rejected) and the evidence IDs behind each. It stops when one hypothesis is supported and the others are rejected or lacking evidence.
- **Evidence IDs:** a wrapper assigns E1, E2, ... to every tool result. Claims in the diagnosis must cite IDs.
- **Critic pass:** a second LLM call checks the draft for unsupported claims, missed alternatives and unsafe advice. If it finds problems, the agent may do a limited number of extra steps or lower confidence.

**Code-enforced limits (never left to the LLM):**
- Maximum number of steps (e.g. 8) and a total time limit.
- Only allowlisted read-only tools can be called.
- The same tool with the same arguments is not repeated.
- On hitting a limit, the agent stops and reports with the evidence so far.
- The final diagnosis must pass `validate_diagnosis` and the critic pass.

**Skills:** each failure scenario is a Markdown file in `skills/` (symptoms, steps, how to interpret results, confidence rules, do-not-do, next steps, and post-v1 a list of remediation action IDs). The agent reads `INDEX.md`, loads the matching skill, and follows it. New scenarios are added by dropping in a new file, with no code change.

**Playbook mode (kept as fallback and benchmark):** runs the `required_tools` listed in the chosen skill's header, with the LLM only analyzing. It is built first (Phases 5 and 6) to give a predictable baseline. The agent loop (Phase 6b) is then compared against it on the reproduced test failures.

**Later:** new skills (stuck terminating, migration failure, post-upgrade); Kafka trigger; similar past incidents offered to the agent as a tool.

## 6. Tools (built after Phase 1 data discovery)

Tool functions are written only after exploring what the MCP servers expose. Planned set:

| Tool | Source | Purpose |
|---|---|---|
| `get_vm_state` | Prometheus (KubeVirt) | VM/VMI phase and recent transitions |
| `get_node_health` | Prometheus (kube-state, node-exporter) | Node ready/pressure, unschedulable, CPU/memory/disk |
| `get_network_health` | Prometheus (node-exporter) | Interface errors, drops, traffic anomalies |
| `get_storage_health_pvc` | Prometheus (kube-state) | PVC phase, Pending/Lost |
| `get_storage_health_dell` | Prometheus (Dell CSM) | Backend and volume health |
| `get_storage_health_portworx` | Prometheus (Portworx) | Volume and node/pool health |
| `search_container_logs` | Splunk | Logs for launcher, handler, controller, CSI and operator pods |
| `get_maintenance_signals` | Prometheus + Splunk | Inferred drain/upgrade/maintenance activity |
| `find_related_vms_down` | Prometheus | Other VMs down at the same time, shared node/storage |
| `get_vm_timeline` | Prometheus + Splunk | One timestamped sequence of state changes and key log lines before and after the alert |
| `get_topology` | Topology DB + Prometheus labels + overrides | Where the VM sits: node, storage backend, network domain, cluster, datacenter, with `unknown` for gaps and the last sync time |
| `get_recent_alerts` | Postgres | Other incidents in a time window, with their topology tags |
| `compare_scope` | Prometheus | For a dimension and value (e.g. a storage backend), how many VMs are down vs how many exist there |
| `list_skills`, `load_skill` | Local files | Let the agent read investigation procedures |
| `get_k8s_events` (after data upgrade) | Splunk | Events for a VM, pod, PVC or node in a time window (scheduling, attach, mount, eviction) |
| `get_object_history` (after data upgrade) | Splunk | State changes of VM, VMI, DataVolume, PVC, Node (conditions, finalizers, deletion timestamps) |
| `get_node_system_logs` (after data upgrade) | Splunk | kubelet, CRI-O and kernel logs for a node |
| `request_remediation` (post-v1) | AAP through the action catalog | The only way the agent can trigger a change. See section 16 |

Every evidence item is a dict with: `id` (E1, E2, ...), `source`, `query`, `time_range`, `result_summary`, `error` (if the query failed). A small wrapper assigns the ID.

## 7. Failure types and skills (one skill file each)

Metric and log names are starting points and **must be verified on the cluster** in Phase 1.

| Failure type | Evidence |
|---|---|
| VM won't start | VM/VMI phase, launcher pod phase and restarts, `virt-launcher` / `virt-controller` logs |
| Node unresponsive | Node conditions, `virt-handler` status, node-exporter metrics, other VMs on that node, inferred maintenance signals |
| PVC/storage stuck | PVC phase, Dell CSM / Portworx metrics, CSI and attach/mount errors in logs |
| Multiple VMs down | Other VMs down in the same window, shared node, shared storage backend; decide "common cause" vs "separate incidents" |

## 8. Files and functions

| File | Functions |
|---|---|
| `config.py` | `load_config()` |
| `alert_parser.py` | `parse_alert(text)` |
| `mcp_client.py` | `list_tools(server)`, `call_mcp_tool(server, name, args)` |
| `tools_*.py` | The tool functions in section 6 |
| `skills.py` | `list_skills()`, `load_skill(name)`, `get_required_tools(name)`, `classify_failure(alert)` |
| `skills/*.md` | `INDEX.md`, `vm_wont_start.md`, `node_unresponsive.md`, `storage_stuck.md`, `multi_vm_down.md`; added in the correlation phase: `storage_backend_outage.md`, `site_or_network_outage.md` |
| `llm.py` | `call_llm(messages)`, `diagnose(alert, evidence, similar)` |
| `agent.py` | `run_agent(alert)`, `build_tool_list()`, `run_tool_safely(name, args)` |
| `validator.py` | `validate_diagnosis(diagnosis, evidence)` (checks cited IDs exist and support the claim) |
| `critic.py` | `review_diagnosis(diagnosis, evidence, hypotheses)` |
| `prompts/agent_system.md` | Agent role, rules, stop conditions |
| `db.py` | `init_db()`, `save_incident(...)`, `find_similar_incidents(...)`, `save_feedback(...)` |
| `topology.py` | `get_topology(vm, cluster)`, `load_topology_overrides()` |
| `correlation.py` | `get_recent_alerts(window)`, `compare_scope(dimension, value)`, `group_alert(alert)` |
| `report.py` | `format_report(...)` |
| `main.py`, `feedback.py` | Entry points |
| `redact.py` (Phase P1) | `redact(text)` and injection flagging |
| `run_evals.py`, `evals/` (Phase 6a) | Eval harness and cases (see EVALUATION.md) |
| `run_security_checks.py` (Phase P1) | Security checks (see SECURITY.md) |
| `aap_client.py`, `actions.py`, `actions.yaml` (post-v1) | Remediation through AAP (section 16) |

## 9. Diagnosis output (JSON from the LLM)

```json
{
  "failure_type": "storage_stuck",
  "probable_cause": "short text",
  "confidence": "low | medium | high",
  "hypotheses": [
    {"cause": "short text", "status": "supported | rejected | open", "evidence_ids": ["E3", "E5"]}
  ],
  "evidence_used": ["E1", "E3"],
  "inferred_items": ["things not directly observed"],
  "missing_evidence": ["what could not be checked"],
  "next_steps": ["specific things the engineer should check"],
  "do_not_do": ["e.g. do not restart the VM yet"],
  "similar_incident_ids": [12, 31],
  "steps_taken": 6
}
```

## 10. Postgres (schema `vmdown_agent`)

**incidents**: id, created_at, cluster, namespace, vm_name, severity, alert_time, raw_alert, failure_type, symptoms (JSON list of tags such as `pvc_pending`, `node_notready`), evidence (JSON), diagnosis (JSON).

**feedback**: id, incident_id, verdict (correct/wrong/partial), actual_cause, notes, created_at.

**incident_groups**: id, opened_at, status (open/closed), suspected_dimension, suspected_value, scope (node/storage/network/cluster/site), summary. Incidents also store `group_id` and a `topology` JSON snapshot taken at alert time, so history stays correct if the topology later changes.

**agent_steps**: id, incident_id, step, tool, args, result_summary, hypotheses, created_at. An **actions** table is added in the post-v1 phases (section 16).

**Similarity (v1):** match on failure_type first, then rank by overlapping symptom tags. Prefer incidents whose feedback says "correct". Show why each one matched.

**Similarity (later):** add embeddings once there are roughly 30+ saved incidents with feedback. Saved data stays the same.

## 11. Safety rules

- All MCP queries are read-only. Only query operations are exposed.
- The agent can only call tools from an allowlist. Step, time and repeat limits are enforced in code.
- Every external call has a timeout and retry limit.
- Failed queries are recorded as evidence errors, never hidden.
- Correlation is not causation: the validator rejects or downgrades a cause supported only by a correlated metric.
- Inferred signals are labeled as inferred.
- If evidence is insufficient, the report says so instead of guessing.
- Secrets come from environment variables and are never hard-coded or printed.
- Raw alerts and logs may contain sensitive names, so the schema must be access-controlled.
- Alerts, logs, events, topology data and past incident text are untrusted data, never instructions. They are quoted, size-capped and checked for injection-like text before reaching the LLM (basic version in Phase 6b, hardened in Phase P1).
- Sensitive values are redacted before anything is sent to the LLM or stored (Phase P1). Until then, use only the test cluster and non-sensitive data.
- The full threat model and controls are in `SECURITY.md`.

## 12. Configuration (environment variables)

`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `PROM_MCP_URL`, `PROM_MCP_TOKEN`, `SPLUNK_MCP_URL`, `SPLUNK_MCP_TOKEN`, `DATABASE_URL`, `TOPOLOGY_DB_URL` (read-only user)

## 13. Testing

On the test cluster, deliberately cause each failure type:
- VM won't start (e.g. impossible resource request)
- Node unresponsive
- PVC stuck Pending
- Several VMs down on one node

For each, record the alert JSON and the true cause, then check the agent's diagnosis. Keep these as eval cases. The full plan (agent trajectory evals, safety evals, repeat runs, shadow mode) is in `EVALUATION.md`.

## 14. Success criteria for v1

- Runs end to end from pasted JSON to saved report for all four failure types.
- Correct failure type on all reproduced test cases.
- Probable cause correct, or honestly marked low confidence, on most test cases.
- No report claims a cause without cited evidence.
- Repeating a past failure shows the earlier incident as a similar match.
- The agent chooses tools sensibly (verified from the step log) and stops on its own or at a limit.
- Related alerts are grouped correctly and investigated once (Phase 8b).
- The eval suite passes, including every safety case (`EVALUATION.md`).
- Zero write actions against the cluster.

## 15. Correlating related incidents (single VM vs many VMs, one or several clusters)

A VM alert is a symptom. A group of alerts that share a position is evidence of a shared cause. Phases up to 8 handle one alert at a time with same-cluster checks. Phase 8b adds full correlation, still within v1, because it needs stored incidents.

**Topology tags.** Every incident is tagged with: node, storage backend (Dell array or Portworx cluster), StorageClass, network domain (VLAN, rack, switch), cluster, datacenter. Version and recent-change tags are added when available.

**Topology source (partial data is expected)**
- First choice: the read-only UAT copy of the topology application's database (synced about 3 times, so it can be hours old). Use a read-only DB user and fixed, parameterized queries only.
- Then: Prometheus node labels (for example zone or region).
- Then: a hand-maintained `topology_overrides.yaml` for known gaps.
- Any dimension that cannot be found is returned as `unknown`. The report must say which dimensions are unknown and that correlation is limited, and must show when the topology data was last synced.

**Grouping rules**
1. On each new alert, fetch recent alerts (default window 10 minutes) and group alerts that share a tag.
2. **Compare affected against total.** For each shared tag, compute affected VMs / all VMs on that tag. A tag is a suspect only if the share is high. This stops the agent blaming a huge shared component by coincidence.
3. Decide scope top-down: several clusters in one datacenter (site), one storage backend across clusters (storage), all nodes of one cluster (cluster or its network), one node (node), otherwise individual incidents.
4. Create or update an `incident_group`. New matching alerts attach to the open group.
5. **Investigate once per group.** An alert that joins an open group is attached and shown with the group's diagnosis. A full re-investigation runs only when the group grows meaningfully or the suspected scope changes.

**Monitoring blind spot.** A datacenter or network outage can make metrics and logs disappear instead of showing errors. A cluster whose metrics have stopped arriving is itself evidence, and missing data must never be read as healthy.

**Skills.** `multi_vm_down.md` carries the top-down order. `storage_backend_outage.md` and `site_or_network_outage.md` are added in the correlation phase.

**With Kafka later,** alerts stream in continuously and grouping happens naturally in the same code. Parent/child linking in ServiceNow can be added then.

## 16. Remediation actions via Ansible Automation Platform (post-v1)

Not part of v1. Designed now so v1 choices do not block it.

**Principles**
- Playbooks live in Git and run as AAP job templates or workflows. They are never stored in skill files.
- Skills only list **action IDs** under "Remediation options", with the evidence that must hold first and the risk level.
- The agent has one remediation tool: `request_remediation(action_id, params, reason, evidence_ids)`. It cannot name a playbook, run commands or choose arbitrary inputs.
- Code, not the LLM, enforces the rules below.

**Action catalog (`actions.yaml`)** holds one entry per action:
- `action_id`, `description`, `aap_template_id` (or workflow ID)
- `risk`: low or high (high is never agent-triggered)
- `allowed_params`: only cluster, namespace, VM name or node name, each validated
- `requires_approval`: true for every action
- `preconditions`: failure type, minimum confidence, required evidence kinds
- `postcheck`: how success is measured (for example VM phase Running within N minutes)

**Flow**
1. The agent produces a diagnosis and proposes an action ID from the loaded skill.
2. Code checks: action exists in the catalog, risk allows agent use, params are valid, preconditions are met, the critic found no unsupported claims.
3. An engineer approves every action (AAP workflow approval node or an external approval step).
4. Code launches the AAP workflow (precheck, approval, action, postcheck) through the controller API and polls its status.
5. Result, postcheck outcome, who approved and timestamps are saved with the incident in Postgres.
6. If the postcheck fails, the agent stops, reports and escalates. It does not try further actions on its own.

**Launch inputs:** use a survey on the template to limit inputs to the allowed fields. Check how your AAP version handles launch-time variables (surveys versus prompt-on-launch, which can differ for workflows).

**Planned actions** (playbooks are used only for actions that change something; reading data comes from OTel data in Splunk, see section 3)

| Risk | Actions |
|---|---|
| low (approval required) | `restart_vm_graceful`, `restart_virt_handler_pod`, `migrate_vms_off_node`, `retry_datavolume_import`, `cleanup_stale_import_pvc` |
| high (humans only) | Force-delete VMI or pod, delete volume attachments, restart CRI-O, reboot or fence a node, change memory limits |

Every action playbook needs a precheck (is it safe) and a postcheck (did it work).

**Safety rules**
- No action without matching preconditions and an engineer approval.
- One action at a time per VM, with a cooldown to prevent loops.
- Dry-run or check mode where possible.
- Full audit trail in Postgres.
- A kill switch (environment flag) turns remediation off globally.

## 17. Reference material

`VM_DOWN_REFERENCE.md` summarizes common OCV VM-down scenarios (symptoms, causes, checks, fixes, engineer tools) from public Red Hat and KubeVirt sources. It is the source for writing the skill files. Items that need Kubernetes events or object state must be marked "unverified" by the agent.

## 18. Open items (resolved in Phase 1)

- Exact MCP tool names and argument formats for Prometheus and Splunk.
- Exact metric names (KubeVirt, kube-state, node-exporter, Dell CSM, Portworx).
- Splunk index/sourcetype names and field names for container logs (including guest OS and error fields).
- Which operator/node-agent logs best reveal drains and upgrades.
- Exact schema name and database permissions.
- Topology database: tables, columns, which clusters and dimensions it covers, exact sync schedule, and who grants a read-only account.

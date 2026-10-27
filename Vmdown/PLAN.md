# PLAN: VMDown Triage Agent

Each phase ends with something you can **run** and **verify**. Do not start a phase until the previous one passes its "Done when" check. Code style throughout: plain functions and dicts, no classes.

## Roadmap

| Stage | Phases | Outcome |
|---|---|---|
| Foundation | 0 to 2 | Connections work, data explored, alerts parsed and enriched |
| Evidence | 3, 4, 4b | Tools that fetch metrics, logs, events and object history |
| Skills and diagnosis | 5, 6, 6a | Skill files, first end-to-end report, eval harness and baseline |
| Agent | 6b | Bounded agent loop, compared against the baseline |
| Memory and correlation | 7, 8, 8b, 9 | Saved incidents, similar-incident lookup, grouping across VMs and clusters, feedback |
| v1 hardening | 10 | Regression set, README, DESIGN.md updated |
| Production readiness | P1 to P6 | Security, observability, CI and deployment, shadow mode, rollout, Kafka |
| Remediation | 11 to 13 | Approved actions through AAP |

**Standing rules**
- Until Phase P1 is complete, run the agent only against the test cluster and non-sensitive data.
- Phase 4b (events and object history) can be delayed. The agent then marks those items "unverified".
- Do not start remediation (Phases 11 to 13) before P1 to P5 are done.
- Start the data and access requests (`DATA_REQUIREMENTS.md`, topology DB account, collector changes) on day one, because they take the longest.

---

## Phase 0: Project setup and connectivity

**Goal:** Prove your machine can reach everything the agent depends on.

**Build**
- Project folder, virtual environment, `requirements.txt`, `.env` file (not committed to git).
- `config.py` with `load_config()` reading environment variables.
- `check_setup.py` that tests each connection and prints PASS/FAIL.

**Run:** `python check_setup.py`

**Done when**
- LLM gateway returns a reply to "say hello".
- Prometheus MCP server connects.
- Splunk MCP server connects.
- Postgres connects and the `vmdown_agent` schema can be created.
- The topology database (read-only UAT copy) connects with a read-only user.
- The gateway's tool-calling support is tested: either it works with the OpenAI tool format, or you choose JSON-reply mode for the agent loop (see DESIGN.md open questions).

---

## Phase 1: Data discovery

**Goal:** Find out what the MCP servers expose and which metrics and logs are actually useful. Nothing else is built until this is done, because every later tool depends on it.

**Build**
- `mcp_client.py` with `list_tools(server)` and `call_mcp_tool(server, name, args)`.
- `discover.py` that lists the tools of both MCP servers and their input arguments.
- Manual exploration on the test cluster, recorded in `DISCOVERY.md`.
- Go through `DATA_REQUIREMENTS.md`: mark every item Present, Partial or Missing, and decide for each gap whether to procure it, accept it, or work around it. Start the procurement requests early, because the OTel and collector changes take time.

**Run:** `python discover.py`

**Done when `DISCOVERY.md` contains:**
- The completed status table from `DATA_REQUIREMENTS.md`, with an owner and decision for every Missing or Partial item.
- Prometheus and Splunk tool names and arguments.
- The real metric names for: VMI phase, pod phase and restarts, node conditions, unschedulable nodes, PVC phase, node-exporter network/disk, Dell CSM, Portworx.
- Splunk index, sourcetype and field names for container logs (VM name, namespace, pod, guest OS, error).
- Which operator and node-agent logs show drains or upgrades.
- Topology database: tables and columns, which clusters and dimensions (datacenter, storage backend, network domain, node) it covers and which it does not, and the sync schedule.
- A list of anything you expected but could not find.

---

## Phase 2: Alert parsing and VM enrichment

**Goal:** Turn pasted JSON into a clean alert, then add VM details from Splunk.

**Build**
- `alert_parser.py`: `parse_alert(text)` loads the JSON and reports clearly which fields are missing or malformed.
- `enrich_vm_context(alert)`: Splunk search for guest OS, recent errors, launcher pod and node.
- `main.py` (first version) that asks for the pasted JSON.

**Run:** `python main.py`, then paste a sample alert for a real VM.

**Done when**
- A valid alert prints the parsed fields plus the enrichment results.
- A bad alert (missing field, invalid JSON) gives a clear error message.
- A VM that does not exist gives "no data found" instead of a crash.

---

## Phase 3: Prometheus evidence tools

**Goal:** Build and test each metric tool on its own, before combining anything.

**Build** (one function at a time, each returning the standard evidence dict)
1. `get_vm_state`
2. `get_node_health`
3. `get_network_health` (node-exporter errors and drops)
4. `get_storage_health_pvc`
5. `get_storage_health_dell`
6. `get_storage_health_portworx`
7. `find_related_vms_down`
- A small wrapper that assigns an evidence ID (E1, E2, ...) to every tool result.
- `test_tools.py`: a small script that runs any tool for a VM and prints the evidence.

**Run:** `python test_tools.py get_node_health <node-name>` (and so on for each tool)

**Done when**
- Every tool returns correct data for a healthy VM and sensible data for a broken one on the test cluster.
- A failed or empty query produces an evidence dict with an `error`, never a crash.

---

## Phase 4: Log tools

**Goal:** Searchable container-log evidence.

**Build**
- `search_container_logs(...)` for launcher, handler, controller, CSI and operator pods, with a time window around the alert.
- `get_maintenance_signals(...)` combining node-unschedulable metrics with operator log patterns. Output is labeled "inferred".
- `get_vm_timeline(...)`: merges metric state changes and key log lines into one timestamped sequence from 30 minutes before the alert to now.
- Log results are trimmed to a safe size before going to the LLM (only relevant lines, capped count).

**Run:** `python test_tools.py search_container_logs <pod>`

**Done when**
- Logs return for a known pod and time window.
- Output size is capped.
- A drain you trigger on the test cluster shows up in the maintenance signals.
- For a failure you caused, the timeline shows the sequence in the right order.

---

## Phase 4b: Events, object-state and node-log tools (needs the data upgrade)

**Goal:** Give the agent Kubernetes events, object history and node system logs from Splunk, so diagnoses no longer have to say "unverified" for them.

**Prerequisite (done by whoever owns the OTel pipeline, can run in parallel with earlier phases):**
- Kubernetes objects receiver: events in watch mode; VM, VMI, DataVolume, PVC and Node objects (set the API group for custom resources). Single replica to avoid duplicates. Filter noisy fields and namespaces.
- journald collection for kubelet, CRI-O and kernel logs.
- Data lands in a Splunk index through your existing path. Security review of the read permissions.

**Build** (after the data is searchable)
- `get_k8s_events`, `get_object_history`, `get_node_system_logs`, each returning evidence dicts with IDs.
- Extend `get_vm_timeline` to merge events and object changes.
- Update the skills: replace "unverified" notes with the new checks (scheduler messages, attach and mount errors, finalizers, deletion timestamps).
- Record the new Splunk index, sourcetype and field names in `DISCOVERY.md`.

**Run:** `python test_tools.py get_k8s_events <vm> <namespace>` after causing a failure on the test cluster.

**Done when**
- Events for a failure you caused appear with correct timestamps, including events from before the VM went down.
- Object history shows the VM and VMI state changes and deletion timestamps.
- The timeline includes events and object changes in the right order.
- If this phase is skipped, the agent still works and marks those items "unverified".

---

## Phase 5: Skill files and classification (no LLM diagnosis yet)

**Goal:** Write each investigation procedure as a Markdown skill file, and collect evidence automatically from them.

**Build**
- `skills/` folder with `INDEX.md` (one line per skill) and four skills: `vm_wont_start.md`, `node_unresponsive.md`, `storage_stuck.md`, `multi_vm_down.md`.
- Each skill file has a small header (`name`, `use_when`, `required_tools`) followed by sections: Symptoms, Steps, How to interpret results, Confidence rules, Do not do, Next steps, and an empty "Remediation options" section to be filled in post-v1 (action IDs only).
- `skills.py`: `list_skills()`, `load_skill(name)`, `get_required_tools(name)` (plain file reading and string handling).
- `classify_failure(alert)`: simple rules on metrics that return a skill name as a hint.
- Playbook mode: run the `required_tools` of the chosen skill, in order.
- Write skills from what Phase 1 discovered, using real metric names and log patterns. Use `VM_DOWN_REFERENCE.md` for the common causes, checks and safety notes.

**Run:** Cause each failure on the test cluster, paste its alert, run `python main.py --mode playbook`.

**Done when**
- All four reproduced failures pick the right skill.
- Each evidence bundle contains what you would check manually.
- Evidence gaps are listed explicitly.
- Adding a new skill file and an `INDEX.md` line makes it available without any code change.

---

## Phase 6: LLM diagnosis, validation and report

**Goal:** The first complete end-to-end result in the terminal.

**Build**
- `llm.py`: `call_llm(messages)` and `diagnose(alert, evidence, similar)`, returning the JSON structure from SPEC section 9. If the LLM returns invalid JSON, retry once, then fail clearly. `similar` is an empty list until Phase 8.
- The diagnosis prompt includes the chosen skill's interpretation and confidence rules.
- `validator.py`: `validate_diagnosis(...)` rejects causes that cite no evidence IDs or IDs that do not exist, and downgrades confidence for correlation-only causes.
- `report.py`: `format_report(...)` for readable terminal output.

**Run:** `python main.py` on each of the four test failures.

**Done when**
- Each run prints a report with cause, confidence, evidence, missing evidence and next steps.
- You compare it with the true cause: failure type correct, cause correct or honestly low confidence.
- Removing an evidence source makes the report say "insufficient evidence" instead of guessing.

---

## Phase 6a: Evaluation harness (build before the agent loop)

**Goal:** Be able to measure quality before and after the agent loop exists. See `EVALUATION.md`.

**Build**
- `evals/FAULTS.md`: for each failure type, the steps to cause it on the test cluster, the true cause, and the cleanup.
- `evals/cases/`: eval cases in the format from EVALUATION.md section 2. Start with at least one case per failure type, plus one healthy-VM case and one missing-data case. Grow toward 4 to 8 per type.
- `evals/cases/safety/`: injection and secret cases using recorded tool outputs (a planted log line, a malicious VM name).
- `run_evals.py --mode playbook --repeat 3`: runs every case through the same function `main.py` uses, checks failure type, forbidden phrases, evidence-ID validity, steps and time, and saves results together with the prompt, skill and model versions.
- Save the playbook-mode results as the **baseline**.

**Run:** `python run_evals.py --mode playbook --repeat 3`

**Done when**
- A results table exists for all cases and is stable across repeats.
- The baseline is saved.
- A deliberately broken skill or prompt makes at least one eval fail, which proves the evals can catch regressions.
- The safety cases are written and run. Cases that depend on the validator pass now. Cases that depend on quoting and injection flagging are expected to pass after Phase 6b, and redaction cases after Phase P1. Mark those pending until then.

---

## Phase 6b: Bounded agent loop (makes it a true agent)

**Goal:** The LLM decides which tool to call next, reads the result, and decides when it has enough evidence. Code enforces the safety limits.

**Build**
- `prompts/agent_system.md`: the agent's role, rules (read-only, cite evidence IDs, say "insufficient evidence", no restart advice before cause is known), stop conditions and output format. Loaded from file so you can edit it without touching code.
- `agent.py`: `run_agent(alert)` with a simple loop:
  1. Give the LLM the alert, enrichment, and the list of tools (names, descriptions, arguments) using the OpenAI-style tool-calling format your gateway supports.
  2. The LLM replies with either a tool call or "I'm done, here is my diagnosis".
  3. Code runs the tool, adds the result to the conversation, and repeats.
- Tool descriptions written clearly so the LLM knows when to use each tool (reuses the Phase 3 and 4 functions unchanged).
- Hard limits in code, not left to the LLM:
  - Maximum number of steps (e.g. 8).
  - Total time limit.
  - Only allowlisted read-only tools can be called.
  - The same tool with the same arguments cannot be repeated.
  - On hitting a limit, the agent must stop and report with the evidence so far.
- Hypothesis tracking: after every tool result the agent returns an updated list of hypotheses (cause, status open/supported/rejected, evidence IDs). Code stores the list at each step. The agent may stop only when one hypothesis is supported or the limits are reached.
- Evidence IDs: tool results shown to the agent carry their IDs, and the final diagnosis must cite them.
- Basic prompt-injection protection: wrap every tool result and alert field in delimiters, tell the model in the system prompt that quoted content is data only, validate tool arguments in code, and flag injection-like text. This is the first version of SECURITY.md section 4. Phase P1 hardens it.
- `critic.py`: `review_diagnosis(...)` is a second LLM call that checks the draft for unsupported claims, missed alternatives and unsafe advice. If it objects, the agent gets up to two more steps or the confidence is lowered, and the critic's notes appear in the report.
- Every step is logged (tool, arguments, result summary, hypotheses) and stored with the incident, so you can see how the agent reasoned.
- The final diagnosis still goes through `validate_diagnosis`.
- `main.py --mode playbook` (Phase 6 behavior) or `--mode agent` (this loop).
- `list_skills` and `load_skill` are tools the agent can call. The classifier's hint tells it which skill to read first, but it may load other skills or go beyond a skill if the evidence points elsewhere.

**Run:** `python main.py --mode agent`, then run the same four test failures as in Phase 6.

**Done when**
- The step log shows the agent choosing tools that make sense for each failure, not a fixed order.
- It stops by itself once evidence is sufficient, or reports "insufficient evidence" when it cannot find enough.
- Limits work: a forced low step limit ends the run cleanly with a partial report.
- It never calls a tool outside the allowlist.
- The hypothesis list changes sensibly over the run (for example, a storage hypothesis is rejected once storage looks healthy).
- Every claim in the final report cites an existing evidence ID.
- The critic catches a deliberately planted unsupported claim in a test.
- `python run_evals.py --mode agent --repeat 3` passes the trajectory checks from EVALUATION.md section 4 (sensible tool choice, no repeated calls, stops on its own, handles tool errors, abstains when data is missing, stable across repeats).
- All safety evals pass in agent mode (no out-of-allowlist call, injections flagged).
- A comparison table, playbook vs agent, from the eval results: failure type, cause correct, steps used, time taken, tokens, evidence gaps.
- You decide which mode is default. A sensible approach is the agent as default, with playbook mode as a fallback and a benchmark.

---

## Phase 7: Save incidents to Postgres

**Goal:** Every run is stored.

**Build**
- `db.py`: `init_db()` (creates `incidents`, `feedback` and `agent_steps` tables) and `save_incident(...)`.
- Symptom tags generated from the evidence (e.g. `pvc_pending`, `node_notready`).
- The agent's step log (from Phase 6b) is saved with the incident.
- `main.py` saves after printing and shows the incident ID.

**Run:** `python main.py`, then check the table in a Postgres client.

**Done when**
- A row appears with the alert, evidence, diagnosis, failure type and symptom tags.
- If Postgres is down, the report still prints and a warning is shown.

---

## Phase 8: Similar-incident lookup

**Goal:** Past incidents improve new diagnoses.

**Build**
- `find_similar_incidents(...)`: match failure type, rank by shared symptom tags, show why each matched.
- `main.py` runs it before diagnosis, passes matches to the LLM (in agent mode, into the agent's starting context), and lists them in the report.

**Run:** Cause the same failure twice and run the agent each time.

**Done when**
- The second run lists the first incident as a similar match with the reason.
- With an empty database, the agent works normally.

---

## Phase 8b: Topology and alert correlation

**Goal:** Alerts that share a cause are grouped, and the agent investigates the shared factor once instead of once per VM.

**Build**
- `topology.py`: `get_topology(vm, cluster)` reads the read-only UAT copy (fixed queries, read-only user), then fills gaps from Prometheus node labels and `topology_overrides.yaml`. It returns each dimension (node, storage backend, network domain, cluster, datacenter) or `unknown`, plus the last sync time.
- Postgres: `incident_groups` table, plus `group_id` and a `topology` JSON snapshot on incidents.
- `correlation.py`: `get_recent_alerts(window)`, `compare_scope(dimension, value)` (affected vs total from Prometheus), `group_alert(alert)`.
- Tools added to the agent: `get_topology`, `get_recent_alerts`, `compare_scope`.
- Skills: `storage_backend_outage.md`, `site_or_network_outage.md`, and the top-down order added to `multi_vm_down.md`.
- `main.py`: after parsing, call `group_alert`. An alert that joins an open group is attached and shown with the group's diagnosis. A full re-investigation runs only if the group grew meaningfully or the scope changed.
- Blind-spot rule: a cluster whose metrics have stopped is reported as evidence and never treated as healthy.
- `tests/alerts/` with crafted alert JSON files for the scenarios below.

**Run:** Paste the crafted alerts one after another with `python main.py`, then check the groups in Postgres.

**Done when**
- Three alerts for VMs on one node form one group with scope "node".
- Alerts spread across two different storage backends are not wrongly grouped as a storage incident.
- The report shows affected vs total for the suspected tag.
- For a cluster with no topology data, the report says correlation is limited and lists the unknown dimensions.
- The report shows when the topology data was last synced.
- With the topology database unreachable, the agent still works using Prometheus labels and overrides.
- A cluster with stopped metrics is flagged as such.

---

## Phase 9: Feedback loop

**Goal:** Engineers can say whether the diagnosis was right.

**Build**
- `save_feedback(...)` and `feedback.py`.
- Similarity ranking prefers incidents marked "correct" and shows the confirmed cause.

**Run:** `python feedback.py <incident_id>`, enter the verdict and the real cause.

**Done when**
- A feedback row is saved.
- A later similar incident displays the confirmed real cause from that feedback.

---

## Phase 10: Hardening and regression set

**Goal:** Make it reliable enough to hand to others.

**Build**
- Timeouts and retry limits on every MCP and LLM call.
- Secrets never printed, including in error messages.
- `tests/` with the four reproduced failure alerts plus their true causes, and `run_tests.py` that checks failure type and cause for each. Include a grouped scenario (several alerts, one shared cause) from Phase 8b.
- `README.md` with setup and usage steps.
- Update `DESIGN.md` so it matches what was actually built.
- Read-only check: confirm that only query tools are ever called.

**Run:** `python run_tests.py`

**Done when**
- All four regression cases pass.
- `python run_evals.py` passes in both modes with no safety failures.
- Bad input, an unreachable MCP server, and an LLM error each produce a clear message, not a stack trace.
- A new person can set up and run it from the README.

---

## Production readiness phases (P1 to P6)

v1 (Phases 0 to 10) gives a working, safe, read-only agent. These phases make it production-grade. Do P1 to P5 before relying on the agent in production and before the remediation phases. Controls come from `SECURITY.md`, measurements and rollout from `EVALUATION.md`, structure from `DESIGN.md`.

---

## Phase P1: Security hardening

**Goal:** Close the gaps in SECURITY.md before real data and real alerts flow through the agent.

**Build**
- Read-only service accounts for Prometheus, Splunk and the topology DB. A Postgres user limited to its own schema. Secrets from a secret manager or environment, never in Git.
- `redact.py`: `redact(text)` using one reviewed rules file, applied before anything goes to the LLM and before anything is stored.
- Harden the basic quoting and injection flagging from Phase 6b: shared helper functions, stricter size caps, more injection patterns, and tests drawn from the safety evals.
- Data retention rule implemented (cleanup or summarization of old raw evidence).
- Written confirmation of what the LLM gateway logs and retains.
- `run_security_checks.py`: attempts a write with each credential (must fail), scans for secrets, checks that a non-allowlisted tool is refused.

**Run:** `python run_security_checks.py`, then `python run_evals.py --tags safety`

**Done when**
- The checklist in SECURITY.md section 10 passes.
- Injection evals pass in both modes.
- A planted secret never appears in an LLM payload or in Postgres.

---

## Phase P2: Observability and reliability

**Goal:** See how the agent behaves in operation and survive failures.

**Build**
- A run ID on every log line, plus structured logs.
- Traces and metrics for the agent through your existing OTel pipeline: runs, duration, steps, tokens, tool errors, LLM errors.
- A dashboard and alerts for agent failure rate, latency and cost.
- Retries with backoff and a circuit breaker on MCP and LLM calls.
- Automatic fallback to playbook mode when the LLM is unavailable, with the report saying so.
- Per-run token and time budgets, and a concurrency cap.

**Run:** Send alerts, then block the LLM gateway and send another.

**Done when**
- The dashboard shows runs, latency, failures and token use.
- The fallback works and is labeled in the report.
- A run that exceeds its budget is cut off cleanly.
- An alert fires when the agent's failure rate rises.

---

## Phase P3: Packaging, CI and deployment

**Goal:** Reproducible releases with eval gates.

**Build**
- A container image. Decide how it runs (service, worker or scheduled job).
- Config per environment (dev, UAT, prod), versioned DB migration scripts.
- A CI pipeline: lint, unit tests for pure functions, contract tests for tools using fixtures, `run_evals.py` on fixtures, dependency scan.
- Prompts, skills and `actions.yaml` in Git with required review.
- Versioned releases with rollback. Each incident records the prompt, skill and model versions used.

**Done when**
- Changing a skill triggers CI, runs evals and blocks on a safety failure or a drop beyond the agreed margin.
- A release deploys to UAT from CI and a rollback works.
- Incidents show the versions that produced them.

---

## Phase P4: Shadow mode

**Goal:** Prove the agent on real alerts without affecting anyone.

**Build**
- Record the **baseline** first: how long engineers currently take to reach a first useful diagnosis.
- Feed real alerts (paste, export, or Kafka later). The agent runs on each and writes to Postgres only.
- A weekly review report: accuracy by failure type, unsafe count, abstention, cost, steps.
- The feedback command used on every shadow incident.
- A routine that turns each wrong or unsafe case into a new eval case, and into a skill or prompt change if needed.

**Run:** For the period agreed in EVALUATION.md section 9.

**Done when**
- The stage 2 exit criteria in EVALUATION.md are met and signed off by the owner.
- Every wrong or unsafe case has been reviewed and converted.

---

## Phase P5: Assisted rollout and operations

**Goal:** Engineers use the agent's reports in real work, and the agent has an owner.

**Build**
- Report delivery where engineers work (ServiceNow work note, Slack or other, decided with the team). Delivery only, never automatic actions.
- Easy feedback (one command or button).
- Named owners and an on-call route for the agent. An operations runbook: what to do when the agent is wrong, down or costly.
- A skill lifecycle: owner, review cadence, update after OpenShift or CNV upgrades.
- Scheduled weekly evals and a drift dashboard. A cost review.

**Done when**
- Engineers receive reports on real incidents.
- Usefulness ratings and time to first diagnosis are tracked against the baseline.
- The runbook has been exercised in a tabletop test.
- Owners are named.

---

## Phase P6: Kafka trigger and concurrency

**Goal:** Alerts arrive automatically and bursts stay under control.

**Build**
- A Kafka consumer that produces the same alert JSON the parser already accepts.
- A dedupe key, rate limits, backpressure and dead-letter handling.
- Per-group serialization so one group is never investigated twice at once.
- A way to replay alerts for testing.

**Done when**
- Alerts flow from Kafka into the agent.
- Duplicate alerts do not cause duplicate runs.
- An alert storm test (for example 50 related alerts) produces a few groups with bounded cost.
- The consumer recovers after a restart without losing alerts.

---

## Post-v1 phases: remediation through Ansible Automation Platform

Start these only after the v1 success criteria in SPEC section 14 are met, production readiness phases P1 to P5 are done, and shadow-mode results have earned trust in the diagnoses. See SPEC section 16 for the design.

---

## Phase 11: Action catalog and safety framework

**Goal:** Build the guardrails before any change-making action exists. Playbooks are used only for actions that change something. Read-only data comes from OTel data in Splunk, not from playbooks.

**Build**
- `actions.yaml` with the catalog fields from SPEC section 16.
- `aap_client.py`: `launch_job(template_id, params)`, `get_job_status(job_id)`, `get_job_output(job_id)`.
- `actions.py`: `check_action_allowed(action_id, params, diagnosis)` (allowlist, param validation, risk, preconditions).
- One harmless test job template in AAP (for example a no-op that echoes its inputs), with a survey limiting inputs.
- `request_remediation` added as an agent tool, with no real actions enabled yet.
- A global kill-switch environment flag.

**Run:** `python test_action.py noop_test <vm> <namespace>`

**Done when**
- The test job runs in AAP and its output comes back with an evidence ID.
- A disallowed action ID, invalid param or high-risk action is rejected with a clear message and never reaches AAP.
- The kill switch blocks all launches.

---

## Phase 12: Approval workflow and first low-risk action

**Goal:** One real action, end to end, with approval and verification.

**Build**
- An AAP workflow: precheck, approval node, action, postcheck, for `restart_vm_graceful`.
- Approval request message that includes the diagnosis, evidence IDs and the proposed action.
- Agent flow: propose action, run `check_action_allowed`, request approval, wait, launch, poll, record the postcheck.
- Postgres tables for actions: incident ID, action ID, params, approver, timestamps, outcome.
- "Remediation options" section filled in for the relevant skills.

**Run:** On the test cluster, stop a VM unintentionally and run the agent through the full flow.

**Done when**
- Nothing runs before approval.
- A rejected approval ends the flow cleanly.
- The postcheck confirms the VM is running, or the agent escalates and stops.
- The audit record is saved.
- Repeating the request within the cooldown is blocked.

---

## Phase 13: Remaining low-risk actions and review

**Goal:** Add a few more actions and review the results before widening trust.

**Build**
- Playbooks and catalog entries, one at a time, each with its own precheck and postcheck: `restart_virt_handler_pod`, `migrate_vms_off_node`, `retry_datavolume_import`, `cleanup_stale_import_pvc`.
- A review report from Postgres: actions taken, approvals, success rate, any postcheck failures.

**Run:** Trigger each scenario on the test cluster.

**Done when**
- Every action passes its precheck and postcheck tests, including a case where the precheck correctly refuses to run.
- High-risk actions remain impossible to trigger from the agent.
- The review report shows no unapproved actions.

---

## After the above (not part of this plan)

- **v2:** Agent can query similar past incidents as a tool during its investigation.
- **New skills** (no code change, see `VM_DOWN_REFERENCE.md`): stuck Stopping/Terminating, VM OOM-killed, migration or drain failure, post-upgrade failures, guest boot failure, node system logs once collected.
- **Smarter agent helpers:** memory lookup as an agent tool, an ask-the-engineer tool, result compaction for long logs.
- **Skills from experience:** turn incidents marked "correct" into draft skills.
- **Further data** (see the P2 items in `DATA_REQUIREMENTS.md`): audit logs, hardware metrics and logs, synthetic probes to VM IPs, guest-level signals, network device data, each with its own tool.
- **Smarter matching:** embeddings once there are 30+ incidents with feedback.

## Risks to watch

- Phase 1 may show that some metrics or log fields are missing. If so, adjust the skills and tools, not the plan order, and let the agent mark those items "unverified".
- Large log results can overflow the LLM context, so cap and filter them early.
- The LLM may sound confident on thin evidence, which is why the validator in Phase 6 and the critic in Phase 6b exist.
- The gateway may not support OpenAI-style tool calling reliably. Phase 0 tests this, and JSON-reply mode is the fallback.
- Data procurement (events, object state, node logs, topology access) has long lead times. Request it in Phase 1, not when you need it.
- The topology data is partial and can be hours old. Correlation is only as good as it, so the report must always show what is unknown.
- A small eval set can mislead. Grow it from every real miss, and keep adding variety.
- Cost and latency can grow with agent steps. Watch them from Phase 6b onward.

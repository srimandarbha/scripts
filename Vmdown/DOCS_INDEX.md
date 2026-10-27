# VMDown Triage Agent: document index

Start here. Seven documents, each with one job.

## Reading order

| # | File | Answers | Read it when |
|---|---|---|---|
| 1 | `SPEC.md` | What the agent does, its limits, data contracts, tools and safety rules | First. It is the source of truth for scope |
| 2 | `PLAN.md` | In what order to build it. Every phase ends with something you can run and verify | Before and during the build |
| 3 | `DESIGN.md` | How the pieces fit: architecture, data formats, error handling, decision log | When writing or changing code |
| 4 | `DATA_REQUIREMENTS.md` | Which metrics, logs, Kubernetes events and objects you need, with priorities | Phase 1, and to start procurement requests now |
| 5 | `EVALUATION.md` | How to test the agent, measure quality, and roll out through shadow mode | Phase 6a onward, and before every release |
| 6 | `SECURITY.md` | Threat model, prompt-injection defenses, access and data handling | Phase 6b and Phase P1 |
| 7 | `VM_DOWN_REFERENCE.md` | Common VM-down scenarios, causes, checks and fixes from public sources | Phase 5, when writing skill files |

## How they relate

- **SPEC** says what. **PLAN** says when. **DESIGN** says how.
- **DATA_REQUIREMENTS** feeds Phase 1 and Phase 4b.
- **EVALUATION** and **SECURITY** gate every release and every rollout stage.
- **VM_DOWN_REFERENCE** is source material for the skill files you write in Phase 5.
- If code and documents disagree, fix one of them and note the change in the decision log in DESIGN.md.

## Before Phase 0: things to line up now

Some of these take days or weeks, so ask early.

- [ ] LLM gateway: base URL, API key, model name, and whether it supports OpenAI-style tool calling.
- [ ] Prometheus MCP and Splunk MCP: URLs and read-only tokens.
- [ ] Postgres: a new schema and a user limited to it.
- [ ] Topology database: a read-only account on the UAT copy, and the sync schedule.
- [ ] Test cluster where you may cause failures on purpose.
- [ ] Written answer from the platform owner on what the LLM gateway logs and retains.
- [ ] Requests started for the missing data in `DATA_REQUIREMENTS.md` (events and object state, node journald logs, scrape-health and `cluster` labels).
- [ ] An owner named for the agent, and an owner for reviewing skills, prompts and the action catalog.

## Decisions still open (they do not block Phase 0)

- Accuracy thresholds and the shadow-mode duration (EVALUATION.md). Set them after you have a baseline.
- How long to keep raw incident evidence in Postgres (SECURITY.md).
- Whether the production agent runs as a service, a worker, or a scheduled job (DESIGN.md, Phase P3).
- Where reports are delivered to engineers: ServiceNow, Slack or other (Phase P5).

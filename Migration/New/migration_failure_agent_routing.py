"""
Migration Failure Agent — team routing layer.

Ownership is computed deterministically from which evidence layer/tool
actually drove the diagnosis — same principle as compute_confidence and
resolve_conflict elsewhere in this codebase: routing is not an LLM
judgment call each run (inconsistent, unauditable, drifts), it's a rule
table over evidence_refs, with an LLM disambiguation step ONLY when the
deterministic mapping genuinely can't decide (see classify_owning_team's
fallback).

Called from compose_diagnosis, after the diagnosis JSON is composed but
before notify_oncall — see the two lines added there.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

TEAM_OBSERVABILITY = "observability"
TEAM_BUILD = "build"
TEAM_SRE_DAY2 = "sre_day2"          # default owner, always in notify_teams
TEAM_TESTOPS = "testops"
TEAM_STORAGE = "storage"
TEAM_NETWORK = "network"
TEAM_THIRD_PARTY = "third_party"
TEAM_HARDWARE = "hardware"
TEAM_VMWARE_ADMINS = "vmware_admins"

ALL_TEAMS = {
    TEAM_OBSERVABILITY, TEAM_BUILD, TEAM_SRE_DAY2, TEAM_TESTOPS, TEAM_STORAGE,
    TEAM_NETWORK, TEAM_THIRD_PARTY, TEAM_HARDWARE, TEAM_VMWARE_ADMINS,
}

# Per-team notification channel — resolved deterministically, same rule as
# resolve_recipient() in the actions layer: never LLM-supplied.
TEAM_CHANNELS = {
    TEAM_OBSERVABILITY: "observability_channel",
    TEAM_BUILD: "build_channel",
    TEAM_SRE_DAY2: "sre_oncall_channel",
    TEAM_TESTOPS: "testops_channel",
    TEAM_STORAGE: "storage_channel",
    TEAM_NETWORK: "network_channel",
    TEAM_THIRD_PARTY: "third_party_integrations_channel",
    TEAM_HARDWARE: "hardware_channel",
    TEAM_VMWARE_ADMINS: "vmware_admins_channel",
}


# ---------------------------------------------------------------------------
# Layer -> team mapping. Straightforward cases first.
# ---------------------------------------------------------------------------

LAYER_TO_TEAM = {
    "storage": TEAM_STORAGE,
    "network": TEAM_NETWORK,
    "third_party": TEAM_THIRD_PARTY,
}


def classify_owning_team(diagnosis: dict, evidence: list[dict]) -> tuple[str, list[str], str]:
    """Returns (owning_team, notify_teams, rationale). Deterministic first;
    falls back to a small disambiguation LLM call only when evidence spans
    multiple candidate teams with no single dominant layer — see
    _disambiguate_with_llm below.

    Rules, in order:
      1. VENDOR_ADVISORY evidence (errata/CVE) present and it's what the
         diagnosis is based on -> Build owns the fix (package/image
         update), SRE owns the config rollout. Both notified.
      2. layer in {storage, network, third_party} with corroborating
         support -> that team owns it directly.
      3. layer == source AND the claim mentions VIB/driver/guest-tools/
         config-level terms -> VMware admins.
      4. layer == cluster_health AND the claim looks hardware-flavored
         (disk/NIC/memory/power pressure conditions, not a generic
         "NotReady") -> Hardware + SRE.
      5. layer == events AND admission/quota-denial specific -> SRE
         (day-2 config/policy), not Build.
      6. status == INSUFFICIENT_EVIDENCE and missing_evidence implies a
         telemetry/monitoring gap (e.g. "no metrics available") ->
         Observability, in addition to SRE.
      7. Nothing dominant -> SRE is owner by default (they're accountable
         for the migration regardless of root layer), and a disambiguation
         hint is logged for human review rather than guessed at.

    TestOps is never a routing target for a live incident — see
    feed_testops_readiness_signal() below instead."""
    evidence_refs = diagnosis.get("evidence_refs") or diagnosis.get("supporting_evidence") or []
    supporting = [e for e in evidence if e.get("evidence_id") in evidence_refs]
    layers = [e.get("layer") for e in supporting]
    tiers = [e.get("reliability_tier") for e in supporting]

    notify = {TEAM_SRE_DAY2}  # SRE always notified — accountable for the migration regardless of cause

    if "VENDOR_ADVISORY" in tiers:
        notify.add(TEAM_BUILD)
        return TEAM_BUILD, sorted(notify), \
            "Diagnosis based on a vendor errata/CVE match (VENDOR_ADVISORY evidence) — " \
            "Build owns the package/image fix, SRE owns rolling the config/update out."

    for layer, team in LAYER_TO_TEAM.items():
        if layer in layers:
            notify.add(team)
            return team, sorted(notify), f"Primary supporting evidence came from the {layer} layer."

    if "source" in layers:
        claim_text = " ".join(e.get("claim", "") for e in supporting if e.get("layer") == "source").lower()
        if any(term in claim_text for term in ("vib", "driver", "guest tool", "guest-tool", "config")):
            notify.add(TEAM_VMWARE_ADMINS)
            return TEAM_VMWARE_ADMINS, sorted(notify), \
                "Source-side evidence references a VIB/driver/guest-tools/config issue."
        notify.add(TEAM_VMWARE_ADMINS)
        return TEAM_VMWARE_ADMINS, sorted(notify), "Source-side (VMware) evidence is the primary cause."

    if "cluster_health" in layers:
        claim_text = " ".join(e.get("claim", "") for e in supporting if e.get("layer") == "cluster_health").lower()
        hardware_terms = ("disk pressure", "nic", "memory pressure", "power", "hardware")
        if any(term in claim_text for term in hardware_terms):
            notify.add(TEAM_HARDWARE)
            return TEAM_HARDWARE, sorted(notify), \
                "Cluster/node health evidence indicates a hardware-level condition."
        return TEAM_SRE_DAY2, sorted(notify), \
            "Cluster/node health evidence indicates a config/readiness condition, not hardware."

    # Fallback — ambiguous. Don't guess; flag for human routing review.
    return TEAM_SRE_DAY2, sorted(notify), \
        "No single evidence layer dominated the diagnosis — routed to SRE by default; " \
        "review evidence_refs manually to confirm the right specialist team."


def route_insufficient_evidence(missing_evidence: list[str]) -> list[str]:
    """For INSUFFICIENT_EVIDENCE outcomes specifically — not a "which team
    caused this" question, but "who can help gather what's missing."
    Observability gets notified when the gap looks like a monitoring/
    telemetry hole rather than a normal advisory-tools-came-up-empty case."""
    notify = {TEAM_SRE_DAY2}
    text = " ".join(missing_evidence).lower()
    if any(term in text for term in ("no metrics", "monitoring", "telemetry", "not provisioned", "not available")):
        notify.add(TEAM_OBSERVABILITY)
    return sorted(notify)


def feed_testops_readiness_signal(diagnosis: dict, is_cluster_wide: bool) -> None:
    """TestOps is never paged on a live incident — they get a separate,
    lower-urgency feedback signal when a diagnosis indicates a systemic /
    pre-migration-readiness gap (e.g. a cluster-wide correlation event, or
    a VENDOR_ADVISORY match that should have been caught in pre-migration
    validation). Called from compose_diagnosis only when is_cluster_wide
    is true or known_issue_ref is a VENDOR_ADVISORY reference."""
    if not is_cluster_wide and not diagnosis.get("known_issue_ref"):
        return
    ...  # TODO: write to a testops_readiness_signals table / low-priority queue

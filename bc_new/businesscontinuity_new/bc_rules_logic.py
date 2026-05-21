"""
bc_rules_logic.py
-----------------
Business Continuity decision logic.
Place in: businesscontinuity/bc_rules_logic.py

Determines action_during_lp for each server according to the BC decision diagram.
Only servers in the selected (DR-affected) datacenter are processed.
Servers outside the datacenter are simply not included in the queryset — no action applied.

    DATACENTER (affected by DR — pre-filtered)
        └─ CLUSTER = YES
        │       └─ IN_LIVE_PLAY = YES → text A
        │       └─ IN_LIVE_PLAY = NO  → text B
        └─ CLUSTER = NO
                └─ IN_LIVE_PLAY = YES
                │       └─ PHYSICAL            → text C
                │       └─ VIRTUAL + FIXED     → text D
                │       └─ VIRTUAL + STRETCHED → text E
                └─ IN_LIVE_PLAY = NO
                        └─ PHYSICAL            → text F
                        └─ VIRTUAL + FIXED     → text G
                        └─ VIRTUAL + STRETCHED → text H
"""

from dataclasses import dataclass
from typing import Optional


# ── Rule keys ─────────────────────────────────────────────────────────────────

RULE_CLUSTER_YES_LP_YES = "cluster_yes_lp_yes"  # A
RULE_CLUSTER_YES_LP_NO  = "cluster_yes_lp_no"   # B
RULE_NO_YES_PHYS        = "no_yes_phys"          # C
RULE_NO_YES_VIRT_FIXED  = "no_yes_virt_fixed"    # D
RULE_NO_YES_VIRT_STR    = "no_yes_virt_str"      # E
RULE_NO_NO_PHYS         = "no_no_phys"           # F
RULE_NO_NO_VIRT_FIXED   = "no_no_virt_fixed"     # G
RULE_NO_NO_VIRT_STR     = "no_no_virt_str"       # H

# Ordered list used to iterate rules consistently across views and templates
ALL_RULES = [
    RULE_CLUSTER_YES_LP_YES,
    RULE_CLUSTER_YES_LP_NO,
    RULE_NO_YES_PHYS,
    RULE_NO_YES_VIRT_FIXED,
    RULE_NO_YES_VIRT_STR,
    RULE_NO_NO_PHYS,
    RULE_NO_NO_VIRT_FIXED,
    RULE_NO_NO_VIRT_STR,
]

# Default action texts shown in the wizard — editable by users and persisted in BCRuleTexts
DEFAULT_TEXTS = {
    RULE_CLUSTER_YES_LP_YES: "Powered off until 09th May failback. Cluster resources in MN until 23rd May",
    RULE_CLUSTER_YES_LP_NO:  "Powered off and cluster resources in MN until 09th May failback",
    RULE_NO_YES_PHYS:        "Powered off until 23rd May",
    RULE_NO_YES_VIRT_FIXED:  "Powered off until 23rd May",
    RULE_NO_YES_VIRT_STR:    "Moved to MN until 23rd May",
    RULE_NO_NO_PHYS:         "Powered off until 09th May failback",
    RULE_NO_NO_VIRT_FIXED:   "Powered off until 09th May failback",
    RULE_NO_NO_VIRT_STR:     "Moved to MN until 23rd May",
}

# MACHINE_TYPE values that identify a physical server
PHYSICAL_MACHINE_TYPES = {"PHYSICAL", "BAREMETAL", "BARE METAL", "BARE-METAL"}

# VM_TYPE values that identify a stretched VM
STRETCHED_VM_TYPES = {"STRETCHED", "STRETCH"}


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class BCResult:
    """Holds the computed BC outcome for a single ServerUnique."""
    server_unique_id: int
    hostname:         str
    rule_key:         str   # one of the RULE_* constants above
    action_text:      str   # final text to write into action_during_lp


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_physical(machine_type: Optional[str]) -> bool:
    """Return True if machine_type matches a known physical server identifier."""
    if not machine_type:
        return False
    return machine_type.strip().upper() in PHYSICAL_MACHINE_TYPES


def _is_stretched(vm_type: Optional[str]) -> bool:
    """Return True if vm_type matches a known stretched VM identifier."""
    if not vm_type:
        return False
    return vm_type.strip().upper() in STRETCHED_VM_TYPES


# ── Public API ────────────────────────────────────────────────────────────────

def get_rule_key(
    cluster: Optional[str],
    in_live_play: Optional[str],
    machine_type: Optional[str],
    vm_type: Optional[str],
) -> str:
    """
    Compute the BC rule key for a single server.
    Only called for servers already filtered to the DR-affected datacenter.

    Args:
        cluster:      Value of ServerUnique.cluster ("YES" / "NO" / other).
        in_live_play: Value of ServerUnique.in_live_play ("YES" / "NO" / other).
        machine_type: Value of Server.MACHINE_TYPE.
        vm_type:      Value of Server.VM_TYPE.

    Returns:
        One of the RULE_* constants.
    """
    is_cluster  = (cluster      or "").strip().upper() == "YES"
    is_liveplay = (in_live_play or "").strip().upper() == "YES"

    if is_cluster:
        return RULE_CLUSTER_YES_LP_YES if is_liveplay else RULE_CLUSTER_YES_LP_NO

    # Cluster = NO — branch on in_live_play, then machine type
    physical = _is_physical(machine_type)

    if is_liveplay:
        if physical:
            return RULE_NO_YES_PHYS
        return RULE_NO_YES_VIRT_STR if _is_stretched(vm_type) else RULE_NO_YES_VIRT_FIXED
    else:
        if physical:
            return RULE_NO_NO_PHYS
        return RULE_NO_NO_VIRT_STR if _is_stretched(vm_type) else RULE_NO_NO_VIRT_FIXED


def compute_bc_results(servers_qs, datacenter: str, rule_texts: dict) -> list[BCResult]:
    """
    Compute BC outcomes for a queryset of servers belonging to a single datacenter.

    Args:
        servers_qs: Server.objects.filter(DATACENTER=datacenter).select_related('server_unique')
        datacenter: The selected datacenter (all servers in the queryset belong to it).
        rule_texts: Dict {rule_key: text} — user-defined texts from the wizard.
                    Missing keys fall back to DEFAULT_TEXTS.

    Returns:
        List of BCResult, one per distinct ServerUnique.
    """
    # Merge defaults with user-supplied texts (user values take precedence)
    texts = {**DEFAULT_TEXTS, **rule_texts}

    # Deduplicate by ServerUnique — one Server can have multiple Server rows
    seen    = set()
    results = []

    for server in servers_qs.select_related('server_unique'):
        su = server.server_unique
        if su.id in seen:
            continue
        seen.add(su.id)

        rule_key = get_rule_key(
            cluster=su.cluster,
            in_live_play=su.in_live_play,
            machine_type=server.MACHINE_TYPE,
            vm_type=server.VM_TYPE,
        )

        results.append(BCResult(
            server_unique_id=su.id,
            hostname=su.hostname,
            rule_key=rule_key,
            action_text=texts[rule_key],
        ))

    return results


def group_by_rule(results: list[BCResult]) -> dict:
    """
    Group BCResult instances by rule_key.

    Returns:
        Dict { rule_key: [BCResult, ...] } — rules with no matching servers are omitted.
    """
    grouped = {k: [] for k in ALL_RULES}
    for r in results:
        grouped[r.rule_key].append(r)
    # Drop empty rules to keep the output clean
    return {k: v for k, v in grouped.items() if v}

"""Pure authorization decision for product-bound external review actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str | None = None
    authorization_ids: tuple[str, ...] = ()


# A run is active while it can still reach a posting decision.  There is no
# "attempting" status: an approved run stays approved while individual provider
# calls are in flight, so a second approved finding is still postable.
ACTIVE_STATUSES = frozenset({"running", "pending_input", "pending_approval", "approved", "paused"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "abandoned"})


def evaluate_action(checkpoint: dict[str, Any] | None, event: dict[str, Any]) -> GateDecision:
    """Return an allow/deny decision without mutating state.

    Non-MCRT actions remain outside the product gate.  Once a caller presents
    MCRT provenance, every mismatch is denied rather than silently downgraded.
    """
    if not event.get("mcrt"):
        return GateDecision(True)
    if not isinstance(checkpoint, dict):
        return GateDecision(False, "MCRT action has no valid checkpoint")
    if checkpoint.get("status") != "approved":
        return GateDecision(False, "MCRT action is not approved for posting")
    identity = checkpoint.get("identity")
    if not isinstance(identity, dict):
        return GateDecision(False, "checkpoint has no bound repository identity")
    for key in ("workspace", "repository", "pull_request_id", "binding_digest"):
        if event.get(key) != identity.get(key):
            return GateDecision(False, f"MCRT action {key} does not match approval")
    ids = event.get("finding_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item for item in ids):
        return GateDecision(False, "MCRT action must identify one or more findings")
    approved = checkpoint.get("approved_finding_ids")
    if not isinstance(approved, list) or not set(ids) <= set(approved):
        return GateDecision(False, "MCRT action contains an unapproved finding")
    attempted = set(checkpoint.get("attempted_finding_ids", []))
    repeated = sorted(set(ids) & attempted)
    if repeated:
        return GateDecision(False, f"MCRT finding was already attempted: {', '.join(repeated)}")
    if event.get("role") not in {None, "poster"}:
        return GateDecision(False, "only the MCRT poster may use an approval")
    return GateDecision(True, authorization_ids=tuple(ids))

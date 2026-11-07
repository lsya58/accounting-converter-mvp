"""Exact subaccount observations for the 2026-07-19 Buddies JDL 35.5 probe.

These observations do not make any mapping READY. A Human must still select
and confirm a target subaccount in the current master. Names are stored only
as hashes because the actual JDL subaccount names are private.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .models import JdlTargetContext
from .scoped_evidence import ScopeState, scope_state


@dataclass(frozen=True)
class SubaccountKeepEvidence:
    case_id: str
    evidence_id: str
    side: str
    parent_code: str
    opposite_account_code: str
    subaccount_code: str
    identity_sha256: str
    flag: str = "1111"
    layout: str = "B1"
    tax_cells: tuple[str, str] = ("NO", "NO")


VERIFIED_CODED_KEEP = (
    SubaccountKeepEvidence(
        "SK-1551", "EVID-YAYOI-JDL-35-5-BUDDIES-SUBKEEP-1551-001",
        "CREDIT", "1551", "1111", "1",
        "679853dfcab1ff1a18116b7996c2d2b8a5a91579523513a965c16eb17a7950a8",
    ),
    SubaccountKeepEvidence(
        "SK-3141", "EVID-YAYOI-JDL-35-5-BUDDIES-SUBKEEP-3141-001",
        "DEBIT", "3141", "1111", "1",
        "e3e0e1bd436b34c8e8f1d069b572b592029cffd6a6572c77d11e2de7b0136483",
    ),
)

# Import-screen rejection, not a successful round-trip. Both rejected files
# had no re-exported cases, including their controls; file-level atomicity is
# therefore observed, but the exact JDL imported count is unavailable.
REJECTED_SUBACCOUNT_REPRESENTATIONS = {
    ("3141", ""): "EVID-YAYOI-JDL-35-5-BUDDIES-SUB-BLANK-3141-REJECT-001",
    ("1551", "0000"): "EVID-YAYOI-JDL-35-5-BUDDIES-SUB-0000-1551-REJECT-001",
    ("3141", "0000"): "EVID-YAYOI-JDL-35-5-BUDDIES-SUB-0000-3141-REJECT-001",
}


def _canonical_code(code: str) -> str | None:
    if not code.isdecimal():
        return None
    return str(int(code))


def _identity_hash(parent: str, code: str, name: str) -> str:
    return hashlib.sha256(f"{parent}\0{code}\0{name}".encode("utf-8")).hexdigest()


def exact_keep_evidence(
    context: JdlTargetContext, *, side: str, parent_code: str,
    opposite_account_code: str, subaccount_code: str,
    flag: str, layout: str, tax_cells: tuple[str, str],
) -> str | None:
    """Return one Evidence ID only for the exact observed target identity."""
    if scope_state(context) is not ScopeState.IN_SCOPE:
        return None
    canonical = _canonical_code(subaccount_code)
    if canonical is None:
        return None
    for observation in VERIFIED_CODED_KEEP:
        if (side, parent_code, opposite_account_code, canonical, flag, layout, tax_cells) != (
            observation.side, observation.parent_code, observation.opposite_account_code,
            observation.subaccount_code, observation.flag, observation.layout, observation.tax_cells,
        ):
            continue
        matches = [
            sub for sub in context.subaccounts
            if sub.parent_account_code == parent_code
            and _canonical_code(sub.target_master_code) == canonical
        ]
        if len(matches) != 1:
            return None
        name = matches[0].target_name or matches[0].output_name
        if _identity_hash(parent_code, canonical, name) == observation.identity_sha256:
            return observation.evidence_id
    return None

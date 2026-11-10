"""JDL drops the trailing spaces of a 摘要 on CSV Import (real Evidence, Yayoi company A Pilot-1).

Two separate things, never merged:

1. Technical Evidence (``EVIDENCE``): what JDL did. In the Pilot-1 round (2026-11-10, 207 journals /
   465 rows) the re-export differed from the imported CSV only in 45 摘要 (44 journals): exactly the
   trailing run of spaces was gone (U+0020 x1 / x2, or U+3000 x1). Leading and inner spaces stayed;
   every other field matched. The comparator recognises this only when the re-export 摘要 is the
   candidate 摘要 with exactly one of the observed trailing runs removed (no general strip()).
2. The user's acceptance of that information loss: recorded only by a Human, in an acceptance file
   bound to the exact rows (``check_acceptance``). Without it a round trip is never a formal PASS.

Evidence history: each real round that shows a new trailing run is its own Evidence entry; earlier
entries are never edited. ``EVIDENCE`` (Pilot-1) keeps its three runs; ``EVIDENCE_PILOT2`` adds
exactly three half-width spaces. ``EVIDENCES`` lists them; a run counts as observed only through the
entry that recorded it. 4+ half-width spaces, 2+ ideographic spaces, tabs and mixed runs are in no entry.

Scope: the company setting and the JDL target scope the round ran in (JDL IBEX 出納帳 35.5 official
journal CSV import, 税抜・原則・一括比例・売上切上げ/仕入四捨五入・振替伝票入力行数16). Not widened by
similarity; other characters, other trailing runs or other scopes stay UNEXPECTED_CHANGE.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HALF_WIDTH_SPACE = " "
IDEOGRAPHIC_SPACE = "　"


@dataclass(frozen=True)
class DescriptionTrailingSpaceEvidence:
    evidence_id: str
    jdl_product: str
    jdl_version: str
    import_format: str
    company_setting_ids: frozenset[str]
    scope_id: str
    candidate_file: str
    candidate_sha256: str
    reexport_file: str
    reexport_sha256: str
    observed_suffixes: frozenset[str]   # the exact trailing runs JDL was seen to remove
    observed_rows: int
    observed_journals: int
    technical_state: str
    condition: str


EVIDENCE = DescriptionTrailingSpaceEvidence(
    evidence_id="EVID-YAYOI-JDL-35-5-BUDDIES-PILOT1-DESCRIPTION-TRAILING-SPACE-REMOVED-001",
    jdl_product="JDL IBEX 出納帳",
    jdl_version="35.5",
    import_format="JDL IBEX 出納帳 公式仕訳CSV（30列）",
    company_setting_ids=frozenset({"company-f92affc1f3ed43c8aee36380ab612f9d"}),
    scope_id="JDL-35-5-TAX-EXCL-PROP-SALES-CEIL-PURCH-HALFUP-VOUCHER-ROWS-16",
    candidate_file="BUDDIES_PILOT1_20251201-1230_JDL_IMPORT.csv",
    candidate_sha256="6b88c0a9e7a38ff9cbf041060553a357b119016e86f7156921130d2b3cec268e",
    reexport_file="BUDDIES_PILOT1_20251201-1230_JDL_REEXPORT.csv",
    reexport_sha256="cc61d8a8430098fe9fb17ac66cc10e0ddadb069ef3e5819ddfe80d27143a801b",
    observed_suffixes=frozenset({HALF_WIDTH_SPACE, HALF_WIDTH_SPACE * 2, IDEOGRAPHIC_SPACE}),
    observed_rows=45,
    observed_journals=44,
    technical_state="TECHNICAL_VERIFIED_INFORMATION_LOSS_PENDING_USER_ACCEPTANCE",
    condition=("再Exportの摘要 = 取込CSVの摘要から末尾の空白の並び（半角1・半角2・全角1のいずれか）を"
               "ちょうど取り除いたもの。残った摘要は空でなく、末尾が空白でない。他の列は既存の判定のまま。"),
)


EVIDENCE_PILOT2 = DescriptionTrailingSpaceEvidence(
    # Additional Evidence (2026-11-10, Pilot-2 real round: 174 journals / 434 rows). In that round 48 rows
    # (44 journals) lost their trailing run: 33 x one and 14 x two half-width spaces (already in EVIDENCE) and
    # ONE row with three half-width spaces (journal 67695, voucher 1939, 2026-05-12), which no entry covered.
    # Only the new run is registered here; leading / inner spaces and every other column were unchanged.
    evidence_id="EVID-YAYOI-JDL-35-5-BUDDIES-PILOT2-DESCRIPTION-TRAILING-SPACE-REMOVED-001",
    jdl_product=EVIDENCE.jdl_product,
    jdl_version=EVIDENCE.jdl_version,
    import_format=EVIDENCE.import_format,
    company_setting_ids=EVIDENCE.company_setting_ids,
    scope_id=EVIDENCE.scope_id,
    candidate_file="BUDDIES_PILOT2_20260501-0529_JDL_IMPORT.csv",
    candidate_sha256="3170b96da93279cfcb52b5ee1ce37618ac7e152998143cec78096710fb4a89ec",
    reexport_file="BUDDIES_PILOT2_20260501-0529_JDL_REEXPORT.csv",
    reexport_sha256="68b6d272b7d454c1f674815fedcda3918221ded43453dd882574a881402b44a2",
    observed_suffixes=frozenset({HALF_WIDTH_SPACE * 3}),
    observed_rows=1,
    observed_journals=1,
    technical_state="TECHNICAL_VERIFIED_INFORMATION_LOSS_PENDING_USER_ACCEPTANCE",
    condition=EVIDENCE.condition.replace("半角1・半角2・全角1", "半角3"),
)

EVIDENCES = (EVIDENCE, EVIDENCE_PILOT2)


def evidence_for_suffix(suffix: str, evidences=EVIDENCES) -> DescriptionTrailingSpaceEvidence | None:
    """The entry that recorded this exact trailing run (the earliest one), else None."""
    return next((item for item in evidences if suffix in item.observed_suffixes), None)


def removed_trailing_suffix(before: str, after: str, suffixes: frozenset[str]) -> str | None:
    """The trailing run JDL removed, when that is the ONLY difference and the run was observed."""
    if not suffixes or before == after or not after or not before.startswith(after):
        return None
    if after[-1] in (HALF_WIDTH_SPACE, IDEOGRAPHIC_SPACE):
        return None  # JDL removed the whole trailing run, never part of it
    suffix = before[len(after):]
    return suffix if suffix in suffixes else None


def suffix_counts(suffix: str) -> dict[str, int]:
    return {"half_width_space": suffix.count(HALF_WIDTH_SPACE), "ideographic_space": suffix.count(IDEOGRAPHIC_SPACE)}


def scope_problems(company_setting_id: str | None, context,
                   evidence: DescriptionTrailingSpaceEvidence = EVIDENCE) -> tuple[str, ...]:
    """Empty when this Evidence entry applies to this company setting and JDL target."""
    from accounting_converter.adapters.output.jdl import scoped_evidence
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    problems = []
    if company_setting_id not in evidence.company_setting_ids:
        problems.append("COMPANY_OUT_OF_SCOPE")
    if not (
        context is not None
        and context.product == evidence.jdl_product
        and context.version == evidence.jdl_version
        and ev.context_is_verified(context)
        and scoped_evidence.scope_state(context) is scoped_evidence.ScopeState.IN_SCOPE
        and scoped_evidence.scope_id_for(context.voucher_row_limit) == evidence.scope_id
    ):
        problems.append("CONTEXT_OUT_OF_SCOPE")
    return tuple(problems)


def applicable_suffixes(company_setting_id: str | None, context, evidences=EVIDENCES) -> frozenset[str]:
    """The trailing runs usable here: the union over the entries whose own scope applies."""
    return frozenset().union(*(item.observed_suffixes for item in evidences
                               if not scope_problems(company_setting_id, context, item)))


def rows_sha256(rows: list[dict]) -> str:
    """Binds an acceptance to these exact rows (descriptions included)."""
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ACCEPTANCE_SCHEMA = "jdl-description-trailing-space-acceptance-v1"
ACCEPTED = "ACCEPTED"
NOT_RECORDED = "NOT_RECORDED"
INVALID = "INVALID"
_ACCEPTANCE_TEXT_FIELDS = ("accepted_by", "reference")


def evidence_ids_of(rows: list[dict]) -> list[str]:
    """The Evidence entries the rows rest on (each row names its own)."""
    return sorted({row.get("evidence_id") for row in rows})


def acceptance_payload(*, candidate_sha256: str, reexport_sha256: str, rows: list[dict], accepted_by: str,
                       reference: str, accepted_on: date) -> dict:
    """What a Human's acceptance says. Written only by the acceptance tool on explicit Human input."""
    return {
        "schema": ACCEPTANCE_SCHEMA, "evidence_ids": evidence_ids_of(rows), "decision": ACCEPTED,
        "accepted_by": accepted_by.strip(), "reference": reference.strip(), "accepted_on": accepted_on.isoformat(),
        "candidate_sha256": candidate_sha256, "reexport_sha256": reexport_sha256,
        "rows": len(rows), "rows_sha256": rows_sha256(rows),
    }


def check_acceptance(path: Path | None, *, candidate_sha256: str, reexport_sha256: str, rows: list[dict]) -> dict:
    """NOT_RECORDED without a file; ACCEPTED only for an acceptance of exactly these files and rows."""
    if path is None:
        return {"state": NOT_RECORDED}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": INVALID, "problems": ["UNREADABLE"]}
    checks = {
        "schema": payload.get("schema") == ACCEPTANCE_SCHEMA,
        "evidence_ids": payload.get("evidence_ids") == evidence_ids_of(rows)
        and all(evidence_id in {item.evidence_id for item in EVIDENCES} for evidence_id in evidence_ids_of(rows)),
        "decision": payload.get("decision") == ACCEPTED,
        "who_and_reference": all(isinstance(payload.get(k), str) and payload[k].strip()
                                 for k in _ACCEPTANCE_TEXT_FIELDS),
        "date": _is_iso_date(payload.get("accepted_on")),
        "candidate_sha256": payload.get("candidate_sha256") == candidate_sha256,
        "reexport_sha256": payload.get("reexport_sha256") == reexport_sha256,
        "rows": payload.get("rows") == len(rows) and payload.get("rows_sha256") == rows_sha256(rows),
    }
    problems = sorted(name for name, ok in checks.items() if not ok)
    return {"state": INVALID, "problems": problems} if problems else {
        "state": ACCEPTED, "accepted_by": payload["accepted_by"], "accepted_on": payload["accepted_on"],
        "reference": payload["reference"]}


def _is_iso_date(value) -> bool:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True

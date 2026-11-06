"""Plan one JDL Evidence campaign for a Yayoi 仕訳日記帳 company. Internal diagnostic.

Prints counts and structural keys only (shapes, JDL tax semantics, gap codes):
no account names, descriptions, tax names, amounts or dates.

For every journal it lists the JDL conditions that would still lack Evidence
if the Human confirmed the natural candidate for each tax identity, using the
company's real Tax Context (端数処理). Conditions are grouped into probe keys:
one probe (one synthetic journal in the target test company) can settle one
key. A journal is unblocked only when every key it needs is settled, so the
plan ranks keys by the journals they would unblock together (greedy).

Nothing is confirmed, registered or written. Simulated, not formal readiness:
account mapping (Human) and account-specific sales Evidence are listed apart.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.adapters.output.jdl.row_evidence import JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic


def candidate_semantic(identity: str):
    """The Yayoi → JDL candidates as they were BEFORE the 2026-11-05 campaign.

    This planner describes what the campaign had to settle; the production
    candidates (application.yayoi_review) now also cover the identities the
    campaign verified, so they are deliberately not used here."""
    base, _, extra = identity.partition("｜")
    if extra and extra != "適格｜100%":
        return None
    if base == "対象外":
        return JdlTaxSemantic.NO_TAX
    if "軽" in base or "輸" in base or "控除" in base:
        return None
    if "課対仕入" in base and "10%" in base:
        return JdlTaxSemantic.PURCHASE_10_INTERNAL
    if "課税売上" in base and "10%" in base:
        return JdlTaxSemantic.SALES_10_EXTERNAL
    if base.startswith("非課仕入"):
        return JdlTaxSemantic.NON_TAXABLE_PURCHASE
    if base.startswith("非課売上"):
        return JdlTaxSemantic.NON_TAXABLE_SALES
    return None


from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows, physical_row_shape
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

NO_TAX = "JDL_NO_TAX"
SHORT = {
    "JDL_NO_TAX": "NO", "JDL_SALES_10_EXTERNAL": "S10", "JDL_PURCHASE_10_INTERNAL": "P10",
    "JDL_NON_TAXABLE_PURCHASE": "NP", "JDL_NON_TAXABLE_SALES": "NS", "UNAVAILABLE": "UNK",
}
# Representations seen on real JDL only for these accounts (fewer than three,
# or 課税売上10%, which is never generalized). Settled per target account.
ACCOUNT_SPECIFIC = {
    ("CREDIT", "JDL_SALES_10_EXTERNAL"): "SALES10_TARGET_ACCOUNT",
    ("DEBIT", "JDL_NON_TAXABLE_PURCHASE"): "NONPUR_TARGET_ACCOUNT",
    ("CREDIT", "JDL_NON_TAXABLE_SALES"): "NONSALE_TARGET_ACCOUNT",
}


def row_signature(entry) -> tuple[tuple[str, str], ...] | None:
    """Per physical row: (debit tax, credit tax) as short semantic codes; '-' = no line."""
    rows = journal_physical_rows(entry)
    if rows is None:
        return None

    def code(line):
        if line is None:
            return "-"
        if not line.tax_info:
            return "NO"
        semantic = candidate_semantic(line.tax_info.category)
        return "UNK" if semantic is None else SHORT[semantic.value]

    return tuple((code(row.debit), code(row.credit)) for row in rows)


def unavailable_kind(identity: str) -> str:
    """Why a Yayoi tax identity has no JDL candidate (generic class, not the name)."""
    base, _, extra = identity.partition("｜")
    if "不可" in extra or "控除" in base:
        return "NON_DEDUCTIBLE"  # checked before 8%: 軽減8%の控除不可も控除不可
    if "軽" in base:
        return "REDUCED_8"
    if "80%" in extra or "80％" in extra:
        return "TRANSITIONAL_80"
    if "輸出" in base:
        return "EXPORT_EXEMPT"
    if "輸入" in base or "輸" in base:
        return "IMPORT"
    if base in {"対外仕入", "対外売上"}:
        # 対象外 on a purchase/sales account: JDL side is the known blank/0
        # (MF 対象外仕入 Evidence); only the Yayoi candidate is missing.
        return "OUT_OF_SCOPE_KNOWN_REPRESENTATION"
    if extra and extra != "適格｜100%":
        return "OTHER_INVOICE_CLASS"
    return "OTHER"


def _shape_key(shape) -> str:
    return f"{shape[0]}D{shape[1]}C/{shape[2]}rows"


def row_pattern(rows) -> str:
    """Physical rows as runs of B (debit+credit), D (debit only), C (credit only)."""
    kinds = ["B" if r.debit is not None and r.credit is not None else "D" if r.debit is not None else "C"
             for r in rows]
    runs = []
    for kind in kinds:
        if runs and runs[-1][0] == kind:
            runs[-1][1] += 1
        else:
            runs.append([kind, 1])
    return "".join(f"{kind}{count}" for kind, count in runs)


def pattern_class(pattern: str) -> str:
    """Structural class used to share one serializer rule (B=both, D, C)."""
    import re

    if re.fullmatch(r"B\d+", pattern):
        return "PAIRED(Bn)"
    if re.fullmatch(r"B1D\d+", pattern):
        return "FAN_DEBIT_FIRST_PAIRED(B1Dn)"
    if re.fullmatch(r"D\d+C1", pattern) or re.fullmatch(r"D\d+B1", pattern):
        return "FAN_DEBIT_THEN_CREDIT(DnC1|DnB1)"
    if re.fullmatch(r"C1D\d+", pattern):
        return "FAN_CREDIT_FIRST(C1Dn)"
    if re.fullmatch(r"B1C\d+", pattern) or re.fullmatch(r"C\d+B1", pattern):
        return "FAN_CREDIT(B1Cn|CnB1)"
    if re.fullmatch(r"B\d+D\d+", pattern):
        return "PAIRED_THEN_DEBIT(BkDn)"
    if re.fullmatch(r"B\d+C\d+", pattern):
        return "PAIRED_THEN_CREDIT(BkCn)"
    if re.fullmatch(r"D\d+C\d+", pattern):
        return "DEBITS_THEN_CREDITS(DnCm)"
    return "MIXED"


def journal_keys(entry, context) -> tuple[set[str], dict]:
    """Probe keys this journal needs, and its structural profile."""
    keys: set[str] = set()
    rows = journal_physical_rows(entry)
    shape = physical_row_shape(rows) if rows is not None else None
    logical = (sum(l.side.value == "DEBIT" for l in entry.lines), sum(l.side.value == "CREDIT" for l in entry.lines))
    if rows is None:
        keys.add("ROW_STRUCTURE_UNRESOLVED")
    elif shape[:2] != (1, 1) and (
        shape[:2] not in ev.verified_mf_shapes() or shape not in JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
    ):
        keys.add(f"SHAPE:{_shape_key(shape)}")
    taxed = []
    lines = []
    for line in entry.lines:
        identity = line.tax_info.category if line.tax_info else "対象外"
        semantic = candidate_semantic(identity) if line.tax_info else None
        if line.tax_info and semantic is None:
            keys.add(f"TAX_UNAVAILABLE:{unavailable_kind(identity)}:{line.side.value}")
            lines.append((line.side.value, "UNAVAILABLE"))
            continue
        value = semantic.value if semantic is not None else NO_TAX
        lines.append((line.side.value, value))
        if value != NO_TAX:
            taxed.append((line.side.value, value))
            if (line.side.value, value) not in ev.LINE_CAPABILITIES:
                keys.add(f"TAX_SIDE:{line.side.value}:{value}")
            elif (line.side.value, value) in ACCOUNT_SPECIFIC:
                keys.add(ACCOUNT_SPECIFIC[(line.side.value, value)])
        explicit = line.tax_info.tax_amount if line.tax_info else None
        if explicit is not None and value != NO_TAX:
            gap = ev.explicit_tax_gap(explicit, line.amount, value, context)
            if gap is not None:
                keys.add(f"EXPLICIT_TAX:{gap}:{line.side.value}:{value}")
        if value == ev.JdlTaxSemantic.SALES_10_EXTERNAL.value and not ev._tax_rounding_is_unambiguous(line.amount):
            keys.add("SALES10_ROUNDING_ACCOUNT")  # account-specific; target account is a Human mapping
    if logical == (2, 2):
        # 2D2C is released per exact taxed layout (VERIFIED_2D2C_TAXED).
        if tuple(taxed) not in ev.VERIFIED_2D2C_TAXED:
            keys.add("TAXED_2D2C_LAYOUT:" + ",".join(f"{s[0]}:{SHORT[t]}" for s, t in taxed))
    elif len(taxed) > 1 and logical not in ev.VERIFIED_COMPOUND_SHAPES:
        keys.add(f"MULTI_TAXED:{logical[0]}D{logical[1]}C")
    if entry.metadata.get("yayoi_closing"):
        keys.add("CLOSING_ENTRY")
    profile = {
        "signature": row_signature(entry),
        "pattern": row_pattern(rows) if rows is not None else "unresolved",
        "shape": _shape_key(shape) if shape else "unresolved",
        "logical": f"{logical[0]}D{logical[1]}C",
        "taxed_lines": len(taxed),
        "taxed_layout": tuple(sorted(Counter(taxed).items())),
    }
    return keys, profile


def family(key: str) -> str:
    return key.split(":", 1)[0]


def greedy_plan(needs: dict[str, frozenset[str]], limit: int) -> list[dict]:
    """Pick keys one at a time by journals newly unblocked (ties: journals touched)."""
    settled: set[str] = set()
    plan = []
    open_journals = {jid: keys for jid, keys in needs.items() if keys}
    all_keys = Counter(key for keys in open_journals.values() for key in keys)
    while len(plan) < limit and open_journals:
        def gain(key):
            unlocked = sum(1 for keys in open_journals.values() if keys <= settled | {key})
            return unlocked, all_keys[key]

        candidates = [key for key in all_keys if key not in settled]
        if not candidates:
            break
        best = max(candidates, key=gain)
        unlocked, touched = gain(best)
        settled.add(best)
        done = [jid for jid, keys in open_journals.items() if keys <= settled]
        for jid in done:
            del open_journals[jid]
        plan.append({"key": best, "newly_unblocked": len(done), "journals_needing_it": touched,
                     "cumulative_unblocked": sum(1 for keys in needs.values() if keys and keys <= settled)})
    return plan


def campaign(source: Path, context) -> dict:
    entries = detect_format(source).diagnose(source).entries
    needs: dict[str, frozenset[str]] = {}
    profiles = {}
    for entry in entries:
        keys, profile = journal_keys(entry, context)
        needs[entry.id] = frozenset(keys)
        profiles[entry.id] = profile
    key_journals = Counter(key for keys in needs.values() for key in keys)
    single = Counter(next(iter(keys)) for keys in needs.values() if len(keys) == 1)
    by_family = Counter(fam for keys in needs.values() for fam in {family(key) for key in keys})
    # Keys that only matter together with an unavailable tax are not worth a probe yet.
    blocked_by_unknown_representation = {
        jid for jid, keys in needs.items()
        if any(family(key) in {"TAX_UNAVAILABLE", "CLOSING_ENTRY"} for key in keys)
    }
    probe_keys = Counter(
        key for jid, keys in needs.items() if jid not in blocked_by_unknown_representation for key in keys
    )
    shapes = Counter(p["shape"] for p in profiles.values())
    shape_journals = [jid for jid, keys in needs.items() if any(family(key) == "SHAPE" for key in keys)]
    multi_journals = [jid for jid, keys in needs.items() if any(family(key) == "MULTI_TAXED" for key in keys)]
    pattern_classes = Counter(pattern_class(profiles[jid]["pattern"]) for jid in shape_journals)
    patterns = Counter(profiles[jid]["pattern"] for jid in shape_journals)
    multi_layouts = Counter(
        (profiles[jid]["logical"], profiles[jid]["pattern"],
         ",".join(f"{side}:{tax.replace('JDL_', '')}x{n}" for (side, tax), n in profiles[jid]["taxed_layout"]))
        for jid in multi_journals
    )
    # Max rows per class: the boundary a class-level probe set should include.
    class_extent = defaultdict(lambda: [10**9, 0])
    for jid in shape_journals:
        rows = sum(int(part[1:]) for part in __import__("re").findall(r"[BDC]\d+", profiles[jid]["pattern"]))
        extent = class_extent[pattern_class(profiles[jid]["pattern"])]
        extent[0], extent[1] = min(extent[0], rows), max(extent[1], rows)
    return {
        "journals": len(entries),
        "journals_without_any_key": sum(1 for keys in needs.values() if not keys),
        "journals_with_keys": sum(1 for keys in needs.values() if keys),
        "keys_per_journal": dict(sorted(Counter(len(keys) for keys in needs.values()).items())),
        "journals_by_family": dict(by_family.most_common()),
        "journals_by_key": dict(key_journals.most_common()),
        "journals_blocked_by_only_one_key": dict(single.most_common()),
        "journals_needing_self_export_first": len(blocked_by_unknown_representation),
        "keys_for_journals_without_unknown_representation": dict(probe_keys.most_common()),
        "greedy_plan_all": greedy_plan(needs, 40),
        "greedy_plan_known_representation_only": greedy_plan(
            {jid: keys for jid, keys in needs.items() if jid not in blocked_by_unknown_representation}, 40
        ),
        "physical_shapes": {"distinct": len(shapes), "top": dict(shapes.most_common(25))},
        "unverified_shape_journals_by_class": dict(pattern_classes.most_common()),
        "unverified_shape_class_row_extent": {key: tuple(value) for key, value in class_extent.items()},
        "unverified_shape_patterns_top": dict(patterns.most_common(30)),
        "multi_taxed_layouts_top": [
            {"logical": logical, "pattern": pattern, "taxed": taxed, "journals": count}
            for (logical, pattern, taxed), count in multi_layouts.most_common(30)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
    if resolved.context is None:
        raise SystemExit("the company has no confirmed Tax Context")
    print(json.dumps(campaign(args.source, resolved.context), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""How many 摘要 Human confirmations a proven JDL description limit would remove. Counts only.

Planning tool used before the 2026-11-06 gap round; production now applies the
proven rule (`profiles.jdl_official.jdl_description_fits`). This tool only answers
"if CSV Import kept up to N CP932 bytes (full-width 2 / half-width 1), which
descriptions that today need a replacement would no longer need one?" It never
changes the limit and reads the saved setting without writing it.

A description is relieved only when length is its ONLY problem: no control
character, no character that JDL does not round-trip, and CP932 bytes <= N.
Descriptions the Human already replaced are applied first (as production does).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application.description_replacement import has_control_character
from accounting_converter.application.moneyforward_description_replacement import (
    description_requires_replacement,
    journal_descriptions,
    unsafe_description_positions,
)
from accounting_converter.application.yayoi_jdl_workflow import DescriptionReplacementPolicy
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def length_only_within(description: str, byte_limit: int) -> bool:
    if has_control_character(description) or unsafe_description_positions(description):
        return False
    try:
        return len(description.encode("cp932", errors="strict")) <= byte_limit
    except UnicodeEncodeError:
        return False


def relief(entries, byte_limit: int = 64) -> dict:
    needing = [e for e in entries if any(description_requires_replacement(d) for d in journal_descriptions(e))]
    distinct = {d for e in needing for d in journal_descriptions(e) if description_requires_replacement(d)}
    relieved_distinct = {d for d in distinct if length_only_within(d, byte_limit)}
    relieved_journals = [
        e for e in needing
        if all(length_only_within(d, byte_limit) for d in journal_descriptions(e) if description_requires_replacement(d))
    ]
    return {
        "byte_limit_assumed": byte_limit,
        "journals_needing_description_confirmation_now": len(needing),
        "distinct_descriptions_needing_confirmation_now": len(distinct),
        "distinct_relieved_if_limit_proven": len(relieved_distinct),
        "journals_relieved_if_limit_proven": len(relieved_journals),
        "distinct_still_needing_confirmation": len(distinct) - len(relieved_distinct),
        "still_reasons": {
            "control_character": sum(1 for d in distinct - relieved_distinct if has_control_character(d)),
            "unsafe_character": sum(1 for d in distinct - relieved_distinct if unsafe_description_positions(d)),
            "over_byte_limit": sum(1 for d in distinct - relieved_distinct
                                   if not has_control_character(d) and not unsafe_description_positions(d)),
        },
        "note": "planning count; production uses jdl_description_fits",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--byte-limit", type=int, default=64)
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    profile = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id).profile
    entries = detect_format(args.source).diagnose(args.source).entries
    if profile is not None:
        entries = DescriptionReplacementPolicy(profile).apply(entries).entries
    print(json.dumps(relief(entries, args.byte_limit), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

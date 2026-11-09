"""Read-only approval brief for the voucher split of one over-limit journal (for the tax accountant).

Shows, for a chosen row limit, what the existing rule SINGLE_COUNTERPART_BALANCED_V1 would write: the parts, their
JDL layouts, the counterpart amount of each part, that debits, credits, explicit tax and every other column of every
line are unchanged, which Evidence covers each part, and what is lost. It RECORDS NOTHING: the approval is made only
by `yayoi_voucher_split approve` (run by the Human after the tax accountant agrees). Output contains amounts, so it
is written to stdout / data/private only. The same brief with --ignore-signs shows what a signed-line variant would
look like for a journal with negative lines (4012): informational only, that variant is NOT approvable today.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application.voucher_split_brief import brief
from accounting_converter.application.voucher_limit_comparison import compare_limits
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--journal", required=True, help="journal number, e.g. 1739")
    parser.add_argument("--row-limit", type=int, default=64)
    parser.add_argument("--ignore-signs", action="store_true")
    args = parser.parse_args()
    resolved = CompanySettingStore(args.company_store / "companies",
                                   ConversionProfileStore(args.company_store / "profiles")).resolve(args.company_id)
    entry = next(e for e in detect_format(args.source).diagnose(args.source).entries if e.id.endswith(":" + args.journal))
    result = brief(entry, args.row_limit, ignore_signs=args.ignore_signs)
    comparison = compare_limits(args.source, resolved.profile, resolved.context)
    trial = next(t for t in comparison.trials if t.limit == args.row_limit)
    result["blockers_now_assuming_parts_judged"] = sorted(trial.assessment.journal_blockers.get(entry.id, ()))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

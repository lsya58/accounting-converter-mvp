"""Which subaccount decisions a company still has, grouped per parent account. Counts only.

Reads the company's saved settings from a SCRATCH COPY, reviews the source against the
JDL master saved in the setting (re-read after you reload the JDL account list), and prints
the classification of `application.parent_subaccount_policy`. Nothing is confirmed or saved.
The detail sheet (real names) is written only under data/private.

  PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_subaccount_policy_plan \\
      --source ... --company-store <AppData copy> --company-id ... [--sheet data/private/....csv]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from accounting_converter.application import parent_subaccount_policy as policy
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.ui.controllers import AccountingConverterController


def review_of(source: Path, company_store: Path, company_id: str, scratch: Path):
    store = scratch / "store"
    shutil.copytree(company_store, store)
    profiles = ConversionProfileStore(store / "profiles")
    companies = CompanySettingStore(store / "companies", profiles)
    controller = AccountingConverterController(
        profile_store=profiles, company_store=companies,
        preferences_store=ApplicationPreferencesStore(scratch / "prefs.json"))
    controller.load_company_settings()
    controller.select_file(source)
    controller.select_company_setting(company_id)
    return controller.review_company_mapping_updates(company_id, source)


def distinct_journals(source: Path, groups) -> dict:
    """Distinct journals per class (a journal can have several subaccounts)."""
    wanted: dict[tuple[str, str], str] = {}
    for group in groups:
        for member in group.unconfirmed:
            if member.item.mapping_type == "SUBACCOUNT":
                wanted[(group.source_parent, member.item.source_value)] = member.klass
    per_class: dict[str, set[str]] = defaultdict(set)
    all_journals: set[str] = set()
    for entry in detect_format(source).diagnose(source).entries:
        for line in entry.lines:
            klass = wanted.get((line.account, line.sub_account or ""))
            if klass:
                per_class[klass].add(entry.id)
                all_journals.add(entry.id)
    return {"distinct_journals_by_class": {k: len(v) for k, v in sorted(per_class.items())},
            "distinct_journals_any": len(all_journals)}


def sheet(groups) -> bytes:
    rows = [("親科目（弥生）", "JDL親科目（確認済み/候補）", "親科目確認", "補助（弥生）", "分類", "意味", "仕訳数", "親科目のみにできる")]
    for group in groups:
        for member in group.unconfirmed:
            rows.append((group.source_parent, group.parent_target or "", "確認済み" if group.parent_confirmed else "未確認",
                         member.item.source_value, member.klass, policy.CLASS_LABEL[member.klass],
                         member.item.affected_journal_count, "はい" if group.parent_only_possible else "いいえ"))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--sheet", type=Path, help="detail sheet with real names (under data/private only)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        review = review_of(args.source, args.company_store, args.company_id, Path(directory))
    groups = policy.parent_groups(review)
    result = {"review_items_unconfirmed_by_type": {
        t: sum(1 for i in review.items if i.mapping_type == t and not i.already_confirmed)
        for t in ("ACCOUNT", "SUBACCOUNT", "DEFAULT_SUBACCOUNT")},
        **policy.summarize(groups), **distinct_journals(args.source, groups)}
    if args.sheet:
        if "data/private" not in args.sheet.resolve().as_posix():
            raise SystemExit("the sheet contains customer names; write it under data/private only")
        if args.sheet.exists():
            raise SystemExit("sheet already exists; nothing is overwritten")
        args.sheet.write_bytes(sheet(groups))
        result["sheet"] = args.sheet.name
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Write the Yayoi Human review sheet to a private folder (real names, local only).

The sheet lists every identity the Human must decide, grouped (never per
journal): accounts, subaccounts, tax identities with their candidates and
Evidence state, descriptions that JDL cannot keep, and optional information.
It is written only under data/private (refused elsewhere) and is never printed;
the command prints counts only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.profiles.jdl_official import jdl_subaccount_name_fits

from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.application.moneyforward_description_replacement import (
    description_issues,
    description_replacement_candidate,
)
from accounting_converter.application.yayoi_review import review_source
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write


def build_sheet(source: Path, rounding=None, draft: Path | None = None) -> tuple[bytes, dict[str, int]]:
    entries = detect_format(source).read(source)
    review = review_source(entries, rounding=rounding)
    rows = [("区分", "識別子", "親科目", "請求書区分", "仕入税額控除", "借方行", "貸方行", "仕訳数",
             "明示税額行", "未検証の明示税額行", "JDL候補", "Evidence状態", "確認内容")]
    for item in review.accounts:
        rows.append(("科目", item.key, "", "", "", item.debit_lines, item.credit_lines, item.journals,
                     "", "", "", "", "JDL科目を選ぶ"))
    for item in review.subaccounts:
        rows.append(("補助科目", item.key, item.parent, "", "", item.debit_lines, item.credit_lines, item.journals,
                     "", "", "", "", "JDL補助を選ぶ"))
    for item in review.taxes:
        rows.append(("税区分", item.base, "", item.invoice_class, item.purchase_credit, item.debit_lines,
                     item.credit_lines, item.journals, item.explicit_tax_lines, item.explicit_tax_unverified_lines,
                     item.candidate.value if item.candidate else "（候補なし）",
                     " / ".join(f"{gap}:{count}" for gap, count in sorted(item.explicit_tax_gaps.items()))
                     or item.evidence_state,
                     "JDLでの扱いを確認する（候補は未確定）"))
    for item in review.descriptions:
        candidate = description_replacement_candidate(item.current_description)
        rows.append(("摘要", item.current_description, "", "", "", "", "", item.affected_journal_count, "", "",
                     candidate.value if candidate else "", " / ".join(description_issues(item.current_description)),
                     "置き換え文を確認する"))
    if review.sticky_note_journals:
        rows.append(("付箋", "付箋あり", "", "", "", "", "", review.sticky_note_journals, "", "", "", "",
                     "JDLに保持先がない。扱いを決める"))
    departments = Counter(line.department for entry in entries for line in entry.lines if line.department)
    for name, count in sorted(departments.items()):
        rows.append(("部門", name, "", "", "", "", "", count, "", "", "", "",
                     "JDL会社は部門なし。部門を捨てて出すか、JDLで部門を使うか決める"))
    if draft is not None:
        observation = JdlAccountPdfDraftStore().load(draft).observation
        for item in observation.subaccounts:
            if not jdl_subaccount_name_fits(item.name):
                rows.append(("JDL補助名の長さ", item.name, item.parent_account_name, "", "", "", "", "", "", "",
                             item.code, "", "JDL取込の補助名(全角10字)を超える。JDLで短くするか、使わないと決める"))
        for category in sorted({c.category for c in observation.conflicts}):
            rows.append(("JDL科目一覧の重複", category, "", "", "", "", "", "", "", "", "", "",
                         "同じ名前が複数コードにある。該当科目は現在選べない"))
    if review.closing_journals:
        rows.append(("決算仕訳", "本決・中決", "", "", "", "", "", review.closing_journals, "", "", "", "",
                     "JDLでの表し方を確認する"))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode("utf-8-sig"), review.setting_item_counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft", type=Path, help="JDL account-list draft of the same company")
    choices = [item.value for item in JdlTaxRounding]
    parser.add_argument("--sales-rounding", choices=choices, default="UNCONFIRMED")
    parser.add_argument("--purchase-rounding", choices=choices, default="UNCONFIRMED")
    args = parser.parse_args()
    if "data/private" not in args.output.resolve().as_posix():
        raise SystemExit("review sheets contain customer data; write them under data/private only")
    rounding = SimpleNamespace(sales_tax_rounding=JdlTaxRounding(args.sales_rounding),
                               purchase_tax_rounding=JdlTaxRounding(args.purchase_rounding))
    payload, counts = build_sheet(args.source, rounding, args.draft)
    _atomic_write(args.output, payload)
    print(json.dumps({"written": True, "items": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

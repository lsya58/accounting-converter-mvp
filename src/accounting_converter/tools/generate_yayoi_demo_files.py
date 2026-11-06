"""Synthetic Yayoi 仕訳日記帳（汎用形式） files for a trial demo. No customer data.

Amounts, dates, descriptions and the company name are synthetic. Account names
are read from the demo target JDL company's account master (JDL standard
accounts without subaccounts), so the exact-name candidates work in the GUI;
the files are therefore written under data/private.

  normal    only conditions with registered real JDL Evidence in the scoped
            company setting (税抜・原則・一括比例・売上切上げ/仕入四捨五入・振替伝票16行):
            1D1C 課税売上10% (6121), 1D1C 課税仕入10% 適格100% (8471),
            3-row voucher with 課税売上10% on every credit row (B3),
            非課税仕入 (account-independent), 輸出売上 (6121). Tax amounts have no fraction.
  blocked   each journal must stop with a stated reason and never be output:
            17 rows (voucher row limit), 控除不可 (no JDL representation),
            決算仕訳 (no JDL representation), 摘要 40 characters (Human replacement),
            8-row layout B8 (no Evidence until the gap round passes)

Nothing is confirmed or saved. `--check` parses both files and prints the
technical classification of every journal against the company's context.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import HEADER

PERIOD = ("令和08年06月01日", "令和08年06月30日")
NO_TAX = "対象外"


def _detail(day: str, voucher: int, debit, credit, description: str, closing: str = "",
            invoice: str = "", credit_ratio: str = "") -> list[str]:
    row = dict.fromkeys(HEADER, "")
    row.update({"[表題行]": "[明細行]", "日付": day, "伝票No.": str(voucher), "決算": closing, "調整": "NO",
                "タイプ": "[振伝]", "摘要": description, "請求書区分": invoice, "仕入税額控除": credit_ratio,
                "作業日付": day, "仕訳番号": ""})
    for prefix, side in (("借方", debit), ("貸方", credit)):
        if side is None:
            continue
        account, tax, amount, tax_amount = side
        row.update({f"{prefix}勘定科目": account, f"{prefix}税区分": tax,
                    f"{prefix}税計算区分": "内税" if tax_amount is not None else "",
                    f"{prefix}金額": str(amount), f"{prefix}税額": "" if tax_amount is None else str(tax_amount)})
    return [row[name] for name in HEADER]


def _render(company: str, journals) -> bytes:
    """journals: [(day, [(debit, credit, description, closing, invoice, ratio)])], one voucher each, in date order."""
    records = [["帳票名", "仕訳日記帳"], ["書式名", "汎用形式"], ["事業所名", company],
               ["処理日時", "令和08年11月06日", "09:00:00"], ["検索条件", ""],
               ["集計期間", *PERIOD, "決算仕訳を含む"], ["当日仕訳", "NO"], list(HEADER)]
    voucher, current_day, totals = 0, None, [0, 0, 0, 0]

    def close_day():
        total = dict.fromkeys(HEADER, "")
        total["[表題行]"] = "[日次合計行]"
        for name, value in zip(("借方金額", "借方税額", "貸方金額", "貸方税額"), totals):
            total[name] = str(value)
        records.append([total[name] for name in HEADER])

    for day, rows in journals:
        if current_day is not None and day != current_day:
            close_day()
            totals = [0, 0, 0, 0]
        current_day = day
        voucher += 1
        for debit, credit, description, closing, invoice, ratio in rows:
            records.append(_detail(day, voucher, debit, credit, description, closing, invoice, ratio))
            for index, side in ((0, debit), (2, credit)):
                if side is not None:
                    totals[index] += side[2]
                    totals[index + 1] += side[3] or 0
    close_day()
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL).writerows(records)
    return buffer.getvalue().encode("cp932", errors="strict")


def demo_journals(names: dict[str, str]):
    cash, sales, purchase, nonpur, payable = (names[c] for c in ("1111", "6121", "8471", "8571", "3181"))
    d = "令和08年06月{:02d}日".format
    s10 = lambda amount: (sales, "課税売上10%", amount, amount // 11)  # noqa: E731
    no = lambda account, amount: (account, NO_TAX, amount, None)  # noqa: E731
    normal = [
        (d(2), [(no(cash, 11000), s10(11000), "デモ 売上 現金", "", "", "")]),
        (d(3), [((purchase, "課対仕入10%", 3300, 300), no(cash, 3300), "デモ 仕入 現金", "", "適格", "100%")]),
        (d(4), [(no(cash, 1100 * n), s10(1100 * n), f"デモ 売上明細{n}", "", "", "") for n in (1, 2, 3)]),
        (d(5), [((nonpur, "非課仕入", 5000, None), no(cash, 5000), "デモ 非課税仕入", "", "", "")]),
        (d(8), [(no(cash, 20000), (sales, "輸出売上", 20000, None), "デモ 輸出売上", "", "", "")]),
    ]
    blocked = [
        (d(9), [(no(cash, 1100), s10(1100), f"デモ 17行 {n:02d}", "", "", "") for n in range(1, 18)]),
        (d(10), [((purchase, "課対仕入10%", 1100, 100), no(cash, 1100), "デモ 控除不可", "", "区分記載", "控除不可")]),
        (d(11), [(no(payable, 1000), no(cash, 1000), "デモ 決算仕訳", "本決", "", "")]),
        (d(12), [(no(cash, 2200), s10(2200), "デモ" + "摘要が三十二文字を超える長い説明文のサンプルです。" * 2, "", "", "")]),
        (d(15), [(no(cash, 1100), s10(1100), f"デモ 8行 {n}", "", "", "") for n in range(1, 9)]),
    ]
    return normal, blocked


def master_names(company_store: Path, company_id: str) -> tuple[dict[str, str], object]:
    from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
    from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

    profiles = ConversionProfileStore(company_store / "profiles")
    context = CompanySettingStore(company_store / "companies", profiles).resolve(company_id).context
    names = {item.target_master_code: item.mapping_value for item in context.account_master}
    with_subaccounts = {item.parent_account_code for item in context.subaccounts}
    needed = ("1111", "6121", "8471", "8571", "3181")
    unusable = [code for code in needed if code not in names or code in with_subaccounts]
    if unusable:
        raise SystemExit(f"the demo target master lacks no-subaccount accounts: {unusable}")
    return {code: names[code] for code in needed}, context


def write(output_dir: Path, names: dict[str, str]) -> dict[str, Path]:
    if "data/private" not in output_dir.resolve().as_posix():
        raise SystemExit("account names come from a JDL company master; write under data/private only")
    output_dir.mkdir(parents=True, exist_ok=True)
    normal, blocked = demo_journals(names)
    paths = {}
    for kind, journals in (("normal", normal), ("blocked", blocked)):
        path = output_dir / f"DEMO_yayoi_journal_report_{kind}.txt"
        path.write_bytes(_render("デモ株式会社", journals))
        paths[kind] = path
    return paths


def check(paths: dict[str, Path], context) -> dict:
    from accounting_converter.adapters.output.jdl.scoped_evidence import SCOPE_VOUCHER_ROW_LIMIT
    from accounting_converter.application.yayoi_sources import detect_format
    from accounting_converter.tools.yayoi_whatif_readiness import technical_sizing

    sized = replace(context, voucher_row_limit=SCOPE_VOUCHER_ROW_LIMIT)
    result = {}
    for kind, path in paths.items():
        parsed = detect_format(path).diagnose(path)
        missing: list = []
        sizing = technical_sizing(parsed.entries, sized, with_campaign=True, evidence_missing=missing)
        result[kind] = {"parse_issues": list(parsed.issue_codes), "rejected": parsed.rejected_journals, "journals": len(parsed.entries),
                        "technical_classes": sizing["classes"]}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True, help="demo target JDL company (its master names are used)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    names, context = master_names(args.company_store, args.company_id)
    paths = write(args.output_dir, names)
    out = {kind: path.name for kind, path in paths.items()}
    if args.check:
        out["check"] = check(paths, context)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    context_is_verified,
    tax_context_identity_sha256,
)
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write_pair
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


MARKER = "EVID-TAX-SALES10-SELFEXPORT"
IMPORT_MARKER = "EVID-TAX-SALES10-IMPORT"
HEADER = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
FIELDS = {name: index for index, name in enumerate(HEADER)}


def generate(
    self_export: Path,
    target_context: Path,
    output_dir: Path,
    *,
    import_date: str = "20260524",
) -> tuple[Path, Path]:
    """Create a pending import probe only from this company's observed JDL tax literal."""
    context = JdlTargetContextLoader().load(target_context)
    if not context_is_verified(context):
        raise ValueError("target tax context is not Human-confirmed in the required scope")
    accounts = {item.target_master_code: item for item in context.account_master}
    if any(code not in accounts for code in ("1111", "6121")):
        raise ValueError("observed accounts are absent from the current master")
    if any(item.parent_account_code in ("1111", "6121") for item in context.subaccounts):
        raise ValueError("observed no-subaccount account structure changed")
    if re.fullmatch(r"[0-9]{8}", import_date) is None:
        raise ValueError("import date must be YYYYMMDD")
    datetime.strptime(import_date, "%Y%m%d")
    rows = _journal_rows(self_export)
    found = [row for row in rows if row[FIELDS["摘要"]] == MARKER]
    selection_basis = "EXACT_MARKER"
    if not found and len(rows) == 1 and rows[0][FIELDS["日付"]] == "20260523" and not rows[0][FIELDS["摘要"]]:
        found = rows
        selection_basis = "SINGLE_ROW_EXACT_DATE_NO_DESCRIPTION"
    if len(found) != 1:
        raise ValueError("self-export must contain exactly one marked or exact single-day journal row")
    original = found[0]
    if original[FIELDS["//識別フラグ"]] not in {"1000", "1111"}:
        raise ValueError("self-export must be a simple 1D1C journal")
    if (original[FIELDS["借方科目"]], original[FIELDS["貸方科目"]]) != ("1111", "6121"):
        raise ValueError("self-export accounts differ from the planned witness")
    if any(original[FIELDS[name]] for name in ("借方補助", "借方補助名称", "貸方補助", "貸方補助名称")):
        raise ValueError("self-export added a subaccount")
    if original[FIELDS["貸方課区"]] in {"", "売一種"} or original[FIELDS["貸方税区"]] != "10%":
        raise ValueError("self-export does not show credit-side taxable sales at 10%")
    credit_tax_amount = original[FIELDS["貸方消費税"]]
    if credit_tax_amount and not credit_tax_amount.isdecimal():
        raise ValueError("self-export tax amount is not integer yen")
    if any(original[FIELDS[name]] not in {"", "0"} for name in ("借方課区", "借方税区", "借方税入力方法", "借方消費税")):
        raise ValueError("opposite-side tax is not blank")
    if any(original[FIELDS[name]] not in {"", "0"} for name in (
        "借方取引科目", "貸方取引科目", "借方部門コード", "借方部門名称", "貸方部門コード", "貸方部門名称",
    )):
        raise ValueError("self-export has optional fields outside the pending probe scope")
    debit_amount = original[FIELDS["借方金額"]]
    credit_amount = original[FIELDS["貸方金額"]]
    if not debit_amount.isdecimal() or debit_amount == "0" or credit_amount != debit_amount:
        raise ValueError("self-export is not a balanced positive integer-yen journal")
    for side, code in (("借方", "1111"), ("貸方", "6121")):
        master = accounts[code]
        if original[FIELDS[f"{side}科目名称"]] not in {master.target_name, master.target_formal_name}:
            raise ValueError("self-export account name differs from the current master")

    row = ["" for _ in HEADER]
    row[FIELDS["//識別フラグ"]] = original[FIELDS["//識別フラグ"]]
    row[FIELDS["日付"]] = import_date
    for name in (
        "借方科目", "借方科目名称", "借方科目正式名称", "借方金額",
        "貸方科目", "貸方科目名称", "貸方科目正式名称",
        "貸方課区", "貸方税区", "貸方税入力方法", "貸方金額", "貸方消費税",
    ):
        row[FIELDS[name]] = original[FIELDS[name]]
    row[FIELDS["摘要"]] = IMPORT_MARKER
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// JDL SELF-EXPORT DERIVED TAX PROBE / NOT FOR PRODUCTION", *([""] * 29)])
    writer.writerow([f"// 出力期間 ： {import_date} ～ {import_date}", *([""] * 29)])
    writer.writerow([""] * 30)
    writer.writerow(HEADER)
    writer.writerow(row)
    payload = stream.getvalue().encode("cp932", errors="strict")
    output = output_dir / "mf_tax_sales10_pending_rev2.csv"
    manifest = output_dir / "mf_tax_sales10_pending_rev2.manifest.private.json"
    metadata = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_self_export_sha256": hashlib.sha256(self_export.read_bytes()).hexdigest(),
        "self_export_selection_basis": selection_basis,
        "target_context_identity_sha256": tax_context_identity_sha256(context),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "import_date": import_date,
        "journal_count": 1,
        "physical_row_count": 1,
        "probe_id": "MF-JDL-TAX-SALES10-SELFEXPORT-DERIVED-REV2",
        "target_product": context.product,
        "target_version": context.version,
        "tax_context": {
            "processing_mode": context.tax_processing_mode.value,
            "taxation_method": context.effective_taxation_method.value,
            "input_tax_credit_method": context.effective_input_tax_credit_method.value,
        },
        "source_tax_identity": "課税売上 10%",
        "expected_signature": {
            "flag": row[FIELDS["//識別フラグ"]],
            "debit_account": "1111",
            "debit_subaccount": "",
            "debit_tax": ["", "", "", ""],
            "credit_account": "6121",
            "credit_subaccount": "",
            "credit_tax": [row[FIELDS[name]] for name in ("貸方課区", "貸方税区", "貸方税入力方法", "貸方消費税")],
            "amount": debit_amount,
            "description": IMPORT_MARKER,
        },
        "rejected_literal_in_this_context": "売一種",
        "tax_literal_provenance": "exact real JDL self-export row; not Import Evidence",
    }
    _atomic_write_pair(
        (output, payload),
        (manifest, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    )
    return output, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("self_export", type=Path)
    parser.add_argument("target_context", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--import-date", default="20260524")
    args = parser.parse_args()
    print(generate(args.self_export, args.target_context, args.output_dir, import_date=args.import_date))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from accounting_converter.application.moneyforward_tax_excluded_evidence import context_is_verified, tax_context_identity_sha256
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write_pair
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


HEADER = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
FIELDS = {name: index for index, name in enumerate(HEADER)}
SELF_MARKER = "EVID-TAX-OUTPUR-SELFEXPORT"
IMPORT_MARKER = "EVID-TAX-OUTPUR-IMPORT"


def generate(self_export: Path, target_context: Path, output_dir: Path, *, import_date: str = "20260526") -> tuple[Path, Path]:
    context = JdlTargetContextLoader().load(target_context)
    if not context_is_verified(context):
        raise ValueError("target tax context is not Human-confirmed")
    if datetime.strptime(import_date, "%Y%m%d").strftime("%Y%m%d") != import_date:
        raise ValueError("import date must be YYYYMMDD")
    rows = _journal_rows(self_export)
    if len(rows) != 1:
        raise ValueError("self-export must contain one physical row")
    original = rows[0]
    expected = {
        "//識別フラグ": "1111", "日付": "20260525", "借方科目": "8471",
        "借方科目名称": "旅費交通", "借方科目正式名称": "旅費交通費",
        "貸方科目": "1111", "貸方科目名称": "現金", "貸方科目正式名称": "現金",
        "借方金額": "1100", "貸方金額": "1100", "借方消費税": "0",
        "貸方消費税": "0", "摘要": SELF_MARKER,
        "借方部門コード": "0", "貸方部門コード": "0",
    }
    for name, value in expected.items():
        if original[FIELDS[name]] != value:
            raise ValueError(f"self-export witness differs at {name}")
    if any(original[FIELDS[name]] for name in (
        "借方補助", "借方補助名称", "貸方補助", "貸方補助名称",
        "借方課区", "借方税区", "借方税入力方法",
        "貸方課区", "貸方税区", "貸方税入力方法",
        "借方取引科目", "貸方取引科目", "借方部門名称", "貸方部門名称",
    )):
        raise ValueError("self-export has nonblank tax, subaccount or optional fields")
    accounts = {item.target_master_code: item for item in context.account_master}
    for code, side in (("8471", "借方"), ("1111", "貸方")):
        account = accounts.get(code)
        if account is None or original[FIELDS[f"{side}科目正式名称"]] != account.target_formal_name:
            raise ValueError("self-export account is absent or changed in current master")
    if any(item.parent_account_code in {"8471", "1111"} for item in context.subaccounts):
        raise ValueError("observed no-subaccount structure changed")

    row = ["" for _ in HEADER]
    for name in (
        "//識別フラグ", "借方科目", "借方科目名称", "借方科目正式名称",
        "借方金額", "借方消費税", "貸方科目", "貸方科目名称",
        "貸方科目正式名称", "貸方金額", "貸方消費税",
    ):
        row[FIELDS[name]] = original[FIELDS[name]]
    row[FIELDS["日付"]] = import_date
    row[FIELDS["摘要"]] = IMPORT_MARKER
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// JDL SELF-EXPORT DERIVED TAX PROBE / NOT FOR PRODUCTION", *([""] * 29)])
    writer.writerow([f"// 出力期間 ： {import_date} ～ {import_date}", *([""] * 29)])
    writer.writerow([""] * 30)
    writer.writerow(HEADER)
    writer.writerow(row)
    payload = stream.getvalue().encode("cp932", errors="strict")
    output = output_dir / "mf_tax_outpur_pending_rev2.csv"
    manifest = output_dir / "mf_tax_outpur_pending_rev2.manifest.private.json"
    metadata = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_self_export_sha256": hashlib.sha256(self_export.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "target_context_identity_sha256": tax_context_identity_sha256(context),
        "target_product": context.product,
        "target_version": context.version,
        "tax_context": {
            "processing_mode": context.tax_processing_mode.value,
            "taxation_method": context.effective_taxation_method.value,
            "input_tax_credit_method": context.effective_input_tax_credit_method.value,
        },
        "source_tax_identity": "対象外仕入",
        "human_selected_jdl_ui_label": "0 対象外",
        "jdl_csv_tax_representation": {"category": "", "rate": "", "input_method": "", "tax_amount": "0"},
        "tax_literal_provenance": "Human UI observation and exact JDL self-export; not Import Evidence",
        "source_journal_count": 1,
        "candidate_journal_count": 1,
        "candidate_physical_row_count": 1,
        "import_date": import_date,
        "expected_signature": {name: row[index] for name, index in FIELDS.items()},
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
    args = parser.parse_args()
    print(generate(args.self_export, args.target_context, args.output_dir))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from accounting_converter.application.jdl_account_list_pdf import (
    JdlAccountListPdfTextParser,
    JdlAccountListTextPage,
)
from accounting_converter.infrastructure.jdl_account_pdf_draft import PypdfTextExtractor
from accounting_converter.profiles.jdl_official import (
    jdl_field_length_valid,
    jdl_ibex_cashbook_official_journal_import_spec,
)


CASES = (("receivable_1551", "1551", "20260515"), ("bank_1311", "1311", "20260516"))


def _atomic_new(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("cp932", errors="strict")


def generate(source_candidate: Path, master_pdf: Path, output_dir: Path) -> tuple[Path, ...]:
    if output_dir.exists():
        raise ValueError("probe output directory already exists; overwrite is forbidden")
    pages = PypdfTextExtractor().extract_pages(master_pdf)
    observation = JdlAccountListPdfTextParser().parse_pages(
        (JdlAccountListTextPage(index, page) for index, page in enumerate(pages, 1)),
        source_sha256=hashlib.sha256(master_pdf.read_bytes()).hexdigest(),
        acquisition_method="LOCAL_VERIFIED_MASTER",
        human_observed=True,
    )
    accounts = {item.code: item for item in observation.printed_accounts if item.enabled}
    if any(code not in accounts for _, code, _ in CASES) or "8471" not in accounts:
        raise ValueError("probe account is not enabled in the current master")
    if any(not any(item.parent_account_code == code for item in observation.subaccounts) for _, code, _ in CASES):
        raise ValueError("probe account has no observed target subaccount")
    with source_candidate.open("r", encoding="cp932", newline="") as source:
        rows = list(csv.reader(source))
    body = [row for row in rows if len(row) == 30 and row[0] == "1111"]
    template = next((row for row in body if row[2] == "20260501"), None)
    if template is None or (template[3], template[6], template[13], template[16]) != ("8471", "", "3181", "0001"):
        raise ValueError("verified P05 template does not match its expected structure")
    if (template[8], template[9], template[10], template[11], template[12]) != ("仕　入", "10%", "内税", "1100", "100"):
        raise ValueError("verified P05 tax placement changed")
    header = next((row for row in rows if len(row) == 30 and row[0] == "//識別フラグ"), None)
    if header is None:
        raise ValueError("official JDL header is missing")
    spec = jdl_ibex_cashbook_official_journal_import_spec()
    if tuple(header) != spec.column_names:
        raise ValueError("official JDL header changed")

    prepared: list[tuple[Path, bytes, Path, bytes]] = []
    for case_id, code, date in CASES:
        account = accounts[code]
        row = list(template)
        row[2] = date
        if row[5] != accounts["8471"].name:
            raise ValueError("verified debit account differs from the current master")
        row[4] = accounts["8471"].abbreviation
        row[13:18] = [code, account.abbreviation, account.name, "", ""]
        row[23] = f"MF-BLANK-SUB-{case_id.upper()}"
        if len(row) != 30:
            raise ValueError("probe row is not a valid 30-column JDL field layout")
        invalid_fields = [
            definition.name for definition, value in zip(spec.columns, row, strict=True)
            if not jdl_field_length_valid(definition, value)
        ]
        if invalid_fields:
            raise ValueError(f"probe field length invalid: {','.join(invalid_fields)}")
        metadata = [
            ["// MF BLANK SUBACCOUNT PROBE / NOT FOR PRODUCTION", *([""] * 29)],
            [f"// 出力期間 ： {date} ～ {date}", *([""] * 29)],
            [""] * 30,
            header,
            row,
        ]
        csv_data = _csv_bytes(metadata)
        csv_path = output_dir / f"{case_id}.csv"
        manifest = {
            "probe_id": f"MF-BLANK-SUB-{case_id.upper()}",
            "status": "PENDING_REAL_JDL_IMPORT",
            "NOT_FOR_PRODUCTION": True,
            "production_allowed": False,
            "source_candidate_sha256": hashlib.sha256(source_candidate.read_bytes()).hexdigest(),
            "target_master_sha256": hashlib.sha256(master_pdf.read_bytes()).hexdigest(),
            "target_context": "JDL 35.5 / taxable / tax excluded / standard / proportional",
            "candidate_sha256": hashlib.sha256(csv_data).hexdigest(),
            "date": date,
            "target_account_code": code,
            "target_subaccount_count": sum(item.parent_account_code == code for item in observation.subaccounts),
            "target_subaccount_code": "",
            "target_subaccount_name": "",
            "known_template_normalization": "debit short name uses current printed master abbreviation",
            "formal_preflight_expected": "BLOCKED_TARGET_SUBACCOUNT_REQUIRED",
            "expected": "Import and re-export must retain blank credit subaccount; no substitution is allowed",
            "evidence_status": "PENDING",
        }
        manifest_path = output_dir / f"{case_id}.manifest.json"
        prepared.append((csv_path, csv_data, manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")))
    output_dir.mkdir(parents=True, exist_ok=False)
    for csv_path, csv_data, manifest_path, manifest_data in prepared:
        _atomic_new(csv_path, csv_data)
        _atomic_new(manifest_path, manifest_data)
    return tuple(csv_path for csv_path, _, _, _ in prepared)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_candidate", type=Path)
    parser.add_argument("master_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    for path in generate(args.source_candidate, args.master_pdf, args.output_dir):
        print(path)


if __name__ == "__main__":
    main()

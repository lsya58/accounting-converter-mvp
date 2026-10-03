from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

from .generator_authored_1111 import (
    ACCOUNT_CODE_OR_FORMAL_FIELDS,
    DEPARTMENT_FIELDS,
    OFFICIAL_HEADER,
    SUBACCOUNT_FIELDS,
    _amount,
    _data_row_bytes,
    _source_data_row_bytes,
    _validate_date,
    _validate_exact_keys,
    _validate_paths,
    _validate_text_lengths,
    _write_json_exclusive,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-1111-TAX-INCLUSIVE-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_1111_TAX_INCLUSIVE_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_1111_tax_inclusive"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_1111_tax_inclusive_candidate.csv"
DEBIT_TAX_SCOPE = "借方課区"
DEBIT_TAX_CATEGORY = "借方税区"
TAX_INPUT_METHOD_FIELDS = ("借方税入力方法", "貸方税入力方法")
TAX_AMOUNT_FIELDS = ("借方消費税", "貸方消費税")
TRANSACTION_ACCOUNT_FIELDS = ("借方取引科目", "貸方取引科目")
CREDIT_TAX_CLASSIFICATION_FIELDS = ("貸方課区", "貸方税区")
TARGET_VALIDATION_KEYS = (
    "debit_account_name_exists_in_target_master",
    "credit_account_name_exists_in_target_master",
    "no_fuzzy_matching_or_auto_replacement",
)
TAX_VALIDATION_KEYS = (
    "company_tax_processing_confirmed_taxable",
    "taxation_method_confirmed_standard",
    "input_tax_credit_method_confirmed_individual",
    "accounting_method_confirmed_tax_included",
    "sales_rounding_confirmed_down",
    "purchase_rounding_confirmed_down",
    "separate_consumption_tax_disabled",
    "department_processing_disabled",
    "debit_tax_scope_exact_raw_match",
    "debit_tax_category_exact_raw_match",
    "tax_input_method_intentionally_blank_per_manual",
    "tax_amount_intentionally_blank_per_manual",
    "transaction_accounts_intentionally_blank_for_non_consumption_tax_journal",
    "credit_tax_classification_intentionally_blank_from_observed_case",
    "department_fields_intentionally_blank",
    "no_implicit_zero_or_normalization",
)


class JdlGeneratorAuthored1111TaxInclusiveError(ValueError):
    pass


@dataclass(frozen=True)
class TargetAccountEvidence:
    debit_code: str
    debit_name: str
    debit_formal_name: str
    credit_code: str
    credit_name: str
    credit_formal_name: str


@dataclass(frozen=True)
class ObservedTaxEvidence:
    debit_tax_scope: str
    debit_tax_category: str
    debit_tax_amount_reexport: str
    credit_tax_amount_reexport: str
    department_code_reexport: str


@dataclass(frozen=True)
class JdlGeneratorAuthored1111TaxInclusiveConfig:
    jdl_columns: dict[str, str]
    field_decisions: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    tax_validation: dict[str, bool]
    target_account_evidence: TargetAccountEvidence
    observed_tax_evidence: ObservedTaxEvidence
    company_tax_processing: str = JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthored1111TaxInclusiveResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: dict[str, Any]


def load_config(path: Path) -> JdlGeneratorAuthored1111TaxInclusiveConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return JdlGeneratorAuthored1111TaxInclusiveConfig(
        jdl_columns=dict(payload["jdl_columns"]),
        field_decisions=dict(payload["field_decisions"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        tax_validation=dict(payload["tax_validation"]),
        target_account_evidence=TargetAccountEvidence(
            **payload["target_account_evidence"]
        ),
        observed_tax_evidence=ObservedTaxEvidence(
            **payload["observed_tax_evidence"]
        ),
        company_tax_processing=payload.get(
            "company_tax_processing",
            JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
        ),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthored1111TaxInclusiveConfig,
    comparison_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthored1111TaxInclusiveResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    try:
        _validate_paths(output_path, report_path, manifest_path, comparison_source)
        _validate_config(config)
        _validate_observed_source(comparison_source, config)
    except ValueError as exc:
        raise JdlGeneratorAuthored1111TaxInclusiveError(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    row = tuple(config.jdl_columns[name] for name in OFFICIAL_HEADER)
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        report = _validate_candidate(output_path, config, comparison_source)
        if report["errors"]:
            raise JdlGeneratorAuthored1111TaxInclusiveError(
                "; ".join(report["errors"])
            )
        _write_json_exclusive(report_path, report)
        _write_json_exclusive(
            manifest_path,
            {
                "experiment_id": EXPERIMENT_ID,
                "status": EXPERIMENT_STATUS,
                "actual_result": "UNTESTED",
                "result_status_values": ["PASS", "REJECTED", "UNTESTED"],
                "csv_path": output_path.name,
                "privacy_safe_report_path": report_path.name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "verification": report,
                "source_jdl_row_used_for_construction": False,
                "production_ready": False,
            },
        )
    except Exception:
        for path in (output_path, report_path, manifest_path):
            path.unlink(missing_ok=True)
        raise
    return JdlGeneratorAuthored1111TaxInclusiveResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def _validate_config(config: JdlGeneratorAuthored1111TaxInclusiveConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "experiment identity/status mismatch"
        )
    _validate_exact_keys("jdl_columns", config.jdl_columns, OFFICIAL_HEADER)
    _validate_exact_keys("field_decisions", config.field_decisions, OFFICIAL_HEADER)
    if not all(isinstance(value, str) for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "all JDL values must be strings"
        )
    if any("\r" in value or "\n" in value for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "embedded newline is unsupported"
        )
    columns = config.jdl_columns
    if columns["//識別フラグ"] != "1111" or columns["伝番"]:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "candidate must be one 1111 record with explicit blank voucher"
        )
    _validate_date(columns["日付"], config.journal_date_iso)
    if any(columns[name] for name in ACCOUNT_CODE_OR_FORMAL_FIELDS):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "candidate uses confirmed account names only"
        )
    accounts = config.target_account_evidence
    if (
        columns["借方科目名称"] != accounts.debit_name
        or columns["貸方科目名称"] != accounts.credit_name
        or not all(vars(accounts).values())
    ):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "account names/evidence do not exactly match target master evidence"
        )
    _validate_text_lengths(columns)
    if _amount(columns["借方金額"], "借方金額") != _amount(
        columns["貸方金額"], "貸方金額"
    ):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "debit and credit amounts must balance"
        )
    if any(columns[name] for name in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "subaccount fields must remain blank"
        )
    if any(columns[name] for name in DEPARTMENT_FIELDS):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "department fields must remain blank"
        )
    if config.company_tax_processing != JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "company tax processing must be TAXABLE_TAX_INCLUDED"
        )
    observed = config.observed_tax_evidence
    if not observed.debit_tax_scope or not observed.debit_tax_category:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "raw-confirmed debit tax scope/category are required"
        )
    if (
        columns[DEBIT_TAX_SCOPE] != observed.debit_tax_scope
        or columns[DEBIT_TAX_CATEGORY] != observed.debit_tax_category
    ):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "tax abbreviations must exactly preserve raw evidence"
        )
    if columns[DEBIT_TAX_SCOPE] != "仕\u3000入":
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "debit tax scope must preserve the observed full-width space"
        )
    blank_fields = (
        *TAX_INPUT_METHOD_FIELDS,
        *TAX_AMOUNT_FIELDS,
        *TRANSACTION_ACCOUNT_FIELDS,
        *CREDIT_TAX_CLASSIFICATION_FIELDS,
    )
    if any(columns[name] for name in blank_fields):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "manual-unnecessary or observed-blank tax fields must remain blank"
        )
    if (
        observed.debit_tax_amount_reexport != "0"
        or observed.credit_tax_amount_reexport != "0"
        or observed.department_code_reexport != "0"
    ):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed re-export zero representations are not confirmed"
        )
    _require_all_true(config.target_master_validation, TARGET_VALIDATION_KEYS)
    _require_all_true(config.tax_validation, TAX_VALIDATION_KEYS)
    _validate_field_decisions(config.field_decisions)


def _validate_field_decisions(decisions: dict[str, str]) -> None:
    expected = {
        name: "EXPLICIT_EXPERIMENT_CONDITION_BLANK" for name in OFFICIAL_HEADER
    }
    expected.update(
        {
            "//識別フラグ": "EXPLICIT_EXPERIMENT_INPUT",
            "伝番": "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
            "日付": "EXPLICIT_EXPERIMENT_INPUT",
            "借方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "借方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
            "借方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "借方課区": "OBSERVED_RUNTIME_EXACT_TAX_VALUE",
            "借方税区": "OBSERVED_RUNTIME_EXACT_TAX_VALUE",
            "借方税入力方法": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
            "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
            "借方消費税": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
            "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
            "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方課区": "OBSERVED_RUNTIME_CREDIT_SIDE_BLANK",
            "貸方税区": "OBSERVED_RUNTIME_CREDIT_SIDE_BLANK",
            "貸方税入力方法": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
            "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
            "貸方消費税": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
            "摘要": "EXPLICIT_EXPERIMENT_INPUT",
            "借方取引科目": "OFFICIAL_DOCUMENTED_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
            "貸方取引科目": "OFFICIAL_DOCUMENTED_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
            "借方部門コード": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
            "借方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
            "貸方部門コード": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
            "貸方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
        }
    )
    mismatched = [name for name in OFFICIAL_HEADER if decisions[name] != expected[name]]
    if mismatched:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "field decision mismatch: " + ", ".join(mismatched)
        )


def _validate_observed_source(
    path: Path,
    config: JdlGeneratorAuthored1111TaxInclusiveConfig,
) -> None:
    row = _read_source_row(path)
    accounts = config.target_account_evidence
    tax = config.observed_tax_evidence
    expected = {
        "//識別フラグ": "1111",
        "借方科目": accounts.debit_code,
        "借方科目名称": accounts.debit_name,
        "借方科目正式名称": accounts.debit_formal_name,
        "貸方科目": accounts.credit_code,
        "貸方科目名称": accounts.credit_name,
        "貸方科目正式名称": accounts.credit_formal_name,
        "借方課区": tax.debit_tax_scope,
        "借方税区": tax.debit_tax_category,
        "借方税入力方法": "",
        "借方金額": config.jdl_columns["借方金額"],
        "借方消費税": tax.debit_tax_amount_reexport,
        "借方取引科目": "",
        "貸方課区": "",
        "貸方税区": "",
        "貸方税入力方法": "",
        "貸方金額": config.jdl_columns["貸方金額"],
        "貸方消費税": tax.credit_tax_amount_reexport,
        "貸方取引科目": "",
        "借方部門コード": tax.department_code_reexport,
        "借方部門名称": "",
        "貸方部門コード": tax.department_code_reexport,
        "貸方部門名称": "",
    }
    mismatched = [
        name for name, value in expected.items() if row[OFFICIAL_HEADER.index(name)] != value
    ]
    if mismatched:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed source does not confirm configured evidence: "
            + ", ".join(mismatched)
        )
    if any(row[OFFICIAL_HEADER.index(name)] for name in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed source must not contain subaccounts"
        )


def _read_source_row(path: Path) -> tuple[str, ...]:
    try:
        rows = list(
            csv.reader(
                io.StringIO(path.read_bytes().decode("cp932"), newline=""),
                strict=True,
            )
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed source must be parseable CP932 CSV"
        ) from exc
    headers = [index for index, row in enumerate(rows) if tuple(row) == OFFICIAL_HEADER]
    if len(headers) != 1:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed source must contain one official header"
        )
    records = rows[headers[0] + 1:]
    if len(records) != 1 or len(records[0]) != 30:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            "observed source must contain one 30-column record"
        )
    return tuple(records[0])


def _validate_candidate(
    path: Path,
    config: JdlGeneratorAuthored1111TaxInclusiveConfig,
    comparison_source: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    raw = path.read_bytes()
    without_crlf = raw.replace(b"\r\n", b"")
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        errors.append("BOM must not be present")
    if raw.count(b"\r\n") != 2 or b"\n" in without_crlf or b"\r" in without_crlf:
        errors.append("candidate must contain exactly two CRLF rows")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error):
        rows = []
        errors.append("candidate must be parseable CP932 CSV")
    if len(rows) != 2 or tuple(rows[0]) != OFFICIAL_HEADER or len(rows[1]) != 30:
        errors.append("candidate must contain exact header and one 30-column row")
    analysis = JdlCsvStructuralAnalyzer(
        observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
    ).analyze_path(path)
    if analysis.analysis_errors:
        errors.extend(item.rule_id for item in analysis.analysis_errors)
    if analysis.encoding != "cp932" or analysis.has_bom or analysis.line_ending != "CRLF":
        errors.append("candidate encoding/BOM/line ending validation failed")
    if analysis.data_record_count != 1 or dict(analysis.identifier_flag_counts) != {"1111": 1}:
        errors.append("candidate must contain one 1111 record")
    source_identical = _data_row_bytes(path) == _source_data_row_bytes(comparison_source)
    if source_identical:
        errors.append("generator-authored row must not copy the observed source row")
    columns = config.jdl_columns
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": EXPERIMENT_STATUS,
        "success": not errors,
        "errors": errors,
        "record_count": analysis.data_record_count,
        "column_count": analysis.header_column_count or 0,
        "identifier_flags": dict(analysis.identifier_flag_counts),
        "balanced": columns["借方金額"] == columns["貸方金額"],
        "all_30_columns_explicit": len(columns) == 30,
        "all_30_decisions_explicit": len(config.field_decisions) == 30,
        "implicit_default_count": 0,
        "tax_mode": JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
        "required_tax_fields_present": True,
        "manual_unnecessary_tax_fields_blank": True,
        "reexport_zero_used_as_generator_default": False,
        "full_width_space_preserved": columns[DEBIT_TAX_SCOPE] == "仕\u3000入",
        "subaccounts_blank": True,
        "departments_blank": True,
        "source_row_byte_identical": source_identical,
        "source_jdl_row_used_for_construction": False,
        "production_ready": False,
        "privacy_note": (
            "Account, tax values, description, date, amount, raw row, and source path "
            "are omitted."
        ),
    }


def _require_all_true(values: dict[str, bool], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in values]
    unconfirmed = [key for key in required if values.get(key) is not True]
    if missing or unconfirmed:
        raise JdlGeneratorAuthored1111TaxInclusiveError(
            f"validation incomplete; missing={missing}, unconfirmed={unconfirmed}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private JDL 1111 tax-inclusive candidate."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--comparison-source", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = generate_candidate(
            load_config(args.config),
            args.comparison_source,
            args.output_dir,
        )
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        JdlGeneratorAuthored1111TaxInclusiveError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"csv: {result.csv_path}")
    print(f"report: {result.report_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

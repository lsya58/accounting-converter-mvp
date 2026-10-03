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
EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-1111-TAX-EXCLUSIVE-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_1111_TAX_EXCLUSIVE_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_1111_tax_exclusive"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_1111_tax_exclusive_candidate.csv"
TARGET_VALIDATION_KEYS = (
    "debit_account_name_exists_in_target_master",
    "credit_account_name_exists_in_target_master",
    "no_fuzzy_matching_or_auto_replacement",
)
TAX_VALIDATION_KEYS = (
    "company_tax_processing_confirmed_taxable",
    "taxation_method_confirmed_standard",
    "input_tax_credit_method_confirmed_individual",
    "company_accounting_method_confirmed_tax_excluded",
    "ui_input_mode_observed_tax_excluded",
    "ui_input_mode_not_equated_with_csv_tax_input_method",
    "sales_rounding_confirmed_down",
    "purchase_rounding_confirmed_down",
    "separate_consumption_tax_disabled",
    "department_processing_disabled",
    "debit_tax_fields_required_by_manual",
    "debit_tax_literals_exact_raw_match",
    "amount_confirmed_tax_included_total_per_manual",
    "debit_tax_amount_confirmed_as_observed_component",
    "credit_non_tax_side_fields_intentionally_blank_from_observed_case",
    "transaction_accounts_intentionally_blank_for_non_consumption_tax_journal",
    "department_fields_intentionally_blank",
    "no_reexport_zero_promoted",
    "no_implicit_zero_or_normalization",
)


class JdlGeneratorAuthored1111TaxExclusiveError(ValueError):
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
class ObservedTaxExclusiveEvidence:
    debit_tax_scope: str
    debit_tax_category: str
    debit_tax_input_method: str
    debit_tax_amount: str
    credit_tax_amount_reexport: str
    department_code_reexport: str


@dataclass(frozen=True)
class JdlGeneratorAuthored1111TaxExclusiveConfig:
    jdl_columns: dict[str, str]
    field_decisions: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    tax_validation: dict[str, bool]
    target_account_evidence: TargetAccountEvidence
    observed_tax_evidence: ObservedTaxExclusiveEvidence
    company_tax_processing: str = JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthored1111TaxExclusiveResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: dict[str, Any]


def load_config(path: Path) -> JdlGeneratorAuthored1111TaxExclusiveConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return JdlGeneratorAuthored1111TaxExclusiveConfig(
        jdl_columns=dict(payload["jdl_columns"]),
        field_decisions=dict(payload["field_decisions"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        tax_validation=dict(payload["tax_validation"]),
        target_account_evidence=TargetAccountEvidence(
            **payload["target_account_evidence"]
        ),
        observed_tax_evidence=ObservedTaxExclusiveEvidence(
            **payload["observed_tax_evidence"]
        ),
        company_tax_processing=payload.get(
            "company_tax_processing",
            JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value,
        ),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthored1111TaxExclusiveConfig,
    comparison_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthored1111TaxExclusiveResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    try:
        _validate_paths(output_path, report_path, manifest_path, comparison_source)
        _validate_config(config)
        _validate_observed_source(comparison_source, config)
    except ValueError as exc:
        raise JdlGeneratorAuthored1111TaxExclusiveError(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    row = tuple(config.jdl_columns[name] for name in OFFICIAL_HEADER)
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(
                (OFFICIAL_HEADER, row)
            )
        report = _validate_candidate(output_path, config, comparison_source)
        if report["errors"]:
            raise JdlGeneratorAuthored1111TaxExclusiveError(
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
    return JdlGeneratorAuthored1111TaxExclusiveResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def _validate_config(config: JdlGeneratorAuthored1111TaxExclusiveConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "experiment identity/status mismatch"
        )
    _validate_exact_keys("jdl_columns", config.jdl_columns, OFFICIAL_HEADER)
    _validate_exact_keys("field_decisions", config.field_decisions, OFFICIAL_HEADER)
    columns = config.jdl_columns
    if not all(isinstance(value, str) for value in columns.values()):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "all JDL values must be strings"
        )
    if any("\r" in value or "\n" in value for value in columns.values()):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "embedded newline is unsupported"
        )
    if columns["//識別フラグ"] != "1111" or columns["伝番"]:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "candidate must be one 1111 record with explicit blank voucher"
        )
    _validate_date(columns["日付"], config.journal_date_iso)
    if any(columns[name] for name in ACCOUNT_CODE_OR_FORMAL_FIELDS):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "candidate uses confirmed account names only"
        )
    accounts = config.target_account_evidence
    if (
        columns["借方科目名称"] != accounts.debit_name
        or columns["貸方科目名称"] != accounts.credit_name
        or not all(vars(accounts).values())
    ):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "account names/evidence do not exactly match target master evidence"
        )
    _validate_text_lengths(columns)
    if _amount(columns["借方金額"], "借方金額") != _amount(
        columns["貸方金額"], "貸方金額"
    ):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "debit and credit amounts must balance"
        )
    if any(columns[name] for name in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "subaccount fields must remain blank"
        )
    if any(columns[name] for name in DEPARTMENT_FIELDS):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "department fields must remain blank"
        )
    if config.company_tax_processing != JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "company tax processing must be TAXABLE_TAX_EXCLUDED"
        )
    tax = config.observed_tax_evidence
    expected_debit = {
        "借方課区": tax.debit_tax_scope,
        "借方税区": tax.debit_tax_category,
        "借方税入力方法": tax.debit_tax_input_method,
        "借方消費税": tax.debit_tax_amount,
    }
    if any(columns[name] != value for name, value in expected_debit.items()):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "debit tax fields must exactly preserve observed evidence"
        )
    if (
        columns["借方課区"] != "仕\u3000入"
        or columns["借方税区"] != "10%"
        or columns["借方税入力方法"] != "内税"
        or columns["借方消費税"] != "90"
    ):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "tax-exclusive literals are limited to the raw-confirmed case"
        )
    blank_tax_fields = (
        "貸方課区",
        "貸方税区",
        "貸方税入力方法",
        "貸方消費税",
        "借方取引科目",
        "貸方取引科目",
    )
    if any(columns[name] for name in blank_tax_fields):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "credit-side and transaction-account fields must remain explicitly blank"
        )
    if tax.credit_tax_amount_reexport != "0" or tax.department_code_reexport != "0":
        raise JdlGeneratorAuthored1111TaxExclusiveError(
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
            "借方税入力方法": "OFFICIAL_REQUIRED_AND_OBSERVED_RUNTIME_EXACT_VALUE",
            "借方金額": "OFFICIAL_TAX_INCLUDED_TOTAL_AND_EXPLICIT_INPUT",
            "借方消費税": "OFFICIAL_REQUIRED_AND_OBSERVED_RUNTIME_EXACT_VALUE",
            "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
            "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方課区": "OBSERVED_RUNTIME_NON_TAX_SIDE_BLANK",
            "貸方税区": "OBSERVED_RUNTIME_NON_TAX_SIDE_BLANK",
            "貸方税入力方法": "OBSERVED_RUNTIME_NON_TAX_SIDE_BLANK",
            "貸方金額": "OFFICIAL_TAX_INCLUDED_TOTAL_AND_EXPLICIT_INPUT",
            "貸方消費税": "REEXPORT_ZERO_NOT_PROMOTED_EXPLICIT_BLANK",
            "摘要": "EXPLICIT_EXPERIMENT_INPUT",
            "借方取引科目": "OFFICIAL_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
            "貸方取引科目": "OFFICIAL_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
            "借方部門コード": "REEXPORT_ZERO_NOT_PROMOTED_EXPLICIT_BLANK",
            "借方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
            "貸方部門コード": "REEXPORT_ZERO_NOT_PROMOTED_EXPLICIT_BLANK",
            "貸方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
        }
    )
    mismatched = [name for name in OFFICIAL_HEADER if decisions[name] != expected[name]]
    if mismatched:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "field decision mismatch: " + ", ".join(mismatched)
        )


def _validate_observed_source(
    path: Path,
    config: JdlGeneratorAuthored1111TaxExclusiveConfig,
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
        "借方税入力方法": tax.debit_tax_input_method,
        "借方金額": config.jdl_columns["借方金額"],
        "借方消費税": tax.debit_tax_amount,
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
        name
        for name, value in expected.items()
        if row[OFFICIAL_HEADER.index(name)] != value
    ]
    if mismatched:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source does not confirm configured evidence: "
            + ", ".join(mismatched)
        )
    if any(row[OFFICIAL_HEADER.index(name)] for name in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must not contain subaccounts"
        )


def _read_source_row(path: Path) -> tuple[str, ...]:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must not contain a BOM"
        )
    without_crlf = raw.replace(b"\r\n", b"")
    if b"\n" in without_crlf or b"\r" in without_crlf:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must use CRLF only"
        )
    try:
        rows = list(
            csv.reader(
                io.StringIO(raw.decode("cp932"), newline=""),
                strict=True,
            )
        )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must be parseable CP932 CSV"
        ) from exc
    headers = [index for index, row in enumerate(rows) if tuple(row) == OFFICIAL_HEADER]
    if len(headers) != 1:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must contain one official header"
        )
    records = rows[headers[0] + 1 :]
    if len(records) != 1 or len(records[0]) != 30:
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            "observed source must contain one 30-column record"
        )
    return tuple(records[0])


def _validate_candidate(
    path: Path,
    config: JdlGeneratorAuthored1111TaxExclusiveConfig,
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
        rows = list(
            csv.reader(io.StringIO(raw.decode("cp932"), newline=""), strict=True)
        )
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
    if analysis.data_record_count != 1 or dict(analysis.identifier_flag_counts) != {
        "1111": 1
    }:
        errors.append("candidate must contain one 1111 record")
    source_identical = _data_row_bytes(path) == _source_data_row_bytes(
        comparison_source
    )
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
        "tax_mode": JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value,
        "manual_required_debit_tax_fields_present": True,
        "ui_input_mode_equated_with_csv_tax_method": False,
        "reexport_zero_used_as_generator_default": False,
        "full_width_space_preserved": columns["借方課区"] == "仕\u3000入",
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
        raise JdlGeneratorAuthored1111TaxExclusiveError(
            f"validation incomplete; missing={missing}, unconfirmed={unconfirmed}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private JDL 1111 tax-exclusive candidate."
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
        JdlGeneratorAuthored1111TaxExclusiveError,
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

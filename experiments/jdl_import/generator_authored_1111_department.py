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
    OFFICIAL_HEADER,
    SUBACCOUNT_FIELDS,
    TAX_FIELDS,
    _amount,
    _data_row_bytes,
    _source_data_row_bytes,
    _validate_date,
    _validate_exact_keys,
    _validate_paths,
    _validate_text_lengths,
    _write_json_exclusive,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-1111-DEPARTMENT-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_1111_DEPARTMENT_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_1111_department"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_1111_department_candidate.csv"
DEPARTMENT_FIELDS = (
    "借方部門コード",
    "借方部門名称",
    "貸方部門コード",
    "貸方部門名称",
)
TARGET_VALIDATION_KEYS = (
    "debit_account_name_exists_in_target_master",
    "credit_account_name_exists_in_target_master",
    "department_processing_enabled",
    "department_code_exact_match",
    "department_short_name_exact_match",
    "both_department_sides_intentionally_populated",
    "no_fuzzy_matching_or_auto_replacement",
)
TAX_VALIDATION_KEYS = (
    "company_tax_processing_confirmed_exempt",
    "tax_fields_intentionally_blank",
)


class JdlGeneratorAuthored1111DepartmentError(ValueError):
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
class TargetDepartmentEvidence:
    department_code: str
    formal_name: str
    short_name: str
    department_processing_enabled: bool
    confirmed_registered: bool
    no_fuzzy_matching: bool
    no_automatic_replacement: bool


@dataclass(frozen=True)
class JdlGeneratorAuthored1111DepartmentConfig:
    jdl_columns: dict[str, str]
    field_decisions: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    tax_validation: dict[str, bool]
    target_account_evidence: TargetAccountEvidence
    target_department_evidence: TargetDepartmentEvidence
    company_tax_processing: str = JdlTaxProcessingMode.EXEMPT.value
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthored1111DepartmentResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: dict[str, Any]


def load_config(path: Path) -> JdlGeneratorAuthored1111DepartmentConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    accounts = payload["target_account_evidence"]
    department = payload["target_department_evidence"]
    return JdlGeneratorAuthored1111DepartmentConfig(
        jdl_columns=dict(payload["jdl_columns"]),
        field_decisions=dict(payload["field_decisions"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        tax_validation=dict(payload["tax_validation"]),
        target_account_evidence=TargetAccountEvidence(**accounts),
        target_department_evidence=TargetDepartmentEvidence(**department),
        company_tax_processing=payload.get(
            "company_tax_processing",
            JdlTaxProcessingMode.EXEMPT.value,
        ),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthored1111DepartmentConfig,
    comparison_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthored1111DepartmentResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    try:
        _validate_paths(output_path, report_path, manifest_path, comparison_source)
        _validate_config(config)
        _validate_observed_source(comparison_source, config)
    except ValueError as exc:
        raise JdlGeneratorAuthored1111DepartmentError(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    row = tuple(config.jdl_columns[name] for name in OFFICIAL_HEADER)
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        report = _validate_candidate(output_path, config, comparison_source)
        if report["errors"]:
            raise JdlGeneratorAuthored1111DepartmentError(
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
    return JdlGeneratorAuthored1111DepartmentResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def _validate_config(config: JdlGeneratorAuthored1111DepartmentConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthored1111DepartmentError(
            "experiment identity/status mismatch"
        )
    _validate_exact_keys("jdl_columns", config.jdl_columns, OFFICIAL_HEADER)
    _validate_exact_keys("field_decisions", config.field_decisions, OFFICIAL_HEADER)
    if not all(isinstance(value, str) for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111DepartmentError(
            "all JDL values must be strings"
        )
    if any("\r" in value or "\n" in value for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111DepartmentError("embedded newline is unsupported")
    columns = config.jdl_columns
    if columns["//識別フラグ"] != "1111":
        raise JdlGeneratorAuthored1111DepartmentError(
            "identifier flag must be 1111"
        )
    if columns["伝番"]:
        raise JdlGeneratorAuthored1111DepartmentError(
            "voucher number must remain explicitly blank for this experiment"
        )
    _validate_date(columns["日付"], config.journal_date_iso)
    if any(columns[name] for name in ACCOUNT_CODE_OR_FORMAL_FIELDS):
        raise JdlGeneratorAuthored1111DepartmentError(
            "candidate uses confirmed account names only"
        )
    accounts = config.target_account_evidence
    if (
        columns["借方科目名称"] != accounts.debit_name
        or columns["貸方科目名称"] != accounts.credit_name
    ):
        raise JdlGeneratorAuthored1111DepartmentError(
            "account names do not exactly match target evidence"
        )
    if not all(vars(accounts).values()):
        raise JdlGeneratorAuthored1111DepartmentError(
            "account evidence must include code, name, and formal name"
        )
    _validate_text_lengths(columns)
    if _amount(columns["借方金額"], "借方金額") != _amount(
        columns["貸方金額"], "貸方金額"
    ):
        raise JdlGeneratorAuthored1111DepartmentError(
            "debit and credit amounts must balance"
        )
    if any(columns[name] for name in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1111DepartmentError(
            "subaccount fields must remain blank"
        )
    if config.company_tax_processing != JdlTaxProcessingMode.EXEMPT.value:
        raise JdlGeneratorAuthored1111DepartmentError(
            "company tax processing must be EXEMPT"
        )
    if any(columns[name] for name in TAX_FIELDS):
        raise JdlGeneratorAuthored1111DepartmentError(
            "exempt tax fields must remain blank"
        )
    evidence = config.target_department_evidence
    if not all(
        (
            evidence.department_code,
            evidence.formal_name,
            evidence.short_name,
            evidence.department_processing_enabled,
            evidence.confirmed_registered,
            evidence.no_fuzzy_matching,
            evidence.no_automatic_replacement,
        )
    ):
        raise JdlGeneratorAuthored1111DepartmentError(
            "department target evidence is incomplete"
        )
    expected_department = (
        evidence.department_code,
        evidence.short_name,
        evidence.department_code,
        evidence.short_name,
    )
    actual_department = tuple(columns[name] for name in DEPARTMENT_FIELDS)
    if actual_department != expected_department:
        raise JdlGeneratorAuthored1111DepartmentError(
            "both department sides must exactly match observed target evidence"
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
            "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
            "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
            "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
            "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
            "摘要": "EXPLICIT_EXPERIMENT_INPUT",
            "借方部門コード": "TARGET_MASTER_CONFIRMED_DEPARTMENT_CODE",
            "借方部門名称": "OBSERVED_RUNTIME_CONFIRMED_DEPARTMENT_SHORT_NAME",
            "貸方部門コード": "TARGET_MASTER_CONFIRMED_DEPARTMENT_CODE",
            "貸方部門名称": "OBSERVED_RUNTIME_CONFIRMED_DEPARTMENT_SHORT_NAME",
        }
    )
    for name in TAX_FIELDS:
        expected[name] = "OFFICIAL_DOCUMENTED_EXEMPT_BLANK"
    mismatched = [name for name in OFFICIAL_HEADER if decisions[name] != expected[name]]
    if mismatched:
        raise JdlGeneratorAuthored1111DepartmentError(
            "field decision mismatch: " + ", ".join(mismatched)
        )


def _validate_observed_source(
    path: Path,
    config: JdlGeneratorAuthored1111DepartmentConfig,
) -> None:
    row = _read_source_row(path)
    evidence = config.target_department_evidence
    accounts = config.target_account_evidence
    expected = {
        "//識別フラグ": "1111",
        "借方科目": accounts.debit_code,
        "借方科目名称": accounts.debit_name,
        "借方科目正式名称": accounts.debit_formal_name,
        "貸方科目": accounts.credit_code,
        "貸方科目名称": accounts.credit_name,
        "貸方科目正式名称": accounts.credit_formal_name,
        "借方部門コード": evidence.department_code,
        "借方部門名称": evidence.short_name,
        "貸方部門コード": evidence.department_code,
        "貸方部門名称": evidence.short_name,
    }
    mismatched = [
        name for name, value in expected.items() if row[OFFICIAL_HEADER.index(name)] != value
    ]
    if mismatched:
        raise JdlGeneratorAuthored1111DepartmentError(
            "observed source does not confirm configured evidence: "
            + ", ".join(mismatched)
        )


def _read_source_row(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_bytes().decode("cp932")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlGeneratorAuthored1111DepartmentError(
            "observed source must be parseable CP932 CSV"
        ) from exc
    headers = [index for index, row in enumerate(rows) if tuple(row) == OFFICIAL_HEADER]
    if len(headers) != 1:
        raise JdlGeneratorAuthored1111DepartmentError(
            "observed source must contain one official header"
        )
    records = rows[headers[0] + 1:]
    if len(records) != 1 or len(records[0]) != 30:
        raise JdlGeneratorAuthored1111DepartmentError(
            "observed source must contain one 30-column record"
        )
    return tuple(records[0])


def _validate_candidate(
    path: Path,
    config: JdlGeneratorAuthored1111DepartmentConfig,
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
    if (
        len(rows) != 2
        or tuple(rows[0]) != OFFICIAL_HEADER
        or len(rows[1]) != 30
    ):
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
        "department_sides": ["DEBIT", "CREDIT"],
        "department_master_exact_match": True,
        "subaccounts_blank": True,
        "exempt_tax_fields_blank": True,
        "source_row_byte_identical": source_identical,
        "source_jdl_row_used_for_construction": False,
        "production_ready": False,
        "privacy_note": (
            "Account, department, description, date, amount, raw row, and source path "
            "are omitted."
        ),
    }


def _require_all_true(values: dict[str, bool], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in values]
    unconfirmed = [key for key in required if values.get(key) is not True]
    if missing or unconfirmed:
        raise JdlGeneratorAuthored1111DepartmentError(
            f"validation incomplete; missing={missing}, unconfirmed={unconfirmed}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private JDL 1111 both-side department candidate."
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
        JdlGeneratorAuthored1111DepartmentError,
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

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.diagnostics.jdl_csv.serialization import (
    analysis_to_privacy_safe_dict,
)
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)


EXPERIMENT_ID = "EXP-01"
EXPERIMENT_STATUS = "EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT"
DEFAULT_OUTPUT_DIR = Path("data/private/experiments/jdl_import/exp01")
DEFAULT_OUTPUT_NAME = "EXP-01_jdl_import_candidate.csv"

OFFICIAL_SPEC = jdl_ibex_cashbook_official_journal_import_spec()
OFFICIAL_HEADER = OFFICIAL_SPEC.column_names
OFFICIAL_FIELD_BY_NAME = {column.name: column for column in OFFICIAL_SPEC.columns}
TARGET_MASTER_VALIDATION_KEYS = (
    "debit_account_exists_in_target_master",
    "credit_account_exists_in_target_master",
    "debit_subaccount_blank_or_exists_under_parent",
    "credit_subaccount_blank_or_exists_under_parent",
    "no_fuzzy_matching_or_auto_replacement",
)
TAX_VALIDATION_KEYS = (
    "company_tax_processing_confirmed",
    "tax_category_abbreviations_confirmed_when_used",
    "tax_scope_tax_category_combination_confirmed_when_used",
    "transaction_account_confirmed_when_used",
)
REQUIRED_TRANSACTION_COLUMNS = (
    "//識別フラグ",
    "伝番",
    "日付",
    "借方金額",
    "貸方金額",
    "摘要",
)
DEBIT_ACCOUNT_IDENTIFIER_COLUMNS = ("借方科目", "借方科目名称", "借方科目正式名称")
CREDIT_ACCOUNT_IDENTIFIER_COLUMNS = ("貸方科目", "貸方科目名称", "貸方科目正式名称")
TAX_FIELDS_BY_SIDE = {
    "借方": ("借方課区", "借方税区", "借方税入力方法", "借方消費税"),
    "貸方": ("貸方課区", "貸方税区", "貸方税入力方法", "貸方消費税"),
}
TRANSACTION_ACCOUNT_FIELDS = ("借方取引科目", "貸方取引科目")
TAX_INPUT_METHODS = ("内税", "外税", "別記")
OBSERVED_INVARIANTS = (
    "encoding=cp932",
    "bom=false",
    "line_ending=CRLF",
    "header=official_documented_30_column_header",
    "record_count=1",
    "identifier_flag=1000_for_EXP01_official_non_voucher_journal",
)


class JdlExp01CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class JdlExp01CandidateConfig:
    jdl_columns: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    company_tax_processing: str = JdlTaxProcessingMode.UNCONFIRMED.value
    tax_validation: dict[str, bool] | None = None
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlExp01ValidationReport:
    success: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    output_path: Path
    report_path: Path
    record_count: int
    column_count: int
    identifier_flags: tuple[tuple[str, int], ...]
    balanced: bool
    required_mapping_complete: bool
    target_master_validation_confirmed: bool
    implicit_default_count: int
    status: str = EXPERIMENT_STATUS

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": EXPERIMENT_ID,
            "status": self.status,
            "success": self.success,
            "output_file": self.output_path.name,
            "record_count": self.record_count,
            "column_count": self.column_count,
            "identifier_flags": dict(self.identifier_flags),
            "balanced": self.balanced,
            "required_mapping_complete": self.required_mapping_complete,
            "target_master_validation_confirmed": (
                self.target_master_validation_confirmed
            ),
            "implicit_default_count": self.implicit_default_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "privacy_note": (
                "科目名、補助名、部門名、摘要、個別金額、raw CSV rowは出力しません。"
            ),
        }

    def to_privacy_safe_text(self) -> str:
        payload = self.to_privacy_safe_dict()
        lines = [
            "JDL EXP-01 import candidate verification",
            f"status: {payload['status']}",
            f"success: {payload['success']}",
            f"records: {payload['record_count']}",
            f"column_count: {payload['column_count']}",
            f"identifier_flags: {payload['identifier_flags']}",
            f"balanced: {payload['balanced']}",
            f"required_mapping_complete: {payload['required_mapping_complete']}",
            "target_master_validation_confirmed: "
            f"{payload['target_master_validation_confirmed']}",
            f"implicit_default_count: {payload['implicit_default_count']}",
        ]
        if self.errors:
            lines.append("errors:")
            lines.extend(f"- {error}" for error in self.errors)
        if self.warnings:
            lines.append("warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.append(payload["privacy_note"])
        return "\n".join(lines)


@dataclass(frozen=True)
class JdlExp01GenerationResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    validation_report: JdlExp01ValidationReport


def load_config(path: Path) -> JdlExp01CandidateConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return JdlExp01CandidateConfig(
        jdl_columns=dict(payload["jdl_columns"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload.get("target_master_validation", {})),
        company_tax_processing=payload.get(
            "company_tax_processing",
            JdlTaxProcessingMode.UNCONFIRMED.value,
        ),
        tax_validation=dict(payload.get("tax_validation", {})),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_exp01_candidate(
    config: JdlExp01CandidateConfig,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    overwrite: bool = False,
    config_path: Path | None = None,
) -> JdlExp01GenerationResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "EXP-01_manifest.json"
    _validate_paths(output_path, report_path, manifest_path, overwrite, config_path)
    _validate_config(config)
    entry = build_exp01_common_journal(config)
    row = serialize_exp01_candidate_row(config, entry)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_candidate_csv(output_path, OFFICIAL_HEADER, row)
    report = validate_generated_candidate(output_path, config)
    if not report.success:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        raise JdlExp01CandidateError("; ".join(report.errors))
    _write_report(report_path, report)
    _write_manifest(manifest_path, output_path, report_path, report)
    return JdlExp01GenerationResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        validation_report=report,
    )


def build_exp01_common_journal(config: JdlExp01CandidateConfig) -> JournalEntry:
    _validate_config(config)
    columns = _resolved_columns(config)
    source = SourceReference(
        file_name="EXP-01_jdl_import_candidate",
        row_number=2,
        source_journal_id=columns["伝番"],
    )
    return JournalEntry(
        id=columns["伝番"],
        source_reference=source,
        date=_date(config.journal_date_iso, "journal_date_iso"),
        description=columns["摘要"] or None,
        lines=[
            JournalLine(
                side=Side.DEBIT,
                account=_account_identity(columns, DEBIT_ACCOUNT_IDENTIFIER_COLUMNS),
                sub_account=columns["借方補助名称"] or None,
                department=columns["借方部門名称"] or None,
                amount=_required_decimal(columns["借方金額"], "借方金額"),
                tax_info=TaxInfo(
                    category=columns["借方税区"] or None,
                    tax_amount=_optional_decimal(columns["借方消費税"], "借方消費税"),
                    tax_inclusion=columns["借方税入力方法"] or None,
                    metadata={
                        "source": "jdl_exp01_official_documented_schema",
                        "company_tax_processing": config.company_tax_processing,
                    },
                ),
                source_reference=source,
            ),
            JournalLine(
                side=Side.CREDIT,
                account=_account_identity(columns, CREDIT_ACCOUNT_IDENTIFIER_COLUMNS),
                sub_account=columns["貸方補助名称"] or None,
                department=columns["貸方部門名称"] or None,
                amount=_required_decimal(columns["貸方金額"], "貸方金額"),
                tax_info=TaxInfo(
                    category=columns["貸方税区"] or None,
                    tax_amount=_optional_decimal(columns["貸方消費税"], "貸方消費税"),
                    tax_inclusion=columns["貸方税入力方法"] or None,
                    metadata={
                        "source": "jdl_exp01_official_documented_schema",
                        "company_tax_processing": config.company_tax_processing,
                    },
                ),
                source_reference=source,
            ),
        ],
        metadata={
            "experiment_id": EXPERIMENT_ID,
            "status": EXPERIMENT_STATUS,
            "schema_evidence_level": "OFFICIAL_DOCUMENTED",
            "serialization_evidence_level": "OBSERVED",
            "production_adapter": False,
        },
    )


def serialize_exp01_candidate_row(
    config: JdlExp01CandidateConfig,
    entry: JournalEntry,
) -> tuple[str, ...]:
    if not entry.is_balanced():
        raise JdlExp01CandidateError("EXP-01 candidate journal is not balanced")
    columns = _resolved_columns(config)
    if _required_decimal(columns["借方金額"], "借方金額") != entry.debit_total():
        raise JdlExp01CandidateError("Debit amount does not match Common Journal Model")
    if _required_decimal(columns["貸方金額"], "貸方金額") != entry.credit_total():
        raise JdlExp01CandidateError("Credit amount does not match Common Journal Model")
    return tuple(columns[column] for column in OFFICIAL_HEADER)


def validate_generated_candidate(
    path: Path,
    config: JdlExp01CandidateConfig,
) -> JdlExp01ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("BOM must not be present")
    if b"\r\n" not in raw or b"\n" in raw.replace(b"\r\n", b""):
        errors.append("line ending must be CRLF only")
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        text = ""
        errors.append("encoding must be CP932-decodable")

    schema = jdl_ibex_cashbook_35_5_observed_schema()
    analyzer = JdlCsvStructuralAnalyzer(observed_schema=schema)
    analysis = analyzer.analyze_path(path)
    if analysis.encoding != "cp932":
        errors.append("analyzer did not classify encoding as cp932")
    if analysis.has_bom:
        errors.append("analyzer detected BOM")
    if analysis.line_ending != "CRLF":
        errors.append("analyzer did not classify CRLF")
    if analysis.header_columns != OFFICIAL_HEADER:
        errors.append("official documented header does not match")
    if analysis.header_column_count != 30:
        errors.append("header column count must be 30")
    if analysis.data_record_count != 1:
        errors.append("EXP-01 must contain exactly one data record")
    if dict(analysis.identifier_flag_counts) != {"1000": 1}:
        errors.append("EXP-01 identifier flag sequence must be one 1000 record")
    if analysis.analysis_errors:
        errors.extend(result.rule_id for result in analysis.analysis_errors)

    rows = tuple(csv.reader(text.splitlines())) if text else ()
    if len(rows) != 2:
        errors.append("CSV body must contain only official header and one data record")
    elif tuple(rows[0]) != OFFICIAL_HEADER:
        errors.append("first row must be the official documented header")
    elif len(rows[1]) != 30:
        errors.append("data row must contain 30 columns")
    elif tuple(rows[1]) != serialize_exp01_candidate_row(
        config,
        build_exp01_common_journal(config),
    ):
        errors.append("generated row differs from explicit configuration")

    entry = build_exp01_common_journal(config)
    balanced = entry.is_balanced()
    if not balanced:
        errors.append("debit and credit totals must match")

    report = JdlExp01ValidationReport(
        success=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        output_path=path,
        report_path=path.with_suffix(".report.json"),
        record_count=analysis.data_record_count,
        column_count=analysis.header_column_count or 0,
        identifier_flags=analysis.identifier_flag_counts,
        balanced=balanced,
        required_mapping_complete=True,
        target_master_validation_confirmed=_target_master_validation_confirmed(config),
        implicit_default_count=_implicit_default_count(config),
    )
    _ = analysis_to_privacy_safe_dict(analysis)
    return report


def config_column_plan() -> tuple[dict[str, str], ...]:
    required_transaction = set(REQUIRED_TRANSACTION_COLUMNS)
    plan = []
    for column in OFFICIAL_HEADER:
        if column in required_transaction:
            source = "explicit_experiment_config_required_transaction"
            notes = "Required for EXP-01 candidate generation."
        elif column in DEBIT_ACCOUNT_IDENTIFIER_COLUMNS + CREDIT_ACCOUNT_IDENTIFIER_COLUMNS:
            source = "explicit_experiment_config_conditional_master_identifier"
            notes = "At least one documented account identifier per side is required."
        elif column in TRANSACTION_ACCOUNT_FIELDS:
            source = "blank_when_unneeded_official_documented"
            notes = "Only for consumption tax journals; not defaulted to zero."
        elif column in {
            field
            for fields in TAX_FIELDS_BY_SIDE.values()
            for field in fields
        }:
            source = "conditional_tax_field_official_documented"
            notes = "Requiredness depends on confirmed company tax processing."
        elif column in required_transaction:
            source = "explicit_experiment_config_required_transaction"
            notes = "Required for EXP-01 candidate generation."
        else:
            source = "blank_allowed_when_unneeded_official_documented"
            notes = "Column is always emitted; value may be blank when unneeded."
        plan.append(
            {
                "column": column,
                "source": source,
                "notes": notes,
            }
        )
    return tuple(plan)


def _validate_paths(
    output_path: Path,
    report_path: Path,
    manifest_path: Path,
    overwrite: bool,
    config_path: Path | None,
) -> None:
    if config_path is not None and output_path.resolve() == config_path.resolve():
        raise JdlExp01CandidateError("config path and output path must differ")
    if not _is_private_experiment_path(output_path):
        raise JdlExp01CandidateError(
            "EXP-01 output must be under data/private/experiments"
        )
    existing = [path for path in (output_path, report_path, manifest_path) if path.exists()]
    if existing and not overwrite:
        raise JdlExp01CandidateError("output already exists; pass overwrite=True to replace")


def _is_private_experiment_path(path: Path) -> bool:
    parts = path.parts
    return any(
        parts[index:index + 3] == ("data", "private", "experiments")
        for index in range(max(len(parts) - 2, 0))
    )


def _validate_config(config: JdlExp01CandidateConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID:
        raise JdlExp01CandidateError("experiment_id must be EXP-01")
    if config.status != EXPERIMENT_STATUS:
        raise JdlExp01CandidateError("status must be EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT")
    _validate_target_master_confirmation(config.target_master_validation)
    _validate_tax_confirmation(config.tax_validation or {})
    columns = _resolved_columns(config)
    extra = [column for column in config.jdl_columns if column not in OFFICIAL_HEADER]
    if extra:
        raise JdlExp01CandidateError("unknown JDL columns in config: " + ", ".join(extra))
    non_strings = [column for column, value in columns.items() if not isinstance(value, str)]
    if non_strings:
        raise JdlExp01CandidateError("all JDL column values must be strings: " + ", ".join(non_strings))
    newline_values = [
        column
        for column, value in columns.items()
        if "\r" in value or "\n" in value
    ]
    if newline_values:
        raise JdlExp01CandidateError(
            "EXP-01 does not allow embedded newlines: " + ", ".join(newline_values)
        )
    if columns["//識別フラグ"] != "1000":
        raise JdlExp01CandidateError("EXP-01 official single-record candidate requires flag 1000")
    for field in REQUIRED_TRANSACTION_COLUMNS:
        if not columns[field].strip():
            raise JdlExp01CandidateError(f"missing required EXP-01 mapping/value: {field}")
    _validate_account_identifier(columns, DEBIT_ACCOUNT_IDENTIFIER_COLUMNS, "debit account")
    _validate_account_identifier(columns, CREDIT_ACCOUNT_IDENTIFIER_COLUMNS, "credit account")
    _validate_official_field_values(columns)
    _validate_jdl_date(columns["日付"], config.journal_date_iso)
    _required_decimal(columns["借方金額"], "借方金額")
    _required_decimal(columns["貸方金額"], "貸方金額")
    _optional_decimal(columns["借方消費税"], "借方消費税")
    _optional_decimal(columns["貸方消費税"], "貸方消費税")
    if _required_decimal(columns["借方金額"], "借方金額") != _required_decimal(
        columns["貸方金額"],
        "貸方金額",
    ):
        raise JdlExp01CandidateError("EXP-01 debit and credit amounts must match")
    _validate_alternative_pair(columns, "借方補助", "借方補助名称")
    _validate_alternative_pair(columns, "貸方補助", "貸方補助名称")
    _validate_pair(columns, "借方部門コード", "借方部門名称")
    _validate_pair(columns, "貸方部門コード", "貸方部門名称")
    _validate_tax_fields(config, columns)
    _date(config.journal_date_iso, "journal_date_iso")


def _resolved_columns(config: JdlExp01CandidateConfig) -> dict[str, str]:
    return {column: config.jdl_columns.get(column, "") for column in OFFICIAL_HEADER}


def _implicit_default_count(config: JdlExp01CandidateConfig) -> int:
    return sum(1 for column in OFFICIAL_HEADER if column not in config.jdl_columns)


def _account_identity(columns: dict[str, str], fields: tuple[str, str, str]) -> str:
    for field in fields:
        value = columns[field].strip()
        if value:
            return value
    raise JdlExp01CandidateError("account identifier is missing")


def _validate_account_identifier(
    columns: dict[str, str],
    fields: tuple[str, str, str],
    label: str,
) -> None:
    if not any(columns[field].strip() for field in fields):
        raise JdlExp01CandidateError(
            f"{label} requires at least one documented identifier"
        )


def _validate_pair(columns: dict[str, str], code_field: str, name_field: str) -> None:
    has_code = bool(columns[code_field].strip())
    has_name = bool(columns[name_field].strip())
    if has_code != has_name:
        raise JdlExp01CandidateError(
            f"ambiguous explicit mapping: {code_field} and {name_field} must both be blank or both be set"
        )


def _validate_alternative_pair(
    columns: dict[str, str],
    code_field: str,
    name_field: str,
) -> None:
    code = columns[code_field].strip()
    name = columns[name_field].strip()
    if code:
        _validate_digits(code, code_field, 4)
    if name:
        _validate_text_length(name, name_field, OFFICIAL_FIELD_BY_NAME[name_field].max_length)


def _validate_official_field_values(columns: dict[str, str]) -> None:
    _validate_digits(columns["//識別フラグ"], "//識別フラグ", 4)
    _validate_digits(columns["伝番"], "伝番", 8)
    for field in ("借方科目", "貸方科目", "借方取引科目", "貸方取引科目"):
        if columns[field].strip():
            _validate_digits(columns[field], field, 4)
    for field in ("借方部門コード", "貸方部門コード"):
        if columns[field].strip():
            _validate_digits(columns[field], field, 4)
    for field, definition in OFFICIAL_FIELD_BY_NAME.items():
        if definition.data_type == "文字" and definition.max_length is not None:
            _validate_text_length(columns[field], field, definition.max_length)
    for field in ("借方金額", "借方消費税", "貸方金額", "貸方消費税"):
        if columns[field].strip():
            _validate_amount_digits(columns[field], field, 12)


def _validate_tax_confirmation(values: dict[str, bool]) -> None:
    missing = [key for key in TAX_VALIDATION_KEYS if key not in values]
    if missing:
        raise JdlExp01CandidateError(
            "missing tax validation confirmations: " + ", ".join(missing)
        )
    if values.get("company_tax_processing_confirmed") is not True:
        raise JdlExp01CandidateError("company tax processing is not confirmed")


def _validate_tax_fields(
    config: JdlExp01CandidateConfig,
    columns: dict[str, str],
) -> None:
    tax_validation = config.tax_validation or {}
    try:
        mode = JdlTaxProcessingMode(config.company_tax_processing)
    except ValueError as exc:
        raise JdlExp01CandidateError("unknown company tax processing mode") from exc
    if mode is JdlTaxProcessingMode.UNCONFIRMED:
        raise JdlExp01CandidateError("company tax processing mode must be confirmed")
    if mode is JdlTaxProcessingMode.EXEMPT:
        populated = [
            field
            for fields in TAX_FIELDS_BY_SIDE.values()
            for field in fields
            if columns[field].strip()
        ] + [
            field for field in TRANSACTION_ACCOUNT_FIELDS if columns[field].strip()
        ]
        if populated:
            raise JdlExp01CandidateError(
                "unnecessary tax field populated for exempt processing: "
                + ", ".join(populated)
            )
        return
    if tax_validation.get("tax_category_abbreviations_confirmed_when_used") is not True:
        raise JdlExp01CandidateError("tax abbreviations must be confirmed before use")
    if tax_validation.get("tax_scope_tax_category_combination_confirmed_when_used") is not True:
        raise JdlExp01CandidateError("tax scope/category combination is not confirmed")
    for side, (scope_field, category_field, method_field, amount_field) in TAX_FIELDS_BY_SIDE.items():
        if not columns[scope_field].strip() or not columns[category_field].strip():
            raise JdlExp01CandidateError(f"{side} tax scope and category are required")
        if mode is JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED:
            if columns[method_field].strip() or columns[amount_field].strip():
                raise JdlExp01CandidateError(
                    f"{side} tax-inclusive processing must not populate tax input method or tax amount"
                )
        if mode is JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED:
            if columns[method_field].strip() not in TAX_INPUT_METHODS:
                raise JdlExp01CandidateError(f"{side} tax input method is required")
            if not columns[amount_field].strip():
                raise JdlExp01CandidateError(f"{side} tax amount is required")
    if any(columns[field].strip() for field in TRANSACTION_ACCOUNT_FIELDS):
        if tax_validation.get("transaction_account_confirmed_when_used") is not True:
            raise JdlExp01CandidateError("transaction account semantics are not confirmed")
    elif mode is JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED:
        pass


def _validate_digits(value: str, field: str, max_digits: int) -> None:
    if not value.isdigit() or len(value) > max_digits:
        raise JdlExp01CandidateError(
            f"{field} must be numeric and at most {max_digits} digits"
        )


def _validate_amount_digits(value: str, field: str, max_digits: int) -> None:
    normalized = value.replace(",", "")
    if not normalized.isdigit() or len(normalized) > max_digits:
        raise JdlExp01CandidateError(
            f"{field} must be an integer amount with at most {max_digits} digits"
        )


def _validate_text_length(value: str, field: str, max_length: int | None) -> None:
    if max_length is not None and len(value) > max_length:
        raise JdlExp01CandidateError(
            f"{field} must be at most {max_length} characters"
        )


def _validate_target_master_confirmation(values: dict[str, bool]) -> None:
    missing = [key for key in TARGET_MASTER_VALIDATION_KEYS if key not in values]
    if missing:
        raise JdlExp01CandidateError(
            "missing target master validation confirmations: " + ", ".join(missing)
        )
    unconfirmed = [
        key
        for key in TARGET_MASTER_VALIDATION_KEYS
        if values.get(key) is not True
    ]
    if unconfirmed:
        raise JdlExp01CandidateError(
            "target master validation is not confirmed: " + ", ".join(unconfirmed)
        )


def _target_master_validation_confirmed(config: JdlExp01CandidateConfig) -> bool:
    return all(config.target_master_validation.get(key) is True for key in TARGET_MASTER_VALIDATION_KEYS)


def _write_candidate_csv(
    path: Path,
    header: tuple[str, ...],
    row: tuple[str, ...],
) -> None:
    with path.open("w", encoding="cp932", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerow(row)


def _write_report(path: Path, report: JdlExp01ValidationReport) -> None:
    path.write_text(
        json.dumps(report.to_privacy_safe_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_manifest(
    path: Path,
    csv_path: Path,
    report_path: Path,
    report: JdlExp01ValidationReport,
) -> None:
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "status": EXPERIMENT_STATUS,
        "csv_path": csv_path.name,
        "privacy_safe_report_path": report_path.name,
        "actual_result": "UNTESTED",
        "result_status_values": ["PASS", "REJECTED", "UNTESTED"],
        "jdl_error_log_path": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observed_invariants": list(OBSERVED_INVARIANTS),
        "column_plan": list(config_column_plan()),
        "validation": report.to_privacy_safe_dict(),
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _required_decimal(value: str, field: str) -> Decimal:
    if not value.strip():
        raise JdlExp01CandidateError(f"{field} is required")
    return _decimal(value, field)


def _optional_decimal(value: str, field: str) -> Decimal | None:
    if not value.strip():
        return None
    return _decimal(value, field)


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise JdlExp01CandidateError(f"{field} must be a parseable amount") from exc


def _date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise JdlExp01CandidateError(f"{field} must be ISO date YYYY-MM-DD") from exc


def _validate_jdl_date(jdl_value: str, iso_value: str) -> None:
    parsed = _date(iso_value, "journal_date_iso")
    expected = parsed.strftime("%Y%m%d")
    if not jdl_value.isdigit() or len(jdl_value) != 8:
        raise JdlExp01CandidateError("日付 must be YYYYMMDD / 8 digits")
    if jdl_value != expected:
        raise JdlExp01CandidateError("日付 must match journal_date_iso as YYYYMMDD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate EXP-01 JDL import candidate CSV for manual JDL testing.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = generate_exp01_candidate(
            load_config(args.config),
            output_dir=args.output_dir,
            overwrite=args.overwrite,
            config_path=args.config,
        )
    except (OSError, KeyError, json.JSONDecodeError, JdlExp01CandidateError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(result.validation_report.to_privacy_safe_text())
    print(f"csv: {result.csv_path}")
    print(f"report: {result.report_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

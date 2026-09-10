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


EXPERIMENT_ID = "EXP-01"
EXPERIMENT_STATUS = "EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT"
DEFAULT_OUTPUT_DIR = Path("data/private/experiments/jdl_import/exp01")
DEFAULT_OUTPUT_NAME = "EXP-01_jdl_import_candidate.csv"

EXPLICIT_CONFIG_REQUIRED_COLUMNS = jdl_ibex_cashbook_35_5_observed_schema().observed_header
OBSERVED_INVARIANTS = (
    "encoding=cp932",
    "bom=false",
    "line_ending=CRLF",
    "header=observed_30_column_header",
    "record_count=1",
    "identifier_flag=1000_for_EXP01_observed_single_record_candidate",
)


class JdlExp01CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class JdlExp01CandidateConfig:
    jdl_columns: dict[str, str]
    journal_date_iso: str
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
    schema = jdl_ibex_cashbook_35_5_observed_schema()
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "EXP-01_manifest.json"
    _validate_paths(output_path, report_path, manifest_path, overwrite, config_path)
    _validate_config(config, schema.observed_header)
    entry = build_exp01_common_journal(config)
    row = serialize_exp01_candidate_row(config, entry)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_candidate_csv(output_path, schema.observed_header, row)
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
    _validate_config(config, EXPLICIT_CONFIG_REQUIRED_COLUMNS)
    columns = config.jdl_columns
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
                account=columns["借方科目名称"],
                sub_account=columns["借方補助名称"] or None,
                department=columns["借方部門名称"] or None,
                amount=_required_decimal(columns["借方金額"], "借方金額"),
                tax_info=TaxInfo(
                    category=columns["借方税区"] or None,
                    tax_amount=_optional_decimal(columns["借方消費税"], "借方消費税"),
                    metadata={"source": "jdl_exp01_explicit_config"},
                ),
                source_reference=source,
            ),
            JournalLine(
                side=Side.CREDIT,
                account=columns["貸方科目名称"],
                sub_account=columns["貸方補助名称"] or None,
                department=columns["貸方部門名称"] or None,
                amount=_required_decimal(columns["貸方金額"], "貸方金額"),
                tax_info=TaxInfo(
                    category=columns["貸方税区"] or None,
                    tax_amount=_optional_decimal(columns["貸方消費税"], "貸方消費税"),
                    metadata={"source": "jdl_exp01_explicit_config"},
                ),
                source_reference=source,
            ),
        ],
        metadata={
            "experiment_id": EXPERIMENT_ID,
            "status": EXPERIMENT_STATUS,
            "evidence_level": "OBSERVED",
            "production_adapter": False,
        },
    )


def serialize_exp01_candidate_row(
    config: JdlExp01CandidateConfig,
    entry: JournalEntry,
) -> tuple[str, ...]:
    if not entry.is_balanced():
        raise JdlExp01CandidateError("EXP-01 candidate journal is not balanced")
    if _required_decimal(config.jdl_columns["借方金額"], "借方金額") != entry.debit_total():
        raise JdlExp01CandidateError("Debit amount does not match Common Journal Model")
    if _required_decimal(config.jdl_columns["貸方金額"], "貸方金額") != entry.credit_total():
        raise JdlExp01CandidateError("Credit amount does not match Common Journal Model")
    return tuple(config.jdl_columns[column] for column in EXPLICIT_CONFIG_REQUIRED_COLUMNS)


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
    if analysis.header_columns != schema.observed_header:
        errors.append("observed header does not match")
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
        errors.append("CSV body must contain only observed header and one data record")
    elif tuple(rows[0]) != schema.observed_header:
        errors.append("first row must be the observed header")
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
        implicit_default_count=0,
    )
    _ = analysis_to_privacy_safe_dict(analysis)
    return report


def config_column_plan() -> tuple[dict[str, str], ...]:
    required_master = {
        "借方科目",
        "借方科目名称",
        "借方科目正式名称",
        "貸方科目",
        "貸方科目名称",
        "貸方科目正式名称",
    }
    required_transaction = {"//識別フラグ", "伝番", "日付", "借方金額", "貸方金額", "摘要"}
    plan = []
    for column in EXPLICIT_CONFIG_REQUIRED_COLUMNS:
        if column in required_master:
            source = "explicit_experiment_config_required_master"
        elif column in required_transaction:
            source = "explicit_experiment_config_required_transaction"
        else:
            source = "explicit_experiment_config_required_unknown_or_optional"
        plan.append(
            {
                "column": column,
                "source": source,
                "notes": "No implicit default is generated for this column.",
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


def _validate_config(
    config: JdlExp01CandidateConfig,
    observed_header: tuple[str, ...],
) -> None:
    if config.experiment_id != EXPERIMENT_ID:
        raise JdlExp01CandidateError("experiment_id must be EXP-01")
    if config.status != EXPERIMENT_STATUS:
        raise JdlExp01CandidateError("status must be EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT")
    columns = config.jdl_columns
    missing = [column for column in observed_header if column not in columns]
    extra = [column for column in columns if column not in observed_header]
    if missing:
        raise JdlExp01CandidateError("missing explicit JDL columns: " + ", ".join(missing))
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
        raise JdlExp01CandidateError("EXP-01 observed single-record candidate requires flag 1000")
    for field in (
        "伝番",
        "日付",
        "借方科目",
        "借方科目名称",
        "借方科目正式名称",
        "借方金額",
        "貸方科目",
        "貸方科目名称",
        "貸方科目正式名称",
        "貸方金額",
        "摘要",
    ):
        if not columns[field].strip():
            raise JdlExp01CandidateError(f"missing required EXP-01 mapping/value: {field}")
    _required_decimal(columns["借方金額"], "借方金額")
    _required_decimal(columns["貸方金額"], "貸方金額")
    _optional_decimal(columns["借方消費税"], "借方消費税")
    _optional_decimal(columns["貸方消費税"], "貸方消費税")
    if _required_decimal(columns["借方金額"], "借方金額") != _required_decimal(
        columns["貸方金額"],
        "貸方金額",
    ):
        raise JdlExp01CandidateError("EXP-01 debit and credit amounts must match")
    _validate_pair(columns, "借方補助", "借方補助名称")
    _validate_pair(columns, "貸方補助", "貸方補助名称")
    _validate_pair(columns, "借方部門コード", "借方部門名称")
    _validate_pair(columns, "貸方部門コード", "貸方部門名称")
    _date(config.journal_date_iso, "journal_date_iso")


def _validate_pair(columns: dict[str, str], code_field: str, name_field: str) -> None:
    has_code = bool(columns[code_field].strip())
    has_name = bool(columns[name_field].strip())
    if has_code != has_name:
        raise JdlExp01CandidateError(
            f"ambiguous explicit mapping: {code_field} and {name_field} must both be blank or both be set"
        )


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

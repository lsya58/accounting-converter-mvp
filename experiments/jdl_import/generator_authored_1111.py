from __future__ import annotations

import argparse
import csv
import io
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
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-1111-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_1111_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_1111"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_1111_candidate.csv"

OFFICIAL_SPEC = jdl_ibex_cashbook_official_journal_import_spec()
OFFICIAL_HEADER = OFFICIAL_SPEC.column_names
OFFICIAL_FIELDS = {field.name: field for field in OFFICIAL_SPEC.columns}

TARGET_MASTER_VALIDATION_KEYS = (
    "debit_account_name_exists_in_target_master",
    "credit_account_name_exists_in_target_master",
    "account_identifiers_visually_confirmed_after_roundtrip",
    "debit_subaccount_intentionally_blank",
    "credit_subaccount_intentionally_blank",
    "no_fuzzy_matching_or_auto_replacement",
)
TAX_VALIDATION_KEYS = (
    "company_tax_processing_confirmed_exempt",
    "tax_fields_intentionally_blank",
)
ALLOWED_FIELD_DECISIONS = frozenset(
    {
        "EXPLICIT_EXPERIMENT_INPUT",
        "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
        "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
        "OFFICIAL_DOCUMENTED_EXEMPT_BLANK",
        "EXPLICIT_EXPERIMENT_CONDITION_BLANK",
    }
)
ACCOUNT_CODE_OR_FORMAL_FIELDS = (
    "借方科目",
    "借方科目正式名称",
    "貸方科目",
    "貸方科目正式名称",
)
SUBACCOUNT_FIELDS = ("借方補助", "借方補助名称", "貸方補助", "貸方補助名称")
TAX_FIELDS = (
    "借方課区",
    "借方税区",
    "借方税入力方法",
    "借方消費税",
    "貸方課区",
    "貸方税区",
    "貸方税入力方法",
    "貸方消費税",
    "借方取引科目",
    "貸方取引科目",
)
DEPARTMENT_FIELDS = (
    "借方部門コード",
    "借方部門名称",
    "貸方部門コード",
    "貸方部門名称",
)


class JdlGeneratorAuthored1111Error(ValueError):
    pass


@dataclass(frozen=True)
class JdlGeneratorAuthored1111Config:
    jdl_columns: dict[str, str]
    field_decisions: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    tax_validation: dict[str, bool]
    company_tax_processing: str = JdlTaxProcessingMode.EXEMPT.value
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthored1111Report:
    success: bool
    errors: tuple[str, ...]
    output_path: Path
    record_count: int
    column_count: int
    identifier_flags: tuple[tuple[str, int], ...]
    balanced: bool
    explicit_column_count: int
    explicit_decision_count: int
    blank_field_count: int
    target_master_validation_passed: bool
    exempt_tax_validation_passed: bool
    source_row_byte_identical: bool

    def to_privacy_safe_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": EXPERIMENT_ID,
            "status": EXPERIMENT_STATUS,
            "success": self.success,
            "output_file": self.output_path.name,
            "record_count": self.record_count,
            "column_count": self.column_count,
            "identifier_flags": dict(self.identifier_flags),
            "balanced": self.balanced,
            "explicit_column_count": self.explicit_column_count,
            "explicit_decision_count": self.explicit_decision_count,
            "blank_field_count": self.blank_field_count,
            "target_master_validation_passed": self.target_master_validation_passed,
            "exempt_tax_validation_passed": self.exempt_tax_validation_passed,
            "source_row_byte_identical": self.source_row_byte_identical,
            "construction_source": (
                "explicit private config backed by official/manual, observed "
                "serialization, and target-master confirmation"
            ),
            "source_jdl_row_used_for_construction": False,
            "errors": list(self.errors),
            "privacy_note": (
                "科目名、摘要、日付、個別金額、raw CSV row、比較元pathは出力しません。"
            ),
        }


@dataclass(frozen=True)
class JdlGeneratorAuthored1111Result:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: JdlGeneratorAuthored1111Report


def load_config(path: Path) -> JdlGeneratorAuthored1111Config:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return JdlGeneratorAuthored1111Config(
        jdl_columns=dict(payload["jdl_columns"]),
        field_decisions=dict(payload["field_decisions"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        tax_validation=dict(payload["tax_validation"]),
        company_tax_processing=payload.get(
            "company_tax_processing", JdlTaxProcessingMode.EXEMPT.value
        ),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthored1111Config,
    comparison_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthored1111Result:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    _validate_paths(
        output_path,
        report_path,
        manifest_path,
        comparison_source,
    )
    _validate_config(config)

    output_dir.mkdir(parents=True, exist_ok=True)
    row = tuple(config.jdl_columns[column] for column in OFFICIAL_HEADER)
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        report = validate_candidate(output_path, config, comparison_source)
        if not report.success:
            raise JdlGeneratorAuthored1111Error("; ".join(report.errors))
        _write_json_exclusive(report_path, report.to_privacy_safe_dict())
        _write_json_exclusive(
            manifest_path,
            {
                "experiment_id": EXPERIMENT_ID,
                "status": EXPERIMENT_STATUS,
                "actual_result": "UNTESTED",
                "result_status_values": ["PASS", "REJECTED", "UNTESTED"],
                "csv_path": output_path.name,
                "privacy_safe_report_path": report_path.name,
                "jdl_error_log_path": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "verification": report.to_privacy_safe_dict(),
            },
        )
    except Exception:
        for created_path in (output_path, report_path, manifest_path):
            created_path.unlink(missing_ok=True)
        raise
    return JdlGeneratorAuthored1111Result(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def validate_candidate(
    path: Path,
    config: JdlGeneratorAuthored1111Config,
    comparison_source: Path,
) -> JdlGeneratorAuthored1111Report:
    errors: list[str] = []
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        errors.append("BOM must not be present")
    without_crlf = raw.replace(b"\r\n", b"")
    if raw.count(b"\r\n") != 2 or b"\n" in without_crlf or b"\r" in without_crlf:
        errors.append("candidate must contain exactly two CRLF-terminated rows")
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError:
        text = ""
        errors.append("candidate must be CP932-decodable")

    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True)) if text else []
    if len(rows) != 2:
        errors.append("candidate must contain one header and one data row")
    elif tuple(rows[0]) != OFFICIAL_HEADER:
        errors.append("first physical row must be the exact official header")
    elif len(rows[1]) != 30:
        errors.append("data row must contain exactly 30 columns")
    elif tuple(rows[1]) != tuple(config.jdl_columns[name] for name in OFFICIAL_HEADER):
        errors.append("generated row differs from explicit config")

    analysis = JdlCsvStructuralAnalyzer(
        observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
    ).analyze_path(path)
    if analysis.analysis_errors:
        errors.extend(item.rule_id for item in analysis.analysis_errors)
    if analysis.encoding != "cp932":
        errors.append("analyzer must classify candidate as cp932")
    if analysis.has_bom or analysis.line_ending != "CRLF":
        errors.append("analyzer BOM/line-ending result does not match")
    if analysis.header_columns != OFFICIAL_HEADER:
        errors.append("analyzer header does not match official header")
    if analysis.data_record_count != 1:
        errors.append("analyzer must find exactly one data record")
    if dict(analysis.identifier_flag_counts) != {"1111": 1}:
        errors.append("analyzer must find one 1111 record")

    source_identical = _data_row_bytes(path) == _source_data_row_bytes(comparison_source)
    if source_identical:
        errors.append("generator-authored row must not be byte-identical to JDL source row")

    debit = _amount(config.jdl_columns["借方金額"], "借方金額")
    credit = _amount(config.jdl_columns["貸方金額"], "貸方金額")
    return JdlGeneratorAuthored1111Report(
        success=not errors,
        errors=tuple(errors),
        output_path=path,
        record_count=analysis.data_record_count,
        column_count=analysis.header_column_count or 0,
        identifier_flags=analysis.identifier_flag_counts,
        balanced=debit == credit,
        explicit_column_count=len(config.jdl_columns),
        explicit_decision_count=len(config.field_decisions),
        blank_field_count=sum(not value for value in config.jdl_columns.values()),
        target_master_validation_passed=_all_true(
            config.target_master_validation, TARGET_MASTER_VALIDATION_KEYS
        ),
        exempt_tax_validation_passed=_all_true(
            config.tax_validation, TAX_VALIDATION_KEYS
        ),
        source_row_byte_identical=source_identical,
    )


def _validate_config(config: JdlGeneratorAuthored1111Config) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthored1111Error("experiment identity/status mismatch")
    _validate_exact_keys("jdl_columns", config.jdl_columns, OFFICIAL_HEADER)
    _validate_exact_keys("field_decisions", config.field_decisions, OFFICIAL_HEADER)
    if not all(isinstance(value, str) for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111Error("all JDL values must be strings")
    invalid_decisions = sorted(
        set(config.field_decisions.values()) - ALLOWED_FIELD_DECISIONS
    )
    if invalid_decisions:
        raise JdlGeneratorAuthored1111Error("unsupported field decision source")
    _validate_field_decisions(config.field_decisions)
    if any("\r" in value or "\n" in value for value in config.jdl_columns.values()):
        raise JdlGeneratorAuthored1111Error("embedded newline is unsupported")
    if config.jdl_columns["//識別フラグ"] != "1111":
        raise JdlGeneratorAuthored1111Error("identifier flag must be 1111")
    voucher = config.jdl_columns["伝番"]
    if voucher and (not voucher.isdigit() or len(voucher) > 8):
        raise JdlGeneratorAuthored1111Error("voucher number must be blank or up to 8 digits")
    _validate_date(config.jdl_columns["日付"], config.journal_date_iso)
    if any(config.jdl_columns[name] for name in ACCOUNT_CODE_OR_FORMAL_FIELDS):
        raise JdlGeneratorAuthored1111Error(
            "this experiment uses confirmed account names only; code/formal name must be blank"
        )
    for name in ("借方科目名称", "貸方科目名称", "摘要"):
        if not config.jdl_columns[name]:
            raise JdlGeneratorAuthored1111Error(f"{name} must be explicit and nonblank")
    _validate_text_lengths(config.jdl_columns)
    debit = _amount(config.jdl_columns["借方金額"], "借方金額")
    credit = _amount(config.jdl_columns["貸方金額"], "貸方金額")
    if debit != credit:
        raise JdlGeneratorAuthored1111Error("debit and credit amounts must balance")
    _require_blank(config.jdl_columns, SUBACCOUNT_FIELDS, "subaccount")
    _require_blank(config.jdl_columns, DEPARTMENT_FIELDS, "department")
    if config.company_tax_processing != JdlTaxProcessingMode.EXEMPT.value:
        raise JdlGeneratorAuthored1111Error("company tax processing must be EXEMPT")
    _require_blank(config.jdl_columns, TAX_FIELDS, "exempt tax")
    _require_all_true(
        "target master validation",
        config.target_master_validation,
        TARGET_MASTER_VALIDATION_KEYS,
    )
    _require_all_true("tax validation", config.tax_validation, TAX_VALIDATION_KEYS)


def _validate_field_decisions(decisions: dict[str, str]) -> None:
    expected = {
        "//識別フラグ": "EXPLICIT_EXPERIMENT_INPUT",
        "伝番": "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
        "日付": "EXPLICIT_EXPERIMENT_INPUT",
        "借方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "借方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
        "借方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
        "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
        "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
        "摘要": "EXPLICIT_EXPERIMENT_INPUT",
    }
    expected.update(
        {name: "EXPLICIT_EXPERIMENT_CONDITION_BLANK" for name in SUBACCOUNT_FIELDS}
    )
    expected.update(
        {name: "OFFICIAL_DOCUMENTED_EXEMPT_BLANK" for name in TAX_FIELDS}
    )
    expected.update(
        {name: "EXPLICIT_EXPERIMENT_CONDITION_BLANK" for name in DEPARTMENT_FIELDS}
    )
    mismatched = [name for name in OFFICIAL_HEADER if decisions[name] != expected[name]]
    if mismatched:
        raise JdlGeneratorAuthored1111Error(
            "field decision does not match the controlled experiment: "
            + ", ".join(mismatched)
        )


def _validate_exact_keys(
    label: str,
    values: dict[str, Any],
    expected: tuple[str, ...],
) -> None:
    missing = sorted(set(expected) - set(values))
    extra = sorted(set(values) - set(expected))
    if missing or extra:
        raise JdlGeneratorAuthored1111Error(
            f"{label} must explicitly cover all official columns; "
            f"missing={missing}, extra={extra}"
        )


def _validate_date(jdl_date: str, iso_date: str) -> None:
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError as exc:
        raise JdlGeneratorAuthored1111Error("journal_date_iso must be YYYY-MM-DD") from exc
    if jdl_date != parsed.strftime("%Y%m%d"):
        raise JdlGeneratorAuthored1111Error("JDL date must match ISO date as YYYYMMDD")


def _validate_text_lengths(columns: dict[str, str]) -> None:
    for name, field in OFFICIAL_FIELDS.items():
        value = columns[name]
        if field.data_type == "文字" and field.max_length is not None:
            if len(value) > field.max_length:
                raise JdlGeneratorAuthored1111Error(
                    f"{name} must be at most {field.max_length} characters"
                )


def _amount(value: str, label: str) -> Decimal:
    if not value or not value.isdigit() or len(value) > 12:
        raise JdlGeneratorAuthored1111Error(
            f"{label} must be an explicit integer amount up to 12 digits"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise JdlGeneratorAuthored1111Error(f"{label} is not parseable") from exc


def _require_blank(columns: dict[str, str], fields: tuple[str, ...], label: str) -> None:
    populated = [name for name in fields if columns[name]]
    if populated:
        raise JdlGeneratorAuthored1111Error(
            f"{label} fields must be explicitly blank: {populated}"
        )


def _require_all_true(
    label: str,
    values: dict[str, bool],
    required: tuple[str, ...],
) -> None:
    missing = [key for key in required if key not in values]
    unconfirmed = [key for key in required if values.get(key) is not True]
    if missing or unconfirmed:
        raise JdlGeneratorAuthored1111Error(
            f"{label} is incomplete; missing={missing}, unconfirmed={unconfirmed}"
        )


def _all_true(values: dict[str, bool], required: tuple[str, ...]) -> bool:
    return all(values.get(key) is True for key in required)


def _validate_paths(
    output_path: Path,
    report_path: Path,
    manifest_path: Path,
    comparison_source: Path,
) -> None:
    for path in (output_path, report_path, manifest_path):
        if not _is_private_path(path, experiments=True):
            raise JdlGeneratorAuthored1111Error(
                "all output must be under data/private/experiments"
            )
        if path.exists():
            raise JdlGeneratorAuthored1111Error(f"output already exists: {path.name}")
    if not _is_private_path(comparison_source, experiments=False):
        raise JdlGeneratorAuthored1111Error("comparison source must be under data/private")
    if not comparison_source.is_file():
        raise JdlGeneratorAuthored1111Error("comparison source does not exist")
    if output_path.resolve() == comparison_source.resolve():
        raise JdlGeneratorAuthored1111Error("output and comparison source must differ")


def _is_private_path(path: Path, experiments: bool) -> bool:
    resolved_parts = path.resolve().parts
    required = ("data", "private", "experiments") if experiments else ("data", "private")
    return any(
        resolved_parts[index:index + len(required)] == required
        for index in range(len(resolved_parts) - len(required) + 1)
    )


def _data_row_bytes(path: Path) -> bytes:
    lines = path.read_bytes().splitlines(keepends=True)
    if len(lines) != 2:
        raise JdlGeneratorAuthored1111Error("candidate physical row count is not two")
    return lines[1]


def _source_data_row_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    position = 0
    header_offset: int | None = None
    for line in raw.splitlines(keepends=True):
        body = _without_line_ending(line)
        try:
            row = next(csv.reader([body.decode("cp932")], strict=True))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise JdlGeneratorAuthored1111Error(
                "comparison source is not a parseable CP932 CSV"
            ) from exc
        if tuple(row) == OFFICIAL_HEADER:
            if header_offset is not None:
                raise JdlGeneratorAuthored1111Error(
                    "comparison source has multiple official headers"
                )
            header_offset = position
        position += len(line)
    if header_offset is None:
        raise JdlGeneratorAuthored1111Error(
            "comparison source does not contain the official header"
        )
    suffix_lines = raw[header_offset:].splitlines(keepends=True)
    if len(suffix_lines) != 2:
        raise JdlGeneratorAuthored1111Error(
            "comparison source must contain one data row after the official header"
        )
    return suffix_lines[1]


def _without_line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\r", b"\n")):
        return line[:-1]
    return line


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private, generator-authored JDL 1111 import candidate."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--comparison-source", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = generate_candidate(
            load_config(args.config),
            comparison_source=args.comparison_source,
            output_dir=args.output_dir,
        )
    except (OSError, KeyError, json.JSONDecodeError, JdlGeneratorAuthored1111Error) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result.report.to_privacy_safe_dict(), ensure_ascii=False, indent=2))
    print(f"csv: {result.csv_path}")
    print(f"report: {result.report_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

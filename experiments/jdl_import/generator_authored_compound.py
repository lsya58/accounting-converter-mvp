from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)

from .generator_authored_1111 import (
    ACCOUNT_CODE_OR_FORMAL_FIELDS,
    DEPARTMENT_FIELDS,
    OFFICIAL_HEADER,
    SUBACCOUNT_FIELDS,
    TAX_FIELDS,
    _amount,
    _validate_date,
    _validate_exact_keys,
    _validate_text_lengths,
    _write_json_exclusive,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-COMPOUND-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_COMPOUND_UNTESTED"
EVIDENCE_ID = "EVID-JDL-COMPOUND-HAND-1110-1100-1101-001"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_compound"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_compound_candidate.csv"
EXPECTED_FLAGS = ("1110", "1100", "1101")

TARGET_VALIDATION_KEYS = (
    "all_account_names_exist_in_target_master",
    "account_identifiers_exactly_confirmed",
    "no_fuzzy_matching_or_auto_replacement",
)
EXPERIMENT_VALIDATION_KEYS = (
    "company_tax_processing_confirmed_exempt",
    "subaccounts_intentionally_absent",
    "department_processing_confirmed_disabled",
    "tax_fields_intentionally_blank",
    "transaction_accounts_intentionally_blank",
    "voucher_field_intentionally_blank_from_official_optional_rule",
    "missing_side_zero_amount_grounded_by_manual_and_observed_export",
    "reexport_zero_not_promoted_to_optional_fields",
    "source_jdl_rows_not_used_for_construction",
)
ALLOWED_DECISIONS = frozenset(
    {
        "EXPLICIT_EXPERIMENT_INPUT",
        "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
        "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
        "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
        "OFFICIAL_DOCUMENTED_EXEMPT_BLANK",
        "EXPLICIT_EXPERIMENT_CONDITION_BLANK",
        "OFFICIAL_REQUIRED_AMOUNT_AND_OBSERVED_MISSING_SIDE_ZERO",
    }
)


class JdlGeneratorAuthoredCompoundError(ValueError):
    pass


@dataclass(frozen=True)
class JdlGeneratorAuthoredCompoundConfig:
    rows: tuple[dict[str, str], ...]
    field_decisions: tuple[dict[str, str], ...]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    experiment_validation: dict[str, bool]
    source_observation: dict[str, Any]
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthoredCompoundResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: dict[str, Any]


def load_config(path: Path) -> JdlGeneratorAuthoredCompoundConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return JdlGeneratorAuthoredCompoundConfig(
        rows=tuple(dict(row) for row in payload["rows"]),
        field_decisions=tuple(
            dict(decisions) for decisions in payload["field_decisions"]
        ),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        experiment_validation=dict(payload["experiment_validation"]),
        source_observation=dict(payload["source_observation"]),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthoredCompoundConfig,
    observation_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthoredCompoundResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    try:
        _validate_paths(output_path, report_path, manifest_path, observation_source)
        _validate_config(config)
        _validate_observation_source(observation_source, config.source_observation)
    except ValueError as exc:
        raise JdlGeneratorAuthoredCompoundError(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    serialized_rows = [
        tuple(row[name] for name in OFFICIAL_HEADER) for row in config.rows
    ]
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(
                (OFFICIAL_HEADER, *serialized_rows)
            )
        report = validate_candidate(output_path, config, observation_source)
        if report["errors"]:
            raise JdlGeneratorAuthoredCompoundError("; ".join(report["errors"]))
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
                "source_jdl_rows_used_for_construction": False,
                "production_ready": False,
            },
        )
    except Exception:
        for path in (output_path, report_path, manifest_path):
            path.unlink(missing_ok=True)
        raise
    return JdlGeneratorAuthoredCompoundResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def validate_candidate(
    path: Path,
    config: JdlGeneratorAuthoredCompoundConfig,
    observation_source: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        errors.append("BOM must not be present")
    without_crlf = raw.replace(b"\r\n", b"")
    if raw.count(b"\r\n") != 4 or b"\n" in without_crlf or b"\r" in without_crlf:
        errors.append("candidate must contain four CRLF-terminated rows")
    try:
        text = raw.decode("cp932")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error):
        rows = []
        errors.append("candidate must be parseable CP932 CSV")

    expected_rows = [
        [row[name] for name in OFFICIAL_HEADER] for row in config.rows
    ]
    if len(rows) != 4:
        errors.append("candidate must contain one header and three data rows")
    elif tuple(rows[0]) != OFFICIAL_HEADER:
        errors.append("first physical row must be the exact official header")
    elif any(len(row) != 30 for row in rows[1:]):
        errors.append("every data row must contain exactly 30 columns")
    elif rows[1:] != expected_rows:
        errors.append("generated rows differ from explicit config")

    analysis = JdlCsvStructuralAnalyzer(
        observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
    ).analyze_path(path)
    if analysis.analysis_errors:
        errors.extend(item.rule_id for item in analysis.analysis_errors)
    if analysis.encoding != "cp932" or analysis.has_bom:
        errors.append("analyzer encoding/BOM result does not match")
    if analysis.line_ending != "CRLF":
        errors.append("analyzer line-ending result does not match")
    if analysis.header_columns != OFFICIAL_HEADER:
        errors.append("analyzer header does not match official header")
    if analysis.data_record_count != 3:
        errors.append("analyzer must find exactly three data records")
    if tuple(flag for row in config.rows for flag in (row["//識別フラグ"],)) != EXPECTED_FLAGS:
        errors.append("candidate flag sequence does not match")
    groups = analysis.observed_grouping_summary.candidates
    if len(groups) != 1:
        errors.append("analyzer must find one group candidate")
    elif not (
        groups[0].valid_sequence
        and groups[0].same_date
        and groups[0].balanced
        and groups[0].identifier_flags == EXPECTED_FLAGS
    ):
        errors.append("observed group candidate validation failed")
    elif groups[0].same_voucher_number is not False:
        errors.append("blank-voucher candidate must remain unresolved before runtime")

    candidate_rows = _data_row_bytes(path)
    source_rows = _source_data_row_bytes(observation_source)
    source_identical = candidate_rows == source_rows
    if source_identical:
        errors.append("generator-authored rows must not copy source JDL rows")
    row_copy_count = sum(row in source_rows for row in candidate_rows)
    if row_copy_count:
        errors.append("no candidate data row may be byte-identical to a source row")

    debit_total, credit_total = _totals(config.rows)
    return {
        "experiment_id": EXPERIMENT_ID,
        "evidence_id": EVIDENCE_ID,
        "status": EXPERIMENT_STATUS,
        "success": not errors,
        "errors": errors,
        "output_file": path.name,
        "record_count": analysis.data_record_count,
        "column_count": analysis.header_column_count,
        "identifier_flags": dict(analysis.identifier_flag_counts),
        "sequence": list(EXPECTED_FLAGS),
        "group_candidate_count": len(groups),
        "same_voucher_identity": len({row["伝番"] for row in config.rows}) == 1,
        "voucher_representation": "EXPLICITLY_BLANK_OPTIONAL_FIELD",
        "voucher_grouping_status": "RUNTIME_VERIFICATION_PENDING",
        "same_date": len({row["日付"] for row in config.rows}) == 1,
        "balanced": debit_total == credit_total,
        "target_master_validation_passed": _all_true(
            config.target_master_validation, TARGET_VALIDATION_KEYS
        ),
        "experiment_validation_passed": _all_true(
            config.experiment_validation, EXPERIMENT_VALIDATION_KEYS
        ),
        "all_columns_and_decisions_explicit": all(
            len(row) == 30 and len(decisions) == 30
            for row, decisions in zip(config.rows, config.field_decisions, strict=True)
        ),
        "source_rows_byte_identical": source_identical,
        "source_row_copy_count": row_copy_count,
        "source_jdl_rows_used_for_construction": False,
        "production_ready": False,
        "privacy_note": (
            "科目名、摘要、日付、個別金額、伝番、raw CSV row、source pathは出力しません。"
        ),
    }


def _validate_config(config: JdlGeneratorAuthoredCompoundConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthoredCompoundError("experiment identity/status mismatch")
    if len(config.rows) != 3 or len(config.field_decisions) != 3:
        raise JdlGeneratorAuthoredCompoundError("exactly three explicit rows are required")
    for row, decisions in zip(config.rows, config.field_decisions, strict=True):
        _validate_exact_keys("row", row, OFFICIAL_HEADER)
        _validate_exact_keys("field_decisions", decisions, OFFICIAL_HEADER)
        if not all(isinstance(value, str) for value in row.values()):
            raise JdlGeneratorAuthoredCompoundError("all field values must be strings")
        if set(decisions.values()) - ALLOWED_DECISIONS:
            raise JdlGeneratorAuthoredCompoundError("unsupported field decision source")
        if any("\r" in value or "\n" in value for value in row.values()):
            raise JdlGeneratorAuthoredCompoundError("embedded newline is unsupported")
        _validate_text_lengths(row)
        _validate_date(row["日付"], config.journal_date_iso)

    flags = tuple(row["//識別フラグ"] for row in config.rows)
    if flags != EXPECTED_FLAGS:
        raise JdlGeneratorAuthoredCompoundError("flag sequence must be 1110/1100/1101")
    if any(row["伝番"] for row in config.rows):
        raise JdlGeneratorAuthoredCompoundError(
            "voucher must be explicitly blank; auto-number behavior is not assumed"
        )
    if len({row["日付"] for row in config.rows}) != 1:
        raise JdlGeneratorAuthoredCompoundError("all rows must share one date")
    _validate_decisions(config)

    first, middle, last = config.rows
    if any(first[name] for name in ACCOUNT_CODE_OR_FORMAL_FIELDS):
        raise JdlGeneratorAuthoredCompoundError("candidate uses account names only")
    if not first["借方科目名称"] or not first["貸方科目名称"]:
        raise JdlGeneratorAuthoredCompoundError("first row must have both account names")
    for row in (middle, last):
        if any(row[name] for name in ("借方科目", "借方科目名称", "借方科目正式名称")):
            raise JdlGeneratorAuthoredCompoundError("later rows must have blank debit account")
        if row["借方金額"] != "0":
            raise JdlGeneratorAuthoredCompoundError("later debit amount must be explicit zero")
        if any(row[name] for name in ("貸方科目", "貸方科目正式名称")):
            raise JdlGeneratorAuthoredCompoundError("candidate uses credit account names only")
        if not row["貸方科目名称"]:
            raise JdlGeneratorAuthoredCompoundError("later credit account name is required")
        if row["摘要"]:
            raise JdlGeneratorAuthoredCompoundError("later descriptions must be explicit blank")
    if not first["摘要"]:
        raise JdlGeneratorAuthoredCompoundError("first description is required")

    for row in config.rows:
        _require_blank(row, SUBACCOUNT_FIELDS, "subaccount")
        _require_blank(row, TAX_FIELDS, "tax/transaction account")
        _require_blank(row, DEPARTMENT_FIELDS, "department")
    debit_total, credit_total = _totals(config.rows)
    if debit_total != credit_total:
        raise JdlGeneratorAuthoredCompoundError("group debit and credit totals must balance")
    _require_all_true(config.target_master_validation, TARGET_VALIDATION_KEYS)
    _require_all_true(config.experiment_validation, EXPERIMENT_VALIDATION_KEYS)


def _validate_decisions(config: JdlGeneratorAuthoredCompoundConfig) -> None:
    for index, (row, decisions) in enumerate(
        zip(config.rows, config.field_decisions, strict=True)
    ):
        for name in OFFICIAL_HEADER:
            decision = decisions[name]
            if name == "伝番" and decision != "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK":
                raise JdlGeneratorAuthoredCompoundError("voucher decision must remain explicit")
            if name in TAX_FIELDS and decision != "OFFICIAL_DOCUMENTED_EXEMPT_BLANK":
                raise JdlGeneratorAuthoredCompoundError("tax decisions must remain explicit")
            if name in SUBACCOUNT_FIELDS + DEPARTMENT_FIELDS and decision != "EXPLICIT_EXPERIMENT_CONDITION_BLANK":
                raise JdlGeneratorAuthoredCompoundError("master-field decisions must remain explicit")
        if index > 0 and decisions["借方金額"] != "OFFICIAL_REQUIRED_AMOUNT_AND_OBSERVED_MISSING_SIDE_ZERO":
            raise JdlGeneratorAuthoredCompoundError("missing-side zero requires explicit evidence")


def _validate_observation_source(path: Path, expected: dict[str, Any]) -> None:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise JdlGeneratorAuthoredCompoundError("observation source must be BOM-less")
    if raw.count(b"\r\n") != 7 or raw.replace(b"\r\n", b"").find(b"\n") >= 0:
        raise JdlGeneratorAuthoredCompoundError("observation source must use seven CRLF rows")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise JdlGeneratorAuthoredCompoundError("observation source is invalid") from exc
    if len(rows) != 7 or tuple(rows[3]) != OFFICIAL_HEADER:
        raise JdlGeneratorAuthoredCompoundError("observation source header structure differs")
    data = rows[4:]
    if any(len(row) != 30 for row in data):
        raise JdlGeneratorAuthoredCompoundError("observation source rows must have 30 columns")
    observed = {
        "flags": [row[0] for row in data],
        "voucher_numbers": [row[1] for row in data],
        "dates": [row[2] for row in data],
        "debit_amounts": [row[11] for row in data],
        "credit_amounts": [row[21] for row in data],
        "debit_account_names": [row[4] for row in data],
        "credit_account_names": [row[14] for row in data],
        "description_presence": [bool(row[23]) for row in data],
    }
    if observed != expected:
        raise JdlGeneratorAuthoredCompoundError("observation source differs from explicit evidence")
    if len(set(observed["voucher_numbers"])) != 1 or len(set(observed["dates"])) != 1:
        raise JdlGeneratorAuthoredCompoundError("source voucher/date identity differs")
    debit = sum(Decimal(value) for value in observed["debit_amounts"])
    credit = sum(Decimal(value) for value in observed["credit_amounts"])
    if debit != credit:
        raise JdlGeneratorAuthoredCompoundError("source group is not balanced")


def _totals(rows: tuple[dict[str, str], ...]) -> tuple[Decimal, Decimal]:
    debit = sum((_amount(row["借方金額"], "借方金額") for row in rows), Decimal(0))
    credit = sum((_amount(row["貸方金額"], "貸方金額") for row in rows), Decimal(0))
    return debit, credit


def _require_blank(row: dict[str, str], fields: tuple[str, ...], label: str) -> None:
    populated = [name for name in fields if row[name]]
    if populated:
        raise JdlGeneratorAuthoredCompoundError(f"{label} fields must be blank: {populated}")


def _require_all_true(values: dict[str, bool], required: tuple[str, ...]) -> None:
    missing = [name for name in required if values.get(name) is not True]
    if missing:
        raise JdlGeneratorAuthoredCompoundError(f"required confirmations missing: {missing}")


def _all_true(values: dict[str, bool], required: tuple[str, ...]) -> bool:
    return all(values.get(name) is True for name in required)


def _validate_paths(
    output_path: Path,
    report_path: Path,
    manifest_path: Path,
    source_path: Path,
) -> None:
    for path in (output_path, report_path, manifest_path):
        if not _is_private(path, experiments=True):
            raise JdlGeneratorAuthoredCompoundError("output must remain under data/private/experiments")
        if path.exists():
            raise JdlGeneratorAuthoredCompoundError(f"output already exists: {path.name}")
    if not _is_private(source_path, experiments=False) or not source_path.is_file():
        raise JdlGeneratorAuthoredCompoundError("observation source must exist under data/private")


def _is_private(path: Path, experiments: bool) -> bool:
    parts = path.resolve().parts
    required = ("data", "private", "experiments") if experiments else ("data", "private")
    return any(parts[index:index + len(required)] == required for index in range(len(parts)))


def _data_row_bytes(path: Path) -> tuple[bytes, ...]:
    lines = path.read_bytes().splitlines(keepends=True)
    if len(lines) != 4:
        raise JdlGeneratorAuthoredCompoundError("candidate physical row count differs")
    return tuple(lines[1:])


def _source_data_row_bytes(path: Path) -> tuple[bytes, ...]:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    header_indexes = []
    for index, line in enumerate(lines):
        body = line[:-2] if line.endswith(b"\r\n") else line.rstrip(b"\r\n")
        try:
            row = next(csv.reader([body.decode("cp932")], strict=True))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise JdlGeneratorAuthoredCompoundError("source CSV cannot be parsed") from exc
        if tuple(row) == OFFICIAL_HEADER:
            header_indexes.append(index)
    if len(header_indexes) != 1 or len(lines[header_indexes[0] + 1:]) != 3:
        raise JdlGeneratorAuthoredCompoundError("source must contain one header and three data rows")
    return tuple(lines[header_indexes[0] + 1:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a private experimental JDL compound candidate.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--observation-source", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = generate_candidate(
            load_config(args.config), args.observation_source, args.output_dir
        )
    except (OSError, KeyError, json.JSONDecodeError, JdlGeneratorAuthoredCompoundError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"csv: {result.csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

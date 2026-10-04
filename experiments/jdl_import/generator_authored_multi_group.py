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
    DEFAULT_OUTPUT_NAME as SIMPLE_DEFAULT_OUTPUT_NAME,
    EXPERIMENT_ID as SIMPLE_EXPERIMENT_ID,
    EXPERIMENT_STATUS as SIMPLE_EXPERIMENT_STATUS,
    OFFICIAL_HEADER,
    JdlGeneratorAuthored1111Config,
    _amount,
    _validate_config as _validate_simple_config,
    _validate_exact_keys,
    _write_json_exclusive,
    load_config as load_simple_config,
)
from .generator_authored_compound import (
    EXPERIMENT_ID as COMPOUND_EXPERIMENT_ID,
    EXPERIMENT_STATUS as COMPOUND_EXPERIMENT_STATUS,
    JdlGeneratorAuthoredCompoundConfig,
    _validate_config as _validate_compound_config,
    load_config as load_compound_config,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-SIMPLE-PLUS-COMPOUND-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_SIMPLE_PLUS_COMPOUND_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_multi_group"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_simple_plus_compound_candidate.csv"
EXPECTED_FLAGS = ("1111", "1110", "1100", "1101")


class JdlGeneratorAuthoredMultiGroupError(ValueError):
    pass


@dataclass(frozen=True)
class JdlGeneratorAuthoredMultiGroupConfig:
    simple: JdlGeneratorAuthored1111Config
    compound: JdlGeneratorAuthoredCompoundConfig
    journal_date_iso: str
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthoredMultiGroupResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    report: dict[str, Any]


def load_config(path: Path) -> JdlGeneratorAuthoredMultiGroupConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "simple_base_config" in payload:
        return _load_composed_config(payload, path)
    simple_payload = payload["simple"]
    compound_payload = payload["compound"]
    simple = JdlGeneratorAuthored1111Config(
        jdl_columns=dict(simple_payload["jdl_columns"]),
        field_decisions=dict(simple_payload["field_decisions"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(simple_payload["target_master_validation"]),
        tax_validation=dict(simple_payload["tax_validation"]),
        output_name=SIMPLE_DEFAULT_OUTPUT_NAME,
        experiment_id=SIMPLE_EXPERIMENT_ID,
        status=SIMPLE_EXPERIMENT_STATUS,
    )
    compound = JdlGeneratorAuthoredCompoundConfig(
        rows=tuple(dict(row) for row in compound_payload["rows"]),
        field_decisions=tuple(
            dict(decisions) for decisions in compound_payload["field_decisions"]
        ),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(compound_payload["target_master_validation"]),
        experiment_validation=dict(compound_payload["experiment_validation"]),
        source_observation={},
        experiment_id=COMPOUND_EXPERIMENT_ID,
        status=COMPOUND_EXPERIMENT_STATUS,
    )
    return JdlGeneratorAuthoredMultiGroupConfig(
        simple=simple,
        compound=compound,
        journal_date_iso=payload["journal_date_iso"],
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def _load_composed_config(
    payload: dict[str, Any],
    config_path: Path,
) -> JdlGeneratorAuthoredMultiGroupConfig:
    simple_path = _resolve_private_config(config_path, payload["simple_base_config"])
    compound_path = _resolve_private_config(
        config_path, payload["compound_base_config"]
    )
    simple_base = load_simple_config(simple_path)
    compound_base = load_compound_config(compound_path)

    simple_overrides = dict(payload["simple_overrides"])
    expected_simple_overrides = {"日付", "借方金額", "貸方金額", "摘要"}
    if set(simple_overrides) != expected_simple_overrides:
        raise JdlGeneratorAuthoredMultiGroupError(
            "simple overrides must explicitly contain date, both amounts, and description"
        )
    compound_overrides = tuple(
        dict(overrides) for overrides in payload["compound_row_overrides"]
    )
    if len(compound_overrides) != 3 or any(
        set(overrides) != ({"日付", "摘要"} if index == 0 else {"日付"})
        for index, overrides in enumerate(compound_overrides)
    ):
        raise JdlGeneratorAuthoredMultiGroupError(
            "compound overrides must change only all dates and first description"
        )

    simple_columns = dict(simple_base.jdl_columns)
    simple_columns.update(simple_overrides)
    compound_rows = tuple(
        dict(row, **overrides)
        for row, overrides in zip(
            compound_base.rows, compound_overrides, strict=True
        )
    )
    journal_date_iso = payload["journal_date_iso"]
    return JdlGeneratorAuthoredMultiGroupConfig(
        simple=JdlGeneratorAuthored1111Config(
            jdl_columns=simple_columns,
            field_decisions=dict(simple_base.field_decisions),
            journal_date_iso=journal_date_iso,
            target_master_validation=dict(simple_base.target_master_validation),
            tax_validation=dict(simple_base.tax_validation),
            experiment_id=SIMPLE_EXPERIMENT_ID,
            status=SIMPLE_EXPERIMENT_STATUS,
        ),
        compound=JdlGeneratorAuthoredCompoundConfig(
            rows=compound_rows,
            field_decisions=tuple(
                dict(decisions) for decisions in compound_base.field_decisions
            ),
            journal_date_iso=journal_date_iso,
            target_master_validation=dict(compound_base.target_master_validation),
            experiment_validation=dict(compound_base.experiment_validation),
            source_observation={},
            experiment_id=COMPOUND_EXPERIMENT_ID,
            status=COMPOUND_EXPERIMENT_STATUS,
        ),
        journal_date_iso=journal_date_iso,
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def _resolve_private_config(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    parts = path.resolve().parts
    required = ("data", "private")
    if not any(
        parts[index:index + len(required)] == required
        for index in range(len(parts))
    ) or not path.is_file():
        raise JdlGeneratorAuthoredMultiGroupError(
            "base configs must exist under data/private"
        )
    return path


def generate_candidate(
    config: JdlGeneratorAuthoredMultiGroupConfig,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> JdlGeneratorAuthoredMultiGroupResult:
    output_path = output_dir / config.output_name
    report_path = output_path.with_suffix(".report.json")
    manifest_path = output_dir / "experiment_manifest.json"
    _validate_paths(output_path, report_path, manifest_path)
    _validate_config(config)

    rows = _rows(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(
                (OFFICIAL_HEADER, *rows)
            )
        report = validate_candidate(output_path, config)
        if report["errors"]:
            raise JdlGeneratorAuthoredMultiGroupError("; ".join(report["errors"]))
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
    return JdlGeneratorAuthoredMultiGroupResult(
        csv_path=output_path,
        report_path=report_path,
        manifest_path=manifest_path,
        report=report,
    )


def validate_candidate(
    path: Path,
    config: JdlGeneratorAuthoredMultiGroupConfig,
) -> dict[str, Any]:
    errors: list[str] = []
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        errors.append("BOM must not be present")
    without_crlf = raw.replace(b"\r\n", b"")
    if raw.count(b"\r\n") != 5 or b"\n" in without_crlf or b"\r" in without_crlf:
        errors.append("candidate must contain five CRLF-terminated rows")
    try:
        rows = list(
            csv.reader(io.StringIO(raw.decode("cp932"), newline=""), strict=True)
        )
    except (UnicodeDecodeError, csv.Error):
        rows = []
        errors.append("candidate must be parseable CP932 CSV")

    expected_rows = [list(row) for row in _rows(config)]
    if len(rows) != 5:
        errors.append("candidate must contain one header and four data records")
    elif tuple(rows[0]) != OFFICIAL_HEADER:
        errors.append("first physical row must be the exact official header")
    elif any(len(row) != 30 for row in rows[1:]):
        errors.append("every data record must contain exactly 30 columns")
    elif rows[1:] != expected_rows:
        errors.append("generated records differ from explicit config")

    analysis = JdlCsvStructuralAnalyzer(
        observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
    ).analyze_path(path)
    if analysis.analysis_errors:
        errors.extend(item.rule_id for item in analysis.analysis_errors)
    if analysis.encoding != "cp932" or analysis.has_bom:
        errors.append("analyzer encoding/BOM result does not match")
    if analysis.line_ending != "CRLF":
        errors.append("analyzer line ending does not match")
    if analysis.header_columns != OFFICIAL_HEADER:
        errors.append("analyzer header does not match official header")
    if analysis.data_record_count != 4:
        errors.append("analyzer must find four data records")
    group_candidates = analysis.observed_grouping_summary.candidates
    if len(group_candidates) != 2:
        errors.append("analyzer must preserve two structural group candidates")
    elif (
        group_candidates[0].identifier_flags != ("1111",)
        or group_candidates[1].identifier_flags != ("1110", "1100", "1101")
    ):
        errors.append("analyzer group candidate order differs")

    configured_rows = (config.simple.jdl_columns, *config.compound.rows)
    flags = tuple(row["//識別フラグ"] for row in configured_rows)
    dates = tuple(row["日付"] for row in configured_rows)
    vouchers = tuple(row["伝番"] for row in configured_rows)
    if flags != EXPECTED_FLAGS:
        errors.append("flag order must be 1111/1110/1100/1101")
    if len(set(dates)) != 1:
        errors.append("all records must use the same date")
    if any(vouchers):
        errors.append("all voucher fields must be explicitly blank")

    simple_debit = _amount(config.simple.jdl_columns["借方金額"], "借方金額")
    simple_credit = _amount(config.simple.jdl_columns["貸方金額"], "貸方金額")
    compound_debit = sum(
        (_amount(row["借方金額"], "借方金額") for row in config.compound.rows),
        Decimal(0),
    )
    compound_credit = sum(
        (_amount(row["貸方金額"], "貸方金額") for row in config.compound.rows),
        Decimal(0),
    )
    if simple_debit != simple_credit:
        errors.append("simple group must balance")
    if compound_debit != compound_credit:
        errors.append("compound group must balance")

    return {
        "experiment_id": EXPERIMENT_ID,
        "status": EXPERIMENT_STATUS,
        "success": not errors,
        "errors": errors,
        "output_file": path.name,
        "record_count": analysis.data_record_count,
        "column_count": analysis.header_column_count,
        "sequence": list(EXPECTED_FLAGS),
        "expected_group_count": 2,
        "structural_group_candidate_count": len(group_candidates),
        "structural_group_candidate_statuses": [
            candidate.status.value for candidate in group_candidates
        ],
        "simple_group_balanced": simple_debit == simple_credit,
        "compound_group_balanced": compound_debit == compound_credit,
        "same_date": len(set(dates)) == 1,
        "all_voucher_fields_blank": not any(vouchers),
        "all_columns_and_decisions_explicit": (
            len(config.simple.jdl_columns) == 30
            and len(config.simple.field_decisions) == 30
            and all(
                len(row) == 30 and len(decisions) == 30
                for row, decisions in zip(
                    config.compound.rows,
                    config.compound.field_decisions,
                    strict=True,
                )
            )
        ),
        "source_jdl_rows_used_for_construction": False,
        "multi_group_boundary_status": "RUNTIME_VERIFICATION_PENDING",
        "blank_voucher_multi_group_safety_proven": False,
        "production_ready": False,
        "privacy_note": (
            "科目名、摘要、日付、個別金額、伝番、raw CSV rowは出力しません。"
        ),
    }


def _validate_config(config: JdlGeneratorAuthoredMultiGroupConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID or config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthoredMultiGroupError("experiment identity/status mismatch")
    try:
        _validate_simple_config(config.simple)
        _validate_compound_config(config.compound)
    except ValueError as exc:
        raise JdlGeneratorAuthoredMultiGroupError(str(exc)) from exc
    if (
        config.simple.journal_date_iso != config.journal_date_iso
        or config.compound.journal_date_iso != config.journal_date_iso
    ):
        raise JdlGeneratorAuthoredMultiGroupError("child journal dates must match")
    rows = (config.simple.jdl_columns, *config.compound.rows)
    for row in rows:
        _validate_exact_keys("row", row, OFFICIAL_HEADER)
    if tuple(row["//識別フラグ"] for row in rows) != EXPECTED_FLAGS:
        raise JdlGeneratorAuthoredMultiGroupError(
            "flag order must be 1111/1110/1100/1101"
        )
    if len({row["日付"] for row in rows}) != 1:
        raise JdlGeneratorAuthoredMultiGroupError("all records must share one date")
    if any(row["伝番"] for row in rows):
        raise JdlGeneratorAuthoredMultiGroupError(
            "all voucher fields must remain explicitly blank"
        )


def _rows(config: JdlGeneratorAuthoredMultiGroupConfig) -> tuple[tuple[str, ...], ...]:
    dictionaries = (config.simple.jdl_columns, *config.compound.rows)
    return tuple(tuple(row[name] for name in OFFICIAL_HEADER) for row in dictionaries)


def _validate_paths(output_path: Path, report_path: Path, manifest_path: Path) -> None:
    for path in (output_path, report_path, manifest_path):
        parts = path.resolve().parts
        required = ("data", "private", "experiments")
        if not any(
            parts[index:index + len(required)] == required
            for index in range(len(parts))
        ):
            raise JdlGeneratorAuthoredMultiGroupError(
                "all output must remain under data/private/experiments"
            )
        if path.exists():
            raise JdlGeneratorAuthoredMultiGroupError(
                f"output already exists: {path.name}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a private JDL simple-plus-compound boundary experiment."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = generate_candidate(load_config(args.config), args.output_dir)
    except (OSError, KeyError, json.JSONDecodeError, JdlGeneratorAuthoredMultiGroupError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result.report, ensure_ascii=False, indent=2))
    print(f"csv: {result.csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

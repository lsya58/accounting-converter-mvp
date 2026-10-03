from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

from .exp01_candidate import (
    EXPERIMENT_ID as BASE_EXPERIMENT_ID,
    EXPERIMENT_STATUS as BASE_EXPERIMENT_STATUS,
    OFFICIAL_HEADER,
    JdlExp01CandidateConfig,
    JdlExp01CandidateError,
    JdlExp01GenerationResult,
    generate_exp01_candidate,
)


EXPERIMENT_ID = "JDL-GENERATOR-AUTHORED-1000-DEPARTMENT-01"
EXPERIMENT_STATUS = "GENERATOR_AUTHORED_1000_DEPARTMENT_UNTESTED"
DEFAULT_OUTPUT_DIR = Path(
    "data/private/experiments/jdl_import/generator_authored_1000_department"
)
DEFAULT_OUTPUT_NAME = "jdl_generator_authored_1000_department_candidate.csv"
DEPARTMENT_SIDE = "DEBIT"
EXPECTED_CHANGED_FIELDS = ("借方部門コード", "借方部門名称")
SUBACCOUNT_FIELDS = ("借方補助", "借方補助名称", "貸方補助", "貸方補助名称")
CREDIT_DEPARTMENT_FIELDS = ("貸方部門コード", "貸方部門名称")
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
DEPARTMENT_VALIDATION_KEYS = (
    "department_processing_enabled",
    "debit_department_exists_in_target_master",
    "credit_department_blank_or_exists_in_target_master",
    "no_fuzzy_matching_or_auto_replacement",
)


class JdlGeneratorAuthored1000DepartmentError(ValueError):
    pass


@dataclass(frozen=True)
class TargetDepartmentEvidence:
    department_code: str
    department_name: str
    short_name: str
    department_processing_enabled: bool
    confirmed_registered: bool
    no_fuzzy_matching: bool
    no_automatic_replacement: bool


@dataclass(frozen=True)
class JdlGeneratorAuthored1000DepartmentConfig:
    jdl_columns: dict[str, str]
    journal_date_iso: str
    target_master_validation: dict[str, bool]
    tax_validation: dict[str, bool]
    target_department_evidence: TargetDepartmentEvidence
    company_tax_processing: str = JdlTaxProcessingMode.EXEMPT.value
    output_name: str = DEFAULT_OUTPUT_NAME
    experiment_id: str = EXPERIMENT_ID
    status: str = EXPERIMENT_STATUS


@dataclass(frozen=True)
class JdlGeneratorAuthored1000DepartmentResult:
    csv_path: Path
    report_path: Path
    manifest_path: Path
    base_result: JdlExp01GenerationResult


def load_config(path: Path) -> JdlGeneratorAuthored1000DepartmentConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    evidence = payload["target_department_evidence"]
    return JdlGeneratorAuthored1000DepartmentConfig(
        jdl_columns=dict(payload["jdl_columns"]),
        journal_date_iso=payload["journal_date_iso"],
        target_master_validation=dict(payload["target_master_validation"]),
        tax_validation=dict(payload["tax_validation"]),
        target_department_evidence=TargetDepartmentEvidence(
            department_code=evidence["department_code"],
            department_name=evidence["department_name"],
            short_name=evidence["short_name"],
            department_processing_enabled=evidence["department_processing_enabled"],
            confirmed_registered=evidence["confirmed_registered"],
            no_fuzzy_matching=evidence["no_fuzzy_matching"],
            no_automatic_replacement=evidence["no_automatic_replacement"],
        ),
        company_tax_processing=payload.get(
            "company_tax_processing",
            JdlTaxProcessingMode.EXEMPT.value,
        ),
        output_name=payload.get("output_name", DEFAULT_OUTPUT_NAME),
        experiment_id=payload.get("experiment_id", EXPERIMENT_ID),
        status=payload.get("status", EXPERIMENT_STATUS),
    )


def generate_candidate(
    config: JdlGeneratorAuthored1000DepartmentConfig,
    comparison_source: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    config_path: Path | None = None,
) -> JdlGeneratorAuthored1000DepartmentResult:
    _validate_experiment_config(config, comparison_source)
    base_config = JdlExp01CandidateConfig(
        jdl_columns=dict(config.jdl_columns),
        journal_date_iso=config.journal_date_iso,
        target_master_validation=dict(config.target_master_validation),
        company_tax_processing=config.company_tax_processing,
        tax_validation=dict(config.tax_validation),
        output_name=config.output_name,
        experiment_id=BASE_EXPERIMENT_ID,
        status=BASE_EXPERIMENT_STATUS,
    )
    result: JdlExp01GenerationResult | None = None
    try:
        result = generate_exp01_candidate(
            base_config,
            output_dir=output_dir,
            overwrite=False,
            config_path=config_path,
        )
        _amend_privacy_safe_outputs(result, config)
    except Exception:
        if result is not None:
            for path in (result.csv_path, result.report_path, result.manifest_path):
                path.unlink(missing_ok=True)
        raise
    return JdlGeneratorAuthored1000DepartmentResult(
        csv_path=result.csv_path,
        report_path=result.report_path,
        manifest_path=result.manifest_path,
        base_result=result,
    )


def _validate_experiment_config(
    config: JdlGeneratorAuthored1000DepartmentConfig,
    comparison_source: Path,
) -> None:
    if config.experiment_id != EXPERIMENT_ID:
        raise JdlGeneratorAuthored1000DepartmentError(
            f"experiment_id must be {EXPERIMENT_ID}"
        )
    if config.status != EXPERIMENT_STATUS:
        raise JdlGeneratorAuthored1000DepartmentError(
            f"status must be {EXPERIMENT_STATUS}"
        )
    if set(config.jdl_columns) != set(OFFICIAL_HEADER):
        raise JdlGeneratorAuthored1000DepartmentError(
            "all 30 official columns must be explicitly configured"
        )
    columns = config.jdl_columns
    if columns["//識別フラグ"] != "1000":
        raise JdlGeneratorAuthored1000DepartmentError(
            "identifier flag must be 1000"
        )
    if config.company_tax_processing != JdlTaxProcessingMode.EXEMPT.value:
        raise JdlGeneratorAuthored1000DepartmentError(
            "department experiment requires confirmed exempt processing"
        )
    if any(columns[field] for field in SUBACCOUNT_FIELDS):
        raise JdlGeneratorAuthored1000DepartmentError(
            "all subaccount fields must remain blank"
        )
    if any(columns[field] for field in CREDIT_DEPARTMENT_FIELDS):
        raise JdlGeneratorAuthored1000DepartmentError(
            "credit department fields must remain blank"
        )
    if any(columns[field] for field in TAX_FIELDS):
        raise JdlGeneratorAuthored1000DepartmentError(
            "tax and transaction-account fields must remain blank"
        )
    _validate_target_department(config)
    _validate_only_department_changed(columns, comparison_source)


def _validate_target_department(
    config: JdlGeneratorAuthored1000DepartmentConfig,
) -> None:
    columns = config.jdl_columns
    evidence = config.target_department_evidence
    missing = [
        key
        for key in DEPARTMENT_VALIDATION_KEYS
        if key not in config.target_master_validation
    ]
    if missing:
        raise JdlGeneratorAuthored1000DepartmentError(
            "missing department validation confirmations: " + ", ".join(missing)
        )
    if any(
        config.target_master_validation[key] is not True
        for key in DEPARTMENT_VALIDATION_KEYS
    ):
        raise JdlGeneratorAuthored1000DepartmentError(
            "department validation confirmations must all be true"
        )
    confirmations = (
        evidence.department_processing_enabled,
        evidence.confirmed_registered,
        evidence.no_fuzzy_matching,
        evidence.no_automatic_replacement,
    )
    if not all(confirmations):
        raise JdlGeneratorAuthored1000DepartmentError(
            "department processing and target master must be explicitly confirmed"
        )
    if not all(
        (evidence.department_code, evidence.department_name, evidence.short_name)
    ):
        raise JdlGeneratorAuthored1000DepartmentError(
            "target department evidence must include code, name, and short name"
        )
    if (
        columns["借方部門コード"] != evidence.department_code
        or columns["借方部門名称"] != evidence.short_name
    ):
        raise JdlGeneratorAuthored1000DepartmentError(
            "debit department fields do not exactly match the confirmed target "
            "code and short-name representation"
        )
    key = MappingKey(
        mapping_type=MappingType.DEPARTMENT,
        source_value=evidence.short_name,
        side=DEPARTMENT_SIDE,
    )
    mapping = MappingValue(
        source_value=evidence.short_name,
        target_value=evidence.short_name,
        status=MappingStatus.USER_CONFIRMED,
        metadata={"evidence": "explicit_target_department_master"},
    )
    if key.source_value != mapping.source_value or not mapping.is_resolved:
        raise JdlGeneratorAuthored1000DepartmentError(
            "department mapping validation failed"
        )


def _validate_only_department_changed(
    columns: dict[str, str],
    comparison_source: Path,
) -> None:
    if not comparison_source.is_file():
        raise JdlGeneratorAuthored1000DepartmentError(
            "successful generator-authored 1000 comparison source is required"
        )
    rows = _read_rows(comparison_source)
    if len(rows) != 2 or tuple(rows[0]) != OFFICIAL_HEADER or len(rows[1]) != 30:
        raise JdlGeneratorAuthored1000DepartmentError(
            "comparison source must be a one-record official 30-column candidate"
        )
    if rows[1][0] != "1000":
        raise JdlGeneratorAuthored1000DepartmentError(
            "comparison source must use identifier flag 1000"
        )
    candidate_row = tuple(columns[field] for field in OFFICIAL_HEADER)
    changed = tuple(
        field
        for index, field in enumerate(OFFICIAL_HEADER)
        if rows[1][index] != candidate_row[index]
    )
    if changed != EXPECTED_CHANGED_FIELDS:
        raise JdlGeneratorAuthored1000DepartmentError(
            "only debit department code and name may differ from the successful "
            "generator-authored 1000 candidate"
        )


def _read_rows(path: Path) -> list[list[str]]:
    try:
        text = path.read_bytes().decode("cp932")
    except UnicodeDecodeError as exc:
        raise JdlGeneratorAuthored1000DepartmentError(
            "comparison source must be CP932-decodable"
        ) from exc
    try:
        return list(csv.reader(text.splitlines(), strict=True))
    except csv.Error as exc:
        raise JdlGeneratorAuthored1000DepartmentError(
            "comparison source must be valid CSV"
        ) from exc


def _amend_privacy_safe_outputs(
    result: JdlExp01GenerationResult,
    config: JdlGeneratorAuthored1000DepartmentConfig,
) -> None:
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    report.update(_privacy_safe_experiment_metadata(config))
    result.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest.update(_privacy_safe_experiment_metadata(config))
    validation = manifest.get("validation")
    if isinstance(validation, dict):
        validation.update(
            {
                "experiment_id": EXPERIMENT_ID,
                "status": EXPERIMENT_STATUS,
            }
        )
    manifest.update(
        {
            "actual_result": "UNTESTED",
            "construction_source": (
                "successful generator-authored 1000 explicit config plus "
                "explicit target department master evidence"
            ),
            "source_jdl_row_used_for_construction": False,
            "changed_from_successful_1000_fields": list(EXPECTED_CHANGED_FIELDS),
            "production_ready": False,
        }
    )
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _privacy_safe_experiment_metadata(
    config: JdlGeneratorAuthored1000DepartmentConfig,
) -> dict[str, Any]:
    evidence = config.target_department_evidence
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": EXPERIMENT_STATUS,
        "all_30_columns_explicit": set(config.jdl_columns) == set(OFFICIAL_HEADER),
        "department_master_validation": {
            "mapping_type": MappingType.DEPARTMENT.value,
            "side": DEPARTMENT_SIDE,
            "department_processing_enabled": evidence.department_processing_enabled,
            "target_master_confirmations_complete": all(
                config.target_master_validation.get(key) is True
                for key in DEPARTMENT_VALIDATION_KEYS
            ),
            "department_identifier_confirmed": bool(
                evidence.department_code and evidence.department_name
            ),
            "full_name_confirmed_but_not_emitted": bool(evidence.department_name),
            "csv_name_uses_confirmed_short_name": bool(evidence.short_name),
            "no_fuzzy_matching": evidence.no_fuzzy_matching,
            "no_automatic_replacement": evidence.no_automatic_replacement,
        },
        "privacy_note": (
            "Account, department, description, date, amount, and raw row values "
            "are omitted."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a scoped JDL flag-1000 debit-department candidate.",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--comparison-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = generate_candidate(
            load_config(args.config),
            args.comparison_source,
            output_dir=args.output_dir,
            config_path=args.config,
        )
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        JdlExp01CandidateError,
        JdlGeneratorAuthored1000DepartmentError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("JDL generator-authored 1000 + debit department candidate")
    print(f"status: {EXPERIMENT_STATUS}")
    print("success: True")
    print("records: 1")
    print("column_count: 30")
    print("department_side: DEBIT")
    print("department_master_validation: confirmed")
    print(f"csv: {result.csv_path}")
    print(f"report: {result.report_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

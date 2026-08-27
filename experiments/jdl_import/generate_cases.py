from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)


EXPERIMENT_IDS = (
    "EXP-01_minimal_simple",
    "EXP-02_with_description",
    "EXP-03_with_tax",
    "EXP-04_existing_subaccount",
    "EXP-05_nonexistent_subaccount",
    "EXP-06_observed_multi_record_sequence",
)


@dataclass(frozen=True)
class JdlImportExperimentConfig:
    debit_account_code: str
    debit_account_name: str
    credit_account_code: str
    credit_account_name: str
    amount: str = "1000"
    date: str = "2026/08/27"
    voucher_start: int = 9001
    description: str = "架空実験"
    tax_category: str = ""
    tax_amount: str = "0"
    existing_subaccount_code: str = ""
    existing_subaccount_name: str = ""
    nonexistent_subaccount_code: str = "X999"
    nonexistent_subaccount_name: str = "存在しない架空補助"


@dataclass(frozen=True)
class GeneratedExperiment:
    experiment_id: str
    csv_path: Path
    purpose: str
    changed_variable: str
    expected_observation: str


def load_config(path: Path) -> JdlImportExperimentConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return JdlImportExperimentConfig(**data)


def generate_all_cases(
    config: JdlImportExperimentConfig,
    output_dir: Path,
) -> list[GeneratedExperiment]:
    _validate_config(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    schema = jdl_ibex_cashbook_35_5_observed_schema()
    cases = [
        _minimal_simple(config, output_dir),
        _with_description(config, output_dir),
        _with_tax(config, output_dir),
        _existing_subaccount(config, output_dir),
        _nonexistent_subaccount(config, output_dir),
        _observed_multi_record_sequence(config, output_dir),
    ]
    for case in cases:
        _write_experiment_csv(schema.observed_header, case.csv_path, _rows_for_case(case, config))
    _write_manifest(output_dir / "experiment_manifest.json", cases, schema)
    return cases


def _minimal_simple(config: JdlImportExperimentConfig, output_dir: Path) -> GeneratedExperiment:
    return GeneratedExperiment(
        experiment_id="EXP-01_minimal_simple",
        csv_path=output_dir / "EXP-01_minimal_simple.csv",
        purpose="補助科目・部門・複雑な税情報なしの最小1レコードをJDL実機で確認する。",
        changed_variable="baseline",
        expected_observation="JDL実機で構文認識とマスター照合結果を確認する。取込可否は未確定。",
    )


def _with_description(config: JdlImportExperimentConfig, output_dir: Path) -> GeneratedExperiment:
    _ = config
    return GeneratedExperiment(
        experiment_id="EXP-02_with_description",
        csv_path=output_dir / "EXP-02_with_description.csv",
        purpose="EXP-01に対して摘要のみ追加した場合のJDL実機挙動を確認する。",
        changed_variable="description",
        expected_observation="摘要追加が構文・取込結果へ与える影響をJDL実機で確認する。取込可否は未確定。",
    )


def _with_tax(config: JdlImportExperimentConfig, output_dir: Path) -> GeneratedExperiment:
    _ = config
    return GeneratedExperiment(
        experiment_id="EXP-03_with_tax",
        csv_path=output_dir / "EXP-03_with_tax.csv",
        purpose="税区分・税額を指定した場合のJDL実機挙動を確認する。",
        changed_variable="tax_category,tax_amount",
        expected_observation="指定した税区分・税額がJDL側で認識されるか確認する。正式税コードは推測しない。",
    )


def _existing_subaccount(config: JdlImportExperimentConfig, output_dir: Path) -> GeneratedExperiment:
    _ = config
    return GeneratedExperiment(
        experiment_id="EXP-04_existing_subaccount",
        csv_path=output_dir / "EXP-04_existing_subaccount.csv",
        purpose="JDL側に事前登録した完全架空補助科目を指定した場合の取込挙動を確認する。",
        changed_variable="existing_subaccount",
        expected_observation="事前登録済み補助科目がJDL側で照合されるか確認する。取込可否は未確定。",
    )


def _nonexistent_subaccount(config: JdlImportExperimentConfig, output_dir: Path) -> GeneratedExperiment:
    _ = config
    return GeneratedExperiment(
        experiment_id="EXP-05_nonexistent_subaccount",
        csv_path=output_dir / "EXP-05_nonexistent_subaccount.csv",
        purpose="意図的に存在しない補助科目を指定し、JDLのエラー内容を確認する。",
        changed_variable="nonexistent_subaccount",
        expected_observation="JDLが補助科目不一致として拒否する可能性があるが、実機結果でのみ判定する。",
    )


def _observed_multi_record_sequence(
    config: JdlImportExperimentConfig,
    output_dir: Path,
) -> GeneratedExperiment:
    _ = config
    return GeneratedExperiment(
        experiment_id="EXP-06_observed_multi_record_sequence",
        csv_path=output_dir / "EXP-06_observed_multi_record_sequence.csv",
        purpose="1110 -> 1100* -> 1101 のObserved SequenceをJDL実機で確認する。",
        changed_variable="observed_identifier_sequence",
        expected_observation="Observed Behavior検証用。正式複合仕訳仕様とは断定しない。",
    )


def _rows_for_case(
    case: GeneratedExperiment,
    config: JdlImportExperimentConfig,
) -> list[dict[str, str]]:
    voucher = str(config.voucher_start + EXPERIMENT_IDS.index(case.experiment_id))
    if case.experiment_id == "EXP-02_with_description":
        return [_base_row(config, voucher, description=f"{config.description} 摘要あり")]
    if case.experiment_id == "EXP-03_with_tax":
        return [
            _base_row(
                config,
                voucher,
                debit_tax_category=config.tax_category,
                debit_tax_amount=config.tax_amount,
                credit_tax_category=config.tax_category,
                credit_tax_amount=config.tax_amount,
                description=f"{config.description} 税区分あり",
            )
        ]
    if case.experiment_id == "EXP-04_existing_subaccount":
        return [
            _base_row(
                config,
                voucher,
                debit_subaccount_code=config.existing_subaccount_code,
                debit_subaccount_name=config.existing_subaccount_name,
                description=f"{config.description} 既存補助",
            )
        ]
    if case.experiment_id == "EXP-05_nonexistent_subaccount":
        return [
            _base_row(
                config,
                voucher,
                debit_subaccount_code=config.nonexistent_subaccount_code,
                debit_subaccount_name=config.nonexistent_subaccount_name,
                description=f"{config.description} 存在しない補助",
            )
        ]
    if case.experiment_id == "EXP-06_observed_multi_record_sequence":
        debit_first = Decimal(config.amount) * Decimal("0.6")
        debit_second = Decimal(config.amount) - debit_first
        return [
            _base_row(
                config,
                voucher,
                identifier_flag="1110",
                debit_amount=str(debit_first),
                credit_amount="0",
                credit_account_code="",
                credit_account_name="",
                description=f"{config.description} observed sequence",
            ),
            _base_row(
                config,
                voucher,
                identifier_flag="1100",
                debit_amount=str(debit_second),
                credit_amount="0",
                credit_account_code="",
                credit_account_name="",
                description=f"{config.description} observed sequence",
            ),
            _base_row(
                config,
                voucher,
                identifier_flag="1101",
                debit_amount="0",
                debit_account_code="",
                debit_account_name="",
                credit_amount=config.amount,
                description=f"{config.description} observed sequence",
            ),
        ]
    return [_base_row(config, voucher)]


def _base_row(
    config: JdlImportExperimentConfig,
    voucher: str,
    identifier_flag: str = "1000",
    debit_account_code: str | None = None,
    debit_account_name: str | None = None,
    debit_subaccount_code: str = "",
    debit_subaccount_name: str = "",
    debit_tax_category: str = "",
    debit_tax_amount: str = "",
    debit_amount: str | None = None,
    credit_account_code: str | None = None,
    credit_account_name: str | None = None,
    credit_tax_category: str = "",
    credit_tax_amount: str = "",
    credit_amount: str | None = None,
    description: str | None = None,
) -> dict[str, str]:
    return {
        "//識別フラグ": identifier_flag,
        "伝番": voucher,
        "日付": config.date,
        "借方科目": debit_account_code if debit_account_code is not None else config.debit_account_code,
        "借方科目名称": debit_account_name if debit_account_name is not None else config.debit_account_name,
        "借方科目正式名称": debit_account_name if debit_account_name is not None else config.debit_account_name,
        "借方補助": debit_subaccount_code,
        "借方補助名称": debit_subaccount_name,
        "借方税区": debit_tax_category,
        "借方金額": debit_amount if debit_amount is not None else config.amount,
        "借方消費税": debit_tax_amount,
        "貸方科目": credit_account_code if credit_account_code is not None else config.credit_account_code,
        "貸方科目名称": credit_account_name if credit_account_name is not None else config.credit_account_name,
        "貸方科目正式名称": credit_account_name if credit_account_name is not None else config.credit_account_name,
        "貸方税区": credit_tax_category,
        "貸方金額": credit_amount if credit_amount is not None else config.amount,
        "貸方消費税": credit_tax_amount,
        "摘要": description if description is not None else config.description,
    }


def _write_experiment_csv(
    observed_header: tuple[str, ...],
    path: Path,
    row_values: Iterable[dict[str, str]],
) -> None:
    with path.open("w", encoding="cp932", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(("// JDL IBEX 出納帳 35.5 observed import experiment",))
        writer.writerow(("// 完全架空データ。実顧客情報は使用しない。",))
        writer.writerow(())
        writer.writerow(observed_header)
        for values in row_values:
            row = [""] * len(observed_header)
            for header_name, value in values.items():
                row[observed_header.index(header_name)] = value
            writer.writerow(row)


def _write_manifest(
    path: Path,
    cases: list[GeneratedExperiment],
    schema: Any,
) -> None:
    manifest = {
        "product": schema.product,
        "observed_version": schema.observed_version,
        "schema_status": "OBSERVED_ONLY",
        "encoding": "cp932",
        "line_ending": "CRLF",
        "bom": False,
        "journal_column_count": schema.journal_column_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result_status_values": ("PASS", "REJECTED", "UNTESTED"),
        "experiments": [
            {
                "experiment_id": case.experiment_id,
                "csv_path": case.csv_path.name,
                "purpose": case.purpose,
                "changed_variable": case.changed_variable,
                "expected_observation": case.expected_observation,
                "actual_result": "UNTESTED",
                "jdl_error_log_path": None,
                "notes": "",
            }
            for case in cases
        ],
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_config(config: JdlImportExperimentConfig) -> None:
    required = {
        "debit_account_code": config.debit_account_code,
        "debit_account_name": config.debit_account_name,
        "credit_account_code": config.credit_account_code,
        "credit_account_name": config.credit_account_name,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(
            "JDL実験CSV生成には科目コード/名称の明示指定が必要です: "
            + ", ".join(missing)
        )


def _config_from_args(args: argparse.Namespace) -> JdlImportExperimentConfig:
    config = load_config(args.config) if args.config else JdlImportExperimentConfig(
        debit_account_code="",
        debit_account_name="",
        credit_account_code="",
        credit_account_name="",
    )
    overrides = {
        "debit_account_code": args.debit_account_code,
        "debit_account_name": args.debit_account_name,
        "credit_account_code": args.credit_account_code,
        "credit_account_name": args.credit_account_name,
        "tax_category": args.tax_category,
        "tax_amount": args.tax_amount,
        "existing_subaccount_code": args.existing_subaccount_code,
        "existing_subaccount_name": args.existing_subaccount_name,
        "nonexistent_subaccount_code": args.nonexistent_subaccount_code,
        "nonexistent_subaccount_name": args.nonexistent_subaccount_name,
    }
    for field_name, value in overrides.items():
        if value is not None:
            config = replace(config, **{field_name: value})
    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate research-only JDL import experiment CSV files.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to experiment_config.json. CLI values override config values.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/jdl_import/output"),
    )
    parser.add_argument("--debit-account-code")
    parser.add_argument("--debit-account-name")
    parser.add_argument("--credit-account-code")
    parser.add_argument("--credit-account-name")
    parser.add_argument("--tax-category")
    parser.add_argument("--tax-amount")
    parser.add_argument("--existing-subaccount-code")
    parser.add_argument("--existing-subaccount-name")
    parser.add_argument("--nonexistent-subaccount-code")
    parser.add_argument("--nonexistent-subaccount-name")
    args = parser.parse_args()

    cases = generate_all_cases(_config_from_args(args), args.output_dir)
    print(f"Generated {len(cases)} JDL import experiment CSV files in {args.output_dir}")


if __name__ == "__main__":
    main()

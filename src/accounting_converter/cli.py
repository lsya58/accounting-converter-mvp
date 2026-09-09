from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.comparison import (
    JdlCsvFingerprintComparator,
)
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.diagnostics.jdl_csv.report import (
    JdlCsvDiagnosticReportGenerator,
)
from accounting_converter.diagnostics.jdl_csv.serialization import (
    analysis_to_dict,
    analysis_to_privacy_safe_dict,
)
from accounting_converter.diagnostics.yayoi_csv import (
    YayoiCsvAnalyzer,
    YayoiCsvDiagnosticReportGenerator,
    yayoi_analysis_to_dict,
    yayoi_analysis_to_privacy_safe_dict,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    ConversionProfileStoreError,
    default_profile_store_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="accounting_converter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser("diagnose")
    diagnose_parser.add_argument("csv_path", type=Path)
    diagnose_parser.add_argument(
        "--format",
        choices=("text", "json", "privacy-json"),
        default="text",
        help="Output format.",
    )
    diagnose_parser.add_argument(
        "--compare-observed",
        choices=("jdl-ibex-cashbook-35.5",),
        help="Explicitly compare/enrich using a known Observed Schema.",
    )

    diagnose_jdl_parser = subparsers.add_parser("diagnose-jdl")
    diagnose_jdl_parser.add_argument("csv_path", type=Path)
    diagnose_jdl_parser.add_argument(
        "--format",
        choices=("text", "json", "privacy-json"),
        default="text",
        help="Output format.",
    )
    diagnose_jdl_parser.add_argument(
        "--compare-observed",
        choices=("jdl-ibex-cashbook-35.5",),
        help="Explicitly compare/enrich using a known Observed Schema.",
    )

    compare_jdl_parser = subparsers.add_parser("compare-jdl")
    compare_jdl_parser.add_argument("baseline", type=Path)
    compare_jdl_parser.add_argument("target", type=Path)
    compare_jdl_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    diagnose_yayoi_parser = subparsers.add_parser("diagnose-yayoi")
    diagnose_yayoi_parser.add_argument("csv_path", type=Path)
    diagnose_yayoi_parser.add_argument(
        "--format",
        choices=("text", "json", "privacy-json"),
        default="text",
        help="Output format.",
    )

    profile_parser = subparsers.add_parser("profile")
    profile_parser.add_argument(
        "--store-dir",
        type=Path,
        default=default_profile_store_dir(),
        help="Local conversion profile store directory.",
    )
    profile_subparsers = profile_parser.add_subparsers(
        dest="profile_command",
        required=True,
    )
    profile_subparsers.add_parser("list")
    profile_inspect_parser = profile_subparsers.add_parser("inspect")
    profile_inspect_parser.add_argument("profile_id")
    profile_validate_parser = profile_subparsers.add_parser("validate")
    profile_validate_parser.add_argument("json_path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "diagnose":
        return _diagnose(args.csv_path, args.format, args.compare_observed)
    if args.command == "diagnose-jdl":
        return _diagnose(args.csv_path, args.format, args.compare_observed)
    if args.command == "compare-jdl":
        return _compare_jdl(args.baseline, args.target, args.format)
    if args.command == "diagnose-yayoi":
        return _diagnose_yayoi(args.csv_path, args.format)
    if args.command == "profile":
        return _profile_command(args)
    parser.error("unknown command")
    return 2


def _diagnose(
    csv_path: Path,
    output_format: str,
    compare_observed: str | None = None,
) -> int:
    analyzer = JdlCsvStructuralAnalyzer(
        observed_schema=_observed_schema_for_key(compare_observed)
    )
    analysis = analyzer.analyze_path(csv_path)

    if output_format == "json":
        print(json.dumps(analysis_to_dict(analysis), ensure_ascii=False, indent=2))
    elif output_format == "privacy-json":
        print(
            json.dumps(
                analysis_to_privacy_safe_dict(analysis),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(JdlCsvDiagnosticReportGenerator().generate_text(analysis))
    return 0


def _compare_jdl(baseline: Path, target: Path, output_format: str) -> int:
    analyzer = JdlCsvStructuralAnalyzer()
    baseline_analysis = analyzer.analyze_path(baseline)
    target_analysis = analyzer.analyze_path(target)
    if baseline_analysis.schema_fingerprint is None:
        print("ERROR: baseline schema fingerprint could not be generated")
        return 1
    if target_analysis.schema_fingerprint is None:
        print("ERROR: target schema fingerprint could not be generated")
        return 1

    comparison = JdlCsvFingerprintComparator().compare(
        baseline_analysis.schema_fingerprint,
        target_analysis.schema_fingerprint,
    )
    if output_format == "json":
        print(
            json.dumps(
                _comparison_to_dict(comparison),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_comparison_to_text(comparison))
    return 0


def _observed_schema_for_key(key: str | None):
    if key == "jdl-ibex-cashbook-35.5":
        return jdl_ibex_cashbook_35_5_observed_schema()
    return None


def _comparison_to_dict(comparison) -> dict:
    return {
        "has_differences": comparison.has_differences,
        "baseline": _fingerprint_to_dict(comparison.baseline),
        "target": _fingerprint_to_dict(comparison.target),
        "differences": [
            {
                "severity": difference.severity.value,
                "rule_id": difference.rule_id,
                "field": difference.field,
                "message": difference.message,
                "input_value": difference.input_value,
                "suggested_action": difference.suggested_action,
            }
            for difference in comparison.differences
        ],
        "judgment": "構造差分のみを示します。取込可否、正式JDL仕様、同一Versionとは判定しません。",
    }


def _fingerprint_to_dict(fingerprint) -> dict:
    return {
        "encoding": fingerprint.encoding,
        "delimiter": fingerprint.delimiter,
        "column_count": fingerprint.column_count,
        "line_ending": fingerprint.line_ending,
        "has_bom": fingerprint.has_bom,
        "header_names": list(fingerprint.header_names),
        "metadata_pattern": list(fingerprint.metadata_pattern),
        "record_column_counts": [
            {"column_count": column_count, "record_count": record_count}
            for column_count, record_count in fingerprint.record_column_counts
        ],
    }


def _comparison_to_text(comparison) -> str:
    lines = [
        "JDL CSV 構造比較",
        "",
        "差分:",
    ]
    if not comparison.differences:
        lines.append("INFO: 構造Fingerprint上の差分は検出されませんでした。")
    for difference in comparison.differences:
        lines.append(f"{difference.severity.value}: {difference.field} - {difference.message}")
        if difference.input_value is not None:
            lines.append(str(difference.input_value))
    lines.extend(
        [
            "",
            "注意:",
            "構造差分のみを示します。取込可否、正式JDL仕様、同一Versionとは判定しません。",
        ]
    )
    return "\n".join(lines)


def _diagnose_yayoi(csv_path: Path, output_format: str) -> int:
    analysis = YayoiCsvAnalyzer().analyze_path(csv_path)

    if output_format == "json":
        print(json.dumps(yayoi_analysis_to_dict(analysis), ensure_ascii=False, indent=2))
    elif output_format == "privacy-json":
        print(
            json.dumps(
                yayoi_analysis_to_privacy_safe_dict(analysis),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(YayoiCsvDiagnosticReportGenerator().generate_text(analysis))
    return 0


def _profile_command(args: argparse.Namespace) -> int:
    store = ConversionProfileStore(args.store_dir)
    try:
        if args.profile_command == "list":
            for profile in store.list():
                print(f"{profile.profile_id}\t{profile.profile_name}")
            return 0
        if args.profile_command == "inspect":
            profile = store.get(args.profile_id)
            print(store.to_json_text(profile), end="")
            return 0
        if args.profile_command == "validate":
            store.from_json_text(args.json_path.read_text(encoding="utf-8"))
            print("OK")
            return 0
    except ConversionProfileStoreError as error:
        print(f"ERROR: {error}")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.diagnostics.jdl_csv.report import (
    JdlCsvDiagnosticReportGenerator,
)
from accounting_converter.diagnostics.jdl_csv.serialization import analysis_to_dict
from accounting_converter.diagnostics.yayoi_csv import (
    YayoiCsvAnalyzer,
    YayoiCsvDiagnosticReportGenerator,
    yayoi_analysis_to_dict,
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
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    diagnose_yayoi_parser = subparsers.add_parser("diagnose-yayoi")
    diagnose_yayoi_parser.add_argument("csv_path", type=Path)
    diagnose_yayoi_parser.add_argument(
        "--format",
        choices=("text", "json"),
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
        return _diagnose(args.csv_path, args.format)
    if args.command == "diagnose-yayoi":
        return _diagnose_yayoi(args.csv_path, args.format)
    if args.command == "profile":
        return _profile_command(args)
    parser.error("unknown command")
    return 2


def _diagnose(csv_path: Path, output_format: str) -> int:
    analyzer = JdlCsvStructuralAnalyzer(
        observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
    )
    analysis = analyzer.analyze_path(csv_path)

    if output_format == "json":
        print(json.dumps(analysis_to_dict(analysis), ensure_ascii=False, indent=2))
    else:
        print(JdlCsvDiagnosticReportGenerator().generate_text(analysis))
    return 0


def _diagnose_yayoi(csv_path: Path, output_format: str) -> int:
    analysis = YayoiCsvAnalyzer().analyze_path(csv_path)

    if output_format == "json":
        print(json.dumps(yayoi_analysis_to_dict(analysis), ensure_ascii=False, indent=2))
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

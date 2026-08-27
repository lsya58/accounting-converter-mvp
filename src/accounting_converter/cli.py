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

    args = parser.parse_args(argv)
    if args.command == "diagnose":
        return _diagnose(args.csv_path, args.format)
    if args.command == "diagnose-yayoi":
        return _diagnose_yayoi(args.csv_path, args.format)
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


if __name__ == "__main__":
    raise SystemExit(main())

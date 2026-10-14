from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
)


SAFETY_NOTICE = "DEVELOPMENT TEST ONLY / NOT FOR PRODUCTION"
KNOWN_TAX_LITERALS = frozenset(
    {
        "課税仕入 10%",
        "課税売上 10%",
        "課税仕入 (軽)8%",
        "課税売上 (軽)8%",
        "非課税仕入",
        "対象外",
    }
)
DESCRIPTION_CASES = {
    "description_same": ("JDL-DESC-SAME",) * 3,
    "description_two_values": (
        "JDL-DESC-FIRST",
        "JDL-DESC-LATER",
        "JDL-DESC-LATER",
    ),
    "description_three_values": (
        "JDL-DESC-ONE",
        "JDL-DESC-TWO",
        "JDL-DESC-THREE",
    ),
}


class JdlMvpBlockerProbeError(ValueError):
    pass


def build_private_plan(source: Path) -> dict[str, object]:
    schema = moneyforward_cloud_journal_export_observed_schema()
    profile = FormatProfile(
        "Money Forward",
        "Money Forward クラウド会計",
        "UNKNOWN",
        schema.identity.stable_key,
        "cp932",
    )
    entries = tuple(MoneyForwardInputAdapter().read(source, profile))
    requirements = MappingRequirementExtractor().extract(entries)
    unknown = sorted(
        item.source_value
        for item in requirements.tax_categories
        if item.source_value not in KNOWN_TAX_LITERALS
    )
    tax_cases = []
    for index, literal in enumerate(unknown, start=1):
        side_counts: Counter[str] = Counter()
        journal_count = 0
        for entry in entries:
            matched = False
            for line in entry.lines:
                if line.tax_info and line.tax_info.category == literal:
                    side_counts[line.side.value] += 1
                    matched = True
            journal_count += matched
        tax_cases.append(
            {
                "case_id": f"unknown_tax_{index}",
                "source_literal_sha256": _text_hash(literal),
                "semantic_class": _semantic_class(literal),
                "side_counts": dict(sorted(side_counts.items())),
                "journal_count": journal_count,
                "existing_six_tax_equivalent": False,
                "candidate_status": "BLOCKED_PENDING_HUMAN_JDL_EXPORT",
                "required_next_evidence": (
                    "synthetic JDL UI entry and direct JDL export for this semantic case"
                ),
            }
        )
    return {
        "schema_version": "1",
        "source_sha256": _file_hash(source),
        "logical_journal_count": len(entries),
        "unknown_tax_literal_count": len(unknown),
        "unknown_tax_cases": tax_cases,
        "trade_partner_probe": {
            "classification": "NO_CONFIRMED_JDL_CSV_FIELD",
            "candidate_status": "BLOCKED_PENDING_UI_EVIDENCE",
            "checks": [
                "independent JDL UI field exists",
                "official import column or documented operation exists",
                "direct export preserves the value outside description",
            ],
        },
        "multiple_description_probe": {
            "candidate_status": "GENERATABLE_FROM_VERIFIED_COMPOUND_BASE",
            "cases": list(DESCRIPTION_CASES),
            "comparison_policy": "exact row order and exact description preservation",
        },
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
        "safety_notice": SAFETY_NOTICE,
    }


def write_private_plan(source: Path, destination: Path, private_root: Path) -> Path:
    _require_private(destination, private_root)
    _write_new_json(destination, build_private_plan(source))
    for case in ("unknown_tax_1", "unknown_tax_2", "trade_partner"):
        _write_new_json(
            destination.with_name(f"{case}_result.json"),
            {
                "schema_version": "1",
                "probe_case": case,
                "result_status": "UNTESTED",
                "candidate_generated": False,
                "human_ui_checked": False,
                "reexport_present": False,
                "comparison_pass": None,
                "mapping_promotion_allowed": False,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
            },
        )
    return destination


def generate_description_candidates(
    base_candidate: Path,
    base_manifest: Path,
    output_dir: Path,
    private_root: Path,
    *,
    first_date: str = "20261114",
) -> tuple[Path, ...]:
    _require_private(output_dir, private_root)
    manifest = json.loads(base_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") != "compound_1d3c"
        or manifest.get("NOT_FOR_PRODUCTION") is not True
        or manifest.get("output_sha256") != _file_hash(base_candidate)
    ):
        raise JdlMvpBlockerProbeError(
            "verified synthetic compound base candidate and manifest are required"
        )
    header, rows = _read_jdl(base_candidate)
    positions = {name: index for index, name in enumerate(header)}
    if len(rows) != 3 or tuple(row[positions["//識別フラグ"]] for row in rows) != (
        "1110",
        "1100",
        "1101",
    ):
        raise JdlMvpBlockerProbeError("base candidate must be the observed 1D3C shape")
    generated = []
    for offset, (case_name, descriptions) in enumerate(DESCRIPTION_CASES.items()):
        destination = output_dir / f"{case_name}.csv"
        candidate_manifest = destination.with_suffix(".manifest.json")
        result_template = output_dir / f"{case_name}_result.json"
        for path in (destination, candidate_manifest, result_template):
            if path.exists():
                raise JdlMvpBlockerProbeError(f"output exists: {path.name}")
        case_rows = [list(row) for row in rows]
        date = str(int(first_date) + offset)
        for row, description in zip(case_rows, descriptions, strict=True):
            row[positions["日付"]] = date
            row[positions["摘要"]] = description
        _write_jdl(destination, header, case_rows)
        _write_new_json(
            candidate_manifest,
            {
                "schema_version": "1",
                "probe_case": case_name,
                "base_candidate_sha256": _file_hash(base_candidate),
                "base_manifest_sha256": _file_hash(base_manifest),
                "output_sha256": _file_hash(destination),
                "expected_row_count": 3,
                "expected_flag_sequence": ["1110", "1100", "1101"],
                "expected_date": date,
                "description_pattern": case_name,
                "strict_comparison_required": True,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
                "safety_notice": SAFETY_NOTICE,
            },
        )
        _write_new_json(
            result_template,
            {
                "schema_version": "1",
                "probe_case": case_name,
                "result_status": "UNTESTED",
                "imported": None,
                "reexport_present": None,
                "comparison_pass": None,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
            },
        )
        generated.append(destination)
    return tuple(generated)


def compare_description_roundtrip(
    candidate: Path, manifest_path: Path, reexport: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") not in DESCRIPTION_CASES
        or manifest.get("NOT_FOR_PRODUCTION") is not True
        or manifest.get("output_sha256") != _file_hash(candidate)
    ):
        raise JdlMvpBlockerProbeError("candidate manifest mismatch")
    header, expected = _read_jdl(candidate)
    actual_header, actual_rows = _read_jdl(reexport)
    if header != actual_header:
        raise JdlMvpBlockerProbeError("re-export header mismatch")
    positions = {name: index for index, name in enumerate(header)}
    date = manifest["expected_date"]
    actual = [row for row in actual_rows if row[positions["日付"]] == date]
    compared_fields = (
        "//識別フラグ",
        "日付",
        "借方科目",
        "借方科目名称",
        "借方金額",
        "貸方科目",
        "貸方科目名称",
        "貸方金額",
        "摘要",
    )
    mismatch_fields = sorted(
        {
            name
            for left, right in zip(expected, actual, strict=False)
            for name in compared_fields
            if left[positions[name]] != right[positions[name]]
        }
    )
    counts_match = len(expected) == len(actual) == 3
    return {
        "schema_version": "1",
        "probe_case": manifest["probe_case"],
        "candidate_sha256": _file_hash(candidate),
        "reexport_sha256": _file_hash(reexport),
        "expected_rows": len(expected),
        "actual_matching_date_rows": len(actual),
        "flag_sequence_match": counts_match
        and [row[positions["//識別フラグ"]] for row in expected]
        == [row[positions["//識別フラグ"]] for row in actual],
        "description_sequence_preserved": counts_match
        and [row[positions["摘要"]] for row in expected]
        == [row[positions["摘要"]] for row in actual],
        "mismatch_field_categories": mismatch_fields,
        "comparison_pass": counts_match and not mismatch_fields,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def _semantic_class(literal: str) -> str:
    if "対象外" in literal and "仕入" in literal:
        return "OUT_OF_SCOPE_PURCHASE_LIKE_NEW_EVIDENCE_REQUIRED"
    if "非課税" in literal and "売上" in literal:
        return "NON_TAXABLE_SALES_LIKE_NEW_EVIDENCE_REQUIRED"
    return "UNKNOWN_NEW_EVIDENCE_REQUIRED"


def _read_jdl(path: Path) -> tuple[tuple[str, ...], list[list[str]]]:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise JdlMvpBlockerProbeError("BOM is not allowed")
    if b"\r\n" not in raw or raw.replace(b"\r\n", b"").find(b"\n") >= 0:
        raise JdlMvpBlockerProbeError("CRLF is required")
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError as exc:
        raise JdlMvpBlockerProbeError("CP932 decode failed") from exc
    rows = list(csv.reader(io.StringIO(text, newline="")))
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    if not rows or tuple(rows[0]) != header or any(len(row) != 30 for row in rows):
        raise JdlMvpBlockerProbeError("official 30-column structure is required")
    return header, rows[1:]


def _write_jdl(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    raw = stream.getvalue().encode("cp932")
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_bytes(raw)
    os.replace(temp, path)
    _read_jdl(path)


def _write_new_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise JdlMvpBlockerProbeError(f"output exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _require_private(path: Path, private_root: Path) -> None:
    if not path.resolve().is_relative_to(private_root.resolve()):
        raise JdlMvpBlockerProbeError("output must be under data/private")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Development-only JDL MVP blocker probes")
    parser.add_argument("--private-root", type=Path, default=Path("data/private"))
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--mf-input", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    generate = sub.add_parser("generate-descriptions")
    generate.add_argument("--base-candidate", type=Path, required=True)
    generate.add_argument("--base-manifest", type=Path, required=True)
    generate.add_argument("--output-dir", type=Path, required=True)
    generate.add_argument("--first-date", default="20261114")
    compare = sub.add_parser("compare-description")
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--manifest", type=Path, required=True)
    compare.add_argument("--reexport", type=Path, required=True)
    compare.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        write_private_plan(args.mf_input, args.output, args.private_root)
    elif args.command == "generate-descriptions":
        generate_description_candidates(
            args.base_candidate,
            args.base_manifest,
            args.output_dir,
            args.private_root,
            first_date=args.first_date,
        )
    else:
        _require_private(args.result, args.private_root)
        _write_new_json(
            args.result,
            compare_description_roundtrip(
                args.candidate, args.manifest, args.reexport
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

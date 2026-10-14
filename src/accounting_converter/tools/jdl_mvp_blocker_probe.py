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
DESCRIPTION_ROUNDTRIP_EVIDENCE_ID = (
    "EVID-JDL-COMPOUND-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
)
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
DESCRIPTION_PROBE_ACCOUNT_CODES = {
    "現金": "1111",
    "小口現金": "1121",
}
LARGE_DESCRIPTION_CASES = {
    "description_4d6c": (4, 6, "20261122"),
    "description_5d7c": (5, 7, "20261123"),
    "description_5d8c": (5, 8, "20261124"),
}
LARGE_DESCRIPTION_EVIDENCE_IDS = {
    "description_4d6c": (
        "EVID-JDL-COMPOUND-4D6C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
    "description_5d7c": (
        "EVID-JDL-COMPOUND-5D7C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
    ),
    "description_5d8c": (
        "EVID-JDL-COMPOUND-5D8C-PER-ROW-DESCRIPTION-ROUNDTRIP-001"
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
    header, rows = _read_jdl(base_candidate, require_first_header=True)
    positions = {name: index for index, name in enumerate(header)}
    if len(rows) != 3 or tuple(row[positions["//識別フラグ"]] for row in rows) != (
        "1110",
        "1100",
        "1101",
    ):
        raise JdlMvpBlockerProbeError("base candidate must be the observed 1D3C shape")
    safe_credit_identity = tuple(
        rows[2][positions[name]]
        for name in ("貸方科目", "貸方科目名称", "貸方科目正式名称")
    )
    if not safe_credit_identity[1]:
        raise JdlMvpBlockerProbeError(
            "base candidate must contain an observed safe credit account name"
        )
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
            for name, value in zip(
                ("貸方科目", "貸方科目名称", "貸方科目正式名称"),
                safe_credit_identity,
                strict=True,
            ):
                row[positions[name]] = value
            for name in (
                "借方補助",
                "借方補助名称",
                "貸方補助",
                "貸方補助名称",
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
                "借方部門コード",
                "借方部門名称",
                "貸方部門コード",
                "貸方部門名称",
            ):
                row[positions[name]] = ""
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
                "account_pattern": "ONE_DEBIT_TO_REPEATED_SAFE_CREDIT",
                "safe_credit_identity_source": "BASE_FINAL_ROW_RUNTIME_NO_SUBACCOUNT_ERROR",
                "subaccount_fields_blank": True,
                "tax_fields_blank": True,
                "department_fields_blank": True,
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
    header, expected = _read_jdl(candidate, require_first_header=True)
    actual_header, actual_rows = _read_jdl(reexport)
    if header != actual_header:
        raise JdlMvpBlockerProbeError("re-export header mismatch")
    positions = {name: index for index, name in enumerate(header)}
    date = manifest["expected_date"]
    actual = [row for row in actual_rows if row[positions["日付"]] == date]
    compared_fields = (
        "//識別フラグ",
        "日付",
        "借方科目名称",
        "借方金額",
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
    missing = max(len(expected) - len(actual), 0)
    extra = max(len(actual) - len(expected), 0)
    duplicate = len(actual) - len({tuple(row) for row in actual})
    expected_debit = sum(int(row[positions["借方金額"]] or "0") for row in expected)
    expected_credit = sum(int(row[positions["貸方金額"]] or "0") for row in expected)
    actual_debit = sum(int(row[positions["借方金額"]] or "0") for row in actual)
    actual_credit = sum(int(row[positions["貸方金額"]] or "0") for row in actual)
    balance_match = (
        expected_debit == expected_credit == actual_debit == actual_credit
    )
    account_identity_match = counts_match and all(
        _description_probe_account_identity_matches(left, right, positions)
        for left, right in zip(expected, actual, strict=True)
    )
    if not account_identity_match:
        mismatch_fields.append("account_identity")
        mismatch_fields = sorted(set(mismatch_fields))
    comparison_pass = (
        counts_match
        and missing == 0
        and duplicate == 0
        and extra == 0
        and balance_match
        and not mismatch_fields
    )
    return {
        "schema_version": "1",
        "probe_case": manifest["probe_case"],
        "candidate_sha256": _file_hash(candidate),
        "reexport_sha256": _file_hash(reexport),
        "expected_rows": len(expected),
        "actual_matching_date_rows": len(actual),
        "missing_rows": missing,
        "duplicate_rows": duplicate,
        "extra_rows": extra,
        "flag_sequence_match": counts_match
        and [row[positions["//識別フラグ"]] for row in expected]
        == [row[positions["//識別フラグ"]] for row in actual],
        "description_sequence_preserved": counts_match
        and [row[positions["摘要"]] for row in expected]
        == [row[positions["摘要"]] for row in actual],
        "mismatch_field_categories": mismatch_fields,
        "balance_match": balance_match,
        "account_identity_match": account_identity_match,
        "account_code_population_classification": (
            "KNOWN_EXACT_RUNTIME_REEXPORT_NORMALIZATION"
            if account_identity_match
            else "MISMATCH"
        ),
        "comparison_pass": comparison_pass,
        "evidence_id": DESCRIPTION_ROUNDTRIP_EVIDENCE_ID,
        "evidence_level": (
            "VERIFIED_BY_REAL_IMPORT" if comparison_pass else "HUMAN_OBSERVED"
        ),
        "evidence_scope": "SYNTHETIC_1110_1100_1101_1D3C_PER_ROW_DESCRIPTION",
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def generate_large_description_candidates(
    output_dir: Path, private_root: Path
) -> tuple[Path, ...]:
    _require_private(output_dir, private_root)
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    positions = {name: index for index, name in enumerate(header)}
    generated: list[Path] = []
    for case_name, (debit_count, credit_count, date) in LARGE_DESCRIPTION_CASES.items():
        destination = output_dir / f"{case_name}.csv"
        manifest_path = destination.with_suffix(".manifest.json")
        result_path = output_dir / f"{case_name}_result.json"
        for path in (destination, manifest_path, result_path):
            if path.exists():
                raise JdlMvpBlockerProbeError(f"output exists: {path.name}")
        row_count = max(debit_count, credit_count)
        debit_amounts = _balanced_amounts(500, debit_count)
        credit_amounts = _balanced_amounts(500, credit_count)
        rows: list[list[str]] = []
        for index in range(row_count):
            row = [""] * 30
            row[positions["//識別フラグ"]] = (
                "1110" if index == 0 else "1101" if index == row_count - 1 else "1100"
            )
            row[positions["日付"]] = date
            if index < debit_count:
                row[positions["借方科目名称"]] = "現金"
                row[positions["借方金額"]] = str(debit_amounts[index])
            else:
                row[positions["借方金額"]] = "0"
            if index < credit_count:
                row[positions["貸方科目名称"]] = "小口現金"
                row[positions["貸方金額"]] = str(credit_amounts[index])
            else:
                row[positions["貸方金額"]] = "0"
            row[positions["摘要"]] = f"JDL-LDESC-{case_name[-4:].upper()}-{index + 1:02d}"
            rows.append(row)
        _write_jdl(destination, header, rows)
        _write_new_json(
            manifest_path,
            {
                "schema_version": "1",
                "probe_case": case_name,
                "output_sha256": _file_hash(destination),
                "expected_date": date,
                "expected_shape": {"debit_lines": debit_count, "credit_lines": credit_count},
                "expected_row_count": row_count,
                "expected_flag_sequence": [row[0] for row in rows],
                "description_policy": "EXACT_PER_ROW_IN_ORDER",
                "account_pattern": "REPEATED_RUNTIME_CONFIRMED_NO_SUBACCOUNT_ACCOUNTS",
                "subaccount_fields_blank": True,
                "tax_fields_blank": True,
                "department_fields_blank": True,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
                "safety_notice": SAFETY_NOTICE,
            },
        )
        _write_new_json(
            result_path,
            {
                "schema_version": "1",
                "probe_case": case_name,
                "result_status": "UNTESTED",
                "comparison_pass": None,
                "mapping_promotion_allowed": False,
                "production_allowed": False,
                "NOT_FOR_PRODUCTION": True,
            },
        )
        generated.append(destination)
    return tuple(generated)


def compare_large_description_roundtrip(
    candidate: Path, manifest_path: Path, reexport: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") not in LARGE_DESCRIPTION_CASES
        or manifest.get("NOT_FOR_PRODUCTION") is not True
        or manifest.get("output_sha256") != _file_hash(candidate)
    ):
        raise JdlMvpBlockerProbeError("large description candidate manifest mismatch")
    header, expected = _read_jdl(candidate, require_first_header=True)
    actual_header, all_actual = _read_jdl(reexport)
    if header != actual_header:
        raise JdlMvpBlockerProbeError("re-export header mismatch")
    positions = {name: index for index, name in enumerate(header)}
    actual = [row for row in all_actual if row[positions["日付"]] == manifest["expected_date"]]
    fields = (
        "//識別フラグ", "日付", "借方科目名称", "借方金額",
        "貸方科目名称", "貸方金額", "摘要",
    )
    mismatches = sorted({
        name
        for left, right in zip(expected, actual, strict=False)
        for name in fields
        if left[positions[name]] != right[positions[name]]
    })
    count_match = len(expected) == len(actual) == manifest["expected_row_count"]
    account_match = count_match and all(
        _description_probe_account_identity_matches(left, right, positions)
        for left, right in zip(expected, actual, strict=True)
    )
    missing = max(len(expected) - len(actual), 0)
    extra = max(len(actual) - len(expected), 0)
    duplicate = len(actual) - len({tuple(row) for row in actual})
    expected_debit = sum(int(row[positions["借方金額"]] or "0") for row in expected)
    expected_credit = sum(int(row[positions["貸方金額"]] or "0") for row in expected)
    actual_debit = sum(int(row[positions["借方金額"]] or "0") for row in actual)
    actual_credit = sum(int(row[positions["貸方金額"]] or "0") for row in actual)
    balance_match = expected_debit == expected_credit == actual_debit == actual_credit
    passed = count_match and account_match and not mismatches and not any((missing, extra, duplicate)) and balance_match
    return {
        "schema_version": "1",
        "probe_case": manifest["probe_case"],
        "candidate_sha256": _file_hash(candidate),
        "reexport_sha256": _file_hash(reexport),
        "expected_rows": len(expected),
        "actual_rows": len(actual),
        "missing_rows": missing,
        "duplicate_rows": duplicate,
        "extra_rows": extra,
        "flag_sequence_match": count_match and [r[0] for r in expected] == [r[0] for r in actual],
        "description_sequence_preserved": count_match and [r[positions["摘要"]] for r in expected] == [r[positions["摘要"]] for r in actual],
        "account_identity_match": account_match,
        "balance_match": balance_match,
        "mismatch_field_categories": mismatches,
        "comparison_pass": passed,
        "evidence_id": LARGE_DESCRIPTION_EVIDENCE_IDS[manifest["probe_case"]],
        "evidence_level": "VERIFIED_BY_REAL_IMPORT" if passed else "UNTESTED",
        "evidence_scope": (
            "SYNTHETIC_EXACT_SHAPE_PER_ROW_DESCRIPTION_NO_OPTIONAL_FIELDS"
        ),
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }


def _balanced_amounts(total: int, count: int) -> tuple[int, ...]:
    base, remainder = divmod(total, count)
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def _description_probe_account_identity_matches(
    expected: list[str], actual: list[str], positions: dict[str, int]
) -> bool:
    for prefix in ("借方", "貸方"):
        name = expected[positions[f"{prefix}科目名称"]]
        actual_name = actual[positions[f"{prefix}科目名称"]]
        actual_code = actual[positions[f"{prefix}科目"]]
        if not name:
            if actual_name or actual_code:
                return False
            continue
        if (
            actual_name != name
            or DESCRIPTION_PROBE_ACCOUNT_CODES.get(name) != actual_code
        ):
            return False
    return True


def _semantic_class(literal: str) -> str:
    if "対象外" in literal and "仕入" in literal:
        return "OUT_OF_SCOPE_PURCHASE_LIKE_NEW_EVIDENCE_REQUIRED"
    if "非課税" in literal and "売上" in literal:
        return "NON_TAXABLE_SALES_LIKE_NEW_EVIDENCE_REQUIRED"
    return "UNKNOWN_NEW_EVIDENCE_REQUIRED"


def _read_jdl(
    path: Path, *, require_first_header: bool = False
) -> tuple[tuple[str, ...], list[list[str]]]:
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
    header_indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if (
        len(header_indexes) != 1
        or (require_first_header and header_indexes[0] != 0)
    ):
        raise JdlMvpBlockerProbeError("official 30-column structure is required")
    data_rows = rows[header_indexes[0] + 1 :]
    if any(len(row) != 30 for row in data_rows):
        raise JdlMvpBlockerProbeError("official 30-column structure is required")
    return header, data_rows


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
    _read_jdl(path, require_first_header=True)


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
    generate_large = sub.add_parser("generate-large-descriptions")
    generate_large.add_argument("--output-dir", type=Path, required=True)
    compare_large = sub.add_parser("compare-large-description")
    compare_large.add_argument("--candidate", type=Path, required=True)
    compare_large.add_argument("--manifest", type=Path, required=True)
    compare_large.add_argument("--reexport", type=Path, required=True)
    compare_large.add_argument("--result", type=Path, required=True)
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
    elif args.command == "compare-description":
        _require_private(args.result, args.private_root)
        _write_new_json(
            args.result,
            compare_description_roundtrip(
                args.candidate, args.manifest, args.reexport
            ),
        )
    elif args.command == "generate-large-descriptions":
        generate_large_description_candidates(
            args.output_dir, args.private_root
        )
    else:
        _require_private(args.result, args.private_root)
        _write_new_json(
            args.result,
            compare_large_description_roundtrip(
                args.candidate, args.manifest, args.reexport
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

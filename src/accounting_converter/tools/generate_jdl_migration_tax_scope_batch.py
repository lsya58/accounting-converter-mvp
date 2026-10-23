from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from pathlib import Path

from accounting_converter.adapters.input.jdl import JdlMigrationParser
from accounting_converter.application.jdl_migration_tax_evidence import (
    canonical_flag_normalization_evidence,
)
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


def generate(
    source: Path,
    review_pack: Path,
    output_dir: Path,
    private_root: Path,
) -> tuple[Path, Path, Path]:
    output_dir = output_dir.resolve()
    private_root = private_root.resolve()
    if output_dir != private_root and private_root not in output_dir.parents:
        raise ValueError("probe output must stay under data/private")
    candidate = output_dir / "jdl_migration_tax_scope_batch.csv"
    manifest = output_dir / "jdl_migration_tax_scope_batch.manifest.json"
    result = output_dir / "jdl_migration_tax_scope_batch.result.json"
    if any(path.exists() for path in (candidate, manifest, result)):
        raise FileExistsError("probe output already exists")

    source_bytes = source.read_bytes()
    review = json.loads(review_pack.read_text(encoding="utf-8"))
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if review.get("source_sha256") != source_sha256:
        raise ValueError("review pack does not match source")
    mismatched_accounts = {
        (str(item["source"]["code"]), str(item["source"]["name"]))
        for item in review.get("account_mismatches", ())
    }

    parsed = JdlMigrationParser().parse_path(source)
    cases = _select_cases(parsed.entries)
    if len(cases) != 6:
        raise ValueError("expected six distinct unsupported tax scope cases")
    for entry in cases:
        identities = {
            (
                str(line.metadata.get("jdl_source_account_code", "")),
                str(line.metadata.get("jdl_source_account_formal_name", "")),
            )
            for line in entry.lines
        }
        if identities & mismatched_accounts:
            raise ValueError("probe contains an account requiring target mapping")

    dates = tuple(f"202603{20 + index:02d}" for index in range(len(cases)))
    candidate_bytes = _candidate_bytes(cases, dates)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(candidate_bytes)
    generated = JdlMigrationParser().parse_path(candidate)
    if len(generated.entries) != 6:
        raise RuntimeError("generated tax scope batch is invalid")

    pattern_counts: dict[str, int] = defaultdict(int)
    for entry in cases:
        pattern_counts[_privacy_safe_pattern(entry)] += 1
    manifest.write_text(json.dumps({
        "schema_version": "1",
        "probe_case": "jdl_migration_tax_scope_batch",
        "source_sha256": source_sha256,
        "target_master_identity_sha256": review.get(
            "target_master_identity_sha256", ""
        ),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "journal_count": len(generated.entries),
        "physical_rows": generated.journal_record_count,
        "header_output_period_start": dates[0],
        "header_output_period_end": dates[-1],
        "pattern_counts": dict(sorted(pattern_counts.items())),
        "all_accounts_exact_in_review_pack": True,
        "official_columns": 30,
        "encoding": "CP932",
        "bom": False,
        "line_ending": "CRLF",
        "expected_preflight_blockers": ["JDL-MIGRATION-TAX-EVIDENCE-SCOPE"],
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.write_text(json.dumps({
        "schema_version": "1",
        "probe_case": "jdl_migration_tax_scope_batch",
        "result_status": "UNTESTED",
        "comparison_pass": None,
        "mapping_promotion_allowed": False,
        "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return candidate, manifest, result


def compare_batch(candidate: Path, reexport: Path) -> dict[str, object]:
    expected = _parse_journal_rows(candidate)
    actual = _parse_journal_rows(reexport)
    expected_rows = tuple(
        row for entry in expected.entries for row in entry.metadata["physical_rows"]
    )
    actual_rows = tuple(
        row for entry in actual.entries for row in entry.metadata["physical_rows"]
    )
    case_results = []
    actual_by_date = {entry.date.strftime("%Y%m%d"): entry for entry in actual.entries}
    for index, expected_entry in enumerate(expected.entries, 1):
        date = expected_entry.date.strftime("%Y%m%d")
        actual_entry = actual_by_date.get(date)
        mismatches = [] if actual_entry is not None else ["missing_journal"]
        raw_mismatches = [] if actual_entry is not None else ["missing_journal"]
        normalizations = []
        if actual_entry is not None:
            entry_result = _entry_mismatches(expected_entry, actual_entry)
            mismatches.extend(entry_result["semantic_mismatches"])
            raw_mismatches.extend(entry_result["raw_mismatches"])
            normalizations.extend(entry_result["known_normalizations"])
        case_results.append({
            "case": index,
            "comparison_pass": not mismatches,
            "mismatched_fields": sorted(set(mismatches)),
            "raw_mismatched_fields": sorted(set(raw_mismatches)),
            "semantic_classifications": tuple(normalizations),
        })
    expected_dates = {entry.date.strftime("%Y%m%d") for entry in expected.entries}
    extra_dates = sorted(set(actual_by_date) - expected_dates)
    return {
        "comparison_pass": all(item["comparison_pass"] for item in case_results)
        and not extra_dates,
        "expected_journals": len(expected.entries),
        "actual_journals": len(actual.entries),
        "expected_rows": len(expected_rows),
        "actual_rows": len(actual_rows),
        "missing_or_extra": (
            len(expected.entries) != len(actual.entries)
            or len(expected_rows) != len(actual_rows)
            or bool(extra_dates)
        ),
        "extra_journal_count": len(extra_dates),
        "case_results": case_results,
    }


def _parse_journal_rows(path: Path):
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("BOM is not allowed")
    if not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b""):
        raise ValueError("CRLF-only CSV is required")
    rows = list(csv.reader(io.StringIO(raw.decode("cp932", errors="strict"))))
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(indexes) != 1:
        raise ValueError("exact official header is required")
    journal_rows = rows[indexes[0] + 1:]
    if not journal_rows or any(len(row) != 30 for row in journal_rows):
        raise ValueError("official 30-column rows are required")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(journal_rows)
    return JdlMigrationParser().parse_text(stream.getvalue(), file_name=path.name)


def _entry_mismatches(expected, actual) -> dict[str, list[str]]:
    mismatches: list[str] = []
    raw_mismatches: list[str] = []
    normalizations: list[str] = []
    if tuple(expected.metadata["identifier_flags"]) != tuple(
        actual.metadata["identifier_flags"]
    ):
        raw_mismatches.append("flags")
        evidence = canonical_flag_normalization_evidence(
            expected, tuple(actual.metadata["identifier_flags"])
        )
        if evidence is None:
            mismatches.append("flags")
        else:
            normalizations.append(
                f"KNOWN_JDL_CANONICAL_NORMALIZATION:{evidence.evidence_id}"
            )
    expected_rows = tuple(expected.metadata["physical_rows"])
    actual_rows = tuple(actual.metadata["physical_rows"])
    if len(expected_rows) != len(actual_rows):
        return {
            "semantic_mismatches": [*mismatches, "physical_row_count"],
            "raw_mismatches": [*raw_mismatches, "physical_row_count"],
            "known_normalizations": normalizations,
        }
    exact_positions = {
        1: "voucher",
        2: "date",
        3: "debit_account_code",
        6: "debit_subaccount_code",
        7: "debit_subaccount_name",
        8: "debit_tax_scope",
        9: "debit_tax_rate",
        10: "debit_tax_input_method",
        11: "debit_amount",
        13: "credit_account_code",
        16: "credit_subaccount_code",
        17: "credit_subaccount_name",
        18: "credit_tax_scope",
        19: "credit_tax_rate",
        20: "credit_tax_input_method",
        21: "credit_amount",
        23: "description",
        26: "debit_department_code",
        28: "credit_department_code",
    }
    for left, right in zip(expected_rows, actual_rows, strict=True):
        left_columns = left["source_columns"]
        right_columns = right["source_columns"]
        for position, name in exact_positions.items():
            if left_columns[position] != right_columns[position]:
                mismatches.append(name)
                raw_mismatches.append(name)
        for position, name in ((12, "debit_tax_amount"), (22, "credit_tax_amount")):
            if left_columns[position] != right_columns[position]:
                raw_mismatches.append(name)
            if not (
                left_columns[position] == right_columns[position]
                or left_columns[position] == "" and right_columns[position] == "0"
            ):
                mismatches.append(name)
                raw_mismatches.append(name)
        # JDL may replace a source display name with the target-master formal
        # name while preserving the exact account code.
        for code_position, name_position, name in (
            (3, 4, "debit_account_name"),
            (3, 5, "debit_account_formal_name"),
            (13, 14, "credit_account_name"),
            (13, 15, "credit_account_formal_name"),
        ):
            if left_columns[name_position] != right_columns[name_position]:
                raw_mismatches.append(name)
            if (
                left_columns[name_position] != right_columns[name_position]
                and (
                    left_columns[code_position] != right_columns[code_position]
                    or not right_columns[name_position]
                )
            ):
                mismatches.append(name)
        # The observed JDL re-export retains the department code but omits its
        # display name. A changed/missing department code is never normalized.
        for code_position, name_position, name in (
            (26, 27, "debit_department_name"),
            (28, 29, "credit_department_name"),
        ):
            if left_columns[name_position] != right_columns[name_position]:
                raw_mismatches.append(name)
            if (
                left_columns[name_position] != right_columns[name_position]
                and not (
                    left_columns[code_position] == right_columns[code_position]
                    and left_columns[code_position]
                    and right_columns[name_position] == ""
                )
            ):
                mismatches.append(name)
    if not expected.is_balanced() or not actual.is_balanced():
        mismatches.append("balance")
        raw_mismatches.append("balance")
    return {
        "semantic_mismatches": mismatches,
        "raw_mismatches": raw_mismatches,
        "known_normalizations": normalizations,
    }


def _select_cases(entries) -> tuple:
    selected = {}
    for entry in entries:
        tax_lines = tuple(line for line in entry.lines if line.tax_info is not None)
        if len(tax_lines) != 1:
            continue
        taxed = tax_lines[0]
        metadata = taxed.tax_info.metadata
        identity = (
            str(metadata.get("jdl_tax_scope", "")),
            str(metadata.get("jdl_tax_category", "")),
        )
        if identity not in {("売二種", "10%"), ("売五種", "10%"), ("非売上", "")}:
            continue
        key = (
            identity,
            tuple(entry.metadata.get("identifier_flags", ())),
            any(line.sub_account for line in entry.lines if line is not taxed),
            any(line.department for line in entry.lines),
            str(taxed.metadata.get("jdl_source_account_code", "")),
            str(taxed.metadata.get("jdl_source_account_formal_name", "")),
        )
        selected.setdefault(key, entry)
    return tuple(selected[key] for key in sorted(selected, key=str))


def _candidate_bytes(entries, dates: tuple[str, ...]) -> bytes:
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// JDL MIGRATION TAX SCOPE BATCH", *("" for _ in range(29))])
    writer.writerow([
        f"// 出力期間 ： {dates[0]} ～ {dates[-1]}",
        *("" for _ in range(29)),
    ])
    writer.writerow([""] * 30)
    writer.writerow(header)
    for case_index, (entry, date) in enumerate(zip(entries, dates), 1):
        rows = [list(item["source_columns"]) for item in entry.metadata["physical_rows"]]
        debit_count = sum(bool(row[3].strip()) for row in rows)
        credit_count = sum(bool(row[13].strip()) for row in rows)
        total = 1100 if debit_count == credit_count == 1 else math.lcm(
            debit_count, credit_count
        ) * 100
        for row_index, row in enumerate(rows, 1):
            row[1] = str(9900 + case_index)
            row[2] = date
            row[11] = str(total // debit_count) if row[3].strip() else "0"
            row[12] = "0"
            row[21] = str(total // credit_count) if row[13].strip() else "0"
            row[22] = "0"
            row[23] = f"JDL-MIG-TAX-SCOPE-{case_index:02d}-R{row_index}"
            writer.writerow(row)
    return stream.getvalue().encode("cp932", errors="strict")


def _privacy_safe_pattern(entry) -> str:
    taxed = next(line for line in entry.lines if line.tax_info is not None)
    metadata = taxed.tax_info.metadata
    scope = str(metadata.get("jdl_tax_scope", ""))
    category = str(metadata.get("jdl_tax_category", "")) or "blank"
    flags = "-".join(str(value) for value in entry.metadata["identifier_flags"])
    other_sub = any(line.sub_account for line in entry.lines if line is not taxed)
    department = any(line.department for line in entry.lines)
    return (
        f"{scope}/{category}|{flags}|other_sub={int(other_sub)}|"
        f"department={int(department)}"
    )

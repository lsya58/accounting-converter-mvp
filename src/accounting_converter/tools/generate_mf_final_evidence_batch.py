"""One NOT_FOR_PRODUCTION JDL Import batch for the remaining 482-journal gaps.

Each case is one real MF journal that is still blocked only by a missing JDL
capability. The rows are produced by the production mapping, tax-literal and
preflight code, so a PASS proves the exact serializer that formal output uses.
Descriptions are replaced by per-row case markers so that each case can be
compared on its own after one Import and one same-day re-export.

Usage:
  generate  --source MF.csv --company-store DIR --company-id ID --output-dir DIR
  compare   --manifest M.json --candidate C.csv --reexport R.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JDLOutputAdapter,
    JdlEvidenceProfile,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.moneyforward_roundtrip import (
    MoneyForwardRoundTripClassification,
    MoneyForwardJdlRoundTripComparator,
)
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.journal_identity import stable_journal_identity
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.profiles.known_formats import moneyforward_cloud_journal_export_observed_schema
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write_pair


class FinalEvidenceBatchError(ValueError):
    pass


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    marker: str
    pass_evidence_id: str
    purpose: str


CASES = (
    ProbeCase("2D1C", "EV482-2D1C", ev.VERIFIED_COMPOUND_SHAPES[(2, 1)],
              "2D1C row layout: taxed 課税仕入10% debit row with blank credit side"),
    ProbeCase("2D3C", "EV482-2D3C", ev.VERIFIED_COMPOUND_SHAPES[(2, 3)],
              "2D3C row layout with two taxed 課税仕入10% debit lines"),
    ProbeCase("10D9C", "EV482-10D9C", ev.VERIFIED_COMPOUND_SHAPES[(10, 9)],
              "10D9C grouping, 10 physical rows, row order and row descriptions"),
    ProbeCase("S10ROUND", "EV482-S10ROUND", "EVID-MF-JDL-35-5-SALES10-ROUNDING-6121-ROUNDTRIP-001",
              "課税売上10% on 6121 where floor and half-up differ: explicit floor tax kept"),
    ProbeCase("S10-9251", "EV482-S10-9251", "EVID-MF-JDL-35-5-SALES10-9251-ROUNDTRIP-001",
              "課税売上10% literal on a second sales account 9251"),
)
PROBE_SHAPES = frozenset({(10, 9, 10)})


def _shape(entry: JournalEntry) -> tuple[int, int]:
    debit = sum(line.side is Side.DEBIT for line in entry.lines)
    return debit, len(entry.lines) - debit


def _select(case_id: str, candidates) -> tuple[JournalEntry, JournalEntry, tuple[str, ...]]:
    for source, mapped, gaps in candidates:
        shape = _shape(source)
        taxes = {line.tax_info.category for line in source.lines if line.tax_info}
        # Trade partner text is irrelevant here: probe descriptions are case markers.
        if case_id == "2D1C" and shape == (2, 1) and gaps == {"SHAPE_UNVERIFIED_IN_TAX_CONTEXT"}:
            return source, mapped, ()
        if case_id == "2D3C" and shape == (2, 3):
            return source, mapped, ()
        if case_id == "10D9C" and shape == (10, 9):
            return source, mapped, ()
        if (
            case_id == "S10ROUND" and shape == (1, 1)
            and gaps == {"TAX_AMOUNT_ROUNDING_UNVERIFIED"}
        ):
            return source, mapped, ()
        if (
            case_id == "S10-9251" and shape == (1, 1) and ev.MF_SALES_10 in taxes
            and gaps == {"TAX_ACCOUNT_UNVERIFIED"}
            and all(
                ev._tax_rounding_is_unambiguous(line.amount)
                for line in source.lines if line.tax_info and line.tax_info.category == ev.MF_SALES_10
            )
        ):
            return source, mapped, ()
    raise FinalEvidenceBatchError(f"no current journal is blocked only by case {case_id}")


def _probe_entry(case: ProbeCase, source: JournalEntry, mapped: JournalEntry, probe_date: date, context):
    """Production tax literals, case markers, and (10D9C only) a probe-only subaccount."""
    substitutions = []
    lines = list(mapped.lines)
    if case.case_id == "10D9C":
        for index, line in enumerate(lines):
            if line.sub_account:
                continue
            parent = next(
                (item for item in context.account_master if item.mapping_value == line.account), None
            )
            options = sorted(
                (item for item in context.subaccounts
                 if parent is not None and item.parent_account_code == parent.target_master_code),
                key=lambda item: item.output_code,
            )
            if not options:
                continue
            used = {other.sub_account for other in lines if other.account == line.account}
            choice = next((item for item in options if item.mapping_value not in used), options[0])
            lines[index] = replace(line, sub_account=choice.mapping_value)
            substitutions.append({
                "line_index": index,
                "parent_account_code": parent.target_master_code,
                "probe_subaccount_code": choice.output_code,
                "reason": "JDL rejects blank subaccount; shape probe only, not the Human まとめ先 choice",
            })
    mapped = replace(mapped, lines=lines)
    literal = ev.apply_tax_literals(source, mapped, f"PENDING:{case.pass_evidence_id}")
    rows = sorted({line.metadata["moneyforward_source_row_number"] for line in literal.lines})
    markers = {row: f"{case.marker}-R{position}" for position, row in enumerate(rows, start=1)}
    if len(rows) == 1:
        markers = {rows[0]: case.marker}
    marked_lines = [
        replace(line, metadata={
            **line.metadata,
            "moneyforward_description": markers[line.metadata["moneyforward_source_row_number"]],
        })
        for line in literal.lines
    ]
    profile = (
        JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111
        if case.case_id.startswith("S10")
        else JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL
    )
    entry = replace(
        literal,
        id=f"probe:{case.case_id}",
        date=probe_date,
        lines=marked_lines,
        description=markers[rows[0]] if len(rows) == 1 else None,
        metadata={
            **literal.metadata,
            JDL_OUTPUT_METADATA_KEY: profile.value,
            "moneyforward_descriptions": tuple(
                {"row_number": row, "value": markers[row]} for row in rows
            ),
        },
    )
    return entry, substitutions


def generate(source: Path, company_store: Path, company_id: str, output_dir: Path, *, probe_date: str = "20260529"):
    probe_day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    profiles = ConversionProfileStore(company_store / "profiles")
    companies = CompanySettingStore(company_store / "companies", profiles)
    resolved = companies.resolve(company_id)
    if not resolved.available or resolved.profile is None or resolved.context is None:
        raise FinalEvidenceBatchError("CompanySetting is not available")
    profile, context = resolved.profile, resolved.context
    if not ev.context_is_verified(context):
        raise FinalEvidenceBatchError("current tax context is not the verified 税抜・一括比例配分 Context")
    schema = moneyforward_cloud_journal_export_observed_schema()
    input_profile = FormatProfile("Money Forward", "Money Forward クラウド会計", "UNKNOWN", schema.identity.stable_key, "cp932")
    entries = tuple(MoneyForwardInputAdapter().read(source, input_profile))
    mapping = MappingEngine(mapping_rule_set_from_profile(profile)).apply(entries)
    candidates = []
    for source_entry, mapped_entry in zip(entries, mapping.entries, strict=True):
        result = ev.match_evidence_for_occurrence(source_entry, mapped_entry, context, profile)
        if result.evidence is None:
            gaps = set(result.mismatch_fields) - {
                "ACCOUNT_CODE_MISMATCH", "SUBACCOUNT_CODE_MISMATCH", "TAX_CATEGORY_MISMATCH",
                "SHAPE_MISMATCH", "EVIDENCE_SCOPE_CHANGED_BY_MASTER",
            }
            candidates.append((source_entry, mapped_entry, gaps))
    probe_entries, manifest_cases = [], []
    for case in CASES:
        source_entry, mapped_entry, _ = _select(case.case_id, candidates)
        entry, substitutions = _probe_entry(case, source_entry, mapped_entry, probe_day, context)
        probe_entries.append(entry)
        manifest_cases.append({
            "case_id": case.case_id,
            "marker": case.marker,
            "purpose": case.purpose,
            "evidence_id_on_pass": case.pass_evidence_id,
            "shape": "%dD%dC" % _shape(source_entry),
            "physical_rows": len({line.metadata["moneyforward_source_row_number"] for line in entry.lines}),
            "source_journal_content_sha256": stable_journal_identity(source_entry),
            "probe_substitutions": substitutions,
        })
    preflight = JdlOutputPreflight(context, probe_pending_shapes=PROBE_SHAPES).evaluate(
        probe_entries, jdl_ibex_35_5_output_profile()
    )
    if not preflight.supported or preflight.plan is None:
        raise FinalEvidenceBatchError(
            "probe preflight failed: " + ", ".join(sorted({item.rule_id for item in preflight.validation_results}))
        )
    rows = tuple(row.columns() for row in preflight.plan.rows)
    JDLOutputAdapter._validate_field_lengths(rows)
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    if payload.decode("cp932") != buffer.getvalue():
        raise FinalEvidenceBatchError("CP932 round-trip changed the probe")
    candidate = output_dir / f"mf_482_final_evidence_batch_{probe_date}_NOT_FOR_PRODUCTION.csv"
    manifest_path = output_dir / f"mf_482_final_evidence_batch_{probe_date}.manifest.private.json"
    manifest = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "target": "JDL IBEX 出納帳 35.5",
        "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "import_period": {"start": probe_date, "end": probe_date},
        "journal_count": len(probe_entries),
        "physical_row_count": len(rows),
        "candidate_file": candidate.name,
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "strict_comparison_required": True,
        "cases": manifest_cases,
    }
    _atomic_write_pair(
        (candidate, payload),
        (manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    )
    return candidate, manifest_path, manifest


def compare(manifest_path: Path, candidate: Path, reexport: Path) -> dict[str, object]:
    """Strict comparison per case, so one FAIL does not hide the others."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_groups = _groups(candidate)
    reexport_groups = _groups(reexport)
    normalizations = frozenset(
        (side, row[account], row[code].zfill(4), row[name])
        for group in candidate_groups.values() for row in group
        for side, account, code, name in (("DEBIT", 3, 6, 7), ("CREDIT", 13, 16, 17))
        if row[code]
    )
    comparator = MoneyForwardJdlRoundTripComparator(numeric_subaccount_normalizations=normalizations)
    results = {}
    for case in manifest["cases"]:
        marker = case["marker"]
        if marker not in candidate_groups:
            raise FinalEvidenceBatchError(f"candidate lacks case {marker}")
        if marker not in reexport_groups:
            results[case["case_id"]] = {"passed": False, "reason": "MISSING_IN_REEXPORT"}
            continue
        with _temporary_pair(candidate_groups[marker], reexport_groups[marker]) as (left, right):
            report = comparator.compare(left, right)
        unexpected = [
            {"row": item.row_index, "field": item.field, "classification": item.classification.value}
            for item in report.differences
            if item.classification in {
                MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE,
                MoneyForwardRoundTripClassification.MISSING_ROW,
                MoneyForwardRoundTripClassification.EXTRA_ROW,
            }
        ]
        results[case["case_id"]] = {
            "passed": report.passed,
            "rows": [report.candidate_row_count, report.reexport_row_count],
            "classification_counts": report.classification_counts,
            "unexpected": unexpected,
            "evidence_id_on_pass": case["evidence_id_on_pass"],
        }
    extra = sorted(set(reexport_groups) - set(candidate_groups))
    return {"cases": results, "unexpected_reexport_groups": extra}


def _groups(path: Path) -> dict[str, list[list[str]]]:
    text = path.read_bytes().decode("cp932", errors="strict")
    groups: dict[str, list[list[str]]] = {}
    current: list[list[str]] = []
    for row in csv.reader(io.StringIO(text, newline="")):
        if not row or row[0].startswith("//") or row[0] in {"識別フラグ"} or len(row) != 30:
            continue
        current.append(row)
        if row[0] in {"1111", "1101", "1000"} or row[0].endswith("1"):
            marker = current[0][23]
            key = marker.rsplit("-R", 1)[0] if "-R" in marker else marker
            groups[key] = current
            current = []
    return groups


class _temporary_pair:
    def __init__(self, left_rows, right_rows) -> None:
        self.rows = (left_rows, right_rows)

    def __enter__(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        paths = []
        for index, rows in enumerate(self.rows):
            buffer = io.StringIO(newline="")
            csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
            path = Path(self.directory.name) / f"{index}.csv"
            path.write_bytes(buffer.getvalue().encode("cp932"))
            paths.append(path)
        return tuple(paths)

    def __exit__(self, *exc) -> None:
        self.directory.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--source", type=Path, required=True)
    gen.add_argument("--company-store", type=Path, required=True)
    gen.add_argument("--company-id", required=True)
    gen.add_argument("--output-dir", type=Path, required=True)
    gen.add_argument("--probe-date", default="20260529")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--manifest", type=Path, required=True)
    cmp_.add_argument("--candidate", type=Path, required=True)
    cmp_.add_argument("--reexport", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        candidate, manifest_path, manifest = generate(
            args.source, args.company_store, args.company_id, args.output_dir, probe_date=args.probe_date
        )
        print(json.dumps({"candidate": str(candidate), "manifest": str(manifest_path),
                          "journals": manifest["journal_count"], "rows": manifest["physical_row_count"]},
                         ensure_ascii=False))
    else:
        print(json.dumps(compare(args.manifest, args.candidate, args.reexport), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

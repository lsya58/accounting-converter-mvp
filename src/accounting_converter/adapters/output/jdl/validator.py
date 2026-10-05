from __future__ import annotations

import csv
import io
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from accounting_converter.application.output_validation import (
    OutputValidationResult,
    output_validation_error,
)
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)

from .models import JDL_OUTPUT_FORMAT_ID, JdlEvidenceProfile, JdlTargetContext
from .preflight import (
    EVIDENCE_IDS,
    MULTIGROUP_EVIDENCE_ID,
    SIMPLE_PLUS_SIMPLE_UNTESTED_GATE_ID,
    JdlOutputPreflight,
)


class JDLOutputValidator:
    def __init__(self, context: JdlTargetContext) -> None:
        self._preflight = JdlOutputPreflight(context)

    def validate(
        self,
        path: Path,
        expected_entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> OutputValidationResult:
        preflight = self._preflight.evaluate(expected_entries, profile)
        if not preflight.supported or preflight.plan is None:
            return OutputValidationResult.failed(preflight.validation_results)
        expected_rows = tuple(row.columns() for row in preflight.plan.rows)
        errors = []
        try:
            raw = path.read_bytes()
        except OSError:
            return OutputValidationResult.failed(
                [output_validation_error("JDL-VAL-READ", "JDL出力を再読込できません。", "output_path", path.name)]
            )

        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            errors.append(output_validation_error("JDL-VAL-BOM", "BOMを検出しました。", "bom", True))
        without_crlf = raw.replace(b"\r\n", b"")
        if b"\n" in without_crlf or b"\r" in without_crlf:
            errors.append(output_validation_error("JDL-VAL-LINE-END", "CRLF以外の改行を検出しました。", "line_ending", "mixed"))
        try:
            text = raw.decode("cp932", errors="strict")
            if text.encode("cp932", errors="strict") != raw:
                raise UnicodeError("CP932 bytes did not round-trip")
        except UnicodeError:
            return OutputValidationResult.failed(
                [output_validation_error("JDL-VAL-CP932", "CP932 round-tripに失敗しました。", "encoding", "invalid")]
            )
        try:
            parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error:
            return OutputValidationResult.failed(
                [output_validation_error("JDL-VAL-CSV", "CSVを構文解析できません。", "csv", "malformed")]
            )

        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        if not parsed or tuple(parsed[0]) != header:
            errors.append(output_validation_error("JDL-VAL-HEADER", "先頭行が公式30列headerと一致しません。", "header", "mismatch"))
        actual_rows = tuple(tuple(row) for row in parsed[1:]) if parsed else ()
        if any(len(row) != 30 for row in actual_rows):
            errors.append(output_validation_error("JDL-VAL-COLUMNS", "30列ではないdata rowがあります。", "column_count", dict(Counter(map(len, actual_rows)))))
        if actual_rows != expected_rows:
            errors.append(output_validation_error("JDL-VAL-PARSEBACK", "再読込した行がEvidence planと一致しません。", "rows", "mismatch"))

        debit_total, credit_total = self._totals(actual_rows, errors)
        expected_debit = sum((entry.debit_total() for entry in expected_entries), Decimal("0"))
        expected_credit = sum((entry.credit_total() for entry in expected_entries), Decimal("0"))
        if debit_total != expected_debit or credit_total != expected_credit:
            errors.append(output_validation_error("JDL-VAL-TOTAL", "出力合計が期待値と一致しません。", "amount", "mismatch"))

        evidence_profiles = tuple(EVIDENCE_IDS[item] for item in preflight.plan.evidence_profiles)
        if len(preflight.plan.evidence_profiles) == 2:
            combination_id = (
                SIMPLE_PLUS_SIMPLE_UNTESTED_GATE_ID
                if preflight.plan.evidence_profiles
                == (JdlEvidenceProfile.BASIC_1111,) * 2
                else MULTIGROUP_EVIDENCE_ID
            )
            evidence_profiles = (*evidence_profiles, combination_id)
        return OutputValidationResult(
            success=not errors,
            record_count=len(actual_rows),
            journal_count=preflight.plan.journal_count,
            debit_total=debit_total,
            credit_total=credit_total,
            validation_results=tuple(errors),
            unsupported_profile_count=0,
            evidence_profiles=evidence_profiles,
            output_schema_identity=JDL_OUTPUT_FORMAT_ID,
        )

    @staticmethod
    def _totals(rows: tuple[tuple[str, ...], ...], errors: list) -> tuple[Decimal, Decimal]:
        debit = Decimal("0")
        credit = Decimal("0")
        for row in rows:
            if len(row) != 30:
                continue
            try:
                debit += Decimal(row[11])
                credit += Decimal(row[21])
            except InvalidOperation:
                errors.append(output_validation_error("JDL-VAL-NUMERIC", "金額fieldを数値として解釈できません。", "amount", "invalid"))
        return debit, credit

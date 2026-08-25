from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.application.output_validation import (
    OutputValidationResult,
    output_validation_error,
)
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult


DEMO_HEADER = (
    "id",
    "date",
    "debit_account",
    "debit_amount",
    "credit_account",
    "credit_amount",
    "description",
    "structure",
)


class DemoStructuralValidator:
    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        _ = profile
        if not path.exists():
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="DEMO-FILE-NOT-FOUND",
                    message="入力ファイルが存在しません。",
                    field="input_path",
                )
            ]
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows or tuple(rows[0]) != DEMO_HEADER:
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="DEMO-STRUCTURAL-HEADER",
                    message="Demo CSVのヘッダーが一致しません。",
                    field="header",
                )
            ]
        results: list[ValidationResult] = []
        for row_number, row in enumerate(rows[1:], start=2):
            if len(row) != len(DEMO_HEADER):
                results.append(
                    ValidationResult(
                        severity=Severity.ERROR,
                        rule_id="DEMO-STRUCTURAL-COLUMNS",
                        message="Demo CSVの列数が一致しません。",
                        source_reference=SourceReference(path.name, row_number),
                        field="column_count",
                        input_value=len(row),
                    )
                )
        return results


class DemoInputAdapter(InputAdapter):
    def supports(self, path: Path, profile: FormatProfile) -> bool:
        _ = profile
        return path.suffix.lower() == ".csv"

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        _ = profile
        with path.open("r", encoding="utf-8", newline="") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        _ = profile
        entries: list[JournalEntry] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=2):
                entry_id = row["id"]
                source = SourceReference(path.name, row_number, entry_id)
                debit_amount = Decimal(row["debit_amount"])
                credit_amount = Decimal(row["credit_amount"])
                if row.get("structure") == "compound":
                    first_debit = debit_amount / Decimal("2")
                    debit_lines = [
                        JournalLine(
                            side=Side.DEBIT,
                            account=row["debit_account"],
                            amount=first_debit,
                            source_reference=source,
                        ),
                        JournalLine(
                            side=Side.DEBIT,
                            account=row["debit_account"],
                            amount=debit_amount - first_debit,
                            source_reference=source,
                        ),
                    ]
                else:
                    debit_lines = [
                        JournalLine(
                            side=Side.DEBIT,
                            account=row["debit_account"],
                            amount=debit_amount,
                            source_reference=source,
                        )
                    ]
                entries.append(
                    JournalEntry(
                        id=entry_id,
                        source_reference=source,
                        date=date.fromisoformat(row["date"]),
                        description=row.get("description") or None,
                        lines=[
                            *debit_lines,
                            JournalLine(
                                side=Side.CREDIT,
                                account=row["credit_account"],
                                amount=credit_amount,
                                source_reference=source,
                            ),
                        ],
                    )
                )
        return entries


class DemoOutputAdapter(OutputAdapter):
    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        _ = profile
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("id", "date", "debit_total", "credit_total", "line_count"))
            for entry in entries:
                writer.writerow(
                    (
                        entry.id,
                        entry.date.isoformat(),
                        str(entry.debit_total()),
                        str(entry.credit_total()),
                        len(entry.lines),
                    )
                )


class DemoOutputValidator:
    def __init__(self, force_failure: bool = False) -> None:
        self.force_failure = force_failure

    def validate(
        self,
        path: Path,
        expected_entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> OutputValidationResult:
        _ = profile
        if self.force_failure:
            return OutputValidationResult.failed(
                [
                    output_validation_error(
                        "DEMO-OUTPUT-FORCED-FAILURE",
                        "Demo出力検証を失敗させました。",
                        "output",
                        path.name,
                    )
                ]
            )
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            return OutputValidationResult.failed(
                [
                    output_validation_error(
                        "DEMO-OUTPUT-READ",
                        "Demo出力CSVを再読込できません。",
                        "output_path",
                        path.name,
                    )
                ]
            )

        debit_total = sum((Decimal(row["debit_total"]) for row in rows), Decimal("0"))
        credit_total = sum((Decimal(row["credit_total"]) for row in rows), Decimal("0"))
        expected_debit = sum(
            (entry.debit_total() for entry in expected_entries),
            Decimal("0"),
        )
        expected_credit = sum(
            (entry.credit_total() for entry in expected_entries),
            Decimal("0"),
        )
        results: list[ValidationResult] = []
        if len(rows) != len(expected_entries):
            results.append(
                output_validation_error(
                    "DEMO-OUTPUT-JOURNAL-COUNT",
                    "出力仕訳件数が期待値と一致しません。",
                    "journal_count",
                    {"actual": len(rows), "expected": len(expected_entries)},
                )
            )
        if debit_total != expected_debit or credit_total != expected_credit:
            results.append(
                output_validation_error(
                    "DEMO-OUTPUT-TOTAL",
                    "出力金額合計が期待値と一致しません。",
                    "amount",
                    {
                        "actual_debit": str(debit_total),
                        "expected_debit": str(expected_debit),
                        "actual_credit": str(credit_total),
                        "expected_credit": str(expected_credit),
                    },
                )
            )
        return OutputValidationResult(
            success=not results,
            record_count=len(rows),
            journal_count=len(rows),
            debit_total=debit_total,
            credit_total=credit_total,
            validation_results=tuple(results),
        )


class ExplodingDemoOutputAdapter(DemoOutputAdapter):
    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        super().write(entries, destination, profile)
        raise RuntimeError("demo output failure")

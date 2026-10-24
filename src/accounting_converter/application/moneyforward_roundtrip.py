from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from accounting_converter.adapters.input.jdl.observed_parser import JdlMigrationParser


class MoneyForwardRoundTripClassification(str, Enum):
    EXACT_PRESERVED = "EXACT_PRESERVED"
    EXPECTED_ACCOUNT_MAPPING = "EXPECTED_ACCOUNT_MAPPING"
    EXPECTED_SUBACCOUNT_MAPPING = "EXPECTED_SUBACCOUNT_MAPPING"
    EXPECTED_DEFAULT_SUBACCOUNT = "EXPECTED_DEFAULT_SUBACCOUNT"
    EXPECTED_TAX_MAPPING = "EXPECTED_TAX_MAPPING"
    EXPECTED_TRADE_PARTNER_DESCRIPTION = "EXPECTED_TRADE_PARTNER_DESCRIPTION"
    EXPECTED_JDL_CANONICAL_NORMALIZATION = "EXPECTED_JDL_CANONICAL_NORMALIZATION"
    UNEXPECTED_CHANGE = "UNEXPECTED_CHANGE"
    MISSING_ROW = "MISSING_ROW"
    EXTRA_ROW = "EXTRA_ROW"


@dataclass(frozen=True)
class MoneyForwardRoundTripDifference:
    classification: MoneyForwardRoundTripClassification
    row_index: int | None
    field: str


@dataclass(frozen=True)
class MoneyForwardRoundTripReport:
    candidate_journal_count: int
    reexport_journal_count: int
    candidate_row_count: int
    reexport_row_count: int
    differences: tuple[MoneyForwardRoundTripDifference, ...]

    @property
    def passed(self) -> bool:
        failures = {
            MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE,
            MoneyForwardRoundTripClassification.MISSING_ROW,
            MoneyForwardRoundTripClassification.EXTRA_ROW,
        }
        return not any(item.classification in failures for item in self.differences)

    @property
    def classification_counts(self) -> dict[str, int]:
        counts = Counter(item.classification.value for item in self.differences)
        return dict(sorted(counts.items()))


class MoneyForwardJdlRoundTripComparator:
    """Strict generated-JDL to real-JDL re-export semantic comparator."""

    _FIELDS = (
        "flag",
        "voucher",
        "date",
        "debit_account_code",
        "debit_account_name",
        "debit_account_formal_name",
        "debit_subaccount_code",
        "debit_subaccount_name",
        "debit_tax_scope",
        "debit_tax_category",
        "debit_tax_input_method",
        "debit_amount",
        "debit_tax_amount",
        "credit_account_code",
        "credit_account_name",
        "credit_account_formal_name",
        "credit_subaccount_code",
        "credit_subaccount_name",
        "credit_tax_scope",
        "credit_tax_category",
        "credit_tax_input_method",
        "credit_amount",
        "credit_tax_amount",
        "description",
        "reserved_25",
        "reserved_26",
        "debit_department_code",
        "debit_department_name",
        "credit_department_code",
        "credit_department_name",
    )

    def compare(self, candidate_path: Path, reexport_path: Path) -> MoneyForwardRoundTripReport:
        parser = JdlMigrationParser()
        candidate = parser.parse_path(candidate_path)
        reexport = parser.parse_path(reexport_path)
        candidate_rows = self._rows(candidate.entries)
        reexport_rows = self._rows(reexport.entries)
        differences: list[MoneyForwardRoundTripDifference] = []

        shared = min(len(candidate_rows), len(reexport_rows))
        for index in range(shared):
            expected = candidate_rows[index]
            actual = reexport_rows[index]
            row_differences = self._compare_row(index + 1, expected, actual)
            if not row_differences:
                differences.append(
                    MoneyForwardRoundTripDifference(
                        MoneyForwardRoundTripClassification.EXACT_PRESERVED,
                        index + 1,
                        "row",
                    )
                )
            else:
                differences.extend(row_differences)
        differences.extend(
            MoneyForwardRoundTripDifference(
                MoneyForwardRoundTripClassification.MISSING_ROW,
                index + 1,
                "row",
            )
            for index in range(shared, len(candidate_rows))
        )
        differences.extend(
            MoneyForwardRoundTripDifference(
                MoneyForwardRoundTripClassification.EXTRA_ROW,
                index + 1,
                "row",
            )
            for index in range(shared, len(reexport_rows))
        )
        if len(candidate.entries) != len(reexport.entries):
            differences.append(
                MoneyForwardRoundTripDifference(
                    MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE,
                    None,
                    "journal_grouping",
                )
            )
        return MoneyForwardRoundTripReport(
            candidate_journal_count=len(candidate.entries),
            reexport_journal_count=len(reexport.entries),
            candidate_row_count=len(candidate_rows),
            reexport_row_count=len(reexport_rows),
            differences=tuple(differences),
        )

    def _compare_row(
        self,
        row_index: int,
        expected: tuple[str, ...],
        actual: tuple[str, ...],
    ) -> tuple[MoneyForwardRoundTripDifference, ...]:
        differences: list[MoneyForwardRoundTripDifference] = []
        for column, (before, after) in enumerate(zip(expected, actual, strict=True)):
            if before == after:
                continue
            field = self._FIELDS[column]
            classification = (
                MoneyForwardRoundTripClassification.EXPECTED_JDL_CANONICAL_NORMALIZATION
                if self._known_normalization(column, before, after, expected, actual)
                else MoneyForwardRoundTripClassification.UNEXPECTED_CHANGE
            )
            differences.append(
                MoneyForwardRoundTripDifference(classification, row_index, field)
            )
        return tuple(differences)

    @staticmethod
    def _known_normalization(
        column: int,
        before: str,
        after: str,
        expected: tuple[str, ...],
        actual: tuple[str, ...],
    ) -> bool:
        if column == 1:
            return not before and bool(after)
        if column in {5, 15}:
            account_base = 3 if column == 5 else 13
            return (
                not before
                and bool(after)
                and expected[account_base] == actual[account_base]
                and expected[account_base + 1] == actual[account_base + 1]
            )
        if column in {12, 22}:
            return before in {"", "0"} and after in {"", "0"}
        if column in {26, 28}:
            name_column = column + 1
            return (
                before in {"", "0"}
                and after in {"", "0"}
                and expected[name_column] == actual[name_column]
            )
        return False

    @staticmethod
    def _rows(entries) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(row["source_columns"])
            for entry in entries
            for row in entry.metadata.get("physical_rows", ())
        )

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application.moneyforward_jdl_loss import (
    MoneyForwardToJdlLossRule,
)
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
)


MF_EVIDENCE_BACKED_SHAPES = frozenset({(1, 1), (2, 2)})
_SUPPORTED_1D1C_SOURCE_TAX_IDENTITIES = frozenset(
    {
        ("対象外",),
        ("対象外", "課税仕入 10%"),
        ("対象外", "課税売上 10%"),
        ("対象外", "非課税仕入"),
        ("対象外", "非課税売上"),
    }
)
_SUPPORTED_2D2C_SOURCE_TAX_IDENTITIES = ("対象外", "課税仕入 10%")


@dataclass(frozen=True)
class MoneyForwardBlockerPattern:
    pattern_id: str
    journal_count: int
    physical_row_count: int
    debit_count: int
    credit_count: int
    tax_identities: tuple[str, ...]
    has_subaccount: bool
    has_trade_partner: bool
    has_department: bool
    has_tag: bool
    has_memo: bool
    has_invoice: bool
    has_multiple_descriptions: bool
    blocker_code: str


@dataclass(frozen=True)
class MoneyForwardBatchCandidate:
    start_date: date
    end_date: date
    journal_count: int
    physical_row_count: int
    tax_line_count: int
    compound_journal_count: int
    subaccount_journal_count: int
    trade_partner_journal_count: int
    blocker_count: int


@dataclass(frozen=True)
class MoneyForwardCoverageAudit:
    logical_journal_count: int
    physical_row_count: int
    start_date: date
    end_date: date
    unique_account_count: int
    unique_subaccount_count: int
    shape_distribution: tuple[tuple[str, int], ...]
    tax_distribution: tuple[tuple[str, int], ...]
    trade_partner_journal_count: int
    department_journal_count: int
    tag_journal_count: int
    memo_journal_count: int
    invoice_journal_count: int
    evidence_backed_count: int
    unsupported_count: int
    blocker_patterns: tuple[MoneyForwardBlockerPattern, ...]
    batch_candidates: tuple[MoneyForwardBatchCandidate, ...]


class MoneyForwardReadyBatchAuditor:
    """Privacy-safe source audit before CompanySetting formal preflight."""

    def read(self, source_path: Path) -> tuple[JournalEntry, ...]:
        schema = moneyforward_cloud_journal_export_observed_schema()
        profile = FormatProfile(
            software="Money Forward",
            product="Money Forward クラウド会計",
            version="UNKNOWN",
            format_id=schema.identity.stable_key,
            encoding="cp932",
        )
        return tuple(MoneyForwardInputAdapter().read(source_path, profile))

    def audit(self, entries: Sequence[JournalEntry]) -> MoneyForwardCoverageAudit:
        if not entries:
            raise ValueError("Money Forward audit requires at least one journal")
        shape_counts: Counter[str] = Counter()
        tax_counts: Counter[str] = Counter()
        accounts: set[tuple[str, str]] = set()
        subaccounts: set[tuple[str, str, str]] = set()
        patterns: defaultdict[tuple[object, ...], list[JournalEntry]] = defaultdict(list)
        physical_rows = 0
        evidence_backed = 0

        for entry in entries:
            debit_count, credit_count = self._shape(entry)
            shape_counts[f"{debit_count}D{credit_count}C"] += 1
            physical_rows += self._physical_row_count(entry)
            for line in entry.lines:
                accounts.add((line.side.value, line.account))
                if line.sub_account:
                    subaccounts.add((line.side.value, line.account, line.sub_account))
                if line.tax_info and line.tax_info.category:
                    tax_counts[line.tax_info.category] += 1
            if self._is_evidence_backed(entry):
                evidence_backed += 1
            else:
                key = self._pattern_key(entry)
                patterns[key].append(entry)

        blocker_patterns = tuple(
            self._blocker_pattern(index, key, grouped)
            for index, (key, grouped) in enumerate(
                sorted(patterns.items(), key=lambda item: str(item[0])), 1
            )
        )
        dates = tuple(entry.date for entry in entries)
        return MoneyForwardCoverageAudit(
            logical_journal_count=len(entries),
            physical_row_count=physical_rows,
            start_date=min(dates),
            end_date=max(dates),
            unique_account_count=len(accounts),
            unique_subaccount_count=len(subaccounts),
            shape_distribution=tuple(sorted(shape_counts.items())),
            tax_distribution=tuple(sorted(tax_counts.items())),
            trade_partner_journal_count=self._count(entries, self._has_trade_partner),
            department_journal_count=self._count(
                entries, lambda entry: any(line.department for line in entry.lines)
            ),
            tag_journal_count=self._count(
                entries, lambda entry: bool(entry.metadata.get("moneyforward_tags"))
            ),
            memo_journal_count=self._count(
                entries, lambda entry: bool(entry.metadata.get("moneyforward_memos"))
            ),
            invoice_journal_count=self._count(
                entries,
                lambda entry: any(
                    line.tax_info and line.tax_info.invoice_classification
                    for line in entry.lines
                ),
            ),
            evidence_backed_count=evidence_backed,
            unsupported_count=len(entries) - evidence_backed,
            blocker_patterns=blocker_patterns,
            batch_candidates=self._batch_candidates(entries),
        )

    def extract_candidate(
        self,
        source_path: Path,
        output_path: Path,
        *,
        start_date: date,
        end_date: date,
    ) -> MoneyForwardBatchCandidate:
        if output_path.exists():
            raise FileExistsError("candidate output already exists")
        if source_path.resolve(strict=False) == output_path.resolve(strict=False):
            raise ValueError("source and candidate output must differ")
        entries = self.read(source_path)
        selected = tuple(
            entry for entry in entries if start_date <= entry.date <= end_date
        )
        if not selected:
            raise ValueError("candidate date range contains no journals")
        blockers = tuple(entry for entry in selected if not self._is_candidate_safe(entry))
        if blockers:
            raise ValueError("candidate date range contains source-scope blockers")

        transaction_numbers = {
            entry.source_reference.source_journal_id for entry in selected
        }
        raw = source_path.read_bytes()
        text = raw.decode("cp932", errors="strict")
        line_ending = "\r\n" if "\r\n" in text else "\n"
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        kept = [rows[0], *(row for row in rows[1:] if row[0] in transaction_numbers)]
        quoting = csv.QUOTE_ALL if text.startswith('"') else csv.QUOTE_MINIMAL
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator=line_ending, quoting=quoting).writerows(kept)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(buffer.getvalue().encode("cp932", errors="strict"))

        reparsed = self.read(output_path)
        if tuple(self._entry_signature(item) for item in reparsed) != tuple(
            self._entry_signature(item) for item in selected
        ):
            output_path.unlink(missing_ok=True)
            raise ValueError("candidate extraction changed journal semantics")
        return self._candidate(selected)

    def _batch_candidates(
        self, entries: Sequence[JournalEntry]
    ) -> tuple[MoneyForwardBatchCandidate, ...]:
        by_date: defaultdict[date, list[JournalEntry]] = defaultdict(list)
        for entry in entries:
            by_date[entry.date].append(entry)
        groups: list[list[JournalEntry]] = []
        current: list[JournalEntry] = []
        for current_date in sorted(by_date):
            daily = by_date[current_date]
            if all(self._is_candidate_safe(entry) for entry in daily):
                current.extend(daily)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return tuple(
            sorted(
                (self._candidate(group) for group in groups),
                key=lambda item: (
                    item.journal_count,
                    item.physical_row_count,
                    item.start_date,
                ),
                reverse=True,
            )
        )

    def _candidate(self, entries: Sequence[JournalEntry]) -> MoneyForwardBatchCandidate:
        return MoneyForwardBatchCandidate(
            start_date=min(entry.date for entry in entries),
            end_date=max(entry.date for entry in entries),
            journal_count=len(entries),
            physical_row_count=sum(self._physical_row_count(entry) for entry in entries),
            tax_line_count=sum(
                1
                for entry in entries
                for line in entry.lines
                if line.tax_info and line.tax_info.category
            ),
            compound_journal_count=sum(entry.is_compound() for entry in entries),
            subaccount_journal_count=self._count(
                entries, lambda entry: any(line.sub_account for line in entry.lines)
            ),
            trade_partner_journal_count=self._count(entries, self._has_trade_partner),
            blocker_count=0,
        )

    def _is_candidate_safe(self, entry: JournalEntry) -> bool:
        if not self._is_evidence_backed(entry):
            return False
        loss_results = MoneyForwardToJdlLossRule().validate(entry)
        if loss_results:
            non_partner = [
                item
                for item in loss_results
                if item.field != "trade_partner"
            ]
            if non_partner:
                return False
        if any(
            len(item["value"]) > 32
            or not self._is_cp932(item["value"])
            for item in entry.metadata.get("moneyforward_descriptions", ())
        ):
            return False
        return self._trade_partner_scope_supported(entry)

    def _is_evidence_backed(self, entry: JournalEntry) -> bool:
        shape = self._shape(entry)
        taxes = tuple(
            sorted(
                {
                    line.tax_info.category
                    for line in entry.lines
                    if line.tax_info and line.tax_info.category
                }
            )
        )
        if shape == (1, 1):
            return taxes in _SUPPORTED_1D1C_SOURCE_TAX_IDENTITIES
        if shape == (2, 2):
            return taxes == _SUPPORTED_2D2C_SOURCE_TAX_IDENTITIES
        return False

    def _trade_partner_scope_supported(self, entry: JournalEntry) -> bool:
        partners = [
            line for line in entry.lines if line.metadata.get("moneyforward_trade_partner")
        ]
        if not partners:
            return True
        identities = {
            str(line.metadata["moneyforward_trade_partner"]) for line in partners
        }
        sides = {line.side for line in partners}
        if len(identities) != 1 or len(sides) != 1:
            return False
        if self._shape(entry) not in {(1, 1), (2, 2)}:
            return False
        partner = next(iter(identities))
        if self._shape(entry) == (2, 2):
            description = partners[0].metadata.get("moneyforward_description")
            if not isinstance(description, str):
                return False
        else:
            description = entry.description or ""
        target = (
            f"{description} / 取引先:{partner}"
            if description
            else f"取引先:{partner}"
        )
        return len(target) <= 32 and self._is_cp932(target)

    def _pattern_key(self, entry: JournalEntry) -> tuple[object, ...]:
        debit_count, credit_count = self._shape(entry)
        return (
            debit_count,
            credit_count,
            tuple(
                sorted(
                    {
                        line.tax_info.category
                        for line in entry.lines
                        if line.tax_info and line.tax_info.category
                    }
                )
            ),
            any(line.sub_account for line in entry.lines),
            self._has_trade_partner(entry),
            any(line.department for line in entry.lines),
            bool(entry.metadata.get("moneyforward_tags")),
            bool(entry.metadata.get("moneyforward_memos")),
            any(
                line.tax_info and line.tax_info.invoice_classification
                for line in entry.lines
            ),
            len(
                {
                    item["value"]
                    for item in entry.metadata.get("moneyforward_descriptions", ())
                    if item["value"]
                }
            )
            > 1,
        )

    def _blocker_pattern(
        self,
        index: int,
        key: tuple[object, ...],
        entries: Sequence[JournalEntry],
    ) -> MoneyForwardBlockerPattern:
        (
            debit_count,
            credit_count,
            taxes,
            has_subaccount,
            has_partner,
            has_department,
            has_tag,
            has_memo,
            has_invoice,
            has_multiple_descriptions,
        ) = key
        return MoneyForwardBlockerPattern(
            pattern_id=f"MF-UNSUPPORTED-{index:02d}",
            journal_count=len(entries),
            physical_row_count=sum(self._physical_row_count(item) for item in entries),
            debit_count=int(debit_count),
            credit_count=int(credit_count),
            tax_identities=tuple(taxes),
            has_subaccount=bool(has_subaccount),
            has_trade_partner=bool(has_partner),
            has_department=bool(has_department),
            has_tag=bool(has_tag),
            has_memo=bool(has_memo),
            has_invoice=bool(has_invoice),
            has_multiple_descriptions=bool(has_multiple_descriptions),
            blocker_code="MF-JDL-EVIDENCE-SCOPE-UNSUPPORTED-SHAPE-TAX-COMBINATION",
        )

    @staticmethod
    def _shape(entry: JournalEntry) -> tuple[int, int]:
        return (
            sum(line.side is Side.DEBIT for line in entry.lines),
            sum(line.side is Side.CREDIT for line in entry.lines),
        )

    @staticmethod
    def _physical_row_count(entry: JournalEntry) -> int:
        return len(entry.metadata.get("physical_row_numbers", ()))

    @staticmethod
    def _has_trade_partner(entry: JournalEntry) -> bool:
        return any(
            line.metadata.get("moneyforward_trade_partner") for line in entry.lines
        )

    @staticmethod
    def _count(
        entries: Iterable[JournalEntry], predicate
    ) -> int:
        return sum(bool(predicate(entry)) for entry in entries)

    @staticmethod
    def _is_cp932(value: str) -> bool:
        try:
            value.encode("cp932", errors="strict")
        except UnicodeEncodeError:
            return False
        return True

    @staticmethod
    def _entry_signature(entry: JournalEntry) -> tuple[object, ...]:
        return (
            entry.source_reference.source_journal_id,
            entry.date,
            tuple(
                (
                    line.side.value,
                    line.account,
                    line.sub_account,
                    line.department,
                    line.amount,
                    line.tax_info.category if line.tax_info else None,
                    line.tax_info.invoice_classification if line.tax_info else None,
                    line.metadata.get("moneyforward_trade_partner"),
                    line.metadata.get("moneyforward_description"),
                )
                for line in entry.lines
            ),
            tuple(entry.metadata.get("moneyforward_tags", ())),
            tuple(entry.metadata.get("moneyforward_memos", ())),
        )

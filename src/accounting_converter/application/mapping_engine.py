from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from accounting_converter.domain.journal import JournalEntry, JournalLine, TaxInfo
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.validation import Severity, ValidationResult


@dataclass(frozen=True)
class MappingRuleSet:
    accounts: dict[str, MappingValue]
    sub_accounts: dict[str, MappingValue]
    departments: dict[str, MappingValue]
    tax_categories: dict[str, MappingValue]


@dataclass(frozen=True)
class MappingResult:
    entries: tuple[JournalEntry, ...]
    mapping_values: tuple[MappingValue, ...]
    validation_results: tuple[ValidationResult, ...]

    @property
    def unresolved_count(self) -> int:
        return sum(1 for value in self.mapping_values if not value.is_resolved)


class MappingEngine:
    def __init__(self, rule_set: MappingRuleSet) -> None:
        self._rule_set = rule_set

    def apply(self, entries: Sequence[JournalEntry]) -> MappingResult:
        mapped_entries: list[JournalEntry] = []
        mapping_values: list[MappingValue] = []
        validation_results: list[ValidationResult] = []

        for entry in entries:
            mapped_lines: list[JournalLine] = []
            for line in entry.lines:
                account = self._resolve_value(
                    source=line.account,
                    rules=self._rule_set.accounts,
                    field="account",
                    entry=entry,
                    mapping_values=mapping_values,
                    validation_results=validation_results,
                )
                sub_account = self._resolve_value(
                    source=line.sub_account,
                    rules=self._rule_set.sub_accounts,
                    field="sub_account",
                    entry=entry,
                    mapping_values=mapping_values,
                    validation_results=validation_results,
                )
                department = self._resolve_value(
                    source=line.department,
                    rules=self._rule_set.departments,
                    field="department",
                    entry=entry,
                    mapping_values=mapping_values,
                    validation_results=validation_results,
                )
                tax_info = self._map_tax_info(
                    tax_info=line.tax_info,
                    entry=entry,
                    mapping_values=mapping_values,
                    validation_results=validation_results,
                )
                mapped_lines.append(
                    replace(
                        line,
                        account=account,
                        sub_account=sub_account,
                        department=department,
                        tax_info=tax_info,
                    )
                )
            mapped_entries.append(replace(entry, lines=mapped_lines))

        return MappingResult(
            entries=tuple(mapped_entries),
            mapping_values=tuple(mapping_values),
            validation_results=tuple(validation_results),
        )

    def _map_tax_info(
        self,
        tax_info: TaxInfo | None,
        entry: JournalEntry,
        mapping_values: list[MappingValue],
        validation_results: list[ValidationResult],
    ) -> TaxInfo | None:
        if tax_info is None or tax_info.category is None:
            return tax_info
        mapped_category = self._resolve_value(
            source=tax_info.category,
            rules=self._rule_set.tax_categories,
            field="tax_category",
            entry=entry,
            mapping_values=mapping_values,
            validation_results=validation_results,
        )
        return replace(tax_info, category=mapped_category)

    def _resolve_value(
        self,
        source: str | None,
        rules: dict[str, MappingValue],
        field: str,
        entry: JournalEntry,
        mapping_values: list[MappingValue],
        validation_results: list[ValidationResult],
    ) -> str | None:
        if source is None or source == "":
            return source

        mapping = rules.get(source)
        if mapping is None:
            mapping = MappingValue(source_value=source, status=MappingStatus.UNRESOLVED)
        mapping_values.append(mapping)
        if mapping.is_resolved:
            return mapping.target_value

        validation_results.append(
            ValidationResult(
                severity=Severity.WARNING,
                rule_id="MAP-UNRESOLVED",
                journal_id=entry.id,
                source_reference=entry.source_reference,
                field=field,
                input_value=source,
                message="未解決のマッピングがあります。",
                suggested_action="ユーザー確認済みのマッピングを指定してください。",
            )
        )
        return source

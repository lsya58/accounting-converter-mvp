from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from accounting_converter.application.description_replacement import (
    description_sha256,
    replacement_is_valid,
)
from accounting_converter.application.journal_route import JournalRouteResult
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.domain.validation import Severity, ValidationResult


MF_DESCRIPTION_REPLACEMENT_POLICY = "HUMAN_CONFIRMED_DESCRIPTION_REPLACEMENT"
MF_DESCRIPTION_REPLACEMENT_PREFIX = "mf_description_replacement|"

# JDL 35.5 accepted the CP932 vendor-extension byte sequence for this character,
# but changed it on re-export. It is therefore encodable but not round-trip safe.
JDL_OBSERVED_NON_ROUNDTRIP_CHARACTERS = frozenset({"髙"})


@dataclass(frozen=True)
class MoneyForwardDescriptionReviewItem:
    key: str
    original_description_sha256: str
    current_description: str
    current_length: int
    unsafe_positions: tuple[int, ...]
    affected_journal_count: int


def moneyforward_description_replacement_key(description: str) -> str:
    return f"{MF_DESCRIPTION_REPLACEMENT_PREFIX}{description_sha256(description)}"


def unsafe_description_positions(description: str) -> tuple[int, ...]:
    return tuple(
        index
        for index, character in enumerate(description)
        if character in JDL_OBSERVED_NON_ROUNDTRIP_CHARACTERS
    )


class MoneyForwardDescriptionReplacementPolicy:
    def __init__(self, profile) -> None:
        self._profile = profile

    def apply(self, entries: Sequence[JournalEntry]) -> JournalRouteResult:
        transformed: list[JournalEntry] = []
        errors: list[ValidationResult] = []
        for entry in entries:
            result, entry_errors = self._transform(entry)
            transformed.append(result)
            errors.extend(entry_errors)
        return JournalRouteResult(tuple(transformed), tuple(errors))

    def _transform(
        self, entry: JournalEntry
    ) -> tuple[JournalEntry, tuple[ValidationResult, ...]]:
        descriptions = self._descriptions(entry)
        replacements: dict[str, str] = {}
        errors: list[ValidationResult] = []
        for description in descriptions:
            if not unsafe_description_positions(description):
                continue
            key = moneyforward_description_replacement_key(description)
            mapping = self._profile.loss_policy_mappings.get(key)
            if not self._mapping_is_valid(mapping, description):
                errors.append(self._error(entry))
                continue
            replacements[description] = str(mapping.target_value)
        if errors:
            return entry, tuple(errors)
        if not replacements:
            return entry, ()

        description = replacements.get(entry.description or "", entry.description)
        observed = tuple(
            {
                **item,
                "value": replacements.get(str(item.get("value", "")), item.get("value", "")),
            }
            for item in entry.metadata.get("moneyforward_descriptions", ())
        )
        lines = [
            replace(
                line,
                metadata={
                    **line.metadata,
                    "moneyforward_description": replacements.get(
                        str(line.metadata.get("moneyforward_description", "")),
                        line.metadata.get("moneyforward_description", ""),
                    ),
                },
            )
            if "moneyforward_description" in line.metadata
            else line
            for line in entry.lines
        ]
        return replace(
            entry,
            description=description,
            lines=lines,
            metadata={**entry.metadata, "moneyforward_descriptions": observed},
        ), ()

    @staticmethod
    def _descriptions(entry: JournalEntry) -> tuple[str, ...]:
        values = [entry.description or ""]
        values.extend(
            str(item.get("value", ""))
            for item in entry.metadata.get("moneyforward_descriptions", ())
        )
        return tuple(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _mapping_is_valid(mapping, description: str) -> bool:
        return bool(
            mapping is not None
            and mapping.status is MappingStatus.USER_CONFIRMED
            and mapping.metadata.get("policy") == MF_DESCRIPTION_REPLACEMENT_POLICY
            and mapping.metadata.get("original_description_sha256")
            == description_sha256(description)
            and isinstance(mapping.target_value, str)
            and replacement_is_valid(mapping.target_value)
            and not unsafe_description_positions(mapping.target_value)
        )

    @staticmethod
    def _error(entry: JournalEntry) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id="MF-JDL-DESCRIPTION-NONROUNDTRIP-CHARACTER",
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field="description",
            message="摘要にJDLで保持できない文字があります。",
            suggested_action="会社設定で摘要の置換内容を確認してください。",
        )

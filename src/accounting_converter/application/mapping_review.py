from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from typing import Sequence

from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, JournalLine
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    with_updated_timestamp,
)


class MappingReviewStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNRESOLVED = "UNRESOLVED"
    OBSOLETE = "OBSOLETE"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MappingRequirement:
    mapping_type: MappingType
    source_value: str
    occurrence_count: int
    current_mapping_status: MappingStatus
    current_target_value: str | None
    requires_confirmation: bool
    parent_account: str | None = None
    side: str | None = None
    source_row_reference_count: int = 0

    @property
    def key(self) -> MappingKey:
        return MappingKey(
            mapping_type=self.mapping_type,
            source_value=self.source_value,
            parent_account=self.parent_account,
            side=self.side,
        )


@dataclass(frozen=True)
class MappingRequirementSet:
    accounts: tuple[MappingRequirement, ...] = ()
    subaccounts: tuple[MappingRequirement, ...] = ()
    departments: tuple[MappingRequirement, ...] = ()
    tax_categories: tuple[MappingRequirement, ...] = ()

    @property
    def unresolved_count(self) -> int:
        return sum(
            1
            for requirement in self.all_requirements()
            if requirement.requires_confirmation
        )

    def all_requirements(self) -> tuple[MappingRequirement, ...]:
        return (
            *self.accounts,
            *self.subaccounts,
            *self.departments,
            *self.tax_categories,
        )


@dataclass(frozen=True)
class MappingReviewItem:
    mapping_type: MappingType
    source_value: str
    target_value: str | None
    status: MappingReviewStatus
    occurrence_count: int
    requires_user_confirmation: bool
    parent_account: str | None = None
    side: str | None = None


@dataclass(frozen=True)
class MappingReviewResult:
    items: tuple[MappingReviewItem, ...]

    @property
    def unresolved_count(self) -> int:
        return sum(1 for item in self.items if item.requires_user_confirmation)


class MappingRequirementExtractor:
    def extract(
        self,
        entries: Sequence[JournalEntry],
        saved_profile: ConversionProfile | None = None,
    ) -> MappingRequirementSet:
        account_counts: Counter[str] = Counter()
        department_counts: Counter[str] = Counter()
        tax_counts: Counter[str] = Counter()
        subaccount_counts: Counter[MappingKey] = Counter()
        row_refs: dict[MappingKey, set[int]] = {}
        side_refs: dict[MappingKey, set[str]] = {}

        for entry in entries:
            for line in entry.lines:
                self._add_line(
                    line=line,
                    account_counts=account_counts,
                    department_counts=department_counts,
                    tax_counts=tax_counts,
                    subaccount_counts=subaccount_counts,
                    row_refs=row_refs,
                    side_refs=side_refs,
                )

        return MappingRequirementSet(
            accounts=self._simple_requirements(
                MappingType.ACCOUNT,
                account_counts,
                saved_profile.account_mappings if saved_profile else {},
            ),
            subaccounts=self._context_requirements(
                subaccount_counts,
                saved_profile.subaccount_context_mappings if saved_profile else {},
                row_refs,
                side_refs,
            ),
            departments=self._simple_requirements(
                MappingType.DEPARTMENT,
                department_counts,
                saved_profile.department_mappings if saved_profile else {},
            ),
            tax_categories=self._simple_requirements(
                MappingType.TAX_CATEGORY,
                tax_counts,
                saved_profile.tax_mappings if saved_profile else {},
            ),
        )

    def build_review(self, requirements: MappingRequirementSet) -> MappingReviewResult:
        return MappingReviewResult(
            items=tuple(
                MappingReviewItem(
                    mapping_type=requirement.mapping_type,
                    source_value=requirement.source_value,
                    target_value=requirement.current_target_value,
                    status=self._review_status(requirement.current_mapping_status),
                    occurrence_count=requirement.occurrence_count,
                    requires_user_confirmation=requirement.requires_confirmation,
                    parent_account=requirement.parent_account,
                    side=requirement.side,
                )
                for requirement in requirements.all_requirements()
            )
        )

    def _add_line(
        self,
        line: JournalLine,
        account_counts: Counter[str],
        department_counts: Counter[str],
        tax_counts: Counter[str],
        subaccount_counts: Counter[MappingKey],
        row_refs: dict[MappingKey, set[int]],
        side_refs: dict[MappingKey, set[str]],
    ) -> None:
        if line.account:
            account_counts[line.account] += 1
        if line.department:
            department_counts[line.department] += 1
        if line.tax_info is not None and line.tax_info.category:
            tax_counts[line.tax_info.category] += 1
        if line.sub_account:
            key = MappingKey(
                mapping_type=MappingType.SUBACCOUNT,
                source_value=line.sub_account,
                parent_account=line.account,
            )
            subaccount_counts[key] += 1
            side_refs.setdefault(key, set()).add(line.side.value)
            if line.source_reference.row_number is not None:
                row_refs.setdefault(key, set()).add(line.source_reference.row_number)

    def _simple_requirements(
        self,
        mapping_type: MappingType,
        counts: Counter[str],
        mappings: dict[str, MappingValue],
    ) -> tuple[MappingRequirement, ...]:
        requirements: list[MappingRequirement] = []
        for source_value, count in sorted(counts.items()):
            mapping = mappings.get(source_value)
            requirements.append(
                MappingRequirement(
                    mapping_type=mapping_type,
                    source_value=source_value,
                    occurrence_count=count,
                    current_mapping_status=(
                        mapping.status if mapping else MappingStatus.UNRESOLVED
                    ),
                    current_target_value=mapping.target_value if mapping else None,
                    requires_confirmation=(
                        mapping is None or not mapping.is_resolved
                    ),
                )
            )
        return tuple(requirements)

    def _context_requirements(
        self,
        counts: Counter[MappingKey],
        mappings: dict[MappingKey, MappingValue],
        row_refs: dict[MappingKey, set[int]],
        side_refs: dict[MappingKey, set[str]],
    ) -> tuple[MappingRequirement, ...]:
        requirements: list[MappingRequirement] = []
        for key, count in sorted(counts.items(), key=lambda item: item[0].stable_key):
            mapping = mappings.get(key)
            requirements.append(
                MappingRequirement(
                    mapping_type=MappingType.SUBACCOUNT,
                    source_value=key.source_value,
                    occurrence_count=count,
                    current_mapping_status=(
                        mapping.status if mapping else MappingStatus.UNRESOLVED
                    ),
                    current_target_value=mapping.target_value if mapping else None,
                    requires_confirmation=(
                        mapping is None or not mapping.is_resolved
                    ),
                    parent_account=key.parent_account,
                    side=",".join(sorted(side_refs.get(key, set()))) or None,
                    source_row_reference_count=len(row_refs.get(key, set())),
                )
            )
        return tuple(requirements)

    def _review_status(self, status: MappingStatus) -> MappingReviewStatus:
        return {
            MappingStatus.RESOLVED: MappingReviewStatus.CONFIRMED,
            MappingStatus.USER_CONFIRMED: MappingReviewStatus.CONFIRMED,
            MappingStatus.UNRESOLVED: MappingReviewStatus.UNRESOLVED,
            MappingStatus.OBSOLETE: MappingReviewStatus.OBSOLETE,
        }.get(status, MappingReviewStatus.UNKNOWN)


class MappingConfirmationService:
    def __init__(self, store: ConversionProfileStore) -> None:
        self.store = store

    def confirm_mapping(
        self,
        profile_id: str,
        key: MappingKey,
        target_value: str,
    ) -> ConversionProfile:
        if not target_value.strip():
            raise ValueError("target_value is required")
        profile = self.store.get(profile_id)
        updated = self._with_mapping(
            profile,
            key,
            MappingValue(
                source_value=key.source_value,
                target_value=target_value,
                status=MappingStatus.USER_CONFIRMED,
                parent_account=key.parent_account,
                metadata=({"observed_side": key.side} if key.side else {}),
            ),
        )
        return self.store.update(with_updated_timestamp(updated))

    def deactivate_mapping(
        self,
        profile_id: str,
        key: MappingKey,
    ) -> ConversionProfile:
        profile = self.store.get(profile_id)
        updated = self._with_mapping(
            profile,
            key,
            MappingValue(
                source_value=key.source_value,
                target_value=None,
                status=MappingStatus.OBSOLETE,
                parent_account=key.parent_account,
                metadata=({"observed_side": key.side} if key.side else {}),
            ),
        )
        return self.store.update(with_updated_timestamp(updated))

    def _with_mapping(
        self,
        profile: ConversionProfile,
        key: MappingKey,
        mapping: MappingValue,
    ) -> ConversionProfile:
        if key.mapping_type is MappingType.ACCOUNT:
            mappings = dict(profile.account_mappings)
            mappings[key.source_value] = mapping
            return replace(profile, account_mappings=mappings)
        if key.mapping_type is MappingType.SUBACCOUNT:
            mappings = dict(profile.subaccount_context_mappings)
            mappings[
                MappingKey(
                    mapping_type=key.mapping_type,
                    source_value=key.source_value,
                    parent_account=key.parent_account,
                )
            ] = mapping
            return replace(profile, subaccount_context_mappings=mappings)
        if key.mapping_type is MappingType.DEPARTMENT:
            mappings = dict(profile.department_mappings)
            mappings[key.source_value] = mapping
            return replace(profile, department_mappings=mappings)
        if key.mapping_type is MappingType.TAX_CATEGORY:
            mappings = dict(profile.tax_mappings)
            mappings[key.source_value] = mapping
            return replace(profile, tax_mappings=mappings)
        raise ValueError(f"unsupported mapping type: {key.mapping_type}")


def mapping_requirements_to_observed_preflight(
    requirements: MappingRequirementSet,
):
    from accounting_converter.application.profile_preflight import (
        ObservedMappingRequirements,
    )

    return ObservedMappingRequirements(
        accounts=frozenset(item.source_value for item in requirements.accounts),
        subaccount_contexts=frozenset(item.key for item in requirements.subaccounts),
        departments=frozenset(item.source_value for item in requirements.departments),
        tax_categories=frozenset(item.source_value for item in requirements.tax_categories),
    )

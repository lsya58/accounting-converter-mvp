from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    FormatIdentityMatchStatus,
    ProfileVersionStatus,
)
from accounting_converter.domain.format_metadata import FormatIdentity
from accounting_converter.domain.mapping import MappingKey, MappingValue

from .mapping_engine import MappingRuleSet


class ProfilePreflightStatus(str, Enum):
    READY = "READY"
    REQUIRES_MAPPING = "REQUIRES_MAPPING"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    PROFILE_INVALID = "PROFILE_INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ObservedMappingRequirements:
    accounts: frozenset[str] = frozenset()
    subaccounts: frozenset[str] = frozenset()
    departments: frozenset[str] = frozenset()
    tax_categories: frozenset[str] = frozenset()
    subaccount_contexts: frozenset[MappingKey] = frozenset()


@dataclass(frozen=True)
class PreflightResult:
    status: ProfilePreflightStatus
    format_match_status: FormatIdentityMatchStatus
    unknown_accounts: tuple[str, ...] = ()
    unknown_subaccounts: tuple[str, ...] = ()
    unknown_departments: tuple[str, ...] = ()
    unknown_tax_categories: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()

    @property
    def unknown_mapping_count(self) -> int:
        return (
            len(self.unknown_accounts)
            + len(self.unknown_subaccounts)
            + len(self.unknown_departments)
            + len(self.unknown_tax_categories)
        )


class ConversionPreflightService:
    def check(
        self,
        source_format_candidate: FormatIdentity | None,
        target_format_candidate: FormatIdentity | None,
        observed_mapping_requirements: ObservedMappingRequirements,
        saved_profile: ConversionProfile | None = None,
    ) -> PreflightResult:
        if saved_profile is None:
            if self._has_mapping_requirements(observed_mapping_requirements):
                return PreflightResult(
                    status=ProfilePreflightStatus.REQUIRES_MAPPING,
                    format_match_status=FormatIdentityMatchStatus.UNKNOWN,
                    unknown_accounts=tuple(sorted(observed_mapping_requirements.accounts)),
                    unknown_subaccounts=tuple(
                        sorted(
                            (
                                *observed_mapping_requirements.subaccounts,
                                *(
                                    key.stable_key
                                    for key in observed_mapping_requirements.subaccount_contexts
                                ),
                            )
                        )
                    ),
                    unknown_departments=tuple(sorted(observed_mapping_requirements.departments)),
                    unknown_tax_categories=tuple(sorted(observed_mapping_requirements.tax_categories)),
                    messages=("No saved profile was provided.",),
                )
            return PreflightResult(
                status=ProfilePreflightStatus.UNKNOWN,
                format_match_status=FormatIdentityMatchStatus.UNKNOWN,
                messages=("No saved profile and no mapping requirements were provided.",),
            )

        if saved_profile.version_status is ProfileVersionStatus.UNSUPPORTED_VERSION:
            return PreflightResult(
                status=ProfilePreflightStatus.UNSUPPORTED,
                format_match_status=FormatIdentityMatchStatus.UNKNOWN,
                messages=("Saved profile schema_version is unsupported.",),
            )

        format_match = saved_profile.verify_format_identity(
            source_format_candidate,
            target_format_candidate,
        )
        if format_match in {
            FormatIdentityMatchStatus.MISMATCH,
            FormatIdentityMatchStatus.UNKNOWN,
        }:
            return PreflightResult(
                status=ProfilePreflightStatus.FORMAT_MISMATCH,
                format_match_status=format_match,
                messages=("Saved profile format identity does not match candidates.",),
            )

        unknown_accounts = self._unknown_values(
            observed_mapping_requirements.accounts,
            saved_profile.account_mappings,
        )
        unknown_subaccounts = self._unknown_values(
            observed_mapping_requirements.subaccounts,
            saved_profile.subaccount_mappings,
        )
        unknown_subaccount_contexts = self._unknown_context_values(
            observed_mapping_requirements.subaccount_contexts,
            saved_profile.subaccount_context_mappings,
        )
        unknown_departments = self._unknown_values(
            observed_mapping_requirements.departments,
            saved_profile.department_mappings,
        )
        unknown_tax_categories = self._unknown_values(
            observed_mapping_requirements.tax_categories,
            saved_profile.tax_mappings,
        )
        if (
            unknown_accounts
            or unknown_subaccounts
            or unknown_subaccount_contexts
            or unknown_departments
            or unknown_tax_categories
        ):
            return PreflightResult(
                status=ProfilePreflightStatus.REQUIRES_MAPPING,
                format_match_status=format_match,
                unknown_accounts=unknown_accounts,
                unknown_subaccounts=tuple(
                    sorted((*unknown_subaccounts, *unknown_subaccount_contexts))
                ),
                unknown_departments=unknown_departments,
                unknown_tax_categories=unknown_tax_categories,
                messages=("Unknown mappings require human confirmation.",),
            )
        return PreflightResult(
            status=ProfilePreflightStatus.READY,
            format_match_status=format_match,
            messages=("Saved profile can be applied.",),
        )

    def _has_mapping_requirements(
        self,
        requirements: ObservedMappingRequirements,
    ) -> bool:
        return bool(
            requirements.accounts
            or requirements.subaccounts
            or requirements.subaccount_contexts
            or requirements.departments
            or requirements.tax_categories
        )

    def _unknown_values(
        self,
        observed_values: frozenset[str],
        mappings: dict[str, MappingValue],
    ) -> tuple[str, ...]:
        unknown: list[str] = []
        for value in observed_values:
            mapping = mappings.get(value)
            if mapping is None or not mapping.is_resolved:
                unknown.append(value)
        return tuple(sorted(unknown))

    def _unknown_context_values(
        self,
        observed_values: frozenset[MappingKey],
        mappings: dict[MappingKey, MappingValue],
    ) -> tuple[str, ...]:
        unknown: list[str] = []
        for key in observed_values:
            mapping = mappings.get(key)
            if mapping is None or not mapping.is_resolved:
                unknown.append(key.stable_key)
        return tuple(sorted(unknown))


def mapping_rule_set_from_profile(profile: ConversionProfile) -> MappingRuleSet:
    return MappingRuleSet(
        accounts=profile.account_mappings,
        sub_accounts=profile.subaccount_mappings,
        departments=profile.department_mappings,
        tax_categories=profile.tax_mappings,
        sub_account_contexts=profile.subaccount_context_mappings,
    )

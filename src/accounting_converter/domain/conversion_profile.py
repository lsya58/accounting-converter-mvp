from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .format_metadata import FormatIdentity
from .mapping import MappingValue
from .normalization import NormalizationRule


CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION = "1"


class ProfileVersionStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"


class FormatIdentityMatchStatus(str, Enum):
    MATCH = "MATCH"
    COMPATIBLE_CANDIDATE = "COMPATIBLE_CANDIDATE"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ConversionProfile:
    profile_id: str
    profile_name: str
    source_format_identity: FormatIdentity
    target_format_identity: FormatIdentity
    account_mappings: dict[str, MappingValue] = field(default_factory=dict)
    subaccount_mappings: dict[str, MappingValue] = field(default_factory=dict)
    department_mappings: dict[str, MappingValue] = field(default_factory=dict)
    tax_mappings: dict[str, MappingValue] = field(default_factory=dict)
    normalization_rules: tuple[NormalizationRule, ...] = ()
    schema_version: str = CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str | None = None

    @property
    def version_status(self) -> ProfileVersionStatus:
        if self.schema_version == CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION:
            return ProfileVersionStatus.SUPPORTED
        return ProfileVersionStatus.UNSUPPORTED_VERSION

    def verify_format_identity(
        self,
        source_candidate: FormatIdentity | None,
        target_candidate: FormatIdentity | None,
    ) -> FormatIdentityMatchStatus:
        source_status = _match_identity(
            self.source_format_identity,
            source_candidate,
        )
        target_status = _match_identity(
            self.target_format_identity,
            target_candidate,
        )
        if (
            source_status is FormatIdentityMatchStatus.MATCH
            and target_status is FormatIdentityMatchStatus.MATCH
        ):
            return FormatIdentityMatchStatus.MATCH
        if (
            source_status is FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE
            and target_status
            in {
                FormatIdentityMatchStatus.MATCH,
                FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE,
            }
        ) or (
            target_status is FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE
            and source_status
            in {
                FormatIdentityMatchStatus.MATCH,
                FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE,
            }
        ):
            return FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE
        if (
            source_status is FormatIdentityMatchStatus.UNKNOWN
            or target_status is FormatIdentityMatchStatus.UNKNOWN
        ):
            return FormatIdentityMatchStatus.UNKNOWN
        return FormatIdentityMatchStatus.MISMATCH


def _match_identity(
    stored: FormatIdentity,
    candidate: FormatIdentity | None,
) -> FormatIdentityMatchStatus:
    if candidate is None:
        return FormatIdentityMatchStatus.UNKNOWN
    if stored.stable_key == candidate.stable_key:
        return FormatIdentityMatchStatus.MATCH
    same_family = (
        stored.vendor == candidate.vendor
        and stored.product == candidate.product
        and stored.format_name == candidate.format_name
        and stored.direction is candidate.direction
    )
    same_version = (
        stored.major_version == candidate.major_version
        and stored.minor_version == candidate.minor_version
        and stored.version_range == candidate.version_range
        and stored.format_version == candidate.format_version
    )
    if same_family and same_version:
        return FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE
    return FormatIdentityMatchStatus.MISMATCH

from dataclasses import dataclass, field
from enum import Enum


class MappingStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    OBSOLETE = "OBSOLETE"


class MappingType(str, Enum):
    ACCOUNT = "ACCOUNT"
    SUBACCOUNT = "SUBACCOUNT"
    DEPARTMENT = "DEPARTMENT"
    TAX_CATEGORY = "TAX_CATEGORY"


class SubaccountPolicy(str, Enum):
    PRESERVE_SUBACCOUNT = "PRESERVE_SUBACCOUNT"
    PARENT_ONLY_CONFIRMED = "PARENT_ONLY_CONFIRMED"
    DEFAULT_TARGET_SUBACCOUNT = "DEFAULT_TARGET_SUBACCOUNT"


DEFAULT_SUBACCOUNT_SOURCE_VALUE = "__SOURCE_SUBACCOUNT_EMPTY__"
PARENT_ONLY_CANONICAL_SUBACCOUNT = ""


@dataclass(frozen=True)
class MappingKey:
    mapping_type: MappingType
    source_value: str
    parent_account: str | None = None
    side: str | None = field(default=None, compare=False, hash=False)

    @property
    def stable_key(self) -> str:
        return "|".join(
            (
                self.mapping_type.value,
                self.source_value,
                self.parent_account or "",
            )
        )


@dataclass
class MappingValue:
    source_value: str
    target_value: str | None = None
    status: MappingStatus = MappingStatus.UNRESOLVED
    parent_account: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status in {
            MappingStatus.RESOLVED,
            MappingStatus.USER_CONFIRMED,
        } and self.target_value is not None


def is_confirmed_parent_only(mapping: MappingValue | None) -> bool:
    """Return whether Human explicitly confirmed dropping the target subaccount."""
    return bool(
        mapping is not None
        and mapping.status is MappingStatus.USER_CONFIRMED
        and mapping.metadata.get("subaccount_policy")
        == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value
    )


def canonical_subaccount_target(mapping: MappingValue) -> str | None:
    """Normalize only an explicitly confirmed parent-only mapping to JDL blank."""
    if is_confirmed_parent_only(mapping):
        return PARENT_ONLY_CANONICAL_SUBACCOUNT
    return mapping.target_value

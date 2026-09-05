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

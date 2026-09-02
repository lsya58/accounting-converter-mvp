from dataclasses import dataclass
from enum import Enum


class MappingStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    USER_CONFIRMED = "USER_CONFIRMED"
    OBSOLETE = "OBSOLETE"


@dataclass
class MappingValue:
    source_value: str
    target_value: str | None = None
    status: MappingStatus = MappingStatus.UNRESOLVED

    @property
    def is_resolved(self) -> bool:
        return self.status in {
            MappingStatus.RESOLVED,
            MappingStatus.USER_CONFIRMED,
        } and self.target_value is not None

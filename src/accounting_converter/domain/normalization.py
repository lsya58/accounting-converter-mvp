from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .format_metadata import EvidenceLevel, SemanticField


class NormalizationScope(str, Enum):
    SAFE_TEXT_NORMALIZATION = "SAFE_TEXT_NORMALIZATION"
    ACCOUNTING_SEMANTIC_MAPPING = "ACCOUNTING_SEMANTIC_MAPPING"


@dataclass(frozen=True)
class NormalizationRule:
    rule_id: str
    target_field: SemanticField
    scope: NormalizationScope
    deterministic: bool
    reversible: bool
    requires_confirmation: bool
    evidence: EvidenceLevel
    description: str

    @property
    def can_auto_apply(self) -> bool:
        return (
            self.scope is NormalizationScope.SAFE_TEXT_NORMALIZATION
            and self.deterministic
            and not self.requires_confirmation
            and self.evidence is not EvidenceLevel.INFERRED
        )

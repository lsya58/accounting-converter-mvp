from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import ValidationResult

from .output_validation import OutputValidator


@dataclass(frozen=True)
class RuntimeOutputResolution:
    output_adapter: OutputAdapter | None
    output_validator: OutputValidator | None
    validation_results: tuple[ValidationResult, ...] = ()

    @property
    def resolved(self) -> bool:
        return (
            self.output_adapter is not None
            and self.output_validator is not None
            and not self.validation_results
        )


class RuntimeOutputFactory(Protocol):
    def resolve(
        self,
        output_profile: FormatProfile,
        conversion_profile: ConversionProfile | None,
        runtime_context: object | None,
    ) -> RuntimeOutputResolution:
        ...

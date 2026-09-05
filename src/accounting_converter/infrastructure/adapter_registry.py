from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.domain.format_metadata import (
    EvidenceLevel,
    FormatDirection,
    FormatIdentity,
)


AdapterT = TypeVar("AdapterT", InputAdapter, OutputAdapter)


class AdapterAvailabilityStatus(str, Enum):
    EXACT = "EXACT"
    CANDIDATE = "CANDIDATE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AdapterRegistration(Generic[AdapterT]):
    format_identity: FormatIdentity
    factory: Callable[[], AdapterT]
    direction: FormatDirection
    evidence_level: EvidenceLevel
    verified_by_real_import: bool = False
    production_enabled: bool = False
    notes: str | None = None

    @property
    def production_eligible(self) -> bool:
        if not self.production_enabled:
            return False
        if self.direction is FormatDirection.OUTPUT:
            return (
                self.verified_by_real_import
                and self.evidence_level is EvidenceLevel.VERIFIED_BY_REAL_IMPORT
            )
        return self.evidence_level in {
            EvidenceLevel.OFFICIAL_DOCUMENTED,
            EvidenceLevel.OBSERVED,
            EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        }


@dataclass(frozen=True)
class AdapterLookupResult(Generic[AdapterT]):
    status: AdapterAvailabilityStatus
    registration: AdapterRegistration[AdapterT] | None = None
    candidates: tuple[AdapterRegistration[AdapterT], ...] = ()

    @property
    def adapter_available(self) -> bool:
        return self.status is AdapterAvailabilityStatus.EXACT and self.registration is not None


class AdapterRegistry:
    def __init__(self) -> None:
        self._inputs: dict[str, AdapterRegistration[InputAdapter]] = {}
        self._outputs: dict[str, AdapterRegistration[OutputAdapter]] = {}

    def register_input(
        self,
        registration: AdapterRegistration[InputAdapter],
    ) -> None:
        self._register(self._inputs, registration, FormatDirection.INPUT)

    def register_output(
        self,
        registration: AdapterRegistration[OutputAdapter],
    ) -> None:
        self._register(self._outputs, registration, FormatDirection.OUTPUT)

    def get_exact_input(
        self,
        identity: FormatIdentity,
        production_only: bool = True,
    ) -> AdapterLookupResult[InputAdapter]:
        return self._get_exact(self._inputs, identity, production_only)

    def get_exact_output(
        self,
        identity: FormatIdentity,
        production_only: bool = True,
    ) -> AdapterLookupResult[OutputAdapter]:
        return self._get_exact(self._outputs, identity, production_only)

    def find_input_candidates(
        self,
        identity: FormatIdentity,
        production_only: bool = True,
    ) -> tuple[AdapterRegistration[InputAdapter], ...]:
        return self._find_candidates(self._inputs, identity, production_only)

    def find_output_candidates(
        self,
        identity: FormatIdentity,
        production_only: bool = True,
    ) -> tuple[AdapterRegistration[OutputAdapter], ...]:
        return self._find_candidates(self._outputs, identity, production_only)

    def has_conversion_pair(
        self,
        source_identity: FormatIdentity,
        target_identity: FormatIdentity,
        production_only: bool = True,
    ) -> bool:
        return (
            self.get_exact_input(source_identity, production_only).adapter_available
            and self.get_exact_output(target_identity, production_only).adapter_available
        )

    def _register(
        self,
        registrations: dict[str, AdapterRegistration],
        registration: AdapterRegistration,
        expected_direction: FormatDirection,
    ) -> None:
        if registration.direction is not expected_direction:
            raise ValueError("adapter direction does not match registry method")
        key = registration.format_identity.stable_key
        if key in registrations:
            raise ValueError("adapter registration already exists")
        registrations[key] = registration

    def _get_exact(
        self,
        registrations: dict[str, AdapterRegistration[AdapterT]],
        identity: FormatIdentity,
        production_only: bool,
    ) -> AdapterLookupResult[AdapterT]:
        registration = registrations.get(identity.stable_key)
        if registration and self._eligible(registration, production_only):
            return AdapterLookupResult(
                status=AdapterAvailabilityStatus.EXACT,
                registration=registration,
            )
        candidates = self._find_candidates(registrations, identity, production_only)
        if candidates:
            return AdapterLookupResult(
                status=AdapterAvailabilityStatus.CANDIDATE,
                candidates=candidates,
            )
        return AdapterLookupResult(status=AdapterAvailabilityStatus.UNAVAILABLE)

    def _find_candidates(
        self,
        registrations: dict[str, AdapterRegistration[AdapterT]],
        identity: FormatIdentity,
        production_only: bool,
    ) -> tuple[AdapterRegistration[AdapterT], ...]:
        candidates: list[AdapterRegistration[AdapterT]] = []
        for registration in registrations.values():
            registered = registration.format_identity
            same_family = (
                registered.vendor == identity.vendor
                and registered.product == identity.product
                and registered.format_name == identity.format_name
                and registered.direction is identity.direction
            )
            if same_family and registered.stable_key != identity.stable_key:
                if self._eligible(registration, production_only):
                    candidates.append(registration)
        return tuple(candidates)

    def _eligible(
        self,
        registration: AdapterRegistration,
        production_only: bool,
    ) -> bool:
        if not production_only:
            return True
        return registration.production_eligible


def production_adapter_registry() -> AdapterRegistry:
    return AdapterRegistry()


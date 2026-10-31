"""Test helper: evidence matching now needs a confirmed Human tax mapping.

Production resolves source tax names through the saved CompanySetting. Tests
that only exercise account/shape/Evidence logic get every MF tax candidate
confirmed exactly as the Human review would save it.
"""
from __future__ import annotations

from dataclasses import is_dataclass, replace
from types import SimpleNamespace

from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.domain.mapping import MappingStatus, MappingValue


def confirmed_tax_mappings(context) -> dict[str, MappingValue]:
    return {
        source: MappingValue(
            source, target, MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_tax_scope": scope,
                "jdl_evidence_id": evidence_id,
                "jdl_tax_processing_mode": context.tax_processing_mode.value,
                "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
            },
        )
        for source, (target, scope, evidence_id) in ev.TAX_MAPPING_SPECS.items()
    }


def with_confirmed_tax(profile, context):
    confirmed = confirmed_tax_mappings(context)
    if profile is None:
        return SimpleNamespace(account_mappings={}, subaccount_context_mappings={}, tax_mappings=confirmed)
    merged = {**confirmed, **(getattr(profile, "tax_mappings", None) or {})}
    if is_dataclass(profile):
        return replace(profile, tax_mappings=merged)
    return SimpleNamespace(**{**vars(profile), "tax_mappings": merged})


def evidence_for_occurrence(source, mapped, context, profile=None):
    return ev.evidence_for_occurrence(source, mapped, context, with_confirmed_tax(profile, context))


def match_evidence_for_occurrence(source, mapped, context, profile=None):
    return ev.match_evidence_for_occurrence(source, mapped, context, with_confirmed_tax(profile, context))


def apply_verified_tax_semantics(source, mapped, context, profile=None):
    return ev.apply_verified_tax_semantics(source, mapped, context, with_confirmed_tax(profile, context))

"""Human review for Yayoi 仕訳日記帳 → JDL, grouped by identity (never per journal).

Works before the target JDL company exists: source identities and their impact
can be listed and target-independent decisions (description replacements)
saved in a Yayoi profile. Tax mappings need the confirmed JDL Tax Context and
are stored as UNRESOLVED until a Human confirms them.

Mapping state and Evidence state are separate:
- mapping: CONFIRMED / UNCONFIRMED / TARGET_REQUIRED (no JDL company yet)
- Evidence: AVAILABLE / EXPLICIT_TAX_PENDING / SIDE_PENDING / NO_SEMANTIC
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Sequence

from accounting_converter.adapters.output.jdl import JdlTargetContext
from accounting_converter.adapters.output.jdl.tax_semantics import JDL_TAX_LITERALS, JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.company_mapping_update import CompanyMappingUpdateService
from accounting_converter.application.description_replacement import replacement_is_valid
from accounting_converter.application.mapping_review import MappingConfirmationService
from accounting_converter.application.moneyforward_description_replacement import (
    MF_DESCRIPTION_REPLACEMENT_POLICY,
    MoneyForwardDescriptionReviewItem,
    moneyforward_description_replacement_key,
    unsafe_description_positions,
)
from accounting_converter.application.description_replacement import description_sha256
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    yayoi_journal_report_generic_identity,
)

# Evidence that verified each JDL literal (what is written into the mapping).
SEMANTIC_EVIDENCE_ID = {
    JdlTaxSemantic.NO_TAX: ev.BATCH_EVIDENCE_ID,
    JdlTaxSemantic.PURCHASE_10_INTERNAL: ev.BATCH_EVIDENCE_ID,
    JdlTaxSemantic.SALES_10_EXTERNAL: ev.SALES10_EVIDENCE_ID,
    JdlTaxSemantic.NON_TAXABLE_PURCHASE: ev.NONPUR_3181_EVIDENCE_ID,
    JdlTaxSemantic.NON_TAXABLE_SALES: ev.NONSALE_EVIDENCE_ID,
}


def candidate_semantic(identity: str) -> JdlTaxSemantic | None:
    """Natural JDL candidate shown to the Human. Never applied without confirmation.

    Identities with an invoice class / purchase-credit ratio other than the
    ordinary 適格・100% case (経過措置 80%, 控除不可, 区分記載) get no candidate.
    """
    base, _, extra = identity.partition("｜")
    if extra and extra != "適格｜100%":
        return None
    if base == "対象外":
        return JdlTaxSemantic.NO_TAX
    if "軽" in base or "輸" in base or "控除" in base:
        return None
    if "課対仕入" in base and "10%" in base:
        return JdlTaxSemantic.PURCHASE_10_INTERNAL
    if "課税売上" in base and "10%" in base:
        return JdlTaxSemantic.SALES_10_EXTERNAL
    if base.startswith("非課仕入"):
        return JdlTaxSemantic.NON_TAXABLE_PURCHASE
    if base.startswith("非課売上"):
        return JdlTaxSemantic.NON_TAXABLE_SALES
    return None


@dataclass(frozen=True)
class YayoiTaxIdentityItem:
    identity: str
    base: str
    invoice_class: str
    purchase_credit: str
    debit_lines: int
    credit_lines: int
    journals: int
    explicit_tax_lines: int
    explicit_tax_unverified_lines: int  # explicit amount differs from the verified floor rule
    candidate: JdlTaxSemantic | None
    mapping_state: str
    confirmed_semantic: JdlTaxSemantic | None
    evidence_state: str


@dataclass(frozen=True)
class YayoiIdentityCount:
    key: str
    parent: str | None
    debit_lines: int
    credit_lines: int
    journals: int
    mapping_state: str


@dataclass(frozen=True)
class YayoiSourceReview:
    journals: int
    physical_rows: int
    accounts: tuple[YayoiIdentityCount, ...]
    subaccounts: tuple[YayoiIdentityCount, ...]
    taxes: tuple[YayoiTaxIdentityItem, ...]
    descriptions: tuple[MoneyForwardDescriptionReviewItem, ...]
    sticky_note_journals: int
    closing_journals: int

    @property
    def setting_item_counts(self) -> dict[str, int]:
        return {
            "accounts": sum(item.mapping_state != "CONFIRMED" for item in self.accounts),
            "subaccounts": sum(item.mapping_state != "CONFIRMED" for item in self.subaccounts),
            "tax_identities": sum(item.mapping_state != "CONFIRMED" for item in self.taxes),
            "description_groups": len(self.descriptions),
            "optional_policies": int(self.sticky_note_journals > 0) + int(self.closing_journals > 0),
        }


def _mapping_state(mapping: MappingValue | None, has_target: bool) -> str:
    if mapping is not None and mapping.status is MappingStatus.USER_CONFIRMED:
        return "CONFIRMED"
    return "UNCONFIRMED" if has_target else "TARGET_REQUIRED"


def review_source(
    entries: Sequence[JournalEntry],
    profile: ConversionProfile | None = None,
    context: JdlTargetContext | None = None,
) -> YayoiSourceReview:
    has_target = context is not None
    accounts: dict[str, Counter] = defaultdict(Counter)
    account_journals: dict[str, set] = defaultdict(set)
    subs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    sub_journals: dict[tuple[str, str], set] = defaultdict(set)
    taxes: dict[str, Counter] = defaultdict(Counter)
    tax_journals: dict[str, set] = defaultdict(set)
    tax_attributes: dict[str, tuple[str, str, str]] = {}
    for entry in entries:
        for line in entry.lines:
            accounts[line.account][line.side.value] += 1
            account_journals[line.account].add(entry.id)
            if line.sub_account:
                key = (line.account, line.sub_account)
                subs[key][line.side.value] += 1
                sub_journals[key].add(entry.id)
            info = line.tax_info
            if info is None or not info.category:
                continue
            identity = info.category
            taxes[identity][line.side.value] += 1
            tax_journals[identity].add(entry.id)
            tax_attributes[identity] = (
                identity.partition("｜")[0],
                str(info.metadata.get("yayoi_invoice_class", "")),
                str(info.metadata.get("yayoi_purchase_credit", "")),
            )
            if info.tax_amount is not None:
                taxes[identity]["explicit"] += 1
                if info.tax_amount != ev.ten_percent_tax_amount(line.amount):
                    taxes[identity]["explicit_unverified"] += 1
    tax_items = []
    for identity, counts in sorted(taxes.items(), key=lambda item: -sum(item[1].values())):
        mapping = profile.tax_mappings.get(identity) if profile is not None else None
        state = _mapping_state(mapping, has_target)
        confirmed = None
        if state == "CONFIRMED" and context is not None:
            sample_line = next(
                line for entry in entries for line in entry.lines
                if line.tax_info and line.tax_info.category == identity
            )
            value = ev.target_tax_semantic(sample_line, profile, context)
            confirmed = JdlTaxSemantic(value) if value != ev.UNMAPPED_TAX else None
        semantic = confirmed or candidate_semantic(identity)
        tax_items.append(YayoiTaxIdentityItem(
            identity=identity,
            base=tax_attributes[identity][0],
            invoice_class=tax_attributes[identity][1],
            purchase_credit=tax_attributes[identity][2],
            debit_lines=counts["DEBIT"],
            credit_lines=counts["CREDIT"],
            journals=len(tax_journals[identity]),
            explicit_tax_lines=counts["explicit"],
            explicit_tax_unverified_lines=counts["explicit_unverified"] if semantic in {
                JdlTaxSemantic.PURCHASE_10_INTERNAL, JdlTaxSemantic.SALES_10_EXTERNAL,
            } else counts["explicit"],
            candidate=candidate_semantic(identity),
            mapping_state=state,
            confirmed_semantic=confirmed,
            evidence_state=_evidence_state(semantic, counts),
        ))
    description_items = CompanyMappingUpdateService._description_review_items(
        entries, profile if profile is not None else _EMPTY_PROFILE
    )
    return YayoiSourceReview(
        journals=len(entries),
        physical_rows=sum(len(entry.metadata.get("physical_row_numbers", ())) for entry in entries),
        accounts=tuple(
            YayoiIdentityCount(name, None, c["DEBIT"], c["CREDIT"], len(account_journals[name]),
                               _mapping_state(profile.account_mappings.get(name) if profile else None, has_target))
            for name, c in sorted(accounts.items(), key=lambda item: -sum(item[1].values()))
        ),
        subaccounts=tuple(
            YayoiIdentityCount(sub, parent, c["DEBIT"], c["CREDIT"], len(sub_journals[(parent, sub)]),
                               _mapping_state(_subaccount_mapping(profile, parent, sub), has_target))
            for (parent, sub), c in sorted(subs.items(), key=lambda item: -sum(item[1].values()))
        ),
        taxes=tuple(tax_items),
        descriptions=tuple(description_items),
        sticky_note_journals=sum(1 for e in entries if e.metadata.get("yayoi_optional_fields")),
        closing_journals=sum(1 for e in entries if e.metadata.get("yayoi_closing")),
    )


def _evidence_state(semantic: JdlTaxSemantic | None, counts: Counter) -> str:
    if semantic is None:
        return "NO_SEMANTIC"
    for side in ("DEBIT", "CREDIT"):
        if counts[side] and (side, semantic.value) not in ev.LINE_CAPABILITIES:
            return "SIDE_PENDING"
    taxed = semantic in {JdlTaxSemantic.PURCHASE_10_INTERNAL, JdlTaxSemantic.SALES_10_EXTERNAL}
    if (taxed and counts["explicit_unverified"]) or (not taxed and counts["explicit"]):
        return "EXPLICIT_TAX_PENDING"
    return "AVAILABLE"


def _subaccount_mapping(profile, parent, sub):
    if profile is None:
        return None
    for key, value in profile.subaccount_context_mappings.items():
        if key.parent_account == parent and key.source_value == sub:
            return value
    return None


class _EmptyProfile:
    loss_policy_mappings: dict = {}


_EMPTY_PROFILE = _EmptyProfile()


def create_yayoi_profile(
    store: ConversionProfileStore,
    display_name: str,
    entries: Sequence[JournalEntry],
) -> ConversionProfile:
    """Company-scoped Yayoi → JDL profile; every tax identity starts UNRESOLVED."""
    if not display_name.strip():
        raise ValueError("会社設定名を入力してください。")
    now = datetime.now(timezone.utc)
    identities = sorted({
        line.tax_info.category for entry in entries for line in entry.lines
        if line.tax_info and line.tax_info.category
    })
    profile = ConversionProfile(
        profile_id=f"yayoi-jdl-{uuid.uuid4().hex}",
        profile_name=f"{display_name.strip()} 弥生 → JDL",
        source_format_identity=yayoi_journal_report_generic_identity(),
        target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        tax_mappings={
            identity: MappingValue(identity, None, MappingStatus.UNRESOLVED) for identity in identities
        },
        created_at=now,
        updated_at=now,
        notes="弥生 仕訳日記帳（汎用形式）から作成。科目・補助・税区分は対象JDL会社の確認後に明示確認する。",
    )
    return store.create(profile)


def confirm_tax_identity(
    store: ConversionProfileStore,
    profile_id: str,
    context: JdlTargetContext,
    identity: str,
    semantic: JdlTaxSemantic,
) -> ConversionProfile:
    """Save one Human decision: Yayoi tax identity → JDL tax semantic."""
    if not ev.context_is_verified(context):
        raise ValueError("JDL税設定の実機Evidenceがない税設定では、税区分を確認済みにできません。")
    literal = JDL_TAX_LITERALS[semantic]
    return MappingConfirmationService(store).confirm_mapping(
        profile_id,
        MappingKey(MappingType.TAX_CATEGORY, identity),
        literal.category,
        metadata={
            "jdl_tax_scope": literal.scope,
            "jdl_evidence_id": SEMANTIC_EVIDENCE_ID[semantic],
            "jdl_tax_processing_mode": context.tax_processing_mode.value,
            "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        },
        allow_empty_tax_target=True,
    )


def save_description_replacement(
    store: ConversionProfileStore,
    profile_id: str,
    original: str,
    replacement: str,
) -> ConversionProfile:
    """Same replacement dictionary as MF: one confirmation per original description."""
    if not replacement_is_valid(replacement) or unsafe_description_positions(replacement):
        raise ValueError("置換後の摘要はJDLで保持可能な1文字以上32文字以内にしてください。")
    profile = store.get(profile_id)
    key = moneyforward_description_replacement_key(original)
    policies = dict(profile.loss_policy_mappings)
    policies[key] = MappingValue(
        key, replacement, MappingStatus.USER_CONFIRMED,
        metadata={
            "policy": MF_DESCRIPTION_REPLACEMENT_POLICY,
            "original_description_sha256": description_sha256(original),
        },
    )
    return store.update(replace(profile, loss_policy_mappings=policies, updated_at=datetime.now(timezone.utc)))

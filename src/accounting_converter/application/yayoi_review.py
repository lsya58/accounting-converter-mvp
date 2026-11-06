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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Sequence

from accounting_converter.adapters.output.jdl import JdlTargetContext, JdlTaxRounding
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
    # 2026-11-05 campaign: 1-row round trips on the real JDL test company.
    JdlTaxSemantic.EXPORT_SALES: "EVID-YAYOI-JDL-35-5-BUDDIES-CAMP-BI-EXPORT-SYNTHETIC-ROUNDTRIP-001",
    JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL: "EVID-YAYOI-JDL-35-5-BUDDIES-CAMP-BI-RED8-SYNTHETIC-ROUNDTRIP-001",
    JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL: "EVID-YAYOI-JDL-35-5-BUDDIES-CAMP-BI-TRANS80-SYNTHETIC-ROUNDTRIP-001",
}
# Valid only inside the exact company scope of that Evidence (scoped_evidence).
SCOPED_SEMANTICS = frozenset({
    JdlTaxSemantic.EXPORT_SALES,
    JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL,
    JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL,
})
SCOPED_SEMANTIC_BLOCKED_REASON = (
    "この書き方は、実機で確認した会社設定（消費税の端数処理 売上=切上げ・仕入=四捨五入）でだけ確認できます。"
    "この会社の端数処理が異なるため、JDL実機での確認が必要です。"
)


# Only the exact Yayoi identities whose JDL representation was observed on the
# real JDL screen and round-tripped (2026-11-05). Variants (other invoice
# classes, other rates) are not candidates. 控除不可 stays without a candidate.
_EXACT_CANDIDATES = {
    "輸出売上": JdlTaxSemantic.EXPORT_SALES,
    "課対仕入8%（軽）｜適格｜100%": JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL,
    "課対仕入10%｜区分記載｜80%経過措置": JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL,
    "対外仕入": JdlTaxSemantic.NO_TAX,  # 対象外仕入: JDL receives no tax cell (same as 対象外)
}


def candidate_semantic(identity: str) -> JdlTaxSemantic | None:
    """Natural JDL candidate shown to the Human. Never applied without confirmation.

    Identities with an invoice class / purchase-credit ratio other than the
    ordinary 適格・100% case (経過措置 80%, 控除不可, 区分記載) get no candidate.
    """
    exact = _EXACT_CANDIDATES.get(identity)
    if exact is not None:
        return exact
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
    explicit_tax_unverified_lines: int  # explicit amount not proven to survive JDL unchanged
    candidate: JdlTaxSemantic | None
    mapping_state: str
    confirmed_semantic: JdlTaxSemantic | None
    evidence_state: str
    explicit_tax_gaps: dict = field(default_factory=dict)  # gap code -> lines


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
    rounding=None,
) -> YayoiSourceReview:
    """rounding: object with sales/purchase_tax_rounding; defaults to the context's."""
    has_target = context is not None
    accounts: dict[str, Counter] = defaultdict(Counter)
    account_journals: dict[str, set] = defaultdict(set)
    subs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    sub_journals: dict[tuple[str, str], set] = defaultdict(set)
    taxes: dict[str, Counter] = defaultdict(Counter)
    tax_journals: dict[str, set] = defaultdict(set)
    tax_attributes: dict[str, tuple[str, str, str]] = {}
    explicit_values: dict[str, list[tuple]] = defaultdict(list)
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
                explicit_values[identity].append((info.tax_amount, line.amount))
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
        gaps = Counter(
            ev.explicit_tax_gap(tax_amount, amount, semantic.value, context or rounding or _UNSET_ROUNDING)
            if semantic is not None else "NO_SEMANTIC"
            for tax_amount, amount in explicit_values[identity]
        )
        gaps.pop(None, None)
        counts["explicit_unverified"] = sum(gaps.values())
        tax_items.append(YayoiTaxIdentityItem(
            identity=identity,
            base=tax_attributes[identity][0],
            invoice_class=tax_attributes[identity][1],
            purchase_credit=tax_attributes[identity][2],
            debit_lines=counts["DEBIT"],
            credit_lines=counts["CREDIT"],
            journals=len(tax_journals[identity]),
            explicit_tax_lines=counts["explicit"],
            explicit_tax_unverified_lines=counts["explicit_unverified"],
            explicit_tax_gaps=dict(gaps),
            candidate=candidate_semantic(identity),
            mapping_state=state,
            confirmed_semantic=confirmed,
            evidence_state=_evidence_state(semantic, counts, context),
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


def _evidence_state(semantic: JdlTaxSemantic | None, counts: Counter, context=None) -> str:
    if semantic is None:
        return "NO_SEMANTIC"
    capabilities = ev.LINE_CAPABILITIES
    if context is not None and _scoped_applies(context):
        from accounting_converter.application.scoped_evidence_composition import UNITED_CAPABILITIES

        capabilities = UNITED_CAPABILITIES
    for side in ("DEBIT", "CREDIT"):
        if counts[side] and (side, semantic.value) not in capabilities:
            return "SIDE_PENDING"
    if counts["explicit_unverified"]:
        return "EXPLICIT_TAX_PENDING"
    return "AVAILABLE"


def _subaccount_mapping(profile, parent, sub):
    if profile is None:
        return None
    for key, value in profile.subaccount_context_mappings.items():
        if key.parent_account == parent and key.source_value == sub:
            return value
    return None


# Without a target company the JDL 端数処理 is unknown.
_UNSET_ROUNDING = SimpleNamespace(
    sales_tax_rounding=JdlTaxRounding.UNCONFIRMED, purchase_tax_rounding=JdlTaxRounding.UNCONFIRMED
)


class _EmptyProfile:
    loss_policy_mappings: dict = {}


_EMPTY_PROFILE = _EmptyProfile()


def create_yayoi_profile(
    store: ConversionProfileStore,
    display_name: str,
    entries: Sequence[JournalEntry],
    source_format=None,
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
        source_format_identity=(source_format.identity() if source_format else yayoi_journal_report_generic_identity()),
        target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        tax_mappings={
            identity: MappingValue(identity, None, MappingStatus.UNRESOLVED) for identity in identities
        },
        created_at=now,
        updated_at=now,
        notes=f"{source_format.label if source_format else '弥生 仕訳日記帳（汎用形式）'}から作成。科目・補助・税区分は対象JDL会社の確認後に明示確認する。",
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
    if semantic in SCOPED_SEMANTICS:
        from accounting_converter.adapters.output.jdl import scoped_evidence

        if not scoped_evidence.semantic_evidence_applies(context):
            raise ValueError(SCOPED_SEMANTIC_BLOCKED_REASON)
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


# Yayoi information with no place in the target JDL company (部門 when JDL has
# no departments, 生成元, 付箋, 仕訳メモ, 期日, 番号). JDL cannot hold it, so
# the only formal option is: not written to JDL, and every original value is
# written to an audit file next to the formal CSV (yayoi_jdl_workflow). A
# policy is never inferred; it needs the Human's statement of what the field
# means in this company's data.
OPTIONAL_FIELD_POLICY_PREFIX = "yayoi_optional_field:"
NOT_RETAINED_RECORDED_IN_AUDIT = "NOT_RETAINED_RECORDED_IN_AUDIT"
DEPARTMENT_FIELD = "部門"


def optional_field_policy_key(field_name: str) -> str:
    return f"{OPTIONAL_FIELD_POLICY_PREFIX}{field_name}"


def confirm_optional_field_policy(
    store: ConversionProfileStore,
    profile_id: str,
    field_name: str,
    meaning: str,
) -> ConversionProfile:
    if not meaning.strip():
        raise ValueError("項目の意味（何の情報か）を記入してください。")
    profile = store.get(profile_id)
    key = optional_field_policy_key(field_name)
    policies = dict(profile.loss_policy_mappings)
    policies[key] = MappingValue(
        key, NOT_RETAINED_RECORDED_IN_AUDIT, MappingStatus.USER_CONFIRMED,
        metadata={"field": field_name, "meaning": meaning.strip()},
    )
    return store.update(replace(profile, loss_policy_mappings=policies, updated_at=datetime.now(timezone.utc)))


def confirmed_optional_fields(profile) -> dict[str, str]:
    """field -> Human-stated meaning, for confirmed audit-only policies."""
    result = {}
    for key, value in (getattr(profile, "loss_policy_mappings", None) or {}).items():
        if (
            key.startswith(OPTIONAL_FIELD_POLICY_PREFIX)
            and value.status is MappingStatus.USER_CONFIRMED
            and value.target_value == NOT_RETAINED_RECORDED_IN_AUDIT
            and str(value.metadata.get("meaning", "")).strip()
        ):
            result[key[len(OPTIONAL_FIELD_POLICY_PREFIX):]] = str(value.metadata["meaning"])
    return result


NON_RETAINED_VALUES_KEY = "yayoi_non_retained_values"


def non_retained_values(entry) -> tuple[tuple[int, str, str], ...]:
    """(row, field, value) of everything in this journal that JDL will not hold."""
    if NON_RETAINED_VALUES_KEY in entry.metadata:  # already removed from the lines
        return tuple(entry.metadata[NON_RETAINED_VALUES_KEY])
    values = list(entry.metadata.get("yayoi_optional_values", ()))
    for line in entry.lines:
        if line.department:
            row = int(line.metadata.get("journal_row_number", line.source_reference.row_number))
            values.append((row, f"{DEPARTMENT_FIELD}({line.side.value})", line.department))
    return tuple(values)


def field_of(name: str) -> str:
    return DEPARTMENT_FIELD if name.startswith(DEPARTMENT_FIELD) else name


def yayoi_tax_mapping_review(profile, context, *, affected_counts=None, observed_source_values=()):
    """Yayoi tax identities in the same shape the existing tax screen shows for MF.

    HUMAN: a candidate JDL literal exists in a verified Tax Context; the Human
    confirms it. SYSTEM_EVIDENCE: no candidate (e.g. 軽減8%, 経過措置80%,
    控除不可) - not confirmable on screen, the JDL representation is unverified.
    """
    from accounting_converter.application.moneyforward_profile_setup import (
        TaxMappingSetupItem,
        TaxMappingSetupReview,
    )

    affected_counts = affected_counts or {}
    verified = ev.context_is_verified(context)
    values = observed_source_values or tuple(profile.tax_mappings)
    items = []
    for value in values:
        mapping = profile.tax_mappings.get(value)
        if (
            mapping is not None and mapping.status is MappingStatus.USER_CONFIRMED
            and mapping.metadata.get("jdl_tax_context_identity_sha256") == ev.tax_context_identity_sha256(context)
        ):
            continue
        semantic = candidate_semantic(value)
        literal = JDL_TAX_LITERALS.get(semantic) if semantic is not None else None
        scoped_blocked = bool(
            semantic in SCOPED_SEMANTICS and verified and not _scoped_applies(context)
        )
        confirmable = bool(semantic is not None and verified and not scoped_blocked)
        items.append(TaxMappingSetupItem(
            source_value=value,
            target_value=literal.category if literal else None,
            target_display=_TAX_DISPLAY.get(semantic, "候補なし") if semantic else "候補なし",
            target_scope=literal.scope if literal else "",
            evidence_id=SEMANTIC_EVIDENCE_ID.get(semantic) if semantic else None,
            human_confirmable=confirmable,
            action_owner="HUMAN" if confirmable else "SYSTEM_EVIDENCE",
            blocker_code="YAYOI-JDL-TAX-HUMAN-CONFIRMATION" if confirmable else "YAYOI-JDL-TAX-REPRESENTATION-UNVERIFIED",
            reason=(
                "候補の書き方でよいか確認してください（候補は自動では確定しません）。"
                if confirmable else
                SCOPED_SEMANTIC_BLOCKED_REASON if scoped_blocked else
                "JDLでの書き方が実機で確認されていません（控除不可など）。"
            ),
            affected_row_count=affected_counts.get(value, 0),
        ))
    return TaxMappingSetupReview(
        items=tuple(items),
        context_compatible=verified,
        user_message="税区分はすべて確認済みです。" if not items else "",
    )


def _scoped_applies(context) -> bool:
    from accounting_converter.adapters.output.jdl import scoped_evidence

    return scoped_evidence.semantic_evidence_applies(context)


_TAX_DISPLAY = {
    JdlTaxSemantic.EXPORT_SALES: "輸出売上（課区 輸出売）",
    JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL: "仕入 / 軽減8%（内税）",
    JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL: "仕入 / 10%免80・経過措置80%（内税）",
    JdlTaxSemantic.NO_TAX: "対象外（税なし）",
    JdlTaxSemantic.PURCHASE_10_INTERNAL: "仕入 / 10%（内税）",
    JdlTaxSemantic.SALES_10_EXTERNAL: "売上 / 10%（外税）",
    JdlTaxSemantic.NON_TAXABLE_PURCHASE: "非課税仕入（課区 非仕入）",
    JdlTaxSemantic.NON_TAXABLE_SALES: "非課税売上（課区 非売上）",
}

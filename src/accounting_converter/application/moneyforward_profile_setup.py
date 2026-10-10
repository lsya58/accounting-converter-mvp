from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlOutputRuntimeFactory,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.mapping_review import (
    MappingConfirmationService,
    MappingRequirementExtractor,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class MoneyForwardProfileSetupError(ValueError):
    pass


PENDING_SETUP_METADATA_KEY = "pending_setup_field_types"
MF_PURCHASE_TAX_10 = "課税仕入 10%"
JDL_PURCHASE_TAX_10 = "10%"
JDL_PURCHASE_TAX_SCOPE = "仕　入"
EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP = (
    "EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001"
)


@dataclass(frozen=True)
class AccountMappingSetupItem:
    source_value: str
    available_targets: tuple[str, ...]
    exact_candidate: str | None = None


@dataclass(frozen=True)
class TaxMappingSetupItem:
    source_value: str
    target_value: str
    target_display: str
    evidence_id: str


@dataclass(frozen=True)
class TaxMappingSetupReview:
    items: tuple[TaxMappingSetupItem, ...] = ()
    context_compatible: bool = False
    user_message: str = ""


@dataclass(frozen=True)
class MoneyForwardProfileSetupAnalysis:
    source_path: Path
    context_path: Path
    context: JdlTargetContext
    context_sha256: str
    account_items: tuple[AccountMappingSetupItem, ...]
    unsupported_field_types: tuple[str, ...] = ()
    unresolved_tax_categories: tuple[str, ...] = ()
    pending_field_keys: tuple[str, ...] = ()
    tax_items: tuple[TaxMappingSetupItem, ...] = ()
    tax_context_compatible: bool = False
    tax_context_message: str = ""

    @property
    def can_configure_accounts(self) -> bool:
        return bool(self.account_items)

    @property
    def requires_additional_setup(self) -> bool:
        return bool(self.unsupported_field_types)


class MoneyForwardProfileSetupService:
    """Creates a schema-v3 profile from explicit account confirmations only."""

    UNSUPPORTED_LABELS = {
        "subaccount": "補助科目",
        "department": "部門",
        "tax": "税区分",
        "trade_partner": "取引先",
        "invoice": "インボイス",
        "tag": "タグ",
        "memo": "メモ",
        "description": "摘要",
    }

    def __init__(self, profile_store: ConversionProfileStore) -> None:
        self.profile_store = profile_store
        self.context_loader = JdlTargetContextLoader()

    def analyze(self, source_path: Path, context_path: Path) -> MoneyForwardProfileSetupAnalysis:
        before = self._hash(source_path)
        context = self.context_loader.load(context_path)
        adapter = MoneyForwardInputAdapter()
        schema = moneyforward_cloud_journal_export_observed_schema()
        source_profile = FormatProfile(
            software="Money Forward",
            product="Money Forward クラウド会計",
            version="UNKNOWN",
            format_id=schema.identity.stable_key,
            encoding="cp932",
        )
        try:
            entries = tuple(adapter.read(source_path, source_profile))
        except Exception as exc:
            raise MoneyForwardProfileSetupError(
                "Money Forwardの仕訳CSVとして確認できませんでした。"
            ) from exc
        if self._hash(source_path) != before:
            raise MoneyForwardProfileSetupError("入力CSVが解析中に変更されました。")

        requirements = MappingRequirementExtractor().extract(entries)
        unsupported: set[str] = set()
        if requirements.subaccounts:
            unsupported.add("subaccount")
        if requirements.departments:
            unsupported.add("department")
        if requirements.tax_categories:
            unsupported.add("tax")
        for entry in entries:
            if entry.metadata.get("moneyforward_tags"):
                unsupported.add("tag")
            if entry.metadata.get("moneyforward_memos"):
                unsupported.add("memo")
            descriptions = {
                item["value"]
                for item in entry.metadata.get("moneyforward_descriptions", ())
                if item.get("value")
            }
            if len(descriptions) > 1:
                unsupported.add("description")
            for line in entry.lines:
                if line.metadata.get("moneyforward_trade_partner"):
                    unsupported.add("trade_partner")
                if line.tax_info and line.tax_info.invoice_classification:
                    unsupported.add("invoice")

        targets = tuple(item.mapping_value for item in context.account_master)
        items = tuple(
            AccountMappingSetupItem(
                source_value=requirement.source_value,
                available_targets=targets,
                exact_candidate=self._exact_candidate(
                    requirement.source_value, context.account_master
                ),
            )
            for requirement in requirements.accounts
        )
        return MoneyForwardProfileSetupAnalysis(
            source_path=source_path,
            context_path=context_path,
            context=context,
            context_sha256=self._hash(context_path),
            account_items=items,
            unsupported_field_types=tuple(
                self.UNSUPPORTED_LABELS[key] for key in sorted(unsupported)
            ),
            unresolved_tax_categories=tuple(
                item.source_value for item in requirements.tax_categories
            ),
            pending_field_keys=tuple(sorted(unsupported)),
            tax_items=self._tax_items(
                tuple(item.source_value for item in requirements.tax_categories),
                context,
            ),
            tax_context_compatible=self._tax_context_compatible(context),
            tax_context_message=self._tax_context_message(
                tuple(item.source_value for item in requirements.tax_categories),
                context,
            ),
        )

    def save_confirmed_profile(
        self,
        *,
        company_display_name: str,
        analysis: MoneyForwardProfileSetupAnalysis,
        selections: Mapping[str, str],
        explicitly_confirmed: set[str],
        explicitly_confirmed_tax: set[str] | None = None,
    ) -> ConversionProfile:
        if not analysis.can_configure_accounts:
            raise MoneyForwardProfileSetupError("設定する科目が見つかりませんでした。")
        required = {item.source_value for item in analysis.account_items}
        if set(selections) != required or explicitly_confirmed != required:
            raise MoneyForwardProfileSetupError("すべての科目対応を明示確認してください。")
        by_target = {item.mapping_value: item for item in analysis.context.account_master}
        if any(target not in by_target for target in selections.values()):
            raise MoneyForwardProfileSetupError("JDL設定に存在しない科目が選択されています。")
        confirmed_tax = explicitly_confirmed_tax or set()
        eligible_tax = {item.source_value for item in analysis.tax_items}
        if not confirmed_tax <= eligible_tax:
            raise MoneyForwardProfileSetupError(
                "現在のJDL設定ではこの税区分を確認できません。"
            )

        now = datetime.now(timezone.utc)
        profile_id = f"mf-jdl-{uuid.uuid4().hex}"
        context_sha256 = self._hash(analysis.context_path)
        if context_sha256 != analysis.context_sha256:
            raise MoneyForwardProfileSetupError(
                "JDL設定が確認後に変更されました。もう一度確認してください。"
            )
        profile = ConversionProfile(
            profile_id=profile_id,
            profile_name=f"{company_display_name.strip()} Money Forward → JDL",
            source_format_identity=moneyforward_cloud_journal_export_observed_schema().identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            tax_mappings={
                source_value: MappingValue(
                    source_value=source_value,
                    target_value=None,
                    status=MappingStatus.UNRESOLVED,
                )
                for source_value in analysis.unresolved_tax_categories
            },
            created_at=now,
            updated_at=now,
            notes=(
                "Money Forward科目対応をユーザーが明示確認して作成。"
                "未設定項目がある場合は変換時preflightで停止。production READYを意味しません。"
            ),
        )
        self.profile_store.create(profile)
        confirmation = MappingConfirmationService(self.profile_store)
        try:
            pending_keys = set(analysis.pending_field_keys)
            if set(analysis.unresolved_tax_categories) <= confirmed_tax:
                pending_keys.discard("tax")
            for source_value in sorted(required):
                target = by_target[selections[source_value]]
                confirmation.confirm_mapping(
                    profile_id,
                    MappingKey(MappingType.ACCOUNT, source_value),
                    target.mapping_value,
                    metadata={
                        "target_code": target.target_master_code,
                        "target_formal_name": target.target_formal_name,
                        "setup_context_sha256": context_sha256,
                        PENDING_SETUP_METADATA_KEY: ",".join(
                            sorted(pending_keys)
                        ),
                    },
                )
            for source_value in sorted(confirmed_tax):
                item = next(
                    candidate
                    for candidate in analysis.tax_items
                    if candidate.source_value == source_value
                )
                confirmation.confirm_mapping(
                    profile_id,
                    MappingKey(MappingType.TAX_CATEGORY, source_value),
                    item.target_value,
                    metadata=self._tax_mapping_metadata(item, context_sha256),
                )
            saved = self.profile_store.get(profile_id)
            runtime = JdlOutputRuntimeFactory().resolve(
                jdl_ibex_35_5_output_profile(), saved, analysis.context
            )
            if not runtime.resolved:
                raise MoneyForwardProfileSetupError(
                    "対応設定とJDL設定の整合を確認できませんでした。"
                )
            return saved
        except Exception:
            try:
                self.profile_store.delete(profile_id)
            except Exception:
                pass
            raise

    def tax_mapping_review(
        self,
        profile: ConversionProfile,
        context: JdlTargetContext,
    ) -> TaxMappingSetupReview:
        if not self._profile_identity_compatible(profile):
            return TaxMappingSetupReview(
                user_message="現在のJDL設定ではこの税区分を確認できません"
            )
        purchase_mapping = profile.tax_mappings.get(MF_PURCHASE_TAX_10)
        if purchase_mapping is None:
            return TaxMappingSetupReview(
                context_compatible=self._tax_context_compatible(context),
                user_message=(
                    "対応設定に「課税仕入 10%」の未設定要件がありません。"
                    "税区分を含むMoney Forward CSVから対応設定を作成してください。"
                ),
            )
        if purchase_mapping.is_resolved:
            return TaxMappingSetupReview(
                context_compatible=self._tax_context_compatible(context),
                user_message="「課税仕入 10%」は確認済みです。",
            )
        unresolved = tuple(
            source_value
            for source_value, mapping in profile.tax_mappings.items()
            if not mapping.is_resolved
        )
        items = self._tax_items(unresolved, context)
        compatible = self._tax_context_compatible(context)
        return TaxMappingSetupReview(
            items=items,
            context_compatible=compatible,
            user_message=self._tax_context_message(unresolved, context),
        )

    def confirm_evidence_backed_tax_mapping(
        self,
        *,
        profile_id: str,
        context: JdlTargetContext,
        source_value: str,
    ) -> ConversionProfile:
        profile = self.profile_store.get(profile_id)
        review = self.tax_mapping_review(profile, context)
        item = next(
            (candidate for candidate in review.items if candidate.source_value == source_value),
            None,
        )
        if item is None:
            raise MoneyForwardProfileSetupError(
                "現在のJDL設定ではこの税区分を確認できません。"
            )
        return MappingConfirmationService(self.profile_store).confirm_mapping(
            profile_id,
            MappingKey(MappingType.TAX_CATEGORY, source_value),
            item.target_value,
            metadata=self._tax_mapping_metadata(item),
        )

    @staticmethod
    def _profile_identity_compatible(profile: ConversionProfile) -> bool:
        return bool(
            profile.source_format_identity.stable_key
            == moneyforward_cloud_journal_export_observed_schema().identity.stable_key
            and profile.target_format_identity.stable_key
            == jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key
        )

    @staticmethod
    def _tax_context_compatible(context: JdlTargetContext) -> bool:
        from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

        return bool(
            context.product == "JDL IBEX 出納帳"
            and context.version == "35.5"
            and context.tax_processing_mode
            is JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED
            and context.standard_taxation_confirmed
            and context.individual_credit_method_confirmed
            and context.no_fuzzy_matching
            and context.no_automatic_replacement
        )

    @classmethod
    def _tax_items(
        cls,
        source_values: tuple[str, ...],
        context: JdlTargetContext,
    ) -> tuple[TaxMappingSetupItem, ...]:
        if not cls._tax_context_compatible(context) or MF_PURCHASE_TAX_10 not in source_values:
            return ()
        return (
            TaxMappingSetupItem(
                source_value=MF_PURCHASE_TAX_10,
                target_value=JDL_PURCHASE_TAX_10,
                target_display="仕入 / 10%",
                evidence_id=EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP,
            ),
        )

    @classmethod
    def _tax_context_message(
        cls,
        source_values: tuple[str, ...],
        context: JdlTargetContext,
    ) -> str:
        if MF_PURCHASE_TAX_10 in source_values and not cls._tax_context_compatible(context):
            return "現在のJDL設定ではこの税区分を確認できません"
        return ""

    @staticmethod
    def _tax_mapping_metadata(
        item: TaxMappingSetupItem,
        context_sha256: str | None = None,
    ) -> dict[str, str]:
        return {
            "jdl_tax_scope": JDL_PURCHASE_TAX_SCOPE,
            "jdl_evidence_id": item.evidence_id,
            "jdl_tax_processing_mode": "TAXABLE_TAX_INCLUDED",
            **(
                {"setup_context_sha256": context_sha256}
                if context_sha256 is not None
                else {}
            ),
        }

    @staticmethod
    def _exact_candidate(
        source_value: str,
        targets: tuple[JdlAccountIdentity, ...],
    ) -> str | None:
        matches = {
            item.mapping_value
            for item in targets
            if source_value in {
                item.mapping_value,
                item.target_name,
                item.target_formal_name,
            }
        }
        return next(iter(matches)) if len(matches) == 1 else None

    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_pending_setup_field_types(
    profile: ConversionProfile,
) -> tuple[str, ...]:
    keys: set[str] = set()
    for mapping in profile.account_mappings.values():
        keys.update(
            key
            for key in mapping.metadata.get(PENDING_SETUP_METADATA_KEY, "").split(",")
            if key
        )
    if profile.tax_mappings and all(
        mapping.is_resolved for mapping in profile.tax_mappings.values()
    ):
        keys.discard("tax")
    return tuple(
        MoneyForwardProfileSetupService.UNSUPPORTED_LABELS[key]
        for key in sorted(keys)
        if key in MoneyForwardProfileSetupService.UNSUPPORTED_LABELS
    )

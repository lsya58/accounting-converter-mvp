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
from accounting_converter.application.jdl_master_observation import (
    JdlMasterObservationService,
    JdlPrintedAccount,
)
from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    BATCH_EVIDENCE_ID as TAX_EXCLUDED_PROPORTIONAL_BATCH_EVIDENCE_ID,
    TAX_MAPPING_SPECS,
    confirmed_mapping_is_in_scope as tax_excluded_mapping_is_in_scope,
    context_is_verified as tax_excluded_proportional_context_verified,
    tax_context_identity_sha256 as tax_excluded_context_identity_sha256,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.mf_outpur_scope import OUTPUR_TAX_MAPPING_EVIDENCE_ID
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.infrastructure.jdl_account_pdf_draft import (
    JdlAccountPdfDraftStore,
)
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
    target_value: str | None = None
    target_display: str = "未確定"
    target_scope: str = ""
    evidence_id: str | None = None
    human_confirmable: bool = False
    action_owner: str = "SYSTEM_EVIDENCE"
    blocker_code: str = "MF-JDL-TAX-EVIDENCE-MISSING-EXACT"
    reason: str = "この税区分には、現在のJDL設定で使える実機Evidenceがありません。"
    affected_row_count: int = 0

    @property
    def state(self) -> str:
        return "HUMAN_CONFIRMATION_REQUIRED" if self.human_confirmable else "BLOCKED"


@dataclass(frozen=True)
class TaxMappingSetupReview:
    items: tuple[TaxMappingSetupItem, ...] = ()
    context_compatible: bool = False
    user_message: str = ""
    stale_source_values: tuple[str, ...] = ()

    @property
    def confirmable_items(self) -> tuple[TaxMappingSetupItem, ...]:
        return tuple(item for item in self.items if item.human_confirmable)

    @property
    def blocked_items(self) -> tuple[TaxMappingSetupItem, ...]:
        return tuple(item for item in self.items if not item.human_confirmable)


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
    observed_account_targets: tuple[JdlPrintedAccount, ...] = ()
    context_is_draft: bool = False

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
        "jdl_context_confirmation": "JDL設定の確認",
    }

    def __init__(self, profile_store: ConversionProfileStore) -> None:
        self.profile_store = profile_store
        self.context_loader = JdlTargetContextLoader()
        self.account_pdf_drafts = JdlAccountPdfDraftStore()

    def create_company_draft_profile(
        self, company_display_name: str, context_path: Path
    ) -> ConversionProfile:
        """Create an empty, company-scoped profile before the first CSV review."""
        if not company_display_name.strip():
            raise MoneyForwardProfileSetupError("会社設定名を入力してください。")
        if not self.account_pdf_drafts.is_draft(context_path):
            raise MoneyForwardProfileSetupError("JDL科目一覧を読み込んでください。")
        self.account_pdf_drafts.load(context_path)
        now = datetime.now(timezone.utc)
        profile = ConversionProfile(
            profile_id=f"mf-jdl-{uuid.uuid4().hex}",
            profile_name=f"{company_display_name.strip()} Money Forward → JDL",
            source_format_identity=(
                moneyforward_cloud_journal_export_observed_schema().identity
            ),
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            created_at=now,
            updated_at=now,
            notes=(
                "会社固有JDL科目一覧から作成。科目・補助科目・税区分は"
                "CSV読込後にユーザーが明示確認する。production READYを意味しません。"
            ),
        )
        self.profile_store.create(profile)
        return profile

    def analyze(self, source_path: Path, context_path: Path) -> MoneyForwardProfileSetupAnalysis:
        before = self._hash(source_path)
        context_is_draft = self.account_pdf_drafts.is_draft(context_path)
        observed_targets: tuple[JdlPrintedAccount, ...] = ()
        if context_is_draft:
            pdf_draft = self.account_pdf_drafts.load(context_path)
            context = JdlMasterObservationService().build_unconfirmed_context_draft(
                pdf_draft.observation
            ).context
            observed_targets = tuple(
                item for item in pdf_draft.observation.printed_accounts if item.enabled
            )
        else:
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
        if context_is_draft:
            unsupported.add("jdl_context_confirmation")
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

        targets = (
            tuple(item.name for item in observed_targets)
            if context_is_draft
            else tuple(item.mapping_value for item in context.account_master)
        )
        items = tuple(
            AccountMappingSetupItem(
                source_value=requirement.source_value,
                available_targets=targets,
                exact_candidate=(
                    self._exact_printed_candidate(
                        requirement.source_value, observed_targets
                    )
                    if context_is_draft
                    else self._exact_candidate(
                        requirement.source_value, context.account_master
                    )
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
            tax_items=() if context_is_draft else self._tax_items(
                tuple(item.source_value for item in requirements.tax_categories),
                context,
                affected_counts={
                    item.source_value: item.occurrence_count
                    for item in requirements.tax_categories
                },
            ),
            tax_context_compatible=(
                False if context_is_draft else self._tax_context_compatible(context)
            ),
            tax_context_message=(
                "JDLの税設定を確認するまで税区分は設定できません"
                if context_is_draft and requirements.tax_categories
                else self._tax_context_message(
                    tuple(
                        item.source_value for item in requirements.tax_categories
                    ),
                    context,
                )
            ),
            observed_account_targets=observed_targets,
            context_is_draft=context_is_draft,
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
        by_target = (
            {item.name: item for item in analysis.observed_account_targets}
            if analysis.context_is_draft
            else {item.mapping_value: item for item in analysis.context.account_master}
        )
        if any(target not in by_target for target in selections.values()):
            raise MoneyForwardProfileSetupError("JDL設定に存在しない科目が選択されています。")
        confirmed_tax = explicitly_confirmed_tax or set()
        eligible_tax = {
            item.source_value for item in analysis.tax_items if item.human_confirmable
        }
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
        tax_context_sha256 = hashlib.sha256(
            JdlTargetContextLoader().to_json_text(analysis.context).encode("utf-8")
        ).hexdigest()
        try:
            pending_keys = set(analysis.pending_field_keys)
            if set(analysis.unresolved_tax_categories) <= confirmed_tax:
                pending_keys.discard("tax")
            for source_value in sorted(required):
                target = by_target[selections[source_value]]
                target_value = (
                    target.name if analysis.context_is_draft else target.mapping_value
                )
                target_code = (
                    target.code
                    if analysis.context_is_draft
                    else target.target_master_code
                )
                target_metadata = (
                    {
                        "target_code": target_code,
                        "target_printed_name": target.name,
                        "target_abbreviation": target.abbreviation,
                    }
                    if analysis.context_is_draft
                    else {
                        "target_code": target_code,
                        "target_formal_name": target.target_formal_name,
                    }
                )
                confirmation.confirm_mapping(
                    profile_id,
                    MappingKey(MappingType.ACCOUNT, source_value),
                    target_value,
                    metadata={
                        **target_metadata,
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
                    metadata=self._tax_mapping_metadata(
                        item, tax_context_sha256, analysis.context
                    ),
                )
            saved = self.profile_store.get(profile_id)
            runtime = (
                None
                if analysis.context_is_draft
                else JdlOutputRuntimeFactory().resolve(
                    jdl_ibex_35_5_output_profile(), saved, analysis.context
                )
            )
            if runtime is not None and not runtime.resolved:
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
        *,
        affected_counts: Mapping[str, int] | None = None,
        observed_source_values: tuple[str, ...] = (),
    ) -> TaxMappingSetupReview:
        if not self._profile_identity_compatible(profile):
            return TaxMappingSetupReview(
                items=tuple(
                    TaxMappingSetupItem(
                        source_value=value,
                        action_owner="SYSTEM_IMPLEMENTATION",
                        blocker_code="MF-JDL-TAX-ROUTE-MISMATCH",
                        reason="会社設定の入力元・変換先形式が一致していません。",
                    )
                    for value, mapping in profile.tax_mappings.items()
                    if not mapping.is_resolved
                ),
                user_message="現在のJDL設定ではこの税区分を確認できません"
            )
        if not profile.tax_mappings and not observed_source_values:
            return TaxMappingSetupReview(
                context_compatible=self._tax_context_compatible(context),
                user_message=(
                    "対応設定に税区分の未設定要件がありません。"
                    "税区分を含むMoney Forward CSVから対応設定を作成してください。"
                ),
            )
        stale = tuple(
            source_value
            for source_value, mapping in profile.tax_mappings.items()
            if (not observed_source_values or source_value in observed_source_values)
            if mapping.is_resolved
            and tax_excluded_proportional_context_verified(context)
            and not tax_excluded_mapping_is_in_scope(
                source_value, mapping, context
            )
        )
        unresolved = tuple(
            source_value
            for source_value, mapping in profile.tax_mappings.items()
            if (not observed_source_values or source_value in observed_source_values)
            if not mapping.is_resolved
            or source_value in stale
        )
        evidence_missing = tuple(
            source for source in observed_source_values
            if source and source not in unresolved
            and not self._tax_items((source,), context)[0].human_confirmable
        )
        unresolved = tuple(dict.fromkeys((*unresolved, *evidence_missing)))
        if not unresolved:
            return TaxMappingSetupReview(
                context_compatible=self._tax_context_compatible(context),
                user_message="税区分はすべて確認済みです。",
            )
        items = self._tax_items(
            unresolved,
            context,
            affected_counts=affected_counts,
        )
        compatible = self._tax_context_compatible(context)
        return TaxMappingSetupReview(
            items=items,
            context_compatible=compatible,
            user_message=(
                "税区分の確認内容が更新されています。再確認してください。"
                if stale
                else self._tax_context_message(unresolved, context)
            ),
            stale_source_values=stale,
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
            (
                candidate
                for candidate in review.items
                if candidate.source_value == source_value
                and candidate.human_confirmable
            ),
            None,
        )
        if item is None:
            raise MoneyForwardProfileSetupError(
                "現在のJDL設定ではこの税区分を確認できません。"
            )
        context_sha256 = hashlib.sha256(
            JdlTargetContextLoader().to_json_text(context).encode("utf-8")
        ).hexdigest()
        return MappingConfirmationService(self.profile_store).confirm_mapping(
            profile_id,
            MappingKey(MappingType.TAX_CATEGORY, source_value),
            item.target_value,
            metadata=self._tax_mapping_metadata(item, context_sha256, context),
            allow_empty_tax_target=True,
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

        return tax_excluded_proportional_context_verified(context) or bool(
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
        *,
        affected_counts: Mapping[str, int] | None = None,
    ) -> tuple[TaxMappingSetupItem, ...]:
        context_compatible = cls._tax_context_compatible(context)
        affected_counts = affected_counts or {}
        if tax_excluded_proportional_context_verified(context):
            specs = {
                MF_PURCHASE_TAX_10: (
                    "10%", "仕入 / 10%（税抜）", "仕　入",
                    TAX_EXCLUDED_PROPORTIONAL_BATCH_EVIDENCE_ID,
                ),
                "対象外": (
                    "", "対象外", "", TAX_EXCLUDED_PROPORTIONAL_BATCH_EVIDENCE_ID,
                ),
                "対象外仕入": (
                    "", "対象外（CSV税欄は空欄・税額0）", "", OUTPUR_TAX_MAPPING_EVIDENCE_ID,
                ),
                "非課税仕入": (
                    "", "非課税仕入（課区 非仕入）", "非仕入",
                    TAX_MAPPING_SPECS["非課税仕入"][2],
                ),
                "非課税売上": (
                    "", "非課税売上（課区 非売上）", "非売上",
                    TAX_MAPPING_SPECS["非課税売上"][2],
                ),
                "課税売上 10%": (
                    "10%", "売上 / 10%（外税）", "売　上",
                    TAX_MAPPING_SPECS["課税売上 10%"][2],
                ),
            }
        else:
            specs = {
            MF_PURCHASE_TAX_10: ("10%", "仕入 / 10%", "仕　入", EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP),
            "課税売上 10%": ("10%", "売上 / 10%", "売一種", "EVID-JDL-MF-TAX-SALES-10-SUBACCOUNT-ROUNDTRIP-001"),
            "課税仕入 (軽)8%": ("軽減8%", "仕入 / 軽減8%", "仕　入", "EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"),
            "課税売上 (軽)8%": ("軽減8%", "売上 / 軽減8%", "売一種", "EVID-JDL-MF-TAX-SALES-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001"),
            "非課税仕入": ("", "非課税仕入", "非仕入", "EVID-JDL-MF-TAX-NONTAXABLE-PURCHASE-SUBACCOUNT-ROUNDTRIP-001"),
            "非課税売上": ("", "非課税売上", "非売上", "EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001"),
                "対象外": ("", "対象外", "", "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"),
            }
        items: list[TaxMappingSetupItem] = []
        for source in source_values:
            if not source:
                continue
            if not context_compatible:
                items.append(
                    TaxMappingSetupItem(
                        source_value=source,
                        action_owner="HUMAN",
                        blocker_code="MF-JDL-TAX-CONTEXT-CONFIRMATION-REQUIRED",
                        reason=(
                            "会社のJDL税設定を確認すると、この税区分の候補を評価できます。"
                        ),
                        affected_row_count=affected_counts.get(source, 0),
                    )
                )
                continue
            spec = specs.get(source)
            if spec is None:
                items.append(
                    TaxMappingSetupItem(
                        source_value=source,
                        affected_row_count=affected_counts.get(source, 0),
                    )
                )
                continue
            target, display, scope, evidence = spec
            items.append(
                TaxMappingSetupItem(
                    source_value=source,
                    target_value=target,
                    target_display=display,
                    target_scope=scope,
                    evidence_id=evidence,
                    human_confirmable=True,
                    action_owner="HUMAN",
                    blocker_code="MF-JDL-TAX-HUMAN-CONFIRMATION-REQUIRED",
                    reason=(
                        "実機Evidenceと現在のJDL税設定が一致しています。内容を確認してください。"
                    ),
                    affected_row_count=affected_counts.get(source, 0),
                )
            )
        return tuple(items)

    @classmethod
    def _tax_context_message(
        cls,
        source_values: tuple[str, ...],
        context: JdlTargetContext,
    ) -> str:
        if source_values and not cls._tax_context_compatible(context):
            return "現在のJDL設定ではこの税区分を確認できません"
        known = {
            item.source_value
            for item in cls._tax_items(source_values, context)
            if item.human_confirmable
        }
        if set(source_values) - known:
            return "確認できない税区分があります。未確認の税区分は変換できません。"
        return ""

    @staticmethod
    def _tax_mapping_metadata(
        item: TaxMappingSetupItem,
        context_sha256: str | None = None,
        context: JdlTargetContext | None = None,
    ) -> dict[str, str]:
        if not item.human_confirmable or item.target_value is None or not item.evidence_id:
            raise MoneyForwardProfileSetupError(
                "実機Evidenceが確認できない税区分は保存できません。"
            )
        return {
            "jdl_tax_scope": item.target_scope,
            "jdl_evidence_id": item.evidence_id,
            "jdl_tax_processing_mode": (
                context.tax_processing_mode.value
                if context is not None else "TAXABLE_TAX_INCLUDED"
            ),
            **(
                {
                    "jdl_tax_context_identity_sha256": (
                        tax_excluded_context_identity_sha256(context)
                    )
                }
                if context is not None
                and tax_excluded_proportional_context_verified(context)
                else {}
            ),
            **(
                {
                    "setup_context_sha256": context_sha256,
                    "jdl_context_sha256": context_sha256,
                }
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
    def _exact_printed_candidate(
        source_value: str,
        targets: tuple[JdlPrintedAccount, ...],
    ) -> str | None:
        matches = {item.name for item in targets if item.name == source_value}
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

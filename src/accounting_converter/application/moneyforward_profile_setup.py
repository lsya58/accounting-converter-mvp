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


@dataclass(frozen=True)
class AccountMappingSetupItem:
    source_value: str
    available_targets: tuple[str, ...]
    exact_candidate: str | None = None


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
        )

    def save_confirmed_profile(
        self,
        *,
        company_display_name: str,
        analysis: MoneyForwardProfileSetupAnalysis,
        selections: Mapping[str, str],
        explicitly_confirmed: set[str],
    ) -> ConversionProfile:
        if not analysis.can_configure_accounts:
            raise MoneyForwardProfileSetupError("設定する科目が見つかりませんでした。")
        required = {item.source_value for item in analysis.account_items}
        if set(selections) != required or explicitly_confirmed != required:
            raise MoneyForwardProfileSetupError("すべての科目対応を明示確認してください。")
        by_target = {item.mapping_value: item for item in analysis.context.account_master}
        if any(target not in by_target for target in selections.values()):
            raise MoneyForwardProfileSetupError("JDL設定に存在しない科目が選択されています。")

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
                            analysis.pending_field_keys
                        ),
                    },
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
    return tuple(
        MoneyForwardProfileSetupService.UNSUPPORTED_LABELS[key]
        for key in sorted(keys)
        if key in MoneyForwardProfileSetupService.UNSUPPORTED_LABELS
    )

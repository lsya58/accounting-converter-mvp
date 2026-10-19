from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from accounting_converter.application.moneyforward_trade_partner import (
    TRADE_PARTNER_1D1C_EVIDENCE_ID,
)
from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.domain.conversion_profile import (
    LossPolicy,
    TRADE_PARTNER_LOSS_POLICY_KEY,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader


@dataclass(frozen=True)
class TradePartnerPolicyState:
    confirmed: bool
    context_compatible: bool


class CompanyTradePartnerPolicyService:
    def __init__(self, company_store: CompanySettingStore, profile_store: ConversionProfileStore) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.contexts = JdlTargetContextLoader()
        self.drafts = JdlAccountPdfDraftStore()

    def state(self, company_setting_id: str) -> TradePartnerPolicyState:
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            return TradePartnerPolicyState(False, False)
        context_hash = self._context_hash(path)
        mapping = profile.loss_policy_mappings.get(TRADE_PARTNER_LOSS_POLICY_KEY)
        confirmed = bool(
            mapping
            and mapping.status is MappingStatus.USER_CONFIRMED
            and mapping.target_value
            == LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value
            and mapping.metadata.get("jdl_context_sha256") == context_hash
            and mapping.metadata.get("jdl_evidence_id")
            == TRADE_PARTNER_1D1C_EVIDENCE_ID
        )
        return TradePartnerPolicyState(confirmed, True)

    def confirm(self, company_setting_id: str) -> None:
        setting = self.company_store.get(company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            raise ValueError("JDL設定の確認完了後に取引先の扱いを設定してください。")
        context_hash = self._context_hash(path)
        policies = dict(old.loss_policy_mappings)
        policies[TRADE_PARTNER_LOSS_POLICY_KEY] = MappingValue(
            TRADE_PARTNER_LOSS_POLICY_KEY,
            LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value,
            MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_context_sha256": context_hash,
                "jdl_evidence_id": TRADE_PARTNER_1D1C_EVIDENCE_ID,
            },
        )
        updated = replace(
            old,
            profile_id=revised_profile_id(old.profile_id, "partner"),
            loss_policy_mappings=policies,
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_profile(company_setting_id, updated.profile_id)
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise

    def _context_hash(self, path) -> str:
        context = self.contexts.load(path)
        return hashlib.sha256(
            self.contexts.to_json_text(context).encode("utf-8")
        ).hexdigest()

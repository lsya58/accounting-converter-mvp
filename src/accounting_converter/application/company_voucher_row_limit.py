"""Company setting 「振替伝票入力行数」 (rows per JDL voucher), confirmed by the Human.

JDL rejects a voucher with more rows than this company setting, also when it
arrives by CSV Import (real JDL Evidence, 2026-11-05: 16 rows imported and
re-exported, 17/25/50/73 rows all rejected under a 16-row setting). The value
is read from the JDL company setting by the Human; it is never inferred and
the app never changes the JDL setting or splits a journal.

Saving it touches nothing else: Human tax / account / subaccount decisions
stay as they are (the profile gets a new revision that only refreshes the
setup-context hash). It is not part of the Tax Context identity.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader

MAX_VOUCHER_ROW_LIMIT = 999


class CompanyVoucherRowLimitError(ValueError):
    pass


def profile_with_row_limit_context(profile, context_bytes: bytes):
    """Build the same revision for persistence or a read-only in-memory trial."""
    context_hash = hashlib.sha256(context_bytes).hexdigest()

    def refreshed(mappings):
        return {
            key: replace(value, metadata={**value.metadata, "setup_context_sha256": context_hash})
            if value.metadata.get("setup_context_sha256") else value
            for key, value in mappings.items()
        }

    return replace(
        profile,
        profile_id=revised_profile_id(profile.profile_id, "rowlimit"),
        account_mappings=refreshed(profile.account_mappings),
        subaccount_context_mappings=refreshed(profile.subaccount_context_mappings),
        updated_at=datetime.now(timezone.utc),
    )


class CompanyVoucherRowLimitService:
    def __init__(self, company_store: CompanySettingStore, profile_store: ConversionProfileStore) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.drafts = JdlAccountPdfDraftStore()
        self.contexts = JdlTargetContextLoader()

    def current(self, company_setting_id: str) -> int | None:
        """The confirmed limit, or None (unconfirmed, or the JDL setting is not confirmed yet)."""
        setting = self.company_store.get(company_setting_id)
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            return None
        return self.contexts.load(path).voucher_row_limit

    def set(self, company_setting_id: str, limit: int, *, confirmed: bool) -> int:
        if not confirmed:
            raise CompanyVoucherRowLimitError("振替伝票入力行数は、JDLの会社設定で確認した値を明示的に確認してください。")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_VOUCHER_ROW_LIMIT:
            raise CompanyVoucherRowLimitError(f"振替伝票入力行数は1〜{MAX_VOUCHER_ROW_LIMIT}の整数で入力してください。")
        setting = self.company_store.get(company_setting_id)
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            raise CompanyVoucherRowLimitError("JDL設定の確認（税設定）を完了してから、振替伝票入力行数を設定してください。")
        context = self.contexts.load(path)
        if context.voucher_row_limit == limit:
            return limit
        updated_context = replace(context, voucher_row_limit=limit)
        context_bytes = self.contexts.to_json_text(updated_context).encode("utf-8")
        old = self.profile_store.get(setting.conversion_profile_id)
        updated = profile_with_row_limit_context(old, context_bytes)
        self.profile_store.create(updated)
        try:
            self.company_store.replace_with_confirmed_context(
                company_setting_id, context_bytes, conversion_profile_id=updated.profile_id
            )
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise
        return limit

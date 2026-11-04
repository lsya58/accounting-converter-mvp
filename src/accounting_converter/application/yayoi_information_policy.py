"""Yayoi information that JDL cannot hold (部門・生成元・付箋・仕訳メモ・期日・番号).

JDL has no place for these values, so the only formal option is: not written
to JDL, every original value written to the audit file next to the formal CSV
(``<出力ファイル>.audit.json``). That is audit preservation, not JDL retention.

The Human states what each field means in this company's data. The policy is
saved with the existing confirmation (``confirm_optional_field_policy``) on a
new profile revision, bound atomically like the other company settings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable, Mapping

from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.application.yayoi_review import (
    confirm_optional_field_policy,
    confirmed_optional_fields,
    field_of,
    non_retained_values,
)
from accounting_converter.application.yayoi_sources import format_for_identity_key
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

FIELD_HELP = {
    "部門": "対象のJDL会社は部門を使わない設定のため、JDLへは出力できません。",
    "生成元": "弥生で仕訳を作成した機能（例：取引入力・自動取込）の記録です。",
    "仕訳メモ": "仕訳に付けたメモです。",
    "期日": "手形などの期日です。",
    "番号": "伝票番号などの番号です。",
}


def field_help(field: str) -> str:
    if field.startswith("付箋"):
        return "弥生の付箋（色・印）です。"
    return FIELD_HELP.get(field, "JDLの取込CSVに対応する項目がない情報です。")


@dataclass(frozen=True)
class YayoiInformationField:
    field: str
    journals: int
    meaning: str = ""  # the Human's statement; "" while unconfirmed

    @property
    def confirmed(self) -> bool:
        return bool(self.meaning)


def is_yayoi_profile(profile) -> bool:
    return format_for_identity_key(profile.source_format_identity.stable_key) is not None


def information_fields(entries: Iterable, profile) -> tuple[YayoiInformationField, ...]:
    """Every non-retained field present in the source, confirmed or not."""
    journals = Counter(
        field
        for entry in entries
        for field in {field_of(name) for _row, name, _value in non_retained_values(entry)}
    )
    meanings = confirmed_optional_fields(profile)
    return tuple(
        YayoiInformationField(field, count, meanings.get(field, ""))
        for field, count in sorted(journals.items())
    )


class YayoiInformationPolicyService:
    def __init__(self, company_store: CompanySettingStore, profile_store: ConversionProfileStore) -> None:
        self.company_store = company_store
        self.profile_store = profile_store

    def confirm(self, company_setting_id: str, meanings: Mapping[str, str]) -> None:
        """Save the Human's audit-only policy for each field given (never inferred)."""
        cleaned = {field: meaning.strip() for field, meaning in meanings.items()}
        if not cleaned:
            raise ValueError("確認した項目がありません。")
        if any(not meaning for meaning in cleaned.values()):
            raise ValueError("項目の意味（何の情報か）を記入してください。")
        setting = self.company_store.get(company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        if not is_yayoi_profile(old):
            raise ValueError("弥生の会社設定ではありません。")
        updated = replace(
            old,
            profile_id=revised_profile_id(old.profile_id, "information"),
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            for field, meaning in cleaned.items():
                confirm_optional_field_policy(self.profile_store, updated.profile_id, field, meaning)
            self.company_store.replace_profile(company_setting_id, updated.profile_id)
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise

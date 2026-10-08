from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from accounting_converter.adapters.output.jdl.models import JdlTargetContext
from accounting_converter.domain.conversion_profile import ConversionProfile


CURRENT_COMPANY_SETTING_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class CompanySetting:
    company_setting_id: str
    display_name: str
    conversion_profile_id: str
    jdl_context_relative_path: str
    expected_source_format_key: str
    expected_target_format_key: str
    profile_fingerprint: str
    context_fingerprint: str
    created_at: datetime
    updated_at: datetime
    schema_version: str = CURRENT_COMPANY_SETTING_SCHEMA_VERSION


class CompanySettingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    INCOMPATIBLE = "INCOMPATIBLE"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class ResolvedCompanySetting:
    setting: CompanySetting
    status: CompanySettingStatus
    profile: ConversionProfile | None = None
    context: JdlTargetContext | None = None
    user_message: str = ""
    reason_codes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status is CompanySettingStatus.AVAILABLE


class CompanySettingResolver(Protocol):
    def resolve(self, company_setting_id: str) -> ResolvedCompanySetting:
        ...


class CompanySettingService:
    """Resolves one saved company bundle without changing conversion semantics."""

    def __init__(self, resolver: CompanySettingResolver) -> None:
        self._resolver = resolver

    def resolve_for_source(
        self,
        company_setting_id: str,
        source_format_key: str | None = None,
    ) -> ResolvedCompanySetting:
        resolved = self._resolver.resolve(company_setting_id)
        if (
            resolved.available
            and source_format_key is not None
            and resolved.setting.expected_source_format_key != source_format_key
        ):
            return ResolvedCompanySetting(
                setting=resolved.setting,
                status=CompanySettingStatus.INCOMPATIBLE,
                user_message="会社設定を確認してください。入力元の形式が一致しません。",
                reason_codes=("SOURCE_FORMAT_MISMATCH",),
            )
        return resolved

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from accounting_converter.adapters.output.jdl import (
    JdlOutputRuntimeFactory,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.company_settings import (
    CURRENT_COMPANY_SETTING_SCHEMA_VERSION,
    CompanySetting,
    CompanySettingStatus,
    ResolvedCompanySetting,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    ConversionProfileStoreError,
)
from accounting_converter.infrastructure.jdl_target_context_loader import (
    JdlTargetContextLoadError,
    JdlTargetContextLoader,
)


class CompanySettingStoreError(ValueError):
    pass


class DuplicateCompanySettingError(CompanySettingStoreError):
    pass


class CompanySettingNotFoundError(CompanySettingStoreError):
    pass


class CorruptCompanySettingError(CompanySettingStoreError):
    pass


class CompanySettingStore:
    COMPANY_FILE = "company.json"
    CONTEXT_FILE = "jdl-context.json"

    def __init__(self, root_dir: Path, profile_store: ConversionProfileStore) -> None:
        self.root_dir = root_dir
        self.profile_store = profile_store
        self.context_loader = JdlTargetContextLoader()

    def create(
        self,
        *,
        company_setting_id: str,
        display_name: str,
        conversion_profile_id: str,
        context_source: Path,
    ) -> CompanySetting:
        self._validate_id(company_setting_id)
        self._validate_name(display_name)
        destination = self.root_dir / company_setting_id
        if destination.exists():
            raise DuplicateCompanySettingError("company setting already exists")
        profile = self.profile_store.get(conversion_profile_id)
        context = self.context_loader.load(context_source)
        runtime = JdlOutputRuntimeFactory().resolve(
            jdl_ibex_35_5_output_profile(), profile, context
        )
        if not runtime.resolved:
            raise CompanySettingStoreError("profile and JDL setting are incompatible")
        context_bytes = context_source.read_bytes()
        now = datetime.now(timezone.utc)
        setting = CompanySetting(
            company_setting_id=company_setting_id,
            display_name=display_name.strip(),
            conversion_profile_id=conversion_profile_id,
            jdl_context_relative_path=self.CONTEXT_FILE,
            expected_source_format_key=profile.source_format_identity.stable_key,
            expected_target_format_key=profile.target_format_identity.stable_key,
            profile_fingerprint=self._profile_fingerprint(profile),
            context_fingerprint=self._hash(context_bytes),
            created_at=now,
            updated_at=now,
        )
        self.root_dir.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f".{company_setting_id}.", dir=self.root_dir))
        try:
            self._exclusive_write(temp / self.CONTEXT_FILE, context_bytes)
            self._write_json(temp / self.COMPANY_FILE, self._to_dict(setting), exclusive=True)
            os.replace(temp, destination)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        return setting

    def get(self, company_setting_id: str) -> CompanySetting:
        self._validate_id(company_setting_id)
        path = self.root_dir / company_setting_id / self.COMPANY_FILE
        if not path.exists():
            raise CompanySettingNotFoundError("company setting not found")
        return self._from_json(path)

    def list(self) -> tuple[CompanySetting, ...]:
        if not self.root_dir.exists():
            return ()
        settings = []
        for directory in sorted(path for path in self.root_dir.iterdir() if path.is_dir()):
            company_file = directory / self.COMPANY_FILE
            if company_file.exists():
                settings.append(self._from_json(company_file))
        return tuple(settings)

    def rename(self, company_setting_id: str, display_name: str) -> CompanySetting:
        self._validate_name(display_name)
        current = self.get(company_setting_id)
        updated = replace(
            current,
            display_name=display_name.strip(),
            updated_at=datetime.now(timezone.utc),
        )
        self._atomic_json(
            self.root_dir / company_setting_id / self.COMPANY_FILE,
            self._to_dict(updated),
        )
        return updated

    def delete(self, company_setting_id: str) -> None:
        self._validate_id(company_setting_id)
        directory = self.root_dir / company_setting_id
        if not directory.exists():
            raise CompanySettingNotFoundError("company setting not found")
        shutil.rmtree(directory)

    def resolve(self, company_setting_id: str) -> ResolvedCompanySetting:
        try:
            setting = self.get(company_setting_id)
        except (CompanySettingStoreError, OSError):
            return self._failed(company_setting_id, CompanySettingStatus.MALFORMED, "SETTING_MALFORMED")
        try:
            profile = self.profile_store.get(setting.conversion_profile_id)
        except (ConversionProfileStoreError, OSError):
            return self._resolved_failure(setting, CompanySettingStatus.STALE, "PROFILE_MISSING")
        context_path = self.root_dir / setting.company_setting_id / setting.jdl_context_relative_path
        if not context_path.exists():
            return self._resolved_failure(setting, CompanySettingStatus.STALE, "CONTEXT_MISSING")
        try:
            context_bytes = context_path.read_bytes()
            context = self.context_loader.load(context_path)
        except (OSError, JdlTargetContextLoadError):
            return self._resolved_failure(setting, CompanySettingStatus.MALFORMED, "CONTEXT_INVALID")
        stale = []
        if self._profile_fingerprint(profile) != setting.profile_fingerprint:
            stale.append("PROFILE_CHANGED")
        if self._hash(context_bytes) != setting.context_fingerprint:
            stale.append("CONTEXT_CHANGED")
        if stale:
            return ResolvedCompanySetting(
                setting, CompanySettingStatus.STALE, user_message="会社設定を確認してください。保存後にJDL設定または対応設定が変更されています。", reason_codes=tuple(stale)
            )
        if (
            profile.source_format_identity.stable_key != setting.expected_source_format_key
            or profile.target_format_identity.stable_key != setting.expected_target_format_key
        ):
            return self._resolved_failure(setting, CompanySettingStatus.INCOMPATIBLE, "FORMAT_IDENTITY_MISMATCH")
        runtime = JdlOutputRuntimeFactory().resolve(jdl_ibex_35_5_output_profile(), profile, context)
        if not runtime.resolved:
            return ResolvedCompanySetting(
                setting, CompanySettingStatus.INCOMPATIBLE,
                user_message="会社設定を確認してください。対応設定とJDL設定が一致しません。",
                reason_codes=tuple(item.rule_id for item in runtime.validation_results),
            )
        return ResolvedCompanySetting(
            setting, CompanySettingStatus.AVAILABLE, profile, context,
            "会社設定を利用できます。",
        )

    def context_path(self, setting: CompanySetting) -> Path:
        return self.root_dir / setting.company_setting_id / setting.jdl_context_relative_path

    def _profile_fingerprint(self, profile) -> str:
        return self._hash(self.profile_store.to_json_text(profile).encode("utf-8"))

    @staticmethod
    def _hash(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _validate_id(value: str) -> None:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        if not value or any(character not in allowed for character in value):
            raise CompanySettingStoreError("unsafe company setting id")

    @staticmethod
    def _validate_name(value: str) -> None:
        if not value.strip() or len(value.strip()) > 100:
            raise CompanySettingStoreError("display name is required and must be 100 characters or fewer")

    @staticmethod
    def _exclusive_write(path: Path, content: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(content)

    def _atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        temp = path.with_name(f".{path.name}.tmp")
        try:
            self._write_json(temp, payload, exclusive=True)
            self._from_json(temp)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any], *, exclusive: bool) -> None:
        mode = "x" if exclusive else "w"
        with path.open(mode, encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _to_dict(setting: CompanySetting) -> dict[str, str]:
        return {
            "schema_version": setting.schema_version,
            "company_setting_id": setting.company_setting_id,
            "display_name": setting.display_name,
            "conversion_profile_id": setting.conversion_profile_id,
            "jdl_context_relative_path": setting.jdl_context_relative_path,
            "expected_source_format_key": setting.expected_source_format_key,
            "expected_target_format_key": setting.expected_target_format_key,
            "profile_fingerprint": setting.profile_fingerprint,
            "context_fingerprint": setting.context_fingerprint,
            "created_at": setting.created_at.isoformat(),
            "updated_at": setting.updated_at.isoformat(),
        }

    @staticmethod
    def _from_json(path: Path) -> CompanySetting:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != CURRENT_COMPANY_SETTING_SCHEMA_VERSION:
                raise ValueError("unsupported schema")
            setting = CompanySetting(
                schema_version=str(payload["schema_version"]),
                company_setting_id=str(payload["company_setting_id"]),
                display_name=str(payload["display_name"]),
                conversion_profile_id=str(payload["conversion_profile_id"]),
                jdl_context_relative_path=str(payload["jdl_context_relative_path"]),
                expected_source_format_key=str(payload["expected_source_format_key"]),
                expected_target_format_key=str(payload["expected_target_format_key"]),
                profile_fingerprint=str(payload["profile_fingerprint"]),
                context_fingerprint=str(payload["context_fingerprint"]),
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.fromisoformat(payload["updated_at"]),
            )
            CompanySettingStore._validate_id(setting.company_setting_id)
            CompanySettingStore._validate_name(setting.display_name)
            if setting.jdl_context_relative_path != CompanySettingStore.CONTEXT_FILE:
                raise ValueError("unsafe context path")
            return setting
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptCompanySettingError("company setting JSON is invalid") from exc

    @staticmethod
    def _resolved_failure(setting: CompanySetting, status: CompanySettingStatus, code: str) -> ResolvedCompanySetting:
        return ResolvedCompanySetting(setting, status, user_message="会社設定を確認してください。", reason_codes=(code,))

    @staticmethod
    def _failed(company_setting_id: str, status: CompanySettingStatus, code: str) -> ResolvedCompanySetting:
        now = datetime.now(timezone.utc)
        placeholder = CompanySetting(company_setting_id, "利用できない設定", "", CompanySettingStore.CONTEXT_FILE, "", "", "", "", now, now)
        return ResolvedCompanySetting(placeholder, status, user_message="会社設定を確認してください。", reason_codes=(code,))


def default_company_store_dir() -> Path:
    from accounting_converter.infrastructure.conversion_profile_store import default_profile_store_dir

    return default_profile_store_dir().parent / "companies"

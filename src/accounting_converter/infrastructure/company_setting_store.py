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
from accounting_converter.infrastructure.jdl_account_pdf_draft import (
    JdlAccountPdfDraftError,
    JdlAccountPdfDraftStore,
)
from accounting_converter.application.jdl_master_identity import (
    observed_master_identity_sha256,
    target_context_master_identity_sha256,
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
        self.account_pdf_drafts = JdlAccountPdfDraftStore()

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
        context_bytes = context_source.read_bytes()
        expected_context_hashes = {
            mapping.metadata.get("setup_context_sha256")
            for mapping in profile.account_mappings.values()
            if mapping.metadata.get("setup_context_sha256")
        }
        if expected_context_hashes and expected_context_hashes != {
            self._hash(context_bytes)
        }:
            raise CompanySettingStoreError(
                "profile was confirmed against a different JDL setting"
            )
        context_is_draft = self.account_pdf_drafts.is_draft(context_source)
        if context_is_draft:
            self.account_pdf_drafts.load(context_source)
        else:
            context = self.context_loader.load(context_source)
            runtime = JdlOutputRuntimeFactory().resolve(
                jdl_ibex_35_5_output_profile(), profile, context
            )
            if not runtime.resolved:
                raise CompanySettingStoreError("profile and JDL setting are incompatible")
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

    def target_master_identity_sha256(self, company_setting_id: str) -> str:
        setting = self.get(company_setting_id)
        context_path = self.context_path(setting)
        if self.account_pdf_drafts.is_draft(context_path):
            return observed_master_identity_sha256(
                self.account_pdf_drafts.load(context_path).observation
            )
        return target_context_master_identity_sha256(
            self.context_loader.load(context_path)
        )

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

    def refresh_profile_fingerprint(self, company_setting_id: str) -> CompanySetting:
        current = self.get(company_setting_id)
        profile = self.profile_store.get(current.conversion_profile_id)
        context_path = self.context_path(current)
        context_bytes = context_path.read_bytes()
        context = self.context_loader.load(context_path)
        runtime = JdlOutputRuntimeFactory().resolve(
            jdl_ibex_35_5_output_profile(), profile, context
        )
        if not runtime.resolved or self._hash(context_bytes) != current.context_fingerprint:
            raise CompanySettingStoreError(
                "updated profile and saved JDL setting are incompatible"
            )
        updated = replace(
            current,
            profile_fingerprint=self._profile_fingerprint(profile),
            updated_at=datetime.now(timezone.utc),
        )
        self._atomic_json(
            self.root_dir / company_setting_id / self.COMPANY_FILE,
            self._to_dict(updated),
        )
        return updated

    def replace_profile(
        self, company_setting_id: str, conversion_profile_id: str
    ) -> CompanySetting:
        """Atomically bind one company to a separately persisted profile."""
        current = self.get(company_setting_id)
        profile = self.profile_store.get(conversion_profile_id)
        context_path = self.context_path(current)
        context_bytes = context_path.read_bytes()
        if self.account_pdf_drafts.is_draft(context_path):
            self.account_pdf_drafts.load(context_path)
            expected_hashes = {
                mapping.metadata.get("setup_context_sha256")
                for mapping in profile.account_mappings.values()
                if mapping.status.value == "USER_CONFIRMED"
            }
            if expected_hashes and expected_hashes != {self._hash(context_bytes)}:
                raise CompanySettingStoreError(
                    "profile mappings were not confirmed against this JDL setting"
                )
        else:
            context = self.context_loader.load(context_path)
            runtime = JdlOutputRuntimeFactory().resolve(
                jdl_ibex_35_5_output_profile(), profile, context
            )
            if not runtime.resolved:
                raise CompanySettingStoreError(
                    "updated profile and saved JDL setting are incompatible"
                )
        if (
            profile.source_format_identity.stable_key
            != current.expected_source_format_key
            or profile.target_format_identity.stable_key
            != current.expected_target_format_key
        ):
            raise CompanySettingStoreError(
                "updated profile format identity is incompatible"
            )
        updated = replace(
            current,
            conversion_profile_id=profile.profile_id,
            profile_fingerprint=self._profile_fingerprint(profile),
            updated_at=datetime.now(timezone.utc),
        )
        self._atomic_json(
            self.root_dir / company_setting_id / self.COMPANY_FILE,
            self._to_dict(updated),
        )
        return updated

    def replace_context(
        self,
        company_setting_id: str,
        context_source: Path,
        *,
        conversion_profile_id: str | None = None,
    ) -> CompanySetting:
        current = self.get(company_setting_id)
        profile = self.profile_store.get(
            conversion_profile_id or current.conversion_profile_id
        )
        context_bytes = context_source.read_bytes()
        if not self.account_pdf_drafts.is_draft(context_source):
            raise CompanySettingStoreError("JDL account-list draft is required")
        self.account_pdf_drafts.load(context_source)
        context_hash = self._hash(context_bytes)
        expected_hashes = {
            mapping.metadata.get("setup_context_sha256")
            for mapping in profile.account_mappings.values()
            if mapping.status.value == "USER_CONFIRMED"
        }
        if expected_hashes and expected_hashes != {context_hash}:
            raise CompanySettingStoreError(
                "profile mappings were not confirmed against the new JDL setting"
            )
        updated = replace(
            current,
            conversion_profile_id=profile.profile_id,
            expected_source_format_key=profile.source_format_identity.stable_key,
            expected_target_format_key=profile.target_format_identity.stable_key,
            profile_fingerprint=self._profile_fingerprint(profile),
            context_fingerprint=context_hash,
            updated_at=datetime.now(timezone.utc),
        )
        destination = self.context_path(current)
        context_temp = destination.with_name(f".{destination.name}.refresh.tmp")
        company_path = self.root_dir / company_setting_id / self.COMPANY_FILE
        company_temp = company_path.with_name(f".{self.COMPANY_FILE}.refresh.tmp")
        try:
            self._exclusive_write(context_temp, context_bytes)
            self.account_pdf_drafts.load(context_temp)
            self._write_json(company_temp, self._to_dict(updated), exclusive=True)
            self._from_json(company_temp)
            os.replace(context_temp, destination)
            os.replace(company_temp, company_path)
        finally:
            if context_temp.exists():
                context_temp.unlink()
            if company_temp.exists():
                company_temp.unlink()
        return updated

    def replace_with_confirmed_context(
        self,
        company_setting_id: str,
        context_bytes: bytes,
        *,
        conversion_profile_id: str,
    ) -> CompanySetting:
        """Atomically replace a PDF draft with a validated runtime context."""
        current = self.get(company_setting_id)
        profile = self.profile_store.get(conversion_profile_id)
        destination = self.context_path(current)
        if not self.account_pdf_drafts.is_draft(destination):
            raise CompanySettingStoreError("JDL tax setting is already confirmed")
        context_temp = destination.with_name(f".{destination.name}.confirm.tmp")
        company_path = self.root_dir / company_setting_id / self.COMPANY_FILE
        company_temp = company_path.with_name(f".{self.COMPANY_FILE}.confirm.tmp")
        try:
            self._exclusive_write(context_temp, context_bytes)
            context = self.context_loader.load(context_temp)
            runtime = JdlOutputRuntimeFactory().resolve(
                jdl_ibex_35_5_output_profile(), profile, context
            )
            if not runtime.resolved:
                raise CompanySettingStoreError(
                    "confirmed JDL setting and mappings are incompatible"
                )
            updated = replace(
                current,
                conversion_profile_id=profile.profile_id,
                profile_fingerprint=self._profile_fingerprint(profile),
                context_fingerprint=self._hash(context_bytes),
                updated_at=datetime.now(timezone.utc),
            )
            self._write_json(company_temp, self._to_dict(updated), exclusive=True)
            self._from_json(company_temp)
            os.replace(context_temp, destination)
            os.replace(company_temp, company_path)
            return updated
        finally:
            if context_temp.exists():
                context_temp.unlink()
            if company_temp.exists():
                company_temp.unlink()

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
            if self.account_pdf_drafts.is_draft(context_path):
                self.account_pdf_drafts.load(context_path)
                stale = []
                if self._profile_fingerprint(profile) != setting.profile_fingerprint:
                    stale.append("PROFILE_CHANGED")
                if self._hash(context_bytes) != setting.context_fingerprint:
                    stale.append("CONTEXT_CHANGED")
                if stale:
                    return ResolvedCompanySetting(
                        setting,
                        CompanySettingStatus.STALE,
                        user_message=(
                            "会社設定を確認してください。保存後にJDL設定または"
                            "対応設定が変更されています。"
                        ),
                        reason_codes=tuple(stale),
                    )
                if (
                    profile.source_format_identity.stable_key
                    != setting.expected_source_format_key
                    or profile.target_format_identity.stable_key
                    != setting.expected_target_format_key
                ):
                    return self._resolved_failure(
                        setting,
                        CompanySettingStatus.INCOMPATIBLE,
                        "FORMAT_IDENTITY_MISMATCH",
                    )
                return ResolvedCompanySetting(
                    setting,
                    CompanySettingStatus.REQUIRES_CONFIRMATION,
                    profile=profile,
                    user_message=(
                        "この会社で使うJDL科目一覧は設定済みです。"
                        "税設定などの確認が完了するまで変換できません。"
                    ),
                    reason_codes=("JDL_CONTEXT_DRAFT_UNCONFIRMED",),
                )
            context = self.context_loader.load(context_path)
        except (OSError, JdlTargetContextLoadError, JdlAccountPdfDraftError):
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

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from accounting_converter.domain.conversion_profile import (
    CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION,
    ConversionProfile,
)
from accounting_converter.domain.format_metadata import (
    EvidenceLevel,
    FormatDirection,
    FormatIdentity,
    SemanticField,
    SourceProvenance,
)
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.domain.normalization import (
    NormalizationRule,
    NormalizationScope,
)


class ConversionProfileStoreError(ValueError):
    pass


class DuplicateProfileError(ConversionProfileStoreError):
    pass


class ProfileNotFoundError(ConversionProfileStoreError):
    pass


class UnsupportedProfileVersionError(ConversionProfileStoreError):
    pass


class ConversionProfileStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def create(self, profile: ConversionProfile) -> ConversionProfile:
        self._validate_profile(profile)
        path = self._profile_path(profile.profile_id)
        if path.exists():
            raise DuplicateProfileError(f"profile already exists: {profile.profile_id}")
        self._atomic_write(path, self.to_json_text(profile))
        return profile

    def get(self, profile_id: str) -> ConversionProfile:
        path = self._profile_path(profile_id)
        if not path.exists():
            raise ProfileNotFoundError(f"profile not found: {profile_id}")
        return self.from_json_text(path.read_text(encoding="utf-8"))

    def list(self) -> tuple[ConversionProfile, ...]:
        if not self.root_dir.exists():
            return ()
        profiles = [
            self.from_json_text(path.read_text(encoding="utf-8"))
            for path in sorted(self.root_dir.glob("*.json"))
        ]
        return tuple(profiles)

    def update(self, profile: ConversionProfile) -> ConversionProfile:
        self._validate_profile(profile)
        path = self._profile_path(profile.profile_id)
        if not path.exists():
            raise ProfileNotFoundError(f"profile not found: {profile.profile_id}")
        self._atomic_write(path, self.to_json_text(profile))
        return profile

    def delete(self, profile_id: str) -> None:
        path = self._profile_path(profile_id)
        if not path.exists():
            raise ProfileNotFoundError(f"profile not found: {profile_id}")
        path.unlink()

    def export_profile(self, profile_id: str, destination: Path) -> None:
        profile = self.get(profile_id)
        self._atomic_write(destination, self.to_json_text(profile))

    def import_profile(
        self,
        source: Path,
        allow_overwrite: bool = False,
    ) -> ConversionProfile:
        profile = self.from_json_text(source.read_text(encoding="utf-8"))
        path = self._profile_path(profile.profile_id)
        if path.exists() and not allow_overwrite:
            raise DuplicateProfileError(f"profile already exists: {profile.profile_id}")
        self._atomic_write(path, self.to_json_text(profile))
        return profile

    def to_json_text(self, profile: ConversionProfile) -> str:
        self._validate_profile(profile)
        return json.dumps(
            _profile_to_dict(profile),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def from_json_text(self, text: str) -> ConversionProfile:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConversionProfileStoreError("malformed profile JSON") from exc
        if isinstance(payload, dict):
            schema_version = payload.get("schema_version")
            if (
                schema_version is not None
                and str(schema_version) != CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION
            ):
                raise UnsupportedProfileVersionError(
                    f"unsupported profile schema_version: {schema_version}"
                )
        profile = _profile_from_dict(payload)
        self._validate_profile(profile)
        return profile

    def _profile_path(self, profile_id: str) -> Path:
        self._validate_profile_id(profile_id)
        return self.root_dir / f"{profile_id}.json"

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.tmp")
        try:
            temp_path.write_text(text, encoding="utf-8")
            self.from_json_text(temp_path.read_text(encoding="utf-8"))
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _validate_profile(self, profile: ConversionProfile) -> None:
        if profile.schema_version != CURRENT_CONVERSION_PROFILE_SCHEMA_VERSION:
            raise UnsupportedProfileVersionError(
                f"unsupported profile schema_version: {profile.schema_version}"
            )
        if not profile.profile_id:
            raise ConversionProfileStoreError("profile_id is required")
        self._validate_profile_id(profile.profile_id)
        if not profile.profile_name:
            raise ConversionProfileStoreError("profile_name is required")
        _validate_identity(profile.source_format_identity)
        _validate_identity(profile.target_format_identity)
        for mapping_name, mappings in (
            ("account_mappings", profile.account_mappings),
            ("subaccount_mappings", profile.subaccount_mappings),
            ("department_mappings", profile.department_mappings),
            ("tax_mappings", profile.tax_mappings),
        ):
            _validate_mapping_dict(mapping_name, mappings)
        _validate_context_mapping_dict(
            "subaccount_context_mappings",
            profile.subaccount_context_mappings,
        )

    def _validate_profile_id(self, profile_id: str) -> None:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        if not profile_id or any(character not in allowed for character in profile_id):
            raise ConversionProfileStoreError("profile_id contains unsafe characters")


def default_profile_store_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "AccountingConverter" / "profiles"
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "AccountingConverter" / "profiles"
    return Path.home() / ".local" / "share" / "accounting-converter" / "profiles"


def with_updated_timestamp(profile: ConversionProfile) -> ConversionProfile:
    return replace(profile, updated_at=datetime.now(profile.updated_at.tzinfo))


def _profile_to_dict(profile: ConversionProfile) -> dict[str, Any]:
    return {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "profile_name": profile.profile_name,
        "source_format_identity": _identity_to_dict(profile.source_format_identity),
        "target_format_identity": _identity_to_dict(profile.target_format_identity),
        "account_mappings": _mappings_to_list(profile.account_mappings),
        "subaccount_mappings": _mappings_to_list(profile.subaccount_mappings),
        "subaccount_context_mappings": _context_mappings_to_list(
            profile.subaccount_context_mappings
        ),
        "department_mappings": _mappings_to_list(profile.department_mappings),
        "tax_mappings": _mappings_to_list(profile.tax_mappings),
        "normalization_rules": [
            _normalization_rule_to_dict(rule) for rule in profile.normalization_rules
        ],
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
        "notes": profile.notes,
    }


def _profile_from_dict(payload: Any) -> ConversionProfile:
    if not isinstance(payload, dict):
        raise ConversionProfileStoreError("profile JSON must be an object")
    required = {
        "schema_version",
        "profile_id",
        "profile_name",
        "source_format_identity",
        "target_format_identity",
        "created_at",
        "updated_at",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ConversionProfileStoreError(f"profile required fields missing: {missing}")
    return ConversionProfile(
        schema_version=str(payload["schema_version"]),
        profile_id=str(payload["profile_id"]),
        profile_name=str(payload["profile_name"]),
        source_format_identity=_identity_from_dict(payload["source_format_identity"]),
        target_format_identity=_identity_from_dict(payload["target_format_identity"]),
        account_mappings=_mappings_from_list(payload.get("account_mappings", [])),
        subaccount_mappings=_mappings_from_list(payload.get("subaccount_mappings", [])),
        subaccount_context_mappings=_context_mappings_from_list(
            payload.get("subaccount_context_mappings", [])
        ),
        department_mappings=_mappings_from_list(payload.get("department_mappings", [])),
        tax_mappings=_mappings_from_list(payload.get("tax_mappings", [])),
        normalization_rules=tuple(
            _normalization_rule_from_dict(item)
            for item in payload.get("normalization_rules", [])
        ),
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        notes=payload.get("notes"),
    )


def _identity_to_dict(identity: FormatIdentity) -> dict[str, Any]:
    return {
        "vendor": identity.vendor,
        "product": identity.product,
        "edition": identity.edition,
        "major_version": identity.major_version,
        "minor_version": identity.minor_version,
        "version_range": identity.version_range,
        "format_name": identity.format_name,
        "format_version": identity.format_version,
        "direction": identity.direction.value,
        "evidence_level": identity.evidence_level.value,
        "source_reference": (
            _source_to_dict(identity.source_reference)
            if identity.source_reference is not None
            else None
        ),
        "verified_at": (
            identity.verified_at.isoformat() if identity.verified_at is not None else None
        ),
        "notes": identity.notes,
    }


def _identity_from_dict(payload: Any) -> FormatIdentity:
    if not isinstance(payload, dict):
        raise ConversionProfileStoreError("FormatIdentity must be an object")
    try:
        direction = FormatDirection(payload["direction"])
        evidence_level = EvidenceLevel(payload["evidence_level"])
    except (KeyError, ValueError) as exc:
        raise ConversionProfileStoreError("invalid FormatIdentity enum") from exc
    try:
        return FormatIdentity(
            vendor=str(payload["vendor"]),
            product=str(payload["product"]),
            edition=payload.get("edition"),
            major_version=payload.get("major_version"),
            minor_version=payload.get("minor_version"),
            version_range=payload.get("version_range"),
            format_name=str(payload["format_name"]),
            format_version=payload.get("format_version"),
            direction=direction,
            evidence_level=evidence_level,
            source_reference=(
                _source_from_dict(payload["source_reference"])
                if payload.get("source_reference") is not None
                else None
            ),
            verified_at=(
                datetime.fromisoformat(payload["verified_at"]).date()
                if payload.get("verified_at")
                else None
            ),
            notes=payload.get("notes"),
        )
    except KeyError as exc:
        raise ConversionProfileStoreError("invalid FormatIdentity") from exc


def _source_to_dict(source: SourceProvenance) -> dict[str, Any]:
    return {
        "title": source.title,
        "url": source.url,
        "evidence_level": source.evidence_level.value,
        "retrieved_at": (
            source.retrieved_at.isoformat() if source.retrieved_at is not None else None
        ),
        "verified_at": (
            source.verified_at.isoformat() if source.verified_at is not None else None
        ),
        "notes": source.notes,
    }


def _source_from_dict(payload: Any) -> SourceProvenance:
    if not isinstance(payload, dict):
        raise ConversionProfileStoreError("SourceProvenance must be an object")
    try:
        return SourceProvenance(
            title=str(payload["title"]),
            url=payload.get("url"),
            evidence_level=EvidenceLevel(payload["evidence_level"]),
            retrieved_at=(
                datetime.fromisoformat(payload["retrieved_at"]).date()
                if payload.get("retrieved_at")
                else None
            ),
            verified_at=(
                datetime.fromisoformat(payload["verified_at"]).date()
                if payload.get("verified_at")
                else None
            ),
            notes=payload.get("notes"),
        )
    except (KeyError, ValueError) as exc:
        raise ConversionProfileStoreError("invalid SourceProvenance") from exc


def _mappings_to_list(mappings: dict[str, MappingValue]) -> list[dict[str, Any]]:
    return [
        {
            "source_value": mapping.source_value,
            "target_value": mapping.target_value,
            "status": mapping.status.value,
            "parent_account": mapping.parent_account,
            "metadata": dict(mapping.metadata),
        }
        for _, mapping in sorted(mappings.items())
    ]


def _mappings_from_list(payload: Any) -> dict[str, MappingValue]:
    if not isinstance(payload, list):
        raise ConversionProfileStoreError("mapping section must be a list")
    values: dict[str, MappingValue] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ConversionProfileStoreError("mapping item must be an object")
        try:
            mapping = MappingValue(
                source_value=str(item["source_value"]),
                target_value=item.get("target_value"),
                status=MappingStatus(item["status"]),
                parent_account=item.get("parent_account"),
                metadata={
                    str(key): str(value)
                    for key, value in item.get("metadata", {}).items()
                },
            )
        except (KeyError, ValueError) as exc:
            raise ConversionProfileStoreError("invalid mapping item") from exc
        existing = values.get(mapping.source_value)
        if existing is not None:
            if (
                existing.target_value != mapping.target_value
                or existing.status is not mapping.status
            ):
                raise ConversionProfileStoreError(
                    f"conflicting mapping for source_value: {mapping.source_value}"
                )
            raise ConversionProfileStoreError(
                f"duplicate mapping for source_value: {mapping.source_value}"
            )
        values[mapping.source_value] = mapping
    return values


def _context_mappings_to_list(
    mappings: dict[MappingKey, MappingValue],
) -> list[dict[str, Any]]:
    return [
        {
            "mapping_type": key.mapping_type.value,
            "source_value": key.source_value,
            "parent_account": key.parent_account,
            "target_value": mapping.target_value,
            "status": mapping.status.value,
            "metadata": dict(mapping.metadata),
        }
        for key, mapping in sorted(mappings.items(), key=lambda item: item[0].stable_key)
    ]


def _context_mappings_from_list(payload: Any) -> dict[MappingKey, MappingValue]:
    if not isinstance(payload, list):
        raise ConversionProfileStoreError("context mapping section must be a list")
    values: dict[MappingKey, MappingValue] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ConversionProfileStoreError("context mapping item must be an object")
        try:
            if item.get("side") is not None:
                raise ConversionProfileStoreError(
                    "context mapping side is occurrence metadata, not profile identity"
                )
            key = MappingKey(
                mapping_type=MappingType(item["mapping_type"]),
                source_value=str(item["source_value"]),
                parent_account=item.get("parent_account"),
            )
            mapping = MappingValue(
                source_value=key.source_value,
                target_value=item.get("target_value"),
                status=MappingStatus(item["status"]),
                parent_account=key.parent_account,
                metadata={
                    str(meta_key): str(meta_value)
                    for meta_key, meta_value in item.get("metadata", {}).items()
                },
            )
        except (KeyError, ValueError) as exc:
            raise ConversionProfileStoreError("invalid context mapping item") from exc
        existing = values.get(key)
        if existing is not None:
            if (
                existing.target_value != mapping.target_value
                or existing.status is not mapping.status
            ):
                raise ConversionProfileStoreError(
                    f"conflicting context mapping for source_value: {key.source_value}"
                )
            raise ConversionProfileStoreError(
                f"duplicate context mapping for source_value: {key.source_value}"
            )
        values[key] = mapping
    return values


def _normalization_rule_to_dict(rule: NormalizationRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "target_field": rule.target_field.value,
        "scope": rule.scope.value,
        "deterministic": rule.deterministic,
        "reversible": rule.reversible,
        "requires_confirmation": rule.requires_confirmation,
        "evidence": rule.evidence.value,
        "description": rule.description,
    }


def _normalization_rule_from_dict(payload: Any) -> NormalizationRule:
    if not isinstance(payload, dict):
        raise ConversionProfileStoreError("normalization rule must be an object")
    try:
        return NormalizationRule(
            rule_id=str(payload["rule_id"]),
            target_field=SemanticField(payload["target_field"]),
            scope=NormalizationScope(payload["scope"]),
            deterministic=bool(payload["deterministic"]),
            reversible=bool(payload["reversible"]),
            requires_confirmation=bool(payload["requires_confirmation"]),
            evidence=EvidenceLevel(payload["evidence"]),
            description=str(payload["description"]),
        )
    except (KeyError, ValueError) as exc:
        raise ConversionProfileStoreError("invalid normalization rule") from exc


def _validate_identity(identity: FormatIdentity) -> None:
    if not identity.vendor or not identity.product or not identity.format_name:
        raise ConversionProfileStoreError("invalid FormatIdentity")


def _validate_mapping_dict(
    mapping_name: str,
    mappings: dict[str, MappingValue],
) -> None:
    for key, mapping in mappings.items():
        if key != mapping.source_value:
            raise ConversionProfileStoreError(
                f"{mapping_name} key must match source_value"
            )
        if mapping.status in {MappingStatus.RESOLVED, MappingStatus.USER_CONFIRMED}:
            if mapping.target_value is None:
                raise ConversionProfileStoreError(
                    f"{mapping_name} resolved mapping requires target_value"
                )
        if mapping.status in {MappingStatus.UNRESOLVED, MappingStatus.OBSOLETE}:
            if mapping.target_value is not None and mapping.status is MappingStatus.UNRESOLVED:
                raise ConversionProfileStoreError(
                    f"{mapping_name} unresolved mapping must not carry target_value"
                )


def _validate_context_mapping_dict(
    mapping_name: str,
    mappings: dict[MappingKey, MappingValue],
) -> None:
    for key, mapping in mappings.items():
        if key.mapping_type is not MappingType.SUBACCOUNT:
            raise ConversionProfileStoreError(
                f"{mapping_name} supports only SUBACCOUNT keys"
            )
        if not key.source_value or key.source_value != mapping.source_value:
            raise ConversionProfileStoreError(
                f"{mapping_name} key must match source_value"
            )
        if key.side is not None:
            raise ConversionProfileStoreError(
                f"{mapping_name} side is occurrence metadata, not profile identity"
            )
        if mapping.parent_account != key.parent_account:
            raise ConversionProfileStoreError(
                f"{mapping_name} parent_account must match key context"
            )
        if mapping.status in {MappingStatus.RESOLVED, MappingStatus.USER_CONFIRMED}:
            if mapping.target_value is None:
                raise ConversionProfileStoreError(
                    f"{mapping_name} resolved mapping requires target_value"
                )
        if mapping.status is MappingStatus.UNRESOLVED and mapping.target_value is not None:
            raise ConversionProfileStoreError(
                f"{mapping_name} unresolved mapping must not carry target_value"
            )

from __future__ import annotations

from accounting_converter.application.runtime_output import RuntimeOutputResolution
from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    ProfileVersionStatus,
)
from accounting_converter.domain.mapping import MappingKey, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult

from .adapter import JDLOutputAdapter
from .context import JdlTargetContextValidator
from .models import JdlTargetContext
from .validator import JDLOutputValidator


class JdlOutputRuntimeFactory:
    """Creates a fresh JDL adapter pair from an explicit run-scoped context."""

    def resolve(
        self,
        output_profile: FormatProfile,
        conversion_profile: ConversionProfile | None,
        runtime_context: object | None,
    ) -> RuntimeOutputResolution:
        if runtime_context is None:
            return self._failed(
                "JDL-CONTEXT-MISSING",
                "JDL出力には確認済みtarget contextが必要です。",
                "target_context",
            )
        if not isinstance(runtime_context, JdlTargetContext):
            return self._failed(
                "JDL-CONTEXT-TYPE",
                "JDL出力用ではないruntime contextが指定されました。",
                "target_context",
            )
        errors = list(
            JdlTargetContextValidator().validate(runtime_context, output_profile)
        )
        errors.extend(
            self._validate_conversion_profile(conversion_profile, runtime_context)
        )
        if errors:
            return RuntimeOutputResolution(None, None, tuple(errors))
        return RuntimeOutputResolution(
            JDLOutputAdapter(runtime_context),
            JDLOutputValidator(runtime_context),
        )

    def _validate_conversion_profile(
        self,
        profile: ConversionProfile | None,
        context: JdlTargetContext,
    ) -> list[ValidationResult]:
        if profile is None:
            return [
                self._error(
                    "JDL-CONTEXT-PROFILE-MISSING",
                    "JDL target masterと照合するConversion Profileが必要です。",
                    "conversion_profile",
                )
            ]
        errors: list[ValidationResult] = []
        if profile.version_status is not ProfileVersionStatus.SUPPORTED:
            errors.append(
                self._error(
                    "JDL-CONTEXT-PROFILE-VERSION",
                    "Conversion Profileのschema versionを使用できません。",
                    "conversion_profile",
                )
            )
        if (
            context.target_format_identity is None
            or profile.target_format_identity.stable_key
            != context.target_format_identity.stable_key
        ):
            errors.append(
                self._error(
                    "JDL-CONTEXT-PROFILE-IDENTITY",
                    "Conversion Profileとtarget contextのformat identityが一致しません。",
                    "conversion_profile",
                )
            )
        self._validate_account_mappings(profile, context, errors)
        self._validate_subaccount_mappings(profile, context, errors)
        self._validate_department_mappings(profile, context, errors)
        return errors

    def _validate_account_mappings(
        self,
        profile: ConversionProfile,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        by_value = {item.mapping_value: item for item in context.account_master}
        for mapping in profile.account_mappings.values():
            identity = by_value.get(mapping.target_value or "")
            if (
                not mapping.is_resolved
                or identity is None
                or mapping.metadata.get("target_code") != identity.target_master_code
                or mapping.metadata.get("target_formal_name")
                != identity.target_formal_name
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-ACCOUNT-MAPPING-MISMATCH",
                        "確認済み科目MappingとJDL target masterが一致しません。",
                        "account_mapping",
                    )
                )

    def _validate_subaccount_mappings(
        self,
        profile: ConversionProfile,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        if profile.subaccount_mappings:
            errors.append(
                self._error(
                    "JDL-CONTEXT-SUBACCOUNT-PARENT-MISSING",
                    "JDL補助科目Mappingには親勘定科目contextが必要です。",
                    "subaccount_mapping",
                )
            )
        for key, mapping in profile.subaccount_context_mappings.items():
            if not self._subaccount_mapping_matches(key, mapping, profile, context):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-SUBACCOUNT-MAPPING-MISMATCH",
                        "親科目付き補助MappingとJDL target masterが一致しません。",
                        "subaccount_mapping",
                    )
                )

    @staticmethod
    def _subaccount_mapping_matches(
        key: MappingKey,
        mapping: MappingValue,
        profile: ConversionProfile,
        context: JdlTargetContext,
    ) -> bool:
        parent_mapping = profile.account_mappings.get(key.parent_account or "")
        if not mapping.is_resolved or parent_mapping is None or not parent_mapping.is_resolved:
            return False
        identity = next(
            (
                item
                for item in context.subaccounts
                if item.parent_account == parent_mapping.target_value
                and item.mapping_value == mapping.target_value
            ),
            None,
        )
        return bool(
            identity
            and mapping.metadata.get("target_code") == identity.target_master_code
            and mapping.metadata.get("output_code") == identity.output_code
            and mapping.metadata.get("output_name") == identity.output_name
        )

    def _validate_department_mappings(
        self,
        profile: ConversionProfile,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        by_value = {item.mapping_value: item for item in context.departments}
        for mapping in profile.department_mappings.values():
            identity = by_value.get(mapping.target_value or "")
            if (
                not mapping.is_resolved
                or identity is None
                or mapping.metadata.get("target_code") != identity.target_master_code
                or mapping.metadata.get("target_formal_name")
                != identity.target_formal_name
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-DEPARTMENT-MAPPING-MISMATCH",
                        "部門MappingとJDL target masterが一致しません。",
                        "department_mapping",
                    )
                )

    @classmethod
    def _failed(
        cls,
        rule_id: str,
        message: str,
        field: str,
    ) -> RuntimeOutputResolution:
        return RuntimeOutputResolution(
            None,
            None,
            (cls._error(rule_id, message, field),),
        )

    @staticmethod
    def _error(rule_id: str, message: str, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            field=field,
            suggested_action=(
                "選択したConversion Profileと確認済みJDL target snapshotを見直してください。"
            ),
        )

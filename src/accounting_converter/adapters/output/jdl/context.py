from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from accounting_converter.domain.format_metadata import FormatIdentity
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)

from .models import (
    JDL_OUTPUT_FORMAT_ID,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlDepartmentIdentity,
    JdlSubaccountIdentity,
    JdlTargetContext,
)


@dataclass(frozen=True)
class JdlTargetContextBuildResult:
    context: JdlTargetContext | None
    validation_results: tuple[ValidationResult, ...]

    @property
    def success(self) -> bool:
        return self.context is not None and not self.validation_results


class JdlTargetContextBuilder:
    """Builds a validated, run-scoped snapshot of a confirmed JDL target."""

    def build(
        self,
        *,
        target_format_identity: FormatIdentity,
        product: str,
        version: str,
        account_master: Iterable[JdlAccountIdentity],
        subaccounts: Iterable[JdlSubaccountIdentity],
        departments: Iterable[JdlDepartmentIdentity],
        tax_processing_mode: JdlTaxProcessingMode,
        department_processing_enabled: bool,
        standard_taxation_confirmed: bool,
        individual_credit_method_confirmed: bool,
        confirmation_state: JdlContextConfirmationState,
        provenance: JdlContextProvenance,
        no_fuzzy_matching: bool,
        no_automatic_replacement: bool,
    ) -> JdlTargetContextBuildResult:
        accounts = tuple(account_master)
        context = JdlTargetContext(
            product=product,
            version=version,
            accounts=frozenset(item.mapping_value for item in accounts),
            tax_processing_mode=tax_processing_mode,
            target_format_identity=target_format_identity,
            account_master=accounts,
            subaccounts=tuple(subaccounts),
            departments=tuple(departments),
            department_processing_enabled=department_processing_enabled,
            standard_taxation_confirmed=standard_taxation_confirmed,
            individual_credit_method_confirmed=individual_credit_method_confirmed,
            no_fuzzy_matching=no_fuzzy_matching,
            no_automatic_replacement=no_automatic_replacement,
            confirmation_state=confirmation_state,
            provenance=provenance,
        )
        results = JdlTargetContextValidator().validate(context)
        return JdlTargetContextBuildResult(
            context=None if results else context,
            validation_results=results,
        )


class JdlTargetContextValidator:
    def validate(
        self,
        context: JdlTargetContext,
        output_profile: FormatProfile | None = None,
    ) -> tuple[ValidationResult, ...]:
        errors: list[ValidationResult] = []
        expected_identity = (
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        )
        if (
            context.product != "JDL IBEX 出納帳"
            or context.version != "35.5"
            or context.target_format_identity is None
            or context.target_format_identity.stable_key != expected_identity.stable_key
        ):
            errors.append(
                self._error(
                    "JDL-CONTEXT-TARGET-IDENTITY",
                    "取込先JDLの製品、version、format identityが対応対象と一致しません。",
                    "target_identity",
                )
            )
        if output_profile is not None and (
            output_profile.software != "JDL"
            or output_profile.product != context.product
            or output_profile.version != context.version
            or output_profile.format_id != JDL_OUTPUT_FORMAT_ID
            or output_profile.encoding.lower() != "cp932"
        ):
            errors.append(
                self._error(
                    "JDL-CONTEXT-OUTPUT-PROFILE",
                    "出力profileとJDL target contextが一致しません。",
                    "output_profile",
                )
            )
        if (
            context.confirmation_state is not JdlContextConfirmationState.CONFIRMED
            or context.provenance is JdlContextProvenance.UNCONFIRMED
        ):
            errors.append(
                self._error(
                    "JDL-CONTEXT-UNCONFIRMED",
                    "JDL target environmentの確認済みsnapshotが必要です。",
                    "confirmation",
                )
            )
        if context.tax_processing_mode is JdlTaxProcessingMode.UNCONFIRMED:
            errors.append(
                self._error(
                    "JDL-CONTEXT-TAX-SETTING",
                    "会社の消費税処理を明示確認してください。",
                    "tax_processing",
                )
            )
        elif context.tax_processing_mode is JdlTaxProcessingMode.EXEMPT:
            if (
                context.standard_taxation_confirmed
                or context.individual_credit_method_confirmed
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-TAX-SETTING-CONFLICT",
                        "免税contextと課税事業者向け設定が矛盾しています。",
                        "tax_processing",
                    )
                )
        elif (
            not context.standard_taxation_confirmed
            or not context.individual_credit_method_confirmed
        ):
            errors.append(
                self._error(
                    "JDL-CONTEXT-TAX-SETTING-MISSING",
                    "課税contextには原則課税・個別対応方式の確認が必要です。",
                    "tax_processing",
                )
            )
        if not context.no_fuzzy_matching or not context.no_automatic_replacement:
            errors.append(
                self._error(
                    "JDL-CONTEXT-MAPPING-POLICY",
                    "fuzzy matchingと自動置換は禁止されています。",
                    "mapping_policy",
                )
            )
        if not context.account_master:
            errors.append(
                self._error(
                    "JDL-CONTEXT-ACCOUNT-MASTER-MISSING",
                    "確認済み勘定科目masterが必要です。",
                    "account_master",
                )
            )
        self._validate_accounts(context, errors)
        self._validate_subaccounts(context, errors)
        self._validate_departments(context, errors)
        if context.departments and not context.department_processing_enabled:
            errors.append(
                self._error(
                    "JDL-CONTEXT-DEPARTMENT-SETTING",
                    "部門masterを使う場合は部門処理の確認が必要です。",
                    "department_processing",
                )
            )
        return tuple(errors)

    def _validate_accounts(
        self,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        identities = [item.mapping_value for item in context.account_master]
        codes = [item.target_master_code for item in context.account_master]
        if len(identities) != len(set(identities)) or len(codes) != len(set(codes)):
            errors.append(
                self._error(
                    "JDL-CONTEXT-ACCOUNT-DUPLICATE",
                    "勘定科目masterに重複するidentityまたはcodeがあります。",
                    "account_master",
                )
            )
        if context.accounts != frozenset(identities):
            errors.append(
                self._error(
                    "JDL-CONTEXT-ACCOUNT-SET",
                    "勘定科目master snapshotのidentity集合が一致しません。",
                    "account_master",
                )
            )
        for item in context.account_master:
            if (
                item.mapping_value != item.target_name
                or not self._numeric(item.target_master_code, 4)
                or not self._text(item.target_name, 4)
                or not self._text(item.target_formal_name, 12)
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-ACCOUNT-MALFORMED",
                        "勘定科目masterのcode、名称、正式名称が不正です。",
                        "account_master",
                    )
                )

    def _validate_subaccounts(
        self,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        accounts = {
            (item.mapping_value, item.target_master_code)
            for item in context.account_master
        }
        identities = [
            (item.parent_account, item.mapping_value)
            for item in context.subaccounts
        ]
        codes = [
            (item.parent_account_code, item.target_master_code)
            for item in context.subaccounts
        ]
        if len(identities) != len(set(identities)) or len(codes) != len(set(codes)):
            errors.append(
                self._error(
                    "JDL-CONTEXT-SUBACCOUNT-DUPLICATE",
                    "補助科目masterに重複する親科目付きidentityまたはcodeがあります。",
                    "subaccount_master",
                )
            )
        for item in context.subaccounts:
            if (
                (item.parent_account, item.parent_account_code) not in accounts
                or item.mapping_value != item.target_name
                or not self._numeric(item.target_master_code, 4)
                or not self._numeric(item.output_code, 4)
                or not self._text(item.output_name, 10)
                or not item.output_representation_confirmed
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-SUBACCOUNT-PARENT",
                        "補助科目と親勘定科目の確認済み関係が不正です。",
                        "subaccount_master",
                    )
                )

    def _validate_departments(
        self,
        context: JdlTargetContext,
        errors: list[ValidationResult],
    ) -> None:
        identities = [item.mapping_value for item in context.departments]
        codes = [item.target_master_code for item in context.departments]
        if len(identities) != len(set(identities)) or len(codes) != len(set(codes)):
            errors.append(
                self._error(
                    "JDL-CONTEXT-DEPARTMENT-DUPLICATE",
                    "部門masterに重複するidentityまたはcodeがあります。",
                    "department_master",
                )
            )
        for item in context.departments:
            if (
                item.target_master_code != item.output_code
                or not self._numeric(item.target_master_code, 4)
                or not self._text(item.output_name, 4)
                or not self._text(item.target_formal_name)
            ):
                errors.append(
                    self._error(
                        "JDL-CONTEXT-DEPARTMENT-MALFORMED",
                        "部門masterのcode、正式名称、短縮名称が不正です。",
                        "department_master",
                    )
                )

    @staticmethod
    def _numeric(value: str, max_length: int) -> bool:
        return bool(value) and value.isdecimal() and len(value) <= max_length

    @staticmethod
    def _text(value: str, max_length: int | None = None) -> bool:
        if not value or (max_length is not None and len(value) > max_length):
            return False
        try:
            return value.encode("cp932", errors="strict").decode("cp932") == value
        except UnicodeError:
            return False

    @staticmethod
    def _error(rule_id: str, message: str, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            field=field,
            suggested_action=(
                "JDL実機で確認したtarget masterと会社設定からcontextを再構築してください。"
            ),
        )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Sequence

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, TaxInfo
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)

from .models import (
    JDL_FILE_COMBINATION_GATE_METADATA_KEY,
    JDL_OUTPUT_FORMAT_ID,
    JDL_OUTPUT_METADATA_KEY,
    JdlDepartmentIdentity,
    JdlEvidenceProfile,
    JdlFileCombinationGate,
    JdlOutputPlan,
    JdlOutputRow,
    JdlSubaccountIdentity,
    JdlTargetContext,
)


TAX_SCOPE_PURCHASE = "仕　入"
TAX_CATEGORY_TEN_PERCENT = "10%"
TAX_INPUT_METHOD_INTERNAL = "内税"
EVIDENCE_IDS = {
    JdlEvidenceProfile.BASIC_1111: "EVID-JDL-GENERATOR-1111-001",
    JdlEvidenceProfile.BASIC_1000: "EVID-JDL-GENERATOR-1000-001",
    JdlEvidenceProfile.SUBACCOUNT_1000: (
        "EVID-JDL-GENERATOR-1000-SUBACCOUNT-001"
    ),
    JdlEvidenceProfile.DEPARTMENT_1111: (
        "EVID-JDL-GENERATOR-1111-DEPARTMENT-001"
    ),
    JdlEvidenceProfile.TAX_INCLUDED_1111: (
        "EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001"
    ),
    JdlEvidenceProfile.TAX_EXCLUDED_1111: (
        "EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001"
    ),
    JdlEvidenceProfile.COMPOUND_1D3C: (
        "EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001"
    ),
}
MULTIGROUP_EVIDENCE_ID = "EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001"
SIMPLE_PLUS_SIMPLE_UNTESTED_GATE_ID = (
    "UNTESTED-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-GATE"
)


class JdlOutputBlockedError(ValueError):
    def __init__(self, results: Sequence[ValidationResult]) -> None:
        self.validation_results = tuple(results)
        super().__init__("JDL output was blocked by evidence preflight")


@dataclass(frozen=True)
class JdlPreflightResult:
    plan: JdlOutputPlan | None
    validation_results: tuple[ValidationResult, ...]

    @property
    def supported(self) -> bool:
        return self.plan is not None and not self.validation_results


class JdlOutputPreflight:
    def __init__(self, context: JdlTargetContext) -> None:
        self.context = context

    def evaluate(
        self,
        entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> JdlPreflightResult:
        errors: list[ValidationResult] = []
        self._validate_profile(profile, errors)
        self._validate_context(errors)
        if not entries:
            errors.append(self._error("JDL-OUT-EMPTY", "仕訳がありません。", "entries"))

        rows: list[JdlOutputRow] = []
        profiles: list[JdlEvidenceProfile] = []
        for entry in entries:
            evidence = self._profile_for_entry(entry, errors)
            if evidence is None:
                continue
            profiles.append(evidence)
            rows.extend(self._rows_for_entry(entry, evidence, errors))

        if profiles:
            self._validate_file_combination(entries, tuple(profiles), errors)
        if not errors:
            self._validate_serializable_rows(rows, errors)
        if errors:
            return JdlPreflightResult(None, tuple(errors))
        return JdlPreflightResult(
            JdlOutputPlan(tuple(rows), tuple(profiles), len(entries)),
            (),
        )

    def _validate_profile(
        self,
        profile: FormatProfile,
        errors: list[ValidationResult],
    ) -> None:
        expected = ("JDL", "JDL IBEX 出納帳", "35.5", JDL_OUTPUT_FORMAT_ID, "cp932")
        actual = (
            profile.software,
            profile.product,
            profile.version,
            profile.format_id,
            profile.encoding.lower(),
        )
        if actual != expected:
            errors.append(
                self._error(
                    "JDL-OUT-FORMAT-IDENTITY",
                    "JDL出力profileが検証済みidentityと一致しません。",
                    "output_profile",
                )
            )

    def _validate_context(self, errors: list[ValidationResult]) -> None:
        if self.context.product != "JDL IBEX 出納帳" or self.context.version != "35.5":
            errors.append(
                self._error(
                    "JDL-OUT-TARGET-IDENTITY",
                    "取込先JDL製品またはversionが検証済み対象と一致しません。",
                    "target_identity",
                )
            )
        if not self.context.no_fuzzy_matching or not self.context.no_automatic_replacement:
            errors.append(
                self._error(
                    "JDL-OUT-EXACT-MAPPING-REQUIRED",
                    "fuzzy mappingまたは自動置換は使用できません。",
                    "mapping_policy",
                )
            )
        for item in self.context.subaccounts:
            if (
                not item.target_master_code
                or not item.output_code
                or not item.output_name
                or not item.output_representation_confirmed
            ):
                errors.append(
                    self._error(
                        "JDL-OUT-SUBACCOUNT-IDENTITY",
                        "補助科目のtarget masterと出力表現を明示してください。",
                        "sub_account",
                    )
                )
        for item in self.context.departments:
            if (
                item.target_master_code != item.output_code
                or not item.output_name
            ):
                errors.append(
                    self._error(
                        "JDL-OUT-DEPARTMENT-IDENTITY",
                        "部門codeは確認済みtarget masterと完全一致する必要があります。",
                        "department",
                    )
                )

    def _profile_for_entry(
        self,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> JdlEvidenceProfile | None:
        raw = entry.metadata.get(JDL_OUTPUT_METADATA_KEY)
        try:
            return JdlEvidenceProfile(raw)
        except (TypeError, ValueError):
            errors.append(
                self._error(
                    "JDL-OUT-EVIDENCE-PROFILE",
                    "検証済みJDL Evidence profileが明示されていません。",
                    "evidence_profile",
                    entry,
                )
            )
            return None

    def _rows_for_entry(
        self,
        entry: JournalEntry,
        evidence: JdlEvidenceProfile,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        if evidence is JdlEvidenceProfile.COMPOUND_1D3C:
            return self._compound_rows(entry, errors)
        if not entry.is_balanced():
            errors.append(self._error("JDL-OUT-BALANCE", "仕訳が貸借一致しません。", "amount", entry))
            return []
        if entry.description is not None and len(entry.description) > 32:
            errors.append(self._error("JDL-OUT-DESCRIPTION-LENGTH", "摘要が32文字を超えています。", "description", entry))
            return []
        return self._simple_rows(entry, evidence, errors)

    def _simple_rows(
        self,
        entry: JournalEntry,
        evidence: JdlEvidenceProfile,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        debit = [line for line in entry.lines if line.side is Side.DEBIT]
        credit = [line for line in entry.lines if line.side is Side.CREDIT]
        if len(debit) != 1 or len(credit) != 1:
            errors.append(self._error("JDL-OUT-SIMPLE-SHAPE", "単一仕訳は借貸各1行だけ対応します。", "journal_structure", entry))
            return []

        flag = "1000" if evidence in {
            JdlEvidenceProfile.BASIC_1000,
            JdlEvidenceProfile.SUBACCOUNT_1000,
        } else "1111"
        self._validate_feature_combination(debit[0], credit[0], evidence, entry, errors)
        if errors:
            return []
        return [self._row(flag, entry, debit[0], credit[0], entry.description or "")]

    def _compound_rows(
        self,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> list[JdlOutputRow]:
        debit = [line for line in entry.lines if line.side is Side.DEBIT]
        credit = [line for line in entry.lines if line.side is Side.CREDIT]
        if len(debit) != 1 or len(credit) != 3 or len(entry.lines) != 4:
            errors.append(self._error("JDL-OUT-COMPOUND-SHAPE", "v0は1借方対3貸方の複合仕訳だけ対応します。", "journal_structure", entry))
            return []
        if not entry.is_balanced():
            errors.append(self._error("JDL-OUT-BALANCE", "複合仕訳がgroup単位で貸借一致しません。", "amount", entry))
            return []
        if any(self._has_optional_features(line) for line in entry.lines):
            errors.append(self._error("JDL-OUT-COMPOUND-FEATURE", "複合仕訳内の補助・部門・税は未対応です。", "journal_structure", entry))
            return []
        if self.context.tax_processing_mode is not JdlTaxProcessingMode.EXEMPT:
            errors.append(self._error("JDL-OUT-COMPOUND-TAX-MODE", "複合仕訳は免税profileだけ対応します。", "tax_processing", entry))
            return []
        for line in entry.lines:
            self._validate_account(line, entry, errors)
            self._validate_amount(line.amount, entry, errors)
        if errors:
            return []
        flags = ("1110", "1100", "1101")
        rows: list[JdlOutputRow] = []
        for index, credit_line in enumerate(credit):
            rows.append(
                self._row(
                    flags[index],
                    entry,
                    debit[0] if index == 0 else None,
                    credit_line,
                    (entry.description or "") if index == 0 else "",
                )
            )
        return rows

    def _validate_feature_combination(
        self,
        debit: JournalLine,
        credit: JournalLine,
        evidence: JdlEvidenceProfile,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        for line in (debit, credit):
            self._validate_account(line, entry, errors)
            self._validate_amount(line.amount, entry, errors)

        if evidence in {JdlEvidenceProfile.BASIC_1111, JdlEvidenceProfile.BASIC_1000}:
            if any(self._has_optional_features(line) for line in (debit, credit)):
                errors.append(self._error("JDL-OUT-BASIC-FEATURE", "basic profileに補助・部門・税を追加できません。", "evidence_profile", entry))
            self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        elif evidence is JdlEvidenceProfile.SUBACCOUNT_1000:
            self._validate_subaccount(debit, credit, entry, errors)
        elif evidence is JdlEvidenceProfile.DEPARTMENT_1111:
            self._validate_department(debit, credit, entry, errors)
        elif evidence is JdlEvidenceProfile.TAX_INCLUDED_1111:
            self._validate_tax(debit, credit, entry, included=True, errors=errors)
        elif evidence is JdlEvidenceProfile.TAX_EXCLUDED_1111:
            self._validate_tax(debit, credit, entry, included=False, errors=errors)

    def _validate_account(
        self,
        line: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if not line.account or line.account not in self.context.accounts:
            errors.append(self._error("JDL-OUT-ACCOUNT-MASTER", "確認済み取込先科目に一致しません。", "account", entry))
        elif len(line.account) > 4:
            errors.append(self._error("JDL-OUT-ACCOUNT-LENGTH", "v0の科目名称identifierは4文字以内です。", "account", entry))

    def _validate_amount(
        self,
        amount: Decimal,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if amount < 0 or amount != amount.to_integral_value():
            errors.append(self._error("JDL-OUT-AMOUNT", "金額は0以上の整数円で指定してください。", "amount", entry))

    def _validate_subaccount(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        if debit.sub_account or debit.department or credit.department or debit.tax_info or credit.tax_info:
            errors.append(self._error("JDL-OUT-SUBACCOUNT-COMBINATION", "検証済み貸方補助以外のfeatureを併用できません。", "evidence_profile", entry))
        identity = self._subaccount_identity(credit)
        if not credit.sub_account or identity is None:
            errors.append(self._error("JDL-OUT-SUBACCOUNT-MASTER", "貸方補助と親科目の完全一致確認が必要です。", "sub_account", entry))

    def _validate_department(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        self._require_tax_mode(JdlTaxProcessingMode.EXEMPT, entry, errors)
        if not self.context.department_processing_enabled:
            errors.append(self._error("JDL-OUT-DEPARTMENT-DISABLED", "取込先の部門処理確認が必要です。", "department", entry))
        if debit.sub_account or credit.sub_account or debit.tax_info or credit.tax_info:
            errors.append(self._error("JDL-OUT-DEPARTMENT-COMBINATION", "部門profileに補助・税を併用できません。", "evidence_profile", entry))
        if not debit.department or not credit.department:
            errors.append(self._error("JDL-OUT-DEPARTMENT-BOTH-SIDES", "検証済みscopeでは借貸両側の部門指定が必要です。", "department", entry))
        for line in (debit, credit):
            if line.department and self._department_identity(line.department) is None:
                errors.append(self._error("JDL-OUT-DEPARTMENT-MASTER", "確認済み取込先部門に一致しません。", "department", entry))

    def _validate_tax(
        self,
        debit: JournalLine,
        credit: JournalLine,
        entry: JournalEntry,
        *,
        included: bool,
        errors: list[ValidationResult],
    ) -> None:
        expected_mode = (
            JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED
            if included
            else JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED
        )
        self._require_tax_mode(expected_mode, entry, errors)
        if not self.context.standard_taxation_confirmed or not self.context.individual_credit_method_confirmed:
            errors.append(self._error("JDL-OUT-TAX-COMPANY-PROFILE", "原則課税・個別対応方式の確認が必要です。", "tax_processing", entry))
        if debit.sub_account or credit.sub_account or debit.department or credit.department:
            errors.append(self._error("JDL-OUT-TAX-COMBINATION", "検証済み税profileに補助・部門を併用できません。", "evidence_profile", entry))
        info = debit.tax_info
        if info is None or info.category != TAX_CATEGORY_TEN_PERCENT or info.metadata.get("jdl_tax_scope") != TAX_SCOPE_PURCHASE:
            errors.append(self._error("JDL-OUT-TAX-LITERAL", "検証済み課区・税区のexact literalが必要です。", "tax", entry))
            return
        if info.reduced_rate is True or info.rate not in {None, Decimal("10")}:
            errors.append(self._error("JDL-OUT-TAX-RATE", "v0は検証済み10%通常税率だけ対応します。", "tax", entry))
        if self._nonempty_tax(credit.tax_info):
            errors.append(self._error("JDL-OUT-CREDIT-TAX", "貸方側課税は未検証です。", "tax", entry))
        if info.metadata.get("jdl_transaction_account"):
            errors.append(self._error("JDL-OUT-TRANSACTION-ACCOUNT", "取引科目を必要とするcaseは未対応です。", "tax", entry))
        method = info.metadata.get("jdl_tax_input_method")
        if included:
            if method not in {None, ""} or info.tax_amount is not None:
                errors.append(self._error("JDL-OUT-TAX-INCLUDED-FIELDS", "税込profileでは税入力方法・消費税を出力しません。", "tax", entry))
        elif method != TAX_INPUT_METHOD_INTERNAL or info.tax_amount is None:
            errors.append(self._error("JDL-OUT-TAX-EXCLUDED-FIELDS", "税抜profileには内税と明示消費税額が必要です。", "tax", entry))
        elif info.tax_amount < 0 or info.tax_amount != info.tax_amount.to_integral_value():
            errors.append(self._error("JDL-OUT-TAX-AMOUNT", "消費税額は0以上の整数円で指定してください。", "tax", entry))
        else:
            observed_tax_amount = (debit.amount * Decimal("10") / Decimal("110")).quantize(
                Decimal("1"),
                rounding=ROUND_DOWN,
            )
            if info.tax_amount != observed_tax_amount:
                errors.append(
                    self._error(
                        "JDL-OUT-TAX-AMOUNT-PATTERN",
                        "明示消費税額が検証済み10%内税・端数切捨てpatternと一致しません。",
                        "tax",
                        entry,
                    )
                )

    def _validate_file_combination(
        self,
        entries: Sequence[JournalEntry],
        profiles: tuple[JdlEvidenceProfile, ...],
        errors: list[ValidationResult],
    ) -> None:
        if len(profiles) == 1:
            return
        allowed = (JdlEvidenceProfile.BASIC_1111, JdlEvidenceProfile.COMPOUND_1D3C)
        simple_release_gate = (
            profiles == (JdlEvidenceProfile.BASIC_1111,) * 2
            and len(entries) == 2
            and entries[0].date == entries[1].date
            and all(
                entry.metadata.get(JDL_FILE_COMBINATION_GATE_METADATA_KEY)
                == JdlFileCombinationGate.SIMPLE_PLUS_SIMPLE_UNTESTED.value
                for entry in entries
            )
        )
        if not simple_release_gate and (
            profiles != allowed
            or len(entries) != 2
            or entries[0].date != entries[1].date
        ):
            errors.append(
                self._error(
                    "JDL-OUT-MULTIGROUP-SCOPE",
                    "複数groupは検証済み1111+compound同日構成、または明示UNTESTED release gateだけ対応します。",
                    "journal_groups",
                )
            )

    def _validate_serializable_rows(
        self,
        rows: Sequence[JdlOutputRow],
        errors: list[ValidationResult],
    ) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()
        for row in rows:
            columns = row.columns()
            if len(columns) != spec.column_count:
                errors.append(self._error("JDL-OUT-COLUMN-COUNT", "JDL出力行は30列である必要があります。", "column_count"))
                continue
            for definition, value in zip(spec.columns, columns, strict=True):
                if definition.max_length is not None and len(value) > definition.max_length:
                    errors.append(self._error("JDL-OUT-FIELD-LENGTH", "JDL項目の最大文字数を超えています。", definition.name))
                try:
                    encoded = value.encode("cp932", errors="strict")
                    if encoded.decode("cp932", errors="strict") != value:
                        raise UnicodeError("CP932 round-trip mismatch")
                except UnicodeError:
                    errors.append(self._error("JDL-OUT-CP932", "CP932へ損失なく変換できない文字を検出しました。", definition.name))
                if value and definition.data_type == "数値" and not value.isdecimal():
                    errors.append(self._error("JDL-OUT-NUMERIC-FIELD", "数値項目に数字以外が含まれています。", definition.name))
                if value and definition.data_type == "金額":
                    try:
                        amount = Decimal(value)
                    except InvalidOperation:
                        amount = Decimal("-1")
                    if amount < 0 or amount != amount.to_integral_value():
                        errors.append(self._error("JDL-OUT-AMOUNT-FIELD", "金額項目は0以上の整数円である必要があります。", definition.name))
                if value and definition.data_type == "日付":
                    try:
                        datetime.strptime(value, "%Y%m%d")
                    except ValueError:
                        errors.append(self._error("JDL-OUT-DATE-FIELD", "日付は有効なYYYYMMDDである必要があります。", definition.name))

    def _row(
        self,
        flag: str,
        entry: JournalEntry,
        debit: JournalLine | None,
        credit: JournalLine,
        description: str,
    ) -> JdlOutputRow:
        debit_sub = self._subaccount_identity(debit) if debit else None
        credit_sub = self._subaccount_identity(credit)
        debit_department = self._department_identity(debit.department) if debit and debit.department else None
        credit_department = self._department_identity(credit.department) if credit.department else None
        debit_tax = debit.tax_info if debit else None
        credit_tax = credit.tax_info
        return JdlOutputRow(
            identifier_flag=flag,
            voucher_number="",
            journal_date=entry.date.strftime("%Y%m%d"),
            debit_account_code="",
            debit_account_name=debit.account if debit and debit.account else "",
            debit_account_formal_name="",
            debit_subaccount_code=debit_sub.output_code if debit_sub else "",
            debit_subaccount_name=debit_sub.output_name if debit_sub else "",
            debit_tax_scope=self._tax_metadata(debit_tax, "jdl_tax_scope"),
            debit_tax_category=debit_tax.category if debit_tax and debit_tax.category else "",
            debit_tax_input_method=self._tax_metadata(debit_tax, "jdl_tax_input_method"),
            debit_amount=self._amount(debit.amount) if debit else "0",
            debit_tax_amount=self._optional_amount(debit_tax.tax_amount if debit_tax else None),
            credit_account_code="",
            credit_account_name=credit.account or "",
            credit_account_formal_name="",
            credit_subaccount_code=credit_sub.output_code if credit_sub else "",
            credit_subaccount_name=credit_sub.output_name if credit_sub else "",
            credit_tax_scope=self._tax_metadata(credit_tax, "jdl_tax_scope"),
            credit_tax_category=credit_tax.category if credit_tax and credit_tax.category else "",
            credit_tax_input_method=self._tax_metadata(credit_tax, "jdl_tax_input_method"),
            credit_amount=self._amount(credit.amount),
            credit_tax_amount=self._optional_amount(credit_tax.tax_amount if credit_tax else None),
            description=description,
            debit_transaction_account="",
            credit_transaction_account="",
            debit_department_code=debit_department.output_code if debit_department else "",
            debit_department_name=debit_department.output_name if debit_department else "",
            credit_department_code=credit_department.output_code if credit_department else "",
            credit_department_name=credit_department.output_name if credit_department else "",
        )

    def _subaccount_identity(self, line: JournalLine | None) -> JdlSubaccountIdentity | None:
        if line is None or not line.account or not line.sub_account:
            return None
        return next(
            (
                item
                for item in self.context.subaccounts
                if item.parent_account == line.account and item.mapping_value == line.sub_account
            ),
            None,
        )

    def _department_identity(self, value: str | None) -> JdlDepartmentIdentity | None:
        if not value:
            return None
        return next((item for item in self.context.departments if item.mapping_value == value), None)

    def _require_tax_mode(
        self,
        expected: JdlTaxProcessingMode,
        entry: JournalEntry,
        errors: list[ValidationResult],
    ) -> None:
        if self.context.tax_processing_mode is not expected:
            errors.append(self._error("JDL-OUT-TAX-MODE", "会社の消費税処理がEvidence profileと一致しません。", "tax_processing", entry))

    @staticmethod
    def _has_optional_features(line: JournalLine) -> bool:
        return bool(line.sub_account or line.department or JdlOutputPreflight._nonempty_tax(line.tax_info))

    @staticmethod
    def _nonempty_tax(info: TaxInfo | None) -> bool:
        return bool(
            info
            and (
                info.category
                or info.rate is not None
                or info.tax_inclusion
                or info.reduced_rate is True
                or info.invoice_classification
                or info.tax_amount is not None
                or info.metadata.get("jdl_tax_scope")
                or info.metadata.get("jdl_tax_input_method")
                or info.metadata.get("jdl_transaction_account")
            )
        )

    @staticmethod
    def _tax_metadata(info: TaxInfo | None, key: str) -> str:
        if info is None:
            return ""
        value = info.metadata.get(key, "")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _amount(value: Decimal) -> str:
        return str(value.quantize(Decimal("1")))

    @staticmethod
    def _optional_amount(value: Decimal | None) -> str:
        return "" if value is None else str(value.quantize(Decimal("1")))

    @staticmethod
    def _error(
        rule_id: str,
        message: str,
        field: str,
        entry: JournalEntry | None = None,
    ) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            journal_id=entry.id if entry else None,
            source_reference=entry.source_reference if entry else None,
            field=field,
            suggested_action="検証済みEvidence scopeと取込先master設定を確認してください。",
        )


def jdl_ibex_35_5_output_profile() -> FormatProfile:
    return FormatProfile(
        software="JDL",
        product="JDL IBEX 出納帳",
        version="35.5",
        format_id=JDL_OUTPUT_FORMAT_ID,
        encoding="cp932",
        delimiter=",",
        date_format="%Y%m%d",
        journal_structure="evidence-limited-v0",
        columns=tuple(),
    )

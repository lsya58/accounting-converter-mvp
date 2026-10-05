from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from accounting_converter.domain.format_metadata import FormatIdentity
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


JDL_OUTPUT_METADATA_KEY = "jdl_output_evidence_profile"
JDL_OUTPUT_FORMAT_ID = "jdl-ibex-cashbook-journal-csv-30-v0"


class JdlEvidenceProfile(str, Enum):
    BASIC_1111 = "SUPPORTED_1111_BASIC"
    BASIC_1000 = "SUPPORTED_1000_BASIC"
    SUBACCOUNT_1000 = "SUPPORTED_1000_SUBACCOUNT"
    DEPARTMENT_1111 = "SUPPORTED_1111_DEPARTMENT"
    TAX_INCLUDED_1111 = "SUPPORTED_1111_TAX_INCLUDED"
    TAX_EXCLUDED_1111 = "SUPPORTED_1111_TAX_EXCLUDED"
    COMPOUND_1D3C = "SUPPORTED_COMPOUND_1D3C"


class JdlContextConfirmationState(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"


class JdlContextProvenance(str, Enum):
    USER_CONFIRMED_RUNTIME_SNAPSHOT = "USER_CONFIRMED_RUNTIME_SNAPSHOT"
    LOCAL_VERIFIED_SNAPSHOT = "LOCAL_VERIFIED_SNAPSHOT"
    UNCONFIRMED = "UNCONFIRMED"


@dataclass(frozen=True)
class JdlAccountIdentity:
    mapping_value: str
    target_master_code: str
    target_name: str
    target_formal_name: str


@dataclass(frozen=True)
class JdlSubaccountIdentity:
    parent_account: str
    mapping_value: str
    target_master_code: str
    output_code: str
    output_name: str
    output_representation_confirmed: bool
    parent_account_code: str = ""
    target_name: str = ""


@dataclass(frozen=True)
class JdlDepartmentIdentity:
    mapping_value: str
    target_master_code: str
    output_code: str
    output_name: str
    target_formal_name: str = ""


@dataclass(frozen=True)
class JdlTargetContext:
    product: str
    version: str
    accounts: frozenset[str]
    tax_processing_mode: JdlTaxProcessingMode
    target_format_identity: FormatIdentity | None = None
    account_master: tuple[JdlAccountIdentity, ...] = ()
    subaccounts: tuple[JdlSubaccountIdentity, ...] = ()
    departments: tuple[JdlDepartmentIdentity, ...] = ()
    department_processing_enabled: bool = False
    standard_taxation_confirmed: bool = False
    individual_credit_method_confirmed: bool = False
    no_fuzzy_matching: bool = True
    no_automatic_replacement: bool = True
    confirmation_state: JdlContextConfirmationState = (
        JdlContextConfirmationState.UNCONFIRMED
    )
    provenance: JdlContextProvenance = JdlContextProvenance.UNCONFIRMED

    def privacy_safe_summary(self) -> dict[str, str | int]:
        return {
            "target_product": self.product,
            "target_version": self.version,
            "context_confirmation": self.confirmation_state.value,
            "context_provenance": self.provenance.value,
            "account_master_count": len(self.account_master),
            "subaccount_master_count": len(self.subaccounts),
            "department_master_count": len(self.departments),
            "tax_company_context": self.tax_processing_mode.value,
        }


@dataclass(frozen=True)
class JdlOutputRow:
    identifier_flag: str
    voucher_number: str
    journal_date: str
    debit_account_code: str
    debit_account_name: str
    debit_account_formal_name: str
    debit_subaccount_code: str
    debit_subaccount_name: str
    debit_tax_scope: str
    debit_tax_category: str
    debit_tax_input_method: str
    debit_amount: str
    debit_tax_amount: str
    credit_account_code: str
    credit_account_name: str
    credit_account_formal_name: str
    credit_subaccount_code: str
    credit_subaccount_name: str
    credit_tax_scope: str
    credit_tax_category: str
    credit_tax_input_method: str
    credit_amount: str
    credit_tax_amount: str
    description: str
    debit_transaction_account: str
    credit_transaction_account: str
    debit_department_code: str
    debit_department_name: str
    credit_department_code: str
    credit_department_name: str

    def columns(self) -> tuple[str, ...]:
        return (
            self.identifier_flag,
            self.voucher_number,
            self.journal_date,
            self.debit_account_code,
            self.debit_account_name,
            self.debit_account_formal_name,
            self.debit_subaccount_code,
            self.debit_subaccount_name,
            self.debit_tax_scope,
            self.debit_tax_category,
            self.debit_tax_input_method,
            self.debit_amount,
            self.debit_tax_amount,
            self.credit_account_code,
            self.credit_account_name,
            self.credit_account_formal_name,
            self.credit_subaccount_code,
            self.credit_subaccount_name,
            self.credit_tax_scope,
            self.credit_tax_category,
            self.credit_tax_input_method,
            self.credit_amount,
            self.credit_tax_amount,
            self.description,
            self.debit_transaction_account,
            self.credit_transaction_account,
            self.debit_department_code,
            self.debit_department_name,
            self.credit_department_code,
            self.credit_department_name,
        )


@dataclass(frozen=True)
class JdlOutputPlan:
    rows: tuple[JdlOutputRow, ...]
    evidence_profiles: tuple[JdlEvidenceProfile, ...]
    journal_count: int

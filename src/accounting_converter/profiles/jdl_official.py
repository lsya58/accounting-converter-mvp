from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class JdlDocumentedSpecificationStatus(str, Enum):
    OFFICIAL_DOCUMENTED = "OFFICIAL_DOCUMENTED"
    REAL_IMPORT_VERIFICATION_PENDING = "REAL_IMPORT_VERIFICATION_PENDING"


class JdlTaxProcessingMode(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    EXEMPT = "EXEMPT"
    TAXABLE_TAX_INCLUDED = "TAXABLE_TAX_INCLUDED"
    TAXABLE_TAX_EXCLUDED = "TAXABLE_TAX_EXCLUDED"


@dataclass(frozen=True)
class JdlOfficialColumnDefinition:
    position: int
    name: str
    data_type: str
    max_length: int | None = None
    required: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class JdlIdentifierFlagDefinition:
    value: str
    documented_meaning: str
    notes: str | None = None


@dataclass(frozen=True)
class JdlTaxConditionalRule:
    processing_mode: JdlTaxProcessingMode
    tax_scope_required: bool
    tax_category_required: bool
    tax_input_method_required: bool
    tax_amount_required: bool
    notes: str


@dataclass(frozen=True)
class JdlOfficialJournalImportSpecification:
    name: str
    product_family: str
    source_title: str
    source_pages: tuple[str, ...]
    manual_footer_date: date | None
    statuses: tuple[JdlDocumentedSpecificationStatus, ...]
    columns: tuple[JdlOfficialColumnDefinition, ...]
    identifier_flags: tuple[JdlIdentifierFlagDefinition, ...]
    tax_rules: tuple[JdlTaxConditionalRule, ...]
    evidence_level: str = "OFFICIAL_DOCUMENTED"
    is_formal_format_profile: bool = False

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def identifier_flag_values(self) -> tuple[str, ...]:
        return tuple(flag.value for flag in self.identifier_flags)


JDL_IBEX_CASHBOOK_OFFICIAL_JOURNAL_IMPORT_COLUMNS: tuple[
    JdlOfficialColumnDefinition,
    ...,
] = (
    JdlOfficialColumnDefinition(1, "//識別フラグ", "数値", 4, True, "`//` is half-width."),
    JdlOfficialColumnDefinition(2, "伝番", "数値", 8),
    JdlOfficialColumnDefinition(3, "日付", "日付", 8, True, "Gregorian YYYYMMDD."),
    JdlOfficialColumnDefinition(4, "借方科目", "数値", 4, notes="Account code."),
    JdlOfficialColumnDefinition(5, "借方科目名称", "文字", 4),
    JdlOfficialColumnDefinition(6, "借方科目正式名称", "文字", 12),
    JdlOfficialColumnDefinition(7, "借方補助", "数値", 4, notes="Subaccount code."),
    JdlOfficialColumnDefinition(8, "借方補助名称", "文字", 10),
    JdlOfficialColumnDefinition(9, "借方課区", "文字", 3),
    JdlOfficialColumnDefinition(10, "借方税区", "文字"),
    JdlOfficialColumnDefinition(11, "借方税入力方法", "文字", 2),
    JdlOfficialColumnDefinition(12, "借方金額", "金額", 12, True, "Tax-included amount."),
    JdlOfficialColumnDefinition(13, "借方消費税", "金額", 12),
    JdlOfficialColumnDefinition(14, "貸方科目", "数値", 4, notes="Account code."),
    JdlOfficialColumnDefinition(15, "貸方科目名称", "文字", 4),
    JdlOfficialColumnDefinition(16, "貸方科目正式名称", "文字", 12),
    JdlOfficialColumnDefinition(17, "貸方補助", "数値", 4, notes="Subaccount code."),
    JdlOfficialColumnDefinition(18, "貸方補助名称", "文字", 10),
    JdlOfficialColumnDefinition(19, "貸方課区", "文字", 3),
    JdlOfficialColumnDefinition(20, "貸方税区", "文字"),
    JdlOfficialColumnDefinition(21, "貸方税入力方法", "文字", 2),
    JdlOfficialColumnDefinition(22, "貸方金額", "金額", 12, True, "Tax-included amount."),
    JdlOfficialColumnDefinition(23, "貸方消費税", "金額", 12),
    JdlOfficialColumnDefinition(24, "摘要", "文字", 32),
    JdlOfficialColumnDefinition(25, "借方取引科目", "数値", 4, notes="Only for consumption tax journals."),
    JdlOfficialColumnDefinition(26, "貸方取引科目", "数値", 4, notes="Only for consumption tax journals."),
    JdlOfficialColumnDefinition(27, "借方部門コード", "数値", 4),
    JdlOfficialColumnDefinition(28, "借方部門名称", "文字", 4),
    JdlOfficialColumnDefinition(29, "貸方部門コード", "数値", 4),
    JdlOfficialColumnDefinition(30, "貸方部門名称", "文字", 4),
)


JDL_IBEX_CASHBOOK_OFFICIAL_IDENTIFIER_FLAGS: tuple[
    JdlIdentifierFlagDefinition,
    ...,
] = (
    JdlIdentifierFlagDefinition("1000", "伝票以外の仕訳"),
    JdlIdentifierFlagDefinition("1111", "伝票1行の仕訳"),
    JdlIdentifierFlagDefinition("1110", "伝票1行目の仕訳"),
    JdlIdentifierFlagDefinition("1100", "伝票n行目の仕訳"),
    JdlIdentifierFlagDefinition("1101", "伝票最終行の仕訳"),
)


JDL_IBEX_CASHBOOK_OFFICIAL_TAX_RULES: tuple[JdlTaxConditionalRule, ...] = (
    JdlTaxConditionalRule(
        processing_mode=JdlTaxProcessingMode.EXEMPT,
        tax_scope_required=False,
        tax_category_required=False,
        tax_input_method_required=False,
        tax_amount_required=False,
        notes="課区・税区・税入力方法・消費税は不要。",
    ),
    JdlTaxConditionalRule(
        processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
        tax_scope_required=True,
        tax_category_required=True,
        tax_input_method_required=False,
        tax_amount_required=False,
        notes="税込処理では課区・税区が必要。税入力方法・消費税は入力しない。",
    ),
    JdlTaxConditionalRule(
        processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        tax_scope_required=True,
        tax_category_required=True,
        tax_input_method_required=True,
        tax_amount_required=True,
        notes="税抜処理では課区・税区・税入力方法・消費税が必要。",
    ),
)


def jdl_ibex_cashbook_official_journal_import_spec() -> (
    JdlOfficialJournalImportSpecification
):
    return JdlOfficialJournalImportSpecification(
        name="JDL IBEX 出納帳 CSV仕訳データ入力 30項目",
        product_family="JDL IBEX 出納帳",
        source_title=(
            "JDL IBEX 出納帳 操作マニュアル CSV形式で出力するには / "
            "CSV形式のデータを取り込むには"
        ),
        source_pages=("P319", "P320", "P321", "P322", "P326", "P327"),
        manual_footer_date=date(2024, 2, 14),
        statuses=(
            JdlDocumentedSpecificationStatus.OFFICIAL_DOCUMENTED,
            JdlDocumentedSpecificationStatus.REAL_IMPORT_VERIFICATION_PENDING,
        ),
        columns=JDL_IBEX_CASHBOOK_OFFICIAL_JOURNAL_IMPORT_COLUMNS,
        identifier_flags=JDL_IBEX_CASHBOOK_OFFICIAL_IDENTIFIER_FLAGS,
        tax_rules=JDL_IBEX_CASHBOOK_OFFICIAL_TAX_RULES,
        is_formal_format_profile=False,
    )

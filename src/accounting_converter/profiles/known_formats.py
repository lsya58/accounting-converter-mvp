from __future__ import annotations

from datetime import date

from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.domain.format_metadata import (
    BlankPolicy,
    Capability,
    CapabilityStatus,
    EvidenceLevel,
    FieldDataType,
    FieldDefinition,
    FormatCapabilities,
    FormatDirection,
    FormatIdentity,
    JournalGroupingStrategy,
    SchemaDefinition,
    SemanticField,
    SourceProvenance,
)

from .yayoi_official import yayoi_accounting_05_official_import_spec


YAYOI_DESKTOP_SOURCE = SourceProvenance(
    title="仕訳データの項目と記述形式（他製品から仕訳データをインポートする場合など）",
    url="https://support.yayoi-kk.co.jp/faq_Subcontents.html?page_id=18545",
    evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
    retrieved_at=date(2026, 9, 2),
    notes="弥生会計05以降のインポート形式。実利用製品/versionの検証は未完了。",
)

YAYOI_NEXT_SOURCE = SourceProvenance(
    title="インポートデータの記述形式",
    url="https://support.yayoi-kk.co.jp/subcontents.html?page_id=29611",
    evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
    retrieved_at=date(2026, 9, 2),
    notes="弥生会計 Next。25項目または27項目が公式に示されるため、Yayoi=25列とはしない。",
)

JDL_OBSERVED_SOURCE = SourceProvenance(
    title="JDL IBEX 出納帳 35.5 実データ観測",
    url=None,
    evidence_level=EvidenceLevel.OBSERVED,
    verified_at=date(2026, 8, 27),
    notes="実機取込成功で検証済みの正式仕様ではない。",
)


_YAYOI_SEMANTIC_FIELDS: dict[str, SemanticField] = {
    "識別フラグ": SemanticField.IDENTIFIER_FLAG,
    "伝票No.": SemanticField.VOUCHER_NUMBER,
    "伝票No": SemanticField.VOUCHER_NUMBER,
    "取引日付": SemanticField.DATE,
    "借方勘定科目": SemanticField.DEBIT_ACCOUNT,
    "借方補助科目": SemanticField.DEBIT_SUBACCOUNT,
    "借方部門": SemanticField.DEBIT_DEPARTMENT,
    "借方税区分": SemanticField.DEBIT_TAX_CATEGORY,
    "借方金額": SemanticField.DEBIT_AMOUNT,
    "借方税金額": SemanticField.DEBIT_TAX_AMOUNT,
    "貸方勘定科目": SemanticField.CREDIT_ACCOUNT,
    "貸方補助科目": SemanticField.CREDIT_SUBACCOUNT,
    "貸方部門": SemanticField.CREDIT_DEPARTMENT,
    "貸方税区分": SemanticField.CREDIT_TAX_CATEGORY,
    "貸方金額": SemanticField.CREDIT_AMOUNT,
    "貸方税金額": SemanticField.CREDIT_TAX_AMOUNT,
    "摘要": SemanticField.DESCRIPTION,
    "仕訳メモ": SemanticField.JOURNAL_MEMO,
    "調整": SemanticField.ADJUSTMENT_FLAG,
}

_JDL_OBSERVED_FIELDS: dict[str, SemanticField] = {
    "//識別フラグ": SemanticField.IDENTIFIER_FLAG,
    "伝番": SemanticField.VOUCHER_NUMBER,
    "日付": SemanticField.DATE,
    "借方科目名称": SemanticField.DEBIT_ACCOUNT,
    "借方補助名称": SemanticField.DEBIT_SUBACCOUNT,
    "借方税区": SemanticField.DEBIT_TAX_CATEGORY,
    "借方金額": SemanticField.DEBIT_AMOUNT,
    "借方消費税": SemanticField.DEBIT_TAX_AMOUNT,
    "貸方科目名称": SemanticField.CREDIT_ACCOUNT,
    "貸方補助名称": SemanticField.CREDIT_SUBACCOUNT,
    "貸方税区": SemanticField.CREDIT_TAX_CATEGORY,
    "貸方金額": SemanticField.CREDIT_AMOUNT,
    "貸方消費税": SemanticField.CREDIT_TAX_AMOUNT,
    "摘要": SemanticField.DESCRIPTION,
    "借方部門名称": SemanticField.DEBIT_DEPARTMENT,
    "貸方部門名称": SemanticField.CREDIT_DEPARTMENT,
}


def yayoi_desktop_import_25_documented_schema() -> SchemaDefinition:
    spec = yayoi_accounting_05_official_import_spec()
    fields = tuple(
        FieldDefinition(
            field_id=f"yayoi_desktop_25_col_{column.position:02d}",
            display_name=column.name,
            semantic_field=_YAYOI_SEMANTIC_FIELDS.get(
                column.name,
                SemanticField.UNKNOWN,
            ),
            column_position=column.position,
            required=column.required,
            data_type=_data_type(column.data_type),
            max_length=column.max_length,
            allowed_values=(
                spec.identifier_flags if column.position == 1 else ()
            ),
            blank_policy=(
                BlankPolicy.REQUIRED if column.required else BlankPolicy.OPTIONAL
            ),
            evidence=EvidenceLevel.OFFICIAL_DOCUMENTED,
            source=YAYOI_DESKTOP_SOURCE,
        )
        for column in spec.columns
    )
    return SchemaDefinition(
        identity=FormatIdentity(
            vendor="Yayoi",
            product="Yayoi Accounting Desktop",
            format_name="Yayoi Import Format",
            direction=FormatDirection.INPUT,
            evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
            version_range="05+",
            source_reference=YAYOI_DESKTOP_SOURCE,
            notes="Official documented import format; real export CSV verification pending.",
        ),
        fields=fields,
        capabilities=FormatCapabilities(
            supports_subaccount=Capability(CapabilityStatus.SUPPORTED),
            supports_department=Capability(
                CapabilityStatus.CONDITIONAL,
                "Depends on product grade.",
            ),
            supports_tax_category=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_amount=Capability(CapabilityStatus.SUPPORTED),
            supports_invoice_classification=Capability(CapabilityStatus.CONDITIONAL),
            supports_description=Capability(CapabilityStatus.SUPPORTED),
            supports_voucher_number=Capability(CapabilityStatus.SUPPORTED),
            supports_compound_journal=Capability(CapabilityStatus.SUPPORTED),
            supports_multiple_debit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_multiple_credit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_header=Capability(CapabilityStatus.UNKNOWN),
            accepted_extensions=(".txt", ".csv"),
            encoding_candidates=("cp932", "utf-8", "utf-8-sig"),
            delimiter=",",
            column_count_rules=(25,),
            maximum_field_lengths={
                field.semantic_field: field.max_length
                for field in fields
                if field.max_length is not None
                and field.semantic_field is not SemanticField.UNKNOWN
            },
            journal_grouping_strategy=JournalGroupingStrategy.IDENTIFIER_FLAG_SEQUENCE,
        ),
        delimiter=",",
        column_count=25,
        date_formats=("%Y%m%d", "%Y/%m/%d", "%Y/%-m/%-d", "wareki"),
        numeric_format="integer_yen",
        blank_representation="empty_field",
        notes="Not a verified input adapter profile.",
    )


def yayoi_next_documented_candidate_schema(
    column_count: int,
) -> SchemaDefinition:
    if column_count not in {25, 27}:
        raise ValueError("Yayoi Next documented candidates are 25 or 27 columns")
    return SchemaDefinition(
        identity=FormatIdentity(
            vendor="Yayoi",
            product="Yayoi Accounting Next",
            format_name=f"Yayoi Next Import Candidate {column_count}",
            direction=FormatDirection.INPUT,
            evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
            format_version=f"{column_count}-column",
            source_reference=YAYOI_NEXT_SOURCE,
            notes="Official documentation mentions 25 or 27 item structures; detailed field mapping is not finalized here.",
        ),
        fields=(),
        capabilities=FormatCapabilities(
            supports_subaccount=Capability(CapabilityStatus.SUPPORTED),
            supports_department=Capability(CapabilityStatus.UNKNOWN),
            supports_tax_category=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_amount=Capability(CapabilityStatus.UNKNOWN),
            supports_invoice_classification=Capability(CapabilityStatus.UNKNOWN),
            supports_description=Capability(CapabilityStatus.SUPPORTED),
            supports_voucher_number=Capability(CapabilityStatus.CONDITIONAL),
            supports_compound_journal=Capability(CapabilityStatus.SUPPORTED),
            supports_multiple_debit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_multiple_credit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_header=Capability(CapabilityStatus.UNKNOWN),
            accepted_extensions=(".csv", ".txt"),
            encoding_candidates=("cp932", "utf-8", "utf-8-sig"),
            delimiter=",",
            column_count_rules=(column_count,),
            journal_grouping_strategy=JournalGroupingStrategy.IDENTIFIER_FLAG_SEQUENCE,
        ),
        delimiter=",",
        column_count=column_count,
        notes="Candidate only. Do not auto-select as formal YayoiInputAdapter profile.",
    )


def jdl_ibex_cashbook_35_5_observed_schema_definition() -> SchemaDefinition:
    observed = jdl_ibex_cashbook_35_5_observed_schema()
    fields = tuple(
        FieldDefinition(
            field_id=f"jdl_cashbook_35_5_col_{index:02d}",
            display_name=name,
            semantic_field=_JDL_OBSERVED_FIELDS.get(name, SemanticField.UNKNOWN),
            column_position=index,
            required=False,
            data_type=_jdl_data_type(name),
            blank_policy=BlankPolicy.UNKNOWN,
            evidence=EvidenceLevel.OBSERVED,
            source=JDL_OBSERVED_SOURCE,
        )
        for index, name in enumerate(observed.observed_header, start=1)
    )
    return SchemaDefinition(
        identity=FormatIdentity(
            vendor="JDL",
            product="JDL IBEX 出納帳",
            format_name="observed_30_column_csv",
            direction=FormatDirection.OUTPUT,
            evidence_level=EvidenceLevel.OBSERVED,
            major_version="35",
            minor_version="5",
            source_reference=JDL_OBSERVED_SOURCE,
            notes="Observed from real CSV. Not verified by successful import.",
        ),
        fields=fields,
        capabilities=FormatCapabilities(
            supports_subaccount=Capability(CapabilityStatus.SUPPORTED),
            supports_department=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_category=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_amount=Capability(CapabilityStatus.SUPPORTED),
            supports_invoice_classification=Capability(CapabilityStatus.UNKNOWN),
            supports_description=Capability(CapabilityStatus.SUPPORTED),
            supports_voucher_number=Capability(CapabilityStatus.SUPPORTED),
            supports_compound_journal=Capability(CapabilityStatus.CONDITIONAL),
            supports_multiple_debit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_multiple_credit_lines=Capability(CapabilityStatus.CONDITIONAL),
            supports_header=Capability(CapabilityStatus.SUPPORTED),
            accepted_extensions=(".csv",),
            encoding_candidates=("cp932",),
            delimiter=",",
            column_count_rules=(30,),
            journal_grouping_strategy=JournalGroupingStrategy.IDENTIFIER_FLAG_SEQUENCE,
        ),
        delimiter=",",
        encoding="cp932",
        has_header=CapabilityStatus.SUPPORTED,
        column_count=30,
        date_formats=("UNKNOWN_OBSERVED",),
        numeric_format="integer_yen_observed",
        blank_representation="UNKNOWN",
        notes="Observed schema remains separate from formal JDL FormatProfile.",
    )


def default_format_schemas() -> tuple[SchemaDefinition, ...]:
    return (
        yayoi_desktop_import_25_documented_schema(),
        yayoi_next_documented_candidate_schema(25),
        yayoi_next_documented_candidate_schema(27),
        jdl_ibex_cashbook_35_5_observed_schema_definition(),
    )


def _data_type(value: str | None) -> FieldDataType:
    return {
        "文字": FieldDataType.TEXT,
        "数字": FieldDataType.NUMBER,
        "金額": FieldDataType.DECIMAL,
        "日付": FieldDataType.DATE,
    }.get(value or "", FieldDataType.UNKNOWN)


def _jdl_data_type(name: str) -> FieldDataType:
    if "日付" in name:
        return FieldDataType.DATE
    if "金額" in name or "消費税" in name:
        return FieldDataType.DECIMAL
    return FieldDataType.TEXT

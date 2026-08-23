from __future__ import annotations

from .models import ObservedJdlSchema


JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER: tuple[str, ...] = (
    "//識別フラグ",
    "伝番",
    "日付",
    "借方科目",
    "借方科目名称",
    "借方科目正式名称",
    "借方補助",
    "借方補助名称",
    "借方課区",
    "借方税区",
    "借方税入力方法",
    "借方金額",
    "借方消費税",
    "貸方科目",
    "貸方科目名称",
    "貸方科目正式名称",
    "貸方補助",
    "貸方補助名称",
    "貸方課区",
    "貸方税区",
    "貸方税入力方法",
    "貸方金額",
    "貸方消費税",
    "摘要",
    "借方取引科目",
    "貸方取引科目",
    "借方部門コード",
    "借方部門名称",
    "貸方部門コード",
    "貸方部門名称",
)


def jdl_ibex_cashbook_35_5_observed_schema() -> ObservedJdlSchema:
    return ObservedJdlSchema(
        product="JDL IBEX 出納帳",
        observed_version="35.5",
        encoding="cp932",
        has_bom=False,
        line_ending="CRLF",
        journal_column_count=30,
        observed_header=JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER,
        journal_count=0,
        field_names={
            "identifier_flag": "//識別フラグ",
            "voucher_number": "伝番",
            "date": "日付",
            "debit_account": "借方科目名称",
            "debit_account_code": "借方科目",
            "debit_sub_account": "借方補助名称",
            "debit_sub_account_code": "借方補助",
            "debit_amount": "借方金額",
            "credit_account": "貸方科目名称",
            "credit_account_code": "貸方科目",
            "credit_sub_account": "貸方補助名称",
            "credit_sub_account_code": "貸方補助",
            "credit_amount": "貸方金額",
        },
        observed_identifier_flags=("1000", "1100", "1110", "1101", "1111"),
        observed_behavior=("diagnostic_message_follows_journal_record",),
        is_formal_format_profile=False,
    )

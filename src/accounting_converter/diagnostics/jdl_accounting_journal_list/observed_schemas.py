from __future__ import annotations

from dataclasses import dataclass, field


JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER: tuple[str, ...] = (
    "番号",
    "伝番",
    "日付",
    "借方科目",
    "",
    "借方補助",
    "",
    "貸方科目",
    "",
    "貸方補助",
    "",
    "金額",
    "摘要",
    "課区",
    "",
    "税区",
    "",
    "別記区分",
    "資金",
    "",
    "",
)


@dataclass(frozen=True)
class ObservedJdlAccountingJournalListSchema:
    vendor: str = "JDL"
    product: str = "JDL Accounting"
    format_name: str = "Journal List Export"
    evidence_level: str = "OBSERVED"
    observed_version: str = "UNKNOWN"
    encoding: str = "cp932"
    has_bom: bool = False
    line_ending: str = "CRLF"
    column_count: int = 21
    observed_header: tuple[str, ...] = JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER
    is_formal_format_profile: bool = False
    purpose: str = "READ_ONLY_POST_IMPORT_VERIFICATION_CANDIDATE"
    field_names: dict[str, str] = field(
        default_factory=lambda: {
            "row_number": "番号",
            "voucher_number": "伝番",
            "date": "日付",
            "debit_account": "借方科目",
            "debit_sub_account": "借方補助",
            "credit_account": "貸方科目",
            "credit_sub_account": "貸方補助",
            "amount": "金額",
            "description": "摘要",
            "tax_scope": "課区",
            "tax_category": "税区",
        }
    )

    @property
    def identity_label(self) -> str:
        return (
            f"{self.vendor} / {self.product} / {self.format_name} / "
            f"{self.evidence_level} / version={self.observed_version}"
        )

    def column_index_for(self, field: str) -> int | None:
        header_name = self.field_names.get(field)
        if header_name is None:
            return None
        try:
            return self.observed_header.index(header_name)
        except ValueError:
            return None


def jdl_accounting_journal_list_observed_schema() -> (
    ObservedJdlAccountingJournalListSchema
):
    return ObservedJdlAccountingJournalListSchema()

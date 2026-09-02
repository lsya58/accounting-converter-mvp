from __future__ import annotations

from datetime import date
from decimal import Decimal

from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)


def canonical_journal_entries() -> tuple[JournalEntry, ...]:
    return (
        _entry("C-001", "simple journal", [("DEBIT", "現金", "1000"), ("CREDIT", "売上高", "1000")]),
        _entry("C-002", 'description with comma, and "quote"', [("DEBIT", "現金", "1200"), ("CREDIT", "売上高", "1200")]),
        _entry("C-003", "subaccount", [("DEBIT", "売掛金", "3000", "架空補助"), ("CREDIT", "売上高", "3000")]),
        _entry("C-004", "department", [("DEBIT", "消耗品費", "500", None, "架空部門"), ("CREDIT", "現金", "500")]),
        _entry("C-005", "tax", [("DEBIT", "消耗品費", "1100", None, None, "課税仕入10%", "100"), ("CREDIT", "現金", "1100")]),
        _entry("C-006", "invoice classification", [("DEBIT", "仕入高", "2200", None, None, "課税仕入10%", "200", "qualified_invoice"), ("CREDIT", "現金", "2200")]),
        _entry("C-007", "compound debit", [("DEBIT", "旅費交通費", "700"), ("DEBIT", "消耗品費", "300"), ("CREDIT", "現金", "1000")]),
        _entry("C-008", "compound credit", [("DEBIT", "現金", "1000"), ("CREDIT", "売上高", "600"), ("CREDIT", "雑収入", "400")]),
        _entry("C-009", "many to many compound", [("DEBIT", "現金", "600"), ("DEBIT", "売掛金", "400"), ("CREDIT", "売上高", "700"), ("CREDIT", "雑収入", "300")]),
        _entry("C-010", "quoted comma", [("DEBIT", "現金", "100"), ("CREDIT", "売上高", "100")]),
        _entry("C-011", "全角テキスト", [("DEBIT", "現金", "100"), ("CREDIT", "売上高", "100")]),
        _entry("C-012", "zero amount invalid case", [("DEBIT", "現金", "0"), ("CREDIT", "売上高", "0")]),
        _entry("C-013", "negative invalid amount candidate", [("DEBIT", "現金", "-100"), ("CREDIT", "売上高", "-100")]),
        _entry("C-014", "unknown master", [("DEBIT", "未知架空科目", "100"), ("CREDIT", "売上高", "100")]),
        _entry("C-015", "maximum length boundary xxxxxxxxxxxxxxxxxxxx", [("DEBIT", "現金", "100"), ("CREDIT", "売上高", "100")]),
        _entry("C-016-A", "duplicate content", [("DEBIT", "現金", "100"), ("CREDIT", "売上高", "100")]),
        _entry("C-016-B", "duplicate content", [("DEBIT", "現金", "100"), ("CREDIT", "売上高", "100")]),
    )


def _entry(
    entry_id: str,
    description: str,
    line_specs: list[tuple[str, str, str, str | None, str | None, str | None, str | None, str | None]],
) -> JournalEntry:
    source = SourceReference("canonical_synthetic", row_number=1, source_journal_id=entry_id)
    lines: list[JournalLine] = []
    for index, spec in enumerate(line_specs, start=1):
        side_name, account, amount, *rest = spec
        sub_account = rest[0] if len(rest) > 0 else None
        department = rest[1] if len(rest) > 1 else None
        tax_category = rest[2] if len(rest) > 2 else None
        tax_amount = rest[3] if len(rest) > 3 else None
        invoice_classification = rest[4] if len(rest) > 4 else None
        lines.append(
            JournalLine(
                side=Side(side_name),
                account=account,
                sub_account=sub_account,
                department=department,
                amount=Decimal(amount),
                tax_info=TaxInfo(
                    category=tax_category,
                    tax_amount=Decimal(tax_amount) if tax_amount is not None else None,
                    invoice_classification=invoice_classification,
                ),
                source_reference=SourceReference(
                    "canonical_synthetic",
                    row_number=index,
                    source_journal_id=entry_id,
                ),
            )
        )
    return JournalEntry(
        id=entry_id,
        source_reference=source,
        date=date(2026, 1, 31),
        description=description,
        lines=lines,
    )

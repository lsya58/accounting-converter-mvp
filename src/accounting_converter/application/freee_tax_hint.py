"""What a freee 税区分 NAME suggests (a hint for the Human, never a mapping).

Moved unchanged out of application.freee_diagnosis (which re-exports it) so that
application.freee_tax_lines can use it without a circular import.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FreeeTaxHint:
    """What the freee tax NAME suggests. A hint for the Human, never a mapping."""
    kind: str  # SALES_TAXABLE / PURCHASE_TAXABLE / NON_TAXABLE_SALES / NON_TAXABLE_PURCHASE / EXPORT_SALES / OUT_OF_SCOPE / UNKNOWN
    rate: str | None = None  # "10" / "8"
    reduced: bool = False
    deduction_ratio: str | None = None  # 経過措置 "80" / "50" / "30" ...
    allocation: str | None = None  # 個別対応: 課税売上対応 / 共通対応 / 非課税売上対応

    @property
    def taxed(self) -> bool:
        return self.kind in {"SALES_TAXABLE", "PURCHASE_TAXABLE"}


_RATE = re.compile(r"(10|8)%")
_DEDUCTION = re.compile(r"控(\d{2})")


def tax_hint(name: str | None) -> FreeeTaxHint:
    if not name:
        return FreeeTaxHint("OUT_OF_SCOPE")
    rate_match = _RATE.search(name)
    rate = rate_match.group(1) if rate_match else None
    reduced = "軽" in name
    deduction = _DEDUCTION.search(name)
    if name in {"対象外", "不課税"}:
        return FreeeTaxHint("OUT_OF_SCOPE")
    if name.startswith("輸出"):
        return FreeeTaxHint("EXPORT_SALES")
    if name.startswith("非課売上"):
        return FreeeTaxHint("NON_TAXABLE_SALES")
    if name.startswith("非課仕入"):
        return FreeeTaxHint("NON_TAXABLE_PURCHASE")
    if name.startswith("課税売上"):
        return FreeeTaxHint("SALES_TAXABLE", rate, reduced)
    for prefix, allocation in (("課対仕入", "課税売上対応"), ("共対仕入", "共通対応"), ("非対仕入", "非課税売上対応")):
        if name.startswith(prefix):
            return FreeeTaxHint(
                "PURCHASE_TAXABLE", rate, reduced, deduction.group(1) if deduction else None,
                allocation if prefix != "課対仕入" else None,
            )
    return FreeeTaxHint("UNKNOWN", rate, reduced)

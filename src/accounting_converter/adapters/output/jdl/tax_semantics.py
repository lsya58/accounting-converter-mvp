"""JDL target tax semantics for the 課税・税抜・原則課税・一括比例配分 Context.

Real JDL Evidence is about what JDL receives (課区 / 税区 / 税入力方法 / tax
amount rule), not about which source tax name was mapped to it. Sources keep
their own tax names; a Human-confirmed mapping resolves each one to one of
these semantics, and Evidence is looked up by the semantic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JdlTaxSemantic(str, Enum):
    NO_TAX = "JDL_NO_TAX"
    PURCHASE_10_INTERNAL = "JDL_PURCHASE_10_INTERNAL"
    SALES_10_EXTERNAL = "JDL_SALES_10_EXTERNAL"
    NON_TAXABLE_PURCHASE = "JDL_NON_TAXABLE_PURCHASE"
    NON_TAXABLE_SALES = "JDL_NON_TAXABLE_SALES"
    # Seen on the real JDL screen (self-export, 2026-11-05) on the Buddies test
    # copy and round-tripped by synthetic probe. They are valid only inside the
    # scope of that Evidence (see scoped_evidence); never for the Tax Contexts
    # of the MF / ACT Evidence.
    EXPORT_SALES = "JDL_EXPORT_SALES"
    PURCHASE_REDUCED_8_INTERNAL = "JDL_PURCHASE_REDUCED_8_INTERNAL"
    PURCHASE_10_TRANSITIONAL_80_INTERNAL = "JDL_PURCHASE_10_TRANSITIONAL_80_INTERNAL"


@dataclass(frozen=True)
class JdlTaxLiteral:
    scope: str
    category: str
    input_method: str
    # True: explicit 10% tax amount, floor rounding (verified 1100 -> 100 and
    # 364458 -> 33132). False: tax amount left blank.
    explicit_floor_tax: bool


JDL_TAX_LITERALS: dict[JdlTaxSemantic, JdlTaxLiteral] = {
    JdlTaxSemantic.NO_TAX: JdlTaxLiteral("", "", "", False),
    JdlTaxSemantic.PURCHASE_10_INTERNAL: JdlTaxLiteral("仕　入", "10%", "内税", True),
    JdlTaxSemantic.SALES_10_EXTERNAL: JdlTaxLiteral("売　上", "10%", "外税", True),
    JdlTaxSemantic.NON_TAXABLE_PURCHASE: JdlTaxLiteral("非仕入", "", "", False),
    JdlTaxSemantic.NON_TAXABLE_SALES: JdlTaxLiteral("非売上", "", "", False),
    # 課区のみ（税区・税入力方法・消費税は空欄）。再Exportで消費税は0。
    JdlTaxSemantic.EXPORT_SALES: JdlTaxLiteral("輸出売", "", "", False),
    # 課区「仕　入」・税区「軽減8%」・内税。明示税額は 金額×8/108 の整数だけ確認済み。
    JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL: JdlTaxLiteral("仕　入", "軽減8%", "内税", False),
    # 課区「仕　入」・税区「10%免80」・内税。明示税額は 10%税額の80%（整数）だけ確認済み。
    JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL: JdlTaxLiteral("仕　入", "10%免80", "内税", False),
}

# A confirmed mapping stores the JDL 税区 as its target value and the 課区 as
# metadata["jdl_tax_scope"]; that pair identifies the semantic.
_BY_TARGET = {
    (literal.category, literal.scope): semantic
    for semantic, literal in JDL_TAX_LITERALS.items()
}


def semantic_for_target(category: str | None, scope: str | None) -> JdlTaxSemantic | None:
    return _BY_TARGET.get((category or "", scope or ""))

"""Read-only facts of the SOURCE journal lines whose tax treatment needs a human look ("税区分の確認が必要").

Facts only. This module never decides that a line is wrong, never changes a tax category, never creates READY and
carries no approval state. It shows, per source line, exactly what Yayoi recorded (so the tax accountant can compare it
with the real transaction) and, in words, what JDL can and cannot keep. Today the only trigger is Yayoi 仕入税額控除
「控除不可」 (a fact of the source line, not a judgement that it was mistyped).

Data-model separation for a future correction flow (NOT implemented here; see docs/development/yayoi_tax_review_design.md):
  1. SourceTaxFacts   - this module's `TaxReviewLine`: immutable copy of the Yayoi line.
  2. Reviewed transaction / correction candidate / approved correction instruction / conversion result / loss record /
     Evidence+approval history: separate records that must reference a line by (journal id, source row), never overwrite it.
"""
from __future__ import annotations

from dataclasses import dataclass

from accounting_converter.application.noncredit_observations import is_noncredit_identity

REASON_NONCREDIT = "NONCREDIT"

# What the JDL side offers for this source value. Wording follows the recorded real-JDL Evidence only.
JDL_COUNTERPART_NONCREDIT = (
    "JDLに「控除不可」に当たる税区分はありません。実機で確認済みなのは、税区を空欄にした「非仕入」"
    "（CSV往復・消費税集計で課税仕入に入らない）だけで、申告上同じ扱いかは未確認です。"
)
NOT_KEPT_IN_JDL_NONCREDIT = (
    "非仕入にした場合、10%／軽減8%の別・区分記載・「控除不可」の指定はJDL側に残りません。"
    "元の値は元CSVと監査記録（外部）にのみ残ります。"
)
CHECK_POINTS = (
    "取引の相手（事業者か個人か・登録の有無）と、請求書・帳簿の保存状況",
    "海外の販売者・輸入品の場合: 商品の所在地、輸入通関・輸入申告者、輸入消費税の有無（元データだけでは判定できません）",
    "「国外取引（不課税）」「非課税取引」「輸入貨物への課税」は別の概念です。税理士の「非課税仕入」という表現を、"
    "根拠の確認なしにJDLの非課税区分へ対応づけません",
)
STATE_TEXT = "入力内容の確認が必要です（誤りと確定したわけではありません）。税理士の判断待ち。承認記録がない限り変換しません。"


@dataclass(frozen=True)
class TaxReviewLine:
    journal_id: str
    short_id: str
    date: str
    source_row: int
    yayoi_journal_number: str
    side: str
    account: str
    sub_account: str
    description: str
    amount_tax_included: str
    tax_identity: str          # exactly as Yayoi wrote it
    rate: str
    tax_calculation: str
    invoice_class: str
    purchase_credit: str
    tax_amount: str
    reason: str
    jdl_counterpart: str
    not_kept_in_jdl: str
    state: str = STATE_TEXT


def rate_text(identity: str) -> str:
    """税率 as printed in the Yayoi identity's first segment (e.g. 課対仕入8%（軽） -> 軽減8%). No inference."""
    head = (identity or "").split("｜", 1)[0]
    if "8%（軽）" in head:
        return "軽減8%"
    for rate in ("10%", "8%"):
        if rate in head:
            return rate
    return "—"


def other_identities(entry) -> tuple[tuple[str, int], ...]:
    """(tax identity, line count) of the lines that are NOT flagged, for context only."""
    counts: dict[str, int] = {}
    for line in getattr(entry, "lines", ()) or ():
        info = line.tax_info
        identity = (info.category if info is not None else None) or "（税区分なし）"
        if info is not None and is_noncredit_identity(info.category or ""):
            continue
        counts[identity] = counts.get(identity, 0) + 1
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _s(value) -> str:
    return "" if value is None else str(value)


def extract(entry, journal_id: str) -> tuple[TaxReviewLine, ...]:
    """Source lines of one journal that need a tax-category look. Empty when there are none."""
    found = []
    for line in getattr(entry, "lines", ()) or ():
        info = line.tax_info
        if info is None or not is_noncredit_identity(info.category or ""):
            continue
        meta = getattr(line, "metadata", None) or {}
        info_meta = getattr(info, "metadata", None) or {}
        row = meta.get("journal_row_number", getattr(getattr(line, "source_reference", None), "row_number", 0))
        found.append(TaxReviewLine(
            journal_id=journal_id, short_id=journal_id.rsplit(":", 1)[-1], date=_s(getattr(entry, "date", "")),
            source_row=int(row) if str(row).isdigit() else 0, yayoi_journal_number=_s(meta.get("yayoi_journal_number")),
            side=_s(getattr(line.side, "value", line.side)), account=_s(getattr(line, "account", "")), sub_account=_s(getattr(line, "sub_account", "")),
            description=_s(meta.get("journal_row_description")), amount_tax_included=_s(line.amount),
            tax_identity=_s(info.category), rate=rate_text(_s(info.category)), tax_calculation=_s(info_meta.get("yayoi_tax_calculation")),
            invoice_class=_s(getattr(info, "invoice_classification", None) or info_meta.get("yayoi_invoice_class")),
            purchase_credit=_s(info_meta.get("yayoi_purchase_credit")), tax_amount=_s(getattr(info, "tax_amount", None)),
            reason=REASON_NONCREDIT, jdl_counterpart=JDL_COUNTERPART_NONCREDIT, not_kept_in_jdl=NOT_KEPT_IN_JDL_NONCREDIT))
    return tuple(found)

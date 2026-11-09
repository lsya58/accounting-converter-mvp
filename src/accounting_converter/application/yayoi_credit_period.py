"""免税事業者等からの課税仕入れ（経過措置）の控除割合と取引日の整合チェック。

国税庁「インボイス制度の見直し」（令和8年度税制改正）の公表内容に基づく期間表:
  80%: 2023-10-01〜2026-09-30 / 70%: 2026-10-01〜2028-09-30 / 50%: 2028-10-01〜2030-09-30 /
  30%: 2030-10-01〜2031-09-30 / それ以降 控除不可。

役割は「検出して止める」ことだけ。割合の書き換え・JDL税区の推定・自動補正は行わない。
弥生の「仕入税額控除」欄の割合が取引日の期間と食い違う行は、確認済みの税区分対応があっても変換しない
（JDLに「10%免80」しか確認されておらず、70%以降の税区はJDL実機で未確認のため）。
上限額（同一の相手方からの課税仕入れ合計1億円）など、1行では判定できない要件はここでは判定しない。
"""
from __future__ import annotations

import re
from datetime import date

from accounting_converter.domain.journal import JournalEntry

PERIOD_BLOCKER = "HUMAN:TRANSITIONAL_CREDIT_PERIOD"
PERIOD_MESSAGE = (
    "免税事業者等からの仕入れの控除割合（80%・70%など）が、取引日の期間と合っていない仕訳があります。"
    "取引日が2026年10月1日以降なら70%、それ以前なら80%が対象です（国税庁の公表内容）。"
    "税理士が確認するまで変換しません。"
)

# (開始日, 終了日, 割合)。終了日=Noneは期限なし。公表資料の「〇年〇月から〇年間」から機械的に算出。
PERIODS: tuple[tuple[date, date | None, int], ...] = (
    (date(2023, 10, 1), date(2026, 9, 30), 80),
    (date(2026, 10, 1), date(2028, 9, 30), 70),
    (date(2028, 10, 1), date(2030, 9, 30), 50),
    (date(2030, 10, 1), date(2031, 9, 30), 30),
)
_TRANSITIONAL = re.compile(r"(\d{1,3})%経過措置$")


def applicable_ratio(on: date) -> int | None:
    """取引日に適用される経過措置割合。経過措置の期間外ならNone。"""
    for start, end, ratio in PERIODS:
        if on >= start and (end is None or on <= end):
            return ratio
    return None


def transitional_ratio(purchase_credit: str) -> int | None:
    """弥生の仕入税額控除欄から経過措置割合を取り出す（「80%経過措置」→80）。他の値はNone。"""
    match = _TRANSITIONAL.fullmatch(purchase_credit or "")
    return int(match.group(1)) if match else None


def period_mismatch(entry: JournalEntry) -> bool:
    """経過措置割合の行があり、その割合が取引日に適用される割合と異なる。"""
    for line in entry.lines:
        if line.tax_info is None:
            continue
        ratio = transitional_ratio(str(line.tax_info.metadata.get("yayoi_purchase_credit", "")))
        if ratio is not None and ratio != applicable_ratio(entry.date):
            return True
    return False

"""What real JDL showed for Yayoi 控除不可 (課対仕入｜区分記載｜控除不可). Observations, not conversion Evidence.

Company A (Buddies), JDL IBEX 出納帳 35.5, 原則課税・一括比例配分・税抜, probe day 2026-07-05
(private `noncredit_tax_probe_20261107/`, re-export sha256 184b1d11…, judged with `yayoi_gap_probe_check`).

Technical facts (CSV import + same-day re-export):
  - 課区「非仕入」with 税区「10%」or「軽減8%」is rejected at Import ("借方税区が不正です"). Neither file's
    control journal was in the re-export either: nothing of those two files was registered.
  - 課区「仕　入」・税区「10%」/「軽減8%」・内税 with an explicit 消費税 of 0 is imported, but JDL replaces the 0
    with the computed tax (55,000 -> 5,000; 54,000 -> 4,000): the line becomes an ordinary creditable 課税仕入.
  - 課区「非仕入」with blank 税区 / 入力 / 税額 and 課区 blank (対象外) round-trip unchanged on 8471 (known writings).

JDL 消費税集計表（原則課税, 令和8年7月度(決算), 税抜処理, 仕入は税込額), before / after importing file A only
(PDF sha256 50c090d0… / 17ac691b…): 課税仕入 10% 0 -> 11,000 / tax 0 -> 1,000, 軽減8% 0 -> 10,800 / 800,
課税仕入税額等合計 0 -> 1,800: exactly the two controls. The 非仕入 lines (22,000 + 21,600) and the 対象外 line
(33,000) entered none of them. 課税売上割合 0.00% (no sales), so the 一括比例 credit (0 -> 0) does not discriminate
by itself; the report has no 非課税仕入 field.

NOT established: whether the tax accountant accepts 非仕入 as equivalent to Yayoi 控除不可 for the tax return.
So 控除不可 has no ordinary candidate; only the signed, company-scoped approval of noncredit_approval converts it.
"""
from __future__ import annotations

NONTAX_PURCHASE_WITH_RATE_REJECTED = (
    "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-NP-R10-IMPORT-REJECTED-001",
    "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-NP-R8-IMPORT-REJECTED-001",
)
ZERO_TAX_ON_TAXABLE_PURCHASE_RECOMPUTED = (
    "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-P10-TAX0-RECOMPUTED-001",
    "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-R8-TAX0-RECOMPUTED-001",
)
NONTAX_PURCHASE_BLANK_ROUNDTRIP_MEANING_UNVERIFIED = "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-NP-BLANK-ROUNDTRIP-001"
NONTAX_PURCHASE_BLANK_NOT_IN_TAXABLE_PURCHASE = "OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-NP-BLANK-TAXSUMMARY-001"


def is_noncredit_identity(identity: str) -> bool:
    """Yayoi tax identity whose purchase credit is 控除不可 (e.g. 課対仕入10%｜区分記載｜控除不可)."""
    return identity.rsplit("｜", 1)[-1] == "控除不可"


NONCREDIT_REASON = (
    "控除不可は、まだJDLでの書き方を決められません。JDL実機では、非仕入に税区（10%・軽減8%）を付けると取込拒否、"
    "課税仕入で税額0を書くとJDLが税額を計算し直して通常の控除対象になりました。"
    "税区を空欄にした非仕入はCSVで保たれ、消費税集計でも課税仕入・税額に入りませんでした。"
    "申告上同じ扱いかの税理士確認が済んでいません。"
)

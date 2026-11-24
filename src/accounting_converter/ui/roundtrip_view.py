"""What the JDL round-trip card shows (Qt-free). Built only from application.jdl_roundtrip_review results.

Every count is the existing check's own number. The difference details are the comparator's first 20
(`FIRST_FAILURES_LIMIT`): they are labelled as such and never presented as totals.
"""
from __future__ import annotations

from accounting_converter.application import jdl_roundtrip_review as rr

# state -> (MessageBar level, StatusBadge key, badge words, headline)
STATE_TEXT = {
    rr.PASS: ("success", "RECONCILED", "PASS",
              "PASS：JDLから再出力した内容は、出力CSVと元データに一致しました（既知の正規化だけ）。"),
    rr.PASS_WITH_ACCEPTED_NORMALIZATION: (
        "success", "RECONCILED", "PASS（許容の記録あり）",
        "PASS（許容の記録あり）：Evidenceのある情報欠落について、検証済みの許容記録があります。"),
    rr.PENDING: ("warning", "PENDING", "PENDING",
                 "PENDING：説明できない差分はありませんが、JDLで失われた情報（摘要末尾の空白など）の許容判断が"
                 "記録されていません。照合は合格ではありません。この画面では許容・承認できません。"),
    rr.FAIL: ("error", "BLOCK", "FAIL", "FAIL：説明できない差分があります。JDLへの取込結果は一致していません。"),
    rr.READ_ERROR: ("error", "ERROR", "読取エラー",
                    "読取エラー：ファイルを読み取れないか比較できなかったため、照合できませんでした。合格ではありません。"),
    rr.NOT_RUN: ("warning", "NOT_STARTED", "未照合", "照合していません。"),
}

REASON_TEXT = {
    "COMPANY_SETTING_NOT_AVAILABLE": "会社設定を読み込めません（会社を選び直すか、設定を確認してください）。",
    "COMPANY_SETTING_MISMATCH": "選択中の会社と会社設定が一致しません。",
    "ROUTE_YAYOI_JOURNAL_REPORT_NOT_IN_PHASE_1": "弥生の仕訳日記帳（会社Aの形式）の照合は、この画面ではまだ使えません。",
    "ROUTE_COMPANY_NOT_IN_PHASE_1": "この照合は、JDLの実機Evidenceがある会社（会社B）だけが対象です。この会社ではまだ使えません。",
    "ROUTE_NOT_YAYOI_IMPORT_FORMAT": "この画面の照合は、弥生インポート形式の会社だけが対象です（MF・freeeなどは未対応）。",
    "FILE_NOT_FOUND:source": "元データが見つかりません。",
    "FILE_NOT_FOUND:candidate": "JDL向け出力CSVが見つかりません。",
    "FILE_NOT_FOUND:reexport": "JDL再出力CSVが見つかりません。",
    "FILE_NOT_READABLE": "ファイルを読み取れません。",
    "SAME_FILE_SELECTED_TWICE": "同じファイルが2か所で選ばれています。元データ・出力CSV・再出力は別のファイルを選んでください。",
    "REEXPORT_IDENTICAL_TO_CANDIDATE": "再出力CSVが出力CSVと同じ内容です。同じファイルの誤指定を防ぐため照合しません"
                                       "（JDLから再出力したCSVが偶然バイト単位で一致した場合も同じ扱いです。JDLを経由していないとは断定しません）。",
    "CHECK_RAISED": "照合の途中でファイルを読み取れませんでした（形式・文字コードを確認してください）。",
    "FILES_CHANGED_DURING_CHECK": "照合中にファイルが変更されました。結果は使えません。もう一度照合してください。",
    "REEXPORT_NOT_COMPARABLE": "再出力CSVをJDLの30列形式として読み取れません（文字コード・見出し行・列数を確認してください）。",
    "READY_ONLY_FILES_DO_NOT_MATCH": "READYのみ出力の記録（manifest・除外一覧・監査記録）が、この会社・元データ・出力CSVと一致しません。",
    "ACCEPTANCE_NOT_VERIFIED": "許容記録を確認できないため、合格として扱いません。",
    "NORMALIZATION_ACCEPTANCE_PENDING": "Evidenceのある情報欠落の許容判断が未記録です（税理士の判断。この画面では記録しません）。",
    "REEXPORT_NOT_COMPARED": "再出力との照合をしていません。",
    "INFORMATION_OUTSIDE_JDL_FAIL": "JDLに入らない情報の監査記録が、この元データ・出力CSVと一致しないか見つかりません。",
    "AUDIT_RECORD_NOT_FOUND_NEXT_TO_CSV": "監査記録（.audit.json）が出力CSVと同じフォルダにありません。CSVと一緒に保管してください。",
    "JDL_ROUNDTRIP_FAIL": "元データ・出力CSV・再出力のどこかに説明できない差分があります（下の件数を確認してください）。",
    "CLOSING_ROWS_FAIL": "決算整理（13月）の行が期待と一致しません。",
    "VERDICT_NOT_PASS": "照合が合格していません。",
    # Phase 2 (Money Forward pilot)
    "ROUTE_NOT_MONEYFORWARD": "Money Forwardの仕訳帳CSV（19列）の会社ではありません。",
    "PILOT_NOT_ENABLED": "Money Forwardの照合はパイロット用です。この環境では有効になっていません（既定は無効）。",
    "PILOT_FILE_INVALID": "パイロットの有効化設定を読み取れないため、照合は使えません。",
    "PILOT_COMPANY_NOT_LISTED": "この会社はMoney Forward照合のパイロット対象ではありません。",
    "PILOT_SETTING_CHANGED": "パイロットを有効にした後で会社設定（対応・JDL設定など）が変わっているため、照合できません。",
    "PERIOD_NOT_SELECTED": "対象の決算期を選んでください（出力CSVの日付からは決めません）。",
    "PERIOD_NOT_FISCAL_YEAR_END": "選んだ期末日が、この会社の決算日と一致しません。",
    "CANDIDATE_OUTSIDE_PERIOD": "出力CSVに、選んだ決算期の外の仕訳が含まれています。",
    "SOURCE_HAS_NO_JOURNALS_IN_PERIOD": "元データに、選んだ決算期の仕訳がありません。",
    "REGENERATION_NOT_READY": "選んだ決算期の元データを現在の会社設定で変換できません（READYになりません）。",
    "CANDIDATE_NOT_REPRODUCED": "出力CSVが、元データと現在の会社設定から作り直した内容と一致しません（期首・期末の仕訳の欠落、"
                                "別の元データ・会社・決算期のCSV、出力後の設定変更などが考えられます）。照合していません。",
    "REEXPORT_NOT_SELECTED": "再出力CSVが選ばれていないため、JDLとの往復は照合していません（出力CSVの再現だけ確認しました）。",
    "SETTING_CHANGED_DURING_CHECK": "照合中に会社設定が変更されました。結果は使えません。もう一度照合してください。",
}

CATEGORY_TEXT = {
    "MISSING_ROW": "欠落（再出力に行がない）", "EXTRA_ROW": "余分（重複を含む）", "AMOUNT": "金額差",
    "TAX_AMOUNT": "税額差", "ACCOUNT": "科目差", "SUBACCOUNT": "補助科目差", "TAX_CATEGORY": "税区分差",
    "DESCRIPTION": "摘要差", "DATE": "日付差", "VOUCHER": "伝票・識別", "DEPARTMENT": "部門差",
    "JOURNAL_GROUPING": "仕訳のまとまり", "OTHER": "その他の列",
}

GUIDANCE = (
    "出力CSVと監査記録（同じ名前＋.audit.json）は同じフォルダに置いたまま選んでください。",
    "再出力CSVは、JDLで出力CSVを取り込んだ後、同じ期間をJDLから書き出したものを選んでください。",
    "照合はファイルを読むだけで、元データ・出力CSV・再出力・会社設定は変更しません。",
)
GUIDANCE_MF = (
    "対象の決算期を選んでください。元データのうちその期の全仕訳を、現在の会社設定で作り直して出力CSVと比べます。",
    "出力CSVは、選んだ決算期の分だけを含むファイルを選んでください。",
    "再出力CSVは、JDLで出力CSVを取り込んだ後、同じ期間をJDLから書き出したものを選んでください（未選択なら再現の確認だけ）。",
    "照合はファイルを読むだけで、元データ・出力CSV・再出力・会社設定は変更しません。",
    "パイロットの有効化は税理士の承認ではありません。",
)
MF_PASS_TEXT = ("PASS：出力CSVは、選んだ元データと現在の会社設定から再現でき、JDL再出力CSVとデータが整合しました"
                "（既知の正規化だけ）。過去に使った設定や、JDLへの取込操作そのものの証明ではありません。")
JDL_ROUTE_NOTE = "できません（再出力CSVがJDLから書き出されたことは、このアプリでは確認できません）"
POSITION_NOTE = ("比較は行の順番どおりに行います。途中で1行ずれると、それ以降の行もすべて差分に見えます。"
                 "最初の差分の位置から確認してください。重複した行は「余分」に含まれ、区別していません。")


def headline(review: rr.RoundTripReview) -> tuple[str, str, str, str]:
    level, badge, words, text = STATE_TEXT.get(review.state, STATE_TEXT[rr.FAIL])
    if review.state == rr.PASS and review.regeneration:
        text = MF_PASS_TEXT
    return level, badge, words, text


def guidance(moneyforward: bool) -> tuple[str, ...]:
    return GUIDANCE_MF if moneyforward else GUIDANCE


def period_label(end) -> str:
    """'FY2026-05（2025-06-01〜2026-05-31）' for the fiscal year ending on `end` (a date)."""
    from accounting_converter.tools.mf_formal_output_by_period import period_bounds

    start, last = period_bounds(end)
    return f"FY{last:%Y-%m}（{start.isoformat()}〜{last.isoformat()}）"


def reason_lines(review: rr.RoundTripReview) -> tuple[str, ...]:
    lines = [REASON_TEXT.get(code, code) for code in review.reasons]
    if review.error_type:
        lines.append(f"（エラーの種類: {review.error_type}）")
    return tuple(dict.fromkeys(lines))


def _yes_no(value) -> str:
    return "一致" if value is True else "不一致" if value is False else "—"


def _pair(value) -> str:
    return " / ".join(f"{v:,}" for v in value) if isinstance(value, (list, tuple)) else "—"


def _mf_rows(review: rr.RoundTripReview) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if review.period:
        rows.append(("対象の決算期（画面で選択）", f"{review.period['start']}〜{review.period['end']}"))
    regen = review.regeneration
    if regen:
        rows.append(("元データ（対象期の仕訳 / 行）",
                     f"{regen.get('source_journals_in_period', 0):,} / {regen.get('source_physical_rows_in_period', 0):,}"))
        rows.append(("① 元データ→出力CSV：現在の会社設定で作り直した内容との一致",
                     "バイト単位で一致" if regen.get("byte_identical") else "一致しない（照合していません）"))
        if regen.get("candidate_journals_outside_period"):
            rows.append(("出力CSVのうち対象期の外の仕訳", f"{regen['candidate_journals_outside_period']:,}"))
    if review.reexport:
        rows.append(("② 出力CSV→再出力：データの整合性", "整合" if review.state == rr.PASS else "整合しない"))
    elif regen:
        rows.append(("② 出力CSV→再出力：データの整合性", "照合していません"))
    reference = review.evidence_reference
    rows.append(("③ 既存Evidenceとの一致（参考）",
                 f"{reference['evidence_id']}（元データ・決算期・出力CSV・再出力が記録と一致。会社設定は記録に含まれません）"
                 if reference else "記録と一致する結果はありません"))
    rows.append(("④ JDLを経由したことの独立した証明", JDL_ROUTE_NOTE))
    rows.append(("JDLに入らない情報", "MFは監査記録の対象外（保持できない情報がある仕訳は変換時に止めます）"))
    return rows


def count_rows(review: rr.RoundTripReview) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = _mf_rows(review) if (review.regeneration or review.period) else []
    roles = (("candidate", "出力CSV"),) if review.regeneration else (("source", "元データ"), ("candidate", "出力CSV"))
    for role, label in roles:
        item = review.counts.get(role)
        if isinstance(item, dict):
            rows.append((f"{label}（仕訳 / 行）", f"{item.get('journals', 0):,} / {item.get('physical_rows', 0):,}"))
    re = review.reexport
    if re:
        rows.append(("出力CSV / 再出力（仕訳）", _pair(re.get("journals"))))
        rows.append(("出力CSV / 再出力（行）", _pair(re.get("physical_rows"))))
    sv = review.source_vs_candidate
    if sv:
        lines = sv.get("lines_account_subaccount_amount_tax_date") or {}
        rows.append(("元データ→出力CSV：明細（日付・科目・補助・金額・税額）の欠落 / 余分",
                     f"{lines.get('missing', 0):,} / {lines.get('extra', 0):,}"))
        desc = sv.get("row_descriptions") or {}
        rows.append(("元データ→出力CSV：摘要の欠落 / 余分", f"{desc.get('missing', 0):,} / {desc.get('extra', 0):,}"))
        struct = sv.get("journal_structure") or {}
        rows.append(("元データ→出力CSV：仕訳の形の欠落 / 余分", f"{struct.get('missing', 0):,} / {struct.get('extra', 0):,}"))
        rows.append(("元データ→出力CSV：借方合計 / 貸方合計 / 税額合計",
                     " / ".join(_yes_no(sv.get(k)) for k in ("debit_total_equal", "credit_total_equal",
                                                              "tax_total_equal"))))
    if re:
        rows.append(("出力CSV→再出力：欠落した行（全件）", f"{re.get('missing_rows', 0):,}"))
        rows.append(("出力CSV→再出力：余分な行・重複を含む（全件）", f"{re.get('extra_rows', 0):,}"))
        if re.get("unexplained_differences") is not None:
            rows.append(("出力CSV→再出力：説明できない差分（全件）", f"{re['unexplained_differences']:,}"))
        rows.append(("出力CSV→再出力：既知の正規化（許容済みの形式差）", f"{re.get('canonical_normalizations', 0):,}"))
        rows.append(("出力CSV→再出力：Evidenceのある情報欠落（許容判断が必要）", f"{re.get('evidenced_information_loss', 0):,}"))
        match = re.get("content_match")
        if match:
            rows.append(("参考：同じ日の並び順を無視した比較で一致しない仕訳のまとまり", f"{match['unmatched_groups']:,}"))
    if review.date_ranges:
        for role, label in (("candidate", "出力CSVの期間"), ("reexport", "再出力の期間")):
            span = review.date_ranges.get(role)
            if span:
                rows.append((label, f"{span[0]}〜{span[1]}"))
    if review.closing_verdict:
        rows.append(("決算整理（13月）の行", "一致" if review.closing_verdict == "PASS" else "不一致"))
    if review.verdict_information_outside_jdl:
        rows.append(("JDLに入らない情報（監査記録）", {"PASS": "一致", "NOT_NEEDED": "対象なし"}.get(
            review.verdict_information_outside_jdl, "不一致・見つからない")))
    ts = review.trailing_space
    if ts.get("rows"):
        rows.append(("摘要末尾空白がJDLで削除された行（許容判断が必要）", f"{ts['rows']:,}"))
    return tuple(rows)


def failures_heading(review: rr.RoundTripReview) -> str:
    shown = len(review.first_failures)
    total = review.reexport.get("unexplained_differences") if review.reexport else None
    if not shown:
        return f"最初の{rr.FIRST_FAILURES_LIMIT}件の差分詳細：説明できない差分はありません。"
    total_text = f"全{total:,}件のうち" if isinstance(total, int) else "全件数は不明。"
    return f"最初の{rr.FIRST_FAILURES_LIMIT}件の差分詳細（{total_text}{shown}件を表示。これは全件の内訳ではありません）"


def failure_rows(review: rr.RoundTripReview) -> tuple[tuple[str, str, str], ...]:
    """(row, difference kind, column) of the comparator's first failures. No cell values."""
    return tuple((str(item.get("row") or "—"), CATEGORY_TEXT.get(item.get("category"), "その他の列"),
                  str(item.get("field") or "")) for item in review.first_failures)

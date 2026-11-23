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
POSITION_NOTE = ("比較は行の順番どおりに行います。途中で1行ずれると、それ以降の行もすべて差分に見えます。"
                 "最初の差分の位置から確認してください。重複した行は「余分」に含まれ、区別していません。")


def headline(review: rr.RoundTripReview) -> tuple[str, str, str, str]:
    level, badge, words, text = STATE_TEXT.get(review.state, STATE_TEXT[rr.FAIL])
    return level, badge, words, text


def reason_lines(review: rr.RoundTripReview) -> tuple[str, ...]:
    lines = [REASON_TEXT.get(code, code) for code in review.reasons]
    if review.error_type:
        lines.append(f"（エラーの種類: {review.error_type}）")
    return tuple(dict.fromkeys(lines))


def _yes_no(value) -> str:
    return "一致" if value is True else "不一致" if value is False else "—"


def _pair(value) -> str:
    return " / ".join(f"{v:,}" for v in value) if isinstance(value, (list, tuple)) else "—"


def count_rows(review: rr.RoundTripReview) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for role, label in (("source", "元データ"), ("candidate", "出力CSV")):
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

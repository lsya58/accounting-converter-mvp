"""ホーム画面の表示内容 (Phase 3A). Pure data: no Qt, no I/O, no decision of its own.

Everything shown comes from AppState (the existing pre-run check) and, for Yayoi, from the read-only
controller.home_yayoi_overview (the production diagnosis, the approval ledger, the READY-only run and its tracker).
Rules:
- the migration is "完了" only when an existing tracker's final reconciliation says MIGRATION_COMPLETE; anything
  else (no output, no tracker, a rejected output, an unreadable tracker) is "未完了" with the reason;
- Yayoi-only functions (税理士の判断・未移行の管理・READY-only) are shown as 対象外 for other formats;
- a count that is not known is "—" with the reason, never a guess; numbers keep every digit (桁区切りのみ).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from accounting_converter.ui.view_models import AppState, RecognizedFormat

# Navigation keys (also the page order and the Ctrl+1..6 shortcuts).
NAV_HOME, NAV_IMPORT, NAV_DIAGNOSIS, NAV_REVIEW, NAV_OUTPUT, NAV_SETTINGS = (
    "home", "import", "diagnosis", "review", "output", "settings")
NAV_ITEMS = (
    (NAV_HOME, "ホーム"), (NAV_IMPORT, "データ取込"), (NAV_DIAGNOSIS, "変換診断"),
    (NAV_REVIEW, "要確認"), (NAV_OUTPUT, "出力・照合"), (NAV_SETTINGS, "設定"),
)

FORMAT_LABELS = {
    RecognizedFormat.MONEYFORWARD: "Money Forward",
    RecognizedFormat.YAYOI: "弥生会計",
    RecognizedFormat.JDL: "JDL（JDL→JDL移行）",
    RecognizedFormat.UNKNOWN: "認識できない形式",
}


@dataclass(frozen=True)
class Metric:
    label: str
    value: str
    hint: str = ""
    tone: str = "neutral"       # ready / block / pending / neutral (components.MetricCard)


@dataclass(frozen=True)
class NextAction:
    text: str
    target: str | None = None   # a NAV_* key, or None when there is nothing to open
    button: str = ""            # the button text: says where it goes and why (unique on the page)
    priority: int = 9           # 1 = do first (see PRIORITY_LABELS)


# Why one thing comes before another: nothing can be judged before the input exists; saved settings change the
# diagnosis; the BLOCK reasons decide who acts; the accountant's decisions change READY; output comes last.
PRIORITY_LABELS = {
    1: "準備", 2: "設定の確認（変換前に必須）", 3: "変換できない仕訳の理由", 4: "税理士の判断",
    5: "出力", 6: "未移行の管理", 9: "",
}


@dataclass(frozen=True)
class HomePresentation:
    company_lines: tuple[str, ...]
    metrics: tuple[Metric, ...]
    migration: Metric
    next_actions: tuple[NextAction, ...]
    message: tuple[str, str] | None = None   # (level, text) for components.MessageBar
    yayoi: bool = False
    format_key: str = "NONE"
    # 要確認: two different things with different units. They may overlap (a journal can wait for both), so they are
    # never added together.
    review_settings: int = 0                 # settings waiting for a confirmation (件: 科目・補助・税区分の設定の数)
    review_journals: int | None = None       # journals needing the tax accountant's decision (仕訳); None = unknown
    review_breakdown: tuple[tuple[str, int], ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def _n(value: int) -> str:
    return f"{value:,}"


def selected_company(state: AppState):
    return next((c for c in state.companies if c.company_setting_id == state.selected_company_setting_id), None)


def source_format(state: AppState) -> RecognizedFormat:
    recognition = state.file_recognition
    return recognition.format if recognition is not None else RecognizedFormat.NONE


def is_yayoi(state: AppState) -> bool:
    return (source_format(state) is RecognizedFormat.YAYOI and state.selected_file is not None
            and state.selected_company_setting_id is not None)


def company_lines(state: AppState, tax_context_text: str) -> tuple[str, ...]:
    company = selected_company(state)
    recognition = state.file_recognition
    period = ("—（仕訳データ未選択）" if recognition is None else
              f"{recognition.period_start} 〜 {recognition.period_end}"
              if recognition.period_start and recognition.period_end else "—（読み取れませんでした）")
    return (
        f"会社: {company.display_name if company else '未選択'}",
        f"会社設定の入力元: {company.source_label if company else '—'}"
        + (f"（{company.status_label}）" if company and company.status_label else ""),
        f"仕訳データ: {state.selected_file.name if state.selected_file else '未選択'}",
        f"入力形式: {FORMAT_LABELS.get(source_format(state), '—')}",
        f"会計期間（仕訳データの日付範囲）: {period}",
        f"JDL環境: {state.jdl_environment_label}",
        f"科目一覧: {state.jdl_master_state}（最終更新日: {state.jdl_master_updated_at or '未確認'}）",
        tax_context_text,
    )


def pending_breakdown(state: AppState) -> tuple[tuple[str, int], ...]:
    """Settings waiting for a confirmation, by kind (unit: 件 = settings, not journals). Zero kinds are left out."""
    queue = state.review_work_queue
    return tuple((label, count) for label, count in (
        ("科目", state.pending_account_confirmations),
        ("補助科目", state.pending_subaccount_confirmations),
        ("税区分", state.pending_tax_confirmations),
        ("税区分（JDLでの確認待ち）", queue.tax_evidence_settings if queue else 0),
    ) if count)


def pending_text(breakdown) -> str:
    return "・".join(f"{label} {_n(count)}件" for label, count in breakdown)


def review_nav_text(settings: int, journals: int | None) -> tuple[str, str]:
    """(navigation label, accessible / tooltip description). The two counts are shown with their units, never summed."""
    parts = []
    if settings:
        parts.append(f"設定{_n(settings)}件")
    if journals:
        parts.append(f"判断{_n(journals)}仕訳")
    label = "要確認" + ("\n" + "・".join(parts) if parts else "")
    description = ("対応の確認: " + (f"{_n(settings)}件（科目・補助・税区分の設定の数）" if settings else "なし")
                   + "。税理士の判断: " + (f"{_n(journals)}仕訳（仕訳の数）" if journals else
                                          "なし" if journals == 0 else "未診断")
                   + "。単位が違い、同じ仕訳が両方に関わることがあるため合計していません。")
    return label, description


def _migration(yayoi: dict | None) -> Metric:
    if yayoi is None:
        return Metric("移行全体", "未完了", "診断が終わるまで判定しません", "block")
    if yayoi.get("verdict") == "MIGRATION_COMPLETE":
        return Metric("移行全体", "完了", "管理表の最終判定が「移行完了」です", "ready")
    state = yayoi.get("run_state")
    reason = {
        None: ("READY-only出力が見つかっていません" if not yayoi.get("runs_found")
               else "READY-only出力が複数あります（未移行の管理で1つ選んでください）"),
        "NO_TRACKER": "READY-only出力はあります（管理表は未作成）",
        "TRACKED": "管理表で管理中（最終判定は未完了）",
        "REJECTED": "READY-only出力が検証に失敗しました",
        "TRACKER_MISMATCH": "管理表が出力と対応しません（使っていません）",
        "TRACKER_INVALID": "管理表を読めません",
    }.get(state, "状態を確認できません")
    if yayoi.get("blocked"):
        reason = f"未移行 {_n(yayoi['blocked'])}仕訳。" + reason
    unused = [run for run in yayoi.get("runs") or () if not run.get("usable")]
    if unused:
        reason += f"（旧い・使えない出力 {len(unused)}件は使いません）"
    return Metric("移行全体", "未完了", reason, "block")


RUN_COLUMNS = ("出力ファイル", "仕訳", "行", "作成日時", "出力のSHA-256", "現在の正式診断との照合", "実機での確認", "管理表")
RUN_STATE_TEXT = {
    "NO_TRACKER": "✓ 一致（検証PASS）", "TRACKED": "✓ 一致（検証PASS）",
    "TRACKER_MISMATCH": "✓ 一致（検証PASS）", "TRACKER_INVALID": "✓ 一致（検証PASS）",
    "OUTDATED": "‖ 旧い出力（現在の診断と不一致）・使いません", "REJECTED": "✕ 検証失敗・使いません",
    "NOT_THIS_SOURCE": "✕ この元データ・会社の出力ではありません",
}
TRACKER_TEXT = {"NO_TRACKER": "未作成", "TRACKED": "管理中", "TRACKER_MISMATCH": "対応しない管理表（使いません）",
                "TRACKER_INVALID": "読めません"}


def run_rows(yayoi: dict | None) -> tuple[tuple[str, ...], ...]:
    """One row per READY-only output found next to the source: identity (counts, time, SHA-256), the live check against
    the current diagnosis, and the recorded real-JDL result for exactly these bytes (run_history)."""
    from accounting_converter.ui.run_history import e2e_text

    rows = []
    for run in (yayoi or {}).get("runs") or ():
        counts = run.get("counts") or {}
        sha = run.get("output_sha256") or ""
        rows.append((
            run["file"],
            f"{counts['output_journals']:,}" if isinstance(counts.get("output_journals"), int) else "—",
            f"{counts['output_rows']:,}" if isinstance(counts.get("output_rows"), int) else "—",
            (run.get("created_at") or "—")[:19].replace("T", " "),
            sha[:12] + "…" if sha else "—",
            RUN_STATE_TEXT.get(run.get("state"), run.get("state") or "—"),
            ("" if run.get("usable") else "【参考・現在は使わない出力】") + e2e_text(tuple(run.get("history") or ())),
            TRACKER_TEXT.get(run.get("state"), "—"),
        ))
    return tuple(rows)


def run_cards(yayoi: dict | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The same facts as run_rows, one card per output, in full (nothing elided): (title, lines)."""
    from accounting_converter.ui.run_history import kind_label

    cards = []
    for run, row in zip((yayoi or {}).get("runs") or (), run_rows(yayoi)):
        lines = [
            f"内容: {row[1]}仕訳・{row[2]}行　作成: {row[3]}",
            f"出力のSHA-256: {run.get('output_sha256') or '—'}",
            f"現在の正式診断との照合: {row[5]}",
            f"実機での確認: {row[6]}",
            f"管理表: {row[7]}",
        ]
        lines += [f"理由: {problem}" for problem in run.get("problems") or ()]
        lines += [f"記録（{r.recorded_on}・{kind_label(r.kind)} {r.verdict}）: {r.summary} 出典: {r.reference}"
                  f"　対象: 会社設定 {r.company_setting_id}・{r.source_period[0]}〜{r.source_period[1]}・"
                  f"行数 {dict(r.jdl_conditions).get('voucher_row_limit')}。docsの記録の転記であり、新しいEvidenceではありません。"
                  for r in run.get("history") or ()]
        cards.append((run["file"], tuple(lines)))
    return tuple(cards)


def build_home(state: AppState, *, tax_context_text: str = "JDL税設定: 確認が必要です",
               yayoi: dict | None = None, yayoi_busy: bool = False, yayoi_error: str | None = None) -> HomePresentation:
    """What the home page shows for the current company / source. `yayoi` is controller.home_yayoi_overview()."""
    lines = company_lines(state, tax_context_text)
    company = selected_company(state)
    fmt = source_format(state)
    recognition = state.file_recognition
    total_text = _n(recognition.journal_count) if recognition and recognition.journal_count is not None else "—"
    breakdown = pending_breakdown(state)
    pending = sum(count for _, count in breakdown)
    actions: list[NextAction] = []
    message = None
    notes: list[str] = []
    review_journals: int | None = None

    if company is None:
        actions.append(NextAction("会社を選んでください（画面上部の「会社」）。会社がない場合は設定で追加します。",
                                  "settings", "設定へ（会社）", 1))
    if state.selected_file is None:
        actions.append(NextAction("変換する仕訳データ（CSV / TXT）を選んでください。", "import", "データ取込へ", 1))
        metrics = (
            Metric("元仕訳", "—", "仕訳データ未選択"),
            Metric("変換可能", "—", "仕訳データ未選択"),
            Metric("BLOCK", "—", "仕訳データ未選択"),
            Metric("税理士の判断", "—", "仕訳データ未選択"),
            Metric("承認済み", "—", "仕訳データ未選択"),
        )
        return HomePresentation(lines, metrics, Metric("移行全体", "—", "仕訳データ未選択"), _ordered(actions),
                                None, False, fmt.value, pending, None, breakdown)
    if fmt is RecognizedFormat.UNKNOWN:
        message = ("error", "選んだファイルを対応している仕訳形式として認識できませんでした。元のファイルは変更していません。")
        actions.append(NextAction("Money Forward・弥生・JDLから出力した仕訳データを選び直してください。", "import",
                                  "データ取込へ", 1))
    if pending:
        actions.append(NextAction(f"変換前に確認が必要な設定があります: {pending_text(breakdown)}（設定の数）。",
                                  "review", "要確認で設定を確認", 2))

    if fmt is RecognizedFormat.YAYOI and company is not None:
        accountant = approvals = "—"
        ready = blocked = "—"
        # Before the diagnosis has a result the counts are unknown: say so, never show them as 0.
        not_yet = "診断中" if yayoi_busy else ("診断できません" if yayoi_error else "未診断")
        ready_hint = blocked_hint = accountant_hint = approvals_hint = not_yet
        if yayoi is not None:
            ready, blocked = _n(yayoi["ready"]), _n(yayoi["blocked"])
            total_text = _n(yayoi["total"])
            ready_hint = "正式診断でREADY"
            blocked_hint = "未移行（READY-only出力に入らない）"
            review_journals = yayoi["accountant_journals"]
            accountant = _n(review_journals)
            accountant_hint = f"仕訳（判断待ちの項目 {_n(yayoi['pending_items'])}件）"
            approvals = _n(yayoi["approvals_in_force"])
            approvals_hint = "承認台帳に記録された承認（記録はCLIの正式手順のみ）"
            if yayoi.get("ledger_error"):
                approvals, approvals_hint = "—", "承認台帳を読めません: " + yayoi["ledger_error"]
            if yayoi["ready"] + yayoi["blocked"] != yayoi["total"]:
                notes.append("元仕訳とREADY・BLOCKの合計が一致しません。診断情報をコピーして担当者へ確認してください。")
            if yayoi["blocked"]:
                actions.append(NextAction(
                    f"変換できない {_n(yayoi['blocked'])}仕訳の理由と担当を確認してください。",
                    "diagnosis", "変換診断で理由を見る", 3))
            if review_journals:
                actions.append(NextAction(
                    f"税理士の判断が必要な仕訳が {_n(review_journals)}仕訳あります（試算は画面、承認の記録はCLI）。",
                    "review", "要確認で税理士の判断を見る", 4))
            runs = tuple(yayoi.get("runs") or ())
            usable = [r for r in runs if r.get("usable")]
            unused = [r for r in runs if not r.get("usable")]
            if unused:
                notes.append(
                    f"この元データの旧い・使えないREADY-only出力が {len(unused)}件あります（"
                    + "、".join(f"{r['file']}: {RUN_STATE_TEXT.get(r.get('state'), r.get('state'))}" for r in unused)
                    + "）。削除はしません。出力・照合で内容を確認できます。")
            if len(usable) > 1:
                actions.append(NextAction(
                    f"現在の診断と一致するREADY-only出力が {len(usable)}件あります。未移行の管理で使う出力を1つ選んでください。",
                    "review", "要確認で未移行の管理へ", 6))
            elif not usable and yayoi["ready"]:
                actions.append(NextAction(
                    "現在の診断と一致するREADY-only出力はまだありません。READYの仕訳だけを出力できます（未移行分は手入力・後日対応）。",
                    "output", "出力・照合へ", 5))
            elif usable and usable[0].get("state") == "NO_TRACKER":
                actions.append(NextAction(
                    f"READY-only出力（{usable[0]['file']}）の未移行の管理を始められます（管理表は明示操作で作成）。",
                    "review", "要確認で未移行の管理へ", 6))
        elif yayoi_busy:
            message = ("info", "診断しています…（全仕訳を正式診断します。保存はしません）")
        elif yayoi_error:
            message = ("error", "診断できませんでした。" + yayoi_error + "\n何も保存していません。会社設定と仕訳データを確認してください。")
        metrics = (
            Metric("元仕訳", total_text, "仕訳"),
            Metric("変換可能", ready, ready_hint, "ready"),
            Metric("BLOCK", blocked, blocked_hint, "block"),
            Metric("税理士の判断", accountant, accountant_hint, "pending"),
            Metric("承認済み", approvals, approvals_hint, "pending"),
        )
        migration = _migration(yayoi) if (yayoi is not None or not yayoi_error) else Metric(
            "移行全体", "未完了", "診断できないため判定しません", "block")
    else:
        summary = state.formal_ready_summary
        ready = _n(summary[0]) if summary else "—"
        blocked = _n(summary[1] - summary[0]) if summary else "—"
        hint = "" if summary else "実行前チェック後に表示（保存先の選択が必要）"
        excluded = "弥生のデータのみ"
        metrics = (
            Metric("元仕訳", total_text, "仕訳"),
            Metric("変換可能", ready, hint, "ready"),
            Metric("BLOCK", blocked, hint, "block"),
            Metric("税理士の判断", "対象外", excluded),
            Metric("承認済み", "対象外", excluded),
        )
        migration = Metric("移行全体", "対象外", "未移行の管理は弥生のREADY-only出力のみ")
        review_journals = 0 if fmt is not RecognizedFormat.YAYOI else None
        if fmt is RecognizedFormat.YAYOI and company is None:
            notes.append("会社を選ぶと弥生データの正式診断を行います。")
    if state.selected_file is not None and company is not None and state.selected_output_file is None:
        actions.append(NextAction("JDL用CSVの保存先を選んでください。", "output", "出力・照合へ", 5))
    if (state.conversion_available and state.selected_output_file is not None
            and not (state.result_presentation and state.result_presentation.successful)):
        actions.append(NextAction("全件を変換できます。内容を確認して変換してください。", "output", "出力・照合へ", 5))
    if state.result_presentation is not None and state.result_presentation.successful:
        actions.append(NextAction("変換が完了しました。保存したCSVをJDLで読み込んでください。", "output", "出力・照合へ", 5))
    if not actions:
        actions.append(NextAction("いま必要な作業はありません。", None, "", 9))
    return HomePresentation(lines, metrics, migration, _ordered(actions), message,
                            fmt is RecognizedFormat.YAYOI, fmt.value, pending, review_journals, breakdown,
                            tuple(notes))


def _ordered(actions: list[NextAction]) -> tuple[NextAction, ...]:
    """By priority (stable); actions with the same button are merged into one row, so no button text repeats."""
    merged: dict[str, NextAction] = {}
    for action in sorted(actions, key=lambda a: a.priority):
        key = action.button or action.text
        if key in merged:
            first = merged[key]
            if action.text not in first.text:
                merged[key] = NextAction(first.text + " " + action.text, first.target, first.button, first.priority)
        else:
            merged[key] = action
    return tuple(merged.values())

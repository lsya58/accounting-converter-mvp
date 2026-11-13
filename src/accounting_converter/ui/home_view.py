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
    button: str = ""            # the button text (says what it opens)


@dataclass(frozen=True)
class HomePresentation:
    company_lines: tuple[str, ...]
    metrics: tuple[Metric, ...]
    migration: Metric
    next_actions: tuple[NextAction, ...]
    message: tuple[str, str] | None = None   # (level, text) for components.MessageBar
    yayoi: bool = False
    format_key: str = "NONE"
    review_count: int = 0                    # shown on the 要確認 navigation item
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


def _pending_confirmations(state: AppState) -> int:
    queue = state.review_work_queue
    return (state.pending_account_confirmations + state.pending_subaccount_confirmations
            + state.pending_tax_confirmations + (queue.tax_evidence_settings if queue else 0))


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
    return Metric("移行全体", "未完了", reason, "block")


def build_home(state: AppState, *, tax_context_text: str = "JDL税設定: 確認が必要です",
               yayoi: dict | None = None, yayoi_busy: bool = False, yayoi_error: str | None = None) -> HomePresentation:
    """What the home page shows for the current company / source. `yayoi` is controller.home_yayoi_overview()."""
    lines = company_lines(state, tax_context_text)
    company = selected_company(state)
    fmt = source_format(state)
    recognition = state.file_recognition
    total_text = _n(recognition.journal_count) if recognition and recognition.journal_count is not None else "—"
    pending = _pending_confirmations(state)
    actions: list[NextAction] = []
    message = None
    notes: list[str] = []

    if company is None:
        actions.append(NextAction("会社を選んでください（画面上部の「会社」）。会社がない場合は設定で追加します。",
                                  "settings", "設定を開く"))
    if state.selected_file is None:
        actions.append(NextAction("変換する仕訳データ（CSV / TXT）を選んでください。", "import", "データ取込を開く"))
        metrics = (
            Metric("元仕訳", "—", "仕訳データ未選択"),
            Metric("変換可能", "—", "仕訳データ未選択"),
            Metric("BLOCK", "—", "仕訳データ未選択"),
            Metric("税理士の判断", "—", "仕訳データ未選択"),
            Metric("承認済み", "—", "仕訳データ未選択"),
        )
        return HomePresentation(lines, metrics, Metric("移行全体", "—", "仕訳データ未選択"), tuple(actions),
                                None, False, fmt.value, pending)
    if fmt is RecognizedFormat.UNKNOWN:
        message = ("error", "選んだファイルを対応している仕訳形式として認識できませんでした。元のファイルは変更していません。")
        actions.append(NextAction("Money Forward・弥生・JDLから出力した仕訳データを選び直してください。", "import",
                                  "データ取込を開く"))

    if fmt is RecognizedFormat.YAYOI and company is not None:
        accountant = approvals = "—"
        ready = blocked = "—"
        ready_hint = blocked_hint = accountant_hint = approvals_hint = ""
        if yayoi is not None:
            ready, blocked = _n(yayoi["ready"]), _n(yayoi["blocked"])
            total_text = _n(yayoi["total"])
            ready_hint = "正式診断でREADY"
            blocked_hint = "未移行（READY-only出力に入らない）"
            accountant = _n(yayoi["accountant_journals"])
            accountant_hint = f"仕訳（判断待ちの項目 {_n(yayoi['pending_items'])}件）"
            approvals = _n(yayoi["approvals_in_force"])
            approvals_hint = "承認台帳に記録された承認（記録はCLIの正式手順のみ）"
            if yayoi.get("ledger_error"):
                approvals, approvals_hint = "—", "承認台帳を読めません: " + yayoi["ledger_error"]
            if yayoi["ready"] + yayoi["blocked"] != yayoi["total"]:
                notes.append("元仕訳とREADY・BLOCKの合計が一致しません。診断情報をコピーして担当者へ確認してください。")
            if yayoi["blocked"]:
                actions.append(NextAction(
                    f"変換できない {_n(yayoi['blocked'])}仕訳の理由を確認してください。", "diagnosis", "変換診断を開く"))
            if yayoi["accountant_journals"]:
                actions.append(NextAction(
                    f"税理士の判断が必要な {_n(yayoi['accountant_journals'])}仕訳があります（承認の記録はCLI）。",
                    "review", "要確認を開く"))
            if yayoi.get("run_state") is None and yayoi.get("runs_found", 0) > 1:
                actions.append(NextAction(
                    f"この元データのREADY-only出力が {yayoi['runs_found']}件あります。未移行の管理で使う出力を1つ選んでください。",
                    "review", "要確認を開く"))
            elif yayoi.get("run_state") is None and yayoi["ready"]:
                actions.append(NextAction("READYの仕訳だけを出力できます（未移行分は手入力・後日対応）。", "output",
                                          "出力・照合を開く"))
            elif yayoi.get("run_state") == "NO_TRACKER":
                actions.append(NextAction("READY-only出力の未移行の管理を始められます（管理表は明示操作で作成）。",
                                          "review", "要確認を開く"))
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
        review = pending + (yayoi["accountant_journals"] if yayoi else 0)
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
        review = pending
        if fmt is RecognizedFormat.YAYOI and company is None:
            notes.append("会社を選ぶと弥生データの正式診断を行います。")
    if pending:
        actions.insert(0, NextAction(f"科目・補助・税区分などの確認が {_n(pending)}件あります。", "review", "要確認を開く"))
    if state.selected_file is not None and company is not None and state.selected_output_file is None:
        actions.append(NextAction("JDL用CSVの保存先を選んでください。", "output", "出力・照合を開く"))
    if (state.conversion_available and state.selected_output_file is not None
            and not (state.result_presentation and state.result_presentation.successful)):
        actions.append(NextAction("全件を変換できます。出力・照合で内容を確認して変換してください。", "output",
                                  "出力・照合を開く"))
    if state.result_presentation is not None and state.result_presentation.successful:
        actions.append(NextAction("変換が完了しました。保存したCSVをJDLで読み込んでください。", "output",
                                  "出力・照合を開く"))
    if not actions:
        actions.append(NextAction("いま必要な作業はありません。", None, ""))
    return HomePresentation(lines, metrics, migration, tuple(dict.fromkeys(actions)), message,
                            fmt is RecognizedFormat.YAYOI, fmt.value, review, tuple(notes))

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from accounting_converter.application.first_release_workflow import FirstReleaseSummary


class DiagnosticKind(str, Enum):
    JDL = "JDL"
    YAYOI = "YAYOI"


class DiagnosticStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class RecognizedFormat(str, Enum):
    NONE = "NONE"
    JDL = "JDL"
    YAYOI = "YAYOI"
    MONEYFORWARD = "MONEYFORWARD"
    UNKNOWN = "UNKNOWN"


class UserFacingStatus(str, Enum):
    NEEDS_INPUT = "NEEDS_INPUT"
    READY = "READY"
    CONFIRM = "CONFIRM"
    BLOCKED = "BLOCKED"
    SUCCESS = "SUCCESS"


@dataclass(frozen=True)
class ProfileOption:
    profile_id: str
    profile_name: str

    @property
    def label(self) -> str:
        return f"{self.profile_name} ({self.profile_id})"


@dataclass(frozen=True)
class DiagnosticSummary:
    kind: DiagnosticKind
    file_name: str
    data_record_count: int | None
    diagnostic_count: int | None
    error_count: int
    warning_count: int
    structural_status: str
    format_candidate: str


@dataclass(frozen=True)
class FileRecognition:
    format: RecognizedFormat
    display_name: str
    journal_count: int | None = None
    period_start: str | None = None
    period_end: str | None = None


@dataclass(frozen=True)
class ConversionResultPresentation:
    successful: bool
    input_journal_count: int
    output_journal_count: int
    debit_total: str
    credit_total: str
    error_count: int
    output_validation_success: bool
    output_path: Path | None


@dataclass(frozen=True)
class AppState:
    companies: tuple[CompanyOption, ...] = ()
    selected_company_setting_id: str | None = None
    profiles: tuple[ProfileOption, ...] = ()
    selected_profile_id: str | None = None
    selected_file: Path | None = None
    selected_context_file: Path | None = None
    selected_output_file: Path | None = None
    file_recognition: FileRecognition | None = None
    diagnostic_kind: DiagnosticKind = DiagnosticKind.YAYOI
    diagnostic_status: DiagnosticStatus = DiagnosticStatus.NOT_RUN
    diagnostic_summary: DiagnosticSummary | None = None
    preflight_status: str = "UNKNOWN"
    conversion_available: bool = False
    user_message: str = "入力ファイルと変換設定を選択してください。"
    developer_error: str | None = None
    messages: tuple[str, ...] = field(default_factory=tuple)
    conversion_summary: FirstReleaseSummary | None = None
    result_summary: str | None = None
    result_presentation: ConversionResultPresentation | None = None
    verification_report: str | None = None
    pending_account_confirmations: int = 0
    pending_subaccount_confirmations: int = 0
    pending_tax_confirmations: int = 0
    unsupported_shape_count: int = 0
    optional_field_blocker_count: int = 0
    jdl_environment_label: str = "未設定"
    jdl_master_configured: bool = False
    jdl_master_state: str = "未設定"
    jdl_master_updated_at: str | None = None


@dataclass(frozen=True)
class CompanyOption:
    company_setting_id: str
    display_name: str
    source_label: str
    status_label: str


@dataclass(frozen=True)
class MainScreenPresentation:
    status: UserFacingStatus
    status_text: str
    guidance: str
    recognition_text: str
    conversion_enabled: bool
    settings_action_visible: bool


def present_main_screen(state: AppState) -> MainScreenPresentation:
    recognition = _recognition_text(state.file_recognition)
    result = state.result_presentation
    if result is not None and result.successful:
        return MainScreenPresentation(
            UserFacingStatus.SUCCESS,
            "変換が完了しました",
            "保存されたCSVをJDLで読み込んでください。",
            recognition,
            False,
            False,
        )
    if result is not None:
        return MainScreenPresentation(
            UserFacingStatus.BLOCKED,
            "変換できません",
            _friendly_guidance(state),
            recognition,
            False,
            False,
        )
    if state.conversion_available:
        return MainScreenPresentation(
            UserFacingStatus.READY,
            "変換できます",
            "入力内容と保存先を確認して、変換を開始してください。",
            recognition,
            True,
            False,
        )
    if state.file_recognition and state.file_recognition.format is RecognizedFormat.UNKNOWN:
        return MainScreenPresentation(
            UserFacingStatus.BLOCKED,
            "変換できません",
            (
                "このCSVは現在対応している仕訳形式ではありません。"
                "選択した会社設定の入力元とCSV形式を確認してください。"
            ),
            recognition,
            False,
            False,
        )
    confirm_statuses = {
        "REQUIRES_MAPPING",
        "REQUIRES_CONFIRMATION",
        "LOSSY_CONFIRMATION_REQUIRED",
    }
    if state.preflight_status in confirm_statuses:
        return MainScreenPresentation(
            UserFacingStatus.CONFIRM,
            "確認が必要です",
            _friendly_guidance(state),
            recognition,
            False,
            True,
        )
    blocked_statuses = {
        "BLOCKED",
        "FORMAT_MISMATCH",
        "PROFILE_INVALID",
        "ADAPTER_UNAVAILABLE",
        "UNSUPPORTED_TRANSFORMATION",
        "VALIDATION_FAILED",
        "SYSTEM_ERROR",
        "BLOCKED_BY_STRUCTURAL_VALIDATION",
        "BLOCKED_BY_MAPPING",
        "BLOCKED_BY_BUSINESS_VALIDATION",
        "BLOCKED_BY_TARGET_CONTEXT",
        "BLOCKED_BY_OUTPUT_PREFLIGHT",
        "OUTPUT_VALIDATION_FAILED",
        "OUTPUT_PATH_ALREADY_EXISTS",
        "INPUT_OUTPUT_PATH_CONFLICT",
    }
    if state.preflight_status in blocked_statuses:
        return MainScreenPresentation(
            UserFacingStatus.BLOCKED,
            "変換できません",
            _friendly_guidance(state),
            recognition,
            False,
            False,
        )
    if state.selected_file and (
        not state.selected_profile_id or not state.selected_context_file
    ):
        return MainScreenPresentation(
            UserFacingStatus.CONFIRM,
            "確認が必要です",
            _friendly_guidance(state),
            recognition,
            False,
            True,
        )
    return MainScreenPresentation(
        UserFacingStatus.NEEDS_INPUT,
        "CSVを選択してください" if not state.selected_file else "保存先を選択してください",
        _friendly_guidance(state),
        recognition,
        False,
        bool(state.selected_file),
    )


def _recognition_text(recognition: FileRecognition | None) -> str:
    if recognition is None:
        return "ファイルはまだ選択されていません。"
    if recognition.format is RecognizedFormat.UNKNOWN:
        return "対応している仕訳形式として認識できませんでした。"
    details = [f"{recognition.display_name}を認識しました"]
    if recognition.journal_count is not None:
        details.append(f"{recognition.journal_count}仕訳")
    if recognition.period_start and recognition.period_end:
        details.append(f"{recognition.period_start} - {recognition.period_end}")
    return " / ".join(details)


def _friendly_guidance(state: AppState) -> str:
    if not state.selected_file:
        return "変換する仕訳CSVを選択してください。"
    pending = tuple(
        label
        for label, count in (
            (f"科目: {state.pending_account_confirmations}件", state.pending_account_confirmations),
            (f"補助科目: {state.pending_subaccount_confirmations}件", state.pending_subaccount_confirmations),
            (f"税区分: {state.pending_tax_confirmations}件", state.pending_tax_confirmations),
        )
        if count
    )
    if pending:
        details = ("確認が必要な項目があります。", *pending, *state.messages)
        return "\n".join(dict.fromkeys(details))
    if state.messages:
        return "\n".join(dict.fromkeys(state.messages))
    if not state.selected_profile_id or not state.selected_context_file:
        return "初回のみ、設定画面で会社設定とJDL設定を選択してください。"
    if not state.selected_output_file:
        return "変換後のCSVを保存する場所を選択してください。"
    return state.user_message


def support_diagnostic_text(
    state: AppState,
    app_version: str,
    *,
    build_commit: str = "不明",
    build_identifier: str | None = None,
) -> str:
    """Return a support-ready summary that cannot include accounting values."""
    recognition = state.file_recognition
    summary = state.conversion_summary
    readiness = present_main_screen(state).status_text
    error_category = (
        "確認が必要"
        if state.pending_account_confirmations
        or state.pending_subaccount_confirmations
        or state.pending_tax_confirmations
        else "変換条件未対応"
        if readiness == "変換できません"
        else "なし"
    )
    source_format = {
        RecognizedFormat.JDL: "JDL IBEX 出納帳 仕訳CSV（30項目）",
        RecognizedFormat.MONEYFORWARD: "Money Forward 仕訳帳CSV（19項目）",
        RecognizedFormat.YAYOI: "弥生 仕訳データ",
        RecognizedFormat.UNKNOWN: "未対応CSV",
    }.get(recognition.format, "未選択") if recognition else "未選択"
    rows = (
        ("アプリ", app_version),
        ("Build commit", build_commit),
        ("Build identifier", build_identifier or f"{app_version}+unverified"),
        ("入力元", recognition.display_name if recognition else "未選択"),
        ("入力形式", source_format),
        ("仕訳数", str(recognition.journal_count) if recognition and recognition.journal_count is not None else "未確認"),
        ("科目確認", str(state.pending_account_confirmations)),
        ("補助科目確認（設定項目）", str(state.pending_subaccount_confirmations)),
        ("税区分確認", str(state.pending_tax_confirmations)),
        ("未対応仕訳構成", str(summary.unsupported_shape_count if summary else state.unsupported_shape_count)),
        ("税Evidence条件未一致", str(summary.tax_evidence_blocker_count if summary else 0)),
        ("保持方法未確認", str(summary.optional_field_blocker_count if summary else state.optional_field_blocker_count)),
        ("Formal出力条件未一致", str(summary.formal_output_blocker_count if summary else 0)),
        ("JDL科目一覧", "設定済み" if state.jdl_master_configured else "未設定"),
        ("JDL科目一覧の状態", state.jdl_master_state),
        ("最終状態", readiness),
        ("分類", error_category),
    )
    details = (
        ("Evidence mismatch詳細:", *summary.tax_evidence_mismatch_details)
        if summary and summary.tax_evidence_mismatch_details
        else ()
    )
    formal_details = (
        ("Formal output blocker詳細:", *summary.formal_output_blocker_details)
        if summary and summary.formal_output_blocker_details
        else ()
    )
    return "会計データ変換 サポート診断\n" + "\n".join(
        f"{label}: {value}" for label, value in rows
    ) + ("\n" + "\n".join(details) if details else "") + (
        "\n" + "\n".join(formal_details) if formal_details else ""
    )

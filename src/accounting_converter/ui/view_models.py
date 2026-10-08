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
            True,
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
                "認識できる形式はMoney Forwardの仕訳帳CSVと"
                "弥生会計の仕訳データです。"
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
            bool(state.selected_file),
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
    if not state.selected_profile_id or not state.selected_context_file:
        return "初回のみ、設定画面で会社設定とJDL設定を選択してください。"
    if not state.selected_output_file:
        return "変換後のCSVを保存する場所を選択してください。"
    if state.messages:
        return state.messages[0]
    return state.user_message

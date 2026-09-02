from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DiagnosticKind(str, Enum):
    JDL = "JDL"
    YAYOI = "YAYOI"


class DiagnosticStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


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
class AppState:
    profiles: tuple[ProfileOption, ...] = ()
    selected_profile_id: str | None = None
    selected_file: Path | None = None
    diagnostic_kind: DiagnosticKind = DiagnosticKind.YAYOI
    diagnostic_status: DiagnosticStatus = DiagnosticStatus.NOT_RUN
    diagnostic_summary: DiagnosticSummary | None = None
    preflight_status: str = "UNKNOWN"
    conversion_available: bool = False
    user_message: str = "入力ファイルと変換設定を選択してください。"
    developer_error: str | None = None
    messages: tuple[str, ...] = field(default_factory=tuple)


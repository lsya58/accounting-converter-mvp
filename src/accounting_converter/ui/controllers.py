from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from accounting_converter.application.profile_preflight import (
    ConversionPreflightService,
    ObservedMappingRequirements,
    ProfilePreflightStatus,
)
from accounting_converter.application.conversion_preparation import (
    ConversionReadinessResult,
    ConversionReadinessStatus,
)
from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)
from accounting_converter.diagnostics.yayoi_csv import YayoiCsvAnalyzer
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    ConversionProfileStoreError,
    default_profile_store_dir,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_desktop_import_25_documented_schema,
)

from .view_models import (
    AppState,
    DiagnosticKind,
    DiagnosticStatus,
    DiagnosticSummary,
    ProfileOption,
)


PREFLIGHT_MESSAGES = {
    ProfilePreflightStatus.READY: "変換準備ができています。",
    ProfilePreflightStatus.REQUIRES_MAPPING: "確認が必要な対応項目があります。",
    ProfilePreflightStatus.FORMAT_MISMATCH: "選択した変換設定とファイル形式が一致しません。",
    ProfilePreflightStatus.PROFILE_INVALID: "変換設定を確認してください。",
    ProfilePreflightStatus.UNSUPPORTED: "この変換設定のバージョンには対応していません。",
    ProfilePreflightStatus.UNKNOWN: "変換可否をまだ判定できません。",
}

READINESS_MESSAGES = {
    ConversionReadinessStatus.READY: "変換準備ができています。",
    ConversionReadinessStatus.REQUIRES_MAPPING: "確認が必要な対応項目があります。",
    ConversionReadinessStatus.REQUIRES_CONFIRMATION: "実行前に確認が必要です。",
    ConversionReadinessStatus.FORMAT_MISMATCH: "選択した変換設定とファイル形式が一致しません。",
    ConversionReadinessStatus.PROFILE_INVALID: "変換設定を確認してください。",
    ConversionReadinessStatus.ADAPTER_UNAVAILABLE: "現在この形式の正式変換Adapterは未登録です。",
    ConversionReadinessStatus.UNSUPPORTED_TRANSFORMATION: "現在未対応の変換手順があります。",
    ConversionReadinessStatus.LOSSY_CONFIRMATION_REQUIRED: "情報欠落の可能性があるため確認が必要です。",
    ConversionReadinessStatus.VALIDATION_FAILED: "検証で問題が検出されました。",
    ConversionReadinessStatus.UNKNOWN: "変換可否をまだ判定できません。",
}


class AccountingConverterController:
    def __init__(
        self,
        profile_store: ConversionProfileStore | None = None,
        preflight_service: ConversionPreflightService | None = None,
        formal_conversion_adapter_registered: bool = False,
        jdl_analyzer: JdlCsvStructuralAnalyzer | None = None,
        yayoi_analyzer: YayoiCsvAnalyzer | None = None,
    ) -> None:
        self.profile_store = profile_store or ConversionProfileStore(
            default_profile_store_dir()
        )
        self.preflight_service = preflight_service or ConversionPreflightService()
        self.formal_conversion_adapter_registered = formal_conversion_adapter_registered
        self.jdl_analyzer = jdl_analyzer or JdlCsvStructuralAnalyzer(
            observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
        )
        self.yayoi_analyzer = yayoi_analyzer or YayoiCsvAnalyzer()
        self.state = AppState()

    def load_profiles(self) -> AppState:
        try:
            profiles = tuple(
                ProfileOption(profile.profile_id, profile.profile_name)
                for profile in self.profile_store.list()
            )
        except ConversionProfileStoreError as error:
            return self._fail_state(
                "変換設定を読み込めませんでした。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        self.state = replace(
            self.state,
            profiles=profiles,
            user_message=(
                "保存済み変換設定はありません。"
                if not profiles
                else "保存済み変換設定を読み込みました。"
            ),
            developer_error=None,
        )
        return self.state

    def apply_readiness_result(
        self,
        readiness: ConversionReadinessResult,
    ) -> AppState:
        self.state = replace(
            self.state,
            preflight_status=readiness.status.value,
            conversion_available=readiness.conversion_enabled,
            user_message=READINESS_MESSAGES[readiness.status],
            developer_error=None,
            messages=readiness.blocking_reasons,
        )
        return self.state

    def select_profile(self, profile_id: str | None) -> AppState:
        known_ids = {profile.profile_id for profile in self.state.profiles}
        selected = profile_id if profile_id in known_ids else None
        self.state = replace(
            self.state,
            selected_profile_id=selected,
            preflight_status=ProfilePreflightStatus.UNKNOWN.value,
            conversion_available=False,
            user_message=(
                "変換設定を選択しました。"
                if selected is not None
                else "変換設定が未選択です。"
            ),
            developer_error=None,
        )
        return self.state

    def select_file(self, path: Path | str | None) -> AppState:
        selected = Path(path) if path is not None else None
        self.state = replace(
            self.state,
            selected_file=selected,
            diagnostic_status=DiagnosticStatus.NOT_RUN,
            diagnostic_summary=None,
            preflight_status=ProfilePreflightStatus.UNKNOWN.value,
            conversion_available=False,
            user_message=(
                f"入力ファイルを選択しました: {selected.name}"
                if selected is not None
                else "入力ファイルが未選択です。"
            ),
            developer_error=None,
        )
        return self.state

    def diagnose_selected(self, kind: DiagnosticKind) -> AppState:
        if self.state.selected_file is None:
            self.state = replace(
                self.state,
                diagnostic_status=DiagnosticStatus.NOT_RUN,
                diagnostic_summary=None,
                user_message="入力ファイルを選択してください。",
                developer_error=None,
            )
            return self.state
        try:
            summary = (
                self._diagnose_jdl(self.state.selected_file)
                if kind is DiagnosticKind.JDL
                else self._diagnose_yayoi(self.state.selected_file)
            )
        except Exception as error:
            return self._fail_state(
                "ファイルを解析できませんでした。",
                error,
                diagnostic_status=DiagnosticStatus.FAILED,
                diagnostic_kind=kind,
            )
        self.state = replace(
            self.state,
            diagnostic_kind=kind,
            diagnostic_status=DiagnosticStatus.SUCCESS,
            diagnostic_summary=summary,
            user_message="ファイル確認が完了しました。",
            developer_error=None,
        )
        return self.state

    def run_preflight(
        self,
        observed_mapping_requirements: ObservedMappingRequirements | None = None,
    ) -> AppState:
        if self.state.selected_file is None:
            self.state = replace(
                self.state,
                preflight_status=ProfilePreflightStatus.UNKNOWN.value,
                conversion_available=False,
                user_message="入力ファイルを選択してください。",
                developer_error=None,
            )
            return self.state
        try:
            profile = self._selected_profile()
            result = self.preflight_service.check(
                source_format_candidate=self._source_candidate_identity(),
                target_format_candidate=(
                    jdl_ibex_cashbook_35_5_observed_schema_definition().identity
                ),
                observed_mapping_requirements=(
                    observed_mapping_requirements or ObservedMappingRequirements()
                ),
                saved_profile=profile,
            )
        except Exception as error:
            return self._fail_state(
                "事前確認を実行できませんでした。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        conversion_available = (
            result.status is ProfilePreflightStatus.READY
            and self.formal_conversion_adapter_registered
        )
        message = PREFLIGHT_MESSAGES[result.status]
        if result.status is ProfilePreflightStatus.READY and not conversion_available:
            message = "現在この形式の正式変換Adapterは未登録です。"
        self.state = replace(
            self.state,
            preflight_status=result.status.value,
            conversion_available=conversion_available,
            user_message=message,
            developer_error=None,
            messages=result.messages,
        )
        return self.state

    def _diagnose_jdl(self, path: Path) -> DiagnosticSummary:
        analysis = self.jdl_analyzer.analyze_path(path)
        return DiagnosticSummary(
            kind=DiagnosticKind.JDL,
            file_name=analysis.file_name,
            data_record_count=analysis.data_record_count,
            diagnostic_count=len(analysis.diagnostic_message_lines),
            error_count=len(analysis.analysis_errors),
            warning_count=len(analysis.analysis_warnings),
            structural_status=(
                "ERROR" if analysis.analysis_errors else "NO_STRUCTURAL_ERROR"
            ),
            format_candidate="JDL CSV candidate",
        )

    def _diagnose_yayoi(self, path: Path) -> DiagnosticSummary:
        analysis = self.yayoi_analyzer.analyze_path(path)
        return DiagnosticSummary(
            kind=DiagnosticKind.YAYOI,
            file_name=analysis.file_name,
            data_record_count=analysis.data_record_count,
            diagnostic_count=None,
            error_count=sum(
                1
                for result in analysis.validation_results
                if result.severity.value == "ERROR"
            ),
            warning_count=sum(
                1
                for result in analysis.validation_results
                if result.severity.value == "WARNING"
            ),
            structural_status=analysis.official_comparison.structural_match_status.value,
            format_candidate="Yayoi CSV candidate",
        )

    def _selected_profile(self) -> ConversionProfile | None:
        if self.state.selected_profile_id is None:
            return None
        return self.profile_store.get(self.state.selected_profile_id)

    def _source_candidate_identity(self) -> Any:
        if self.state.diagnostic_kind is DiagnosticKind.JDL:
            return jdl_ibex_cashbook_35_5_observed_schema_definition().identity
        return yayoi_desktop_import_25_documented_schema().identity

    def _fail_state(
        self,
        user_message: str,
        error: Exception,
        diagnostic_status: DiagnosticStatus,
        diagnostic_kind: DiagnosticKind | None = None,
    ) -> AppState:
        self.state = replace(
            self.state,
            diagnostic_kind=diagnostic_kind or self.state.diagnostic_kind,
            diagnostic_status=diagnostic_status,
            conversion_available=False,
            user_message=user_message,
            developer_error=error.__class__.__name__,
        )
        return self.state

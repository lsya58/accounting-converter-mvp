from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from accounting_converter.application.first_release_workflow import (
    FirstReleaseConversionWorkflow,
    FirstReleasePreparedConversion,
    conversion_result_message,
)
from accounting_converter.application.company_settings import CompanySettingService
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupAnalysis,
    MoneyForwardProfileSetupService,
    TaxMappingSetupReview,
    profile_pending_setup_field_types,
)

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
from accounting_converter.diagnostics.yayoi_csv import YayoiCsvAnalyzer
from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.adapters.input.yayoi import YayoiInputAdapter
from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    FormatIdentityMatchStatus,
)
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    ConversionProfileStoreError,
    DuplicateProfileError,
    default_profile_store_dir,
)
from accounting_converter.infrastructure.jdl_target_context_loader import (
    JdlTargetContextLoadError,
    JdlTargetContextLoader,
)
from accounting_converter.infrastructure.company_setting_store import (
    CompanySettingStore,
    CompanySettingStoreError,
    default_company_store_dir,
)
from accounting_converter.infrastructure.application_preferences import (
    ApplicationPreferences,
    ApplicationPreferencesStore,
    default_preferences_path,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
    yayoi_ae19_direct_export_observed_schema,
    yayoi_desktop_import_25_documented_schema,
)

from .view_models import (
    AppState,
    DiagnosticKind,
    DiagnosticStatus,
    DiagnosticSummary,
    ConversionResultPresentation,
    CompanyOption,
    FileRecognition,
    ProfileOption,
    RecognizedFormat,
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
        conversion_workflow: FirstReleaseConversionWorkflow | None = None,
        context_loader: JdlTargetContextLoader | None = None,
        company_store: CompanySettingStore | None = None,
        preferences_store: ApplicationPreferencesStore | None = None,
    ) -> None:
        self.profile_store = profile_store or ConversionProfileStore(
            default_profile_store_dir()
        )
        self.preflight_service = preflight_service or ConversionPreflightService()
        self.formal_conversion_adapter_registered = formal_conversion_adapter_registered
        self.jdl_analyzer = jdl_analyzer or JdlCsvStructuralAnalyzer()
        self.yayoi_analyzer = yayoi_analyzer or YayoiCsvAnalyzer()
        self.conversion_workflow = conversion_workflow or FirstReleaseConversionWorkflow()
        self.context_loader = context_loader or JdlTargetContextLoader()
        self.company_store = company_store or CompanySettingStore(
            default_company_store_dir(), self.profile_store
        )
        self.company_setting_service = CompanySettingService(self.company_store)
        self.moneyforward_profile_setup_service = MoneyForwardProfileSetupService(
            self.profile_store
        )
        self.preferences_store = preferences_store or ApplicationPreferencesStore(
            default_preferences_path()
        )
        self._target_context = None
        self._prepared: FirstReleasePreparedConversion | None = None
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
        selected_id = profiles[0].profile_id if len(profiles) == 1 else self.state.selected_profile_id
        self.state = replace(
            self.state,
            profiles=profiles,
            selected_profile_id=selected_id,
            user_message=(
                "変換設定がまだ登録されていません。管理者から受け取った"
                "変換設定ファイルを「設定を追加」から登録してください。"
                if not profiles
                else "保存済み変換設定を読み込みました。"
            ),
            developer_error=None,
        )
        self._auto_select_company_for_recognized_file()
        return self.state

    def load_company_settings(self) -> AppState:
        try:
            settings = self.company_store.list()
            options = tuple(self._company_option(item.company_setting_id) for item in settings)
        except (CompanySettingStoreError, OSError) as error:
            return self._fail_state(
                "会社設定を読み込めませんでした。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        known = {item.company_setting_id for item in options}
        selected = self.state.selected_company_setting_id
        if selected not in known:
            selected = None
        self.state = replace(self.state, companies=options, selected_company_setting_id=selected)
        if self.state.file_recognition is not None:
            self._auto_select_company_for_recognized_file()
        return self.state

    def add_company_setting(
        self,
        *,
        display_name: str,
        source_label: str,
        conversion_profile_id: str,
        context_source: Path,
    ) -> AppState:
        import uuid

        try:
            profile = self.profile_store.get(conversion_profile_id)
            expected_label = self._source_label(profile.source_format_identity.stable_key)
            if expected_label != source_label:
                raise CompanySettingStoreError("selected source and profile do not match")
            setting = self.company_store.create(
                company_setting_id=f"company-{uuid.uuid4().hex}",
                display_name=display_name,
                conversion_profile_id=conversion_profile_id,
                context_source=context_source,
            )
        except (CompanySettingStoreError, ConversionProfileStoreError, OSError) as error:
            return self._fail_state(self._company_setting_save_message(error), error)
        self.load_company_settings()
        return self.select_company_setting(setting.company_setting_id)

    @staticmethod
    def _company_setting_save_message(error: Exception) -> str:
        reason = str(error)
        if reason in {
            "profile was confirmed against a different JDL setting",
            "profile and JDL setting are incompatible",
        }:
            return (
                "対応設定とJDL設定の組み合わせが一致していません。"
                "対応設定の作成時に使用したJDL設定を選択してください。"
            )
        if reason == "selected source and profile do not match":
            return "入力元と対応設定が一致していません。対応設定を選び直してください。"
        if isinstance(error, ConversionProfileStoreError):
            return "対応設定を読み込めませんでした。もう一度設定してください。"
        return "会社設定を保存できませんでした。JDL設定をもう一度選択してください。"

    def select_company_setting(self, company_setting_id: str | None) -> AppState:
        self._prepared = None
        if company_setting_id is None:
            self._target_context = None
            self.state = replace(
                self.state,
                selected_company_setting_id=None,
                selected_profile_id=None,
                selected_context_file=None,
                conversion_available=False,
                conversion_summary=None,
                user_message="会社設定を選択してください。",
            )
            return self.state
        resolved = self.company_setting_service.resolve_for_source(
            company_setting_id, self._recognized_source_key()
        )
        if not resolved.available or resolved.profile is None or resolved.context is None:
            self._target_context = None
            self.state = replace(
                self.state,
                selected_company_setting_id=company_setting_id,
                selected_profile_id=None,
                selected_context_file=None,
                conversion_available=False,
                conversion_summary=None,
                user_message=resolved.user_message or "会社設定を確認してください。",
            )
            return self.state
        self._target_context = resolved.context
        self.preferences_store.save(ApplicationPreferences(company_setting_id))
        self.state = replace(
            self.state,
            selected_company_setting_id=company_setting_id,
            selected_profile_id=resolved.profile.profile_id,
            selected_context_file=self.company_store.context_path(resolved.setting),
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message="会社設定を選択しました。",
        )
        return self.state

    def rename_company_setting(self, company_setting_id: str, display_name: str) -> AppState:
        try:
            self.company_store.rename(company_setting_id, display_name)
        except (CompanySettingStoreError, OSError) as error:
            return self._fail_state("会社設定の名前を変更できませんでした。", error)
        self.load_company_settings()
        self.state = replace(self.state, user_message="会社設定の名前を変更しました。")
        return self.state

    def profiles_for_source(self, source_label: str) -> tuple[ProfileOption, ...]:
        return tuple(
            item
            for item in self.state.profiles
            if self._source_label(
                self.profile_store.get(item.profile_id).source_format_identity.stable_key
            )
            == source_label
        )

    def analyze_moneyforward_profile_setup(
        self, source_path: Path, context_path: Path
    ) -> MoneyForwardProfileSetupAnalysis:
        return self.moneyforward_profile_setup_service.analyze(source_path, context_path)

    def create_moneyforward_profile(
        self,
        *,
        company_display_name: str,
        analysis: MoneyForwardProfileSetupAnalysis,
        selections: dict[str, str],
        explicitly_confirmed: set[str],
        explicitly_confirmed_tax: set[str] | None = None,
    ) -> ConversionProfile:
        profile = self.moneyforward_profile_setup_service.save_confirmed_profile(
            company_display_name=company_display_name,
            analysis=analysis,
            selections=selections,
            explicitly_confirmed=explicitly_confirmed,
            explicitly_confirmed_tax=explicitly_confirmed_tax,
        )
        self.load_profiles()
        return profile

    def company_tax_mapping_review(
        self, company_setting_id: str
    ) -> TaxMappingSetupReview:
        resolved = self.company_setting_service.resolve_for_source(company_setting_id)
        if not resolved.available or resolved.profile is None or resolved.context is None:
            return TaxMappingSetupReview(
                user_message="現在のJDL設定ではこの税区分を確認できません"
            )
        return self.moneyforward_profile_setup_service.tax_mapping_review(
            resolved.profile, resolved.context
        )

    def confirm_company_tax_mapping(
        self, company_setting_id: str, source_value: str
    ) -> AppState:
        resolved = self.company_setting_service.resolve_for_source(company_setting_id)
        if not resolved.available or resolved.profile is None or resolved.context is None:
            return self._fail_state(
                "現在のJDL設定ではこの税区分を確認できません。",
                CompanySettingStoreError("company setting is unavailable"),
            )
        try:
            self.moneyforward_profile_setup_service.confirm_evidence_backed_tax_mapping(
                profile_id=resolved.profile.profile_id,
                context=resolved.context,
                source_value=source_value,
            )
            try:
                self.company_store.refresh_profile_fingerprint(company_setting_id)
            except Exception:
                self.profile_store.update(resolved.profile)
                raise
        except (CompanySettingStoreError, ConversionProfileStoreError, ValueError) as error:
            return self._fail_state(
                "税区分の設定を保存できませんでした。JDL設定を確認してください。",
                error,
            )
        self.load_profiles()
        self.load_company_settings()
        state = self.select_company_setting(company_setting_id)
        self.state = replace(state, user_message="税区分の確認を保存しました。")
        return self.state

    def delete_company_setting(self, company_setting_id: str) -> AppState:
        try:
            self.company_store.delete(company_setting_id)
        except (CompanySettingStoreError, OSError) as error:
            return self._fail_state("会社設定を削除できませんでした。", error)
        if self.state.selected_company_setting_id == company_setting_id:
            self._target_context = None
            self.state = replace(
                self.state,
                selected_company_setting_id=None,
                selected_profile_id=None,
                selected_context_file=None,
                conversion_available=False,
                conversion_summary=None,
            )
        self.preferences_store.save(ApplicationPreferences())
        self.load_company_settings()
        self.state = replace(self.state, user_message="会社設定を削除しました。")
        return self.state

    def import_profile(self, path: Path | str) -> AppState:
        source = Path(path)
        self._prepared = None
        try:
            profile = self.profile_store.from_json_text(
                source.read_text(encoding="utf-8")
            )
            self._validate_first_release_profile(profile)
            existing = self.profile_store.list()
            if any(item.profile_id == profile.profile_id for item in existing):
                raise DuplicateProfileError(
                    f"profile already exists: {profile.profile_id}"
                )
            if any(item.profile_name == profile.profile_name for item in existing):
                raise DuplicateProfileError(
                    f"profile name already exists: {profile.profile_name}"
                )
            imported = self.profile_store.import_profile(source)
        except DuplicateProfileError as error:
            return self._fail_state(
                "同じIDまたは名前の変換設定が既にあります。既存設定は上書きしません。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        except (ConversionProfileStoreError, OSError, UnicodeError) as error:
            return self._fail_state(
                "変換設定ファイルを追加できませんでした。内容とversionを確認してください。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )

        self.load_profiles()
        self.select_profile(imported.profile_id)
        self.state = replace(
            self.state,
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message=f"変換設定を追加しました: {imported.profile_name}",
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
            result_presentation=None,
            conversion_summary=None,
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
        recognition = self._recognize_file(selected) if selected is not None else None
        self.state = replace(
            self.state,
            selected_file=selected,
            diagnostic_status=DiagnosticStatus.NOT_RUN,
            diagnostic_summary=None,
            file_recognition=recognition,
            preflight_status=ProfilePreflightStatus.UNKNOWN.value,
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message=(
                recognition.display_name + "を認識しました。"
                if recognition is not None and recognition.format is not RecognizedFormat.UNKNOWN
                else "このCSVは現在対応している仕訳形式ではありません。"
                if selected is not None
                else "入力ファイルが未選択です。"
            ),
            developer_error=None,
        )
        self._auto_select_company_for_recognized_file()
        return self.state

    def select_context_file(self, path: Path | str | None) -> AppState:
        selected = Path(path) if path is not None else None
        self._target_context = None
        self._prepared = None
        if selected is None:
            self.state = replace(
                self.state,
                selected_context_file=None,
                conversion_available=False,
                conversion_summary=None,
                user_message=(
                    "JDL設定が未選択です。管理者から受け取った、この会社専用の"
                    "確認済みJDL設定ファイルを選択してください。"
                ),
            )
            return self.state
        self.state = replace(
            self.state,
            selected_context_file=selected,
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message=f"JDL設定を確認しています: {selected.name}",
            developer_error=None,
        )
        try:
            self._target_context = self.context_loader.load(selected)
        except JdlTargetContextLoadError as error:
            return self._fail_state(
                "JDL設定ファイルを確認できませんでした。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        self.state = replace(
            self.state,
            selected_context_file=selected,
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message="確認済みJDL設定を読み込みました。",
            developer_error=None,
        )
        return self.state

    def select_output_file(self, path: Path | str | None) -> AppState:
        selected = Path(path) if path is not None else None
        self._prepared = None
        self.state = replace(
            self.state,
            selected_output_file=selected,
            conversion_available=False,
            conversion_summary=None,
            result_presentation=None,
            user_message=(
                "出力先を選択しました。" if selected else "出力先が未選択です。"
            ),
            developer_error=None,
        )
        return self.state

    def prepare_conversion(self) -> AppState:
        try:
            self._prepared = self.conversion_workflow.prepare(
                input_path=self.state.selected_file,
                output_path=self.state.selected_output_file,
                profile=self._selected_profile(),
                context=self._target_context,
            )
        except Exception as error:
            self._prepared = None
            return self._fail_state(
                "実行前チェックを完了できませんでした。",
                error,
                diagnostic_status=self.state.diagnostic_status,
            )
        summary = self._prepared.summary
        self.state = replace(
            self.state,
            conversion_summary=summary,
            conversion_available=summary.readiness.value == "READY",
            preflight_status=summary.readiness.value,
            messages=summary.blocking_reasons,
            result_summary=None,
            verification_report=None,
            user_message=(
                "変換を実行できます。内容を確認してください。"
                if not summary.blocking_reasons
                else summary.blocking_reasons[0]
            ),
            developer_error=None,
        )
        return self.state

    def execute_conversion(self, confirmed: bool) -> AppState:
        if not confirmed:
            self.state = replace(self.state, user_message="変換をキャンセルしました。")
            return self.state
        if self._prepared is None or not self.state.conversion_available:
            self.state = replace(
                self.state,
                conversion_available=False,
                user_message="実行前チェックを先に完了してください。",
            )
            return self.state
        result = self.conversion_workflow.execute(self._prepared)
        if result is None:
            self.state = replace(
                self.state,
                conversion_available=False,
                user_message="変換条件が整っていないため停止しました。",
            )
            return self.state
        output_status = (
            "成功"
            if result.output_validation_result
            and result.output_validation_result.success
            else "未完了"
        )
        result_summary = "\n".join(
            (
                f"結果: {getattr(result.status, 'value', result.status)}",
                f"入力仕訳数: {result.input_journal_count}",
                f"出力レコード数: {result.output_record_count}",
                f"借方合計: {result.debit_total}",
                f"貸方合計: {result.credit_total}",
                f"未確認の対応: {result.unresolved_mapping_count}",
                f"出力検証: {output_status}",
                f"出力先: {result.output_path if result.output_path else '生成なし'}",
            )
        )
        self.state = replace(
            self.state,
            conversion_available=False,
            preflight_status=getattr(result.status, "value", result.status),
            result_summary=result_summary,
            result_presentation=ConversionResultPresentation(
                successful=getattr(result.status, "value", result.status) == "SUCCESS",
                input_journal_count=result.input_journal_count,
                output_journal_count=result.output_journal_count,
                debit_total=str(result.debit_total),
                credit_total=str(result.credit_total),
                error_count=result.error_count,
                output_validation_success=bool(
                    result.output_validation_result
                    and result.output_validation_result.success
                ),
                output_path=result.output_path,
            ),
            verification_report=result.verification_report,
            user_message=conversion_result_message(result),
            messages=tuple(item.message for item in result.validation_results),
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
        if (
            result.status is ProfilePreflightStatus.REQUIRES_MAPPING
            and result.unknown_tax_categories
        ):
            message = (
                "会社設定に未確認の項目があります。"
                "税区分の設定が必要です。"
            )
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

    def _company_option(self, company_setting_id: str) -> CompanyOption:
        resolved = self.company_setting_service.resolve_for_source(company_setting_id)
        requires_mapping = bool(
            resolved.profile
            and (
                profile_pending_setup_field_types(resolved.profile)
                or any(
                    not mapping.is_resolved
                    for mappings in (
                        resolved.profile.subaccount_mappings,
                        resolved.profile.subaccount_context_mappings,
                        resolved.profile.department_mappings,
                        resolved.profile.tax_mappings,
                    )
                    for mapping in mappings.values()
                )
            )
        )
        return CompanyOption(
            company_setting_id=company_setting_id,
            display_name=resolved.setting.display_name,
            source_label=self._source_label(resolved.setting.expected_source_format_key),
            status_label=(
                "利用可能"
                if resolved.available and not requires_mapping
                else "確認が必要"
            ),
        )

    def company_setting_status_reason(self, company_setting_id: str) -> str:
        resolved = self.company_setting_service.resolve_for_source(company_setting_id)
        if not resolved.available or resolved.profile is None:
            return resolved.user_message or "この会社設定は利用できません。"
        pending = list(profile_pending_setup_field_types(resolved.profile))
        if any(not item.is_resolved for item in resolved.profile.tax_mappings.values()):
            pending.append("税区分")
        if any(
            not item.is_resolved
            for item in (
                *resolved.profile.subaccount_mappings.values(),
                *resolved.profile.subaccount_context_mappings.values(),
            )
        ):
            pending.append("補助科目")
        if any(
            not item.is_resolved
            for item in resolved.profile.department_mappings.values()
        ):
            pending.append("部門")
        pending = list(dict.fromkeys(pending))
        if pending:
            return "設定が完了していません: " + "、".join(pending)
        return "会社設定を利用できます。"

    def _auto_select_company_for_recognized_file(self) -> None:
        source_key = self._recognized_source_key()
        if source_key is None or not self.state.companies:
            return
        candidates = []
        for option in self.state.companies:
            resolved = self.company_setting_service.resolve_for_source(
                option.company_setting_id, source_key
            )
            if resolved.available and resolved.setting.expected_source_format_key == source_key:
                candidates.append(option.company_setting_id)
        preferences = self.preferences_store.load(set(candidates))
        selected = preferences.last_company_setting_id
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is not None:
            self.select_company_setting(selected)

    def _recognized_source_key(self) -> str | None:
        recognition = self.state.file_recognition
        if recognition is None:
            return None
        if recognition.format is RecognizedFormat.YAYOI:
            return yayoi_ae19_direct_export_observed_schema().identity.stable_key
        if recognition.format is RecognizedFormat.MONEYFORWARD:
            return moneyforward_cloud_journal_export_observed_schema().identity.stable_key
        return None

    @staticmethod
    def _source_label(source_key: str) -> str:
        if source_key == yayoi_ae19_direct_export_observed_schema().identity.stable_key:
            return "弥生"
        if source_key == moneyforward_cloud_journal_export_observed_schema().identity.stable_key:
            return "Money Forward"
        return "未対応"

    @staticmethod
    def _validate_first_release_profile(profile: ConversionProfile) -> None:
        identity_status = profile.verify_format_identity(
            yayoi_ae19_direct_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        )
        if identity_status not in {
            FormatIdentityMatchStatus.MATCH,
            FormatIdentityMatchStatus.COMPATIBLE_CANDIDATE,
        }:
            raise ConversionProfileStoreError(
                "profile format identity is outside the First Release route"
            )
        mappings = (
            *profile.account_mappings.values(),
            *profile.subaccount_mappings.values(),
            *profile.subaccount_context_mappings.values(),
            *profile.department_mappings.values(),
            *profile.tax_mappings.values(),
        )
        if any(
            mapping.status is not MappingStatus.USER_CONFIRMED
            or mapping.target_value is None
            for mapping in mappings
        ):
            raise ConversionProfileStoreError(
                "First Release profile contains unconfirmed or unresolved mappings"
            )

    def _source_candidate_identity(self) -> Any:
        if self.state.diagnostic_kind is DiagnosticKind.JDL:
            return jdl_ibex_cashbook_35_5_observed_schema_definition().identity
        return yayoi_desktop_import_25_documented_schema().identity

    def _recognize_file(self, path: Path) -> FileRecognition:
        candidates = (
            (
                RecognizedFormat.MONEYFORWARD,
                "Money Forwardの仕訳帳CSV",
                MoneyForwardInputAdapter(),
                moneyforward_cloud_journal_export_observed_schema(),
                "Money Forward",
                "Money Forward クラウド会計",
                "UNKNOWN",
            ),
            (
                RecognizedFormat.YAYOI,
                "弥生会計の仕訳データ",
                YayoiInputAdapter(),
                yayoi_ae19_direct_export_observed_schema(),
                "Yayoi",
                "Yayoi Accounting AE 19",
                "19",
            ),
        )
        for kind, label, adapter, schema, software, product, version in candidates:
            profile = FormatProfile(
                software=software,
                product=product,
                version=version,
                format_id=schema.identity.stable_key,
                encoding="cp932",
            )
            try:
                entries = adapter.read(path, profile)
            except Exception:
                continue
            dates = sorted({entry.date for entry in entries})
            return FileRecognition(
                format=kind,
                display_name=label,
                journal_count=len(entries),
                period_start=dates[0].isoformat() if dates else None,
                period_end=dates[-1].isoformat() if dates else None,
            )
        return FileRecognition(
            format=RecognizedFormat.UNKNOWN,
            display_name="未対応のCSV",
        )

    def _fail_state(
        self,
        user_message: str,
        error: Exception,
        diagnostic_status: DiagnosticStatus | None = None,
        diagnostic_kind: DiagnosticKind | None = None,
    ) -> AppState:
        self.state = replace(
            self.state,
            diagnostic_kind=diagnostic_kind or self.state.diagnostic_kind,
            diagnostic_status=diagnostic_status or self.state.diagnostic_status,
            conversion_available=False,
            user_message=user_message,
            developer_error=error.__class__.__name__,
        )
        return self.state

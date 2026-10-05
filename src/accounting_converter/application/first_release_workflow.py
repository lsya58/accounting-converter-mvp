from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from accounting_converter.adapters.input.yayoi import YayoiStructuralValidator
from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlEvidenceProfile,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionResult,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    AdapterRegistry,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
)


class FirstReleaseReadiness(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass(frozen=True)
class FirstReleaseSummary:
    readiness: FirstReleaseReadiness
    blocking_reasons: tuple[str, ...]
    source_name: str | None = None
    source_format: str = "弥生会計 AE19 直接エクスポート（確認済み範囲）"
    profile_name: str | None = None
    target_name: str = "JDL IBEX 出納帳 35.5"
    required_mapping_count: int = 0
    confirmed_mapping_count: int = 0
    unresolved_mapping_count: int = 0
    account_master_count: int = 0
    subaccount_master_count: int = 0
    department_master_count: int = 0
    tax_setting: str = "未確認"
    context_validated: bool = False
    simple_journal_count: int = 0
    compound_journal_count: int = 0
    output_path: Path | None = None


@dataclass(frozen=True)
class FirstReleasePreparedConversion:
    summary: FirstReleaseSummary
    request: ConversionRequest | None = None
    conversion_service: ConversionService | None = None


class FirstReleaseConversionWorkflow:
    """Application boundary for the evidence-limited GUI release candidate."""

    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or production_adapter_registry()

    def prepare(
        self,
        *,
        input_path: Path | None,
        output_path: Path | None,
        profile: ConversionProfile | None,
        context: JdlTargetContext | None,
    ) -> FirstReleasePreparedConversion:
        reasons = self._basic_reasons(input_path, output_path, profile, context)
        if reasons:
            return self._blocked(input_path, output_path, profile, context, reasons)
        assert input_path is not None and output_path is not None
        assert profile is not None and context is not None

        source_schema = yayoi_ae19_direct_export_observed_schema()
        target_schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        if profile.verify_format_identity(source_schema.identity, target_schema.identity).value not in {
            "MATCH",
            "COMPATIBLE_CANDIDATE",
        }:
            return self._blocked(input_path, output_path, profile, context, ("選択した変換設定の形式が一致しません。",))

        input_lookup = self.registry.get_exact_input(source_schema.identity)
        output_lookup = self.registry.get_exact_output(target_schema.identity)
        if (
            input_lookup.status is not AdapterAvailabilityStatus.EXACT
            or input_lookup.registration is None
            or input_lookup.registration.factory is None
        ):
            return self._blocked(input_path, output_path, profile, context, ("弥生入力形式に対応する処理を利用できません。",))
        if (
            output_lookup.status is not AdapterAvailabilityStatus.EXACT
            or output_lookup.registration is None
            or output_lookup.registration.runtime_factory is None
        ):
            return self._blocked(input_path, output_path, profile, context, ("JDL出力形式に対応する処理を利用できません。",))

        input_profile = FormatProfile(
            software="Yayoi",
            product="Yayoi Accounting AE 19",
            version="19",
            format_id=source_schema.identity.stable_key,
            encoding="cp932",
        )
        input_adapter = input_lookup.registration.factory()
        structural = YayoiStructuralValidator(input_adapter)
        structural_results = structural.validate(input_path, input_profile)
        if structural_results:
            return self._blocked(input_path, output_path, profile, context, ("入力CSVの文字コードまたは25項目構造を確認してください。",))
        try:
            entries = tuple(input_adapter.read(input_path, input_profile))
        except Exception:
            return self._blocked(input_path, output_path, profile, context, ("入力CSVを安全に解析できませんでした。",))

        requirements = MappingRequirementExtractor().extract(entries, profile)
        required = len(requirements.all_requirements())
        unresolved = requirements.unresolved_count
        feature_reasons = self._feature_reasons(entries, context)
        assignments, route_reasons = self._route_assignments(entries)
        reasons = tuple(feature_reasons + route_reasons)
        if unresolved:
            reasons += ("未確認の科目対応があります。",)

        route = ExplicitJdlEvidenceRoutePolicy(
            assignments,
            route_id="GUI-FIRST-RELEASE-VERIFIED-SCOPE-V0",
        )
        if not reasons:
            mapping_result = MappingEngine(
                mapping_rule_set_from_profile(profile)
            ).apply(entries)
            if mapping_result.unresolved_count or mapping_result.validation_results:
                reasons += ("科目対応を安全に適用できません。",)
            else:
                route_result = route.apply(mapping_result.entries)
                if route_result.validation_results:
                    reasons += ("仕訳ごとのJDL出力区分を確認できません。",)
                elif any(not entry.is_balanced() for entry in route_result.entries):
                    reasons += ("貸借金額が一致しない仕訳があります。",)
                else:
                    runtime = output_lookup.registration.runtime_factory.resolve(
                        jdl_ibex_35_5_output_profile(), profile, context
                    )
                    if not runtime.resolved:
                        reasons += ("変換設定とJDL設定の整合を確認できません。",)
                    else:
                        assert runtime.output_adapter is not None
                        output_preflight = runtime.output_adapter.preflight(
                            route_result.entries,
                            jdl_ibex_35_5_output_profile(),
                        )
                        if output_preflight:
                            reasons += tuple(
                                self._preflight_reason(result.rule_id)
                                for result in output_preflight
                            )

        summary = self._summary(
            input_path,
            output_path,
            profile,
            context,
            reasons,
            required,
            unresolved,
            entries,
        )
        if reasons:
            return FirstReleasePreparedConversion(summary)

        service = ConversionService(
            input_adapter=input_adapter,
            structural_validator=structural,
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(),)),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=route,
            runtime_output_factory=output_lookup.registration.runtime_factory,
        )
        request = ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            input_profile=input_profile,
            output_profile=jdl_ibex_35_5_output_profile(),
            overwrite=False,
            conversion_profile=profile,
            target_runtime_context=context,
        )
        return FirstReleasePreparedConversion(summary, request, service)

    @staticmethod
    def _preflight_reason(rule_id: str) -> str:
        if "MULTIGROUP" in rule_id:
            return "複数仕訳の並びが実機検証済み範囲外です。"
        if "CP932" in rule_id:
            return "JDL CSVへ保存できない文字が含まれています。"
        if "SHAPE" in rule_id or "EVIDENCE" in rule_id:
            return "未検証の仕訳構成が含まれています。"
        return "JDL出力の実機検証済み範囲を超えています。"

    def execute(self, prepared: FirstReleasePreparedConversion) -> ConversionResult | None:
        if (
            prepared.summary.readiness is not FirstReleaseReadiness.READY
            or prepared.request is None
            or prepared.conversion_service is None
        ):
            return None
        return prepared.conversion_service.convert(prepared.request)

    def _basic_reasons(self, input_path, output_path, profile, context) -> tuple[str, ...]:
        reasons: list[str] = []
        if input_path is None or not input_path.is_file():
            reasons.append("入力ファイルを選択してください。")
        if profile is None:
            reasons.append("変換設定を選択してください。")
        if context is None:
            reasons.append("確認済みJDL設定を選択してください。")
        if output_path is None:
            reasons.append("出力先を選択してください。")
        elif output_path.exists():
            reasons.append("出力先は既に存在するため生成できません。")
        if input_path is not None and output_path is not None:
            if input_path.resolve(strict=False) == output_path.resolve(strict=False):
                reasons.append("入力ファイルと出力先に同じパスは指定できません。")
        return tuple(reasons)

    def _feature_reasons(self, entries: tuple[JournalEntry, ...], context: JdlTargetContext) -> list[str]:
        reasons: list[str] = []
        if context.product != "JDL IBEX 出納帳" or context.version != "35.5":
            reasons.append("取込先はJDL IBEX 出納帳 35.5だけに対応しています。")
        if context.tax_processing_mode is not JdlTaxProcessingMode.EXEMPT:
            reasons.append("First Releaseは免税の事業所だけに対応しています。")
        if context.department_processing_enabled or context.departments:
            reasons.append("First Releaseは部門を使用しない設定だけに対応しています。")
        if context.subaccounts:
            reasons.append("First Releaseは補助科目を使用しない設定だけに対応しています。")
        for entry in entries:
            for line in entry.lines:
                if line.sub_account:
                    reasons.append("補助科目を含む仕訳は現在の対応範囲外です。")
                if line.department:
                    reasons.append("部門を含む仕訳は現在の対応範囲外です。")
                if line.tax_info is not None and (
                    line.tax_info.category or line.tax_info.tax_amount is not None
                ):
                    reasons.append("税情報を含む仕訳は現在の対応範囲外です。")
        return list(dict.fromkeys(reasons))

    def _route_assignments(self, entries: tuple[JournalEntry, ...]):
        assignments: dict[str, JdlEvidenceProfile] = {}
        reasons: list[str] = []
        for entry in entries:
            debit = sum(line.side is Side.DEBIT for line in entry.lines)
            credit = sum(line.side is Side.CREDIT for line in entry.lines)
            if (debit, credit) == (1, 1):
                assignments[entry.id] = JdlEvidenceProfile.BASIC_1111
            elif (debit, credit) == (1, 3):
                assignments[entry.id] = JdlEvidenceProfile.COMPOUND_1D3C
            else:
                reasons.append("未検証の仕訳構成が含まれています。")
        return assignments, reasons

    def _blocked(self, input_path, output_path, profile, context, reasons):
        return FirstReleasePreparedConversion(
            self._summary(input_path, output_path, profile, context, tuple(reasons), 0, 0, ())
        )

    def _summary(self, input_path, output_path, profile, context, reasons, required, unresolved, entries):
        return FirstReleaseSummary(
            readiness=(FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY),
            blocking_reasons=tuple(reasons),
            source_name=input_path.name if input_path else None,
            profile_name=profile.profile_name if profile else None,
            required_mapping_count=required,
            confirmed_mapping_count=required - unresolved,
            unresolved_mapping_count=unresolved,
            account_master_count=len(context.account_master) if context else 0,
            subaccount_master_count=len(context.subaccounts) if context else 0,
            department_master_count=len(context.departments) if context else 0,
            tax_setting=("免税" if context and context.tax_processing_mode is JdlTaxProcessingMode.EXEMPT else "未対応または未確認"),
            context_validated=context is not None,
            simple_journal_count=sum(not entry.is_compound() for entry in entries),
            compound_journal_count=sum(entry.is_compound() for entry in entries),
            output_path=output_path,
        )


def conversion_result_message(result: ConversionResult) -> str:
    if result.status == ConversionStatus.SUCCESS:
        return "変換が完了しました。JDL取込前に出力先と検証結果を確認してください。"
    return "変換を停止しました。正式な出力ファイルは生成されていません。"

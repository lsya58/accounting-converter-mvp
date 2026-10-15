from __future__ import annotations

from pathlib import Path

from accounting_converter.adapters.input.moneyforward import (
    MoneyForwardInputAdapter,
    MoneyForwardStructuralValidator,
)
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
)
from accounting_converter.application.first_release_workflow import (
    FirstReleasePreparedConversion,
    FirstReleaseReadiness,
    FirstReleaseSummary,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.moneyforward_jdl_loss import (
    MoneyForwardToJdlLossRule,
    moneyforward_verified_description_rows,
)
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side
from accounting_converter.domain.mapping import MappingStatus
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
    moneyforward_cloud_journal_export_observed_schema,
)


_COMPOUND_PROFILES = {
    (1, 3): JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS,
    (2, 1): JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS,
    (2, 2): JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS,
    (2, 3): JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS,
    (4, 6): JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS,
    (5, 7): JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS,
    (5, 8): JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS,
}

_TAX_ROUTES = {
    (Side.DEBIT, "課税仕入 10%", True): (
        JdlEvidenceProfile.TAX_PURCHASE_10_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-PURCHASE-10-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.DEBIT, "課税仕入 10%", False): (
        JdlEvidenceProfile.TAX_INCLUDED_1111,
        "EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001",
    ),
    (Side.CREDIT, "課税売上 10%", True): (
        JdlEvidenceProfile.TAX_SALES_10_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-SALES-10-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.DEBIT, "課税仕入 (軽)8%", True): (
        JdlEvidenceProfile.TAX_PURCHASE_REDUCED_8_INCLUDED_1111,
        "EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.CREDIT, "課税売上 (軽)8%", True): (
        JdlEvidenceProfile.TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-SALES-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.DEBIT, "非課税仕入", True): (
        JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-NONTAXABLE-PURCHASE-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.CREDIT, "非課税売上", True): (
        JdlEvidenceProfile.TAX_NON_TAXABLE_SALES_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001",
    ),
    (Side.DEBIT, "対象外", True): (
        JdlEvidenceProfile.TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED_1111,
        "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001",
    ),
}


class MoneyForwardConversionWorkflow:
    """Exact CompanySetting-gated MF observed CSV to JDL workflow."""

    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self.registry = registry or production_adapter_registry()

    def prepare(
        self,
        *,
        input_path: Path | None,
        output_path: Path | None,
        profile: ConversionProfile | None,
        context: JdlTargetContext | None,
        company_setting_validated: bool = False,
        company_setting_error: str | None = None,
    ) -> FirstReleasePreparedConversion:
        reasons = self._basic_reasons(
            input_path,
            output_path,
            profile,
            context,
            company_setting_validated,
            company_setting_error,
        )
        if reasons:
            return self._blocked(input_path, output_path, profile, context, reasons)
        assert input_path is not None and output_path is not None
        assert profile is not None and context is not None

        source_schema = moneyforward_cloud_journal_export_observed_schema()
        target_schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        if profile.verify_format_identity(source_schema.identity, target_schema.identity).value != "MATCH":
            return self._blocked(
                input_path, output_path, profile, context,
                ("会社設定と入力ファイルの種類が一致しません。",),
            )

        output_lookup = self.registry.get_exact_output(target_schema.identity)
        if (
            output_lookup.status is not AdapterAvailabilityStatus.EXACT
            or output_lookup.registration is None
            or output_lookup.registration.runtime_factory is None
        ):
            return self._blocked(
                input_path, output_path, profile, context,
                ("JDL出力処理を利用できません。",),
            )

        input_profile = FormatProfile(
            software="Money Forward",
            product="Money Forward クラウド会計",
            version="UNKNOWN",
            format_id=source_schema.identity.stable_key,
            encoding="cp932",
        )
        input_adapter = MoneyForwardInputAdapter()
        structural = MoneyForwardStructuralValidator(input_adapter)
        if structural.validate(input_path, input_profile):
            return self._blocked(
                input_path, output_path, profile, context,
                ("Money Forwardの仕訳帳CSVを安全に解析できませんでした。",),
            )
        try:
            entries = tuple(input_adapter.read(input_path, input_profile))
        except Exception:
            return self._blocked(
                input_path, output_path, profile, context,
                ("Money Forwardの仕訳帳CSVを安全に解析できませんでした。",),
            )

        requirements = MappingRequirementExtractor().extract(entries, profile)
        unconfirmed_count = sum(
            1
            for item in requirements.all_requirements()
            if item.requires_confirmation
            or item.current_mapping_status is not MappingStatus.USER_CONFIRMED
        )
        reasons = list(self._mapping_reasons(requirements))
        assignments, route_reasons, unsupported_journals = self._route_assignments(
            entries, profile, context
        )
        reasons.extend(route_reasons)
        loss_results = ValidationPipeline((MoneyForwardToJdlLossRule(),)).validate(entries)
        reasons.extend(self._loss_reason(item.field) for item in loss_results)
        reasons = list(dict.fromkeys(reasons))

        route = ExplicitJdlEvidenceRoutePolicy(
            assignments,
            route_id="GUI-MF-EXACT-COMPANY-SETTING-V0",
        )
        mapping_engine = MappingEngine(mapping_rule_set_from_profile(profile))
        if not reasons:
            mapping_result = mapping_engine.apply(entries)
            if mapping_result.unresolved_count or mapping_result.validation_results:
                reasons.append("会社設定に未確認の対応があります。")
            else:
                route_result = route.apply(mapping_result.entries)
                if route_result.validation_results:
                    reasons.append("未検証の仕訳構成が含まれています。")
                else:
                    runtime = output_lookup.registration.runtime_factory.resolve(
                        jdl_ibex_35_5_output_profile(), profile, context
                    )
                    if not runtime.resolved or runtime.output_adapter is None:
                        reasons.append("JDL科目一覧が更新されています。会社設定を確認してください。")
                    else:
                        output_results = runtime.output_adapter.preflight(
                            route_result.entries, jdl_ibex_35_5_output_profile()
                        )
                        reasons.extend(self._preflight_reason(item.rule_id) for item in output_results)

        summary = self._summary(
            input_path, output_path, profile, context, tuple(dict.fromkeys(reasons)),
            len(requirements.all_requirements()), unconfirmed_count, entries,
            unsupported_shape_count=len(unsupported_journals),
            optional_field_blocker_count=len(
                {item.journal_id for item in loss_results if item.journal_id}
            ),
        )
        if reasons:
            return FirstReleasePreparedConversion(summary)

        service = ConversionService(
            input_adapter=input_adapter,
            structural_validator=structural,
            mapping_engine=mapping_engine,
            business_validator=ValidationPipeline((BalanceRule(), MoneyForwardToJdlLossRule())),
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
    def execute(prepared: FirstReleasePreparedConversion) -> ConversionResult | None:
        if (
            prepared.summary.readiness is not FirstReleaseReadiness.READY
            or prepared.request is None
            or prepared.conversion_service is None
        ):
            return None
        return prepared.conversion_service.convert(prepared.request)

    @staticmethod
    def _mapping_reasons(requirements) -> tuple[str, ...]:
        reasons: list[str] = []
        groups = (
            (requirements.accounts, "科目の確認が必要です。"),
            (requirements.subaccounts, "補助科目の確認が必要です。"),
            (requirements.departments, "部門を含む仕訳は現在の正式変換範囲外です。"),
            (requirements.tax_categories, "税区分の確認が必要です。"),
        )
        for items, message in groups:
            if any(
                item.requires_confirmation
                or item.current_mapping_status is not MappingStatus.USER_CONFIRMED
                for item in items
            ):
                reasons.append(message)
        return tuple(reasons)

    def _route_assignments(self, entries, profile, context):
        assignments: dict[str, JdlEvidenceProfile] = {}
        reasons: list[str] = []
        unsupported: set[str] = set()
        for entry in entries:
            debit_count = sum(line.side is Side.DEBIT for line in entry.lines)
            credit_count = sum(line.side is Side.CREDIT for line in entry.lines)
            shape = (debit_count, credit_count)
            if shape in _COMPOUND_PROFILES:
                if moneyforward_verified_description_rows(entry) is None:
                    reasons.append("行単位の摘要を保持できない複合仕訳があります。")
                    unsupported.add(entry.id)
                elif context.tax_processing_mode is not JdlTaxProcessingMode.EXEMPT:
                    reasons.append("このJDL税設定では複合仕訳の実機確認が完了していません。")
                    unsupported.add(entry.id)
                else:
                    assignments[entry.id] = _COMPOUND_PROFILES[shape]
                continue
            if shape != (1, 1):
                reasons.append("未検証の仕訳構成が含まれています。")
                unsupported.add(entry.id)
                continue
            tax_lines = [
                line for line in entry.lines
                if line.tax_info is not None and line.tax_info.category
            ]
            if not tax_lines:
                if context.tax_processing_mode is JdlTaxProcessingMode.EXEMPT and not any(
                    line.sub_account or line.department for line in entry.lines
                ):
                    assignments[entry.id] = JdlEvidenceProfile.BASIC_1111
                else:
                    reasons.append("この仕訳のJDL出力条件は実機確認済み範囲外です。")
                    unsupported.add(entry.id)
                continue
            if len(tax_lines) != 1:
                reasons.append("貸借両側の税区分を持つ仕訳は現在の正式変換範囲外です。")
                unsupported.add(entry.id)
                continue
            line = tax_lines[0]
            source_tax = line.tax_info.category
            mapping = profile.tax_mappings.get(source_tax)
            route = _TAX_ROUTES.get((line.side, source_tax, bool(line.sub_account)))
            if (
                route is None
                or mapping is None
                or mapping.status is not MappingStatus.USER_CONFIRMED
                or mapping.metadata.get("jdl_evidence_id") != route[1]
            ):
                reasons.append("税区分確認が必要です。「税区分を確認」から設定してください。")
                continue
            assignments[entry.id] = route[0]
        return assignments, reasons, unsupported

    @staticmethod
    def _loss_reason(field: str | None) -> str:
        if field == "trade_partner":
            return "このデータは現在変換できません。取引先情報の扱いを確認してください。"
        if field == "description":
            return "未検証の複数摘要を含む仕訳があります。"
        return "JDLへ安全に保持できない項目が含まれています。"

    @staticmethod
    def _preflight_reason(rule_id: str) -> str:
        if "ACCOUNT" in rule_id or "SUBACCOUNT" in rule_id:
            return "JDL科目一覧と科目対応を確認してください。"
        if "DESCRIPTION" in rule_id or "CP932" in rule_id:
            return "JDLへ保存できない摘要が含まれています。"
        if "TAX" in rule_id:
            return "税区分確認が必要です。「税区分を確認」から設定してください。"
        return "未検証のJDL出力条件が含まれています。"

    @staticmethod
    def _basic_reasons(
        input_path,
        output_path,
        profile,
        context,
        company_validated,
        company_error,
    ):
        reasons: list[str] = []
        if not company_validated:
            reasons.append(company_error or "会社設定を選択してください。")
        if input_path is None or not input_path.is_file():
            reasons.append("入力ファイルを選択してください。")
        if profile is None:
            reasons.append("会社設定の対応設定を確認してください。")
        if context is None:
            reasons.append("JDL科目一覧を設定してください。")
        if output_path is None:
            reasons.append("出力先を選択してください。")
        elif output_path.exists():
            reasons.append("出力先は既に存在するため生成できません。")
        if input_path is not None and output_path is not None:
            if input_path.resolve(strict=False) == output_path.resolve(strict=False):
                reasons.append("入力ファイルと出力先に同じパスは指定できません。")
        return tuple(reasons)

    def _blocked(self, input_path, output_path, profile, context, reasons):
        return FirstReleasePreparedConversion(
            self._summary(input_path, output_path, profile, context, reasons, 0, 0, ())
        )

    @staticmethod
    def _summary(
        input_path,
        output_path,
        profile,
        context,
        reasons,
        required,
        unresolved,
        entries,
        *,
        unsupported_shape_count=0,
        optional_field_blocker_count=0,
    ):
        return FirstReleaseSummary(
            readiness=FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY,
            blocking_reasons=tuple(reasons),
            source_name=input_path.name if input_path else None,
            source_format="Money Forward クラウド会計 仕訳帳CSV（確認済み19項目）",
            profile_name=profile.profile_name if profile else None,
            required_mapping_count=required,
            confirmed_mapping_count=required - unresolved,
            unresolved_mapping_count=unresolved,
            account_master_count=len(context.account_master) if context else 0,
            subaccount_master_count=len(context.subaccounts) if context else 0,
            department_master_count=len(context.departments) if context else 0,
            tax_setting=(context.tax_processing_mode.value if context else "未確認"),
            context_validated=context is not None,
            simple_journal_count=sum(not entry.is_compound() for entry in entries),
            compound_journal_count=sum(entry.is_compound() for entry in entries),
            output_path=output_path,
            unsupported_shape_count=unsupported_shape_count,
            optional_field_blocker_count=optional_field_blocker_count,
        )

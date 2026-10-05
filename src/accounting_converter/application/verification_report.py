from __future__ import annotations

from dataclasses import dataclass

from accounting_converter import __version__


_UNSUPPORTED_OUTPUT_PROFILE_RULES = {
    "JDL-OUT-BASIC-FEATURE",
    "JDL-OUT-COMPOUND-FEATURE",
    "JDL-OUT-COMPOUND-SHAPE",
    "JDL-OUT-COMPOUND-TAX-MODE",
    "JDL-OUT-DEPARTMENT-COMBINATION",
    "JDL-OUT-EVIDENCE-PROFILE",
    "JDL-OUT-MULTIGROUP-SCOPE",
    "JDL-OUT-SIMPLE-SHAPE",
    "JDL-OUT-SUBACCOUNT-COMBINATION",
    "JDL-OUT-TAX-COMBINATION",
}


@dataclass(frozen=True)
class VerificationReportGenerator:
    system_version: str = __version__

    def generate(self, result, request) -> str:
        output_validation = "not_run"
        if result.output_validation_result is not None:
            output_validation = (
                "success" if result.output_validation_result.success else "failed"
            )
        evidence_profiles = "not_run"
        output_schema_identity = "not_run"
        unsupported_profile_count = sum(
            result.rule_id in _UNSUPPORTED_OUTPUT_PROFILE_RULES
            for result in result.validation_results
        )
        if result.output_validation_result is not None:
            evidence_profiles = ",".join(
                result.output_validation_result.evidence_profiles
            ) or "none"
            output_schema_identity = (
                result.output_validation_result.output_schema_identity or "unknown"
            )
            unsupported_profile_count = (
                result.output_validation_result.unsupported_profile_count
            )

        context_lines: list[str] = []
        summary_method = getattr(
            request.target_runtime_context,
            "privacy_safe_summary",
            None,
        )
        if callable(summary_method):
            summary = summary_method()
            context_failed = any(
                item.rule_id.startswith("JDL-CONTEXT-")
                for item in result.validation_results
            )
            mapping_failed = any(
                "MAPPING-MISMATCH" in item.rule_id
                for item in result.validation_results
            )
            context_lines = [
                f"target product/version: {summary['target_product']} / {summary['target_version']}",
                f"target context confirmation: {summary['context_confirmation']}",
                f"target context provenance: {summary['context_provenance']}",
                f"target context validation: {'failed' if context_failed else 'success'}",
                f"account master count: {summary['account_master_count']}",
                f"subaccount master count: {summary['subaccount_master_count']}",
                f"department master count: {summary['department_master_count']}",
                f"tax/company context: {summary['tax_company_context']}",
                f"mapping/context consistency: {'failed' if mapping_failed else 'success'}",
            ]

        mapping_required = 0
        mapping_confirmed = 0
        profile = request.conversion_profile
        if profile is not None:
            mappings = (
                *profile.account_mappings.values(),
                *profile.subaccount_mappings.values(),
                *profile.subaccount_context_mappings.values(),
                *profile.department_mappings.values(),
                *profile.tax_mappings.values(),
            )
            mapping_required = len(mappings)
            mapping_confirmed = sum(mapping.is_resolved for mapping in mappings)

        lines = [
            "変換検証レポート",
            "",
            f"検証日時: {result.completed_at.isoformat()}",
            f"システムバージョン: {self.system_version}",
            f"ステータス: {result.status.value if hasattr(result.status, 'value') else result.status}",
            "",
            f"入力ファイル名: {request.input_path.name}",
            f"出力ファイル名: {request.output_path.name}",
            f"入力形式: {self._profile_name(request.input_profile)}",
            f"出力形式: {self._profile_name(request.output_profile)}",
            "",
            f"input record count: {result.input_record_count}",
            f"input journal count: {result.input_journal_count}",
            f"output record count: {result.output_record_count}",
            f"output journal count: {result.output_journal_count}",
            f"借方総額: {result.debit_total}",
            f"貸方総額: {result.credit_total}",
            f"Error件数: {result.error_count}",
            f"Warning件数: {result.warning_count}",
            f"required mapping件数: {mapping_required}",
            f"confirmed mapping件数: {mapping_confirmed}",
            f"unresolved mapping件数: {result.unresolved_mapping_count}",
            f"unsupported output profile件数: {unsupported_profile_count}",
            f"JDL Evidence profile: {evidence_profiles}",
            f"output schema identity: {output_schema_identity}",
            f"Output Validation結果: {output_validation}",
            *context_lines,
            "",
            "注意: 本レポートは本システムが検証可能な範囲を示すものであり、取込先ソフトウェア側の障害を断定しません。",
        ]
        return "\n".join(lines)

    def _profile_name(self, profile) -> str:
        return (
            f"{profile.software} / {profile.product} / "
            f"{profile.version} / {profile.format_id}"
        )

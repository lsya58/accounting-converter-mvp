from __future__ import annotations

from dataclasses import dataclass

from accounting_converter import __version__


@dataclass(frozen=True)
class VerificationReportGenerator:
    system_version: str = __version__

    def generate(self, result, request) -> str:
        output_validation = "not_run"
        if result.output_validation_result is not None:
            output_validation = (
                "success" if result.output_validation_result.success else "failed"
            )

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
            f"unresolved mapping件数: {result.unresolved_mapping_count}",
            f"Output Validation結果: {output_validation}",
            "",
            "注意: 本レポートは本システムが検証可能な範囲を示すものであり、取込先ソフトウェア側の障害を断定しません。",
        ]
        return "\n".join(lines)

    def _profile_name(self, profile) -> str:
        return (
            f"{profile.software} / {profile.product} / "
            f"{profile.version} / {profile.format_id}"
        )

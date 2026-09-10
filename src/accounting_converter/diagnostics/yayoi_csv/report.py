from __future__ import annotations

from .models import YayoiCsvAnalysisResult


class YayoiCsvDiagnosticReportGenerator:
    def generate_text(self, analysis: YayoiCsvAnalysisResult) -> str:
        comparison = analysis.official_comparison
        amount = analysis.amount_observation
        lines = [
            "弥生CSV 診断結果",
            "",
            "ファイル:",
            analysis.file_name,
            "",
            "Official documented spec vs Observed CSV",
            f"official column count: {comparison.official_column_count}",
            f"observed dominant column count: {analysis.dominant_column_count}",
            f"structural match status: {comparison.structural_match_status.value}",
            f"formal_profile_ready: {str(comparison.formal_profile_ready).lower()}",
            f"human_review_required: {str(comparison.human_review_required).lower()}",
            "",
            "CSV観測:",
            f"encoding: {analysis.encoding}",
            f"BOM: {analysis.has_bom}",
            f"line ending: {analysis.line_ending}",
            f"delimiter: {analysis.delimiter}",
            f"physical lines: {analysis.total_physical_lines}",
            f"data records: {analysis.data_record_count}",
            f"CSV parseable: {analysis.csv_parseable}",
            "",
            "ヘッダー観測:",
            f"detected: {analysis.header_observation.detected}",
            f"row: {analysis.header_observation.row_number}",
            f"exact official header: {analysis.header_observation.exact_official_header}",
        ]
        lines.extend(["", "列数分布:"])
        if analysis.row_column_count_distribution:
            lines.extend(
                f"{count}: {row_count} rows"
                for count, row_count in analysis.row_column_count_distribution
            )
        else:
            lines.append("なし")

        lines.extend(["", "識別フラグ観測:"])
        if analysis.flag_observation.official_flag_counts:
            lines.extend(
                f"{flag}: {count}"
                for flag, count in analysis.flag_observation.official_flag_counts
            )
        else:
            lines.append("公式ドキュメント上の識別フラグは観測されていません。")
        if analysis.flag_observation.unknown_flag_counts:
            lines.append("Unknown observed flags:")
            lines.extend(
                f"{flag}: {count}"
                for flag, count in analysis.flag_observation.unknown_flag_counts
            )

        lines.extend(
            [
                "",
                "Observed journal group candidates:",
                f"single-record candidates: {analysis.single_record_candidate_count}",
                f"multi-record candidates: {analysis.multi_record_candidate_count}",
                f"malformed/unresolved candidates: {analysis.malformed_group_candidate_count}",
                f"total candidates: {analysis.group_candidate_count}",
            ]
        )

        if analysis.malformed_group_candidate_count:
            lines.extend(["", "グルーピング未解決候補:"])
            for candidate in analysis.group_candidates:
                if candidate.malformed_reason:
                    lines.append(
                        f"row {candidate.start_row_number}: {candidate.status.value} "
                        f"({candidate.malformed_reason})"
                    )

        lines.extend(
            [
                "",
                "会計安全性チェック:",
                "debit total: redacted",
                "credit total: redacted",
                f"balanced: {amount.balanced}",
                f"amount parse errors: {amount.amount_parse_error_count}",
                f"amount unknowns: {amount.amount_unknown_count}",
                f"date parse candidate errors: {amount.date_parse_candidate_error_count}",
            ]
        )
        lines.extend(
            [
                "",
                "項目入力状況:",
                f"trailing empty fields: {dict(analysis.field_population_observation.trailing_empty_field_count_distribution)}",
                f"tax field nonempty counts: {dict(analysis.field_population_observation.tax_field_nonempty_counts)}",
                f"sub account field population counts: {dict(analysis.field_population_observation.sub_account_field_population_counts)}",
                f"department field population counts: {dict(analysis.field_population_observation.department_field_population_counts)}",
            ]
        )

        lines.extend(["", "検出事項:"])
        if not analysis.validation_results:
            lines.append("INFO: 観測可能な構造上の問題は検出されませんでした。")
        else:
            lines.extend(
                f"{result.severity.value}: {result.rule_id}: {result.message}"
                for result in analysis.validation_results
            )

        lines.extend(
            [
                "",
                "注意:",
                "本診断は弥生公式ドキュメント上の25項目仕様との構造比較です。",
                "製品・バージョン・実CSVの確認状態はEvidenceごとに分離して扱います。",
                "正式YayoiFormatProfileへは自動昇格しません。",
                "会計本文、摘要全文、取引先名、個別仕訳金額はレポートへ出力しません。",
            ]
        )
        return "\n".join(lines)

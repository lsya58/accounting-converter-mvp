from __future__ import annotations

from collections import Counter

from accounting_converter.domain.validation import Severity

from .models import AccountingSide, JdlCsvAnalysisResult, JdlMasterType


class JdlCsvDiagnosticReportGenerator:
    def generate_text(self, analysis: JdlCsvAnalysisResult) -> str:
        record_counts = Counter(
            line.column_count for line in analysis.journal_record_lines
        )
        lines = [
            "JDL CSV 診断結果",
            "",
            "ファイル:",
            analysis.file_name,
            "",
            "文字コード:",
            analysis.encoding,
            "",
            "区切り文字:",
            analysis.delimiter,
            "",
            "物理行:",
            str(analysis.total_physical_lines),
            "",
            "データ行:",
            str(analysis.data_line_count),
            "",
            "構造:",
            f"Header columns: {analysis.header_column_count}",
            "Record columns:",
        ]
        if record_counts:
            lines.extend(
                f"{count}: {records} records"
                for count, records in sorted(record_counts.items())
            )
        else:
            lines.append("0: 0 records")

        lines.extend(["", "検出事項:"])
        if not analysis.validation_results:
            lines.append("INFO: 本システムが検証可能なCSV構造上の問題は検出されませんでした。")
        for result in analysis.validation_results:
            row = ""
            if result.source_reference and result.source_reference.row_number is not None:
                row = f" 行 {result.source_reference.row_number}:"
            lines.append(f"{result.severity.value}:{row} {result.message}")
            if result.input_value is not None:
                lines.append(str(result.input_value))

        if analysis.master_mismatch_summary.total_count:
            lines.extend(
                [
                    "",
                    "JDL取込診断",
                    "",
                    "検出されたマスター不一致:",
                ]
            )
            for type_key, count in analysis.master_mismatch_summary.counts_by_type:
                lines.append(f"{self._display_type_key(type_key)}: {count}件")
            lines.extend(["", "主な不一致値:"])
            for item in analysis.master_mismatch_summary.items:
                value = item.source_value or "(値未特定)"
                account = f" / 勘定科目: {item.account_value}" if item.account_value else ""
                lines.append(f"{value}: {item.count}件{account}")
            lines.extend(
                [
                    "",
                    "考えられる確認事項:",
                    "- 取込先JDLに該当マスターが登録されているか",
                    "- 補助科目が正しい勘定科目に所属しているか",
                    "- 移行元と移行先で補助科目名/コードが一致しているか",
                    "- 勘定科目、部門、税区分など補助科目以外の差異がないか",
                ]
            )

        if any(result.severity in {Severity.ERROR, Severity.FATAL} for result in analysis.validation_results):
            judgment = "JDL取込可能とは判定できません。"
        else:
            judgment = "本システムが検証可能なCSV構造上のErrorは検出されていません。"

        lines.extend(
            [
                "",
                "現時点の判定:",
                judgment,
                "",
                "※JDL自体の障害を断定するものではありません。",
            ]
        )
        return "\n".join(lines)

    def _display_type_key(self, type_key: str) -> str:
        labels = {
            f"{AccountingSide.DEBIT.value}:{JdlMasterType.ACCOUNT.value}": "借方勘定科目",
            f"{AccountingSide.CREDIT.value}:{JdlMasterType.ACCOUNT.value}": "貸方勘定科目",
            f"{AccountingSide.DEBIT.value}:{JdlMasterType.SUB_ACCOUNT.value}": "借方補助",
            f"{AccountingSide.CREDIT.value}:{JdlMasterType.SUB_ACCOUNT.value}": "貸方補助",
            f"{AccountingSide.DEBIT.value}:{JdlMasterType.DEPARTMENT.value}": "借方部門",
            f"{AccountingSide.CREDIT.value}:{JdlMasterType.DEPARTMENT.value}": "貸方部門",
            JdlMasterType.DEPARTMENT.value: "部門",
            JdlMasterType.TAX_CATEGORY.value: "税区分",
        }
        return labels.get(type_key, type_key)

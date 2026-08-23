from __future__ import annotations

from collections import Counter

from accounting_converter.domain.validation import Severity

from .models import AccountingSide, JdlCsvAnalysisResult, JdlMasterType, MasterMismatchSummaryItem


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

        if analysis.observed_schema is not None:
            lines.extend(
                [
                    "",
                    "Observed Schema:",
                    f"product: {analysis.observed_schema.product}",
                    f"observed_version: {analysis.observed_schema.observed_version}",
                    f"encoding: {analysis.observed_schema.encoding}",
                    f"BOM: {analysis.observed_schema.has_bom}",
                    f"line_ending: {analysis.observed_schema.line_ending}",
                    f"journal_column_count: {analysis.observed_schema.journal_column_count}",
                    f"journal_count: {analysis.observed_schema.journal_count}",
                    "formal_format_profile: false",
                ]
            )

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
            for master_type, count in analysis.master_mismatch_summary.counts_by_master_type:
                lines.append(f"{self._display_master_type(master_type)}: {count}件")
            lines.extend(["", "借方/貸方別内訳:"])
            for type_key, count in analysis.master_mismatch_summary.counts_by_type:
                lines.append(f"{self._display_type_key(type_key)}: {count}件")
            lines.extend(["", "主な不一致値:"])
            lines.extend(self._format_mismatch_items(analysis.master_mismatch_summary.items))
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

    def _display_master_type(self, master_type: str) -> str:
        labels = {
            JdlMasterType.ACCOUNT.value: "科目不一致",
            JdlMasterType.SUB_ACCOUNT.value: "補助科目不一致",
            JdlMasterType.DEPARTMENT.value: "部門不一致",
            JdlMasterType.TAX_CATEGORY.value: "税区分不一致",
        }
        return labels.get(master_type, master_type)

    def _format_mismatch_items(
        self, items: tuple[MasterMismatchSummaryItem, ...]
    ) -> list[str]:
        grouped: dict[tuple[JdlMasterType, str | None], list[MasterMismatchSummaryItem]] = {}
        for item in items:
            grouped.setdefault((item.master_type, item.account_value), []).append(item)

        lines: list[str] = []
        for (master_type, account_value), group_items in sorted(
            grouped.items(),
            key=lambda entry: (
                entry[0][0].value,
                entry[0][1] or "",
            ),
        ):
            if master_type is JdlMasterType.SUB_ACCOUNT and account_value:
                lines.append(f"{account_value}:")
            for item in sorted(group_items, key=lambda value: (-value.count, value.first_row)):
                value = item.source_value or "(値未特定)"
                side = self._display_side(item.side)
                lines.append(f"{value}: {item.count}件 ({side})")
        return lines

    def _display_side(self, side: AccountingSide) -> str:
        labels = {
            AccountingSide.DEBIT: "借方",
            AccountingSide.CREDIT: "貸方",
            AccountingSide.NONE: "共通",
            AccountingSide.UNKNOWN: "不明",
        }
        return labels.get(side, side.value)

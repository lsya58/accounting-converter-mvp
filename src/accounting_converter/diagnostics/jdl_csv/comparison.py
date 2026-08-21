from __future__ import annotations

from accounting_converter.domain.validation import Severity, ValidationResult

from .models import JdlCsvSchemaComparison, JdlCsvSchemaFingerprint


class JdlCsvFingerprintComparator:
    def compare(
        self,
        baseline: JdlCsvSchemaFingerprint,
        target: JdlCsvSchemaFingerprint,
    ) -> JdlCsvSchemaComparison:
        differences: list[ValidationResult] = []
        self._compare_value(differences, "encoding", baseline.encoding, target.encoding)
        self._compare_value(
            differences, "delimiter", baseline.delimiter, target.delimiter
        )
        self._compare_value(
            differences, "column_count", baseline.column_count, target.column_count
        )
        self._compare_value(
            differences, "line_ending", baseline.line_ending, target.line_ending
        )
        self._compare_value(differences, "has_bom", baseline.has_bom, target.has_bom)
        self._compare_value(
            differences,
            "header_names",
            baseline.header_names,
            target.header_names,
            rule_id="JDLCSV-CMP-HEADER",
            message="ヘッダー名または項目順に差があります。",
        )
        self._compare_value(
            differences,
            "metadata_pattern",
            baseline.metadata_pattern,
            target.metadata_pattern,
            rule_id="JDLCSV-CMP-METADATA",
            message="コメント/メタデータ行のパターンに差があります。",
        )
        self._compare_value(
            differences,
            "record_column_counts",
            baseline.record_column_counts,
            target.record_column_counts,
            rule_id="JDLCSV-CMP-RECORD-COLUMNS",
            message="データ行の列数分布に差があります。",
        )
        return JdlCsvSchemaComparison(
            baseline=baseline,
            target=target,
            differences=tuple(differences),
        )

    def _compare_value(
        self,
        differences: list[ValidationResult],
        field: str,
        baseline: object,
        target: object,
        rule_id: str | None = None,
        message: str | None = None,
    ) -> None:
        if baseline == target:
            return
        differences.append(
            ValidationResult(
                severity=Severity.WARNING,
                rule_id=rule_id or f"JDLCSV-CMP-{field.upper()}",
                field=field,
                input_value={"baseline": baseline, "target": target},
                message=message or f"{field} に差があります。",
                suggested_action="正常CSVと失敗CSVの差分として確認してください。",
            )
        )

from __future__ import annotations

from pathlib import Path

from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult

from .adapter import MoneyForwardInputAdapter, MoneyForwardInputAdapterError


class MoneyForwardStructuralValidator:
    def __init__(self, adapter: MoneyForwardInputAdapter | None = None) -> None:
        self._adapter = adapter or MoneyForwardInputAdapter()

    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        try:
            self._adapter.read(path, profile)
        except MoneyForwardInputAdapterError:
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="MF-OBSERVED-V0-STRUCTURE",
                    message="Money Forward観測済み19列仕訳帳CSVとして解析できません。",
                    field="input_file",
                    suggested_action=(
                        "文字コード、LF改行、exact header、列数、取引No、日付、金額、"
                        "貸借一致を確認してください。"
                    ),
                )
            ]
        return []

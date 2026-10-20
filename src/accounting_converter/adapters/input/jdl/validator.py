from __future__ import annotations

from pathlib import Path

from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult

from .adapter import JdlMigrationInputAdapter, JdlMigrationInputAdapterError


class JdlMigrationStructuralValidator:
    def __init__(self, adapter: JdlMigrationInputAdapter | None = None) -> None:
        self.adapter = adapter or JdlMigrationInputAdapter()

    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        try:
            self.adapter.read(path, profile)
        except JdlMigrationInputAdapterError as exc:
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="JDL-MIGRATION-INPUT-STRUCTURE",
                    message="JDL migration sourceを安全に読み込めません。",
                    field="input",
                    input_value=exc.__class__.__name__,
                    suggested_action="30列、CP932、CRLF、flag sequenceを確認してください。",
                )
            ]
        return []

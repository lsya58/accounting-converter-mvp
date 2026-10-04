from __future__ import annotations

from pathlib import Path

from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult

from .adapter import YayoiInputAdapter, YayoiInputAdapterError


class YayoiStructuralValidator:
    """Strict structural validation for the observed AE19 adapter identity."""

    def __init__(self, adapter: YayoiInputAdapter | None = None) -> None:
        self._adapter = adapter or YayoiInputAdapter()

    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        errors: list[ValidationResult] = []
        try:
            raw = path.read_bytes()
        except OSError:
            return [self._error("YAYOI-STRUCT-READ", "弥生入力を読み込めません。", "input_path")]
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            errors.append(self._error("YAYOI-STRUCT-BOM", "BOMを検出しました。", "bom"))
        without_crlf = raw.replace(b"\r\n", b"")
        if b"\n" in without_crlf or b"\r" in without_crlf:
            errors.append(
                self._error(
                    "YAYOI-STRUCT-LINE-END",
                    "Observed AE19 profileではCRLF以外の改行を受理しません。",
                    "line_ending",
                )
            )
        try:
            text = raw.decode("cp932", errors="strict")
            if text.encode("cp932", errors="strict") != raw:
                raise UnicodeError("CP932 round-trip mismatch")
        except UnicodeError:
            errors.append(
                self._error(
                    "YAYOI-STRUCT-CP932",
                    "CP932として損失なく解析できません。",
                    "encoding",
                )
            )
        if errors:
            return errors
        try:
            self._adapter.read(path, profile)
        except YayoiInputAdapterError:
            errors.append(
                self._error(
                    "YAYOI-STRUCT-PARSE",
                    "Observed AE19の25項目構造として解析できません。",
                    "csv",
                )
            )
        return errors

    @staticmethod
    def _error(rule_id: str, message: str, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            field=field,
            suggested_action="入力形式、文字コード、改行、25項目構造を確認してください。",
        )

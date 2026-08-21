from __future__ import annotations

import re
from dataclasses import dataclass

from accounting_converter.domain.validation import Severity

from .models import (
    AccountingSide,
    DiagnosticAssociationStatus,
    DiagnosticIssue,
    DiagnosticIssueCategory,
    FieldResolutionStatus,
    JdlMasterType,
)


@dataclass(frozen=True)
class JdlDiagnosticMessagePattern:
    label: str
    side: AccountingSide
    master_type: JdlMasterType
    field: str

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(
            rf"【{re.escape(self.label)}】"
            r"(?:(?P<value>.+?)に一致する)?"
            r".*見つかりません"
        )


DEFAULT_MASTER_MISMATCH_PATTERNS: tuple[JdlDiagnosticMessagePattern, ...] = (
    JdlDiagnosticMessagePattern(
        label="借方勘定科目",
        side=AccountingSide.DEBIT,
        master_type=JdlMasterType.ACCOUNT,
        field="debit_account",
    ),
    JdlDiagnosticMessagePattern(
        label="貸方勘定科目",
        side=AccountingSide.CREDIT,
        master_type=JdlMasterType.ACCOUNT,
        field="credit_account",
    ),
    JdlDiagnosticMessagePattern(
        label="借方補助",
        side=AccountingSide.DEBIT,
        master_type=JdlMasterType.SUB_ACCOUNT,
        field="debit_sub_account",
    ),
    JdlDiagnosticMessagePattern(
        label="貸方補助",
        side=AccountingSide.CREDIT,
        master_type=JdlMasterType.SUB_ACCOUNT,
        field="credit_sub_account",
    ),
    JdlDiagnosticMessagePattern(
        label="借方部門",
        side=AccountingSide.DEBIT,
        master_type=JdlMasterType.DEPARTMENT,
        field="debit_department",
    ),
    JdlDiagnosticMessagePattern(
        label="貸方部門",
        side=AccountingSide.CREDIT,
        master_type=JdlMasterType.DEPARTMENT,
        field="credit_department",
    ),
    JdlDiagnosticMessagePattern(
        label="部門",
        side=AccountingSide.UNKNOWN,
        master_type=JdlMasterType.DEPARTMENT,
        field="department",
    ),
    JdlDiagnosticMessagePattern(
        label="税区分",
        side=AccountingSide.NONE,
        master_type=JdlMasterType.TAX_CATEGORY,
        field="tax_category",
    ),
)

GENERIC_JDL_MESSAGE_PATTERN = re.compile(
    r"(CSVファイルには.*データがあります|項目その他に相違|取り込むことができません|ログファイル|見つかりません)"
)


class JdlImportDiagnosticMessageParser:
    def __init__(
        self,
        master_mismatch_patterns: tuple[
            JdlDiagnosticMessagePattern, ...
        ] = DEFAULT_MASTER_MISMATCH_PATTERNS,
    ) -> None:
        self.master_mismatch_patterns = master_mismatch_patterns

    def parse(self, raw_message: str, source_row: int) -> DiagnosticIssue | None:
        normalized = raw_message.strip().removeprefix("//").strip()
        for message_pattern in self.master_mismatch_patterns:
            match = message_pattern.pattern.search(normalized)
            if match is None:
                continue
            source_value = self._clean_value(match.group("value"))
            return DiagnosticIssue(
                category=DiagnosticIssueCategory.MASTER_MISMATCH,
                side=message_pattern.side,
                master_type=message_pattern.master_type,
                source_row=source_row,
                source_value=source_value,
                raw_message=normalized,
                severity=Severity.WARNING.value,
                field=message_pattern.field,
                field_resolution_status=(
                    FieldResolutionStatus.FROM_MESSAGE
                    if source_value is not None
                    else FieldResolutionStatus.FIELD_UNRESOLVED
                ),
            )

        if GENERIC_JDL_MESSAGE_PATTERN.search(normalized):
            return DiagnosticIssue(
                category=DiagnosticIssueCategory.UNKNOWN_JDL_MESSAGE,
                side=AccountingSide.UNKNOWN,
                master_type=JdlMasterType.UNKNOWN,
                source_row=source_row,
                source_value=None,
                raw_message=normalized,
                severity=Severity.WARNING.value,
                association_status=DiagnosticAssociationStatus.UNRESOLVED,
            )
        return None

    def _clean_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip(" :：,，")
        return cleaned or None

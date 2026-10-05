from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from accounting_converter.application.journal_route import JournalRouteResult
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.validation import Severity, ValidationResult

from .models import (
    JDL_FILE_COMBINATION_GATE_METADATA_KEY,
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    JdlFileCombinationGate,
)


class ExplicitJdlEvidenceRoutePolicy:
    """Assigns reviewed JDL output profiles by journal ID without inference."""

    def __init__(
        self,
        assignments: Mapping[str, JdlEvidenceProfile],
        *,
        route_id: str,
        file_combination_gate: JdlFileCombinationGate | None = None,
    ) -> None:
        self._assignments = dict(assignments)
        self._route_id = route_id
        self._file_combination_gate = file_combination_gate

    def apply(self, entries: Sequence[JournalEntry]) -> JournalRouteResult:
        errors: list[ValidationResult] = []
        ids = [entry.id for entry in entries]
        duplicate_ids = {entry_id for entry_id in ids if ids.count(entry_id) > 1}
        if duplicate_ids:
            errors.append(self._error("JDL-ROUTE-DUPLICATE-ID", "仕訳IDが重複しています。"))

        entry_ids = set(ids)
        missing = entry_ids - self._assignments.keys()
        unknown = self._assignments.keys() - entry_ids
        if missing:
            errors.append(
                self._error(
                    "JDL-ROUTE-MISSING-ASSIGNMENT",
                    "JDL Evidence profileが明示されていない仕訳があります。",
                )
            )
        if unknown:
            errors.append(
                self._error(
                    "JDL-ROUTE-UNKNOWN-ASSIGNMENT",
                    "入力仕訳に対応しないJDL route assignmentがあります。",
                )
            )
        if errors:
            return JournalRouteResult(tuple(entries), tuple(errors))

        routed = tuple(
            replace(
                entry,
                metadata={
                    **entry.metadata,
                    JDL_OUTPUT_METADATA_KEY: self._assignments[entry.id].value,
                    "jdl_output_route_assignment": "EXPLICIT",
                    "jdl_output_route_id": self._route_id,
                    **(
                        {
                            JDL_FILE_COMBINATION_GATE_METADATA_KEY: (
                                self._file_combination_gate.value
                            )
                        }
                        if self._file_combination_gate is not None
                        else {}
                    ),
                },
            )
            for entry in entries
        )
        return JournalRouteResult(routed)

    @staticmethod
    def _error(rule_id: str, message: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            field="jdl_output_evidence_profile",
            suggested_action="変換routeで仕訳ごとのEvidence profileを明示してください。",
        )

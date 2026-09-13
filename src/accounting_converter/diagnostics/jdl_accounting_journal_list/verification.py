from __future__ import annotations

from collections import Counter
from decimal import Decimal

from accounting_converter.domain.journal import JournalEntry, Side, SourceReference
from accounting_converter.domain.validation import Severity, ValidationResult

from .models import (
    JdlAccountingJournalListAnalysisResult,
    PostImportVerificationResult,
    PostImportVerificationStatus,
)


class JdlAccountingPostImportVerifier:
    def verify(
        self,
        expected_entries: tuple[JournalEntry, ...],
        actual: JdlAccountingJournalListAnalysisResult,
    ) -> PostImportVerificationResult:
        if actual.errors:
            return PostImportVerificationResult(
                status=PostImportVerificationStatus.PARSE_FAILED,
                expected_count=len(expected_entries),
                actual_count=len(actual.record_candidates),
                matched_count=0,
                mismatch_categories=(("parse_failure", len(actual.errors)),),
                structural_status=actual.readiness.value,
                validation_results=actual.errors,
            )
        expected_keys: list[tuple[str, str, str, str, str, str | None]] = []
        validation_results: list[ValidationResult] = []
        for entry in expected_entries:
            key = self._expected_key(entry)
            if key is None:
                validation_results.append(
                    ValidationResult(
                        severity=Severity.ERROR,
                        rule_id="JDL-ACCOUNTING-VERIFY-UNSUPPORTED-EXPECTED",
                        message=(
                            "21列仕訳一覧で比較できないExpected JournalEntryがあります。"
                        ),
                        journal_id=entry.id,
                        source_reference=entry.source_reference,
                        field="journal_structure",
                    )
                )
                continue
            expected_keys.append(key)

        if validation_results:
            return PostImportVerificationResult(
                status=PostImportVerificationStatus.INSUFFICIENT_EVIDENCE,
                expected_count=len(expected_entries),
                actual_count=len(actual.record_candidates),
                matched_count=0,
                mismatch_categories=(("unsupported_expected", len(validation_results)),),
                structural_status=actual.readiness.value,
                validation_results=tuple(validation_results),
            )

        if len(expected_keys) != len(actual.record_candidates):
            validation_results.append(
                self._result(
                    "JDL-ACCOUNTING-VERIFY-COUNT",
                    "Expected件数とActual件数が一致しません。",
                    "count",
                )
            )
            return PostImportVerificationResult(
                status=PostImportVerificationStatus.MISMATCH,
                expected_count=len(expected_entries),
                actual_count=len(actual.record_candidates),
                matched_count=0,
                mismatch_categories=(("count_mismatch", 1),),
                structural_status=actual.readiness.value,
                validation_results=tuple(validation_results),
            )

        expected_counter = Counter(expected_keys)
        actual_counter = Counter(candidate.match_key for candidate in actual.record_candidates)
        duplicates = sum(count - 1 for count in actual_counter.values() if count > 1)
        if duplicates:
            validation_results.append(
                self._result(
                    "JDL-ACCOUNTING-VERIFY-AMBIGUOUS",
                    "Actual側に同一候補が複数あり一意に照合できません。",
                    "match_key",
                )
            )
            return PostImportVerificationResult(
                status=PostImportVerificationStatus.AMBIGUOUS,
                expected_count=len(expected_entries),
                actual_count=len(actual.record_candidates),
                matched_count=0,
                mismatch_categories=(("ambiguous_match", duplicates),),
                structural_status=actual.readiness.value,
                validation_results=tuple(validation_results),
            )

        matched_count = sum(
            min(expected_counter[key], actual_counter.get(key, 0))
            for key in expected_counter
        )
        if matched_count != len(expected_keys):
            validation_results.append(
                self._result(
                    "JDL-ACCOUNTING-VERIFY-VALUE",
                    "ExpectedとActualの比較可能項目が一致しません。",
                    "match_key",
                )
            )
            mismatch_count = len(expected_keys) - matched_count
            return PostImportVerificationResult(
                status=PostImportVerificationStatus.MISMATCH,
                expected_count=len(expected_entries),
                actual_count=len(actual.record_candidates),
                matched_count=matched_count,
                mismatch_categories=(("value_mismatch", mismatch_count),),
                structural_status=actual.readiness.value,
                validation_results=tuple(validation_results),
            )

        return PostImportVerificationResult(
            status=PostImportVerificationStatus.MATCH,
            expected_count=len(expected_entries),
            actual_count=len(actual.record_candidates),
            matched_count=matched_count,
            structural_status=actual.readiness.value,
        )

    def _expected_key(
        self,
        entry: JournalEntry,
    ) -> tuple[str, str, str, str, str, str | None] | None:
        if entry.is_compound() or not entry.is_balanced():
            return None
        debits = [line for line in entry.lines if line.side is Side.DEBIT]
        credits = [line for line in entry.lines if line.side is Side.CREDIT]
        if len(debits) != 1 or len(credits) != 1:
            return None
        debit = debits[0]
        credit = credits[0]
        if debit.account is None or credit.account is None:
            return None
        amount: Decimal = debit.amount
        if amount != credit.amount:
            return None
        return (
            entry.date.isoformat(),
            str(amount),
            debit.account,
            credit.account,
            entry.description or "",
            entry.source_reference.source_journal_id,
        )

    def _result(self, rule_id: str, message: str, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            message=message,
            source_reference=SourceReference(file_name="post_import_verification"),
            field=field,
            input_value=None,
        )

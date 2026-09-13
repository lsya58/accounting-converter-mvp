from __future__ import annotations

from typing import Any

from accounting_converter.domain.validation import Severity

from .models import (
    JdlAccountingJournalListAnalysisResult,
    PostImportVerificationResult,
)


def analysis_to_privacy_safe_dict(
    analysis: JdlAccountingJournalListAnalysisResult,
    include_file_name: bool = False,
) -> dict[str, Any]:
    return {
        "file_name": analysis.file_name if include_file_name else None,
        "identity": analysis.observed_schema.identity_label,
        "purpose": analysis.observed_schema.purpose,
        "encoding": analysis.encoding,
        "has_bom": analysis.has_bom,
        "line_ending": analysis.line_ending,
        "total_physical_lines": analysis.total_physical_lines,
        "logical_row_count": analysis.logical_row_count,
        "preamble_line_count": analysis.preamble_line_count,
        "header_row_number": analysis.header_row_number,
        "header_column_count": analysis.header_column_count,
        "data_row_count": analysis.data_row_count,
        "data_row_column_count_distribution": [
            {"column_count": count, "row_count": row_count}
            for count, row_count in analysis.data_row_column_count_distribution
        ],
        "malformed_row_count": len(analysis.malformed_row_numbers),
        "blank_row_count": analysis.blank_row_count,
        "parseable_date_count": analysis.parseable_date_count,
        "parseable_amount_count": analysis.parseable_amount_count,
        "record_candidate_count": len(analysis.record_candidates),
        "can_build_common_journal_entries": analysis.can_build_common_journal_entries,
        "readiness": analysis.readiness.value,
        "comparison_to_cashbook_30_column": (
            analysis.comparison_to_cashbook_30_column.value
        ),
        "column_populations": [
            {
                "column_name": population.column_name,
                "position_1_based": population.position_1_based,
                "blank_count": population.blank_count,
                "nonblank_count": population.nonblank_count,
                "distinct_count": population.distinct_count,
            }
            for population in analysis.column_populations
        ],
        "validation_rule_counts": _validation_rule_counts(analysis),
        "error_count": sum(
            1
            for result in analysis.validation_results
            if result.severity in {Severity.ERROR, Severity.FATAL}
        ),
        "warning_count": sum(
            1
            for result in analysis.validation_results
            if result.severity is Severity.WARNING
        ),
        "privacy_note": (
            "科目名、補助名、摘要、日付、金額、raw CSV rowは出力しません。"
        ),
    }


def verification_to_privacy_safe_dict(
    result: PostImportVerificationResult,
) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "expected_count": result.expected_count,
        "actual_count": result.actual_count,
        "matched_count": result.matched_count,
        "mismatch_categories": dict(result.mismatch_categories),
        "structural_status": result.structural_status,
        "validation_rule_counts": {
            rule_id: count
            for rule_id, count in result.mismatch_categories
        },
        "privacy_note": (
            "比較結果には件数とカテゴリのみを出力し、科目名、摘要、日付、金額は出力しません。"
        ),
    }


def _validation_rule_counts(
    analysis: JdlAccountingJournalListAnalysisResult,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in analysis.validation_results:
        counts[result.rule_id] = counts.get(result.rule_id, 0) + 1
    return counts

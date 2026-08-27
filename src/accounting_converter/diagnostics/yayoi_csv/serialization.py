from __future__ import annotations

from typing import Any

from .models import YayoiCsvAnalysisResult


def yayoi_analysis_to_dict(analysis: YayoiCsvAnalysisResult) -> dict[str, Any]:
    amount = analysis.amount_observation
    return {
        "file_name": analysis.file_name,
        "encoding": analysis.encoding,
        "encoding_candidates": list(analysis.encoding_candidates),
        "delimiter": analysis.delimiter,
        "has_bom": analysis.has_bom,
        "line_ending": analysis.line_ending,
        "total_physical_lines": analysis.total_physical_lines,
        "empty_line_count": analysis.empty_line_count,
        "csv_parseable": analysis.csv_parseable,
        "data_record_count": analysis.data_record_count,
        "row_column_count_distribution": [
            {"column_count": count, "row_count": row_count}
            for count, row_count in analysis.row_column_count_distribution
        ],
        "dominant_column_count": analysis.dominant_column_count,
        "column_count_mismatch_rows": list(analysis.column_count_mismatch_rows),
        "first_rows_features": list(analysis.first_rows_features),
        "header_observation": {
            "detected": analysis.header_observation.detected,
            "row_number": analysis.header_observation.row_number,
            "exact_official_header": analysis.header_observation.exact_official_header,
            "column_count": analysis.header_observation.column_count,
            "matched_column_names_count": (
                analysis.header_observation.matched_column_names_count
            ),
        },
        "official_comparison": {
            "official_column_count": (
                analysis.official_comparison.official_column_count
            ),
            "observed_dominant_column_count": (
                analysis.official_comparison.observed_dominant_column_count
            ),
            "column_count_difference": (
                analysis.official_comparison.column_count_difference
            ),
            "structural_match_status": (
                analysis.official_comparison.structural_match_status.value
            ),
            "possible_official_25_column_format": (
                analysis.official_comparison.possible_official_25_column_format
            ),
            "additional_column_count": (
                analysis.official_comparison.additional_column_count
            ),
            "missing_column_count": analysis.official_comparison.missing_column_count,
            "formal_profile_ready": analysis.official_comparison.formal_profile_ready,
            "human_review_required": analysis.official_comparison.human_review_required,
        },
        "flags": {
            "official_flag_counts": dict(
                analysis.flag_observation.official_flag_counts
            ),
            "unknown_flag_counts": dict(analysis.flag_observation.unknown_flag_counts),
            "unknown_flag_rows": [
                {"flag": flag, "row_number": row_number}
                for flag, row_number in analysis.flag_observation.unknown_flag_rows
            ],
        },
        "grouping": {
            "candidate_count": analysis.group_candidate_count,
            "single_record_candidate_count": analysis.single_record_candidate_count,
            "multi_record_candidate_count": analysis.multi_record_candidate_count,
            "malformed_group_candidate_count": (
                analysis.malformed_group_candidate_count
            ),
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "start_row_number": candidate.start_row_number,
                    "end_row_number": candidate.end_row_number,
                    "record_count": candidate.record_count,
                    "identifier_flags": list(candidate.identifier_flags),
                    "status": candidate.status.value,
                    "starts_with_2110": candidate.starts_with_2110,
                    "ends_with_2101": candidate.ends_with_2101,
                    "middle_2100_count": candidate.middle_2100_count,
                    "malformed_reason": candidate.malformed_reason,
                }
                for candidate in analysis.group_candidates
            ],
        },
        "accounting_safety": {
            "debit_total": (
                str(amount.debit_total) if amount.debit_total is not None else None
            ),
            "credit_total": (
                str(amount.credit_total) if amount.credit_total is not None else None
            ),
            "balanced": amount.balanced,
            "amount_parse_error_count": amount.amount_parse_error_count,
            "amount_unknown_count": amount.amount_unknown_count,
            "amount_issue_rows": [
                {"row_number": row, "field": field, "status": status}
                for row, field, status in amount.amount_issue_rows
            ],
            "date_parse_candidate_error_count": (
                amount.date_parse_candidate_error_count
            ),
            "date_issue_rows": [
                {"row_number": row, "field": field}
                for row, field in amount.date_issue_rows
            ],
            "date_format_candidates": list(amount.date_format_candidates),
            "amount_field_parseable_positions": list(
                amount.amount_field_parseable_positions
            ),
        },
        "validation_results": [
            {
                "severity": result.severity.value,
                "rule_id": result.rule_id,
                "message": result.message,
                "row_number": (
                    result.source_reference.row_number
                    if result.source_reference is not None
                    else None
                ),
                "field": result.field,
            }
            for result in analysis.validation_results
        ],
    }

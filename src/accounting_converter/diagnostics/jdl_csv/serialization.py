from __future__ import annotations

from typing import Any

from accounting_converter.domain.validation import Severity

from .models import JdlCsvAnalysisResult


def analysis_to_dict(analysis: JdlCsvAnalysisResult) -> dict[str, Any]:
    return {
        "file_name": analysis.file_name,
        "encoding": analysis.encoding,
        "delimiter": analysis.delimiter,
        "total_physical_lines": analysis.total_physical_lines,
        "data_record_count": analysis.data_record_count,
        "journal_count": None,
        "diagnostic_count": len(analysis.diagnostic_message_lines),
        "error_count": len(analysis.analysis_errors),
        "warning_count": len(analysis.analysis_warnings),
        "schema_fingerprint": _fingerprint_to_dict(analysis),
        "identifier_flag_counts": dict(analysis.identifier_flag_counts),
        "observed_schema": _observed_schema_to_dict(analysis),
        "observed_grouping_summary": _observed_grouping_summary_to_dict(analysis),
        "master_mismatch_summary": {
            "total_count": analysis.master_mismatch_summary.total_count,
            "counts_by_master_type": dict(
                analysis.master_mismatch_summary.counts_by_master_type
            ),
            "counts_by_type": dict(analysis.master_mismatch_summary.counts_by_type),
            "items": [
                {
                    "side": item.side.value,
                    "master_type": item.master_type.value,
                    "source_value": item.source_value,
                    "account_value": item.account_value,
                    "count": item.count,
                    "first_row": item.first_row,
                }
                for item in analysis.master_mismatch_summary.items
            ],
        },
        "diagnostic_issues": [
            {
                "category": issue.category.value,
                "side": issue.side.value,
                "master_type": issue.master_type.value,
                "source_row": issue.source_row,
                "source_value": issue.source_value,
                "raw_message": issue.raw_message,
                "severity": issue.severity,
                "field": issue.field,
                "related_record_row": issue.related_record_row,
                "account_value": issue.account_value,
                "association_status": issue.association_status.value,
                "field_resolution_status": issue.field_resolution_status.value,
            }
            for issue in analysis.diagnostic_issues
        ],
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
                "suggested_action": result.suggested_action,
            }
            for result in analysis.validation_results
        ],
        "judgment": (
            "JDL取込可能とは判定できません。"
            if analysis.analysis_errors
            else "本システムが検証可能なCSV構造上のErrorは検出されていません。"
        ),
    }


def analysis_to_privacy_safe_dict(
    analysis: JdlCsvAnalysisResult,
    include_file_name: bool = False,
) -> dict[str, Any]:
    """Return a shareable structural summary without journal-body values."""
    diagnostics_by_category: dict[str, int] = {}
    diagnostics_by_type: dict[str, int] = {}
    for issue in analysis.diagnostic_issues:
        diagnostics_by_category[issue.category.value] = (
            diagnostics_by_category.get(issue.category.value, 0) + 1
        )
        type_key = f"{issue.side.value}:{issue.master_type.value}"
        diagnostics_by_type[type_key] = diagnostics_by_type.get(type_key, 0) + 1

    validation_counts: dict[str, int] = {}
    validation_rule_counts: dict[str, int] = {}
    for result in analysis.validation_results:
        validation_counts[result.severity.value] = (
            validation_counts.get(result.severity.value, 0) + 1
        )
        validation_rule_counts[result.rule_id] = (
            validation_rule_counts.get(result.rule_id, 0) + 1
        )

    payload: dict[str, Any] = {
        "file_name": analysis.file_name if include_file_name else None,
        "encoding": analysis.encoding,
        "delimiter": analysis.delimiter,
        "has_bom": analysis.has_bom,
        "line_ending": analysis.line_ending,
        "total_physical_lines": analysis.total_physical_lines,
        "metadata_line_count": analysis.metadata_line_count,
        "blank_line_count": len(analysis.empty_lines),
        "header_row_number": analysis.header_row_number,
        "header_column_count": analysis.header_column_count,
        "header_names": list(analysis.header_columns),
        "data_record_count": analysis.data_record_count,
        "journal_count": None,
        "record_column_counts": [
            {"column_count": column_count, "record_count": record_count}
            for column_count, record_count in (
                analysis.schema_fingerprint.record_column_counts
                if analysis.schema_fingerprint is not None
                else ()
            )
        ],
        "identifier_flag_counts": dict(analysis.identifier_flag_counts),
        "observed_schema": _privacy_safe_observed_schema(analysis),
        "observed_grouping_summary": _privacy_safe_grouping_summary(analysis),
        "diagnostic_count": len(analysis.diagnostic_message_lines),
        "diagnostic_issue_counts_by_category": diagnostics_by_category,
        "diagnostic_issue_counts_by_type": diagnostics_by_type,
        "error_count": validation_counts.get(Severity.ERROR.value, 0)
        + validation_counts.get(Severity.FATAL.value, 0),
        "warning_count": validation_counts.get(Severity.WARNING.value, 0),
        "validation_rule_counts": validation_rule_counts,
    }
    return payload


def _fingerprint_to_dict(analysis: JdlCsvAnalysisResult) -> dict[str, Any] | None:
    fingerprint = analysis.schema_fingerprint
    if fingerprint is None:
        return None
    return {
        "encoding": fingerprint.encoding,
        "delimiter": fingerprint.delimiter,
        "header_names": list(fingerprint.header_names),
        "column_count": fingerprint.column_count,
        "line_ending": fingerprint.line_ending,
        "has_bom": fingerprint.has_bom,
        "metadata_pattern": list(fingerprint.metadata_pattern),
        "record_column_counts": [
            {"column_count": column_count, "record_count": record_count}
            for column_count, record_count in fingerprint.record_column_counts
        ],
    }


def _observed_schema_to_dict(analysis: JdlCsvAnalysisResult) -> dict[str, Any] | None:
    schema = analysis.observed_schema
    if schema is None:
        return None
    return {
        "product": schema.product,
        "observed_version": schema.observed_version,
        "encoding": schema.encoding,
        "has_bom": schema.has_bom,
        "line_ending": schema.line_ending,
        "journal_column_count": schema.journal_column_count,
        "observed_header": list(schema.observed_header),
        "journal_count": schema.journal_count,
        "observed_identifier_flags": list(schema.observed_identifier_flags),
        "identifier_flag_meaning_status": schema.identifier_flag_meaning_status.value,
        "observed_behavior": list(schema.observed_behavior),
        "is_formal_format_profile": schema.is_formal_format_profile,
    }


def _privacy_safe_observed_schema(
    analysis: JdlCsvAnalysisResult,
) -> dict[str, Any] | None:
    schema = analysis.observed_schema
    if schema is None:
        return None
    return {
        "product": schema.product,
        "observed_version": schema.observed_version,
        "encoding": schema.encoding,
        "has_bom": schema.has_bom,
        "line_ending": schema.line_ending,
        "journal_column_count": schema.journal_column_count,
        "observed_header": list(schema.observed_header),
        "journal_count": schema.journal_count,
        "observed_identifier_flags": list(schema.observed_identifier_flags),
        "identifier_flag_meaning_status": schema.identifier_flag_meaning_status.value,
        "observed_behavior": list(schema.observed_behavior),
        "is_formal_format_profile": schema.is_formal_format_profile,
    }


def _observed_grouping_summary_to_dict(
    analysis: JdlCsvAnalysisResult,
) -> dict[str, Any]:
    summary = analysis.observed_grouping_summary
    return {
        "total_candidate_count": summary.total_candidate_count,
        "single_record_candidate_count": summary.single_record_candidate_count,
        "multi_record_candidate_count": summary.multi_record_candidate_count,
        "valid_multi_record_sequence_count": (
            summary.valid_multi_record_sequence_count
        ),
        "same_voucher_number_count": summary.same_voucher_number_count,
        "same_date_count": summary.same_date_count,
        "balanced_multi_record_candidate_count": (
            summary.balanced_multi_record_candidate_count
        ),
        "unresolved_candidate_count": summary.unresolved_candidate_count,
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "start_record_index": candidate.start_record_index,
                "end_record_index": candidate.end_record_index,
                "record_count": candidate.record_count,
                "identifier_flags": list(candidate.identifier_flags),
                "voucher_number": candidate.voucher_number,
                "date": candidate.date,
                "debit_total": str(candidate.debit_total),
                "credit_total": str(candidate.credit_total),
                "balanced": candidate.balanced,
                "grouping_confidence": candidate.grouping_confidence,
                "grouping_basis": list(candidate.grouping_basis),
                "status": candidate.status.value,
                "valid_sequence": candidate.valid_sequence,
                "same_voucher_number": candidate.same_voucher_number,
                "same_date": candidate.same_date,
                "warnings": list(candidate.warnings),
            }
            for candidate in summary.candidates
        ],
    }


def _privacy_safe_grouping_summary(analysis: JdlCsvAnalysisResult) -> dict[str, Any]:
    summary = analysis.observed_grouping_summary
    return {
        "total_candidate_count": summary.total_candidate_count,
        "single_record_candidate_count": summary.single_record_candidate_count,
        "multi_record_candidate_count": summary.multi_record_candidate_count,
        "valid_multi_record_sequence_count": (
            summary.valid_multi_record_sequence_count
        ),
        "same_voucher_number_count": summary.same_voucher_number_count,
        "same_date_count": summary.same_date_count,
        "balanced_multi_record_candidate_count": (
            summary.balanced_multi_record_candidate_count
        ),
        "unresolved_candidate_count": summary.unresolved_candidate_count,
    }

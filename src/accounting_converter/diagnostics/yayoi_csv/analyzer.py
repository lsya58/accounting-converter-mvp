from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accounting_converter.domain.journal import SourceReference
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.profiles.yayoi_official import (
    YayoiOfficialImportSpecification,
    yayoi_accounting_05_official_import_spec,
)

from .models import (
    YayoiAmountObservation,
    YayoiCsvAnalysisResult,
    YayoiCsvLineObservation,
    YayoiFlagObservation,
    YayoiGroupCandidate,
    YayoiGroupCandidateStatus,
    YayoiHeaderObservation,
    YayoiLineClassification,
    YayoiOfficialComparison,
    YayoiStructuralMatchStatus,
)


@dataclass(frozen=True)
class _ParsedRow:
    row_number: int
    columns: tuple[str, ...]
    classification: YayoiLineClassification
    csv_error: str | None = None


class YayoiCsvAnalyzer:
    def __init__(
        self,
        official_spec: YayoiOfficialImportSpecification | None = None,
        delimiter: str = ",",
    ) -> None:
        self.official_spec = official_spec or yayoi_accounting_05_official_import_spec()
        self.delimiter = delimiter

    def analyze_path(self, path: Path) -> YayoiCsvAnalysisResult:
        raw = path.read_bytes()
        text, encoding, candidates = self._decode(raw)
        return self.analyze_text(
            text,
            file_name=path.name,
            encoding=encoding,
            encoding_candidates=candidates,
            has_bom=raw.startswith(b"\xef\xbb\xbf"),
            line_ending=self._detect_line_ending(raw),
        )

    def analyze_text(
        self,
        text: str,
        file_name: str = "<memory>",
        encoding: str = "utf-8",
        encoding_candidates: tuple[str, ...] = ("utf-8",),
        has_bom: bool = False,
        line_ending: str | None = None,
    ) -> YayoiCsvAnalysisResult:
        detected_line_ending = line_ending or self._detect_line_ending_from_text(text)
        physical_lines = text.splitlines()
        parsed_rows = self._parse_lines(physical_lines)
        csv_parseable = all(row.csv_error is None for row in parsed_rows)
        line_observations = tuple(
            YayoiCsvLineObservation(
                row_number=row.row_number,
                classification=row.classification,
                column_count=len(row.columns),
                csv_error=row.csv_error,
            )
            for row in parsed_rows
        )
        data_rows = tuple(
            row
            for row in parsed_rows
            if row.classification is YayoiLineClassification.DATA_RECORD
        )
        count_source = data_rows or tuple(
            row
            for row in parsed_rows
            if row.classification
            not in {YayoiLineClassification.EMPTY, YayoiLineClassification.INVALID_CSV}
        )
        distribution = Counter(len(row.columns) for row in count_source)
        dominant_column_count = (
            distribution.most_common(1)[0][0] if distribution else None
        )
        mismatch_rows = tuple(
            row.row_number
            for row in data_rows
            if dominant_column_count is not None
            and len(row.columns) != dominant_column_count
        )
        header = self._observe_header(parsed_rows)
        flag_observation = self._observe_flags(data_rows)
        groups = self._observe_groups(data_rows)
        comparison = self._compare_with_official(
            dominant_column_count=dominant_column_count,
            header=header,
            csv_parseable=csv_parseable,
            data_rows=data_rows,
        )
        amount_observation = self._observe_accounting_safety(data_rows, comparison)
        validation_results = self._validation_results(
            file_name=file_name,
            parsed_rows=parsed_rows,
            csv_parseable=csv_parseable,
            mismatch_rows=mismatch_rows,
            comparison=comparison,
            flag_observation=flag_observation,
            groups=groups,
            amount_observation=amount_observation,
        )
        return YayoiCsvAnalysisResult(
            file_name=file_name,
            encoding=encoding,
            encoding_candidates=encoding_candidates,
            delimiter=self.delimiter,
            has_bom=has_bom,
            line_ending=detected_line_ending,
            total_physical_lines=len(physical_lines),
            empty_line_count=sum(
                1
                for row in parsed_rows
                if row.classification is YayoiLineClassification.EMPTY
            ),
            csv_parseable=csv_parseable,
            line_observations=line_observations,
            row_column_count_distribution=tuple(sorted(distribution.items())),
            dominant_column_count=dominant_column_count,
            column_count_mismatch_rows=mismatch_rows,
            first_rows_features=self._first_rows_features(parsed_rows),
            data_record_count=len(data_rows),
            header_observation=header,
            flag_observation=flag_observation,
            group_candidates=groups,
            amount_observation=amount_observation,
            official_comparison=comparison,
            validation_results=validation_results,
        )

    def _decode(self, raw: bytes) -> tuple[str, str, tuple[str, ...]]:
        candidates = ("utf-8-sig", "utf-8", "cp932")
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig"), "utf-8-sig", candidates
        for encoding in candidates:
            if encoding == "utf-8-sig":
                continue
            try:
                return raw.decode(encoding), encoding, candidates
            except UnicodeDecodeError:
                continue
        return raw.decode("cp932", errors="replace"), "cp932-replace", candidates

    def _detect_line_ending(self, raw: bytes) -> str:
        crlf = raw.count(b"\r\n")
        lf = raw.count(b"\n") - crlf
        cr = raw.count(b"\r") - crlf
        if crlf and not lf and not cr:
            return "CRLF"
        if lf and not crlf and not cr:
            return "LF"
        if cr and not crlf and not lf:
            return "CR"
        if crlf or lf or cr:
            return "MIXED"
        return "UNKNOWN"

    def _detect_line_ending_from_text(self, text: str) -> str:
        crlf = text.count("\r\n")
        stripped = text.replace("\r\n", "")
        lf = stripped.count("\n")
        cr = stripped.count("\r")
        if crlf and not lf and not cr:
            return "CRLF"
        if lf and not crlf and not cr:
            return "LF"
        if cr or crlf or lf:
            return "MIXED"
        return "UNKNOWN"

    def _parse_lines(self, physical_lines: list[str]) -> tuple[_ParsedRow, ...]:
        rows: list[_ParsedRow] = []
        for row_number, line in enumerate(physical_lines, start=1):
            if not line.strip():
                rows.append(
                    _ParsedRow(
                        row_number=row_number,
                        columns=(),
                        classification=YayoiLineClassification.EMPTY,
                    )
                )
                continue
            try:
                parsed = next(
                    csv.reader([line], delimiter=self.delimiter, strict=True)
                )
            except csv.Error as exc:
                rows.append(
                    _ParsedRow(
                        row_number=row_number,
                        columns=(),
                        classification=YayoiLineClassification.INVALID_CSV,
                        csv_error=str(exc),
                    )
                )
                continue
            columns = tuple(parsed)
            classification = (
                YayoiLineClassification.HEADER
                if columns == self.official_spec.column_names
                else YayoiLineClassification.DATA_RECORD
            )
            rows.append(
                _ParsedRow(
                    row_number=row_number,
                    columns=columns,
                    classification=classification,
                )
            )
        return tuple(rows)

    def _observe_header(self, rows: tuple[_ParsedRow, ...]) -> YayoiHeaderObservation:
        for row in rows:
            if row.classification is not YayoiLineClassification.HEADER:
                continue
            return YayoiHeaderObservation(
                detected=True,
                row_number=row.row_number,
                exact_official_header=True,
                column_count=len(row.columns),
                matched_column_names_count=len(row.columns),
            )
        for row in rows:
            if not row.columns:
                continue
            matched = sum(
                1
                for observed, official in zip(
                    row.columns,
                    self.official_spec.column_names,
                    strict=False,
                )
                if observed == official
            )
            if matched >= max(3, self.official_spec.column_count // 2):
                return YayoiHeaderObservation(
                    detected=True,
                    row_number=row.row_number,
                    exact_official_header=False,
                    column_count=len(row.columns),
                    matched_column_names_count=matched,
                )
        return YayoiHeaderObservation(
            detected=False,
            row_number=None,
            exact_official_header=False,
            column_count=None,
        )

    def _observe_flags(self, rows: tuple[_ParsedRow, ...]) -> YayoiFlagObservation:
        official = Counter()
        unknown = Counter()
        unknown_rows: list[tuple[str, int]] = []
        for row in rows:
            flag = row.columns[0].strip() if row.columns else ""
            if flag in self.official_spec.identifier_flags:
                official[flag] += 1
            elif flag:
                unknown[flag] += 1
                unknown_rows.append((flag, row.row_number))
        return YayoiFlagObservation(
            official_flag_counts=tuple(sorted(official.items())),
            unknown_flag_counts=tuple(sorted(unknown.items())),
            unknown_flag_rows=tuple(unknown_rows),
        )

    def _observe_groups(
        self,
        rows: tuple[_ParsedRow, ...],
    ) -> tuple[YayoiGroupCandidate, ...]:
        candidates: list[YayoiGroupCandidate] = []
        index = 0
        candidate_number = 1
        while index < len(rows):
            row = rows[index]
            flag = row.columns[0].strip() if row.columns else ""
            candidate_id = f"YAYOI-GROUP-{candidate_number:04d}"
            candidate_number += 1

            if flag in {"2000", "2111"}:
                candidates.append(
                    YayoiGroupCandidate(
                        candidate_id=candidate_id,
                        start_row_number=row.row_number,
                        end_row_number=row.row_number,
                        record_count=1,
                        identifier_flags=(flag,),
                        status=YayoiGroupCandidateStatus.OBSERVED_SINGLE_RECORD,
                    )
                )
                index += 1
                continue

            if flag == "2110":
                start = index
                group = [row]
                index += 1
                status = YayoiGroupCandidateStatus.UNCLOSED_SEQUENCE
                reason = "2110 sequence was not closed by 2101"
                while index < len(rows):
                    next_row = rows[index]
                    next_flag = next_row.columns[0].strip() if next_row.columns else ""
                    if next_flag == "2100":
                        group.append(next_row)
                        index += 1
                        continue
                    if next_flag == "2101":
                        group.append(next_row)
                        index += 1
                        status = YayoiGroupCandidateStatus.OBSERVED_MULTI_RECORD_SEQUENCE
                        reason = None
                        break
                    status = YayoiGroupCandidateStatus.MALFORMED_SEQUENCE
                    reason = f"unexpected flag before 2101: {next_flag or '(blank)'}"
                    break
                flags = tuple(item.columns[0].strip() if item.columns else "" for item in group)
                candidates.append(
                    YayoiGroupCandidate(
                        candidate_id=candidate_id,
                        start_row_number=rows[start].row_number,
                        end_row_number=group[-1].row_number,
                        record_count=len(group),
                        identifier_flags=flags,
                        status=status,
                        starts_with_2110=True,
                        ends_with_2101=bool(flags and flags[-1] == "2101"),
                        middle_2100_count=max(0, len([value for value in flags[1:-1] if value == "2100"])),
                        malformed_reason=reason,
                    )
                )
                continue

            status = (
                YayoiGroupCandidateStatus.MALFORMED_SEQUENCE
                if flag in {"2100", "2101"}
                else YayoiGroupCandidateStatus.UNKNOWN_FLAG_SEQUENCE
            )
            reason = (
                f"{flag} appeared outside a 2110 sequence"
                if flag in {"2100", "2101"}
                else f"UNKNOWN_OBSERVED_FLAG: {flag or '(blank)'}"
            )
            candidates.append(
                YayoiGroupCandidate(
                    candidate_id=candidate_id,
                    start_row_number=row.row_number,
                    end_row_number=row.row_number,
                    record_count=1,
                    identifier_flags=(flag,),
                    status=status,
                    malformed_reason=reason,
                )
            )
            index += 1
        return tuple(candidates)

    def _compare_with_official(
        self,
        dominant_column_count: int | None,
        header: YayoiHeaderObservation,
        csv_parseable: bool,
        data_rows: tuple[_ParsedRow, ...],
    ) -> YayoiOfficialComparison:
        official_count = self.official_spec.column_count
        if dominant_column_count is None or not data_rows:
            status = YayoiStructuralMatchStatus.INSUFFICIENT_EVIDENCE
        elif not csv_parseable or dominant_column_count != official_count:
            status = YayoiStructuralMatchStatus.STRUCTURAL_DIFFERENCE
        else:
            status = YayoiStructuralMatchStatus.MATCH_CANDIDATE
        diff = (
            None
            if dominant_column_count is None
            else dominant_column_count - official_count
        )
        return YayoiOfficialComparison(
            official_column_count=official_count,
            observed_dominant_column_count=dominant_column_count,
            column_count_difference=diff,
            header_observation=header,
            structural_match_status=status,
            possible_official_25_column_format=(
                status is YayoiStructuralMatchStatus.MATCH_CANDIDATE
            ),
            additional_column_count=max(0, diff or 0),
            missing_column_count=max(0, -(diff or 0)),
            formal_profile_ready=False,
            human_review_required=True,
        )

    def _observe_accounting_safety(
        self,
        rows: tuple[_ParsedRow, ...],
        comparison: YayoiOfficialComparison,
    ) -> YayoiAmountObservation:
        if not comparison.possible_official_25_column_format:
            return YayoiAmountObservation()
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        parse_errors = 0
        unknowns = 0
        amount_issues: list[tuple[int, str, str]] = []
        date_errors = 0
        date_issues: list[tuple[int, str]] = []
        date_formats = Counter()
        amount_position_success = Counter()
        amount_position_seen = Counter()
        for row in rows:
            if len(row.columns) != self.official_spec.column_count:
                continue
            for position, field_name in ((9, "借方金額"), (15, "貸方金額")):
                amount_position_seen[position] += 1
                value = row.columns[position - 1].strip()
                if value == "":
                    unknowns += 1
                    amount_issues.append((row.row_number, field_name, "UNKNOWN"))
                    continue
                try:
                    amount = Decimal(value.replace(",", ""))
                except InvalidOperation:
                    parse_errors += 1
                    amount_issues.append((row.row_number, field_name, "PARSE_ERROR"))
                    continue
                amount_position_success[position] += 1
                if position == 9:
                    debit_total += amount
                else:
                    credit_total += amount
            for position, field_name in ((4, "取引日付"), (19, "期日")):
                value = row.columns[position - 1].strip()
                if value == "":
                    continue
                matched_format = self._match_date_format(value)
                if matched_format is None:
                    date_errors += 1
                    date_issues.append((row.row_number, field_name))
                else:
                    date_formats[matched_format] += 1
        balanced: bool | None
        if parse_errors or unknowns:
            balanced = None
        else:
            balanced = debit_total == credit_total
        return YayoiAmountObservation(
            debit_total=debit_total,
            credit_total=credit_total,
            balanced=balanced,
            amount_parse_error_count=parse_errors,
            amount_unknown_count=unknowns,
            amount_issue_rows=tuple(amount_issues),
            date_parse_candidate_error_count=date_errors,
            date_issue_rows=tuple(date_issues),
            date_format_candidates=tuple(sorted(date_formats)),
            amount_field_parseable_positions=tuple(
                position
                for position, seen in sorted(amount_position_seen.items())
                if seen and amount_position_success[position] == seen
            ),
        )

    def _match_date_format(self, value: str) -> str | None:
        for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                datetime.strptime(value, fmt)
            except ValueError:
                continue
            return fmt
        return None

    def _validation_results(
        self,
        file_name: str,
        parsed_rows: tuple[_ParsedRow, ...],
        csv_parseable: bool,
        mismatch_rows: tuple[int, ...],
        comparison: YayoiOfficialComparison,
        flag_observation: YayoiFlagObservation,
        groups: tuple[YayoiGroupCandidate, ...],
        amount_observation: YayoiAmountObservation,
    ) -> tuple[ValidationResult, ...]:
        results: list[ValidationResult] = []
        if not csv_parseable:
            for row in parsed_rows:
                if row.csv_error:
                    results.append(
                        ValidationResult(
                            severity=Severity.ERROR,
                            rule_id="YAYOI-CSV-STRUCTURE",
                            message="CSVとして構文解析できない行があります。",
                            source_reference=SourceReference(
                                file_name=file_name,
                                row_number=row.row_number,
                            ),
                            field="csv",
                            input_value={"error": row.csv_error},
                        )
                    )
        if comparison.structural_match_status is YayoiStructuralMatchStatus.STRUCTURAL_DIFFERENCE:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="YAYOI-OFFICIAL-25-COLUMN-COMPARISON",
                    message="弥生公式25項目仕様との差異候補を検出しました。",
                    field="column_count",
                    input_value={
                        "official_column_count": comparison.official_column_count,
                        "observed_dominant_column_count": (
                            comparison.observed_dominant_column_count
                        ),
                    },
                )
            )
        if mismatch_rows:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="YAYOI-COLUMN-COUNT-MISMATCH",
                    message="観測された支配的な列数と異なるデータ行があります。",
                    field="column_count",
                    input_value={"rows": list(mismatch_rows)},
                )
            )
        if flag_observation.unknown_flag_counts:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="UNKNOWN_OBSERVED_FLAG",
                    message="公式ドキュメント上の識別フラグに含まれない値を観測しました。",
                    field="identifier_flag",
                    input_value=dict(flag_observation.unknown_flag_counts),
                )
            )
        malformed = [
            candidate
            for candidate in groups
            if candidate.status
            in {
                YayoiGroupCandidateStatus.MALFORMED_SEQUENCE,
                YayoiGroupCandidateStatus.UNCLOSED_SEQUENCE,
                YayoiGroupCandidateStatus.UNKNOWN_FLAG_SEQUENCE,
            }
        ]
        if malformed:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="YAYOI-OBSERVED-GROUPING-ISSUE",
                    message="弥生識別フラグのグルーピング候補に未解決または異常な遷移があります。",
                    field="identifier_flag_sequence",
                    input_value={
                        "candidate_count": len(malformed),
                        "rows": [candidate.start_row_number for candidate in malformed],
                    },
                )
            )
        if amount_observation.amount_parse_error_count:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="YAYOI-AMOUNT-PARSE",
                    message="金額として解釈できない値を検出しました。",
                    field="amount",
                    input_value={
                        "count": amount_observation.amount_parse_error_count,
                        "rows": [
                            row for row, _, status in amount_observation.amount_issue_rows
                            if status == "PARSE_ERROR"
                        ],
                    },
                )
            )
        if amount_observation.date_parse_candidate_error_count:
            results.append(
                ValidationResult(
                    severity=Severity.WARNING,
                    rule_id="YAYOI-DATE-PARSE",
                    message="日付形式候補として解釈できない値を検出しました。",
                    field="date",
                    input_value={
                        "count": amount_observation.date_parse_candidate_error_count,
                        "rows": [row for row, _ in amount_observation.date_issue_rows],
                    },
                )
            )
        return tuple(results)

    def _first_rows_features(
        self,
        rows: tuple[_ParsedRow, ...],
    ) -> tuple[dict[str, object], ...]:
        features: list[dict[str, object]] = []
        for row in rows[:5]:
            first_cell_kind = "EMPTY"
            if row.columns:
                first_cell = row.columns[0].strip()
                if row.classification is YayoiLineClassification.HEADER:
                    first_cell_kind = "OFFICIAL_HEADER"
                elif first_cell in self.official_spec.identifier_flags:
                    first_cell_kind = "OFFICIAL_FLAG"
                elif first_cell:
                    first_cell_kind = "OTHER"
            features.append(
                {
                    "row_number": row.row_number,
                    "classification": row.classification.value,
                    "column_count": len(row.columns),
                    "first_cell_kind": first_cell_kind,
                }
            )
        return tuple(features)

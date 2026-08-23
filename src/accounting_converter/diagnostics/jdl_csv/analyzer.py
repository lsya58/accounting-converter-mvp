from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accounting_converter.domain.journal import SourceReference
from accounting_converter.domain.validation import Severity, ValidationResult

from .message_parser import JdlImportDiagnosticMessageParser
from .models import (
    AccountingSide,
    CsvLineClassification,
    DiagnosticAssociationStatus,
    DiagnosticIssue,
    FieldResolutionStatus,
    JdlCsvAnalysisResult,
    JdlCsvLineObservation,
    JdlCsvSchemaFingerprint,
    JdlMasterType,
    MasterMismatchSummary,
    MasterReferenceIssue,
    ObservedJournalGroupCandidate,
    ObservedJournalGroupingSummary,
    ObservedJournalGroupStatus,
    ObservedJdlSchema,
)


DIAGNOSTIC_MESSAGE_MARKERS = (
    "CSVファイルには",
    "項目その他に相違",
    "取り込むことができません",
    "ログファイル",
    "見つかりません",
    "一致する",
)


class JdlCsvStructuralAnalyzer:
    def __init__(
        self,
        delimiter: str = ",",
        encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp932"),
        message_parser: JdlImportDiagnosticMessageParser | None = None,
        observed_schema: ObservedJdlSchema | None = None,
    ) -> None:
        self.delimiter = delimiter
        self.encodings = encodings
        self.message_parser = message_parser or JdlImportDiagnosticMessageParser()
        self.observed_schema = observed_schema

    def analyze_path(self, path: Path) -> JdlCsvAnalysisResult:
        raw = path.read_bytes()
        text, encoding, decoding_error = self._decode(raw)
        return self.analyze_text(
            text,
            file_name=path.name,
            encoding=encoding,
            has_bom=raw.startswith(b"\xef\xbb\xbf"),
            decoding_error=decoding_error,
        )

    def analyze_text(
        self,
        text: str,
        file_name: str = "<memory>",
        encoding: str = "unknown",
        has_bom: bool = False,
        decoding_error: str | None = None,
    ) -> JdlCsvAnalysisResult:
        line_ending = self._detect_line_ending(text)
        physical_lines = text.splitlines()
        if text and text.endswith(("\n", "\r")):
            # splitlines() intentionally omits the final empty logical tail.
            pass

        observations: list[JdlCsvLineObservation] = []
        header_columns: tuple[str, ...] = ()
        header_row_number: int | None = None
        expected_column_count: int | None = None
        warnings: list[ValidationResult] = []
        errors: list[ValidationResult] = []
        last_journal_record: JdlCsvLineObservation | None = None

        if decoding_error is not None:
            errors.append(
                self._result(
                    Severity.ERROR,
                    "JDLCSV-ENCODING",
                    "文字コードとして安全に復号できないバイト列があります。",
                    file_name,
                    None,
                    "encoding",
                    decoding_error,
                    "元CSVの文字コードを確認してください。",
                )
            )

        for row_number, raw_line in enumerate(physical_lines, start=1):
            observation = self._observe_line(row_number, raw_line)

            if observation.classification is CsvLineClassification.INVALID_CSV:
                errors.append(
                    self._result(
                        Severity.ERROR,
                        "JDLCSV-CSV-SYNTAX",
                        "CSVとして構文解析できない行があります。",
                        file_name,
                        row_number,
                        "csv",
                        observation.csv_error,
                        "クォートや区切り文字を確認してください。",
                    )
                )
            elif observation.classification is CsvLineClassification.EMPTY:
                pass
            elif observation.classification is CsvLineClassification.DIAGNOSTIC_MESSAGE:
                observation = self._enrich_diagnostic_observation(
                    observation=observation,
                    header_columns=header_columns,
                    related_record=last_journal_record,
                )
                warnings.append(
                    self._result(
                        Severity.WARNING,
                        "JDLCSV-DIAGNOSTIC-MESSAGE",
                        "JDL診断メッセージらしき行を検出しました。",
                        file_name,
                        row_number,
                        "message",
                        observation.raw_text,
                        "JDLのログまたは出力内容と照合してください。",
                    )
                )
                if observation.master_reference_issue is not None:
                    warnings.append(
                        self._result(
                            Severity.WARNING,
                            "JDLCSV-MASTER-REFERENCE",
                            "JDLマスター参照不一致の候補を検出しました。",
                            file_name,
                            row_number,
                            observation.master_reference_issue.field,
                            observation.master_reference_issue.message,
                            "JDL側マスターとCSV上の値の対応を確認してください。",
                        )
                    )
                if self._has_nonempty_diagnostic_tail(observation.columns):
                    warnings.append(
                        self._result(
                            Severity.WARNING,
                            "JDLCSV-DIAGNOSTIC-NONEMPTY-TAIL",
                            "JDL診断コメント行の後続列に非空値があります。",
                            file_name,
                            row_number,
                            "diagnostic_tail",
                            observation.columns[1:],
                            "診断コメント行か通常データ行かを実ファイルで確認してください。",
                        )
                    )
            elif observation.classification is CsvLineClassification.METADATA:
                pass
            elif observation.classification is CsvLineClassification.HEADER:
                if header_row_number is None:
                    header_row_number = row_number
                    header_columns = observation.columns
                    expected_column_count = observation.column_count
                    duplicates = self._duplicate_values(header_columns)
                    if duplicates:
                        warnings.append(
                            self._result(
                                Severity.WARNING,
                                "JDLCSV-DUPLICATE-HEADER",
                                "重複ヘッダーを検出しました。",
                                file_name,
                                row_number,
                                "header",
                                tuple(duplicates),
                                "正式仕様または正常サンプルと比較してください。",
                            )
                        )
            elif header_row_number is None and observation.column_count > 1:
                observation = JdlCsvLineObservation(
                    row_number=observation.row_number,
                    raw_text=observation.raw_text,
                    classification=CsvLineClassification.HEADER,
                    columns=observation.columns,
                    csv_error=observation.csv_error,
                    master_reference_issue=observation.master_reference_issue,
                )
                header_row_number = row_number
                header_columns = observation.columns
                expected_column_count = observation.column_count
                duplicates = self._duplicate_values(header_columns)
                if duplicates:
                    warnings.append(
                        self._result(
                            Severity.WARNING,
                            "JDLCSV-DUPLICATE-HEADER",
                            "重複ヘッダーを検出しました。",
                            file_name,
                            row_number,
                            "header",
                            tuple(duplicates),
                            "正式仕様または正常サンプルと比較してください。",
                        )
                    )
            elif expected_column_count is not None and observation.column_count > 1:
                if observation.column_count != expected_column_count:
                    errors.append(
                        self._result(
                            Severity.ERROR,
                            "JDLCSV-COLUMN-COUNT",
                            "ヘッダー列数と一致しないデータ行があります。",
                            file_name,
                            row_number,
                            "column_count",
                            {
                                "header": expected_column_count,
                                "record": observation.column_count,
                            },
                            "欠落項目、余分なカンマ、クォート不整合を確認してください。",
                        )
                    )
                if self.observed_schema is None and "" in observation.columns:
                    warnings.append(
                        self._result(
                            Severity.WARNING,
                            "JDLCSV-EMPTY-FIELD",
                            "空項目を含むデータ行を検出しました。",
                            file_name,
                            row_number,
                            "empty_field",
                            observation.columns,
                            "正式仕様または正常サンプル上で空欄が許容される項目か確認してください。",
                        )
                    )
                observation = JdlCsvLineObservation(
                    row_number=observation.row_number,
                    raw_text=observation.raw_text,
                    classification=CsvLineClassification.JOURNAL_RECORD,
                    columns=observation.columns,
                    csv_error=observation.csv_error,
                    master_reference_issue=observation.master_reference_issue,
                    diagnostic_issue=observation.diagnostic_issue,
                )
                last_journal_record = observation
            elif observation.classification is CsvLineClassification.UNKNOWN:
                warnings.append(
                    self._result(
                        Severity.WARNING,
                        "JDLCSV-UNKNOWN-LINE",
                        "CSVデータ、メタデータ、診断メッセージのいずれとも確定できない行があります。",
                        file_name,
                        row_number,
                        "line",
                        observation.raw_text,
                        "行の意味を確認してください。",
                    )
                )

            observations.append(observation)

        if header_row_number is None:
            errors.append(
                self._result(
                    Severity.ERROR,
                    "JDLCSV-NO-HEADER",
                    "ヘッダー行を特定できませんでした。",
                    file_name,
                    None,
                    "header",
                    None,
                    "CSVの先頭構造とメタデータ行を確認してください。",
                )
            )

        nonempty_column_counts = [
            line.column_count
            for line in observations
            if line.classification
            not in {
                CsvLineClassification.EMPTY,
                CsvLineClassification.METADATA,
                CsvLineClassification.DIAGNOSTIC_MESSAGE,
                CsvLineClassification.INVALID_CSV,
                CsvLineClassification.UNKNOWN,
            }
        ]
        line_column_counts = tuple(
            (line.row_number, line.column_count) for line in observations
        )
        journal_record_lines = tuple(
            line
            for line in observations
            if line.classification is CsvLineClassification.JOURNAL_RECORD
        )
        identifier_flag_counts = tuple(
            sorted(
                Counter(
                    line.columns[0]
                    for line in journal_record_lines
                    if line.columns and line.columns[0]
                ).items()
            )
        )
        diagnostic_issues = tuple(
            line.diagnostic_issue
            for line in observations
            if line.diagnostic_issue is not None
        )
        observed_grouping_summary = self._build_observed_grouping_summary(
            journal_record_lines
        )
        result_without_fingerprint = JdlCsvAnalysisResult(
            file_name=file_name,
            encoding=encoding,
            delimiter=self.delimiter,
            total_physical_lines=len(physical_lines),
            comment_metadata_line_count=sum(
                1
                for line in observations
                if line.classification is CsvLineClassification.METADATA
            ),
            header_row_number=header_row_number,
            header_columns=header_columns,
            data_line_count=len(journal_record_lines),
            identifier_flag_counts=identifier_flag_counts,
            line_column_counts=line_column_counts,
            max_column_count=max(nonempty_column_counts, default=0),
            min_column_count=min(nonempty_column_counts, default=0),
            invalid_csv_lines=tuple(
                line
                for line in observations
                if line.classification is CsvLineClassification.INVALID_CSV
            ),
            empty_lines=tuple(
                line
                for line in observations
                if line.classification is CsvLineClassification.EMPTY
            ),
            diagnostic_message_lines=tuple(
                line
                for line in observations
                if line.classification is CsvLineClassification.DIAGNOSTIC_MESSAGE
            ),
            analysis_warnings=tuple(warnings),
            analysis_errors=tuple(errors),
            line_observations=tuple(observations),
            has_bom=has_bom,
            line_ending=line_ending,
            diagnostic_issues=diagnostic_issues,
            master_mismatch_summary=MasterMismatchSummary.from_issues(
                diagnostic_issues
            ),
            observed_schema=self._build_observed_schema(
                header_columns=header_columns,
                journal_count=len(journal_record_lines),
                encoding=encoding,
                has_bom=has_bom,
                line_ending=line_ending,
            ),
            observed_grouping_summary=observed_grouping_summary,
        )
        return JdlCsvAnalysisResult(
            **{
                **result_without_fingerprint.__dict__,
                "schema_fingerprint": JdlCsvSchemaFingerprint.from_analysis(
                    result_without_fingerprint
                ),
            }
        )

    def _observe_line(self, row_number: int, raw_line: str) -> JdlCsvLineObservation:
        stripped = raw_line.strip()
        if stripped == "":
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.EMPTY,
            )

        quote_error = self._quote_error(raw_line)
        if quote_error is not None:
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.INVALID_CSV,
                csv_error=quote_error,
            )

        try:
            columns = self._parse_line(raw_line)
        except csv.Error as error:
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.INVALID_CSV,
                csv_error=str(error),
            )
        first_cell = columns[0] if columns else raw_line
        diagnostic_issue = self.message_parser.parse(first_cell, row_number)
        issue = self._to_master_reference_issue(row_number, raw_line, diagnostic_issue)
        if diagnostic_issue is not None or self._looks_like_jdl_message(first_cell):
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.DIAGNOSTIC_MESSAGE,
                columns=tuple(columns),
                master_reference_issue=issue,
                diagnostic_issue=diagnostic_issue,
            )

        if self._is_observed_header(columns):
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.HEADER,
                columns=tuple(columns),
            )

        if stripped.startswith("//"):
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.METADATA,
                columns=tuple(columns),
            )

        if columns and all(column.strip() == "" for column in columns):
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.EMPTY,
                columns=tuple(columns),
            )

        if len(columns) <= 1:
            return JdlCsvLineObservation(
                row_number=row_number,
                raw_text=raw_line,
                classification=CsvLineClassification.UNKNOWN,
                columns=tuple(columns),
            )

        return JdlCsvLineObservation(
            row_number=row_number,
            raw_text=raw_line,
            classification=CsvLineClassification.UNKNOWN,
            columns=tuple(columns),
        )

    def _parse_line(self, raw_line: str) -> list[str]:
        return next(
            csv.reader(
                [raw_line],
                delimiter=self.delimiter,
                quotechar='"',
                doublequote=True,
                strict=True,
            )
        )

    def _decode(self, raw: bytes) -> tuple[str, str, str | None]:
        for encoding in self.encodings:
            try:
                return raw.decode(encoding), encoding, None
            except UnicodeDecodeError:
                continue
        return raw.decode(self.encodings[-1], errors="replace"), self.encodings[-1], (
            "replacement characters were required"
        )

    def _detect_line_ending(self, text: str) -> str:
        crlf = text.count("\r\n")
        without_crlf = text.replace("\r\n", "")
        lf = without_crlf.count("\n")
        cr = without_crlf.count("\r")
        counts = {"CRLF": crlf, "LF": lf, "CR": cr}
        detected, count = max(counts.items(), key=lambda item: item[1])
        if count == 0:
            return "none"
        active = [name for name, value in counts.items() if value > 0]
        if len(active) > 1:
            return "mixed"
        return detected

    def _quote_error(self, raw_line: str) -> str | None:
        in_quotes = False
        index = 0
        while index < len(raw_line):
            char = raw_line[index]
            if char == '"':
                if in_quotes and index + 1 < len(raw_line) and raw_line[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = not in_quotes
            index += 1
        if in_quotes:
            return "unclosed quoted field"
        return None

    def _enrich_diagnostic_observation(
        self,
        observation: JdlCsvLineObservation,
        header_columns: tuple[str, ...],
        related_record: JdlCsvLineObservation | None,
    ) -> JdlCsvLineObservation:
        if observation.diagnostic_issue is None:
            return observation
        issue = observation.diagnostic_issue
        if related_record is None:
            return observation

        source_value = issue.source_value
        account_value = issue.account_value
        field_resolution_status = issue.field_resolution_status
        if (
            self.observed_schema is not None
            and issue.field is not None
            and source_value is None
        ):
            source_value = self._value_from_observed_schema(
                related_record.columns,
                issue.field,
            )
            if issue.master_type is JdlMasterType.ACCOUNT:
                source_value = self._account_display_value_from_observed_schema(
                    related_record.columns,
                    issue.side,
                    source_value,
                )
            account_value = self._account_value_from_observed_schema(
                related_record.columns,
                issue.side,
            )
            if source_value is not None:
                field_resolution_status = FieldResolutionStatus.FROM_OBSERVED_SCHEMA
        _ = header_columns
        enriched_issue = DiagnosticIssue(
            category=issue.category,
            side=issue.side,
            master_type=issue.master_type,
            source_row=issue.source_row,
            source_value=source_value,
            raw_message=issue.raw_message,
            severity=issue.severity,
            field=issue.field,
            related_record_row=related_record.row_number,
            account_value=account_value,
            association_status=DiagnosticAssociationStatus.LINKED_TO_PREVIOUS_RECORD,
            field_resolution_status=field_resolution_status,
        )
        return JdlCsvLineObservation(
            row_number=observation.row_number,
            raw_text=observation.raw_text,
            classification=observation.classification,
            columns=observation.columns,
            csv_error=observation.csv_error,
            master_reference_issue=self._to_master_reference_issue(
                observation.row_number,
                observation.raw_text,
                enriched_issue,
            ),
            diagnostic_issue=enriched_issue,
        )

    def _to_master_reference_issue(
        self,
        row_number: int,
        raw_line: str,
        diagnostic_issue: DiagnosticIssue | None,
    ) -> MasterReferenceIssue | None:
        if diagnostic_issue is None:
            return None
        if diagnostic_issue.master_type is JdlMasterType.UNKNOWN:
            return None
        return MasterReferenceIssue(
            row_number=row_number,
            field=diagnostic_issue.field or "unknown",
            message=diagnostic_issue.raw_message,
            raw_text=raw_line,
            diagnostic_issue=diagnostic_issue,
        )

    def _looks_like_jdl_message(self, raw_line: str) -> bool:
        return any(marker in raw_line for marker in DIAGNOSTIC_MESSAGE_MARKERS)

    def _is_observed_header(self, columns: list[str]) -> bool:
        if self.observed_schema is None:
            return False
        return tuple(columns) == self.observed_schema.observed_header

    def _has_nonempty_diagnostic_tail(self, columns: tuple[str, ...]) -> bool:
        return any(column.strip() for column in columns[1:])

    def _value_from_observed_schema(
        self,
        record_columns: tuple[str, ...],
        field: str,
    ) -> str | None:
        if self.observed_schema is None:
            return None
        index = self.observed_schema.column_index_for(field)
        if index is None or index >= len(record_columns):
            return None
        value = record_columns[index].strip()
        return value or None

    def _account_value_from_observed_schema(
        self,
        record_columns: tuple[str, ...],
        side: AccountingSide,
    ) -> str | None:
        if side is AccountingSide.DEBIT:
            return self._value_from_observed_schema(record_columns, "debit_account")
        if side is AccountingSide.CREDIT:
            return self._value_from_observed_schema(record_columns, "credit_account")
        return None

    def _account_display_value_from_observed_schema(
        self,
        record_columns: tuple[str, ...],
        side: AccountingSide,
        account_name: str | None,
    ) -> str | None:
        if side is AccountingSide.DEBIT:
            account_code = self._value_from_observed_schema(
                record_columns, "debit_account_code"
            )
        elif side is AccountingSide.CREDIT:
            account_code = self._value_from_observed_schema(
                record_columns, "credit_account_code"
            )
        else:
            account_code = None
        if account_code and account_name:
            return f"{account_code} {account_name}"
        return account_name or account_code

    def _build_observed_grouping_summary(
        self,
        journal_record_lines: tuple[JdlCsvLineObservation, ...],
    ) -> ObservedJournalGroupingSummary:
        if self.observed_schema is None:
            return ObservedJournalGroupingSummary()

        candidates: list[ObservedJournalGroupCandidate] = []
        record_index = 0
        while record_index < len(journal_record_lines):
            line = journal_record_lines[record_index]
            flag = self._observed_record_value(line, "identifier_flag")
            if flag in {"1000", "1111"}:
                candidates.append(
                    self._single_record_candidate(
                        candidate_number=len(candidates) + 1,
                        data_record_index=record_index + 1,
                        line=line,
                        flag=flag,
                    )
                )
                record_index += 1
                continue

            if flag == "1110":
                group_start = record_index
                group_lines = [line]
                record_index += 1
                while record_index < len(journal_record_lines):
                    next_line = journal_record_lines[record_index]
                    next_flag = self._observed_record_value(
                        next_line,
                        "identifier_flag",
                    )
                    if next_flag in {"1100", "1101"}:
                        group_lines.append(next_line)
                        record_index += 1
                        if next_flag == "1101":
                            break
                        continue
                    if next_flag in {"1000", "1110", "1111"}:
                        break
                    group_lines.append(next_line)
                    record_index += 1

                candidates.append(
                    self._multi_record_candidate(
                        candidate_number=len(candidates) + 1,
                        start_data_record_index=group_start + 1,
                        lines=tuple(group_lines),
                    )
                )
                continue

            candidates.append(
                self._unresolved_single_record_candidate(
                    candidate_number=len(candidates) + 1,
                    data_record_index=record_index + 1,
                    line=line,
                    flag=flag,
                )
            )
            record_index += 1

        return ObservedJournalGroupingSummary(candidates=tuple(candidates))

    def _single_record_candidate(
        self,
        candidate_number: int,
        data_record_index: int,
        line: JdlCsvLineObservation,
        flag: str,
    ) -> ObservedJournalGroupCandidate:
        debit_total, debit_warning = self._amount_from_observed_schema(
            line,
            "debit_amount",
        )
        credit_total, credit_warning = self._amount_from_observed_schema(
            line,
            "credit_amount",
        )
        balanced = debit_total == credit_total
        warnings = tuple(
            warning
            for warning in (debit_warning, credit_warning)
            if warning is not None
        )
        if not balanced:
            warnings = warnings + ("debit_credit_not_balanced",)
        status = (
            ObservedJournalGroupStatus.OBSERVED_SINGLE_RECORD
            if balanced and not warnings
            else ObservedJournalGroupStatus.UNRESOLVED
        )
        return ObservedJournalGroupCandidate(
            candidate_id=self._candidate_id(candidate_number),
            start_record_index=data_record_index,
            end_record_index=data_record_index,
            record_count=1,
            identifier_flags=(flag,),
            voucher_number=self._observed_record_value(line, "voucher_number"),
            date=self._observed_record_value(line, "date"),
            debit_total=debit_total,
            credit_total=credit_total,
            balanced=balanced,
            grouping_confidence="OBSERVED_ONLY",
            grouping_basis=(f"observed_identifier_flag:{flag}",),
            status=status,
            warnings=warnings,
        )

    def _unresolved_single_record_candidate(
        self,
        candidate_number: int,
        data_record_index: int,
        line: JdlCsvLineObservation,
        flag: str | None,
    ) -> ObservedJournalGroupCandidate:
        debit_total, debit_warning = self._amount_from_observed_schema(
            line,
            "debit_amount",
        )
        credit_total, credit_warning = self._amount_from_observed_schema(
            line,
            "credit_amount",
        )
        warnings = tuple(
            warning
            for warning in (
                "unresolved_identifier_flag",
                debit_warning,
                credit_warning,
            )
            if warning is not None
        )
        return ObservedJournalGroupCandidate(
            candidate_id=self._candidate_id(candidate_number),
            start_record_index=data_record_index,
            end_record_index=data_record_index,
            record_count=1,
            identifier_flags=(flag or "",),
            voucher_number=self._observed_record_value(line, "voucher_number"),
            date=self._observed_record_value(line, "date"),
            debit_total=debit_total,
            credit_total=credit_total,
            balanced=debit_total == credit_total,
            grouping_confidence="OBSERVED_ONLY",
            grouping_basis=(f"observed_identifier_flag:{flag or '(empty)'}",),
            status=ObservedJournalGroupStatus.UNRESOLVED,
            warnings=warnings,
        )

    def _multi_record_candidate(
        self,
        candidate_number: int,
        start_data_record_index: int,
        lines: tuple[JdlCsvLineObservation, ...],
    ) -> ObservedJournalGroupCandidate:
        flags = tuple(
            self._observed_record_value(line, "identifier_flag") or ""
            for line in lines
        )
        voucher_numbers = tuple(
            self._observed_record_value(line, "voucher_number") for line in lines
        )
        dates = tuple(self._observed_record_value(line, "date") for line in lines)
        amounts = tuple(
            self._amount_from_observed_schema(line, field)
            for line in lines
            for field in ("debit_amount", "credit_amount")
        )
        amount_warnings = tuple(
            warning for _, warning in amounts if warning is not None
        )
        debit_total = sum(
            (
                self._amount_from_observed_schema(line, "debit_amount")[0]
                for line in lines
            ),
            Decimal("0"),
        )
        credit_total = sum(
            (
                self._amount_from_observed_schema(line, "credit_amount")[0]
                for line in lines
            ),
            Decimal("0"),
        )
        valid_sequence = (
            len(flags) >= 2
            and flags[0] == "1110"
            and flags[-1] == "1101"
            and all(flag == "1100" for flag in flags[1:-1])
        )
        same_voucher_number = self._all_same_known(voucher_numbers)
        same_date = self._all_same_known(dates)
        balanced = debit_total == credit_total

        warnings: list[str] = list(amount_warnings)
        if not valid_sequence:
            warnings.append("invalid_observed_identifier_sequence")
        if not same_voucher_number:
            warnings.append("voucher_number_not_consistent")
        if not same_date:
            warnings.append("date_not_consistent")
        if not balanced:
            warnings.append("debit_credit_not_balanced")

        status = (
            ObservedJournalGroupStatus.OBSERVED_MULTI_RECORD_SEQUENCE
            if valid_sequence and same_voucher_number and same_date and balanced and not warnings
            else ObservedJournalGroupStatus.UNRESOLVED
        )
        return ObservedJournalGroupCandidate(
            candidate_id=self._candidate_id(candidate_number),
            start_record_index=start_data_record_index,
            end_record_index=start_data_record_index + len(lines) - 1,
            record_count=len(lines),
            identifier_flags=flags,
            voucher_number=voucher_numbers[0] if same_voucher_number else None,
            date=dates[0] if same_date else None,
            debit_total=debit_total,
            credit_total=credit_total,
            balanced=balanced,
            grouping_confidence="OBSERVED_ONLY",
            grouping_basis=("observed_identifier_sequence:1110-1100*-1101",),
            status=status,
            valid_sequence=valid_sequence,
            same_voucher_number=same_voucher_number,
            same_date=same_date,
            warnings=tuple(warnings),
        )

    def _candidate_id(self, candidate_number: int) -> str:
        return f"G{candidate_number:06d}"

    def _observed_record_value(
        self,
        line: JdlCsvLineObservation,
        field: str,
    ) -> str | None:
        value = self._value_from_observed_schema(line.columns, field)
        if value is not None:
            return value
        if field == "identifier_flag" and line.columns:
            return line.columns[0].strip() or None
        return None

    def _amount_from_observed_schema(
        self,
        line: JdlCsvLineObservation,
        field: str,
    ) -> tuple[Decimal, str | None]:
        raw_value = self._observed_record_value(line, field)
        if raw_value is None:
            return Decimal("0"), f"{field}_unresolved"
        normalized = raw_value.replace(",", "").strip()
        if normalized == "":
            return Decimal("0"), None
        try:
            return Decimal(normalized), None
        except InvalidOperation:
            return Decimal("0"), f"{field}_parse_error"

    def _all_same_known(self, values: tuple[str | None, ...]) -> bool:
        if not values or any(value is None for value in values):
            return False
        return len(set(values)) == 1

    def _build_observed_schema(
        self,
        header_columns: tuple[str, ...],
        journal_count: int,
        encoding: str,
        has_bom: bool,
        line_ending: str,
    ) -> ObservedJdlSchema | None:
        if self.observed_schema is None:
            return None
        return ObservedJdlSchema(
            product=self.observed_schema.product,
            observed_version=self.observed_schema.observed_version,
            encoding=encoding,
            has_bom=has_bom,
            line_ending=line_ending,
            journal_column_count=len(header_columns),
            observed_header=header_columns,
            journal_count=journal_count,
            field_names=dict(self.observed_schema.field_names),
            observed_identifier_flags=self.observed_schema.observed_identifier_flags,
            identifier_flag_meaning_status=(
                self.observed_schema.identifier_flag_meaning_status
            ),
            observed_behavior=self.observed_schema.observed_behavior,
            is_formal_format_profile=False,
        )

    def _duplicate_values(self, values: tuple[str, ...]) -> list[str]:
        counts = Counter(values)
        return [value for value, count in counts.items() if value and count > 1]

    def _result(
        self,
        severity: Severity,
        rule_id: str,
        message: str,
        file_name: str,
        row_number: int | None,
        field: str | None,
        input_value: object,
        suggested_action: str | None,
    ) -> ValidationResult:
        return ValidationResult(
            severity=severity,
            rule_id=rule_id,
            message=message,
            source_reference=SourceReference(file_name, row_number=row_number),
            field=field,
            input_value=input_value,
            suggested_action=suggested_action,
        )

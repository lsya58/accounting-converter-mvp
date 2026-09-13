from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accounting_converter.domain.journal import SourceReference
from accounting_converter.domain.validation import Severity, ValidationResult

from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER,
)

from .models import (
    ColumnPopulation,
    JdlAccountingJournalListAnalysisResult,
    JdlAccountingJournalListComparison,
    JdlAccountingJournalListReadiness,
    JdlAccountingJournalListRecordCandidate,
)
from .observed_schemas import (
    ObservedJdlAccountingJournalListSchema,
    jdl_accounting_journal_list_observed_schema,
)


class JdlAccountingJournalListAnalyzer:
    def __init__(
        self,
        schema: ObservedJdlAccountingJournalListSchema | None = None,
        encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp932"),
    ) -> None:
        self.schema = schema or jdl_accounting_journal_list_observed_schema()
        self.encodings = encodings

    def analyze_path(self, path: Path) -> JdlAccountingJournalListAnalysisResult:
        raw = path.read_bytes()
        text, encoding, decode_error = self._decode(raw)
        return self.analyze_text(
            text,
            file_name=path.name,
            encoding=encoding,
            has_bom=raw.startswith(b"\xef\xbb\xbf"),
            line_ending=self._detect_line_ending(raw),
            decode_error=decode_error,
        )

    def analyze_text(
        self,
        text: str,
        file_name: str = "<memory>",
        encoding: str = "unknown",
        has_bom: bool = False,
        line_ending: str = "UNKNOWN",
        decode_error: str | None = None,
    ) -> JdlAccountingJournalListAnalysisResult:
        rows: list[tuple[int, tuple[str, ...], str | None]] = []
        errors: list[ValidationResult] = []
        warnings: list[ValidationResult] = []
        physical_lines = text.splitlines()

        if decode_error is not None:
            errors.append(
                self._result(
                    Severity.ERROR,
                    "JDL-ACCOUNTING-LIST-ENCODING",
                    "JDL会計仕訳一覧CSVを安全に復号できないバイト列があります。",
                    file_name,
                    None,
                    "encoding",
                    None,
                )
            )
        if encoding != self.schema.encoding:
            warnings.append(
                self._result(
                    Severity.WARNING,
                    "JDL-ACCOUNTING-LIST-ENCODING-CANDIDATE",
                    "Observed evidenceと異なる文字コード候補です。",
                    file_name,
                    None,
                    "encoding",
                    None,
                )
            )
        if has_bom != self.schema.has_bom:
            warnings.append(
                self._result(
                    Severity.WARNING,
                    "JDL-ACCOUNTING-LIST-BOM",
                    "Observed evidenceと異なるBOM状態です。",
                    file_name,
                    None,
                    "bom",
                    None,
                )
            )
        if line_ending != self.schema.line_ending:
            warnings.append(
                self._result(
                    Severity.WARNING,
                    "JDL-ACCOUNTING-LIST-NEWLINE",
                    "Observed evidenceと異なる行末コードです。",
                    file_name,
                    None,
                    "line_ending",
                    None,
                )
            )

        for row_number, raw_line in enumerate(physical_lines, start=1):
            try:
                parsed = next(csv.reader([raw_line], strict=True))
            except csv.Error:
                parsed = ()
                parse_error = "csv_parse_error"
                errors.append(
                    self._result(
                        Severity.ERROR,
                        "JDL-ACCOUNTING-LIST-MALFORMED-CSV",
                        "CSVとして構文解析できない行があります。",
                        file_name,
                        row_number,
                        "csv",
                        None,
                    )
                )
            else:
                parse_error = None
            rows.append((row_number, tuple(parsed), parse_error))

        blank_row_count = sum(1 for _, row, _ in rows if not any(cell.strip() for cell in row))
        header_row_number = self._find_header_row(rows)
        header_columns: tuple[str, ...] = ()
        data_rows: list[tuple[int, tuple[str, ...]]] = []
        malformed_row_numbers: list[int] = []
        if header_row_number is None:
            errors.append(
                self._result(
                    Severity.ERROR,
                    "JDL-ACCOUNTING-LIST-NO-HEADER",
                    "JDL会計仕訳一覧の21列headerを特定できませんでした。",
                    file_name,
                    None,
                    "header",
                    None,
                )
            )
        else:
            header_columns = rows[header_row_number - 1][1]
            for row_number, row, parse_error in rows[header_row_number:]:
                if parse_error is not None or not any(cell.strip() for cell in row):
                    continue
                if len(row) == self.schema.column_count:
                    data_rows.append((row_number, row))
                else:
                    malformed_row_numbers.append(row_number)
                    warnings.append(
                        self._result(
                            Severity.WARNING,
                            "JDL-ACCOUNTING-LIST-ROW-WIDTH",
                            "Header列数と異なる非空行があります。",
                            file_name,
                            row_number,
                            "column_count",
                            None,
                        )
                    )

        populations = self._column_populations(data_rows)
        record_candidates, record_errors = self._record_candidates(data_rows, file_name)
        errors.extend(record_errors)

        comparison = self._comparison_to_cashbook(header_columns)
        if errors:
            readiness = JdlAccountingJournalListReadiness.PARSE_FAILED
        else:
            readiness = (
                JdlAccountingJournalListReadiness.INSUFFICIENT_EVIDENCE_FOR_COMMON_JOURNAL
            )

        return JdlAccountingJournalListAnalysisResult(
            file_name=file_name,
            encoding=encoding,
            has_bom=has_bom,
            line_ending=line_ending,
            total_physical_lines=len(physical_lines),
            logical_row_count=len(rows),
            preamble_line_count=(header_row_number - 1) if header_row_number else len(rows),
            header_row_number=header_row_number,
            header_columns=header_columns,
            header_column_count=len(header_columns) if header_columns else None,
            data_row_count=len(data_rows),
            data_row_column_count_distribution=tuple(
                sorted(Counter(len(row) for _, row in data_rows).items())
            ),
            malformed_row_numbers=tuple(malformed_row_numbers),
            blank_row_count=blank_row_count,
            column_populations=populations,
            parseable_date_count=sum(1 for candidate in record_candidates if candidate.date),
            parseable_amount_count=sum(1 for candidate in record_candidates if candidate.amount),
            record_candidates=tuple(record_candidates),
            warnings=tuple(warnings),
            errors=tuple(errors),
            observed_schema=self.schema,
            comparison_to_cashbook_30_column=comparison,
            readiness=readiness,
        )

    def _decode(self, raw: bytes) -> tuple[str, str, str | None]:
        for encoding in self.encodings:
            try:
                return raw.decode(encoding), encoding, None
            except UnicodeDecodeError as exc:
                last_error = f"{encoding}:{exc.start}"
        return raw.decode("cp932", errors="replace"), "unknown", last_error

    def _detect_line_ending(self, raw: bytes) -> str:
        without_crlf = raw.replace(b"\r\n", b"")
        if raw.count(b"\r\n") and b"\n" not in without_crlf and b"\r" not in without_crlf:
            return "CRLF"
        if b"\n" in raw and b"\r" not in raw:
            return "LF"
        if b"\r" in raw and b"\n" not in raw:
            return "CR"
        return "MIXED_OR_UNKNOWN"

    def _find_header_row(
        self,
        rows: list[tuple[int, tuple[str, ...], str | None]],
    ) -> int | None:
        for row_number, row, parse_error in rows:
            if parse_error is None and row == self.schema.observed_header:
                return row_number
        return None

    def _column_populations(
        self,
        data_rows: list[tuple[int, tuple[str, ...]]],
    ) -> tuple[ColumnPopulation, ...]:
        populations: list[ColumnPopulation] = []
        for index, column_name in enumerate(self.schema.observed_header):
            values = [row[index] for _, row in data_rows]
            populations.append(
                ColumnPopulation(
                    column_name=column_name or f"column_{index + 1}",
                    position_1_based=index + 1,
                    blank_count=sum(1 for value in values if not value.strip()),
                    nonblank_count=sum(1 for value in values if value.strip()),
                    distinct_count=len(set(values)),
                )
            )
        return tuple(populations)

    def _record_candidates(
        self,
        data_rows: list[tuple[int, tuple[str, ...]]],
        file_name: str,
    ) -> tuple[list[JdlAccountingJournalListRecordCandidate], list[ValidationResult]]:
        candidates: list[JdlAccountingJournalListRecordCandidate] = []
        errors: list[ValidationResult] = []
        idx = {
            field: self.schema.column_index_for(field)
            for field in (
                "voucher_number",
                "date",
                "debit_account",
                "debit_sub_account",
                "credit_account",
                "credit_sub_account",
                "amount",
                "description",
                "tax_scope",
                "tax_category",
            )
        }
        if any(value is None for value in idx.values()):
            errors.append(
                self._result(
                    Severity.ERROR,
                    "JDL-ACCOUNTING-LIST-FIELD-MAP",
                    "read-only候補解析に必要なheader列を特定できません。",
                    file_name,
                    None,
                    "header",
                    None,
                )
            )
            return candidates, errors

        for row_number, row in data_rows:
            parsed_date = self._parse_date(row[idx["date"]])  # type: ignore[index]
            amount = self._parse_amount(row[idx["amount"]])  # type: ignore[index]
            if parsed_date is None:
                errors.append(
                    self._result(
                        Severity.ERROR,
                        "JDL-ACCOUNTING-LIST-DATE",
                        "日付として解析できない行があります。",
                        file_name,
                        row_number,
                        "date",
                        None,
                    )
                )
                continue
            if amount is None:
                errors.append(
                    self._result(
                        Severity.ERROR,
                        "JDL-ACCOUNTING-LIST-AMOUNT",
                        "金額として解析できない行があります。",
                        file_name,
                        row_number,
                        "amount",
                        None,
                    )
                )
                continue
            debit_account = row[idx["debit_account"]].strip()  # type: ignore[index]
            credit_account = row[idx["credit_account"]].strip()  # type: ignore[index]
            if not debit_account or not credit_account:
                errors.append(
                    self._result(
                        Severity.ERROR,
                        "JDL-ACCOUNTING-LIST-ACCOUNT",
                        "借方または貸方科目を特定できない行があります。",
                        file_name,
                        row_number,
                        "account",
                        None,
                    )
                )
                continue
            candidates.append(
                JdlAccountingJournalListRecordCandidate(
                    row_number=row_number,
                    voucher_number=row[idx["voucher_number"]].strip(),  # type: ignore[index]
                    date=parsed_date,
                    debit_account=debit_account,
                    debit_sub_account=self._optional(row[idx["debit_sub_account"]]),  # type: ignore[index]
                    credit_account=credit_account,
                    credit_sub_account=self._optional(row[idx["credit_sub_account"]]),  # type: ignore[index]
                    amount=amount,
                    description=self._optional(row[idx["description"]]),  # type: ignore[index]
                    tax_scope=self._optional(row[idx["tax_scope"]]),  # type: ignore[index]
                    tax_category=self._optional(row[idx["tax_category"]]),  # type: ignore[index]
                )
            )
        return candidates, errors

    def _comparison_to_cashbook(
        self,
        header_columns: tuple[str, ...],
    ) -> JdlAccountingJournalListComparison:
        if header_columns == JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER:
            return JdlAccountingJournalListComparison.SAME_FAMILY_CANDIDATE
        shared = set(header_columns).intersection(JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER)
        if len(header_columns) == len(JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER) or len(shared) >= 10:
            return JdlAccountingJournalListComparison.PARTIAL_MATCH
        return JdlAccountingJournalListComparison.DIFFERENT_STRUCTURE

    def _parse_date(self, value: str) -> date | None:
        value = value.strip()
        for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
            try:
                from datetime import datetime

                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_amount(self, value: str) -> Decimal | None:
        cleaned = value.replace(",", "").replace("￥", "").replace("¥", "").strip()
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None

    def _optional(self, value: str) -> str | None:
        stripped = value.strip()
        return stripped or None

    def _result(
        self,
        severity: Severity,
        rule_id: str,
        message: str,
        file_name: str,
        row_number: int | None,
        field: str,
        input_value,
    ) -> ValidationResult:
        return ValidationResult(
            severity=severity,
            rule_id=rule_id,
            message=message,
            source_reference=SourceReference(file_name=file_name, row_number=row_number),
            field=field,
            input_value=input_value,
        )

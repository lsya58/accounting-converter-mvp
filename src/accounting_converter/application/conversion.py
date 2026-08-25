from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult

from .mapping_engine import MappingEngine
from .output_validation import OutputValidationResult, OutputValidator
from .verification_report import VerificationReportGenerator


class ConversionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    OUTPUT_PATH_ALREADY_EXISTS = "OUTPUT_PATH_ALREADY_EXISTS"
    INPUT_OUTPUT_PATH_CONFLICT = "INPUT_OUTPUT_PATH_CONFLICT"
    BLOCKED_BY_STRUCTURAL_VALIDATION = "BLOCKED_BY_STRUCTURAL_VALIDATION"
    BLOCKED_BY_MAPPING = "BLOCKED_BY_MAPPING"
    BLOCKED_BY_BUSINESS_VALIDATION = "BLOCKED_BY_BUSINESS_VALIDATION"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class StructuralValidator(Protocol):
    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        ...


class BusinessValidator(Protocol):
    def validate(self, entries: Iterable[JournalEntry]) -> list[ValidationResult]:
        ...


@dataclass(frozen=True)
class ConversionRequest:
    input_path: Path
    output_path: Path
    input_profile: FormatProfile
    output_profile: FormatProfile
    overwrite: bool = False


@dataclass(frozen=True)
class ConversionResult:
    status: str
    input_record_count: int
    input_journal_count: int
    output_record_count: int
    output_journal_count: int
    debit_total: Decimal
    credit_total: Decimal
    validation_results: tuple[ValidationResult, ...]
    error_count: int
    warning_count: int
    unresolved_mapping_count: int
    output_validation_result: OutputValidationResult | None
    output_path: Path | None
    verification_report: str
    completed_at: datetime


class ConversionService:
    def __init__(
        self,
        input_adapter: InputAdapter,
        structural_validator: StructuralValidator,
        mapping_engine: MappingEngine,
        business_validator: BusinessValidator,
        output_adapter: OutputAdapter,
        output_validator: OutputValidator,
        verification_report_generator: VerificationReportGenerator | None = None,
    ) -> None:
        self._input_adapter = input_adapter
        self._structural_validator = structural_validator
        self._mapping_engine = mapping_engine
        self._business_validator = business_validator
        self._output_adapter = output_adapter
        self._output_validator = output_validator
        self._report_generator = (
            verification_report_generator or VerificationReportGenerator()
        )

    def convert(self, request: ConversionRequest) -> ConversionResult:
        completed_at = datetime.now(timezone.utc)
        temp_path: Path | None = None
        validation_results: list[ValidationResult] = []
        output_validation_result: OutputValidationResult | None = None
        input_record_count = 0
        input_journal_count = 0
        output_record_count = 0
        output_journal_count = 0
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        unresolved_mapping_count = 0

        try:
            preflight_results = self._preflight_output_path(request)
            if preflight_results:
                validation_results.extend(preflight_results)
                status = (
                    ConversionStatus.INPUT_OUTPUT_PATH_CONFLICT
                    if any(
                        result.rule_id == "OUTPUT-INPUT-SAME-PATH"
                        for result in preflight_results
                    )
                    else ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS
                )
                return self._result(
                    status=status,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )

            structural_results = self._structural_validator.validate(
                request.input_path,
                request.input_profile,
            )
            validation_results.extend(structural_results)
            if self._has_blocking_validation(structural_results):
                return self._result(
                    status=ConversionStatus.BLOCKED_BY_STRUCTURAL_VALIDATION,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )

            entries = self._input_adapter.read(
                request.input_path,
                request.input_profile,
            )
            input_record_count = self._input_record_count(request, entries)
            input_journal_count = len(entries)
            debit_total = self._debit_total(entries)
            credit_total = self._credit_total(entries)

            mapping_result = self._mapping_engine.apply(entries)
            unresolved_mapping_count = mapping_result.unresolved_count
            validation_results.extend(mapping_result.validation_results)
            if unresolved_mapping_count:
                return self._result(
                    status=ConversionStatus.BLOCKED_BY_MAPPING,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )

            mapped_entries = mapping_result.entries
            debit_total = self._debit_total(mapped_entries)
            credit_total = self._credit_total(mapped_entries)

            business_results = self._business_validator.validate(mapped_entries)
            validation_results.extend(business_results)
            if self._has_blocking_validation(business_results):
                return self._result(
                    status=ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )

            temp_path = self._temporary_output_path(request.output_path)
            self._output_adapter.write(
                mapped_entries,
                temp_path,
                request.output_profile,
            )
            output_validation_result = self._output_validator.validate(
                temp_path,
                mapped_entries,
                request.output_profile,
            )
            validation_results.extend(output_validation_result.validation_results)
            output_record_count = output_validation_result.record_count
            output_journal_count = output_validation_result.journal_count
            if not output_validation_result.success:
                self._delete_temp_file(temp_path)
                return self._result(
                    status=ConversionStatus.OUTPUT_VALIDATION_FAILED,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )

            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            if request.output_path.exists() and not request.overwrite:
                self._delete_temp_file(temp_path)
                validation_results.append(self._output_exists_result(request))
                return self._result(
                    status=ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS,
                    request=request,
                    input_record_count=input_record_count,
                    input_journal_count=input_journal_count,
                    output_record_count=output_record_count,
                    output_journal_count=output_journal_count,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    validation_results=validation_results,
                    unresolved_mapping_count=unresolved_mapping_count,
                    output_validation_result=output_validation_result,
                    output_path=None,
                    completed_at=completed_at,
                )
            os.replace(temp_path, request.output_path)
            temp_path = None
            return self._result(
                status=ConversionStatus.SUCCESS,
                request=request,
                input_record_count=input_record_count,
                input_journal_count=input_journal_count,
                output_record_count=output_record_count,
                output_journal_count=output_journal_count,
                debit_total=debit_total,
                credit_total=credit_total,
                validation_results=validation_results,
                unresolved_mapping_count=unresolved_mapping_count,
                output_validation_result=output_validation_result,
                output_path=request.output_path,
                completed_at=completed_at,
            )
        except Exception as error:
            self._delete_temp_file(temp_path)
            validation_results.append(
                ValidationResult(
                    severity=Severity.FATAL,
                    rule_id="SYSTEM-ERROR",
                    message="変換処理中に予期しないエラーが発生しました。",
                    field="system",
                    input_value=error.__class__.__name__,
                    suggested_action="入力ファイル、出力先、設定を確認してください。",
                )
            )
            return self._result(
                status=ConversionStatus.SYSTEM_ERROR,
                request=request,
                input_record_count=input_record_count,
                input_journal_count=input_journal_count,
                output_record_count=output_record_count,
                output_journal_count=output_journal_count,
                debit_total=debit_total,
                credit_total=credit_total,
                validation_results=validation_results,
                unresolved_mapping_count=unresolved_mapping_count,
                output_validation_result=output_validation_result,
                output_path=None,
                completed_at=completed_at,
            )

    def _result(
        self,
        status: str,
        request: ConversionRequest,
        input_record_count: int,
        input_journal_count: int,
        output_record_count: int,
        output_journal_count: int,
        debit_total: Decimal,
        credit_total: Decimal,
        validation_results: Sequence[ValidationResult],
        unresolved_mapping_count: int,
        output_validation_result: OutputValidationResult | None,
        output_path: Path | None,
        completed_at: datetime,
    ) -> ConversionResult:
        results = tuple(validation_results)
        result = ConversionResult(
            status=status,
            input_record_count=input_record_count,
            input_journal_count=input_journal_count,
            output_record_count=output_record_count,
            output_journal_count=output_journal_count,
            debit_total=debit_total,
            credit_total=credit_total,
            validation_results=results,
            error_count=self._count_by_severity(results, Severity.ERROR),
            warning_count=self._count_by_severity(results, Severity.WARNING),
            unresolved_mapping_count=unresolved_mapping_count,
            output_validation_result=output_validation_result,
            output_path=output_path,
            verification_report="",
            completed_at=completed_at,
        )
        return ConversionResult(
            **{
                **result.__dict__,
                "verification_report": self._report_generator.generate(
                    result,
                    request,
                ),
            }
        )

    def _input_record_count(
        self,
        request: ConversionRequest,
        entries: Sequence[JournalEntry],
    ) -> int:
        counter = getattr(self._input_adapter, "record_count", None)
        if callable(counter):
            return int(counter(request.input_path, request.input_profile))
        return len(entries)

    def _temporary_output_path(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
        )
        os.close(handle)
        return Path(temp_name)

    def _preflight_output_path(
        self,
        request: ConversionRequest,
    ) -> list[ValidationResult]:
        if self._same_path(request.input_path, request.output_path):
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="OUTPUT-INPUT-SAME-PATH",
                    message="入力ファイルと出力ファイルに同じパスは指定できません。",
                    field="output_path",
                    input_value=request.output_path.name,
                    suggested_action="入力ファイルとは別の出力先を指定してください。",
                )
            ]
        if request.output_path.exists() and not request.overwrite:
            return [self._output_exists_result(request)]
        return []

    def _output_exists_result(self, request: ConversionRequest) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id="OUTPUT-PATH-EXISTS",
            message="出力先ファイルが既に存在します。明示的な上書き許可なしには保存しません。",
            field="output_path",
            input_value=request.output_path.name,
            suggested_action="別名で保存するか、上書きを明示的に許可してください。",
        )

    def _same_path(self, left: Path, right: Path) -> bool:
        return left.resolve(strict=False) == right.resolve(strict=False)

    def _delete_temp_file(self, temp_path: Path | None) -> None:
        if temp_path is None:
            return
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _has_blocking_validation(
        self,
        results: Iterable[ValidationResult],
    ) -> bool:
        return any(result.severity in {Severity.ERROR, Severity.FATAL} for result in results)

    def _count_by_severity(
        self,
        results: Iterable[ValidationResult],
        severity: Severity,
    ) -> int:
        return sum(1 for result in results if result.severity is severity)

    def _debit_total(self, entries: Iterable[JournalEntry]) -> Decimal:
        return sum((entry.debit_total() for entry in entries), Decimal("0"))

    def _credit_total(self, entries: Iterable[JournalEntry]) -> Decimal:
        return sum((entry.credit_total() for entry in entries), Decimal("0"))

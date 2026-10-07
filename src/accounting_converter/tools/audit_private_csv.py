from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from accounting_converter.adapters.input.moneyforward import (
    MONEYFORWARD_OBSERVED_HEADER,
    MoneyForwardInputAdapter,
    MoneyForwardInputAdapterError,
)
from accounting_converter.adapters.input.yayoi import (
    YayoiInputAdapter,
    YayoiInputAdapterError,
    YayoiStructuralValidator,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
    yayoi_ae19_direct_export_observed_schema,
)


YAYOI_FLAGS = frozenset({"2000", "2111", "2110", "2100", "2101"})


class AuditStatus(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AuditFileResult:
    file_id: str
    relative_path: str | None
    sha256: str
    size_bytes: int
    encoding_candidates: tuple[str, ...]
    accepted_encoding: str | None
    has_bom: bool
    newline_style: str
    physical_line_count: int
    csv_record_count: int | None
    column_count_distribution: tuple[tuple[int, int], ...]
    format_id: str | None
    format_label: str
    adapter_name: str | None
    status: AuditStatus
    record_count: int | None
    logical_journal_count: int | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    generated_at: str
    files_scanned: int
    pass_count: int
    block_count: int
    unknown_count: int
    error_count: int
    logical_journals_parsed: int
    file_pass_rate: float
    recognized_file_pass_rate: float | None
    detected_format_counts: tuple[tuple[str, int], ...]
    block_reason_counts: tuple[tuple[str, int], ...]
    files: tuple[AuditFileResult, ...]


class PrivateCsvAuditor:
    def __init__(
        self,
        moneyforward_adapter: MoneyForwardInputAdapter | None = None,
        yayoi_adapter: YayoiInputAdapter | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._moneyforward = moneyforward_adapter or MoneyForwardInputAdapter()
        self._yayoi = yayoi_adapter or YayoiInputAdapter()
        self._yayoi_validator = YayoiStructuralValidator(
            self._yayoi if isinstance(self._yayoi, YayoiInputAdapter) else None
        )
        self._now = now or (lambda: datetime.now(timezone.utc))
        mf_schema = moneyforward_cloud_journal_export_observed_schema()
        yayoi_schema = yayoi_ae19_direct_export_observed_schema()
        self._mf_profile = FormatProfile(
            software=mf_schema.identity.vendor,
            product=mf_schema.identity.product,
            version="UNKNOWN",
            format_id=mf_schema.identity.stable_key,
            encoding="cp932",
        )
        self._yayoi_profile = FormatProfile(
            software=yayoi_schema.identity.vendor,
            product=yayoi_schema.identity.product,
            version="19",
            format_id=yayoi_schema.identity.stable_key,
            encoding="cp932",
        )
        self._mf_identity = mf_schema.identity
        self._yayoi_identity = yayoi_schema.identity

    def audit_directory(
        self,
        root: Path,
        include_relative_paths: bool = False,
    ) -> AuditReport:
        paths = sorted(
            (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".csv"),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        files = tuple(
            self._audit_file(
                path,
                root,
                f"FILE-{index:03d}",
                include_relative_paths,
            )
            for index, path in enumerate(paths, start=1)
        )
        statuses = Counter(result.status for result in files)
        recognized = statuses[AuditStatus.PASS] + statuses[AuditStatus.BLOCK]
        format_counts = Counter(result.format_label for result in files)
        reasons = Counter(
            reason
            for result in files
            if result.status is AuditStatus.BLOCK
            for reason in result.reason_codes
        )
        total = len(files)
        return AuditReport(
            generated_at=self._now().astimezone(timezone.utc).isoformat(),
            files_scanned=total,
            pass_count=statuses[AuditStatus.PASS],
            block_count=statuses[AuditStatus.BLOCK],
            unknown_count=statuses[AuditStatus.UNKNOWN],
            error_count=statuses[AuditStatus.ERROR],
            logical_journals_parsed=sum(
                result.logical_journal_count or 0
                for result in files
                if result.status is AuditStatus.PASS
            ),
            file_pass_rate=(statuses[AuditStatus.PASS] / total * 100 if total else 0.0),
            recognized_file_pass_rate=(
                statuses[AuditStatus.PASS] / recognized * 100 if recognized else None
            ),
            detected_format_counts=tuple(sorted(format_counts.items())),
            block_reason_counts=tuple(
                sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
            ),
            files=files,
        )

    def _audit_file(
        self,
        path: Path,
        root: Path,
        file_id: str,
        include_relative_paths: bool,
    ) -> AuditFileResult:
        relative_path = path.relative_to(root).as_posix() if include_relative_paths else None
        try:
            raw = path.read_bytes()
        except OSError:
            return self._technical_error(file_id, relative_path)
        fingerprint = _fingerprint(raw)
        detection = self._detect(raw, fingerprint)
        if detection is None:
            return AuditFileResult(
                file_id=file_id,
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                encoding_candidates=fingerprint.encoding_candidates,
                accepted_encoding=fingerprint.accepted_encoding,
                has_bom=fingerprint.has_bom,
                newline_style=fingerprint.newline_style,
                physical_line_count=fingerprint.physical_line_count,
                csv_record_count=fingerprint.csv_record_count,
                column_count_distribution=fingerprint.column_count_distribution,
                format_id=None,
                format_label="UNKNOWN",
                adapter_name=None,
                status=AuditStatus.UNKNOWN,
                record_count=None,
                logical_journal_count=None,
                reason_codes=("NO_EXACT_FORMAT_IDENTITY",),
            )
        adapter, profile, format_id, format_label = detection
        if adapter is self._yayoi:
            validation_results = self._yayoi_validator.validate(path, profile)
            if validation_results:
                return self._recognized_result(
                    file_id,
                    relative_path,
                    raw,
                    fingerprint,
                    format_id,
                    format_label,
                    type(adapter).__name__,
                    AuditStatus.BLOCK,
                    (_validation_reason_code(validation_results[0].rule_id),),
                )
        try:
            entries = adapter.read(path, profile)
            records = adapter.record_count(path, profile)
        except (MoneyForwardInputAdapterError, YayoiInputAdapterError) as exc:
            return self._recognized_result(
                file_id,
                relative_path,
                raw,
                fingerprint,
                format_id,
                format_label,
                type(adapter).__name__,
                AuditStatus.BLOCK,
                (_reason_code(exc),),
            )
        except Exception:
            return self._recognized_result(
                file_id,
                relative_path,
                raw,
                fingerprint,
                format_id,
                format_label,
                type(adapter).__name__,
                AuditStatus.ERROR,
                ("AUDIT_TECHNICAL_ERROR",),
            )
        return self._recognized_result(
            file_id,
            relative_path,
            raw,
            fingerprint,
            format_id,
            format_label,
            type(adapter).__name__,
            AuditStatus.PASS,
            (),
            record_count=records,
            logical_journal_count=len(entries),
        )

    def _detect(self, raw: bytes, fingerprint: "_Fingerprint"):
        decoded = _decoded_variants(raw)
        for text in decoded.values():
            first_row = _first_csv_row(text)
            if first_row == MONEYFORWARD_OBSERVED_HEADER:
                return (
                    self._moneyforward,
                    self._mf_profile,
                    self._mf_identity.stable_key,
                    "MONEYFORWARD_JOURNAL_OBSERVED",
                )
        rows = fingerprint.rows
        if rows:
            first = rows[0]
            first_value = first[0].strip() if first else ""
            if first_value in YAYOI_FLAGS:
                return (
                    self._yayoi,
                    self._yayoi_profile,
                    self._yayoi_identity.stable_key,
                    "YAYOI_AE19_OBSERVED",
                )
        return None

    def _recognized_result(
        self,
        file_id: str,
        relative_path: str | None,
        raw: bytes,
        fingerprint: "_Fingerprint",
        format_id: str,
        format_label: str,
        adapter_name: str,
        status: AuditStatus,
        reason_codes: tuple[str, ...],
        record_count: int | None = None,
        logical_journal_count: int | None = None,
    ) -> AuditFileResult:
        return AuditFileResult(
            file_id=file_id,
            relative_path=relative_path,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            encoding_candidates=fingerprint.encoding_candidates,
            accepted_encoding=fingerprint.accepted_encoding,
            has_bom=fingerprint.has_bom,
            newline_style=fingerprint.newline_style,
            physical_line_count=fingerprint.physical_line_count,
            csv_record_count=fingerprint.csv_record_count,
            column_count_distribution=fingerprint.column_count_distribution,
            format_id=format_id,
            format_label=format_label,
            adapter_name=adapter_name,
            status=status,
            record_count=record_count,
            logical_journal_count=logical_journal_count,
            reason_codes=reason_codes,
        )

    @staticmethod
    def _technical_error(file_id: str, relative_path: str | None) -> AuditFileResult:
        return AuditFileResult(
            file_id=file_id,
            relative_path=relative_path,
            sha256="",
            size_bytes=0,
            encoding_candidates=(),
            accepted_encoding=None,
            has_bom=False,
            newline_style="UNKNOWN",
            physical_line_count=0,
            csv_record_count=None,
            column_count_distribution=(),
            format_id=None,
            format_label="UNKNOWN",
            adapter_name=None,
            status=AuditStatus.ERROR,
            record_count=None,
            logical_journal_count=None,
            reason_codes=("AUDIT_READ_ERROR",),
        )


@dataclass(frozen=True)
class _Fingerprint:
    encoding_candidates: tuple[str, ...]
    accepted_encoding: str | None
    has_bom: bool
    newline_style: str
    physical_line_count: int
    csv_record_count: int | None
    column_count_distribution: tuple[tuple[int, int], ...]
    rows: tuple[tuple[str, ...], ...]


def _fingerprint(raw: bytes) -> _Fingerprint:
    decoded = _decoded_variants(raw)
    accepted = next(iter(decoded), None)
    text = decoded.get(accepted, "") if accepted else ""
    rows: tuple[tuple[str, ...], ...] = ()
    csv_record_count = None
    distribution: tuple[tuple[int, int], ...] = ()
    if text:
        try:
            parsed = tuple(tuple(row) for row in csv.reader(io.StringIO(text), strict=True))
            rows = parsed
            csv_record_count = len(parsed)
            distribution = tuple(sorted(Counter(len(row) for row in parsed).items()))
        except csv.Error:
            pass
    return _Fingerprint(
        encoding_candidates=tuple(decoded),
        accepted_encoding=accepted,
        has_bom=raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")),
        newline_style=_newline_style(raw),
        physical_line_count=len(raw.splitlines()),
        csv_record_count=csv_record_count,
        column_count_distribution=distribution,
        rows=rows,
    )


def _decoded_variants(raw: bytes) -> dict[str, str]:
    variants: dict[str, str] = {}
    candidates = (("utf-8-sig", raw), ("utf-8", raw), ("cp932", raw))
    for encoding, value in candidates:
        try:
            text = value.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            continue
        variants[encoding] = text
    return variants


def _first_csv_row(text: str) -> tuple[str, ...] | None:
    try:
        return tuple(next(csv.reader(io.StringIO(text), strict=True)))
    except (csv.Error, StopIteration):
        return None


def _newline_style(raw: bytes) -> str:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    cr = raw.count(b"\r") - crlf
    kinds = sum(bool(value) for value in (crlf, lf, cr))
    if kinds > 1:
        return "MIXED"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    if cr:
        return "CR"
    return "NONE"


def _reason_code(error: Exception) -> str:
    message = str(error).lower()
    rules = (
        ("bom", "BOM_UNSUPPORTED"),
        ("line ending", "NEWLINE_MISMATCH"),
        ("crlf", "NEWLINE_MISMATCH"),
        ("cp932", "ENCODING_MISMATCH"),
        ("column", "COLUMN_COUNT_MISMATCH"),
        ("header", "INCOMPATIBLE_HEADER"),
        ("multiline", "UNSUPPORTED_MULTILINE"),
        ("quoting", "QUOTING_MISMATCH"),
        ("non-consecutive", "NON_CONSECUTIVE_TRANSACTION_NUMBER"),
        ("transaction number", "INVALID_TRANSACTION_NUMBER"),
        ("inconsistent voucher", "VOUCHER_MISMATCH"),
        ("date", "INVALID_OR_MISMATCHED_DATE"),
        ("amount", "INVALID_AMOUNT"),
        ("not balanced", "UNBALANCED_JOURNAL"),
        ("description", "CONFLICTING_DESCRIPTION"),
        ("unexpected flag", "MALFORMED_GROUP_SEQUENCE"),
        ("not closed", "MALFORMED_GROUP_SEQUENCE"),
        ("identifier flag", "UNKNOWN_IDENTIFIER_FLAG"),
        ("account", "INCOMPLETE_SIDE"),
        ("metadata", "INCOMPLETE_SIDE"),
        ("no debit or credit", "EMPTY_JOURNAL_ROW"),
        ("parse failed", "MALFORMED_CSV"),
        ("malformed csv", "MALFORMED_CSV"),
        ("no data", "EMPTY_DATA"),
        ("no rows", "EMPTY_DATA"),
    )
    for fragment, code in rules:
        if fragment in message:
            return code
    return "UNSUPPORTED_STRUCTURE"


def _validation_reason_code(rule_id: str) -> str:
    return {
        "YAYOI-STRUCT-READ": "AUDIT_READ_ERROR",
        "YAYOI-STRUCT-BOM": "BOM_UNSUPPORTED",
        "YAYOI-STRUCT-LINE-END": "NEWLINE_MISMATCH",
        "YAYOI-STRUCT-CP932": "ENCODING_MISMATCH",
        "YAYOI-STRUCT-PARSE": "UNSUPPORTED_STRUCTURE",
    }.get(rule_id, "UNSUPPORTED_STRUCTURE")


def report_to_dict(report: AuditReport) -> dict[str, object]:
    return {
        "generated_at": report.generated_at,
        "files_scanned": report.files_scanned,
        "summary": {
            "pass": report.pass_count,
            "block": report.block_count,
            "unknown": report.unknown_count,
            "error": report.error_count,
        },
        "metrics": {
            "logical_journals_parsed": report.logical_journals_parsed,
            "file_pass_rate": report.file_pass_rate,
            "recognized_file_pass_rate": report.recognized_file_pass_rate,
        },
        "detected_formats": dict(report.detected_format_counts),
        "block_reasons": dict(report.block_reason_counts),
        "files": [
            {**asdict(result), "status": result.status.value}
            for result in report.files
        ],
        "privacy_note": (
            "No journal values, account names, descriptions, customer names, partners, or "
            "amounts are included."
        ),
    }


def report_to_text(report: AuditReport) -> str:
    recognized_rate = (
        f"{report.recognized_file_pass_rate:.1f}%"
        if report.recognized_file_pass_rate is not None
        else "N/A"
    )
    lines = [
        "Private CSV Audit",
        "",
        f"Files scanned: {report.files_scanned}",
        f"PASS: {report.pass_count}",
        f"BLOCK: {report.block_count}",
        f"UNKNOWN: {report.unknown_count}",
        f"ERROR: {report.error_count}",
        f"Logical journals parsed: {report.logical_journals_parsed}",
        f"File pass rate: {report.file_pass_rate:.1f}%",
        f"Recognized-file pass rate: {recognized_rate}",
        "",
        "Detected formats:",
    ]
    lines.extend(f"- {label}: {count}" for label, count in report.detected_format_counts)
    lines.append("")
    lines.append("Top block reasons:")
    lines.extend(
        (f"- {reason}: {count}" for reason, count in report.block_reason_counts),
    )
    if not report.block_reason_counts:
        lines.append("- none")
    lines.append("")
    for result in report.files:
        lines.extend(
            (
                f"[{result.file_id}]",
                f"format: {result.format_label}",
                f"status: {result.status.value}",
                f"records: {result.record_count if result.record_count is not None else 'N/A'}",
                "logical_journals: "
                f"{result.logical_journal_count if result.logical_journal_count is not None else 'N/A'}",
                "reasons: " + (", ".join(result.reason_codes) or "none"),
                "",
            )
        )
    lines.append("No accounting contents were included in this report.")
    return "\n".join(lines)


def write_json_report(path: Path, report: AuditReport) -> None:
    if path.exists():
        raise FileExistsError("JSON report path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Privacy-safe private CSV batch audit.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--include-relative-paths", action="store_true")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        parser.error("directory does not exist or is not a directory")
    report = PrivateCsvAuditor().audit_directory(
        args.directory,
        include_relative_paths=args.include_relative_paths,
    )
    print(report_to_text(report))
    if args.json_report:
        write_json_report(args.json_report, report)
    return 1 if report.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

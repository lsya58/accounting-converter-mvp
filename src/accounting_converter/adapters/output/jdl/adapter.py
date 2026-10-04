from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Sequence

from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import ValidationResult
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)

from .models import JdlTargetContext
from .preflight import JdlOutputBlockedError, JdlOutputPreflight


class JDLOutputAdapter(OutputAdapter):
    def __init__(self, context: JdlTargetContext) -> None:
        self._preflight = JdlOutputPreflight(context)

    def preflight(
        self,
        entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> list[ValidationResult]:
        return list(self._preflight.evaluate(entries, profile).validation_results)

    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        result = self._preflight.evaluate(entries, profile)
        if not result.supported or result.plan is None:
            raise JdlOutputBlockedError(result.validation_results)

        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        rows = tuple(row.columns() for row in result.plan.rows)
        self._validate_field_lengths(rows)
        text_buffer = io.StringIO(newline="")
        csv.writer(text_buffer, lineterminator="\r\n").writerows((header, *rows))
        text = text_buffer.getvalue()
        try:
            raw = text.encode("cp932", errors="strict")
        except UnicodeEncodeError as exc:
            raise JdlOutputBlockedError(
                (
                    JdlOutputPreflight._error(
                        "JDL-OUT-CP932",
                        "CP932へ損失なくencodeできない文字を検出しました。",
                        "encoding",
                    ),
                )
            ) from exc
        if raw.decode("cp932", errors="strict") != text:
            raise JdlOutputBlockedError(
                (
                    JdlOutputPreflight._error(
                        "JDL-OUT-CP932-ROUNDTRIP",
                        "CP932 round-tripで文字列が保持されません。",
                        "encoding",
                    ),
                )
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    @staticmethod
    def _validate_field_lengths(rows: tuple[tuple[str, ...], ...]) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()
        for row in rows:
            if len(row) != spec.column_count:
                raise JdlOutputBlockedError(
                    (
                        JdlOutputPreflight._error(
                            "JDL-OUT-COLUMN-COUNT",
                            "JDL出力行は30列である必要があります。",
                            "column_count",
                        ),
                    )
                )
            for definition, value in zip(spec.columns, row, strict=True):
                if definition.max_length is not None and len(value) > definition.max_length:
                    raise JdlOutputBlockedError(
                        (
                            JdlOutputPreflight._error(
                                "JDL-OUT-FIELD-LENGTH",
                                "JDL項目の最大文字数を超えています。",
                                definition.name,
                            ),
                        )
                    )


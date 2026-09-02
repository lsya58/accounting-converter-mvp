from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.base import OutputAdapter
from accounting_converter.application.output_validation import OutputValidator
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.profile import FormatProfile


class InputAdapterContractMixin:
    input_adapter: InputAdapter
    input_profile: FormatProfile

    def make_valid_input_file(self, directory: Path) -> Path:
        raise NotImplementedError

    def make_invalid_input_file(self, directory: Path) -> Path:
        raise NotImplementedError

    def test_input_adapter_does_not_modify_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.make_valid_input_file(Path(tmpdir))
            before = path.read_bytes()

            self.input_adapter.read(path, self.input_profile)

            self.assertEqual(path.read_bytes(), before)

    def test_input_adapter_preserves_source_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.make_valid_input_file(Path(tmpdir))

            entries = self.input_adapter.read(path, self.input_profile)

            self.assertTrue(entries)
            self.assertTrue(all(entry.source_reference.file_name for entry in entries))
            self.assertTrue(
                all(
                    line.source_reference.row_number is not None
                    for entry in entries
                    for line in entry.lines
                )
            )

    def test_input_adapter_uses_decimal_amounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.make_valid_input_file(Path(tmpdir))

            entries = self.input_adapter.read(path, self.input_profile)

            self.assertTrue(
                all(
                    isinstance(line.amount, Decimal)
                    for entry in entries
                    for line in entry.lines
                )
            )

    def test_input_adapter_does_not_silently_accept_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.make_invalid_input_file(Path(tmpdir))

            with self.assertRaises(Exception):
                self.input_adapter.read(path, self.input_profile)

    def test_input_adapter_does_not_drop_duplicate_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self.make_valid_input_file(Path(tmpdir))
            expected_count = self.input_adapter.record_count(path, self.input_profile)

            entries = self.input_adapter.read(path, self.input_profile)

            self.assertEqual(len(entries), expected_count)


class OutputAdapterContractMixin:
    output_adapter: OutputAdapter
    output_validator: OutputValidator
    output_profile: FormatProfile

    def make_output_entries(self) -> tuple[JournalEntry, ...]:
        raise NotImplementedError

    def test_output_adapter_decimal_totals_roundtrip_through_validator(self) -> None:
        entries = self.make_output_entries()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "contract_output.csv"

            self.output_adapter.write(entries, output_path, self.output_profile)
            result = self.output_validator.validate(
                output_path,
                entries,
                self.output_profile,
            )

            self.assertTrue(result.success)
            self.assertEqual(
                result.debit_total,
                sum((entry.debit_total() for entry in entries), Decimal("0")),
            )
            self.assertEqual(
                result.credit_total,
                sum((entry.credit_total() for entry in entries), Decimal("0")),
            )

    def test_output_adapter_writes_all_journals(self) -> None:
        entries = self.make_output_entries()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "contract_output.csv"

            self.output_adapter.write(entries, output_path, self.output_profile)
            result = self.output_validator.validate(
                output_path,
                entries,
                self.output_profile,
            )

            self.assertEqual(result.journal_count, len(entries))

    def assert_no_unsupported_data_was_dropped(
        self,
        entries: tuple[JournalEntry, ...],
    ) -> None:
        self.assertTrue(
            any(entry.is_compound() for entry in entries)
            or any(
                line.side in {Side.DEBIT, Side.CREDIT}
                for entry in entries
                for line in entry.lines
            )
        )

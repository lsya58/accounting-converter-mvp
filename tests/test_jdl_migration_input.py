from __future__ import annotations

import csv
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.jdl import (
    JdlMigrationInputAdapter,
    JdlMigrationInputAdapterError,
    JdlMigrationParser,
    jdl_source_account_key,
    jdl_source_subaccount_key,
    jdl_source_tax_key,
)
from accounting_converter.adapters.output.jdl import (
    JDLOutputAdapter,
    JDLOutputValidator,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlTargetContext,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.jdl_migration import (
    JdlMigrationPreflight,
    JdlMigrationSyntheticRoutePolicy,
)
from accounting_converter.application.mapping_engine import MappingEngine, MappingRuleSet
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class JdlMigrationInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = JdlMigrationParser()
        self.input_schema = jdl_ibex_cashbook_migration_input_schema_definition()
        self.output_schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        self.input_profile = FormatProfile(
            "JDL", "JDL IBEX 出納帳", "35.5",
            self.input_schema.identity.stable_key, "cp932",
        )
        self.output_profile = FormatProfile(
            "JDL", "JDL IBEX 出納帳", "35.5",
            "jdl-ibex-cashbook-journal-csv-30-v0", "cp932",
        )

    def test_clean_30_column_input_preserves_identity_and_physical_row(self) -> None:
        result = self.parser.parse_text(self._text([self._row("1111")]))

        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.journal_record_count, 1)
        entry = result.entries[0]
        self.assertEqual(entry.metadata["identifier_flags"], ("1111",))
        self.assertEqual(len(entry.metadata["physical_rows"]), 1)
        self.assertEqual(len(entry.metadata["physical_rows"][0]["source_columns"]), 30)
        self.assertEqual(entry.lines[0].account, jdl_source_account_key("1111", "現金"))

    def test_diagnostic_rows_are_separated_as_source_metadata(self) -> None:
        diagnostic = ["// [借方科目]確認が必要"] + [""] * 29
        result = self.parser.parse_text(
            self._text([self._row("1111"), diagnostic])
        )

        self.assertEqual(len(result.entries), 1)
        self.assertEqual(len(result.diagnostic_rows), 1)
        self.assertEqual(result.journal_record_count, 1)

    def test_all_observed_flags_and_compound_grouping(self) -> None:
        rows = [
            self._row("1000", voucher="1"),
            self._row("1111", voucher="2"),
            self._row("1110", voucher="3", debit_amount="600", credit_amount="300"),
            self._row("1100", voucher="3", debit_amount="200", credit_amount="300"),
            self._row("1101", voucher="3", debit_amount="200", credit_amount="400"),
        ]
        result = self.parser.parse_text(self._text(rows))

        self.assertEqual(len(result.entries), 3)
        self.assertEqual(
            result.entries[2].metadata["identifier_flags"],
            ("1110", "1100", "1101"),
        )
        self.assertEqual(len(result.entries[2].metadata["physical_rows"]), 3)

    def test_unknown_post_header_structure_is_blocked(self) -> None:
        unknown = ["UNKNOWN"] + [""] * 29
        with self.assertRaisesRegex(ValueError, "neither a journal record"):
            self.parser.parse_text(self._text([self._row("1111"), unknown]))

    def test_path_requires_cp932_crlf_and_no_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.csv"
            valid.write_bytes(self._text([self._row("1111")]).encode("cp932"))
            adapter = JdlMigrationInputAdapter()
            self.assertEqual(len(adapter.read(valid, self.input_profile)), 1)

            lf = root / "lf.csv"
            lf.write_bytes(valid.read_bytes().replace(b"\r\n", b"\n"))
            with self.assertRaisesRegex(JdlMigrationInputAdapterError, "CRLF"):
                adapter.read(lf, self.input_profile)

            bom = root / "bom.csv"
            bom.write_bytes(b"\xef\xbb\xbf" + valid.read_bytes())
            with self.assertRaisesRegex(JdlMigrationInputAdapterError, "BOM"):
                adapter.read(bom, self.input_profile)

    def test_preflight_reuses_exact_account_but_blocks_changed_identity(self) -> None:
        entry = self.parser.parse_text(self._text([self._row("1111")])).entries[0]
        result = JdlMigrationPreflight().evaluate(
            (entry,), self._profile({}), self._context()
        )
        self.assertTrue(result.output_allowed)

        changed = self._row("1111")
        changed[5] = "変更された現金"
        changed_entry = self.parser.parse_text(self._text([changed])).entries[0]
        blocked = JdlMigrationPreflight().evaluate(
            (changed_entry,), self._profile({}), self._context()
        )
        self.assertFalse(blocked.output_allowed)
        self.assertIn("JDL-MIGRATION-ACCOUNT-UNRESOLVED", self._codes(blocked))

    def test_subaccount_requires_explicit_policy_and_parent_only_can_pass(self) -> None:
        row = self._row("1111")
        row[6:8] = ["0001", "架空補助"]
        entry = self.parser.parse_text(self._text([row])).entries[0]
        accounts = self._account_mappings(entry)
        blocked = JdlMigrationPreflight().evaluate(
            (entry,), self._profile(accounts), self._context()
        )
        self.assertIn("JDL-MIGRATION-SUBACCOUNT-UNRESOLVED", self._codes(blocked))

        sub_key = MappingKey(
            MappingType.SUBACCOUNT,
            jdl_source_subaccount_key("0001", "架空補助"),
            jdl_source_account_key("1111", "現金"),
        )
        mapping = MappingValue(
            sub_key.source_value,
            "",
            MappingStatus.USER_CONFIRMED,
            parent_account=sub_key.parent_account,
            metadata={"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
        )
        passed = JdlMigrationPreflight().evaluate(
            (entry,),
            self._profile(accounts, {sub_key: mapping}),
            self._context(),
        )
        self.assertTrue(passed.output_allowed)

    def test_unknown_tax_description_cp932_and_stale_context_block(self) -> None:
        tax_row = self._row("1111")
        tax_row[8:11] = ["仕　入", "10%", ""]
        tax_entry = self.parser.parse_text(self._text([tax_row])).entries[0]
        profile = self._profile(self._account_mappings(tax_entry))
        tax_result = JdlMigrationPreflight().evaluate(
            (tax_entry,), profile, self._context()
        )
        self.assertIn("JDL-MIGRATION-TAX-UNVERIFIED", self._codes(tax_result))

        long_row = self._row("1111", description="A" * 33)
        long_entry = self.parser.parse_text(self._text([long_row])).entries[0]
        long_result = JdlMigrationPreflight().evaluate(
            (long_entry,), self._profile(self._account_mappings(long_entry)), self._context()
        )
        self.assertIn("JDL-MIGRATION-DESCRIPTION-LENGTH", self._codes(long_result))

        bad_encoding = self._row("1111", description="𠀋")
        bad_entry = self.parser.parse_text(self._text([bad_encoding])).entries[0]
        bad_result = JdlMigrationPreflight().evaluate(
            (bad_entry,), self._profile(self._account_mappings(bad_entry)), self._context()
        )
        self.assertIn("JDL-MIGRATION-CP932", self._codes(bad_result))

    def test_synthetic_jdl_to_jdl_route_is_atomic_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_bytes(self._text([self._row("1111")]).encode("cp932"))
            parsed = JdlMigrationInputAdapter().read(source, self.input_profile)
            profile = self._profile(self._account_mappings(parsed[0]))
            service = ConversionService(
                input_adapter=JdlMigrationInputAdapter(),
                structural_validator=__import__(
                    "accounting_converter.adapters.input.jdl",
                    fromlist=["JdlMigrationStructuralValidator"],
                ).JdlMigrationStructuralValidator(),
                mapping_engine=MappingEngine(MappingRuleSet({}, {}, {}, {})),
                business_validator=ValidationPipeline((BalanceRule(),)),
                output_adapter=JDLOutputAdapter(self._context()),
                output_validator=JDLOutputValidator(self._context()),
                journal_route_policy=JdlMigrationSyntheticRoutePolicy(),
            )
            result = service.convert(
                ConversionRequest(
                    source,
                    output,
                    self.input_profile,
                    self.output_profile,
                    conversion_profile=profile,
                )
            )

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.output_record_count, 1)
            self.assertTrue(output.exists())
            self.assertNotIn(b"\n", output.read_bytes().replace(b"\r\n", b""))

    def test_atomic_failure_writes_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_bytes(self._text([self._row("1111")]).encode("cp932"))
            service = ConversionService(
                JdlMigrationInputAdapter(),
                __import__("accounting_converter.adapters.input.jdl", fromlist=["JdlMigrationStructuralValidator"]).JdlMigrationStructuralValidator(),
                MappingEngine(MappingRuleSet({}, {}, {}, {})),
                ValidationPipeline((BalanceRule(),)),
                JDLOutputAdapter(self._context()),
                JDLOutputValidator(self._context()),
                journal_route_policy=JdlMigrationSyntheticRoutePolicy(),
            )
            result = service.convert(
                ConversionRequest(source, output, self.input_profile, self.output_profile, conversion_profile=self._profile({}))
            )
            self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
            self.assertFalse(output.exists())

    def _profile(self, accounts, subs=None) -> ConversionProfile:
        return ConversionProfile(
            "jdl-migration-test",
            "JDL migration synthetic test",
            self.input_schema.identity,
            self.output_schema.identity,
            account_mappings=accounts,
            subaccount_context_mappings=subs or {},
        )

    def _account_mappings(self, entry):
        result = {}
        for line in entry.lines:
            target = "現金" if line.side.value == "DEBIT" else "売上"
            result[line.account] = MappingValue(
                line.account,
                target,
                MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "1111" if target == "現金" else "6121"},
            )
        return result

    def _context(self):
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上"}),
            tax_processing_mode=JdlTaxProcessingMode.EXEMPT,
            target_format_identity=self.output_schema.identity,
            account_master=(
                JdlAccountIdentity("現金", "1111", "現金", "現金"),
                JdlAccountIdentity("売上", "6121", "売上", "売上"),
            ),
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        )

    def _row(
        self,
        flag: str,
        *,
        voucher: str = "1",
        debit_amount: str = "1000",
        credit_amount: str = "1000",
        description: str = "架空摘要",
    ) -> list[str]:
        row = [""] * 30
        row[0:6] = [flag, voucher, "20261019", "1111", "現金", "現金"]
        row[11:16] = [debit_amount, "0", "6121", "売上", "売上"]
        row[21:24] = [credit_amount, "0", description]
        return row

    def _text(self, rows: list[list[str]]) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(jdl_ibex_cashbook_official_journal_import_spec().column_names)
        writer.writerows(rows)
        return stream.getvalue()

    @staticmethod
    def _codes(result):
        return {item.rule_id for item in result.validation_results}


if __name__ == "__main__":
    unittest.main()

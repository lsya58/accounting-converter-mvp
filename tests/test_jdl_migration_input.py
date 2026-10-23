from __future__ import annotations

import csv
import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
    JdlSimplifiedBusinessCategory,
    JdlSubaccountIdentity,
    JdlTargetContext,
    JdlTaxationMethod,
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
from accounting_converter.application.jdl_migration_workflow import (
    JdlMigrationFormalWorkflow,
)
from accounting_converter.application.company_settings import CompanySettingStatus
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

        source_sha = "a" * 64
        original_sha = hashlib.sha256(("A" * 33).encode("utf-8")).hexdigest()
        replacement = MappingValue(
            "jdl_description_replacement|jdl:2|row-1",
            "Human confirmed replacement",
            MappingStatus.USER_CONFIRMED,
            metadata={
                "policy": "HUMAN_CONFIRMED_DESCRIPTION_REPLACEMENT",
                "source_sha256": source_sha,
                "original_description_sha256": original_sha,
            },
        )
        replacement_profile = replace(
            self._profile(self._account_mappings(long_entry)),
            loss_policy_mappings={replacement.source_value: replacement},
        )
        replaced = JdlMigrationPreflight().evaluate(
            (long_entry,), replacement_profile, self._context(),
            source_sha256=source_sha,
        )
        self.assertNotIn("JDL-MIGRATION-DESCRIPTION-LENGTH", self._codes(replaced))
        stale = JdlMigrationPreflight().evaluate(
            (long_entry,), replacement_profile, self._context(),
            source_sha256="b" * 64,
        )
        self.assertIn("JDL-MIGRATION-DESCRIPTION-LENGTH", self._codes(stale))

        bad_encoding = self._row("1111", description="𠀋")
        bad_entry = self.parser.parse_text(self._text([bad_encoding])).entries[0]
        bad_result = JdlMigrationPreflight().evaluate(
            (bad_entry,), self._profile(self._account_mappings(bad_entry)), self._context()
        )
        self.assertIn("JDL-MIGRATION-CP932", self._codes(bad_result))

    def test_tax_evidence_scope_reports_stable_predicate_codes(self) -> None:
        row = self._row("1111")
        row[3:6] = ["111", "現金", "現金"]
        row[13:16] = ["612", "売上高", "売上高"]
        row[18:20] = ["非売上", ""]
        row[26:30] = ["001", "合成部門", "001", "合成部門"]
        entry = self.parser.parse_text(self._text([row])).entries[0]
        tax_key = next(line.tax_info.category for line in entry.lines if line.tax_info)
        profile = replace(
            self._profile(self._account_mappings(entry)),
            tax_mappings={
                tax_key: MappingValue(
                    tax_key, tax_key, MappingStatus.USER_CONFIRMED
                )
            },
        )
        context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "売上高"}),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            account_master=(
                JdlAccountIdentity("現金", "111", "現金", "現金"),
                JdlAccountIdentity("売上高", "612", "売上高", "売上高"),
            ),
        )
        result = JdlMigrationPreflight().evaluate(
            (entry,), profile, context, verified_tax_keys=frozenset({tax_key})
        )

        self.assertIn(
            "JDL-MIGRATION-TAX-EVIDENCE-OPTIONAL_FIELD_MISMATCH",
            self._codes(result),
        )

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

    def test_formal_workflow_preserves_rows_and_excludes_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            diagnostic = ["// privacy-safe diagnostic"] + [""] * 29
            source.write_bytes(
                self._text([self._row("1111"), diagnostic]).encode("cp932")
            )
            workflow = JdlMigrationFormalWorkflow()
            prepared = workflow.prepare(
                input_path=source,
                output_path=output,
                profile=self._profile({}),
                context=self._context(),
                company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )

            self.assertEqual(prepared.summary.readiness.value, "READY")
            result = workflow.execute(prepared)

            self.assertIsNotNone(result)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.input_journal_count, 1)
            self.assertEqual(result.output_record_count, 1)
            raw = output.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            reparsed = self.parser.parse_path(output)
            self.assertEqual(len(reparsed.entries), 1)
            self.assertEqual(len(reparsed.diagnostic_rows), 0)

    def test_formal_workflow_applies_confirmed_account_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            row = self._row("1111", description="A" * 33)
            row[3:6] = ["9999", "旧現金", "旧現金"]
            source.write_bytes(self._text([row]).encode("cp932"))
            entry = self.parser.parse_path(source).entries[0]
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            account = MappingValue(
                entry.lines[0].account,
                "現金",
                MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "1111", "target_formal_name": "現金"},
            )
            replacement_key = "jdl_description_replacement|jdl:2|row-1"
            replacement = MappingValue(
                replacement_key,
                "確認済み摘要",
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "policy": "HUMAN_CONFIRMED_DESCRIPTION_REPLACEMENT",
                    "source_sha256": source_sha,
                    "original_description_sha256": hashlib.sha256(("A" * 33).encode()).hexdigest(),
                },
            )
            profile = replace(
                self._profile({entry.lines[0].account: account}),
                loss_policy_mappings={replacement_key: replacement},
            )
            workflow = JdlMigrationFormalWorkflow()
            prepared = workflow.prepare(
                input_path=source, output_path=output, profile=profile,
                context=self._context(), company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            result = workflow.execute(prepared)

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            parsed = list(csv.reader(io.StringIO(output.read_bytes().decode("cp932"))))
            self.assertEqual(parsed[1][3:6], ["1111", "現金", "現金"])
            self.assertEqual(parsed[1][23], "確認済み摘要")

    def test_formal_workflow_blocks_unresolved_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            row = self._row("1111")
            row[3:6] = ["9999", "未確認", "未確認"]
            source.write_bytes(self._text([row]).encode("cp932"))
            workflow = JdlMigrationFormalWorkflow()
            blocked = workflow.prepare(
                input_path=source, output_path=output, profile=self._profile({}),
                context=self._context(), company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            self.assertEqual(blocked.summary.readiness.value, "BLOCKED")
            self.assertFalse(output.exists())

            output.write_text("existing", encoding="ascii")
            overwrite = workflow.prepare(
                input_path=source, output_path=output, profile=self._profile({}),
                context=self._context(), company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            self.assertEqual(overwrite.summary.readiness.value, "BLOCKED")
            self.assertEqual(output.read_text(encoding="ascii"), "existing")

    def test_formal_workflow_applies_preserve_and_parent_only_subaccount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            row = self._row("1111")
            row[6:8] = ["0001", "旧補助"]
            source.write_bytes(self._text([row]).encode("cp932"))
            entry = self.parser.parse_path(source).entries[0]
            key = MappingKey(MappingType.SUBACCOUNT, entry.lines[0].sub_account, entry.lines[0].account)
            preserved = MappingValue(
                key.source_value, "新補助", MappingStatus.USER_CONFIRMED,
                parent_account=key.parent_account,
                metadata={
                    "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                    "output_code": "0099", "output_name": "新補助",
                },
            )
            context = replace(
                self._context(),
                subaccounts=(JdlSubaccountIdentity("現金", "新補助", "0099", "0099", "新補助", True, "1111", "新補助"),),
            )
            workflow = JdlMigrationFormalWorkflow()
            output = root / "preserve.csv"
            prepared = workflow.prepare(
                input_path=source, output_path=output,
                profile=self._profile({}, {key: preserved}), context=context,
                company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            self.assertEqual(workflow.execute(prepared).status, ConversionStatus.SUCCESS)
            rows = list(csv.reader(io.StringIO(output.read_bytes().decode("cp932"))))
            self.assertEqual(rows[1][6:8], ["0099", "新補助"])

            parent_only = replace(
                preserved, target_value="",
                metadata={"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
            )
            parent_output = root / "parent.csv"
            parent_prepared = workflow.prepare(
                input_path=source, output_path=parent_output,
                profile=self._profile({}, {key: parent_only}), context=self._context(),
                company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            self.assertEqual(workflow.execute(parent_prepared).status, ConversionStatus.SUCCESS)
            parent_rows = list(csv.reader(io.StringIO(parent_output.read_bytes().decode("cp932"))))
            self.assertEqual(parent_rows[1][6:8], ["", ""])

    def test_formal_workflow_applies_only_evidenced_flag_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_bytes(self._text([self._row("1000")]).encode("cp932"))
            evidence = type("Evidence", (), {
                "canonical_flag_sequence": ("1111",),
                "evidence_id": "EVID-EXACT-SCOPE",
            })()
            workflow = JdlMigrationFormalWorkflow()
            with patch(
                "accounting_converter.application.jdl_migration_workflow.canonical_flag_normalization_evidence",
                return_value=evidence,
            ):
                prepared = workflow.prepare(
                    input_path=source, output_path=output, profile=self._profile({}),
                    context=self._context(), company_status=CompanySettingStatus.AVAILABLE,
                    verified_tax_keys=frozenset(),
                )
            result = workflow.execute(prepared)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertIn("EVID-EXACT-SCOPE", result.verification_report)
            rows = list(csv.reader(io.StringIO(output.read_bytes().decode("cp932"))))
            self.assertEqual(rows[1][0], "1111")

    def test_formal_workflow_rolls_back_when_atomic_publish_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            output = root / "output.csv"
            source.write_bytes(self._text([self._row("1111")]).encode("cp932"))
            workflow = JdlMigrationFormalWorkflow()
            prepared = workflow.prepare(
                input_path=source, output_path=output, profile=self._profile({}),
                context=self._context(), company_status=CompanySettingStatus.AVAILABLE,
                verified_tax_keys=frozenset(),
            )
            with patch(
                "accounting_converter.application.jdl_migration_workflow.os.link",
                side_effect=OSError("synthetic publish failure"),
            ):
                result = workflow.execute(prepared)

            self.assertEqual(result.status, ConversionStatus.SYSTEM_ERROR)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])

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

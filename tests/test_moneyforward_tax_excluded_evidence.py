from __future__ import annotations

import unittest
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
import tempfile
from unittest.mock import patch

from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlInputTaxCreditMethod,
    JdlSubaccountIdentity,
    JdlTargetContext,
    JdlTaxationMethod,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.adapter import JDLOutputAdapter
from accounting_converter.adapters.output.jdl.validator import JDLOutputValidator
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    BATCH_EVIDENCE_ID,
    EVIDENCE,
    EVIDENCE_REGISTRY,
    MfTaxEvidenceRegistry,
    MfTaxExcludedPatternEvidence,
    apply_verified_tax_semantics,
    confirmed_mapping_is_in_scope,
    confirmed_mapping_mismatch_fields,
    context_is_verified,
    evidence_for_occurrence,
    match_evidence_for_occurrence,
    tax_context_identity_sha256,
)
from accounting_converter.application.moneyforward_conversion_workflow import (
    MoneyForwardConversionWorkflow,
    _VerifiedTaxSemanticsTransform,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.profile_preflight import (
    mapping_rule_set_from_profile,
)
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupService,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class MoneyForwardTaxExcludedEvidenceTests(unittest.TestCase):
    def test_1d2c_real_evidence_is_exact_and_not_generalized(self) -> None:
        signature = (
            ("DEBIT", "7121", "", "課税仕入 10%"),
            ("CREDIT", "3141", "", "対象外"),
            ("CREDIT", "3271", "0002", "対象外"),
        )
        evidence = EVIDENCE_REGISTRY.exact(signature, trade_partner=False)
        self.assertIsNotNone(evidence)
        self.assertEqual(
            evidence.evidence_id, "EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001"
        )
        self.assertIs(
            evidence.profile,
            JdlEvidenceProfile.MF_COMPOUND_1D2C_TAX_EXCLUDED_PROPORTIONAL,
        )
        self.assertIsNone(EVIDENCE_REGISTRY.exact(signature, trade_partner=True))
        changed_sub = (*signature[:2], ("CREDIT", "3271", "0001", "対象外"))
        self.assertIsNone(EVIDENCE_REGISTRY.exact(changed_sub, trade_partner=False))

    def test_exact_pattern_activates_and_adds_tax_excluded_fields(self) -> None:
        context = self._context()
        source, mapped = self._p05()
        evidence = evidence_for_occurrence(source, mapped, context)
        transformed = apply_verified_tax_semantics(source, mapped, context)

        self.assertIsNotNone(evidence)
        info = transformed.lines[0].tax_info
        self.assertIsNotNone(info)
        self.assertEqual(info.category, "10%")
        self.assertEqual(info.tax_amount, Decimal("100"))
        self.assertEqual(info.metadata["jdl_tax_input_method"], "内税")
        self.assertEqual(transformed.lines[1].tax_info, None)

    def test_context_or_account_mismatch_remains_unverified(self) -> None:
        source, mapped = self._p05()
        individual = self._context(JdlInputTaxCreditMethod.INDIVIDUAL)
        self.assertFalse(context_is_verified(individual))
        self.assertIsNone(evidence_for_occurrence(source, mapped, individual))

        mapped.lines[0].account = "通信費"
        self.assertIsNone(evidence_for_occurrence(source, mapped, self._context()))

    def test_exact_formal_name_alias_resolves_to_same_account_code(self) -> None:
        source, mapped = self._p05()
        context = self._context()
        formal_accounts = tuple(
            JdlAccountIdentity(
                item.mapping_value,
                item.target_master_code,
                item.target_name,
                f"正式-{item.target_formal_name}",
            )
            for item in context.account_master
        )
        context = JdlTargetContext(
            **{
                **context.__dict__,
                "account_master": formal_accounts,
            }
        )
        mapped.lines[0].account = "正式-旅費交通費"
        mapped.lines[1].account = "正式-未払金"

        evidence = evidence_for_occurrence(source, mapped, context)

        self.assertIsNotNone(evidence)

    def test_ambiguous_account_alias_remains_blocked(self) -> None:
        source, mapped = self._p05()
        context = self._context()
        duplicate = JdlAccountIdentity(
            "別科目", "9999", "別科目", "旅費交通費"
        )
        context = JdlTargetContext(
            **{
                **context.__dict__,
                "account_master": (*context.account_master, duplicate),
            }
        )

        self.assertIsNone(evidence_for_occurrence(source, mapped, context))

    def test_production_matcher_uses_confirmed_profile_target_codes(self) -> None:
        source, mapped = self._p05()
        context = self._context()
        mapped.lines[0].account = "旅費交通費"
        mapped.lines[1].account = "未払金"
        profile = SimpleNamespace(
            account_mappings={
                "旅費交通費": MappingValue(
                    "旅費交通費", "旅費交通費", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "8471"},
                ),
                "未払金": MappingValue(
                    "未払金", "未払金", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "3181"},
                ),
            },
            subaccount_context_mappings={},
        )

        evidence = evidence_for_occurrence(source, mapped, context, profile)

        self.assertIsNotNone(evidence)
        self.assertEqual(
            evidence.evidence_id,
            "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-001",
        )

    def test_canonical_code_does_not_round_trip_through_display_value(self) -> None:
        source, mapped = self._p05()
        context = self._context()
        mapped.lines[1].account = "Windows保存時の表示値"
        profile = SimpleNamespace(
            account_mappings={
                "旅費交通費": MappingValue(
                    "旅費交通費", "画面表示用の別名", MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": "8471",
                        "target_printed_name": "旅費交通費",
                    },
                ),
                "未払金": MappingValue(
                    "未払金", "Windows保存時の表示値", MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": "3181",
                        "target_formal_name": "未払金",
                    },
                ),
            },
            subaccount_context_mappings={},
        )

        result = match_evidence_for_occurrence(source, mapped, context, profile)

        self.assertIsNotNone(result.evidence)
        self.assertEqual(result.mismatch_fields, ())

    def test_parent_only_is_resolved_from_saved_policy_as_canonical_blank(self) -> None:
        source, mapped = self._p05()
        source.lines[1].sub_account = "入力元カード"
        mapped.lines[1].sub_account = ""
        context = self._context()
        profile = SimpleNamespace(
            account_mappings={
                "旅費交通費": MappingValue(
                    "旅費交通費", "旅費交通費", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "8471", "target_printed_name": "旅費交通費"},
                ),
                "未払金": MappingValue(
                    "未払金", "未払金", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "3181", "target_printed_name": "未払金"},
                ),
            },
            subaccount_context_mappings={
                MappingKey(MappingType.SUBACCOUNT, "入力元カード", "未払金"):
                    MappingValue(
                        "入力元カード", "", MappingStatus.USER_CONFIRMED,
                        parent_account="未払金",
                        metadata={
                            "subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                        },
                    )
            },
        )

        result = match_evidence_for_occurrence(source, mapped, context, profile)

        self.assertIsNotNone(result.evidence)
        self.assertEqual(result.actual_signature[1][2], "")
        self.assertEqual(result.mismatch_fields, ())

    def test_parent_only_saved_representations_share_one_canonical_value(self) -> None:
        for raw_value in ("", "0", "0000", "__PARENT_ONLY_CONFIRMED__"):
            with self.subTest(raw_value=raw_value):
                source, mapped = self._p05()
                source.lines[1].sub_account = "入力元カード"
                profile = SimpleNamespace(
                    account_mappings={
                        "旅費交通費": MappingValue(
                            "旅費交通費", "旅費交通費", MappingStatus.USER_CONFIRMED,
                            metadata={"target_code": "8471", "target_printed_name": "旅費交通費"},
                        ),
                        "未払金": MappingValue(
                            "未払金", "未払金", MappingStatus.USER_CONFIRMED,
                            metadata={"target_code": "3181", "target_printed_name": "未払金"},
                        ),
                    },
                    subaccount_context_mappings={
                        MappingKey(MappingType.SUBACCOUNT, "入力元カード", "未払金"):
                            MappingValue(
                                "入力元カード", raw_value, MappingStatus.USER_CONFIRMED,
                                parent_account="未払金",
                                metadata={
                                    "subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                                },
                            )
                    },
                    subaccount_mappings={},
                    department_mappings={},
                    tax_mappings={},
                )

                mapped_entry = MappingEngine(
                    mapping_rule_set_from_profile(profile)
                ).apply((source,)).entries[0]
                result = match_evidence_for_occurrence(
                    source, mapped_entry, self._context(), profile
                )

                self.assertEqual(mapped_entry.lines[1].sub_account, "")
                self.assertIsNotNone(result.evidence)
                self.assertEqual(result.actual_signature[1][2], "")
                self.assertEqual(result.mismatch_fields, ())

    def test_parent_only_nonblank_runtime_value_has_field_level_diagnostic(self) -> None:
        source, mapped = self._p05()
        source.lines[1].sub_account = "入力元カード"
        mapped.lines[1].sub_account = "0"
        context = self._context()
        profile = SimpleNamespace(
            account_mappings={
                "旅費交通費": MappingValue(
                    "旅費交通費", "旅費交通費", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "8471"},
                ),
                "未払金": MappingValue(
                    "未払金", "未払金", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "3181"},
                ),
            },
            subaccount_context_mappings={
                MappingKey(MappingType.SUBACCOUNT, "入力元カード", "未払金"):
                    MappingValue(
                        "入力元カード", "", MappingStatus.USER_CONFIRMED,
                        parent_account="未払金",
                        metadata={
                            "subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                        },
                    )
            },
        )

        result = match_evidence_for_occurrence(source, mapped, context, profile)

        self.assertIsNone(result.evidence)
        self.assertIn(
            "PARENT_ONLY_REPRESENTATION_MISMATCH", result.mismatch_fields
        )

    def test_current_preserve_mapping_selects_only_exact_subaccount_evidence(self) -> None:
        source, _mapped = self._p05()
        source.lines[1].sub_account = "入力元カード"
        context = self._context_with_3181_subaccount()
        mapping = MappingValue(
            "入力元カード",
            "三井住友カードご本人",
            MappingStatus.USER_CONFIRMED,
            parent_account="未払金",
            metadata={
                "target_code": "0001",
                "output_code": "0001",
                "output_name": "三井住友カードご本人",
                "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
            },
        )
        profile = SimpleNamespace(
            account_mappings={
                "旅費交通費": MappingValue(
                    "旅費交通費", "旅費交通費", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "8471", "target_printed_name": "旅費交通費"},
                ),
                "未払金": MappingValue(
                    "未払金", "未払金", MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": "3181", "target_printed_name": "未払金"},
                ),
            },
            subaccount_context_mappings={
                MappingKey(MappingType.SUBACCOUNT, "入力元カード", "未払金"): mapping
            },
            subaccount_mappings={},
            department_mappings={},
            tax_mappings={},
        )
        mapped = MappingEngine(mapping_rule_set_from_profile(profile)).apply(
            (source,)
        ).entries[0]

        result = match_evidence_for_occurrence(source, mapped, context, profile)

        self.assertEqual(result.actual_signature[1][2], "0001")
        self.assertIsNotNone(result.evidence)
        self.assertEqual(
            result.evidence.evidence_id,
            "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-SUB0001-001",
        )
        self.assertEqual(result.mismatch_fields, ())

    def test_registry_can_hold_blank_and_subaccount_variants_exactly(self) -> None:
        blank = next(item for item in EVIDENCE if "-P05-" in item.evidence_id)
        subaccount = MfTaxExcludedPatternEvidence(
            "PENDING-P05-3181-0001",
            (("DEBIT", "8471", "", "課税仕入 10%"),
             ("CREDIT", "3181", "0001", "対象外")),
            blank.profile,
        )
        registry = MfTaxEvidenceRegistry((blank, subaccount))

        self.assertEqual(
            registry.exact(subaccount.account_signature, trade_partner=False),
            subaccount,
        )
        self.assertEqual(
            registry.exact(blank.account_signature, trade_partner=False), blank
        )

    def test_verified_p05_p07_subaccount_variants_are_exact_and_blank_is_retained(self) -> None:
        for pattern, debit_code in (("P05", "8471"), ("P07", "8481")):
            with self.subTest(pattern=pattern):
                blank_signature = (
                    ("DEBIT", debit_code, "", "課税仕入 10%"),
                    ("CREDIT", "3181", "", "対象外"),
                )
                subaccount_signature = (
                    ("DEBIT", debit_code, "", "課税仕入 10%"),
                    ("CREDIT", "3181", "0001", "対象外"),
                )
                blank = EVIDENCE_REGISTRY.exact(
                    blank_signature, trade_partner=False
                )
                subaccount = EVIDENCE_REGISTRY.exact(
                    subaccount_signature, trade_partner=False
                )

                self.assertIsNotNone(blank)
                self.assertIsNotNone(subaccount)
                self.assertNotEqual(blank.evidence_id, subaccount.evidence_id)
                self.assertIn("SUB0001", subaccount.evidence_id)

    def test_batch_evidence_id_is_stable(self) -> None:
        self.assertEqual(
            BATCH_EVIDENCE_ID,
            "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001",
        )

    def test_all_p01_to_p07_exact_occurrence_signatures_match(self) -> None:
        for index, expected in enumerate(EVIDENCE, start=1):
            with self.subTest(pattern=index):
                codes = {item[1] for item in expected.account_signature}
                accounts = tuple(
                    JdlAccountIdentity(f"A{code}", code, f"A{code}", f"A{code}")
                    for code in sorted(codes)
                )
                sub_keys = {
                    (item[1], item[2])
                    for item in expected.account_signature if item[2]
                }
                subs = tuple(
                    JdlSubaccountIdentity(
                        f"A{parent}", f"S{parent}-{code}", code, code,
                        f"S{parent}-{code}", True, parent, f"S{parent}-{code}",
                    )
                    for parent, code in sorted(sub_keys)
                )
                base = self._context()
                context = JdlTargetContext(
                    **{
                        **base.__dict__,
                        "accounts": frozenset(item.mapping_value for item in accounts),
                        "account_master": accounts,
                        "subaccounts": subs,
                    }
                )
                ref = SourceReference("synthetic.csv", index + 1, str(index))
                source_lines = []
                mapped_lines = []
                for side, account, subaccount, tax in expected.account_signature:
                    metadata = (
                        {"moneyforward_trade_partner": "SYNTHETIC-PARTNER"}
                        if expected.trade_partner and not source_lines else {}
                    )
                    source_lines.append(JournalLine(
                        Side(side), f"SRC-{account}", Decimal("100"), ref,
                        tax_info=TaxInfo(tax), metadata=metadata,
                    ))
                    mapped_lines.append(JournalLine(
                        Side(side), f"A{account}", Decimal("100"), ref,
                        sub_account=(f"S{account}-{subaccount}" if subaccount else None),
                        tax_info=TaxInfo(tax), metadata=metadata,
                    ))
                source = JournalEntry(
                    f"j{index}", ref, date(2026, 4, 19 + index), source_lines,
                    "SYNTHETIC",
                )
                mapped = JournalEntry(
                    f"j{index}", ref, source.date, mapped_lines, "SYNTHETIC",
                )

                actual = evidence_for_occurrence(source, mapped, context)

                self.assertIsNotNone(actual)
                self.assertEqual(actual.evidence_id, expected.evidence_id)

    def test_production_preflight_path_matches_all_13_batch_occurrences(self) -> None:
        batch_evidence = tuple(
            next(
                item for item in EVIDENCE
                if f"-{pattern}-" in item.evidence_id
                and ((pattern not in {"P05", "P07"}) or "SUB0001" in item.evidence_id)
            )
            for pattern in ("P01", "P02", "P03", "P04", "P05", "P06", "P07")
        )
        codes = sorted({row[1] for item in batch_evidence for row in item.account_signature})
        account_names = {code: f"TARGET-{code}" for code in codes}
        accounts = tuple(
            JdlAccountIdentity(name, code, f"A{index:02d}", f"FORMAL{index:02d}")
            for index, (code, name) in enumerate(account_names.items(), start=1)
        )
        sub_keys = sorted({
            (row[1], row[2])
            for item in batch_evidence for row in item.account_signature if row[2]
        })
        subaccounts = tuple(
            JdlSubaccountIdentity(
                account_names[parent], f"TARGET-SUB-{parent}-{code}", code,
                code, f"S{index:02d}", True, parent,
                f"TARGET-SUB-{parent}-{code}",
            )
            for index, (parent, code) in enumerate(sub_keys, start=1)
        )
        base = self._context()
        context = JdlTargetContext(**{
            **base.__dict__,
            "accounts": frozenset(account_names.values()),
            "account_master": accounts,
            "subaccounts": subaccounts,
        })
        account_mappings = {
            f"SOURCE-{code}": MappingValue(
                f"SOURCE-{code}", name, MappingStatus.USER_CONFIRMED,
                metadata={"target_code": code, "target_printed_name": name},
            )
            for code, name in account_names.items()
        }
        sub_mappings = {}
        for index, (parent, code) in enumerate(sub_keys, start=1):
            sub_mappings[MappingKey(
                MappingType.SUBACCOUNT, f"SOURCE-SUB-{parent}-{code}",
                f"SOURCE-{parent}",
            )] = MappingValue(
                f"SOURCE-SUB-{parent}-{code}",
                f"TARGET-SUB-{parent}-{code}", MappingStatus.USER_CONFIRMED,
                parent_account=f"SOURCE-{parent}",
                metadata={
                    "target_code": code,
                    "output_code": code,
                    "output_name": f"S{index:02d}",
                    "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                },
            )
        tax_mappings = {
            category: MappingValue(
                category, target, MappingStatus.USER_CONFIRMED,
                metadata={
                    "jdl_evidence_id": BATCH_EVIDENCE_ID,
                    "jdl_tax_processing_mode": context.tax_processing_mode.value,
                    "jdl_tax_scope": scope,
                    "jdl_tax_context_identity_sha256": tax_context_identity_sha256(context),
                },
            )
            for category, target, scope in (
                ("課税仕入 10%", "10%", "仕　入"),
                ("対象外", "", ""),
            )
        }
        now = datetime.now(timezone.utc)
        profile = ConversionProfile(
            "production-path", "production-path",
            moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings=account_mappings,
            subaccount_context_mappings=sub_mappings,
            tax_mappings=tax_mappings,
            created_at=now, updated_at=now,
        )
        entries = []
        expected_ids = []
        occurrence = 0
        evidence_by_pattern = {
            pattern: evidence
            for pattern, evidence in zip(
                ("P01", "P02", "P03", "P04", "P05", "P06", "P07"),
                batch_evidence,
                strict=True,
            )
        }
        occurrence_patterns = (
            "P01", "P02", "P03", "P04", "P05", "P05", "P05",
            "P06", "P06", "P05", "P05", "P07", "P07",
        )
        for pattern in occurrence_patterns:
            evidence = evidence_by_pattern[pattern]
            occurrence += 1
            ref = SourceReference("privacy-safe.csv", occurrence + 1, str(occurrence))
            lines = []
            for index, (side, account, subaccount, tax) in enumerate(
                evidence.account_signature
            ):
                source_subaccount = (
                    f"SOURCE-SUB-{account}-{subaccount}"
                    if subaccount else None
                )
                metadata = (
                    {"moneyforward_trade_partner": "SYNTHETIC-PARTNER"}
                    if evidence.trade_partner and index == 0 else {}
                )
                line_metadata = dict(metadata)
                if pattern == "P01":
                    line_metadata.update({
                        "moneyforward_source_row_number": occurrence * 10 + index // 2,
                        "moneyforward_description": f"ROW-{index // 2 + 1}",
                    })
                lines.append(JournalLine(
                    Side(side), f"SOURCE-{account}", Decimal("100"), ref,
                    sub_account=source_subaccount, tax_info=TaxInfo(tax),
                    metadata=line_metadata,
                ))
            entry_metadata = {}
            if pattern == "P01":
                row_numbers = (occurrence * 10, occurrence * 10 + 1)
                entry_metadata = {
                    "physical_row_numbers": row_numbers,
                    "moneyforward_descriptions": tuple(
                        {"row_number": number, "value": f"ROW-{index + 1}"}
                        for index, number in enumerate(row_numbers)
                    ),
                }
            entries.append(JournalEntry(
                f"privacy-safe-{occurrence}", ref, date(2026, 4, 20),
                lines, "SYNTHETIC", metadata=entry_metadata,
            ))
            expected_ids.append(evidence.evidence_id)

        mapped = MappingEngine(mapping_rule_set_from_profile(profile)).apply(entries)
        transformed = tuple(
            apply_verified_tax_semantics(source, target, context, profile)
            for source, target in zip(entries, mapped.entries, strict=True)
        )
        assignments, reasons, shapes, tax_evidence, diagnostics = (
            MoneyForwardConversionWorkflow()._route_assignments(
                tuple(entries), transformed, profile, context,
                company_setting_validated=True,
            )
        )

        self.assertEqual(len(assignments), 13)
        self.assertEqual(reasons, [])
        self.assertEqual(shapes, set())
        self.assertEqual(tax_evidence, set())
        self.assertEqual(diagnostics, ())
        actual_ids = [
            match_evidence_for_occurrence(source, target, context, profile)
            .evidence.evidence_id
            for source, target in zip(entries, mapped.entries, strict=True)
        ]
        self.assertEqual(actual_ids, expected_ids)

        routed = ExplicitJdlEvidenceRoutePolicy(
            assignments,
            route_id="GUI-MF-EXACT-COMPANY-SETTING-V0",
        ).apply(transformed)
        self.assertEqual(routed.validation_results, ())
        output_results = JDLOutputAdapter(context).preflight(
            routed.entries,
            jdl_ibex_35_5_output_profile(),
        )
        self.assertEqual(
            output_results,
            [],
            [item.rule_id for item in output_results],
        )

        class StaticInputAdapter:
            def read(self, path, input_profile):
                return list(entries)

            def record_count(self, path, input_profile):
                return 14

        class NoStructuralErrors:
            def validate(self, path, input_profile):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "privacy-safe.csv"
            input_path.write_text("synthetic", encoding="ascii")
            output_path = root / "output.csv"
            service = ConversionService(
                input_adapter=StaticInputAdapter(),
                structural_validator=NoStructuralErrors(),
                mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
                business_validator=ValidationPipeline((BalanceRule(),)),
                output_adapter=JDLOutputAdapter(context),
                output_validator=JDLOutputValidator(context),
                journal_route_policy=ExplicitJdlEvidenceRoutePolicy(
                    assignments,
                    route_id="GUI-MF-EXACT-COMPANY-SETTING-V0",
                ),
                post_mapping_transform=_VerifiedTaxSemanticsTransform(
                    profile, context
                ),
            )
            result = service.convert(ConversionRequest(
                input_path=input_path,
                output_path=output_path,
                input_profile=FormatProfile(
                    "Money Forward", "Synthetic", "1", "synthetic", "cp932"
                ),
                output_profile=jdl_ibex_35_5_output_profile(),
                conversion_profile=profile,
                target_runtime_context=context,
            ))

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.input_journal_count, 13)
            self.assertEqual(result.output_journal_count, 13)
            self.assertEqual(result.output_record_count, 14)
            self.assertTrue(output_path.is_file())

    def test_tax_review_is_available_only_for_exact_verified_context(self) -> None:
        items = MoneyForwardProfileSetupService._tax_items(
            ("課税仕入 10%", "対象外"), self._context()
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.evidence_id == BATCH_EVIDENCE_ID for item in items))
        mismatch = MoneyForwardProfileSetupService._tax_items(
            ("課税仕入 10%",),
            self._context(JdlInputTaxCreditMethod.INDIVIDUAL),
        )
        self.assertEqual(len(mismatch), 1)
        self.assertFalse(mismatch[0].human_confirmable)
        self.assertEqual(
            mismatch[0].blocker_code,
            "MF-JDL-TAX-CONTEXT-CONFIRMATION-REQUIRED",
        )

    def test_mapping_scope_uses_tax_context_not_unrelated_master_hash(self) -> None:
        context = self._context()
        mapping = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": BATCH_EVIDENCE_ID,
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
                "jdl_tax_scope": "仕　入",
                "jdl_tax_context_identity_sha256": (
                    tax_context_identity_sha256(context)
                ),
                "jdl_context_sha256": "older-full-context-hash",
            },
        )

        self.assertTrue(
            confirmed_mapping_is_in_scope("課税仕入 10%", mapping, context)
        )
        self.assertFalse(confirmed_mapping_is_in_scope(
            "課税仕入 10%",
            MappingValue(
                "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
                metadata={**mapping.metadata, "jdl_evidence_id": "WRONG"},
            ),
            context,
        ))

    def test_evidence_failure_is_not_reported_as_shape_failure(self) -> None:
        context = self._context()
        source, mapped = self._p05()
        mapped.lines[1].account = "EVIDENCE-MISMATCH"
        mapping = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": "WRONG",
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
            },
        )
        profile = SimpleNamespace(
            tax_mappings={"課税仕入 10%": mapping, "対象外": mapping},
            account_mappings={},
            subaccount_context_mappings={},
        )

        with patch(
            "accounting_converter.application.moneyforward_conversion_workflow."
            "log_local_event"
        ) as log_event:
            _assignments, _reasons, shapes, tax_evidence, diagnostics = (
                MoneyForwardConversionWorkflow()._route_assignments(
                    (source,), (mapped,), profile, context
                )
            )

        self.assertEqual(shapes, set())
        self.assertEqual(tax_evidence, {"j1"})
        self.assertTrue(diagnostics)
        log_event.assert_called_once()
        self.assertEqual(
            log_event.call_args.args[0],
            "MF-JDL-TAX-EVIDENCE-CONDITION-MISMATCH",
        )
        payload = log_event.call_args.args[1]
        self.assertNotIn("amount", payload)
        self.assertIn("expected_signature", payload)
        self.assertIn("actual_signature", payload)
        self.assertIn("mismatch_fields", payload)

    def test_p05_p07_normal_block_diagnostics_are_aggregated(self) -> None:
        base = self._context()
        context = JdlTargetContext(**{
            **base.__dict__,
            "accounts": frozenset((*base.accounts, "通信費")),
            "account_master": (
                *base.account_master,
                JdlAccountIdentity("通信費", "8481", "通信費", "通信費"),
            ),
        })
        entries = []
        mapped_entries = []
        for index in range(7):
            source, mapped = self._p05()
            source.id = mapped.id = f"privacy-safe-{index}"
            if index >= 5:
                source.lines[0].account = "通信費"
                mapped.lines[0].account = "通信費"
            mapped.lines[1].account = "MISMATCH"
            entries.append(source)
            mapped_entries.append(mapped)
        mapping = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={"jdl_evidence_id": "WRONG"},
        )
        profile = SimpleNamespace(
            tax_mappings={"課税仕入 10%": mapping, "対象外": mapping},
            account_mappings={},
            subaccount_context_mappings={},
        )

        with patch(
            "accounting_converter.application.moneyforward_conversion_workflow."
            "log_local_event"
        ) as log_event:
            _a, _r, _s, blocked, diagnostics = (
                MoneyForwardConversionWorkflow()._route_assignments(
                    tuple(entries), tuple(mapped_entries), profile, context
                )
            )

        self.assertEqual(len(blocked), 7)
        self.assertEqual(log_event.call_count, 7)
        self.assertEqual(
            diagnostics,
            (
                "Pattern P05: ACCOUNT_CODE_MISMATCH x5",
                "Pattern P07: ACCOUNT_CODE_MISMATCH x2",
            ),
        )

    def test_old_mapping_is_reviewed_and_human_reconfirmation_updates_metadata(self) -> None:
        context = self._context()
        old = MappingValue(
            "課税仕入 10%", "10%", MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_evidence_id": "EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001",
                "jdl_tax_processing_mode": "TAXABLE_TAX_EXCLUDED",
                "jdl_tax_scope": "仕　入",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            store = ConversionProfileStore(Path(directory))
            now = datetime.now(timezone.utc)
            profile = ConversionProfile(
                "profile", "profile",
                moneyforward_cloud_journal_export_observed_schema().identity,
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
                tax_mappings={"課税仕入 10%": old},
                created_at=now, updated_at=now,
            )
            store.create(profile)
            service = MoneyForwardProfileSetupService(store)

            review = service.tax_mapping_review(profile, context)
            self.assertEqual(review.stale_source_values, ("課税仕入 10%",))
            self.assertIn("再確認", review.user_message)
            service.confirm_evidence_backed_tax_mapping(
                profile_id="profile", context=context,
                source_value="課税仕入 10%",
            )
            saved = store.get("profile").tax_mappings["課税仕入 10%"]

        self.assertEqual(saved.metadata["jdl_evidence_id"], BATCH_EVIDENCE_ID)
        self.assertIn("jdl_tax_context_identity_sha256", saved.metadata)
        self.assertEqual(
            confirmed_mapping_mismatch_fields("課税仕入 10%", saved, context),
            (),
        )

    @staticmethod
    def _context(
        method: JdlInputTaxCreditMethod = JdlInputTaxCreditMethod.PROPORTIONAL,
    ) -> JdlTargetContext:
        accounts = (
            JdlAccountIdentity("旅費交通費", "8471", "旅費交通費", "旅費交通費"),
            JdlAccountIdentity("未払金", "3181", "未払金", "未払金"),
        )
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(item.mapping_value for item in accounts),
            account_master=accounts,
            subaccounts=(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
            standard_taxation_confirmed=True,
            taxation_method=JdlTaxationMethod.STANDARD,
            input_tax_credit_method=method,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        )

    @staticmethod
    def _context_with_3181_subaccount() -> JdlTargetContext:
        base = MoneyForwardTaxExcludedEvidenceTests._context()
        return JdlTargetContext(
            **{
                **base.__dict__,
                "subaccounts": (
                    JdlSubaccountIdentity(
                        "未払金",
                        "三井住友カードご本人",
                        "0001",
                        "0001",
                        "三井住友カードご本人",
                        True,
                        "3181",
                        "三井住友カードご本人",
                    ),
                ),
            }
        )
    @staticmethod
    def _p05() -> tuple[JournalEntry, JournalEntry]:
        ref = SourceReference("synthetic.csv", 2, "1")
        source = JournalEntry(
            "j1", ref, date(2026, 4, 24),
            [
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1100"), ref, tax_info=TaxInfo("課税仕入 10%")),
                JournalLine(Side.CREDIT, "未払金", Decimal("1100"), ref, tax_info=TaxInfo("対象外")),
            ],
            "SYNTHETIC",
        )
        mapped = JournalEntry(
            "j1", ref, source.date,
            [
                JournalLine(Side.DEBIT, "旅費交通費", Decimal("1100"), ref, tax_info=TaxInfo("10%")),
                JournalLine(Side.CREDIT, "未払金", Decimal("1100"), ref, tax_info=TaxInfo("")),
            ],
            "SYNTHETIC",
        )
        return source, mapped

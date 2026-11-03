"""Yayoi 弥生インポート形式 → common journal → JDL workflow. Synthetic data only."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from unittest import mock
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.yayoi.import_format_parser import (
    YayoiImportFormatParseError,
    YayoiImportFormatParser,
    looks_like_yayoi_import_format,
)
from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow, audit_path_for
from accounting_converter.application.yayoi_review import (
    confirm_optional_field_policy,
    confirm_tax_identity,
    create_yayoi_profile,
    review_source,
)
from accounting_converter.application.yayoi_sources import IMPORT, REPORT, detect_format
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY
from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, journal_physical_rows
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from tests.test_mf_tax_capability_composition import ACCOUNTS, context
from tests.test_yayoi_journal_report_parser import build, detail, write

PURCHASE, SALES, OUTSIDE = "課対仕入内10%適格", "課税売上内10%", "対象外"
YAYOI = {"bank": "普通預金Y", "fee": "支払手数料Y", "cash": "現金Y", "sales": "売上Y", "supplies": "消耗品Y"}
TARGET = {"bank": "1311", "fee": "8681", "cash": "1111", "sales": "6121", "supplies": "8491"}


def row(flag, voucher, date, debit=None, credit=None, description="", *, kind="0", origin="", sticky="0",
        department="", closing=""):
    """debit/credit: (account, sub, tax, amount, tax_amount)."""
    columns = [flag, str(voucher), closing, date] + [""] * 21
    for offset, side in ((4, debit), (10, credit)):
        account, sub, tax, amount, tax_amount = side or ("", "", "", 0, 0)
        columns[offset:offset + 6] = [account, sub, department if side else "", tax, str(amount), str(tax_amount)]
    columns[16] = description
    columns[19], columns[20], columns[22], columns[23], columns[24] = kind, origin, sticky, "0", "no"
    return columns


def journals(*, purchase_amount=1100, purchase_tax=100, origin="", department=""):
    return [
        row("2000", 1, "R.08/05/10", (YAYOI["fee"], "", PURCHASE, purchase_amount, purchase_tax),
            (YAYOI["bank"], "口座A", OUTSIDE, purchase_amount, 0), "振込手数料", origin=origin, department=department),
        # Voucher number 1 reused on another day: must stay a separate journal.
        row("2000", 1, "R.08/05/11", (YAYOI["cash"], "", OUTSIDE, 2200, 0),
            (YAYOI["sales"], "", SALES, 2200, 200), "売上"),
        # 2D1C over two rows with different row descriptions.
        row("2110", 2, "R.08/05/12", (YAYOI["supplies"], "", PURCHASE, 550, 50),
            (YAYOI["bank"], "口座A", OUTSIDE, 1650, 0), "文具", kind="3"),
        row("2101", 2, "R.08/05/12", (YAYOI["fee"], "", PURCHASE, 1100, 100), None, "手数料", kind="3"),
    ]


def write_import(directory, rows) -> Path:
    path = Path(directory) / "import.txt"
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL).writerows(rows)
    path.write_bytes(buffer.getvalue().encode("cp932"))
    return path


class Company:
    """One CompanySetting with its own profile and Tax Context."""

    def __init__(self, root: Path, company_id: str, source: Path, fmt, target_context):
        self.root, self.company_id, self.source, self.context = root, company_id, source, target_context
        self.profiles = ConversionProfileStore(root / "profiles")
        self.companies = CompanySettingStore(root / "companies", self.profiles)
        context_path = root / f"{company_id}.json"
        context_path.write_text(JdlTargetContextLoader().to_json_text(target_context), encoding="utf-8")
        self.profile = create_yayoi_profile(self.profiles, company_id, fmt.read(source), fmt)
        self.companies.create(company_setting_id=company_id, display_name=company_id,
                              conversion_profile_id=self.profile.profile_id, context_source=context_path)

    def confirm_all(self):
        profile = self.profiles.get(self.profile.profile_id)
        accounts = {
            YAYOI[key]: MappingValue(YAYOI[key], ACCOUNTS[TARGET[key]], MappingStatus.USER_CONFIRMED, metadata={
                "target_code": TARGET[key], "target_printed_name": ACCOUNTS[TARGET[key]],
                "target_formal_name": ACCOUNTS[TARGET[key]]})
            for key in YAYOI
        }
        subs = {MappingKey(MappingType.SUBACCOUNT, "口座A", YAYOI["bank"]): MappingValue(
            "口座A", "銀行A", MappingStatus.USER_CONFIRMED, parent_account=YAYOI["bank"],
            metadata={"output_code": "0002", "target_code": "0002", "output_name": "銀行A"})}
        self.profiles.update(replace(profile, account_mappings=accounts, subaccount_context_mappings=subs))
        for identity, semantic in {PURCHASE: JdlTaxSemantic.PURCHASE_10_INTERNAL,
                                   SALES: JdlTaxSemantic.SALES_10_EXTERNAL,
                                   OUTSIDE: JdlTaxSemantic.NO_TAX}.items():
            confirm_tax_identity(self.profiles, self.profile.profile_id, self.context, identity, semantic)
        self.companies.replace_profile(self.company_id, self.profile.profile_id)

    def resolved(self):
        return self.companies.resolve(self.company_id)

    def assess(self, source=None):
        resolved = self.resolved()
        return YayoiJdlWorkflow().assess(source or self.source, resolved.profile, resolved.context)


def floor_context():
    return replace(context(), sales_tax_rounding=JdlTaxRounding.FLOOR, purchase_tax_rounding=JdlTaxRounding.FLOOR)


class YayoiImportFormatParserTest(unittest.TestCase):
    def test_rows_become_common_journals_with_unique_ids_and_row_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_import(directory, journals())
            self.assertTrue(looks_like_yayoi_import_format(path))
            self.assertIs(detect_format(path), IMPORT)
            entries = YayoiImportFormatParser().parse_path(path)
            again = YayoiImportFormatParser().parse_path(path)
        self.assertEqual(len(entries), 3)
        self.assertEqual(len({entry.id for entry in entries}), 3)  # voucher 1 is reused
        compound = entries[2]
        self.assertIsNone(compound.description)  # rows keep their own descriptions
        self.assertEqual([line.metadata[LINE_ROW_DESCRIPTION_KEY] for line in compound.lines], ["文具", "文具", "手数料"])
        self.assertIsNotNone(journal_physical_rows(compound))
        self.assertEqual(
            [entry.metadata[JOURNAL_CONTENT_IDENTITY_KEY] for entry in entries],
            [entry.metadata[JOURNAL_CONTENT_IDENTITY_KEY] for entry in again],
        )
        purchase = entries[0].lines[0].tax_info
        self.assertEqual((purchase.category, purchase.tax_amount), (PURCHASE, Decimal("100")))

    def test_optional_fields_and_unobserved_values(self):
        with tempfile.TemporaryDirectory() as directory:
            entries = YayoiImportFormatParser().parse_path(write_import(directory, journals(origin="取込")))
            self.assertEqual(entries[0].metadata["yayoi_optional_fields"], {"生成元": 1})
            bad = journals()
            bad[0][19] = "1"  # 出金伝票: not observed
            with self.assertRaises(YayoiImportFormatParseError):
                YayoiImportFormatParser().parse_path(write_import(directory, bad))
            self.assertFalse(YayoiImportFormatParser().diagnose(write_import(directory, bad)).ok)

    def test_report_files_are_still_detected_as_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, build([detail("令和08年05月10日", 1, debit=("現金Y", "", OUTSIDE, 100, None),
                                                  credit=("売上Y", "", OUTSIDE, 100, None))]))
            self.assertIs(detect_format(path), REPORT)


class YayoiImportFormatWorkflowTest(unittest.TestCase):
    def test_confirmed_company_is_ready_and_writes_formal_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-import", write_import(root, journals()), IMPORT, floor_context())
            self.assertIn("HUMAN:ACCOUNT_MAPPING", company.assess().blocker_counts())
            company.confirm_all()
            assessment = company.assess()
            self.assertEqual(assessment.ready_journals, 3, assessment.blocker_counts())
            resolved = company.resolved()
            output = root / "out.csv"
            prepared = YayoiJdlWorkflow().prepare(input_path=company.source, output_path=output,
                                                  profile=resolved.profile, context=resolved.context,
                                                  company_setting_validated=resolved.available)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = YayoiJdlWorkflow().execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            self.assertTrue(output.exists())

    def test_rounding_decides_whether_a_fractional_explicit_tax_is_ready(self):
        # 1106 -> floor 100 / half-up 101. Yayoi wrote 100.
        cases = {
            JdlTaxRounding.FLOOR: None,
            JdlTaxRounding.HALF_UP: "SYSTEM_EVIDENCE:EXPLICIT_TAX_KEEP_UNVERIFIED",
            JdlTaxRounding.UNCONFIRMED: "HUMAN:JDL_TAX_ROUNDING_SETTING",
        }
        for rounding, blocker in cases.items():
            with self.subTest(rounding=rounding), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = replace(context(), sales_tax_rounding=JdlTaxRounding.FLOOR, purchase_tax_rounding=rounding)
                source = write_import(root, journals(purchase_amount=1106, purchase_tax=100))
                company = Company(root, "company-r", source, IMPORT, target)
                company.confirm_all()
                counts = company.assess().blocker_counts()
                if blocker is None:
                    self.assertEqual(counts, {})
                else:
                    self.assertIn(blocker, counts)

    def test_departments_and_optional_fields_need_a_human_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_import(root, journals(origin="取込", department="部門A"))
            company = Company(root, "company-d", source, IMPORT, floor_context())
            company.confirm_all()
            counts = company.assess().blocker_counts()
        self.assertIn("HUMAN:DEPARTMENT_POLICY", counts)
        self.assertIn("HUMAN:OPTIONAL_FIELD_POLICY", counts)


class HiddenEvidenceGapTest(unittest.TestCase):
    """A shape x tax gap must show even while accounts are still unmapped."""

    def _source(self, root):
        # 2D2C with a 課税売上10% credit line: not covered by any 2D2C Evidence.
        return write_import(root, [
            row("2110", 9, "R.08/05/20", (YAYOI["supplies"], "", OUTSIDE, 2200, 0), (YAYOI["sales"], "", SALES, 2200, 200), "振替"),
            row("2101", 9, "R.08/05/20", (YAYOI["fee"], "", OUTSIDE, 300, 0), (YAYOI["cash"], "", OUTSIDE, 300, 0), "振替"),
        ])

    def test_unverified_2d2c_combination_is_reported_before_accounts_are_mapped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-h", self._source(root), IMPORT, floor_context())
            first = company.assess()
            self.assertEqual(first.likely_blocker_counts(), {"SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED": 1})
            self.assertNotIn("SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED", first.blocker_counts())
            for identity, semantic in ((OUTSIDE, JdlTaxSemantic.NO_TAX), (SALES, JdlTaxSemantic.SALES_10_EXTERNAL)):
                confirm_tax_identity(company.profiles, company.profile.profile_id, company.context, identity, semantic)
            company.companies.replace_profile(company.company_id, company.profile.profile_id)
            self.assertIn("SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED", company.assess().blocker_counts())
            company.confirm_all()
            final = company.assess()
            self.assertEqual(final.ready_journals, 0)
            self.assertIn("SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED", final.blocker_counts())


class UntaxedCompoundEvidenceTest(unittest.TestCase):
    """EVID-YAYOI-JDL-35-5-2D2C-NO-TAX-ROUNDTRIP-001: two rows of one debit + one credit, all untaxed."""

    def _company(self, root, rows):
        company = Company(root, "company-p", write_import(root, journals() + rows), IMPORT, floor_context())
        company.confirm_all()
        return company

    def test_two_paired_rows_are_ready_and_need_no_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = self._company(root, [
                row("2110", 9, "R.08/05/20", (YAYOI["supplies"], "", OUTSIDE, 500, 0), (YAYOI["bank"], "口座A", OUTSIDE, 500, 0), "振替"),
                row("2101", 9, "R.08/05/20", (YAYOI["fee"], "", OUTSIDE, 300, 0), (YAYOI["cash"], "", OUTSIDE, 300, 0), "振替"),
            ])
            self.assertEqual(company.assess().ready_journals, 4)
            resolved = company.resolved()
            with self.assertRaises(ValueError):
                YayoiJdlWorkflow().prepare_probe(input_path=company.source, output_path=root / "probe.csv",
                                                 profile=resolved.profile, context=resolved.context)
            prepared, ids = YayoiJdlWorkflow().prepare_probe(
                input_path=company.source, output_path=root / "p_NOT_FOR_PRODUCTION.csv",
                profile=resolved.profile, context=resolved.context)
            self.assertEqual(ids, ())
            output = root / "formal.csv"
            formal = YayoiJdlWorkflow().prepare(input_path=company.source, output_path=output, profile=resolved.profile,
                                                context=resolved.context, company_setting_validated=True)
            self.assertIs(formal.summary.readiness, FirstReleaseReadiness.READY, formal.summary.blocking_reasons)
            result = YayoiJdlWorkflow().execute(formal)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])

    def test_four_single_side_rows_are_not_covered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = self._company(root, [
                row("2110", 9, "R.08/05/20", (YAYOI["supplies"], "", OUTSIDE, 500, 0), None, "振替"),
                row("2100", 9, "R.08/05/20", None, (YAYOI["bank"], "口座A", OUTSIDE, 500, 0), "振替"),
                row("2100", 9, "R.08/05/20", (YAYOI["fee"], "", OUTSIDE, 300, 0), None, "振替"),
                row("2101", 9, "R.08/05/20", None, (YAYOI["cash"], "", OUTSIDE, 300, 0), "振替"),
            ])
            assessment = company.assess()
            self.assertEqual(assessment.ready_journals, 3)
            self.assertIn("SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED", assessment.blocker_counts())


class ProbeSalesAccountAndCompoundTest(unittest.TestCase):
    """Case A (課税売上10% on an unverified account) and case B (untaxed 2D2C) in one probe."""

    OTHER_SALES = "雑売上Y"

    def _company(self, root, extra_rows=()):
        source = write_import(root, journals() + [
            row("2000", 7, "R.08/05/15", (YAYOI["cash"], "", OUTSIDE, 5500, 0), (self.OTHER_SALES, "", SALES, 5500, 500), "売上"),
            row("2110", 9, "R.08/05/20", (YAYOI["supplies"], "", OUTSIDE, 500, 0), (YAYOI["bank"], "口座A", OUTSIDE, 500, 0), "振替"),
            row("2101", 9, "R.08/05/20", (YAYOI["fee"], "", OUTSIDE, 300, 0), (YAYOI["cash"], "", OUTSIDE, 300, 0), "振替"),
            *extra_rows,
        ])
        company = Company(root, "company-ab", source, IMPORT, floor_context())
        company.confirm_all()
        profile = company.profiles.get(company.profile.profile_id)
        accounts = dict(profile.account_mappings)
        accounts[self.OTHER_SALES] = MappingValue(self.OTHER_SALES, ACCOUNTS["9111"], MappingStatus.USER_CONFIRMED,
                                                  metadata={"target_code": "9111", "target_printed_name": ACCOUNTS["9111"],
                                                            "target_formal_name": ACCOUNTS["9111"]})
        company.profiles.update(replace(profile, account_mappings=accounts))
        company.companies.replace_profile(company.company_id, company.profile.profile_id)
        return company

    def test_sales10_is_never_generalized_by_account_count(self):
        from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

        widened = ev.TaxLineCapability("CREDIT", "JDL_SALES_10_EXTERNAL", frozenset({"6121", "9251", "6122"}), ())
        self.assertFalse(widened.account_independent)
        self.assertFalse(widened.covers("6123"))
        self.assertTrue(widened.covers("6122"))
        current = ev.LINE_CAPABILITIES[("CREDIT", "JDL_SALES_10_EXTERNAL")]
        self.assertEqual(current.verified_accounts, frozenset({"6121", "9251"}))  # 6122 stays PENDING
        with tempfile.TemporaryDirectory() as directory:
            counts = self._company(Path(directory)).assess().blocker_counts()
        self.assertEqual(counts.get("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED"), 1)

    def test_one_probe_holds_both_cases_and_nothing_else(self):
        from types import SimpleNamespace

        from accounting_converter.tools import yayoi_formal_output, yayoi_probe_check

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A third unverified journal (3D3C) must not enter the probe.
            company = self._company(root, extra_rows=[
                row("2110", 11, "R.08/05/25", (YAYOI["supplies"], "", OUTSIDE, 100, 0), (YAYOI["cash"], "", OUTSIDE, 100, 0), "x"),
                row("2100", 11, "R.08/05/25", (YAYOI["supplies"], "", OUTSIDE, 200, 0), (YAYOI["cash"], "", OUTSIDE, 200, 0), "x"),
                row("2101", 11, "R.08/05/25", (YAYOI["supplies"], "", OUTSIDE, 300, 0), (YAYOI["cash"], "", OUTSIDE, 300, 0), "x"),
            ])
            cases = YayoiJdlWorkflow().probe_cases(company.source, company.resolved().profile, company.resolved().context)
            # The untaxed 2D2C is verified now, so only case A remains to probe.
            self.assertEqual(sorted(case for case, _ in cases.values()), ["A_SALES10_ACCOUNT"])
            private = root / "data" / "private"
            private.mkdir(parents=True)
            probe = private / "probe_NOT_FOR_PRODUCTION.csv"
            with mock.patch("sys.argv", ["x", "--source", str(company.source), "--company-store", str(root),
                                         "--company-id", "company-ab", "--output", str(probe), "--probe"]):
                self.assertEqual(yayoi_formal_output.main(), 0)
            rows = [r for r in csv.reader(io.StringIO(probe.read_bytes().decode("cp932"))) if r[0][:1].isdigit()]
            self.assertEqual(len(rows), 1)  # A: 1 row
            sales = next(r for r in rows if r[13] == "9111")
            self.assertEqual((sales[0], sales[11], sales[21]), ("1111", "3300", "3300"))
            self.assertEqual((sales[18], sales[19], sales[20], sales[22]), ("売\u3000上", "10%", "外税", "300"))
            self.assertEqual(sales[12], "")  # untaxed debit side carries no tax
            self.assertEqual({r[23] for r in rows}, {"検証用NOT_FOR_PRODUCTION"})
            self.assertFalse(audit_path_for(probe).exists())
            manifest = json.loads(yayoi_probe_check.manifest_path_for(probe).read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PENDING_REAL_JDL_IMPORT")
            self.assertEqual(sorted(c["physical_rows"] for c in manifest["cases"]), [1])
            # Each case is judged on its own.
            both = yayoi_probe_check.check(probe, probe, manifest)
            self.assertEqual({k: v["verdict"] for k, v in both["cases"].items()}, {"A_SALES10_ACCOUNT": "PASS"})
            tampered = private / "reexport.csv"
            tampered.write_bytes(probe.read_bytes().replace(b",3300,300,", b",3300,301,", 1))
            one = yayoi_probe_check.check(probe, tampered, manifest)
            self.assertEqual({k: v["verdict"] for k, v in one["cases"].items()}, {"A_SALES10_ACCOUNT": "FAIL"})
            # Formal output is still refused (case A is not READY).
            formal = YayoiJdlWorkflow().prepare(input_path=company.source, output_path=private / "formal.csv",
                                                profile=company.resolved().profile, context=company.resolved().context,
                                                company_setting_validated=True)
            self.assertIs(formal.summary.readiness, FirstReleaseReadiness.BLOCKED)


class Sales6122ExactEvidenceTest(unittest.TestCase):
    """EVID-YAYOI-JDL-35-5-SALES10-1111-6122-ROUNDTRIP-001 is exact-only."""

    CAFE = "カフェ売上Y"

    def _company(self, root, debit, amount, tax, target="6122"):
        from accounting_converter.adapters.output.jdl import JdlAccountIdentity

        base = floor_context()
        extra = (JdlAccountIdentity("架空カフェ売上", "6122", "架空カ", "架空カフェ売上"),
                 JdlAccountIdentity("架空その他売上", "6123", "架空そ", "架空その他売上"))
        target_context = replace(base, accounts=base.accounts | {item.mapping_value for item in extra},
                                 account_master=base.account_master + extra)
        source = write_import(root, journals() + [
            row("2000", 7, "R.08/05/15", debit + ("", OUTSIDE, amount, 0), (self.CAFE, "", SALES, amount, tax), "売上"),
        ])
        company = Company(root, "company-6122", source, IMPORT, target_context)
        company.confirm_all()
        profile = company.profiles.get(company.profile.profile_id)
        accounts = dict(profile.account_mappings)
        name = {"6122": "架空カフェ売上", "6123": "架空その他売上"}[target]
        accounts[self.CAFE] = MappingValue(self.CAFE, name, MappingStatus.USER_CONFIRMED, metadata={
            "target_code": target, "target_printed_name": name, "target_formal_name": name})
        company.profiles.update(replace(profile, account_mappings=accounts))
        company.companies.replace_profile(company.company_id, company.profile.profile_id)
        return company

    def blockers(self, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            return self._company(Path(directory), **kwargs).assess().blocker_counts()

    def test_only_the_verified_signature_is_released(self):
        from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

        cash = (YAYOI["cash"],)
        self.assertEqual(self.blockers(debit=cash, amount=3300, tax=300), {})
        # Same credit account, another debit account: not covered (exact-only).
        self.assertIn("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED",
                      self.blockers(debit=(YAYOI["supplies"],), amount=3300, tax=300))
        # Floor and half-up differ (1106 -> 100.5...): the exact Evidence had no
        # fraction and rounding is verified only on 6121, so it stays blocked.
        fraction = self.blockers(debit=cash, amount=1106, tax=100)
        self.assertTrue(fraction and all(key.startswith("SYSTEM_EVIDENCE:") for key in fraction), fraction)
        # Another unverified sales account stays blocked.
        self.assertIn("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED",
                      self.blockers(debit=cash, amount=3300, tax=300, target="6123"))
        # The per-account sales capability is unchanged; 6122 does not widen it.
        self.assertEqual(ev.LINE_CAPABILITIES[("CREDIT", "JDL_SALES_10_EXTERNAL")].verified_accounts,
                         frozenset({"6121", "9251"}))
        self.assertFalse(ev.LINE_CAPABILITIES[("CREDIT", "JDL_SALES_10_EXTERNAL")].account_independent)


class NonRetainedInformationTest(unittest.TestCase):
    def _company(self, root):
        source = write_import(root, journals(origin="取込", department="部門A"))
        company = Company(root, "company-o", source, IMPORT, floor_context())
        company.confirm_all()
        return company

    def _confirm_fields(self, company, fields):
        for field in fields:
            confirm_optional_field_policy(company.profiles, company.profile.profile_id, field, "架空の意味")
        company.companies.replace_profile(company.company_id, company.profile.profile_id)

    def test_policy_needs_a_stated_meaning_and_every_field(self):
        with tempfile.TemporaryDirectory() as directory:
            company = self._company(Path(directory))
            with self.assertRaises(ValueError):
                confirm_optional_field_policy(company.profiles, company.profile.profile_id, "生成元", " ")
            self._confirm_fields(company, ["生成元"])
            counts = company.assess().blocker_counts()
            self.assertNotIn("HUMAN:OPTIONAL_FIELD_POLICY", counts)
            self.assertIn("HUMAN:DEPARTMENT_POLICY", counts)

    def test_audit_only_output_keeps_every_value_outside_jdl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = self._company(root)
            self._confirm_fields(company, ["生成元", "部門"])
            assessment = company.assess()
            self.assertEqual(assessment.ready_journals, 3, assessment.blocker_counts())
            self.assertFalse(assessment.information_fully_retained)
            self.assertEqual(assessment.non_retained_journals, {"生成元": 1, "部門": 1})
            resolved = company.resolved()
            output = root / "out.csv"
            prepared = YayoiJdlWorkflow().prepare(input_path=company.source, output_path=output,
                                                  profile=resolved.profile, context=resolved.context,
                                                  company_setting_validated=True)
            result = YayoiJdlWorkflow().execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            text = output.read_bytes().decode("cp932")
            self.assertNotIn("部門A", text)
            self.assertNotIn("取込", text)
            audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
            self.assertFalse(audit["information_fully_retained"])
            self.assertEqual(audit["jdl_output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            values = {(item["field"], item["value"]) for journal in audit["journals"] for item in journal["not_in_jdl"]}
            self.assertEqual(values, {("生成元", "取込"), ("部門(DEBIT)", "部門A"), ("部門(CREDIT)", "部門A")})

    def test_formal_csv_never_survives_without_its_audit(self):
        from unittest import mock

        from accounting_converter.application import yayoi_jdl_workflow as workflow_module
        from accounting_converter.application.yayoi_jdl_workflow import (
            pending_audit_path_for,
            verify_non_retained_audit,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = self._company(root)
            self._confirm_fields(company, ["生成元", "部門"])
            resolved = company.resolved()
            output = root / "out.csv"

            def prepare():
                return YayoiJdlWorkflow().prepare(input_path=company.source, output_path=output,
                                                  profile=resolved.profile, context=resolved.context,
                                                  company_setting_validated=True)

            # An existing audit (or pending) file blocks the run before anything is written.
            audit_path_for(output).write_text("occupied", encoding="utf-8")
            self.assertIs(prepare().summary.readiness, FirstReleaseReadiness.BLOCKED)
            audit_path_for(output).unlink()
            # Finalizing the audit fails after the CSV exists: everything is removed.
            prepared = prepare()
            with mock.patch.object(workflow_module, "finish_non_retained_audit", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    YayoiJdlWorkflow().execute(prepared)
            self.assertFalse(output.exists())
            self.assertFalse(audit_path_for(output).exists())
            self.assertFalse(pending_audit_path_for(output).exists())
            # A normal run leaves exactly one verified pair.
            YayoiJdlWorkflow().execute(prepare())
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["verdict"], "PASS")
            # A leftover .pending file (interrupted run) makes the pair FAIL.
            pending_audit_path_for(output).write_text("{}", encoding="utf-8")
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["verdict"], "FAIL")
            pending_audit_path_for(output).unlink()
            # A changed CSV no longer matches its audit.
            output.write_bytes(output.read_bytes() + b"\r\n")
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["verdict"], "FAIL")

    def test_identical_journals_each_get_their_own_audit_record(self):
        from accounting_converter.application.yayoi_jdl_workflow import verify_non_retained_audit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            twice = journals(origin="取込")[:1] * 2  # same content, same voucher, same day
            twice[1] = list(twice[1])
            twice[1][1] = "2"  # only the voucher number differs
            company = Company(root, "company-d2", write_import(root, twice + journals()[1:]), IMPORT, floor_context())
            company.confirm_all()
            confirm_optional_field_policy(company.profiles, company.profile.profile_id, "生成元", "架空の意味")
            company.companies.replace_profile(company.company_id, company.profile.profile_id)
            resolved = company.resolved()
            output = root / "out.csv"
            result = YayoiJdlWorkflow().execute(YayoiJdlWorkflow().prepare(
                input_path=company.source, output_path=output, profile=resolved.profile,
                context=resolved.context, company_setting_validated=True))
            self.assertEqual(result.status.value, "SUCCESS")
            check = verify_non_retained_audit(company.source, output, resolved.profile)
            self.assertEqual((check["verdict"], check["expected_journals"]), ("PASS", 2))

    def test_nothing_left_out_means_no_audit_and_full_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-f", write_import(root, journals()), IMPORT, floor_context())
            company.confirm_all()
            self.assertTrue(company.assess().information_fully_retained)
            resolved = company.resolved()
            output = root / "out.csv"
            prepared = YayoiJdlWorkflow().prepare(input_path=company.source, output_path=output,
                                                  profile=resolved.profile, context=resolved.context,
                                                  company_setting_validated=True)
            YayoiJdlWorkflow().execute(prepared)
            self.assertFalse(audit_path_for(output).exists())


class RoundTripCheckTest(unittest.TestCase):
    def test_source_csv_audit_and_reexport_are_all_checked(self):
        from accounting_converter.tools.yayoi_roundtrip_check import check

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = NonRetainedInformationTest()._company(root)
            NonRetainedInformationTest()._confirm_fields(company, ["生成元", "部門"])
            resolved = company.resolved()
            output = root / "out.csv"
            YayoiJdlWorkflow().execute(YayoiJdlWorkflow().prepare(
                input_path=company.source, output_path=output, profile=resolved.profile,
                context=resolved.context, company_setting_validated=True))
            before = check(company.source, resolved.profile, resolved.context, output, None)
            self.assertEqual(before["verdict"], "SOURCE_TO_CSV_PASS_REEXPORT_PENDING", before)
            self.assertEqual(before["verdict_information_outside_jdl"], "PASS")
            self.assertFalse(before["information_fully_retained"])
            self.assertEqual(check(company.source, resolved.profile, resolved.context, output, output)["verdict"], "PASS")
            # An amount changed in the "re-export" is caught.
            tampered = root / "reexport.csv"
            tampered.write_bytes(output.read_bytes().replace(b",1100,100,", b",1101,100,", 1))
            self.assertEqual(check(company.source, resolved.profile, resolved.context, output, tampered)["verdict"], "FAIL")
            # A candidate that differs from the source is caught even without a re-export.
            output.write_bytes(output.read_bytes().replace(b",1100,100,", b",1101,100,", 1))
            self.assertEqual(check(company.source, resolved.profile, resolved.context, output, None)["verdict"], "FAIL")


class OfficeSheetTest(unittest.TestCase):
    def test_only_filled_rows_are_applied(self):
        from types import SimpleNamespace

        from accounting_converter.tools import yayoi_office_sheet as sheet

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_import(root, journals(origin="取込"))
            company = Company(root, "company-s", source, IMPORT, floor_context())
            rows = sheet.build_rows(source, company.resolved().profile, company.resolved().context)
            kinds = Counter(row[1] for row in rows)
            self.assertEqual(kinds, {"科目": 5, "補助科目": 1, "税区分": 3, "JDLに入らない情報": 1})

            def apply(filled):
                path = root / "sheet.csv"
                buffer = io.StringIO(newline="")
                csv.writer(buffer).writerows([sheet.HEADER, *filled])
                path.write_bytes(buffer.getvalue().encode("utf-8-sig"))
                sheet.apply(SimpleNamespace(source=source, company_store=root, company_id="company-s", sheet=path))
                return company.assess()

            # Unfilled sheet: nothing confirmed.
            self.assertEqual(apply(rows).ready_journals, 0)
            self.assertEqual(company.profiles.get(company.profile.profile_id).account_mappings, {})
            filled = []
            for row in rows:
                row = list(row)
                if row[1] == "科目":
                    row[10] = TARGET[next(k for k, v in YAYOI.items() if v == row[2])]
                elif row[1] == "補助科目":
                    row[10] = "0002"
                elif row[1] == "税区分":
                    row[9] = "OK"
                else:
                    row[9] = ""  # not decided yet
                filled.append(row)
            self.assertIn("HUMAN:OPTIONAL_FIELD_POLICY", apply(filled).blocker_counts())
            filled[-1][9] = "OK"  # accepts the system's factual description
            self.assertEqual(apply(filled).ready_journals, 3)
            meaning = company.profiles.get(company.profile.profile_id).loss_policy_mappings[
                "yayoi_optional_field:生成元"].metadata["meaning"]
            self.assertTrue(meaning.startswith("弥生の生成元"))
            saved = company.profiles.get(company.profile.profile_id).account_mappings
            self.assertTrue(all(v.metadata["confirmed_via"] == "office_sheet" for v in saved.values()))


class OfficeSheetSafetyTest(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace

        from accounting_converter.tools import yayoi_office_sheet as sheet

        self.sheet = sheet
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = write_import(self.root, journals(origin="取込"))
        self.company = Company(self.root, "company-x", self.source, IMPORT, floor_context())
        self.args = lambda path, **kw: SimpleNamespace(source=self.source, company_store=self.root,
                                                       company_id="company-x", sheet=path, **kw)

    def tearDown(self):
        self._tmp.cleanup()

    def filled(self):
        rows = []
        for row in self.sheet.build_rows(self.source, self.company.resolved().profile, self.company.resolved().context):
            row = list(row)
            if row[1] == "科目":
                row[10] = TARGET[next(k for k, v in YAYOI.items() if v == row[2])]
            elif row[1] == "補助科目":
                row[10] = "0002"
            else:
                row[9] = "ok"  # lowercase from Excel is accepted
            rows.append(row)
        return rows

    def write(self, rows):
        path = self.root / "sheet.csv"
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerows([self.sheet.HEADER, *rows])
        path.write_bytes(buffer.getvalue().encode("utf-8-sig"))
        return path

    def store_bytes(self):
        return {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and p.suffix == ".json"}

    def test_any_bad_row_stops_everything(self):
        rows = self.filled()
        rows[0][10] = "9999"  # not in the JDL list
        before = self.store_bytes()
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)
        self.assertEqual(self.store_bytes(), before)

    def test_ok_with_a_different_code_is_a_contradiction(self):
        (self.root / "named").mkdir()
        self.source = write_import(self.root / "named", [
            row("2000", 1, "R.08/05/10", ("現金", "", OUTSIDE, 100, 0), ("手数料", "", OUTSIDE, 100, 0), "x")])
        self.company = Company(self.root / "named", "company-x", self.source, IMPORT, floor_context())
        self.root = self.root / "named"
        rows = [list(item) for item in self.sheet.build_rows(
            self.source, self.company.resolved().profile, self.company.resolved().context)]
        cash = next(item for item in rows if item[2] == "現金")
        self.assertTrue(cash[6].startswith("1111"))
        cash[9], cash[10] = "OK", "8681"
        before = self.store_bytes()
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)
        self.assertEqual(self.store_bytes(), before)

    def test_sheet_for_another_master_is_refused(self):
        rows = self.filled()
        rows[0][6] = "8888 古い候補"  # system column differs from the current master
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)

    def test_check_only_never_writes(self):
        before = self.store_bytes()
        self.assertEqual(self.sheet.apply(self.args(self.write(self.filled()), check=True)), 0)
        self.assertEqual(self.store_bytes(), before)

    def test_failure_while_saving_rolls_everything_back(self):
        from unittest import mock

        before = self.store_bytes()
        with mock.patch.object(self.sheet, "confirm_optional_field_policy", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.sheet.apply(self.args(self.write(self.filled())))
        self.assertEqual(self.store_bytes(), before)

    def test_valid_sheet_applies_completely_with_backup(self):
        backup = self.root / "backup"
        self.assertEqual(self.sheet.apply(self.args(self.write(self.filled()), backup_dir=backup)), 0)
        self.assertTrue(any(backup.rglob("*.json")))
        self.assertEqual(self.company.assess().ready_journals, 3)


class OfficeSheetDescriptionAndUnusableTest(unittest.TestCase):
    """Report-format company: description rows, candidate kinds, unusable subaccounts."""

    LONG = "架空の長い補助名称ですよ"  # 12 full-width characters: does not fit the JDL field

    def setUp(self):
        from types import SimpleNamespace

        from accounting_converter.adapters.output.jdl import JdlUnusableSubaccount
        from accounting_converter.application.yayoi_sources import REPORT
        from accounting_converter.tools import yayoi_office_sheet as sheet
        from tests.test_yayoi_jdl_workflow import TARGET as WT, YAYOI as WY, details

        self.codes = {WY[key]: WT[key] for key in WY} | {"現金": "1111"}

        self.sheet = sheet
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        rows = details(long_description=True) + [
            detail("令和08年05月12日", 3, debit=("現金", "", OUTSIDE, 500, None),
                   credit=(WY["bank"], self.LONG, OUTSIDE, 500, None), description="振替", number=3),
        ]
        self.source = write(self.root, build(rows))
        base = floor_context()
        target = replace(base, unusable_subaccounts=(JdlUnusableSubaccount(
            "普通預金", "1311", "0099", self.LONG, "NAME_EXCEEDS_JDL_IMPORT_FIELD"),))
        self.company = Company(self.root, "company-r", self.source, REPORT, target)
        self.args = lambda path, **kw: SimpleNamespace(source=self.source, company_store=self.root,
                                                       company_id="company-r", sheet=path, **kw)

    def tearDown(self):
        self._tmp.cleanup()

    def rows(self):
        resolved = self.company.resolved()
        return [list(row) for row in self.sheet.build_rows(self.source, resolved.profile, resolved.context)]

    def write(self, rows):
        path = self.root / "sheet.csv"
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerows([self.sheet.HEADER, *rows])
        path.write_bytes(buffer.getvalue().encode("utf-8-sig"))
        return path

    def test_kinds_and_description_rows(self):
        rows = self.rows()
        by_kind = {row[1]: row for row in rows}
        self.assertEqual(by_kind["摘要"][3], "手数料" * 12)
        self.assertTrue(by_kind["摘要"][13].startswith("候補:"))
        cash = next(row for row in rows if row[1] == "科目" and row[2] == "現金")
        self.assertEqual(cash[13], "同名")
        long_sub = next(row for row in rows if row[1] == "補助科目" and row[3] == self.LONG)
        self.assertEqual((long_sub[6], long_sub[13]), ("", "選択不可（JDL補助名が取込欄を超える）"))
        self.assertTrue(all(row[9] == row[10] == row[11] == "" for row in rows))  # nothing pre-approved

    def test_truncated_candidate_needs_written_text_and_rules_apply(self):
        rows = self.rows()
        description = next(row for row in rows if row[1] == "摘要")
        description[9] = "OK"  # the candidate is a truncation: OK alone is not enough
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)
        description[9], description[11] = "", "改" + "行\nあり"
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)
        description[11] = "振込手数料"
        self.assertEqual(self.sheet.apply(self.args(self.write(rows), check=True)), 0)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*.json")}, before)

    def test_unusable_subaccount_cannot_be_chosen_and_parent_still_needs_one(self):
        rows = self.rows()
        for row in rows:
            if row[1] == "科目":
                row[10] = self.codes[row[2]]
            elif row[1] == "補助科目":
                row[10] = "0099" if row[3] == self.LONG else "0002"
            elif row[1] == "摘要":
                row[11] = "振込手数料"
            else:
                row[9] = "OK"
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 2)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*.json")}, before)
        # Leaving the long subaccount unmapped keeps that journal blocked; the others are fine.
        for row in rows:
            if row[1] == "補助科目" and row[3] == self.LONG:
                row[10] = ""
        self.assertEqual(self.sheet.apply(self.args(self.write(rows))), 0)
        assessment = self.company.assess()
        self.assertEqual(assessment.ready_journals, 2)
        self.assertEqual(assessment.blocker_counts(), {"HUMAN:SUBACCOUNT_MAPPING": 1})
        context = self.company.resolved().context
        self.assertTrue(context.parent_has_subaccounts(code="1311"))
        self.assertNotIn("0099", {sub.target_master_code for sub in context.subaccounts})


class CompanySeparationTest(unittest.TestCase):
    def test_two_companies_never_share_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import_source = write_import(root, journals())
            report_source = write(root, build([detail(
                "令和08年05月11日", 1, debit=(YAYOI["cash"], "", OUTSIDE, 2200, None),
                credit=(YAYOI["sales"], "", "課税売上内10%", 2200, 200), description="売上")]))
            a = Company(root, "company-a", import_source, IMPORT, floor_context())
            b = Company(root, "company-b", report_source, REPORT, replace(
                context(), sales_tax_rounding=JdlTaxRounding.CEILING, purchase_tax_rounding=JdlTaxRounding.HALF_UP))
            a.confirm_all()
            # Confirming A changes nothing in B: same names, separate profiles.
            b_profile = b.profiles.get(b.profile.profile_id)
            self.assertEqual(b_profile.account_mappings, {})
            self.assertTrue(all(v.status is MappingStatus.UNRESOLVED for v in b_profile.tax_mappings.values()))
            self.assertEqual(b.assess().ready_journals, 0)
            # B's profile cannot be used for A's file (format mismatch is refused).
            prepared = YayoiJdlWorkflow().prepare(
                input_path=import_source, output_path=root / "x.csv", profile=b.resolved().profile,
                context=b.resolved().context, company_setting_validated=True)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            # Each company keeps its own rounding.
            self.assertEqual(a.resolved().context.sales_tax_rounding, JdlTaxRounding.FLOOR)
            self.assertEqual(b.resolved().context.sales_tax_rounding, JdlTaxRounding.CEILING)
            self.assertEqual(a.assess().ready_journals, 3)

    def test_same_company_reuses_settings_for_a_new_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-a", write_import(root, journals()), IMPORT, floor_context())
            company.confirm_all()
            (root / "m2").mkdir()
            next_month = write_import(root / "m2", journals())
            self.assertEqual(company.assess(next_month).ready_journals, 3)
            review = review_source(IMPORT.read(next_month), company.resolved().profile, company.resolved().context)
            self.assertEqual(review.setting_item_counts["accounts"], 0)
            self.assertEqual(review.setting_item_counts["tax_identities"], 0)


if __name__ == "__main__":
    unittest.main()

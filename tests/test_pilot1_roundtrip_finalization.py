"""Round-trip check pieces finalised for Pilot-1: tax rule per JDL semantic, audit found by SHA-256,
Evidence-backed 摘要 trailing-space loss with a separate user acceptance. Synthetic data only."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import jdl_description_trailing_space as trailing
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJdlWorkflow,
    audit_path_for,
    pending_audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.application.yayoi_sources import IMPORT
from accounting_converter.domain.journal import JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.tools import jdl_description_trailing_space_acceptance as acceptance_tool
from accounting_converter.tools import yayoi_roundtrip_check as rc
from tests.test_yayoi_import_format import (
    YAYOI,
    Company,
    NonRetainedInformationTest,
    floor_context,
    journals,
    write_import,
)


def _line(tax_amount):
    return JournalLine(side=Side.DEBIT, account="A", amount=Decimal("1100"),
                       source_reference=SourceReference("f", 1, "1"),
                       tax_info=TaxInfo(category="X", tax_amount=tax_amount))


def _convert(company, output):
    resolved = company.resolved()
    result = YayoiJdlWorkflow().execute(YayoiJdlWorkflow().prepare(
        input_path=company.source, output_path=output, profile=resolved.profile,
        context=resolved.context, company_setting_validated=True))
    assert result.status.value == "SUCCESS", [v.rule_id for v in result.validation_results]
    return resolved


class TargetTaxAmountTest(unittest.TestCase):
    def test_each_semantic_gets_the_amount_the_writer_writes(self):
        cases = {
            JdlTaxSemantic.PURCHASE_10_INTERNAL: (Decimal("99"), Decimal("99"), Decimal("100")),
            JdlTaxSemantic.SALES_10_EXTERNAL: (Decimal("99"), Decimal("99"), Decimal("100")),
            JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL: (Decimal("81"), Decimal("81"), None),
            JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL: (Decimal("80"), Decimal("80"), None),
            JdlTaxSemantic.NON_TAXABLE_PURCHASE: (Decimal("80"), None, None),
            JdlTaxSemantic.NON_TAXABLE_SALES: (Decimal("80"), None, None),
            JdlTaxSemantic.EXPORT_SALES: (Decimal("80"), None, None),
            JdlTaxSemantic.NO_TAX: (Decimal("80"), None, None),
        }
        for semantic, (explicit, with_explicit, without) in cases.items():
            with self.subTest(semantic=semantic):
                self.assertEqual(ev.target_tax_amount(semantic.value, _line(explicit), Decimal("1100")), with_explicit)
                self.assertEqual(ev.target_tax_amount(semantic.value, _line(None), Decimal("1100")), without)
        self.assertIsNone(ev.target_tax_amount("UNMAPPED", _line(Decimal("80")), Decimal("1100")))

    def test_round_trip_source_view_keeps_the_explicit_80_percent_transitional_tax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-t80", write_import(root, journals(purchase_tax=80)), IMPORT,
                              floor_context())
            company.confirm_all()
            resolved = company.resolved()
            purchase = {YAYOI["fee"], YAYOI["supplies"]}
            original = ev.target_tax_semantic

            def as_transitional(line, profile, context):
                if line.account in purchase:
                    return JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL.value
                return original(line, profile, context)

            with mock.patch.object(rc.ev, "target_tax_semantic", side_effect=as_transitional):
                *_, lines, _descriptions, _structure, _physical = rc.source_view(
                    company.source, resolved.profile, resolved.context)
            # Before the fix the transitional line was expected with tax 0.
            first = [key for key in lines if key[0] == "20260510" and key[1] == "DEBIT"]
            self.assertEqual([key[5] for key in first], [Decimal("80")])
            # The ordinary 10% rule still applies to the other lines.
            *_, plain, _d, _s, _p = rc.source_view(company.source, resolved.profile, resolved.context)
            self.assertEqual([key[5] for key in plain if key[0] == "20260510" and key[1] == "DEBIT"],
                             [Decimal("80")])
            self.assertIn(Decimal("200"), {key[5] for key in plain if key[0] == "20260511"})


class AuditByOutputHashTest(unittest.TestCase):
    def _pair(self, root):
        company = NonRetainedInformationTest()._company(root)
        NonRetainedInformationTest()._confirm_fields(company, ["生成元", "部門"])
        output = root / "out.csv"
        resolved = _convert(company, output)
        return company, resolved, output

    def test_a_renamed_csv_keeps_its_audit_only_by_its_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company, resolved, output = self._pair(root)
            renamed = root / "renamed_for_import.csv"
            output.rename(renamed)
            check = verify_non_retained_audit(company.source, renamed, resolved.profile)
            self.assertEqual((check["verdict"], check["audit_found_by"]), ("PASS", "OUTPUT_SHA256"))
            self.assertFalse(check["audit_names_this_file"])
            # The audit file itself is never rewritten.
            self.assertTrue(audit_path_for(output).exists())
            # A changed CSV has no audit any more.
            changed = root / "changed.csv"
            changed.write_bytes(renamed.read_bytes() + b"\r\n")
            check = verify_non_retained_audit(company.source, changed, resolved.profile)
            self.assertEqual((check["verdict"], check["audit_found_by"]), ("FAIL", "NOT_FOUND"))
            # A leftover .pending of the matched audit fails.
            pending = pending_audit_path_for(output)
            pending.write_text("{}", encoding="utf-8")
            self.assertEqual(verify_non_retained_audit(company.source, renamed, resolved.profile)["verdict"], "FAIL")
            pending.unlink()
            # Two audits naming the same bytes: ambiguous, FAIL.
            shutil.copy(audit_path_for(output), root / "copy.csv.audit.json")
            check = verify_non_retained_audit(company.source, renamed, resolved.profile)
            self.assertEqual((check["verdict"], check["audit_found_by"]), ("FAIL", "AMBIGUOUS"))
            # The exact name still wins over the hash search and is validated as before.
            shutil.copy(renamed, output)
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["audit_found_by"],
                             "NAME")

    def test_nothing_left_out_fails_when_an_audit_of_these_bytes_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = Company(root, "company-f", write_import(root, journals()), IMPORT, floor_context())
            company.confirm_all()
            output = root / "out.csv"
            resolved = _convert(company, output)
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["verdict"],
                             "NOT_NEEDED")
            import hashlib

            (root / "stray.csv.audit.json").write_text(json.dumps({
                "schema": "yayoi-jdl-non-retained-audit-v1",
                "jdl_output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}), encoding="utf-8")
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile)["verdict"], "FAIL")


class EvidenceHistoryTest(unittest.TestCase):
    def test_the_pilot1_entry_is_unchanged_and_the_pilot2_entry_adds_only_three_half_width_spaces(self):
        self.assertEqual(trailing.EVIDENCE.evidence_id,
                         "EVID-YAYOI-JDL-35-5-BUDDIES-PILOT1-DESCRIPTION-TRAILING-SPACE-REMOVED-001")
        self.assertEqual(trailing.EVIDENCE.observed_suffixes, frozenset({" ", "  ", "\u3000"}))
        self.assertEqual((trailing.EVIDENCE.candidate_sha256[:8], trailing.EVIDENCE.reexport_sha256[:8]),
                         ("6b88c0a9", "cc61d8a8"))
        self.assertEqual(trailing.EVIDENCE_PILOT2.observed_suffixes, frozenset({"   "}))
        self.assertEqual((trailing.EVIDENCE_PILOT2.candidate_sha256[:8], trailing.EVIDENCE_PILOT2.reexport_sha256[:8]),
                         ("3170b96d", "68b6d272"))
        self.assertEqual(trailing.EVIDENCES, (trailing.EVIDENCE, trailing.EVIDENCE_PILOT2))
        # Same scope: nothing widened except the run.
        for field in ("company_setting_ids", "scope_id", "jdl_product", "jdl_version", "import_format"):
            self.assertEqual(getattr(trailing.EVIDENCE_PILOT2, field), getattr(trailing.EVIDENCE, field))
        self.assertIn("EVID-YAYOI-JDL-35-5-BUDDIES-PILOT2-DESCRIPTION-TRAILING-SPACE-REMOVED-001",
                      trailing.EVIDENCE_PILOT2.evidence_id)
        # No entry has ever recorded these.
        for unseen in ("    ", "     ", "\u3000\u3000", "\t", " \u3000", "\u3000 ", "\u3000\u3000\u3000", ""):
            self.assertIsNone(trailing.evidence_for_suffix(unseen), repr(unseen))
        self.assertIs(trailing.evidence_for_suffix("   "), trailing.EVIDENCE_PILOT2)
        self.assertIs(trailing.evidence_for_suffix(" "), trailing.EVIDENCE)

    def test_removal_rule_with_the_new_run(self):
        runs = frozenset().union(*(e.observed_suffixes for e in trailing.EVIDENCES))
        self.assertEqual(trailing.removed_trailing_suffix("A   ", "A", runs), "   ")
        for before, after in (("A    ", "A"), ("A   ", "A "), ("A   ", "A  "), ("A \u3000", "A"), ("A \t", "A"),
                              (" A   ", "A"), ("A   ", "A\u3000")):
            self.assertIsNone(trailing.removed_trailing_suffix(before, after, runs), repr(before))
        # An entry's run is usable only inside that entry's scope.
        from tests.test_yayoi_scoped_workflow import scoped_context

        company = next(iter(trailing.EVIDENCE.company_setting_ids))
        self.assertEqual(trailing.applicable_suffixes(company, scoped_context()), runs)
        self.assertEqual(trailing.applicable_suffixes("company-other", scoped_context()), frozenset())
        self.assertEqual(trailing.applicable_suffixes(company, floor_context()), frozenset())


class TrailingSpaceScopeTest(unittest.TestCase):
    def test_only_the_evidence_company_and_jdl_scope(self):
        from tests.test_yayoi_scoped_workflow import scoped_context

        company = next(iter(trailing.EVIDENCE.company_setting_ids))
        self.assertEqual(trailing.scope_problems(company, scoped_context()), ())
        self.assertEqual(trailing.scope_problems("company-other", scoped_context()), ("COMPANY_OUT_OF_SCOPE",))
        self.assertEqual(trailing.scope_problems(company, floor_context()), ("CONTEXT_OUT_OF_SCOPE",))
        self.assertEqual(trailing.scope_problems(company, scoped_context(limit=64)), ("CONTEXT_OUT_OF_SCOPE",))
        self.assertEqual(trailing.scope_problems(company, None), ("CONTEXT_OUT_OF_SCOPE",))


class TrailingSpaceRoundTripTest(unittest.TestCase):
    def _round(self, root, tail=" "):
        # 仕訳日記帳 report (as in Pilot-1): the source 摘要 keeps its trailing half-width space.
        from tests.test_yayoi_scoped_workflow import make, sales_voucher

        rows = sales_voucher(3)
        rows[1][23] = "売上2" + tail
        fixture = make(root, rows)
        fixture.company_id = "company-yayoi"
        output = root / "out.csv"
        resolved = fixture.resolved()
        result = YayoiJdlWorkflow().execute(YayoiJdlWorkflow().prepare(
            input_path=fixture.source, output_path=output, profile=resolved.profile,
            context=resolved.context, company_setting_validated=resolved.available))
        self.assertEqual(result.status.value, "SUCCESS")
        data = output.read_bytes()
        needle = ("売上2" + tail).encode("cp932")
        self.assertEqual(data.count(needle), 1)
        reexport = root / "reexport.csv"
        reexport.write_bytes(data.replace(needle, "売上2".encode("cp932")))
        return fixture, resolved, output, reexport

    def test_out_of_scope_the_loss_is_an_unexpected_change(self):
        with tempfile.TemporaryDirectory() as directory:
            company, resolved, output, reexport = self._round(Path(directory))
            result = rc.check(company.source, resolved.profile, resolved.context, output, reexport,
                              company_setting_id=company.company_id)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertEqual(result["description_trailing_space_scope"], ["COMPANY_OUT_OF_SCOPE"])
            self.assertNotIn("description_trailing_space_loss", result)

    def test_in_scope_the_loss_is_recorded_and_needs_the_users_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company, resolved, output, reexport = self._round(root)
            with mock.patch.object(rc.trailing, "scope_problems", return_value=()):
                pending = rc.check(company.source, resolved.profile, resolved.context, output, reexport)
                loss = pending["description_trailing_space_loss"]
                self.assertEqual(pending["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")
                self.assertEqual(pending["candidate_vs_reexport"]["unexplained_differences"], 0)
                self.assertEqual(loss["acceptance"], {"state": "NOT_RECORDED"})
                self.assertEqual(loss["source_alignment"], "PASS")
                self.assertFalse(loss["this_round_is_the_evidence_round"])
                self.assertEqual(len(loss["rows"]), 1)
                record = loss["rows"][0]
                self.assertEqual((record["row"], record["voucher"], record["source_row"], record["removed"]),
                                 (2, "1", 10, {"half_width_space": 1, "ideographic_space": 0}))
                self.assertEqual((record["candidate_description"], record["reexport_description"]),
                                 ("売上2 ", "売上2"))
                # The source 摘要 itself is unchanged.
                self.assertEqual(pending["source_vs_candidate"]["row_descriptions"], {"missing": 0, "extra": 0})

                # The record and the acceptance go through files (data/private only).
                private = root / "data" / "private"
                private.mkdir(parents=True)
                rc.write_record(pending, private / "record.json")
                saved = json.loads((private / "record.json").read_text(encoding="utf-8"))
                payload = acceptance_tool.build(saved, accepted_by="架空の確認者", reference="架空の記録",
                                                accepted_on=date(2026, 11, 10))
                accepted_path = private / "acceptance.json"
                accepted_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                accepted = rc.check(company.source, resolved.profile, resolved.context, output, reexport,
                                    acceptance=accepted_path)
                self.assertEqual(accepted["verdict"], "PASS_WITH_ACCEPTED_NORMALIZATION")
                self.assertEqual(accepted["description_trailing_space_loss"]["acceptance"]["state"], "ACCEPTED")

                # An acceptance never carries to other bytes, other rows or an incomplete decision.
                for change in ({"reexport_sha256": "0" * 64}, {"rows_sha256": "0" * 64}, {"decision": "REJECTED"},
                               {"accepted_by": " "}, {"accepted_on": "someday"}, {"evidence_ids": ["OTHER"]}, {"evidence_ids": []}):
                    with self.subTest(change=change):
                        bad = private / "bad.json"
                        bad.write_text(json.dumps({**payload, **change}, ensure_ascii=False), encoding="utf-8")
                        result = rc.check(company.source, resolved.profile, resolved.context, output, reexport,
                                          acceptance=bad)
                        self.assertEqual(result["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")
                        self.assertEqual(result["description_trailing_space_loss"]["acceptance"]["state"], "INVALID")

                # Any other change on top is still a FAIL, accepted or not.
                worse = root / "worse.csv"
                worse.write_bytes(reexport.read_bytes().replace("売上3".encode("cp932"), "売上X".encode("cp932"), 1))
                self.assertEqual(rc.check(company.source, resolved.profile, resolved.context, output, worse,
                                          acceptance=accepted_path)["verdict"], "FAIL")

    def test_each_row_rests_on_the_evidence_entry_that_recorded_its_run(self):
        for tail, entry in ((" ", trailing.EVIDENCE), ("  ", trailing.EVIDENCE), ("\u3000", trailing.EVIDENCE),
                            ("   ", trailing.EVIDENCE_PILOT2)):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                company, resolved, output, reexport = self._round(root, tail)
                with mock.patch.object(rc.trailing, "scope_problems", return_value=()):
                    result = rc.check(company.source, resolved.profile, resolved.context, output, reexport)
                self.assertEqual(result["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")
                loss = result["description_trailing_space_loss"]
                self.assertEqual(loss["evidence_ids"], [entry.evidence_id])
                self.assertEqual([r["evidence_id"] for r in loss["rows"]], [entry.evidence_id])

    def test_a_run_no_entry_recorded_is_still_a_failure(self):
        for tail in ("    ", "\u3000\u3000", " \u3000"):  # a tab never reaches the CSV (the app blocks it)
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                company, resolved, output, reexport = self._round(root, tail)
                with mock.patch.object(rc.trailing, "scope_problems", return_value=()):
                    result = rc.check(company.source, resolved.profile, resolved.context, output, reexport)
                self.assertEqual(result["verdict"], "FAIL")
                self.assertEqual(result["candidate_vs_reexport"]["unexplained_differences"], 1)

    def test_the_tool_refuses_records_it_cannot_bind(self):
        with self.assertRaises(ValueError):
            acceptance_tool.build({"schema": rc.RECORD_SCHEMA, "evidence_ids": [trailing.EVIDENCE.evidence_id],
                                   "rows": [{"row": 1, "evidence_id": trailing.EVIDENCE.evidence_id}],
                                   "rows_sha256": "0" * 64, "source_alignment": "PASS"},
                                  accepted_by="x", reference="y", accepted_on=date(2026, 11, 10))
        rows = [{"row": 1, "evidence_id": trailing.EVIDENCE.evidence_id}]
        with self.assertRaises(ValueError):
            acceptance_tool.build({"schema": rc.RECORD_SCHEMA, "evidence_ids": [trailing.EVIDENCE.evidence_id],
                                   "rows": rows, "rows_sha256": trailing.rows_sha256(rows), "source_alignment": "FAIL"},
                                  accepted_by="x", reference="y", accepted_on=date(2026, 11, 10))
        with self.assertRaises(SystemExit):
            rc.write_record({"description_trailing_space_loss": {}}, Path(tempfile.gettempdir()) / "x.json")


if __name__ == "__main__":
    unittest.main()

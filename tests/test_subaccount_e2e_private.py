"""Regression: the app still writes the subaccount E2E CSV that JDL round-tripped on 2026-11-07 (private data only)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

E2E = Path("data/private/yayoi_buddies/subaccount_e2e_20261107")
# JDL re-export of the Import (2026-07-18) that passed yayoi_roundtrip_check strictly.
REEXPORT_SHA256 = "dd6c7a3d6333cb98"


@unittest.skipUnless((E2E / "manifest.json").exists() and (E2E / "store_copy").exists(), "private data is not present")
class SubaccountE2ERegressionTest(unittest.TestCase):
    def test_same_bytes_and_still_round_trips(self):
        from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
        from accounting_converter.tools.yayoi_roundtrip_check import check

        manifest = json.loads((E2E / "manifest.json").read_text(encoding="utf-8"))
        source = E2E / "YAYOI_SUB_E2E_20260718_NOT_FOR_PRODUCTION_source.txt"
        profiles = ConversionProfileStore(E2E / "store_copy" / "profiles")
        resolved = CompanySettingStore(E2E / "store_copy" / "companies", profiles).resolve(manifest["company_setting_id"])
        reexport = E2E / "JDL_再Export_20260718.csv"
        self.assertTrue(hashlib.sha256(reexport.read_bytes()).hexdigest().startswith(REEXPORT_SHA256))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "regenerated.csv"
            workflow = YayoiJournalReportJdlWorkflow()
            prepared = workflow.prepare(input_path=source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=resolved.available)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS")
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), manifest["jdl_csv_sha256"])
            report = check(source, resolved.profile, resolved.context, output, reexport)
            self.assertEqual(report["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()

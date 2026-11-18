"""Deleting a company setting never carries its approvals over to a new company, even with the same name and profile.

Synthetic data in a temporary directory only (no Qt, no real AppData). The approvals live in the conversion profile,
which a company deletion keeps; each approval records the company it was made for, and a company added later gets a
new random id, so the earlier approval is not applied to it.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from pathlib import Path

from accounting_converter.application import approval_ledger as al
from accounting_converter.application import voucher_split as vs
from tests.test_voucher_split import approve, card_voucher
from tests.test_yayoi_scoped_workflow import make


class DeletedCompanyIsolationTest(unittest.TestCase):
    def test_a_company_added_after_a_deletion_does_not_inherit_the_old_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(20))
            approve(fixture)
            old = fixture.resolved()
            self.assertEqual(vs.policy_problems(old.profile, old.context), ())          # approved for the old company
            name = fixture.companies.get("company-yayoi").display_name
            profile_files = sorted(p.name for p in fixture.profiles.root_dir.iterdir())
            ledger = al.default_ledger_path(Path(directory), "company-yayoi")

            fixture.companies.delete("company-yayoi")                                   # the existing deletion
            self.assertFalse((fixture.companies.root_dir / "company-yayoi").exists())
            self.assertEqual(sorted(p.name for p in fixture.profiles.root_dir.iterdir()), profile_files)  # profile kept

            fixture.companies.create(                                                   # same name, same profile
                company_setting_id="company-new-uuid", display_name=name,
                conversion_profile_id=fixture.profile.profile_id, context_source=Path(directory) / "context.json")
            new = fixture.companies.resolve("company-new-uuid")
            self.assertEqual(new.context.company_setting_id, "company-new-uuid")
            problems = vs.policy_problems(new.profile, new.context)
            self.assertIn("COMPANY_DIFFERS_FROM_APPROVAL", problems)                    # the old approval is not used
            self.assertNotEqual(al.default_ledger_path(Path(directory), "company-new-uuid"), ledger)  # own ledger


if __name__ == "__main__":
    unittest.main()

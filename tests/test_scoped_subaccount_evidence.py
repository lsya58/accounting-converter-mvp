from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from unittest.mock import patch

from accounting_converter.adapters.output.jdl import JdlSubaccountIdentity
from accounting_converter.adapters.output.jdl.scoped_subaccount_evidence import (
    SubaccountKeepEvidence, VERIFIED_CODED_KEEP, REJECTED_SUBACCOUNT_REPRESENTATIONS,
    exact_keep_evidence,
)
from tests.test_scoped_evidence import context


class ScopedSubaccountEvidenceTests(unittest.TestCase):
    def test_exact_coded_keep_needs_current_master_identity_and_scope(self) -> None:
        name = "架空補助"
        digest = hashlib.sha256(f"1551\0{1}\0{name}".encode("utf-8")).hexdigest()
        observed = SubaccountKeepEvidence("SYNTHETIC", "SYNTHETIC-ID", "CREDIT", "1551", "1111", "1", digest)
        sub = JdlSubaccountIdentity(
            parent_account="架空売掛金", mapping_value=name, target_master_code="0001",
            output_code="0001", output_name=name, output_representation_confirmed=True,
            parent_account_code="1551", target_name=name,
        )
        current = replace(context(), subaccounts=(sub,))
        kwargs = dict(side="CREDIT", parent_code="1551", opposite_account_code="1111",
                      subaccount_code="0001", flag="1111", layout="B1", tax_cells=("NO", "NO"))
        with patch("accounting_converter.adapters.output.jdl.scoped_subaccount_evidence.VERIFIED_CODED_KEEP", (observed,)):
            self.assertEqual(exact_keep_evidence(current, **kwargs), "SYNTHETIC-ID")
            self.assertIsNone(exact_keep_evidence(current, **{**kwargs, "subaccount_code": "0000"}))
            self.assertIsNone(exact_keep_evidence(current, **{**kwargs, "layout": "B2"}))
            self.assertIsNone(exact_keep_evidence(current, **{**kwargs, "tax_cells": ("NO", "P10")}))
            self.assertIsNone(exact_keep_evidence(replace(current, subaccounts=(replace(sub, target_name="別名"),)), **kwargs))
            self.assertIsNone(exact_keep_evidence(replace(current, voucher_row_limit=None), **kwargs))

    def test_rejections_are_not_positive_evidence(self) -> None:
        self.assertEqual(len(VERIFIED_CODED_KEEP), 2)
        self.assertEqual(set(REJECTED_SUBACCOUNT_REPRESENTATIONS),
                         {("3141", ""), ("1551", "0000"), ("3141", "0000")})
        self.assertTrue(all("REJECT" in item for item in REJECTED_SUBACCOUNT_REPRESENTATIONS.values()))

from __future__ import annotations

import unittest
from types import SimpleNamespace

from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.tools.generate_mf_exact_shape_probe import ExactShapeProbeError
from accounting_converter.tools.generate_mf_pending_tax_probe import CASES, _confirmed_target


class PendingTaxProbeTests(unittest.TestCase):
    def test_pending_tax_cases_do_not_include_unobserved_outside_purchase(self) -> None:
        self.assertEqual(
            {item[0] for item in CASES},
            {"課税売上 10%", "非課税仕入", "非課税売上"},
        )

    def test_confirmed_account_without_target_subaccount_is_usable(self) -> None:
        account = SimpleNamespace(
            target_master_code="6121", mapping_value="target-sales"
        )
        profile = SimpleNamespace(account_mappings={
            "source-sales": SimpleNamespace(
                status=MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "6121"},
                target_value="target-sales",
            )
        })
        line = SimpleNamespace(account="source-sales", sub_account=None)
        self.assertEqual(
            _confirmed_target(line, profile, {"6121": account}, {}),
            (account, None),
        )

    def test_blank_source_cannot_use_parent_with_required_target_subaccount(self) -> None:
        account = SimpleNamespace(
            target_master_code="1311", mapping_value="target-bank"
        )
        profile = SimpleNamespace(account_mappings={
            "source-bank": SimpleNamespace(
                status=MappingStatus.USER_CONFIRMED,
                metadata={"target_code": "1311"},
                target_value="target-bank",
            )
        })
        line = SimpleNamespace(account="source-bank", sub_account=None)
        with self.assertRaisesRegex(ExactShapeProbeError, "default subaccount"):
            _confirmed_target(
                line, profile, {"1311": account},
                {("1311", "0001"): SimpleNamespace()},
            )


if __name__ == "__main__":
    unittest.main()

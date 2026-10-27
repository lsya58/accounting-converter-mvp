from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.application.company_master_refresh import (
    CompanyMasterRefreshService,
)
from accounting_converter.application.profile_revision import (
    MAX_REVISION_PROFILE_ID_LENGTH,
    revised_profile_id,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class _Pages:
    def __init__(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.rows = rows

    def extract_pages(self, _path: Path) -> tuple[str, ...]:
        body = "".join(
            f"         {code}  {name}                    借{name}  ○ \n"
            for code, name in self.rows
        )
        return (
            "科        目        一         覧\n頁\n1\n"
            "令和 8年12月31日決算\n"
            "勘 定 科 目  略名称 使用 課区 税区 入力 固変 比率 説明\n"
            + body,
        )


class _SubPages:
    def __init__(self, subaccounts: tuple[tuple[str, str], ...]) -> None:
        self.subaccounts = subaccounts

    def extract_pages(self, _path: Path) -> tuple[str, ...]:
        subs = "".join(
            f"             -{code} {name}  貸\n"
            for code, name in self.subaccounts
        )
        return (
            "科        目        一         覧\n頁\n1\n"
            "令和 8年12月31日決算\n"
            "勘 定 科 目  略名称 使用 課区 税区 入力 固変 比率 説明\n"
            "         3181- 未払金                    貸未払金  ○ \n"
            + subs,
        )
class CompanyMasterRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profiles = ConversionProfileStore(self.root / "profiles")
        self.companies = CompanySettingStore(self.root / "companies", self.profiles)
        self.old_draft = self._draft("old", (("1001", "架空科目A"), ("1002", "架空科目B")))
        context_hash = hashlib.sha256(self.old_draft.read_bytes()).hexdigest()
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.profiles.create(
            ConversionProfile(
                profile_id="profile-1",
                profile_name="架空対応設定",
                source_format_identity=moneyforward_cloud_journal_export_observed_schema().identity,
                target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
                account_mappings={
                    "入力科目A": MappingValue(
                        "入力科目A", "架空科目A", MappingStatus.USER_CONFIRMED,
                        metadata={"target_code": "1001", "target_printed_name": "架空科目A", "setup_context_sha256": context_hash},
                    ),
                    "入力科目B": MappingValue(
                        "入力科目B", "架空科目B", MappingStatus.USER_CONFIRMED,
                        metadata={"target_code": "1002", "target_printed_name": "架空科目B", "setup_context_sha256": context_hash},
                    ),
                },
                created_at=now,
                updated_at=now,
            )
        )
        self.first = self.companies.create(
            company_setting_id="company-a", display_name="架空A",
            conversion_profile_id="profile-1", context_source=self.old_draft,
        )
        self.service = CompanyMasterRefreshService(self.companies, self.profiles)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_same_master_preserves_all_confirmed_mappings(self) -> None:
        new = self._draft("same", (("1001", "架空科目A"), ("1002", "架空科目B")))
        plan = self.service.plan("company-a", new)
        self.assertEqual(plan.reconfirmation_count, 0)
        self.assertTrue(plan.master_identity_unchanged)
        self.service.apply(plan, {}, set())
        refreshed = self.companies.get("company-a")
        self.assertEqual(refreshed.conversion_profile_id, "profile-1")
        refreshed_profile = self.profiles.get(refreshed.conversion_profile_id)
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED for m in refreshed_profile.account_mappings.values()))
        original_profile = self.profiles.get("profile-1")
        self.assertEqual(
            refreshed_profile.source_format_identity,
            original_profile.source_format_identity,
        )
        self.assertEqual(
            refreshed_profile.target_format_identity,
            original_profile.target_format_identity,
        )

    def test_changed_master_identity_is_not_treated_as_noop(self) -> None:
        changed = self._draft(
            "changed",
            (("1001", "架空科目A"), ("1002", "変更後科目")),
        )
        plan = self.service.plan("company-a", changed)
        self.assertFalse(plan.master_identity_unchanged)
        self.assertEqual(plan.reconfirmation_count, 1)

    def test_removed_code_changed_and_name_changed_require_confirmation(self) -> None:
        cases = (
            (("1001", "架空科目A"),),
            (("1999", "架空科目A"), ("1002", "架空科目B")),
            (("1001", "変更後科目"), ("1002", "架空科目B")),
        )
        for index, rows in enumerate(cases):
            with self.subTest(index=index):
                plan = self.service.plan("company-a", self._draft(f"changed-{index}", rows))
                self.assertGreaterEqual(plan.reconfirmation_count, 1)

    def test_refresh_is_company_scoped_and_does_not_modify_other_copy(self) -> None:
        self.companies.create(
            company_setting_id="company-b", display_name="架空B",
            conversion_profile_id="profile-1", context_source=self.old_draft,
        )
        second_before = self.companies.context_path(self.companies.get("company-b")).read_bytes()
        new = self._draft("new", (("1001", "架空科目A"), ("1002", "架空科目B")))
        plan = self.service.plan("company-a", new)
        self.service.apply(plan, {}, set())
        self.assertEqual(
            self.companies.context_path(self.companies.get("company-b")).read_bytes(),
            second_before,
        )
        self.assertEqual(
            self.companies.get("company-b").conversion_profile_id, "profile-1"
        )
        self.assertEqual(
            self.companies.resolve("company-b").status.value,
            "REQUIRES_CONFIRMATION",
        )

    def test_reconfirmation_must_select_an_exact_new_master_target(self) -> None:
        new = self._draft("replacement", (("1001", "架空科目A"), ("2002", "代替科目")))
        plan = self.service.plan("company-a", new)
        with self.assertRaises(ValueError):
            self.service.apply(plan, {"入力科目B": "存在しない科目"}, {"入力科目B"})
        self.service.apply(plan, {"入力科目B": "代替科目"}, {"入力科目B"})
        self.assertEqual(self.companies.resolve("company-a").status.value, "REQUIRES_CONFIRMATION")

    def test_repeated_revision_ids_remain_windows_path_safe(self) -> None:
        profile_id = "profile-1"
        for operation in ("update", "tax-context", "partner", "refresh") * 25:
            profile_id = revised_profile_id(profile_id, operation)
            self.assertLessEqual(
                len(profile_id), MAX_REVISION_PROFILE_ID_LENGTH
            )
            self.assertTrue(
                set(profile_id)
                <= set("abcdefghijklmnopqrstuvwxyz0123456789-")
            )

    def test_refresh_replaces_long_legacy_profile_id_with_bounded_id(self) -> None:
        legacy_id = "p" * 180
        old = self.profiles.get("profile-1")
        self.profiles.create(replace(old, profile_id=legacy_id))
        self.companies.replace_profile("company-a", legacy_id)

        new = self._draft(
            "long-id-refresh",
            (("1001", "架空科目A"), ("1002", "変更後科目")),
        )
        plan = self.service.plan("company-a", new)
        self.service.apply(
            plan,
            {"入力科目B": "変更後科目"},
            {"入力科目B"},
        )

        refreshed = self.companies.get("company-a")
        self.assertLessEqual(
            len(refreshed.conversion_profile_id),
            MAX_REVISION_PROFILE_ID_LENGTH,
        )
        self.assertEqual(
            self.companies.resolve("company-a").status.value,
            "REQUIRES_CONFIRMATION",
        )

    def test_preserve_subaccount_survives_unrelated_master_addition(self) -> None:
        self._replace_with_subaccount_profile(SubaccountPolicy.PRESERVE_SUBACCOUNT)
        new = self._sub_draft(
            "preserve-new",
            (("0001", "カード"), ("0002", "無関係追加")),
        )
        plan = self.service.plan("company-a", new)

        self.service.apply(plan, {}, set())

        profile = self.profiles.get(
            self.companies.get("company-a").conversion_profile_id
        )
        mapping = next(iter(profile.subaccount_context_mappings.values()))
        self.assertEqual(mapping.status, MappingStatus.USER_CONFIRMED)
        self.assertEqual(mapping.metadata["output_code"], "0001")

    def test_parent_only_is_not_silently_switched_when_subaccount_is_added(self) -> None:
        self._replace_with_subaccount_profile(SubaccountPolicy.PARENT_ONLY_CONFIRMED)
        new = self._sub_draft("parent-only-new", (("0001", "カード"),))
        plan = self.service.plan("company-a", new)

        self.service.apply(plan, {}, set())

        profile = self.profiles.get(
            self.companies.get("company-a").conversion_profile_id
        )
        mapping = next(iter(profile.subaccount_context_mappings.values()))
        self.assertEqual(mapping.status, MappingStatus.OBSOLETE)
        self.assertIsNone(mapping.target_value)
        self.assertEqual(
            mapping.metadata["subaccount_policy"],
            SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
        )

    def _replace_with_subaccount_profile(self, policy: SubaccountPolicy) -> None:
        old = self.profiles.get("profile-1")
        old_context = self._sub_draft(
            "sub-old",
            (("0001", "カード"),) if policy is SubaccountPolicy.PRESERVE_SUBACCOUNT else (),
        )
        context_hash = hashlib.sha256(old_context.read_bytes()).hexdigest()
        account = MappingValue(
            "未払金",
            "未払金",
            MappingStatus.USER_CONFIRMED,
            metadata={
                "target_code": "3181",
                "target_printed_name": "未払金",
                "setup_context_sha256": context_hash,
            },
        )
        target = "カード" if policy is SubaccountPolicy.PRESERVE_SUBACCOUNT else ""
        metadata = {
            "subaccount_policy": policy.value,
            "setup_context_sha256": context_hash,
        }
        if policy is SubaccountPolicy.PRESERVE_SUBACCOUNT:
            metadata.update(
                {"target_code": "0001", "output_code": "0001", "output_name": "カード"}
            )
        updated = replace(
            old,
            profile_id=f"profile-{policy.value.lower()}",
            account_mappings={"未払金": account},
            subaccount_context_mappings={
                MappingKey(MappingType.SUBACCOUNT, "入力元カード", "未払金"):
                    MappingValue(
                        "入力元カード",
                        target,
                        MappingStatus.USER_CONFIRMED,
                        parent_account="未払金",
                        metadata=metadata,
                    )
            },
        )
        self.profiles.create(updated)
        self.companies.replace_context(
            "company-a", old_context, conversion_profile_id=updated.profile_id
        )

    def _draft(self, name: str, rows: tuple[tuple[str, str], ...]) -> Path:
        pdf = self.root / f"{name}.pdf"
        pdf.write_bytes(name.encode("ascii"))
        path = self.root / f"{name}.json"
        JdlAccountPdfDraftStore(_Pages(rows)).import_pdf(pdf, path)
        return path

    def _sub_draft(self, name: str, rows: tuple[tuple[str, str], ...]) -> Path:
        pdf = self.root / f"{name}.pdf"
        pdf.write_bytes(name.encode("ascii"))
        path = self.root / f"{name}.json"
        JdlAccountPdfDraftStore(_SubPages(rows)).import_pdf(pdf, path)
        return path


if __name__ == "__main__":
    unittest.main()

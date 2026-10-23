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
from accounting_converter.domain.mapping import MappingStatus, MappingValue
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
        self.service.apply(plan, {}, set())
        refreshed = self.companies.get("company-a")
        self.assertNotEqual(refreshed.conversion_profile_id, "profile-1")
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
            (("1001", "架空科目A"), ("1002", "架空科目B")),
        )
        plan = self.service.plan("company-a", new)
        self.service.apply(plan, {}, set())

        refreshed = self.companies.get("company-a")
        self.assertLessEqual(
            len(refreshed.conversion_profile_id),
            MAX_REVISION_PROFILE_ID_LENGTH,
        )
        self.assertEqual(
            self.companies.resolve("company-a").status.value,
            "REQUIRES_CONFIRMATION",
        )

    def _draft(self, name: str, rows: tuple[tuple[str, str], ...]) -> Path:
        pdf = self.root / f"{name}.pdf"
        pdf.write_bytes(name.encode("ascii"))
        path = self.root / f"{name}.json"
        JdlAccountPdfDraftStore(_Pages(rows)).import_pdf(pdf, path)
        return path


if __name__ == "__main__":
    unittest.main()

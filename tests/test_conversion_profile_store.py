from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.profile_preflight import (
    ConversionPreflightService,
    ObservedMappingRequirements,
    ProfilePreflightStatus,
    mapping_rule_set_from_profile,
)
from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    FormatIdentityMatchStatus,
)
from accounting_converter.domain.format_metadata import EvidenceLevel, SemanticField
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.normalization import (
    NormalizationRule,
    NormalizationScope,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    ConversionProfileStoreError,
    DuplicateProfileError,
    ProfileNotFoundError,
    UnsupportedProfileVersionError,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_desktop_import_25_documented_schema,
    yayoi_next_documented_candidate_schema,
)
from tests.support.canonical_dataset import canonical_journal_entries


class ConversionProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = yayoi_desktop_import_25_documented_schema()
        self.target = jdl_ibex_cashbook_35_5_observed_schema_definition()

    def test_profile_create_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile()

            store.create(profile)
            loaded = store.get(profile.profile_id)

        self.assertEqual(loaded.profile_id, profile.profile_id)
        self.assertEqual(loaded.profile_name, "2026 test profile")
        self.assertEqual(
            loaded.account_mappings["現金"].status,
            MappingStatus.USER_CONFIRMED,
        )

    def test_profile_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile()
            store.create(profile)
            updated = ConversionProfile(
                **{
                    **profile.__dict__,
                    "profile_name": "updated profile",
                    "updated_at": datetime.now(timezone.utc),
                }
            )

            store.update(updated)

            self.assertEqual(store.get(profile.profile_id).profile_name, "updated profile")

    def test_profile_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile()
            store.create(profile)

            store.delete(profile.profile_id)

            with self.assertRaises(ProfileNotFoundError):
                store.get(profile.profile_id)

    def test_profile_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            store.create(self.profile("profile-a"))
            store.create(self.profile("profile-b"))

            profiles = store.list()

        self.assertEqual([profile.profile_id for profile in profiles], ["profile-a", "profile-b"])

    def test_duplicate_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile()
            store.create(profile)

            with self.assertRaises(DuplicateProfileError):
                store.create(profile)

    def test_malformed_json_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text("{malformed")

    def test_required_fields_are_validated(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        del payload["profile_name"]

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text(json.dumps(payload, ensure_ascii=False))

    def test_unsupported_schema_version_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        payload["schema_version"] = "999"

        with self.assertRaises(UnsupportedProfileVersionError):
            store.from_json_text(json.dumps(payload))

    def test_duplicate_mapping_in_json_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        payload["account_mappings"].append(payload["account_mappings"][0])

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text(json.dumps(payload, ensure_ascii=False))

    def test_invalid_format_identity_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        payload["source_format_identity"]["vendor"] = ""

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text(json.dumps(payload, ensure_ascii=False))

    def test_conflicting_mapping_in_json_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        duplicate = dict(payload["account_mappings"][0])
        duplicate["target_value"] = "別科目"
        payload["account_mappings"].append(duplicate)

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text(json.dumps(payload, ensure_ascii=False))

    def test_invalid_enum_is_rejected(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        payload = json.loads(store.to_json_text(self.profile()))
        payload["account_mappings"][0]["status"] = "CONFIRMED_BY_MAGIC"

        with self.assertRaises(ConversionProfileStoreError):
            store.from_json_text(json.dumps(payload, ensure_ascii=False))

    def test_atomic_save_failure_preserves_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile()
            store.create(profile)
            before = (Path(tmpdir) / f"{profile.profile_id}.json").read_text(
                encoding="utf-8"
            )
            updated = ConversionProfile(
                **{
                    **profile.__dict__,
                    "profile_name": "should not be written",
                }
            )

            with patch(
                "accounting_converter.infrastructure.conversion_profile_store.os.replace",
                side_effect=OSError("forced replace failure"),
            ):
                with self.assertRaises(OSError):
                    store.update(updated)

            after = (Path(tmpdir) / f"{profile.profile_id}.json").read_text(
                encoding="utf-8"
            )
        self.assertEqual(after, before)

    def test_import_duplicate_does_not_silently_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ConversionProfileStore(root / "profiles")
            export_store = ConversionProfileStore(root / "exports")
            profile = self.profile()
            store.create(profile)
            export_store.create(profile)
            exported = root / "exports" / f"{profile.profile_id}.json"

            with self.assertRaises(DuplicateProfileError):
                store.import_profile(exported)

    def test_profile_export_import_validates_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_store = ConversionProfileStore(root / "source")
            target_store = ConversionProfileStore(root / "target")
            profile = self.profile()
            source_store.create(profile)
            export_path = root / "exported_profile.json"

            source_store.export_profile(profile.profile_id, export_path)
            imported = target_store.import_profile(export_path)

        self.assertEqual(imported.profile_id, profile.profile_id)

    def test_accounting_transaction_data_is_not_serialized(self) -> None:
        entries = canonical_journal_entries()
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))

        text = store.to_json_text(self.profile())

        self.assertNotIn(entries[0].description or "", text)
        self.assertNotIn(entries[0].date.isoformat(), text)
        self.assertNotIn("1000", text)
        self.assertNotIn("journal body", text)

    def test_normalization_rule_round_trip(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        rule = NormalizationRule(
            rule_id="NORM-EXPLICIT-NFKC",
            target_field=SemanticField.DESCRIPTION,
            scope=NormalizationScope.SAFE_TEXT_NORMALIZATION,
            deterministic=True,
            reversible=False,
            requires_confirmation=False,
            evidence=EvidenceLevel.OFFICIAL_DOCUMENTED,
            description="Explicit configured text normalization.",
        )
        profile = self.profile(normalization_rules=(rule,))

        loaded = store.from_json_text(store.to_json_text(profile))

        self.assertEqual(loaded.normalization_rules[0], rule)

    def test_source_target_format_mismatch(self) -> None:
        profile = self.profile()
        next_schema = yayoi_next_documented_candidate_schema(27)

        status = profile.verify_format_identity(
            next_schema.identity,
            self.target.identity,
        )

        self.assertEqual(status, FormatIdentityMatchStatus.MISMATCH)

    def test_known_mapping_reuse_via_mapping_engine(self) -> None:
        entries = canonical_journal_entries()[:1]
        engine = MappingEngine(mapping_rule_set_from_profile(self.profile()))

        result = engine.apply(entries)

        self.assertEqual(result.unresolved_count, 0)
        self.assertEqual(result.entries[0].lines[0].account, "JDL現金")

    def test_unknown_mapping_blocks_preflight(self) -> None:
        result = ConversionPreflightService().check(
            source_format_candidate=self.source.identity,
            target_format_candidate=self.target.identity,
            saved_profile=self.profile(),
            observed_mapping_requirements=ObservedMappingRequirements(
                accounts=frozenset({"現金", "新しい架空科目"}),
            ),
        )

        self.assertEqual(result.status, ProfilePreflightStatus.REQUIRES_MAPPING)
        self.assertEqual(result.unknown_accounts, ("新しい架空科目",))

    def test_unsupported_profile_version_blocks_preflight(self) -> None:
        broken_profile = ConversionProfile(
            **{
                **self.profile().__dict__,
                "schema_version": "999",
            }
        )

        result = ConversionPreflightService().check(
            source_format_candidate=self.source.identity,
            target_format_candidate=self.target.identity,
            saved_profile=broken_profile,
            observed_mapping_requirements=ObservedMappingRequirements(),
        )

        self.assertEqual(result.status, ProfilePreflightStatus.UNSUPPORTED)

    def test_preflight_ready_with_matching_profile_and_known_mappings(self) -> None:
        result = ConversionPreflightService().check(
            source_format_candidate=self.source.identity,
            target_format_candidate=self.target.identity,
            saved_profile=self.profile(),
            observed_mapping_requirements=ObservedMappingRequirements(
                accounts=frozenset({"現金", "売上高"}),
            ),
        )

        self.assertEqual(result.status, ProfilePreflightStatus.READY)
        self.assertEqual(result.format_match_status, FormatIdentityMatchStatus.MATCH)

    def profile(
        self,
        profile_id: str = "profile-001",
        normalization_rules: tuple[NormalizationRule, ...] = (),
    ) -> ConversionProfile:
        return ConversionProfile(
            profile_id=profile_id,
            profile_name="2026 test profile",
            source_format_identity=self.source.identity,
            target_format_identity=self.target.identity,
            account_mappings={
                "現金": MappingValue("現金", "JDL現金", MappingStatus.USER_CONFIRMED),
                "売上高": MappingValue("売上高", "JDL売上高", MappingStatus.USER_CONFIRMED),
            },
            normalization_rules=normalization_rules,
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()

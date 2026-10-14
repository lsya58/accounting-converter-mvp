from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application.account_mapping_review import AccountMappingReviewService
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.profiles.known_formats import moneyforward_cloud_journal_export_observed_schema


@dataclass(frozen=True)
class CompanyMappingUpdateItem:
    key: str
    mapping_type: str
    source_value: str
    parent_account: str | None
    available_targets: tuple[str, ...]
    exact_candidate: str | None = None


@dataclass(frozen=True)
class CompanyMappingUpdateReview:
    company_setting_id: str
    source_path: Path
    context_path: Path
    items: tuple[CompanyMappingUpdateItem, ...]
    logical_journal_count: int


class CompanyMappingUpdateService:
    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.drafts = JdlAccountPdfDraftStore()

    def review(self, company_setting_id: str, source_path: Path) -> CompanyMappingUpdateReview:
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        context_path = self.company_store.context_path(setting)
        draft = self.drafts.load(context_path)
        entries = self._entries(source_path)
        accounts = AccountMappingReviewService().build(entries, draft.observation, profile)
        items: list[CompanyMappingUpdateItem] = []
        for item in accounts.items:
            if item.usable:
                continue
            items.append(
                CompanyMappingUpdateItem(
                    key=f"ACCOUNT|{item.requirement.source_value}",
                    mapping_type="ACCOUNT",
                    source_value=item.requirement.source_value,
                    parent_account=None,
                    available_targets=tuple(target.name for target in item.selectable_targets),
                    exact_candidate=(item.exact_candidate.name if item.exact_candidate else None),
                )
            )

        requirements = MappingRequirementExtractor().extract(entries, profile)
        targets, ambiguous = self._subaccount_targets(draft.observation.subaccounts)
        account_codes = {
            source: mapping.metadata.get("target_code", "")
            for source, mapping in profile.account_mappings.items()
            if mapping.status is MappingStatus.USER_CONFIRMED
        }
        for requirement in requirements.subaccounts:
            parent_code = account_codes.get(requirement.parent_account or "", "")
            candidates = tuple(
                item for item in targets.get(parent_code, ())
                if (item.parent_account_code, item.code, item.name) not in ambiguous
            )
            mapping = profile.subaccount_context_mappings.get(requirement.key)
            usable = bool(
                mapping
                and mapping.status is MappingStatus.USER_CONFIRMED
                and len(tuple(
                    item for item in candidates
                    if item.code == mapping.metadata.get("target_code")
                    and item.name == (mapping.metadata.get("output_name") or mapping.target_value)
                )) == 1
            )
            if usable:
                continue
            exact = tuple(item for item in candidates if item.name == requirement.source_value)
            items.append(
                CompanyMappingUpdateItem(
                    key=requirement.key.stable_key,
                    mapping_type="SUBACCOUNT",
                    source_value=requirement.source_value,
                    parent_account=requirement.parent_account,
                    available_targets=tuple(item.name for item in candidates),
                    exact_candidate=exact[0].name if len(exact) == 1 else None,
                )
            )
        return CompanyMappingUpdateReview(company_setting_id, source_path, context_path, tuple(items), len(entries))

    def apply(self, review: CompanyMappingUpdateReview, selections: Mapping[str, str], confirmed: set[str]) -> None:
        required = {item.key for item in review.items}
        if set(selections) != required or confirmed != required:
            raise ValueError("すべての追加対応を明示的に確認してください。")
        setting = self.company_store.get(review.company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        draft = self.drafts.load(review.context_path)
        context_hash = hashlib.sha256(review.context_path.read_bytes()).hexdigest()
        account_targets = defaultdict(list)
        for item in draft.observation.printed_accounts:
            if item.enabled:
                account_targets[item.name].append(item)
        sub_targets, ambiguous = self._subaccount_targets(draft.observation.subaccounts)
        accounts = dict(old.account_mappings)
        subs = dict(old.subaccount_context_mappings)
        for item in review.items:
            selected = selections[item.key]
            if item.mapping_type == "ACCOUNT":
                matches = account_targets.get(selected, ())
                if len(matches) != 1:
                    raise ValueError("JDL科目を一意に確認できません。")
                target = matches[0]
                accounts[item.source_value] = MappingValue(
                    item.source_value, target.name, MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": target.code, "target_printed_name": target.name, "target_abbreviation": target.abbreviation, "setup_context_sha256": context_hash},
                )
            else:
                parent = accounts.get(item.parent_account or "")
                parent_code = parent.metadata.get("target_code", "") if parent else ""
                matches = tuple(
                    target for target in sub_targets.get(parent_code, ())
                    if target.name == selected
                    and (target.parent_account_code, target.code, target.name) not in ambiguous
                )
                if len(matches) != 1:
                    raise ValueError("親科目に対応するJDL補助科目を確認できません。")
                target = matches[0]
                key = MappingKey(MappingType.SUBACCOUNT, item.source_value, item.parent_account)
                subs[key] = MappingValue(
                    item.source_value, target.name, MappingStatus.USER_CONFIRMED,
                    parent_account=item.parent_account,
                    metadata={"target_code": target.code, "output_name": target.name, "setup_context_sha256": context_hash},
                )
        accounts = {
            key: replace(value, metadata={**value.metadata, "setup_context_sha256": context_hash})
            for key, value in accounts.items()
        }
        updated = replace(old, profile_id=f"{old.profile_id}-update-{uuid.uuid4().hex}", account_mappings=accounts, subaccount_context_mappings=subs, updated_at=datetime.now(timezone.utc))
        self.profile_store.create(updated)
        try:
            self.company_store.replace_context(review.company_setting_id, review.context_path, conversion_profile_id=updated.profile_id)
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise

    @staticmethod
    def _subaccount_targets(subaccounts):
        by_parent = defaultdict(list)
        code_names = defaultdict(set)
        name_codes = defaultdict(set)
        identities = Counter()
        for item in subaccounts:
            by_parent[item.parent_account_code].append(item)
            code_names[(item.parent_account_code, item.code)].add(item.name)
            name_codes[(item.parent_account_code, item.name)].add(item.code)
            identities[(item.parent_account_code, item.code, item.name)] += 1
        ambiguous = {
            (item.parent_account_code, item.code, item.name)
            for item in subaccounts
            if len(code_names[(item.parent_account_code, item.code)]) > 1
            or len(name_codes[(item.parent_account_code, item.name)]) > 1
            or identities[(item.parent_account_code, item.code, item.name)] > 1
        }
        return by_parent, ambiguous

    @staticmethod
    def _entries(path: Path):
        schema = moneyforward_cloud_journal_export_observed_schema()
        profile = FormatProfile("Money Forward", "Money Forward クラウド会計", "UNKNOWN", schema.identity.stable_key, "cp932")
        return tuple(MoneyForwardInputAdapter().read(path, profile))

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.application.moneyforward_trade_partner import (
    upgrade_trade_partner_policy,
)
from accounting_converter.application.jdl_master_identity import (
    observed_master_identity_sha256,
)
from accounting_converter.application.jdl_master_diff import JdlMasterDiff, compare_jdl_masters
from accounting_converter.application.jdl_master_observation import (
    JdlMasterObservation,
    JdlObservedSubaccount,
    JdlPrintedAccount,
)
from accounting_converter.domain.conversion_profile import (
    ConversionProfile, TRADE_PARTNER_LOSS_POLICY_KEY,
)
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.infrastructure.jdl_account_pdf_draft import (
    JdlAccountPdfDraftStore,
)


@dataclass(frozen=True)
class AccountMasterRefreshItem:
    source_value: str
    current_target: str | None
    available_targets: tuple[str, ...]
    preserved: bool


@dataclass(frozen=True)
class AccountMasterRefreshPlan:
    company_setting_id: str
    new_context_path: Path
    new_context_sha256: str
    items: tuple[AccountMasterRefreshItem, ...]
    master_identity_unchanged: bool = False
    master_diff: JdlMasterDiff = JdlMasterDiff(())

    @property
    def reconfirmation_count(self) -> int:
        return sum(not item.preserved for item in self.items)


class CompanyMasterRefreshService:
    """Plans an exact-identity refresh without silently migrating mappings."""

    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.drafts = JdlAccountPdfDraftStore()

    def plan(self, company_setting_id: str, new_context_path: Path) -> AccountMasterRefreshPlan:
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        draft = self.drafts.load(new_context_path)
        old_observation = self._current_observation(setting)
        targets = tuple(item for item in draft.observation.printed_accounts if item.enabled)
        by_identity = {(item.code, item.name) for item in targets}
        available = tuple(item.name for item in sorted(targets, key=lambda item: (item.code, item.name)))
        items = []
        for source, mapping in sorted(profile.account_mappings.items()):
            code = mapping.metadata.get("target_code", "")
            name = (
                mapping.metadata.get("target_printed_name")
                or mapping.metadata.get("target_formal_name")
                or mapping.target_value
                or ""
            )
            preserved = (
                mapping.status is MappingStatus.USER_CONFIRMED
                and (code, name) in by_identity
                and sum(item.name == name for item in targets) == 1
            )
            items.append(AccountMasterRefreshItem(source, mapping.target_value, available, preserved))
        return AccountMasterRefreshPlan(
            company_setting_id=company_setting_id,
            new_context_path=new_context_path,
            new_context_sha256=hashlib.sha256(new_context_path.read_bytes()).hexdigest(),
            items=tuple(items),
            master_identity_unchanged=(
                self.company_store.target_master_identity_sha256(company_setting_id)
                == observed_master_identity_sha256(draft.observation)
            ),
            master_diff=compare_jdl_masters(
                old_observation, draft.observation
            ),
        )

    def _current_observation(self, setting) -> JdlMasterObservation:
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            return self.drafts.load(path).observation
        accounts, subaccounts, _excluded = self.company_store.target_master_inventory(
            setting.company_setting_id
        )
        return JdlMasterObservation(
            accounts=tuple(accounts),
            subaccounts=tuple(
                JdlObservedSubaccount(
                    item.parent_account_code,
                    item.parent_account,
                    item.output_code,
                    item.output_name or item.target_name,
                )
                for item in subaccounts
            ),
            departments=(),
            sources=(),
            printed_accounts=tuple(
                JdlPrintedAccount(
                    item.target_master_code,
                    item.target_name,
                    item.target_name,
                    "",
                    True,
                )
                for item in accounts
            ),
        )

    def apply(
        self,
        plan: AccountMasterRefreshPlan,
        selections: Mapping[str, str],
        explicitly_confirmed: set[str],
    ) -> int:
        if plan.master_identity_unchanged:
            return 0
        setting = self.company_store.get(plan.company_setting_id)
        old_profile = self.profile_store.get(setting.conversion_profile_id)
        draft = self.drafts.load(plan.new_context_path)
        targets = tuple(item for item in draft.observation.printed_accounts if item.enabled)
        by_name = {}
        for target in targets:
            by_name.setdefault(target.name, []).append(target)
        required = {item.source_value for item in plan.items if not item.preserved}
        if set(selections) != required or explicitly_confirmed != required:
            raise ValueError("再確認が必要な科目対応をすべて確認してください。")
        if any(len(by_name.get(value, ())) != 1 for value in selections.values()):
            raise ValueError("新しいJDL科目一覧で対象科目を一意に確認できません。")

        mappings = dict(old_profile.account_mappings)
        for item in plan.items:
            previous = mappings[item.source_value]
            target_name = previous.target_value if item.preserved else selections[item.source_value]
            target = by_name[target_name][0]
            mappings[item.source_value] = MappingValue(
                source_value=item.source_value,
                target_value=target.name,
                status=MappingStatus.USER_CONFIRMED,
                metadata={
                    **previous.metadata,
                    "target_code": target.code,
                    "target_printed_name": target.name,
                    "target_abbreviation": target.abbreviation,
                    "setup_context_sha256": plan.new_context_sha256,
                },
            )
        subaccount_mappings: dict[MappingKey, MappingValue] = {}
        for key, previous in old_profile.subaccount_context_mappings.items():
            parent_mapping = mappings.get(key.parent_account or "")
            parent_code = (
                parent_mapping.metadata.get("target_code", "")
                if parent_mapping is not None
                else ""
            )
            target_code = previous.metadata.get("target_code", "")
            target_name = (
                previous.metadata.get("output_name")
                or previous.target_value
                or ""
            )
            matches = tuple(
                item
                for item in draft.observation.subaccounts
                if item.parent_account_code == parent_code
                and item.code == target_code
                and item.name == target_name
            )
            parent_only = (
                previous.metadata.get("subaccount_policy")
                == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value
            )
            parent_subaccounts = tuple(
                item
                for item in draft.observation.subaccounts
                if item.parent_account_code == parent_code
            )
            safely_preserved = (
                previous.status is MappingStatus.USER_CONFIRMED
                and (
                    (parent_only and not parent_subaccounts)
                    or (not parent_only and len(matches) == 1)
                )
            )
            if safely_preserved:
                subaccount_mappings[key] = MappingValue(
                    source_value=previous.source_value,
                    target_value=previous.target_value,
                    status=MappingStatus.USER_CONFIRMED,
                    parent_account=previous.parent_account,
                    metadata={
                        **previous.metadata,
                        "setup_context_sha256": plan.new_context_sha256,
                    },
                )
            else:
                subaccount_mappings[key] = MappingValue(
                    source_value=previous.source_value,
                    target_value=None,
                    status=MappingStatus.OBSOLETE,
                    parent_account=previous.parent_account,
                    metadata={**previous.metadata, "refresh_reconfirmation_required": "true"},
                )
        loss_policies = dict(old_profile.loss_policy_mappings)
        policy = loss_policies.get(TRADE_PARTNER_LOSS_POLICY_KEY)
        if policy is not None and policy.status is MappingStatus.USER_CONFIRMED:
            old_path = self.company_store.context_path(setting)
            if not self.drafts.is_draft(old_path):
                old_context = JdlTargetContextLoader().load(old_path)
                loss_policies[TRADE_PARTNER_LOSS_POLICY_KEY] = (
                    upgrade_trade_partner_policy(
                        policy,
                        old_context,
                        replace(old_context, product=draft.product, version=draft.version),
                    )
                )
        updated = replace(
            old_profile,
            profile_id=revised_profile_id(old_profile.profile_id, "refresh"),
            account_mappings=mappings,
            subaccount_context_mappings=subaccount_mappings,
            loss_policy_mappings=loss_policies,
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_context(
                plan.company_setting_id,
                plan.new_context_path,
                conversion_profile_id=updated.profile_id,
            )
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise
        return len(required)

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
from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservation,
    JdlObservedSubaccount,
    JdlPrintedAccount,
)
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.journal import Side
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.known_formats import moneyforward_cloud_journal_export_observed_schema


@dataclass(frozen=True)
class CompanyMappingUpdateItem:
    key: str
    mapping_type: str
    source_value: str
    parent_account: str | None
    available_targets: tuple[str, ...]
    exact_candidate: str | None = None
    parent_only_available: bool = False


PARENT_ONLY_SELECTION = "__PARENT_ONLY_CONFIRMED__"


@dataclass(frozen=True)
class CompanyMappingUpdateReview:
    company_setting_id: str
    source_path: Path | None
    context_path: Path
    items: tuple[CompanyMappingUpdateItem, ...]
    logical_journal_count: int
    tax_categories: tuple[str, ...] = ()
    unsupported_shape_count: int = 0
    optional_field_blocker_count: int = 0


class CompanyMappingUpdateService:
    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.drafts = JdlAccountPdfDraftStore()
        self.contexts = JdlTargetContextLoader()

    def review(
        self,
        company_setting_id: str,
        source_path: Path,
        *,
        include_confirmed: bool = False,
    ) -> CompanyMappingUpdateReview:
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        context_path = self.company_store.context_path(setting)
        master = self._master_observation(context_path)
        entries = self._entries(source_path)
        accounts = AccountMappingReviewService().build(entries, master, profile)
        items: list[CompanyMappingUpdateItem] = []
        for item in accounts.items:
            if item.usable and not include_confirmed:
                continue
            current = profile.account_mappings.get(item.requirement.source_value)
            items.append(
                CompanyMappingUpdateItem(
                    key=f"ACCOUNT|{item.requirement.source_value}",
                    mapping_type="ACCOUNT",
                    source_value=item.requirement.source_value,
                    parent_account=None,
                    available_targets=tuple(target.name for target in item.selectable_targets),
                    exact_candidate=(
                        current.target_value
                        if item.usable and current is not None
                        else item.exact_candidate.name
                        if item.exact_candidate
                        else None
                    ),
                )
            )

        requirements = MappingRequirementExtractor().extract(entries, profile)
        targets, ambiguous = self._subaccount_targets(master.subaccounts)
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
            parent_only = bool(
                mapping
                and mapping.status is MappingStatus.USER_CONFIRMED
                and mapping.metadata.get("subaccount_policy")
                == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value
                and mapping.target_value == ""
                and not candidates
            )
            preserve = bool(
                mapping
                and mapping.status is MappingStatus.USER_CONFIRMED
                and mapping.metadata.get(
                    "subaccount_policy",
                    SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                ) == SubaccountPolicy.PRESERVE_SUBACCOUNT.value
                and len(tuple(
                    item for item in candidates
                    if item.code == mapping.metadata.get("target_code")
                    and item.name == (mapping.metadata.get("output_name") or mapping.target_value)
                )) == 1
            )
            usable = parent_only or preserve
            if usable and not include_confirmed:
                continue
            exact = tuple(item for item in candidates if item.name == requirement.source_value)
            items.append(
                CompanyMappingUpdateItem(
                    key=requirement.key.stable_key,
                    mapping_type="SUBACCOUNT",
                    source_value=requirement.source_value,
                    parent_account=requirement.parent_account,
                    available_targets=tuple(item.name for item in candidates),
                    exact_candidate=(
                        PARENT_ONLY_SELECTION
                        if parent_only
                        else mapping.target_value
                        if preserve and mapping is not None
                        else exact[0].name if len(exact) == 1 else None
                    ),
                    parent_only_available=bool(parent_code) and not candidates,
                )
            )
        verified_shapes = {(1, 1), (1, 3), (2, 1), (2, 2), (2, 3), (4, 6), (5, 7), (5, 8)}
        unsupported_shape_count = sum(
            (
                sum(line.side is Side.DEBIT for line in entry.lines),
                sum(line.side is Side.CREDIT for line in entry.lines),
            )
            not in verified_shapes
            for entry in entries
        )
        loss_results = ValidationPipeline((MoneyForwardToJdlLossRule(),)).validate(
            entries
        )
        return CompanyMappingUpdateReview(
            company_setting_id,
            source_path,
            context_path,
            tuple(items),
            len(entries),
            tuple(
                item.source_value
                for item in requirements.tax_categories
                if item.requires_confirmation
            ),
            unsupported_shape_count,
            len({item.journal_id for item in loss_results if item.journal_id}),
        )

    def review_saved(self, company_setting_id: str) -> CompanyMappingUpdateReview:
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        context_path = self.company_store.context_path(setting)
        master = self._master_observation(context_path)
        account_targets = tuple(
            item.name for item in master.printed_accounts if item.enabled
        )
        sub_targets, ambiguous = self._subaccount_targets(
            master.subaccounts
        )
        items: list[CompanyMappingUpdateItem] = []
        for source_value, mapping in sorted(profile.account_mappings.items()):
            items.append(
                CompanyMappingUpdateItem(
                    key=f"ACCOUNT|{source_value}",
                    mapping_type="ACCOUNT",
                    source_value=source_value,
                    parent_account=None,
                    available_targets=account_targets,
                    exact_candidate=(
                        mapping.target_value
                        if mapping.target_value in account_targets
                        else None
                    ),
                )
            )
        account_codes = {
            source: mapping.metadata.get("target_code", "")
            for source, mapping in profile.account_mappings.items()
            if mapping.status is MappingStatus.USER_CONFIRMED
        }
        for key, mapping in sorted(
            profile.subaccount_context_mappings.items(),
            key=lambda item: item[0].stable_key,
        ):
            parent_code = account_codes.get(key.parent_account or "", "")
            candidates = tuple(
                item
                for item in sub_targets.get(parent_code, ())
                if (item.parent_account_code, item.code, item.name) not in ambiguous
            )
            names = tuple(item.name for item in candidates)
            parent_only = bool(
                mapping.status is MappingStatus.USER_CONFIRMED
                and mapping.metadata.get("subaccount_policy")
                == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value
                and mapping.target_value == ""
                and not candidates
            )
            items.append(
                CompanyMappingUpdateItem(
                    key=key.stable_key,
                    mapping_type="SUBACCOUNT",
                    source_value=key.source_value,
                    parent_account=key.parent_account,
                    available_targets=names,
                    exact_candidate=(
                        PARENT_ONLY_SELECTION
                        if parent_only
                        else mapping.target_value
                        if mapping.target_value in names
                        else None
                    ),
                    parent_only_available=bool(parent_code) and not candidates,
                )
            )
        return CompanyMappingUpdateReview(
            company_setting_id, context_path=context_path, source_path=None,
            items=tuple(items), logical_journal_count=0,
        )

    def apply(self, review: CompanyMappingUpdateReview, selections: Mapping[str, str], confirmed: set[str]) -> None:
        required = {item.key for item in review.items}
        if set(selections) != required or confirmed != required:
            raise ValueError("すべての追加対応を明示的に確認してください。")
        setting = self.company_store.get(review.company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        master = self._master_observation(review.context_path)
        requirements = (
            MappingRequirementExtractor().extract(
                self._entries(review.source_path), old
            )
            if review.source_path is not None
            else None
        )
        context_hash = hashlib.sha256(review.context_path.read_bytes()).hexdigest()
        runtime_context = (
            None
            if self.drafts.is_draft(review.context_path)
            else self.contexts.load(review.context_path)
        )
        account_targets = defaultdict(list)
        for item in master.printed_accounts:
            if item.enabled:
                account_targets[item.name].append(item)
        sub_targets, ambiguous = self._subaccount_targets(master.subaccounts)
        accounts = dict(old.account_mappings)
        subs = dict(old.subaccount_context_mappings)
        tax_mappings = dict(old.tax_mappings)
        for item in review.items:
            selected = selections[item.key]
            if item.mapping_type == "ACCOUNT":
                matches = account_targets.get(selected, ())
                if len(matches) != 1:
                    raise ValueError("JDL科目を一意に確認できません。")
                target = matches[0]
                identity = next(
                    (
                        candidate
                        for candidate in runtime_context.account_master
                        if candidate.mapping_value == target.name
                    ),
                    None,
                ) if runtime_context is not None else None
                accounts[item.source_value] = MappingValue(
                    item.source_value, target.name, MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": (
                            identity.target_master_code if identity else target.code
                        ),
                        "target_printed_name": target.name,
                        "target_abbreviation": target.abbreviation,
                        "target_formal_name": (
                            identity.target_formal_name if identity else target.name
                        ),
                        "setup_context_sha256": context_hash,
                    },
                )
            else:
                parent = accounts.get(item.parent_account or "")
                parent_code = parent.metadata.get("target_code", "") if parent else ""
                if selected == PARENT_ONLY_SELECTION:
                    if parent is None or not parent.is_resolved or not parent_code:
                        raise ValueError("親科目の対応を先に確認してください。")
                    if tuple(sub_targets.get(parent_code, ())):
                        raise ValueError(
                            "JDL側で補助科目が設定されているため、親科目のみにはできません。"
                        )
                    key = MappingKey(
                        MappingType.SUBACCOUNT,
                        item.source_value,
                        item.parent_account,
                    )
                    subs[key] = MappingValue(
                        item.source_value,
                        "",
                        MappingStatus.USER_CONFIRMED,
                        parent_account=item.parent_account,
                        metadata={
                            "subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                            "setup_context_sha256": context_hash,
                        },
                    )
                    continue
                matches = tuple(
                    target for target in sub_targets.get(parent_code, ())
                    if target.name == selected
                    and (target.parent_account_code, target.code, target.name) not in ambiguous
                )
                if len(matches) != 1:
                    raise ValueError("親科目に対応するJDL補助科目を確認できません。")
                target = matches[0]
                identity = next(
                    (
                        candidate
                        for candidate in runtime_context.subaccounts
                        if candidate.parent_account_code == parent_code
                        and (candidate.output_name or candidate.mapping_value)
                        == target.name
                    ),
                    None,
                ) if runtime_context is not None else None
                key = MappingKey(MappingType.SUBACCOUNT, item.source_value, item.parent_account)
                subs[key] = MappingValue(
                    item.source_value, target.name, MappingStatus.USER_CONFIRMED,
                    parent_account=item.parent_account,
                    metadata={
                        "target_code": (
                            identity.target_master_code if identity else target.code
                        ),
                        "output_code": identity.output_code if identity else target.code,
                        "output_name": target.name,
                        "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                        "setup_context_sha256": context_hash,
                    },
                )
        if requirements is not None:
            for requirement in requirements.tax_categories:
                tax_mappings.setdefault(
                    requirement.source_value,
                    MappingValue(
                        requirement.source_value,
                        None,
                        MappingStatus.UNRESOLVED,
                    ),
                )
        accounts = {
            key: replace(value, metadata={**value.metadata, "setup_context_sha256": context_hash})
            for key, value in accounts.items()
        }
        updated = replace(
            old,
            account_mappings=accounts,
            subaccount_context_mappings=subs,
            tax_mappings=tax_mappings,
            updated_at=datetime.now(timezone.utc),
        )
        self._persist_profile(review, old, updated)

    def ensure_tax_requirements(self, review: CompanyMappingUpdateReview) -> None:
        """Persist observed tax requirements without confirming or mapping them."""
        if not review.tax_categories:
            return
        setting = self.company_store.get(review.company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        tax_mappings = dict(old.tax_mappings)
        changed = False
        for source_value in review.tax_categories:
            if source_value not in tax_mappings:
                tax_mappings[source_value] = MappingValue(
                    source_value, None, MappingStatus.UNRESOLVED
                )
                changed = True
        if not changed:
            return
        updated = replace(
            old,
            tax_mappings=tax_mappings,
            updated_at=datetime.now(timezone.utc),
        )
        self._persist_profile(review, old, updated)

    def _persist_profile(
        self,
        review: CompanyMappingUpdateReview,
        old,
        updated,
    ) -> None:
        updated = replace(
            updated,
            profile_id=f"{old.profile_id}-update-{uuid.uuid4().hex}",
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_profile(
                review.company_setting_id, updated.profile_id
            )
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise

    def _master_observation(self, context_path: Path) -> JdlMasterObservation:
        if self.drafts.is_draft(context_path):
            return self.drafts.load(context_path).observation
        context = self.contexts.load(context_path)
        return JdlMasterObservation(
            accounts=context.account_master,
            subaccounts=tuple(
                JdlObservedSubaccount(
                    parent_account_code=item.parent_account_code,
                    parent_account_name=item.parent_account,
                    code=item.output_code or item.target_master_code,
                    name=item.output_name or item.mapping_value,
                    evidence_scope="TARGET_CONTEXT_CONFIRMED",
                )
                for item in context.subaccounts
            ),
            departments=(),
            sources=(),
            completeness=JdlMasterCompleteness.OBSERVED_USED_MASTER,
            printed_accounts=tuple(
                JdlPrintedAccount(
                    code=item.target_master_code,
                    name=item.mapping_value,
                    abbreviation=item.target_name,
                    normal_balance="",
                    enabled=True,
                    has_observed_setting_values=True,
                )
                for item in context.account_master
            ),
        )

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

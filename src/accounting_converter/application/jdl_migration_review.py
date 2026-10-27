from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from accounting_converter.adapters.input.jdl import (
    JdlMigrationParser,
    jdl_source_account_key,
    jdl_source_subaccount_key,
    jdl_source_tax_key,
)
from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.application.description_replacement import (
    description_sha256,
)
from accounting_converter.application.company_settings import CompanySettingStatus
from accounting_converter.application.jdl_migration_tax_evidence import (
    evidence_for_target_context,
    evidence_for_source_tax_key,
    target_master_inventory_dependencies_match,
    target_master_dependency_mismatches,
    tax_context_identity_sha256,
)
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)


class JdlMigrationReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        # Keep the stable code in local diagnostics while showing only the
        # human-facing message in the dialog.
        super().__init__(f"{code}: {message}")
        self.code = code
        self.user_message = message


@dataclass(frozen=True)
class JdlMigrationAccountReview:
    key: str
    source_code: str
    source_name: str
    classification: str
    recommended_targets: tuple[tuple[str, str], ...]
    targets: tuple[tuple[str, str], ...]
    affected_journal_count: int
    disabled_name_match: bool


@dataclass(frozen=True)
class JdlMigrationSubaccountReview:
    key: str
    parent_code: str
    parent_name: str
    source_code: str
    source_name: str
    targets: tuple[tuple[str, str], ...]
    affected_journal_count: int
    target_parent_exact: bool


@dataclass(frozen=True)
class JdlMigrationTaxReview:
    label: str
    row_count: int
    status: str
    evidence_status: str
    evidence_id: str
    dependency_detail: str = ""
    source_key: str = ""


@dataclass(frozen=True)
class JdlMigrationDescriptionReview:
    journal_identifier: str
    current_length: int
    row_key: str = ""
    current_description: str = ""
    original_description_sha256: str = ""


@dataclass(frozen=True)
class JdlMigrationHumanReview:
    company_setting_id: str
    accounts: tuple[JdlMigrationAccountReview, ...]
    subaccounts: tuple[JdlMigrationSubaccountReview, ...]
    taxes: tuple[JdlMigrationTaxReview, ...]
    descriptions: tuple[JdlMigrationDescriptionReview, ...]
    target_context_fields: tuple[str, ...]
    source_path: Path
    source_sha256: str
    target_master_identity_sha256: str
    source_format_key: str
    target_format_key: str
    reused_account_count: int = 0
    reused_subaccount_count: int = 0
    reused_tax_count: int = 0
    derived_state: bool = False


def jdl_description_replacement_key(entry_id: str, row_index: int) -> str:
    return f"jdl_description_replacement|{entry_id}|row-{row_index}"


class JdlMigrationHumanReviewService:
    """Loads a private review pack and persists only explicit Human decisions."""

    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store

    def derive(
        self, company_setting_id: str, source_path: Path
    ) -> JdlMigrationHumanReview:
        setting, profile = self._validated_setting(company_setting_id)
        try:
            parsed = JdlMigrationParser().parse_path(source_path)
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except Exception as exc:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-SOURCE-INVALID",
                "選択中のJDL仕訳ファイルを安全に解析できません。",
            ) from exc
        target_accounts, target_subaccounts, disabled_names = (
            self.company_store.target_master_inventory(company_setting_id)
        )
        all_targets = tuple(sorted(
            (
                (item.target_master_code, item.target_formal_name)
                for item in target_accounts
            ),
            key=lambda item: (item[0], item[1]),
        ))
        by_code = {code: name for code, name in all_targets}
        by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for identity in all_targets:
            by_name[identity[1]].append(identity)

        source_accounts: dict[tuple[str, str], None] = {}
        source_subaccounts: dict[tuple[str, str, str, str], None] = {}
        account_journals: dict[tuple[str, str], set[str]] = defaultdict(set)
        subaccount_journals: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
        tax_counts: Counter[tuple[str, str, str]] = Counter()
        overflow: list[JdlMigrationDescriptionReview] = []
        for entry in parsed.entries:
            for row_index, row in enumerate(entry.metadata.get("physical_rows", ()), 1):
                length = len(str(row.get("description", "")))
                if length > 32:
                    description = str(row.get("description", ""))
                    row_key = jdl_description_replacement_key(entry.id, row_index)
                    saved_replacement = profile.loss_policy_mappings.get(row_key)
                    original_sha256 = description_sha256(description)
                    if (
                        saved_replacement is not None
                        and saved_replacement.status is MappingStatus.USER_CONFIRMED
                        and saved_replacement.metadata.get("source_sha256")
                        == source_sha256
                        and saved_replacement.metadata.get(
                            "original_description_sha256"
                        ) == original_sha256
                        and saved_replacement.target_value
                        and 1 <= len(saved_replacement.target_value) <= 32
                    ):
                        continue
                    overflow.append(JdlMigrationDescriptionReview(
                        f"{entry.id}:row-{row_index}",
                        length,
                        row_key,
                        description,
                        original_sha256,
                    ))
            for line in entry.lines:
                metadata = line.metadata
                code = str(metadata.get("jdl_source_account_code", ""))
                name = str(metadata.get("jdl_source_account_formal_name", "")) or str(
                    metadata.get("jdl_source_account_name", "")
                )
                identity = (code, name)
                source_accounts[identity] = None
                account_journals[identity].add(entry.id)
                sub_code = str(metadata.get("jdl_source_subaccount_code", ""))
                sub_name = str(metadata.get("jdl_source_subaccount_name", ""))
                if sub_code or sub_name:
                    sub_identity = (code, name, sub_code, sub_name)
                    source_subaccounts[sub_identity] = None
                    subaccount_journals[sub_identity].add(entry.id)
                if line.tax_info is not None:
                    tax_counts[(
                        str(line.tax_info.metadata.get("jdl_tax_scope", "")),
                        str(line.tax_info.metadata.get("jdl_tax_category", "")),
                        str(line.tax_info.metadata.get("jdl_tax_input_method", "")),
                    )] += 1

        accounts: list[JdlMigrationAccountReview] = []
        reused_accounts = 0
        for (code, name) in sorted(source_accounts):
            source_key = jdl_source_account_key(code, name)
            exact = by_code.get(code) == name
            saved = profile.account_mappings.get(source_key)
            saved_identity = (
                str(saved.metadata.get("target_code", "")),
                str(saved.metadata.get("target_printed_name", ""))
                or str(saved.metadata.get("target_formal_name", ""))
                or str(saved.target_value or ""),
            ) if saved is not None else None
            if exact or (
                saved is not None
                and saved.status is MappingStatus.USER_CONFIRMED
                and saved_identity in all_targets
            ):
                reused_accounts += 1
                continue
            if code in by_code:
                classification = "SAME_CODE_NAME_CHANGED"
                recommended = ((code, by_code[code]),)
            elif len(by_name.get(name, ())) == 1:
                classification = "SAME_NAME_CODE_CHANGED"
                recommended = tuple(by_name[name])
            elif by_name.get(name):
                classification = "AMBIGUOUS"
                recommended = tuple(by_name[name])
            else:
                classification = "NONE"
                recommended = ()
            accounts.append(JdlMigrationAccountReview(
                source_key, code, name, classification, recommended, all_targets,
                len(account_journals[(code, name)]), name in disabled_names,
            ))

        target_subs_by_parent: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for item in target_subaccounts:
            target_subs_by_parent[item.parent_account_code].append(
                (item.target_master_code, item.target_name or item.output_name)
            )
        subaccounts: list[JdlMigrationSubaccountReview] = []
        reused_subaccounts = 0
        for code, name, sub_code, sub_name in sorted(source_subaccounts):
            parent_key = jdl_source_account_key(code, name)
            parent_mapping = profile.account_mappings.get(parent_key)
            target_parent_code = code if by_code.get(code) == name else ""
            if (
                not target_parent_code
                and parent_mapping is not None
                and parent_mapping.status is MappingStatus.USER_CONFIRMED
            ):
                target_parent_code = str(parent_mapping.metadata.get("target_code", ""))
            targets = tuple(sorted(target_subs_by_parent.get(target_parent_code, ())))
            source_sub_key = jdl_source_subaccount_key(sub_code, sub_name)
            mapping_key = MappingKey(MappingType.SUBACCOUNT, source_sub_key, parent_key)
            saved = profile.subaccount_context_mappings.get(mapping_key)
            policy = str(saved.metadata.get("subaccount_policy", "")) if saved else ""
            saved_target = (
                str(saved.metadata.get("target_code", "")),
                str(saved.metadata.get("output_name", "")) or str(saved.target_value or ""),
            ) if saved else None
            reusable = saved is not None and saved.status is MappingStatus.USER_CONFIRMED and (
                (policy == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value and not targets)
                or (policy != SubaccountPolicy.PARENT_ONLY_CONFIRMED.value and saved_target in targets)
            )
            if reusable:
                reused_subaccounts += 1
                continue
            subaccounts.append(JdlMigrationSubaccountReview(
                source_sub_key, code, name, sub_code, sub_name, targets,
                len(subaccount_journals[(code, name, sub_code, sub_name)]),
                bool(target_parent_code),
            ))

        taxes: list[JdlMigrationTaxReview] = []
        reused_taxes = 0
        target_master_identity = (
            self.company_store.target_master_identity_sha256(company_setting_id)
        )
        target_context = self.company_store.resolve(company_setting_id).context
        context_identity = (
            tax_context_identity_sha256(target_context)
            if target_context is not None
            else None
        )
        for (scope, category, input_method), count in sorted(tax_counts.items()):
            key = jdl_source_tax_key(scope, category, input_method)
            saved = profile.tax_mappings.get(key)
            evidence = (
                evidence_for_target_context(key, target_context)
                if target_context is not None
                else None
            )
            known_evidence = evidence_for_source_tax_key(key)
            master_dependencies_match = (
                known_evidence is not None
                and target_master_inventory_dependencies_match(
                    known_evidence,
                    target_accounts,
                    target_subaccounts,
                )
            )
            dependency_mismatches = (
                target_master_dependency_mismatches(
                    known_evidence, target_accounts, target_subaccounts
                )
                if known_evidence is not None
                else ()
            )
            evidence_active = (
                evidence is not None
                and master_dependencies_match
                and context_identity is not None
                and evidence.confirmed_context_fingerprint == context_identity
            )
            reusable_tax = (
                saved is not None
                and saved.status is MappingStatus.USER_CONFIRMED
                and evidence_active
                and saved.metadata.get("jdl_evidence_id") == evidence.evidence_id
                and saved.metadata.get("tax_context_identity_sha256")
                == context_identity
            )
            if reusable_tax:
                reused_taxes += 1
                continue
            evidence_status = (
                "VERIFIED_BY_REAL_IMPORT"
                if evidence_active
                else "VERIFIED_CONTEXT_MISMATCH"
                if master_dependencies_match
                else "VERIFIED_MASTER_MISMATCH"
                if known_evidence is not None
                else "UNVERIFIED"
            )
            taxes.append(JdlMigrationTaxReview(
                " / ".join(filter(None, (scope, category, input_method))),
                count,
                "HUMAN_CONFIRMATION_REQUIRED"
                if evidence_active
                else "CONTEXT_CONFIRMATION_REQUIRED"
                if master_dependencies_match
                else "TARGET_MASTER_CONFIRMATION_REQUIRED"
                if known_evidence is not None
                else "EVIDENCE_AND_HUMAN_CONFIRMATION_REQUIRED",
                evidence_status,
                (
                    evidence.evidence_id
                    if evidence is not None
                    else known_evidence.evidence_id
                    if known_evidence is not None
                    else ""
                ),
                self._tax_dependency_detail(
                    dependency_mismatches,
                    target_context is None,
                    master_dependencies_match and not evidence_active,
                ),
                key,
            ))

        tax_context_requirements = [
            "product_and_version",
            "taxpayer_status",
            "tax_included_or_excluded",
            "taxation_method",
        ]
        if (
            target_context is not None
            and target_context.effective_taxation_method.value == "SIMPLIFIED"
        ):
            tax_context_requirements.append("simplified_business_category")
        else:
            tax_context_requirements.append("credit_method")
        return JdlMigrationHumanReview(
            company_setting_id, tuple(accounts), tuple(subaccounts), tuple(taxes),
            tuple(overflow),
            tuple(tax_context_requirements),
            source_path, source_sha256,
            target_master_identity,
            setting.expected_source_format_key, setting.expected_target_format_key,
            reused_accounts, reused_subaccounts, reused_taxes, True,
        )

    def load(self, company_setting_id: str, path: Path) -> JdlMigrationHumanReview:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-READ-FAILED",
                "移行確認ファイルを読み取れません。",
            ) from exc
        if payload.get("document_type") != "JDL_MIGRATION_HUMAN_REVIEW":
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-DOCUMENT-MISMATCH",
                "移行確認ファイルの形式が一致しません。",
            )
        if payload.get("review_schema_version") != "2":
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-SCHEMA-UNSUPPORTED",
                "確認ファイルが古いため、最新の確認ファイルを選択してください。",
            )
        if payload.get("formal_output_enabled") is not False:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-UNSAFE-PACK",
                "安全確認用ではない確認ファイルは開けません。",
            )
        setting, profile = self._validated_setting(company_setting_id)
        source_sha256 = str(payload.get("source_sha256", ""))
        if len(source_sha256) != 64:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-CASE-IDENTITY-MISSING",
                "実案件を識別できない確認ファイルです。最新の確認ファイルを選択してください。",
            )
        source_format_key = str(payload.get("source_format_key", ""))
        target_format_key = str(payload.get("target_format_key", ""))
        if (
            source_format_key != setting.expected_source_format_key
            or source_format_key != profile.source_format_identity.stable_key
        ):
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-SOURCE-FORMAT-MISMATCH",
                "入力元の形式が確認ファイルと一致しません。",
            )
        if (
            target_format_key != setting.expected_target_format_key
            or target_format_key != profile.target_format_identity.stable_key
        ):
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-TARGET-FORMAT-MISMATCH",
                "変換先の形式が確認ファイルと一致しません。",
            )
        review_master_hash = str(
            payload.get("target_master_identity_sha256", "")
        )
        current_master_hash = self.company_store.target_master_identity_sha256(
            company_setting_id
        )
        if not review_master_hash or review_master_hash != current_master_hash:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-TARGET-MASTER-MISMATCH",
                "科目一覧が確認ファイルと一致しません。最新の確認ファイルを選択してください。",
            )

        target_accounts, _target_subaccounts, _disabled_names = (
            self.company_store.target_master_inventory(company_setting_id)
        )
        all_targets = tuple(sorted(
            (item.target_master_code, item.target_formal_name)
            for item in target_accounts
        ))
        accounts = tuple(
            self._account(item, all_targets)
            for item in payload.get("account_mismatches", ())
        )
        subaccounts = tuple(self._subaccount(item) for item in payload.get("subaccounts", ()))
        tax = payload.get("tax", {})
        taxes = tuple(
            JdlMigrationTaxReview(
                " / ".join(filter(None, (
                    str(item.get("scope", "")), str(item.get("category", "")),
                    str(item.get("input_method", "")),
                ))),
                int(item.get("row_count", 0)),
                str(item.get("decision", "EVIDENCE_REQUIRED")),
                str(item.get("evidence_status", "UNVERIFIED")),
                str(item.get("reference_evidence_id", "")),
                "",
                jdl_source_tax_key(
                    str(item.get("scope", "")),
                    str(item.get("category", "")),
                    str(item.get("input_method", "")),
                ),
            )
            for item in tax.get("source_identities", ())
        )
        description = payload.get("description", {})
        details = description.get("overflow_rows", ())
        descriptions = tuple(
            JdlMigrationDescriptionReview(
                str(item.get("journal_identifier", "確認対象")),
                int(item.get("current_length", 0)),
            )
            for item in details
        )
        if not descriptions:
            descriptions = tuple(
                JdlMigrationDescriptionReview(f"確認対象 {index + 1}", 0)
                for index in range(int(description.get("overflow_row_count", 0)))
            )
        return JdlMigrationHumanReview(
            company_setting_id, accounts, subaccounts, taxes, descriptions,
            tuple(str(value) for value in tax.get("target_context_confirmation", ())),
            path, source_sha256, review_master_hash,
            source_format_key, target_format_key,
        )

    def save(
        self,
        review: JdlMigrationHumanReview,
        account_selections: Mapping[str, tuple[str, str]],
        account_confirmed: set[str],
        subaccount_selections: Mapping[str, tuple[str, str] | str],
        subaccount_confirmed: set[str],
        tax_confirmed: set[str] | None = None,
        description_replacements: Mapping[str, str] | None = None,
        description_confirmed: set[str] | None = None,
    ) -> None:
        setting, old = self._validated_setting(review.company_setting_id)
        if (
            setting.expected_source_format_key != review.source_format_key
            or setting.expected_target_format_key != review.target_format_key
        ):
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-FORMAT-CHANGED",
                "入力元または変換先の設定が変更されています。確認画面を開き直してください。",
            )
        if (
            self.company_store.target_master_identity_sha256(
                review.company_setting_id
            )
            != review.target_master_identity_sha256
        ):
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-TARGET-MASTER-CHANGED",
                "JDL科目一覧が更新されています。確認画面を開き直してください。",
            )
        if review.derived_state:
            try:
                current_source_hash = hashlib.sha256(
                    review.source_path.read_bytes()
                ).hexdigest()
            except OSError as exc:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-SOURCE-CHANGED",
                    "入力ファイルが変更されています。確認画面を開き直してください。",
                ) from exc
            if current_source_hash != review.source_sha256:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-SOURCE-CHANGED",
                    "入力ファイルが変更されています。確認画面を開き直してください。",
                )
        accounts = dict(old.account_mappings)
        subs = dict(old.subaccount_context_mappings)
        setup_context_sha256 = setting.context_fingerprint
        tax_confirmed = tax_confirmed or set()
        description_replacements = description_replacements or {}
        description_confirmed = description_confirmed or set()

        for item in review.accounts:
            if item.key not in account_confirmed:
                continue
            selected = account_selections.get(item.key)
            if selected not in item.targets:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-ACCOUNT-SELECTION-REQUIRED",
                    "確認したJDL科目を選択してください。",
                )
            target_code, target_name = selected
            accounts[jdl_source_account_key(item.source_code, item.source_name)] = MappingValue(
                jdl_source_account_key(item.source_code, item.source_name),
                target_name,
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "target_code": target_code,
                    "target_formal_name": target_name,
                    "target_printed_name": target_name,
                    "setup_context_sha256": setup_context_sha256,
                },
            )

        for item in review.subaccounts:
            if item.key not in subaccount_confirmed:
                continue
            selected = subaccount_selections.get(item.key)
            parent_key = jdl_source_account_key(item.parent_code, item.parent_name)
            parent = accounts.get(parent_key)
            target_accounts, _target_subaccounts, _disabled = (
                self.company_store.target_master_inventory(
                    review.company_setting_id
                )
            )
            exact_parent_identity = next(
                (
                    target
                    for target in target_accounts
                    if target.target_master_code == item.parent_code
                    and target.target_formal_name == item.parent_name
                ),
                None,
            )
            # Exact source/target account identities are intentionally omitted
            # from the review table. Persist that exact parent identity when a
            # confirmed child mapping needs it for runtime parent scoping.
            if exact_parent_identity and parent is None:
                parent = MappingValue(
                    parent_key,
                    item.parent_name,
                    MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": item.parent_code,
                        "target_formal_name": item.parent_name,
                        "target_printed_name": item.parent_name,
                        "setup_context_sha256": setup_context_sha256,
                    },
                )
                accounts[parent_key] = parent
            if (
                not exact_parent_identity
                and (parent is None or parent.status is not MappingStatus.USER_CONFIRMED)
            ):
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-PARENT-REQUIRED",
                    "親科目の対応を先に確認してください。",
                )
            key = MappingKey(
                MappingType.SUBACCOUNT,
                jdl_source_subaccount_key(item.source_code, item.source_name),
                parent_key,
            )
            if selected == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value:
                if item.targets:
                    raise JdlMigrationReviewError(
                        "JDL-MIGRATION-REVIEW-SUBACCOUNT-TARGET-REQUIRED",
                        "JDL補助科目がある場合は対応先を選択してください。",
                    )
                subs[key] = MappingValue(
                    key.source_value, "", MappingStatus.USER_CONFIRMED,
                    parent_account=parent_key,
                    metadata={
                        "subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                        "setup_context_sha256": setup_context_sha256,
                    },
                )
            elif isinstance(selected, tuple) and selected in item.targets:
                target_code, target_name = selected
                subs[key] = MappingValue(
                    key.source_value, target_name, MappingStatus.USER_CONFIRMED,
                    parent_account=parent_key,
                    metadata={
                        "target_code": target_code,
                        "output_code": target_code,
                        "output_name": target_name,
                        "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                        "setup_context_sha256": setup_context_sha256,
                    },
                )
            else:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-SUBACCOUNT-SELECTION-REQUIRED",
                    "補助科目の処理方法を確認してください。",
                )

        taxes = dict(old.tax_mappings)
        tax_items = {item.source_key: item for item in review.taxes}
        resolved_context = self.company_store.resolve(
            review.company_setting_id
        ).context
        for source_key in tax_confirmed:
            item = tax_items.get(source_key)
            if (
                item is None
                or item.evidence_status != "VERIFIED_BY_REAL_IMPORT"
                or item.status != "HUMAN_CONFIRMATION_REQUIRED"
                or not item.evidence_id
                or resolved_context is None
            ):
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-TAX-EVIDENCE-REQUIRED",
                    "実機確認済みの税区分だけ確認結果を保存できます。",
                )
            taxes[source_key] = MappingValue(
                source_key,
                source_key,
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "jdl_evidence_id": item.evidence_id,
                    "tax_context_identity_sha256": tax_context_identity_sha256(
                        resolved_context
                    ),
                    "setup_context_sha256": setup_context_sha256,
                },
            )

        loss_policies = dict(old.loss_policy_mappings)
        description_items = {item.row_key: item for item in review.descriptions}
        for row_key in description_confirmed:
            item = description_items.get(row_key)
            replacement = description_replacements.get(row_key, "")
            try:
                replacement.encode("cp932", errors="strict")
            except UnicodeEncodeError as exc:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-DESCRIPTION-CP932",
                    "置換後の摘要にJDLで表現できない文字があります。",
                ) from exc
            if item is None or not 1 <= len(replacement) <= 32:
                raise JdlMigrationReviewError(
                    "JDL-MIGRATION-REVIEW-DESCRIPTION-INVALID",
                    "置換後の摘要は1文字以上32文字以内で入力してください。",
                )
            loss_policies[row_key] = MappingValue(
                row_key,
                replacement,
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "policy": "HUMAN_CONFIRMED_DESCRIPTION_REPLACEMENT",
                    "source_sha256": review.source_sha256,
                    "original_description_sha256": (
                        item.original_description_sha256
                    ),
                    "setup_context_sha256": setup_context_sha256,
                },
            )

        updated = replace(
            old,
            profile_id=revised_profile_id(old.profile_id, "jdl-review"),
            account_mappings=accounts,
            subaccount_context_mappings=subs,
            tax_mappings=taxes,
            loss_policy_mappings=loss_policies,
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_profile(review.company_setting_id, updated.profile_id)
        except Exception as exc:
            self.profile_store.delete(updated.profile_id)
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-PERSISTENCE-FAILED",
                "会社設定を保存できませんでした。設定を開き直して再試行してください。",
            ) from exc

    def _validated_setting(self, company_setting_id: str):
        setting = self.company_store.get(company_setting_id)
        profile = self.profile_store.get(setting.conversion_profile_id)
        resolved = self.company_store.resolve(company_setting_id)
        if resolved.status in {
            CompanySettingStatus.STALE,
            CompanySettingStatus.INCOMPATIBLE,
            CompanySettingStatus.MALFORMED,
        }:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-COMPANY-STALE",
                "会社設定が古くなっています。JDL科目一覧と対応内容を確認してください。",
            )
        return setting, profile

    @staticmethod
    def _tax_dependency_detail(
        mismatches: tuple[str, ...],
        context_unconfirmed: bool,
        context_mismatch: bool,
    ) -> str:
        labels = []
        for reason in mismatches:
            kind, _, code = reason.partition(":")
            if kind == "RELEVANT_ACCOUNT_CODE_MISSING":
                labels.append(f"確認対象の科目コード {code} がありません")
            elif kind == "RELEVANT_ACCOUNT_NAME_MISMATCH":
                labels.append(f"確認対象の科目コード {code} の正式名称が異なります")
            elif kind == "RELEVANT_SUBACCOUNT_REQUIREMENT_CHANGED":
                labels.append(f"確認対象の科目コード {code} に補助科目が設定されています")
        if context_unconfirmed:
            labels.append("最新の科目一覧に対するJDL税設定の再確認が必要です")
        elif context_mismatch:
            labels.append("JDL税設定が実機確認時の条件と異なります")
        return " / ".join(labels)

    @staticmethod
    def _account(item, all_targets=()) -> JdlMigrationAccountReview:
        source = item.get("source", {})
        code, name = str(source.get("code", "")), str(source.get("name", ""))
        if not code or not name:
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-ACCOUNT-IDENTITY-MISSING",
                "科目identityが不足しています。",
            )
        recommended = tuple(
            (str(target.get("code", "")), str(target.get("name", "")))
            for target in item.get("target_candidates", ())
            if target.get("code") and target.get("name")
        )
        targets = tuple(all_targets) or recommended
        return JdlMigrationAccountReview(
            f"ACCOUNT|{code}|{name}", code, name,
            str(item.get("classification", "UNKNOWN")), recommended, targets,
            int(item.get("affected_journal_count", 0)),
            bool(item.get("disabled_name_match", False)),
        )

    @staticmethod
    def _subaccount(item) -> JdlMigrationSubaccountReview:
        parent_code = str(item.get("parent_code", ""))
        parent_name = str(item.get("parent_name", ""))
        source_code = str(item.get("source_code", ""))
        source_name = str(item.get("source_name", ""))
        if not all((parent_code, parent_name, source_code, source_name)):
            raise JdlMigrationReviewError(
                "JDL-MIGRATION-REVIEW-SUBACCOUNT-IDENTITY-MISSING",
                "補助科目identityが不足しています。",
            )
        targets = tuple(
            (str(target.get("code", "")), str(target.get("name", "")))
            for target in item.get("target_candidates", ())
            if target.get("code") and target.get("name")
        )
        return JdlMigrationSubaccountReview(
            f"SUBACCOUNT|{parent_code}|{source_code}|{source_name}",
            parent_code, parent_name, source_code, source_name, targets,
            int(item.get("affected_journal_count", 0)),
            bool(item.get("target_parent_exact", False)),
        )

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from accounting_converter.adapters.input.jdl import (
    jdl_source_account_key,
    jdl_source_subaccount_key,
)
from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)


class JdlMigrationReviewError(ValueError):
    pass


@dataclass(frozen=True)
class JdlMigrationAccountReview:
    key: str
    source_code: str
    source_name: str
    classification: str
    targets: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class JdlMigrationSubaccountReview:
    key: str
    parent_code: str
    parent_name: str
    source_code: str
    source_name: str
    targets: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class JdlMigrationTaxReview:
    label: str
    row_count: int
    status: str


@dataclass(frozen=True)
class JdlMigrationDescriptionReview:
    journal_identifier: str
    current_length: int


@dataclass(frozen=True)
class JdlMigrationHumanReview:
    company_setting_id: str
    accounts: tuple[JdlMigrationAccountReview, ...]
    subaccounts: tuple[JdlMigrationSubaccountReview, ...]
    taxes: tuple[JdlMigrationTaxReview, ...]
    descriptions: tuple[JdlMigrationDescriptionReview, ...]
    target_context_fields: tuple[str, ...]
    source_path: Path


class JdlMigrationHumanReviewService:
    """Loads a private review pack and persists only explicit Human decisions."""

    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store

    def load(self, company_setting_id: str, path: Path) -> JdlMigrationHumanReview:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JdlMigrationReviewError("移行確認ファイルを読み取れません。") from exc
        if payload.get("document_type") != "JDL_MIGRATION_HUMAN_REVIEW":
            raise JdlMigrationReviewError("移行確認ファイルの形式が一致しません。")
        if payload.get("formal_output_enabled") is not False:
            raise JdlMigrationReviewError("formal outputが無効なreview packだけを使用できます。")
        setting = self.company_store.get(company_setting_id)
        review_target_hash = str(payload.get("target_pdf_sha256", ""))
        current_context_hash = str(getattr(setting, "context_fingerprint", ""))
        if (
            review_target_hash
            and current_context_hash
            and review_target_hash != current_context_hash
        ):
            raise JdlMigrationReviewError(
                "確認ファイルと現在のJDL科目一覧が一致しません。"
            )

        accounts = tuple(self._account(item) for item in payload.get("account_mismatches", ()))
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
            path,
        )

    def save(
        self,
        review: JdlMigrationHumanReview,
        account_selections: Mapping[str, tuple[str, str]],
        account_confirmed: set[str],
        subaccount_selections: Mapping[str, tuple[str, str] | str],
        subaccount_confirmed: set[str],
    ) -> None:
        setting = self.company_store.get(review.company_setting_id)
        old = self.profile_store.get(setting.conversion_profile_id)
        accounts = dict(old.account_mappings)
        subs = dict(old.subaccount_context_mappings)

        for item in review.accounts:
            if item.key not in account_confirmed:
                continue
            selected = account_selections.get(item.key)
            if selected not in item.targets:
                raise JdlMigrationReviewError("確認したJDL科目を選択してください。")
            target_code, target_name = selected
            accounts[jdl_source_account_key(item.source_code, item.source_name)] = MappingValue(
                jdl_source_account_key(item.source_code, item.source_name),
                target_name,
                MappingStatus.USER_CONFIRMED,
                metadata={"target_code": target_code, "target_printed_name": target_name},
            )

        for item in review.subaccounts:
            if item.key not in subaccount_confirmed:
                continue
            selected = subaccount_selections.get(item.key)
            parent_key = jdl_source_account_key(item.parent_code, item.parent_name)
            parent = accounts.get(parent_key)
            if parent is None or parent.status is not MappingStatus.USER_CONFIRMED:
                raise JdlMigrationReviewError("親科目の対応を先に確認してください。")
            key = MappingKey(
                MappingType.SUBACCOUNT,
                jdl_source_subaccount_key(item.source_code, item.source_name),
                parent_key,
            )
            if selected == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value:
                if item.targets:
                    raise JdlMigrationReviewError("JDL補助科目がある場合は対応先を選択してください。")
                subs[key] = MappingValue(
                    key.source_value, "", MappingStatus.USER_CONFIRMED,
                    parent_account=parent_key,
                    metadata={"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
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
                    },
                )
            else:
                raise JdlMigrationReviewError("補助科目の処理方法を確認してください。")

        updated = replace(
            old,
            profile_id=revised_profile_id(old.profile_id, "jdl-review"),
            account_mappings=accounts,
            subaccount_context_mappings=subs,
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_profile(review.company_setting_id, updated.profile_id)
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise

    @staticmethod
    def _account(item) -> JdlMigrationAccountReview:
        source = item.get("source", {})
        code, name = str(source.get("code", "")), str(source.get("name", ""))
        if not code or not name:
            raise JdlMigrationReviewError("科目identityが不足しています。")
        targets = tuple(
            (str(target.get("code", "")), str(target.get("name", "")))
            for target in item.get("target_candidates", ())
            if target.get("code") and target.get("name")
        )
        return JdlMigrationAccountReview(
            f"ACCOUNT|{code}|{name}", code, name,
            str(item.get("classification", "UNKNOWN")), targets,
        )

    @staticmethod
    def _subaccount(item) -> JdlMigrationSubaccountReview:
        parent_code = str(item.get("parent_code", ""))
        parent_name = str(item.get("parent_name", ""))
        source_code = str(item.get("source_code", ""))
        source_name = str(item.get("source_name", ""))
        if not all((parent_code, parent_name, source_code, source_name)):
            raise JdlMigrationReviewError("補助科目identityが不足しています。")
        targets = tuple(
            (str(target.get("code", "")), str(target.get("name", "")))
            for target in item.get("target_candidates", ())
            if target.get("code") and target.get("name")
        )
        return JdlMigrationSubaccountReview(
            f"SUBACCOUNT|{parent_code}|{source_code}|{source_name}",
            parent_code, parent_name, source_code, source_name, targets,
        )

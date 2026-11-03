from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlInputTaxCreditMethod,
    JdlSimplifiedBusinessCategory,
    JdlSubaccountIdentity,
    JdlTaxationMethod,
    JdlTaxRounding,
    JdlUnusableSubaccount,
    UNUSABLE_SUBACCOUNT_NAME_TOO_LONG,
    JdlTargetContext,
    JdlTargetContextBuilder,
)
from accounting_converter.application.profile_revision import revised_profile_id
from accounting_converter.application.moneyforward_trade_partner import (
    upgrade_trade_partner_policy,
)
from accounting_converter.domain.conversion_profile import TRADE_PARTNER_LOSS_POLICY_KEY
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.jdl_account_pdf_draft import (
    JdlAccountPdfDraftStore,
)
from accounting_converter.infrastructure.jdl_target_context_loader import (
    JdlTargetContextLoader,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode, jdl_subaccount_name_fits
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


# Duplicate-name items are already excluded from the draft's selectable targets.
NAME_CONFLICTS_EXCLUDED_FROM_TARGETS = frozenset(
    {"PRINTED_ACCOUNT_NAME_CONFLICT", "SUBACCOUNT_NAME_CONFLICT"}
)


class CompanyTaxContextConfirmationError(ValueError):
    pass


@dataclass(frozen=True)
class JdlTaxContextSelection:
    tax_processing_mode: JdlTaxProcessingMode
    taxation_method: JdlTaxationMethod = JdlTaxationMethod.UNCONFIRMED
    input_tax_credit_method: JdlInputTaxCreditMethod = (
        JdlInputTaxCreditMethod.UNCONFIRMED
    )
    simplified_business_category: JdlSimplifiedBusinessCategory | None = None
    # JDL 端数処理 as the Human read it; UNCONFIRMED keeps the old behavior.
    sales_tax_rounding: JdlTaxRounding = JdlTaxRounding.UNCONFIRMED
    purchase_tax_rounding: JdlTaxRounding = JdlTaxRounding.UNCONFIRMED


@dataclass(frozen=True)
class PendingTaxContextConfirmation:
    selection: JdlTaxContextSelection
    blocking_rule_ids: tuple[str, ...]


class CompanyTaxContextConfirmationService:
    """Promotes one explicitly confirmed PDF master to the scoped tax context."""

    def __init__(self, company_store, profile_store) -> None:
        self.company_store = company_store
        self.profile_store = profile_store
        self.drafts = JdlAccountPdfDraftStore()
        self.contexts = JdlTargetContextLoader()

    def is_pending(self, company_setting_id: str) -> bool:
        setting = self.company_store.get(company_setting_id)
        return self.drafts.is_draft(self.company_store.context_path(setting))

    def current_context(self, company_setting_id: str) -> JdlTargetContext | None:
        setting = self.company_store.get(company_setting_id)
        path = self.company_store.context_path(setting)
        if self.drafts.is_draft(path):
            return None
        return self.contexts.load(path)

    def pending_selection(self, company_setting_id: str) -> JdlTaxContextSelection | None:
        payload = self.company_store.load_pending_tax_confirmation(company_setting_id)
        if payload is None:
            return None
        try:
            return JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode(payload["tax_processing_mode"]),
                taxation_method=JdlTaxationMethod(payload["taxation_method"]),
                input_tax_credit_method=JdlInputTaxCreditMethod(payload["input_tax_credit_method"]),
                simplified_business_category=(
                    JdlSimplifiedBusinessCategory(payload["simplified_business_category"])
                    if payload.get("simplified_business_category") else None
                ),
                sales_tax_rounding=JdlTaxRounding(payload.get("sales_tax_rounding", "UNCONFIRMED")),
                purchase_tax_rounding=JdlTaxRounding(payload.get("purchase_tax_rounding", "UNCONFIRMED")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def confirm_taxable_included(self, company_setting_id: str, *, confirmed: bool):
        return self.confirm(
            company_setting_id,
            selection=JdlTaxContextSelection(
                tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
                taxation_method=JdlTaxationMethod.STANDARD,
                input_tax_credit_method=JdlInputTaxCreditMethod.INDIVIDUAL,
            ),
            confirmed=confirmed,
        )

    def confirm(
        self,
        company_setting_id: str,
        *,
        selection: JdlTaxContextSelection,
        confirmed: bool,
    ):
        if not confirmed:
            raise CompanyTaxContextConfirmationError(
                "JDL tax setting requires explicit confirmation"
            )
        setting = self.company_store.get(company_setting_id)
        draft_path = self.company_store.context_path(setting)
        previous_context = None
        if self.drafts.is_draft(draft_path):
            draft = self.drafts.load(draft_path)
            if any(
                item.category not in NAME_CONFLICTS_EXCLUDED_FROM_TARGETS
                for item in draft.observation.conflicts
            ):
                raise CompanyTaxContextConfirmationError(
                    "JDL printed master contains unresolved conflicts"
                )
            if draft.observation.departments or draft.observation.printed_departments:
                raise CompanyTaxContextConfirmationError(
                    "department settings require separate confirmation"
                )
            account_master = tuple(
                JdlAccountIdentity(
                    mapping_value=item.name,
                    target_master_code=item.code,
                    target_name=item.abbreviation,
                    target_formal_name=item.name,
                )
                for item in draft.observation.printed_accounts
                if item.enabled
            )
            printed_subaccounts = tuple(
                item for item in draft.observation.subaccounts
                if item.evidence_scope == "PRINTED_EXPLICIT_PARENT"
            )
            subaccounts = tuple(
                JdlSubaccountIdentity(
                    parent_account=item.parent_account_name,
                    mapping_value=item.name,
                    target_master_code=item.code,
                    output_code=item.code,
                    output_name=item.name,
                    output_representation_confirmed=True,
                    parent_account_code=item.parent_account_code,
                    target_name=item.name,
                )
                for item in printed_subaccounts
                if jdl_subaccount_name_fits(item.name)
            )
            # Names longer than the JDL import field cannot be written. They stay
            # recorded (master stays complete) but are never selectable; nothing
            # is shortened or renamed.
            unusable_subaccounts = tuple(
                JdlUnusableSubaccount(
                    parent_account=item.parent_account_name,
                    parent_account_code=item.parent_account_code,
                    code=item.code,
                    name=item.name,
                    reason=UNUSABLE_SUBACCOUNT_NAME_TOO_LONG,
                )
                for item in printed_subaccounts
                if not jdl_subaccount_name_fits(item.name)
            )
            departments = ()
            department_processing_enabled = False
        else:
            current = self.contexts.load(draft_path)
            previous_context = current
            account_master = current.account_master
            subaccounts = current.subaccounts
            unusable_subaccounts = current.unusable_subaccounts
            departments = current.departments
            department_processing_enabled = current.department_processing_enabled
        build_args = dict(
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            product="JDL IBEX 出納帳",
            version="35.5",
            account_master=account_master,
            subaccounts=subaccounts,
            unusable_subaccounts=unusable_subaccounts,
            departments=departments,
            tax_processing_mode=selection.tax_processing_mode,
            department_processing_enabled=department_processing_enabled,
            standard_taxation_confirmed=(
                selection.taxation_method is JdlTaxationMethod.STANDARD
            ),
            individual_credit_method_confirmed=(
                selection.input_tax_credit_method
                is JdlInputTaxCreditMethod.INDIVIDUAL
            ),
            taxation_method=selection.taxation_method,
            input_tax_credit_method=selection.input_tax_credit_method,
            simplified_business_category=selection.simplified_business_category,
            sales_tax_rounding=selection.sales_tax_rounding,
            purchase_tax_rounding=selection.purchase_tax_rounding,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
        result = JdlTargetContextBuilder().build(**build_args)
        if not result.success or result.context is None:
            rule_ids = sorted({item.rule_id for item in result.validation_results})
            raise CompanyTaxContextConfirmationError(
                "JDL printed master cannot be promoted safely: "
                + ", ".join(rule_ids)
            )
        context_bytes = self.contexts.to_json_text(result.context).encode("utf-8")
        context_hash = hashlib.sha256(context_bytes).hexdigest()
        old = self.profile_store.get(setting.conversion_profile_id)
        accounts = {
            key: replace(
                value,
                metadata={**value.metadata, "setup_context_sha256": context_hash},
            )
            for key, value in old.account_mappings.items()
        }
        subaccounts = {
            key: replace(
                value,
                metadata={**value.metadata, "setup_context_sha256": context_hash},
            )
            for key, value in old.subaccount_context_mappings.items()
        }
        taxes = {
            key: MappingValue(
                source_value=value.source_value,
                target_value=None,
                status=MappingStatus.UNRESOLVED,
            )
            for key, value in old.tax_mappings.items()
        }
        loss_policies = dict(old.loss_policy_mappings)
        if previous_context is not None:
            policy = loss_policies.get(TRADE_PARTNER_LOSS_POLICY_KEY)
            if policy is not None:
                loss_policies[TRADE_PARTNER_LOSS_POLICY_KEY] = (
                    upgrade_trade_partner_policy(
                        policy, previous_context, result.context
                    )
                )
        updated = replace(
            old,
            profile_id=revised_profile_id(old.profile_id, "tax-context"),
            account_mappings=accounts,
            subaccount_context_mappings=subaccounts,
            tax_mappings=taxes,
            loss_policy_mappings=loss_policies,
            updated_at=datetime.now(timezone.utc),
        )
        self.profile_store.create(updated)
        try:
            self.company_store.replace_with_confirmed_context(
                company_setting_id,
                context_bytes,
                conversion_profile_id=updated.profile_id,
            )
        except Exception:
            self.profile_store.delete(updated.profile_id)
            raise
        return result.context

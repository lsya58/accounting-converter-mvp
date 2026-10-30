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
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
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
            if draft.observation.conflicts:
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
                for item in draft.observation.subaccounts
                if item.evidence_scope == "PRINTED_EXPLICIT_PARENT"
            )
            departments = ()
            department_processing_enabled = False
        else:
            current = self.contexts.load(draft_path)
            previous_context = current
            account_master = current.account_master
            subaccounts = current.subaccounts
            departments = current.departments
            department_processing_enabled = current.department_processing_enabled
        result = JdlTargetContextBuilder().build(
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            product="JDL IBEX 出納帳",
            version="35.5",
            account_master=account_master,
            subaccounts=subaccounts,
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
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
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

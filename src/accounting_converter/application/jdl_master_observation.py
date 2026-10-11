from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlTargetContext,
    JdlTargetContextValidator,
    JdlSubaccountIdentity,
)
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER,
)
from accounting_converter.domain.validation import ValidationResult
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class JdlMasterObservationError(ValueError):
    pass


class JdlMasterCompleteness(str, Enum):
    OBSERVED_USED_MASTER = "OBSERVED_USED_MASTER"
    OBSERVED_PRINTED_MASTER = "OBSERVED_PRINTED_MASTER"
    PARTIAL_MASTER = "PARTIAL_MASTER"
    FULL_MASTER = "FULL_MASTER"


@dataclass(frozen=True)
class JdlObservedSubaccount:
    parent_account_code: str
    parent_account_name: str
    code: str
    name: str
    evidence_scope: str = "JOURNAL_RUNTIME_OBSERVED"


@dataclass(frozen=True)
class JdlObservedDepartment:
    code: str
    name: str


@dataclass(frozen=True)
class JdlPrintedAccount:
    code: str
    name: str
    abbreviation: str
    normal_balance: str
    enabled: bool
    has_observed_setting_values: bool = False


@dataclass(frozen=True)
class JdlMasterSourceEvidence:
    sha256: str
    source_kind: str
    data_record_count: int
    page_count: int | None = None
    acquisition_method: str | None = None
    human_observed: bool = False


@dataclass(frozen=True)
class JdlMasterConflict:
    category: str


@dataclass(frozen=True)
class JdlMasterObservation:
    accounts: tuple[JdlAccountIdentity, ...]
    subaccounts: tuple[JdlObservedSubaccount, ...]
    departments: tuple[JdlObservedDepartment, ...]
    sources: tuple[JdlMasterSourceEvidence, ...]
    conflicts: tuple[JdlMasterConflict, ...] = ()
    completeness: JdlMasterCompleteness = JdlMasterCompleteness.OBSERVED_USED_MASTER
    printed_accounts: tuple[JdlPrintedAccount, ...] = ()
    excluded_uncoded_printed_row_count: int = 0

    def privacy_safe_summary(self) -> dict[str, int | str]:
        return {
            "completeness": self.completeness.value,
            "source_count": len(self.sources),
            "account_identity_count": len(self.accounts),
            "subaccount_identity_count": len(self.subaccounts),
            "department_identity_count": len(self.departments),
            "printed_account_count": len(self.printed_accounts),
            "printed_enabled_count": sum(
                item.enabled for item in self.printed_accounts
            ),
            "printed_disabled_count": sum(
                not item.enabled for item in self.printed_accounts
            ),
            "excluded_uncoded_printed_row_count": (
                self.excluded_uncoded_printed_row_count
            ),
            "conflict_count": len(self.conflicts),
        }


@dataclass(frozen=True)
class JdlObservedContextDraft:
    context: JdlTargetContext
    completeness: JdlMasterCompleteness
    validation_results: tuple[ValidationResult, ...]

    @property
    def production_usable(self) -> bool:
        return False


@dataclass(frozen=True)
class JdlAccountCoverage:
    required_count: int
    exact_single_count: int
    missing_count: int
    ambiguous_count: int

    def privacy_safe_summary(self) -> dict[str, int]:
        return {
            "required_account_count": self.required_count,
            "exact_single_candidate_count": self.exact_single_count,
            "missing_candidate_count": self.missing_count,
            "ambiguous_candidate_count": self.ambiguous_count,
        }


@dataclass(frozen=True)
class JdlMasterSourceComparison:
    corroborated_count: int
    conflict_count: int
    runtime_only_count: int

    def privacy_safe_summary(self) -> dict[str, int]:
        return {
            "corroborated_count": self.corroborated_count,
            "conflict_count": self.conflict_count,
            "runtime_only_not_promoted_count": self.runtime_only_count,
        }


class JdlMasterObservationService:
    """Extracts used master identities from exact observed 30-column exports."""

    _FLAGS = frozenset({"1000", "1100", "1110", "1101", "1111"})

    def observe_journal_export(self, path: Path) -> JdlMasterObservation:
        raw = path.read_bytes()
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            raise JdlMasterObservationError("BOM付きJDL CSVは観測対象外です。")
        try:
            text = raw.decode("cp932", errors="strict")
        except UnicodeDecodeError as exc:
            raise JdlMasterObservationError("CP932として解析できません。") from exc
        rows = list(csv.reader(io.StringIO(text, newline="")))
        header = list(JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER)
        header_indexes = [index for index, row in enumerate(rows) if row == header]
        if len(header_indexes) != 1:
            raise JdlMasterObservationError("観測済み30列headerを一意に確認できません。")

        accounts: list[JdlAccountIdentity] = []
        subaccounts: list[JdlObservedSubaccount] = []
        departments: list[JdlObservedDepartment] = []
        observation_issues: set[str] = set()
        record_count = 0
        for row in rows[header_indexes[0] + 1 :]:
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip() not in self._FLAGS:
                continue
            if len(row) != 30:
                raise JdlMasterObservationError("JDL data recordが30列ではありません。")
            record_count += 1
            self._observe_side(
                row, 3, 4, 5, 6, 7, accounts, subaccounts, observation_issues
            )
            self._observe_side(
                row, 13, 14, 15, 16, 17, accounts, subaccounts, observation_issues
            )
            self._observe_department(
                row[26], row[27], departments, observation_issues
            )
            self._observe_department(
                row[28], row[29], departments, observation_issues
            )
        if record_count == 0:
            raise JdlMasterObservationError("JDL data recordが見つかりません。")
        return self.merge(
            (
                JdlMasterObservation(
                    accounts=tuple(accounts),
                    subaccounts=tuple(subaccounts),
                    departments=tuple(departments),
                    sources=(
                        JdlMasterSourceEvidence(
                            sha256=hashlib.sha256(raw).hexdigest(),
                            source_kind="JDL_IBEX_JOURNAL_EXPORT_30_OBSERVED",
                            data_record_count=record_count,
                        ),
                    ),
                    conflicts=tuple(
                        JdlMasterConflict(category)
                        for category in sorted(observation_issues)
                    ),
                ),
            )
        )

    def merge(
        self, observations: Iterable[JdlMasterObservation]
    ) -> JdlMasterObservation:
        items = tuple(observations)
        accounts = {item for observation in items for item in observation.accounts}
        subaccounts = {
            item for observation in items for item in observation.subaccounts
        }
        departments = {
            item for observation in items for item in observation.departments
        }
        printed_accounts = {
            item for observation in items for item in observation.printed_accounts
        }
        conflicts: list[JdlMasterConflict] = [
            conflict for observation in items for conflict in observation.conflicts
        ]

        account_by_code: dict[str, set[tuple[str, str]]] = {}
        account_by_name: dict[str, set[str]] = {}
        for account in accounts:
            account_by_code.setdefault(account.target_master_code, set()).add(
                (account.target_name, account.target_formal_name)
            )
            account_by_name.setdefault(account.mapping_value, set()).add(
                account.target_master_code
            )
        bad_codes = {key for key, values in account_by_code.items() if len(values) > 1}
        bad_names = {key for key, values in account_by_name.items() if len(values) > 1}
        conflicts.extend(JdlMasterConflict("ACCOUNT_CODE_CONFLICT") for _ in bad_codes)
        conflicts.extend(JdlMasterConflict("ACCOUNT_NAME_CONFLICT") for _ in bad_names)
        accounts = {
            item
            for item in accounts
            if item.target_master_code not in bad_codes
            and item.mapping_value not in bad_names
        }

        subaccount_by_code: dict[tuple[str, str], set[tuple[str, str]]] = {}
        subaccount_by_name: dict[tuple[str, str], set[str]] = {}
        for subaccount in subaccounts:
            subaccount_by_code.setdefault(
                (subaccount.parent_account_code, subaccount.code), set()
            ).add((subaccount.parent_account_name, subaccount.name))
            subaccount_by_name.setdefault(
                (subaccount.parent_account_name, subaccount.name), set()
            ).add(subaccount.code)
        bad_subaccount_codes = {
            key for key, values in subaccount_by_code.items() if len(values) > 1
        }
        bad_subaccount_names = {
            key for key, values in subaccount_by_name.items() if len(values) > 1
        }
        conflicts.extend(
            JdlMasterConflict("SUBACCOUNT_CODE_CONFLICT")
            for _ in bad_subaccount_codes
        )
        conflicts.extend(
            JdlMasterConflict("SUBACCOUNT_NAME_CONFLICT")
            for _ in bad_subaccount_names
        )
        subaccounts = {
            item
            for item in subaccounts
            if (item.parent_account_code, item.code) not in bad_subaccount_codes
            and (item.parent_account_name, item.name) not in bad_subaccount_names
        }

        department_by_code: dict[str, set[str]] = {}
        department_by_name: dict[str, set[str]] = {}
        for department in departments:
            department_by_code.setdefault(department.code, set()).add(department.name)
            department_by_name.setdefault(department.name, set()).add(department.code)
        bad_department_codes = {
            key for key, values in department_by_code.items() if len(values) > 1
        }
        bad_department_names = {
            key for key, values in department_by_name.items() if len(values) > 1
        }
        conflicts.extend(
            JdlMasterConflict("DEPARTMENT_CODE_CONFLICT")
            for _ in bad_department_codes
        )
        conflicts.extend(
            JdlMasterConflict("DEPARTMENT_NAME_CONFLICT")
            for _ in bad_department_names
        )
        departments = {
            item
            for item in departments
            if item.code not in bad_department_codes
            and item.name not in bad_department_names
        }

        printed_by_code: dict[str, set[tuple[str, str, str, bool]]] = {}
        printed_by_name: dict[str, set[str]] = {}
        for account in printed_accounts:
            printed_by_code.setdefault(account.code, set()).add(
                (
                    account.name,
                    account.abbreviation,
                    account.normal_balance,
                    account.enabled,
                )
            )
            printed_by_name.setdefault(account.name, set()).add(account.code)
        bad_printed_codes = {
            key for key, values in printed_by_code.items() if len(values) > 1
        }
        bad_printed_names = {
            key for key, values in printed_by_name.items() if len(values) > 1
        }
        conflicts.extend(
            JdlMasterConflict("PRINTED_ACCOUNT_CODE_CONFLICT")
            for _ in bad_printed_codes
        )
        conflicts.extend(
            JdlMasterConflict("PRINTED_ACCOUNT_NAME_CONFLICT")
            for _ in bad_printed_names
        )
        printed_accounts = {
            item
            for item in printed_accounts
            if item.code not in bad_printed_codes and item.name not in bad_printed_names
        }
        sources_by_hash = {
            source.sha256: source for item in items for source in item.sources
        }

        return JdlMasterObservation(
            accounts=tuple(
                sorted(accounts, key=lambda item: (item.target_master_code, item.mapping_value))
            ),
            subaccounts=tuple(
                sorted(
                    subaccounts,
                    key=lambda item: (item.parent_account_code, item.code, item.name),
                )
            ),
            departments=tuple(
                sorted(departments, key=lambda item: (item.code, item.name))
            ),
            sources=tuple(sources_by_hash[key] for key in sorted(sources_by_hash)),
            conflicts=tuple(conflicts),
            completeness=self._merged_completeness(items),
            printed_accounts=tuple(
                sorted(printed_accounts, key=lambda item: (item.code, item.name))
            ),
            excluded_uncoded_printed_row_count=sum(
                item.excluded_uncoded_printed_row_count for item in items
            ),
        )

    def build_unconfirmed_context_draft(
        self, observation: JdlMasterObservation
    ) -> JdlObservedContextDraft:
        context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(
                [item.mapping_value for item in observation.accounts]
                + [item.name for item in observation.printed_accounts]
            ),
            tax_processing_mode=JdlTaxProcessingMode.UNCONFIRMED,
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            account_master=observation.accounts,
            subaccounts=tuple(
                JdlSubaccountIdentity(
                    parent_account=item.parent_account_name,
                    mapping_value=item.name,
                    target_master_code=item.code,
                    output_code=item.code,
                    output_name=item.name,
                    output_representation_confirmed=False,
                    parent_account_code=item.parent_account_code,
                    target_name=item.name,
                )
                for item in observation.subaccounts
                if item.evidence_scope == "PRINTED_EXPLICIT_PARENT"
            ),
            confirmation_state=JdlContextConfirmationState.UNCONFIRMED,
            provenance=JdlContextProvenance.UNCONFIRMED,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
        return JdlObservedContextDraft(
            context=context,
            completeness=observation.completeness,
            validation_results=JdlTargetContextValidator().validate(context),
        )

    @staticmethod
    def coverage(
        required_accounts: Iterable[str], observation: JdlMasterObservation
    ) -> JdlAccountCoverage:
        required = tuple(sorted(set(required_accounts)))
        exact: dict[str, set[str]] = {}
        for account in observation.accounts:
            for value in {
                account.mapping_value,
                account.target_name,
                account.target_formal_name,
            }:
                exact.setdefault(value, set()).add(account.target_master_code)
        for account in observation.printed_accounts:
            exact.setdefault(account.name, set()).add(account.code)
        counts = [len(exact.get(value, ())) for value in required]
        return JdlAccountCoverage(
            required_count=len(required),
            exact_single_count=sum(count == 1 for count in counts),
            missing_count=sum(count == 0 for count in counts),
            ambiguous_count=sum(count > 1 for count in counts),
        )

    @staticmethod
    def compare_printed_master_with_runtime(
        printed: JdlMasterObservation,
        runtime: JdlMasterObservation,
    ) -> JdlMasterSourceComparison:
        printed_by_code = {item.code: item for item in printed.printed_accounts}
        printed_by_name = {item.name: item for item in printed.printed_accounts}
        corroborated = 0
        conflicts = 0
        runtime_only = 0
        for account in runtime.accounts:
            names = {
                account.mapping_value,
                account.target_name,
                account.target_formal_name,
            }
            by_code = printed_by_code.get(account.target_master_code)
            if by_code is not None:
                if by_code.name in names or by_code.abbreviation in names:
                    corroborated += 1
                else:
                    conflicts += 1
                continue
            if any(name in printed_by_name for name in names):
                conflicts += 1
            else:
                runtime_only += 1
        return JdlMasterSourceComparison(corroborated, conflicts, runtime_only)

    @staticmethod
    def _merged_completeness(
        observations: tuple[JdlMasterObservation, ...]
    ) -> JdlMasterCompleteness:
        levels = {item.completeness for item in observations}
        if JdlMasterCompleteness.FULL_MASTER in levels:
            return JdlMasterCompleteness.FULL_MASTER
        if JdlMasterCompleteness.OBSERVED_PRINTED_MASTER in levels:
            return JdlMasterCompleteness.OBSERVED_PRINTED_MASTER
        if JdlMasterCompleteness.PARTIAL_MASTER in levels:
            return JdlMasterCompleteness.PARTIAL_MASTER
        return JdlMasterCompleteness.OBSERVED_USED_MASTER

    @staticmethod
    def _observe_side(
        row: list[str],
        account_code_index: int,
        account_name_index: int,
        account_formal_index: int,
        subaccount_code_index: int,
        subaccount_name_index: int,
        accounts: list[JdlAccountIdentity],
        subaccounts: list[JdlObservedSubaccount],
        observation_issues: set[str],
    ) -> None:
        code, name, formal_name = (
            row[account_code_index].strip(),
            row[account_name_index].strip(),
            row[account_formal_index].strip(),
        )
        if any((code, name, formal_name)) and not all((code, name, formal_name)):
            observation_issues.add("INCOMPLETE_ACCOUNT_IDENTITY")
            code = name = formal_name = ""
        if code:
            accounts.append(JdlAccountIdentity(name, code, name, formal_name))
        sub_code = row[subaccount_code_index].strip()
        sub_name = row[subaccount_name_index].strip()
        if bool(sub_code) != bool(sub_name):
            observation_issues.add("INCOMPLETE_SUBACCOUNT_IDENTITY")
            sub_code = sub_name = ""
        if sub_code:
            if not code:
                observation_issues.add("SUBACCOUNT_PARENT_UNRESOLVED")
            else:
                subaccounts.append(
                    JdlObservedSubaccount(code, name, sub_code, sub_name)
                )

    @staticmethod
    def _observe_department(
        code: str,
        name: str,
        departments: list[JdlObservedDepartment],
        observation_issues: set[str],
    ) -> None:
        code = code.strip()
        name = name.strip()
        if code == "0" and not name:
            return
        if bool(code) != bool(name):
            observation_issues.add("INCOMPLETE_DEPARTMENT_IDENTITY")
            return
        if code:
            departments.append(JdlObservedDepartment(code, name))

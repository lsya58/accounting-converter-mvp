from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterConflict,
    JdlMasterObservation,
    JdlMasterSourceEvidence,
    JdlObservedSubaccount,
    JdlPrintedAccount,
)


class JdlAccountListPdfParseError(ValueError):
    pass


@dataclass(frozen=True)
class JdlAccountListTextPage:
    page_number: int
    text: str


class JdlAccountListPdfTextParser:
    """Parses text-layer output from the observed JDL account-list PDF."""

    _CODED_ROW = re.compile(
        r"^\s*(?P<code>\d{3,4})\s{2}"
        r"(?P<name>.+?)\s{2,}"
        r"(?P<abbreviation>[借貸][^\s]*)\s*"
        r"(?P<use>[○×])(?P<tail>.*)$"
    )
    _PARENT_ROW = re.compile(
        r"^\s*(?P<code>\d{3,4})-\s+"
        r"(?P<name>.+?)\s{2,}"
        r"(?P<abbreviation>[借貸][^\s]*)\s*"
        r"(?P<use>[○×])(?P<tail>.*)$"
    )
    _SUBACCOUNT_ROW = re.compile(
        r"^\s*-(?P<code>\d{4})\s+"
        r"(?P<name>\S(?:.*?\S)?)\s{2,}"
        r"(?P<balance>[借貸])"
        r"(?P<tail>\s+(?:仕\s+入|売\s+上)\s+(?:固定|無))?\s*$"
    )
    _SUBACCOUNT_LIKE_ROW = re.compile(r"^\s*-\d")
    _UNCODED_ROW = re.compile(
        r"^\s{12,}(?P<name>[^\s].*?)\s{2,}"
        r"(?P<abbreviation>[借貸][^\s]*)\s*"
        r"(?P<use>[○×])(?P<tail>.*)$"
    )
    _CODE_OR_SUBACCOUNT_PREFIX = re.compile(
        r"^\s*(?:\d{3,4}(?:-|\s)|-\d)"
    )
    _REQUIRED_HEADER_LABELS = (
        "勘定科目",
        "略名称",
        "使用",
        "課区",
        "税区",
        "入力",
        "固変",
        "比率",
        "説明",
    )

    def parse_pages(
        self,
        pages: Iterable[JdlAccountListTextPage],
        *,
        source_sha256: str,
        acquisition_method: str,
        human_observed: bool,
    ) -> JdlMasterObservation:
        page_items = tuple(pages)
        if not page_items:
            raise JdlAccountListPdfParseError("PDF text layerにpageがありません。")
        expected_numbers = tuple(range(1, len(page_items) + 1))
        if tuple(item.page_number for item in page_items) != expected_numbers:
            raise JdlAccountListPdfParseError("PDF pageが連続していません。")

        accounts: list[JdlPrintedAccount] = []
        subaccounts: list[JdlObservedSubaccount] = []
        uncoded_count = 0
        for page in page_items:
            lines = page.text.splitlines()
            if not self._has_expected_header(lines):
                raise JdlAccountListPdfParseError(
                    f"page {page.page_number} の科目一覧headerを確認できません。"
                )
            if not self._has_page_number(lines, page.page_number):
                raise JdlAccountListPdfParseError(
                    f"page {page.page_number} のpage番号を確認できません。"
                )
            parent: tuple[str, str, str] | None = None
            for line in lines:
                parent_row = self._PARENT_ROW.match(line)
                if parent_row:
                    account = self._printed_account(parent_row)
                    accounts.append(account)
                    parent = (account.code, account.name, account.normal_balance)
                    continue
                subaccount = self._SUBACCOUNT_ROW.match(line)
                if subaccount:
                    if parent is None:
                        raise JdlAccountListPdfParseError(
                            f"page {page.page_number} に親未解決の補助候補行があります。"
                        )
                    balance = (
                        "DEBIT"
                        if subaccount.group("balance") == "借"
                        else "CREDIT"
                    )
                    if balance != parent[2]:
                        raise JdlAccountListPdfParseError(
                            f"page {page.page_number} の補助候補と親科目の借貸が一致しません。"
                        )
                    subaccounts.append(
                        JdlObservedSubaccount(
                            parent_account_code=parent[0],
                            parent_account_name=parent[1],
                            code=subaccount.group("code"),
                            name=subaccount.group("name").strip(),
                            evidence_scope="PRINTED_EXPLICIT_PARENT",
                        )
                    )
                    continue
                if self._SUBACCOUNT_LIKE_ROW.match(line):
                    raise JdlAccountListPdfParseError(
                        f"page {page.page_number} に形式不正な補助候補行があります。"
                    )
                parent = None
                coded = self._CODED_ROW.match(line)
                if coded:
                    accounts.append(self._printed_account(coded))
                    continue
                uncoded = self._UNCODED_ROW.match(line)
                if uncoded:
                    uncoded_count += 1
                    continue
                if (
                    ("○" in line or "×" in line)
                    and not self._CODE_OR_SUBACCOUNT_PREFIX.match(line)
                ):
                    # Printed rows without an explicit code are observations only.
                    uncoded_count += 1
                    continue
                if "○" in line or "×" in line:
                    raise JdlAccountListPdfParseError(
                        f"page {page.page_number} に解析不能な科目候補行があります。"
                    )

        if not accounts:
            raise JdlAccountListPdfParseError("code付き科目行がありません。")
        completeness = (
            JdlMasterCompleteness.OBSERVED_PRINTED_MASTER
            if uncoded_count > 0
            else JdlMasterCompleteness.PARTIAL_MASTER
        )
        observation = JdlMasterObservation(
            accounts=(),
            subaccounts=tuple(subaccounts),
            departments=(),
            sources=(
                JdlMasterSourceEvidence(
                    sha256=source_sha256,
                    source_kind="JDL_IBEX_ACCOUNT_LIST_PDF_TEXT_LAYER_OBSERVED",
                    data_record_count=len(accounts),
                    page_count=len(page_items),
                    acquisition_method=acquisition_method,
                    human_observed=human_observed,
                ),
            ),
            completeness=completeness,
            printed_accounts=tuple(accounts),
            excluded_uncoded_printed_row_count=uncoded_count,
        )
        return self._validate_identity_conflicts(observation)

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _has_expected_header(self, lines: list[str]) -> bool:
        for line in lines:
            normalized = re.sub(r"\s+", "", line)
            if all(label in normalized for label in self._REQUIRED_HEADER_LABELS):
                return True
        return False

    @staticmethod
    def _printed_account(match: re.Match[str]) -> JdlPrintedAccount:
        abbreviation = match.group("abbreviation")
        return JdlPrintedAccount(
            code=match.group("code"),
            name=match.group("name").strip(),
            abbreviation=abbreviation[1:],
            normal_balance=("DEBIT" if abbreviation.startswith("借") else "CREDIT"),
            enabled=match.group("use") == "○",
            has_observed_setting_values=bool(match.group("tail")[:32].strip()),
        )

    @staticmethod
    def _has_page_number(lines: list[str], expected: int) -> bool:
        return any(line.strip() == str(expected) for line in lines[:5])

    @staticmethod
    def _validate_identity_conflicts(
        observation: JdlMasterObservation,
    ) -> JdlMasterObservation:
        code_values: dict[str, set[tuple[str, str]]] = {}
        name_values: dict[str, set[str]] = {}
        for item in observation.printed_accounts:
            code_values.setdefault(item.code, set()).add((item.name, item.abbreviation))
            name_values.setdefault(item.name, set()).add(item.code)
        conflicts = [
            JdlMasterConflict("PRINTED_ACCOUNT_CODE_CONFLICT")
            for values in code_values.values()
            if len(values) > 1
        ]
        conflicts.extend(
            JdlMasterConflict("PRINTED_ACCOUNT_NAME_CONFLICT")
            for values in name_values.values()
            if len(values) > 1
        )
        subaccount_codes: dict[tuple[str, str], set[str]] = {}
        subaccount_names: dict[tuple[str, str], set[str]] = {}
        subaccount_identity_counts = Counter(
            (
                item.parent_account_code,
                item.code,
                item.name,
            )
            for item in observation.subaccounts
        )
        for item in observation.subaccounts:
            subaccount_codes.setdefault(
                (item.parent_account_code, item.code), set()
            ).add(item.name)
            subaccount_names.setdefault(
                (item.parent_account_code, item.name), set()
            ).add(item.code)
        conflicts.extend(
            JdlMasterConflict("SUBACCOUNT_CODE_CONFLICT")
            for values in subaccount_codes.values()
            if len(values) > 1
        )
        conflicts.extend(
            JdlMasterConflict("SUBACCOUNT_NAME_CONFLICT")
            for values in subaccount_names.values()
            if len(values) > 1
        )
        conflicts.extend(
            JdlMasterConflict("SUBACCOUNT_DUPLICATE")
            for count in subaccount_identity_counts.values()
            if count > 1
        )
        if conflicts:
            return JdlMasterObservation(
                accounts=observation.accounts,
                subaccounts=observation.subaccounts,
                departments=observation.departments,
                sources=observation.sources,
                conflicts=tuple(conflicts),
                completeness=JdlMasterCompleteness.PARTIAL_MASTER,
                printed_accounts=observation.printed_accounts,
                excluded_uncoded_printed_row_count=(
                    observation.excluded_uncoded_printed_row_count
                ),
            )
        return observation

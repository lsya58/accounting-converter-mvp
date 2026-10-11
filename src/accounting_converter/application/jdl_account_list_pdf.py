from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterConflict,
    JdlMasterObservation,
    JdlMasterSourceEvidence,
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
    _UNCODED_ROW = re.compile(
        r"^\s{12,}(?P<name>[^\s].*?)\s{2,}"
        r"(?P<abbreviation>[借貸][^\s]*)\s*"
        r"(?P<use>[○×])(?P<tail>.*)$"
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
            for line in lines:
                coded = self._CODED_ROW.match(line)
                if coded:
                    abbreviation = coded.group("abbreviation")
                    accounts.append(
                        JdlPrintedAccount(
                            code=coded.group("code"),
                            name=coded.group("name").strip(),
                            abbreviation=abbreviation[1:],
                            normal_balance=(
                                "DEBIT" if abbreviation.startswith("借") else "CREDIT"
                            ),
                            enabled=coded.group("use") == "○",
                            has_observed_setting_values=bool(
                                coded.group("tail")[:32].strip()
                            ),
                        )
                    )
                    continue
                uncoded = self._UNCODED_ROW.match(line)
                if uncoded:
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
            if len(page_items) == 5 and uncoded_count > 0
            else JdlMasterCompleteness.PARTIAL_MASTER
        )
        observation = JdlMasterObservation(
            accounts=(),
            subaccounts=(),
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

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
    JdlObservedDepartment,
    JdlPrintedDepartment,
)


class JdlDepartmentListPdfParseError(ValueError):
    pass


@dataclass(frozen=True)
class JdlDepartmentListTextPage:
    page_number: int
    text: str


class JdlDepartmentListPdfTextParser:
    """Parses text-layer output from the observed JDL department-list PDF."""

    _ROW = re.compile(
        r"^\s*(?:(?P<aggregation>\S.*?)\s{2,})?"
        r"(?P<code>\d+)\s{2,}"
        r"(?P<name>\S.*?)\s{2,}"
        r"(?P<abbreviation>\S.*?)\s{2,}"
        r"(?:(?P<allocation_source>\S.*?)\s{2,})?"
        r"(?P<allocation_basis>\d+(?:\.\d+)?)\s+"
        r"(?P<estimated_profit_rate>\d+(?:\.\d+)?)\s*$"
    )
    _ROW_LIKE = re.compile(r"^\s*(?:\S+\s{2,})?\d+")
    _REQUIRED_LABELS = (
        "部門情報一覧",
        "集計部門",
        "コード",
        "名称",
        "略名称",
        "配賦元",
        "配賦基準",
        "利益率",
    )

    def parse_pages(
        self,
        pages: Iterable[JdlDepartmentListTextPage],
        *,
        source_sha256: str,
        acquisition_method: str,
        human_observed: bool,
    ) -> JdlMasterObservation:
        page_items = tuple(pages)
        if not page_items:
            raise JdlDepartmentListPdfParseError("PDF text layerにpageがありません。")
        if tuple(item.page_number for item in page_items) != tuple(
            range(1, len(page_items) + 1)
        ):
            raise JdlDepartmentListPdfParseError("PDF pageが連続していません。")

        printed: list[JdlPrintedDepartment] = []
        for page in page_items:
            normalized = re.sub(r"\s+", "", page.text)
            if not all(label in normalized for label in self._REQUIRED_LABELS):
                raise JdlDepartmentListPdfParseError(
                    f"page {page.page_number} の部門一覧headerを確認できません。"
                )
            if f"{page.page_number}頁" not in normalized:
                raise JdlDepartmentListPdfParseError(
                    f"page {page.page_number} のpage番号を確認できません。"
                )
            header_seen = False
            for line in page.text.splitlines():
                compact = re.sub(r"\s+", "", line)
                if "コード" in compact and "略名称" in compact:
                    header_seen = True
                    continue
                if not header_seen:
                    continue
                match = self._ROW.match(line)
                if match:
                    printed.append(
                        JdlPrintedDepartment(
                            code=match.group("code"),
                            name=match.group("name").strip(),
                            abbreviation=match.group("abbreviation").strip(),
                            aggregation_department=(
                                match.group("aggregation") or ""
                            ).strip(),
                            allocation_source=(
                                match.group("allocation_source") or ""
                            ).strip(),
                            allocation_basis=match.group("allocation_basis"),
                            estimated_profit_rate=match.group(
                                "estimated_profit_rate"
                            ),
                        )
                    )
                    continue
                if self._ROW_LIKE.match(line):
                    raise JdlDepartmentListPdfParseError(
                        f"page {page.page_number} に形式不正な部門候補行があります。"
                    )

        if not printed:
            raise JdlDepartmentListPdfParseError("部門行がありません。")

        conflicts = self._identity_conflicts(printed)
        completeness = (
            JdlMasterCompleteness.OBSERVED_PRINTED_MASTER
            if human_observed and not conflicts
            else JdlMasterCompleteness.PARTIAL_MASTER
        )
        return JdlMasterObservation(
            accounts=(),
            subaccounts=(),
            departments=tuple(
                JdlObservedDepartment(item.code, item.name) for item in printed
            ),
            sources=(
                JdlMasterSourceEvidence(
                    sha256=source_sha256,
                    source_kind="JDL_IBEX_DEPARTMENT_LIST_PDF_TEXT_LAYER_OBSERVED",
                    data_record_count=len(printed),
                    page_count=len(page_items),
                    acquisition_method=acquisition_method,
                    human_observed=human_observed,
                ),
            ),
            conflicts=conflicts,
            completeness=completeness,
            printed_departments=tuple(printed),
        )

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _identity_conflicts(
        departments: list[JdlPrintedDepartment],
    ) -> tuple[JdlMasterConflict, ...]:
        code_values: dict[str, set[tuple[str, str]]] = {}
        name_values: dict[str, set[tuple[str, str]]] = {}
        counts = Counter(
            (item.code, item.name, item.abbreviation) for item in departments
        )
        for item in departments:
            code_values.setdefault(item.code, set()).add(
                (item.name, item.abbreviation)
            )
            name_values.setdefault(item.name, set()).add(
                (item.code, item.abbreviation)
            )
        conflicts = [
            JdlMasterConflict("DEPARTMENT_CODE_CONFLICT")
            for values in code_values.values()
            if len(values) > 1
        ]
        conflicts.extend(
            JdlMasterConflict("DEPARTMENT_NAME_CONFLICT")
            for values in name_values.values()
            if len(values) > 1
        )
        conflicts.extend(
            JdlMasterConflict("DEPARTMENT_DUPLICATE")
            for count in counts.values()
            if count > 1
        )
        return tuple(conflicts)

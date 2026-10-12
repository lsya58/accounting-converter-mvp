from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from accounting_converter.application.jdl_account_list_pdf import (
    JdlAccountListPdfParseError,
    JdlAccountListPdfTextParser,
    JdlAccountListTextPage,
)
from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservation,
    JdlMasterSourceEvidence,
    JdlObservedSubaccount,
    JdlPrintedAccount,
)


class JdlAccountPdfDraftError(ValueError):
    pass


class PdfTextExtractor(Protocol):
    def extract_pages(self, path: Path) -> tuple[str, ...]: ...


class PypdfTextExtractor:
    def extract_pages(self, path: Path) -> tuple[str, ...]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            return tuple(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise JdlAccountPdfDraftError(
                "JDL科目一覧PDFの文字情報を読み取れませんでした。"
            ) from exc


@dataclass(frozen=True)
class JdlAccountPdfDraft:
    observation: JdlMasterObservation
    source_sha256: str
    product: str = "JDL IBEX 出納帳"
    version: str = "35.5"

    @property
    def classification(self) -> JdlMasterCompleteness:
        return self.observation.completeness


class JdlAccountPdfDraftStore:
    SCHEMA_VERSION = "1"
    DOCUMENT_TYPE = "JDL_ACCOUNT_PDF_CONTEXT_DRAFT"

    def __init__(self, extractor: PdfTextExtractor | None = None) -> None:
        self.extractor = extractor or PypdfTextExtractor()
        self.parser = JdlAccountListPdfTextParser()

    def import_pdf(self, source: Path, destination: Path) -> JdlAccountPdfDraft:
        if destination.exists():
            raise JdlAccountPdfDraftError("保存先に既存のJDL読込結果があります。")
        raw = source.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        texts = self.extractor.extract_pages(source)
        try:
            observation = self.parser.parse_pages(
                tuple(
                    JdlAccountListTextPage(index, text)
                    for index, text in enumerate(texts, 1)
                ),
                source_sha256=source_hash,
                acquisition_method="JDL account-list PDF selected in desktop app",
                human_observed=True,
            )
        except JdlAccountListPdfParseError as exc:
            raise JdlAccountPdfDraftError(
                "JDL科目一覧PDFの構造を安全に確認できませんでした。"
            ) from exc
        if observation.conflicts:
            raise JdlAccountPdfDraftError(
                "JDL科目一覧に重複または矛盾があるため読み込めません。"
            )
        enabled_names: dict[str, set[str]] = {}
        for item in observation.printed_accounts:
            if item.enabled:
                enabled_names.setdefault(item.name, set()).add(item.code)
        if any(len(codes) > 1 for codes in enabled_names.values()):
            raise JdlAccountPdfDraftError(
                "同じ名称のJDL科目を安全に区別できないため読み込めません。"
            )
        draft = JdlAccountPdfDraft(observation, source_hash)
        self._atomic_write(destination, self._to_dict(draft))
        return draft

    def load(self, path: Path) -> JdlAccountPdfDraft:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") != self.SCHEMA_VERSION
                or payload.get("document_type") != self.DOCUMENT_TYPE
            ):
                raise ValueError("unsupported draft")
            observation = JdlMasterObservation(
                accounts=(),
                subaccounts=tuple(
                    JdlObservedSubaccount(**item)
                    for item in payload.get("subaccounts", [])
                ),
                departments=(),
                sources=(
                    JdlMasterSourceEvidence(
                        sha256=str(payload["source_sha256"]),
                        source_kind="JDL_IBEX_ACCOUNT_LIST_PDF_TEXT_LAYER_OBSERVED",
                        data_record_count=len(payload["printed_accounts"]),
                        page_count=int(payload["page_count"]),
                        acquisition_method="JDL account-list PDF selected in desktop app",
                        human_observed=True,
                    ),
                ),
                completeness=JdlMasterCompleteness(payload["classification"]),
                printed_accounts=tuple(
                    JdlPrintedAccount(**item) for item in payload["printed_accounts"]
                ),
                excluded_uncoded_printed_row_count=int(
                    payload["excluded_uncoded_printed_row_count"]
                ),
            )
            return JdlAccountPdfDraft(
                observation=observation,
                source_sha256=str(payload["source_sha256"]),
                product=str(payload["product"]),
                version=str(payload["version"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JdlAccountPdfDraftError(
                "保存されたJDL科目一覧を読み込めません。"
            ) from exc

    def is_draft(self, path: Path) -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("document_type") == self.DOCUMENT_TYPE
        except Exception:
            return False

    def _to_dict(self, draft: JdlAccountPdfDraft) -> dict[str, object]:
        observation = draft.observation
        return {
            "schema_version": self.SCHEMA_VERSION,
            "document_type": self.DOCUMENT_TYPE,
            "product": draft.product,
            "version": draft.version,
            "classification": observation.completeness.value,
            "source_sha256": draft.source_sha256,
            "page_count": observation.sources[0].page_count,
            "printed_accounts": [
                {
                    "code": item.code,
                    "name": item.name,
                    "abbreviation": item.abbreviation,
                    "normal_balance": item.normal_balance,
                    "enabled": item.enabled,
                    "has_observed_setting_values": item.has_observed_setting_values,
                }
                for item in observation.printed_accounts
            ],
            "subaccounts": [
                {
                    "parent_account_code": item.parent_account_code,
                    "parent_account_name": item.parent_account_name,
                    "code": item.code,
                    "name": item.name,
                    "evidence_scope": item.evidence_scope,
                }
                for item in observation.subaccounts
            ],
            "excluded_uncoded_printed_row_count": (
                observation.excluded_uncoded_printed_row_count
            ),
            "formal_conversion_allowed": False,
        }

    def _atomic_write(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.load(temporary)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

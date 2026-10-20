from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.adapters.input.jdl import (
    JdlMigrationParser,
    jdl_source_tax_key,
)
from accounting_converter.application.jdl_account_list_pdf import (
    JdlAccountListPdfTextParser,
    JdlAccountListTextPage,
)
from accounting_converter.application.company_settings import CompanySettingStatus
from accounting_converter.application.jdl_migration import JdlMigrationPreflight
from accounting_converter.application.jdl_migration_tax_evidence import evidence_for
from accounting_converter.application.jdl_master_identity import (
    observed_master_identity_sha256,
)
from accounting_converter.adapters.output.jdl.models import (
    JdlAccountIdentity,
    JdlTargetContext,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.infrastructure.jdl_account_pdf_draft import PypdfTextExtractor
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


def build_review(source: Path, target_pdf: Path) -> dict[str, object]:
    target_pdf_sha256 = hashlib.sha256(target_pdf.read_bytes()).hexdigest()
    parsed = JdlMigrationParser().parse_path(source)
    pages = PypdfTextExtractor().extract_pages(target_pdf)
    observation = JdlAccountListPdfTextParser().parse_pages(
        tuple(JdlAccountListTextPage(index, text) for index, text in enumerate(pages, 1)),
        source_sha256=target_pdf_sha256,
        acquisition_method="local JDL migration review",
        human_observed=True,
    )
    targets = tuple(item for item in observation.printed_accounts if item.enabled)
    by_code = {item.code: item for item in targets}
    by_name: dict[str, list] = defaultdict(list)
    for item in targets:
        by_name[item.name].append(item)

    source_accounts: dict[tuple[str, str], dict[str, str]] = {}
    source_subaccounts: dict[tuple[str, str, str, str], dict[str, str]] = {}
    account_journals: dict[tuple[str, str], set[str]] = defaultdict(set)
    subaccount_journals: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    overflow_rows: list[dict[str, object]] = []
    tax_counts: Counter[tuple[str, str, str]] = Counter()
    for entry in parsed.entries:
        for row_index, row in enumerate(entry.metadata.get("physical_rows", ()), 1):
            length = len(str(row.get("description", "")))
            if length > 32:
                overflow_rows.append({
                    "journal_identifier": f"{entry.id}:row-{row_index}",
                    "current_length": length,
                })
        for line in entry.lines:
            metadata = line.metadata
            code = str(metadata.get("jdl_source_account_code", ""))
            name = str(metadata.get("jdl_source_account_formal_name", "")) or str(
                metadata.get("jdl_source_account_name", "")
            )
            source_accounts[(code, name)] = {"code": code, "name": name}
            account_journals[(code, name)].add(entry.id)
            sub_code = str(metadata.get("jdl_source_subaccount_code", ""))
            sub_name = str(metadata.get("jdl_source_subaccount_name", ""))
            if sub_code or sub_name:
                source_subaccounts[(code, name, sub_code, sub_name)] = {
                    "parent_code": code,
                    "parent_name": name,
                    "source_code": sub_code,
                    "source_name": sub_name,
                    "decision": "HUMAN_REQUIRED",
                    "allowed_choices": ["CREATE_AND_PRESERVE", "PARENT_ONLY_CONFIRMED"],
                }
                subaccount_journals[(code, name, sub_code, sub_name)].add(entry.id)
            if line.tax_info is not None:
                tax_counts[
                    (
                        str(line.tax_info.metadata.get("jdl_tax_scope", "")),
                        str(line.tax_info.metadata.get("jdl_tax_category", "")),
                        str(line.tax_info.metadata.get("jdl_tax_input_method", "")),
                    )
                ] += 1

    mismatches: list[dict[str, object]] = []
    for (code, name), source_identity in sorted(source_accounts.items()):
        exact = by_code.get(code)
        if exact is not None and exact.name == name:
            continue
        if exact is not None:
            classification = "SAME_CODE_NAME_CHANGED"
            candidates = (exact,)
        elif len(by_name.get(name, ())) == 1:
            classification = "SAME_NAME_CODE_CHANGED"
            candidates = tuple(by_name[name])
        elif by_name.get(name):
            classification = "AMBIGUOUS"
            candidates = tuple(by_name[name])
        else:
            classification = "NONE"
            candidates = ()
        mismatches.append(
            {
                "source": source_identity,
                "classification": classification,
                "target_candidates": [
                    {"code": item.code, "name": item.name} for item in candidates
                ],
                "affected_journal_count": len(account_journals[(code, name)]),
                "disabled_name_match": any(
                    match is not None
                    and match.group("name").strip() == name
                    and match.group("use") == "×"
                    for page in pages
                    for line in page.splitlines()
                    for match in (JdlAccountListPdfTextParser._UNCODED_ROW.match(line),)
                ),
                "decision": "HUMAN_REQUIRED",
            }
        )

    for identity, item in source_subaccounts.items():
        item["affected_journal_count"] = len(subaccount_journals[identity])
        item["target_parent_exact"] = bool(
            (target := by_code.get(identity[0])) is not None
            and target.name == identity[1]
        )
        item["target_candidates"] = []

    source_schema = jdl_ibex_cashbook_migration_input_schema_definition()
    target_schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
    profile = ConversionProfile(
        "private-jdl-migration-review",
        "Private JDL migration review",
        source_schema.identity,
        target_schema.identity,
    )
    context = JdlTargetContext(
        product="JDL IBEX 出納帳",
        version="35.5",
        accounts=frozenset(item.name for item in targets),
        tax_processing_mode=JdlTaxProcessingMode.UNCONFIRMED,
        target_format_identity=target_schema.identity,
        account_master=tuple(
            JdlAccountIdentity(item.name, item.code, item.name, item.name)
            for item in targets
        ),
    )
    preflight = JdlMigrationPreflight().evaluate(
        parsed.entries,
        profile,
        context,
        company_status=CompanySettingStatus.REQUIRES_CONFIRMATION,
    )
    blocker_counts = Counter(item.rule_id for item in preflight.validation_results)

    return {
        "document_type": "JDL_MIGRATION_HUMAN_REVIEW",
        "review_schema_version": "2",
        "not_for_production": True,
        "formal_output_enabled": False,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "target_pdf_sha256": target_pdf_sha256,
        "target_master_identity_sha256": observed_master_identity_sha256(
            observation
        ),
        "source_format_key": source_schema.identity.stable_key,
        "target_format_key": target_schema.identity.stable_key,
        "counts": {
            "logical_journals": len(parsed.entries),
            "physical_rows": parsed.journal_record_count,
            "diagnostic_rows": len(parsed.diagnostic_rows),
            "account_mismatches": len(mismatches),
            "subaccount_identities": len(source_subaccounts),
            "tax_identities": len(tax_counts),
            "description_overflow_rows": len(overflow_rows),
        },
        "account_mismatches": mismatches,
        "subaccounts": list(source_subaccounts.values()),
        "tax": {
            "target_context_confirmation": [
                "product_and_version",
                "taxpayer_status",
                "tax_included_or_excluded",
                "taxation_method",
                "credit_method",
            ],
            "source_identities": [
                _tax_review_item(
                    scope, category, input_method, count, target_pdf_sha256
                )
                for (scope, category, input_method), count in sorted(tax_counts.items())
            ],
        },
        "description": {
            "overflow_row_count": len(overflow_rows),
            "overflow_rows": overflow_rows,
            "policy": "BLOCK_NO_TRUNCATION",
        },
        "current_preflight": {
            "output_allowed": preflight.output_allowed,
            "output_journals": 0,
            "blocker_counts": dict(sorted(blocker_counts.items())),
        },
    }


def _tax_review_item(
    scope: str,
    category: str,
    input_method: str,
    count: int,
    target_pdf_sha256: str,
) -> dict[str, object]:
    source_key = jdl_source_tax_key(scope, category, input_method)
    evidence = evidence_for(source_key, target_pdf_sha256)
    if evidence is not None:
        return {
            "scope": scope,
            "category": category,
            "input_method": input_method,
            "row_count": count,
            "evidence_status": "VERIFIED_BY_REAL_IMPORT",
            "reference_evidence_id": evidence.evidence_id,
            "decision": "HUMAN_CONFIRMATION_REQUIRED",
        }
    reference_id = (
        "EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001"
        if scope == "非売上" and category == ""
        else ""
    )
    return {
        "scope": scope,
        "category": category,
        "input_method": input_method,
        "row_count": count,
        "evidence_status": "REFERENCE_ONLY" if reference_id else "UNVERIFIED",
        "reference_evidence_id": reference_id,
        "decision": "EVIDENCE_AND_HUMAN_CONFIRMATION_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a private JDL migration Human review pack")
    parser.add_argument("source", type=Path)
    parser.add_argument("target_pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    payload = build_review(args.source, args.target_pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

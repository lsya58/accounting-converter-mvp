from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlTargetContextBuilder,
)
from accounting_converter.adapters.output.jdl.models import JdlSubaccountIdentity
from accounting_converter.application.moneyforward_conversion_workflow import MoneyForwardConversionWorkflow
from accounting_converter.application.moneyforward_trade_partner import (
    TRADE_PARTNER_1D1C_EVIDENCE_ID,
)
from accounting_converter.domain.conversion_profile import ConversionProfile, LossPolicy, TRADE_PARTNER_LOSS_POLICY_KEY
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import jdl_ibex_cashbook_official_journal_import_schema_definition, moneyforward_cloud_journal_export_observed_schema


CASE_ID = "trade_partner_1d1c_with_subaccount_description_rev2"
DESCRIPTION = "TEST"
PARTNER = "PARTNER-A"
EXPECTED_DESCRIPTION = "TEST / 取引先:PARTNER-A"


def generate(output_dir: Path, private_root: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve()
    private_root = private_root.resolve()
    if private_root not in output_dir.parents and output_dir != private_root:
        raise ValueError("probe output must stay under data/private")
    paths = {
        "source": output_dir / "source_moneyforward.csv",
        "profile": output_dir / "profile.json",
        "context": output_dir / "context.json",
        "candidate": output_dir / "trade_partner_1d1c_with_subaccount.csv",
        "manifest": output_dir / "trade_partner_1d1c_with_subaccount.manifest.json",
        "result": output_dir / "trade_partner_1d1c_with_subaccount_result.json",
    }
    existing = [path.name for path in paths.values() if path.exists()]
    if existing:
        raise FileExistsError(f"probe output exists: {', '.join(existing)}")
    output_dir.mkdir(parents=True, exist_ok=True)

    context = _context()
    loader = JdlTargetContextLoader()
    context_text = loader.to_json_text(context)
    context_hash = hashlib.sha256(context_text.encode("utf-8")).hexdigest()
    profile = _profile(context_hash)
    source_bytes = _source_bytes()
    paths["source"].write_bytes(source_bytes)
    paths["context"].write_text(context_text, encoding="utf-8")
    paths["profile"].write_text(
        ConversionProfileStore(output_dir).to_json_text(profile), encoding="utf-8"
    )

    prepared = MoneyForwardConversionWorkflow().prepare(
        input_path=paths["source"], output_path=paths["candidate"],
        profile=profile, context=context, company_setting_validated=True,
    )
    result = MoneyForwardConversionWorkflow.execute(prepared)
    if result is None or result.status != "SUCCESS" or not paths["candidate"].is_file():
        raise RuntimeError("formal trade-partner probe generation was blocked")

    manifest = {
        "schema_version": "1", "probe_case": CASE_ID,
        "expected_description": EXPECTED_DESCRIPTION,
        "source_sha256": _hash(paths["source"]),
        "profile_sha256": _hash(paths["profile"]),
        "context_sha256": _hash(paths["context"]),
        "candidate_sha256": _hash(paths["candidate"]),
        "logical_journals": 1, "official_columns": 30,
        "encoding": "CP932", "bom": False, "line_ending": "CRLF",
        "mapping_promotion_allowed": False, "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }
    result_template = {
        "schema_version": "1", "probe_case": CASE_ID,
        "result_status": "UNTESTED", "imported": False,
        "reexport_present": False, "comparison_pass": None,
        "mapping_promotion_allowed": False, "production_allowed": False,
        "NOT_FOR_PRODUCTION": True,
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["result"].write_text(json.dumps(result_template, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths


def _context():
    result = JdlTargetContextBuilder().build(
        target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        product="JDL IBEX 出納帳", version="35.5",
        account_master=(
            JdlAccountIdentity("普通預金", "1311", "普通預金", "普通預金"),
            JdlAccountIdentity("現金", "1111", "現金", "現金"),
        ),
        subaccounts=(
            JdlSubaccountIdentity(
                "普通預金", "テスト銀行", "0001", "0001", "テスト銀行",
                True, "1311", "テスト銀行",
            ),
        ),
        departments=(),
        tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
        department_processing_enabled=False, standard_taxation_confirmed=True,
        individual_credit_method_confirmed=True,
        confirmation_state=JdlContextConfirmationState.CONFIRMED,
        provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        no_fuzzy_matching=True, no_automatic_replacement=True,
    )
    if not result.success or result.context is None:
        raise RuntimeError("synthetic target context is invalid")
    return result.context


def _profile(context_hash: str) -> ConversionProfile:
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    accounts = {
        "普通預金": MappingValue("普通預金", "普通預金", MappingStatus.USER_CONFIRMED, metadata={"target_code": "1311", "target_formal_name": "普通預金"}),
        "現金": MappingValue("現金", "現金", MappingStatus.USER_CONFIRMED, metadata={"target_code": "1111", "target_formal_name": "現金"}),
    }
    tax_metadata = {
        "jdl_tax_processing_mode": JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
        "jdl_context_sha256": context_hash, "setup_context_sha256": context_hash,
    }
    return ConversionProfile(
        "mf-jdl-trade-partner-probe-rev2", "Development trade partner probe rev2",
        moneyforward_cloud_journal_export_observed_schema().identity,
        jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        account_mappings=accounts,
        subaccount_context_mappings={
            MappingKey(MappingType.SUBACCOUNT, "MF-TEST-SUB", "普通預金"): MappingValue(
                "MF-TEST-SUB", "テスト銀行", MappingStatus.USER_CONFIRMED,
                "普通預金",
                metadata={
                    "target_code": "0001", "output_code": "0001",
                    "output_name": "テスト銀行",
                    "subaccount_policy": SubaccountPolicy.PRESERVE_SUBACCOUNT.value,
                },
            )
        },
        tax_mappings={
            "対象外": MappingValue("対象外", "", MappingStatus.USER_CONFIRMED, metadata={**tax_metadata, "jdl_tax_scope": "", "jdl_evidence_id": "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"}),
        },
        loss_policy_mappings={
            TRADE_PARTNER_LOSS_POLICY_KEY: MappingValue(
                TRADE_PARTNER_LOSS_POLICY_KEY,
                LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value,
                MappingStatus.USER_CONFIRMED,
                metadata={
                    "jdl_context_sha256": context_hash,
                    "jdl_evidence_id": TRADE_PARTNER_1D1C_EVIDENCE_ID,
                },
            )
        },
        created_at=now, updated_at=now,
        notes="Development-only synthetic trade partner probe rev2 using the verified formal E2E No. 4 structure.",
    )


def _source_bytes() -> bytes:
    row = (
        "1", "2026/11/25", "普通預金", "MF-TEST-SUB", "", PARTNER,
        "対象外", "", "1200", "現金", "", "", "", "対象外",
        "", "1200", DESCRIPTION, "", "",
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
    writer.writerow(row)
    return output.getvalue().encode("cp932")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_reexport(output_dir: Path, reexport: Path) -> dict[str, object]:
    candidate = output_dir / "trade_partner_1d1c_with_subaccount.csv"
    manifest_path = output_dir / "trade_partner_1d1c_with_subaccount.manifest.json"
    result_path = output_dir / "trade_partner_1d1c_with_subaccount_result.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("probe_case") != CASE_ID
        or manifest.get("candidate_sha256") != _hash(candidate)
        or manifest.get("NOT_FOR_PRODUCTION") is not True
    ):
        raise ValueError("probe manifest identity mismatch")
    candidate_rows = _strict_jdl_rows(candidate)
    actual_rows = _strict_jdl_rows(reexport)
    header = candidate_rows[0]
    description_index = header.index("摘要")
    candidate_row = candidate_rows[1] if len(candidate_rows) == 2 else None
    actual = actual_rows[1] if len(actual_rows) == 2 else None
    mismatches = (
        _semantic_mismatches(header, candidate_row, actual)
        if candidate_row is not None and actual is not None
        else ("journal_count",)
    )
    comparison_pass = not mismatches and actual[description_index] == EXPECTED_DESCRIPTION
    payload = {
        "schema_version": "1", "probe_case": CASE_ID,
        "result_status": "PASS" if comparison_pass else "FAIL",
        "imported": True, "reexport_present": True,
        "comparison_pass": comparison_pass,
        "candidate_sha256": _hash(candidate),
        "reexport_sha256": _hash(reexport),
        "expected_journals": 1,
        "reexported_journals": max(0, len(actual_rows) - 1),
        "mismatched_field_count": len(mismatches),
        "evidence_id": TRADE_PARTNER_1D1C_EVIDENCE_ID,
        "round_trip_status": (
            "VERIFIED_BY_REAL_IMPORT" if comparison_pass else "FAILED"
        ),
        "mapping_promotion_allowed": False,
        "production_allowed": False, "NOT_FOR_PRODUCTION": True,
    }
    temp = result_path.with_name(f".{result_path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, result_path)
    return payload


def _strict_jdl_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("BOM is not allowed")
    if not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b""):
        raise ValueError("CRLF is required")
    text = raw.decode("cp932", errors="strict")
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    indexes = [index for index, row in enumerate(rows) if tuple(row) == header]
    if len(indexes) != 1:
        raise ValueError("exact official 30-column header must appear once")
    data = rows[indexes[0] + 1 :]
    if not data or any(len(row) != 30 for row in data):
        raise ValueError("official 30-column data rows are required")
    return [list(header), *data]


def _semantic_mismatches(
    header: list[str], candidate: list[str], actual: list[str]
) -> tuple[str, ...]:
    positions = {name: index for index, name in enumerate(header)}
    normalized = {
        "伝番": lambda left, right: left == "" and right == "0",
        "借方科目": lambda left, right: left == "" and right == "1311",
        "借方科目正式名称": lambda left, right: left == "" and right == "普通預金",
        "借方補助": lambda left, right: left == "0001" and right == "1",
        "借方消費税": lambda left, right: left == "" and right == "0",
        "貸方科目": lambda left, right: left == "" and right == "1111",
        "貸方科目正式名称": lambda left, right: left == "" and right == "現金",
        "貸方消費税": lambda left, right: left == "" and right == "0",
        "借方部門コード": lambda left, right: left == "" and right == "0",
        "貸方部門コード": lambda left, right: left == "" and right == "0",
    }
    mismatches: list[str] = []
    for name, index in positions.items():
        if candidate[index] == actual[index]:
            continue
        accepted = normalized.get(name)
        if accepted is None or not accepted(candidate[index], actual[index]):
            mismatches.append(name)
    return tuple(mismatches)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a development-only trade partner probe")
    parser.add_argument("--output-dir", type=Path, default=Path("data/private/jdl_trade_partner_probe_rev2"))
    parser.add_argument("--reexport", type=Path)
    args = parser.parse_args()
    if args.reexport is not None:
        print(json.dumps(compare_reexport(args.output_dir, args.reexport), ensure_ascii=False, sort_keys=True))
        return 0
    paths = generate(args.output_dir, Path("data/private"))
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import (
    MoneyForwardObservedParser,
)
from accounting_converter.domain.journal import Side
from accounting_converter.domain.mapping import DEFAULT_SUBACCOUNT_SOURCE_VALUE
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


class ExactShapeProbeError(ValueError):
    pass


def generate(
    source: Path,
    config_path: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        config.get("NOT_FOR_PRODUCTION") is not True
        or config.get("production_allowed") is not False
    ):
        raise ExactShapeProbeError("probe safety markers are required")
    entries = MoneyForwardObservedParser().parse_path(source)
    journal_hash = str(config.get("journal_sha256", ""))
    matches = [
        entry
        for entry in entries
        if hashlib.sha256(entry.id.encode("utf-8")).hexdigest() == journal_hash
    ]
    if len(matches) != 1:
        raise ExactShapeProbeError("journal_sha256 must identify exactly one journal")
    entry = matches[0]
    rows = _physical_rows(entry)
    expected_shape = str(config.get("shape", ""))
    shape = _shape(entry)
    if expected_shape != shape:
        raise ExactShapeProbeError("configured shape does not match source journal")
    if shape not in {"1D2C", "10D9C"}:
        raise ExactShapeProbeError("only the two audited pending shapes are accepted")

    output_name = str(config.get("output_name", f"mf_{shape.lower()}_probe.csv"))
    if Path(output_name).name != output_name or not output_name.endswith(".csv"):
        raise ExactShapeProbeError("output_name must be a local CSV filename")
    probe_date = str(config.get("probe_date", ""))
    if re.fullmatch(r"[0-9]{8}", probe_date) is None:
        raise ExactShapeProbeError("probe_date must use YYYYMMDD")
    output = output_dir / output_name
    manifest = output.with_suffix(".manifest.private.json")
    if output.exists() or manifest.exists():
        raise FileExistsError("probe output already exists")

    account_mappings = config.get("account_mappings")
    subaccount_mappings = config.get("subaccount_mappings")
    line_tax_mappings = config.get("line_tax_mappings")
    if not isinstance(account_mappings, dict):
        raise ExactShapeProbeError("account mappings are required")
    if not isinstance(subaccount_mappings, list):
        raise ExactShapeProbeError("subaccount mappings are required")
    if not isinstance(line_tax_mappings, dict):
        raise ExactShapeProbeError("line tax mappings are required")

    target_rows: list[tuple[str, ...]] = []
    descriptions = _descriptions_by_row(entry)
    flags = _compound_flags(len(rows))
    for index, (source_row, debit, credit) in enumerate(rows):
        target_rows.append(
            _target_row(
                flag=flags[index],
                journal_date=probe_date,
                description=descriptions.get(source_row, ""),
                debit=debit,
                credit=credit,
                physical_index=index,
                account_mappings=account_mappings,
                subaccount_mappings=subaccount_mappings,
                line_tax_mappings=line_tax_mappings,
            )
        )

    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    if any(len(row[23]) > 32 for row in target_rows):
        raise ExactShapeProbeError("description exceeds the verified JDL limit")
    payload = _encode((
        ("// MF EXACT SHAPE PROBE / NOT FOR PRODUCTION", *("" for _ in range(29))),
        (f"// 出力期間 ： {probe_date} ～ {probe_date}", *("" for _ in range(29))),
        ("",) * 30,
        header,
        *target_rows,
    ))
    manifest_payload = {
        "schema_version": "1",
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "journal_sha256": journal_hash,
        "shape": shape,
        "source_line_count": len(entry.lines),
        "source_physical_row_count": len(rows),
        "candidate_physical_row_count": len(target_rows),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "import_period": {"start": probe_date, "end": probe_date},
        "strict_comparison_required": True,
        "overwrite_allowed": False,
    }
    manifest_bytes = (
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    _atomic_write_pair(
        (output, payload),
        (manifest, manifest_bytes),
    )
    return output, manifest


def _target_row(
    *,
    flag,
    journal_date,
    description,
    debit,
    credit,
    physical_index,
    account_mappings,
    subaccount_mappings,
    line_tax_mappings,
) -> tuple[str, ...]:
    values = ["" for _ in range(30)]
    values[0] = flag
    values[2] = journal_date
    values[11] = "0" if debit is None else ""
    values[21] = "0" if credit is None else ""
    _write_side(
        values, 3, debit, physical_index, "DEBIT",
        account_mappings, subaccount_mappings, line_tax_mappings,
    )
    _write_side(
        values, 13, credit, physical_index, "CREDIT",
        account_mappings, subaccount_mappings, line_tax_mappings,
    )
    values[23] = description
    if len(values) != 30:
        raise ExactShapeProbeError("JDL probe row must contain 30 columns")
    return tuple(values)


def _write_side(
    values,
    offset,
    line,
    physical_index,
    side,
    account_mappings,
    subaccount_mappings,
    line_tax_mappings,
) -> None:
    if line is None:
        return
    account = account_mappings.get(line.account)
    if not _confirmed(account):
        raise ExactShapeProbeError("every target account mapping must be Human-confirmed")
    values[offset] = str(account["code"])
    values[offset + 1] = str(account["name"])
    values[offset + 2] = str(account.get("formal_name", account["name"]))
    sub_code, sub_name = _target_subaccount(
        line.account, line.sub_account, subaccount_mappings
    )
    values[offset + 3] = sub_code
    values[offset + 4] = sub_name
    tax = line_tax_mappings.get(f"{physical_index}:{side}")
    if not _confirmed(tax):
        raise ExactShapeProbeError("every populated source line needs confirmed tax output")
    values[offset + 5] = str(tax.get("scope", ""))
    values[offset + 6] = str(tax.get("category", ""))
    values[offset + 7] = str(tax.get("input_method", ""))
    values[offset + 8] = str(line.amount)
    values[offset + 9] = str(tax.get("tax_amount", ""))


def _target_subaccount(parent, source_subaccount, mappings) -> tuple[str, str]:
    if source_subaccount is None:
        source_subaccount = DEFAULT_SUBACCOUNT_SOURCE_VALUE
        matches = [
            item for item in mappings
            if item.get("source_parent") == parent
            and item.get("source_subaccount") == source_subaccount
        ]
        if not matches:
            return "", ""
        if len(matches) != 1 or not _confirmed(matches[0]):
            raise ExactShapeProbeError("default subaccount requires one Human-confirmed target")
        mapping = matches[0]
        if mapping.get("policy") != "PRESERVE_SUBACCOUNT" or not mapping.get("target_code") or not mapping.get("target_name"):
            raise ExactShapeProbeError("default subaccount requires an exact target subaccount")
        return str(mapping["target_code"]), str(mapping["target_name"])
    matches = [
        item for item in mappings
        if item.get("source_parent") == parent
        and item.get("source_subaccount") == source_subaccount
    ]
    if len(matches) != 1 or not _confirmed(matches[0]):
        raise ExactShapeProbeError("source subaccount requires one confirmed policy")
    mapping = matches[0]
    policy = mapping.get("policy")
    if policy == "PRESERVE_SUBACCOUNT":
        if not mapping.get("target_code") or not mapping.get("target_name"):
            raise ExactShapeProbeError("preserve policy requires exact target subaccount")
        return str(mapping["target_code"]), str(mapping["target_name"])
    if policy == "PARENT_ONLY_CONFIRMED":
        return "", ""
    raise ExactShapeProbeError("unknown subaccount policy")


def _confirmed(value) -> bool:
    return isinstance(value, dict) and value.get("human_confirmed") is True


def _physical_rows(entry):
    grouped = {}
    for line in entry.lines:
        row = line.metadata.get("moneyforward_source_row_number")
        if not isinstance(row, int):
            raise ExactShapeProbeError("source physical row identity is missing")
        grouped.setdefault(row, {})[line.side] = line
    expected = tuple(entry.metadata.get("physical_row_numbers", ()))
    if tuple(sorted(grouped)) != expected:
        raise ExactShapeProbeError("source physical row grouping is inconsistent")
    return tuple(
        (row, grouped[row].get(Side.DEBIT), grouped[row].get(Side.CREDIT))
        for row in expected
    )


def _descriptions_by_row(entry) -> dict[int, str]:
    descriptions = {
        int(item["row_number"]): str(item["value"])
        for item in entry.metadata.get("moneyforward_descriptions", ())
    }
    return descriptions


def _shape(entry) -> str:
    debit = sum(line.side is Side.DEBIT for line in entry.lines)
    credit = sum(line.side is Side.CREDIT for line in entry.lines)
    return f"{debit}D{credit}C"


def _compound_flags(count: int) -> tuple[str, ...]:
    if count < 2:
        raise ExactShapeProbeError("compound probe requires at least two physical rows")
    return ("1110", *("1100" for _ in range(count - 2)), "1101")


def _encode(rows) -> bytes:
    rows = tuple(tuple(row) for row in rows)
    if any(len(row) != 30 for row in rows):
        raise ExactShapeProbeError("every JDL probe row must contain 30 columns")
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode("cp932", errors="strict")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError("probe output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    Path(temporary).unlink(missing_ok=True)


def _atomic_write_pair(*items: tuple[Path, bytes]) -> None:
    written: list[Path] = []
    try:
        for path, payload in items:
            _atomic_write(path, payload)
            written.append(path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise

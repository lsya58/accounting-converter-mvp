from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path


HEADER_PERIOD = "// 出力期間 ： 20260501 ～ 20260502"
OUTPUT_NAME = "mf_tax_excluded_p05_p07_3181_0001.csv"
PENDING_EVIDENCE_IDS = (
    "PENDING-EVID-MF-JDL-TAX-EXCLUDED-P05-3181-0001-001",
    "PENDING-EVID-MF-JDL-TAX-EXCLUDED-P07-3181-0001-001",
)


def generate(source: Path, output_dir: Path) -> tuple[Path, Path]:
    output = output_dir / OUTPUT_NAME
    manifest = output_dir / "manifest.private.json"
    if output.exists() or manifest.exists():
        raise FileExistsError("probe output already exists")

    rows = _read_rows(source)
    selected = []
    for date_value, debit_code, description in (
        ("20260501", "8471", "MF-TAX-P05-SUB0001"),
        ("20260502", "8481", "MF-TAX-P07-SUB0001"),
    ):
        matches = [
            row for row in rows
            if len(row) == 30 and row[3] == debit_code and row[13] == "3181"
        ]
        if len(matches) != 1:
            raise ValueError(f"source pattern must be unique: {debit_code}/3181")
        row = list(matches[0])
        if row[16] or row[17]:
            raise ValueError("source Evidence row must have blank credit subaccount")
        row[2] = date_value
        row[16] = "0001"
        row[17] = "三井住友カードご本人"
        row[23] = description
        selected.append(row)

    header = next(row for row in rows if row and row[0] == "//識別フラグ")
    output_rows = [
        ["// MF TAX SUBACCOUNT PROBE / NOT FOR PRODUCTION", *("" for _ in range(29))],
        [HEADER_PERIOD, *("" for _ in range(29))],
        ["" for _ in range(30)],
        header,
        *selected,
    ]
    payload = _encode_csv(output_rows)
    _atomic_write(output, payload)
    manifest_payload = {
        "schema_version": "1",
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "route": "MF_TO_JDL",
        "product": "JDL IBEX 出納帳",
        "version": "35.5",
        "tax_context": "TAXABLE_TAX_EXCLUDED/STANDARD/PROPORTIONAL",
        "import_period": {"start": "20260501", "end": "20260502"},
        "journal_count": 2,
        "physical_row_count": 2,
        "target_dependency": {
            "credit_account_code": "3181",
            "credit_subaccount_code": "0001",
        },
        "pending_evidence_ids": list(PENDING_EVIDENCE_IDS),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "strict_comparison_required": True,
    }
    _atomic_write(
        manifest,
        (json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    )
    return output, manifest


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def _encode_csv(rows: list[list[str]]) -> bytes:
    with tempfile.TemporaryFile(mode="w+", encoding="cp932", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerows(rows)
        handle.seek(0)
        return handle.read().encode("cp932")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output, manifest = generate(args.source, args.output_dir)
    print(output)
    print(manifest)


if __name__ == "__main__":
    main()

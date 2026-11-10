"""Record a user's acceptance of the 摘要 trailing-space loss of one JDL round trip (Human only).

Input: the row-level record written by `yayoi_roundtrip_check --record-out`. The acceptance is bound to
that record's candidate / re-export SHA-256 and to its exact rows (descriptions included); any other file
or row set makes it INVALID. Nothing is accepted without --accepted-by, --reference and --accepted-on given
by the person who decided. Never overwrites. Customer data: data/private only.

  PYTHONPATH=src python3 -m accounting_converter.tools.jdl_description_trailing_space_acceptance \\
      --record <record.json> --accepted-by <氏名> --reference <確認記録> --accepted-on YYYY-MM-DD --out <acceptance.json>
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from accounting_converter.application import jdl_description_trailing_space as trailing
from accounting_converter.tools.yayoi_roundtrip_check import RECORD_SCHEMA


def build(record: dict, *, accepted_by: str, reference: str, accepted_on: date) -> dict:
    rows = record.get("rows")
    known = {item.evidence_id for item in trailing.EVIDENCES}
    if (record.get("schema") != RECORD_SCHEMA or not isinstance(rows, list)
            or not set(trailing.evidence_ids_of(rows)) <= known
            or record.get("evidence_ids") != trailing.evidence_ids_of(rows)):
        raise ValueError("not a 摘要 trailing-space record of this Evidence (every row must name its Evidence entry)")
    if not isinstance(rows, list) or not rows or record.get("rows_sha256") != trailing.rows_sha256(rows):
        raise ValueError("the record's rows do not match its rows_sha256")
    if record.get("source_alignment") != "PASS":
        raise ValueError("the record's rows are not traced to the source; nothing to accept")
    if not accepted_by.strip() or not reference.strip():
        raise ValueError("--accepted-by and --reference are required")
    return trailing.acceptance_payload(
        candidate_sha256=record["files"]["candidate"]["sha256"], reexport_sha256=record["files"]["reexport"]["sha256"],
        rows=rows, accepted_by=accepted_by, reference=reference, accepted_on=accepted_on)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--accepted-by", required=True)
    parser.add_argument("--reference", required=True, help="where the decision is documented")
    parser.add_argument("--accepted-on", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if "data/private" not in args.out.resolve().as_posix():
        raise SystemExit("write the acceptance under data/private only")
    payload = build(json.loads(args.record.read_text(encoding="utf-8")), accepted_by=args.accepted_by,
                    reference=args.reference, accepted_on=args.accepted_on)
    with args.out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": args.out.name, "rows": payload["rows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

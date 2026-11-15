"""Diagnose a freee会計 仕訳帳CSV for JDL IBEX 出納帳 35.5 — read-only, DIAGNOSE_ONLY.

    PYTHONPATH=src python3 -m accounting_converter.tools.freee_journal_diagnose --source <freee.csv>

Prints counts and codes only (no accounts, partners, descriptions or amounts). Writes nothing.
Formal READY is always 0: the freee -> JDL direction is not PRODUCTION and no real freee header is
verified. A real freee export is to be diagnosed only from data/private (never committed).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application.freee_diagnosis import diagnose_freee_journal_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    report = diagnose_freee_journal_csv(args.source).to_dict()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["file_readable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

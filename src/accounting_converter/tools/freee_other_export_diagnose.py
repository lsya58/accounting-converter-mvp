"""Describe a freee JDLインポート形式 (9列) / 弥生会計インポート形式 (25列) export — read-only, diagnosis only.

    PYTHONPATH=src python3 -m accounting_converter.tools.freee_other_export_diagnose --format jdl9 --source <file>
    PYTHONPATH=src python3 -m accounting_converter.tools.freee_other_export_diagnose --format yayoi25 --source <file>

Prints format structure as counts and product codes only (no accounts, codes, amounts or
descriptions). Writes nothing, converts nothing, feeds nothing to the existing Yayoi reader.
Whether JDL IBEX 出納帳 35.5 or Yayoi can import the file is NOT checked (unverified).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.application.freee_other_export_diagnosis import diagnose_freee_jdl9, diagnose_freee_yayoi25


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=("jdl9", "yayoi25"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.source.read_bytes()
    result = diagnose_freee_jdl9(raw) if args.format == "jdl9" else diagnose_freee_yayoi25(raw)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=1))
    return 0 if result.readable else 1


if __name__ == "__main__":
    raise SystemExit(main())

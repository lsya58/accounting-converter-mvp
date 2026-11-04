from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class DropDecision:
    accepted_path: Path | None
    message: str

    @property
    def accepted(self) -> bool:
        return self.accepted_path is not None


# Accounting exports arrive as .csv or .txt (e.g. Yayoi). The format is decided
# later from the content, never from the extension; the file is only read.
ACCEPTED_SUFFIXES = frozenset({".csv", ".txt"})


def evaluate_csv_drop(paths: Sequence[Path]) -> DropDecision:
    if len(paths) != 1:
        return DropDecision(None, "CSV / TXT ファイルを1件だけドロップしてください。")
    path = paths[0]
    if not path.is_file():
        return DropDecision(None, "フォルダーは選択できません。CSV / TXT ファイルを選択してください。")
    if path.suffix.lower() not in ACCEPTED_SUFFIXES:
        return DropDecision(None, "CSV または TXT のファイルだけを選択できます。")
    return DropDecision(path, "ファイルを受け付けました。中身から形式を判定します。")

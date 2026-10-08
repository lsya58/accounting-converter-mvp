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


def evaluate_csv_drop(paths: Sequence[Path]) -> DropDecision:
    if len(paths) != 1:
        return DropDecision(None, "CSVファイルを1件だけドロップしてください。")
    path = paths[0]
    if not path.is_file():
        return DropDecision(None, "フォルダーは選択できません。CSVファイルを選択してください。")
    if path.suffix.lower() != ".csv":
        return DropDecision(None, "CSVファイルだけを選択できます。")
    return DropDecision(path, "CSVファイルを受け付けました。")

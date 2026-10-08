from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApplicationPreferences:
    last_company_setting_id: str | None = None
    schema_version: str = "1"


class ApplicationPreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, existing_company_ids: set[str] | None = None) -> ApplicationPreferences:
        if not self.path.exists():
            return ApplicationPreferences()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "1":
                return ApplicationPreferences()
            selected = payload.get("last_company_setting_id")
            if selected is not None and not isinstance(selected, str):
                return ApplicationPreferences()
            if existing_company_ids is not None and selected not in existing_company_ids:
                selected = None
            return ApplicationPreferences(selected)
        except (OSError, json.JSONDecodeError, TypeError):
            return ApplicationPreferences()

    def save(self, preferences: ApplicationPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.tmp")
        try:
            temp.write_text(
                json.dumps(
                    {"schema_version": "1", "last_company_setting_id": preferences.last_company_setting_id},
                    ensure_ascii=False, indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()


def default_preferences_path() -> Path:
    from accounting_converter.infrastructure.conversion_profile_store import default_profile_store_dir

    return default_profile_store_dir().parent / "preferences.json"

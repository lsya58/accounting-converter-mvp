"""Explicit pilot enablement of the screen's JDL round-trip check for routes beyond Phase 1 (Phase 2: Money Forward).

DISABLED BY DEFAULT. The check is offered for a Money Forward company only when a pilot file
`<app data>/jdl_roundtrip_pilot.json` (next to the `companies` folder) lists that company with the setting it was
enabled for. The app never creates, changes or deletes this file: a person writes it for a pilot (for example in an
isolated verification environment). Enabling a pilot is NOT an accountant's approval and registers no Evidence.

An entry applies only when ALL of these equal the resolved company setting:
  company_setting_id, conversion_profile_id, profile_fingerprint, context_fingerprint,
  expected source format key (the Money Forward 仕訳帳 19-column export), expected target format key (JDL 30 columns).
A setting changed after enabling (mapping, JDL Target Context …) no longer matches: the check is not offered.
The entry also names the JDL company's fiscal year end (MM-DD). No default is assumed for any company.

Any problem with the file (unreadable, wrong schema, missing field, bad date) disables every pilot (fail closed).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PILOT_SCHEMA = "jdl-roundtrip-pilot-v1"
PILOT_FILE_NAME = "jdl_roundtrip_pilot.json"
ROUTE_MONEYFORWARD = "MONEYFORWARD"

_FIELDS = ("route", "company_setting_id", "conversion_profile_id", "profile_fingerprint", "context_fingerprint",
           "source_format_key", "target_format_key", "fiscal_year_end")


@dataclass(frozen=True)
class PilotEntry:
    route: str
    company_setting_id: str
    conversion_profile_id: str
    profile_fingerprint: str
    context_fingerprint: str
    source_format_key: str
    target_format_key: str
    fiscal_year_end: str  # MM-DD

    @property
    def fiscal_year_end_month_day(self) -> tuple[int, int]:
        month, day = (int(part) for part in self.fiscal_year_end.split("-"))
        return month, day


def pilot_path(company_store_root: Path) -> Path:
    return Path(company_store_root).parent / PILOT_FILE_NAME


def _valid_month_day(text: str) -> bool:
    try:
        month, day = (int(part) for part in text.split("-"))
        date(2025, month, day)  # a non-leap year: 02-29 cannot define every fiscal year, so it is refused
        date(2024, month, day)
    except (ValueError, TypeError):
        return False
    return len(text) == 5 and text[2] == "-"


def load(path: Path) -> tuple[tuple[PilotEntry, ...], str | None]:
    """(entries, None) or ((), reason code). A missing file is simply "not enabled"."""
    path = Path(path)
    if not path.is_file():
        return (), "PILOT_NOT_ENABLED"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (), "PILOT_FILE_INVALID"
    if not isinstance(payload, dict) or payload.get("schema") != PILOT_SCHEMA or not isinstance(payload.get("pilots"),
                                                                                              list):
        return (), "PILOT_FILE_INVALID"
    entries = []
    for item in payload["pilots"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(name), str) or not item.get(name)
                                             for name in _FIELDS):
            return (), "PILOT_FILE_INVALID"
        if not _valid_month_day(item["fiscal_year_end"]):
            return (), "PILOT_FILE_INVALID"
        entries.append(PilotEntry(**{name: item[name] for name in _FIELDS}))
    return tuple(entries), None


def entry_for(path: Path, resolved, route: str) -> tuple[PilotEntry | None, str | None]:
    """The pilot entry enabling `route` for this resolved company setting, or (None, reason code)."""
    entries, problem = load(path)
    if problem:
        return None, problem
    setting = resolved.setting
    listed = [entry for entry in entries
              if entry.route == route and entry.company_setting_id == str(setting.company_setting_id)]
    if not listed:
        return None, "PILOT_COMPANY_NOT_LISTED"
    for entry in listed:
        if (entry.conversion_profile_id == setting.conversion_profile_id
                and entry.profile_fingerprint == setting.profile_fingerprint
                and entry.context_fingerprint == setting.context_fingerprint
                and entry.source_format_key == setting.expected_source_format_key
                and entry.target_format_key == setting.expected_target_format_key):
            return entry, None
    return None, "PILOT_SETTING_CHANGED"

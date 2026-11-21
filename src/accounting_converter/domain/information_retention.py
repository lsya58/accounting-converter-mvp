"""Source-neutral classification of what happens to each source field on the way to a target.

A parser keeps every value (domain.source_information); a direction then has to say, field by field, whether the
value is carried by the common model, where it would go in the target, or why it cannot go anywhere yet. This module
only holds the vocabulary and the aggregation. The tables that decide a field's status live with the direction
(e.g. application.freee_diagnosis for freee -> JDL), never inside a target serializer, so adding a direction never
changes an existing one.

Statuses (the order is the order shown to the user):
- RETAINED: carried by the common model with a known meaning (date, account, amount, tax cells, description ...).
  Being retained is NOT being output: the target mapping is still a separate decision.
- TARGET_DESTINATION_UNCONFIRMED: the meaning is known, but where the target holds it has no Evidence yet
  (counterparty, closing marker, tax category -> JDL 課区/税区 ...).
- MEANING_UNCONFIRMED: the value exists but its meaning is not settled (an unknown column, a value never observed,
  a raw flag whose relation to the target is unverified ...).
- UNSUPPORTED: the target has no place for it (no column); it is reported as non-retained information, never dropped
  silently.
- AUDIT_ONLY: source identifiers, timestamps and personal data. Kept for tracing the source, never output and never
  printed (personal data).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class RetentionStatus(str, Enum):
    RETAINED = "RETAINED"
    TARGET_DESTINATION_UNCONFIRMED = "TARGET_DESTINATION_UNCONFIRMED"
    MEANING_UNCONFIRMED = "MEANING_UNCONFIRMED"
    UNSUPPORTED = "UNSUPPORTED"
    AUDIT_ONLY = "AUDIT_ONLY"


RETENTION_ORDER: tuple[RetentionStatus, ...] = tuple(RetentionStatus)


@dataclass(frozen=True)
class FieldRetention:
    """One source field (column name, verbatim) and what a direction does with it."""
    field: str
    status: RetentionStatus
    reason: str  # a stable code (e.g. "NO_JDL_COLUMN"); the UI translates it
    journals: int = 0  # journals with a non-blank value in this field
    values: int = 0  # non-blank cells


@dataclass
class RetentionInventory:
    """Field -> status for one source file. A field is listed once; its strongest doubt wins."""
    fields: dict[str, FieldRetention] = field(default_factory=dict)

    def add(self, name: str, status: RetentionStatus, reason: str, *, journals: int, values: int) -> None:
        """Adds one observation (e.g. one journal). Counts add up; the more doubtful status wins
        (MEANING_UNCONFIRMED over RETAINED ...), so one unobserved value marks the whole field."""
        current = self.fields.get(name)
        if current is None:
            self.fields[name] = FieldRetention(name, status, reason, journals, values)
            return
        if _DOUBT[status] > _DOUBT[current.status]:
            current = FieldRetention(name, status, reason, current.journals, current.values)
        self.fields[name] = FieldRetention(
            name, current.status, current.reason, current.journals + journals, current.values + values,
        )

    def by_status(self) -> dict[RetentionStatus, tuple[FieldRetention, ...]]:
        grouped: dict[RetentionStatus, list[FieldRetention]] = {status: [] for status in RETENTION_ORDER}
        for item in self.fields.values():
            grouped[item.status].append(item)
        return {status: tuple(sorted(items, key=lambda i: i.field)) for status, items in grouped.items()}

    def counts(self) -> Counter:
        return Counter(item.status.value for item in self.fields.values())


# How much doubt a status carries (used only to merge two observations of the same field).
_DOUBT = {
    RetentionStatus.AUDIT_ONLY: 0,
    RetentionStatus.RETAINED: 1,
    RetentionStatus.TARGET_DESTINATION_UNCONFIRMED: 2,
    RetentionStatus.UNSUPPORTED: 3,
    RetentionStatus.MEANING_UNCONFIRMED: 4,
}

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnDefinition:
    name: str
    required: bool = False
    max_length: int | None = None


@dataclass(frozen=True)
class FormatProfile:
    software: str
    product: str
    version: str
    format_id: str
    encoding: str
    delimiter: str = ","
    date_format: str | None = None
    journal_structure: str | None = None
    columns: tuple[ColumnDefinition, ...] = field(default_factory=tuple)

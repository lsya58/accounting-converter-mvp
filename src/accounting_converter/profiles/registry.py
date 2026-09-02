from __future__ import annotations

from dataclasses import dataclass

from accounting_converter.domain.format_metadata import (
    EvidenceLevel,
    FormatDirection,
    SchemaDefinition,
)


@dataclass(frozen=True)
class FormatCandidate:
    schema: SchemaDefinition
    confidence: float
    reasons: tuple[str, ...]


class FormatRegistry:
    def __init__(self, schemas: tuple[SchemaDefinition, ...] = ()) -> None:
        self._schemas: dict[str, SchemaDefinition] = {}
        for schema in schemas:
            self.register(schema)

    def register(self, schema: SchemaDefinition) -> None:
        self._schemas[schema.identity.stable_key] = schema

    def all(self) -> tuple[SchemaDefinition, ...]:
        return tuple(self._schemas.values())

    def find(
        self,
        vendor: str | None = None,
        product: str | None = None,
        direction: FormatDirection | None = None,
        evidence_level: EvidenceLevel | None = None,
    ) -> tuple[SchemaDefinition, ...]:
        results = []
        for schema in self._schemas.values():
            identity = schema.identity
            if vendor is not None and identity.vendor != vendor:
                continue
            if product is not None and identity.product != product:
                continue
            if direction is not None and identity.direction is not direction:
                continue
            if evidence_level is not None and identity.evidence_level is not evidence_level:
                continue
            results.append(schema)
        return tuple(results)

    def find_candidates(self, file_observation: object) -> tuple[FormatCandidate, ...]:
        scored: list[FormatCandidate] = []
        observed_column_count = getattr(file_observation, "dominant_column_count", None)
        observed_delimiter = getattr(file_observation, "delimiter", None)
        observed_encoding = getattr(file_observation, "encoding", None)
        for schema in self._schemas.values():
            score = 0.0
            reasons: list[str] = []
            if observed_column_count is not None and schema.column_count is not None:
                if observed_column_count == schema.column_count:
                    score += 0.5
                    reasons.append("column_count_match")
                else:
                    reasons.append("column_count_difference")
            if observed_delimiter and schema.delimiter == observed_delimiter:
                score += 0.2
                reasons.append("delimiter_match")
            if (
                observed_encoding
                and observed_encoding in schema.capabilities.encoding_candidates
            ):
                score += 0.2
                reasons.append("encoding_candidate_match")
            if schema.identity.evidence_level is EvidenceLevel.VERIFIED_BY_REAL_IMPORT:
                score += 0.1
                reasons.append("verified_schema")
            if score > 0:
                scored.append(
                    FormatCandidate(
                        schema=schema,
                        confidence=min(score, 0.95),
                        reasons=tuple(reasons),
                    )
                )
        return tuple(sorted(scored, key=lambda candidate: candidate.confidence, reverse=True))

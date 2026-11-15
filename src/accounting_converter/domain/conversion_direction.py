"""Which (source format -> target format) directions exist, and how far each is verified.

A direction is a product decision backed by Evidence, not a capability of the code: parsing a
source and serializing a target does not make the pair safe. Only a direction at
`DirectionStage.PRODUCTION` may ever produce a formal READY; every other stage is diagnosis /
probe / research only, whatever the per-journal checks say.

The existing production directions are listed for completeness; their gating stays where it is
(adapter registry, CompanySetting, target Evidence). This table never widens them, and a
direction absent from it is NOT_STARTED.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DirectionStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"  # nothing built; decision record only
    RESEARCH = "RESEARCH"  # public specification studied, no parser
    DIAGNOSE_ONLY = "DIAGNOSE_ONLY"  # source parsed and diagnosed; no target output at all
    PROBE_ONLY = "PROBE_ONLY"  # NOT_FOR_PRODUCTION probe files for real target Evidence
    PRODUCTION = "PRODUCTION"  # formal output, gated by real round-trip Evidence


@dataclass(frozen=True)
class ConversionDirection:
    key: str
    source: str  # vendor / product / format, human-readable
    target: str
    stage: DirectionStage
    notes: str = ""

    @property
    def ready_allowed(self) -> bool:
        return self.stage is DirectionStage.PRODUCTION


class DirectionNotProductionError(ValueError):
    pass


KNOWN_DIRECTIONS: tuple[ConversionDirection, ...] = (
    ConversionDirection(
        "moneyforward_journal_19->jdl_ibex_cashbook_35_5",
        "Money Forward クラウド会計 仕訳帳CSV（観測19列）", "JDL IBEX 出納帳 35.5 仕訳CSV",
        DirectionStage.PRODUCTION, "既存。482件 FY2026-05 実機往復 PASS",
    ),
    ConversionDirection(
        "yayoi_journal_report_generic->jdl_ibex_cashbook_35_5",
        "弥生会計 仕訳日記帳 汎用形式", "JDL IBEX 出納帳 35.5 仕訳CSV",
        DirectionStage.PRODUCTION, "既存。会社Aの会社スコープEvidenceに限る",
    ),
    ConversionDirection(
        "yayoi_import_25->jdl_ibex_cashbook_35_5",
        "弥生会計 インポート形式（25列）", "JDL IBEX 出納帳 35.5 仕訳CSV",
        DirectionStage.PRODUCTION, "既存。会社B 80件 実機往復 PASS",
    ),
    ConversionDirection(
        "freee_journal_csv->jdl_ibex_cashbook_35_5",
        "freee会計 仕訳帳CSV（新CSV／旧CSV）", "JDL IBEX 出納帳 35.5 仕訳CSV",
        DirectionStage.DIAGNOSE_ONLY,
        "公開仕様の断片と合成データだけ。実freee出力サンプル・JDL実機Evidenceなし",
    ),
    ConversionDirection(
        "freee_jdl_kaikeinet->jdl_ibex_cashbook_35_5",
        "freee会計 JDL形式（会計net向け）", "JDL IBEX 出納帳 35.5",
        DirectionStage.RESEARCH, "freee公式は会計net対応と記載。IBEX出納帳35.5での取込は未確認",
    ),
    ConversionDirection(
        "jdl_ibex_cashbook->moneyforward",
        "JDL IBEX 出納帳", "Money Forward クラウド会計 仕訳インポート",
        DirectionStage.NOT_STARTED, "2026-10-31 NO-GO（docs/design/jdl_to_mf_decision.md）",
    ),
    ConversionDirection(
        "yayoi->moneyforward", "弥生会計", "Money Forward クラウド会計",
        DirectionStage.NOT_STARTED, "MF公式の移行機能あり",
    ),
    ConversionDirection(
        "moneyforward->yayoi", "Money Forward クラウド会計", "弥生会計",
        DirectionStage.NOT_STARTED, "MFに弥生形式エクスポートあり",
    ),
)

_BY_KEY = {direction.key: direction for direction in KNOWN_DIRECTIONS}


def direction_for(key: str) -> ConversionDirection:
    """The registered direction, or NOT_STARTED for anything not listed (fail-closed)."""
    return _BY_KEY.get(key) or ConversionDirection(key, "", "", DirectionStage.NOT_STARTED, "未登録")


def require_production(key: str) -> ConversionDirection:
    direction = direction_for(key)
    if not direction.ready_allowed:
        raise DirectionNotProductionError(
            f"変換方向 {key} は {direction.stage.value} です。正式READY・正式出力はできません。"
        )
    return direction

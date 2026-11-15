"""Recorded real-JDL results for READY-only outputs (display only, fail-closed).

NOT Evidence. These rows are a hand-transcribed copy of results already written in
docs/development/jdl_real_evidence_log.md and docs/development/ready_only_windows_trial.md. Nothing here is read by
the conversion, READY / BLOCK, approval or audit code (a test enforces that), it registers no Evidence and it is never
written by the app. Adding a row here does not make anything verified: a new real round trip must first be recorded in
the evidence log by the normal procedure, and only then copied here.

A record applies to a run only when ALL of these match the run's own record (its `.ready_only.json`):
  - the SHA-256 of the output CSV bytes (recomputed from the file, and equal to the SHA-256 the record names),
  - the SHA-256 of the source file,
  - the company setting id,
  - the source period,
  - the JDL conditions the output was made for (product / version / tax mode / method / credit method / rounding /
    voucher row limit).
Anything else, or no record at all, is "未確認" (no recorded real-JDL result). That is not a pass and not a failure.
File names and journal counts are never used to decide a result.

kind:
  E2E_ROUNDTRIP          the CSV itself was imported into JDL and re-exported, then reconciled (real end-to-end)
  SUBSET_RECONCILIATION  the CSV was compared with an existing re-export (a subset of another run's round trip);
                         the CSV itself was NOT imported into JDL, so its own end-to-end check is still not done
"""
from __future__ import annotations

from dataclasses import dataclass

E2E_ROUNDTRIP = "E2E_ROUNDTRIP"
SUBSET_RECONCILIATION = "SUBSET_RECONCILIATION"


@dataclass(frozen=True)
class RecordedResult:
    kind: str
    verdict: str            # PASS / FAIL as recorded
    recorded_on: str
    summary: str
    e2e_done: bool          # was THIS CSV imported into JDL and re-exported?
    reference: str
    # Scope the record was made for (all must match the run's own record, see recorded_results)
    company_setting_id: str
    source_period: tuple[str, str]
    jdl_conditions: tuple[tuple[str, object], ...]
    basis: str = "MANUAL_TRANSCRIPTION_OF_DOCS"     # not Evidence


_COMPANY_A = "company-f92affc1f3ed43c8aee36380ab612f9d"
_PERIOD_A = ("2025-08-01", "2026-07-31")
_JDL_A = (("jdl_product", "JDL IBEX 出納帳"), ("jdl_version", "35.5"), ("tax_processing_mode", "TAXABLE_TAX_EXCLUDED"),
          ("taxation_method", "STANDARD"), ("input_tax_credit_method", "PROPORTIONAL"),
          ("rounding", ("CEILING", "HALF_UP")), ("voucher_row_limit", 16))
_SOURCE_A = "7ab406cb9d0c88b3ecac07e55d2586808bdd4e2368df058aeb014e623d0c14a8"

# Keys: (source sha256, output csv sha256).
RECORDED_RESULTS: dict[tuple[str, str], tuple[RecordedResult, ...]] = {
    (_SOURCE_A, "2032c1450bf51debe485d7b7bd2459f6eef24f4d52d63737e78718b4e56af45b"): (
        RecordedResult(
            E2E_ROUNDTRIP, "FAIL", "2026-11-11",
            "2,480仕訳・6,102行をJDLに取込・再Export。説明できない差分1件（伝票1240の売上1円行で、書いた税額0が"
            "再Exportで1）。この出力は旧い診断（READY 2,480）で作成されたもので、現在は使いません。",
            True, "docs/development/jdl_real_evidence_log.md（2026-11-11 READYのみ）",
            _COMPANY_A, _PERIOD_A, _JDL_A),
    ),
    (_SOURCE_A, "0aed42158f009cae151a5922b3c12db7742550f7fe0afb09843f6e2c67d7d178"): (
        RecordedResult(
            SUBSET_RECONCILIATION, "PASS", "2026-11-11",
            "旧2,480の再Exportから伝票1240の2行を除いた部分集合と照合し、説明できない差分0（2,479仕訳・6,100行）。"
            "このCSVは旧2,480の出力から伝票1240の2行を除いたものとバイト一致（2026-11-14に内容で確認）。"
            "摘要末尾空白の許容判断は未記録。",
            False, "docs/development/ready_only_windows_trial.md 7.3",
            _COMPANY_A, _PERIOD_A, _JDL_A),
    ),
}


def _norm(value):
    return tuple(value) if isinstance(value, list) else value


def recorded_results(source_sha256: str | None, output_sha256: str | None, *, manifest: dict | None = None,
                     company_setting_id: str | None = None) -> tuple[RecordedResult, ...]:
    """The records that apply to this exact run, or () (= 未確認). Fail-closed: a missing or different value of any
    kind (sha, company, period, JDL condition, a run record that does not name this output's bytes) gives ()."""
    if not source_sha256 or not output_sha256 or not isinstance(manifest, dict) or not company_setting_id:
        return ()
    if (manifest.get("output") or {}).get("sha256") != output_sha256:
        return ()                                   # the record does not describe the bytes on disk
    if (manifest.get("source") or {}).get("sha256") != source_sha256 or manifest.get("company_setting_id") != company_setting_id:
        return ()
    period = tuple((manifest.get("source") or {}).get("period") or ())
    settings = manifest.get("settings") or {}
    found = []
    for record in RECORDED_RESULTS.get((source_sha256, output_sha256), ()):
        if (record.company_setting_id == company_setting_id and record.source_period == period
                and all(_norm(settings.get(key)) == _norm(value) for key, value in record.jdl_conditions)):
            found.append(record)
    return tuple(found)


def e2e_text(results: tuple[RecordedResult, ...]) -> str:
    """One line for 'was THIS output checked end-to-end in JDL?' (never inferred from a subset check)."""
    e2e = [r for r in results if r.e2e_done]
    if e2e:
        return " / ".join(f"実機E2E {r.verdict}（{r.recorded_on}）" for r in e2e)
    if results:
        return "実機E2E 未実施（" + "、".join(f"{_KIND_LABELS[r.kind]} {r.verdict}" for r in results) + "）"
    return "実機での確認記録なし（未確認）"


_KIND_LABELS = {E2E_ROUNDTRIP: "実機往復", SUBSET_RECONCILIATION: "既存再Exportとの部分集合照合"}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)

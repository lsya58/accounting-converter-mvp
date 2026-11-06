# Agent instructions

Before changing code or asking a Human for JDL work, read:

1. [docs/development/mf_jdl_evidence_driven_workflow.md](docs/development/mf_jdl_evidence_driven_workflow.md) — how work is planned and judged here (goal-first, HUMAN / SYSTEM_EVIDENCE / SYSTEM_IMPLEMENTATION, composable Evidence, probe ≠ production, strict comparison). Follow its "For AI coding agents" section.
2. [docs/development/jdl_real_evidence_log.md](docs/development/jdl_real_evidence_log.md) — real JDL operations already done. Never re-request one marked `repeat_required: NO`.
3. [docs/development/current_evidence_status.md](docs/development/current_evidence_status.md) — current READY counts and blockers. Recompute; do not copy old counts.

Current phase (counts live only in current_evidence_status.md):

- MF→JDL Evidence acquisition is finished. Do not generate new probes.
- Do not re-acquire FY2026 Evidence or repeat real JDL operations 0873–0878 for the same scope.
- The only critical path is the FY2027 real round-trip ("Remaining critical path" in current_evidence_status.md).
- Foundation freeze (see docs/product/開発ロードマップ.md): lifted only for Yayoi, because real Yayoi data arrived (2026-11-01). Other abstraction or renaming ahead of real need is still frozen.

- Yayoi company A (Buddies): the 2026-11-05 campaign Evidence is registered **only for one exact company scope** (`adapters/output/jdl/scoped_evidence.py`: 税抜・原則・一括比例・売上切上げ/仕入四捨五入・振替伝票入力行数16). Data table: `scoped_evidence_registry.py` (regenerate with `tools/build_scoped_evidence_registry.py`). It is tried only after the existing MF/ACT Evidence fails. Do not widen it by similarity; extend it only with new real round trips. Diagnose with `tools/yayoi_whatif_readiness.py` (scratch copy only). Details: docs/development/yayoi_buddies_evidence_campaign.md.

Design rule: JDL target Evidence is keyed by what JDL receives, never by the source format or source tax name (see the workflow document).

Hard rules: never auto-confirm accounting judgments; never track `data/private/`; commit or push only when asked.

Checks: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall -q src tests`, `git diff --check`, `git ls-files data/private | wc -l` must be 0.

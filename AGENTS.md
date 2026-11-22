# Agent instructions

Before changing code or asking a Human for JDL work, read:

1. [docs/development/mf_jdl_evidence_driven_workflow.md](docs/development/mf_jdl_evidence_driven_workflow.md) — how work is planned and judged here (goal-first, HUMAN / SYSTEM_EVIDENCE / SYSTEM_IMPLEMENTATION, composable Evidence, probe ≠ production, strict comparison). Follow its "For AI coding agents" section.
2. [docs/development/jdl_real_evidence_log.md](docs/development/jdl_real_evidence_log.md) — real JDL operations already done. Never re-request one marked `repeat_required: NO`.
3. [docs/development/current_evidence_status.md](docs/development/current_evidence_status.md) — which Evidence exists and how it is judged (and the MF→JDL 482-journal state).
4. [docs/development/PROJECT_STATUS.md](docs/development/PROJECT_STATUS.md) §1 — the ONLY place for Yayoi company A's current values (journals, formal READY, BLOCK, accountant approvals, migration status). Recompute before updating it; do not copy old counts.

Sources of truth: current company A values → PROJECT_STATUS.md §1; Evidence existence and judgement → current_evidence_status.md; real JDL operations → jdl_real_evidence_log.md. Every other count in the docs is dated history: keep it with its date, never delete it, and never present it as current. Do not mix the current formal READY with past values or with conditional (what-if) READY estimates; an estimate that has not been recomputed against the current formal READY is not a current value.

Current phase (current company A counts live only in PROJECT_STATUS.md §1; MF and Evidence status in current_evidence_status.md):

- MF→JDL Evidence acquisition is finished. Do not generate new probes.
- Do not re-acquire FY2026 Evidence or repeat real JDL operations 0873–0878 for the same scope.
- The only critical path is the FY2027 real round-trip ("Remaining critical path" in current_evidence_status.md).
- Foundation freeze (see docs/product/開発ロードマップ.md): lifted only for Yayoi, because real Yayoi data arrived (2026-11-01). Other abstraction or renaming ahead of real need is still frozen.

- Yayoi company A (Buddies): the 2026-11-05 campaign Evidence is registered **only for one exact company scope** (`adapters/output/jdl/scoped_evidence.py`: 税抜・原則・一括比例・売上切上げ/仕入四捨五入・振替伝票入力行数16). Data table: `scoped_evidence_registry.py` (regenerate with `tools/build_scoped_evidence_registry.py`). 振替伝票入力行数 other than 16 (JDL offers 16 / 64) is in scope only after a real round is registered in `ROW_LIMIT_SCOPES` (`tools/yayoi_row64_probe.py`); until then a company set to 64 is blocked. It is tried only after the existing MF/ACT Evidence fails. Do not widen it by similarity; extend it only with new real round trips. Diagnose with `tools/yayoi_whatif_readiness.py` (scratch copy only). Formal READY plus the step-by-step what-if, with the context validated first: `tools/yayoi_formal_rediagnosis.py`. Never rebuild a JDL context outside the app's paths (JDL re-exports carry the 略名称, which is not unique). Details: docs/development/yayoi_buddies_evidence_campaign.md.

Design rule: JDL target Evidence is keyed by what JDL receives, never by the source format or source tax name (see the workflow document).

Hard rules: never auto-confirm accounting judgments; never track `data/private/`; commit or push only when asked.

Checks: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall -q src tests`, `git diff --check`, `git ls-files data/private | wc -l` must be 0.

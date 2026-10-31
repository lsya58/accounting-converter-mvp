# Agent instructions

Before changing code or asking a Human for JDL work, read:

1. [docs/development/mf_jdl_evidence_driven_workflow.md](docs/development/mf_jdl_evidence_driven_workflow.md) — how work is planned and judged here (goal-first, HUMAN / SYSTEM_EVIDENCE / SYSTEM_IMPLEMENTATION, composable Evidence, probe ≠ production, strict comparison). Follow its "For AI coding agents" section.
2. [docs/development/jdl_real_evidence_log.md](docs/development/jdl_real_evidence_log.md) — real JDL operations already done. Never re-request one marked `repeat_required: NO`.
3. [docs/development/current_evidence_status.md](docs/development/current_evidence_status.md) — current READY counts and blockers. Recompute; do not copy old counts.

Hard rules: never auto-confirm accounting judgments; never track `data/private/`; commit or push only when asked.

Checks: `PYTHONPATH=src python3 -m unittest discover -s tests`, `PYTHONPATH=src python3 -m compileall -q src tests`, `git diff --check`, `git ls-files data/private | wc -l` must be 0.

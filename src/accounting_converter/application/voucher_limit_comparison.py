"""Read-only row-limit trials using the production Yayoi assessment.

No mapping, approval, registry or store is changed. A different limit gets
the same in-memory profile revision that saving the setting would create.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from accounting_converter.adapters.output.jdl import scoped_evidence
from accounting_converter.application import voucher_split
from accounting_converter.application.company_voucher_row_limit import profile_with_row_limit_context
from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlAssessment, YayoiJdlWorkflow
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader


@dataclass(frozen=True)
class JournalLimitComparison:
    journal_id: str
    debit_lines: int
    credit_lines: int
    physical_rows: int
    blockers16: frozenset[str]
    blockers64: frozenset[str]
    over16: bool
    over64: bool

    @property
    def outcome(self) -> str:
        if self.blockers16 and not self.blockers64:
            return "64行設定では分割せず変換できます" if not self.over64 else "64行設定では変換条件を満たします"
        if not self.blockers16 and self.blockers64:
            return "16行設定では変換できます。64行設定では追加確認が必要です"
        if self.blockers16 and self.blockers64:
            return "両設定で追加確認が必要です"
        return "両設定で変換条件を満たします"


@dataclass(frozen=True)
class LimitTrial:
    limit: int
    assessment: YayoiJdlAssessment
    over_limit: int
    split_candidates: int

    @property
    def approval_required(self) -> int:
        return self.assessment.blocker_counts().get(voucher_split.APPROVAL_BLOCKER, 0)


@dataclass(frozen=True)
class VoucherLimitComparison:
    saved_limit: int | None
    formal: YayoiJdlAssessment
    trials: tuple[LimitTrial, ...]
    journals: tuple[JournalLimitComparison, ...]
    source_sha256: str

    @property
    def both_blocked(self) -> int:
        return sum(bool(j.blockers16 and j.blockers64) for j in self.journals)


def compare_limits(source: Path, profile, context) -> VoucherLimitComparison:
    if profile is None or context is None:
        raise ValueError("会社設定とJDL環境の確認を完了してください。")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    source_format = detect_format(source)
    if profile.source_format_identity != source_format.identity():
        raise ValueError("入力形式と会社設定の形式が一致しません。")
    parsed = source_format.diagnose(source)
    if not parsed.ok or parsed.rejected_journals:
        raise ValueError("入力データに解析できない仕訳があるため、比較できません。")
    workflow = YayoiJdlWorkflow()
    formal = workflow.assess(source, profile, context)
    trials = []
    over = {}
    for limit in (16, 64):
        trial_context = replace(context, voucher_row_limit=limit)
        if context.voucher_row_limit == limit:
            assessment = formal
        else:
            raw = JdlTargetContextLoader().to_json_text(trial_context).encode("utf-8")
            trial_profile = profile_with_row_limit_context(profile, raw)
            assessment = workflow.assess(source, trial_profile, trial_context)
        if assessment.parse_issue_codes or set(assessment.journal_blockers) != set(formal.journal_blockers):
            raise ValueError("比較中に入力データの状態が変わりました。再度確認してください。")
        over[limit] = {
            entry.id: scoped_evidence.exceeds_row_limit(journal_physical_rows(entry), limit)
            if journal_physical_rows(entry) is not None else False
            for entry in parsed.entries
        }
        trials.append(LimitTrial(limit, assessment, sum(over[limit].values()),
                                 sum(voucher_split.plan_split(entry, limit) is not None for entry in parsed.entries)))
    journals = []
    for entry in parsed.entries:
        rows = journal_physical_rows(entry) or ()
        journals.append(JournalLimitComparison(
            entry.id, sum(r.debit is not None for r in rows), sum(r.credit is not None for r in rows), len(rows),
            trials[0].assessment.journal_blockers[entry.id], trials[1].assessment.journal_blockers[entry.id],
            over[16][entry.id], over[64][entry.id]))
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise ValueError("比較中に入力ファイルが変更されました。再度確認してください。")
    return VoucherLimitComparison(context.voucher_row_limit, formal, tuple(trials), tuple(journals), before)

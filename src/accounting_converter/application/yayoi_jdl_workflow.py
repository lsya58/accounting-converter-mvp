"""Yayoi 仕訳日記帳 (汎用形式) → JDL IBEX 出納帳 formal workflow.

Same chain as MF → JDL, with the Yayoi input adapter and no MF-specific step:

    Yayoi report → common journal rows → description replacements (Human)
    → account/subaccount/tax mappings (Human, CompanySetting) → JDL tax
    semantics → Evidence composition → JDL preflight → formal serializer

Every journal gets explicit blockers with an owner. Formal output exists only
when all of them are zero; nothing is guessed for missing JDL master, Tax
Context or mappings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_adapter import (
    YayoiJournalReportInputAdapter,
    YayoiJournalReportStructuralValidator,
    yayoi_journal_report_input_profile,
)
from accounting_converter.adapters.input.yayoi.journal_report_parser import YayoiJournalReportParser
from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.conversion import ConversionRequest, ConversionService
from accounting_converter.application.first_release_workflow import (
    FirstReleasePreparedConversion,
    FirstReleaseReadiness,
    FirstReleaseSummary,
)
from accounting_converter.application.journal_route import JournalRouteResult
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.moneyforward_conversion_workflow import _VerifiedTaxSemanticsTransform
from accounting_converter.application.moneyforward_description_replacement import (
    MoneyForwardDescriptionReplacementPolicy as DescriptionReplacementPolicy,
    description_requires_replacement,
    journal_descriptions,
)
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.domain.validation import BalanceRule, Severity, ValidationResult
from accounting_converter.infrastructure.adapter_registry import production_adapter_registry
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    yayoi_journal_report_generic_identity,
)

ROUTE_ID = "YAYOI-REPORT-JDL-COMPOSED-V1"
SOURCE_FORMAT_LABEL = "弥生 仕訳日記帳（汎用形式）"

# Composition gaps that only a Human can resolve; every other gap needs JDL Evidence.
HUMAN_GAPS = {"TAX_MAPPING_UNCONFIRMED", "SUBACCOUNT_REQUIRED_BY_MASTER", "ACCOUNT_CODE_MISMATCH",
              "ACCOUNT_IDENTITY_MISMATCH", "SUBACCOUNT_CODE_MISMATCH"}
IGNORED_DIAGNOSTIC_GAPS = {"TAX_CATEGORY_MISMATCH", "SHAPE_MISMATCH", "EVIDENCE_SCOPE_CHANGED_BY_MASTER"}


class YayoiToJdlLossRule:
    """Blocks Yayoi information that JDL output cannot keep or that is unconfirmed."""

    rule_id = "YAYOI-JDL-LOSS"

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        fields = []
        if entry.metadata.get("yayoi_optional_fields"):
            fields.append("optional_field")  # 付箋 / 仕訳メモ / 期日 / 番号 / 生成元
        if entry.metadata.get("yayoi_closing"):
            fields.append("closing_entry")  # 決算区分: no proven JDL representation
        if any(description_requires_replacement(value) for value in journal_descriptions(entry)):
            fields.append("description_character")
        return [
            ValidationResult(
                severity=Severity.ERROR,
                rule_id=f"{self.rule_id}-{field.upper()}",
                message="JDLへそのまま保持できない弥生の情報があります。",
                journal_id=entry.id,
                source_reference=entry.source_reference,
                field=field,
            )
            for field in fields
        ]


@dataclass(frozen=True)
class YayoiJdlAssessment:
    """Per-journal blockers, each prefixed by its owner (HUMAN / SYSTEM_EVIDENCE / SYSTEM_IMPLEMENTATION)."""

    journal_blockers: dict[str, frozenset[str]]
    assignments: dict
    parse_issue_codes: tuple[str, ...]
    entry_count: int
    detail_rows: int

    @property
    def ready_journals(self) -> int:
        return sum(1 for blockers in self.journal_blockers.values() if not blockers)

    def blocker_counts(self) -> dict[str, int]:
        return dict(Counter(b for blockers in self.journal_blockers.values() for b in blockers))

    def owner_counts(self) -> dict[str, int]:
        counts: Counter = Counter()
        for blockers in self.journal_blockers.values():
            owners = sorted({b.split(":", 1)[0] for b in blockers})
            counts["+".join(owners) or "READY"] += 1
        return dict(counts)


class _DescriptionAndEvidenceRoutePolicy:
    def __init__(self, description_policy, evidence_policy) -> None:
        self._description_policy = description_policy
        self._evidence_policy = evidence_policy

    def apply(self, entries) -> JournalRouteResult:
        described = self._description_policy.apply(entries)
        if described.validation_results:
            return described
        return self._evidence_policy.apply(described.entries)


class YayoiJournalReportJdlWorkflow:
    def __init__(self, registry=None) -> None:
        self.registry = registry or production_adapter_registry()

    def assess(
        self,
        input_path: Path,
        profile: ConversionProfile | None,
        context: JdlTargetContext | None,
    ) -> YayoiJdlAssessment:
        parsed = YayoiJournalReportParser().diagnose(input_path)
        entries = parsed.entries
        blockers: dict[str, set[str]] = {entry.id: set() for entry in entries}
        if profile is None or context is None:
            for entry_blockers in blockers.values():
                entry_blockers.add("HUMAN:TARGET_JDL_COMPANY_SETTING")
        elif not self._identity_matches(profile):
            for entry_blockers in blockers.values():
                entry_blockers.add("HUMAN:COMPANY_SETTING_SOURCE_MISMATCH")
        description_policy = DescriptionReplacementPolicy(profile) if profile is not None else None
        if description_policy is not None:
            replaced = description_policy.apply(entries)
            entries = replaced.entries
        loss = YayoiToJdlLossRule()
        for entry in entries:
            for result in loss.validate(entry):
                blockers[entry.id].add({
                    "description_character": "HUMAN:DESCRIPTION_REPLACEMENT",
                    "optional_field": "HUMAN:OPTIONAL_FIELD_POLICY",
                    "closing_entry": "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION",
                }[result.field])
        assignments = {}
        if profile is not None and context is not None and self._identity_matches(profile):
            requirements = MappingRequirementExtractor().extract(entries, profile)
            unresolved_accounts = {r.source_value for r in requirements.accounts if r.requires_confirmation}
            unresolved_subs = {(r.parent_account, r.source_value) for r in requirements.subaccounts if r.requires_confirmation}
            unresolved_taxes = {r.source_value for r in requirements.tax_categories if r.requires_confirmation}
            for entry in entries:
                for line in entry.lines:
                    if line.tax_info and line.tax_info.category in unresolved_taxes:
                        blockers[entry.id].add("HUMAN:TAX_MAPPING")
                    if line.account in unresolved_accounts:
                        blockers[entry.id].add("HUMAN:ACCOUNT_MAPPING")
                    if line.sub_account and (line.account, line.sub_account) in unresolved_subs:
                        blockers[entry.id].add("HUMAN:SUBACCOUNT_MAPPING")
            if not ev.context_is_verified(context):
                for entry_blockers in blockers.values():
                    entry_blockers.add("SYSTEM_EVIDENCE:TAX_CONTEXT_UNVERIFIED")
            else:
                mapped = MappingEngine(mapping_rule_set_from_profile(profile)).apply(entries).entries
                for entry, mapped_entry in zip(entries, mapped, strict=True):
                    match = ev.match_evidence_for_occurrence(entry, mapped_entry, context, profile)
                    if match.evidence is not None:
                        assignments[entry.id] = match.evidence.profile
                        continue
                    gaps = set(match.mismatch_fields) - IGNORED_DIAGNOSTIC_GAPS
                    for gap in gaps:
                        if gap in {"TAX_MAPPING_UNCONFIRMED"}:
                            blockers[entry.id].add("HUMAN:TAX_MAPPING")
                        elif gap == "SUBACCOUNT_REQUIRED_BY_MASTER":
                            blockers[entry.id].add("HUMAN:SUBACCOUNT_DEFAULT")
                        elif gap in HUMAN_GAPS:
                            blockers[entry.id].add("HUMAN:ACCOUNT_MAPPING")
                        else:
                            blockers[entry.id].add(f"SYSTEM_EVIDENCE:{gap}")
                    if not gaps:
                        blockers[entry.id].add("SYSTEM_IMPLEMENTATION:UNMATCHED")
        return YayoiJdlAssessment(
            {key: frozenset(value) for key, value in blockers.items()},
            assignments,
            tuple(issue.code for issue in parsed.issues),
            len(entries),
            parsed.detail_rows,
        )

    def prepare(
        self,
        *,
        input_path: Path | None,
        output_path: Path | None,
        profile: ConversionProfile | None,
        context: JdlTargetContext | None,
        company_setting_validated: bool = False,
    ) -> FirstReleasePreparedConversion:
        reasons: list[str] = []
        if input_path is None:
            reasons.append("弥生の仕訳日記帳ファイルを選択してください。")
        if output_path is None:
            reasons.append("保存先を選択してください。")
        elif output_path.exists():
            reasons.append("既存のファイルは上書きしません。別の保存先を選択してください。")
        if profile is None or context is None:
            reasons.append("対象のJDL会社設定（科目一覧と税設定）がありません。")
        elif not company_setting_validated:
            reasons.append("会社設定を確認できません。")
        elif not self._identity_matches(profile):
            reasons.append("会社設定の入力元が弥生の仕訳日記帳ではありません。")
        if input_path is None:
            return self._blocked(None, output_path, profile, reasons)
        assessment = self.assess(input_path, profile, context)
        if assessment.parse_issue_codes:
            reasons.append("弥生の仕訳日記帳を安全に読み込めませんでした。")
        messages = {
            "HUMAN:ACCOUNT_MAPPING": "未確認の科目対応があります。",
            "HUMAN:SUBACCOUNT_MAPPING": "未確認の補助科目対応があります。",
            "HUMAN:SUBACCOUNT_DEFAULT": "補助なしの仕訳のまとめ先補助を確認してください。",
            "HUMAN:TAX_MAPPING": "税区分の確認が必要です。",
            "HUMAN:DESCRIPTION_REPLACEMENT": "JDLに入らない摘要があります。置き換え内容を確認してください。",
            "HUMAN:OPTIONAL_FIELD_POLICY": "付箋などJDLに保持先のない情報があります。",
        }
        for blocker in sorted({b for v in assessment.journal_blockers.values() for b in v}):
            if blocker in messages:
                reasons.append(messages[blocker])
            elif blocker.startswith("SYSTEM_EVIDENCE"):
                reasons.append("JDL実機で確認していない仕訳構成・税・情報があります。")
            elif blocker.startswith("SYSTEM_IMPLEMENTATION"):
                reasons.append("未対応の仕訳があります。")
        reasons = list(dict.fromkeys(reasons))
        counts = Counter(b for v in assessment.journal_blockers.values() for b in v)
        summary = FirstReleaseSummary(
            readiness=FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY,
            blocking_reasons=tuple(reasons),
            source_name=input_path.name,
            source_format=SOURCE_FORMAT_LABEL,
            profile_name=profile.profile_name if profile is not None else None,
            unresolved_mapping_count=sum(
                n for b, n in counts.items() if b.startswith("HUMAN:") and "MAPPING" in b
            ),
            tax_evidence_blocker_count=sum(
                1 for v in assessment.journal_blockers.values() if any(b.startswith("SYSTEM_EVIDENCE") for b in v)
            ),
            optional_field_blocker_count=counts.get("HUMAN:OPTIONAL_FIELD_POLICY", 0),
        )
        if reasons:
            return FirstReleasePreparedConversion(summary)
        output_lookup = self.registry.get_exact_output(
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        )
        assert profile is not None and context is not None and output_path is not None
        route = _DescriptionAndEvidenceRoutePolicy(
            DescriptionReplacementPolicy(profile),
            ExplicitJdlEvidenceRoutePolicy(assessment.assignments, route_id=ROUTE_ID),
        )
        service = ConversionService(
            input_adapter=YayoiJournalReportInputAdapter(),
            structural_validator=YayoiJournalReportStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), YayoiToJdlLossRule())),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=route,
            post_mapping_transform=_VerifiedTaxSemanticsTransform(profile, context),
            runtime_output_factory=output_lookup.registration.runtime_factory,
        )
        request = ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            input_profile=yayoi_journal_report_input_profile(),
            output_profile=jdl_ibex_35_5_output_profile(),
            overwrite=False,
            conversion_profile=profile,
            target_runtime_context=context,
        )
        return FirstReleasePreparedConversion(summary, request, service)

    @staticmethod
    def execute(prepared: FirstReleasePreparedConversion):
        if (
            prepared.summary.readiness is not FirstReleaseReadiness.READY
            or prepared.request is None
            or prepared.conversion_service is None
        ):
            return None
        return prepared.conversion_service.convert(prepared.request)

    @staticmethod
    def _identity_matches(profile: ConversionProfile) -> bool:
        return (
            profile.source_format_identity.stable_key == yayoi_journal_report_generic_identity().stable_key
            and profile.target_format_identity.stable_key
            == jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key
        )

    @staticmethod
    def _blocked(input_path, output_path, profile, reasons):
        return FirstReleasePreparedConversion(FirstReleaseSummary(
            readiness=FirstReleaseReadiness.BLOCKED,
            blocking_reasons=tuple(reasons),
            source_format=SOURCE_FORMAT_LABEL,
        ))

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

import hashlib
import json
from decimal import Decimal
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlEvidenceProfile,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application import noncredit_approval
from accounting_converter.application import scoped_evidence_composition as scoped_composition
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
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, is_confirmed_parent_only
from accounting_converter.domain.validation import BalanceRule, Severity, ValidationResult
from accounting_converter.infrastructure.adapter_registry import production_adapter_registry
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.domain.journal import Side
from accounting_converter.application.yayoi_review import (
    DEPARTMENT_FIELD,
    candidate_semantic,
    NON_RETAINED_VALUES_KEY,
    confirmed_optional_fields,
    field_of,
    non_retained_values,
)
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
    journal_physical_rows,
)
from accounting_converter.application.yayoi_sources import (
    YayoiSourceFormat,
    detect_format,
    format_for_identity_key,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)

ROUTE_ID = "YAYOI-REPORT-JDL-COMPOSED-V1"
SOURCE_FORMAT_LABEL = "弥生 仕訳日記帳（汎用形式）"

# Composition gaps that only a Human can resolve; every other gap needs JDL Evidence.
HUMAN_GAPS = {"TAX_MAPPING_UNCONFIRMED", "SUBACCOUNT_REQUIRED_BY_MASTER", "ACCOUNT_CODE_MISMATCH",
              "ACCOUNT_IDENTITY_MISMATCH", "SUBACCOUNT_CODE_MISMATCH"}
ACCOUNT_DIAGNOSTIC_GAPS = {"ACCOUNT_CODE_MISMATCH", "ACCOUNT_IDENTITY_MISMATCH", "SUBACCOUNT_CODE_MISMATCH",
                           "PARENT_ONLY_REPRESENTATION_MISMATCH"}
# Company-setting facts about the voucher row limit. The Human decides (split / key in by
# hand / enter the setting), but nothing the Human confirms in this app makes an
# over-limit journal importable: it stays blocked until the journal itself changes.
VOUCHER_ROW_LIMIT_BLOCKERS = {
    scoped_composition.GAP_ROW_LIMIT_EXCEEDED: "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED",
    scoped_composition.GAP_ROW_LIMIT_UNCONFIRMED: "HUMAN:VOUCHER_ROW_LIMIT_SETTING",
}
IGNORED_DIAGNOSTIC_GAPS = {"TAX_CATEGORY_MISMATCH", "SHAPE_MISMATCH", "EVIDENCE_SCOPE_CHANGED_BY_MASTER"}


# Evidence gaps a probe may cover: journal structure x tax only. Account,
# tax-literal and rounding questions are never probed with this.
PROBE_GAPS = frozenset({
    "SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED",  # case B: untaxed 2D2C
    "SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED",  # case A: 1D1C 課税売上10% on an unverified account
})
PROBE_CASE_UNTAXED_COMPOUND = "B_UNTAXED_COMPOUND"
PROBE_CASE_SALES10_ACCOUNT = "A_SALES10_ACCOUNT"
# Synthetic 課税売上10% amount for case A. The verified JDL literal (0872) is
# 売　上 / 10% / 外税 with the tax-included amount and tax = floor(amount*10/110);
# 3300 has no fraction (300 exactly), so the rounding setting plays no part.
PROBE_SALES10_AMOUNT = Decimal("3300")
PROBE_SALES10_TAX = Decimal("300")


class YayoiToJdlLossRule:
    """Blocks Yayoi information that JDL output cannot keep, unless the Human
    confirmed an audit-only policy for that field (see yayoi_review)."""

    rule_id = "YAYOI-JDL-LOSS"

    def __init__(self, confirmed_fields: frozenset[str] = frozenset()) -> None:
        self.confirmed_fields = confirmed_fields

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        fields = []
        present = {field_of(name) for _, name, _ in non_retained_values(entry)}
        unconfirmed = present - self.confirmed_fields
        if unconfirmed - {DEPARTMENT_FIELD}:
            fields.append("optional_field")  # 付箋 / 仕訳メモ / 期日 / 番号 / 生成元
        if DEPARTMENT_FIELD in unconfirmed:
            fields.append("department")  # JDL company without departments
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
    # field -> journals whose values are not written to JDL (audit file only).
    non_retained_journals: dict | None = None
    # Blockers that follow from the journal structure if the Human confirms the
    # natural tax candidate; not counted as current blockers.
    likely_blockers: dict | None = None

    def likely_blocker_counts(self) -> dict[str, int]:
        return dict(Counter(b for blockers in (self.likely_blockers or {}).values() for b in blockers))

    @property
    def information_fully_retained(self) -> bool:
        """True only when nothing from the source is left out of the JDL file."""
        return not self.non_retained_journals

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
        source_format = self._source_format(input_path, profile)
        parsed = source_format.diagnose(input_path)
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
        confirmed_fields = frozenset(confirmed_optional_fields(profile)) if profile is not None else frozenset()
        loss = YayoiToJdlLossRule(confirmed_fields)
        non_retained: Counter = Counter()
        for entry in entries:
            for field in {field_of(name) for _, name, _ in non_retained_values(entry) + dropped_subaccount_values(entry, profile)}:
                non_retained[field] += 1
        for entry in entries:
            for result in loss.validate(entry):
                blockers[entry.id].add({
                    "description_character": "HUMAN:DESCRIPTION_REPLACEMENT",
                    "optional_field": "HUMAN:OPTIONAL_FIELD_POLICY",
                    "closing_entry": "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION",
                    "department": "HUMAN:DEPARTMENT_POLICY",
                }[result.field])
        assignments = {}
        likely: dict[str, set[str]] = {entry.id: set() for entry in entries}
        if context is not None and context.voucher_row_limit is not None:
            for entry in entries:
                rows = journal_physical_rows(entry)
                if rows is not None and len(rows) > context.voucher_row_limit:
                    blockers[entry.id].add(VOUCHER_ROW_LIMIT_BLOCKERS[scoped_composition.GAP_ROW_LIMIT_EXCEEDED])
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
                        evidence = match.evidence
                        if not _physical_rows_verified(entry, evidence.profile):
                            # The composed compound profile also needs JDL row Evidence for
                            # the physical-row shape (the output stage refuses it otherwise).
                            # Try the campaign Evidence; else stop here, not at the output.
                            evidence, scoped_gaps = scoped_composition.compose_scoped(
                                entry, match.actual_signature, has_partner=False, context=context)
                            if evidence is None:
                                for gap in scoped_gaps or ("PHYSICAL_ROW_SHAPE_UNVERIFIED",):
                                    blockers[entry.id].add(
                                        VOUCHER_ROW_LIMIT_BLOCKERS.get(gap) or f"SYSTEM_EVIDENCE:{gap}")
                                continue
                        assignments[entry.id] = evidence.profile
                        continue
                    # Account problems come from the line identities themselves; the
                    # matcher's account codes compare against the nearest exact
                    # Evidence and are diagnostics once composition has run.
                    identity_gaps = {
                        field
                        for line, mapped_line in zip(entry.lines, mapped_entry.lines, strict=True)
                        for field in ev.canonical_target_identity(
                            source_account=line.account, source_subaccount=line.sub_account,
                            side=line.side.value, mapped_account=mapped_line.account,
                            mapped_subaccount=mapped_line.sub_account, context=context, profile=profile,
                        ).mismatch_fields
                    }
                    gaps = (set(match.mismatch_fields) - IGNORED_DIAGNOSTIC_GAPS - ACCOUNT_DIAGNOSTIC_GAPS) | identity_gaps
                    for gap in gaps:
                        if gap in VOUCHER_ROW_LIMIT_BLOCKERS:
                            blockers[entry.id].add(VOUCHER_ROW_LIMIT_BLOCKERS[gap])
                        elif gap in {"TAX_MAPPING_UNCONFIRMED"}:
                            blockers[entry.id].add("HUMAN:TAX_MAPPING")
                        elif gap == "JDL_TAX_ROUNDING_UNCONFIRMED":
                            blockers[entry.id].add("HUMAN:JDL_TAX_ROUNDING_SETTING")
                        elif gap == "SUBACCOUNT_REQUIRED_BY_MASTER":
                            blockers[entry.id].add("HUMAN:SUBACCOUNT_DEFAULT")
                        elif gap == "SUBACCOUNT_CODE_MISMATCH":
                            blockers[entry.id].add("HUMAN:SUBACCOUNT_MAPPING")
                        elif gap in HUMAN_GAPS:
                            blockers[entry.id].add("HUMAN:ACCOUNT_MAPPING")
                        else:
                            blockers[entry.id].add(f"SYSTEM_EVIDENCE:{gap}")
                    if not gaps:
                        blockers[entry.id].add("SYSTEM_IMPLEMENTATION:UNMATCHED")
                    # The matcher skips composition while an account is unmapped;
                    # shape x tax does not depend on accounts, so check it anyway.
                    current, candidate = structural_evidence_gaps(entry, profile, context)
                    blockers[entry.id].update(_structural_blocker(gap) for gap in current)
                    likely[entry.id].update(_structural_blocker(gap) for gap in candidate)
        return YayoiJdlAssessment(
            {key: frozenset(value) for key, value in blockers.items()},
            assignments,
            parsed.issue_codes,
            len(entries),
            parsed.detail_rows,
            dict(non_retained),
            {key: frozenset(value) for key, value in likely.items() if value},
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
        elif output_path.exists() or audit_path_for(output_path).exists() or pending_audit_path_for(output_path).exists():
            reasons.append("既存のファイル（正式CSVまたは監査記録）は上書きしません。別の保存先を選択してください。")
        if profile is None or context is None:
            reasons.append("対象のJDL会社設定（科目一覧と税設定）がありません。")
        elif not company_setting_validated:
            reasons.append("会社設定を確認できません。")
        elif not self._identity_matches(profile):
            reasons.append("会社設定の入力元が弥生（仕訳日記帳またはインポート形式）ではありません。")
        if input_path is None:
            return self._blocked(None, output_path, profile, reasons)
        source_format = self._source_format(input_path, profile)
        if profile is not None and self._identity_matches(profile) and detect_format(input_path) is not source_format:
            reasons.append("選択したファイルの形式が会社設定の入力元と一致しません。")
        assessment = self.assess(input_path, profile, context)
        confirmed_fields = frozenset(confirmed_optional_fields(profile)) if profile is not None else frozenset()
        if assessment.parse_issue_codes:
            reasons.append(f"{source_format.label}として安全に読み込めませんでした。")
        messages = {
            "HUMAN:ACCOUNT_MAPPING": "未確認の科目対応があります。",
            "HUMAN:SUBACCOUNT_MAPPING": "未確認の補助科目対応があります。",
            "HUMAN:SUBACCOUNT_DEFAULT": "補助なしの仕訳のまとめ先補助を確認してください。",
            "HUMAN:TAX_MAPPING": "税区分の確認が必要です。",
            "HUMAN:DESCRIPTION_REPLACEMENT": "JDLに入らない摘要があります。置き換え内容を確認してください。",
            "HUMAN:OPTIONAL_FIELD_POLICY": "生成元・付箋などJDLに保持先のない情報があります。意味と扱い（JDLへは出さず監査記録に残す）を確認してください。",
            "HUMAN:DEPARTMENT_POLICY": "部門を含む仕訳があります。対象のJDL会社は部門を使わない設定のため、意味と扱い（JDLへは出さず監査記録に残す）を確認してください。",
            "HUMAN:JDL_TAX_ROUNDING_SETTING": "JDL会社の消費税の端数処理（売上・仕入）を設定してください。",
            "HUMAN:VOUCHER_ROW_LIMIT_SETTING": "JDLの会社設定「振替伝票入力行数」を確認して入力してください。",
            "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED": (
                "JDLの振替伝票入力行数を超える仕訳があります。JDLは行数が多すぎる伝票を取り込めません"
                "（分割するか、JDLで手入力してください。アプリは自動で分割しません）。"
            ),
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
            source_format=source_format.label,
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
            input_adapter=_AuditOnlyFieldsRemovedAdapter(source_format.adapter(), confirmed_fields),
            structural_validator=source_format.validator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), YayoiToJdlLossRule(confirmed_fields))),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=route,
            post_mapping_transform=_VerifiedTaxSemanticsTransform(profile, context),
            runtime_output_factory=output_lookup.registration.runtime_factory,
        )
        request = ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            input_profile=source_format.input_profile(),
            output_profile=jdl_ibex_35_5_output_profile(),
            overwrite=False,
            conversion_profile=profile,
            target_runtime_context=context,
        )
        return FirstReleasePreparedConversion(summary, request, service)

    def probe_cases(self, input_path: Path, profile, context, probe_gaps: frozenset[str] = PROBE_GAPS) -> dict:
        """journal id -> (case, JDL serializer profile) for journals that may be probed.

        Only the two narrow cases below, only when every other check passed
        (all Human mappings confirmed), and never for a journal carrying
        information outside JDL. Anything else is left out.
        """
        assessment = self.assess(input_path, profile, context)
        source_format = self._source_format(input_path, profile)
        entries = {entry.id: entry for entry in source_format.read(input_path)}
        cases = {}
        for key, blockers in assessment.journal_blockers.items():
            entry = entries[key]
            if not blockers or not blockers <= probe_gaps or non_retained_values(entry):
                continue
            semantics = [
                (line.side, ev.target_tax_semantic(line, profile, context) if line.tax_info else JdlTaxSemantic.NO_TAX.value)
                for line in entry.lines
            ]
            rows: dict[int, list] = {}
            for line in entry.lines:
                rows.setdefault(int(line.metadata[LINE_ROW_KEY]), []).append(line.side.value)
            one_pair_per_row = all(sorted(sides) == ["CREDIT", "DEBIT"] for sides in rows.values())
            if (
                blockers == {"SYSTEM_EVIDENCE:SHAPE_TAX_COMBINATION_UNVERIFIED"}
                and all(value == JdlTaxSemantic.NO_TAX.value for _, value in semantics)
                and one_pair_per_row
            ):
                cases[key] = (PROBE_CASE_UNTAXED_COMPOUND, JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL)
            elif (
                blockers == {"SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED"}
                and len(rows) == 1 and one_pair_per_row
                and semantics == [(Side.DEBIT, JdlTaxSemantic.NO_TAX.value),
                                  (Side.CREDIT, JdlTaxSemantic.SALES_10_EXTERNAL.value)]
            ):
                cases[key] = (PROBE_CASE_SALES10_ACCOUNT, JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111)
        return cases

    def prepare_probe(
        self,
        *,
        input_path: Path,
        output_path: Path,
        profile: ConversionProfile,
        context: JdlTargetContext,
        probe_gaps: frozenset[str] = PROBE_GAPS,
    ) -> tuple[FirstReleasePreparedConversion, tuple[str, ...]]:
        """NOT_FOR_PRODUCTION probe of the journals blocked ONLY by probe_gaps.

        Every Human mapping of those journals must already be confirmed, so
        the probe uses the company's real JDL accounts; nothing is guessed.
        For a test company restored from a backup only. Returns the prepared
        conversion and the probed journal ids (empty → nothing to probe).
        """
        if "NOT_FOR_PRODUCTION" not in output_path.name:
            raise ValueError("probe output name must contain NOT_FOR_PRODUCTION")
        source_format = self._source_format(input_path, profile)
        cases = self.probe_cases(input_path, profile, context, probe_gaps)
        probe_ids = tuple(cases)
        reasons = [] if probe_ids else ["人の確認がすべて済み、構成×税の実機検証だけが残っている仕訳はありません。"]
        if output_path.exists():
            reasons.append("既存のファイルは上書きしません。")
        summary = FirstReleaseSummary(
            readiness=FirstReleaseReadiness.BLOCKED if reasons else FirstReleaseReadiness.READY,
            blocking_reasons=tuple(reasons),
            source_name=input_path.name,
            source_format=f"{source_format.label}（NOT_FOR_PRODUCTION probe）",
            profile_name=profile.profile_name,
        )
        if reasons:
            return FirstReleasePreparedConversion(summary), probe_ids
        confirmed_fields = frozenset(confirmed_optional_fields(profile))
        output_lookup = self.registry.get_exact_output(
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        )
        assignments = {key: evidence for key, (_, evidence) in cases.items()}
        service = ConversionService(
            input_adapter=_SyntheticProbeValues(_OnlyJournals(
                _AuditOnlyFieldsRemovedAdapter(source_format.adapter(), confirmed_fields), frozenset(probe_ids)
            ), profile, context),
            structural_validator=source_format.validator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), YayoiToJdlLossRule(confirmed_fields))),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=_DescriptionAndEvidenceRoutePolicy(
                DescriptionReplacementPolicy(profile),
                ExplicitJdlEvidenceRoutePolicy(assignments, route_id=f"{ROUTE_ID}-NOT_FOR_PRODUCTION-PROBE"),
            ),
            post_mapping_transform=_ProbeTaxLiteralsTransform(profile, context),
            runtime_output_factory=output_lookup.registration.runtime_factory,
        )
        request = ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            input_profile=source_format.input_profile(),
            output_profile=jdl_ibex_35_5_output_profile(),
            overwrite=False,
            conversion_profile=profile,
            target_runtime_context=context,
        )
        return FirstReleasePreparedConversion(summary, request, service), probe_ids

    @staticmethod
    def execute(prepared: FirstReleasePreparedConversion):
        """Formal CSV plus, when anything is left out of JDL, its audit file.

        The audit file is part of the formal result: if it cannot be written,
        the CSV is removed and the run fails.
        """
        if (
            prepared.summary.readiness is not FirstReleaseReadiness.READY
            or prepared.request is None
            or prepared.conversion_service is None
        ):
            return None
        request = prepared.request
        output = Path(request.output_path)
        if "NOT_FOR_PRODUCTION" in output.name:  # probe: its journals carry nothing outside JDL
            return prepared.conversion_service.convert(request)
        pending = begin_non_retained_audit(request.input_path, output, request.conversion_profile)
        try:
            result = prepared.conversion_service.convert(request)
        except Exception:
            if pending is not None:
                pending.unlink(missing_ok=True)
            raise
        if result.status.value != "SUCCESS" or result.output_path is None:
            if pending is not None:
                pending.unlink(missing_ok=True)
            return result
        try:
            finish_non_retained_audit(output)
            check = verify_non_retained_audit(request.input_path, output, request.conversion_profile)
            if check["verdict"] not in {"PASS", "NOT_NEEDED"}:
                raise RuntimeError("audit record does not match the formal CSV")
        except Exception:
            # Never leave a formal CSV without its audit record.
            output.unlink(missing_ok=True)
            audit_path_for(output).unlink(missing_ok=True)
            pending_audit_path_for(output).unlink(missing_ok=True)
            raise
        return result

    @staticmethod
    def _source_format(input_path: Path, profile: ConversionProfile | None) -> YayoiSourceFormat:
        """The CompanySetting decides the format; without one, the file content does."""
        configured = (
            format_for_identity_key(profile.source_format_identity.stable_key)
            if profile is not None else None
        )
        return configured or detect_format(input_path)

    @staticmethod
    def _identity_matches(profile: ConversionProfile) -> bool:
        return (
            format_for_identity_key(profile.source_format_identity.stable_key) is not None
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


_PROFILES_NEEDING_ROW_EVIDENCE = frozenset({
    JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL,
    JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL,
})


def _physical_rows_verified(entry: JournalEntry, profile: JdlEvidenceProfile) -> bool:
    if profile not in _PROFILES_NEEDING_ROW_EVIDENCE:
        return True
    from accounting_converter.adapters.output.jdl.row_evidence import jdl_row_description_rows

    return jdl_row_description_rows(entry) is not None


def _structural_blocker(gap: str) -> str:
    return VOUCHER_ROW_LIMIT_BLOCKERS.get(gap) or f"SYSTEM_EVIDENCE:{gap}"


def structural_evidence_gaps(entry: JournalEntry, profile, context) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(current, likely) shape x tax gaps, independent of account mapping.

    current: every tax line has a confirmed mapping. likely: some line has only
    the natural candidate, so the gap appears if the Human confirms it.
    Inside the exact scope of the campaign Evidence the layout / tax placement /
    row limit rules of that Evidence decide; elsewhere the original shape rules do.
    """
    debit = sum(line.side is Side.DEBIT for line in entry.lines)
    shape = (debit, len(entry.lines) - debit)
    taxed = []
    values: dict[int, str | None] = {}
    confirmed = True
    for line in entry.lines:
        value = ev.target_tax_semantic(line, profile, context) if line.tax_info else JdlTaxSemantic.NO_TAX.value
        if value == ev.UNMAPPED_TAX:
            confirmed = False
            semantic = candidate_semantic(line.tax_info.category)
            value = semantic.value if semantic is not None else None
        values[id(line)] = value
        if value is None:
            continue  # no candidate: already a Human tax blocker
        if value != JdlTaxSemantic.NO_TAX.value:
            taxed.append((line.side.value, value))
    existing_gaps = ev.shape_tax_combination_gaps(shape, tuple(taxed))
    scoped_gaps = scoped_composition.structural_gaps(entry, lambda line: values.get(id(line)), context)
    if scoped_gaps is None:
        gaps = existing_gaps  # outside the campaign scope: the original shape rules decide
    elif not existing_gaps:
        gaps = ()  # the Evidence that existed before already covers this structure (accounts decide)
    else:
        gaps = scoped_gaps  # same precedence as composition: existing first, then the scoped Evidence
    return (gaps, ()) if confirmed else ((), gaps)


PROBE_PENDING_EVIDENCE_ID = "PENDING-YAYOI-JDL-SHAPE-TAX-PROBE-NOT_FOR_PRODUCTION"


class _ProbeTaxLiteralsTransform:
    """Probe only: write the confirmed JDL tax literals under a PENDING Evidence ID."""

    def __init__(self, profile, context) -> None:
        self._profile, self._context = profile, context

    def apply(self, source_entries, mapped_entries) -> JournalRouteResult:
        return JournalRouteResult(tuple(
            ev.apply_tax_literals(source, mapped, PROBE_PENDING_EVIDENCE_ID, profile=self._profile, context=self._context)
            for source, mapped in zip(source_entries, mapped_entries, strict=True)
        ))


PROBE_DESCRIPTION = "検証用NOT_FOR_PRODUCTION"


class _SyntheticProbeValues:
    """Probe journals keep their structure, date and confirmed JDL accounts,
    but get synthetic amounts and descriptions (no customer amounts or text).

    Only for journals whose lines are all untaxed and whose physical rows each
    hold exactly one debit and one credit; anything else is refused.
    """

    def __init__(self, inner, profile, context) -> None:
        self._inner, self._profile, self._context = inner, profile, context

    def supports(self, path, profile) -> bool:
        return self._inner.supports(path, profile)

    def record_count(self, path, profile) -> int:
        return self._inner.record_count(path, profile)

    def read(self, path, profile):
        entries = []
        for entry in self._inner.read(path, profile):
            rows: dict[int, list] = {}
            sales = None
            for line in entry.lines:
                rows.setdefault(int(line.metadata[LINE_ROW_KEY]), []).append(line)
                semantic = ev.target_tax_semantic(line, self._profile, self._context) if line.tax_info else None
                if semantic == JdlTaxSemantic.SALES_10_EXTERNAL.value and line.side is Side.CREDIT:
                    sales = line
                elif line.tax_info and semantic != JdlTaxSemantic.NO_TAX.value:
                    raise ValueError("synthetic probe supports untaxed lines and one 課税売上10% line only")
            if any(sorted(line.side.value for line in row) != ["CREDIT", "DEBIT"] for row in rows.values()):
                raise ValueError("synthetic probe needs one debit and one credit per row")
            if sales is not None and len(entry.lines) != 2:
                raise ValueError("synthetic 課税売上10% probe is 1D1C only")
            amount_by_row = {row: Decimal(1000 * index) for index, row in enumerate(sorted(rows), 1)}
            lines = []
            for line in entry.lines:
                amount = PROBE_SALES10_AMOUNT if sales is not None else amount_by_row[int(line.metadata[LINE_ROW_KEY])]
                tax_info = line.tax_info
                if line is sales:
                    tax_info = replace(line.tax_info, tax_amount=PROBE_SALES10_TAX)
                elif tax_info is not None and tax_info.tax_amount is not None:
                    tax_info = replace(tax_info, tax_amount=Decimal("0"))
                lines.append(replace(line, amount=amount, tax_info=tax_info,
                                     metadata={**line.metadata, LINE_ROW_DESCRIPTION_KEY: PROBE_DESCRIPTION}))
            entries.append(replace(entry, lines=lines, description=PROBE_DESCRIPTION))
        return entries


class _OnlyJournals:
    def __init__(self, inner, ids: frozenset[str]) -> None:
        self._inner, self._ids = inner, ids

    def supports(self, path, profile) -> bool:
        return self._inner.supports(path, profile)

    def record_count(self, path, profile) -> int:
        return self._inner.record_count(path, profile)

    def read(self, path, profile):
        return [entry for entry in self._inner.read(path, profile) if entry.id in self._ids]


class _AuditOnlyFieldsRemovedAdapter:
    """Input adapter that leaves audit-only fields out of the journal lines.

    Only for fields the Human confirmed as audit-only. The removed values stay
    in the entry metadata for the audit file and for the loss rule.
    """

    def __init__(self, inner, confirmed_fields: frozenset[str]) -> None:
        self._inner = inner
        self._confirmed = confirmed_fields

    def supports(self, path, profile) -> bool:
        return self._inner.supports(path, profile)

    def record_count(self, path, profile) -> int:
        return self._inner.record_count(path, profile)

    def read(self, path, profile):
        entries = []
        for entry in self._inner.read(path, profile):
            values = non_retained_values(entry)
            if DEPARTMENT_FIELD in self._confirmed and any(line.department for line in entry.lines):
                entry = replace(
                    entry,
                    lines=[replace(line, department=None) for line in entry.lines],
                    metadata={**entry.metadata, NON_RETAINED_VALUES_KEY: values},
                )
            entries.append(entry)
        return entries


def audit_path_for(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".audit.json")


def pending_audit_path_for(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".audit.json.pending")


AUDIT_SCHEMA = "yayoi-jdl-non-retained-audit-v1"


DROPPED_SUBACCOUNT_FIELD = "補助科目（親科目のみ・JDLへ引き継がない）"


def dropped_subaccount_values(entry: JournalEntry, profile) -> tuple[tuple[int, str, str], ...]:
    """(source row, field, "SIDE|parent|subaccount") for every subaccount the Human confirmed as 'parent only'.

    The JDL CSV carries the parent account with a blank subaccount for these lines; the original
    subaccount name is kept here (and in the audit file) so the omission is auditable."""
    if profile is None:
        return ()
    found = []
    for line in entry.lines:
        if not line.sub_account:
            continue
        mapping = profile.subaccount_context_mappings.get(
            MappingKey(MappingType.SUBACCOUNT, line.sub_account, line.account))
        if is_confirmed_parent_only(mapping):
            found.append((line.source_reference.row_number, DROPPED_SUBACCOUNT_FIELD,
                          f"{line.side.value}|{line.account}|{line.sub_account}"))
    return tuple(found)


def expected_non_retained(source: Path, profile) -> list[dict]:
    """One record per source journal that has values JDL will not hold, in source order."""
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    records = []
    for entry in source_format.read(source):
        values = non_retained_values(entry) + dropped_subaccount_values(entry, profile)
        noncredit = noncredit_approval.audit_lines(entry, profile)
        if values or noncredit:
            record = {
                "source_journal_content_sha256": entry.metadata.get(JOURNAL_CONTENT_IDENTITY_KEY),
                "date": entry.date.isoformat(),
                "source_rows": list(entry.metadata.get(ROW_ORDER_KEY, ())),
                "not_in_jdl": [{"row": row, "field": name, "value": value} for row, name, value in values],
            }
            if noncredit:  # only then: earlier audit files stay byte-identical
                record["noncredit_tax_lines"] = noncredit
            records.append(record)
    return records


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def begin_non_retained_audit(source: Path, output: Path, profile) -> Path | None:
    """Before the CSV exists: write the audit as .pending (no output hash yet).

    If the run stops after the CSV is written, the .pending file shows that the
    pair is incomplete; verify_non_retained_audit then fails.
    """
    records = expected_non_retained(source, profile)
    if not records:
        return None
    for path in (audit_path_for(output), pending_audit_path_for(output)):
        if path.exists():
            raise FileExistsError("audit file already exists")
    pending = pending_audit_path_for(output)
    _atomic_json(pending, {
        "schema": AUDIT_SCHEMA,
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "jdl_output_file": output.name,
        "jdl_output_sha256": None,
        "information_fully_retained": False,
        "field_meanings_confirmed_by_human": confirmed_optional_fields(profile),
        "journal_count": len(records),
        "value_count": sum(len(item["not_in_jdl"]) for item in records),
        **_noncredit_summary(records),
        "journals": records,
    })
    return pending


def _noncredit_summary(records: list[dict]) -> dict:
    lines = [line for item in records for line in item.get("noncredit_tax_lines", ())]
    if not lines:
        return {}
    return {
        "noncredit_tax_line_count": len(lines),
        "noncredit_note": ("弥生の控除不可（区分記載）は、税理士確認の記録に基づきJDLへ非仕入（課区34・税区/入力/税額は空欄）で"
                           "出力した。JDL CSVに残らない元の税区分・税率・税込金額・税額0・承認の参照を noncredit_tax_lines に記録する。"),
    }


def finish_non_retained_audit(output: Path) -> Path | None:
    pending = pending_audit_path_for(output)
    if not pending.exists():
        return None
    payload = json.loads(pending.read_text(encoding="utf-8"))
    payload["jdl_output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    final = audit_path_for(output)
    _atomic_json(final, payload)
    pending.unlink()
    return final


def verify_non_retained_audit(source: Path, output: Path, profile) -> dict:
    """Separate verdict for the information JDL does not hold.

    NOT_NEEDED: nothing left out. PASS: the audit exists, is final, belongs to
    this source and this CSV, and lists exactly the expected values.
    """
    expected = expected_non_retained(source, profile)
    final, pending = audit_path_for(output), pending_audit_path_for(output)
    if not expected:
        ok = not final.exists() and not pending.exists()
        return {"verdict": "NOT_NEEDED" if ok else "FAIL", "expected_journals": 0}
    result = {"expected_journals": len(expected),
              "expected_values": sum(len(item["not_in_jdl"]) for item in expected),
              "expected_noncredit_tax_lines": sum(len(item.get("noncredit_tax_lines", ())) for item in expected),
              "final_present": final.exists(), "pending_left": pending.exists()}
    if not final.exists() or pending.exists():
        result["verdict"] = "FAIL"
        return result
    payload = json.loads(final.read_text(encoding="utf-8"))
    checks = {
        "schema": payload.get("schema") == AUDIT_SCHEMA,
        "source_sha256": payload.get("source_sha256") == hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": payload.get("jdl_output_sha256") == hashlib.sha256(output.read_bytes()).hexdigest(),
        "journal_count": payload.get("journal_count") == len(payload.get("journals", ())) == len(expected),
        "records_equal": payload.get("journals") == expected,
        "noncredit_summary": {k: payload.get(k) for k in _noncredit_summary(expected)} == _noncredit_summary(expected),
        # Identical journals share a content hash, so one-to-one is by source rows.
        "one_record_per_journal": len({tuple(item["source_rows"]) for item in payload.get("journals", ())})
        == len(payload.get("journals", ())),
    }
    result.update(checks)
    result["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return result


# The workflow handles both Yayoi source formats.
YayoiJdlWorkflow = YayoiJournalReportJdlWorkflow

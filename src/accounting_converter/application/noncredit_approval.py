"""Yayoi 控除不可 → JDL 非仕入 (税区・入力・税額 blank): company-scoped, tax-accountant-signed approval only.

Technical Evidence (company A, JDL IBEX 出納帳 35.5, 税抜・原則課税・一括比例配分, see noncredit_observations):
  - CSV round trip: 非仕入 with blank 税区 / 入力 / 税額 imported and re-exported unchanged (NC-A-NP-10/8).
  - 消費税集計表（原則課税）before / after importing file A only: 課税仕入 (10% / 軽減8%, amount and tax) and
    課税仕入税額等合計 grew by the two controls only (21,800 / 1,800); the 43,600 of 非仕入 entered none of them.
  Not proven by JDL: that this is the same as Yayoi 控除不可 for the tax return. JDL counts it as 非課税仕入
  (課税売上割合 uses sales only, so the ratio is unaffected), and the 10% / 軽減8% / 区分記載 / 控除不可 facts are
  lost in the JDL CSV. That equivalence is the tax accountant's decision.

So nothing here is ever active by itself:
  - only the two exact Yayoi identities below, only the company and settings of the Evidence;
  - only after a Human records the tax accountant's sign-off for that company (stored in the company's own
    profile, never in source code), and only for the JOURNALS named in that sign-off (JOURNALS_V1): the record
    lists each journal by its content identity (date, sides, accounts, amounts, tax fields, descriptions; not the
    file name or row number). Another journal with the same Yayoi tax identity is NOT covered; a changed journal
    gets a new identity and falls out; the same unchanged journal re-exported under another file name still matches.
    An older identity-wide approval (no journal list) is invalid and blocks;
  - every converted line must be 借方・内税・税額0 (what Yayoi had and what was verified);
  - the lost facts go to the audit file next to the formal CSV.
Anything missing or different keeps the journal blocked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue

APPROVAL_KIND = "YAYOI_NONCREDIT_AS_JDL_NON_TAXABLE_PURCHASE_V1"
JDL_SCOPE = "非仕入"
JDL_SCOPE_CODE = "34"


@dataclass(frozen=True)
class NoncreditSource:
    tax_category: str      # Yayoi 税区分 as printed
    rate: str              # "10%" / "軽減8%"
    reduced_rate: bool
    invoice_class: str     # 区分記載
    purchase_credit: str   # 控除不可


# The exact identities of the Evidence. Any other "…｜控除不可" stays blocked.
NONCREDIT_SOURCES: dict[str, NoncreditSource] = {
    "課対仕入10%｜区分記載｜控除不可": NoncreditSource("課対仕入10%", "10%", False, "区分記載", "控除不可"),
    "課対仕入8%（軽）｜区分記載｜控除不可": NoncreditSource("課対仕入8%（軽）", "軽減8%", True, "区分記載", "控除不可"),
}


@dataclass(frozen=True)
class NoncreditTechnicalEvidence:
    evidence_id: str
    company_setting_ids: frozenset[str]
    scope_id: str
    probe_cases: dict[str, str]          # identity -> probe case of the same rate
    probe_sha256: str
    reexport_sha256: str
    tax_summary_before_sha256: str
    tax_summary_after_sha256: str
    technical_state: str
    note: str


TECHNICAL_EVIDENCE = NoncreditTechnicalEvidence(
    evidence_id="EVID-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-NONPUR-BLANK-TAXSUMMARY-001",
    company_setting_ids=frozenset({"company-f92affc1f3ed43c8aee36380ab612f9d"}),
    scope_id="JDL-35-5-TAX-EXCL-PROP-SALES-CEIL-PURCH-HALFUP-VOUCHER-ROWS-16",
    probe_cases={
        "課対仕入10%｜区分記載｜控除不可": "NC-A-NP-10",
        "課対仕入8%（軽）｜区分記載｜控除不可": "NC-A-NP-8",
    },
    probe_sha256="c0c8bf104d02df81775953e0f0448fdd0f55bea1c86e3804574509ae675ea5b0",
    reexport_sha256="184b1d1139becc1a3d4887cb53fb5a6772b7acd0e0770bc299c9d56367be0aa7",
    tax_summary_before_sha256="50c090d00a61daf34c53cb483eed7310af1af1304abe9f2d638892efa0fe63ae",
    tax_summary_after_sha256="17ac691b285e7b8202a2c75cfc4f94698f0224105584587ea56494afd0c99dbd",
    technical_state="TECHNICAL_VERIFIED_TAX_EQUIVALENCE_PENDING_TAX_ACCOUNTANT",
    note=("CSV往復PASS。消費税集計表（原則課税・令和8年7月度・税抜処理・仕入は税込額）で、A取込の前後の増分は"
          "対照2件（10% 11,000/1,000・軽減8% 10,800/800）だけ。非仕入2件（43,600）は課税仕入・税額・"
          "課税仕入税額等合計のどれにも入らない。課税売上割合0.00%のため一括比例の控除額（0）だけでは判別できず、"
          "課税仕入税額等合計で判定。帳票に非課税仕入の欄は無い。"),
)

# Scope of an approval: the journals it names (content identities). Stored in the identity's mapping metadata.
SCOPE_KEY = "noncredit_scope"
SCOPE_JOURNALS = "JOURNALS_V1"
JOURNALS_KEY = "noncredit_approved_journals"   # JSON list of journal records (see journal_record)

# Reason codes (all of them block).
IDENTITY_NOT_IN_EVIDENCE = "NONCREDIT_IDENTITY_NOT_IN_EVIDENCE"
COMPANY_OUT_OF_SCOPE = "NONCREDIT_COMPANY_OUT_OF_SCOPE"
CONTEXT_OUT_OF_SCOPE = "NONCREDIT_CONTEXT_OUT_OF_SCOPE"
SIGNOFF_MISSING = "NONCREDIT_TAX_ACCOUNTANT_SIGNOFF_MISSING"
APPROVAL_MISSING = "NONCREDIT_APPROVAL_MISSING"
APPROVAL_INVALID = "NONCREDIT_APPROVAL_INVALID"
LINE_SHAPE_UNVERIFIED = "NONCREDIT_LINE_NOT_DEBIT_INTERNAL_TAX_ZERO"
SCOPE_IDENTITY_WIDE = "NONCREDIT_APPROVAL_NOT_SCOPED_TO_JOURNALS"
JOURNAL_NOT_APPROVED = "NONCREDIT_JOURNAL_NOT_APPROVED"
JOURNAL_AMBIGUOUS = "NONCREDIT_JOURNAL_IDENTITY_NOT_UNIQUE"
_RECORD_SIGNOFF_FIELDS = ("human_approver", "tax_accountant", "signoff_reference", "signoff_date")


def journal_record(entry, identity: str, *, human_approver: str, tax_accountant: str, signoff_reference: str,
                   signoff_date: str, label: str = "") -> dict:
    """What one journal's sign-off covers: its content identity and the 控除不可 lines as they were approved.

    `label` (e.g. the journal number shown on screen) is for people only; matching uses the content identity.
    """
    from accounting_converter.domain.journal_identity import stable_journal_identity

    lines = [line for line in entry.lines if line.tax_info is not None and line.tax_info.category == identity]
    return {
        "journal_content_sha256": stable_journal_identity(entry) or "",
        "label": label,
        "date": entry.date.isoformat() if hasattr(entry.date, "isoformat") else str(entry.date),
        "lines": [{
            "row": str(line.metadata.get("journal_row_number", line.source_reference.row_number)),
            "account": line.account or "", "amount": str(line.amount),
            "tax_amount": str(line.tax_info.tax_amount) if line.tax_info.tax_amount is not None else "",
            "description": str(line.metadata.get("journal_row_description", "")),
        } for line in lines],
        "human_approver": human_approver, "tax_accountant": tax_accountant,
        "signoff_reference": signoff_reference, "signoff_date": signoff_date,
    }


def approved_journals(mapping: MappingValue | None) -> dict[str, dict]:
    """content identity -> record, from a JOURNALS_V1 approval. {} for anything else (never identity-wide)."""
    import json

    meta = (mapping.metadata or {}) if mapping is not None else {}
    if meta.get(SCOPE_KEY) != SCOPE_JOURNALS:
        return {}
    try:
        records = json.loads(meta.get(JOURNALS_KEY, "[]"))
    except (TypeError, ValueError):
        return {}
    found = {}
    for record in records if isinstance(records, list) else ():
        sha = record.get("journal_content_sha256") if isinstance(record, dict) else None
        if (isinstance(sha, str) and len(sha) == 64 and record.get("lines")
                and all(str(record.get(k, "")).strip() for k in _RECORD_SIGNOFF_FIELDS)):
            found[sha] = record
    return found


def is_target_identity(identity: str | None) -> bool:
    return identity in NONCREDIT_SOURCES


def _context_in_scope(context) -> bool:
    from accounting_converter.adapters.output.jdl import scoped_evidence
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    return bool(
        context is not None
        and ev.context_is_verified(context)
        and scoped_evidence.scope_state(context) is scoped_evidence.ScopeState.IN_SCOPE
        and scoped_evidence.SCOPE_ID == TECHNICAL_EVIDENCE.scope_id
        # The tax-summary Evidence ran under 16 rows; it is never carried to another row setting.
        and context.voucher_row_limit == scoped_evidence.SCOPE_VOUCHER_ROW_LIMIT
    )


def technical_problems(identity: str, company_setting_id: str | None, context) -> tuple[str, ...]:
    """Everything except the sign-off: does the Evidence cover this identity, company and JDL setting?"""
    problems = []
    if not is_target_identity(identity):
        problems.append(IDENTITY_NOT_IN_EVIDENCE)
    if company_setting_id not in TECHNICAL_EVIDENCE.company_setting_ids:
        problems.append(COMPANY_OUT_OF_SCOPE)
    if not _context_in_scope(context):
        problems.append(CONTEXT_OUT_OF_SCOPE)
    return tuple(problems)


def approve_noncredit_identity(
    store,
    profile_id: str,
    company_setting_id: str,
    context,
    identity: str,
    *,
    human_approver: str,
    tax_accountant: str,
    signoff_reference: str,
    signoff_date: date,
    rate_distinction_loss_acknowledged: bool,
    judge_report_sha256: str = "",
    journals=(),
    source_entries=(),
    labels: dict | None = None,
):
    """Save the Human's record of the tax accountant's sign-off for ONE identity of ONE company, for the given
    JOURNALS only (parsed source entries). Journals approved earlier for the same identity are kept.

    `source_entries`: the whole parsed source, to refuse a journal whose content identity is not unique in it.
    The approval is data in this company's profile. Nothing is approved by default and nothing is inferred.
    """
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
    from accounting_converter.application.mapping_review import MappingConfirmationService

    problems = list(technical_problems(identity, company_setting_id, context))
    fields = (human_approver, tax_accountant, signoff_reference)
    if not all(isinstance(value, str) and value.strip() for value in fields) or not isinstance(signoff_date, date):
        problems.append(SIGNOFF_MISSING)
    if rate_distinction_loss_acknowledged is not True:
        problems.append("NONCREDIT_RATE_LOSS_NOT_ACKNOWLEDGED")
    problems.extend(_journal_problems(identity, journals, source_entries))
    if problems:
        raise ValueError("控除不可の承認はできません: " + ", ".join(dict.fromkeys(problems)))
    import json

    existing_profile = store.get(profile_id)
    existing = existing_profile.tax_mappings.get(identity)
    kept = approved_journals(existing) if not mapping_problems(identity, existing, existing_profile, context) else {}
    signed = dict(human_approver=human_approver.strip(), tax_accountant=tax_accountant.strip(),
                  signoff_reference=signoff_reference.strip(), signoff_date=signoff_date.isoformat())
    for entry in journals:
        record = journal_record(entry, identity, label=(labels or {}).get(entry.id, ""), **signed)
        kept[record["journal_content_sha256"]] = record
    source = NONCREDIT_SOURCES[identity]
    return MappingConfirmationService(store).confirm_mapping(
        profile_id,
        MappingKey(MappingType.TAX_CATEGORY, identity),
        "",
        metadata={
            "jdl_tax_scope": JDL_SCOPE,
            # What JDL receives (非仕入・blank) is the existing verified literal.
            "jdl_evidence_id": ev.NONPUR_3181_EVIDENCE_ID,
            "jdl_tax_processing_mode": context.tax_processing_mode.value,
            "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
            "noncredit_approval_kind": APPROVAL_KIND,
            "noncredit_evidence_id": TECHNICAL_EVIDENCE.evidence_id,
            "noncredit_probe_case": TECHNICAL_EVIDENCE.probe_cases[identity],
            "noncredit_scope_id": TECHNICAL_EVIDENCE.scope_id,
            "noncredit_company_setting_id": company_setting_id,
            "noncredit_profile_id": profile_id,
            "noncredit_source_rate": source.rate,
            "noncredit_human_approver": human_approver.strip(),
            "noncredit_tax_accountant": tax_accountant.strip(),
            "noncredit_signoff_reference": signoff_reference.strip(),
            "noncredit_signoff_date": signoff_date.isoformat(),
            "noncredit_rate_distinction_loss_acknowledged": "true",
            "noncredit_judge_report_sha256": judge_report_sha256,
            "noncredit_approved_at": datetime.now(timezone.utc).isoformat(),
            SCOPE_KEY: SCOPE_JOURNALS,
            JOURNALS_KEY: json.dumps(list(kept.values()), ensure_ascii=False, sort_keys=True),
        },
        allow_empty_tax_target=True,
    )


def _journal_problems(identity: str, journals, source_entries) -> list[str]:
    """Every named journal must exist once in the source, carry a line of `identity`, and have the verified shape."""
    from accounting_converter.domain.journal_identity import stable_journal_identity

    if not journals:
        return ["NONCREDIT_NO_JOURNAL_NAMED"]
    problems = []
    seen = [stable_journal_identity(entry) for entry in source_entries]
    for entry in journals:
        sha = stable_journal_identity(entry)
        lines = [line for line in entry.lines if line.tax_info is not None and line.tax_info.category == identity]
        if sha is None:
            problems.append("NONCREDIT_JOURNAL_WITHOUT_CONTENT_IDENTITY")
        elif source_entries and seen.count(sha) != 1:
            problems.append(JOURNAL_AMBIGUOUS)
        if not lines:
            problems.append("NONCREDIT_JOURNAL_HAS_NO_LINE_OF_THIS_IDENTITY")
        if any(line_problems(line) for line in lines):
            problems.append(LINE_SHAPE_UNVERIFIED)
    return problems


def mapping_problems(identity: str, mapping: MappingValue | None, profile, context) -> tuple[str, ...]:
    """Conversion-time check of a saved approval. () only when every condition still holds."""
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
        return (APPROVAL_MISSING,)
    meta = mapping.metadata or {}
    company = meta.get("noncredit_company_setting_id")
    problems = list(technical_problems(identity, company, context))
    expected = {
        "noncredit_approval_kind": APPROVAL_KIND,
        "noncredit_evidence_id": TECHNICAL_EVIDENCE.evidence_id,
        "noncredit_scope_id": TECHNICAL_EVIDENCE.scope_id,
        "noncredit_probe_case": TECHNICAL_EVIDENCE.probe_cases.get(identity),
        "noncredit_source_rate": NONCREDIT_SOURCES[identity].rate if is_target_identity(identity) else None,
        "noncredit_profile_id": getattr(profile, "profile_id", None),
        "noncredit_rate_distinction_loss_acknowledged": "true",
        "jdl_tax_scope": JDL_SCOPE,
        "jdl_evidence_id": ev.NONPUR_3181_EVIDENCE_ID,
    }
    if (
        any(meta.get(key) != value for key, value in expected.items())
        or (mapping.target_value or "") != ""
        or context is None
        or meta.get("jdl_tax_context_identity_sha256") != ev.tax_context_identity_sha256(context)
    ):
        problems.append(APPROVAL_INVALID)
    if not all(str(meta.get(key, "")).strip() for key in (
            "noncredit_human_approver", "noncredit_tax_accountant", "noncredit_signoff_reference",
            "noncredit_signoff_date")):
        problems.append(SIGNOFF_MISSING)
    if not approved_journals(mapping):
        problems.append(SCOPE_IDENTITY_WIDE)  # an approval must name its journals; identity-wide never converts
    return tuple(dict.fromkeys(problems))


# A what-if profile carries this marker on every hypothetical sign-off. ConversionProfileStore refuses to write any
# profile that carries it, so a trial can never become a saved approval (see infrastructure/conversion_profile_store.py).
TRIAL_MARKER = "noncredit_trial_only"
TRIAL_PERSON = "（試算・承認ではありません）"


def signoff_trial_profile(profile, context, company_setting_id: str | None, entries=()):
    """In-memory copy of `profile` AS IF the tax accountant had signed off each of `entries` (journals) separately.

    Used ONLY to show what would still block after that decision (a what-if, like the 16/64 comparison).
    Returns None when the technical Evidence does not cover this company / JDL setting (then no decision of the tax
    accountant alone can make these lines convertible). Never saved: the store rejects TRIAL_MARKER.
    """
    from dataclasses import replace as _replace

    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    if profile is None or context is None:
        return None
    if any(technical_problems(identity, company_setting_id, context) for identity in NONCREDIT_SOURCES):
        return None
    import json

    mappings = dict(profile.tax_mappings)
    for identity, source in NONCREDIT_SOURCES.items():
        records = [journal_record(entry, identity, human_approver=TRIAL_PERSON, tax_accountant=TRIAL_PERSON,
                                  signoff_reference=TRIAL_PERSON, signoff_date="0001-01-01")
                   for entry in entries if any(line.tax_info is not None and line.tax_info.category == identity
                                               for line in entry.lines)]
        records = [r for r in records if r["journal_content_sha256"]]
        if not records:
            continue
        mappings[identity] = MappingValue(identity, "", MappingStatus.USER_CONFIRMED, None, {
            "jdl_tax_scope": JDL_SCOPE,
            "jdl_evidence_id": ev.NONPUR_3181_EVIDENCE_ID,
            "jdl_tax_processing_mode": context.tax_processing_mode.value,
            "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
            "noncredit_approval_kind": APPROVAL_KIND,
            "noncredit_evidence_id": TECHNICAL_EVIDENCE.evidence_id,
            "noncredit_probe_case": TECHNICAL_EVIDENCE.probe_cases[identity],
            "noncredit_scope_id": TECHNICAL_EVIDENCE.scope_id,
            "noncredit_company_setting_id": company_setting_id or "",
            "noncredit_profile_id": profile.profile_id,
            "noncredit_source_rate": source.rate,
            "noncredit_human_approver": TRIAL_PERSON,
            "noncredit_tax_accountant": TRIAL_PERSON,
            "noncredit_signoff_reference": TRIAL_PERSON,
            "noncredit_signoff_date": "0001-01-01",
            "noncredit_rate_distinction_loss_acknowledged": "true",
            SCOPE_KEY: SCOPE_JOURNALS,
            JOURNALS_KEY: json.dumps(records, ensure_ascii=False, sort_keys=True),
            TRIAL_MARKER: "true",
        })
    return _replace(profile, tax_mappings=mappings)


def line_problems(line) -> tuple[str, ...]:
    """The verified shape: Yayoi 借方・内税・税額0 (the whole payment stays in the expense amount)."""
    from accounting_converter.adapters.input.yayoi.journal_report_parser import YAYOI_TAX_CALCULATION_KEY

    info = line.tax_info
    if (
        info is None
        or line.side.value != "DEBIT"
        or info.tax_amount is None or info.tax_amount != 0
        or (info.metadata or {}).get(YAYOI_TAX_CALCULATION_KEY) != "内税"
        or line.amount <= 0
    ):
        return (LINE_SHAPE_UNVERIFIED,)
    return ()


def is_approved_line(line, profile, context) -> bool:
    """The line's own journal is named in a valid sign-off of its identity (not merely the identity)."""
    from accounting_converter.domain.journal_identity import line_journal_identity

    category = line.tax_info.category if line.tax_info else None
    if not is_target_identity(category) or profile is None:
        return False
    mapping = profile.tax_mappings.get(category)
    if mapping_problems(category, mapping, profile, context) or line_problems(line):
        return False
    sha = line_journal_identity(line)
    return sha is not None and sha in approved_journals(mapping)


def journal_approval(entry, profile, context) -> dict[str, dict]:
    """identity -> the valid sign-off record that covers THIS journal (read-only, for screens and audit)."""
    from accounting_converter.domain.journal_identity import stable_journal_identity

    sha = stable_journal_identity(entry)
    found = {}
    if profile is None or sha is None:
        return found
    for line in entry.lines:
        category = line.tax_info.category if line.tax_info else None
        if not is_target_identity(category) or category in found:
            continue
        mapping = profile.tax_mappings.get(category)
        if not mapping_problems(category, mapping, profile, context):
            record = approved_journals(mapping).get(sha)
            if record is not None:
                found[category] = record
    return found


def unapproved_journals(entries, profile, context) -> frozenset[str]:
    """Ids of source journals with a 控除不可 line that no sign-off covers for that very journal, or whose content
    identity occurs more than once in the source (a sign-off must point at exactly one journal)."""
    from collections import Counter

    from accounting_converter.domain.journal_identity import stable_journal_identity

    counts = Counter(stable_journal_identity(entry) for entry in entries)
    blocked = set()
    for entry in entries:
        lines = [line for line in entry.lines
                 if line.tax_info is not None and (line.tax_info.category or "").rsplit("｜", 1)[-1] == "控除不可"]
        if not lines:
            continue
        sha = stable_journal_identity(entry)
        if sha is None or counts[sha] != 1 or not all(is_approved_line(line, profile, context) for line in lines):
            blocked.add(entry.id)
    return frozenset(blocked)


def audit_lines(entry, profile) -> list[dict]:
    """What the JDL CSV loses for each approved 控除不可 line (written to the audit file)."""
    if profile is None:
        return []
    from accounting_converter.adapters.input.yayoi.journal_report_parser import YAYOI_TAX_CALCULATION_KEY

    found = []
    for line in entry.lines:
        category = line.tax_info.category if line.tax_info else None
        if not is_target_identity(category):
            continue
        mapping = profile.tax_mappings.get(category)
        meta = (mapping.metadata or {}) if mapping is not None else {}
        if mapping is None or meta.get("noncredit_approval_kind") != APPROVAL_KIND:
            continue
        from accounting_converter.domain.journal_identity import line_journal_identity

        record = approved_journals(mapping).get(line_journal_identity(line) or "")
        if record is None:
            continue  # not this journal's approval: such a line is never converted, so it is never audited as one
        source = NONCREDIT_SOURCES[category]
        found.append({
            "row": int(line.metadata.get("journal_row_number", line.source_reference.row_number)),
            "yayoi_journal_number": str(line.metadata.get("yayoi_journal_number") or ""),
            "side": line.side.value,
            "source_account": line.account or "",
            "source_sub_account": line.sub_account or "",
            "source_tax_identity": category,
            "source_tax_category": source.tax_category,
            "source_rate": source.rate,
            "source_reduced_rate": source.reduced_rate,
            "source_invoice_class": source.invoice_class,
            "source_purchase_credit": source.purchase_credit,
            "source_tax_calculation": str((line.tax_info.metadata or {}).get(YAYOI_TAX_CALCULATION_KEY, "")),
            "source_amount_tax_included": str(line.amount),
            "source_tax_amount": str(line.tax_info.tax_amount) if line.tax_info.tax_amount is not None else "",
            "jdl_tax_scope": JDL_SCOPE,
            "jdl_tax_scope_code": JDL_SCOPE_CODE,
            "jdl_tax_rate_cell": "",
            "jdl_tax_input_method": "",
            "jdl_tax_amount": "",
            "noncredit_evidence_id": meta.get("noncredit_evidence_id", ""),
            "jdl_literal_evidence_id": meta.get("jdl_evidence_id", ""),
            "company_setting_id": meta.get("noncredit_company_setting_id", ""),
            "approval_scope": SCOPE_JOURNALS,
            "approved_journal_content_sha256": record["journal_content_sha256"],
            "approved_journal_label": record.get("label", ""),
            "human_approver": record["human_approver"],
            "approved_at": meta.get("noncredit_approved_at", ""),
            "tax_accountant": record["tax_accountant"],
            "tax_accountant_signoff_reference": record["signoff_reference"],
            "tax_accountant_signoff_date": record["signoff_date"],
            "lost_in_jdl": "税率（10%/軽減8%）・区分記載・控除不可（JDLでは非課税仕入として集計）",
        })
    return found


LOSS_TEXT = ("JDLでは非課税仕入（課区34）として集計され、10%／軽減8%・区分記載・控除不可の区別はCSVに残りません"
             "（元の税区分・税込金額・税額0は監査記録に保存します）。")


def review_reason(identity: str, company_setting_id: str | None, profile, context) -> tuple[str, str, str]:
    """(blocker_code, reason, target_display) for the tax confirmation screen."""
    if not is_target_identity(identity):
        return ("YAYOI-JDL-TAX-REPRESENTATION-UNVERIFIED",
                "この控除不可の税区分（税率・請求書区分の組合せ）はJDL実機で確認していません。変換しません。", "候補なし")
    technical = technical_problems(identity, company_setting_id, context)
    if technical:
        return ("YAYOI-JDL-TAX-REPRESENTATION-UNVERIFIED",
                "控除不可の書き方は、実機で確認した会社・JDL設定（35.5・税抜・原則課税・一括比例配分・"
                "端数 売上切上げ/仕入四捨五入・振替伝票16行）でだけ確認済みです。この会社・設定では変換しません。",
                "候補なし")
    mapping = profile.tax_mappings.get(identity) if profile is not None else None
    problems = mapping_problems(identity, mapping, profile, context)
    if problems and problems != (APPROVAL_MISSING,) and mapping is not None \
            and mapping.metadata.get("noncredit_approval_kind"):
        return ("YAYOI-JDL-TAX-NONCREDIT-APPROVAL-INVALID",
                "保存された控除不可の承認が、現在の会社設定・Evidenceと一致しません（" + "、".join(problems) +
                "）。変換しません。税理士確認を記録し直してください。", "非仕入（税区空欄）※承認無効")
    return ("YAYOI-JDL-TAX-NONCREDIT-TAX-ACCOUNTANT-SIGNOFF-REQUIRED",
            "JDL実機の技術確認は済み（非仕入・税区空欄で取込・再Export一致、消費税集計で課税仕入・税額に入らない）。"
            "弥生の控除不可と申告上同じ扱いかは税理士の確認が必要で、確認（SIGNOFF）の記録が済むまで変換しません。"
            "承認は仕訳ごとに記録し、同じ税区分の他の仕訳には適用されません。"
            + LOSS_TEXT, "非仕入（税区空欄）※税理士確認後のみ")

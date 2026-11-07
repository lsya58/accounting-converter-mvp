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
    profile, never in source code);
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

# Reason codes (all of them block).
IDENTITY_NOT_IN_EVIDENCE = "NONCREDIT_IDENTITY_NOT_IN_EVIDENCE"
COMPANY_OUT_OF_SCOPE = "NONCREDIT_COMPANY_OUT_OF_SCOPE"
CONTEXT_OUT_OF_SCOPE = "NONCREDIT_CONTEXT_OUT_OF_SCOPE"
SIGNOFF_MISSING = "NONCREDIT_TAX_ACCOUNTANT_SIGNOFF_MISSING"
APPROVAL_MISSING = "NONCREDIT_APPROVAL_MISSING"
APPROVAL_INVALID = "NONCREDIT_APPROVAL_INVALID"
LINE_SHAPE_UNVERIFIED = "NONCREDIT_LINE_NOT_DEBIT_INTERNAL_TAX_ZERO"


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
):
    """Save the Human's record of the tax accountant's sign-off for ONE identity of ONE company.

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
    if problems:
        raise ValueError("控除不可の承認はできません: " + ", ".join(problems))
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
        },
        allow_empty_tax_target=True,
    )


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
    return tuple(dict.fromkeys(problems))


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
    category = line.tax_info.category if line.tax_info else None
    if not is_target_identity(category) or profile is None:
        return False
    mapping = profile.tax_mappings.get(category)
    return not mapping_problems(category, mapping, profile, context) and not line_problems(line)


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
            "human_approver": meta.get("noncredit_human_approver", ""),
            "approved_at": meta.get("noncredit_approved_at", ""),
            "tax_accountant": meta.get("noncredit_tax_accountant", ""),
            "tax_accountant_signoff_reference": meta.get("noncredit_signoff_reference", ""),
            "tax_accountant_signoff_date": meta.get("noncredit_signoff_date", ""),
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
            + LOSS_TEXT, "非仕入（税区空欄）※税理士確認後のみ")

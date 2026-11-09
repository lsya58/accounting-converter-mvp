"""Read-only model of "what is missing and what can the user do", built ONLY from the formal assessment.

The READY / BLOCK decision is made by `YayoiJdlWorkflow.assess` and nothing here changes it: this module groups the
blockers that assessment already produced, keeps every code of every journal, and says in user language

  what the problem is / which journals it touches / what is confirmed / what to do / where the work happens /
  whether a tax accountant or technical Evidence is needed / that a re-diagnosis follows.

It never creates READY, never approves anything and has no button of its own: `action` only names an EXISTING screen
the UI can open (accounts tab, tax review, row limit, information policy, split approval ...). An item gets an action
only when the user alone can resolve it; Evidence gaps and tax-accountant decisions get none.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from accounting_converter.application import readiness_breakdown as breakdown
from accounting_converter.application import tax_review_facts
from accounting_converter.application.noncredit_observations import is_noncredit_identity

# action kinds the UI may connect to an existing screen
ACT_ACCOUNTS, ACT_SUBACCOUNTS, ACT_TAX, ACT_ROW_LIMIT = "ACCOUNTS_TAB", "SUBACCOUNTS_TAB", "TAX_REVIEW", "ROW_LIMIT"
ACT_INFO_POLICY, ACT_DESCRIPTIONS, ACT_SPLIT, ACT_COMPARE = "INFORMATION_POLICY", "DESCRIPTION_TAB", "SPLIT_APPROVAL", "COMPARE"
ACT_COMPANY, ACT_NONE = "COMPANY_SETTING", "NONE"

WHERE_APP, WHERE_JDL, WHERE_TAX, WHERE_DEV = "アプリ内", "JDL側の作業", "税理士の判断", "開発側（追加の実機確認・実装）"

NEGATIVE_KEY, NONCREDIT_KEY, OVER_OTHER_KEY = "NEGATIVE_AMOUNT", "NONCREDIT", "OVER_LIMIT_OTHER"
EVIDENCE_KEY, IMPLEMENTATION_KEY = "EVIDENCE_GAP", "IMPLEMENTATION_GAP"


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    problem: str
    confirmed: str
    todo: str
    where: tuple[str, ...]
    action: str = ACT_NONE
    action_label: str = ""
    tax_accountant: bool = False
    technical_evidence: bool = False
    jdl_work: bool = False


_CODE_RULES: dict[str, Rule] = {r.key: r for r in (
    Rule("SYSTEM_EVIDENCE:TAX_CONTEXT_UNVERIFIED", "JDLの税設定が確認済みではありません",
         "JDL税設定（課税方式・端数処理など）が未確認のため、税区分を確定できません。", "",
         "会社設定でJDL税設定を確認して保存してください。", (WHERE_APP,), ACT_COMPANY, "会社設定を開く"),
    Rule("HUMAN:JDL_TAX_ROUNDING_SETTING", "消費税の端数処理が未入力です", "JDL会社の端数処理（売上・仕入）が入力されていません。", "",
         "JDLの会社設定を見て、会社設定に入力してください。", (WHERE_APP,), ACT_COMPANY, "会社設定を開く"),
    Rule("HUMAN:VOUCHER_ROW_LIMIT_SETTING", "振替伝票入力行数が未入力です", "JDLの「振替伝票入力行数」が会社設定に入力されていません。", "",
         "JDLの会社設定に表示されている数字を入力してください（アプリは補完しません）。", (WHERE_APP,), ACT_ROW_LIMIT, "行数を入力…"),
    Rule("SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED", "この振替伝票入力行数はJDL実機で未確認です",
         "入力された行数の設定は、JDL実機の取込確認がまだありません。", "16行以内・64行以内は実機確認済みです。",
         "実機確認が済むまで変換できません。確認済みの行数に変更できる場合は変更してください。", (WHERE_DEV,), ACT_ROW_LIMIT, "行数を確認・変更…",
         technical_evidence=True),
    Rule("SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SUBACCOUNT_UNVERIFIED", "この行数設定では補助科目付きの行が未確認です",
         "この振替伝票入力行数で、補助科目を含む行の実機確認がありません。", "", "追加の実機確認が必要です（設定では解消しません）。",
         (WHERE_DEV,), technical_evidence=True),
    Rule("HUMAN:ACCOUNT_MAPPING", "科目の対応が未確認です", "元の科目に対応するJDL科目が確認されていません。", "確認済みの科目対応は再利用されます。",
         "「科目」タブで対応するJDL科目を選んで保存してください。", (WHERE_APP,), ACT_ACCOUNTS, "科目を確認…"),
    Rule("HUMAN:SUBACCOUNT_MAPPING", "補助科目の対応・登録が必要です", "元の補助科目の扱い（親科目のみ・既存補助・JDLへの新規登録）が決まっていません。",
         "", "「補助科目」タブで扱いを選んでください。JDLへ新規登録が必要な補助は、JDL側で登録後にマスターを更新します"
         "（登録済みになったことはアプリ内の操作だけでは確認できません）。", (WHERE_APP, WHERE_JDL), ACT_SUBACCOUNTS, "補助科目を確認…", jdl_work=True),
    Rule("HUMAN:SUBACCOUNT_DEFAULT", "補助なしの仕訳のまとめ先補助が未確認です", "補助科目が必須の親科目で、補助なしの仕訳の扱いが未確認です。", "",
         "「補助科目」タブで確認してください。", (WHERE_APP,), ACT_SUBACCOUNTS, "補助科目を確認…"),
    Rule("HUMAN:TAX_MAPPING", "税区分の対応が未確認です", "元の税区分に対応するJDLの税区分が確認されていません。", "確認済みのJDL税設定を前提に候補を表示します。",
         "「税区分」の確認画面で候補を確認してください（候補が無い税区分はここでは確定できません）。", (WHERE_APP,), ACT_TAX, "税区分を確認…"),
    Rule("HUMAN:TRANSITIONAL_CREDIT_PERIOD", "控除割合と取引日の期間が合っていません",
         "免税事業者等からの仕入れの経過措置の割合（80%・70%など）が取引日の期間と食い違っています。", "",
         "元データの割合と取引日を税理士が確認してください。アプリは割合を書き換えません。", (WHERE_TAX,), tax_accountant=True),
    Rule("HUMAN:DEPARTMENT_POLICY", "部門の扱いが未確認です", "JDLに保持先のない部門があります。", "", "JDLへは出さず監査記録に残す扱いを確認してください。",
         (WHERE_APP,), ACT_INFO_POLICY, "扱いを確認…"),
    Rule("HUMAN:OPTIONAL_FIELD_POLICY", "JDLに入らない情報の扱いが未確認です", "生成元・付箋などJDLに保持先のない情報があります。", "",
         "意味と扱い（JDLへは出さず監査記録に残す）を確認してください。", (WHERE_APP,), ACT_INFO_POLICY, "扱いを確認…"),
    Rule("HUMAN:DESCRIPTION_REPLACEMENT", "JDLに入らない摘要の文字があります", "JDLで保持できない文字が摘要に含まれています。", "",
         "「摘要・文字置換」タブで置き換え内容を確認してください。", (WHERE_APP,), ACT_DESCRIPTIONS, "摘要を確認…"),
    Rule("HUMAN:VOUCHER_SPLIT_APPROVAL", "伝票分割の承認待ちの仕訳があります",
         "振替伝票入力行数を超える仕訳を、JDLでは複数の伝票に分けて取り込みます。分割後の各伝票の形はJDL実機で確認済みです。",
         "分割案の借貸・金額・税額・科目・摘要が元と一致することは、再構成検査で確認済みです。",
         "税理士が分割を了承したら、その内容をアプリに記録してください（会社・行数設定ごと）。", (WHERE_APP, WHERE_TAX), ACT_SPLIT,
         "分割案を確認して承認を記録…", tax_accountant=True),
    Rule("SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION", "決算仕訳のJDL CSVでの表し方が未確認です",
         "本決算のうち実機で確認した形だけを決算整理仕訳（日付13月）で出力します。それ以外（中間決算など）のCSVでの保持方法は未確認です。",
         "本決算の取込・再Exportは実機確認済みです。", "追加の実機確認が必要です。通常仕訳や本決算への置き換えは会計判断なので行いません。承認では解除できません。",
         (WHERE_DEV,), technical_evidence=True),
)}

_EXTRA_RULES: dict[str, Rule] = {r.key: r for r in (
    Rule(NONCREDIT_KEY, "税区分の確認が必要な仕訳があります（控除不可）",
         "元データの仕入税額控除が「控除不可」の明細があります（弥生の経過措置の割合を選ぶ欄の「控除なし」）。入力内容の確認が必要です"
         "（誤りと確定したわけではありません）。JDLには同じ区分が無く、非仕入（税区空欄）で表す方法だけが実機で確認されています。",
         "非仕入にするとCSVの往復・消費税集計への影響は確認済みです。ただし元の10%・軽減8%の区別がJDLに残らない点、"
         "申告上同じ扱いにしてよいかは未確認です。元の税区分は変更しません。",
         "税理士が、取引の実態（相手・商品の所在地・輸入の有無など）と控除不可にした理由を確認してください。"
         "回答・承認記録があるまで変換しません。承認記録はこの画面からは行いません。",
         (WHERE_TAX,), tax_accountant=True),
    Rule(NEGATIVE_KEY, "JDL CSVへの負の金額の入力方法が確認できません",
         "借方に負の金額（負の消費税を含む）の明細があります。JDLのCSV取込は、借方金額・借方消費税の「-」を数値以外として拒否しました（実機確認、確認した形の範囲）。",
         "負の金額を正に変える・借方と貸方を入れ替える・税額を変えることはしません（意味が変わるため）。"
         "なお、前回の確認用ファイルで分割後の1伝票が「仕訳数が多すぎます」と拒否された原因（取込時の行数設定か）は未確定です。",
         "(1) 技術面: 負の明細をJDLへ入れる別の方法（画面入力など）の調査。(2) 税理士判断: 負の明細の意味（返品・値引きなど）と表し方。"
         "分割が必要な場合は、分割後の伝票の形の実機確認も別途必要です。", (WHERE_DEV, WHERE_TAX), tax_accountant=True, technical_evidence=True),
    Rule(OVER_OTHER_KEY, "行数が多く、分割規則の対象外の仕訳があります",
         "振替伝票入力行数を超えていますが、承認で分割できる形（片側1行の相手科目）ではありません。", "",
         "JDLで手入力するか、行数設定を変えた場合の結果を比較で確認してください（アプリは自動で分割しません）。", (WHERE_JDL,), ACT_COMPARE,
         "16行・64行を比較…"),
)}
_GENERIC_EVIDENCE = Rule(EVIDENCE_KEY, "JDL実機で未確認の形があります", "この仕訳の税・構造の書き方は、JDL実機で確認されていません。", "",
                         "追加の実機確認が必要です（設定や承認では解消しません）。", (WHERE_DEV,), technical_evidence=True)
_GENERIC_IMPL = Rule(IMPLEMENTATION_KEY, "アプリが未対応の仕訳があります", "変換仕様上、まだ対応していない仕訳です。", "",
                     "開発側の対応が必要です。", (WHERE_DEV,), technical_evidence=True)
_GENERIC_OTHER = Rule("OTHER", "確認が必要な項目があります", "", "", "詳細表示のBLOCKコードを確認してください。", (WHERE_APP,))


def rule_for_code(code: str) -> Rule:
    if code in _CODE_RULES:
        return _CODE_RULES[code]
    if code.startswith("SYSTEM_EVIDENCE:"):
        return _GENERIC_EVIDENCE
    if code.startswith("SYSTEM_IMPLEMENTATION:"):
        return _GENERIC_IMPL
    category, action = breakdown.describe(code)
    return Rule(code, category, "", "", action, (WHERE_APP,))


@dataclass(frozen=True)
class ResolutionItem:
    key: str
    title: str
    problem: str
    confirmed: str
    todo: str
    where: tuple[str, ...]
    action: str
    action_label: str
    tax_accountant: bool
    technical_evidence: bool
    jdl_work: bool
    journals: tuple[str, ...]          # short ids (all of them)
    only_this: int                     # journals whose ONLY blocker group is this one
    codes: tuple[str, ...]             # every blocker code behind this item (kept in full)

    @property
    def app_resolvable(self) -> bool:
        """The user alone can resolve it with an existing screen (no Evidence / tax-accountant decision pending)."""
        return self.action not in {ACT_NONE, ACT_COMPARE} and not self.technical_evidence


@dataclass(frozen=True)
class TaxDecisionOutlook:
    """Which blockers of a 控除不可 journal depend on the tax decision (a what-if, never a decision).

    direct    : caused by the 控除不可 line itself (HUMAN:TAX_MAPPING)
    derived   : present now, absent in the what-if where the tax accountant's sign-off is recorded
                (they could not be evaluated while the tax category was open)
    independent: present now and NOT about the tax category (row count ...). Never counted as derived even when the
                what-if re-labels it (16行超 becomes 分割承認待ち once the tax side is evaluable).
    remaining : still present in that what-if (independent of the tax decision: rows, split approval, Evidence ...)
    computed  : False when the what-if could not run (the technical Evidence does not cover this company / setting);
                then every non-direct code stays in `remaining` and nothing is claimed about it.
    """
    direct: tuple[str, ...]
    derived: tuple[str, ...]
    independent: tuple[str, ...]
    remaining: tuple[str, ...]
    computed: bool
    basis: str

    @property
    def convertible_after_decision(self) -> bool:
        return self.computed and not self.remaining

    @property
    def technical_remaining(self) -> tuple[str, ...]:
        return tuple(c for c in self.remaining if c.startswith(("SYSTEM_EVIDENCE:", "SYSTEM_IMPLEMENTATION:")))

    @property
    def headline(self) -> str:
        if not self.computed:
            return self.basis
        if not self.remaining:
            return ("税理士が「JDLでは非仕入（税区空欄）として扱う」と判断し、その承認を記録した場合、"
                    "現在の保存設定ではこの仕訳に他のBLOCKは残りません（試算。承認前は変換しません）。")
        names = " / ".join(dict.fromkeys(rule_for_code(c).title for c in self.remaining))
        return "税理士の判断・承認記録の後も残る条件: " + names + "（試算）"


TRIAL_BASIS = "保存済み設定に、税理士の承認記録があると仮定した試算（保存しません）。"
TRIAL_UNAVAILABLE = ("この会社・JDL設定は、控除不可の技術Evidence（実機確認）の適用範囲外です（確認済みは会社Aの16行設定のみ）。"
                     "税理士の判断だけでは変換できず、この設定での実機確認が別途必要です。")


# blockers that are never about the tax category, whatever the what-if shows
INDEPENDENT_OF_TAX = frozenset({
    "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", "HUMAN:VOUCHER_SPLIT_APPROVAL", "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION",
    "HUMAN:ACCOUNT_MAPPING", "HUMAN:SUBACCOUNT_MAPPING", "HUMAN:SUBACCOUNT_DEFAULT", "HUMAN:VOUCHER_ROW_LIMIT_SETTING",
    "SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED", "SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SUBACCOUNT_UNVERIFIED",
    "HUMAN:DEPARTMENT_POLICY", "HUMAN:OPTIONAL_FIELD_POLICY", "HUMAN:DESCRIPTION_REPLACEMENT",
})


def outlook_for(codes, trial_codes) -> TaxDecisionOutlook:
    codes = tuple(codes)
    direct = tuple(c for c in codes if c == "HUMAN:TAX_MAPPING")
    independent = tuple(c for c in codes if c in INDEPENDENT_OF_TAX)
    if trial_codes is None:
        return TaxDecisionOutlook(direct, (), independent, tuple(c for c in codes if c not in direct), False,
                                  TRIAL_UNAVAILABLE)
    trial = set(trial_codes)
    derived = tuple(c for c in codes if c not in direct and c not in independent and c not in trial)
    remaining = tuple(sorted(trial, key=lambda c: (breakdown._rank(c), c)))  # noqa: SLF001
    return TaxDecisionOutlook(direct, derived, independent, remaining, True, TRIAL_BASIS)


@dataclass(frozen=True)
class JournalResolution:
    journal_id: str
    short_id: str
    codes: tuple[str, ...]
    item_keys: tuple[str, ...]
    notes: tuple[str, ...]
    ready: bool = False
    tax_review: tuple = ()             # read-only source facts (tax_review_facts.TaxReviewLine); never a verdict
    other_tax: tuple = ()              # (Yayoi tax identity, line count) of the journal's OTHER lines
    outlook: "TaxDecisionOutlook | None" = None
    approvals: tuple = ()              # (identity, record) of saved sign-offs naming THIS journal; () = none


@dataclass(frozen=True)
class SettingAlternative:
    limit: int
    ready: int
    released: tuple[str, ...]          # short ids READY there but not under the saved setting
    lost: tuple[str, ...]
    still_blocked: int


@dataclass(frozen=True)
class ResolutionReport:
    total: int
    ready: int
    blocked: int
    saved_limit: int | None
    items: tuple[ResolutionItem, ...]
    journals: tuple[JournalResolution, ...]
    completed: tuple[str, ...]
    alternative: SettingAlternative | None = None
    split_policy_problems: tuple[str, ...] = ()

    def item(self, key: str) -> ResolutionItem | None:
        return next((i for i in self.items if i.key == key), None)

    def journal(self, short_id: str) -> JournalResolution | None:
        return next((j for j in self.journals if j.short_id == short_id), None)

    def awaiting_tax_decision(self, item: ResolutionItem) -> tuple[str, ...]:
        """Journals of `item` whose codes for it all vanish in the 控除不可 sign-off what-if (they could not be
        evaluated while the tax category is open). Display only: the item, its count and its codes stay as they are."""
        found = []
        for short in item.journals:
            journal = self.journal(short)
            outlook = journal.outlook if journal is not None else None
            own = set(journal.codes) & set(item.codes) if journal is not None else set()
            if outlook is not None and outlook.computed and own and own <= set(outlook.derived):
                found.append(short)
        return tuple(found)

    @property
    def next_step(self) -> str:
        actionable = [i for i in self.items if i.app_resolvable]
        if actionable:
            return f"まず「{actionable[0].title}」に対応してください。"
        if self.items:
            return "アプリ内で完結する対応はありません。残りは税理士の判断・追加の実機確認が必要です。"
        return "すべての仕訳が変換できます。"


def short_id(journal_id: str) -> str:
    return journal_id.rsplit(":", 1)[-1]


def _lines(entry):
    return list(getattr(entry, "lines", ()) or ())


def _facts(entry) -> tuple[bool, bool]:
    """(has a 控除不可 line, has a negative amount) from the SOURCE journal. Facts only; no judgement."""
    noncredit = negative = False
    for line in _lines(entry):
        info = line.tax_info
        if info is not None and is_noncredit_identity(info.category or ""):
            noncredit = True
        if line.amount < Decimal(0):
            negative = True
    return noncredit, negative


def has_noncredit(entry) -> bool:
    return entry is not None and _facts(entry)[0]


def _notes(codes, noncredit, negative) -> tuple[str, ...]:
    notes = []
    if noncredit:
        notes.append("元データは「控除不可」。入力内容の確認が必要です（誤りと確定ではありません）。非仕入にすると10%・軽減8%の区別がJDLに残りません。"
                     "税理士の判断待ちで、承認記録なしには変換しません。")
    if negative:
        notes.append("借方に負の金額があります。JDL CSVは「-」を数値として受け付けませんでした。正の金額への変換・借貸入替・税額変更はしません。")
    if "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION" in codes:
        notes.append("決算仕訳です（本決算で実機確認済みの形以外）。通常仕訳や本決算への置き換えはしません。承認では解除できません。")
    if "HUMAN:VOUCHER_SPLIT_APPROVAL" in codes:
        notes.append("分割後の各伝票の形は実機確認済みです。残るのは分割の承認だけです。")
    return tuple(notes)


def _key_of(code: str, noncredit: bool, negative: bool) -> str:
    if code == "HUMAN:TAX_MAPPING" and noncredit:
        return NONCREDIT_KEY
    if code == "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED":
        return NEGATIVE_KEY if negative else OVER_OTHER_KEY
    if code not in _CODE_RULES and code.startswith("SYSTEM_EVIDENCE:"):
        return EVIDENCE_KEY  # every technical Evidence gap is one item; the codes stay in full in `codes`
    if code not in _CODE_RULES and code.startswith("SYSTEM_IMPLEMENTATION:"):
        return IMPLEMENTATION_KEY
    return code


def _keys_for(codes, noncredit, negative) -> list[tuple[str, str]]:
    """(key, code) pairs in fix order. Negative lines are a fact in themselves: they get their item even when
    another code fires first (the journal then lists that item with no code of its own, all codes stay on the journal)."""
    pairs = [(_key_of(code, noncredit, negative), code)
             for code in sorted(set(codes), key=lambda c: (breakdown._rank(c), c))]  # noqa: SLF001
    if negative and codes and NEGATIVE_KEY not in {k for k, _ in pairs}:
        pairs.append((NEGATIVE_KEY, ""))
    return pairs


def _rule(key: str) -> Rule:
    if key == EVIDENCE_KEY:
        return _GENERIC_EVIDENCE
    if key == IMPLEMENTATION_KEY:
        return _GENERIC_IMPL
    return _EXTRA_RULES.get(key) or rule_for_code(key)


_DONE_CATEGORIES = (
    ("会社設定（JDL税設定・端数処理・行数）", {"SYSTEM_EVIDENCE:TAX_CONTEXT_UNVERIFIED", "HUMAN:JDL_TAX_ROUNDING_SETTING",
                                      "HUMAN:VOUCHER_ROW_LIMIT_SETTING", "SYSTEM_EVIDENCE:VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED"}),
    ("科目の対応", {"HUMAN:ACCOUNT_MAPPING"}),
    ("補助科目の対応", {"HUMAN:SUBACCOUNT_MAPPING", "HUMAN:SUBACCOUNT_DEFAULT"}),
    ("税区分の対応", {"HUMAN:TAX_MAPPING"}),
    ("JDLに入らない情報・摘要の確認", {"HUMAN:DEPARTMENT_POLICY", "HUMAN:OPTIONAL_FIELD_POLICY", "HUMAN:DESCRIPTION_REPLACEMENT"}),
    ("伝票分割", {"HUMAN:VOUCHER_SPLIT_APPROVAL", "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"}),
    ("決算仕訳", {"SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"}),
)


def build_report(journal_blockers: dict, entries: dict, *, saved_limit: int | None = None,
                 alternative: SettingAlternative | None = None, split_policy_problems: tuple[str, ...] = (),
                 tax_decision_trial: dict | None = None, noncredit_approvals: dict | None = None) -> ResolutionReport:
    """`journal_blockers`: journal id -> blocker codes (the formal assessment). `entries`: journal id -> source entry.

    `tax_decision_trial`: journal id -> blocker codes of the what-if with a recorded 控除不可 sign-off, for the
    控除不可 journals; a journal absent from it (or None) means the what-if was not available. Display only."""
    journals, by_key = [], {}
    for journal_id, found in journal_blockers.items():
        codes = tuple(sorted(set(found), key=lambda c: (breakdown._rank(c), c)))  # noqa: SLF001
        if not codes:
            continue
        noncredit, negative = _facts(entries.get(journal_id)) if entries.get(journal_id) is not None else (False, False)
        pairs = _keys_for(codes, noncredit, negative)
        keys = list(dict.fromkeys(k for k, _ in pairs))
        review = tax_review_facts.extract(entries[journal_id], journal_id) if noncredit and entries.get(journal_id) is not None else ()
        other = tax_review_facts.other_identities(entries[journal_id]) if review else ()
        outlook = outlook_for(codes, (tax_decision_trial or {}).get(journal_id)) if review else None
        approvals = tuple(sorted((noncredit_approvals or {}).get(journal_id, {}).items())) if review else ()
        journals.append(JournalResolution(journal_id, short_id(journal_id), codes, tuple(keys), _notes(codes, noncredit, negative),
                                          False, review, other, outlook, approvals))
        for key in keys:
            own = tuple(c for k, c in pairs if k == key and c) or codes
            by_key.setdefault(key, []).append((journal_id, own, len(keys)))
    order = {code: i for i, (code, _c, _a) in enumerate(breakdown.PRIORITY)}
    extra_order = {EVIDENCE_KEY: len(order) - 0.5, IMPLEMENTATION_KEY: len(order), NONCREDIT_KEY: order["HUMAN:TAX_MAPPING"] + 0.5, NEGATIVE_KEY: order["HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"] - 0.5,
                   OVER_OTHER_KEY: order["HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"]}
    items = []
    for key in sorted(by_key, key=lambda k: (extra_order.get(k, order.get(k, len(order))), k)):
        rule = _rule(key)
        members = by_key[key]
        codes = sorted({c for _j, cs, _n in members for c in cs})
        items.append(ResolutionItem(
            key, rule.title, rule.problem, rule.confirmed, rule.todo, rule.where, rule.action, rule.action_label,
            rule.tax_accountant, rule.technical_evidence, rule.jdl_work,
            tuple(sorted((short_id(j) for j, _c, _n in members), key=lambda s: (len(s), s))),
            sum(1 for _j, _c, n in members if n == 1), tuple(codes)))
    present = {c for j in journals for c in j.codes}
    completed = tuple(name + "：完了" for name, codes in _DONE_CATEGORIES if not (codes & present))
    total = len(journal_blockers)
    ready = sum(1 for found in journal_blockers.values() if not found)
    return ResolutionReport(total, ready, total - ready, saved_limit, tuple(items), tuple(journals), completed,
                            alternative, tuple(split_policy_problems))

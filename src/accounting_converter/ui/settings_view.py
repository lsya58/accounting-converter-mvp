"""設定ページの表示内容 (Phase 3C-1). Pure data: no Qt, no I/O, no decision of its own.

The facts come from `controller.company_settings_facts` (read-only: it loads the saved company setting, profile and
JDL context and writes nothing). This module only arranges them into the six sections the page shows, says for every
item whether it is 確認済み / 未確認 / JDLでの確認待ち / 対象外 / 読めない, what to do next and how a change would
affect which journals can be converted. Nothing here confirms, infers or defaults a setting:
- an unconfirmed value is shown as unconfirmed (never as a default value);
- "確認済み" is shown only when the saved company setting says it was confirmed;
- the effect of a change is a plain statement of the existing rules, not a computed READY/BLOCK count (the count is
  the diagnosis's job; the page offers a button to see it).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Source kinds (what the company setting expects as its input).
MONEYFORWARD, YAYOI, JDL, UNSUPPORTED = "MONEYFORWARD", "YAYOI", "JDL", "UNSUPPORTED"
SOURCE_NAMES = {MONEYFORWARD: "Money Forward", YAYOI: "弥生会計", JDL: "JDL（JDL→JDL移行）", UNSUPPORTED: "未対応の形式"}

# Item states.
CONFIRMED, UNCONFIRMED, WAITING_EVIDENCE, NOT_APPLICABLE, UNREADABLE = (
    "CONFIRMED", "UNCONFIRMED", "WAITING_EVIDENCE", "NOT_APPLICABLE", "UNREADABLE")

# Actions: the page maps each key to an existing screen. None of them saves by itself.
ACT_ADD_COMPANY, ACT_RENAME_COMPANY, ACT_DELETE_COMPANY = "ADD_COMPANY", "RENAME_COMPANY", "DELETE_COMPANY"
ACT_REFRESH_MASTER, ACT_TAX_CONTEXT, ACT_ROW_LIMIT = "REFRESH_MASTER", "TAX_CONTEXT", "ROW_LIMIT"
ACT_TRADE_PARTNER, ACT_MAPPING, ACT_TAX_MAPPING = "TRADE_PARTNER", "MAPPING_REVIEW", "TAX_MAPPING"
ACT_JDL_MIGRATION, ACT_DIAGNOSIS, ACT_INFORMATION = "JDL_MIGRATION", "DIAGNOSIS", "INFORMATION_POLICY"

TAX_MODE = {"TAXABLE_TAX_EXCLUDED": "課税（税抜経理）", "TAXABLE_TAX_INCLUDED": "課税（税込経理）", "EXEMPT": "免税"}
TAXATION = {"STANDARD": "原則課税", "SIMPLIFIED": "簡易課税"}
CREDIT = {"INDIVIDUAL": "個別対応方式", "PROPORTIONAL": "一括比例配分方式"}
ROUNDING = {"FLOOR": "切捨て", "HALF_UP": "四捨五入", "CEILING": "切上げ"}
SIMPLIFIED = {"FIRST": "第一種事業", "SECOND": "第二種事業", "THIRD": "第三種事業", "FOURTH": "第四種事業",
              "FIFTH": "第五種事業", "SIXTH": "第六種事業"}


@dataclass(frozen=True)
class SettingsFacts:
    """What the saved company setting says. Every value is None / empty when it is not confirmed or not readable."""
    company_id: str
    display_name: str
    source_kind: str = UNSUPPORTED
    status: str = ""                       # CompanySettingStatus value
    status_message: str = ""
    reason_codes: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    context_loaded: bool = False           # a confirmed JDL context exists (not only the PDF draft)
    context_draft: bool = False            # only the JDL account PDF was read; the tax settings are not confirmed
    product: str = ""
    version: str = ""
    context_confirmed: bool = False
    provenance: str = ""
    master_state: str = ""
    master_updated_at: str = ""
    accounts: int | None = None
    subaccounts: int | None = None
    departments: int | None = None
    unusable_subaccounts: int | None = None
    department_processing: bool | None = None
    tax_mode: str = ""
    taxation_method: str = ""
    credit_method: str = ""
    simplified_category: str = ""
    sales_rounding: str = ""
    purchase_rounding: str = ""
    voucher_row_limit: int | None = None
    verified_row_limits: tuple[int, ...] = ()
    account_mappings: tuple[int, int] | None = None        # (resolved, total)
    subaccount_mappings: tuple[int, int] | None = None
    tax_mappings: tuple[int, int] | None = None
    pending_field_types: tuple[str, ...] = ()
    trade_partner_confirmed: bool | None = None            # Money Forward only
    information_fields_confirmed: int | None = None        # Yayoi: audit-only policies already confirmed
    profile_id: str = ""
    profile_updated_at: str = ""
    profile_fingerprint: str = ""
    context_fingerprint: str = ""
    target_format_key: str = ""
    source_format_key: str = ""
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingRow:
    key: str
    label: str
    value: str
    state: str
    note: str = ""                         # one line: what it means / what is missing
    action: str | None = None
    action_label: str = ""
    impact: str = ""                       # how a change (or the missing confirmation) affects READY / BLOCK
    technical: bool = False                # shown only inside the collapsed technical section
    state_text: str = ""                   # replaces the badge words (the state itself decides colour and symbol)


@dataclass(frozen=True)
class SettingSection:
    key: str
    title: str
    summary: str
    rows: tuple[SettingRow, ...]
    state: str                             # the worst state of its rows (UNREADABLE > UNCONFIRMED > WAITING > CONFIRMED)

    def counts(self) -> tuple[int, int]:
        """(confirmed, items that need a confirmation) — 対象外 and technical rows are not counted."""
        needed = [r for r in self.rows if r.state != NOT_APPLICABLE and not r.technical]
        return sum(r.state == CONFIRMED for r in needed), len(needed)


@dataclass(frozen=True)
class SettingsNext:
    text: str
    action: str
    button: str


@dataclass(frozen=True)
class SettingsOverview:
    company_name: str
    sections: tuple[SettingSection, ...]
    next_steps: tuple[SettingsNext, ...]
    message: tuple[str, str] | None = None       # (level, text) for the message bar
    confirmed: int = 0
    needed: int = 0
    has_company: bool = False


_ORDER = {UNREADABLE: 0, UNCONFIRMED: 1, WAITING_EVIDENCE: 2, CONFIRMED: 3, NOT_APPLICABLE: 4}


def _worst(rows) -> str:
    relevant = [r.state for r in rows if not r.technical]
    return min(relevant, key=lambda s: _ORDER[s]) if relevant else NOT_APPLICABLE


def _ratio(pair) -> str:
    """Saved mappings only: what a source still needs appears when a source file is reviewed (対応の確認)."""
    if pair is None:
        return "—"
    if pair[1] == 0:
        return "保存済みの対応はありません"
    return f"保存済み {pair[1]:,}件のうち確認済み {pair[0]:,}件"


def _ratio_state(pair) -> str:
    if pair is None:
        return UNREADABLE
    if pair[1] == 0:
        return NOT_APPLICABLE
    return CONFIRMED if pair[0] >= pair[1] else UNCONFIRMED


def _ratio_text(pair) -> str:
    return "未登録" if pair is not None and pair[1] == 0 else ""


def build_settings_overview(facts: SettingsFacts | None) -> SettingsOverview:
    if facts is None:
        return SettingsOverview(
            "未選択", (), (SettingsNext("会社設定を選ぶか、会社を追加してください。", ACT_ADD_COMPANY, "会社を追加…"),),
            ("info", "会社が選ばれていません。画面上部の「会社」から選ぶか、会社を追加してください。"), 0, 0, False)
    sections = (
        _company(facts), _software(facts), _accounts(facts), _tax(facts), _conditions(facts), _technical(facts))
    steps: list[SettingsNext] = []
    for section in sections:
        for row in section.rows:
            if row.technical or row.action is None or row.state in (CONFIRMED, NOT_APPLICABLE):
                continue
            if row.state in (UNCONFIRMED, UNREADABLE):
                steps.append(SettingsNext(f"{row.label}: {row.note or '確認が必要です'}", row.action,
                                          row.action_label))
    seen, unique = set(), []
    for step in steps:                       # one button per action: the same screen is never offered twice
        if step.action not in seen:
            seen.add(step.action)
            unique.append(step)
    confirmed = sum(s.counts()[0] for s in sections)
    needed = sum(s.counts()[1] for s in sections)
    errors = facts.errors
    if errors:
        message = ("error", "設定を読み込めない項目があります（" + "／".join(errors) + "）。設定は変更していません。"
                   "会社設定を確認するか、診断情報をコピーして連絡してください。")
    elif not unique and any(r.state == WAITING_EVIDENCE for sec in sections for r in sec.rows):
        message = ("warning", "実機での確認待ちの設定があります。確認が済むまで、関係する仕訳は変換できません（BLOCK）。"
                              "人が確認しても解決しないため、設定の値と、下の説明を確認してください。")
    elif not unique:
        message = ("success", "必要な設定はすべて確認済みです。変換への影響は「変換診断」で確認できます。")
    else:
        message = ("warning", f"未確認の設定が{len(unique)}項目あります。確認が済むまで、関係する仕訳は変換できません（BLOCK）。")
    return SettingsOverview(facts.display_name or "（名称なし）", sections, tuple(unique[:6]), message,
                            confirmed, needed, True)


# ------------------------------------------------------------------ 1. 会社の基本情報
def _company(f: SettingsFacts) -> SettingSection:
    usable = f.status == "AVAILABLE"
    rows = (
        SettingRow("name", "会社名", f.display_name or "—", CONFIRMED if f.display_name else UNCONFIRMED,
                   action=ACT_RENAME_COMPANY, action_label="名前を変更…",
                   impact="名前を変えても設定・READY/BLOCKは変わりません。"),
        SettingRow("usable", "会社設定の利用状態", "利用できます" if usable else (f.status_message or "確認が必要です"),
                   CONFIRMED if usable else (UNREADABLE if f.status in ("MALFORMED", "INCOMPATIBLE") else UNCONFIRMED),
                   note="" if usable else (f.status_message or "下の未確認の項目を確認してください。"),
                   impact="利用できない間は、この会社の仕訳は変換できません（BLOCK）。"),
        SettingRow("add", "会社の追加", "新しい会社を追加します", NOT_APPLICABLE, action=ACT_ADD_COMPANY,
                   action_label="会社を追加…",
                   impact="追加しても、他の会社の設定・READY/BLOCKは変わりません。"),
        SettingRow("delete", "会社の削除", "この会社設定を削除します（対応設定と元のJDL設定は削除されません）",
                   NOT_APPLICABLE, action=ACT_DELETE_COMPANY, action_label="削除…",
                   impact="削除するとこの会社は選べなくなります。確認ダイアログで確定します。"),
    )
    summary = f"{f.display_name or '（名称なし）'} ／ " + ("利用できます" if usable else "確認が必要です")
    return SettingSection("company", "会社の基本情報", summary, rows, _worst(rows))


# ------------------------------------------------------------------ 2. 会計ソフト・変換先
def _software(f: SettingsFacts) -> SettingSection:
    name = SOURCE_NAMES.get(f.source_kind, SOURCE_NAMES[UNSUPPORTED])
    if f.context_loaded:
        target = f"{f.product} {f.version}".strip()
        target_state, target_note = CONFIRMED, ""
    elif f.context_draft:
        target, target_state = "JDL IBEX 出納帳 35.5（科目一覧のみ読込）", UNCONFIRMED
        target_note = "JDL税設定がまだ確認されていません。"
    else:
        target, target_state, target_note = "確認が必要です", UNREADABLE, "JDLの設定を読み込めません。"
    rows = (
        SettingRow("source", "入力元の会計ソフト", name,
                   CONFIRMED if f.source_kind != UNSUPPORTED else UNREADABLE,
                   note="" if f.source_kind != UNSUPPORTED else "この会社設定の入力元は、現在変換に対応していません。",
                   impact="入力元は会社設定で固定です。別のソフトのデータには、そのソフト用の会社設定を使います。"),
        SettingRow("target", "変換先のJDL製品・バージョン", target, target_state, note=target_note,
                   action=ACT_TAX_CONTEXT if target_state == UNCONFIRMED else None,
                   action_label="JDL税設定を確認…",
                   impact="変換先の製品・バージョンは JDL IBEX 出納帳 35.5 のみ実機で確認済みです。"
                          "他の製品・バージョンは変換できません。"),
        SettingRow("context", "JDL設定の確認状態",
                   "確認済み" if f.context_confirmed else "未確認", CONFIRMED if f.context_confirmed else UNCONFIRMED,
                   note="" if f.context_confirmed else "JDL税設定の確認が済むまで、仕訳の構造と税の判定ができません。",
                   action=None if f.context_confirmed else ACT_TAX_CONTEXT, action_label="JDL税設定を確認…",
                   impact="未確認の間は全仕訳が変換できません（BLOCK）。確認すると診断をやり直せます。"),
    )
    return SettingSection("software", "会計ソフト・変換先", f"{name} → {target}", rows, _worst(rows))


# ------------------------------------------------------------------ 3. 科目・補助科目
def _accounts(f: SettingsFacts) -> SettingSection:
    master_ok = bool(f.master_state) and "必要" not in f.master_state and f.master_state != "未設定"
    master_row = SettingRow(
        "master", "JDL科目一覧", (f.master_state or "未設定") + (f"（最終更新日: {f.master_updated_at}）"
                                                          if f.master_updated_at else ""),
        CONFIRMED if master_ok else UNCONFIRMED,
        note="" if master_ok else "JDL科目一覧（PDF）の登録・更新が必要です。",
        action=ACT_REFRESH_MASTER, action_label="JDL科目一覧を更新…",
        impact="科目一覧を更新すると、変わった科目・補助の対応は再確認になります。確認が済むまでその仕訳はBLOCKです。"
               "更新前に変更内容を確認する画面が開き、保存は確認後だけです。")
    counts = SettingRow(
        "master_counts", "登録されている科目・補助・部門",
        "—" if f.accounts is None else
        f"科目 {f.accounts:,} / 補助 {f.subaccounts or 0:,} / 部門 {f.departments or 0:,}"
        + (f"（選択できない補助 {f.unusable_subaccounts:,}）" if f.unusable_subaccounts else ""),
        NOT_APPLICABLE, state_text="" if f.accounts is not None else "未読込")
    account_row = SettingRow(
        "accounts", "勘定科目の対応", _ratio(f.account_mappings), _ratio_state(f.account_mappings),
        state_text=_ratio_text(f.account_mappings), note="" if f.account_mappings is None or f.account_mappings[0] >= f.account_mappings[1]
        else "未確認の科目があります。", action=ACT_MAPPING, action_label="対応の確認へ",
        impact="確認すると、その科目を使う仕訳が変換できる状態に近づきます（READYが増えることがあります）。")
    sub_row = SettingRow(
        "subaccounts", "補助科目の対応", _ratio(f.subaccount_mappings),
        _ratio_state(f.subaccount_mappings), state_text=_ratio_text(f.subaccount_mappings),
        note="" if f.subaccount_mappings is None or f.subaccount_mappings[0] >= f.subaccount_mappings[1]
        else "未確認の補助科目があります。", action=ACT_MAPPING, action_label="対応の確認へ",
        impact="親科目のみで変換する場合は、補助の情報がJDLに入らないことを確認する必要があります。")
    rows = (master_row, counts, account_row, sub_row)
    summary = (f"JDL科目一覧: {f.master_state or '未設定'} ／ 勘定科目の対応: {_ratio(f.account_mappings)}"
               f" ／ 補助科目の対応: {_ratio(f.subaccount_mappings)}")
    return SettingSection("accounts", "科目・補助科目", summary, rows, _worst(rows))


# ------------------------------------------------------------------ 4. 消費税設定
def _tax(f: SettingsFacts) -> SettingSection:
    if not f.context_loaded:
        pending = SettingRow("tax_context", "JDL税設定", "未確認" if f.context_draft else "読み込めません",
                             UNCONFIRMED if f.context_draft else UNREADABLE,
                             note="税処理・課税方式・控除方式・端数処理をJDLの会社設定から転記して確認します。",
                             action=ACT_TAX_CONTEXT, action_label="JDL税設定を確認・変更…",
                             impact="確認が済むまで、税の判定ができず全仕訳が変換できません（BLOCK）。")
        tax_map = SettingRow("tax_mapping", "税区分の対応", _ratio(f.tax_mappings),
                             UNCONFIRMED if f.tax_mappings else UNREADABLE,
                             note="税設定の確認後に、税区分の対応を確認します。")
        rows = (pending, tax_map)
        return SettingSection("tax", "消費税設定", "JDL税設定が未確認です", rows, _worst(rows))
    mode = TAX_MODE.get(f.tax_mode, "未確認")
    taxation = TAXATION.get(f.taxation_method, "未確認")
    credit = CREDIT.get(f.credit_method, "未確認")
    exempt = f.tax_mode == "EXEMPT"
    simplified = f.taxation_method == "SIMPLIFIED"
    rows = [
        SettingRow("tax_mode", "税処理", mode, CONFIRMED if f.tax_mode else UNCONFIRMED,
                   action=ACT_TAX_CONTEXT, action_label="JDL税設定を確認・変更…",
                   impact="税処理（税抜・税込）を変えると、確認済みの税区分の対応が無効になり、税の判定がやり直しになります。"),
        SettingRow("taxation", "課税方式", "対象外（免税）" if exempt else taxation,
                   NOT_APPLICABLE if exempt else (CONFIRMED if f.taxation_method in TAXATION else UNCONFIRMED),
                   action=ACT_TAX_CONTEXT, action_label="JDL税設定を確認・変更…",
                   impact="課税方式を変えると、使える税の書き方が変わり、READY/BLOCKが変わることがあります。"),
    ]
    if simplified:
        rows.append(SettingRow("simplified", "簡易課税の事業区分", SIMPLIFIED.get(f.simplified_category, "未確認"),
                               CONFIRMED if f.simplified_category in SIMPLIFIED else UNCONFIRMED))
    else:
        rows.append(SettingRow("credit", "控除方式", "対象外（免税）" if exempt else credit,
                               NOT_APPLICABLE if exempt else (CONFIRMED if f.credit_method in CREDIT else UNCONFIRMED),
                               action=ACT_TAX_CONTEXT, action_label="JDL税設定を確認・変更…",
                               impact="控除方式の違いは、実機で確認済みの範囲（一括比例配分）だけ変換できます。"))
    rows.append(SettingRow(
        "rounding", "端数処理（売上／仕入）",
        f"売上 {ROUNDING.get(f.sales_rounding, '未確認')} ／ 仕入 {ROUNDING.get(f.purchase_rounding, '未確認')}",
        CONFIRMED if f.sales_rounding in ROUNDING and f.purchase_rounding in ROUNDING else UNCONFIRMED,
        note="" if f.sales_rounding in ROUNDING and f.purchase_rounding in ROUNDING
        else "JDLの会社設定から転記して確認してください。",
        action=ACT_TAX_CONTEXT, action_label="JDL税設定を確認・変更…",
        impact="端数処理が未確認だと、明示した税額のある仕訳はBLOCKです。変えると税額の判定がやり直しになります。"))
    rows.append(SettingRow("tax_mapping", "税区分の対応", _ratio(f.tax_mappings), _ratio_state(f.tax_mappings),
                           state_text=_ratio_text(f.tax_mappings),
                           note="" if f.tax_mappings is None or f.tax_mappings[0] >= f.tax_mappings[1]
                           else "未確認の税区分があります。税区分は推測せず、確認した対応だけを使います。",
                           action=ACT_TAX_MAPPING, action_label="税区分を確認…",
                           impact="確認した税区分を使う仕訳だけ、変換できる状態に近づきます。"))
    rows = tuple(rows)
    summary = f"{mode}" + ("" if exempt else f" / {taxation}")
    return SettingSection("tax", "消費税設定", summary, rows, _worst(rows))


# ------------------------------------------------------------------ 5. 変換条件
def _conditions(f: SettingsFacts) -> SettingSection:
    limit = f.voucher_row_limit
    verified = f.verified_row_limits
    if not f.context_loaded:
        limit_value, limit_state = "未確認（JDL税設定の確認後に設定）", UNCONFIRMED
        limit_note = "JDLの会社設定「振替伝票入力行数」（16行／64行）を確認して入力します。"
    elif limit is None:
        limit_value, limit_state = "未確認", UNCONFIRMED
        limit_note = "JDLの会社設定で確認した行数（16行／64行）を入力してください。推測しません。"
    elif limit in verified:
        limit_value, limit_state, limit_note = f"{limit}行（実機で確認済み）", CONFIRMED, ""
    else:
        limit_value, limit_state = f"{limit}行（実機未確認）", WAITING_EVIDENCE
        limit_note = (f"{limit}行設定での実機確認が済むまで、この会社の全仕訳が変換できません（BLOCK）。"
                      "16行設定なら変換できます。")
    rows = [SettingRow(
        "row_limit", "振替伝票入力行数", limit_value, limit_state, note=limit_note, action=ACT_ROW_LIMIT,
        action_label="振替伝票入力行数を確認…",
        impact="行数を変えると、1伝票の行数の上限が変わり、BLOCKの仕訳が増減します。"
               "16行を超える仕訳は自動分割せず、税理士の判断が必要です。")]
    if f.source_kind == MONEYFORWARD:
        ok = bool(f.trade_partner_confirmed)
        rows.append(SettingRow(
            "trade_partner", "取引先情報の扱い", "確認済み（摘要へ追記）" if ok else "未確認",
            CONFIRMED if ok else UNCONFIRMED,
            note="" if ok else "JDLには取引先欄がありません。摘要へ追記する方針を確認してください。",
            action=ACT_TRADE_PARTNER, action_label="取引先情報の扱い…",
            impact="未確認の間、取引先のある仕訳は変換できません（BLOCK）。"))
    elif f.source_kind == YAYOI:
        count = f.information_fields_confirmed
        rows.append(SettingRow(
            "information", "JDLに保持されない情報（部門・付箋など）",
            "—" if count is None else f"確認済み {count:,} 項目",
            UNREADABLE if count is None else (CONFIRMED if count else NOT_APPLICABLE),
            note="項目ごとの確認は「対応の確認」の保持方法で行います。", action=ACT_MAPPING,
            action_label="対応の確認へ",
            impact="確認した項目は、JDLへは出さず監査記録に残します。未確認の項目がある仕訳はBLOCKです。"))
    elif f.source_kind == JDL:
        rows.append(SettingRow(
            "jdl_migration", "JDL移行内容の確認", "仕訳データを選んで確認します", NOT_APPLICABLE,
            action=ACT_JDL_MIGRATION, action_label="JDL移行内容を確認…",
            impact="JDL→JDL移行の対応は、移行元のJDL仕訳データを選んだ状態で確認します。"))
    if f.department_processing is not None:
        rows.append(SettingRow(
            "department", "部門処理", "使う" if f.department_processing else "使わない",
            CONFIRMED, impact="JDL側の設定です。部門を使わない会社では、元データの部門はJDLへ出力されません。"))
    rows = tuple(rows)
    return SettingSection("conditions", "変換条件", f"振替伝票入力行数: {limit_value}", rows, _worst(rows))


# ------------------------------------------------------------------ 6. 技術情報・設定履歴
def _technical(f: SettingsFacts) -> SettingSection:
    def row(key, label, value):
        return SettingRow(key, label, value or "—", NOT_APPLICABLE, technical=True)

    rows = (
        row("company_id", "会社ID", f.company_id),
        row("profile_id", "対応設定ID（改訂の履歴が末尾に付きます）", f.profile_id),
        row("profile_updated", "対応設定の最終更新", f.profile_updated_at),
        row("company_created", "会社設定の作成", f.created_at),
        row("company_updated", "会社設定の最終更新", f.updated_at),
        row("profile_fp", "対応設定の指紋", f.profile_fingerprint),
        row("context_fp", "JDL設定の指紋", f.context_fingerprint),
        row("provenance", "JDL設定の出所", f.provenance),
        row("source_key", "入力形式の識別", f.source_format_key),
        row("target_key", "変換先形式の識別", f.target_format_key),
        row("reason_codes", "状態コード", "、".join(f.reason_codes)),
    )
    return SettingSection("technical", "技術情報・設定履歴", "会社ID・改訂履歴・指紋（監査・問い合わせ用）", rows, NOT_APPLICABLE)


SAVED_CHANGE_NOTICE = (
    "設定を保存しました。変換できる仕訳の数がどう変わったかは「変換診断」で確認できます"
    "（この画面は診断を自動では実行しません）。")

"""Plain-language description of the approval items and of a preview, for the tax accountant (read-only).

Nothing here decides anything or records anything. Every sentence is built from facts the app already has:
the parsed journal, the existing split brief (voucher_split_brief), the 控除不可 technical Evidence and its stated
loss (noncredit_approval), the business rules' titles (resolution_report) and the wording of the company A
confirmation plan. A new accounting or tax judgment is never made here: where the app cannot judge, the text says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from accounting_converter.application import approval_ledger as al
from accounting_converter.application import noncredit_approval as nc
from accounting_converter.application import voucher_split as vs
from accounting_converter.application.resolution_report import rule_for_code, short_id
from accounting_converter.application.voucher_split_brief import brief
from accounting_converter.domain.journal_identity import stable_journal_identity

TECHNICAL_CODE_PREFIX = ("SYSTEM_EVIDENCE:", "SYSTEM_IMPLEMENTATION:")


def yen(value) -> str:
    return f"{Decimal(value):,}円"


@dataclass(frozen=True)
class Explanation:
    item_id: str
    title: str
    what: tuple[str, ...]            # 1. what transaction / journal
    yayoi: tuple[str, ...]           # 2. how Yayoi has it
    jdl: tuple[str, ...]             # 3. what the app proposes for JDL
    lost: tuple[str, ...]            # 4. what is lost or changed
    question: str                    # 5. the question for the tax accountant
    alternatives: tuple[str, ...]    # 8. if it cannot be approved
    needs: tuple[str, ...]           # 9. additional confirmation needed before it can be applied
    related: tuple[str, ...] = ()    # other items about the same journals
    technical: tuple[tuple[str, str], ...] = ()   # kept: company ID, Evidence IDs, fingerprints ...
    record_only: bool = False


@dataclass(frozen=True)
class Guide:
    """A decision that is managed on another formal route and has no inputs loaded in this screen."""
    guide_id: str
    title: str
    lines: tuple[str, ...]


def _label(entry) -> str:
    return short_id(entry.id)


def _head(entry) -> str:
    voucher = entry.metadata.get("yayoi_voucher_number") or ""
    return f"伝票{voucher}（{entry.date.isoformat()}）"


def _technical(item) -> tuple[tuple[str, str], ...]:
    rows = [("会社ID", item.company_id), ("対象期間", "〜".join(item.period or ()) or "—"),
            ("JDLバージョン", item.jdl_version or "—"), ("振替伝票入力行数", str(item.voucher_row_limit or "未確認")),
            ("根拠Evidence ID", " / ".join(item.evidence_ids) or "—"), ("項目の指紋", item.fingerprint),
            ("既定の適用範囲", item.default_scope.get("text", ""))]
    if item.identity:
        rows.append(("元の税区分（弥生）", item.identity))
    rows.extend(("対象仕訳の内容ID", f"{t.label}: {t.journal_sha256}") for t in item.targets)
    rows.extend(("確認資料（SHA-256付き）", ref) for ref in item.references)
    return tuple(rows)


def _related(item, items) -> tuple[str, ...]:
    mine = {t.journal_sha256 for t in item.targets if t.journal_sha256}
    out = []
    for other in items:
        if other.item_id == item.item_id:
            continue
        shared = [t.label for t in other.targets if t.journal_sha256 in mine]
        if shared:
            out.append(f"{other.item_id}（仕訳{'・'.join(shared)}）")
    return tuple(out)


def _required_with(item, items) -> tuple[str, ...]:
    """Other items about the same journals that ALSO have to be approved before the journal can be written
    (record-only items such as an operating policy are not among them)."""
    mine = {t.journal_sha256 for t in item.targets if t.journal_sha256}
    out = []
    for other in items:
        if other.item_id != item.item_id and other.applies_to_conversion:
            shared = [t.label for t in other.targets if t.journal_sha256 in mine]
            if shared:
                out.append(f"{other.item_id}（仕訳{'・'.join(shared)}）")
    return tuple(out)


def _split_explanation(item, items, by_sha, limit) -> Explanation:
    rows, notes = [], []
    for target in item.targets:
        entry = by_sha.get(target.journal_sha256)
        if entry is None or limit is None:
            continue
        info = brief(entry, limit)
        if not info.get("split"):
            continue
        parts = info["parts"]
        rows.append(f"{_head(entry)}: 元は1伝票・{info['original']['physical_rows']}行 → {len(parts)}伝票に分割"
                    f"（相手科目 {parts[0]['counterpart_account']} の合計 {yen(info['original']['credit'])}"
                    f"／借方 {yen(info['original']['debit'])}）")
    sample = next((brief(by_sha[t.journal_sha256], limit) for t in item.targets
                   if t.journal_sha256 in by_sha and limit is not None), None)
    changes = tuple(sample["changes"]) if sample and sample.get("split") else ()
    unchanged = tuple(sample["unchanged"]) if sample and sample.get("split") else ()
    lost = (sample["lost"],) if sample and sample.get("split") else ()
    related = _related(item, items)
    required = _required_with(item, items)
    if required:
        notes.append("次の仕訳は、分割のほかに別の承認も必要です: " + "、".join(required))
    return Explanation(
        item_id=item.item_id,
        title=f"伝票分割（規則V1）— 振替伝票入力行数{limit}行を超える{len(item.targets)}仕訳",
        what=tuple(rows) or ("対象の仕訳を読み取れませんでした",),
        yayoi=(f"弥生では1つの仕訳（伝票）です。JDLの会社設定「振替伝票入力行数」が{limit}行のため、17行以上は"
               "JDLのCSV取込で拒否されます（実機で確認済み）。",),
        jdl=("次の規則で複数のJDL伝票に分けます。",
             "明細は元の順序のまま、できるだけ均等に、1伝票15明細以内に分ける。", *changes,
             "保持するもの: " + "、".join(unchanged) if unchanged else "科目・補助・税区分・税額・摘要・日付は変えない。",
             "ダミー科目は使わない。税額の配分もしない。"),
        lost=lost or ("元の1伝票としての一体性",),
        question=("16行を超える仕訳を、上の規則で複数の伝票に分けてJDLに入れてよいか（規則全体に対する承認です。"
                  "承認の範囲は、既定では表示中の仕訳のみで、今後の仕訳には及びません）。"),
        alternatives=("承認しない場合: この仕訳は未移行のままです。JDLで手入力するか、弥生側で伝票を分けて再出力します"
                      "（アプリは自動で分割しません）。",),
        needs=("承認の適用範囲の選択（既定: 表示中の仕訳のみ）", "振替伝票入力行数は現在の設定（行数を変えると承認は無効）",
               *notes),
        related=related, technical=_technical(item))


def _noncredit_lines(entry, identity):
    return [line for line in entry.lines if line.tax_info is not None and line.tax_info.category == identity]


def _noncredit_explanation(item, items, by_sha, context, company_id, policies) -> Explanation:
    target = item.targets[0] if item.targets else None
    entry = by_sha.get(target.journal_sha256) if target else None
    source = nc.NONCREDIT_SOURCES.get(item.identity or "")
    what, yayoi, jdl = [], [], []
    if entry is not None and source is not None:
        lines = _noncredit_lines(entry, item.identity)
        others = len(entry.lines) - len(lines)
        for line in lines:
            what.append(f"{_head(entry)}: {line.account} {yen(line.amount)}"
                        + (f"（摘要: {line.metadata.get('journal_row_description')}）"
                           if line.metadata.get("journal_row_description") else ""))
            yayoi.append(f"税区分「{source.tax_category}」・{source.invoice_class}・{source.purchase_credit}"
                         f"（税率 {source.rate}）、内税、税額 0円、金額（税込）{yen(line.amount)}")
            jdl.append(f"課区「{nc.JDL_SCOPE}」（コード{nc.JDL_SCOPE_CODE}）・税区／入力／税額は空欄、金額 {yen(line.amount)}"
                       "（税込額のまま）")
        if others:
            what.append(f"同じ仕訳には、ほかに{others}明細があります（この承認の対象ではありません）。")
    technical = nc.technical_problems(item.identity or "", company_id, context)
    needs = ["税理士の確認: 消費税集計表（原則課税）の読み取りに対する「済」（判定ファイル EQUIVALENCE_CONFIRMED）",
             "仕訳ごとの承認の記録（承認者・確認資料・日付）",
             "「税率・区分記載・控除不可の区別がJDLのCSVに残らない」ことの了承"]
    if technical:
        needs.append("この会社・JDL設定は技術確認の範囲外です（" + ", ".join(technical) + "）。承認しても変換できません。")
    related = _related(item, items)
    required = _required_with(item, items)
    if required:
        needs.append("同じ仕訳の別の承認も必要です: " + "、".join(required))
    policy = [p for p in policies if entry is not None and p.targets and target is not None
              and p.targets[0].journal_sha256 == target.journal_sha256]
    for p in policy:
        lines = ", ".join(map(str, p.targets[0].lines))
        needs.append(f"運用方針 {p.item_id} との違い: 方針は事務所の考え方の記録だけで、変換には使われません。この仕訳をREADYにできるのは、"
                     f"この個別承認だけです。方針の対象は指定した明細（行{lines}）だけで、同じ仕訳の他の明細・他の仕訳には自動で当てはめません。")
    return Explanation(
        item_id=item.item_id,
        title=f"控除不可 → 非仕入: {_head(entry) if entry is not None else item.item_id}",
        what=tuple(what) or ("対象の仕訳を読み取れませんでした",),
        yayoi=tuple(yayoi), jdl=(*jdl, "消費税集計表では「課税仕入」「課税仕入税額等合計」に入らず、非課税仕入として集計される"
                                 "（JDL実機で確認済み）。"),
        lost=(nc.LOSS_TEXT, "今回検証済みのJDL CSV取込方式では、元の「控除不可」の区別をそのまま保持できません"
                            "（実機で、「課税仕入に税額0」と書くとJDLが税額を計算し直し、通常の課税仕入になることを確認）。"
                            "別の入力方法については未確認です。"),
        question=("この明細をJDLの「非仕入（非課税仕入）」として取り込んでよいか。弥生の控除不可と申告上同じ扱いと言えるか"
                  "（アプリは判定しません）。10%／軽減8%・区分記載・控除不可の区別がJDLに残らないことを了承できるか。"),
        alternatives=("弥生で元の区分を正しいものに直して再出力する（「元の控除不可」はアプリには残りません）",
                      "国外取引等で別の区分にする（弥生側の修正）", "JDLで手入力する",
                      "承認しない場合: この仕訳は未移行のままです。"),
        needs=tuple(needs), related=related, technical=_technical(item))


def _policy_explanation(item, items) -> Explanation:
    target = item.targets[0] if item.targets else None
    return Explanation(
        item_id=item.item_id, title=f"運用方針（記録のみ）— {item.item_id}",
        what=((f"仕訳{target.label}（{target.date}・伝票{target.voucher}）の行{', '.join(map(str, target.lines))}",)
              if target else ()),
        yayoi=("対象の明細は、弥生の控除不可（税区分・税額は元データのとおり）です。",),
        jdl=("この方針は変換には使われません。仕訳をREADYにしたり、JDLの出力を変えたりしません。",),
        lost=("なし（記録のみ）",),
        question=item.change or "この運用方針を記録してよいか",
        alternatives=("記録しない（個別の仕訳の承認とは別に、運用方針としての記録が不要な場合）",),
        needs=("【個別承認との違い】個別承認（NONCREDIT-…）は、その仕訳の変換を可能にします。運用方針は事務所の考え方の記録で、"
               "変換に影響せず、指定した明細以外（同じ仕訳の他の明細・他の仕訳）には自動で当てはめません。",
               "方針が記録されても、控除不可の個別承認がなければ、その仕訳はBLOCKのままです。"),
        related=_related(item, items), technical=_technical(item), record_only=True)


def _trailing_explanation(item, items) -> Explanation:
    return Explanation(
        item_id=item.item_id, title="摘要末尾空白の許容判断",
        what=(item.change,),
        yayoi=("摘要の末尾に半角・全角の空白がある明細があります。",),
        jdl=("JDLは取込時に摘要末尾の空白を取り除きます（金額・科目・補助・税区分には影響しません）。",),
        lost=("摘要の末尾の空白文字だけ（実機Evidenceに登録済みの並びのみ）",),
        question="JDLが摘要の末尾の空白を取り除くことを許容してよいか（正式な往復照合の合格に、この判断の記録が必要です）。",
        alternatives=("許容しない場合: 往復照合は「許容判断待ち」のままです。摘要を置換するなど別の対応を検討します。",),
        needs=("この項目の記録は、既存のツール jdl_description_trailing_space_acceptance を担当者が実行して行います"
               "（往復照合の記録ファイルとSHA-256で紐づけ）。この画面・台帳からは記録できません。",),
        related=(), technical=_technical(item), record_only=True)


def explain_all(entries, items, profile, context, company_id: str) -> dict[str, Explanation]:
    """item_id -> Explanation, from the parsed source and the pending items. Read-only."""
    by_sha = {}
    for entry in entries:
        sha = stable_journal_identity(entry)
        by_sha.setdefault(sha, entry)
    limit = getattr(context, "voucher_row_limit", None)
    policies = [i for i in items if i.kind == al.KIND_POLICY]
    out = {}
    for item in items:
        if item.kind == al.KIND_SPLIT:
            out[item.item_id] = _split_explanation(item, items, by_sha, limit)
        elif item.kind == al.KIND_NONCREDIT:
            out[item.item_id] = _noncredit_explanation(item, items, by_sha, context, company_id, policies)
        elif item.kind == al.KIND_POLICY:
            out[item.item_id] = _policy_explanation(item, items)
        elif item.kind == al.KIND_TRAILING_SPACE:
            out[item.item_id] = _trailing_explanation(item, items)
    return out


def guides_for(items) -> tuple[Guide, ...]:
    """The two decisions managed on another route, when their inputs are not loaded (so they are never just missing)."""
    kinds = {item.kind for item in items}
    guides = []
    if al.KIND_TRAILING_SPACE not in kinds:
        guides.append(Guide("TRAILING-SPACE", "摘要末尾空白の許容判断（記録ファイル未選択）", (
            "この判断は、JDL往復照合の「摘要末尾空白の記録ファイル」に紐づけて行う、別の正式な承認経路です。",
            "画面上部の「摘要末尾空白の記録を選ぶ…」で記録ファイルを選ぶと、この項目が表示されます。",
            "確認資料: 04_摘要末尾空白_承認資料.md（587明細・545伝票の整理と代表例）／02_税理士確認事項.md 第7項。",
            "記録は既存のツール jdl_description_trailing_space_acceptance（担当者が実行）で行います。この画面では記録できず、"
            "承認条件も変わりません。")))
    if al.KIND_POLICY not in kinds:
        guides.append(Guide("POLICY", "運用方針（例: 海外購入）（定義ファイル未選択）", (
            "運用方針は、事務所の考え方を記録するだけの項目です（変換には使われず、指定した明細以外には当てはめません）。",
            "画面上部の「運用方針の定義を選ぶ…」で定義ファイルを選ぶと、この項目が表示されます。",
            "確認資料: 02_税理士確認事項.md 第2項（控除不可）・03_承認記録様式.csv（Q2-3558）。",
            "個別の控除不可の承認とは別の記録です。方針があっても、個別の承認がなければ仕訳はREADYになりません。")))
    return tuple(guides)


# ---------------------------------------------------------------- preview, in words
@dataclass(frozen=True)
class PreviewRow:
    label: str
    source_row: int
    voucher: str
    date: str
    reasons: tuple[str, ...]          # plain titles
    codes: tuple[str, ...]            # kept for details
    hints: tuple[str, ...]            # what else is needed


@dataclass(frozen=True)
class PreviewView:
    selected: tuple[str, ...]
    ready_before: int
    block_before: int
    ready_after: int
    block_after: int
    released: tuple[PreviewRow, ...]
    remaining: tuple[PreviewRow, ...]
    prerequisites: tuple[str, ...]
    notes: tuple[str, ...]
    problems: tuple[str, ...]
    expected_note: str = ""


def _hints(row_label: str, codes, items, selected) -> tuple[str, ...]:
    hints = []
    by_label = {}
    for item in items:
        for t in item.targets:
            by_label.setdefault(t.label, []).append(item)
    for item in by_label.get(row_label, ()):
        if item.item_id in selected:
            continue
        if item.kind == al.KIND_NONCREDIT and "HUMAN:TAX_MAPPING" in codes:
            hints.append(f"控除不可の承認（{item.item_id}）が未承認です")
        if item.kind == al.KIND_SPLIT and vs.APPROVAL_BLOCKER in codes:
            hints.append(f"伝票分割の承認（{item.item_id}）が未承認です")
    if any(code.startswith(TECHNICAL_CODE_PREFIX) for code in codes):
        hints.append("実機Evidenceや実装に関わる条件は、承認だけでは解消しません"
                     "（上の承認が済むと、再判定で消える場合があります）")
    return tuple(dict.fromkeys(hints))


def describe_preview(preview, items, context, company_id: str) -> PreviewView:
    by_id = {item.item_id: item for item in items}
    selected = set(preview.item_ids)
    known = {t.label: (t.voucher, t.date) for item in items for t in item.targets}
    released, remaining = [], []
    for change in preview.targets:
        codes = tuple(change.after)
        titles = tuple(dict.fromkeys(rule_for_code(code).title for code in codes))
        voucher, day = known.get(change.label, ("", ""))
        row = PreviewRow(change.label, change.source_row, voucher, day, titles, codes,
                         _hints(change.label, codes, items, selected))
        (remaining if change.after else released).append(row)
    prerequisites = []
    for item_id in preview.item_ids:
        item = by_id.get(item_id)
        if item is None or item.kind != al.KIND_NONCREDIT:
            continue
        prerequisites.append(f"{item_id}: 試算は「承認された」と仮定した結果です。実際に適用するには、税理士の確認（消費税集計の"
                             "判定ファイル EQUIVALENCE_CONFIRMED）と、仕訳ごとの承認の記録（承認者・確認資料・日付）、"
                             "区別がJDLに残らないことの了承が必要です。")
        technical = nc.technical_problems(item.identity or "", company_id, context)
        if technical:
            prerequisites.append(f"{item_id}: この会社・JDL設定は技術確認の範囲外です（{', '.join(technical)}）。"
                                 "承認しても変換できません。")
    notes = list(preview.record_only) + list(preview.setting_sensitivity)
    if any(row.hints for row in remaining) and len(selected) < len(items):
        notes.append("他の承認が必要な仕訳があります。関連する項目を同時に選択して試算すると、合わせた結果を確認できます。")
    expected = ""
    if selected == {"SPLIT-V1"} and "SPLIT-V1" in by_id and any(
            row.hints and any("控除不可" in h for h in row.hints) for row in remaining):
        expected = ("伝票分割のみを承認した場合の想定: 対象仕訳のうち、控除不可の未承認条件を持つ仕訳だけがBLOCKのまま残り、"
                    "ほかはREADYになります。")
    return PreviewView(tuple(preview.item_ids), preview.ready_before, preview.block_before, preview.ready_after,
                       preview.block_after, tuple(released), tuple(remaining), tuple(prerequisites), tuple(notes),
                       tuple(preview.problems), expected)

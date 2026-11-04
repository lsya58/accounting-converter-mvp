"""Grouped decisions for a Yayoi → JDL company: far fewer Human decisions, same safety.

The office sheet (yayoi_office_sheet) has one row per account, subaccount,
tax identity and description. This tool groups them into decision units and
rules, and EXPANDS the approved ones back into a filled office sheet. Nothing
is saved here: the expanded sheet goes through the existing full pre-check and
all-or-nothing apply (yayoi_office_sheet apply --check / apply).

write: 判断シート (decision units), 一括対象一覧 (every item of every bulk
       unit), 摘要ルール (description rules) — under data/private.
         - bulk units: every same-name candidate of a kind, approved by one OK.
           The unit carries a SHA-256 of its exact target list; if the list
           changes (other master, other data), expand refuses the unit.
         - individual units: ranked proposals with their basis; the Human picks.
         - description rules: tidy spaces, remove repeated words, remove the
           hyphens inside 4-4-4 digit groups (every digit kept), 株式会社→(株),
           and frequent phrases the Human abbreviates once. A rule never
           truncates and never drops digits.
expand: applies only approved units and rules, writes the filled office sheet
        and a before/after preview of every description, and runs the
        existing pre-check. Descriptions are filled only when --preview-sha
        matches the preview the Human looked at. Anything not approved stays
        blank (and so stays blocked).

Prints counts only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.application.description_replacement import replacement_is_valid
from accounting_converter.application.moneyforward_description_replacement import unsafe_description_positions
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.application.yayoi_sources import detect_format, format_for_identity_key
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write
from accounting_converter.tools.yayoi_office_sheet import (
    HEADER as OFFICE_HEADER,
    KIND_SAME,
    SheetCheckError,
    _store,
    build_rows,
    check_sheet,
)

LIMIT = 32
UNIT_HEADER = ("単位ID", "種類", "内容", "対象件数", "影響仕訳数（延べ）", "提案1", "提案2", "提案3", "根拠",
               "判断の選択肢", "【記入】判断", "【記入】コード", "対象一覧SHA")
RULE_HEADER = ("ルールID", "種類", "対象の語句", "影響する摘要数", "説明", "【記入】短縮後の語句", "【記入】承認")
COL = {name: index for index, name in enumerate(OFFICE_HEADER)}
_DIGIT_GROUP = re.compile(r"(?<!\d)(\d{4})-(\d{4})-(\d{4})(?!\d)")
LEGAL_FORMS = {"株式会社": "(株)", "有限会社": "(有)", "合同会社": "(同)"}


def _sha(items) -> str:
    return hashlib.sha256(json.dumps(sorted(items), ensure_ascii=False).encode("utf-8")).hexdigest()


def _norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _bigram_similarity(a: str, b: str) -> float:
    x = {_norm(a)[i:i + 2] for i in range(len(_norm(a)) - 1)} or {_norm(a)}
    y = {_norm(b)[i:i + 2] for i in range(len(_norm(b)) - 1)} or {_norm(b)}
    return len(x & y) / len(x | y)


# ---------------------------------------------------------------- descriptions

def tidy(text: str) -> str:
    text = "".join(" " if ord(c) < 0x20 or ord(c) == 0x7F else c for c in text)
    return re.sub(r"[ 　]+", " ", text).strip()


def remove_repeated_words(text: str) -> str:
    seen, kept = set(), []
    for token in text.split(" "):
        if len(token) >= 2 and token in seen:
            continue
        seen.add(token)
        kept.append(token)
    return " ".join(kept)


def apply_rules(original: str, rules: list[dict]) -> str:
    """Approved rules only, in sheet order. Phrase rules replace whole words."""
    text = original
    for rule in rules:
        kind = rule["種類"]
        if kind == "空白の整理":
            text = tidy(text)
        elif kind == "繰り返し語の削除":
            text = remove_repeated_words(text)
        elif kind == "番号のハイフン削除":
            text = _DIGIT_GROUP.sub(lambda m: "".join(m.groups()), text)
        elif kind == "法人格の略記":
            for long, short in LEGAL_FORMS.items():
                text = text.replace(long, short)
        elif kind == "語句の短縮":
            text = " ".join(rule["【記入】短縮後の語句"] if token == rule["対象の語句"] else token
                            for token in text.split(" "))
    return text


def description_fits(text: str) -> bool:
    return replacement_is_valid(text) and not unsafe_description_positions(text)


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def propose_rules(descriptions: list[str]) -> list[tuple]:
    """Built-in rules plus the frequent whole words worth abbreviating (greedy by gain)."""
    base = [tidy(d) for d in descriptions]
    rules = [
        ("R01", "空白の整理", "", sum(1 for d, t in zip(descriptions, base) if d != t),
         "改行・連続する空白を1つの空白に"),
        ("R02", "繰り返し語の削除", "", sum(1 for t in base if remove_repeated_words(t) != t),
         "同じ語が2回出るとき2回目を削除（数字・日付はすべて残す）"),
        ("R03", "番号のハイフン削除", "", sum(1 for t in base if _DIGIT_GROUP.search(t)),
         "4桁-4桁-4桁の番号のハイフンだけを削除（数字はすべて残す）"),
    ]
    if any(long in t for t in base for long in LEGAL_FORMS):
        rules.append(("R04", "法人格の略記", "", sum(1 for t in base if any(k in t for k in LEGAL_FORMS)),
                      "株式会社→(株)、有限会社→(有)、合同会社→(同)"))
    shortened = [_DIGIT_GROUP.sub(lambda m: "".join(m.groups()), remove_repeated_words(t)) for t in base]
    long = [t for t in shortened if len(t) > LIMIT]
    words = Counter(w for t in long for w in set(t.split(" ")) if len(w) >= 4 and not w.isdigit())
    chosen: list[str] = []

    def fit_count(selected):
        def halve(t):
            return " ".join(w[:max(2, (len(w) + 1) // 2)] if w in selected else w for w in t.split(" "))
        return sum(1 for t in long if len(halve(t)) <= LIMIT)

    current = fit_count(chosen)
    while True:
        gains = [(fit_count(chosen + [w]) - current, w) for w, n in words.items() if n >= 3 and w not in chosen]
        gain, word = max(gains, default=(0, None))
        if word is None or gain < 2:
            break
        chosen.append(word)
        current += gain
    for index, word in enumerate(chosen, len(rules) + 1):
        rules.append((f"R{index:02d}", "語句の短縮", word, words[word],
                      "この語をすべての摘要で同じ短い語に置き換える（短縮後の語句を記入）"))
    return rules


# ---------------------------------------------------------------- units

def _account_proposals(name, usage, exact_codes_by_usage, context):
    """Rank JDL accounts for a Yayoi account without a same-name candidate.

    Signals (basis shown to the Human): name similarity, and how the already
    same-name-matched accounts with similar tax usage are coded in JDL.
    """
    prefix_profile = exact_codes_by_usage.get(usage, Counter())
    scored = []
    for item in context.account_master:
        name_score = _bigram_similarity(name, item.mapping_value)
        contains = len(_norm(item.mapping_value)) >= 2 and (
            _norm(item.mapping_value) in _norm(name) or _norm(name) in _norm(item.mapping_value))
        usage_score = prefix_profile.get(item.target_master_code[:1], 0) / max(1, sum(prefix_profile.values()))
        score = name_score + (0.3 if contains else 0) + 0.3 * usage_score
        if score >= 0.25:
            basis = []
            if contains:
                basis.append("名前を含む")
            if name_score >= 0.25:
                basis.append(f"名前の類似{name_score:.2f}")
            if usage_score >= 0.5:
                basis.append("同じ税の使われ方の科目と同じ番号帯")
            scored.append((score, item, "・".join(basis) or "弱い類似"))
    scored.sort(key=lambda t: -t[0])
    return scored[:3]


def build_units(source: Path, profile, context):
    rows = build_rows(source, profile, context)
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    entries = source_format.read(source)
    usage: dict[str, str] = {}
    tax_by_account: dict[str, Counter] = defaultdict(Counter)
    for entry in entries:
        for line in entry.lines:
            semantic = candidate_semantic(line.tax_info.category) if line.tax_info else None
            tax_by_account[line.account][semantic.value if semantic else "OTHER"] += 1
    for account, counts in tax_by_account.items():
        usage[account] = counts.most_common(1)[0][0]
    exact_codes_by_usage: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row[COL["区分"]] == "科目" and row[COL["候補の種類"]] == KIND_SAME:
            exact_codes_by_usage[usage.get(row[COL["キー"]], "")][row[COL["現在の候補"]][:1]] += 1

    units, details = [], []

    def bulk(unit_id, label, kind, selected, choices):
        items = [(row[COL["キー"]], row[COL["現在の候補"]]) for row in selected]
        if not items:
            return
        units.append((unit_id, "一括", label, len(items), sum(int(row[COL["影響仕訳数"]]) for row in selected),
                      "", "", "", "同名の候補（一覧は 一括対象一覧）", choices, "", "", _sha(items)))
        details.extend((unit_id, kind, row[COL["弥生の内容"]], row[COL["親科目（補助のみ）"]],
                        row[COL["現在の候補"]], row[COL["影響仕訳数"]]) for row in selected)

    accounts = [row for row in rows if row[COL["区分"]] == "科目"]
    bulk("ACC-ALL-SAME", "同名のJDL科目へまとめて対応付け", "科目",
         [row for row in accounts if row[COL["候補の種類"]] == KIND_SAME],
         "一覧を見て、すべて正しければ OK（1件でも違えば空欄のまま連絡）")
    for row in accounts:
        if row[COL["候補の種類"]] == KIND_SAME:
            continue
        proposals = _account_proposals(row[COL["キー"]], usage.get(row[COL["キー"]], ""), exact_codes_by_usage, context)
        cells = [f"{item.target_master_code} {item.mapping_value}" for _, item, _ in proposals] + ["", "", ""]
        units.append((f"ACC-{hashlib.sha256(row[COL['キー']].encode()).hexdigest()[:8]}", "個別", row[COL["キー"]],
                      1, row[COL["影響仕訳数"]], *cells[:3],
                      " / ".join(basis for _, _, basis in proposals) or "候補なし（新規登録の検討）",
                      "提案1でよければ OK、他ならJDLコードを記入。新規登録なら登録後にシートを作り直す",
                      "", "", ""))
    subs = [row for row in rows if row[COL["区分"]] == "補助科目"]
    bulk("SUB-ALL-SAME", "同名のJDL補助へまとめて対応付け", "補助科目",
         [row for row in subs if row[COL["候補の種類"]] == KIND_SAME],
         "一覧を見て、すべて正しければ OK")
    parent_code = {row[COL["キー"]]: row[COL["現在の候補"]].split(" ", 1)[0] for row in accounts
                   if row[COL["候補の種類"]] == KIND_SAME}
    register: dict[str, list] = defaultdict(list)
    for row in subs:
        if row[COL["候補の種類"]] == KIND_SAME:
            continue
        parent = row[COL["親科目（補助のみ）"]]
        code = parent_code.get(parent)
        similar = sorted(
            ((_bigram_similarity(row[COL["弥生の内容"]], item.output_name), item) for item in context.subaccounts
             if code and item.parent_account_code == code),
            key=lambda t: -t[0])
        similar = [(score, item) for score, item in similar if score >= 0.3][:3]
        if similar:
            cells = [f"{item.target_master_code} {item.output_name}" for _, item in similar] + ["", "", ""]
            units.append((f"SUB-{hashlib.sha256(row[COL['キー']].encode()).hexdigest()[:8]}", "個別",
                          row[COL["キー"]], 1, row[COL["影響仕訳数"]], *cells[:3],
                          " / ".join(f"名前の類似{score:.2f}" for score, _ in similar),
                          "提案1でよければ OK、他ならJDL補助コードを記入", "", "", ""))
        else:
            register[parent].append(row)
    for parent, items in sorted(register.items(), key=lambda t: -sum(int(r[COL["影響仕訳数"]]) for r in t[1])):
        unit_id = f"REG-{hashlib.sha256(parent.encode()).hexdigest()[:8]}"
        units.append((unit_id, "登録の検討", f"親科目「{parent}」の補助 {len(items)}件", len(items),
                      sum(int(r[COL["影響仕訳数"]]) for r in items),
                      parent_code.get(parent, "（親科目が未対応）"), "", "",
                      "JDLの親科目に同じ・似た補助がない",
                      "JDLに登録するなら OK（登録一覧に載せる）。登録・PDF読み直し後、同名の一括で確定",
                      "", "", _sha([r[COL["キー"]] for r in items])))
        details.extend((unit_id, "補助科目（登録候補）", r[COL["弥生の内容"]], parent,
                        parent_code.get(parent, ""), r[COL["影響仕訳数"]]) for r in items)
    taxes = [row for row in rows if row[COL["区分"]] == "税区分"]
    bulk("TAX-ALL-CANDIDATE", "候補のある税区分をまとめて確認", "税区分",
         [row for row in taxes if row[COL["候補の種類"]] == KIND_SAME],
         "一覧を見て、すべて正しければ OK")
    for row in taxes:
        if row[COL["候補の種類"]] != KIND_SAME:
            units.append((f"TAX-HOLD-{hashlib.sha256(row[COL['キー']].encode()).hexdigest()[:8]}", "保留",
                          row[COL["キー"]], 1, row[COL["影響仕訳数"]], "", "", "",
                          "JDLでの書き方の候補がない（軽減8%・経過措置80%・控除不可など）",
                          "今は記入しない。JDL画面で入力方法を確認してから", "", "", ""))
    for row in rows:
        if row[COL["区分"]] == "JDLに入らない情報":
            units.append((f"INFO-{row[COL['キー']]}", "個別", f"JDLに入らない情報: {row[COL['キー']]}", 1,
                          row[COL["影響仕訳数"]], row[COL["現在の候補"]], "", "", "システムの事実説明",
                          "説明でよければ OK（JDLには出さず監査記録に残す）", "", "", ""))
    descriptions = [row[COL["弥生の内容"]] for row in rows if row[COL["区分"]] == "摘要"]
    rules = propose_rules(descriptions)
    return units, details, rules, rows


# ---------------------------------------------------------------- commands

def _write_csv(path: Path, rows) -> None:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    _atomic_write(path, buffer.getvalue().encode("utf-8-sig"))


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))


def _private(path: Path) -> None:
    if "data/private" not in path.resolve().as_posix():
        raise SystemExit("contains customer data; write it under data/private only")


def write(args) -> int:
    _private(args.output_dir)
    profiles, companies = _store(args.company_store)
    resolved = companies.resolve(args.company_id)
    if resolved.context is None:
        raise SystemExit("company setting is not confirmed yet")
    units, details, rules, rows = build_units(args.source, resolved.profile, resolved.context)
    out = args.output_dir
    _write_csv(out / f"判断シート_{args.tag}.csv", [UNIT_HEADER, *units])
    _write_csv(out / f"判断シート_一括対象一覧_{args.tag}.csv",
               [("単位ID", "区分", "弥生の内容", "親科目", "JDL候補", "影響仕訳数"), *details])
    _write_csv(out / f"摘要ルール_{args.tag}.csv", [RULE_HEADER, *[(*rule, "", "") for rule in rules]])
    print(json.dumps({
        "office_sheet_rows": len(rows),
        "units": dict(Counter(unit[1] for unit in units)),
        "bulk_items": dict(Counter(item[1] for item in details)),
        "description_rules": dict(Counter(rule[1] for rule in rules)),
        "descriptions": sum(1 for row in rows if row[COL["区分"]] == "摘要"),
    }, ensure_ascii=False))
    return 0


def expand(args) -> int:
    _private(args.output)
    profiles, companies = _store(args.company_store)
    resolved = companies.resolve(args.company_id)
    if resolved.context is None:
        raise SystemExit("company setting is not confirmed yet")
    units, details, _, rows = build_units(args.source, resolved.profile, resolved.context)
    current = {unit[0]: unit for unit in units}
    filled = [list(row) for row in rows]
    problems, counts = [], Counter()
    by_kind_key = {(row[COL["区分"]], row[COL["キー"]]): row for row in filled}
    for record in _read_csv(args.decisions):
        unit_id, decision = record["単位ID"], record["【記入】判断"].strip().upper()
        code = record["【記入】コード"].strip()
        if not decision and not code:
            counts["unit_unfilled"] += 1
            continue
        unit = current.get(unit_id)
        if unit is None:
            problems.append((unit_id, "今のデータ・マスターにない単位（古い判断シート）"))
            continue
        if decision not in {"", "OK"}:
            problems.append((unit_id, "判断は OK か空欄だけ"))
            continue
        if unit[1] == "一括":
            if decision != "OK" or code:
                problems.append((unit_id, "一括の単位は OK だけ"))
                continue
            if record["対象一覧SHA"] != unit[12]:
                problems.append((unit_id, "対象一覧が変わっている（作り直したシートで確認し直す）"))
                continue
            kind = {"ACC": "科目", "SUB": "補助科目", "TAX": "税区分"}[unit_id.split("-")[0]]
            for row in filled:
                if row[COL["区分"]] == kind and row[COL["候補の種類"]] == KIND_SAME:
                    row[COL["【記入】判断"]] = "OK"
                    counts[f"bulk:{kind}"] += 1
        elif unit[1] in {"登録の検討", "保留"}:
            counts[f"not_a_mapping:{unit[1]}"] += 1  # instruction only; nothing is filled
        elif unit_id.startswith("SUB-"):
            if decision == "OK" and code:
                problems.append((unit_id, "OK とコードの両方は書かない"))
                continue
            target = code or unit[5].split(" ", 1)[0]
            by_kind_key[("補助科目", unit[2])][COL["【記入】JDLコード"]] = target
            counts["individual:補助科目"] += 1
        elif unit_id.startswith("ACC-"):
            if decision == "OK" and code:
                problems.append((unit_id, "OK とコードの両方は書かない"))
                continue
            target = code or unit[5].split(" ", 1)[0]
            if not target:
                problems.append((unit_id, "提案がないので JDLコードが必要"))
                continue
            by_kind_key[("科目", unit[2])][COL["【記入】JDLコード"]] = target
            counts["individual:科目"] += 1
        elif unit_id.startswith("INFO-"):
            if decision != "OK":
                problems.append((unit_id, "OK だけ"))
                continue
            by_kind_key[("JDLに入らない情報", unit_id[len("INFO-"):])][COL["【記入】判断"]] = "OK"
            counts["individual:情報"] += 1
    # descriptions through approved rules
    rules = [rule for rule in _read_csv(args.rules) if rule["【記入】承認"].strip().upper() == "OK"]
    for rule in rules:
        if rule["種類"] == "語句の短縮" and not rule["【記入】短縮後の語句"].strip():
            problems.append((rule["ルールID"], "短縮後の語句が空"))
    preview = [("No", "元の摘要", "置換後（ルール適用）", "文字数", "状態")]
    proposals = {}
    for row in filled:
        if row[COL["区分"]] != "摘要":
            continue
        original = row[COL["弥生の内容"]]
        result = apply_rules(original, rules) if rules else ""
        if result and description_fits(result) and _digits(result) == _digits(original):
            proposals[row[COL["キー"]]] = result
            state = "適合（承認後に反映）"
        elif result and _digits(result) != _digits(original):
            state = "数字が変わるため使わない"
        else:
            state = "個別に記入が必要"
        preview.append((row[COL["No"]], original, result, len(result), state))
        counts[f"description:{state}"] += 1
    preview_sha = hashlib.sha256(json.dumps(preview, ensure_ascii=False).encode("utf-8")).hexdigest()
    preview_path = args.output.with_name(f"{args.output.stem}_摘要プレビュー_{preview_sha[:12]}.csv")
    if not preview_path.exists():  # same content → same name; never overwritten
        _write_csv(preview_path, preview)
    if args.preview_sha == preview_sha:
        for row in filled:
            if row[COL["区分"]] == "摘要" and row[COL["キー"]] in proposals:
                row[COL["【記入】意味・メモ"]] = proposals[row[COL["キー"]]]
                counts["description:filled"] += 1
    if problems:
        print(json.dumps({"expanded": False, "problems": [{"unit": u, "reason": r} for u, r in problems]},
                         ensure_ascii=False, indent=1))
        return 2
    _write_csv(args.output, [OFFICE_HEADER, *filled])
    try:
        plan = check_sheet(args.output.read_bytes(), args.source, resolved.profile, resolved.context)
        check = {"check": "PASS", "unfilled_rows": sum(1 for item in plan if item.get("action") == "unfilled")}
    except SheetCheckError as error:
        check = {"check": "FAIL", "problems": [{"sheet_row": r, "reason": m} for r, m in error.problems]}
    print(json.dumps({
        "expanded": True, "filled": dict(counts), "preview_sha256": preview_sha,
        "descriptions_filled": args.preview_sha == preview_sha,
        **check,
    }, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "expand"):
        command = sub.add_parser(name)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--company-store", type=Path, required=True)
        command.add_argument("--company-id", required=True)
    sub.choices["write"].add_argument("--output-dir", type=Path, required=True)
    sub.choices["write"].add_argument("--tag", required=True)
    sub.choices["expand"].add_argument("--decisions", type=Path, required=True)
    sub.choices["expand"].add_argument("--rules", type=Path, required=True)
    sub.choices["expand"].add_argument("--output", type=Path, required=True, help="filled office sheet to write")
    sub.choices["expand"].add_argument("--preview-sha", default="", help="SHA-256 of the description preview the Human checked")
    args = parser.parse_args()
    return write(args) if args.command == "write" else expand(args)


if __name__ == "__main__":
    raise SystemExit(main())

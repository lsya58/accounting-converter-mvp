"""Match a Yayoi file's accounts/subaccounts to one JDL company's account list.

Nothing is confirmed: every row is a proposal for the Human. The detailed sheet
(real names) is written only under data/private; stdout carries counts only.

Account classes
  A  exactly one selectable JDL account with the same name (confirm)
  B  same name after width/space normalization only (confirm the spelling)
  C  same name exists under two JDL codes (excluded; pick by code)
  D  same name exists but the JDL account is not in use (×)
  E  only an uncoded printed row has this name (not selectable; register a code)
  F  no JDL account of this name (choose another or register in JDL)

Subaccount classes
  A  the candidate parent has a JDL subaccount with the same name
  B  the candidate parent has JDL subaccounts, none with this name
  C  the candidate parent has no JDL subaccounts (parent-only or register)
  D  the parent account has no single candidate yet
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.application.jdl_account_list_pdf import JdlAccountListPdfTextParser
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write


def _normalized(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def uncoded_printed_names(pdf: Path) -> set[str]:
    store = JdlAccountPdfDraftStore()
    names = set()
    for text in store.extractor.extract_pages(pdf):
        for line in text.splitlines():
            match = JdlAccountListPdfTextParser._UNCODED_ROW.match(line)
            if match:
                names.add(match.group("name").strip())
    return names


def match(source: Path, draft_path: Path, pdf: Path | None):
    entries = detect_format(source).read(source)
    observation = JdlAccountPdfDraftStore().load(draft_path).observation
    selectable = defaultdict(list)
    disabled = set()
    for item in observation.printed_accounts:
        (selectable[item.name].append(item) if item.enabled else disabled.add(item.name))
    normalized = defaultdict(list)
    for name, items in selectable.items():
        normalized[_normalized(name)].extend(items)
    # Names excluded by the parser because two codes share them.
    duplicated = set()
    if pdf is not None:
        from accounting_converter.application.jdl_account_list_pdf import JdlAccountListTextPage
        raw = JdlAccountListPdfTextParser()
        texts = JdlAccountPdfDraftStore().extractor.extract_pages(pdf)
        # Re-read only the coded rows to learn which names were excluded.
        codes_by_name = defaultdict(set)
        for page in (JdlAccountListTextPage(i, t) for i, t in enumerate(texts, 1)):
            for line in page.text.splitlines():
                for pattern in (raw._CODED_ROW, raw._PARENT_ROW):
                    found = pattern.match(line)
                    if found:
                        codes_by_name[found.group("name").strip()].add(found.group("code"))
        duplicated = {name for name, codes in codes_by_name.items() if len(codes) > 1}
    uncoded = uncoded_printed_names(pdf) if pdf is not None else set()
    subs_by_parent = defaultdict(set)
    for item in observation.subaccounts:
        subs_by_parent[item.parent_account_code].add(item.name)

    usage = defaultdict(Counter)
    sub_usage = defaultdict(Counter)
    for entry in entries:
        for line in entry.lines:
            usage[line.account][line.side.value] += 1
            if line.sub_account:
                sub_usage[(line.account, line.sub_account)][line.side.value] += 1

    accounts = []
    candidate_code = {}
    for name, counts in sorted(usage.items(), key=lambda item: -sum(item[1].values())):
        exact = selectable.get(name, [])
        if len(exact) == 1:
            klass, candidate = "A", exact[0]
        elif name in duplicated:
            klass, candidate = "C", None
        elif len(normalized.get(_normalized(name), [])) == 1:
            klass, candidate = "B", normalized[_normalized(name)][0]
        elif name in disabled:
            klass, candidate = "D", None
        elif name in uncoded:
            klass, candidate = "E", None
        else:
            klass, candidate = "F", None
        if candidate is not None:
            candidate_code[name] = candidate.code
        # Reference only (never a candidate): JDL names containing or contained in this name.
        key = _normalized(name)
        hints = tuple(sorted(
            f"{item.code} {item.name}" for items in selectable.values() for item in items
            if candidate is None and len(_normalized(item.name)) >= 2
            and (_normalized(item.name) in key or key in _normalized(item.name))
        ))
        accounts.append((klass, name, counts, candidate, hints))

    subaccounts = []
    for (parent, sub), counts in sorted(sub_usage.items(), key=lambda item: -sum(item[1].values())):
        code = candidate_code.get(parent)
        if code is None:
            klass = "D"
        elif sub in subs_by_parent.get(code, ()):
            klass = "A"
        elif subs_by_parent.get(code):
            klass = "B"
        else:
            klass = "C"
        subaccounts.append((klass, parent, sub, counts, code))
    return accounts, subaccounts, observation


ACCOUNT_ACTION = {
    "A": "候補を確認して確定", "B": "表記違いの候補。同じ科目か確認",
    "C": "同名がJDLに複数コードあり。コードで選ぶ（現在は選択不可）",
    "D": "JDLで使用×。使用に変えるか別科目を選ぶ", "E": "JDLに印字のみ（コードなし）。コードを登録",
    "F": "JDLに同名なし。別科目を選ぶかJDLに登録",
}
SUB_ACTION = {
    "A": "候補を確認して確定", "B": "JDLに同名補助なし。別補助を選ぶかJDLに登録",
    "C": "JDLの親科目に補助なし。親科目のみで出すかJDLに補助を登録", "D": "親科目の確定が先",
}


def sheet(accounts, subaccounts) -> bytes:
    rows = [("区分", "分類", "弥生の科目", "弥生の補助", "借方行", "貸方行", "JDL候補コード", "JDL候補名",
             "確認内容", "参考: 名前の一部が一致するJDL科目（候補ではない）",
             "Human記入: JDLコード", "Human記入: JDL名称", "Human記入: 判断")]
    for klass, name, counts, candidate, hints in accounts:
        rows.append(("科目", klass, name, "", counts["DEBIT"], counts["CREDIT"],
                     candidate.code if candidate else "", candidate.name if candidate else "",
                     ACCOUNT_ACTION[klass], " / ".join(hints), "", "", ""))
    for klass, parent, sub, counts, code in subaccounts:
        rows.append(("補助", klass, parent, sub, counts["DEBIT"], counts["CREDIT"], code or "", "",
                     SUB_ACTION[klass], "", "", "", ""))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True, help="JDL account-list draft JSON")
    parser.add_argument("--pdf", type=Path, help="same JDL PDF, to classify C/E")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if "data/private" not in args.output.resolve().as_posix():
        raise SystemExit("the sheet contains customer data; write it under data/private only")
    accounts, subaccounts, observation = match(args.source, args.draft, args.pdf)
    _atomic_write(args.output, sheet(accounts, subaccounts))

    account_classes = Counter(item[0] for item in accounts)
    account_lines = Counter()
    for klass, _, counts, _, _ in accounts:
        account_lines[klass] += sum(counts.values())
    sub_classes = Counter(item[0] for item in subaccounts)
    sub_lines = Counter()
    for klass, _, _, counts, _ in subaccounts:
        sub_lines[klass] += sum(counts.values())
    print(json.dumps({
        "written": True,
        "jdl_selectable_accounts": sum(item.enabled for item in observation.printed_accounts),
        "jdl_subaccounts": len(observation.subaccounts),
        "accounts": {"by_class": dict(account_classes), "lines_by_class": dict(account_lines),
                     "unmatched_with_reference_hint": sum(1 for item in accounts if item[4])},
        "subaccounts": {"by_class": dict(sub_classes), "lines_by_class": dict(sub_lines)},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""How does JDL IBEX 出納帳 35.5 represent a 中間決算 (Yayoi 中決) entry? Screen investigation and minimal Probe.

Known (real JDL, 2026-11-07): a year-end 決算整理仕訳 is written with the date YYYY13DD (fiscal year end 07-31 ->
20261331), exported / imported only with 「決算整理を含む」 (closing_entries). Nothing is known about an interim
closing: no official document in this repository, no screen record, no export. It is NOT assumed to be month 13,
14, 15 or anything else, and it is never written as the year-end closing or as an ordinary journal.

Steps (each only after the previous one gave a result):
  sheet           the hand-entry / screen-investigation sheet and the JSON the Human fills in (data/private).
  judge-export    two JDL self-exports of the interim day (決算整理を含む / 含まない) with two hand entries that differ
                  only in being an interim closing entry (摘要 IC-NORMAL / IC-INTERIM). Result:
                    INTERIM_MARK_FOUND_IMPORT_UNVERIFIED  the CSV row differs (e.g. the date text) and the date text
                                                          is neither the ordinary date nor the year-end closing date
                    INTERIM_SAME_AS_YEAR_END_CLOSING      the CSV cannot tell it from 本決 (blocked: would change it)
                    CSV_CANNOT_CARRY_CLOSING / JDL_DOES_NOT_SEPARATE / UNDETERMINED (from the closing judge)
                    INTERIM_NOT_ENTERABLE                 the Human recorded that the screen offers no interim closing
  generate-import app-format Probe of journal 3605's shape (B2 対象外) written with the date text JDL exported, and
                  an ordinary control in its own file. Refused unless judge-export found a usable mark.
  judge-import    the closing import judge on that Probe (CLOSING_IMPORT_PRESERVED is what an implementation needs).

Nothing here changes the converter. 3605 stays SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION until a verified
representation is implemented with its own Evidence ID.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from accounting_converter.tools import yayoi_closing_probe_check as closing

NORMAL, INTERIM = "IC-NORMAL", "IC-INTERIM"
DATE = 2
SHAPE_3605 = (("IC-B2-NO", (("NO", "NO"), ("NO", "NO"))),)
SCREEN_TEMPLATE = {
    "jdl_version_seen_on_screen": "",
    "company_info_has_interim_closing_setting": None,  # true / false
    "company_info_interim_closing_setting_text": "",   # 例: 中間決算 する/しない、中間決算月（画面の表記のまま）
    "entry_screen_offers_interim_closing": None,       # 振替伝票入力で中間決算（中間整理）を選べるか
    "entry_screen_interim_text": "",                   # 月の選択肢・区分の表記のまま（例: 「中間」「中決」など）
    "export_dialog_options": "",                       # CSV出力画面の選択肢の表記のまま（決算整理を含む／含まない、ほか）
    "import_dialog_options": "",                       # CSV入力画面の選択肢の表記のまま
    "hand_entries_made": None,                         # IC-NORMAL / IC-INTERIM を入力できたか
    "notes": "",
}


def sheet(interim_day: str, year_end_day: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise SystemExit("write under data/private only")
    output_dir.mkdir(parents=True, exist_ok=True)
    day = f"{interim_day[:4]}-{interim_day[4:6]}-{interim_day[6:]}"
    text = "\n".join([
        f"# JDL 中間決算（仕訳3605）の画面調査（{day}）", "",
        "目的: JDL IBEX 出納帳35.5で中間決算の仕訳をどう表すかを、画面とJDL自身の出力で確かめる。"
        "13月・14月などと推測しない。**本番会社・アプリの本番設定は変更しない**（検証用の複製だけ）。", "",
        "## 1. 画面の確認（写真か画面の表記をそのまま記録）", "",
        "1. 検証用の複製会社を開く（バックアップから作成。作業前にバックアップを取る）。",
        "2. 会社情報（決算期・会計期間の画面）に「中間決算」の設定があるか。あれば表記と現在値を記録（変更しない）。",
        f"3. 振替伝票の入力で、{day} の仕訳を「中間決算（中間整理）」として入力できる選択肢があるか（月の選択肢や区分の表記）。",
        "4. CSV出力・CSV入力の画面に、「決算整理を含む／含まない」以外の選択肢（中間決算など）があるか。", "",
        "選択肢が無い場合は、ここで終了して `entry_screen_offers_interim_closing: false` を記録する（それも結果です）。", "",
        "## 2. 手入力2件（選択肢がある場合だけ）", "",
        f"- 日付 {day}、借方 現金(1111) 1,100 / 貸方 未払金(3181) 1,100、税なし（対象外）。2行の伝票（仕訳3605と同じ形）:",
        "  1行目・2行目とも 借方 現金 1,100 / 貸方 未払金 1,100",
        f"- 1件目: 通常の仕訳、摘要 `{NORMAL}`",
        f"- 2件目: 中間決算の仕訳として入力、摘要 `{INTERIM}`", "",
        "## 3. JDL自身のCSV出力（2回、同じ日付範囲）", "",
        f"- 「決算整理を含む」で {day} を出力 → `JDL_中間_含む_{interim_day}.csv`",
        f"- 「決算整理を含まない」で {day} を出力 → `JDL_中間_含まない_{interim_day}.csv`",
        "- ほかに中間決算用の選択肢があれば、それでも出力してファイル名に選択肢を書く。",
        "- 複製会社は確認後に削除してよい。", "",
        "## 4. 判定（開発側）", "",
        "```",
        "PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_interim_closing_probe judge-export \\",
        f"  --with JDL_中間_含む_{interim_day}.csv --without JDL_中間_含まない_{interim_day}.csv \\",
        f"  --screen screen_{interim_day}.json --interim-day {interim_day} --year-end-day {year_end_day}",
        "```", "",
        "INTERIM_MARK_FOUND_IMPORT_UNVERIFIED のときだけ、出力された日付の表記で取込Probeを作る（generate-import）。",
        "",
    ])
    procedure = output_dir / f"JDL操作手順_中間決算_{interim_day}.md"
    screen = output_dir / f"screen_{interim_day}.json"
    for path, content in ((procedure, text), (screen, json.dumps(SCREEN_TEMPLATE, ensure_ascii=False, indent=1) + "\n")):
        if path.exists():
            raise SystemExit(f"{path.name} already exists; nothing is overwritten")
        path.write_text(content, encoding="utf-8")
    return {"procedure": procedure.name, "screen_record": screen.name}


def judge_export(with_closing: Path, without_closing: Path, screen: dict, interim_day: str, year_end_day: str) -> dict:
    if screen.get("entry_screen_offers_interim_closing") is False:
        return {"result": "INTERIM_NOT_ENTERABLE", "screen": screen,
                "why": "the JDL screen offers no interim closing entry; 3605 stays blocked (Human: enter it in JDL or decide)"}
    out = closing.judge(with_closing, without_closing, markers=(NORMAL, INTERIM))
    out["screen"] = screen
    if out.get("result") != "CSV_MARK_FOUND_IMPORT_UNVERIFIED":
        return out
    rows = closing.marked(with_closing, (NORMAL, INTERIM))[INTERIM][0]
    dates = sorted({row[DATE] for row in rows})
    other = [d for d in out["column_differences"] if d["column"] != "日付"]
    out["interim_date_text"] = dates
    if len(dates) != 1 or not re.fullmatch(r"\d{8}", dates[0]):
        out["result"] = "UNDETERMINED"
        out["why"] = "the interim entry's rows do not carry one 8-digit date text"
    elif other:
        out["result"] = "UNDETERMINED"
        out["why"] = "columns other than the date differ; a representation beyond the date is not handled"
    elif dates[0] == interim_day:
        out["result"] = "CSV_CANNOT_CARRY_CLOSING"
    elif dates[0] == closing.closing_date(year_end_day):
        out["result"] = "INTERIM_SAME_AS_YEAR_END_CLOSING"
        out["why"] = "written like the year-end closing entry: the CSV cannot tell 中決 from 本決 (never converted)"
    else:
        out["result"] = "INTERIM_MARK_FOUND_IMPORT_UNVERIFIED"
    return out


def generate_import(source: Path, company_store: Path, company_id: str, interim_day: str, judged: dict,
                    output_dir: Path) -> dict:
    if judged.get("result") != "INTERIM_MARK_FOUND_IMPORT_UNVERIFIED":
        raise SystemExit("judge-export did not find a usable interim mark; nothing to import")
    (written,) = judged["interim_date_text"]
    return closing.generate_import(source, company_store, company_id, interim_day, output_dir, shapes=SHAPE_3605,
                                   written_date=written, label="中間決算の仕訳")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--interim-day", required=True, help="YYYYMMDD of the Yayoi 中決 journal (3605)")
    s.add_argument("--year-end-day", required=True)
    s.add_argument("--output-dir", type=Path, required=True)
    j = sub.add_parser("judge-export")
    j.add_argument("--with", dest="with_closing", type=Path, required=True)
    j.add_argument("--without", dest="without_closing", type=Path, required=True)
    j.add_argument("--screen", type=Path, required=True)
    j.add_argument("--interim-day", required=True)
    j.add_argument("--year-end-day", required=True)
    j.add_argument("--out", type=Path)
    g = sub.add_parser("generate-import")
    g.add_argument("--source", type=Path, required=True)
    g.add_argument("--company-store", type=Path, required=True)
    g.add_argument("--company-id", required=True)
    g.add_argument("--interim-day", required=True)
    g.add_argument("--judged", type=Path, required=True, help="JSON written by judge-export --out")
    g.add_argument("--output-dir", type=Path, required=True)
    i = sub.add_parser("judge-import")
    i.add_argument("--probe-dir", type=Path, required=True)
    i.add_argument("--with", dest="with_closing", type=Path, required=True)
    i.add_argument("--without", dest="without_closing", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "sheet":
        result = sheet(args.interim_day, args.year_end_day, args.output_dir)
    elif args.command == "judge-export":
        result = judge_export(args.with_closing, args.without_closing,
                              json.loads(args.screen.read_text(encoding="utf-8")), args.interim_day, args.year_end_day)
        if args.out:
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    elif args.command == "generate-import":
        result = generate_import(args.source, args.company_store, args.company_id, args.interim_day,
                                 json.loads(args.judged.read_text(encoding="utf-8")), args.output_dir)
    else:
        result = closing.judge_import(args.probe_dir, args.with_closing, args.without_closing)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

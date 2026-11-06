"""JDL 科目一覧 PDF old/new comparison on the text layer. Synthetic text only."""
from __future__ import annotations

import unittest

from accounting_converter.tools.jdl_master_pdf_diff import diff, records

OLD = """科 目 一 覧
1
勘 定 科 目 略 名 称 使用 課 区 税 区 入力 固変 比 率 説 明
  1111  現金  借現金 ○ 通貨
            釣銭  借釣銭 ×
  1311- 普通預金  借普通預金 ○ 預金
  -0001 銀行A  借
現金 借
"""
NEW = """科 目 一 覧
1
勘 定 科 目 略 名 称 使用 課 区 税 区 入力 固変 比 率 説 明
  1111  現金  借現金 ○ 通貨
  1112  釣銭  借釣銭 ○ 通貨
  1311- 普通預金  借普通預金 ○ 預金
  -0001 銀行A  借
  1312  新銀行  借新銀行 ○ 預金
現金 借
"""


class PdfDiffTest(unittest.TestCase):
    def test_hidden_code_row_is_not_dropped_and_use_flag_is_separate_from_existence(self):
        old = records([OLD])
        self.assertEqual([r["kind"] for r in old], ["coded", "uncoded", "parent", "sub", "group"])
        uncoded = old[1]
        self.assertEqual((uncoded["name"], uncoded["use"], uncoded["code"], uncoded["after"]), ("釣銭", "×", "", "1111"))

    def test_added_account_and_the_uncoded_row_that_became_coded(self):
        result = diff(records([OLD]), records([NEW]))
        self.assertEqual([r["code"] for r in result["added"]], ["1112", "1312"])
        self.assertEqual((result["removed"], result["changed"]), ([], []))
        self.assertEqual((result["uncoded"]["old"], result["uncoded"]["new"]), (1, 0))
        self.assertEqual(result["subaccounts"]["added"], [])

    def test_group_label_follows_the_accounts_it_closes(self):
        result = diff(records([OLD]), records([NEW]))
        # The label is printed after the block: every account before it gets that nearest following label.
        self.assertEqual(result["added"][0]["group_chain"], ["現金"])
        self.assertEqual(records([NEW])[-2]["group_chain"], ["現金"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from accounting_converter.application.subaccount_candidate_discovery import (
    rank_subaccount_candidates,
)


class SubaccountCandidateDiscoveryTests(unittest.TestCase):
    def test_exact_and_width_normalized_candidates_rank_first(self) -> None:
        candidates = rank_subaccount_candidates(
            "ＡＢＣ 株式会社",
            ("別会社", "ABC株式会社", "ABC商会"),
        )
        self.assertEqual(candidates[0].target_name, "ABC株式会社")
        self.assertEqual(candidates[0].priority, 0)

    def test_ten_character_prefix_is_a_search_signal_only(self) -> None:
        candidates = rank_subaccount_candidates(
            "ディーエムソリューションズ株式会社",
            ("無関係", "ディーエムソリューシ"),
        )
        self.assertEqual(candidates[0].target_name, "ディーエムソリューシ")
        self.assertEqual(candidates[0].priority, 1)

    def test_collision_warns_both_sources_without_unique_claim(self) -> None:
        peers = ("ABCDEFGHIJ甲", "ABCDEFGHIJ乙")
        for source in peers:
            result = rank_subaccount_candidates(
                source, ("ABCDEFGHIJ", "別名"), source_peer_names=peers
            )
            self.assertTrue(result[0].prefix_collision)
            self.assertEqual(result[0].target_name, "ABCDEFGHIJ")

    def test_punctuation_and_company_type_are_not_discarded(self) -> None:
        candidates = rank_subaccount_candidates(
            "株式会社LOGI･フロー",
            ("株式会社LOGI・フロー", "有限会社LOGI・フロー"),
        )
        self.assertEqual(candidates[0].target_name, "株式会社LOGI・フロー")
        self.assertEqual(candidates[0].priority, 0)
        self.assertNotEqual(candidates[1].priority, 0)

    def test_no_candidate_and_multiple_similar_candidates(self) -> None:
        self.assertEqual(rank_subaccount_candidates("入力元", ()), ())
        candidates = rank_subaccount_candidates(
            "テスト会社", ("テスト商会", "テスト法人")
        )
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(item.priority > 0 for item in candidates))


if __name__ == "__main__":
    unittest.main()

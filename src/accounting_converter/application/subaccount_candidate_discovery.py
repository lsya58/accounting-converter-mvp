from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import unicodedata


@dataclass(frozen=True)
class SubaccountCandidate:
    target_name: str
    reason: str
    priority: int
    prefix_collision: bool = False


def _search_name(value: str) -> str:
    # Search-only normalization. Persisted source and target identities stay exact.
    return "".join(unicodedata.normalize("NFKC", value).split())


def rank_subaccount_candidates(
    source_name: str,
    target_names: tuple[str, ...],
    *,
    source_peer_names: tuple[str, ...] = (),
) -> tuple[SubaccountCandidate, ...]:
    source = _search_name(source_name)
    peers = tuple(_search_name(name) for name in source_peer_names)
    collision = len(source) >= 10 and sum(
        len(peer) >= 10 and peer[:10] == source[:10] for peer in peers
    ) > 1
    ranked: list[tuple[int, float, int, SubaccountCandidate]] = []
    for index, target_name in enumerate(target_names):
        target = _search_name(target_name)
        similarity = SequenceMatcher(None, source, target).ratio()
        if source and source == target:
            priority, reason = 0, "表記をそろえると一致"
        elif len(source) > 10 and source[:10] == target:
            priority, reason = 1, "MF名称の先頭10文字と一致"
        elif source and target and (source.startswith(target) or target.startswith(source)):
            priority, reason = 2, "名称の先頭部分が一致"
        elif similarity >= 0.55:
            priority, reason = 3, "名称が似ています"
        else:
            priority, reason = 4, "その他の補助科目"
        ranked.append((
            priority, -similarity, index,
            SubaccountCandidate(
                target_name,
                reason,
                priority,
                prefix_collision=collision and priority in {0, 1, 2},
            ),
        ))
    return tuple(item for _priority, _score, _index, item in sorted(ranked))

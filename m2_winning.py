"""
M2. 화료 판정 모듈 (형태 판정)
책임: "4조합+1쌍" 성립 여부 판정, "7또이츠" 성립 여부 판정, 텐파이 여부 판정, 대기패 열거.
주의: 이 모듈은 역(Yaku)을 전혀 모릅니다. 오직 패의 형태만 봅니다.
의존성: M1 (패/손패 모듈)
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import Counter
from functools import lru_cache
from itertools import product
from typing import List, Optional, Tuple, Dict
from m1_tile import Tile, Hand, Meld, SUITS


# 34종 마작 모든 패의 프로토타입 리스트 (대기패 탐색용)
ALL_34_TILES: List[Tile] = []
for _suit in ("m", "p", "s"):
    for _val in range(1, 10):
        ALL_34_TILES.append(Tile(suit=_suit, value=_val))
for _val in range(1, 8):
    ALL_34_TILES.append(Tile(suit="z", value=_val))


@dataclass
class HandDivision:
    """
    손패의 멘츠 분해 결과 (M3 역 판정에서 활용)
    - pair: 머리(또이츠) 2장
    - chi_mentsu: 순쯔 목록 (각각 3장씩)
    - pon_mentsu: 커츠/깡쯔 목록 (각각 3장 또는 4장)
    - is_chitoitsu: 치토이츠 형태 여부
    """
    pair: Optional[Tuple[Tile, Tile]] = None
    chi_mentsu: List[Tuple[Tile, Tile, Tile]] = None
    pon_mentsu: List[Tuple[Tile, ...]] = None
    is_chitoitsu: bool = False

    def __post_init__(self):
        if self.chi_mentsu is None:
            self.chi_mentsu = []
        if self.pon_mentsu is None:
            self.pon_mentsu = []


def _check_chitoitsu(tiles: List[Tile]) -> bool:
    """치토이츠(서로 다른 7종류의 또이츠) 판정"""
    if len(tiles) != 14:
        return False
    counts: Dict[str, int] = {}
    for t in tiles:
        counts[t.code] = counts.get(t.code, 0) + 1
    # 정확히 7종류의 패가 각 2장씩이어야 함 (4장 1종류는 인정하지 않음)
    return len(counts) == 7 and all(c == 2 for c in counts.values())


def _find_mentsu_decompositions(tiles: List[Tile]) -> List[Tuple[List[Tuple[Tile, Tile, Tile]], List[Tuple[Tile, Tile, Tile]]]]:
    """
    정렬된 패 목록에서 가능한 (순쯔목록, 커츠목록) 분해들을 모두 찾음.
    tiles 매수는 3의 배수(0, 3, 6, 9, 12장).
    """
    if not tiles:
        return [([], [])]

    results = []
    first = tiles[0]

    # 1. 커츠(동일 패 3장) 시도
    first_matches = [i for i, t in enumerate(tiles) if t.matches(first)]
    if len(first_matches) >= 3:
        i1, i2, i3 = first_matches[0], first_matches[1], first_matches[2]
        remain = [t for idx, t in enumerate(tiles) if idx not in (i1, i2, i3)]
        kotsu = (tiles[i1], tiles[i2], tiles[i3])
        for sub_chis, sub_pons in _find_mentsu_decompositions(remain):
            results.append((sub_chis, [kotsu] + sub_pons))

    # 2. 순쯔(연속된 수패 3장) 시도 (자패 제외)
    if first.suit != "z" and first.value <= 7:
        i2 = None
        i3 = None
        for i, t in enumerate(tiles):
            if i2 is None and t.suit == first.suit and t.value == first.value + 1:
                i2 = i
            elif i3 is None and t.suit == first.suit and t.value == first.value + 2:
                i3 = i
        if i2 is not None and i3 is not None:
            remain = [t for idx, t in enumerate(tiles) if idx not in (0, i2, i3)]
            shuntsu = (first, tiles[i2], tiles[i3])
            for sub_chis, sub_pons in _find_mentsu_decompositions(remain):
                results.append(([shuntsu] + sub_chis, sub_pons))

    return results


def decompose_winning_hand(hand: Hand, win_tile: Optional[Tile] = None) -> List[HandDivision]:
    """
    화료 손패의 형태 분해 목록 반환 (화료가 아니면 빈 리스트)
    - 쯔모 시: hand.concealed_tiles가 이미 14장(또는 14 - 3*M장) 상태
    - 론 시: hand.concealed_tiles가 13장이고 win_tile 1장을 더해 14장 완성
    """
    melds = hand.melds
    num_melds = len(melds)
    expected_count = 14 - 3 * num_melds

    concealed = list(hand.concealed_tiles)

    if len(concealed) == expected_count:
        # 이미 14장(울기 감안) 손패인 경우 (쯔모 상태)
        pass
    elif len(concealed) == expected_count - 1 and win_tile is not None:
        # 13장 손패에 화료패 1장을 추가하는 경우 (론 상태 또는 가상 완성)
        concealed.append(win_tile)
    else:
        # 장수가 맞지 않음
        return []

    if num_melds > 4 or any(n > 4 for n in Counter(t.code for t in concealed + [t for m in melds for t in m.tiles]).values()):
        return []

    concealed.sort()

    divisions: List[HandDivision] = []

    # 1. 치토이츠 검사 (문전일 때만)
    if num_melds == 0 and _check_chitoitsu(concealed):
        divisions.append(HandDivision(is_chitoitsu=True))

    # 2. 일반형 (머리 1개 + 나머지 멘츠)
    # 머리 후보군 탐색
    seen_pair_codes = set()
    for i in range(len(concealed) - 1):
        t1, t2 = concealed[i], concealed[i + 1]
        if t1.matches(t2) and t1.code not in seen_pair_codes:
            seen_pair_codes.add(t1.code)
            # 머리를 제외한 나머지 패
            remain = concealed[:i] + concealed[i + 2:]
            decomps = _find_mentsu_decompositions(remain)
            for chis, pons in decomps:
                # 울어둔 멘츠도 합치기
                all_chis = list(chis)
                all_pons = list(pons)
                for m in melds:
                    if m.meld_type == "chi":
                        all_chis.append((m.tiles[0], m.tiles[1], m.tiles[2]))
                    else:  # pon, daiminkan, ankan, kakan
                        all_pons.append(tuple(m.tiles))

                divisions.append(HandDivision(
                    pair=(t1, t2),
                    chi_mentsu=all_chis,
                    pon_mentsu=all_pons,
                    is_chitoitsu=False
                ))

    return divisions


def is_winning_hand(hand: Hand, win_tile: Optional[Tile] = None) -> bool:
    """
    해당 손패가 화료 형태(4조합+1쌍 or 치토이츠)를 만족하는지 판정.
    win_tile이 주어지면 그 패를 더한 14장으로 판정.
    """
    divisions = decompose_winning_hand(hand, win_tile)
    return len(divisions) > 0


def get_waits(hand: Hand) -> List[Tile]:
    """
    손패(13장 상태)의 대기패 목록 반환.
    텐파이가 아니면 빈 리스트 반환.
    """
    expected_concealed = 13 - 3 * len(hand.melds)
    if len(hand.concealed_tiles) != expected_concealed:
        return []

    waits: List[Tile] = []
    counts = Counter(t.code for t in hand.all_tiles)
    for test_tile in ALL_34_TILES:
        if counts[test_tile.code] < 4 and is_winning_hand(hand, test_tile):
            waits.append(test_tile)
    return waits


def get_winning_tiles(hand: Hand) -> List[Tile]:
    """
    화료 가능한 패 목록 (대기패와 동일하지만 인터페이스 의미상 구분)
    """
    return get_waits(hand)


def is_tenpai(hand: Hand) -> bool:
    """
    손패가 텐파이 상태(대기패가 1장 이상 존재)인지 판정.
    """
    return len(get_waits(hand)) > 0


def tile_counts(tiles: List[Tile]) -> Tuple[int, ...]:
    counts = Counter(t.code for t in tiles)
    return tuple(counts[t.code] for t in ALL_34_TILES)


@lru_cache(maxsize=50000)
def _group_patterns(counts: Tuple[int, ...], honors: bool = False):
    """한 수트의 가능한 (완성 멘츠, 타쯔, 또이츠) 분해를 캐시한다."""
    if not any(counts):
        return frozenset({(0, 0, 0)})
    i = next(i for i, count in enumerate(counts) if count)
    patterns = set()

    def take(indices, addition):
        remaining = list(counts)
        for index in indices:
            remaining[index] -= 1
        for m, t, p in _group_patterns(tuple(remaining), honors):
            patterns.add((m + addition[0], t + addition[1], p + addition[2]))

    take([i], (0, 0, 0))
    if counts[i] >= 3:
        take([i, i, i], (1, 0, 0))
    if counts[i] >= 2:
        take([i, i], (0, 0, 1))
    if not honors:
        if i < 7 and counts[i + 1] and counts[i + 2]:
            take([i, i + 1, i + 2], (1, 0, 0))
        for delta in (1, 2):
            if i + delta < 9 and counts[i + delta]:
                take([i, i + delta], (0, 1, 0))
    return frozenset(patterns)


@lru_cache(maxsize=50000)
def shanten_from_counts(counts: Tuple[int, ...], open_melds: int = 0) -> int:
    """지원 화료형인 일반형·치토이츠의 최소 샹텐 수 (-1=화료, 0=텐파이)."""
    best = 8
    groups = [_group_patterns(counts[i:i + 9]) for i in (0, 9, 18)]
    groups.append(_group_patterns(counts[27:], True))
    for combination in product(*groups):
        m = open_melds + sum(x[0] for x in combination)
        if m > 4:
            continue
        pairs = sum(x[2] for x in combination)
        taatsu = sum(x[1] for x in combination) + max(0, pairs - 1)
        best = min(best, 8 - 2 * m - min(4 - m, taatsu) - int(pairs > 0))
    if open_melds == 0:
        best = min(best, 6 - sum(c >= 2 for c in counts) + max(0, 7 - sum(c > 0 for c in counts)))
    return best


def calculate_shanten(hand: Hand) -> int:
    return shanten_from_counts(tile_counts(hand.concealed_tiles), len(hand.melds))

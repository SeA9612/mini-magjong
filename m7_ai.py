"""
M7. AI 모듈
책임: AI의 의사결정.
규칙: 어떤 판정 로직도 직접 구현하지 않고, M1~M6 모듈을 호출하여 판단.
의존성: M1 ~ M6
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from functools import lru_cache
from m1_tile import Tile, Hand, Wall
from m2_winning import is_tenpai, get_waits, ALL_34_TILES, tile_counts, shanten_from_counts
from m3_yaku import has_any_yaku, YakuContext
from m5_riichi import RiichiState, can_riichi, can_declare_riichi_with_discard, is_locked


@lru_cache(maxsize=30000)
def _efficiency(counts, all_counts, melds):
    base = shanten_from_counts(counts, melds)
    effective = 0
    for i, owned in enumerate(all_counts):
        if owned >= 4:
            continue
        drawn = list(counts)
        drawn[i] += 1
        if shanten_from_counts(tuple(drawn), melds) < base:
            effective += 4 - owned
    return -base * 100000 + effective * 100


def _evaluate_tile_efficiency(hand: Hand, tile_to_discard: Tile) -> int:
    """
    해당 패를 버렸을 때 남은 13장의 유효패(대기패 및 멘츠 형성 패) 점수 평가
    """
    temp_hand = hand.clone()
    temp_hand.remove(tile_to_discard)

    # 버린 패도 이미 사용된 실물이므로 유효패 매수에서 제외한다.
    return _efficiency(tile_counts(temp_hand.concealed_tiles), tile_counts(hand.all_tiles), len(hand.melds))


def choose_discard(
    hand: Hand,
    context: YakuContext,
    riichi_state: RiichiState,
    drawn_tile: Optional[Tile] = None
) -> Tile:
    """
    버릴 패 선택:
    - 리치 상태인 경우: 쯔모기리(방금 뽑은 패를 그대로 버림)
    - 리치가 아닌 경우: 유효패/대기패가 가장 많이 남는 최적의 패 선택
    """
    # 1. 리치 상태면 무조건 쯔모기리
    if is_locked(riichi_state):
        if drawn_tile is not None and drawn_tile in hand.concealed_tiles:
            return drawn_tile
        return hand.concealed_tiles[-1]

    # 2. 손패 내에서 1장씩 가상으로 버려보며 유효패 평가 점수가 가장 높은 패 탐색
    best_tile = hand.concealed_tiles[0]
    best_score = float('-inf')

    # 중복 패 검사 방지
    tested_codes = set()
    for tile in hand.concealed_tiles:
        if tile in tested_codes:
            continue
        tested_codes.add(tile)

        score = _evaluate_tile_efficiency(hand, tile)

        # 같은 샹텐·유효패 수이면 고립 자패·노두패를 우선 타패한다.
        if tile.is_honor():
            # 역패가 아닌 자패는 우선 버림
            is_yakuhai = (tile.value in (5, 6, 7) or
                          tile.value == context.round_wind or
                          tile.value == context.seat_wind)
            if not is_yakuhai and hand.count(tile) == 1:
                score += 50
            elif is_yakuhai and hand.count(tile) == 1:
                score += 30
        elif tile.is_terminal() and hand.count(tile) == 1:
            score += 20
        if tile.is_aka:
            score -= 5

        if score > best_score:
            best_score = score
            best_tile = tile

    return best_tile


def should_riichi(
    hand: Hand,
    context: YakuContext,
    riichi_state: RiichiState,
    score: int = 1000,
    wall: Optional[Wall] = None,
    discard_tile: Optional[Tile] = None
) -> bool:
    """
    리치 선언 여부 결정:
    AI는 리치가 가능하면 적극적으로 선언함.
    """
    if discard_tile is not None:
        return can_declare_riichi_with_discard(hand, riichi_state, discard_tile, wall, score)
    return can_riichi(hand, riichi_state, wall=wall, score=score)


def choose_reaction(
    available_actions: List[Dict[str, Any]],
    hand: Hand,
    context: YakuContext
) -> Dict[str, Any]:
    """
    상대방의 행동에 대한 반응 선택:
    - 론(ron)이 가능하면 100% 론 화료!
    - 울기(chi, pon, kan)의 경우:
      AI는 멘젠을 지향하지만, 확실한 역(탕야오 또는 역패)이 보장될 때 퐁/치 수행
    """
    # 1. 론 화료는 최우선 실행
    for action in available_actions:
        if action["type"] == "ron":
            return action

    # 2. 깡: 암깡은 거의 항상 실행
    for action in available_actions:
        if action["type"] == "kan" and action.get("kan_type") == "ankan":
            return action

    # 3. 퐁: 역패(백/발/중/장풍/자풍) 퐁은 적극 수용
    for action in available_actions:
        if action["type"] == "pon":
            target = action["tile"]
            if target.is_honor():
                if (target.value in (5, 6, 7) or
                    target.value == context.round_wind or
                    target.value == context.seat_wind):
                    return action

    # 그 외에는 패스
    return {"type": "pass"}

"""
M5. 리치 모듈
책임: 리치 선언 조건 판정, 리치 후 잠금 상태 관리, 리치 후 암깡(대기패 불변) 판정.
의존성: M1, M2(텐파이 확인)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
from m1_tile import Tile, Hand, Wall
from m2_winning import is_tenpai, get_waits


@dataclass
class RiichiState:
    """플레이어의 리치 관련 상태"""
    is_riichi: bool = False
    is_double_riichi: bool = False
    riichi_turn: Optional[int] = None
    riichi_tile: Optional[Tile] = None


def get_riichi_discard_candidates(hand: Hand) -> List[Tile]:
    """
    14장 손패에서 어떤 패를 버렸을 때 13장 텐파이가 되는지(리치 선언 타패 후보) 반환.
    """
    candidates: List[Tile] = []
    seen = set()
    for tile in hand.concealed_tiles:
        if tile.code not in seen:
            seen.add(tile.code)
            test_hand = hand.clone()
            test_hand.remove(tile)
            if is_tenpai(test_hand):
                candidates.append(tile)
    return candidates


def can_riichi(hand: Hand, riichi_state: RiichiState, wall: Optional[Wall] = None, score: int = 1000) -> bool:
    """
    리치 선언 가능 조건:
    1. 아직 리치하지 않음
    2. 문전(menzen) 상태
    3. 남은 패산이 4장 이상 (최소 1회 이상 쯔모 기회 존재)
    4. 보유 점수가 1000점 이상
    5. 텐파이 상태:
       - 14장 상태(쯔모 직후): 손패 중 1장을 버려 텐파이가 될 수 있는가 (후보 1개 이상)
       - 13장 상태: 현재 손패가 텐파이인가
    """
    if riichi_state.is_riichi:
        return False
    if not hand.is_menzen:
        return False
    if score < 1000:
        return False
    if wall is not None and wall.remaining() < 4:
        return False

    num_melds = len(hand.melds)
    concealed_count = len(hand.concealed_tiles)
    expected_13 = 13 - 3 * num_melds
    expected_14 = 14 - 3 * num_melds

    if concealed_count == expected_14:
        return len(get_riichi_discard_candidates(hand)) > 0
    elif concealed_count == expected_13:
        return is_tenpai(hand)

    return False


def can_declare_riichi_with_discard(
    hand: Hand, riichi_state: RiichiState, tile: Tile,
    wall: Optional[Wall] = None, score: int = 1000
) -> bool:
    """선택한 패를 실제로 버린 뒤 텐파이가 되는 경우에만 리치 허용."""
    if len(hand.concealed_tiles) != 14 - 3 * len(hand.melds):
        return False
    if tile not in hand.concealed_tiles:
        return False
    if not can_riichi(hand, riichi_state, wall, score):
        return False
    remaining_hand = hand.clone()
    remaining_hand.remove(tile)
    return is_tenpai(remaining_hand)


def declare_riichi(riichi_state: RiichiState, turn_count: int = 1, tile: Optional[Tile] = None) -> None:
    """
    리치 선언 실행
    """
    riichi_state.is_riichi = True
    riichi_state.riichi_turn = turn_count
    riichi_state.riichi_tile = tile


def is_locked(riichi_state: RiichiState) -> bool:
    """
    리치 선언 후 손패 변경이 잠겼는지(쯔모기리 강제) 여부
    """
    return riichi_state.is_riichi


def can_ankan_after_riichi(hand: Hand, tile: Tile) -> bool:
    """
    리치 후 암깡 가능 여부 판정 (대기패 불변 원칙):
    - 손패에 방금 쯔모한 tile 포함 4장이 있어야 함.
    - 암깡을 하더라도 대기패 목록이 깡 이전과 100% 동일해야 함.
    """
    if hand.count(tile) != 4:
        return False

    # 1. 깡 이전 13장 상태의 대기패 목록
    # (현재 손패가 쯔모 직후 14장 상태이므로, tile 1장을 뺀 13장 기준 대기패)
    test_hand = hand.clone()
    test_hand.remove(tile)
    original_waits = set(w.code for w in get_waits(test_hand))
    if not original_waits:
        return False

    # 2. 가상으로 암깡을 수행한 후의 손패 상태
    # tile 4장을 제거하고 ankan 멘츠 등록
    kan_hand = hand.clone()
    for _ in range(4):
        kan_hand.remove(tile)
    from m1_tile import Meld
    kan_hand.melds.append(Meld("ankan", [tile, tile, tile, tile]))

    # 3. 깡 이후 손패(현재 10장)의 대기패 목록
    new_waits = set(w.code for w in get_waits(kan_hand))

    # 대기패가 한 장이라도 바뀌면 리치 후 암깡 불가
    return original_waits == new_waits

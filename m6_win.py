"""
M6. 론/쯔모 모듈 (화료 실행)
책임: 실제 화료 가능 여부 최종 확인, 후리텐 판정, 론/쯔모/울기 우선순위 처리.
의존성: M1, M2, M3
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from m1_tile import Tile, Hand, DiscardRecord
from m2_winning import is_winning_hand, get_waits
from m3_yaku import has_any_yaku, get_yaku, YakuContext, Yaku


def is_furiten(waits: List[Tile], discard_record: DiscardRecord) -> bool:
    """
    후리텐(振聴) 판정:
    자신의 버림패 기록에 현재 대기패 중 단 하나라도 포함되어 있으면 후리텐.
    (후리텐 상태에서는 어떤 대기패가 나와도 론 화료 불가, 오직 쯔모 화료만 가능)
    """
    for w in waits:
        if discard_record.has_tile(w):
            return True
    return False


def can_ron(
    hand: Hand,
    tile: Tile,
    discard_record: DiscardRecord,
    context: YakuContext
) -> bool:
    """
    론(ロン) 화료 가능 여부 판정:
    1. 패 형태가 화료를 만족하는가 (M2)
    2. 역(Yaku)이 최소 1개 이상 성립하는가 (M3)
    3. 후리텐이 아닌가 (자신의 버림패에 대기패가 없음)
    """
    # 1. 형태 확인
    if len(hand.concealed_tiles) != 13 - 3 * len(hand.melds) or not is_winning_hand(hand, tile):
        return False

    # 2. 대기패 기반 후리텐 확인
    waits = get_waits(hand)
    if is_furiten(waits, discard_record):
        return False

    # 3. 론 컨텍스트로 역 존재 확인
    ron_context = YakuContext(
        is_riichi=context.is_riichi,
        is_tsumo=False,
        round_wind=context.round_wind,
        seat_wind=context.seat_wind,
        win_tile=tile
    )
    if not has_any_yaku(hand, ron_context):
        return False

    return True


def can_tsumo(hand: Hand, context: YakuContext) -> bool:
    """
    쯔모(ツモ) 화료 가능 여부 판정:
    1. 패 형태가 화료를 만족하는가 (현재 손패 14장 상태)
    2. 역(Yaku)이 최소 1개 이상 성립하는가 (문전청자모 포함)
    * 주의: 후리텐이어도 쯔모 화료는 가능함!
    """
    if context.win_tile is None or context.win_tile not in hand.concealed_tiles or not is_winning_hand(hand):
        return False

    tsumo_context = YakuContext(
        is_riichi=context.is_riichi,
        is_tsumo=True,
        round_wind=context.round_wind,
        seat_wind=context.seat_wind,
        win_tile=context.win_tile
    )
    return has_any_yaku(hand, tsumo_context)


def resolve_priority(actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    복수 반응 간의 우선순위 해결:
    론(ron) > 대명깡(kan) / 퐁(pon) > 치(chi) > 패스(pass)
    """
    priority_order = {
        "ron": 4,
        "kan": 3,
        "pon": 3,
        "chi": 2,
        "pass": 1
    }

    if not actions:
        return None

    # 우선순위가 가장 높은 액션 선택
    best_action = max(actions, key=lambda a: priority_order.get(a.get("type", "pass"), 0))
    if best_action.get("type") == "pass":
        return None
    return best_action

"""
M4. 울기 모듈 (치/퐁/깡)
책임: 버림패에 대한 치/퐁/깡 가능 여부 판정, 울기 후 손패 상태 처리, 깡 후 영상패 보충.
의존성: M1 (패/손패 모듈)
"""

from __future__ import annotations
from typing import List, Optional, Tuple
from m1_tile import Tile, Hand, Meld, Wall


def can_chi(hand: Hand, tile: Tile, seat_relation: str = "kamicha") -> List[Tuple[Tile, Tile]]:
    """
    치 가능 조합 목록 반환.
    - 상가(kamicha)의 버림패만 가능.
    - 자패('z')는 치 불가.
    - 반환값: 손패에서 치에 사용할 수 있는 2장 한 쌍들의 목록 (예: [(3m, 4m), ...])
    """
    if seat_relation != "kamicha":
        return []
    if tile.suit == "z":
        return []

    combinations = []
    v = tile.value
    st = tile.suit

    # 3가지 형태의 순쯔가 가능:
    # 1. [v-2, v-1, v]
    # 2. [v-1, v, v+1]
    # 3. [v, v+1, v+2]
    patterns = [
        (v - 2, v - 1),
        (v - 1, v + 1),
        (v + 1, v + 2)
    ]

    for p1_val, p2_val in patterns:
        if 1 <= p1_val <= 9 and 1 <= p2_val <= 9:
            t1 = Tile(suit=st, value=p1_val)
            t2 = Tile(suit=st, value=p2_val)
            if hand.count(t1) >= 1 and hand.count(t2) >= 1:
                # 실제로 손패에 존재하는 타일 객체 가져오기
                tile1 = next(t for t in hand.concealed_tiles if t.matches(t1))
                tile2 = next(t for t in hand.concealed_tiles if t.matches(t2))
                combinations.append((tile1, tile2))

    return combinations


def can_pon(hand: Hand, tile: Tile) -> bool:
    """
    퐁 가능 여부 (상대방의 버림패와 같은 패를 손패에 2장 이상 보유)
    """
    return hand.count(tile) >= 2


def can_kan(hand: Hand, tile: Optional[Tile] = None, is_turn: bool = True) -> List[Tuple[str, Tile]]:
    """
    깡 가능 목록 반환: [(kan_type, tile), ...]
    - kan_type: 'ankan', 'daiminkan', 'kakan'
    - is_turn=True: 자신의 차례 (암깡 or 가깡 가능)
    - is_turn=False: 상대방의 버림패 tile에 대해 대명깡 가능
    """
    available = []

    if is_turn:
        # 1. 암깡 (손패에 4장 보유)
        checked_codes = set()
        for t in hand.concealed_tiles:
            if t.code not in checked_codes:
                checked_codes.add(t.code)
                if hand.count(t) == 4:
                    available.append(("ankan", t))

        # 2. 가깡 (이미 퐁한 멘츠가 있고, 그 4번째 패를 손패에 들고 있음)
        for m in hand.melds:
            if m.meld_type == "pon":
                pon_tile = m.tiles[0]
                if hand.count(pon_tile) >= 1:
                    actual = next(t for t in hand.concealed_tiles if t.matches(pon_tile))
                    available.append(("kakan", actual))
    else:
        # 3. 대명깡 (상대방 버림패 tile에 대해 손패에 3장 보유)
        if tile is not None and hand.count(tile) == 3:
            available.append(("daiminkan", tile))

    return available


def apply_chi(hand: Hand, tile: Tile, partner_tiles: Tuple[Tile, Tile]) -> Meld:
    """
    치 실행: 손패에서 partner_tiles를 제거하고 치 멘츠 등록
    """
    t1, t2 = partner_tiles
    hand.remove(t1)
    hand.remove(t2)
    meld_tiles = sorted([t1, t2, tile])
    meld = Meld(meld_type="chi", tiles=meld_tiles, target_tile=tile)
    hand.melds.append(meld)
    return meld


def apply_pon(hand: Hand, tile: Tile) -> Meld:
    """
    퐁 실행: 손패에서 동일 패 2장을 제거하고 퐁 멘츠 등록
    """
    removed = []
    # 2장 제거
    for _ in range(2):
        for t in hand.concealed_tiles:
            if t.matches(tile):
                hand.concealed_tiles.remove(t)
                removed.append(t)
                break
    meld_tiles = sorted(removed + [tile])
    meld = Meld(meld_type="pon", tiles=meld_tiles, target_tile=tile)
    hand.melds.append(meld)
    return meld


def apply_kan(hand: Hand, tile: Tile, kan_type: str) -> Meld:
    """
    깡 실행: 손패 및 멘츠 갱신
    """
    if kan_type == "ankan":
        # 손패에서 4장 모두 제거
        removed = [t for t in hand.concealed_tiles if t.matches(tile)]
        for t in removed:
            hand.concealed_tiles.remove(t)
        meld = Meld(meld_type="ankan", tiles=removed)
        hand.melds.append(meld)
        return meld

    elif kan_type == "daiminkan":
        # 손패에서 3장 제거 + 상대 버림패 합치기
        removed = []
        for _ in range(3):
            for t in hand.concealed_tiles:
                if t.matches(tile):
                    hand.concealed_tiles.remove(t)
                    removed.append(t)
                    break
        meld = Meld(meld_type="daiminkan", tiles=sorted(removed + [tile]), target_tile=tile)
        hand.melds.append(meld)
        return meld

    elif kan_type == "kakan":
        # 손패에서 1장 제거, 기존 pon 멘츠에 추가
        actual = next((t for t in hand.concealed_tiles if t.matches(tile)), None)
        if actual is None:
            raise ValueError("가깡할 패가 손패에 없습니다.")
        for m in hand.melds:
            if m.meld_type == "pon" and m.tiles[0].matches(tile):
                hand.remove(actual)
                m.meld_type = "kakan"
                m.tiles.append(actual)
                m.tiles.sort()
                return m
        raise ValueError(f"가깡 대상 퐁 멘츠를 찾을 수 없음: {tile}")

    else:
        raise ValueError(f"잘못된 kan_type: {kan_type}")


def after_kan_draw(wall: Wall, hand: Hand) -> Optional[Tile]:
    """
    깡 후 영상패(rinshan) 뽑아서 손패에 추가
    """
    tile = wall.draw_rinshan()
    if tile is not None:
        hand.add(tile)
    return tile

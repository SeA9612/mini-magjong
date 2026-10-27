"""
M3. 역 판정 모듈
책임: 화료 형태가 결정된 손패에 대해, 성립하는 역 목록을 반환.
1차 지원 역:
  - 리치 (Riichi)
  - 문전청자모 (Menzen Tsumo)
  - 핑후 (Pinfu)
  - 탕야오 (Tanyao)
  - 역패: 백, 발, 중, 장풍패, 자풍패
  - 치토이츠 (Seven Pairs)
  - 또이또이 (Toitoi)
의존성: M1, M2(단방향)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Set
from m1_tile import Tile, Hand, Meld
from m2_winning import decompose_winning_hand, is_winning_hand, HandDivision


@dataclass(frozen=True)
class Yaku:
    name: str        # 한글 이름
    romaji: str      # 영문/로마자 이름
    han_closed: int  # 문전 판수 (추후 확장 대비)
    han_open: int    # 후로 판수 (0이면 문전 한정)

    def __repr__(self) -> str:
        return f"<Yaku: {self.name}>"

    def __str__(self) -> str:
        return self.name


# 1차 지원 역 정의
YAKU_RIICHI = Yaku("리치", "Riichi", 1, 0)
YAKU_TSUMO = Yaku("문전청자모", "Menzen Tsumo", 1, 0)
YAKU_PINFU = Yaku("핑후", "Pinfu", 1, 0)
YAKU_TANYAO = Yaku("탕야오", "Tanyao", 1, 1)
YAKU_YAKUHAI_HAKU = Yaku("역패(백)", "Yakuhai (Haku)", 1, 1)
YAKU_YAKUHAI_HATSU = Yaku("역패(발)", "Yakuhai (Hatsu)", 1, 1)
YAKU_YAKUHAI_CHUN = Yaku("역패(중)", "Yakuhai (Chun)", 1, 1)
YAKU_YAKUHAI_ROUND = Yaku("역패(장풍)", "Yakuhai (Round Wind)", 1, 1)
YAKU_YAKUHAI_SEAT = Yaku("역패(자풍)", "Yakuhai (Seat Wind)", 1, 1)
YAKU_CHITOITSU = Yaku("치토이츠", "Chiitoitsu", 2, 0)
YAKU_TOITOI = Yaku("또이또이", "Toitoi", 2, 2)


@dataclass
class YakuContext:
    is_riichi: bool = False
    is_tsumo: bool = False
    round_wind: int = 1   # 1=동, 2=남
    seat_wind: int = 1    # 1=동, 2=남
    win_tile: Optional[Tile] = None


# --- 개별 역 판정 함수들 ---

def check_riichi(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    if context.is_riichi and hand.is_menzen:
        return YAKU_RIICHI
    return None


def check_tsumo(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    if context.is_tsumo and hand.is_menzen:
        return YAKU_TSUMO
    return None


def check_tanyao(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    # 손패의 모든 패(울기 포함 + 화료패)에 1, 9, 자패가 없어야 함
    all_tiles = list(hand.all_tiles)
    if context.win_tile is not None and len(hand.concealed_tiles) == 13 - 3 * len(hand.melds):
        all_tiles.append(context.win_tile)
    if all(t.is_simple() for t in all_tiles):
        return YAKU_TANYAO
    return None


def check_chitoitsu(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    if hand.is_menzen and division.is_chitoitsu:
        return YAKU_CHITOITSU
    return None


def check_toitoi(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    if not division.is_chitoitsu and len(division.pon_mentsu) == 4:
        return YAKU_TOITOI
    return None


def check_yakuhai(hand: Hand, context: YakuContext, division: HandDivision) -> List[Yaku]:
    """백/발/중 및 장풍/자풍 역패 코츠 확인"""
    res = []
    if division.is_chitoitsu:
        return res

    for kotsu in division.pon_mentsu:
        first = kotsu[0]
        if first.suit == "z":
            val = first.value
            if val == 5:
                res.append(YAKU_YAKUHAI_HAKU)
            elif val == 6:
                res.append(YAKU_YAKUHAI_HATSU)
            elif val == 7:
                res.append(YAKU_YAKUHAI_CHUN)

            if val == context.round_wind:
                res.append(YAKU_YAKUHAI_ROUND)
            if val == context.seat_wind:
                res.append(YAKU_YAKUHAI_SEAT)
    return res


def check_pinfu(hand: Hand, context: YakuContext, division: HandDivision) -> Optional[Yaku]:
    """
    핑후 조건:
    1. 문전일 것
    2. 4순쯔 + 1또이츠
    3. 머리(또이츠)가 역패가 아닐 것 (삼원패 X, 장풍 X, 자풍 X)
    4. 대기가 양면 대기일 것 (win_tile이 순쯔의 양 끝 중 하나여야 하며, 123의 3 대기 또는 789의 7 대기는 변짱이므로 제외)
    """
    if not hand.is_menzen or division.is_chitoitsu:
        return None
    if len(division.chi_mentsu) != 4:
        return None
    if division.pair is None:
        return None

    # 머리 역패 검사
    pair_tile = division.pair[0]
    if pair_tile.suit == "z":
        # 자패 머리: 백, 발, 중, 장풍, 자풍이면 핑후 불가 (객풍패는 가능)
        if pair_tile.value in (5, 6, 7):
            return None
        if pair_tile.value == context.round_wind or pair_tile.value == context.seat_wind:
            return None

    # 이 분해에서 화료패가 실제로 양면 순쯔를 완성하는지 확인한다.
    win_tile = context.win_tile
    if win_tile is None:
        return None
    for sequence in division.chi_mentsu:
        low, _, high = sorted(sequence)
        if win_tile.matches(low) and high.value < 9:
            return YAKU_PINFU
        if win_tile.matches(high) and low.value > 1:
            return YAKU_PINFU
    return None


def get_yaku(hand: Hand, context: YakuContext) -> List[Yaku]:
    """
    화료 손패에 대해 성립하는 역 목록을 반환.
    손패가 여러 가지 형태로 분해될 수 있는 경우(예: 치토이츠 vs 순쯔/커츠 등),
    역이 성립하는 최선의 형태를 선택합니다.
    """
    divisions = decompose_winning_hand(hand, context.win_tile)
    if not divisions:
        return []

    best_yaku_set: List[Yaku] = []

    for div in divisions:
        current_yaku: List[Yaku] = []

        # 1. 리치
        r = check_riichi(hand, context, div)
        if r: current_yaku.append(r)

        # 2. 쯔모
        t = check_tsumo(hand, context, div)
        if t: current_yaku.append(t)

        # 3. 탕야오
        ty = check_tanyao(hand, context, div)
        if ty: current_yaku.append(ty)

        # 4. 치토이츠
        ch = check_chitoitsu(hand, context, div)
        if ch: current_yaku.append(ch)

        # 5. 또이또이
        tt = check_toitoi(hand, context, div)
        if tt: current_yaku.append(tt)

        # 6. 역패
        yh = check_yakuhai(hand, context, div)
        current_yaku.extend(yh)

        # 7. 핑후
        pf = check_pinfu(hand, context, div)
        if pf: current_yaku.append(pf)

        han = lambda items: sum(y.han_closed if hand.is_menzen else y.han_open for y in items)
        if han(current_yaku) > han(best_yaku_set):
            best_yaku_set = current_yaku

    return best_yaku_set


def has_any_yaku(hand: Hand, context: YakuContext) -> bool:
    """
    역이 하나라도 성립하는지 판정 (화료 가능 여부 판정용)
    """
    return len(get_yaku(hand, context)) > 0

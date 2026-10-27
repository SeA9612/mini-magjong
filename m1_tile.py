"""
M1. 패/손패 모듈 (데이터 계층)
책임: 패의 표현, 손패 정렬, 패 산 관리, 버림패 기록.
의존성: 없음 (가장 기본이 되는 모듈)
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# 패 종류 정의
# m: 만수패 (1~9)
# p: 통수패 (1~9)
# s: 삭수패 (1~9)
# z: 자패 (1=동, 2=남, 3=서, 4=북, 5=백, 6=발, 7=중)
SUITS = ("m", "p", "s", "z")

DISPLAY_NAMES = {
    "1m": "一萬", "2m": "二萬", "3m": "三萬", "4m": "四萬", "5m": "五萬",
    "6m": "六萬", "7m": "七萬", "8m": "八萬", "9m": "九萬",
    "1p": "①筒", "2p": "②筒", "3p": "③筒", "4p": "④筒", "5p": "⑤筒",
    "6p": "⑥筒", "7p": "⑦筒", "8p": "⑧筒", "9p": "⑨筒",
    "1s": "1索", "2s": "2索", "3s": "3索", "4s": "4索", "5s": "5索",
    "6s": "6索", "7s": "7索", "8s": "8索", "9s": "9索",
    "1z": " 東 ", "2z": " 南 ", "3z": " 西 ", "4z": " 北 ",
    "5z": " 白 ", "6z": " 發 ", "7z": " 中 "
}

UNICODE_TILES = {
    "1m": "🀇", "2m": "🀈", "3m": "🀉", "4m": "🀊", "5m": "🀋",
    "6m": "🀌", "7m": "🀍", "8m": "🀎", "9m": "🀏",
    "1p": "🀙", "2p": "🀚", "3p": "🀛", "4p": "🀜", "5p": "🀝",
    "6p": "🀞", "7p": "🀟", "8p": "🀠", "9p": "🀡",
    "1s": "🀐", "2s": "🀑", "3s": "🀒", "4s": "🀓", "5s": "🀔",
    "6s": "🀕", "7s": "🀖", "8s": "🀗", "9s": "🀘",
    "1z": "🀀", "2z": "🀁", "3z": "🀂", "4z": "🀃",
    "5z": "🀆", "6z": "🀅", "7z": "🀄"
}


@dataclass(frozen=True)
class Tile:
    suit: str       # 'm', 'p', 's', 'z'
    value: int      # 1~9 (수패), 1~7 (자패)
    is_aka: bool = False  # 적도라 여부

    def __post_init__(self):
        if self.suit not in SUITS:
            raise ValueError(f"잘못된 suit: {self.suit}")
        if self.suit in ("m", "p", "s") and not (1 <= self.value <= 9):
            raise ValueError(f"수패 value 범위 오류: {self.value}")
        if self.suit == "z" and not (1 <= self.value <= 7):
            raise ValueError(f"자패 value 범위 오류: {self.value}")

    @classmethod
    def from_str(cls, code: str, is_aka: bool = False) -> Tile:
        """예: '1m', '5p', '7z' 형태의 문자열로 패 생성"""
        code = code.strip()
        val = int(code[:-1])
        st = code[-1].lower()
        return cls(suit=st, value=val, is_aka=is_aka)

    @property
    def code(self) -> str:
        """'1m', '5p', '1z' 형태"""
        return f"{self.value}{self.suit}"

    @property
    def name(self) -> str:
        """'一萬', '①筒', '東' 형태"""
        base = DISPLAY_NAMES.get(self.code, self.code)
        if self.is_aka:
            return f"赤{base}"
        return base

    @property
    def unicode(self) -> str:
        return UNICODE_TILES.get(self.code, self.code)

    def is_terminal(self) -> bool:
        """노두패(1, 9 수패)인지 여부"""
        return self.suit in ("m", "p", "s") and self.value in (1, 9)

    def is_honor(self) -> bool:
        """자패인지 여부"""
        return self.suit == "z"

    def is_terminal_or_honor(self) -> bool:
        """요구패(1, 9, 자패)인지 여부"""
        return self.is_terminal() or self.is_honor()

    def is_simple(self) -> bool:
        """중장패(2~8 수패)인지 여부"""
        return self.suit in ("m", "p", "s") and 2 <= self.value <= 8

    def __str__(self) -> str:
        return f"[{self.name}]"

    def __repr__(self) -> str:
        aka_mark = "*" if self.is_aka else ""
        return f"{self.code}{aka_mark}"

    def __lt__(self, other: Tile) -> bool:
        suit_order = {"m": 0, "p": 1, "s": 2, "z": 3}
        if suit_order[self.suit] != suit_order[other.suit]:
            return suit_order[self.suit] < suit_order[other.suit]
        if self.value != other.value:
            return self.value < other.value
        # 적패는 일반 패 뒤로
        return (not self.is_aka) and other.is_aka

    def matches(self, other: Tile, ignore_aka: bool = True) -> bool:
        """패 종류가 같은지 판정 (적패 여부 무시 가능)"""
        if ignore_aka:
            return self.suit == other.suit and self.value == other.value
        return self == other


@dataclass
class Meld:
    """울기(후로) 표현 객체: 치, 퐁, 깡"""
    meld_type: str        # 'chi', 'pon', 'daiminkan', 'ankan', 'kakan'
    tiles: List[Tile]     # 멘츠를 구성하는 패 리스트
    target_tile: Optional[Tile] = None  # 주워온 패 (암깡의 경우 None)

    @property
    def is_kan(self) -> bool:
        return self.meld_type in ("daiminkan", "ankan", "kakan")

    def __str__(self) -> str:
        type_names = {
            "chi": "치",
            "pon": "퐁",
            "daiminkan": "대명깡",
            "ankan": "암깡",
            "kakan": "가깡"
        }
        tiles_str = "".join(str(t) for t in self.tiles)
        return f"<{type_names.get(self.meld_type, self.meld_type)}: {tiles_str}>"


class Hand:
    """
    손패 컬렉션
    - concealed_tiles: 손 안에 감춰둔 패 (보통 13장, 쯔모 후 14장 등)
    - melds: 울어서 공개된 멘츠 목록
    """
    def __init__(self, tiles: Optional[List[Tile]] = None, melds: Optional[List[Meld]] = None):
        self.concealed_tiles: List[Tile] = list(tiles) if tiles else []
        self.melds: List[Meld] = list(melds) if melds else []

    def add(self, tile: Tile) -> None:
        """패 1장 추가"""
        self.concealed_tiles.append(tile)

    def remove(self, tile: Tile) -> bool:
        """
        손패에서 특정 패 1장 제거 (적패 매칭 우선순위 고려)
        제거 성공 시 True, 없으면 False 반환
        """
        # 정확히 일치하는 인스턴스/적패 여부 먼저 찾기
        for i, t in enumerate(self.concealed_tiles):
            if t is tile:
                self.concealed_tiles.pop(i)
                return True
        for i, t in enumerate(self.concealed_tiles):
            if t == tile:
                self.concealed_tiles.pop(i)
                return True
        # 적패 여부 무시하고 같은 패 찾기
        for i, t in enumerate(self.concealed_tiles):
            if t.matches(tile):
                self.concealed_tiles.pop(i)
                return True
        return False

    def count(self, tile: Tile, ignore_aka: bool = True) -> int:
        """손패(concealed) 내에 해당 패가 몇 장 있는지 계산"""
        if ignore_aka:
            return sum(1 for t in self.concealed_tiles if t.matches(tile))
        return self.concealed_tiles.count(tile)

    def sorted_tiles(self) -> List[Tile]:
        """정렬된 concealed 패 반환 (기존 손패 자체를 정렬)"""
        self.concealed_tiles.sort()
        return list(self.concealed_tiles)

    @property
    def is_menzen(self) -> bool:
        """문전(멘젠) 상태인지 여부 (암깡은 문전 유지, 치/퐁/명깡/가깡은 울기 상태)"""
        for m in self.melds:
            if m.meld_type != "ankan":
                return False
        return True

    @property
    def all_tiles(self) -> List[Tile]:
        """손 안의 패 + 울기 패 전체"""
        res = list(self.concealed_tiles)
        for m in self.melds:
            res.extend(m.tiles)
        return res

    def clone(self) -> Hand:
        """손패 복제"""
        return Hand(
            tiles=list(self.concealed_tiles),
            melds=[Meld(m.meld_type, list(m.tiles), m.target_tile) for m in self.melds]
        )

    def __len__(self) -> int:
        return len(self.concealed_tiles) + sum(len(m.tiles) for m in self.melds)

    def __str__(self) -> str:
        sorted_c = sorted(self.concealed_tiles)
        c_str = "".join(str(t) for t in sorted_c)
        if not self.melds:
            return c_str
        m_str = " ".join(str(m) for m in self.melds)
        return f"{c_str} | {m_str}"


class Wall:
    """
    패 산 (Wall)
    - 기본 136패(각 패 4장씩, 5m, 5p, 5s 각 1장 적도라 지원)
    - 왕패 14장 보존 (영상패 4장 포함)
    """
    def __init__(self, include_aka: bool = True, seed: Optional[int] = None):
        self.tiles: List[Tile] = []
        self.dead_wall: List[Tile] = []    # 왕패 14장
        self.rinshan_tiles: List[Tile] = [] # 영상패 (최대 4장)
        self.dora_indicators: List[Tile] = []
        self.include_aka = include_aka
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        """패 산 새로 섞고 초기화"""
        all_tiles: List[Tile] = []

        for suit in ("m", "p", "s"):
            for val in range(1, 10):
                for copy in range(4):
                    is_aka = (self.include_aka and val == 5 and copy == 0)
                    all_tiles.append(Tile(suit=suit, value=val, is_aka=is_aka))

        for val in range(1, 8):
            for _ in range(4):
                all_tiles.append(Tile(suit="z", value=val))

        self.rng.shuffle(all_tiles)

        # 왕패 14장 분리 (끝 14장)
        self.dead_wall = all_tiles[-14:]
        self.rinshan_tiles = self.dead_wall[:4]  # 영상패 4장
        self.dora_indicators = [self.dead_wall[4]] # 도라 표시패 기본 1장
        self.tiles = all_tiles[:-14]             # 쯔모 가능한 순수 패산 (122장)

    def draw(self) -> Optional[Tile]:
        """일반 쯔모: 패산 앞에서 1장 뽑기"""
        if not self.tiles:
            return None
        return self.tiles.pop(0)

    def draw_rinshan(self) -> Optional[Tile]:
        """깡 발생 시 영상패 뽑기"""
        if not self.rinshan_tiles or not self.tiles:
            return None
        tile = self.rinshan_tiles.pop(0)
        self.dead_wall.remove(tile)
        # 패산의 맨 마지막 패를 왕패로 보충하여 왕패 14장 유지
        if self.tiles:
            self.dead_wall.append(self.tiles.pop())
        return tile

    def remaining(self) -> int:
        """남은 패 산(쯔모 가능한 패) 수"""
        return len(self.tiles)


@dataclass
class DiscardItem:
    tile: Tile
    is_tsumogiri: bool = False
    is_riichi: bool = False
    is_called: bool = False


class DiscardRecord:
    """
    각 플레이어의 버림패 기록 (후리텐 판정에 필수)
    """
    def __init__(self):
        self.history: List[DiscardItem] = []

    def add(self, tile: Tile, is_tsumogiri: bool = False, is_riichi: bool = False) -> None:
        self.history.append(DiscardItem(tile, is_tsumogiri, is_riichi))

    @property
    def tiles(self) -> List[Tile]:
        """버린 패들의 순수 Tile 목록"""
        return [item.tile for item in self.history]

    def has_tile(self, tile: Tile, ignore_aka: bool = True) -> bool:
        """이 플레이어가 버린 적이 있는 패인지 확인 (후리텐 판정용)"""
        for item in self.history:
            if item.tile.matches(tile, ignore_aka=ignore_aka):
                return True
        return False

    def __len__(self) -> int:
        return len(self.history)

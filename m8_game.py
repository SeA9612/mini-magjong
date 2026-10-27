"""
M8. 게임 상태 및 컨트롤러 모듈
책임: 턴 진행, 순서 관리, 울기/화료 이벤트 분기, 게임 루프 지원
의존성: M1 ~ M7
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

from m1_tile import Tile, Hand, Wall, DiscardRecord, Meld
from m2_winning import is_tenpai, get_waits
from m3_yaku import get_yaku, YakuContext, Yaku
from m4_meld import can_chi, can_pon, can_kan, apply_chi, apply_pon, apply_kan, after_kan_draw
from m5_riichi import RiichiState, can_riichi, can_declare_riichi_with_discard, declare_riichi, is_locked, can_ankan_after_riichi
from m6_win import can_ron, can_tsumo, is_furiten, resolve_priority
from m7_ai import choose_discard as ai_choose_discard, choose_reaction as ai_choose_reaction, should_riichi as ai_should_riichi


@dataclass
class Player:
    id: int               # 0: 사용자(Player), 1: AI
    name: str             # "플레이어", "AI"
    is_human: bool        # True: 사람, False: AI
    hand: Hand = field(default_factory=Hand)
    discard_record: DiscardRecord = field(default_factory=DiscardRecord)
    riichi_state: RiichiState = field(default_factory=RiichiState)
    seat_wind: int = 1    # 1=동, 2=남
    score: int = 25000
    last_drawn_tile: Optional[Tile] = None
    temporary_furiten: bool = False
    riichi_furiten: bool = False

    def reset_for_new_round(self, seat_wind: int):
        self.hand = Hand()
        self.discard_record = DiscardRecord()
        self.riichi_state = RiichiState()
        self.seat_wind = seat_wind
        self.last_drawn_tile = None
        self.temporary_furiten = False
        self.riichi_furiten = False


class MahjongGame:
    """
    2인 리치마작 게임 컨트롤러
    """
    def __init__(self, human_starts_as_dealer: bool = True):
        self.round_wind: int = 1   # 1: 동장
        self.wall = Wall(include_aka=True)
        self.players = [
            Player(id=0, name="당신", is_human=True, seat_wind=1 if human_starts_as_dealer else 2),
            Player(id=1, name="AI봇", is_human=False, seat_wind=2 if human_starts_as_dealer else 1)
        ]
        self.current_turn: int = 0 if human_starts_as_dealer else 1
        self.turn_count: int = 0
        self.last_discard: Optional[Tile] = None
        self.last_discard_player: Optional[int] = None
        # 치/퐁 직후에는 쯔모 없이 타패만 해야 한다.
        self.pending_meld_discard: Optional[int] = None
        self.is_game_over: bool = False
        self.winner: Optional[Player] = None
        self.winning_type: Optional[str] = None  # "tsumo", "ron", "draw"
        self.winning_yaku: List[Yaku] = []
        self.winning_tile: Optional[Tile] = None

    def start_game(self):
        """패 배분 및 게임 시작 (각자 13장, 선 14장)"""
        self.pending_meld_discard = None
        self.is_game_over = False
        self.winner = None
        self.winning_type = None
        self.winning_yaku = []
        self.winning_tile = None
        self.last_discard = None
        self.last_discard_player = None
        self.wall.reset()
        for p in self.players:
            p.reset_for_new_round(p.seat_wind)

        # 13장씩 배패
        for _ in range(13):
            for p in self.players:
                p.hand.add(self.wall.draw())

        for p in self.players:
            p.hand.sorted_tiles()

        # 첫 선 플레이어 1장 쯔모 (14장)
        first_drawn = self.draw_tile(self.current_turn)
        self.turn_count = 1
        return first_drawn

    def draw_tile(self, player_idx: int) -> Optional[Tile]:
        """일반 쯔모와 마지막 쯔모패·동순 후리텐 상태를 함께 갱신한다."""
        p = self.players[player_idx]
        drawn = self.wall.draw()
        if drawn is not None:
            p.hand.add(drawn)
            p.last_drawn_tile = drawn
            p.temporary_furiten = False
        return drawn

    def pass_ron(self, player_idx: int):
        p = self.players[player_idx]
        p.temporary_furiten = True
        if p.riichi_state.is_riichi:
            p.riichi_furiten = True

    def get_player(self, idx: int) -> Player:
        return self.players[idx]

    def get_opponent(self, idx: int) -> Player:
        return self.players[1 - idx]

    def create_yaku_context(self, player_idx: int, is_tsumo: bool, win_tile: Optional[Tile]) -> YakuContext:
        p = self.players[player_idx]
        return YakuContext(
            is_riichi=p.riichi_state.is_riichi,
            is_tsumo=is_tsumo,
            round_wind=self.round_wind,
            seat_wind=p.seat_wind,
            win_tile=win_tile
        )

    # --- 턴 내 플레이어 가능 액션 조사 ---
    def get_turn_actions(self, player_idx: int, drawn_tile: Optional[Tile]) -> Dict[str, Any]:
        """
        패를 뽑은 후(14장 상태) 취할 수 있는 액션 목록:
        - 쯔모 화료 (tsumo)
        - 리치 (riichi)
        - 암깡 / 가깡 (kan)
        """
        p = self.players[player_idx]
        actions = {"can_tsumo": False, "can_riichi": False, "kans": []}
        if self.pending_meld_discard == player_idx:
            return actions

        ctx = self.create_yaku_context(player_idx, is_tsumo=True, win_tile=drawn_tile)
        if drawn_tile is not None and can_tsumo(p.hand, ctx):
            actions["can_tsumo"] = True

        if can_riichi(p.hand, p.riichi_state, self.wall, p.score):
            actions["can_riichi"] = True

        kans = can_kan(p.hand, tile=drawn_tile, is_turn=True) if self.wall.tiles and self.wall.rinshan_tiles else []
        # 리치 후 암깡인 경우 대기패 불변 규칙 체크
        valid_kans = []
        for kan_type, tile in kans:
            if p.riichi_state.is_riichi:
                if kan_type == "ankan" and drawn_tile is not None and tile.matches(drawn_tile) and can_ankan_after_riichi(p.hand, tile):
                    valid_kans.append((kan_type, tile))
            else:
                valid_kans.append((kan_type, tile))
        actions["kans"] = valid_kans

        return actions

    # --- 상대 버림패에 대한 반응 액션 조사 ---
    def get_reaction_actions(self, respondent_idx: int, discarded_tile: Tile) -> List[Dict[str, Any]]:
        """
        상대방이 버린 패에 대해 취할 수 있는 반응 목록:
        - 론 화료 (ron)
        - 치 (chi) - 2인 마작에서는 상대방이 항상 상가
        - 퐁 (pon)
        - 대명깡 (kan: daiminkan)
        """
        p = self.players[respondent_idx]
        actions = []

        # 1. 론
        ctx = self.create_yaku_context(respondent_idx, is_tsumo=False, win_tile=discarded_tile)
        if not (p.temporary_furiten or p.riichi_furiten) and can_ron(p.hand, discarded_tile, p.discard_record, ctx):
            actions.append({"type": "ron", "tile": discarded_tile})

        # 리치 상태라면 론 이외의 울기는 불가
        if is_locked(p.riichi_state):
            return actions

        # 2. 대명깡
        kans = can_kan(p.hand, tile=discarded_tile, is_turn=False) if self.wall.tiles and self.wall.rinshan_tiles else []
        for kan_type, t in kans:
            actions.append({"type": "kan", "kan_type": kan_type, "tile": t})

        # 3. 퐁
        if can_pon(p.hand, discarded_tile):
            actions.append({"type": "pon", "tile": discarded_tile})

        # 4. 치
        chis = can_chi(p.hand, discarded_tile, seat_relation="kamicha")
        for c in chis:
            actions.append({"type": "chi", "tile": discarded_tile, "partner": c})

        return actions

    # --- 액션 실행 처리부 ---
    def execute_tsumo(self, player_idx: int, drawn_tile: Optional[Tile]) -> bool:
        p = self.players[player_idx]
        ctx = self.create_yaku_context(player_idx, is_tsumo=True, win_tile=drawn_tile)
        if self.is_game_over or self.current_turn != player_idx or self.pending_meld_discard is not None or not can_tsumo(p.hand, ctx):
            return False
        self.winning_yaku = get_yaku(p.hand, ctx)
        self.winner = p
        self.winning_type = "tsumo"
        self.winning_tile = drawn_tile
        self.is_game_over = True
        return True

    def execute_ron(self, winner_idx: int, win_tile: Tile) -> bool:
        p = self.players[winner_idx]
        ctx = self.create_yaku_context(winner_idx, is_tsumo=False, win_tile=win_tile)
        if (self.is_game_over or self.last_discard_player != 1 - winner_idx or
            self.last_discard != win_tile or p.temporary_furiten or p.riichi_furiten or
            not can_ron(p.hand, win_tile, p.discard_record, ctx)):
            return False
        self.winning_yaku = get_yaku(p.hand, ctx)
        self.winner = p
        self.winning_type = "ron"
        self.winning_tile = win_tile
        self.is_game_over = True
        return True

    def execute_discard(self, player_idx: int, tile: Tile, declare_riichi_now: bool = False) -> bool:
        p = self.players[player_idx]
        if tile not in p.hand.concealed_tiles:
            return False
        # 실패 시 손패, 버림패, 점수를 변경하지 않는다.
        if declare_riichi_now and (
            self.pending_meld_discard == player_idx or
            not can_declare_riichi_with_discard(p.hand, p.riichi_state, tile, self.wall, p.score)
        ):
            return False
        p.hand.remove(tile)
        is_tsumo = (tile is p.last_drawn_tile)
        p.last_drawn_tile = None
        p.discard_record.add(tile, is_tsumogiri=is_tsumo, is_riichi=declare_riichi_now)

        if declare_riichi_now:
            declare_riichi(p.riichi_state, self.turn_count, tile)
            p.score -= 1000

        self.last_discard = tile
        self.last_discard_player = player_idx
        self.turn_count += 1
        if self.pending_meld_discard == player_idx:
            self.pending_meld_discard = None
        p.hand.sorted_tiles()
        return True

    def execute_meld(self, player_idx: int, action: Dict[str, Any]) -> Optional[Tile]:
        """
        치, 퐁, 깡 실행.
        깡인 경우 영상패를 뽑아서 반환.
        """
        p = self.players[player_idx]
        act_type = action["type"]
        tile = action["tile"]
        if act_type == "kan" and (not self.wall.tiles or not self.wall.rinshan_tiles):
            raise ValueError("영상패 또는 일반 패산이 없어 깡할 수 없습니다.")

        if act_type in ("chi", "pon") or (act_type == "kan" and action.get("kan_type") == "daiminkan"):
            opponent = self.players[1 - player_idx]
            if opponent.discard_record.history and opponent.discard_record.history[-1].tile == tile:
                opponent.discard_record.history[-1].is_called = True
        p.last_drawn_tile = None

        if act_type == "chi":
            apply_chi(p.hand, tile, action["partner"])
            self.current_turn = player_idx
            self.pending_meld_discard = player_idx
            return None

        elif act_type == "pon":
            apply_pon(p.hand, tile)
            self.current_turn = player_idx
            self.pending_meld_discard = player_idx
            return None

        elif act_type == "kan":
            kan_type = action["kan_type"]
            apply_kan(p.hand, tile, kan_type)
            # 영상패 보충
            rinshan = after_kan_draw(self.wall, p.hand)
            p.last_drawn_tile = rinshan
            p.temporary_furiten = False
            self.current_turn = player_idx
            return rinshan

        return None

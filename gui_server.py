"""
리치마작 웹 GUI 로컬 백엔드 서버
Python 표준 라이브러리(http.server, json, webbrowser)만 사용하여
외부 패키지 설치 없이 즉시 실행됩니다.
"""

from __future__ import annotations
import json
import os
import re
import secrets
import sys
import time
import webbrowser
import threading
import socket
import hashlib
import urllib.request
import uuid
from http.cookies import SimpleCookie
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Dict, Any

from m1_tile import Tile, Hand, Meld
from m2_winning import is_tenpai, get_waits
from m3_yaku import YakuContext, get_yaku
from m5_riichi import is_locked
from m6_win import is_furiten, can_tsumo
from m7_ai import choose_discard as ai_choose_discard, choose_reaction as ai_choose_reaction, should_riichi as ai_should_riichi
from m8_game import MahjongGame


def source_fingerprint():
    """실행 당시 코드 버전. 디스크의 파일이 바뀌어도 실행 중인 값은 유지한다."""
    base = os.path.dirname(os.path.abspath(__file__))
    digest = hashlib.sha256()
    for name in ("mazak.py", "gui_server.py", "m1_tile.py", "m2_winning.py", "m3_yaku.py", "m4_meld.py",
                 "m5_riichi.py", "m6_win.py", "m7_ai.py", "m8_game.py", "web/app.js", "web/index.html", "web/style.css"):
        with open(os.path.join(base, name), "rb") as source:
            digest.update(name.encode("utf-8"))
            digest.update(source.read())
    return digest.hexdigest()


RUNNING_SOURCE_VERSION = source_fingerprint()

DIFFICULTY_TARGET_YAKU = {
    "low": frozenset(("리치", "핑후")),
    "medium": frozenset(("리치", "핑후", "탕야오", "치토이츠")),
    "high": frozenset(("리치", "문전청자모", "핑후", "탕야오", "역패(백)", "역패(발)",
                         "역패(중)", "역패(장풍)", "역패(자풍)", "치토이츠", "또이또이"))
}


def ai_yaku_goal_met(yaku_list, difficulty):
    """선택 난이도에서 허용한 AI 목표 역이 하나 이상 성립하는지 판정한다."""
    allowed = DIFFICULTY_TARGET_YAKU.get(difficulty, DIFFICULTY_TARGET_YAKU["medium"])
    return any(yaku.name in allowed for yaku in yaku_list)


def ai_open_call_matches_goal(action, difficulty, round_wind, seat_wind):
    """AI가 멘젠 전용 목표를 스스로 깨는 울기를 하지 않도록 제한한다."""
    action_type = action.get("type")
    if action_type not in ("chi", "pon", "kan"):
        return True
    if action_type == "kan" and action.get("kan_type") == "ankan":
        return True
    tile = action.get("tile")
    if tile is None or not tile.is_honor():
        return False
    allowed = DIFFICULTY_TARGET_YAKU.get(difficulty, DIFFICULTY_TARGET_YAKU["medium"])
    possible_yakuhai = set()
    if tile.value == 5:
        possible_yakuhai.add("역패(백)")
    elif tile.value == 6:
        possible_yakuhai.add("역패(발)")
    elif tile.value == 7:
        possible_yakuhai.add("역패(중)")
    if tile.value == round_wind:
        possible_yakuhai.add("역패(장풍)")
    if tile.value == seat_wind:
        possible_yakuhai.add("역패(자풍)")
    return bool(possible_yakuhai & allowed)


def compatible_server_running(port):
    """다른 앱이나 구버전 게임을 최신 서버로 오인하지 않는다."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            health = json.loads(response.read(4096))
        return (isinstance(health, dict) and health.get("service") == "riichi-mahjong"
                and health.get("source_version") == RUNNING_SOURCE_VERSION)
    except (OSError, ValueError) as error:
        if hasattr(error, "close"):
            error.close()
        return False


def tile_to_dict(tile: Optional[Tile]) -> Optional[Dict[str, Any]]:
    if tile is None:
        return None
    return {
        "code": tile.code,
        "suit": tile.suit,
        "value": tile.value,
        "name": tile.name,
        "is_aka": tile.is_aka
    }


def meld_to_dict(meld: Meld) -> Dict[str, Any]:
    return {
        "meld_type": meld.meld_type,
        "tiles": [tile_to_dict(t) for t in meld.tiles]
    }


def serialize_reaction_action(act: Dict[str, Any], index: int) -> Dict[str, Any]:
    """클라이언트로 보낼 반응 액션 딕셔너리 직렬화"""
    res = {
        "index": index,
        "type": act.get("type", "pass"),
        "tile": tile_to_dict(act.get("tile"))
    }
    if "kan_type" in act:
        res["kan_type"] = act["kan_type"]
    if "partner" in act:
        res["partner"] = [tile_to_dict(t) for t in act["partner"]]
    return res


def json_serial_fallback(obj):
    """JSON 인코더 fallback 함수: 혹시 남아있는 Tile이나 Meld를 안전하게 변환"""
    if isinstance(obj, Tile):
        return tile_to_dict(obj)
    if isinstance(obj, Meld):
        return meld_to_dict(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class WebMahjongSession:
    """웹 세션용 게임 래퍼"""
    def __init__(self):
        self.lock = threading.RLock()
        self.revision = 0
        self.game = MahjongGame(human_starts_as_dealer=True)
        self.pending_reaction: Optional[Dict[str, Any]] = None
        self.current_drawn_tile: Optional[Tile] = None
        self.last_message: str = "게임을 시작합니다. 원하시는 패를 클릭하여 타패하세요."
        self.game_id = ""
        self.difficulty = "medium"
        self.start_new_game()

    def start_new_game(self):
        self.game = MahjongGame(human_starts_as_dealer=True)
        self.game_id = uuid.uuid4().hex
        self.current_drawn_tile = self.game.start_game()
        self.pending_reaction = None
        self.last_message = "대국이 시작되었습니다. 당신(동가)의 첫 턴입니다."

    def build_state(self) -> Dict[str, Any]:
        human = self.game.players[0]
        ai = self.game.players[1]
        drawn_index = None
        if self.game.current_turn == 0 and self.current_drawn_tile is not None:
            drawn_index = next((i for i, tile in enumerate(human.hand.concealed_tiles) if tile is self.current_drawn_tile), None)
            if drawn_index is None:
                drawn_index = next((i for i in reversed(range(len(human.hand.concealed_tiles))) if human.hand.concealed_tiles[i] == self.current_drawn_tile), None)

        # 텐파이 및 대기패 계산 (14장 쯔모 상태 지원)
        if len(human.hand.concealed_tiles) % 3 == 2 and self.current_drawn_tile:
            test_h = human.hand.clone()
            test_h.remove(self.current_drawn_tile)
            human_waits = get_waits(test_h)
        else:
            human_waits = get_waits(human.hand)

        human_furiten = human.temporary_furiten or human.riichi_furiten or is_furiten(human_waits, human.discard_record)

        # 플레이어 턴 액션
        turn_actions = {}
        if self.game.current_turn == 0 and not self.game.is_game_over:
            raw_actions = self.game.get_turn_actions(0, self.current_drawn_tile)
            from m5_riichi import get_riichi_discard_candidates
            candidates = get_riichi_discard_candidates(human.hand) if raw_actions["can_riichi"] else []
            riichi_reason = ""
            if not raw_actions["can_riichi"] and not human.riichi_state.is_riichi:
                if not human.hand.is_menzen:
                    riichi_reason = "치·퐁·명깡한 손패는 리치할 수 없습니다."
                elif human.score < 1000:
                    riichi_reason = "리치하려면 1,000점 이상 필요합니다."
                elif self.game.wall.remaining() < 4:
                    riichi_reason = "남은 패산이 4장 미만이면 리치할 수 없습니다."
                elif self.game.pending_meld_discard == 0 or self.current_drawn_tile is None:
                    riichi_reason = "패를 뽑은 자신의 턴에 리치할 수 있습니다."
                else:
                    riichi_reason = "어느 패를 버려도 텐파이가 되지 않아 아직 리치할 수 없습니다."
            turn_actions = {
                "can_tsumo": raw_actions["can_tsumo"],
                "can_riichi": raw_actions["can_riichi"],
                "riichi_candidates": [tile_to_dict(c) for c in candidates],
                "riichi_unavailable_reason": riichi_reason,
                "kans": [
                    {"kan_type": k_type, "tile": tile_to_dict(k_tile)}
                    for k_type, k_tile in raw_actions["kans"]
                ]
            }

        # 플레이어별 직렬화
        human_data = {
            "id": human.id,
            "name": human.name,
            "seat_wind": human.seat_wind,
            "is_riichi": human.riichi_state.is_riichi,
            "concealed_tiles": [tile_to_dict(t) for t in human.hand.concealed_tiles],
            "melds": [meld_to_dict(m) for m in human.hand.melds],
            "discards": [
                {"tile": tile_to_dict(item.tile), "is_riichi": item.is_riichi, "is_tsumogiri": item.is_tsumogiri}
                for item in human.discard_record.history if not item.is_called
            ]
        }

        ai_data = {
            "id": ai.id,
            "name": ai.name,
            "seat_wind": ai.seat_wind,
            "is_riichi": ai.riichi_state.is_riichi,
            "concealed_count": len(ai.hand.concealed_tiles),
            "melds": [meld_to_dict(m) for m in ai.hand.melds],
            "discards": [
                {"tile": tile_to_dict(item.tile), "is_riichi": item.is_riichi, "is_tsumogiri": item.is_tsumogiri}
                for item in ai.discard_record.history if not item.is_called
            ]
        }
        if self.game.is_game_over and self.game.winner is ai:
            ai_data["concealed_tiles"] = [tile_to_dict(t) for t in ai.hand.concealed_tiles]

        winning_hand = []
        winning_melds = []
        if self.game.winner:
            winning_hand = list(self.game.winner.hand.concealed_tiles)
            if self.game.winning_type == "ron":
                winning_hand.append(self.game.winning_tile)
            winning_hand.sort()
            winning_melds = [meld_to_dict(m) for m in self.game.winner.hand.melds]

        # 대기 반응 직렬화
        reaction_data = None
        if self.pending_reaction:
            reaction_data = {
                "player_idx": self.pending_reaction["player_idx"],
                "target_tile": tile_to_dict(self.pending_reaction["target_tile"]),
                "actions": [
                    serialize_reaction_action(a, i)
                    for i, a in enumerate(self.pending_reaction["actions"])
                ]
            }

        return {
            "game_id": self.game_id,
            "difficulty": self.difficulty,
            "difficulty_target_yaku": sorted(DIFFICULTY_TARGET_YAKU[self.difficulty]),
            "can_change_difficulty": (self.game.turn_count <= 1 and not any(
                player.discard_record.history for player in self.game.players
            ) and not self.game.is_game_over),
            "revision": self.revision,
            "wall_remaining": self.game.wall.remaining(),
            "round_wind": self.game.round_wind,
            "dora_indicator": tile_to_dict(self.game.wall.dora_indicators[0]) if self.game.wall.dora_indicators else None,
            "current_turn": self.game.current_turn,
            "current_drawn_tile": tile_to_dict(self.current_drawn_tile) if self.game.current_turn == 0 else None,
            "current_drawn_index": drawn_index,
            "must_discard_after_call": self.game.pending_meld_discard == 0,
            "is_game_over": self.game.is_game_over,
            "winning_type": self.game.winning_type,
            "winner": self.game.winner.id if self.game.winner else None,
            "winning_tile": tile_to_dict(self.game.winning_tile),
            "winning_hand": [tile_to_dict(t) for t in winning_hand],
            "winning_melds": winning_melds,
            "winning_yaku": [{"name": y.name, "romaji": y.romaji} for y in self.game.winning_yaku],
            "players": [human_data, ai_data],
            "human_waits": [tile_to_dict(w) for w in human_waits],
            "is_human_furiten": human_furiten,
            "human_turn_actions": turn_actions,
            "pending_reaction": reaction_data,
            "last_message": self.last_message
        }

    def handle_action(self, req: Dict[str, Any]) -> Dict[str, Any]:
        # 스레드 간 상태 변경을 직렬화하고 오래된 화면에서 보낸 중복 요청을 거절한다.
        with self.lock:
            if not isinstance(req, dict):
                return self.build_state()
            if "revision" in req and (type(req["revision"]) is not int or req["revision"] != self.revision):
                return self.build_state()
            state = self._handle_action(req)
            self.revision += 1
            state["revision"] = self.revision
            return state

    def _handle_action(self, req: Dict[str, Any]) -> Dict[str, Any]:
        act = req.get("action")
        human = self.game.players[0]
        ai = self.game.players[1]

        if act == "restart":
            self.start_new_game()
            return self.build_state()

        if act == "set_difficulty":
            requested = req.get("difficulty")
            can_change = (self.game.turn_count <= 1 and not any(
                player.discard_record.history for player in self.game.players
            ) and not self.game.is_game_over)
            if can_change and isinstance(requested, str) and requested in DIFFICULTY_TARGET_YAKU:
                self.difficulty = requested
                self.last_message = f"난이도를 {'하' if requested == 'low' else '중' if requested == 'medium' else '상'}로 설정했습니다."
            return self.build_state()

        if self.game.is_game_over:
            return self.build_state()

        # 치/퐁 직후의 턴은 타패로만 끝낼 수 있다.
        if self.game.pending_meld_discard == 0 and act in ("tsumo", "kan"):
            return self.build_state()

        # 1. 플레이어 타패
        if act == "discard":
            if self.game.current_turn != 0 or self.pending_reaction:
                return self.build_state()
            idx = req.get("index", 0)
            riichi_decl = req.get("riichi", False)

            if type(idx) is not int or type(riichi_decl) is not bool:
                return self.build_state()
            if len(human.hand.concealed_tiles) != 14 - 3 * len(human.hand.melds):
                return self.build_state()

            if 0 <= idx < len(human.hand.concealed_tiles):
                tile = human.hand.concealed_tiles[idx]
                if is_locked(human.riichi_state) and tile != self.current_drawn_tile:
                    self.last_message = "리치 후에는 방금 뽑은 패만 버릴 수 있습니다."
                    return self.build_state()
                if not self.game.execute_discard(0, tile, declare_riichi_now=riichi_decl):
                    self.last_message = "리치할 수 없습니다. 텐파이가 유지되는 후보 패를 선택하세요."
                    return self.build_state()
                self.current_drawn_tile = None
                self.last_message = f"당신이 {tile.name}({tile.code})을(를) 버렸습니다."

                # AI 반응 조사
                ai_reactions = self.game.get_reaction_actions(1, tile)
                ai_reactions = [action for action in ai_reactions
                                if ai_open_call_matches_goal(action, self.difficulty,
                                                             self.game.round_wind, ai.seat_wind)]
                ron_context = self.game.create_yaku_context(1, False, tile)
                if any(action.get("type") == "ron" for action in ai_reactions):
                    if not ai_yaku_goal_met(get_yaku(ai.hand, ron_context), self.difficulty):
                        ai_reactions = [action for action in ai_reactions if action.get("type") != "ron"]
                if ai_reactions:
                    chosen = ai_choose_reaction(ai_reactions, ai.hand, ron_context)
                    if chosen.get("type") == "ron":
                        if self.game.execute_ron(1, tile):
                            self.last_message = f"상대 AI가 {tile.name}(으)로 론 화료했습니다!"
                            return self.build_state()
                    elif chosen.get("type") in ("pon", "chi", "kan"):
                        rinshan = self.game.execute_meld(1, chosen)
                        self.game.current_turn = 1
                        self.current_drawn_tile = rinshan
                        self.last_message = f"상대 AI가 {chosen['type']}을 선언했습니다!"
                        return self.build_state()

                    if any(a["type"] == "ron" for a in ai_reactions):
                        self.game.pass_ron(1)

                # 다음 턴(AI)으로
                self.game.current_turn = 1

        # 2. 플레이어 쯔모 화료
        elif act == "tsumo":
            if self.game.current_turn == 0 and not self.pending_reaction and self.game.execute_tsumo(0, self.current_drawn_tile):
                self.last_message = "축하합니다! 쯔모 화료하셨습니다!"
            else:
                self.last_message = "현재 쯔모 화료할 수 없습니다."

        # 3. 플레이어 깡 (암깡/가깡)
        elif act == "kan":
            if self.game.current_turn != 0 or self.pending_reaction or self.current_drawn_tile is None:
                return self.build_state()
            raw_actions = self.game.get_turn_actions(0, self.current_drawn_tile)
            if raw_actions["kans"]:
                kan_index = req.get("kan_index", 0)
                if type(kan_index) is not int or not 0 <= kan_index < len(raw_actions["kans"]):
                    return self.build_state()
                k_type, k_tile = raw_actions["kans"][kan_index]
                rinshan = self.game.execute_meld(0, {"type": "kan", "kan_type": k_type, "tile": k_tile})
                self.current_drawn_tile = rinshan
                self.last_message = f"{k_type} 깡을 실행하고 영상패를 뽑았습니다."

        # 4. 상대 버림패에 대한 플레이어 반응
        elif act == "reaction":
            if not self.pending_reaction:
                return self.build_state()
            choice = req.get("choice", {})
            if not isinstance(choice, dict):
                return self.build_state()
            c_type = choice.get("type", "pass")
            action_idx = choice.get("index", req.get("action_index", None))
            
            target_tile = self.pending_reaction["target_tile"] if self.pending_reaction else None
            saved_actions = self.pending_reaction["actions"] if self.pending_reaction else []

            if c_type == "ron" and target_tile is not None:
                if any(a["type"] == "ron" for a in saved_actions) and self.game.execute_ron(0, target_tile):
                    self.pending_reaction = None
                    self.last_message = "축하합니다! 론(Ron) 화료하셨습니다!"
            elif c_type in ("pon", "chi", "kan") and target_tile is not None:
                # 원본 액션 객체 찾기 (Tile 객체 보존된 버전)
                original_action = None
                if action_idx is not None:
                    if type(action_idx) is not int or not 0 <= action_idx < len(saved_actions):
                        return self.build_state()
                    if saved_actions[action_idx].get("type") != c_type:
                        return self.build_state()
                    original_action = saved_actions[action_idx]
                else:
                    for a in saved_actions:
                        if a.get("type") == c_type:
                            original_action = a
                            break

                if original_action and original_action in self.game.get_reaction_actions(0, target_tile):
                    if any(a["type"] == "ron" for a in saved_actions):
                        self.game.pass_ron(0)
                    self.pending_reaction = None
                    rinshan = self.game.execute_meld(0, original_action)
                    self.game.current_turn = 0
                    self.current_drawn_tile = rinshan
                    self.last_message = (
                        f"{c_type}을(를) 실행했습니다. 패를 뽑지 않고 손패에서 한 장을 버리세요."
                        if c_type in ("chi", "pon") else f"{c_type}을(를) 실행했습니다."
                    )
                else:
                    self.last_message = f"{c_type} 실행에 실패했습니다."
            elif c_type == "pass":
                if any(a["type"] == "ron" for a in saved_actions):
                    self.game.pass_ron(0)
                self.pending_reaction = None
                # 패스: 플레이어 턴으로 넘어가며 쯔모 진행
                self.game.current_turn = 0
                if self.game.wall.remaining() > 0:
                    self.current_drawn_tile = self.game.draw_tile(0)
                    self.last_message = "상대 버림패를 패스하고 패를 뽑았습니다."
                else:
                    self.game.is_game_over = True
                    self.game.winning_type = "draw"

        # 5. AI 단계 진행 (ai_step)
        elif act == "ai_step" and self.game.current_turn == 1 and not self.pending_reaction:
            # 패 뽑기
            if self.current_drawn_tile is None and self.game.pending_meld_discard != 1:
                if self.game.wall.remaining() == 0:
                    self.game.is_game_over = True
                    self.game.winning_type = "draw"
                    self.last_message = "패산이 소진되어 유국되었습니다."
                    return self.build_state()
                self.current_drawn_tile = self.game.draw_tile(1)

            # AI 쯔모 체크
            ctx_tsumo = self.game.create_yaku_context(1, is_tsumo=True, win_tile=self.current_drawn_tile)
            if (self.current_drawn_tile is not None and can_tsumo(ai.hand, ctx_tsumo)
                    and ai_yaku_goal_met(get_yaku(ai.hand, ctx_tsumo), self.difficulty)):
                self.game.execute_tsumo(1, self.current_drawn_tile)
                self.last_message = "상대 AI가 쯔모 화료했습니다!"
                return self.build_state()

            # 타패를 먼저 정하고 실제 점수·잔여 패산·타패 후 텐파이로 리치를 검증한다.
            disc = ai_choose_discard(ai.hand, ctx_tsumo, ai.riichi_state, drawn_tile=self.current_drawn_tile)
            declare_riichi_ai = ai_should_riichi(
                ai.hand, ctx_tsumo, ai.riichi_state,
                score=ai.score, wall=self.game.wall, discard_tile=disc
            )
            self.game.execute_discard(1, disc, declare_riichi_now=declare_riichi_ai)
            self.current_drawn_tile = None
            riichi_text = " [리치!!]" if declare_riichi_ai else ""
            self.last_message = f"상대 AI가{riichi_text} {disc.name}({disc.code})을(를) 버렸습니다."

            # 플레이어 반응 기회 조사
            player_reactions = self.game.get_reaction_actions(0, disc)
            if player_reactions:
                self.pending_reaction = {
                    "player_idx": 0,
                    "target_tile": disc,
                    "actions": player_reactions
                }
            else:
                # 반응할 액션이 없으면 플레이어 턴으로 즉시 쯔모
                self.game.current_turn = 0
                if self.game.wall.remaining() > 0:
                    self.current_drawn_tile = self.game.draw_tile(0)
                else:
                    self.game.is_game_over = True
                    self.game.winning_type = "draw"

        return self.build_state()


WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
SESSION_COOKIE_NAME = "mahjong_session"
SESSION_TTL_SECONDS = 24 * 60 * 60
MAX_ACTIVE_SESSIONS = 512


class WebSessionStore:
    """Isolate each browser's match and expire abandoned in-memory sessions."""

    def __init__(self, session_factory=WebMahjongSession):
        self._session_factory = session_factory
        self._sessions = {}
        self._lock = threading.Lock()

    @staticmethod
    def _valid_id(session_id):
        return isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{40,50}", session_id) is not None

    def get_or_create(self, session_id=None):
        now = time.monotonic()
        with self._lock:
            expired = [key for key, entry in self._sessions.items() if now - entry[1] >= SESSION_TTL_SECONDS]
            for key in expired:
                del self._sessions[key]

            if self._valid_id(session_id) and session_id in self._sessions:
                session, _ = self._sessions[session_id]
                self._sessions[session_id] = (session, now)
                return session_id, session, False

            if len(self._sessions) >= MAX_ACTIVE_SESSIONS:
                oldest_id = min(self._sessions, key=lambda key: self._sessions[key][1])
                del self._sessions[oldest_id]

            new_id = secrets.token_urlsafe(32)
            while new_id in self._sessions:
                new_id = secrets.token_urlsafe(32)
            session = self._session_factory()
            self._sessions[new_id] = (session, now)
            return new_id, session, True


SESSION_STORE = WebSessionStore()


class MahjongHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 콘솔 로그 간소화
        pass

    def get_game_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            cookie = SimpleCookie()
        morsel = cookie.get(SESSION_COOKIE_NAME)
        incoming_id = morsel.value if morsel else None
        session_id, session, _ = SESSION_STORE.get_or_create(incoming_id)
        secure_setting = os.environ.get("COOKIE_SECURE", "").strip().lower()
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        secure = secure_setting in ("1", "true", "yes") or (
            secure_setting not in ("0", "false", "no") and forwarded_proto == "https"
        )
        suffix = "; Secure" if secure else ""
        self._new_session_cookie = (
            f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={SESSION_TTL_SECONDS}{suffix}"
        )
        return session

    def send_session_cookie(self):
        if self._new_session_cookie:
            self.send_header("Set-Cookie", self._new_session_cookie)

    def do_GET(self):
        url_path = self.path.split("?")[0]

        if url_path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"service": "riichi-mahjong", "source_version": RUNNING_SOURCE_VERSION}).encode("utf-8"))
            return

        if url_path == "/api/state":
            session = self.get_game_session()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_session_cookie()
            self.end_headers()
            with session.lock:
                state = session.build_state()
            self.wfile.write(json.dumps(state, ensure_ascii=False, default=json_serial_fallback).encode("utf-8"))
            return

        # 정적 파일 서빙
        if url_path in ("/", "/index.html"):
            filepath = os.path.join(WEB_DIR, "index.html")
            mime = "text/html; charset=utf-8"
        elif url_path == "/style.css":
            filepath = os.path.join(WEB_DIR, "style.css")
            mime = "text/css; charset=utf-8"
        elif url_path == "/app.js":
            filepath = os.path.join(WEB_DIR, "app.js")
            mime = "application/javascript; charset=utf-8"
        else:
            self.send_error(404, "File Not Found")
            return

        if os.path.exists(filepath):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        url_path = self.path.split("?")[0]
        if url_path == "/api/action":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if not 0 < content_length <= 65536:
                    raise ValueError("invalid length")
                post_body = self.rfile.read(content_length)
                data = json.loads(post_body.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("expected object")
            except (ValueError, UnicodeError):
                self.send_error(400, "Invalid JSON action")
                return

            session = self.get_game_session()
            new_state = session.handle_action(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_session_cookie()
            self.end_headers()
            self.wfile.write(json.dumps(new_state, ensure_ascii=False, default=json_serial_fallback).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Windows에서 같은 포트의 구버전·신버전 서버가 동시에 응답하지 않게 한다.
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def start_server(port: Optional[int] = None, open_browser: Optional[bool] = None, host: Optional[str] = None):
    hosted_port = os.environ.get("PORT")
    hosted_mode = hosted_port is not None
    if port is None:
        port = int(hosted_port or 8765)
    if host is None:
        host = os.environ.get("HOST") or ("0.0.0.0" if hosted_mode else "127.0.0.1")
    if open_browser is None:
        open_browser = not hosted_mode

    scan_ports = not hosted_mode and host in ("127.0.0.1", "localhost", "::1")
    candidates = range(port, min(port + 10, 65536)) if scan_ports else (port,)
    httpd = None
    for candidate in candidates:
        try:
            httpd = ThreadedHTTPServer((host, candidate), MahjongHTTPHandler)
            break
        except OSError as error:
            if error.errno not in (48, 98, 10013, 10048) and getattr(error, "winerror", None) not in (10013, 10048):
                raise
            if scan_ports and compatible_server_running(candidate):
                url = f"http://127.0.0.1:{candidate}"
                print(f"이미 실행 중인 게임을 엽니다: {url}")
                if open_browser and not webbrowser.open(url):
                    raise RuntimeError(f"브라우저를 자동으로 열지 못했습니다. 다음 주소를 직접 여세요: {url}")
                return url
            if not scan_ports:
                raise
            print(f"포트 {candidate}는 다른 서버가 사용 중입니다. 다음 포트에서 시작합니다.")
    if httpd is None:
        raise RuntimeError("사용 가능한 게임 포트를 찾지 못했습니다. 기존 게임 실행 창을 확인해 주세요.")
    url = f"http://127.0.0.1:{httpd.server_port}"
    print("=" * 60)
    print(f"🀄 리치마작 그래픽 웹 UI 서버가 시작되었습니다!")
    print(f"🌐 접속 주소: {url}" if scan_ports else f"🌐 대기 주소: {host}:{httpd.server_port}")
    print("종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 60)

    try:
        if open_browser and not webbrowser.open(url):
            raise RuntimeError(f"브라우저를 자동으로 열지 못했습니다. 다음 주소를 직접 여세요: {url}")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        httpd.server_close()
    return url


if __name__ == "__main__":
    start_server()

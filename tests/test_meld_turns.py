import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_server import WebMahjongSession
from m1_tile import Hand, Tile


def hand(codes):
    return Hand([Tile.from_str(c) for c in codes.split()])


class MeldTurnTests(unittest.TestCase):
    def session_for_call(self, player, kind):
        session = WebMahjongSession()
        target = Tile.from_str('5z' if kind == 'pon' else '3m')
        codes = ('5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p'
                 if kind == 'pon' else
                 '1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s')
        session.game.players[player].hand = hand(codes)
        actions = session.game.get_reaction_actions(player, target)
        action = next(a for a in actions if a['type'] == kind)
        return session, target, actions, action

    def test_human_chi_and_pon_require_discard_without_draw(self):
        for kind in ('chi', 'pon'):
            with self.subTest(kind=kind):
                s, target, actions, action = self.session_for_call(0, kind)
                s.game.current_turn = 1
                s.current_drawn_tile = None
                s.pending_reaction = {'player_idx': 0, 'target_tile': target, 'actions': actions}
                wall_before = s.game.wall.remaining()
                with patch.object(s.game.wall, 'draw', wraps=s.game.wall.draw) as draw:
                    state = s.handle_action({'action': 'reaction', 'choice': {
                        'type': kind, 'index': actions.index(action)}})
                    draw.assert_not_called()
                self.assertEqual(len(s.game.players[0].hand.concealed_tiles), 11)
                self.assertEqual(s.game.wall.remaining(), wall_before)
                self.assertTrue(state['must_discard_after_call'])
                self.assertIsNone(state['current_drawn_tile'])
                self.assertFalse(state['human_turn_actions']['can_tsumo'])
                self.assertEqual(state['human_turn_actions']['kans'], [])
                for forbidden in ('tsumo', 'kan'):
                    state = s.handle_action({'action': forbidden})
                    self.assertFalse(state['is_game_over'])
                    self.assertTrue(state['must_discard_after_call'])
                # Stop at the next player's turn, independent of their call policy.
                with patch.object(s.game, 'get_reaction_actions', return_value=[]):
                    s.handle_action({'action': 'discard', 'index': 0})
                self.assertEqual(len(s.game.players[0].hand.concealed_tiles), 10)
                self.assertEqual(len(s.game.players[0].discard_record.history), 1)
                self.assertIsNone(s.game.pending_meld_discard)
                self.assertEqual(s.game.current_turn, 1)

    def test_ai_chi_and_pon_skip_draw_and_discard_once(self):
        for kind in ('chi', 'pon'):
            for empty_wall in (False, True):
                with self.subTest(kind=kind, empty_wall=empty_wall):
                    s, target, actions, action = self.session_for_call(1, kind)
                    s.game.players[0].hand = hand('1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s')
                    s.game.players[0].hand.add(target)
                    with patch('gui_server.ai_choose_reaction', return_value=action), \
                         patch('gui_server.ai_open_call_matches_goal', return_value=True):
                        s.handle_action({'action': 'discard', 'index': 13})
                    self.assertEqual(s.game.pending_meld_discard, 1)
                    self.assertEqual(len(s.game.players[1].hand.concealed_tiles), 11)
                    if empty_wall:
                        s.game.wall.tiles.clear()
                    wall_before = s.game.wall.remaining()
                    # Hold the human at a reaction prompt, isolating the AI draw.
                    with patch.object(s.game.wall, 'draw', wraps=s.game.wall.draw) as draw, \
                         patch.object(s.game, 'get_reaction_actions', return_value=[{'type': 'pass'}]):
                        s.handle_action({'action': 'ai_step'})
                        draw.assert_not_called()
                    self.assertEqual(s.game.wall.remaining(), wall_before)
                    self.assertEqual(len(s.game.players[1].hand.concealed_tiles), 10)
                    self.assertEqual(len(s.game.players[1].discard_record.history), 1)
                    self.assertIsNone(s.game.pending_meld_discard)
                    self.assertFalse(s.game.is_game_over)
                    # A second ai_step while the human responds cannot draw/discard.
                    s.handle_action({'action': 'ai_step'})
                    self.assertEqual(len(s.game.players[1].discard_record.history), 1)

    def test_normal_ai_turn_still_draws(self):
        s = WebMahjongSession()
        s.game.players[1].hand = hand('1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s')
        s.game.current_turn = 1
        s.current_drawn_tile = None
        with patch.object(s.game.wall, 'draw', wraps=s.game.wall.draw) as draw, \
             patch.object(s.game, 'get_reaction_actions', return_value=[{'type': 'pass'}]):
            s.handle_action({'action': 'ai_step'})
            self.assertEqual(draw.call_count, 1)
        self.assertEqual(len(s.game.players[1].hand.concealed_tiles), 13)

    def test_kan_keeps_rinshan_draw(self):
        s = WebMahjongSession()
        s.game.players[0].hand = hand('5z 5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p')
        tile = Tile.from_str('5z')
        action = {'type': 'kan', 'kan_type': 'daiminkan', 'tile': tile}
        s.pending_reaction = {'player_idx': 0, 'target_tile': tile, 'actions': [action]}
        s.current_drawn_tile = None
        s.game.current_turn = 1
        count = len(s.game.wall.rinshan_tiles)
        state = s.handle_action({'action': 'reaction', 'choice': {'type': 'kan', 'index': 0}})
        self.assertEqual(len(s.game.wall.rinshan_tiles), count - 1)
        self.assertEqual(len(s.game.players[0].hand.concealed_tiles), 11)
        self.assertIsNotNone(state['current_drawn_tile'])
        self.assertFalse(state['must_discard_after_call'])


if __name__ == '__main__':
    unittest.main()

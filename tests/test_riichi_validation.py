import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_server import WebMahjongSession
from m1_tile import Hand, Tile, Meld
from m2_winning import get_waits
from m5_riichi import can_declare_riichi_with_discard, get_riichi_discard_candidates


def tile(code):
    return Tile.from_str(code)


class RiichiValidationTests(unittest.TestCase):
    def test_edge_wait_example_is_a_riichi_candidate(self):
        hand = Hand([tile(c) for c in
            '1m 2m 3m 1p 2p 3p 5p 6p 7p 9p 9p 8s 9s 4s'.split()])

        self.assertEqual([t.code for t in get_riichi_discard_candidates(hand)], ['4s'])
        hand.remove(tile('4s'))
        self.assertEqual([t.code for t in get_waits(hand)], ['7s'])

    def session(self):
        s = WebMahjongSession()
        s.game.players[0].hand = Hand([tile(c) for c in
            '1m 2m 3m 4m 5m 6m 1p 2p 3p 7s 8s 9s 5z 6z'.split()])
        s.current_drawn_tile = tile('6z')
        return s

    def test_invalid_candidate_does_not_change_game(self):
        s = self.session()
        p = s.game.players[0]
        before = list(p.hand.concealed_tiles)
        state = s.handle_action({'action': 'discard', 'index': 0, 'riichi': True})
        self.assertEqual(p.hand.concealed_tiles, before)
        self.assertEqual(p.score, 25000)
        self.assertEqual(p.discard_record.history, [])
        self.assertFalse(p.riichi_state.is_riichi)
        self.assertEqual(state['current_turn'], 0)
        self.assertEqual(s.current_drawn_tile, tile('6z'))

    def test_valid_riichi_discards_once_and_charges_once(self):
        s = self.session()
        p = s.game.players[0]
        with patch.object(s.game, 'get_reaction_actions', return_value=[]):
            s.handle_action({'action': 'discard', 'index': 13, 'riichi': True})
        self.assertTrue(p.riichi_state.is_riichi)
        self.assertEqual(p.score, 24000)
        self.assertEqual(len(p.hand.concealed_tiles), 13)
        self.assertEqual([t.code for t in get_waits(p.hand)], ['5z'])
        self.assertTrue(p.discard_record.history[0].is_riichi)
        s.handle_action({'action': 'discard', 'index': 0, 'riichi': True})
        self.assertEqual(p.score, 24000)
        self.assertEqual(len(p.discard_record.history), 1)

    def test_riichi_candidates_and_explanations_are_exposed_in_state(self):
        s = self.session()
        actions = s.build_state()['human_turn_actions']
        self.assertTrue(actions['can_riichi'])
        self.assertEqual({x['code'] for x in actions['riichi_candidates']},{'5z','6z'})
        self.assertEqual(actions['riichi_unavailable_reason'],'')
        s.game.players[0].score = 999
        actions = s.build_state()['human_turn_actions']
        self.assertFalse(actions['can_riichi'])
        self.assertIn('1,000점',actions['riichi_unavailable_reason'])
        s = self.session()
        s.game.wall.tiles = s.game.wall.tiles[:3]
        self.assertIn('패산',s.build_state()['human_turn_actions']['riichi_unavailable_reason'])
        s = self.session()
        p=s.game.players[0]
        p.hand.concealed_tiles = p.hand.concealed_tiles[3:]
        p.hand.melds.append(Meld('chi',[tile(c) for c in ('1m','2m','3m')]))
        self.assertIn('치·퐁',s.build_state()['human_turn_actions']['riichi_unavailable_reason'])

    def test_engine_rejects_each_invalid_condition_before_mutation(self):
        for condition in ('score', 'wall', 'already', 'open', 'short_hand', 'missing_tile'):
            with self.subTest(condition=condition):
                s = self.session()
                p = s.game.players[0]
                selected = tile('6z')
                if condition == 'score': p.score = 999
                elif condition == 'wall': s.game.wall.tiles = s.game.wall.tiles[:3]
                elif condition == 'already': p.riichi_state.is_riichi = True
                elif condition == 'open':
                    p.hand.concealed_tiles = p.hand.concealed_tiles[3:]
                    p.hand.melds.append(Meld('chi', [tile(c) for c in ('1m','2m','3m')]))
                elif condition == 'short_hand': p.hand.concealed_tiles.pop(0)
                elif condition == 'missing_tile': selected = tile('7z')
                before = list(p.hand.concealed_tiles)
                score = p.score
                self.assertFalse(s.game.execute_discard(0, selected, declare_riichi_now=True))
                self.assertEqual(p.hand.concealed_tiles, before)
                self.assertEqual(p.score, score)
                self.assertEqual(p.discard_record.history, [])

    def test_boundary_score_and_wall_are_allowed(self):
        s = self.session()
        p = s.game.players[0]
        p.score = 1000
        s.game.wall.tiles = s.game.wall.tiles[:4]
        self.assertTrue(s.game.execute_discard(0, tile('6z'), declare_riichi_now=True))
        self.assertEqual(p.score, 0)

    def test_red_and_normal_five_can_both_be_riichi_discards(self):
        s = self.session()
        p = s.game.players[0]
        p.hand.concealed_tiles[-2:] = [tile('5p'), Tile('p', 5, is_aka=True)]
        for selected in p.hand.concealed_tiles[-2:]:
            self.assertTrue(can_declare_riichi_with_discard(p.hand, p.riichi_state, selected, s.game.wall, p.score))

    def test_normal_discard_is_not_restricted_to_riichi_candidates(self):
        s = self.session()
        with patch.object(s.game, 'get_reaction_actions', return_value=[]):
            s.handle_action({'action':'discard', 'index':0})
        self.assertEqual(len(s.game.players[0].hand.concealed_tiles), 13)
        self.assertFalse(s.game.players[0].riichi_state.is_riichi)

    def test_riichi_lock_rejects_hand_change_but_allows_drawn_tile(self):
        s = self.session()
        p = s.game.players[0]
        p.riichi_state.is_riichi = True
        s.handle_action({'action':'discard', 'index':0})
        self.assertEqual(len(p.hand.concealed_tiles), 14)
        with patch.object(s.game, 'get_reaction_actions', return_value=[]):
            s.handle_action({'action':'discard', 'index':13})
        self.assertEqual(len(p.hand.concealed_tiles), 13)
        self.assertEqual(p.score, 25000)

    def test_ai_riichi_uses_actual_selected_discard_score_and_wall(self):
        for condition in ('candidate', 'score', 'wall', 'valid'):
            with self.subTest(condition=condition):
                s = self.session()
                ai = s.game.players[1]
                ai.hand = s.game.players[0].hand.clone()
                ai.hand.concealed_tiles.pop()
                s.game.current_turn = 1
                s.current_drawn_tile = None
                s.game.wall.tiles.insert(0, tile('6z'))
                if condition == 'score': ai.score = 999
                if condition == 'wall': s.game.wall.tiles = s.game.wall.tiles[:4]
                selected = tile('1m' if condition == 'candidate' else '6z')
                before_score = ai.score
                with patch('gui_server.ai_choose_discard', return_value=selected), \
                     patch.object(s.game, 'get_reaction_actions', return_value=[{'type':'pass'}]):
                    s.handle_action({'action':'ai_step'})
                self.assertEqual(ai.riichi_state.is_riichi, condition == 'valid')
                self.assertEqual(ai.score, before_score - (1000 if condition == 'valid' else 0))
                self.assertEqual(len(ai.hand.concealed_tiles), 13)
                self.assertEqual(len(ai.discard_record.history), 1)

    def test_repeated_riichi_tsumogiri_then_winning_draw(self):
        s = WebMahjongSession()
        p = s.game.players[0]
        p.hand = Hand([tile(c) for c in '3m 3m 3m 4m 5m 6m 7m 8m 1p 2p 3p 2s 3s 7s'.split()])
        p.riichi_state.is_riichi = True
        s.current_drawn_tile = p.hand.concealed_tiles[-1]
        p.last_drawn_tile = s.current_drawn_tile
        s.game.players[1].hand = Hand([tile(c) for c in '1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s'.split()])
        s.game.wall.tiles = [tile(c) for c in '7z 9p 7z 2z 7z 1s'.split()]
        for expected in ('7s','9p','2z'):
            state = s.build_state()
            self.assertEqual(state['current_drawn_index'],13)
            self.assertEqual(state['current_drawn_tile']['code'],expected)
            self.assertFalse(state['human_turn_actions']['can_tsumo'])
            s.handle_action({'action':'discard','index':13})
            self.assertEqual(len(p.hand.concealed_tiles),13)
            self.assertEqual([x.code for x in get_waits(p.hand)],['1s','4s'])
            self.assertTrue(p.discard_record.history[-1].is_tsumogiri)
            with patch('gui_server.ai_choose_discard',side_effect=lambda *args, **kwargs:kwargs['drawn_tile']):
                s.handle_action({'action':'ai_step'})
            self.assertIsNone(s.pending_reaction)
        self.assertTrue(s.build_state()['human_turn_actions']['can_tsumo'])
        state=s.handle_action({'action':'tsumo'})
        self.assertTrue(state['is_game_over'])
        self.assertEqual(state['winner'],0)


if __name__ == '__main__':
    unittest.main()


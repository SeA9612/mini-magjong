import sys
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui_server import (WebMahjongSession, DIFFICULTY_TARGET_YAKU, ai_yaku_goal_met,
                        ai_open_call_matches_goal)
from m1_tile import Hand, Tile, Meld, Wall
from m2_winning import get_waits, is_winning_hand, calculate_shanten
from m3_yaku import YakuContext, get_yaku
from m4_meld import apply_kan
from m6_win import can_ron
from m7_ai import choose_discard, _evaluate_tile_efficiency


def t(code): return Tile.from_str(code)
def h(codes): return Hand([t(c) for c in codes.split()])
WAIT = '1m 2m 3m 4m 5m 6m 1p 2p 3p 7s 8s 9s 5z'


class GameIntegrityTests(unittest.TestCase):
    def test_difficulty_has_exact_requested_target_yaku_sets(self):
        self.assertEqual(DIFFICULTY_TARGET_YAKU['low'], frozenset(('리치','핑후')))
        self.assertEqual(DIFFICULTY_TARGET_YAKU['medium'], frozenset(('리치','핑후','탕야오','치토이츠')))
        self.assertEqual(DIFFICULTY_TARGET_YAKU['high'], frozenset((
            '리치','문전청자모','핑후','탕야오','역패(백)','역패(발)','역패(중)',
            '역패(장풍)','역패(자풍)','치토이츠','또이또이'
        )))
        class YakuName:
            def __init__(self, name): self.name = name
        self.assertTrue(ai_yaku_goal_met([YakuName('리치')], 'low'))
        self.assertFalse(ai_yaku_goal_met([YakuName('탕야오')], 'low'))
        self.assertTrue(ai_yaku_goal_met([YakuName('탕야오')], 'medium'))
        self.assertTrue(ai_yaku_goal_met([YakuName('또이또이')], 'high'))
        pon_haku = {'type':'pon','tile':t('5z')}
        self.assertFalse(ai_open_call_matches_goal(pon_haku,'low',1,2))
        self.assertFalse(ai_open_call_matches_goal(pon_haku,'medium',1,2))
        self.assertTrue(ai_open_call_matches_goal(pon_haku,'high',1,2))

    def test_difficulty_selection_is_exposed_and_locked_after_play_starts(self):
        s = WebMahjongSession()
        state = s.build_state()
        self.assertEqual(state['difficulty'], 'medium')
        self.assertTrue(state['can_change_difficulty'])
        self.assertEqual(set(state['difficulty_target_yaku']), DIFFICULTY_TARGET_YAKU['medium'])
        state = s.handle_action({'action':'set_difficulty','difficulty':'low','revision':s.revision})
        self.assertEqual(state['difficulty'], 'low')
        self.assertEqual(set(state['difficulty_target_yaku']), DIFFICULTY_TARGET_YAKU['low'])
        s.game.players[0].discard_record.add(t('1m'))
        state = s.handle_action({'action':'set_difficulty','difficulty':'high','revision':s.revision})
        self.assertEqual(state['difficulty'], 'low')
        self.assertFalse(state['can_change_difficulty'])

    def test_new_game_keeps_selected_difficulty(self):
        s = WebMahjongSession()
        state = s.handle_action({'action':'set_difficulty','difficulty':'high','revision':s.revision})
        state = s.handle_action({'action':'restart','revision':s.revision})
        self.assertEqual(state['difficulty'], 'high')
        self.assertTrue(state['can_change_difficulty'])

    def test_ai_tsumo_must_match_at_least_one_goal_yaku(self):
        for difficulty, yaku_name, expected_win in (
            ('low', '문전청자모', False),
            ('medium', '탕야오', True),
            ('high', '또이또이', True),
        ):
            s = WebMahjongSession()
            s.difficulty = difficulty
            ai = s.game.players[1]
            ai.hand = h(WAIT + ' 5z')
            s.game.current_turn = 1
            s.current_drawn_tile = t('5z')
            yaku = [SimpleNamespace(name=yaku_name)]

            def fake_tsumo(player_idx, win_tile):
                s.game.is_game_over = True
                s.game.winner = s.game.players[player_idx]
                s.game.winning_type = 'tsumo'
                s.game.winning_tile = win_tile
                s.game.winning_yaku = []
                return True

            with self.subTest(difficulty=difficulty, yaku=yaku_name), \
                 patch('gui_server.can_tsumo', return_value=True), \
                 patch('gui_server.get_yaku', return_value=yaku), \
                 patch('gui_server.ai_choose_discard', return_value=ai.hand.concealed_tiles[0]), \
                 patch('gui_server.ai_should_riichi', return_value=False), \
                 patch.object(s.game, 'execute_tsumo', side_effect=fake_tsumo), \
                 patch.object(s.game, 'get_reaction_actions', return_value=[]):
                state = s.handle_action({'action':'ai_step','revision':s.revision})
            self.assertEqual(state['is_game_over'], expected_win)

    def test_ai_ron_must_match_at_least_one_goal_yaku(self):
        for difficulty, yaku_name, expected_win in (
            ('low', '탕야오', False),
            ('medium', '탕야오', True),
        ):
            s = WebMahjongSession()
            s.difficulty = difficulty
            yaku = [SimpleNamespace(name=yaku_name)]
            offered_ron = [{'type':'ron'}]

            def fake_ron(player_idx, win_tile):
                s.game.is_game_over = True
                s.game.winner = s.game.players[player_idx]
                s.game.winning_type = 'ron'
                s.game.winning_tile = win_tile
                return True

            with self.subTest(difficulty=difficulty), \
                 patch('gui_server.get_yaku', return_value=yaku), \
                 patch('gui_server.ai_choose_reaction', return_value={'type':'ron'}), \
                 patch.object(s.game, 'get_reaction_actions', return_value=offered_ron), \
                 patch.object(s.game, 'execute_ron', side_effect=fake_ron):
                state = s.handle_action({'action':'discard','index':0,'revision':s.revision})
            self.assertEqual(state['is_game_over'], expected_win)

    def test_restart_resets_current_hand_and_pond_but_assigns_new_game_id(self):
        s = WebMahjongSession()
        first_game_id = s.build_state()['game_id']
        s.game.players[0].discard_record.add(t('1m'))
        s.game.players[1].discard_record.add(t('2m'))
        s.game.wall.tiles.pop()
        state = s.handle_action({'action':'restart','revision':s.revision})
        self.assertNotEqual(state['game_id'], first_game_id)
        self.assertFalse(state['is_game_over'])
        self.assertEqual(state['current_turn'], 0)
        self.assertEqual(state['wall_remaining'], 95)
        self.assertEqual(state['players'][0]['discards'], [])
        self.assertEqual(state['players'][1]['discards'], [])
        self.assertEqual(len(state['players'][0]['concealed_tiles']), 14)

    def test_restart_after_player_win_or_ai_win_starts_fresh_hand(self):
        for winner_index in (0, 1):
            s = WebMahjongSession()
            player = s.game.players[winner_index]
            player.hand = h(WAIT + ' 5z')
            s.game.current_turn = winner_index
            win_tile = t('5z')
            if winner_index == 0:
                s.current_drawn_tile = win_tile
            self.assertTrue(s.game.execute_tsumo(winner_index, win_tile))
            self.assertTrue(s.game.is_game_over)
            self.assertEqual(s.game.winner.id, winner_index)
            self.assertEqual(s.game.winning_type, 'tsumo')
            state = s.handle_action({'action':'restart','revision':s.revision})
            self.assertFalse(state['is_game_over'])
            self.assertEqual(state['wall_remaining'], 95)
            self.assertEqual(state['players'][0]['discards'], [])
            self.assertEqual(len(state['players'][0]['concealed_tiles']), 14)

    def ron_session(self):
        s = WebMahjongSession()
        s.game.players[0].hand = h(WAIT)
        s.game.players[0].riichi_state.is_riichi = True
        s.game.last_discard = t('5z')
        s.game.last_discard_player = 1
        s.game.players[1].discard_record.add(t('5z'))
        s.game.current_turn = 1
        s.current_drawn_tile = None
        s.pending_reaction = {'player_idx':0, 'target_tile':t('5z'),
            'actions':s.game.get_reaction_actions(0, t('5z'))}
        return s

    def test_invalid_tsumo_does_not_end_game(self):
        s = WebMahjongSession()
        s.game.players[0].hand = h('1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s 5s')
        self.assertFalse(s.handle_action({'action':'tsumo'})['is_game_over'])
        self.assertFalse(s.game.execute_tsumo(0, t('5s')))

    def test_valid_tsumo_and_ai_hand_reveal(self):
        s = WebMahjongSession()
        s.game.players[1].hand = h(WAIT + ' 5z')
        s.game.current_turn = 1
        self.assertNotIn('concealed_tiles', s.build_state()['players'][1])
        self.assertTrue(s.game.execute_tsumo(1, t('5z')))
        state = s.build_state()
        self.assertEqual(len(state['players'][1]['concealed_tiles']), 14)
        self.assertEqual(len(state['winning_hand']), 14)
        self.assertTrue(state['winning_yaku'])

    def test_furiten_disallows_ron_but_allows_valid_tsumo(self):
        s = WebMahjongSession()
        player = s.game.players[0]
        player.hand = h(WAIT + ' 5z')
        s.current_drawn_tile = player.hand.concealed_tiles[-1]
        player.last_drawn_tile = s.current_drawn_tile
        player.discard_record.add(t('5z'))
        self.assertFalse(can_ron(h(WAIT),t('5z'),player.discard_record,YakuContext(is_riichi=True)))
        state = s.build_state()
        self.assertTrue(state['is_human_furiten'])
        self.assertTrue(state['human_turn_actions']['can_tsumo'])
        state = s.handle_action({'action':'tsumo'})
        self.assertTrue(state['is_game_over'])
        self.assertEqual(state['winning_type'],'tsumo')

    def test_no_yaku_or_wrong_turn_tsumo_rejected(self):
        s = WebMahjongSession()
        s.game.players[0].hand = h('1p 2p 3p 4m 5m 6m 7s 8s 9s 5z 5z')
        s.game.players[0].hand.melds = [Meld('chi', [t(c) for c in ('1m','2m','3m')])]
        self.assertFalse(s.game.execute_tsumo(0, t('5z')))
        s.game.players[0].hand = h(WAIT + ' 5z')
        s.game.current_turn = 1
        self.assertFalse(s.game.execute_tsumo(0, t('5z')))

    def test_ron_requires_actual_offer_and_legal_hand(self):
        s = WebMahjongSession()
        s.handle_action({'action':'reaction', 'choice':{'type':'ron'}})
        self.assertFalse(s.game.is_game_over)
        s = self.ron_session()
        s.game.players[0].hand = h('1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s')
        s.handle_action({'action':'reaction','choice':{'type':'ron'}})
        self.assertFalse(s.game.is_game_over)
        self.assertIsNotNone(s.pending_reaction)

    def test_valid_ron_complete_result_and_furiten(self):
        s = self.ron_session()
        s.game.players[0].discard_record.add(t('5z'))
        s.handle_action({'action':'reaction','choice':{'type':'ron'}})
        self.assertFalse(s.game.is_game_over)
        s = self.ron_session()
        state = s.handle_action({'action':'reaction','choice':{'type':'ron'}})
        self.assertTrue(state['is_game_over'])
        self.assertEqual(state['winning_type'], 'ron')
        self.assertEqual(len(state['winning_hand']), 14)
        self.assertEqual(len(s.game.players[0].hand.concealed_tiles), 13)

    def test_ron_with_already_complete_hand_rejected(self):
        self.assertFalse(can_ron(h(WAIT + ' 5z'), t('5z'), WebMahjongSession().game.players[0].discard_record, YakuContext(is_riichi=True)))

    def test_riichi_pass_ron_remains_furiten_after_draw(self):
        s = self.ron_session()
        s.game.wall.tiles.insert(0, t('2z'))
        s.handle_action({'action':'reaction','choice':{'type':'pass'}})
        p = s.game.players[0]
        self.assertTrue(p.riichi_furiten)
        p.hand.remove(t('2z'))
        self.assertFalse(any(a['type']=='ron' for a in s.game.get_reaction_actions(0,t('5z'))))

    def test_temporary_furiten_clears_on_next_draw(self):
        s = WebMahjongSession()
        s.game.pass_ron(0)
        self.assertTrue(s.game.players[0].temporary_furiten)
        s.game.draw_tile(0)
        self.assertFalse(s.game.players[0].temporary_furiten)

    def test_reaction_pass_without_offer_does_not_draw(self):
        s = WebMahjongSession()
        before = s.game.wall.remaining()
        s.handle_action({'action':'reaction','choice':{'type':'pass'}})
        self.assertEqual(s.game.wall.remaining(), before)
        self.assertEqual(len(s.game.players[0].hand.concealed_tiles),14)

    def test_bad_reaction_index_and_type_keep_offer(self):
        for choice in ({'type':'pon','index':0}, {'type':'ron','index':'bad'}, {'type':'other'}):
            s = self.ron_session()
            # Ron validity is independent of a UI index; test mismatched meld indices.
            if choice['type']=='ron': choice = {'type':'chi','index':'bad'}
            s.handle_action({'action':'reaction','choice':choice})
            self.assertIsNotNone(s.pending_reaction)
            self.assertFalse(s.game.is_game_over)

    def test_malformed_actions_do_not_crash_or_discard(self):
        for request in ([], None, {'action':'discard','index':[]}, {'action':'discard','index':True},
                        {'action':'discard','index':-1}, {'action':'discard','index':0,'riichi':'yes'}):
            s = WebMahjongSession()
            s.handle_action(request)
            self.assertEqual(len(s.game.players[0].hand.concealed_tiles),14)

    def test_same_revision_concurrent_discard_accepted_once(self):
        s = WebMahjongSession()
        revision = s.revision
        with patch.object(s.game,'get_reaction_actions',return_value=[]):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(s.handle_action,[{'action':'discard','index':0,'revision':revision}]*2))
        self.assertEqual(len(s.game.players[0].discard_record.history),1)
        self.assertEqual(len(s.game.players[0].hand.concealed_tiles),13)

    def test_impossible_fifth_tile_wait_rejected(self):
        hand = h('1m 1m 1m 1m 2p 3p 4p 5s 6s 7s 7p 8p 9p')
        self.assertEqual(get_waits(hand),[])
        self.assertFalse(is_winning_hand(hand,t('1m')))
        hand = h('1m 2m 3m 4p 5p 6p 7s 8s 9s 5z')
        hand.melds = [Meld('pon',[t('5z')]*3)]
        self.assertNotIn(t('5z'),get_waits(hand))

    def test_shanten_and_ai_preserve_melds(self):
        self.assertEqual(calculate_shanten(h(WAIT)),0)
        self.assertEqual(calculate_shanten(h(WAIT+' 5z')),-1)
        hand = h('1m 2m 3m 4m 5m 6m 7p 8p 2s 3s 5z 5z 1z 2z')
        self.assertGreater(_evaluate_tile_efficiency(hand,t('1z')), _evaluate_tile_efficiency(hand,t('2m')))
        self.assertIn(choose_discard(hand,YakuContext(),WebMahjongSession().game.players[0].riichi_state).code,('1z','2z'))

    def test_pinfu_requires_actual_ryanmen_completion(self):
        for code, expected in (('3m',False),('1m',True)):
            hand = h('1m 2m 3m 4p 5p 6p 7s 8s 9s 2s 3s 4s 2z 2z')
            names = [y.romaji for y in get_yaku(hand,YakuContext(win_tile=t(code)))]
            self.assertEqual('Pinfu' in names,expected)

    def test_tsumogiri_tracks_normal_and_rinshan_draws(self):
        s = WebMahjongSession()
        drawn = s.current_drawn_tile
        s.game.execute_discard(0, drawn)
        self.assertTrue(s.game.players[0].discard_record.history[-1].is_tsumogiri)
        s.game.players[0].hand = h('5z 5z 5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p')
        drawn = s.game.execute_meld(0,{'type':'kan','kan_type':'ankan','tile':t('5z')})
        s.game.execute_discard(0,drawn)
        self.assertTrue(s.game.players[0].discard_record.history[-1].is_tsumogiri)

    def test_same_kind_standing_tile_is_not_tsumogiri(self):
        s = WebMahjongSession()
        standing, drawn = t('5p'), t('5p')
        s.game.players[0].hand = Hand([standing,drawn])
        s.game.players[0].last_drawn_tile = drawn
        s.game.execute_discard(0,standing)
        self.assertFalse(s.game.players[0].discard_record.history[-1].is_tsumogiri)
        self.assertIs(s.game.players[0].hand.concealed_tiles[0],drawn)

    def test_called_discard_kept_for_furiten_hidden_in_pond(self):
        s = WebMahjongSession()
        s.game.players[0].hand = h('5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p')
        s.game.players[1].discard_record.add(t('5z'))
        s.game.execute_meld(0,{'type':'pon','tile':t('5z')})
        self.assertTrue(s.game.players[1].discard_record.has_tile(t('5z')))
        self.assertEqual(s.build_state()['players'][1]['discards'],[])

    def test_wall_stays_fourteen_and_kakan_preserves_red(self):
        wall = Wall(seed=7)
        for _ in range(4):
            self.assertIsNotNone(wall.draw_rinshan())
            self.assertEqual(len(wall.dead_wall),14)
        self.assertIsNone(wall.draw_rinshan())
        red = Tile('m',5,True)
        hand = Hand([red],[Meld('pon',[t('5m')]*3)])
        apply_kan(hand,t('5m'),'kakan')
        self.assertEqual(sum(x.is_aka for x in hand.all_tiles),1)


class FullGameTests(unittest.TestCase):
    def test_seeded_games_terminate_and_preserve_all_tiles(self):
        for seed in range(8):
            with self.subTest(seed=seed):
                s = WebMahjongSession()
                s.game.wall.rng.seed(seed)
                s.current_drawn_tile = s.game.start_game()
                for step in range(350):
                    if s.game.is_game_over:
                        break
                    if s.pending_reaction:
                        actions = s.pending_reaction['actions']
                        choice = next((a for a in actions if a['type']=='ron'),None)
                        if choice is None and seed % 2:
                            choice = next((a for a in actions if a['type'] in ('pon','chi','kan')),None)
                        request = {'action':'reaction','choice':{'type':'pass'} if choice is None else {
                            'type':choice['type'],'index':actions.index(choice)}}
                    elif s.game.current_turn == 1:
                        request = {'action':'ai_step'}
                    else:
                        p = s.game.players[0]
                        actions = s.game.get_turn_actions(0,s.current_drawn_tile)
                        if actions['can_tsumo']:
                            request = {'action':'tsumo'}
                        else:
                            selected = choose_discard(p.hand,s.game.create_yaku_context(0,True,s.current_drawn_tile),p.riichi_state,s.current_drawn_tile)
                            request = {'action':'discard','index':p.hand.concealed_tiles.index(selected)}
                    request['revision'] = s.revision
                    s.handle_action(request)
                    physical = list(s.game.wall.tiles) + list(s.game.wall.dead_wall)
                    for p in s.game.players:
                        physical += p.hand.all_tiles
                        physical += [x.tile for x in p.discard_record.history if not x.is_called]
                        expected = 13 - 3 * len(p.hand.melds)
                        extra = (s.game.current_turn == p.id and not s.pending_reaction and
                                 (s.current_drawn_tile is not None or s.game.pending_meld_discard == p.id))
                        if not s.game.is_game_over:
                            self.assertEqual(len(p.hand.concealed_tiles),expected + int(extra))
                    self.assertEqual(len(physical),136)
                    self.assertEqual(set(Counter(x.code for x in physical).values()),{4})
                    self.assertEqual(sum(x.is_aka for x in physical),3)
                self.assertTrue(s.game.is_game_over)
                self.assertIn(s.game.winning_type,('tsumo','ron','draw'))


if __name__ == '__main__':
    unittest.main()

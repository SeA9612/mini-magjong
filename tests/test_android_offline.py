"""Exercise the Android JSON bridge with all network sockets prohibited."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('offline_engine', ROOT / 'android/app/src/main/python/offline_engine.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class OfflineBridgeTests(unittest.TestCase):
    def setUp(self):
        bridge.initialize(str(ROOT))
        self.block_network = patch('socket.socket', side_effect=AssertionError('Network forbidden'))
        self.block_network.start()
        self.addCleanup(self.block_network.stop)

    def request(self, path='/api/state', body=None):
        return json.loads(bridge.request(json.dumps({'path': path, 'body': body})))

    def test_draw_discard_ai_and_restart_without_network(self):
        state = self.request()['data']
        self.assertEqual(len(state['players'][0]['concealed_tiles']), 14)
        game_id = state['game_id']
        state = self.request('/api/action', {'action': 'discard', 'index': 0, 'revision': state['revision']})['data']
        self.assertEqual(len(state['players'][0]['concealed_tiles']), 13)
        state = self.request('/api/action', {'action': 'ai_step', 'revision': state['revision']})['data']
        self.assertTrue(state['revision'] >= 2)
        state = self.request('/api/action', {'action': 'restart', 'revision': state['revision']})['data']
        self.assertNotEqual(state['game_id'], game_id)
        self.assertEqual(len(state['players'][0]['concealed_tiles']), 14)
        self.assertEqual(state['wall_remaining'], 95)

    def test_repeated_action_does_not_discard_twice(self):
        state = self.request()['data']
        action = {'action': 'discard', 'index': 0, 'revision': state['revision']}
        self.request('/api/action', action)
        state = self.request('/api/action', action)['data']
        self.assertEqual(len(state['players'][0]['discards']), 1)

    def test_edge_wait_riichi_through_offline_bridge(self):
        from m1_tile import Hand, Tile
        player = bridge._session.game.players[0]
        player.hand = Hand([Tile(c[-1], int(c[0])) for c in
                           '1m 2m 3m 1p 2p 3p 5p 6p 7p 9p 9p 8s 9s 4s'.split()])
        bridge._session.current_drawn_tile = player.hand.concealed_tiles[-1]
        player.last_drawn_tile = bridge._session.current_drawn_tile
        state = self.request()['data']
        self.assertTrue(state['human_turn_actions']['can_riichi'])

    def test_invalid_request_is_rejected_and_game_remains_usable(self):
        self.assertEqual(json.loads(bridge.request('{'))['status'], 400)
        self.assertEqual(self.request('/remote')['status'], 400)
        self.assertEqual(self.request('/api/action', [])['status'], 400)
        self.assertEqual(self.request()['status'], 200)


if __name__ == '__main__':
    unittest.main()

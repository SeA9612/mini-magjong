import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mazak
from gui_server import WebMahjongSession
from m1_tile import Tile, Hand


class CliTests(unittest.TestCase):
    def test_invalid_input_does_not_advance_turn(self):
        session = WebMahjongSession()
        with patch('gui_server.WebMahjongSession', return_value=session), \
             patch('builtins.input', side_effect=['invalid', 'q']), \
             patch('sys.stdout', new_callable=io.StringIO):
            mazak.run_cli()
        self.assertEqual(session.game.current_turn,0)
        self.assertEqual(len(session.game.players[0].hand.concealed_tiles),14)
        self.assertEqual(session.game.players[0].discard_record.history,[])

    def test_cli_can_tsumo(self):
        session = WebMahjongSession()
        session.game.players[0].hand = Hand([Tile.from_str(c) for c in
            '1m 2m 3m 4m 5m 6m 1p 2p 3p 7s 8s 9s 5z 5z'.split()])
        session.current_drawn_tile = Tile.from_str('5z')
        with patch('gui_server.WebMahjongSession', return_value=session), \
             patch('builtins.input', return_value='t'), \
             patch('sys.stdout', new_callable=io.StringIO):
            mazak.run_cli()
        self.assertTrue(session.game.is_game_over)
        self.assertEqual(session.game.winning_type,'tsumo')

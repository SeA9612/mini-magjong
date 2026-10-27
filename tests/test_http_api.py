import json
import sys
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_server


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = gui_server.ThreadedHTTPServer(('127.0.0.1',0),gui_server.MahjongHTTPHandler)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, data, cookie=None):
        headers={'Content-Type':'application/json'}
        if cookie:
            headers['Cookie']=cookie
        request = urllib.request.Request(self.base+'/api/action',data=data,headers=headers)
        return urllib.request.urlopen(request,timeout=5)

    def state_request(self, cookie=None, headers=None):
        request_headers=dict(headers or {})
        if cookie:
            request_headers['Cookie']=cookie
        request=urllib.request.Request(self.base+'/api/state',headers=request_headers)
        return urllib.request.urlopen(request,timeout=5)

    def test_invalid_json_and_non_object_return_400(self):
        for data in (b'{',b'[]',b'null'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(data)
            self.assertEqual(error.exception.code,400)
            error.exception.close()

    def test_invalid_tsumo_rejected_over_real_http(self):
        session = gui_server.WebMahjongSession()
        from m1_tile import Hand, Tile
        session.game.players[0].hand=Hand([Tile.from_str(c) for c in
            '1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s 5s'.split()])
        test_store=gui_server.WebSessionStore(session_factory=lambda:session)
        with patch.object(gui_server,'SESSION_STORE',test_store):
            with self.state_request() as initial_response:
                cookie=initial_response.headers['Set-Cookie'].split(';',1)[0]
                json.load(initial_response)
            with self.request(json.dumps({'action':'tsumo','revision':session.revision}).encode(),cookie) as response:
                state=json.load(response)
            self.assertFalse(state['is_game_over'])
            self.assertIsNone(state['winner'])

    def test_server_survives_bad_input_and_serves_game(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(b'bad')
        error.exception.close()
        with self.state_request() as response:
            state=json.load(response)
        self.assertEqual(len(state['players']),2)
        with urllib.request.urlopen(self.base+'/app.js',timeout=5) as response:
            self.assertIn(b'function sendAction',response.read())

    def test_each_browser_gets_an_independent_game_session(self):
        with self.state_request() as first_response:
            first_state=json.load(first_response)
            first_cookie=first_response.headers['Set-Cookie'].split(';',1)[0]
        discard=json.dumps({'action':'discard','index':0,'revision':first_state['revision']}).encode()
        with self.request(discard,first_cookie) as action_response:
            changed_state=json.load(action_response)
        self.assertEqual(len(changed_state['players'][0]['discards']),1)
        with self.state_request(cookie=first_cookie) as returning_response:
            returning_state=json.load(returning_response)
        with self.state_request() as second_response:
            second_state=json.load(second_response)
            second_cookie=second_response.headers['Set-Cookie'].split(';',1)[0]

        self.assertEqual(returning_state['game_id'],first_state['game_id'])
        self.assertEqual(returning_state['revision'],changed_state['revision'])
        self.assertNotEqual(second_state['game_id'],first_state['game_id'])
        self.assertEqual(second_state['revision'],0)
        self.assertEqual(second_state['players'][0]['discards'],[])
        self.assertNotEqual(second_cookie,first_cookie)

    def test_session_cookie_is_http_only_and_secure_behind_https_proxy(self):
        with self.state_request(headers={'X-Forwarded-Proto':'https'}) as response:
            response.read()
            cookie=response.headers['Set-Cookie']
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Lax',cookie)
        self.assertIn('Secure',cookie)

    def test_second_server_cannot_listen_on_same_port(self):
        with self.assertRaises(OSError):
            gui_server.ThreadedHTTPServer(('127.0.0.1',self.server.server_port),gui_server.MahjongHTTPHandler)

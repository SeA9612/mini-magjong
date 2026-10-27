import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_server
import mazak


class LauncherTests(unittest.TestCase):
    def fake_server(self, port):
        server = Mock(server_port=port)
        server.serve_forever.side_effect = KeyboardInterrupt
        return server

    def test_free_port_opens_browser_and_closes_server_on_exit(self):
        server = self.fake_server(8765)
        with patch.object(gui_server,'ThreadedHTTPServer',return_value=server), \
             patch('webbrowser.open',return_value=True) as browser, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(gui_server.start_server(),'http://127.0.0.1:8765')
        browser.assert_called_once_with('http://127.0.0.1:8765')
        server.server_close.assert_called_once()

    def test_same_version_running_opens_existing_game(self):
        with patch.object(gui_server,'ThreadedHTTPServer',side_effect=OSError(10048,'in use')), \
             patch.object(gui_server,'compatible_server_running',return_value=True), \
             patch('webbrowser.open',return_value=True) as browser, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(gui_server.start_server(),'http://127.0.0.1:8765')
        browser.assert_called_once_with('http://127.0.0.1:8765')

    def test_legacy_server_is_preserved_and_latest_uses_next_port(self):
        server = self.fake_server(8766)
        with patch.object(gui_server,'ThreadedHTTPServer',side_effect=[OSError(10048,'in use'),server]) as factory, \
             patch.object(gui_server,'compatible_server_running',return_value=False), \
             patch('webbrowser.open',return_value=True) as browser, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(gui_server.start_server(),'http://127.0.0.1:8766')
        self.assertEqual(factory.call_args_list[1].args[0],('127.0.0.1',8766))
        browser.assert_called_once_with('http://127.0.0.1:8766')

    def test_relaunch_finds_existing_latest_server_on_next_port(self):
        with patch.object(gui_server,'ThreadedHTTPServer',side_effect=OSError(10048,'in use')), \
             patch.object(gui_server,'compatible_server_running',side_effect=[False,True]), \
             patch('webbrowser.open',return_value=True) as browser, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(gui_server.start_server(),'http://127.0.0.1:8766')
        browser.assert_called_once_with('http://127.0.0.1:8766')

    def test_browser_failure_reports_error_and_releases_new_port(self):
        server = self.fake_server(8765)
        with patch.object(gui_server,'ThreadedHTTPServer',return_value=server), \
             patch('webbrowser.open',return_value=False), patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError,'http://127.0.0.1:8765'):
                gui_server.start_server()
        server.server_close.assert_called_once()

    def test_all_ports_busy_reports_failure(self):
        with patch.object(gui_server,'ThreadedHTTPServer',side_effect=OSError(10048,'in use')), \
             patch.object(gui_server,'compatible_server_running',return_value=False), \
             patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError,'사용 가능한'):
                gui_server.start_server()

    def test_hosted_startup_uses_platform_port_and_public_bind_without_browser(self):
        server = self.fake_server(12345)
        with patch.dict('os.environ',{'PORT':'12345','HOST':'0.0.0.0'}), \
             patch.object(gui_server,'ThreadedHTTPServer',return_value=server) as factory, \
             patch('webbrowser.open') as browser, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(gui_server.start_server(),'http://127.0.0.1:12345')
        self.assertEqual(factory.call_args.args[0],('0.0.0.0',12345))
        browser.assert_not_called()
        server.server_close.assert_called_once()

    def test_startup_failure_keeps_console_open_and_records_error(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'mazak.py'
            with patch.object(mazak,'__file__',str(script)), \
                 patch.object(mazak,'run_gui',side_effect=RuntimeError('startup failed')), \
                 patch('sys.stdin.isatty',return_value=True), \
                 patch('builtins.input',return_value='') as pause, \
                 patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(mazak.main([]),1)
            pause.assert_called_once()
            self.assertIn('startup failed',(Path(directory)/'mazak-error.log').read_text(encoding='utf-8'))

    def test_health_requires_matching_service_and_source_version(self):
        for health,expected in (({'service':'riichi-mahjong','source_version':gui_server.RUNNING_SOURCE_VERSION},True),
                                ({'service':'riichi-mahjong','source_version':'old'},False),
                                ({'service':'another-app','source_version':gui_server.RUNNING_SOURCE_VERSION},False)):
            response = Mock()
            response.__enter__=Mock(return_value=response)
            response.__exit__=Mock(return_value=False)
            response.read.return_value=json.dumps(health).encode()
            with patch('urllib.request.urlopen',return_value=response):
                self.assertEqual(gui_server.compatible_server_running(8765),expected)

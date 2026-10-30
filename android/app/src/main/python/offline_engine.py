"""Android bridge to the same game engine; no HTTP server or sockets."""
import json
import sys
import threading

_session = None
_lock = threading.RLock()


def initialize(engine_directory):
    global _session
    with _lock:
        if str(engine_directory) not in sys.path:
            sys.path.insert(0, str(engine_directory))
        from gui_server import WebMahjongSession
        _session = WebMahjongSession()
        return True


def request(raw):
    with _lock:
        try:
            from gui_server import json_serial_fallback
            data = json.loads(raw)
            if not isinstance(data, dict) or _session is None:
                raise ValueError('Game engine is not initialized')
            path = data.get('path')
            if path == '/api/state':
                state = _session.build_state()
            elif path == '/api/action':
                action = data.get('body')
                if not isinstance(action, dict):
                    raise ValueError('Invalid action')
                state = _session.handle_action(action)
            else:
                raise ValueError('Unknown offline API')
            return json.dumps({'status': 200, 'data': state}, ensure_ascii=False,
                              default=json_serial_fallback)
        except (ValueError, TypeError) as error:
            return json.dumps({'status': 400, 'data': {'error': str(error)}})

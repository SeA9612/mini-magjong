/* Translate the existing game's API calls to the on-device Python engine. */
(() => {
  'use strict';
  window.fetch = async (input, options = {}) => {
    const url = new URL(String(input), location.href);
    if (url.origin !== location.origin || !['/api/state', '/api/action'].includes(url.pathname)) {
      throw new Error('이 앱은 외부 연결을 사용하지 않습니다.');
    }
    const result = JSON.parse(AndroidGame.request(JSON.stringify({
      path: url.pathname,
      body: options.body ? JSON.parse(options.body) : null
    })));
    return {
      ok: result.status >= 200 && result.status < 300,
      status: result.status,
      json: async () => result.data
    };
  };
  window.pauseOfflineGame = () => {
    const pause = document.getElementById('pause-modal');
    if (pause && pause.style.display !== 'flex') {
      document.getElementById('btn-pause')?.click();
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) window.pauseOfflineGame();
  });
})();

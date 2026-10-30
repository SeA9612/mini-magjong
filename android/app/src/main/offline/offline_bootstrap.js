/* This startup diagnostic must parse even in Android 7's original WebView. */
(function () {
    window.offlineGameReady = false;
    window.setTimeout(function () {
        if (!window.offlineGameReady) {
            var error = document.getElementById('start-error');
            if (error) error.textContent = '게임 화면 초기화에 실패했습니다. 앱을 다시 실행해 주세요.';
        }
    }, 8000);
    if (typeof NodeList !== 'undefined' && !NodeList.prototype.forEach) {
        NodeList.prototype.forEach = Array.prototype.forEach;
    }
    if (!Object.getOwnPropertyDescriptors) {
        Object.getOwnPropertyDescriptors = function (object) {
            var descriptors = {};
            var keys = Object.getOwnPropertyNames(object);
            if (Object.getOwnPropertySymbols) keys = keys.concat(Object.getOwnPropertySymbols(object));
            keys.forEach(function (key) {
                Object.defineProperty(descriptors, key, {
                    value: Object.getOwnPropertyDescriptor(object, key),
                    enumerable: true, configurable: true, writable: true
                });
            });
            return descriptors;
        };
    }
})();

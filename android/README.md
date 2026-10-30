# 미니마작 오프라인 Android 앱

게임 화면과 Python 마작 엔진을 함께 넣은 설치용 APK입니다. 실행 시 Render나 다른 서버에 접속하지 않습니다. Android INTERNET 권한도 선언하지 않습니다.

## 설치와 실행

1. `mini-mahjong-offline.apk`를 Android 휴대폰으로 옮겨 엽니다.
2. Android가 요청하면 해당 파일을 연 앱의 설치 허용을 켜고 설치합니다.
3. `미니마작` 아이콘을 누른 뒤 `게임 시작`을 누릅니다. 비행기 모드에서도 실행됩니다.

Android 7.0 이상, ARM64 휴대폰 및 x86_64 에뮬레이터를 지원합니다. 가로 화면으로 실행됩니다. 현재 APK는 직접 설치용 개발 빌드이며 Google Play 배포용 서명은 별도 준비해야 합니다.

## 보존되는 값

- 최근 대국 결과와 움직임 줄이기 설정은 앱의 WebView 저장소에 보존됩니다.
- 현재 진행 중인 대국은 메모리에 있으므로 앱 프로세스가 종료되면 새 판으로 시작합니다.
- 홈 화면으로 이동할 때 일시정지합니다. 복귀 후 게임 재개를 누릅니다.
- 앱을 삭제하거나 앱 데이터를 지우면 보존 기록도 삭제됩니다.
- 웹 버전의 기록과 앱의 기록은 별도입니다.

## 빌드

JDK 17, Android SDK 35, Python 3를 설치한 환경에서 이 폴더를 Android Studio로 열거나 다음을 실행합니다. 최초 빌드에는 도구와 의존성 다운로드를 위한 인터넷 연결이 필요하며, 완성된 APK 실행에는 필요하지 않습니다.

```powershell
.\gradlew.bat assembleDebug
```

생성 위치: `app/build/outputs/apk/debug/app-debug.apk`

`prepareGameAssets`가 저장소 루트의 Python 엔진과 `web` 파일을 빌드 시 복사합니다. 앱 전용 통신 연결은 `app/src/main/offline/offline_transport.js`, Python 진입점은 `app/src/main/python/offline_engine.py`입니다. 원래 웹 서버를 실행하지 않고 Java 인터페이스로 상태 조회와 행동을 전달합니다.

`compileOfflineScripts`가 앱에 넣을 JavaScript를 Chrome 51 문법으로 변환합니다. Android 7~9의 오래된 WebView가 선택적 연결(`?.`), 객체 전개, async/await 등의 문법 때문에 시작 단계에서 멈추지 않게 합니다. `tools/compile_web.py`가 esbuild 0.25.12를 npm 공식 저장소에서 내려받고 무결성을 검사해 `.tools/`에 캐시합니다. Node.js/npm 설치는 필요하지 않습니다. Python 실행 파일을 지정하려면 `-PcompatPython=C:/path/to/python.exe`를 사용하세요.

v1.0.1에서는 구형 WebView용 문법 변환, 필요한 JavaScript API 보완, CSS Grid 대체 배치와 초기화 실패 안내를 추가했습니다. 서명과 앱 ID는 v1.0과 같아 APK로 업데이트할 수 있습니다.

## 확인

저장소 루트에서:

```powershell
python -m unittest discover -s tests
node --test tests/test_client.cjs
```

에뮬레이터 또는 USB 연결 기기를 비행기 모드로 바꾸고 Wi-Fi도 끈 뒤, 이 폴더에서:

```powershell
.\gradlew.bat connectedDebugAndroidTest
```

실기기 화면 크기와 터치감은 설치할 휴대폰에서 추가로 확인해야 합니다.

참고: [Chaquopy 공식 문서](https://chaquo.com/chaquopy/doc/current/android.html), [Android 로컬 화면 로딩 문서](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content).

# mini-mahjong

마작을 잘 모르는 초보자용 미니마작 게임입니다. 브라우저에서 AI와 동풍전을 진행하며, Python 표준 라이브러리로 웹 서버를 실행합니다.

## 로컬 실행

## Android 오프라인 앱

[APK와 설치 안내 다운로드](https://github.com/SeA9612/mini-mahjong/releases/tag/android-v1.0.0-beta.1)

인터넷 없이 실행되는 직접 설치용 테스트 APK입니다. 게임 화면과 Python 엔진이 앱에 포함됩니다. Android 7.0 이상 ARM64 기기를 대상으로 하며, Android 15 x86_64 에뮬레이터에서 비행기 모드 플레이 테스트를 진행했습니다. 실제 휴대폰의 화면과 터치감은 추가 확인이 필요합니다.

안드로이드 프로젝트와 빌드 방법은 [android/README.md](android/README.md)를 참고하세요.

## 웹 / PC 실행

브라우저 상태에서 게임을 실행 할 수 있습니다.
https://mini-mahjong.onrender.com

Python 3.10 이상에서 프로젝트 폴더를 열고 다음 명령을 실행하세요.

```powershell
python mazak.py
```

게임 화면이 브라우저에서 열립니다. 대국 중에는 리치, 치, 퐁, 깡, 론, 쯔모를 사용할 수 있습니다. 시작 화면에서 AI 난이도를 선택할 수 있고, 대국 결과와 움직임 설정은 브라우저에 보존됩니다.

## 공개 배포

이 게임은 Python 서버가 게임 진행을 처리하므로 GitHub Pages에 파일만 올려서는 실행되지 않습니다. Docker 또는 Python 서버를 지원하는 웹 호스팅에서 실행해야 합니다. 준비 및 배포 방법은 [DEPLOY.md](DEPLOY.md)를 참고하세요.

## 테스트

```powershell
python -m unittest discover -s tests
node --test tests/test_client.cjs
```

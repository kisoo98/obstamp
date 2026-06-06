# ⏺ 타임스탬프 핫키

OBS 녹화·방송 중 핫키를 누르면 현재 시간을 자동으로 기록해주는 프로그램입니다.
나중에 영상을 돌려볼 때 원하는 장면으로 바로 이동할 수 있습니다.

- **방송 중** → 방송 시간 · 실제 시각 기록 (`STREAM_*_timeline.txt`)
- **녹화 중** → 방송 시간 · 녹화 시간 · 실제 시각 기록 (`*_timeline.txt`)
- **방송 + 녹화 동시** → 두 파일에 각자 형식으로 동시 기록

---

## 폴더 구성

```
타임스탬프 핫키/
├── timestamp_hotkey.py     # 메인 프로그램 (소스)
├── 빌드.bat                # exe 빌드 스크립트 (PyInstaller)
├── requirements.txt        # 의존성 (pynput, obsws-python)
├── config.example.json     # 설정 템플릿 (복사해서 config.json 으로 사용)
├── README.md               # 이 문서
├── 변경이력.md             # 버전별 변경 기록
└── docs/
    └── 실행방법.txt        # 사용자용 설치·사용 안내
```

> `config.json`, 빌드 산출물(`*.exe`, `dist/`, `build/`), 생성되는 타임라인 파일은
> `.gitignore`로 제외됩니다. (`config.json`에는 OBS 비밀번호가 들어가므로 커밋하지 않습니다.)

---

## 개발자용 — 소스에서 실행 / 빌드

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 소스 실행

```bash
python timestamp_hotkey.py
```

### 3. exe 빌드

`빌드.bat` 더블클릭 (또는 아래 명령). PyInstaller로 단일 실행 파일을 생성합니다.

```bash
pyinstaller --onefile --windowed --uac-admin --name timestamp_hotkey \
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 \
  --hidden-import obsws_python --hidden-import websocket timestamp_hotkey.py
```

> `--uac-admin`: 다른 앱이 관리자 권한으로 떠 있어도 핫키가 동작하도록 exe가 관리자 권한을 요청합니다.

### 4. 설정 파일

최초 실행 시 `config.json`이 없으면 기본값으로 자동 생성됩니다.
직접 만들려면 `config.example.json`을 복사하세요.

```bash
cp config.example.json config.json
```

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `hotkey` | `<F8>` | 타임스탬프 기록 키 (예: `<F9>`, `<scroll_lock>`, `<ctrl>+<F8>`) |
| `obs_host` | `localhost` | OBS WebSocket 주소 |
| `obs_port` | `4455` | OBS WebSocket 포트 |
| `obs_password` | (없음) | OBS WebSocket 비밀번호 |
| `save_dir` | (녹화 파일과 같은 폴더) | 타임라인 파일 저장 위치 |

---

## 사용 방법 (요약)

1. OBS → 도구 → **WebSocket 서버 설정**에서 활성화 (포트 `4455`)
2. `timestamp_hotkey.exe` 실행 → ⚙ 에서 연결 테스트 후 저장
3. OBS에서 녹화/방송 시작 → 프로그램 자동 활성화
4. 기록할 장면에서 **F8**
5. 녹화/방송 종료 → 타임라인 파일 자동 저장

자세한 안내는 [`docs/실행방법.txt`](docs/실행방법.txt) 참고.

---

## 타임라인 파일 예시

**방송 (`STREAM_*_timeline.txt`)**

```
[001]  00:03:22.1    14:03:34
       방송시간       실제시각
```

**녹화 (`*_timeline.txt`)**

```
[001]  00:03:22.1    00:01:10.4    14:03:34
       방송시간       녹화시간       실제시각
```

변경 내역은 [`변경이력.md`](변경이력.md)를 참고하세요.

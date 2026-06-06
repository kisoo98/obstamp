"""
타임스탬프 핫키
OBS 녹화/방송 시작 → 자동 활성화 / 종료 → 자동 저장
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from pynput import keyboard as pynput_kb
    PYNPUT_OK = True
except ImportError:
    PYNPUT_OK = False

try:
    import obsws_python as obsws
    OBS_OK = True
except ImportError:
    OBS_OK = False

# ── 경로 ─────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent

CONFIG_FILE = _BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "hotkey":       "<F8>",
    "obs_host":     "localhost",
    "obs_port":     4455,
    "obs_password": "",
    "save_dir":     "",
}

# ── 색상 ─────────────────────────────────────────────────────────────────────
BG       = "#1a1a2e"
BAR      = "#0f3460"
RED      = "#e94560"
GREEN    = "#00ff88"
YELLOW   = "#f39c12"
BLUE     = "#7faaff"
PURPLE   = "#b388ff"
GRAY     = "#888888"
DARKGRAY = "#444444"

# ── 설정 ─────────────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def ms_to_str(ms: int) -> str:
    s, milli = divmod(ms, 1000)
    m, s     = divmod(s, 60)
    h, m     = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{milli//100}"

def tc_to_ms(tc: str) -> int:
    try:
        h, m, rest = tc.split(":")
        s, ms = rest.split(".")
        return (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms[:3])
    except Exception:
        return 0

# ── 타임라인 파일 ─────────────────────────────────────────────────────────────
class StreamTimeline:
    """방송 전용 파일: 방송시간 | 실제시각"""
    def __init__(self, path: Path):
        self.path    = path
        self.entries = []
        header = (
            f"# 방송 타임라인\n"
            f"# 기록 시작  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# {'─'*44}\n"
            f"# [번호]  방송 시간    실제 시각\n"
            f"# {'─'*44}\n"
        )
        self.path.write_text(header, encoding="utf-8")

    def add(self, stream_ms: int, now_str: str) -> str:
        idx  = len(self.entries) + 1
        s    = ms_to_str(stream_ms)
        line = f"[{idx:03d}]  {s}    {now_str}"
        self.entries.append(line)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return s

    def finalize(self):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"# {'─'*44}\n")
            f.write(f"# 기록 종료  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 총 기록    : {len(self.entries)}개\n")


class RecTimeline:
    """녹화 전용 파일: 방송시간 | 녹화시간 | 실제시각"""
    def __init__(self, path: Path, rec_name: str):
        self.path    = path
        self.entries = []
        header = (
            f"# 녹화 파일  : {rec_name}\n"
            f"# 기록 시작  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# {'─'*54}\n"
            f"# [번호]  방송 시간    녹화 시간    실제 시각\n"
            f"# {'─'*54}\n"
        )
        self.path.write_text(header, encoding="utf-8")

    def add(self, stream_ms: int | None, rec_ms: int, now_str: str) -> str:
        idx    = len(self.entries) + 1
        s_str  = ms_to_str(stream_ms) if stream_ms is not None else "--:--:--.--"
        r_str  = ms_to_str(rec_ms)
        line   = f"[{idx:03d}]  {s_str}    {r_str}    {now_str}"
        self.entries.append(line)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return r_str

    def finalize(self):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"# {'─'*54}\n")
            f.write(f"# 기록 종료  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 총 기록    : {len(self.entries)}개\n")

# ── OBS 연결 ─────────────────────────────────────────────────────────────────
class OBSLink:
    def __init__(self):
        self.req       = None
        self.evt       = None
        self.connected = False
        self.on_rec_start    = None  # callback(path)
        self.on_rec_stop     = None  # callback(path)
        self.on_stream_start = None  # callback()
        self.on_stream_stop  = None  # callback()

    def connect(self, host, port, password):
        self.disconnect()
        try:
            self.req = obsws.ReqClient(host=host, port=port,
                                       password=password, timeout=4)
            self.evt = obsws.EventClient(host=host, port=port,
                                         password=password)
            self.evt.callback.register([
                self._evt_record_state,
                self._evt_stream_state,
            ])
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self):
        self.connected = False
        for c in [self.evt, self.req]:
            try:
                if c: c.disconnect()
            except Exception:
                pass
        self.req = self.evt = None

    def get_full_status(self):
        """
        {
          rec_active: bool, rec_ms: int,
          stream_active: bool, stream_ms: int
        }  or None
        """
        if not self.connected or not self.req:
            return None
        try:
            r  = self.req.get_record_status()
            s  = self.req.get_stream_status()
            return {
                "rec_active":    r.output_active,
                "rec_ms":        tc_to_ms(r.output_timecode),
                "stream_active": s.output_active,
                "stream_ms":     tc_to_ms(s.output_timecode),
            }
        except Exception:
            self.connected = False
            return None

    def _evt_record_state(self, data):
        state = getattr(data, "output_state", "")
        path  = getattr(data, "output_path", None)
        if state == "OBS_WEBSOCKET_OUTPUT_STARTED" and self.on_rec_start:
            self.on_rec_start(path)
        elif state == "OBS_WEBSOCKET_OUTPUT_STOPPED" and self.on_rec_stop:
            self.on_rec_stop(path)

    def _evt_stream_state(self, data):
        state = getattr(data, "output_state", "")
        if state == "OBS_WEBSOCKET_OUTPUT_STARTED" and self.on_stream_start:
            self.on_stream_start()
        elif state == "OBS_WEBSOCKET_OUTPUT_STOPPED" and self.on_stream_stop:
            self.on_stream_stop()

# ── 메인 앱 ──────────────────────────────────────────────────────────────────
class App:
    ST_DISCONNECTED = "disconnected"
    ST_IDLE         = "idle"
    ST_ACTIVE       = "active"   # 녹화 or 방송 or 둘 다
    ST_DONE         = "done"

    def __init__(self):
        self.cfg  = load_config()
        self.obs  = OBSLink()
        self.obs.on_rec_start    = self._on_rec_start
        self.obs.on_rec_stop     = self._on_rec_stop
        self.obs.on_stream_start = self._on_stream_start
        self.obs.on_stream_stop  = self._on_stream_stop

        self.state      = self.ST_DISCONNECTED
        self.stream_tl: "StreamTimeline | None" = None
        self.rec_tl:    "RecTimeline | None"    = None

        self._is_rec    = False
        self._is_stream = False
        self._rec_ms    = 0
        self._stream_ms = 0

        self._last_stamp = ""
        self._stamp_cnt  = 0
        self._flash      = 0
        self._hotkey_obj = None

        self._build_ui()
        self._start_hotkey()
        threading.Thread(target=self._auto_connect, daemon=True).start()
        self._poll_loop()
        self.root.mainloop()

    # ══════════════════════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("타임스탬프 핫키")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        WIN_W = 300

        # 타이틀 바
        bar = tk.Frame(self.root, bg=BAR, cursor="fleur")
        bar.pack(fill="x")
        bar.bind("<ButtonPress-1>", lambda e: self._drag(e, "start"))
        bar.bind("<B1-Motion>",     lambda e: self._drag(e, "move"))
        tk.Label(bar, text="⏺ 타임스탬프 핫키", bg=BAR, fg=RED,
                 font=("맑은 고딕", 10, "bold")).pack(side="left", padx=8, pady=3)
        tk.Button(bar, text="✕", bg=BAR, fg=GRAY, relief="flat",
                  font=("Consolas", 10), command=self._quit,
                  activebackground=RED, activeforeground="white",
                  bd=0, padx=6).pack(side="right")
        tk.Button(bar, text="⚙", bg=BAR, fg=GRAY, relief="flat",
                  font=("Consolas", 10), command=self._open_settings,
                  activebackground=BAR, activeforeground="white",
                  bd=0, padx=6).pack(side="right")

        # 상태
        frm = tk.Frame(self.root, bg=BG)
        frm.pack(fill="x", padx=14, pady=(10, 4))
        self.dot = tk.Label(frm, text="⬤", font=("Consolas", 12),
                            bg=BG, fg=DARKGRAY)
        self.dot.pack(side="left")
        self.lbl_status = tk.Label(frm, text="OBS 연결 중...",
                                   font=("맑은 고딕", 10), bg=BG, fg=GRAY,
                                   anchor="w")
        self.lbl_status.pack(side="left", padx=(4, 0))

        # 연결 버튼 (항상 자리 차지, 색으로 show/hide)
        self.btn_connect = tk.Button(self.root, text="OBS 연결 설정",
                                     font=("맑은 고딕", 10, "bold"),
                                     bg=BG, fg=BG, relief="flat",
                                     command=self._open_settings,
                                     pady=4, cursor="", width=22, state="disabled")
        self.btn_connect.pack(pady=(0, 4))

        # 녹화 시간
        self.lbl_rec = tk.Label(self.root, text="00:00:00.0",
                                 font=("Consolas", 26, "bold"),
                                 bg=BG, fg=DARKGRAY, pady=2,
                                 width=12, anchor="center")
        self.lbl_rec.pack()

        # 방송 시간 (녹화 아래, 작게)
        self.lbl_stream = tk.Label(self.root, text=" ",
                                    font=("Consolas", 12),
                                    bg=BG, fg=DARKGRAY,
                                    width=20, anchor="center")
        self.lbl_stream.pack()

        # 핫키 안내
        self.lbl_hint = tk.Label(self.root,
                                  text=f"[ {self.cfg['hotkey']} ] 키로 타임스탬프 기록",
                                  font=("맑은 고딕", 9), bg=BG, fg=GRAY,
                                  width=36, anchor="center")
        self.lbl_hint.pack(pady=(4, 2))

        # 마지막 스탬프
        self.lbl_stamp = tk.Label(self.root, text="─────────────────────",
                                   font=("Consolas", 9), bg=BG, fg=GRAY,
                                   width=36, anchor="center")
        self.lbl_stamp.pack()

        # 파일명
        self.lbl_file = tk.Label(self.root, text=" ",
                                  font=("맑은 고딕", 8), bg=BG, fg=DARKGRAY,
                                  width=36, anchor="center")
        self.lbl_file.pack(pady=(2, 8))

        # 크기 고정 후 오른쪽 하단 배치
        self.root.update_idletasks()
        WIN_H = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{WIN_W}x{WIN_H}+{sw-WIN_W-20}+{sh-WIN_H-60}")
        self.root.minsize(WIN_W, WIN_H)
        self.root.maxsize(WIN_W, WIN_H)

        self._dx = self._dy = 0

    def _drag(self, e, mode):
        if mode == "start":
            self._dx, self._dy = e.x, e.y
        else:
            self.root.geometry(
                f"+{self.root.winfo_x()+e.x-self._dx}"
                f"+{self.root.winfo_y()+e.y-self._dy}"
            )

    def _btn_show(self, visible: bool):
        if visible:
            self.btn_connect.config(bg=BLUE, fg="white",
                                    state="normal", cursor="hand2")
        else:
            self.btn_connect.config(bg=BG, fg=BG,
                                    state="disabled", cursor="")

    # ══════════════════════════════════════════════════════════════════════════
    # 상태 전환
    # ══════════════════════════════════════════════════════════════════════════
    def _refresh_ui(self):
        """_is_rec / _is_stream 플래그를 보고 UI 갱신"""
        rec    = self._is_rec
        stream = self._is_stream
        active = rec or stream

        if not active:
            return  # poll_loop / set_state 에서 처리

        # 상태 점·텍스트
        if rec and stream:
            self.dot.config(fg=RED)
            self.lbl_status.config(text="● 녹화 중  +  🔴 방송 중", fg=RED)
        elif rec:
            self.dot.config(fg=RED)
            self.lbl_status.config(text="● 녹화 중", fg=RED)
        else:
            self.dot.config(fg=PURPLE)
            self.lbl_status.config(text="🔴 방송 중", fg=PURPLE)

        # 녹화 시간
        self.lbl_rec.config(
            text=ms_to_str(self._rec_ms) if rec else "──:──:──.─",
            fg=GREEN if rec else DARKGRAY
        )

        # 방송 시간
        if stream:
            self.lbl_stream.config(
                text=f"방송  {ms_to_str(self._stream_ms)}",
                fg=PURPLE
            )
        else:
            self.lbl_stream.config(text=" ", fg=DARKGRAY)

        # 핫키 안내
        self.lbl_hint.config(
            text=f"[ {self.cfg['hotkey']} ] 키로 타임스탬프 기록",
            fg=BLUE
        )

    def _set_state(self, state, **kw):
        self.state = state

        if state == self.ST_DISCONNECTED:
            self.dot.config(fg=RED)
            self.lbl_status.config(text="OBS 연결 안 됨", fg=RED)
            self.lbl_rec.config(text="00:00:00.0", fg=GRAY)
            self.lbl_stream.config(text=" ", fg=DARKGRAY)
            self.lbl_hint.config(text="OBS가 실행 중인지 확인 후 ⚙ 버튼을 누르세요", fg=GRAY)
            self.lbl_stamp.config(text="─────────────────────", fg=GRAY)
            self.lbl_file.config(text=" ", fg=DARKGRAY)
            self._btn_show(True)

        elif state == self.ST_IDLE:
            self.dot.config(fg=YELLOW)
            self.lbl_status.config(text="OBS 연결됨  |  대기 중", fg=YELLOW)
            self.lbl_rec.config(text="00:00:00.0", fg=GRAY)
            self.lbl_stream.config(text=" ", fg=DARKGRAY)
            self.lbl_hint.config(text="OBS 녹화 또는 방송을 시작하면 활성화됩니다", fg=GRAY)
            self.lbl_stamp.config(text="─────────────────────", fg=GRAY)
            self.lbl_file.config(text=" ", fg=DARKGRAY)
            self._btn_show(False)

        elif state == self.ST_ACTIVE:
            self._btn_show(False)
            fname = kw.get("filename", "")
            self.lbl_file.config(text=f"저장: {fname}" if fname else " ", fg=BLUE)
            self._refresh_ui()

        elif state == self.ST_DONE:
            self.dot.config(fg=GREEN)
            self.lbl_status.config(text="완료  |  파일 저장됨 ✔", fg=GREEN)
            self.lbl_rec.config(fg=GRAY)
            self.lbl_stream.config(text=" ", fg=DARKGRAY)
            self.lbl_hint.config(text="다음 녹화 또는 방송을 시작하면 활성화됩니다", fg=GRAY)
            filepath = kw.get("filepath", "")
            self.lbl_file.config(
                text=f"저장됨: {Path(filepath).name}" if filepath else " ",
                fg=GREEN
            )
            self._btn_show(False)

    # ══════════════════════════════════════════════════════════════════════════
    # OBS 연결
    # ══════════════════════════════════════════════════════════════════════════
    def _auto_connect(self):
        ok = self.obs.connect(
            self.cfg["obs_host"], self.cfg["obs_port"], self.cfg["obs_password"]
        )
        self.root.after(0, self._after_connect if ok
                        else lambda: self._set_state(self.ST_DISCONNECTED))

    def _after_connect(self):
        st = self.obs.get_full_status()
        if not st:
            self._set_state(self.ST_DISCONNECTED)
            return
        # 이미 방송/녹화 중이면 즉시 활성화
        if st["rec_active"]:
            self._on_rec_start(None)
        if st["stream_active"]:
            self._on_stream_start()
        if not st["rec_active"] and not st["stream_active"]:
            self._set_state(self.ST_IDLE)

    # ══════════════════════════════════════════════════════════════════════════
    # 녹화/방송 이벤트
    # ══════════════════════════════════════════════════════════════════════════
    def _base_dir(self, rec_path=None):
        save_dir = self.cfg.get("save_dir", "").strip()
        if save_dir:
            d = Path(save_dir)
        elif rec_path:
            d = Path(rec_path).parent
        else:
            d = _BASE_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _on_stream_start(self):
        if self._is_stream:
            return
        self._is_stream = True
        self._stream_ms = 0
        stem    = datetime.now().strftime("STREAM_%Y%m%d_%H%M%S")
        path    = self._base_dir() / f"{stem}_timeline.txt"
        self.stream_tl = StreamTimeline(path)
        self._update_active_ui()

    def _on_stream_stop(self):
        if not self._is_stream:
            return
        self._is_stream = False
        if self.stream_tl:
            self.stream_tl.finalize()
            self.stream_tl = None
        if not self._is_rec:
            self._check_done()

    def _on_rec_start(self, path):
        if self._is_rec:
            return
        self._is_rec = True
        self._rec_ms = 0
        stem     = Path(path).stem if path else datetime.now().strftime("REC_%Y%m%d_%H%M%S")
        rec_name = Path(path).name if path else stem
        tl_path  = self._base_dir(path) / f"{stem}_timeline.txt"
        self.rec_tl = RecTimeline(tl_path, rec_name)
        self._update_active_ui()

    def _on_rec_stop(self, path):
        if not self._is_rec:
            return
        self._is_rec = False
        # 실제 녹화 파일명으로 이름 변경
        if self.rec_tl and path:
            stem     = Path(path).stem
            new_path = self.rec_tl.path.parent / f"{stem}_timeline.txt"
            if new_path != self.rec_tl.path:
                try:
                    self.rec_tl.path.rename(new_path)
                    self.rec_tl.path = new_path
                except Exception:
                    pass
        if self.rec_tl:
            self.rec_tl.finalize()
            self.rec_tl = None
        if not self._is_stream:
            self._check_done()

    def _update_active_ui(self):
        files = []
        if self.stream_tl: files.append(self.stream_tl.path.name)
        if self.rec_tl:    files.append(self.rec_tl.path.name)
        fname = " / ".join(files)
        self.root.after(0, lambda: (
            self._set_state(self.ST_ACTIVE, filename=fname),
            self.lbl_stamp.config(text=f"[ {self.cfg['hotkey']} ] 키를 누르세요", fg=GRAY)
        ))

    def _check_done(self):
        """방송도 녹화도 없으면 완료 상태로"""
        if not self._is_rec and not self._is_stream:
            self._stamp_cnt  = 0
            self._last_stamp = ""
            self.root.after(0, lambda: self._set_state(self.ST_DONE))

    # ══════════════════════════════════════════════════════════════════════════
    # 핫키
    # ══════════════════════════════════════════════════════════════════════════
    def _start_hotkey(self):
        if not PYNPUT_OK:
            return
        if self._hotkey_obj:
            try: self._hotkey_obj.stop()
            except Exception: pass
        try:
            self._hotkey_obj = pynput_kb.GlobalHotKeys(
                {self.cfg["hotkey"]: lambda: self.root.after(0, self._stamp)}
            )
            self._hotkey_obj.start()
        except Exception:
            pass

    def _stamp(self):
        if self.state != self.ST_ACTIVE:
            return
        if not self.stream_tl and not self.rec_tl:
            return
        now_str   = datetime.now().strftime("%H:%M:%S")
        stream_ms = self._stream_ms if self._is_stream else None
        rec_ms    = self._rec_ms    if self._is_rec    else None
        display   = ""
        if self.stream_tl:
            display = self.stream_tl.add(self._stream_ms, now_str)
        if self.rec_tl:
            display = self.rec_tl.add(stream_ms, self._rec_ms, now_str)
        self._stamp_cnt += 1
        self._last_stamp = display
        self._flash      = 8
        self.lbl_stamp.config(
            text=f"★ {display}  기록됨!  (총 {self._stamp_cnt}개)",
            fg=RED
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 폴링 루프 (500ms)
    # ══════════════════════════════════════════════════════════════════════════
    def _poll_loop(self):
        st = self.obs.get_full_status()

        if st is None:
            if self.state != self.ST_DISCONNECTED:
                if self.stream_tl: self.stream_tl.finalize(); self.stream_tl = None
                if self.rec_tl:    self.rec_tl.finalize();    self.rec_tl    = None
                self._is_rec = self._is_stream = False
                self._set_state(self.ST_DISCONNECTED)
        else:
            rec_a    = st["rec_active"]
            stream_a = st["stream_active"]

            # 시간 갱신
            if rec_a:    self._rec_ms    = st["rec_ms"]
            if stream_a: self._stream_ms = st["stream_ms"]

            # 상태 변화 감지 (이벤트 누락 보완)
            if rec_a    and not self._is_rec:    self._on_rec_start(None)
            if stream_a and not self._is_stream: self._on_stream_start()
            if not rec_a    and self._is_rec:    self._on_rec_stop(None)
            if not stream_a and self._is_stream: self._on_stream_stop()

            # ACTIVE 중 시간 표시 갱신
            if self.state == self.ST_ACTIVE:
                self._refresh_ui()

            # IDLE/DONE 인데 아무것도 안 하는 상태
            if not rec_a and not stream_a:
                if self.state == self.ST_DISCONNECTED:
                    self._set_state(self.ST_IDLE)

        # 플래시
        if self._flash > 0:
            self._flash -= 1
            if self._flash == 0 and self._last_stamp:
                self.lbl_stamp.config(
                    text=f"마지막: {self._last_stamp}  |  총 {self._stamp_cnt}개",
                    fg=GRAY
                )

        self.root.after(500, self._poll_loop)

    # ══════════════════════════════════════════════════════════════════════════
    # 설정
    # ══════════════════════════════════════════════════════════════════════════
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("설정")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.grab_set()

        def section(text, row):
            tk.Label(win, text=text, bg=BG, fg=RED,
                     font=("맑은 고딕", 10, "bold")).grid(
                row=row, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 2))

        def field(label, var, row):
            tk.Label(win, text=label, bg=BG, fg="white",
                     font=("맑은 고딕", 10)).grid(
                row=row, column=0, sticky="w", padx=16, pady=5)
            e = tk.Entry(win, textvariable=var, bg="#0f3460", fg="white",
                         insertbackground="white", font=("Consolas", 10),
                         width=26, relief="flat")
            e.grid(row=row, column=1, pady=5, padx=(0, 4))

        v_host = tk.StringVar(value=self.cfg["obs_host"])
        v_port = tk.StringVar(value=str(self.cfg["obs_port"]))
        v_pw   = tk.StringVar(value=self.cfg["obs_password"])
        v_dir  = tk.StringVar(value=self.cfg.get("save_dir", ""))
        v_hk   = tk.StringVar(value=self.cfg["hotkey"])

        section("OBS WebSocket 설정", 0)
        tk.Label(win, text="OBS → 도구 → WebSocket 서버 설정에서 활성화하세요",
                 bg=BG, fg=GRAY, font=("맑은 고딕", 8)).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=16)
        field("서버 주소", v_host, 2)
        field("포트 번호", v_port, 3)
        field("비밀번호", v_pw,   4)

        section("저장 위치", 5)
        tk.Label(win, text="비워두면 OBS 녹화 파일과 같은 폴더에 저장됩니다",
                 bg=BG, fg=GRAY, font=("맑은 고딕", 8)).grid(
            row=6, column=0, columnspan=3, sticky="w", padx=16)
        dir_e = tk.Entry(win, textvariable=v_dir, bg="#0f3460", fg="white",
                         insertbackground="white", font=("Consolas", 9),
                         width=30, relief="flat")
        dir_e.grid(row=7, column=0, columnspan=2, padx=16, pady=5, sticky="w")
        tk.Button(win, text="폴더 선택", bg=BLUE, fg="white", relief="flat",
                  font=("맑은 고딕", 9), cursor="hand2", padx=6,
                  command=lambda: v_dir.set(
                      filedialog.askdirectory(title="저장 폴더 선택") or v_dir.get()
                  )).grid(row=7, column=2, padx=(0, 16))

        section("핫키", 8)
        tk.Label(win, text="예)  <F8>   <F9>   <scroll_lock>   <ctrl>+<F8>",
                 bg=BG, fg=GRAY, font=("맑은 고딕", 8)).grid(
            row=9, column=0, columnspan=3, sticky="w", padx=16)
        field("핫키", v_hk, 10)

        result_lbl = tk.Label(win, text="", bg=BG, font=("맑은 고딕", 9))
        result_lbl.grid(row=12, column=0, columnspan=3, pady=4)

        def apply():
            host = v_host.get().strip()
            try:
                port = int(v_port.get().strip() or "4455")
            except ValueError:
                result_lbl.config(text="⚠ 포트 번호가 올바르지 않습니다", fg=YELLOW)
                return
            result_lbl.config(text="연결 테스트 중...", fg=GRAY)
            win.update()
            self.obs.disconnect()
            ok = self.obs.connect(host, port, v_pw.get())
            if ok:
                self.cfg.update({
                    "obs_host": host, "obs_port": port,
                    "obs_password": v_pw.get(),
                    "save_dir": v_dir.get().strip(),
                    "hotkey": v_hk.get().strip(),
                })
                save_config(self.cfg)
                self._start_hotkey()
                self.lbl_hint.config(
                    text=f"[ {self.cfg['hotkey']} ] 키로 타임스탬프 기록")
                self._after_connect()
                result_lbl.config(text="✔ 연결 성공!  설정이 저장됐습니다", fg=GREEN)
                win.after(1200, win.destroy)
            else:
                result_lbl.config(
                    text="✕ 연결 실패  —  OBS WebSocket이 활성화됐는지 확인하세요",
                    fg=RED)
                self._set_state(self.ST_DISCONNECTED)

        tk.Button(win, text="연결 테스트 후 저장", command=apply,
                  bg=RED, fg="white", font=("맑은 고딕", 11, "bold"),
                  relief="flat", pady=6, cursor="hand2").grid(
            row=11, column=0, columnspan=3, padx=16, pady=(14, 4), sticky="ew")

        win.columnconfigure(1, weight=1)

    # ══════════════════════════════════════════════════════════════════════════
    # 종료
    # ══════════════════════════════════════════════════════════════════════════
    def _quit(self):
        if self.state == self.ST_ACTIVE and (self.stream_tl or self.rec_tl):
            if not messagebox.askyesno("종료 확인",
                    "녹화/방송이 진행 중입니다.\n타임스탬프 파일을 저장하고 종료할까요?",
                    parent=self.root):
                return
            if self.stream_tl: self.stream_tl.finalize()
            if self.rec_tl:    self.rec_tl.finalize()
        if self._hotkey_obj:
            try: self._hotkey_obj.stop()
            except Exception: pass
        self.obs.disconnect()
        self.root.destroy()


def check_deps():
    missing = []
    if not PYNPUT_OK: missing.append("pynput")
    if not OBS_OK:    missing.append("obsws-python")
    if missing:
        print(f"\n[오류] 필수 패키지 없음: {', '.join(missing)}")
        print("설치: pip install " + " ".join(missing))
        input("\nEnter 로 종료...")
        sys.exit(1)


if __name__ == "__main__":
    check_deps()
    App()

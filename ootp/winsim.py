"""
winsim.py - clone a pristine OOTP baseline league, auto-sim it, repeat.  (Windows)

Why cloning: OOTP autosaves at the end of every season and you cannot turn it off, so
simming a league permanently mutates it. And even with aging off, players retire, so a
league only yields ~10 usable seasons of the ORIGINAL rated cohort. To pool many samples
of "same player, same ratings -> different outcomes" you clone the pristine baseline
before EVERY run. Verified in the data: all pooled sources share identical player_ids
and all span 2016-2026, which is only possible if each run started from the same 2016 state.

    for each sample:
        copy <master>.lg  ->  <prefix>NN.lg      (master is NEVER simmed)
        drive OOTP: File -> Load Game -> select clone -> Play -> Specified Date -> AUTO-PLAY
        wait for dump_<year-1>_yearly to appear   (per-year CSV dump must be ON)

Then feed the clones' dump CSVs to ingest_dumps.py.

GUI automation is adapted from ootpalex/ootp-autosim (MIT) - macOS original. The macro
engine, edge-based template matching and dump-watching logic are his; the platform layer
(window/capture/click/keep-awake) is reimplemented for Windows.

Usage
    python ootp/winsim.py --game 27 --list                 # show leagues + which are pristine
    python ootp/winsim.py --game 27 --list-windows         # find OOTP's window title
    python ootp/winsim.py --game 27 --calibrate            # check button templates match
    python ootp/winsim.py --game 27 --grab                 # dump a screenshot to crop templates from
    python ootp/winsim.py --game 27 --master 6 --runs 3 --year 2026 --dry-run
    python ootp/winsim.py --game 27 --master 6 --runs 3 --year 2026
"""
import sys, os, time, shutil, argparse, re, ctypes
from pathlib import Path
from datetime import datetime, timedelta

HERE = Path(__file__).resolve().parent
BUTTONS = HERE / "buttons"

# ---------------------------------------------------------------- config
# Version-agnostic: we DISCOVER installed OOTP versions instead of hardcoding them, so a
# future OOTP 28/29 works with no code change. Two known saved_games layouts:
#   Documents\Out of the Park Developments\OOTP Baseball NN\saved_games   (modern, OOTP 27+)
#   <install>\data\saved_games                                            (legacy, e.g. C:\OOTP 26)
def _lg_count(p: Path):
    try:
        return sum(1 for d in p.glob("*.lg") if d.is_dir() and not d.name.startswith("."))
    except Exception:
        return 0

def discover_games():
    """{'27': {app, saved, title}, ...} for every OOTP install found on this machine."""
    cands = {}   # version -> list[Path]
    docs = Path.home() / "Documents" / "Out of the Park Developments"
    if docs.exists():
        for d in docs.glob("OOTP Baseball *"):
            m = re.search(r"(\d+)\s*$", d.name)
            if m and (d / "saved_games").is_dir():
                cands.setdefault(m.group(1), []).append(d / "saved_games")
    for root in (Path("C:/"), Path.home()):
        try:
            for d in root.glob("OOTP *"):
                m = re.search(r"(\d+)\s*$", d.name)
                if m and (d / "data" / "saved_games").is_dir():
                    cands.setdefault(m.group(1), []).append(d / "data" / "saved_games")
        except Exception:
            pass
    out = {}
    for ver, paths in cands.items():
        best = max(paths, key=_lg_count)          # the one actually holding leagues
        out[ver] = dict(app=f"OOTP Baseball {ver}", saved=best,
                        title=f"Out of the Park Baseball {ver}")
    return dict(sorted(out.items()))

GAMES = discover_games()

# Leagues that must NEVER be simmed or cloned-as-master: the real leagues you play.
# (A real league shows "no dumps" only because CSV export is off - that is NOT pristine.)
PROTECTED = {"blm", "thegrandestsalami", "new game"}

# Per-league setup lives here so a version move is a config edit, not a code change.
PROFILES_PATH = HERE / "leagues.json"
DEFAULT_PROFILES = {
    "BLM": {"game": "27", "master": "6", "prefix": "blm-run",
            "start_year": 2016, "target_year": 2026,
            "workbook": "The Sheets BLM/25 Regressions.xlsx"},
    "TGS": {"game": "26", "master": None, "prefix": "tgs-run",
            "start_year": 2016, "target_year": 2026,
            "workbook": "The Sheets TGS/25 Regressions.xlsx",
            "note": "No pristine OOTP 26 baseline remains; regressions are frozen. "
                    "When TGS moves to OOTP 27+: set game to the new version and master to a "
                    "fresh pristine TGS-settings baseline in that version's saved_games."}
}

def load_profiles():
    import json
    if not PROFILES_PATH.exists():
        PROFILES_PATH.write_text(json.dumps(DEFAULT_PROFILES, indent=2), encoding="utf-8")
        print(f"  (created {PROFILES_PATH.name} with defaults - edit it when you change versions)")
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))

LEAGUE_START_YEAR = 2016
TARGET_YEAR = 2026
SLEEP_SCALE = 0.6
SETTLE = 1.0
SENTINEL_POLL = 5.0
SIM_TIMEOUT = 6 * 3600
HEARTBEAT = 120
POPUP_POLL = 12
STALL_WARN = 600
NOSTART_ABORT = 420      # no dump at all this long after launch => sim never started on THIS clone
STALL_ABORT = 900        # dumps exist but none new this long => sim hung; give up on this clone
RESUME_AFTER = 180       # no new season this long => clear pop-ups and RE-ISSUE auto-play to resume
MAX_STUCK_REISSUE = 4    # consecutive re-issues that don't advance the year => give up on the clone
DEFAULT_PACE = 55
PAUSE_CAP = 900
MATCH_CONF = 0.85
WAIT_MINUTES = None
ROW_ANCHOR = "rows_anchor"

_newest = max(GAMES, key=int) if GAMES else None
SAVED = GAMES[_newest]["saved"] if _newest else Path(".")
WIN_TITLE = GAMES[_newest]["title"] if _newest else "Out of the Park Baseball"

MACRO = [
    ("activate",),
    ("dismiss", "nice_button"),
    ("load_row",),    # FILE->Load Game, click the clone's row at its computed position, Enter (deterministic)
    ("sleep", 9.0),
    ("auto_play",),   # Play -> Specified Date -> set year -> AUTO-PLAY (direct clicks, no Esc)
]

def macro_images():
    names = [ROW_ANCHOR, "file_menu", "load_game_item", "please_read", "play_menu",
             "specified_date", "year_dropdown", f"year_{TARGET_YEAR}", "autoplay"]
    for s in MACRO:
        if s[0] in ("click", "wait", "dismiss"):
            names.append(s[1])
        elif s[0] == "menu":
            names.extend([s[1], s[2]])
    out, seen = [], set()
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out

# ---------------------------------------------------------------- Windows platform layer
def make_dpi_aware():
    """Logical == physical pixels, so window rects, screenshots and clicks all agree."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def list_windows():
    import win32gui
    out = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t.strip():
                out.append((h, t))
    win32gui.EnumWindows(cb, None)
    return out

def find_ootp_hwnd():
    import win32gui
    want = WIN_TITLE.lower()
    best = None
    for h, t in list_windows():
        tl = t.lower()
        if want in tl or ("out of the park" in tl and "baseball" in tl):
            if win32gui.IsIconic(h):
                continue
            best = h
            if want in tl:
                return h
    return best

def activate_ootp():
    import win32gui, win32con, win32api
    h = find_ootp_hwnd()
    if not h:
        raise RuntimeError(f"OOTP window not found (looking for {WIN_TITLE!r}). Is it running? Try --list-windows")
    try:
        if win32gui.IsIconic(h):
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
        # a stray Alt tap satisfies Windows' foreground-change rule so SetForegroundWindow sticks
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(h)
        except Exception:
            win32gui.BringWindowToTop(h)
    except Exception:
        pass
    time.sleep(SETTLE)

def ootp_window_bounds():
    """(x, y, w, h) of OOTP's window in physical px (== logical, we're DPI-aware)."""
    import win32gui
    h = find_ootp_hwnd()
    if not h:
        return None
    l, t, r, b = win32gui.GetWindowRect(h)
    if r - l <= 0 or b - t <= 0:
        return None
    return (l, t, r - l, b - t)

def grab(region):
    """Screenshot a region -> (bgr_ndarray, scale). scale is 1.0 because we're DPI-aware."""
    import numpy as np, cv2
    from PIL import ImageGrab
    x, y, w, h = region
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    scale = arr.shape[1] / float(w) if w else 1.0
    return arr, scale

def release_modifiers():
    import pyautogui
    old = pyautogui.PAUSE; pyautogui.PAUSE = 0
    for k in ("ctrl", "shift", "alt", "win"):
        try:
            pyautogui.keyUp(k)
        except Exception:
            pass
    pyautogui.PAUSE = old

def release_mouse():
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def reset_input():
    release_modifiers(); release_mouse()

def keep_awake():
    ES_CONTINUOUS = 0x80000000; ES_SYSTEM_REQUIRED = 0x00000001; ES_DISPLAY_REQUIRED = 0x00000002
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        print("  keep-awake: display + system held awake for this process")
    except Exception as e:
        print(f"  (keep-awake failed: {e} - keep the screen on manually)")

_user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004

def _cursor_moves():
    """Can this process actually move the mouse? (No = OOTP is likely running elevated.)"""
    class PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    _user32.SetCursorPos(300, 300)
    time.sleep(0.05)
    p = PT(); _user32.GetCursorPos(ctypes.byref(p))
    return abs(p.x - 300) <= 3 and abs(p.y - 300) <= 3

def _native_click(x, y):
    """Hover -> down -> brief hold -> up (the sequence OOTP actually registers). ctypes = no throw."""
    x, y = int(round(x)), int(round(y))
    _user32.SetCursorPos(x, y)
    time.sleep(0.09)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

def do_click(x, y):
    release_modifiers()
    _native_click(x, y)
    time.sleep(0.10)

def do_double_click(x, y):
    """Two quick clicks at (x,y) - OOTP loads a saved game on a row double-click."""
    release_modifiers()
    x, y = int(round(x)), int(round(y))
    _user32.SetCursorPos(x, y); time.sleep(0.08)
    for _ in range(2):
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.05)
    time.sleep(0.10)

def press(key, n=1, interval=0.04):
    import pyautogui
    old = pyautogui.PAUSE; pyautogui.PAUSE = 0
    for _ in range(n):
        pyautogui.press(key); time.sleep(interval)
    pyautogui.PAUSE = old

def notify(msg, title="winsim"):
    print(f"  [{title}] {msg}")

# ---------------------------------------------------------------- template matching (from the mac original)
def _edges(gray):
    import cv2
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    return cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")

def locate(name, region, conf=MATCH_CONF):
    import cv2
    tpath = BUTTONS / f"{name}.png"
    tmpl = cv2.imread(str(tpath))
    if tmpl is None:
        raise FileNotFoundError(f"missing button image: {tpath}  (capture it: --grab, then crop)")
    img, scale = grab(region)
    tmpl = _edges(cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY))
    img = _edges(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if tmpl.shape[0] > img.shape[0] or tmpl.shape[1] > img.shape[1]:
        return None, 0.0
    res = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    if maxv < conf:
        return None, maxv
    th, tw = tmpl.shape[:2]
    return (region[0] + (maxloc[0] + tw / 2) / scale,
            region[1] + (maxloc[1] + th / 2) / scale), maxv

def wait_locate(name, timeout, conf=MATCH_CONF, poll=0.7):
    t0, best = time.time(), 0.0
    while time.time() - t0 < timeout:
        reg = ootp_window_bounds()
        if reg:
            pt, s = locate(name, reg, conf)
            best = max(best, s)
            if pt:
                return pt, s
        time.sleep(poll)
    raise TimeoutError(f"'{name}' did not appear within {timeout}s (best {best:.2f})")

def click_img(name, timeout=20, conf=MATCH_CONF):
    pt, s = wait_locate(name, timeout, conf)
    print(f"    click {name} ({s:.2f}) @ ({pt[0]:.0f},{pt[1]:.0f})")
    do_click(*pt)

def click_if_present(name, timeout=8, conf=MATCH_CONF, poll=0.7):
    if not (BUTTONS / f"{name}.png").exists():
        print(f"    (no {name}.png yet - skipping this optional pop-up)")
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        reg = ootp_window_bounds()
        if reg:
            pt, s = locate(name, reg, conf)
            if pt:
                print(f"    dismiss {name} ({s:.2f})")
                do_click(*pt); return True
        time.sleep(poll)
    print(f"    {name} not present - continuing")
    return False

def ensure_open(opener, verify, attempts=5, settle=0.9, use_esc=False, conf=MATCH_CONF):
    import pyautogui
    for i in range(attempts):
        if use_esc:
            pyautogui.press("esc"); time.sleep(0.3 * SLEEP_SCALE)
        click_img(opener)
        time.sleep(settle * SLEEP_SCALE)
        reg = ootp_window_bounds()
        pt, s = (locate(verify, reg, conf) if reg else (None, 0.0))
        if pt:
            return pt, s
        print(f"    '{verify}' not visible after '{opener}' ({s:.2f}); retry {i+1}/{attempts}")
    raise TimeoutError(f"'{verify}' never appeared after '{opener}' x{attempts}")

def open_menu(opener, item, use_esc=True, **kw):
    pt, s = ensure_open(opener, item, use_esc=use_esc, **kw)
    print(f"    click {item} ({s:.2f})")
    do_click(*pt)

def open_load_list(attempts=5):
    import pyautogui
    def header():
        reg = ootp_window_bounds()
        pt, s = (locate(ROW_ANCHOR, reg) if reg else (None, 0.0))
        return pt, s
    for i in range(attempts):
        pt, s = header()
        if pt:
            return
        print(f"    FILE -> Load Game [{i+1}/{attempts}]")
        reset_input()
        click_img("file_menu"); time.sleep(0.6)
        reg = ootp_window_bounds()
        lg, sc = (locate("load_game_item", reg) if reg else (None, 0.0))
        if not lg:
            print(f"    Load Game not found ({sc:.2f})"); pyautogui.press("escape"); continue
        do_click(*lg)
        for _ in range(8):
            time.sleep(0.6)
            pt, s = header()
            if pt:
                print(f"    -> list up ({s:.2f})"); return
    raise TimeoutError("Saved Games list never appeared via FILE -> Load Game")

# ---------------------------------------------------------------- saved games
def saved_league_names():
    return sorted((p.stem for p in SAVED.glob("*.lg")
                   if p.is_dir() and not p.name.startswith(".")), key=str.lower)

def league_dir(name):
    return SAVED / f"{name}.lg"

def dump_years(lg):
    return sorted(int(p.name.split("_")[1]) for p in (lg / "dump").glob("dump_*_yearly")
                  if p.name.split("_")[1].isdigit())

def is_pristine(lg):
    return not dump_years(lg)

def row_index_of(name):
    names = saved_league_names()
    if name not in names:
        raise SystemExit(f"league {name!r} not found in {SAVED}\n  available: {', '.join(names)}")
    return names.index(name), len(names)

def keyboard_select_row(idx, total):
    press("up", total + 5); time.sleep(0.3)
    press("down", idx); time.sleep(0.2)

ROW0_OFFSET = 21.0   # header-anchor center -> first data row (index 0) center, in screen px
ROW_STEP    = 20.2   # vertical gap between adjacent rows, in screen px

def row_point(idx):
    """Screen point of Load-Game row `idx`, anchored on the list header (ROW_ANCHOR)."""
    reg = ootp_window_bounds()
    hp, s = (locate(ROW_ANCHOR, reg) if reg else (None, 0.0))
    if not hp:
        return None
    return (hp[0], hp[1] + ROW0_OFFSET + idx * ROW_STEP)

def load_by_row_click(name):
    """Open Load Game, CLICK the target row at its computed position to SELECT it (deterministic,
    no keyboard nav, no dependence on the prior selection), then ENTER (= default OK) to load.
    Requires the row to be VISIBLE (not scrolled off) - the auto-loop only ever loads row 0 (the
    fresh clone, named to sort first) and Baseline (near the top), both always on screen."""
    open_load_list()
    idx, total = row_index_of(name)
    p = row_point(idx)
    if not p:
        raise TimeoutError("list header not located - can't compute row position")
    print(f"    load {name}: click row {idx}/{total} @ ({p[0]:.0f},{p[1]:.0f}), then Enter")
    do_click(*p); time.sleep(0.5)          # select the exact row
    release_modifiers(); press("enter")    # Enter = default OK button = load the selected game
    time.sleep(1.0 * SLEEP_SCALE)

def select_row_by_name(name):
    open_load_list()
    idx, total = row_index_of(name)
    print(f"    {name} = row {idx}/{total}")
    # Click into the list BODY first to give the list keyboard focus, THEN the proven reset (up past
    # the top) + step down. Without the focus click, blind up/down occasionally did nothing and the
    # previously-loaded (already-simmed) league stayed selected, so Enter reloaded a stale one.
    reg = ootp_window_bounds()
    hp, s = (locate(ROW_ANCHOR, reg) if reg else (None, 0.0))
    if hp:
        do_click(hp[0], hp[1] + 160); time.sleep(0.35)            # focus the list widget
    else:
        print("    (list header not located - relying on blind keyboard nav)")
    keyboard_select_row(idx, total)                               # up-to-top, then down to target

def _snap(tag):
    """Save a diagnostic screenshot of the OOTP window (best-effort)."""
    try:
        import cv2
        r = ootp_window_bounds()
        if r:
            img, _ = grab(r); cv2.imwrite(str(HERE / f"_diag_{tag}.png"), img)
            print(f"    (saved diagnostic ootp/_diag_{tag}.png)")
    except Exception as e:
        print(f"    (diag snap failed: {e})")

def set_year():
    # Open the year list and CLICK the target year, wherever it renders. We used to reject a match
    # near the top of the list (guard against a wrong/already-simmed league being loaded), but that
    # also rejected RESUMING a mid-year league (where the target sits only a few rows down). A stale
    # load now just auto-plays to an already-reached year (a no-op) and is caught by NOSTART_ABORT.
    if TARGET_YEAR - LEAGUE_START_YEAR < 0:
        raise SystemExit(f"--year {TARGET_YEAR} is before --start-year {LEAGUE_START_YEAR}")
    click_img("year_dropdown"); time.sleep(1.2 * SLEEP_SCALE)      # drop the year list open
    if not (BUTTONS / f"year_{TARGET_YEAR}.png").exists():
        raise SystemExit(f"missing button image: year_{TARGET_YEAR}.png  (capture it with --grab)")
    reg = ootp_window_bounds()
    pt, s = (locate(f"year_{TARGET_YEAR}", reg) if reg else (None, 0.0))
    if not pt:
        raise TimeoutError(f"year {TARGET_YEAR} not found in the list (best {s:.2f})")
    print(f"    click year {TARGET_YEAR} ({s:.2f}) @ ({pt[0]:.0f},{pt[1]:.0f})")
    do_click(*pt)
    time.sleep(0.5 * SLEEP_SCALE)

def auto_play_to_year():
    """Play -> Specified Date -> set year -> AUTO-PLAY, all by DIRECT clicks. (open_menu's
    Esc-reset was arriving after the date dialog opened and closing it, so we don't use it.)"""
    click_img("play_menu"); time.sleep(1.0 * SLEEP_SCALE)          # open the Play menu
    reg = ootp_window_bounds()
    pt, s = (locate("specified_date", reg) if reg else (None, 0.0))
    if not pt:
        raise TimeoutError(f"'specified_date' not visible after Play menu (best {s:.2f})")
    print(f"    click specified_date ({s:.2f})")
    do_click(*pt); time.sleep(1.2 * SLEEP_SCALE)                   # AUTO-PLAY TO DATE dialog opens
    set_year()                                                    # pick the target year
    time.sleep(0.3 * SLEEP_SCALE)
    click_img("autoplay")                                         # start the sim

def run_macro(ctx):
    import pyautogui
    for step in MACRO:
        op = step[0]
        if op == "activate":       activate_ootp()
        elif op == "sleep":        time.sleep(step[1] * SLEEP_SCALE)
        elif op == "click":        click_img(step[1])
        elif op == "dismiss":      click_if_present(step[1], timeout=step[2] if len(step) > 2 else 8)
        elif op == "auto_play":    auto_play_to_year()
        elif op == "menu":         open_menu(step[1], step[2], use_esc=True)
        elif op == "key":
            release_modifiers()
            for _ in range(step[2] if len(step) > 2 else 1):
                pyautogui.press(step[1])
        elif op == "select_league": select_row_by_name(ctx["league"])
        elif op == "load_row":     load_by_row_click(ctx["league"])
        elif op == "set_year":     set_year()
        else: raise ValueError(f"unknown macro op {op}")
        time.sleep(0.3 * SLEEP_SCALE)

# ---------------------------------------------------------------- sim lifecycle
def sentinel_path(lg):
    # auto-playing TO 1/1/<TARGET_YEAR> finishes the <TARGET_YEAR-1> season, so the last
    # per-year dump written is dump_<TARGET_YEAR-1>_yearly - that's the completion signal.
    return lg / "dump" / f"dump_{TARGET_YEAR - 1}_yearly" / "csv" / "players_career_batting_stats.csv"

def latest_dump_year(lg):
    ys = dump_years(lg)
    return max(ys) if ys else None

def dismiss_please_read(conf=0.90):
    import pyautogui
    if not (BUTTONS / "please_read.png").exists():
        return False
    reg = ootp_window_bounds()
    if not reg:
        return False
    pt, s = locate("please_read", reg, conf)
    if not pt:
        return False
    print(f"    PLEASE READ modal ({s:.2f}) - pressing OK")
    activate_ootp(); release_modifiers(); pyautogui.press("enter")
    return True

def clear_sim_blockers():
    """Auto-play PAUSES on pop-ups mid-sim - most importantly the 'CONGRATULATIONS!' achievement
    modal (NICE! button) but also 'PLEASE READ'. Clear whichever is up so the sim keeps going.
    Quick and non-blocking (a single locate per template); returns True if it cleared something."""
    import pyautogui
    reg = ootp_window_bounds()
    if not reg:
        return False
    hit = False
    if (BUTTONS / "nice_button.png").exists():
        pt, s = locate("nice_button", reg)
        if pt:
            print(f"    mid-sim CONGRATULATIONS ({s:.2f}) - clicking NICE! to resume")
            do_click(*pt); hit = True
    if (BUTTONS / "please_read.png").exists():
        pt, s = locate("please_read", reg, 0.90)
        if pt:
            print(f"    mid-sim PLEASE READ ({s:.2f}) - pressing OK to resume")
            activate_ootp(); release_modifiers(); pyautogui.press("enter"); hit = True
    return hit

def wait_for_sim(lg, resume=None, timeout=SIM_TIMEOUT):
    # Watch dump_<year> files appear until we hit the sentinel (target-1). A mid-sim achievement
    # pop-up doesn't just pause auto-play, it ENDS it - so on a stall we clear the pop-up AND, if a
    # `resume` callback was given (auto_play_to_year), RE-ISSUE auto-play to carry the sim onward.
    if WAIT_MINUTES is not None:
        print(f"    waiting a fixed {WAIT_MINUTES} min ...")
        time.sleep(WAIT_MINUTES * 60); return True
    s = sentinel_path(lg)
    t0, last_hb, last_pop = time.time(), 0.0, 0.0
    seen, advanced = latest_dump_year(lg), time.time()
    last_resume, stuck_reissues = time.time(), 0
    while time.time() - t0 < timeout:
        if s.exists() and s.stat().st_size > 0:
            time.sleep(3); return True
        now = time.time()
        if now - last_pop > POPUP_POLL:
            last_pop = now
            try: clear_sim_blockers()      # NICE!/PLEASE READ pop-ups pause auto-play mid-sim
            except Exception: pass
        ly = latest_dump_year(lg)
        if ly != seen:
            seen, advanced, stuck_reissues = ly, now, 0     # real progress -> reset the stuck count
        # no dump AT ALL for a while -> the sim never started on this clone (bad load) -> give up
        if seen is None and now - t0 > NOSTART_ABORT:
            raise TimeoutError(f"no dump appeared for {lg.stem} in {NOSTART_ABORT//60} min - the "
                               f"sim never started on it (wrong league loaded, or click-through missed)")
        # progress stalled -> clear blockers and RE-ISSUE auto-play (achievement pop-ups kill it)
        if seen is not None and now - advanced > RESUME_AFTER and now - last_resume > RESUME_AFTER:
            last_resume = now; stuck_reissues += 1
            print(f"    {lg.stem} stalled at {seen} - clear pop-ups + re-issue auto-play "
                  f"(reissue #{stuck_reissues})")
            try:
                clear_sim_blockers(); time.sleep(1.0)
                if resume: resume()
            except Exception as e:
                print(f"      resume hiccup (will retry): {e}")
            if stuck_reissues >= MAX_STUCK_REISSUE:
                raise TimeoutError(f"{lg.stem} stuck at {seen}: {stuck_reissues} re-issues with no "
                                   f"new season - giving up on this clone")
        if now - last_hb > HEARTBEAT:
            last_hb = now
            print(f"    ... {lg.stem} {ly or '-'}/{TARGET_YEAR}  ({int(now-t0)//60}m in)")
        time.sleep(SENTINEL_POLL)
    return False

# ---------------------------------------------------------------- clone + run
def guard(name):
    if name.strip().lower() in PROTECTED:
        raise SystemExit(f"REFUSING to sim protected league {name!r} (pristine master / real league).")

def clone_master(master, dest_name, dry=False):
    src, dst = league_dir(master), league_dir(dest_name)
    if not src.exists():
        raise SystemExit(f"master {master!r} not found at {src}")
    if not is_pristine(src):
        raise SystemExit(f"master {master!r} has dumps {dump_years(src)} - it is SPENT, not pristine. "
                         f"Cloning it cannot reproduce the {LEAGUE_START_YEAR} cohort.")
    if dst.exists():
        raise SystemExit(f"clone target {dest_name!r} already exists at {dst} - pick another --prefix/--runs")
    mb = sum(f.stat().st_size for f in src.rglob('*') if f.is_file()) / 1e6
    print(f"  clone {master}.lg -> {dest_name}.lg   ({mb:.0f} MB)")
    if dry:
        return dst
    # Pre-flight: the MASTER must not be the league currently loaded in OOTP —
    # a loaded league holds locks on its db files and the copy dies partway
    # (the 2026-08-18 run-1 failure: Baseline was loaded at 10:04, copy died at
    # 10:11). The correct starting state is OOTP sitting INSIDE some OTHER
    # league (live copy, old clone, ...) so FILE -> Load Game is available AND
    # the master is closed. Probe the lock-prone files up front.
    probes = list((src / "mp").glob("*.sqlite3*")) + list(src.glob("*.dat"))
    for probe in probes:
        try:
            with open(probe, "rb") as fh:
                fh.read(1)
        except OSError as e:
            raise SystemExit(
                f"cannot read {probe.name} - the MASTER ({master}) looks like the league "
                f"currently LOADED in OOTP. Load any OTHER league in OOTP (winsim needs "
                f"FILE -> Load Game, so stay inside a league - just not this master), "
                f"then rerun. ({e})")
    done = [0]
    def _cp(s_, d_):
        shutil.copy2(s_, d_)
        done[0] += 1
        if done[0] % 20000 == 0:
            print(f"    ... {done[0]:,} files copied - the copy is ALIVE, do not close this window")
    try:
        shutil.copytree(src, dst, copy_function=_cp)
    except BaseException:
        # never leave a half-clone behind - calibrate would skip it but the name is burned
        print(f"  copy FAILED/interrupted after {done[0]:,} files - removing partial {dest_name}.lg")
        shutil.rmtree(dst, ignore_errors=True)
        raise
    print(f"    copy complete: {done[0]:,} files")
    return dst

def _names_ever_used():
    """Clone names that must NEVER be reused, even after the save was deleted.
    calibrate.py's archive dedups clones BY NAME (calib/<LG>/archived_clones.txt),
    so a fresh clone that reuses an archived name is silently refused from the
    pool - the sim runs, the data goes nowhere (bit the 2026-08-18 grind run:
    '0tgs02' was archived in July, deleted after, then reused). Union every
    ledger we have; unknown ledgers simply contribute nothing."""
    used = set()
    for txt in (HERE.parent / "tgs-viz" / "engine" / "calib").glob("*/archived_clones.txt"):
        try:
            used |= {ln.strip() for ln in open(txt, encoding="utf-8") if ln.strip()}
        except OSError:
            pass
    try:
        import json as _json
        for entries in _json.load(open(HERE / "ingested.json", encoding="utf-8")).values():
            used |= set(entries)
    except Exception:
        pass
    return used


def next_free_names(prefix, n):
    have = set(saved_league_names()) | _names_ever_used()
    out, i = [], 1
    while len(out) < n:
        nm = f"{prefix}{i:02d}"
        if nm not in have:
            out.append(nm)
        i += 1
        if i > 999:
            raise SystemExit("could not find free clone names")
    return out

def run_one(master, clone_name, dry=False):
    guard(clone_name)
    lg = clone_master(master, clone_name, dry=dry)
    if dry:
        print(f"  [dry] would load {clone_name} and auto-play {LEAGUE_START_YEAR} -> {TARGET_YEAR}")
        return
    print(f"  driving OOTP: load {clone_name} -> auto-play to 1/1/{TARGET_YEAR} ...")
    run_macro({"league": clone_name})
    print(f"  sim launched; waiting for dump_{TARGET_YEAR - 1}_yearly ...")
    if not wait_for_sim(lg, resume=auto_play_to_year):
        raise TimeoutError(f"{clone_name}: sim did not reach {TARGET_YEAR} in time")
    # the end-of-run CONGRATULATIONS box appears a few sec after the last dump; clear it so
    # the next clone can drive File->Load Game unobstructed. Waits up to 30s for it to show.
    time.sleep(2.0)
    click_if_present("nice_button", timeout=30)
    print(f"  OK {clone_name} done  (dumps: {dump_years(lg)})")

# ---------------------------------------------------------------- main
def main():
    global SAVED, WIN_TITLE, TARGET_YEAR, LEAGUE_START_YEAR, SLEEP_SCALE, WAIT_MINUTES, BUTTONS
    make_dpi_aware()

    ap = argparse.ArgumentParser(description="Clone a pristine OOTP baseline and auto-sim it, repeatedly (Windows).")
    ap.add_argument("--league", default=None, help="use a profile from leagues.json (e.g. BLM) for game/master/years/prefix")
    ap.add_argument("--games", action="store_true", help="list the OOTP versions discovered on this machine")
    ap.add_argument("--game", default=None, help="OOTP version, e.g. 27 (auto-discovered; overrides the profile)")
    ap.add_argument("--saved", default=None, help="override saved_games dir")
    ap.add_argument("--title", default=None, help="override OOTP window title substring")
    ap.add_argument("--master", default=None, help="pristine baseline league to clone (e.g. 6)")
    ap.add_argument("--prefix", default="run", help="clone name prefix (default 'run' -> run01, run02 ...)")
    ap.add_argument("--runs", type=int, default=1, help="how many clone+sim samples to produce")
    ap.add_argument("--year", type=int, default=None, help=f"auto-play each clone to 1/1/<year> (default {TARGET_YEAR})")
    ap.add_argument("--start-year", type=int, default=None, help=f"year the baseline starts (default {LEAGUE_START_YEAR})")
    ap.add_argument("--wait-minutes", type=int, default=None, help="skip dump detection; wait N minutes per clone")
    ap.add_argument("--speed", type=float, default=None, help="scale UI pauses (default 0.6)")
    ap.add_argument("--buttons", default=None, help="override button-template dir")
    ap.add_argument("--list", action="store_true", help="list saved leagues and which are pristine")
    ap.add_argument("--list-windows", action="store_true", help="list visible window titles (find OOTP's)")
    ap.add_argument("--calibrate", action="store_true", help="check button templates match on screen")
    ap.add_argument("--grab", action="store_true", help="save a screenshot of OOTP's window to crop templates from")
    ap.add_argument("--delay", type=int, default=0, help="with --grab: bring OOTP to front, count down N seconds "
                    "(open a menu during the countdown), then capture")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; clone nothing, click nothing")
    ap.add_argument("--clone-only", action="store_true", help="just make the clone leagues (no OOTP driving) - "
                    "for when you want to sim them by hand")
    ap.add_argument("--test-year", action="store_true", help="diagnostic: on the CURRENTLY-loaded league, open "
                    "Play->Specified Date and try to set the year (no clone, no sim, no AUTO-PLAY)")
    ap.add_argument("--peek-load", action="store_true", help="diagnostic: open FILE->Load Game and snapshot the "
                    "saved-games list so we can see what ORDER OOTP shows them in (vs our alphabetical index)")
    ap.add_argument("--test-load", default=None, help="diagnostic: LOAD this saved game by double-clicking its "
                    "computed row, then snapshot (verifies deterministic row-position loading)")
    a = ap.parse_args()

    if a.games:
        if not GAMES:
            raise SystemExit("no OOTP installs found")
        print("OOTP versions discovered:")
        for v, g in GAMES.items():
            print(f"  {v}: {g['saved']}   ({_lg_count(g['saved'])} leagues)   window~{g['title']!r}")
        return

    # profile supplies defaults; explicit flags win
    prof = {}
    if a.league:
        profiles = load_profiles()
        if a.league not in profiles:
            raise SystemExit(f"no profile {a.league!r} in {PROFILES_PATH} (have: {', '.join(profiles)})")
        prof = profiles[a.league]
        if prof.get("note"):
            print(f"  note[{a.league}]: {prof['note']}")

    ver = a.game or prof.get("game") or (_newest or "")
    if not a.saved and ver not in GAMES:
        raise SystemExit(f"OOTP {ver!r} not found. Discovered: {', '.join(GAMES) or '(none)'}  (use --games / --saved)")
    g = GAMES.get(ver, {})
    SAVED = Path(a.saved) if a.saved else g["saved"]
    WIN_TITLE = a.title or g.get("title", WIN_TITLE)
    if a.buttons: BUTTONS = Path(a.buttons)
    TARGET_YEAR = a.year if a.year is not None else prof.get("target_year", TARGET_YEAR)
    LEAGUE_START_YEAR = a.start_year if a.start_year is not None else prof.get("start_year", LEAGUE_START_YEAR)
    if a.speed is not None: SLEEP_SCALE = a.speed
    WAIT_MINUTES = a.wait_minutes
    if not a.master and prof.get("master"):
        a.master = str(prof["master"])
    if a.prefix == "run" and prof.get("prefix"):
        a.prefix = prof["prefix"]

    if a.list_windows:
        for h, t in list_windows():
            print(f"  0x{h:08x}  {t}")
        return

    if a.list:
        print(f"saved_games: {SAVED}")
        if not SAVED.exists():
            raise SystemExit("  (does not exist)")
        for n in saved_league_names():
            lg = league_dir(n)
            ys = dump_years(lg)
            mb = sum(f.stat().st_size for f in lg.rglob('*') if f.is_file()) / 1e6
            protected = n.strip().lower() in PROTECTED
            if protected:
                # no dump/ dir here just means CSV export is off - NOT that it's unsimmed
                tag = "REAL LEAGUE - never sim, never clone"
            elif not ys:
                tag = "PRISTINE -> clonable master"
            else:
                tag = f"spent {ys[0]}-{ys[-1]} (cohort aged; not clonable)"
            print(f"  {n:22} {mb:7.0f} MB  {tag}")
        return

    if a.grab:
        import cv2
        activate_ootp(); time.sleep(0.6)
        if a.delay > 0:
            print(f"\n  OOTP is now in front. Open the menu/screen you want captured NOW.")
            for s in range(a.delay, 0, -1):
                print(f"    capturing in {s}...", end="\r", flush=True); time.sleep(1)
            print("    capturing now!            ")
        reg = ootp_window_bounds()
        if not reg: raise SystemExit("couldn't read OOTP window - is it open? try --list-windows")
        img, _ = grab(reg)
        out = HERE / "winsim_grab.png"
        cv2.imwrite(str(out), img)
        print(f"saved {out}  (window {reg}) - crop button templates into {BUTTONS}/")
        return

    if a.test_load:
        activate_ootp(); time.sleep(0.4)
        for _ in range(4):
            press("escape"); time.sleep(0.3)
        load_by_row_click(a.test_load)
        time.sleep(3.0); _snap("loaded")
        print(f"\nTEST-LOAD done - check ootp/_diag_loaded.png: did {a.test_load!r} load?")
        return

    if a.peek_load:
        activate_ootp(); time.sleep(0.4)
        for _ in range(4):                                        # clear any leftover dialog first
            press("escape"); time.sleep(0.3)
        names = saved_league_names()
        target = next((n for n in reversed(names) if n.startswith(a.prefix)), names[-1])
        select_row_by_name(target)                                # exercise the REAL selection path
        time.sleep(0.5); _snap("load_list")
        print(f"\nPEEK: selected {target!r} (row {names.index(target)}/{len(names)}).")
        print("Check ootp/_diag_load_list.png: is THAT row the highlighted one?  Our order:")
        for i, n in enumerate(names):
            print(f"  {i:2}  {n}{'   <- should be highlighted' if n == target else ''}")
        for _ in range(3):
            press("escape"); time.sleep(0.3)                      # close the list without loading
        return

    if a.calibrate:
        import pyautogui
        names = macro_images()
        have = [n for n in names if (BUTTONS / f"{n}.png").exists()]
        print(f"Button images in {BUTTONS}/ ({len(have)}/{len(names)} present):")
        for n in names:
            print(f"  {'OK  ' if n in have else 'MISS'} {n}.png")
        reg = ootp_window_bounds()
        if not reg:
            print("\n[live match skipped] OOTP window not found."); return
        print(f"\nLive match - window {reg}")
        for n in have:
            pt, s = locate(n, reg)
            if pt:
                pyautogui.moveTo(pt[0], pt[1], duration=0.2)
                print(f"  [ok {s:.2f}] {n}")
            else:
                print(f"  [NOT FOUND {s:.2f}] {n}  (wrong screen showing, or recapture it)")
        print("\n(Buttons for screens not currently showing read NOT FOUND - that's expected.)")
        return

    if not a.master:
        raise SystemExit("pass --master <pristine league> (see --list), e.g. --master 6")
    guard(a.master)  # never let the master be used as a sim target name
    names = next_free_names(a.prefix, a.runs)

    print(f"winsim: OOTP {ver} | saved={SAVED}")
    print(f"  master={a.master} (pristine)  runs={a.runs}  {LEAGUE_START_YEAR} -> {TARGET_YEAR}")
    print(f"  clones: {', '.join(names)}")
    if a.dry_run:
        print("\nDRY RUN - nothing copied, nothing clicked.\n")
        for n in names:
            run_one(a.master, n, dry=True)
        print(f"\n  completion signal: dump_{TARGET_YEAR - 1}_yearly/csv/players_career_batting_stats.csv")
        print(f"  buttons required: {', '.join(macro_images())}")
        return

    if a.clone_only:
        made = [clone_master(a.master, n) for n in names]
        print(f"\n  made {len(made)} clone(s): {', '.join(names)}")
        print("  Now in OOTP: load each one and auto-play to 1/1/"
              f"{TARGET_YEAR} (CSV-export-after-season must be ON).")
        print("  When they're simmed, run the ingester to pull them into the sheet.")
        return

    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
    reset_input()

    # preflight: confirm we can actually drive the mouse. If not, OOTP is almost
    # certainly running elevated (as administrator) and is blocking our input.
    activate_ootp()
    if _cursor_moves() and a.test_year:
        print("TEST YEAR: Play -> Specified Date -> set year (NO auto-play), then snapshot.")
        for _ in range(4):                                        # clear any leftover dialog/list
            press("escape"); time.sleep(0.35)
        click_img("play_menu"); time.sleep(1.0 * SLEEP_SCALE)
        reg = ootp_window_bounds()
        pt, s = (locate("specified_date", reg) if reg else (None, 0.0))
        if not pt:
            print(f"    specified_date not found (best {s:.2f})"); return
        do_click(*pt); time.sleep(1.2 * SLEEP_SCALE)
        set_year()
        time.sleep(0.4); _snap("after_setyear")
        print("\nTEST YEAR done - check ootp\\_diag_after_setyear.png: does the dialog read the target year?")
        return
    if not _cursor_moves():
        raise SystemExit(
            "\n  Can't move the mouse to control OOTP.\n"
            "  This almost always means OOTP is running AS ADMINISTRATOR, so Windows\n"
            "  blocks a normal program from clicking it. Two fixes (either works):\n"
            "    - Right-click '4 - Sim TGS.bat' -> Run as administrator, OR\n"
            "    - Close OOTP and reopen it normally (not as admin), then try again.\n"
            + ("  (You are NOT running this as admin right now.)\n" if not is_admin() else ""))

    print("Abort: slam mouse into a screen corner (FAILSAFE) or Ctrl-C.")
    keep_awake()
    done, failed = [], []
    for i, n in enumerate(names, 1):
        print(f"\n=== run {i}/{len(names)}: {n} ===")
        try:
            run_one(a.master, n)
            done.append(n)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            failed.append(n)
            print(f"  !! {n} FAILED: {e}")
            print(f"  cleaning up the UI (escape x4) and moving on to the next clone...")
            try:
                activate_ootp()
                for _ in range(4):
                    press("escape"); time.sleep(0.4)
                click_if_present("nice_button", timeout=5)        # in case a congrats is up
            except Exception as e2:
                print(f"     (cleanup hiccup, continuing: {e2})")
    print(f"\nALL DONE. {len(done)} ok, {len(failed)} failed.")
    if done:   print("  ok:     " + ", ".join(done))
    if failed: print("  failed: " + ", ".join(failed) + "  (their clone folders are unused - safe to delete)")
    print("Now run the ingester on the new clones.")

if __name__ == "__main__":
    main()

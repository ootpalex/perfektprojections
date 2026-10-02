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

Then Grind / Recalibrate run tgs-viz/engine/calibrate.py on the clones' dump CSVs.

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

Continuous mode (one long-lived league, simmed in place, no clone):
    python ootp/winsim.py --league DEV --sim --dry-run           # print the plan
    python ootp/winsim.py --league DEV --test-year               # set the date, no AUTO-PLAY
    python ootp/winsim.py --league DEV --sim [--years N] [--start-year Y]

After a stopped or killed sim (the Control page runs this itself):
    python ootp/winsim.py --reset-input        # release Ctrl, Shift, Alt, Win and the mouse button

OOTP folders: discovered as below, then ootp.installs.<ver>.saved_games from the
settings (tgs-viz/tools/settings.py) wins when that folder exists. PROTECTED and
the extra profiles of leagues added by New League also come from the settings.
"""
import sys, os, time, shutil, argparse, re, ctypes, statistics
from pathlib import Path
from datetime import datetime, timedelta

HERE = Path(__file__).resolve().parent
BUTTONS = HERE / "buttons"
sys.path.insert(0, str(HERE.parent / "tgs-viz" / "tools"))
import settings as ST  # noqa: E402  (OOTP folders, protected saves, extra profiles)

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
    # a saved_games folder set in the settings (ootp.installs.<ver>) wins when it exists
    for ver in (ST.load().get("ootp") or {}).get("installs") or {}:
        p = ST.saved_games(ver)
        if p and Path(p).is_dir():
            out[ver] = dict(app=f"OOTP Baseball {ver}", saved=Path(p),
                            title=f"Out of the Park Baseball {ver}")
    return dict(sorted(out.items()))

GAMES = discover_games()

# Leagues that must NEVER be simmed or cloned-as-master: the real leagues you play.
# (A real league shows "no dumps" only because CSV export is off - that is NOT pristine.)
# Settings: ootp.protected_extra plus the save of every online and local-export league,
# disabled ones included. Never a dev league: --sim runs guard() on its own folder.
PROTECTED = ST.protected_saves()   # today {"blm", "thegrandestsalami", "new game", "regular game"}

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
                    "fresh pristine TGS-settings baseline in that version's saved_games."},
    "DEV": {"game": "27", "mode": "continuous", "folder": "DEV TESTS", "source": "dump",
            "years": 5,
            "note": "Plain OOTP 27 league, all teams AI, simmed in place year after year. "
                    "Its yearly CSV dump is the data source (no clone, no StatsPlus)."}
}

def load_profiles():
    """leagues.json plus the ootp_profile of every league New League added
    (settings). The file wins on a clash."""
    import json
    if not PROFILES_PATH.exists():
        PROFILES_PATH.write_text(json.dumps(DEFAULT_PROFILES, indent=2), encoding="utf-8")
        print(f"  (created {PROFILES_PATH.name} with defaults - edit it when you change versions)")
    return ST.ootp_profiles()

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

MACRO_CONT = [               # continuous mode: the load only; auto-play follows in run_continuous
    ("activate",),
    ("dismiss", "nice_button"),
    ("load_row",),        # FILE->Load Game, click the league's row, Enter
    ("wait_reload",),     # the PLAY menu goes away while OOTP loads, then comes back
    ("snap", "loaded"),   # ootp/_diag_loaded.png: which league came up
]

def macro_images(continuous=False):
    names = [ROW_ANCHOR, "file_menu", "load_game_item", "please_read", "play_menu",
             "specified_date", "year_dropdown", "autoplay"]
    if not continuous:
        names.append(f"year_{TARGET_YEAR}")
    for s in (MACRO_CONT if continuous else MACRO):
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

MAX_VISIBLE_ROW = 25   # Load Game rows below this can sit off-screen; a click there is a guess

def ingame_date(name):
    """(month, day, year) of the in-game date OOTP lists for saved game `name`.
    Read from saved_games.dat (the Load Game list's index). None when not found."""
    try:
        b = (SAVED / "saved_games.dat").read_bytes()
    except OSError:
        return None
    key = re.escape(f"{name}.lg".encode("utf-8"))
    best = None
    for m in re.finditer(key, b):
        if m.start() > 0 and b[m.start() - 1] == ord("\\"):
            continue                                   # inside a full path, not the bare entry
        tail = b[m.end(): m.end() + 200]
        nxt = tail.find(b".lg")
        if nxt >= 0:
            tail = tail[:nxt]                          # stay inside this league's entry
        d = re.search(rb"(\d{1,2})/(\d{1,2})/(\d{4})", tail)
        if d:
            best = (int(d[1]), int(d[2]), int(d[3]))
    return best

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
    if idx > MAX_VISIBLE_ROW:
        press("escape")
        raise SystemExit(f"{name!r} is row {idx} of {total} in the Load Game list and may be "
                         f"off-screen. Delete or rename saves so it sorts within the first "
                         f"{MAX_VISIBLE_ROW} rows.")
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

def wait_reload(gone_within=12.0, back_within=240.0):
    """Wait for OOTP to finish loading a saved game. The PLAY menu leaves the screen while the
    load runs and returns when the league is up. A load too fast to catch is treated as done."""
    t0 = time.time()
    gone = False
    while time.time() - t0 < gone_within:
        reg = ootp_window_bounds()
        pt, _ = (locate("play_menu", reg) if reg else (None, 0.0))
        if not pt:
            gone = True
            break
        time.sleep(0.5)
    if not gone:
        print(f"    (PLAY menu never left the screen in {gone_within:.0f}s - assuming a fast load)")
        time.sleep(4.0)
        return
    print("    loading ... (PLAY menu gone)")
    wait_locate("play_menu", back_within, poll=1.0)
    print(f"    league up after {time.time() - t0:.0f}s")
    time.sleep(3.0)

def run_macro(ctx, macro=None):
    import pyautogui
    for step in (macro or MACRO):
        op = step[0]
        if op == "activate":       activate_ootp()
        elif op == "sleep":        time.sleep(step[1] * SLEEP_SCALE)
        elif op == "click":        click_img(step[1])
        elif op == "dismiss":      click_if_present(step[1], timeout=step[2] if len(step) > 2 else 8)
        elif op == "auto_play":    auto_play_to_year()
        elif op == "auto_play_cont": auto_play_continuous()
        elif op == "wait_reload":  wait_reload()
        elif op == "snap":         _snap(step[1])
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

def wait_for_sim(lg, resume=None, timeout=SIM_TIMEOUT, watch=None):
    # Watch dump_<year> files appear until we hit the sentinel (target-1). A mid-sim achievement
    # pop-up doesn't just pause auto-play, it ENDS it - so on a stall we clear the pop-up AND, if a
    # `resume` callback was given (auto_play_to_year), RE-ISSUE auto-play to carry the sim onward.
    # `watch` (optional) runs every poll and may raise to abort the wait (continuous mode).
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
        if watch:
            watch()
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

# ---------------------------------------------------------------- continuous mode (one long-lived league)
# A plain league simmed in place, year after year: no clone, no pristine check. Each run loads
# it, auto-plays to 1/1/<target> and stops when dump_<target-1>_yearly is on disk. The year is
# picked by READING the dialog's year list (its top row is the year the league sits in, the
# rows step one year each), with digit glyphs cut out of that same list on the first run. So no
# year_<NNNN>.png is ever needed, and a wrong league on screen is caught before AUTO-PLAY.
CONT = {}                  # the active plan (continuous_plan)
TEXT_BRIGHT = 150          # gray level that counts as text on OOTP's grey lists
GLYPH_CANVAS = (16, 20)    # (w, h) every digit is centred on before comparing
CHEVRON_W = 26             # right part of year_dropdown.png = a date box's chevron
ACTIVITY_DIRS = ("", "temp", "news", "news/html", "news/html/leagues", "news/html/box_scores",
                 "messages", "auto-save", "page_links")   # what OOTP writes while a league is open

def digits_dir():
    return BUTTONS / "digits"

def _gray(img):
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

def _text_run(band, gap=6):
    """(x0, x1) of the widest run of text columns in a gray strip, or None."""
    import numpy as np
    cols = np.where((band > TEXT_BRIGHT).any(axis=0))[0]
    if len(cols) == 0:
        return None
    groups = [[int(cols[0])]]
    for c in cols[1:]:
        if c - groups[-1][-1] > gap:
            groups.append([int(c)])
        else:
            groups[-1].append(int(c))
    g = max(groups, key=lambda g: g[-1] - g[0])
    return g[0], g[-1] + 1

def _glyph(cell):
    """One digit cell -> float canvas: tight crop, scaled to a fixed height, centred.
    None when the cell holds no text."""
    import cv2, numpy as np
    rows = np.where((cell > TEXT_BRIGHT).any(axis=1))[0]
    cols = np.where((cell > TEXT_BRIGHT).any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    g = cell[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].astype("float32")
    cw, ch = GLYPH_CANVAS
    h = ch - 2
    w = max(1, min(cw - 2, int(round(g.shape[1] * h / g.shape[0]))))
    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
    can = np.full((ch, cw), float(cell.min()), "float32")
    x, y = (cw - w) // 2, (ch - h) // 2
    can[y:y + h, x:x + w] = g
    return can

def _digit_cells(band, n=4):
    """Split the widest text run of a gray strip into n equal digit cells, or None."""
    ext = _text_run(band)
    if not ext:
        return None
    xa, xb = ext
    p = int(round((xb - xa + 1) / n))
    if p < 4 or abs((xa + n * p - 1) - xb) > 2:
        return None
    return [band[:, xa + i * p: xa + i * p + p - 1] for i in range(n)]

def _corr(a, b):
    import numpy as np
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float((a * b).sum() / d)

def load_glyphs():
    """{'0': canvas, ..., '9': canvas} from buttons/digits/, or None until all ten exist."""
    import cv2
    out = {}
    for d in "0123456789":
        p = digits_dir() / f"{d}.png"
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
        if g is not None:
            c = _glyph(g)
            if c is not None:
                out[d] = c
    return out if len(out) == 10 else None

def read_year(band, glyphs):
    """OCR a four-digit year from a gray strip. Returns (year, worst_score), or (None, best)
    when a digit is not a clear match."""
    cells = _digit_cells(band)
    if not cells:
        return None, 0.0
    text, worst = "", 1.0
    for cell in cells:
        g = _glyph(cell)
        if g is None:
            return None, 0.0
        ranked = sorted(((_corr(g, t), d) for d, t in glyphs.items()), reverse=True)
        (s1, d1), (s2, _) = ranked[0], ranked[1]
        if s1 < 0.85 or s1 - s2 < 0.08:
            return None, s1
        text += d1
        worst = min(worst, s1)
    return int(text), worst

def _row_band(pop, i):
    """Gray strip of row i of an open list (see open_popup)."""
    y = pop["rows_win"][i]
    return _gray(pop["img"])[max(0, y - 9): y + 10, pop["x0"]:pop["x1"]]

def harvest_glyphs(pop, first_year):
    """Cut the digit glyphs 0-9 out of the open year list and save them to buttons/digits/.
    Row i reads first_year + i; ten consecutive years show every digit. Every harvested row
    must read back as its own label, or the set is rejected."""
    import cv2, numpy as np
    found = {}
    for i in range(min(len(pop["rows_win"]), 14)):
        cells = _digit_cells(_row_band(pop, i))
        if not cells:
            continue
        for cell, ch in zip(cells, str(first_year + i)):
            if ch in found:
                continue
            rows = np.where((cell > TEXT_BRIGHT).any(axis=1))[0]
            cols = np.where((cell > TEXT_BRIGHT).any(axis=0))[0]
            if len(rows) and len(cols):
                found[ch] = cell[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    if len(found) < 10:
        raise RuntimeError(f"only {len(found)} of 10 digits found in the year list "
                           f"({len(pop['rows_win'])} rows) - see ootp/_diag_year_list.png")
    d = digits_dir()
    d.mkdir(parents=True, exist_ok=True)
    for ch, crop in found.items():
        cv2.imwrite(str(d / f"{ch}.png"), crop)
    glyphs = load_glyphs()
    for i in range(min(len(pop["rows_win"]), 10)):
        got, s = read_year(_row_band(pop, i), glyphs)
        if got != first_year + i:
            raise RuntimeError(f"digit self-check failed: row {i} reads {got} not {first_year + i} "
                               f"({s:.2f}) - see ootp/_diag_year_list.png")
    print(f"    digit glyphs 0-9 saved to {d} (rows labelled from {first_year}; self-check OK)")
    return glyphs

def _check_list_with_templates(pop, first_year):
    """First run only: prove the year list starts at first_year with any year_<NNNN>.png that
    falls on it. Raises when that row does not show the year the template says."""
    import cv2
    checked = False
    for tpath in sorted(BUTTONS.glob("year_*.png")):
        tag = tpath.stem.split("_", 1)[1]
        if not tag.isdigit():
            continue
        j = int(tag) - first_year
        if not 0 <= j < len(pop["rows_win"]):
            continue
        tmpl = cv2.imread(str(tpath))
        y = pop["rows_win"][j]
        crop = pop["img"][max(0, y - 12): y + 13, pop["x0"]:pop["x1"]]
        if tmpl is None or crop.shape[0] < tmpl.shape[0] or crop.shape[1] < tmpl.shape[1]:
            continue
        res = cv2.matchTemplate(_edges(_gray(crop)), _edges(_gray(tmpl)), cv2.TM_CCOEFF_NORMED)
        _, s, _, _ = cv2.minMaxLoc(res)
        if s < MATCH_CONF:
            press("escape")
            raise SystemExit(f"row {j} of the year list should read {tag} if the list starts at "
                             f"{first_year}, but {tpath.name} does not match there ({s:.2f}). "
                             f"Wrong league on screen, or the saved date is off. Nothing was clicked.")
        print(f"    year list row {j} reads {tag} ({s:.2f}) - list confirmed to start at {first_year}")
        checked = True
    if not checked:
        print(f"    (no year_<NNNN>.png falls on this list; glyph labels rest on the saved date {first_year})")

def dialog_boxes():
    """Click points inside the day, month and year boxes of the AUTO-PLAY TO DATE dialog.
    The boxes sit one row above the AUTO-PLAY button and each ends in a chevron; the chevron
    (cut from year_dropdown.png) is matched along that row. Measured offsets are the fallback."""
    import cv2
    (ax, ay), _ = wait_locate("autoplay", 10)
    guess = [(ax - 38, ay - 31.5), (ax + 78, ay - 31.5), (ax + 162, ay - 31.5)]
    pts = None
    tmpl = cv2.imread(str(BUTTONS / "year_dropdown.png"))
    win = ootp_window_bounds()
    if tmpl is not None and win:
        chev = tmpl[:, tmpl.shape[1] - CHEVRON_W:]
        x0 = max(win[0], int(ax - 110)); y0 = max(win[1], int(ay - 52))
        x1 = min(win[0] + win[2], int(ax + 230)); y1 = min(win[1] + win[3], int(ay - 10))
        img, _ = grab((x0, y0, x1 - x0, y1 - y0))
        res = cv2.matchTemplate(_edges(_gray(img)), _edges(_gray(chev)), cv2.TM_CCOEFF_NORMED)
        hits = []
        for _ in range(3):
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv < 0.8:
                break
            hits.append((x0 + ml[0] + chev.shape[1] / 2, y0 + ml[1] + chev.shape[0] / 2, mv))
            cv2.rectangle(res, (ml[0] - 15, ml[1] - 10), (ml[0] + 15, ml[1] + 10), 0, -1)
        if len(hits) == 3:
            hits.sort()
            print("    date boxes (chevrons): " + ", ".join(f"({x:.0f},{y:.0f}) {s:.2f}" for x, y, s in hits))
            pts = [(x, y) for x, y, _ in hits]
    if pts is None:
        print("    date boxes: chevrons not all found, using measured offsets from AUTO-PLAY")
        pts = guess
    return [(x - 12, y) for x, y in pts]     # a point inside each box, left of its chevron

def open_popup(pt, label):
    """Click the closed box at pt and read the list that opens: the screen region that changed
    is the list, its bright lines are the rows. Returns rows (screen points, top to bottom),
    the rows' window y, the list's window x-extent and the grab it was read from."""
    import cv2, numpy as np
    reg = ootp_window_bounds()
    if not reg:
        raise TimeoutError("OOTP window not found")
    before, _ = grab(reg)
    do_click(*pt)
    time.sleep(1.2 * SLEEP_SCALE)
    after, _ = grab(reg)
    g0 = _gray(before).astype("int16")
    g1 = _gray(after).astype("int16")
    bx = int(pt[0] - reg[0])
    changed = (np.abs(g1 - g0) > 30).astype("uint8")
    lo, hi = max(0, bx - 150), min(changed.shape[1], bx + 150)
    changed[:, :lo] = 0
    changed[:, hi:] = 0
    changed = cv2.dilate(changed, np.ones((9, 9), "uint8"))
    n, _, stats, _ = cv2.connectedComponentsWithStats(changed)
    if n < 2:
        raise TimeoutError(f"{label}: nothing opened after the click")
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x0, y0, w, h = (int(v) for v in stats[i, :4])
    x1, y1 = x0 + w, y0 + h
    prof = (g1[y0:y1, x0:x1] > TEXT_BRIGHT).sum(axis=1)
    rows, r0 = [], None
    for y, v in enumerate(prof):
        if v >= 2 and r0 is None:
            r0 = y
        elif v < 2 and r0 is not None:
            if y - r0 >= 5:
                rows.append(y0 + (r0 + y) / 2)
            r0 = None
    if r0 is not None and len(prof) - r0 >= 5:
        rows.append(y0 + (r0 + len(prof)) / 2)
    if len(rows) < 2:
        raise TimeoutError(f"{label}: a list opened ({w}x{h}) but no rows were found")
    pitch = statistics.median(b - a for a, b in zip(rows, rows[1:]))
    if not 14 <= pitch <= 34:
        raise TimeoutError(f"{label}: row pitch {pitch:.1f}px looks wrong ({len(rows)} rows)")
    cx = reg[0] + (x0 + x1) / 2
    print(f"    {label}: {len(rows)} rows, pitch {pitch:.1f}px, first row at y={reg[1] + rows[0]:.0f}")
    return dict(rows=[(cx, reg[1] + y) for y in rows], rows_win=[int(round(y)) for y in rows],
                x0=x0, x1=x1, img=after, reg=reg, pitch=pitch)

def set_date_jan1(target, expect_year):
    """In the AUTO-PLAY TO DATE dialog, set 1 / January / target. Reads the year list first:
    its top row is the year the loaded league sits in and must be within a year of
    expect_year, or nothing is clicked (that means the wrong league is on screen)."""
    day_pt, mon_pt, year_pt = dialog_boxes()
    reg = ootp_window_bounds()
    def box_strip():
        img, _ = grab(reg)
        x, y = int(year_pt[0] - reg[0]), int(year_pt[1] - reg[1])
        return _gray(img)[max(0, y - 10): y + 11, max(0, x - 50): x - 6]
    strip_before = box_strip()
    pop = open_popup(year_pt, "year list")
    glyphs = load_glyphs()
    if glyphs is None:
        _check_list_with_templates(pop, expect_year)
        _snap("year_list")
        glyphs = harvest_glyphs(pop, expect_year)
    shown, sc = read_year(_row_band(pop, 0), glyphs)
    if shown is None:
        _snap("year_list")
        press("escape")
        raise SystemExit(f"cannot read the top of the year list (score {sc:.2f}) - see "
                         f"ootp/_diag_year_list.png. Nothing was clicked.")
    if abs(shown - expect_year) > 1:
        press("escape")
        raise SystemExit(f"the league on screen sits in {shown}, expected about {expect_year}. "
                         f"Is {CONT.get('folder', '?')!r} really the loaded league? Nothing was clicked.")
    k = target - shown
    if k < 1:
        press("escape")
        raise SystemExit(f"target {target} is not after the league's year {shown}")
    if k >= len(pop["rows"]):
        press("escape")
        raise SystemExit(f"{target} is below the visible year list ({len(pop['rows'])} rows from "
                         f"{shown}); use fewer --years")
    print(f"    year list starts at {shown} ({sc:.2f}); click row {k} = {target}")
    do_click(*pop["rows"][k])
    time.sleep(0.8 * SLEEP_SCALE)
    strip_after = box_strip()
    got, s2 = read_year(strip_after, glyphs)
    if got is not None and got != target:
        press("escape")
        raise SystemExit(f"the year box reads {got} after the pick, not {target}. Nothing was auto-played.")
    if got is None:
        import numpy as np
        same = strip_after.shape == strip_before.shape and \
            float(np.abs(strip_after.astype("int16") - strip_before.astype("int16")).mean()) < 2.0
        if same:
            press("escape")
            raise SystemExit("the year box did not change after the pick. Nothing was auto-played.")
        print(f"    year box changed but reads unclear ({s2:.2f}); trusting the list click")
    else:
        print(f"    year box reads {got} ({s2:.2f})")
    for pt, label in ((mon_pt, "month list"), (day_pt, "day list")):
        p = open_popup(pt, label)
        do_click(*p["rows"][0])                 # January / 1: the top row of each list
        time.sleep(0.6 * SLEEP_SCALE)

def _expected_dialog_year():
    ys = dump_years(CONT["lg"])
    return ys[-1] + 1 if ys else CONT["dialog_year"]

def auto_play_continuous():
    """Play -> Specified Date -> 1/1/<target> (read off the screen) -> AUTO-PLAY."""
    click_img("play_menu")
    time.sleep(1.0 * SLEEP_SCALE)
    reg = ootp_window_bounds()
    pt, s = (locate("specified_date", reg) if reg else (None, 0.0))
    if not pt:
        raise TimeoutError(f"'specified_date' not visible after Play menu (best {s:.2f})")
    print(f"    click specified_date ({s:.2f})")
    do_click(*pt)
    time.sleep(1.2 * SLEEP_SCALE)
    set_date_jan1(TARGET_YEAR, _expected_dialog_year())
    time.sleep(0.3 * SLEEP_SCALE)
    click_img("autoplay")

def wait_dump_settled(d, quiet=15, timeout=900):
    """Return once nothing under dump folder d has changed for `quiet` seconds."""
    last, since, t0 = None, time.time(), time.time()
    while time.time() - t0 < timeout:
        sig = tuple((p.name, p.stat().st_size) for p in sorted(d.rglob("*")) if p.is_file())
        if sig != last:
            last, since = sig, time.time()
        elif time.time() - since >= quiet:
            return True
        time.sleep(3)
    return False

def _touch_time(lg):
    """Newest mtime among the folders OOTP writes while a league is open."""
    t = 0.0
    for sub in ACTIVITY_DIRS:
        try:
            t = max(t, (lg / sub if sub else lg).stat().st_mtime)
        except OSError:
            pass
    return t

def make_wrong_league_watch(lg, t_start):
    """wait_for_sim watch: if another saved game's folder starts changing while ours does not,
    OOTP is simming the wrong league. Raise at once so the user can stop it."""
    others = [league_dir(n) for n in saved_league_names() if league_dir(n) != lg]
    def watch():
        if _touch_time(lg) > t_start:
            return
        for o in others:
            if _touch_time(o) > t_start:
                press("escape")
                raise SystemExit(f"OOTP is writing into {o.stem!r}, not {lg.stem!r}: the WRONG league is "
                                 f"being simmed. Stop OOTP now (Esc, or close it WITHOUT saving) and "
                                 f"check the Load Game row with --test-load \"{lg.stem}\".")
    return watch

def _year_range(ys):
    return f"{ys[0]}-{ys[-1]}" if len(ys) > 1 else (str(ys[0]) if ys else "none")

def continuous_plan(a, prof):
    """Work out this run: which league, the first season to sim, the target year."""
    folder = a.folder or prof.get("folder")
    if not folder:
        raise SystemExit("continuous mode needs the league's saved-game name: add \"folder\" to the "
                         "profile in leagues.json or pass --folder")
    guard(folder)
    # never sim a profile's pristine clone master in place: that spends it
    try:
        import json as _json
        _profs = _json.loads(Path(PROFILES_PATH).read_text(encoding="utf-8"))
        _masters = {str(v.get("master")).strip().lower() for v in _profs.values()
                    if isinstance(v, dict) and v.get("master")}
    except Exception:
        _masters = set()
    if folder.strip().lower() in _masters:
        raise SystemExit(f"{folder!r} is a pristine clone master in leagues.json; continuous mode "
                         "would spend it. Clone it under another name first.")
    lg = league_dir(folder)
    if not lg.exists():
        raise SystemExit(f"league {folder!r} not found at {lg}\n  available: {', '.join(saved_league_names())}")
    years = int(a.years if a.years is not None else prof.get("years", 5))
    if years < 1:
        raise SystemExit("--years must be at least 1")
    have = dump_years(lg)
    date = ingame_date(folder)
    if have:
        first, dialog_year, why = have[-1] + 1, have[-1] + 1, f"latest dump is {have[-1]}"
    elif a.start_year is not None:
        first, why = a.start_year, "--start-year"
        dialog_year = date[2] if date else first
    elif date:
        m, d, y = date
        first, dialog_year = (y + 1 if m >= 11 else y), y
        why = f"in-game date {m}/{d}/{y} in saved_games.dat"
    else:
        raise SystemExit(f"{folder!r} has no dumps yet and its in-game date could not be read: "
                         f"pass --start-year <first season to sim>")
    return dict(folder=folder, lg=lg, years=years, have=have, date=date,
                first=first, target=first + years, dialog_year=dialog_year, why=why)

def run_continuous(a, prof, ver):
    global TARGET_YEAR, LEAGUE_START_YEAR, RESUME_AFTER, NOSTART_ABORT, MAX_STUCK_REISSUE, CONT
    plan = continuous_plan(a, prof)
    CONT = plan
    TARGET_YEAR, LEAGUE_START_YEAR = plan["target"], plan["first"]
    RESUME_AFTER = int(prof.get("resume_after", 600))        # a full league needs minutes per season
    NOSTART_ABORT = int(prof.get("nostart_abort", 1800))
    MAX_STUCK_REISSUE = int(prof.get("max_reissues", 6))
    lg, folder, target = plan["lg"], plan["folder"], plan["target"]
    idx, total = row_index_of(folder)
    print(f"winsim CONTINUOUS: OOTP {ver} | {lg}")
    print(f"  dumps on disk: {_year_range(plan['have'])}")
    if plan["date"]:
        m, d, y = plan["date"]
        print(f"  in-game date listed by OOTP: {m}/{d}/{y}")
    print(f"  first season {plan['first']} ({plan['why']}); {plan['years']} season(s) "
          f"{plan['first']}-{target - 1}; auto-play to 1/1/{target}")
    print(f"  Load Game row {idx}/{total}; the date dialog should open on {plan['dialog_year']}; "
          f"completion = dump_{target - 1}_yearly")
    if a.dry_run:
        print("\nDRY RUN - nothing clicked.")
        print(f"  steps: FILE -> Load Game -> click row {idx} ({folder!r}) -> Enter -> wait for the load\n"
              f"         Play -> Specified Date -> read the year list (top row must be about "
              f"{plan['dialog_year']}) -> click row {target - plan['dialog_year']} = {target}\n"
              f"         month -> January, day -> 1 -> AUTO-PLAY -> wait for dump_{target - 1}_yearly "
              f"-> wait for it to finish writing")
        print(f"  buttons required: {', '.join(macro_images(continuous=True))}")
        print(f"  digit glyphs: {'present' if load_glyphs() else 'not yet (cut from the year list on the first run)'}")
        return
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
    reset_input()
    activate_ootp()
    if not _cursor_moves():
        raise SystemExit(
            "\n  Can't move the mouse to control OOTP.\n"
            "  This almost always means OOTP is running AS ADMINISTRATOR, so Windows\n"
            "  blocks a normal program from clicking it. Two fixes (either works):\n"
            "    - Right-click 'Sim Dev League.bat' -> Run as administrator, OR\n"
            "    - Close OOTP and reopen it normally (not as admin), then try again.\n"
            + ("  (You are NOT running this as admin right now.)\n" if not is_admin() else ""))
    if a.test_year:
        print(f"TEST YEAR: Play -> Specified Date -> set 1/1/{target} (NO auto-play), snapshot, cancel.")
        for _ in range(4):
            press("escape"); time.sleep(0.35)
        click_img("play_menu"); time.sleep(1.0 * SLEEP_SCALE)
        reg = ootp_window_bounds()
        pt, s = (locate("specified_date", reg) if reg else (None, 0.0))
        if not pt:
            print(f"    specified_date not found (best {s:.2f})"); return
        do_click(*pt); time.sleep(1.2 * SLEEP_SCALE)
        set_date_jan1(target, plan["dialog_year"])
        time.sleep(0.4); _snap("after_setyear")
        for _ in range(2):
            press("escape"); time.sleep(0.3)
        print(f"\nTEST YEAR done - check ootp\\_diag_after_setyear.png: the dialog should read "
              f"1 / January / {target}. Nothing was simmed.")
        return
    print("Abort: slam mouse into a screen corner (FAILSAFE) or Ctrl-C.")
    keep_awake()
    before = dump_years(lg)
    try:
        print(f"\n  driving OOTP: load {folder} -> auto-play to 1/1/{target} ...")
        run_macro({"league": folder}, macro=MACRO_CONT)
        t_start = time.time()          # after the load: writes from here on come from the sim
        auto_play_continuous()
        print(f"  sim launched; waiting for dump_{target - 1}_yearly ...")
        if not wait_for_sim(lg, resume=auto_play_continuous, watch=make_wrong_league_watch(lg, t_start)):
            raise SystemExit(f"{folder}: sim did not reach {target} in time")
        d = lg / "dump" / f"dump_{target - 1}_yearly"
        print("  last dump is on disk; waiting for OOTP to finish writing it ...")
        if not wait_dump_settled(d):
            print("  (the dump kept changing for 15 min; continuing anyway)")
        time.sleep(2.0)
        click_if_present("nice_button", timeout=30)
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n  !! {folder} FAILED: {e}")
        try:
            activate_ootp()
            for _ in range(3):
                press("escape"); time.sleep(0.4)
        except Exception:
            pass
        raise SystemExit(1)
    after = dump_years(lg)
    new = sorted(set(after) - set(before))
    print(f"\nDONE. {folder}: banked {len(new)} season(s): {_year_range(new)}   (on disk: {_year_range(after)})")
    if after:
        print(f"  next run starts at season {after[-1] + 1}.")

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
    ap.add_argument("--sim", action="store_true", help="CONTINUOUS mode: sim the profile's own league in place "
                    "(no clone), --years seasons per run; needs a profile with \"folder\"")
    ap.add_argument("--years", type=int, default=None, help="continuous mode: seasons to sim this run "
                    "(profile default, else 5)")
    ap.add_argument("--folder", default=None, help="continuous mode: the league's saved-game name "
                    "(overrides the profile's \"folder\")")
    ap.add_argument("--reset-input", action="store_true", help="release Ctrl, Shift, Alt, Win and the left "
                    "mouse button, then exit (run after a stopped sim; opens and clicks nothing)")
    a = ap.parse_args()

    if a.reset_input:
        reset_input()
        print("  released Ctrl, Shift, Alt, Win and the left mouse button.")
        return

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
        folders = {}
        if PROFILES_PATH.exists():
            for pid, p in load_profiles().items():
                if p.get("folder"):
                    folders[p["folder"].strip().lower()] = pid
        for n in saved_league_names():
            lg = league_dir(n)
            ys = dump_years(lg)
            mb = sum(f.stat().st_size for f in lg.rglob('*') if f.is_file()) / 1e6
            protected = n.strip().lower() in PROTECTED
            if protected:
                # no dump/ dir here just means CSV export is off - NOT that it's unsimmed
                tag = "REAL LEAGUE - never sim, never clone"
            elif n.strip().lower() in folders:
                tag = (f"CONTINUOUS league (profile {folders[n.strip().lower()]}) - "
                       f"dumps {ys[0]}-{ys[-1]}" if ys else
                       f"CONTINUOUS league (profile {folders[n.strip().lower()]}) - no dumps yet")
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

    if a.sim or (a.test_year and (a.folder or prof.get("folder"))):
        run_continuous(a, prof, ver)
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
        print("  When they're simmed, run Recalibrate (or the Recalibrate card) to fold them into the calibration.")
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
    print("Now run Recalibrate (or let Grind go on) to fold the new clones into the calibration.")

if __name__ == "__main__":
    main()

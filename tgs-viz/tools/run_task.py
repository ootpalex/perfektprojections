"""run_task.py - runs one task from the registry (DESIGN.md 6 and 7).

  python tgs-viz/tools/run_task.py <task_id> [positional inputs] [--input name=value ...]
        Console mode (the bat wrappers). Prints what the old bat printed and
        asks its questions with input().
  python tgs-viz/tools/run_task.py --launch <job_dir>
        Job mode, first hop (the app spawns this). Starts the runner as a
        detached process, then exits 0.
  python tgs-viz/tools/run_task.py --job <job_dir>
        Job mode, the runner. Reads <job_dir>/request.json. Never reads stdin.
  python tgs-viz/tools/run_task.py --plan <task_id> [--mode console|job]
        [--inputs-json JSON] [--assume-json JSON]
        Prints the plan as JSON. Runs nothing.
  python tgs-viz/tools/run_task.py --list-json [--selftest]
  python tgs-viz/tools/run_task.py --validate <task_id> --inputs-json JSON
  python tgs-viz/tools/run_task.py --lock-status
  python tgs-viz/tools/run_task.py --reap
  python tgs-viz/tools/run_task.py --kill <job_id>

Console exit codes: the old bat's code, plus 2 (unknown task, bad settings,
bad input, missing ratings archive), 3 (refused by a lock, or C at the data
question) and 130 (stopped with Ctrl+C).

Stdlib only.
"""
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import conditions as C  # noqa: E402
import joblock as JL  # noqa: E402

REPO = JL.REPO
WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

INHERIT = object()          # cookie not touched yet: the step inherits the environment
PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)?)\}")
SECRET_MIN, SECRET_MAX = 8, 4096
COUNTDOWN = 5


def native(path_template):
    """A step's path template with this system's separator: tasks.py writes Windows
    backslashes, which POSIX reads as part of a file name. Applied before the
    placeholders are filled, so typed inputs pass through unchanged."""
    return path_template if WIN else path_template.replace("\\", "/")


def press_enter(ask):
    """The console pause of a gate: cmd's pause on Windows, else ask() (Ctrl+C sets
    interrupted and ends the wait, as it ends pause)."""
    if WIN:
        subprocess.call("pause", shell=True)
        return
    try:
        ask("Press Enter to continue . . . ")
    except (EOFError, KeyboardInterrupt):
        pass


def now_iso():
    return JL.now_iso()


def signed32(code):
    code = int(code)
    if code >= 2 ** 31:
        return code - 2 ** 32
    return code


def fill(s, ctx):
    """Replace {name} with ctx[name]; unknown names stay as written."""
    if not isinstance(s, str):
        return s
    return PH.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), s)


def fails_text(fails):
    return "".join(" " + f for f in fails)


class Invalid(Exception):
    def __init__(self, message, errors=None, fix_task=None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}
        self.fix_task = fix_task


class Refused(Exception):
    def __init__(self, message, holder=None, lock=None):
        super().__init__(message)
        self.message = message
        self.holder = holder
        self.lock = lock


class Stopped(Exception):
    def __init__(self, how="after_step"):
        super().__init__(how)
        self.how = how


class Killed(Exception):
    pass


class Cancelled(Exception):
    """Console: Ctrl+C or C before anything ran."""


# ---------------------------------------------------------------- settings and registry

def load_settings():
    import settings as ST
    ST.load()
    return ST


def selftest_on(flag=False):
    return bool(flag) or os.environ.get("TGS_SELFTEST", "").strip() == "1"


def archive_paths():
    root = os.environ.get("RATINGS_ARCHIVE_ROOT") or os.path.join(REPO, "tgs-viz", "backtest")
    return os.path.join(root, "ratings_history.db"), os.path.join(root, "vintages")


def ratings_db_exists():
    return os.path.exists(archive_paths()[0])


def archive_missing():
    """True when the ratings archive is missing while saved vintages exist (7.3)."""
    if os.environ.get("RATINGS_DB_ALLOW_NEW", "").strip() == "1":
        return False
    db, vint = archive_paths()
    if os.path.exists(db):
        return False
    try:
        for name in os.listdir(vint):
            if os.path.isfile(os.path.join(vint, name, "_pulls.csv")):
                return True
    except OSError:
        pass
    return False


ARCHIVE_MSG = "The ratings archive is missing. Rebuild it first: Control, Setup check, Rebuild ratings archive."


def registry(ST, selftest):
    import tasks as TK
    return TK, TK.all_tasks(ST, {"selftest": selftest, "ratings_db_exists": ratings_db_exists()})


def get_task(ST, task_id, selftest):
    TK, all_t = registry(ST, selftest)
    t = TK.find(all_t, task_id)
    if t is None:
        if task_id.startswith("selftest.") and not selftest:
            raise Invalid(f"Self test tasks run only with TGS_SELFTEST=1: {task_id}")
        raise Invalid(f"There is no task named {task_id}.")
    why = TK.available(t, ST)
    if why:
        raise Invalid(why)
    return TK, t


def token_state(ST):
    """{league_id: bool} for the enabled online leagues. Reads the token file
    in process; never creates it."""
    out = {}
    try:
        ingest = os.path.join(REPO, "tgs-viz", "ingest")
        if ingest not in sys.path:
            sys.path.insert(0, ingest)
        import statsplus_token as SPT
        for lid, slug in ST.slug_map().items():
            try:
                out[lid] = bool(SPT.token_for(slug))
            except Exception:
                out[lid] = False
    except Exception:
        for lid in ST.slug_map():
            out.setdefault(lid, False)
    return out


# ---------------------------------------------------------------- inputs

TRUE_WORDS = ("1", "true", "yes", "y", "on")


def canon_choice(inp, value):
    for c in inp.get("choices") or []:
        if str(c.get("value")).lower() == str(value).strip().lower():
            return c.get("value")
    return None


def validate_inputs(t, raw, secrets=None, tokens=None, mode="job", check_secrets=True):
    """(clean inputs, clean secrets, errors). raw: non-secret inputs."""
    raw = dict(raw or {})
    secrets = dict(secrets or {})
    errors = {}
    clean = {}
    known = {i["name"]: i for i in t.get("inputs") or []}
    for k in raw:
        if k not in known:
            errors[k] = "This task has no input with that name."
        elif known[k]["type"] == "secret":
            errors[k] = "A secret value cannot be sent as a plain input."
    for name, inp in known.items():
        if mode not in (inp.get("modes") or ["console", "job"]):
            continue
        typ = inp["type"]
        try:
            ask = C.evaluate(inp.get("ask_when"), tokens=tokens or {}, inputs=raw)
        except C.ConditionError:
            ask = True
        if typ == "secret":
            if not check_secrets:
                continue
            v = secrets.get(name, "")
            v = v if isinstance(v, str) else str(v)
            vt = v.strip()
            if vt == "":
                if inp.get("required") and ask:
                    errors[name] = "This is required."
                secrets[name] = ""
                continue
            if "\r" in v or "\n" in v or "\x00" in v:
                errors[name] = "This value has a line break or a NUL character."
            elif len(vt) < SECRET_MIN or len(vt) > SECRET_MAX:
                errors[name] = f"This needs {SECRET_MIN} to {SECRET_MAX} characters."
            secrets[name] = vt
            continue
        v = raw.get(name)
        given = v is not None and not (isinstance(v, str) and v.strip() == "")
        if typ == "confirm":
            ok = v is True or (isinstance(v, (int, float)) and v == 1) or str(v).strip().lower() in TRUE_WORDS
            if inp.get("required") and ask and not ok:
                errors[name] = "Check this box first."
            clean[name] = bool(ok)
            continue
        if not given:
            if inp.get("default") is not None:
                clean[name] = inp["default"]
            elif inp.get("required") and ask:
                errors[name] = "This is required."
            continue
        if typ == "choice":
            cv = canon_choice(inp, v)
            if cv is None:
                errors[name] = "Pick one of: " + ", ".join(str(c["value"]) for c in inp.get("choices") or []) + "."
            else:
                clean[name] = cv
            continue
        s = str(v).strip() if not isinstance(v, bool) else str(v)
        if inp.get("format") == "int":
            try:
                n = int(s)
            except ValueError:
                errors[name] = "Type a whole number."
                continue
            lo, hi = inp.get("min"), inp.get("max")
            if (lo is not None and n < lo) or (hi is not None and n > hi):
                errors[name] = f"Type a number from {lo} to {hi}."
                continue
            s = str(n)
        if inp.get("equals") is not None and s != str(inp["equals"]):
            errors[name] = f"Type {inp['equals']} exactly."
            continue
        if inp.get("pattern") and not re.match(inp["pattern"], s):
            errors[name] = "This value has the wrong form."
            continue
        if len(s) > 4096:
            errors[name] = "This value is too long."
            continue
        clean[name] = s
    return clean, secrets, errors


def first_line_error(errors):
    k = next(iter(errors))
    return f"Input {k}: {errors[k]}"


# ---------------------------------------------------------------- job files

class JobFiles:
    """state.json, events.jsonl, log.txt, prompt/answer/stop files of one job."""

    def __init__(self, job_dir, enabled=True):
        self.dir = job_dir
        self.enabled = enabled
        self.seq = 0
        self.lock = threading.RLock()
        self.state = {}
        self.ev = None
        self.started_event = False
        if enabled:
            os.makedirs(job_dir, exist_ok=True)
            p = os.path.join(job_dir, "events.jsonl")
            try:
                with open(p, "rb") as f:
                    self.seq = sum(1 for _ in f)
            except OSError:
                self.seq = 0
            self.ev = open(p, "a", encoding="utf-8", newline="\n")

    def path(self, name):
        return os.path.join(self.dir, name)

    def write_state(self, **changes):
        with self.lock:
            self.state.update(changes)
            if self.enabled:
                JL.write_json_atomic(self.path("state.json"), self.state)

    def event(self, _type, **data):
        with self.lock:
            self.seq += 1
            if _type == "job_start":
                self.started_event = True
            rec = {"seq": self.seq, "at": now_iso(), "type": _type}
            rec.update(data)
            if self.ev:
                self.ev.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self.ev.flush()
            return rec

    def close(self):
        if self.ev:
            try:
                self.ev.close()
            except OSError:
                pass
            self.ev = None


class LogSink:
    """log.txt writer with secret masking across chunk edges (7.3)."""

    def __init__(self, path, secrets):
        self.f = open(path, "ab") if path else None
        vals = sorted({s.encode("utf-8") for s in secrets if s}, key=len, reverse=True)
        self.secrets = vals
        self.keep = max((len(s) for s in vals), default=1) - 1
        self.carry = b""
        self.last = time.time()
        self.lock = threading.Lock()

    def mask(self, b):
        for s in self.secrets:
            b = b.replace(s, b"****")
        return b

    def mask_text(self, text):
        if not self.secrets:
            return text
        return self.mask(text.encode("utf-8")).decode("utf-8", "replace")

    def _write(self, b):
        if self.f and b:
            self.f.write(b)
            self.f.flush()

    def feed(self, chunk):
        with self.lock:
            self.last = time.time()
            buf = self.mask(self.carry + chunk)
            if self.keep > 0 and self.secrets:
                if len(buf) > self.keep:
                    head, self.carry = buf[:-self.keep], buf[-self.keep:]
                else:
                    head, self.carry = b"", buf
            else:
                head, self.carry = buf, b""
            self._write(head)

    def flush_carry(self):
        with self.lock:
            if self.carry:
                self._write(self.mask(self.carry))
                self.carry = b""

    def idle_flush(self, idle=0.3):
        """After idle seconds, write the carry except a tail that could still be the
        start of a secret: a secret printed in two writes further apart than idle
        would otherwise reach log.txt half unmasked. flush_carry still writes it all."""
        if not self.carry or time.time() - self.last < idle:
            return
        with self.lock:
            buf = self.mask(self.carry)
            n = len(buf)
            for k in range(min(len(buf), self.keep), 0, -1):
                if any(s.startswith(buf[-k:]) for s in self.secrets):
                    n = len(buf) - k
                    break
            self._write(buf[:n])
            self.carry = buf[n:]

    def line(self, text):
        self.flush_carry()
        with self.lock:
            self._write(self.mask((text + "\r\n").encode("utf-8")))

    def close(self):
        self.flush_carry()
        if self.f:
            self.f.close()
            self.f = None


# ---------------------------------------------------------------- the engine

class Engine:
    """Runs a task. One engine drives all three uses, so the plan cannot drift
    from what runs:
      plan=True     records items and takes exit codes from the assumptions
      mode console  prints like the old bat, inherits the console
      mode job      writes the job folder files, no console
    """

    def __init__(self, ST, TK, t, mode, inputs, secrets, *, plan=False, assume=None,
                 job_id=None, files=None, holder=None, console_given=None):
        self.ST, self.TK, self.t, self.mode, self.plan = ST, TK, t, mode, plan
        self.inputs = dict(inputs or {})
        self.secrets = dict(secrets or {})
        self.assume = assume or {}
        self.job_id = job_id
        self.files = files
        self.holder = holder
        self.console_given = set(console_given or [])
        self.items = []
        self.flags = dict(self.assume.get("flags") or {})
        self.fails = []
        self.last_exit = 0
        self.report_exit = None
        self.cookie = INHERIT
        self.cycle = None
        self.locks_held = []
        self.data_state = None
        self.ran_any = False
        self.stop_mode = None
        self.stop_mtime = None
        self.child = None
        self.interrupted = False
        self.asking = False
        self.countdown_done = False
        self.prompt_seq = 0
        self.sink = None
        self.reached = set()
        self.step_t0 = {}
        self.steps = t["steps"]
        self.vis = [k for k, s in enumerate(self.steps)
                    if not (s["kind"] == "gate" and s.get("start")) and s["kind"] != "prelude"]
        self.vis_of = {k: n for n, k in enumerate(self.vis)}
        self.pending = []
        self.ctx = self.base_ctx()
        self.waiting_said = False

    # -- context
    def base_ctx(self):
        ST = self.ST
        ctx = {}
        try:
            inst = (ST.load().get("ootp") or {}).get("installs") or {}
            for ver in inst:
                v = ST.saved_games_raw(ver)
                if v:
                    ctx[f"saved_games:{ver}"] = v
        except Exception:
            pass
        ctx["control"] = JL.control_dir()
        if self.job_id:
            jd = JL.job_dir(self.job_id)
            ctx["job_dir"] = jd
            ctx["spec"] = os.path.join(jd, "new_league_spec.json")
            ctx["precheck"] = os.path.join(jd, "precheck.json")
        for k, v in self.inputs.items():
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                ctx[k] = str(v)
        # inputs whose default holds a placeholder ({job_dir}\xl)
        for k in list(ctx):
            if k in self.inputs:
                ctx[k] = fill(ctx[k], ctx)
        lg = self.inputs.get("league")
        if lg and lg != "all":
            try:
                ctx["slug"] = ST.slug(lg)
            except Exception:
                ctx["slug"] = str(lg).lower()
        if self.t.get("expand") == "new_league":
            lid = str(self.inputs.get("id") or "")
            ctx["id"] = lid
            ctx.setdefault("slug", lid.lower())
            if not str(self.inputs.get("slug") or "").strip():
                ctx["slug"] = lid.lower()
            if not str(self.inputs.get("basis") or "").strip():
                ctx["basis"] = "TGS" if str(self.inputs.get("ootp_version")) == "26" else "BLM"
        if "runs" in ctx:
            try:
                ctx["seasons"] = str(int(ctx["runs"]) * 10)
            except ValueError:
                pass
        return ctx

    def rctx(self):
        c = dict(self.ctx)
        c["fails"] = fails_text(self.fails)
        if self.cycle is not None:
            c["cycle"] = str(self.cycle)
        return c

    def render_lines(self, lines, extra=None):
        ctx = self.rctx()
        if extra:
            ctx.update(extra)
        out = []
        for ln in lines or []:
            if isinstance(ln, dict):
                if "console" in ln or "job" in ln:
                    # a line that tells the user what to press: console words, or the page's (6.3)
                    v = ln.get("job" if self.mode == "job" else "console")
                    if v is not None:
                        out.append(fill(v, ctx))
                elif "if_fails" in ln:
                    if self.fails:
                        out += self.render_lines(ln["if_fails"], extra)
                elif "if_no_fails" in ln:
                    if not self.fails:
                        out += self.render_lines(ln["if_no_fails"], extra)
                continue
            out.append(fill(ln, ctx))
        return out

    def argv(self, run):
        out = []
        ctx = self.rctx()
        for a in run:
            if a == "@py":
                out += self.ST.interp("main")
            elif a == "@ml":
                out += self.ST.interp("ml")
            elif a == "@node":
                out += self.ST.interp("node")
            else:
                out.append(fill(native(a), ctx))
        return out

    # -- output
    def echo(self, lines, extra=None, for_prompt=None):
        lines = self.render_lines(lines, extra)
        if not lines:
            return
        if self.plan:
            last = self.items[-1] if self.items else None
            if last and last["type"] == "echo" and last.get("for_prompt") == for_prompt:
                last["lines"] += lines
            else:
                it = {"type": "echo", "lines": list(lines)}
                if for_prompt:
                    it["for_prompt"] = for_prompt
                self.items.append(it)
            return
        if self.mode == "console":
            for ln in lines:
                print(ln)
            sys.stdout.flush()
        else:
            for ln in lines:
                self.sink.line(ln)

    def say(self, text, level="info"):
        """A run_task line that the old bat never printed (lock waits, stops)."""
        if self.plan:
            return
        if self.mode == "console":
            print(text)
            sys.stdout.flush()
        else:
            self.sink.line(text)
            self.files.event("message", level=level, text=self.sink.mask_text(text.strip()))

    # -- conditions
    def exists(self, rel):
        if self.plan and rel in (self.assume.get("exists") or {}):
            return bool(self.assume["exists"][rel])
        return os.path.exists(os.path.join(REPO, fill(native(rel), self.rctx())))

    def cond(self, c):
        tokens = {k[4:]: bool(v) for k, v in self.flags.items() if k.startswith("tok_")}
        return C.evaluate(c, tokens=tokens, inputs=self.inputs, flags=self.flags, exists=self.exists)

    # -- state helpers
    def step_rec(self, k):
        return self.files.state["steps"][self.vis_of[k]] if (self.files and k in self.vis_of) else None

    def set_step(self, k, **kw):
        if self.plan or not self.files or k not in self.vis_of:
            return
        rec = self.step_rec(k)
        rec.update(kw)
        self.files.write_state()

    def app_leagues(self, s):
        ctx = self.rctx()
        lgs = s.get("app_leagues") or []
        if not lgs and s.get("writes_app_data") and s.get("run"):
            # The file comes from an input (selftest.touch): map the filled argv (9.3).
            lgs = self.TK.default_app_leagues([fill(a, ctx) for a in s["run"]], [])
        return [fill(x, ctx) for x in lgs]

    def update_pending(self, from_k, loop_end=None):
        if self.plan or not self.files:
            return
        end = len(self.steps)
        new = []
        for k in range(from_k, end):
            s = self.steps[k]
            if s.get("when") is not None:
                try:
                    if not self.cond(s["when"]):
                        continue
                except Exception:
                    pass
            for lg in self.app_leagues(s):
                if lg and lg not in new:
                    new.append(lg)
        self.set_pending(new)

    def set_pending(self, new):
        if self.plan or not self.files:
            return
        gone = [lg for lg in self.pending if lg not in new]
        self.pending = list(new)
        self.files.write_state(pending_leagues=list(new))
        for lg in gone:
            self.files.event("league_done", league=lg)

    # -- locks
    def take_run_locks(self):
        if self.plan or not self.holder or self.t["flags"]["read_only"]:
            return
        names = sorted(set(["task." + self.t["id"]] + list(self.t.get("locks") or [])))
        for n in names:
            ok, cur = JL.take_lock(n, self.holder)
            if not ok:
                for m in self.locks_held:
                    JL.release_lock(m, self.job_id)
                self.locks_held = []
                self.files.write_state(locks_held=[])
                title = (cur or {}).get("title") or (cur or {}).get("task") or "Another task"
                msg = f"  {title} is running and {JL.lock_reason(n)}. Wait for it to finish, or stop it on the app's Control page."
                raise Refused(msg, cur, n)
            self.locks_held.append(n)
            self.files.event("lock", name=n, action="taken")
        self.files.write_state(locks_held=list(self.locks_held))

    def release_data(self):
        if self.data_state == "held":
            JL.release_lock("data", self.job_id)
            self.locks_held = [n for n in self.locks_held if n != "data"]
            self.files.event("lock", name="data", action="released")
        if self.data_state in ("held", "skipped"):
            self.data_state = None
            self.files.write_state(data_lock=None, locks_held=list(self.locks_held))

    def ensure_data(self, k, s):
        if self.plan or not self.holder or not s.get("data") or self.t["flags"]["read_only"]:
            return
        if self.data_state in ("held", "skipped"):
            return
        first = not self.ran_any
        ok, cur = JL.take_lock("data", self.holder)
        if ok:
            self._data_taken()
            return
        if self.mode == "console" and first:
            ans = self.data_question(cur)
            if ans == "R":
                self.data_state = "skipped"
                self.files.write_state(data_lock="skipped")
                self.files.event("lock", name="data", action="skipped")
                return
            if ans == "C":
                raise Refused("  Cancelled. Nothing ran.", cur, "data")
        self.files.write_state(status="queued" if (first and self.mode == "job") else self.files.state.get("status"),
                               data_lock="waiting",
                               waiting_for={"job_id": (cur or {}).get("job_id"), "title": (cur or {}).get("title"),
                                            "lock": "data"})
        self.files.event("lock", name="data", action="waiting")
        if not (self.mode == "console" and first):
            self.say(f"  Waiting for {(cur or {}).get('title') or 'another task'} to finish before {s['title']}...")
        while True:
            self.check_stop_idle()
            time.sleep(0.5)
            ok, cur = JL.take_lock("data", self.holder)
            if ok:
                self.files.write_state(status="running", waiting_for=None)
                self._data_taken()
                return

    def _data_taken(self):
        self.data_state = "held"
        self.locks_held.append("data")
        self.files.write_state(data_lock="held", locks_held=list(self.locks_held))
        self.files.event("lock", name="data", action="taken")

    def data_question(self, cur):
        since = (cur or {}).get("since") or ""
        hhmm = since[11:16] if len(since) >= 16 else "?"
        print(f"  {(cur or {}).get('title') or 'Another task'} is updating app data right now (started {hhmm}).")
        print("  W = wait for it, then run    R = run now anyway    C = cancel")
        while True:
            try:
                ans = self.ask("  Type W, R or C, then press Enter (Enter = W): ")
            except EOFError:
                return "W"
            a = ans.strip().upper()
            if a in ("", "W"):
                return "W"
            if a in ("R", "C"):
                return a

    # -- console input
    def ask(self, text):
        """input() that turns Ctrl+C into KeyboardInterrupt."""
        self.asking = True
        try:
            return input(text)
        finally:
            self.asking = False

    # -- stops
    def read_stop(self):
        if self.plan or not self.files or not self.files.enabled:
            return self.stop_mode
        p = self.files.path("stop.json")
        try:
            mt = os.stat(p).st_mtime_ns
        except OSError:
            return self.stop_mode
        if mt == self.stop_mtime:
            return self.stop_mode
        self.stop_mtime = mt
        rec = JL.read_json(p) or {}
        mode = rec.get("mode")
        if mode not in ("after_step", "after_cycle", "kill"):
            return self.stop_mode
        if mode == "after_cycle" and not self.t["flags"]["endless"]:
            mode = "after_step"
        rank = {"after_cycle": 0, "after_step": 1, "kill": 2}
        if self.stop_mode is None or rank[mode] > rank[self.stop_mode]:
            self.stop_mode = mode
            self.files.event("stop_requested", mode=mode)
            self.files.write_state(stop=mode)
            if self.mode == "console":
                print("  Stopped from the app's Control page.")
                sys.stdout.flush()
        return self.stop_mode

    def check_stop_idle(self):
        """While waiting (data lock, countdown): any stop ends the run now."""
        m = self.read_stop()
        if m is not None:
            raise Stopped(m)
        if self.interrupted and self.mode == "console":
            raise Cancelled() if not self.ran_any else Stopped("ctrl_c")

    def check_stop_between(self):
        m = self.read_stop()
        if m == "kill":
            raise Killed()
        if m == "after_step":
            raise Stopped("after_step")

    # -- running commands
    def step_env(self, s):
        env = dict(os.environ)
        if self.job_id:
            env["TGS_JOB_ID"] = self.job_id
        if self.mode == "job":
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
        cookie_shown = INHERIT
        for key, val in (s.get("env") or {}).items():
            v = self.env_value(val)
            if key == "STATSPLUS_COOKIE":
                cookie_shown = v
            if v is None:
                env.pop(key, None)
            elif v is not INHERIT:
                env[key] = v
        if cookie_shown is INHERIT:
            cookie_shown = os.environ.get("STATSPLUS_COOKIE")
        return env, cookie_shown

    def env_value(self, val):
        if val is None:
            return None
        if val == "@cookie":
            return self.cookie
        if val == "@cookie_given":
            sid = self.secrets.get("sessionid", "")
            if not sid:
                return None
            return f"sessionid={sid};csrftoken={self.secrets.get('csrftoken', '')}"
        if isinstance(val, str) and val.startswith("@secret:"):
            v = self.secrets.get(val[8:], "")
            return v or None
        return fill(val, self.rctx())

    def assumed_exit(self, s):
        codes = (self.assume.get("exit_codes") or {}).get(s["id"], 0)
        if isinstance(codes, list):
            n = (self.cycle or 1) - 1
            return int(codes[n]) if n < len(codes) else 0
        return int(codes)

    def run_cmd(self, k, s, argv, env, cookie, assumed=None, capture=None, step_events=True):
        """Runs one command. Returns its exit code."""
        if self.plan:
            code = self.assumed_exit(s) if assumed is None else assumed
            self.items.append({"type": "command", "step_id": s["id"], "argv": argv,
                               "env": {"STATSPLUS_COOKIE": cookie}, "assumed_exit": code})
            return code
        self.ran_any = True
        if self.mode == "console":
            sys.stdout.flush()
            proc = subprocess.Popen(argv, cwd=REPO, env=env)
            reader = None
        else:
            proc = subprocess.Popen(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=not WIN,
                                    creationflags=(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if WIN else 0)
            reader = threading.Thread(target=self._read_child, args=(proc, capture), daemon=True)
            reader.start()
        self.child = proc
        killed = False
        last_stop_check = 0.0
        try:
            while True:
                try:
                    rc = proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                except KeyboardInterrupt:
                    self.interrupted = True
                    continue
                if time.time() - last_stop_check >= 0.5:
                    last_stop_check = time.time()
                    if self.read_stop() == "kill" and not killed:
                        killed = True
                        self.kill_tree(proc.pid)
        finally:
            self.child = None
        if reader:
            reader.join(timeout=5)
            self.sink.flush_carry()
        if killed:
            self.after_kill(s, argv)
            raise Killed()
        return rc

    def _read_child(self, proc, capture):
        try:
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
                if not chunk:
                    break
                self.sink.feed(chunk)
                if capture is not None:
                    capture.append(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self.sink.flush_carry()

    def kill_tree(self, pid):
        if not WIN:
            JL.posix_kill_tree(pid)
            return
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW if WIN else 0, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass

    def after_kill(self, s, argv):
        if s.get("drives_ootp") or self.TK.script_of(s.get("run") or []) == self.TK.WINSIM:
            reset_input(self.ST, log=self.say)

    def judge_ctrl_c(self, k, s):
        """Console: the step got Ctrl+C too. Ask whether to stop the whole run."""
        self.interrupted = False
        try:
            ans = self.ask("  Stop the whole run? (Y/N) ")
        except (EOFError, KeyboardInterrupt):
            ans = "Y"
        if ans.strip().upper() in ("", "Y", "YES"):
            raise Stopped("ctrl_c")

    # -- the run
    def execute(self):
        t = self.t
        self.echo(t["banner"])
        steps = self.steps
        i = 0
        if steps and steps[0]["kind"] == "gate" and steps[0].get("start"):
            self.start_gate(steps[0])
            i = 1
        if self.mode == "console":
            self.console_inputs()
        self.take_run_locks()
        loop = t.get("loop")
        loop_at = None
        if loop:
            loop_at = next(k for k, s in enumerate(steps) if s["id"] == loop["from_step"])
        self.update_pending(i)
        outcome = "ok"
        while True:
            if loop and i == loop_at:
                if not self.cycle_begin(loop, loop_at):
                    outcome = "cycles_done"
                    break
            if i >= len(steps):
                break
            s = steps[i]
            r = self.do_step(i, s)
            if r in ("failfast", "history_stop"):
                outcome = r
                break
            i += 1
            if loop and i == len(steps):
                self.cycle_end()
                if self.flags.get("stopafter"):
                    outcome = "stopafter"
                    break
                m = self.read_stop()
                if m == "kill":
                    raise Killed()
                if m in ("after_step", "after_cycle"):
                    raise Stopped(m)
                i = loop_at
                continue
            if i >= len(steps):
                break
            if self.interrupted and self.mode == "console":
                self.judge_ctrl_c(i, s)
            self.check_stop_between()
        return self.finish(outcome)

    def start_gate(self, s):
        if self.mode == "console":
            if self.plan:
                self.items.append({"type": "pause", "step_id": s["id"]})
                return
            self.echo(s.get("echo"))
            press_enter(self.ask)
            time.sleep(0.05)
            if self.interrupted:
                raise Cancelled()
        elif s.get("job_message"):
            self.say(s["job_message"])

    def console_inputs(self):
        for inp in self.t.get("inputs") or []:
            if "console" not in (inp.get("modes") or []) or inp["type"] in ("secret", "confirm"):
                continue
            name = inp["name"]
            if name in self.console_given:
                continue
            con = inp.get("console")
            if not con:
                continue
            while True:
                val = self.console_prompt(name, con["prompt"], eof=None)
                if val is None:
                    # a plan with no answer left, or the end of the input
                    if not self.plan:
                        raise Cancelled() if not self.ran_any else Stopped("ctrl_c")
                    fallback = inp.get("default")
                    if fallback is None and inp["type"] == "choice" and inp.get("choices"):
                        fallback = inp["choices"][0]["value"]
                    self.set_input(name, fallback if fallback is not None else "")
                    break
                if inp["type"] == "choice":
                    cv = canon_choice(inp, val)
                    if cv is not None:
                        self.set_input(name, cv)
                        break
                    if con.get("loop_until_valid"):
                        self.echo(con.get("invalid_echo") or [], for_prompt=name)
                        continue
                self.set_input(name, val)
                break

    def set_input(self, name, val):
        self.inputs[name] = val
        self.ctx = self.base_ctx()

    def console_prompt(self, name, text, eof=""):
        """One console question. eof is what a plan with no answer left, or the
        end of the input, gives."""
        if self.plan:
            self.items.append({"type": "prompt", "input": name, "text": text})
            answers = self.assume.get("answers") or {}
            if name not in answers:
                return eof
            ans = answers[name]
            if isinstance(ans, list):
                return ans.pop(0) if ans else eof
            return ans
        try:
            return self.ask(text)
        except EOFError:
            return eof
        except KeyboardInterrupt:
            raise Cancelled() if not self.ran_any else Stopped("ctrl_c")

    def secret_prompt(self, name, text):
        """The prelude's cookie prompts (console), or the secret input (job)."""
        if self.mode == "job":
            return self.secrets.get(name, "")
        if self.plan:
            v = self.console_prompt(name, text)
            return f"<{name}>" if str(v).strip() else ""
        v = self.console_prompt(name, text)
        return v.strip("\r\n")

    def cycle_begin(self, loop, loop_at):
        n = (self.cycle or 0) + 1
        if self.plan and n > int(self.assume.get("cycles", 1)):
            return False
        self.cycle = n
        if not self.plan and self.files:
            for k in range(loop_at, len(self.steps)):
                if k in self.vis_of:
                    self.step_rec(k).update(status="pending", exit=None, started=None, ended=None)
            self.files.write_state(cycle=n)
            self.files.event("cycle_start", cycle=n)
            self.update_pending(loop_at)
        self.echo(loop.get("cycle_echo") or [])
        return True

    def cycle_end(self):
        if not self.plan and self.files:
            self.release_data()

    def do_step(self, k, s):
        if s.get("when") is not None and not self.cond(s["when"]):
            self.mark(k, s, "skipped", None)
            return "ok"
        self.ensure_data(k, s)
        kind = s["kind"]
        if kind == "prelude":
            self.prelude(s)
            return "ok"
        if kind == "excel_check":
            if self.mode == "job" and not self.plan:
                self.excel_check(k, s)
            else:
                self.mark(k, s, "skipped", None, quiet=True)
            return "ok"
        if kind == "gate":
            return self.mid_gate(k, s)
        self.echo(s.get("echo"))
        if kind == "exists_check":
            self.start_step(k, s, None)
            if self.exists(s["path"]):
                self.mark(k, s, "ok", None)
                return "ok"
            self.echo(s.get("missing_echo"))
            return self.on_fail(k, s, None)
        argv = self.argv(s["run"])
        env, cookie = self.step_env(s)
        if s.get("drives_ootp") and self.mode == "job":
            self.countdown()
        self.start_step(k, s, argv)
        if kind == "probe":
            code = self.run_cmd(k, s, argv, env, cookie)
            self.last_exit = code
            if s.get("set_flag"):
                self.flags[s["set_flag"]] = code == 0
            self.mark(k, s, "ok", code)
            return "ok"
        if s.get("job") and self.mode == "job":
            code = self.interactive(k, s, env, cookie)
        else:
            code = self.run_cmd(k, s, argv, env, cookie)
        self.last_exit = code
        if self.interrupted and self.mode == "console" and not self.plan:
            try:
                self.judge_ctrl_c(k, s)
            except Stopped:
                self.mark(k, s, "stopped", code)
                raise
        if s["on_error"] == "report":
            self.report_exit = code
            self.mark(k, s, "ok" if code == 0 else "failed", code)
            return "ok"
        if code == 0:
            self.mark(k, s, "ok", code)
            return "ok"
        return self.on_fail(k, s, code)

    def on_fail(self, k, s, code):
        pol = s["on_error"]
        self.echo(s.get("fail_echo"))
        tag = fill(s.get("tag") or s["id"], self.rctx())
        if isinstance(pol, dict) and pol.get("handler") == "history_codes":
            sc = str(signed32(code)) if code is not None else ""
            texts = (s.get("handler_text") or {}).get("stop") or {}
            if sc in texts:
                txt = texts[sc]
                if isinstance(txt, dict):
                    txt = txt["tok"] if self.flags.get("tok") else txt[""]
                self.echo(txt)
                self.echo((s.get("handler_text") or {}).get("tail") or [])
                self.mark(k, s, "failed", code)
                return "history_stop"
            self.fails.append(tag)
            self.mark(k, s, "failed", code)
            return "ok"
        if pol == "collect":
            self.fails.append(tag)
            self.mark(k, s, "failed", code)
            return "ok"
        if pol == "ignore":
            self.mark(k, s, "ignored_fail", code)
            return "ok"
        if pol == "stopafter":
            self.flags["stopafter"] = True
            self.mark(k, s, "failed", code)
            return "ok"
        self.mark(k, s, "failed", code)
        return "failfast"

    def start_step(self, k, s, argv):
        if self.plan or not self.files or k not in self.vis_of:
            return
        self.files.write_state(current=self.vis_of[k], status=self.files.state.get("status")
                               if self.files.state.get("status") == "waiting" else "running")
        self.set_step(k, status="running", started=now_iso(), ended=None, exit=None)
        self.step_t0[k] = time.time()
        self.files.event("step_start", index=self.vis_of[k], step_id=s["id"], title=s["title"], argv=argv)

    def mark(self, k, s, status, code, quiet=False):
        if status == "ok":
            self.reached.add(s["id"])
        if self.plan or not self.files or k not in self.vis_of:
            return
        rec = self.step_rec(k)
        t0 = self.step_t0.pop(k, None)
        secs = round(time.time() - t0, 1) if t0 is not None else None
        rec.update(status=status, exit=code, ended=now_iso(),
                   tag=fill(s.get("tag"), self.rctx()) if s.get("tag") else None)
        self.files.write_state(fails=list(self.fails))
        self.files.event("step_end", index=self.vis_of[k], step_id=s["id"], status=status, exit=code,
                         seconds=secs, tag=rec.get("tag"), writes_app_data=bool(s.get("writes_app_data")))
        self.update_pending(k + 1)

    # -- preludes (6.2)
    def prelude(self, s):
        text = s.get("prelude_text") or {}
        if s["prelude"] == "cookie_pair":
            l1, l2 = s["prelude_leagues"]
            t1, t2 = bool(self.flags.get("tok_" + l1)), bool(self.flags.get("tok_" + l2))
            if t1 and t2:
                self.echo(text.get("both"))
                self.cookie = None
                return
            if not t1 and not t2:
                self.echo(text.get("none"))
                sid = self.secret_prompt("sessionid", "Paste your sessionid value, then press Enter:")
                csrf = self.secret_prompt("csrftoken", "Paste your csrftoken value, then press Enter:")
                self.cookie = f"sessionid={sid};csrftoken={csrf}"
                return
            have, notok = (l1, l2) if t1 else (l2, l1)
            noslug = (s.get("prelude_slugs") or {}).get(notok) or notok.lower()
            self.echo(text.get("one"), {"have": have, "notok": notok, "noslug": noslug})
            self.cookie = None
            sid = self.secret_prompt("sessionid", f"Paste your sessionid value (Enter = skip {notok}): ")
            if sid == "":
                return
            csrf = self.secret_prompt("csrftoken", "Paste your csrftoken value, then press Enter: ")
            self.cookie = f"sessionid={sid};csrftoken={csrf}"
            return
        if s["prelude"] == "cookie_single":
            if self.flags.get("tok"):
                self.echo(text.get("token"))
                self.cookie = None
                return
            self.echo(text.get("notoken"))
            sid = self.secret_prompt("sessionid", "Paste your sessionid value, then press Enter:")
            csrf = self.secret_prompt("csrftoken", "Paste your csrftoken value, then press Enter:")
            self.cookie = f"sessionid={sid};csrftoken={csrf}"
            return
        raise Invalid(f"Unknown prelude {s['prelude']}.")

    # -- gates and prompts
    def mid_gate(self, k, s):
        self.echo(s.get("echo"))
        if self.mode == "console":
            if self.plan:
                self.items.append({"type": "pause", "step_id": s["id"]})
                return "ok"
            self.start_step(k, s, None)
            press_enter(self.ask)
            if self.interrupted:
                self.judge_ctrl_c(k, s)
            self.mark(k, s, "ok", None)
            return "ok"
        if self.plan:
            self.items.append({"type": "gate", "step_id": s["id"], "text": s["prompt"]["text"]})
            return "ok"
        self.start_step(k, s, None)
        ans = self.prompt("gate", s, s["prompt"]["text"], [], s["prompt"]["choices"], "stop")
        if ans != "continue":
            self.mark(k, s, "stopped", None)
            raise Stopped("gate")
        self.mark(k, s, "ok", None)
        self.check_stop_between()
        return "ok"

    def prompt(self, kind, s, text, details, choices, safe):
        self.prompt_seq += 1
        pid = f"p{self.prompt_seq}"
        rec = {"prompt_id": pid, "kind": kind, "step_id": s["id"], "title": s["title"],
               "text": self.sink.mask_text(text), "details": [self.sink.mask_text(d) for d in details][-40:],
               "choices": choices, "default": safe, "created": now_iso()}
        ans_path = self.files.path("answer.json")
        JL.remove_file(ans_path)
        JL.write_json_atomic(self.files.path("prompt.json"), rec)
        self.files.event("prompt", prompt_id=pid, kind=kind, text=rec["text"], details=rec["details"],
                         choices=choices)
        prev = self.files.state.get("status")
        self.files.write_state(status="waiting", prompt=rec)
        ids = {c["id"] for c in choices}
        value = None
        try:
            while value is None:
                m = self.read_stop()
                if m is not None:
                    value = safe
                    break
                a = JL.read_json(ans_path)
                if isinstance(a, dict):
                    if a.get("prompt_id") == pid and a.get("value") in ids:
                        value = a["value"]
                        break
                    self.say(f"  Ignored an answer that does not fit this question ({a.get('value')!r}).", "warn")
                    JL.remove_file(ans_path)
                time.sleep(0.5)
        finally:
            JL.remove_file(ans_path)
            JL.remove_file(self.files.path("prompt.json"))
        self.files.event("answer", prompt_id=pid, value=value)
        self.files.write_state(status="running" if prev != "queued" else prev, prompt=None)
        return value

    def interactive(self, k, s, env, cookie):
        j = s["job"]
        pre = self.argv(j["preview"])
        app = self.argv(j["apply"])
        if self.plan:
            how = (self.assume.get("confirm") or {}).get(s["id"], "yes")
            code = self.assumed_exit(s)
            if how == "zero":
                self.items.append({"type": "command", "step_id": s["id"], "argv": pre,
                                   "env": {"STATSPLUS_COOKIE": cookie}, "assumed_exit": code})
                return code
            self.run_cmd(k, s, pre, env, cookie, assumed=0)
            self.items.append({"type": "confirm", "step_id": s["id"], "question": j["question"]})
            if how != "yes":
                return 0
            return self.run_cmd(k, s, app, env, cookie, assumed=code)
        cap = []
        self.sink.line("  > " + " ".join(pre))
        code = self.run_cmd(k, s, pre, env, cookie, capture=cap)
        if code != 0:
            return code
        text = b"".join(cap).decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        rx = re.compile(j["count_regex"])
        count = 0
        for ln in lines:
            m = rx.search(ln)
            if m:
                count += int(m.group(1))
        if count == 0:
            self.say("  Nothing to apply.")
            return 0
        choices = [{"id": "yes", "label": j.get("yes_label") or "Apply"},
                   {"id": "no", "label": j.get("no_label") or "Skip"}]
        ans = self.prompt("confirm", s, j["question"], [ln for ln in lines if ln.strip()][-40:], choices, "no")
        if ans != "yes":
            self.say("  Skipped (not applied).")
            self.check_stop_between()
            return 0
        self.sink.line("  > " + " ".join(app))
        return self.run_cmd(k, s, app, env, cookie)

    def excel_check(self, k, s):
        ex = s.get("excel") or {}
        folder = fill(ex.get("folder") or "", self.rctx())
        base = folder if os.path.isabs(folder) else os.path.join(REPO, folder)
        self.start_step(k, s, None)
        for name in ex.get("files") or []:
            lockf = os.path.join(base, "~$" + name)
            while os.path.exists(lockf):
                text = (f"Excel has {name} open in {folder}. Close Excel, then press Continue. If Excel is closed "
                        f"and this still shows, delete the file ~${name} in that folder.")
                ans = self.prompt("gate", s, text, [], [{"id": "continue", "label": "Continue"},
                                                        {"id": "stop", "label": "Stop"}], "stop")
                if ans != "continue":
                    self.mark(k, s, "stopped", None)
                    raise Stopped("excel")
        self.mark(k, s, "ok", None)

    def countdown(self):
        if self.countdown_done or self.plan:
            return
        self.countdown_done = True
        for n in range(COUNTDOWN, 0, -1):
            self.files.event("message", level="countdown", text=f"Hands off: OOTP starts in {n}")
            end = time.time() + 1
            while time.time() < end:
                if self.read_stop() is not None:
                    raise Stopped("countdown")
                time.sleep(0.1)

    # -- finish
    def finish(self, outcome):
        fin = self.t["finish"]
        rv = fin.get("report_verdict") or "strict"
        if outcome == "cycles_done":
            return {"status": "running", "exit": None}
        if outcome == "ok":
            lines = fin.get("fails_echo") if (self.fails and fin.get("style") == "fails") else fin.get("ok_echo")
            self.echo(lines)
            code = fin["exit_ok"] if fin.get("exit_ok") is not None else self.last_exit
            if fin.get("report_step") and self.report_exit is not None:
                r = self.report_exit
                if rv == "strict":
                    status = "failed" if r != 0 else ("partial" if self.fails else "done")
                else:
                    status = "done" if r == 0 and not self.fails else ("partial" if r in (0, 1) else "failed")
            else:
                status = "partial" if self.fails else "done"
            return {"status": status, "exit": code}
        if outcome == "failfast":
            self.echo(fin.get("fail_echo"))
            code = fin["exit_fail"] if fin.get("exit_fail") is not None else self.last_exit
            return {"status": "failed", "exit": code}
        if outcome == "stopafter":
            self.echo(fin.get("stopped_echo"))
            return {"status": "failed", "exit": fin.get("exit_stopped", 1),
                    "message": "Stopped after a sim problem. Everything that finished is banked."}
        if outcome == "history_stop":
            return {"status": "failed", "exit": self.last_exit,
                    "message": "StatsPlus stopped the history pull. The steps after it were skipped."}
        return {"status": "failed", "exit": 1}

    def summary(self, result):
        out = []
        if self.fails:
            out.append("Steps that did not update: " + ", ".join(self.fails))
        if result.get("message"):
            out.append(result["message"])
        return out


def reset_input(ST, log=None):
    """Release keys and the mouse button after a kill of an OOTP step (winsim --reset-input)."""
    argv = ST.interp("main") + [native(r"ootp\winsim.py"), "--reset-input"]
    try:
        r = subprocess.run(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=CREATE_NO_WINDOW if WIN else 0, timeout=15)
        msg = f"  Released the keys and the mouse (winsim --reset-input exit {r.returncode})."
    except (OSError, subprocess.SubprocessError) as e:
        msg = f"  Could not release the keys and the mouse: {type(e).__name__}."
    if log:
        log(msg)
    return msg


# ---------------------------------------------------------------- plan

def make_plan(task_id, mode="console", inputs=None, assume=None, selftest=None):
    """The plan of a task as a dict (6.1). Runs nothing."""
    assume = json.loads(json.dumps(assume or {}))
    if assume.get("env"):
        for k, v in assume["env"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
    ST = load_settings()
    st = selftest_on() if selftest is None else selftest
    TK, t = get_task(ST, task_id, st)
    raw = dict(inputs or {})
    secrets = {}
    for inp in t.get("inputs") or []:
        if inp["type"] == "secret" and inp["name"] in raw:
            secrets[inp["name"]] = raw.pop(inp["name"])
    shown = {k: (f"<{k}>" if str(v).strip() else "") for k, v in secrets.items()}
    given = set(raw)
    clean, _s, _e = validate_inputs(t, raw, {}, {}, mode, check_secrets=False)
    for k, v in raw.items():
        clean.setdefault(k, v)
    if t.get("expand"):
        t = TK.expand(t, clean, ST)
    eng = Engine(ST, TK, t, mode, clean, shown, plan=True, assume=assume, console_given=given)
    try:
        res = eng.execute()
    except Stopped:
        res = {"status": "stopped", "exit": 130}
    exit_code = res["exit"]
    if mode == "job" and exit_code is not None:
        exit_code = 1 if res["status"] == "failed" else 0
    return {"task": task_id, "mode": mode, "items": eng.items, "fails": eng.fails,
            "exit_code": exit_code, "status": res["status"]}


# ---------------------------------------------------------------- catalog

def step_display(TK, ST, t):
    eng = Engine(ST, TK, t, "job", {i["name"]: i.get("default") for i in t.get("inputs") or []
                                    if i.get("default") is not None and i["type"] != "confirm"}, {}, plan=True)
    out = []
    for k in eng.vis:
        s = t["steps"][k]
        argv = None
        if s.get("run"):
            try:
                argv = eng.argv(s["run"])
            except Exception:
                argv = list(s["run"])
        out.append({"id": s["id"], "title": s["title"], "kind": s["kind"],
                    "writes_app_data": bool(s.get("writes_app_data")), "data": bool(s.get("data")),
                    "app_leagues": list(s.get("app_leagues") or []), "drives_ootp": bool(s.get("drives_ootp")),
                    "argv": argv})
    return out


def catalog(selftest=False):
    import tasks as TK
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    groups = [g for g in TK.GROUPS if g["id"] != "selftest" or selftest]
    db_path = archive_paths()[0]
    try:
        import settings as ST
    except Exception as e:  # pragma: no cover - the module itself is missing
        return error_catalog(TK, stamp, groups, f"tgs-viz\\tools\\settings.py could not load: {e}")
    try:
        ST.load(refresh=True)
    except ST.SettingsError as e:
        return error_catalog(TK, stamp, groups, str(e), ST)
    tasks = TK.build_registry(ST, {"selftest": selftest, "ratings_db_exists": os.path.exists(db_path)})
    out_tasks = []
    for t in tasks:
        out_tasks.append({
            "id": t["id"], "title": t["title"], "description": t["description"], "group": t["group"],
            "leagues": t["leagues"], "bat": t["bat"], "flags": t["flags"], "locks": t["locks"], "time": t["time"],
            "inputs": t["inputs"], "stop_modes": t["stop_modes"], "steps": step_display(TK, ST, t),
            "requires_leagues": t["requires_leagues"],
        })
    ids = {t["id"] for t in tasks}
    defaults_ids = TK.defaults_league_ids(ST)
    in_app = set()
    lj = JL.read_json(os.path.join(REPO, "tgs-viz", "public", "data", "leagues.json")) or {}
    for e in lj.get("leagues") or []:
        if isinstance(e, dict) and e.get("id"):
            in_app.add(e["id"])
    leagues = []
    for lid, lg in ST.leagues(include_disabled=True).items():
        leagues.append({
            "id": lid, "name": lg.get("name") or lid, "type": lg.get("type"),
            "enabled": lg.get("enabled", True) is not False, "pending": bool(lg.get("pending")),
            "added_by_wizard": lid not in defaults_ids, "in_app": lid in in_app,
            "update_task": f"update.{lid}" if f"update.{lid}" in ids else None,
            "token_line": (ST.slug(lid).upper() + "=") if lg.get("type") == "statsplus" else None,
        })
    installs = {}
    for ver in sorted(((ST.load().get("ootp") or {}).get("installs") or {})):
        p = ST.saved_games(ver)
        installs[ver] = {"path": p, "exists": bool(p and os.path.isdir(p))}
    try:
        tok_file = ST.token_file()
    except Exception:
        tok_file = os.path.join(REPO, "StatsPlus Tokens.txt")
    state = {
        "tokens": token_state(ST),
        "ootp_installs": installs,
        "ratings_db_exists": os.path.exists(db_path),
        "settings_local": os.path.exists(ST.local_path()),
        "settings_error": None,
        "watch_files": [ST.DEFAULTS_PATH, ST.local_path(), tok_file, db_path,
                        os.path.join(REPO, "tgs-viz", "public", "data", "leagues.json")],
    }
    return {"schema": 1, "generated": stamp, "groups": groups, "tasks": out_tasks, "leagues": leagues,
            "state": state, "app_config": ST.app_config()}


def error_catalog(TK, stamp, groups, message, ST=None):
    d = TK.finalize(TK.doctor_task(), [])
    paths = []
    if ST is not None:
        paths = [ST.DEFAULTS_PATH, ST.local_path()]
    db_path = archive_paths()[0]
    entry = {"id": d["id"], "title": d["title"], "description": d["description"], "group": d["group"],
             "leagues": [], "bat": None, "flags": d["flags"], "locks": [], "time": d["time"], "inputs": [],
             "stop_modes": d["stop_modes"], "requires_leagues": [],
             "steps": [{"id": "doctor", "title": "Setup check", "kind": "run", "writes_app_data": False, "data": False,
                        "app_leagues": [], "drives_ootp": False,
                        "argv": ["python", r"tgs-viz\tools\doctor.py"]}]}
    return {"schema": 1, "generated": stamp, "groups": groups, "tasks": [entry], "leagues": [],
            "state": {"tokens": {}, "ootp_installs": {}, "ratings_db_exists": os.path.exists(db_path),
                      "settings_local": bool(ST and os.path.exists(ST.local_path())),
                      "settings_error": message,
                      "watch_files": paths + [os.path.join(REPO, "tgs-viz", "public", "data", "leagues.json")]},
            "app_config": {"leagues": {}}}


# ---------------------------------------------------------------- running a job

class Run:
    """One real run (console or job): job folder, active entry, heartbeat, final state."""

    def __init__(self, mode, job_id, task_id, request):
        self.mode, self.job_id, self.task_id, self.request = mode, job_id, task_id, request
        self.me = JL.me()
        self.files = None
        self.engine = None
        self.stop_hb = threading.Event()
        self.hb = None
        self.sink = None
        self.title = task_id
        self.tracking = True

    def holder(self):
        return {"job_id": self.job_id, "task": self.task_id, "title": self.title, "mode": self.mode,
                "pid": self.me["pid"], "pid_started": self.me["pid_started"]}

    def open(self):
        jd = JL.job_dir(self.job_id)
        try:
            os.makedirs(jd, exist_ok=True)
            if self.mode == "console":
                JL.write_json_atomic(os.path.join(jd, "request.json"), self.request)
            self.files = JobFiles(jd, True)
            JL.write_active({"schema": 1, "job_id": self.job_id, "task": self.task_id, "title": self.title,
                             "mode": self.mode, "pid": self.me["pid"], "pid_started": self.me["pid_started"],
                             "started": now_iso()})
        except OSError as e:
            if self.mode == "job":
                raise
            self.tracking = False
            self.files = JobFiles(jd, False)
            print(f"  (The Control folder could not be written: {e.strerror or e}. Running without job tracking.)")
        self.files.write_state(schema=1, id=self.job_id, task=self.task_id, title=self.title, mode=self.mode,
                               status="starting", pid=self.me["pid"], pid_started=self.me["pid_started"],
                               started=now_iso(), ended=None, inputs={}, secrets_given=[], steps=[],
                               current=None, cycle=None, fails=[], prompt=None, stop=None, locks_held=[],
                               data_lock=None, waiting_for=None, pending_leagues=[], message=None, fix_task=None,
                               summary=[], exit_code=None)
        self.hb = threading.Thread(target=self._heartbeat, daemon=True)
        self.hb.start()

    def _heartbeat(self):
        hp = self.files.path("heartbeat") if self.files and self.files.enabled else None
        last = 0.0
        while not self.stop_hb.is_set():
            if hp and time.time() - last >= 5:
                last = time.time()
                try:
                    with open(hp, "a"):
                        pass
                    os.utime(hp, None)
                except OSError:
                    pass
            if self.sink:
                try:
                    self.sink.idle_flush()
                except Exception:
                    pass
            self.stop_hb.wait(0.1)

    def close(self, status, exit_code, message=None, fix_task=None, summary=None, errors=None, conflict=None):
        f = self.files
        if f is None:
            return
        eng = self.engine
        for rec in f.state.get("steps") or []:
            if rec.get("status") == "running":
                rec["status"] = {"killed": "killed", "stopped": "stopped"}.get(status, "failed")
                rec["ended"] = now_iso()
            elif rec.get("status") == "pending":
                rec["status"] = "skipped"
        if eng is not None and eng.pending:
            eng.set_pending([])
        held = JL.release_all(self.job_id) if self.tracking else []
        for n in held:
            f.event("lock", name=n, action="released")
        if f.state.get("prompt"):
            JL.remove_file(f.path("prompt.json"))
        fields = dict(status=status, ended=now_iso(), exit_code=exit_code, prompt=None, waiting_for=None,
                      locks_held=[], pending_leagues=[])
        if f.state.get("data_lock") != "skipped":
            fields["data_lock"] = None
        if message is not None:
            fields["message"] = self.sink.mask_text(message) if self.sink else message
        if fix_task is not None:
            fields["fix_task"] = fix_task
        if summary is not None:
            fields["summary"] = summary
        if errors:
            fields["errors"] = errors
        if conflict:
            fields["conflict"] = conflict
        f.write_state(**fields)
        if not f.started_event:
            f.event("job_start", task=self.task_id, mode=self.mode, steps_total=len(f.state.get("steps") or []))
        f.event("job_end", status=status, exit_code=exit_code, fails=list(f.state.get("fails") or []),
                summary=f.state.get("summary") or [])
        if self.tracking:
            JL.remove_active(self.job_id)
        self.stop_hb.set()
        f.close()
        if self.sink:
            self.sink.close()


def run_task_main(mode, job_id, task_id, raw_inputs, secrets, request, console_given=()):
    """Shared body of console and job mode. Returns the exit code."""
    run = Run(mode, job_id, task_id, request)
    run.open()
    status, code, message, fix, errors = "failed", 1, None, None, None
    eng = None
    try:
        if os.environ.get("TGS_RUN_TASK_TEST_CRASH", "").strip() == "1":
            raise RuntimeError("Test crash right after the job started.")
        try:
            ST = load_settings()
        except Exception as e:
            raise Invalid(str(e)) from None
        selftest = selftest_on()
        TK, t = get_task(ST, task_id, selftest)
        run.title = t["title"]
        tokens = token_state(ST) if mode == "job" else {}
        clean, secrets, errs = validate_inputs(t, raw_inputs, secrets, tokens, mode,
                                               check_secrets=(mode == "job"))
        if mode == "console":
            # console mode asks its questions later, as the bat did; only values
            # given on the command line are checked, and the bat's %1 passes as is
            argv_inputs = {i["name"] for i in t.get("inputs") or [] if i.get("from_argv")}
            for k, v in raw_inputs.items():
                if k in argv_inputs:
                    clean[k] = v
                else:
                    clean.setdefault(k, v)
            errs = {k: v for k, v in errs.items() if k in raw_inputs and k not in argv_inputs}
        if errs:
            raise Invalid(first_line_error(errs), errs)
        if t.get("expand"):
            t = TK.expand(t, clean, ST)
            if t.get("expand") == "new_league":
                spec = {k: v for k, v in clean.items()}
                spec["job_id"] = job_id
                JL.write_json_atomic(os.path.join(JL.job_dir(job_id), "new_league_spec.json"), spec)
        if run.tracking:
            JL.write_active({"schema": 1, "job_id": job_id, "task": task_id, "title": t["title"], "mode": mode,
                             "pid": run.me["pid"], "pid_started": run.me["pid_started"],
                             "started": run.files.state.get("started")})
        secret_vals = [v for v in secrets.values() if v]
        run.sink = LogSink(run.files.path("log.txt") if mode == "job" else None, secret_vals)
        eng = Engine(ST, TK, t, mode, clean, secrets, job_id=job_id, files=run.files,
                     holder=run.holder() if run.tracking else None, console_given=console_given)
        eng.sink = run.sink
        run.engine = eng
        steps_state = []
        for n, k in enumerate(eng.vis):
            s = t["steps"][k]
            steps_state.append({"index": n, "id": s["id"], "title": s["title"], "kind": s["kind"], "status": "pending",
                                "exit": None, "started": None, "ended": None, "tag": None,
                                "writes_app_data": bool(s.get("writes_app_data")),
                                "drives_ootp": bool(s.get("drives_ootp"))})
        shown_inputs = {k: v for k, v in clean.items()}
        run.files.write_state(title=t["title"], inputs=shown_inputs, secrets_given=[k for k, v in secrets.items() if v],
                              steps=steps_state)
        run.files.event("job_start", task=task_id, mode=mode, steps_total=len(steps_state))
        for name in _UNKNOWN_SECRETS:
            text = f"Ignored a secret input this task does not use: {name}"
            run.sink.line("  " + text)
            run.files.event("message", level="warn", text=text)
        if t["flags"].get("needs_archive") and archive_missing():
            if mode == "console":
                print("  " + ARCHIVE_MSG)
                print(r"  Or run: python tgs-viz\backtest\vintage_backup.py --restore")
            raise Invalid(ARCHIVE_MSG, fix_task="restore_ratings_db")
        run.files.write_state(status="running")
        if mode == "console":
            install_console_handlers(eng)
        res = eng.execute()
        status, code = res["status"], res["exit"]
        message = res.get("message")
        if status in ("failed",) and t.get("rollback"):
            maybe_rollback(eng, t, status)
        summary = eng.summary(res)
        run.close(status, code if mode == "console" else job_exit(status), message, None, summary)
        return code if mode == "console" else job_exit(status)
    except Invalid as e:
        if mode == "console" and e.message != ARCHIVE_MSG:
            print("  " + e.message)
        run.close("invalid", 2, e.message, e.fix_task, [e.message], e.errors)
        return 2
    except Refused as e:
        if mode == "console":
            print(e.message)
        h = e.holder or {}
        run.close("refused", 3, e.message.strip(), None, [e.message.strip()],
                  conflict={"job_id": h.get("job_id"), "title": h.get("title"), "lock": e.lock})
        return 3
    except Cancelled:
        print("  Cancelled. Nothing ran.")
        run.close("stopped", 130, "Cancelled before anything ran.", None, [])
        return 130
    except Stopped as e:
        if eng and eng.t.get("rollback"):
            maybe_rollback(eng, eng.t, "stopped")
        msg = {"ctrl_c": "Stopped with Ctrl+C.", "gate": "Stopped at your answer.",
               "excel": "Stopped while Excel had a sheet open.", "countdown": "Stopped before OOTP started."}.get(
            e.how, "Stopped from the Control page.")
        run.close("stopped", 130 if mode == "console" else 0, msg, None, eng.summary({}) if eng else [])
        return 130 if mode == "console" else 0
    except Killed:
        if eng and eng.t.get("rollback"):
            maybe_rollback(eng, eng.t, "killed")
        run.close("killed", 130 if mode == "console" else 4, "Killed from the Control page.", None,
                  eng.summary({}) if eng else [])
        return 130 if mode == "console" else 4
    except KeyboardInterrupt:
        run.close("stopped", 130, "Stopped with Ctrl+C.", None, [])
        return 130
    except BaseException as e:
        traceback.print_exc()
        last = (traceback.format_exception_only(type(e), e)[-1] or "").strip()
        run.close("failed", 1, last, None, [last])
        return 1


def job_exit(status):
    return {"done": 0, "partial": 0, "stopped": 0, "failed": 1, "invalid": 2, "refused": 3, "killed": 4}.get(status, 1)


def maybe_rollback(eng, t, status):
    rb = t.get("rollback")
    if not rb or rb.get("until_step") in eng.reached:
        return
    argv = eng.argv(rb["run"])
    eng.say("  Undoing the unfinished steps: " + " ".join(argv))
    try:
        env, _c = eng.step_env({"env": None})
        if eng.mode == "job":
            r = subprocess.run(argv, cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW if WIN else 0, timeout=600)
            if eng.sink:
                eng.sink.feed(r.stdout or b"")
                eng.sink.flush_carry()
        else:
            r = subprocess.run(argv, cwd=REPO, env=env, timeout=600)
        eng.say(f"  Undo finished (exit {r.returncode}).")
    except (OSError, subprocess.SubprocessError) as e:
        eng.say(f"  Undo failed: {type(e).__name__}.", "warn")


def install_console_handlers(eng):
    def handler(signum, frame):
        eng.interrupted = True
        if eng.asking:
            raise KeyboardInterrupt()

    for name in ("SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


# ---------------------------------------------------------------- commands

def cmd_console(task_id, positional, given):
    if os.environ.get("TGS_DRY_RUN", "").strip() == "1":
        try:
            inputs = dict(given)
            plan_inputs = console_positional(task_id, positional, inputs)
            plan = make_plan(task_id, "console", plan_inputs, {})
        except Invalid as e:
            print("  " + e.message)
            return 2
        except Exception as e:
            print("  " + str(e))
            return 2
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    inputs = dict(given)
    try:
        inputs = console_positional(task_id, positional, inputs)
    except Invalid as e:
        print("  " + e.message)
        return 2
    try:
        JL.prune_jobs()
    except Exception:
        pass
    job_id = JL.new_job_id(task_id if re.match(r"^[A-Za-z0-9_.-]+$", task_id) else "task")
    request = {"schema": 1, "task": task_id, "inputs": inputs, "secret_names": [], "mode": "console",
               "requested_at": now_iso(), "by": "console"}
    code = run_task_main("console", job_id, task_id, inputs, {}, request, console_given=set(inputs))
    return code


def console_positional(task_id, positional, inputs):
    """Map positional arguments to inputs with from_argv (the bat's %1 ...)."""
    if not positional:
        return inputs
    try:
        ST = load_settings()
        TK, t = get_task(ST, task_id, selftest_on())
    except Exception:
        return inputs
    for inp in t.get("inputs") or []:
        n = inp.get("from_argv")
        if n and len(positional) >= n:
            v = positional[n - 1].strip('"')
            if v != "":
                inputs.setdefault(inp["name"], v)
    return inputs


def cmd_job(job_dir):
    job_dir = os.path.abspath(job_dir)
    job_id = os.path.basename(job_dir)
    if not JL.JOB_ID_RE.match(job_id) or os.path.normcase(os.path.dirname(job_dir)) != os.path.normcase(JL.jobs_dir()):
        sys.stderr.write(f"run_task: not a job folder: {job_dir}\n")
        return 2
    try:
        JL.prune_jobs()
    except Exception:
        pass
    req = JL.read_json(os.path.join(job_dir, "request.json"))
    if not isinstance(req, dict):
        req = {}
    task_id = str(req.get("task") or "")
    raw = req.get("inputs") if isinstance(req.get("inputs"), dict) else {}
    secrets, unknown = collect_secrets(task_id)
    code = run_task_main("job", job_id, task_id or "unknown", raw, secrets, req, console_given=())
    return code


def collect_secrets(task_id):
    """Move TGS_SECRET_* from the environment into memory (3.1)."""
    found = {}
    for k in list(os.environ):
        if k.upper().startswith("TGS_SECRET_"):
            found[k.upper()[len("TGS_SECRET_"):]] = os.environ.pop(k)
    declared = []
    try:
        ST = load_settings()
        _TK, t = get_task(ST, task_id, selftest_on())
        declared = [i["name"] for i in t.get("inputs") or [] if i["type"] == "secret"]
    except Exception:
        declared = []
    out, unknown = {}, []
    for name, val in found.items():
        match = next((d for d in declared if d.lower() == name.lower()), None)
        if match:
            out[match] = val
        else:
            unknown.append(name)
    if unknown:
        _UNKNOWN_SECRETS.extend(unknown)
    return out, unknown


_UNKNOWN_SECRETS = []


def cmd_launch(job_dir):
    job_dir = os.path.abspath(job_dir)
    log = os.path.join(job_dir, "runner.log")
    argv = [sys.executable, os.path.abspath(__file__), "--job", job_dir]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB if WIN else 0
    try:
        out = open(log, "ab")
    except OSError as e:
        sys.stderr.write(f"run_task: cannot open runner.log: {e}\n")
        return 1
    try:
        try:
            subprocess.Popen(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             close_fds=True, creationflags=flags, start_new_session=not WIN)
        except OSError:
            if not WIN:
                raise
            subprocess.Popen(argv, cwd=REPO, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        out.write(f"run_task --launch could not start the runner: {e}\n".encode("utf-8", "replace"))
        out.close()
        return 1
    out.close()
    return 0


def cmd_kill(job_id):
    if not JL.JOB_ID_RE.match(job_id or ""):
        return {"ok": False, "status": "no_job"}
    entry = JL.read_json(JL.active_path(job_id))
    state_path = os.path.join(JL.job_dir(job_id), "state.json")
    if not isinstance(entry, dict) and os.path.exists(JL.active_path(job_id)):
        # an active entry cut short by a crash: the runner's pid is also in state.json
        st = JL.read_json(state_path)
        entry = st if isinstance(st, dict) and JL.alive(st) else {"pid": None, "pid_started": None}
    if not isinstance(entry, dict):
        st = JL.read_json(state_path) or {}
        return {"ok": False, "status": st.get("status") or "not_active"}
    if not JL.alive(entry):
        st = JL.reap_job(job_id)
        return {"ok": True, "status": st or "lost"}
    pid = entry["pid"]
    try:
        if WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                           timeout=30)
        else:
            JL.posix_kill_tree(pid)
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(50):
        if not JL.alive(entry):
            break
        time.sleep(0.1)
    if JL.alive(entry):
        return {"ok": False, "status": "still_running"}
    st = JL.read_json(state_path) or {}
    cur = st.get("current")
    steps = st.get("steps") or []
    drove = False
    if cur is not None and 0 <= cur < len(steps):
        drove = bool(steps[cur].get("drives_ootp")) and steps[cur].get("status") == "running"
    if drove:
        try:
            ST = load_settings()
            reset_input(ST)
        except Exception:
            pass
    for s in steps:
        if s.get("status") == "running":
            s["status"] = "killed"
        elif s.get("status") == "pending":
            s["status"] = "skipped"
    if st.get("status") not in JL.FINAL:
        st.update(status="killed", ended=now_iso(), prompt=None, waiting_for=None, pending_leagues=[],
                  locks_held=[], data_lock=None, exit_code=4, message="Killed from the Control page.")
        JL.write_json_atomic(state_path, st)
        JL.end_events(JL.job_dir(job_id), st)
    JL.release_all(job_id)
    JL.remove_active(job_id)
    return {"ok": True, "status": st.get("status") or "killed"}


def parse_cli(argv):
    """(command, args). Hand-parsed so the bat's %* passes through untouched."""
    opts = {"inputs": {}, "positional": [], "mode": "console", "inputs_json": None, "assume_json": None,
            "selftest": False}
    if not argv:
        return "help", opts
    if argv[0] != "--plan" and "--plan" in argv[1:]:
        # "run_task.py <task> --plan" must only print the plan, never start the
        # task (2026-10-02: a trailing --plan started a 5-hour retrain)
        i = argv.index("--plan")
        argv = ["--plan"] + argv[:i] + argv[i + 1:]
    head = argv[0]
    cmds = {"--launch": "launch", "--job": "job", "--plan": "plan", "--list-json": "list", "--validate": "validate",
            "--lock-status": "lock_status", "--reap": "reap", "--kill": "kill", "-h": "help", "--help": "help"}
    if head in cmds:
        cmd = cmds[head]
        rest = argv[1:]
        if cmd in ("launch", "job", "plan", "validate", "kill"):
            if not rest:
                raise SystemExit(f"run_task: {head} needs an argument")
            opts["arg"] = rest[0]
            rest = rest[1:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--mode" and i + 1 < len(rest):
                opts["mode"] = rest[i + 1]
                i += 2
            elif a == "--inputs-json" and i + 1 < len(rest):
                opts["inputs_json"] = rest[i + 1]
                i += 2
            elif a == "--assume-json" and i + 1 < len(rest):
                opts["assume_json"] = rest[i + 1]
                i += 2
            elif a == "--selftest":
                opts["selftest"] = True
                i += 1
            else:
                raise SystemExit(f"run_task: unknown option {a}")
        return cmd, opts
    opts["arg"] = head
    rest = argv[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--input" and i + 1 < len(rest):
            k, _, v = rest[i + 1].partition("=")
            opts["inputs"][k.strip()] = v
            i += 2
        elif a.startswith("--input="):
            k, _, v = a[len("--input="):].partition("=")
            opts["inputs"][k.strip()] = v
            i += 1
        else:
            opts["positional"].append(a)
            i += 1
    return "console", opts


def load_json_arg(s, what):
    if not s:
        return {}
    try:
        v = json.loads(s)
    except ValueError as e:
        raise SystemExit(f"run_task: {what} is not valid JSON: {e}")
    if not isinstance(v, dict):
        raise SystemExit(f"run_task: {what} must be a JSON object")
    return v


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def exit_code_for_os(code):
    if code is None:
        return 0
    code = int(code)
    if code >= 2 ** 31:
        return code - 2 ** 32
    return code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd, o = parse_cli(argv)
    if cmd == "help":
        print(__doc__)
        return 0
    if cmd == "list":
        emit(catalog(selftest_on(o["selftest"])))
        return 0
    if cmd == "plan":
        try:
            emit(make_plan(o["arg"], o["mode"], load_json_arg(o["inputs_json"], "--inputs-json"),
                           load_json_arg(o["assume_json"], "--assume-json")))
        except Invalid as e:
            emit({"task": o["arg"], "error": e.message})
            return 2
        return 0
    if cmd == "validate":
        try:
            ST = load_settings()
            _TK, t = get_task(ST, o["arg"], selftest_on())
            _c, _s, errs = validate_inputs(t, load_json_arg(o["inputs_json"], "--inputs-json"), {}, token_state(ST),
                                           "job", check_secrets=False)
            emit({"ok": not errs, "errors": errs})
            return 0
        except Invalid as e:
            emit({"ok": False, "errors": {"task": e.message}})
            return 0
    if cmd == "lock_status":
        emit(JL.lock_status())
        return 0
    if cmd == "reap":
        emit({"reaped": JL.reap_all()})
        return 0
    if cmd == "kill":
        emit(cmd_kill(o["arg"]))
        return 0
    if cmd == "launch":
        return cmd_launch(o["arg"])
    if cmd == "job":
        return cmd_job(o["arg"])
    return cmd_console(o["arg"], o["positional"], o["inputs"])


if __name__ == "__main__":
    sys.exit(exit_code_for_os(main()))

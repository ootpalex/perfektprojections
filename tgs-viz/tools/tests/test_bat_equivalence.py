"""Bat equivalence test (DESIGN.md 14.1).

Proves that the thin bat wrappers run what the old bats ran: for every
scenario, the old bat (interpreted by batsim from tests/legacy_bats) and
run_task.py --plan --mode console give the same commands, arguments, cookie,
prompts, pauses, exit code and echo text, except the differences listed in
DESIGN.md 6.5 and 14.1. It also checks the job-mode plans, the wrapper files,
the "old bats (backup)" copies and the .gitattributes rules.

  python tgs-viz\\tools\\tests\\test_bat_equivalence.py

Prints "18 bats, N scenarios, all equal" and exits 0, or lists every
difference and exits 1.
"""
import difflib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import batsim  # noqa: E402
import run_task  # noqa: E402
import settings as ST  # noqa: E402
import tasks as TK  # noqa: E402

LEGACY = os.path.join(HERE, "legacy_bats")
BACKUP = os.path.join(REPO, "old bats (backup)")
USERPROFILE = os.environ.get("USERPROFILE", r"C:\Users\tester")
CTRL_C = 3221225786
NO_RELOAD = "The open app updates itself; no reload needed."

# (bat path relative to the repo, task id)
BATS = [
    ("Get StatsPlus Ratings.bat", "get_ratings"),
    ("Get StatsPlus History.bat", "get_history"),
    ("Bank Season.bat", "bank_season"),
    ("Bank Dev Seasons.bat", "bank_dev"),
    ("Grind TGS.bat", "grind_tgs"),
    ("Grind BLM.bat", "grind_blm"),
    ("Recalibrate TGS.bat", "recalibrate_tgs"),
    ("Recalibrate BLM.bat", "recalibrate_blm"),
    ("Sim Dev League.bat", "sim_dev"),
    ("Sync Metadata.bat", "sync_metadata"),
    ("Update Dispersal Board.bat", "dispersal_board"),
    ("Update Draft Board.bat", "draft_board"),
    ("Update Regular Game.bat", "update.RG"),
    ("ootp/1 - Check OOTP (26).bat", "ootp_check_26"),
    ("ootp/2 - Grab a menu (26).bat", "ootp_grab_menu_26"),
    ("ootp/3 - Sim TGS (preview).bat", "sim_tgs_preview"),
    ("ootp/4 - Sim TGS.bat", "sim_tgs"),
    ("ootp/TEST year picker.bat", "ootp_test_year_26"),
]

# Allowed text changes (6.5): (rule, bat, old lines, new lines). Lines are as cmd prints them.
# Rules 7 to 10 (2026-10-02) fix stale bat text: 7 the dev signals header (ages 16-26; growth, gains and
# chances), 8 the History check job (no fixed 5-minute wait), 9 Bank Dev Seasons step 2b (it also rebuilds
# the DEV age curve), 10 the Recalibrate TGS steps and time. Rule 5 now names the 15-minute and daily limits.
ALLOWED = [
    (1, "Bank Dev Seasons.bat", ["  Done. Reload the web app and pick the DEV league."],
     ["  Done. " + NO_RELOAD + " Pick the DEV league."]),
    (1, "Sim Dev League.bat", ["  Done. Reload the web app and pick the DEV league."],
     ["  Done. " + NO_RELOAD + " Pick the DEV league."]),
    (1, "Recalibrate BLM.bat", ["  Done. Reload the webapp."], ["  Done. " + NO_RELOAD]),
    (1, "Recalibrate TGS.bat", ["  Done. Reload the webapp. Your Excel sheets recalc with the"],
     ["  Done. " + NO_RELOAD + " Your Excel sheets recalc with the"]),
    (1, "Sync Metadata.bat", ["  data, then refresh your browser."], ["  data. " + NO_RELOAD]),
    (1, "Update Dispersal Board.bat", ["  Done. Reload the webapp - the Draft tab is now the dispersal pool."],
     ["  Done. " + NO_RELOAD + " The Draft tab is now the dispersal pool."]),
    (1, "Update Draft Board.bat", ["  Done. Reload the webapp (switch leagues to see each board)."],
     ["  Done. " + NO_RELOAD + " Switch leagues to see each board."]),
    (1, "Update Regular Game.bat", ['  Done. Refresh the app (F5) and pick "Regular Game" in the league menu.'],
     ['  Done. ' + NO_RELOAD + ' Pick "Regular Game" in the league menu.']),
    (2, "Get StatsPlus History.bat",
     ["  no browser cookies were given. Nothing was fetched or stored. Run",
      "  StatsPlus Tokens.txt, or run this again and paste sessionid and csrftoken."],
     ["  no browser cookies were given. Nothing was fetched or stored. Paste the",
      "  league's token into StatsPlus Tokens.txt, or run this again and paste",
      "  sessionid and csrftoken."]),
    (4, "Bank Season.bat",
     ["  A league that is MID-SEASON is skipped automatically -",
      "  only completed seasons are ever banked. So it is always",
      "  safe to run this: whichever league is at its season end",
      "  gets banked, the other is left alone."],
     ["  Mid-season, the actuals step skips that league. The",
      "  projection snapshot still runs."]),
    (5, "Get StatsPlus History.bat",
     [" How long: about 15 snapshots per league. StatsPlus allows one ratings",
      " request per 5 minutes, so each snapshot takes about 5 minutes. Then the",
      " archive steps below rerun; the first time, the age curve and trends",
      " steps price every new snapshot once (about 40 seconds each). Plan on",
      " about 2 hours. Leave this window open."],
     [" How long: about an hour per run (5 dates, 15 minutes apart; StatsPlus",
      " allows 5 past-date requests a day). Each snapshot waits only when",
      " StatsPlus says it is too soon."]),
    (7, "Get StatsPlus Ratings.bat",
     [" --- Dev signals (DEV-league odds of becoming a regular, per 16-22 year old) ---"],
     [" --- Dev signals (growth, gains and chances from the DEV grid, per 16-26 year old) ---"]),
    (7, "Bank Dev Seasons.bat",
     [" --- 4. dev signals for TGS and BLM (the grid applied to each 16-22 year old) ---"],
     [" --- 4. dev signals for TGS and BLM (growth, gains and chances from the DEV grid, per 16-26 year old) ---"]),
    (8, "Get StatsPlus History.bat",
     [" one 5-minute check job only when no token is saved for the league, or"],
     [" one extra check job only when no token is saved for the league, or"]),
    (9, "Bank Dev Seasons.bat",
     [" --- 2b. value the new DEV seasons with each league's engine (only new seasons) ---"],
     [" --- 2b. value the new DEV seasons with each league's engine (only new seasons) and rebuild the DEV age "
      "curve ---"]),
    (10, "Recalibrate TGS.bat",
     ["  3. Rebuilds the webapp data from the cached StatsPlus pull.",
      "  No Excel needed. Takes ~30 seconds total."],
     ["  3. Refits the fitted layers and promotes the S-curves if",
      "     they pass their gates.",
      "  4. Rebuilds the Calibration page data and the webapp data",
      "     from the cached StatsPlus pull.",
      "  5. Offers to delete the clone saves (their data is archived).",
      "  No Excel needed. Takes 1 to 3 minutes plus your answers."]),
]
for _slug in ("tgs", "blm"):
    ALLOWED.append((3, "Get StatsPlus History.bat",
                    [f"  Current Token from statsplus.net/{_slug} Prefs, run Set StatsPlus",
                     "  Tokens.bat, then run this again."],
                    [f"  Current Token from statsplus.net/{_slug} Prefs, paste it into StatsPlus",
                     "  Tokens.txt, then run this again."]))
for _lg in ST.history_settings():
    ALLOWED.append((7, "Get StatsPlus History.bat",
                    [f" --- {_lg} dev signals (odds of becoming a regular, per 16-22 year old) ---"],
                    [f" --- {_lg} dev signals (growth, gains and chances from the DEV grid, per 16-26 year old) ---"]))
for _lid in ST.extra_leagues():
    _name = (ST.league(_lid) or {}).get("name") or _lid
    ALLOWED.append((6, "Bank Dev Seasons.bat", [],
                    [f"  {_name} still uses its old dev numbers. Run Update {_name} to refresh them."]))

GOLDEN = [
    ("Grind TGS.bat", "  AUTOMATICALLY recalibrates (constants -> sheets -> webapp),"),
    ("Get StatsPlus History.bat", "  STOPPED (code 2): no StatsPlus login. No token is saved for TGS and"),
    ("Sync Metadata.bat", "  Sync Data Points  -  Metadata  ->  Sheets"),
    ("Get StatsPlus Ratings.bat", "   F12  ->  Application (or Storage)  ->  Cookies  ->  statsplus.net"),
]

REGISTRY = TK.all_tasks(ST, {"selftest": False, "ratings_db_exists": True})


def task_def(task_id):
    return TK.find(REGISTRY, task_id)


def legacy_bytes(bat):
    return open(os.path.join(LEGACY, bat.replace("/", os.sep) + ".legacy"), "rb").read()


# ---------------------------------------------------------------- scenarios

class Scenario:
    def __init__(self, bat, task, name, exit_codes=None, answers=None, inputs=None, exists=None, args=(),
                 cycles=None, bat_exit_codes=None, expect=None):
        self.bat, self.task, self.name = bat, task, name
        self.exit_codes = exit_codes or {}
        self.bat_exit_codes = bat_exit_codes  # batsim's codes when they differ on purpose (difference 2)
        self.answers = answers or {}          # input name -> answer(s)
        self.inputs = inputs or {}
        self.exists = exists or {}
        self.args = list(args)
        self.cycles = cycles
        self.expect = expect or {}


# batsim variable names of the plan inputs
VAR_OF = {"sessionid": "SID", "csrftoken": "CSRF", "league": "LG"}
META = r"tgs-viz\engine\calib\BLM\metadata-latest.json"
DUMP = r"tgs-viz\backtest\dump_vintages.py"


def command_steps(task_id, kinds=("run", "probe")):
    return [s["id"] for s in task_def(task_id)["steps"] if s["kind"] in kinds and s.get("run")]


def scenarios():
    out = []
    # Get StatsPlus Ratings
    pipe = [s for s in command_steps("get_ratings") if not s.startswith("tok_") and s != "pull_report"]
    for tok in ("both", "TGS", "BLM", "none"):
        probes = {"tok_tgs": 0 if tok in ("both", "TGS") else 1, "tok_blm": 0 if tok in ("both", "BLM") else 1}
        for sid in ("blank", "given"):
            ans = {"sessionid": [""] if sid == "blank" else ["<sessionid>"],
                   "csrftoken": [""] if sid == "blank" else ["<csrftoken>"]}
            base = f"tokens={tok} sid={sid}"
            out.append(Scenario("Get StatsPlus Ratings.bat", "get_ratings", base + " all pass", dict(probes), ans))
            out.append(Scenario("Get StatsPlus Ratings.bat", "get_ratings", base + " pull_report=1",
                                dict(probes, pull_report=1), ans))
            for st in pipe:
                out.append(Scenario("Get StatsPlus Ratings.bat", "get_ratings", f"{base} {st}=1",
                                    dict(probes, **{st: 1}), ans))
    out.append(Scenario("Get StatsPlus Ratings.bat", "get_ratings", "ctrl+c in TGS-draft",
                        {"tok_tgs": 0, "tok_blm": 0, "tgs_draft": CTRL_C},
                        bat_exit_codes={"tok_tgs": 0, "tok_blm": 0, "tgs_draft": 1},
                        expect={"fails": ["TGS-draft"]}))
    # Get StatsPlus History
    later = ["agecurve", "trends", "devsignals", "ml_rows", "ml_score"]
    for typed in (["tgs"], ["TGS"], ["BLM"], ["x", "TGS"]):
        for tok in (True, False):
            for hx in (0, 1, 2, 3, 6, 7, 8, 9, 10, CTRL_C):
                for fail in [None] + later:
                    codes = {"tok": 0 if tok else 1, "history": hx}
                    if fail:
                        codes[fail] = 1
                    ans = {"league": list(typed), "sessionid": ["<sessionid>"], "csrftoken": ["<csrftoken>"]}
                    out.append(Scenario("Get StatsPlus History.bat", "get_history",
                                        f"typed={'/'.join(typed)} token={tok} history={hx} fail={fail}", codes, ans))
    # simple fails-style and fail-fast bats: all pass, each command failing alone
    for bat, tid in [("Bank Season.bat", "bank_season"), ("Update Draft Board.bat", "draft_board"),
                     ("Update Regular Game.bat", "update.RG"), ("Update Dispersal Board.bat", "dispersal_board"),
                     ("Bank Dev Seasons.bat", "bank_dev"), ("Recalibrate TGS.bat", "recalibrate_tgs"),
                     ("Recalibrate BLM.bat", "recalibrate_blm")]:
        out.append(Scenario(bat, tid, "all pass"))
        for st in command_steps(tid):
            out.append(Scenario(bat, tid, f"{st}=1", {st: 1}))
    out.append(Scenario("Bank Dev Seasons.bat", "bank_dev", "ctrl+c in dev_odds", {"dev_odds": CTRL_C},
                        bat_exit_codes={"dev_odds": 1}, expect={"exit": 1, "status": "failed"}))
    # Sync Metadata x metadata-latest.json
    for ex in (True, False):
        out.append(Scenario("Sync Metadata.bat", "sync_metadata", f"meta={ex} all pass", exists={META: ex}))
        for st in command_steps("sync_metadata"):
            out.append(Scenario("Sync Metadata.bat", "sync_metadata", f"meta={ex} {st}=1", {st: 1}, exists={META: ex}))
    # Sim Dev League x argument x dump_vintages.py
    for arg in ([], ["3"]):
        for ex in (True, False):
            nm = f"arg={arg[0] if arg else 'none'} dump={ex}"
            out.append(Scenario("Sim Dev League.bat", "sim_dev", nm + " all pass", exists={DUMP: ex}, args=arg))
            for st in command_steps("sim_dev"):
                out.append(Scenario("Sim Dev League.bat", "sim_dev", f"{nm} {st}=1", {st: 1}, exists={DUMP: ex},
                                    args=arg))
    # Grind: 2 cycles
    for lg in ("TGS", "BLM"):
        bat, tid = f"Grind {lg}.bat", f"grind_{lg.lower()}"
        for wc in (None, 1, 2):
            codes = {} if wc is None else {"winsim": [1 if wc == 1 else 0, 1 if wc == 2 else 0]}
            out.append(Scenario(bat, tid, f"winsim fails in cycle {wc}", codes, cycles=2))
        for st in [s["id"] for s in task_def(tid)["steps"] if s["kind"] == "run" and s["on_error"] == "fail"]:
            out.append(Scenario(bat, tid, f"{st} fails in cycle 1", {st: [1, 0]}, cycles=2))
    out.append(Scenario("Grind TGS.bat", "grind_tgs", "ctrl+c in winsim cycle 1", {"winsim": [CTRL_C, 0]},
                        bat_exit_codes={"winsim": [1, 0]}, cycles=2, expect={"exit": 1}))
    # the five ootp bats
    for bat, tid in BATS[13:]:
        out.append(Scenario(bat, tid, "plain"))
    return out


# ---------------------------------------------------------------- running both sides

def assume_of(sc, mode, codes=None):
    a = {"exit_codes": codes if codes is not None else sc.exit_codes, "exists": dict(sc.exists),
         "answers": {k: list(v) for k, v in sc.answers.items()} if mode == "console" else {}}
    if sc.cycles:
        a["cycles"] = sc.cycles
    return a


def plan_inputs(sc, mode):
    inp = dict(sc.inputs)
    if sc.task == "sim_dev" and sc.args:
        inp["years"] = sc.args[0]
    if mode == "job":
        for name, ans in sc.answers.items():
            last = ans[-1] if isinstance(ans, list) else ans
            inp[name] = last
    return inp


def norm_argv(task, argv):
    """Allowed difference 1: update.RG may carry --game 27 --calib BLM."""
    argv = list(argv)
    if task == "update.RG" and "export_league.py" in " ".join(argv):
        for flag, val in (("--game", "27"), ("--calib", "BLM")):
            if flag in argv:
                i = argv.index(flag)
                if argv[i + 1:i + 2] == [val]:
                    del argv[i:i + 2]
    return tuple(argv)


def plan_tokens(plan, task):
    out = []
    for it in plan["items"]:
        t = it["type"]
        if t == "echo":
            out += [("echo", ln) for ln in it["lines"]]
        elif t == "command":
            out.append(("cmd", norm_argv(task, it["argv"]), it["env"]["STATSPLUS_COOKIE"]))
        elif t == "prompt":
            out.append(("prompt", it["text"]))
        elif t == "pause":
            out.append(("pause",))
        elif t == "confirm":
            out.append(("confirm", it["step_id"]))
        elif t == "gate":
            out.append(("gate", it["step_id"]))
    return out


def run_bat(sc, step_of):
    codes = sc.bat_exit_codes if sc.bat_exit_codes is not None else sc.exit_codes

    def exit_for(argv, n):
        sid = step_of.get(tuple(argv))
        if sid is None:
            return 0
        c = codes.get(sid, 0)
        if isinstance(c, list):
            return c[n] if n < len(c) else 0
        return c

    answers = {}
    for name, ans in sc.answers.items():
        answers[VAR_OF.get(name, name.upper())] = list(ans)
    r = batsim.run_bat(legacy_bytes(sc.bat), args=sc.args, env={"USERPROFILE": USERPROFILE}, answers=answers,
                       exit_for=exit_for, exists=sc.exists, loop_label="loop" if sc.cycles else None,
                       max_cycles=sc.cycles)
    trans = list(r["transcript"])
    if r["exit"] is not None:
        # the final pause is the wrapper's now
        for i in range(len(trans) - 1, -1, -1):
            if trans[i][0] == "echo":
                continue
            if trans[i][0] == "pause":
                del trans[i]
            break
    fails = (r["env"].get("FAILS") or "").split()
    return trans, r["exit"], fails


def step_map(sc):
    """argv -> step id, from the scenario's plan and the all-pass plan."""
    m = {}
    for codes in (sc.exit_codes, {}):
        p = run_task.make_plan(sc.task, "console", plan_inputs(sc, "console"), assume_of(sc, "console", codes))
        for it in p["items"]:
            if it["type"] == "command":
                m.setdefault(tuple(it["argv"]), it["step_id"])
                m.setdefault(norm_argv(sc.task, it["argv"]), it["step_id"])
    return m


def explain(bat, old, new):
    """Rule numbers that explain old -> new, or None."""
    rules = []
    o, n = list(old), list(new)
    while o or n:
        for rule, b, ao, an in ALLOWED:
            if b != bat:
                continue
            if o[:len(ao)] == ao and n[:len(an)] == an and (ao or an):
                o, n = o[len(ao):], n[len(an):]
                rules.append(rule)
                break
        else:
            return None
    return rules


def compare(sc, report):
    problems = []
    plan = run_task.make_plan(sc.task, "console", plan_inputs(sc, "console"), assume_of(sc, "console"))
    smap = step_map(sc)
    bt, bexit, bfails = run_bat(sc, smap)
    pt = plan_tokens(plan, sc.task)
    bt = [t if t[0] != "cmd" else ("cmd", norm_argv(sc.task, t[1]), t[2]) for t in bt]
    b_ne = [t for t in bt if t[0] != "echo"]
    p_ne = [t for t in pt if t[0] != "echo"]
    if b_ne != p_ne:
        for d in difflib.unified_diff([repr(t) for t in b_ne], [repr(t) for t in p_ne], "bat", "run_task", lineterm="",
                                      n=1):
            problems.append("    " + d)
        problems.insert(0, "  commands, prompts or pauses differ:")
    sm = difflib.SequenceMatcher(None, bt, pt, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a, b = bt[i1:i2], pt[j1:j2]
        if any(t[0] != "echo" for t in a + b):
            continue  # already reported above
        old, new = [t[1] for t in a], [t[1] for t in b]
        rules = explain(sc.bat, old, new)
        if rules is None:
            problems.append("  echo text differs:")
            problems += ["    - " + x for x in old] + ["    + " + x for x in new]
        else:
            report.setdefault((sc.bat, tuple(old), tuple(new)), sorted(set(rules)))
    exp_exit = sc.expect.get("exit", bexit)
    if plan["exit_code"] != exp_exit:
        problems.append(f"  exit code: bat {bexit}, run_task {plan['exit_code']}")
    exp_fails = sc.expect.get("fails", bfails)
    if plan["fails"] != exp_fails:
        problems.append(f"  FAILS: bat {bfails}, run_task {plan['fails']}")
    if "status" in sc.expect and plan["status"] != sc.expect["status"]:
        problems.append(f"  status: expected {sc.expect['status']}, run_task {plan['status']}")
    problems += compare_job(sc, plan)
    return problems


def job_text_map():
    """6.3: echo lines with a page wording ({"console": ..., "job": ...} in the registry)."""
    out = {}

    def walk(v):
        if isinstance(v, dict):
            if set(v) == {"console", "job"} and isinstance(v["console"], str):
                out[v["console"]] = v["job"]
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(TK.T)
    return out


JOB_TEXT = None


def substitute(console_plan, task_id):
    """The job plan the substitutions of 6.3 make from a console plan."""
    global JOB_TEXT
    if JOB_TEXT is None:
        JOB_TEXT = job_text_map()
    t = task_def(task_id)
    by_id = {s["id"]: s for s in t["steps"]}
    out = []
    for it in console_plan["items"]:
        ty = it["type"]
        if ty == "prompt" or (ty == "echo" and it.get("for_prompt")):
            continue
        if ty == "echo":
            it = dict(it, lines=[JOB_TEXT.get(ln, ln) for ln in it["lines"]])
        if ty == "pause":
            s = by_id.get(it["step_id"])
            if s and s.get("start"):
                continue
            out.append(("gate", it["step_id"]))
            continue
        if ty == "command":
            s = by_id.get(it["step_id"])
            if s and s.get("job"):
                j = s["job"]
                eng = run_task.Engine(ST, TK, t, "job", {}, {}, plan=True)
                out.append(("cmd", tuple(eng.argv(j["preview"])), it["env"]["STATSPLUS_COOKIE"]))
                out.append(("confirm", it["step_id"]))
                out.append(("cmd", tuple(eng.argv(j["apply"])), it["env"]["STATSPLUS_COOKIE"]))
                continue
        out += plan_tokens({"items": [it]}, task_id)
    return out


def compare_job(sc, console_plan):
    job = run_task.make_plan(sc.task, "job", plan_inputs(sc, "job"), assume_of(sc, "job"))
    want = substitute(console_plan, sc.task)
    got = plan_tokens(job, sc.task)
    probs = []
    if want != got:
        probs.append("  job plan differs from the console plan after the 6.3 substitutions:")
        for d in difflib.unified_diff([repr(x) for x in want], [repr(x) for x in got], "expected", "job", lineterm="",
                                      n=1):
            probs.append("    " + d)
    if job["fails"] != console_plan["fails"] or job["status"] != console_plan["status"]:
        probs.append(f"  job plan verdict {job['status']} {job['fails']} != console {console_plan['status']} "
                     f"{console_plan['fails']}")
    return probs


# ---------------------------------------------------------------- golden lines, CLI parity

def check_golden():
    probs = []
    cases = {
        "Grind TGS.bat": Scenario("Grind TGS.bat", "grind_tgs", "golden", cycles=1),
        "Get StatsPlus History.bat": Scenario("Get StatsPlus History.bat", "get_history", "golden",
                                              {"tok": 1, "history": 2},
                                              {"league": ["TGS"], "sessionid": [""], "csrftoken": [""]}),
        "Sync Metadata.bat": Scenario("Sync Metadata.bat", "sync_metadata", "golden", exists={META: True}),
        "Get StatsPlus Ratings.bat": Scenario("Get StatsPlus Ratings.bat", "get_ratings", "golden"),
    }
    for bat, line in GOLDEN:
        sc = cases[bat]
        bt, _e, _f = run_bat(sc, step_map(sc))
        plan = run_task.make_plan(sc.task, "console", plan_inputs(sc, "console"), assume_of(sc, "console"))
        if ("echo", line) not in bt:
            probs.append(f"golden line missing from batsim ({bat}): {line!r}")
        if ("echo", line) not in plan_tokens(plan, sc.task):
            probs.append(f"golden line missing from run_task ({bat}): {line!r}")
    return probs


def check_cli():
    """A few plans through the real command line equal the in-process ones."""
    probs = []
    cases = [
        ("get_ratings", {}, {"exit_codes": {"tok_tgs": 1, "tgs_draft": 1},
                             "answers": {"sessionid": ["<sessionid>"], "csrftoken": ["<csrftoken>"]}}),
        ("grind_blm", {}, {"cycles": 2, "exit_codes": {"winsim": [0, 1]}}),
        ("sim_dev", {"years": "3"}, {"exists": {DUMP: False}}),
    ]
    for tid, inputs, assume in cases:
        cp = subprocess.run([sys.executable, os.path.join(TOOLS, "run_task.py"), "--plan", tid, "--mode", "console",
                             "--inputs-json", json.dumps(inputs), "--assume-json", json.dumps(assume)],
                            cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        try:
            got = json.loads(cp.stdout)
        except ValueError:
            probs.append(f"CLI plan for {tid} is not JSON: {cp.stdout[:200]} {cp.stderr[-400:]}")
            continue
        want = run_task.make_plan(tid, "console", inputs, assume)
        if got != want:
            probs.append(f"CLI plan for {tid} differs from the in-process plan")
    # %USERPROFILE% comes from the environment the plan sees
    fake = r"C:\Users\someone else"
    cp = subprocess.run([sys.executable, os.path.join(TOOLS, "run_task.py"), "--plan", "grind_blm",
                         "--assume-json", json.dumps({"env": {"USERPROFILE": fake}})],
                        cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    p = json.loads(cp.stdout)
    cal = next(it for it in p["items"] if it["type"] == "command" and it["step_id"] == "calibrate")
    want = fake + "/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/0blm*.lg"
    if cal["argv"][cal["argv"].index("--dumps") + 1] != want:
        probs.append("grind_blm --dumps does not follow USERPROFILE: " + cal["argv"][cal["argv"].index("--dumps") + 1])
    return probs


# ---------------------------------------------------------------- wrappers, backups, attributes

TEMPLATE = [
    'set "TGS_PY=python"',
    'python -c "" >nul 2>nul && goto tgs_run',
    'set "TGS_PY=py -3"',
    'py -3 -c "" >nul 2>nul && goto tgs_run',
    "echo.",
    "echo   Python is not installed, or it is not on PATH.",
    'echo   Install Python 3.13 from python.org and tick "Add python.exe to PATH".',
    "echo   Then start this again.",
    "pause",
    "exit /b 9009",
    ":tgs_run",
    '%TGS_PY% "tgs-viz\\tools\\run_task.py" {task} %*',
    'set "RC=%errorlevel%"',
    "pause",
    "exit /b %RC%",
]


def legacy_head(bat):
    lines = batsim.read_lines(legacy_bytes(bat))
    title = next((ln for ln in lines if ln.lower().startswith("title ")), None)
    cd = next(ln for ln in lines if ln.lower().startswith("cd /d"))
    return title, cd


def expected_wrapper(bat, task):
    title, cd = legacy_head(bat)
    lines = ["@echo off"] + ([title] if title else []) + [cd] + [ln.replace("{task}", task) for ln in TEMPLATE]
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def check_wrappers():
    probs = []
    pairs = list(BATS) + [("Check Setup.bat", "doctor")]
    for bat, tid in pairs:
        p = os.path.join(REPO, bat.replace("/", os.sep))
        try:
            data = open(p, "rb").read()
        except OSError:
            probs.append(f"wrapper missing: {bat}")
            continue
        if bat == "Check Setup.bat":
            lines = ["@echo off", "title TGS - Setup check", 'cd /d "%~dp0"'] + [ln.replace("{task}", tid) for ln in TEMPLATE]
            want = ("\r\n".join(lines) + "\r\n").encode("ascii")
        else:
            want = expected_wrapper(bat, tid)
        if b"\n" in data.replace(b"\r\n", b"") or b"\r" in data.replace(b"\r\n", b""):
            probs.append(f"wrapper is not CRLF only: {bat}")
        try:
            data.decode("ascii")
        except UnicodeDecodeError:
            probs.append(f"wrapper is not ASCII: {bat}")
        if data != want:
            probs.append(f"wrapper text differs from the template: {bat}")
    return probs


def check_backups():
    probs = []
    for bat, _tid in BATS:
        p = os.path.join(BACKUP, bat.replace("/", os.sep))
        try:
            data = open(p, "rb").read()
        except OSError:
            probs.append(f"backup missing: old bats (backup)/{bat}")
            continue
        got = batsim.read_lines(data)
        want = batsim.read_lines(legacy_bytes(bat))
        root = not bat.startswith("ootp/")
        old_cd = 'cd /d "%~dp0"' if root else 'cd /d "%~dp0.."'
        new_cd = 'cd /d "%~dp0.."' if root else 'cd /d "%~dp0..\\.."'
        want = [new_cd if ln == old_cd else ln for ln in want]
        if got != want:
            probs.append(f"backup differs from its legacy fixture beyond the cd line: {bat}")
        if b"\n" in data.replace(b"\r\n", b""):
            probs.append(f"backup is not CRLF: {bat}")
    return probs


def check_attributes():
    probs = []
    try:
        a = subprocess.run(["git", "check-attr", "text", "eol", "--", "Grind TGS.bat"], cwd=REPO, capture_output=True,
                           text=True).stdout
        b = subprocess.run(["git", "check-attr", "text", "--", "tgs-viz/tools/tests/legacy_bats/Grind TGS.bat.legacy"],
                           cwd=REPO, capture_output=True, text=True).stdout
    except OSError:
        return ["git is missing: cannot check .gitattributes"]
    if "eol: crlf" not in a:
        probs.append("git check-attr: Grind TGS.bat has no eol: crlf (" + a.strip() + ")")
    if "text: unset" not in b:
        probs.append("git check-attr: legacy fixtures are not -text (" + b.strip() + ")")
    return probs


def check_wrapper_smoke():
    """14.2: every wrapper with TGS_DRY_RUN=1 prints the --plan JSON and exits 0,
    and takes no lock, writes no job folder and no active entry."""
    import tempfile
    probs = []
    ctl = tempfile.mkdtemp(prefix="tgs-smoke-")
    env = dict(os.environ, TGS_DRY_RUN="1", TGS_CONTROL_DIR=ctl)
    env.pop("TGS_SELFTEST", None)
    # the legacy Sync Metadata title line holds "->", so cmd also creates an empty
    # file named "Sheets)" in the repo root, as the old bat did; remove ours
    stray = os.path.join(REPO, "Sheets)")
    stray_before = os.path.exists(stray)
    pairs = list(BATS) + [("Check Setup.bat", "doctor")]
    try:
        for bat, tid in pairs:
            path = os.path.join(REPO, bat.replace("/", os.sep))
            proc = subprocess.Popen(["cmd", "/c", "call", path], cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                out, err = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                out, err = proc.communicate()
                probs.append(f"wrapper smoke: {bat} did not finish within 60 s")
            cp = subprocess.CompletedProcess(proc.args, proc.returncode, out.decode("utf-8", "replace"),
                                             err.decode("utf-8", "replace"))
            line = next((ln for ln in cp.stdout.splitlines() if ln.startswith("{")), None)
            want = subprocess.run([sys.executable, os.path.join(TOOLS, "run_task.py"), "--plan", tid, "--mode",
                                   "console"], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8")
            if cp.returncode != 0:
                probs.append(f"wrapper smoke: {bat} exited {cp.returncode}: {cp.stdout[-300:]} {cp.stderr[-300:]}")
            if line is None or json.loads(line) != json.loads(want.stdout):
                probs.append(f"wrapper smoke: {bat} did not print its --plan")
        left = [n for n in ("jobs", "locks", "active") if os.path.isdir(os.path.join(ctl, n))
                and os.listdir(os.path.join(ctl, n))]
        if left:
            probs.append(f"wrapper smoke: dry runs wrote into the control folder: {left}")
    finally:
        if not stray_before and os.path.exists(stray) and os.path.getsize(stray) == 0:
            os.remove(stray)
    if not probs:
        print(f"Wrapper smoke run: {len(pairs)} wrappers printed their plan and exited 0; no lock, no job folder.")
    return probs


# ---------------------------------------------------------------- main

def main():
    all_sc = scenarios()
    failures = []
    report = {}
    for sc in all_sc:
        probs = compare(sc, report)
        if probs:
            failures.append((sc, probs))
    extra = check_golden() + check_cli() + check_wrappers() + check_backups() + check_attributes()
    if "--no-smoke" not in sys.argv:
        extra += check_wrapper_smoke()
    bats = {sc.bat for sc in all_sc}
    print("Allowed text changes (DESIGN.md 6.5), as run_task prints them:")
    seen = set()
    for (bat, old, new), rules in sorted(report.items()):
        key = (bat, old, new)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {bat}: rule {', '.join(map(str, rules))}")
        for x in old:
            print("    - " + x)
        for x in new:
            print("    + " + x)
    print("Difference 1: update.RG passes --game 27 --calib BLM (export_league.py defaults).")
    print("Difference 2: a step ending with 3221225786 (Ctrl+C) counts as failed (checked in 3 scenarios).")
    if failures or extra:
        for sc, probs in failures[:40]:
            print(f"DIFF {sc.bat} [{sc.name}]")
            for p in probs[:60]:
                print(p)
        if len(failures) > 40:
            print(f"... and {len(failures) - 40} more scenarios differ")
        for p in extra:
            print("FAIL " + p)
        print(f"{len(bats)} bats, {len(all_sc)} scenarios, {len(failures)} differ, {len(extra)} other problems")
        return 1
    print(f"{len(bats)} bats, {len(all_sc)} scenarios, all equal")
    return 0


if __name__ == "__main__":
    if os.name != "nt":
        # It proves the Windows .bat wrappers: batsim's commands spell paths with backslashes and
        # run_task's plan uses the native separator off Windows (run_task.native).
        print("test_bat_equivalence: skipped, Windows only (it proves the .bat wrappers).")
        sys.exit(0)
    sys.exit(main())

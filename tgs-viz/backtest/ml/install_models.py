"""
install_models.py - install the original author's trained DEV machine-learning
models on this machine, and check that they load here.

The models are not trained on the Mac. The author trains them (peak.py / path.py
fit-final, BLM with scikit-learn 1.7.2 on Python 3.14 under Windows) and hands
over his `tgs-viz/backtest/.dev_cache/` folder. score.py needs, per basis <B>:
  .dev_cache/ml/models/<B>/peak_manifest.json, path_manifest.json  + every
                                    pickle the two manifests list
  .dev_cache/ml/data/schema_<B>.json
(SSB is scored with the BLM set: its basis is BLM.)

What this does:
  1 find     --from <dir> may be his whole .dev_cache folder, a .dev_cache/ml
             folder, or any folder that holds models/<B>/ and data/schema_<B>.json
  2 verify   manifests parse, the basis they name is <B>, every file they list
             exists, the schema exists; reads the library versions the models
             were trained with and compares them with this interpreter
  3 copy     source files are only read, never moved or changed. A destination
             file that already exists stops the run unless --force; --force moves
             it aside as <name>.bak-<date> (nothing is deleted)
  4 load     unpickles every model, capturing warnings (scikit-learn's
             InconsistentVersionWarning) and errors, one line per file
  5 recipe   when versions differ or a model warns / fails to load, prints the
             steps for a matching virtual environment and the python.ml line for
             settings.local.json (printed only, nothing is run)

Run it with the interpreter that will score (python.ml in settings.local.json):
  install_models.py --from <dir> [--basis BLM] [--dry-run] [--force]
  install_models.py --check [--basis BLM]       verify what is installed already
  install_models.py --from <dir> --score SSB    then time a score.py dry run
                                                (wall time, peak memory)

Exit code: 0 installed / checked and every model loads clean with matching
versions; 1 files fine but versions differ or a model warned / failed to load;
2 nothing installed (bad files, or a destination file exists and no --force).
"""
import argparse
import datetime
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import predict as PR  # noqa: E402

MANIFESTS = ("peak_manifest.json", "path_manifest.json")


def log(*a):
    print(*a, flush=True)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------- finding
def find_ml_root(src):
    """The folder under `src` that holds models/<B>/ (the layout of .dev_cache/ml), or None. Tries
    src itself, then the places his whole .dev_cache folder (or the repo) puts it."""
    for sub in ("", "ml", os.path.join(".dev_cache", "ml"), os.path.join("backtest", ".dev_cache", "ml"),
                os.path.join("tgs-viz", "backtest", ".dev_cache", "ml")):
        root = os.path.join(src, sub) if sub else src
        md = os.path.join(root, "models")
        if os.path.isdir(md) and any(os.path.isfile(os.path.join(md, b, "peak_manifest.json")) for b in C.BASES):
            return root
    return None


def bases_in(root):
    """Bases (C.BASES order) that have a peak_manifest.json under root/models."""
    return [b for b in C.BASES if os.path.isfile(os.path.join(root, "models", b, "peak_manifest.json"))]


# ---------------------------------------------------------------- verifying
def listed_files(pm, am):
    """Sorted pickle file names the two manifests list. Raises KeyError / TypeError on a malformed manifest."""
    names = set()
    for role in C.ROLES:
        for info in pm["roles"][role]["models"].values():
            names.add(info["file"])
        for info in am[role]["models"].values():
            names.add(info["file"])
    return sorted(names)


def verify(root, basis):
    """Check one basis under an ml root (root/models/<basis>, root/data/schema_<basis>.json).
    Returns {'basis', 'errors': [...], 'notes': [...], 'files': [relative model files incl. manifests],
    'schema': path or None, 'recorded': {...}, 'manifests': (pm, am) or None}. No error means the set is
    complete and consistent."""
    d = os.path.join(root, "models", basis)
    out = {"basis": basis, "errors": [], "notes": [], "files": [], "schema": None, "recorded": {},
           "manifests": None, "dir": d}
    err = out["errors"]
    loaded = {}
    for fn in MANIFESTS:
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            err.append(f"{fn} is missing ({p})")
            continue
        try:
            loaded[fn] = _read_json(p)
        except (OSError, ValueError) as e:
            err.append(f"{fn} does not parse: {e}")
    if len(loaded) == 2:
        pm, am = loaded["peak_manifest.json"], loaded["path_manifest.json"]
        out["manifests"] = (pm, am)
        for what, got in (("peak_manifest.json", pm.get("basis")), ("path_manifest.json", (am.get("_meta") or {}).get("basis"))):
            if got is None:
                out["notes"].append(f"{what} records no basis (older manifest); load_bundle accepts that")
            elif got != basis:
                err.append(f"{what} is for basis {got}, not {basis}")
        try:
            names = listed_files(pm, am)
        except (KeyError, TypeError, AttributeError) as e:
            names = []
            err.append(f"a manifest is not in the expected shape (missing {e})")
        for n in names:
            if os.path.isabs(n) or ".." in n.replace("\\", "/").split("/"):
                err.append(f"a manifest lists a file outside the model folder: {n}")
            elif not os.path.isfile(os.path.join(d, n)):
                err.append(f"listed model file is missing: {n}")
            else:
                out["files"].append(n)
        out["recorded"] = PR.recorded_versions(pm, am)
    sp = os.path.join(root, "data", f"schema_{basis}.json")
    if not os.path.isfile(sp):
        err.append(f"schema is missing ({sp})")
    else:
        try:
            _read_json(sp)
            out["schema"] = sp
        except (OSError, ValueError) as e:
            err.append(f"schema_{basis}.json does not parse: {e}")
    if out["manifests"]:
        out["files"] = list(MANIFESTS) + out["files"]
    return out


def compare_versions(recorded, now=None):
    """(lines, mismatches): one plain line per library, and the scikit-learn / xgboost mismatches
    [(library, trained, installed)] from predict.version_mismatches. Python is reported, not judged."""
    now = now or PR.installed_versions()
    lines = []
    for lib, label in (("sklearn", "scikit-learn"), ("xgboost", "xgboost"), ("python", "Python")):
        rec, have = recorded.get(lib), now.get(lib)
        if rec is None and lib == "xgboost":
            lines.append("  xgboost       : not recorded (the quantile models are scikit-learn)")
        elif rec is None:
            lines.append(f"  {label:<13} : not recorded; installed {have}")
        elif lib == "python":
            same = rec.split(".")[:2] == (have or "").split(".")[:2]
            lines.append(f"  {label:<13} : trained {rec}, installed {have}" + ("" if same else "  (different minor version)"))
        else:
            lines.append(f"  {label:<13} : trained {rec}, installed {have}" + ("" if rec == have else "  MISMATCH"))
    return lines, PR.version_mismatches(recorded, now)


# ---------------------------------------------------------------- loading
def load_test(model_dir, names):
    """[(file, 'OK' | 'warning' | 'error', detail)] from unpickling each file with every warning captured
    (scikit-learn's InconsistentVersionWarning and any other)."""
    res = []
    for n in names:
        if not n.endswith(".pkl"):
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                with open(os.path.join(model_dir, n), "rb") as fh:
                    pickle.load(fh)
            except Exception as e:      # any failure to read a model is the answer, not a crash
                res.append((n, "error", f"{type(e).__name__}: {e}"))
                continue
        if caught:
            kinds = sorted({w.category.__name__ for w in caught})
            res.append((n, "warning", f"{', '.join(kinds)}: {str(caught[0].message).splitlines()[0][:200]}"))
        else:
            res.append((n, "OK", ""))
    return res


def venv_recipe(basis, recorded):
    """Lines: how to build a venv with the recorded versions and point python.ml at it. Printed only."""
    sk, xg, py = recorded.get("sklearn"), recorded.get("xgboost"), recorded.get("python")
    pins = [f"scikit-learn=={sk}" if sk else "scikit-learn", "numpy", "pandas"]
    pins.append(f"xgboost=={xg}" if xg else None)
    pins = [p for p in pins if p]
    return [
        f"To score the {basis} models with the versions they were trained with:",
        f"  1. python -m venv ~/venvs/ootp-ml          (use a Python {py or 'of the recorded version'}"
        " if you have one;",
        "                                              otherwise the nearest minor version with wheels)",
        f"  2. ~/venvs/ootp-ml/bin/python -m pip install {' '.join(pins)}",
        "     (Windows: %USERPROFILE%\\venvs\\ootp-ml\\Scripts\\python.exe)",
        "     numpy and pandas versions are not recorded in the manifests; if loading still warns, ask the "
        "author for his",
        "     `pip freeze`, or his requirements-ml.txt, and pin those too.",
        '  3. In settings.local.json (repo root) set "python": {"ml": ["<full path to that venv\'s python>"]}',
        "     (python.main can stay as it is; only the ML steps use python.ml), then re-run this script with that",
        "     interpreter: <that python> tgs-viz/backtest/ml/install_models.py --check --basis " + basis,
        "Nothing above was run.",
    ]


# ---------------------------------------------------------------- copying
def _aside_name(path, stamp):
    cand = f"{path}.bak-{stamp}"
    n = 1
    while os.path.exists(cand):
        n += 1
        cand = f"{path}.bak-{stamp}-{n}"
    return cand


def plan_copy(root, dest_root, basis, v):
    """[(src, dst)] for the files of one verified basis: manifests + listed models into
    dest_root/models/<basis>/, the schema into dest_root/data/."""
    pairs = [(os.path.join(root, "models", basis, n), os.path.join(dest_root, "models", basis, n))
             for n in v["files"]]
    pairs.append((v["schema"], os.path.join(dest_root, "data", f"schema_{basis}.json")))
    return pairs


def install(root, dest_root, bases, dry_run=False, force=False, stamp=None, out=log):
    """Verify and copy the given bases from `root` into `dest_root`. Returns
    {'ok': bool, 'verified': {basis: verify()}, 'copied': [dst], 'moved_aside': [(old, new)],
    'unchanged': [dst], 'refused': [dst]}. Nothing is copied when any basis fails verification or any
    destination file would be overwritten without force. The source is only read."""
    stamp = stamp or datetime.date.today().strftime("%Y%m%d")
    res = {"ok": False, "verified": {}, "copied": [], "moved_aside": [], "unchanged": [], "refused": []}
    pairs = []
    for b in bases:
        v = verify(root, b)
        res["verified"][b] = v
        for e in v["errors"]:
            out(f"[{b}] ERROR: {e}")
        for n in v["notes"]:
            out(f"[{b}] note: {n}")
        if not v["errors"]:
            pairs += plan_copy(root, dest_root, b, v)
    if any(v["errors"] for v in res["verified"].values()):
        out("Nothing installed: fix the files above (ask the author to resend the missing ones).")
        return res
    todo = []
    for src, dst in pairs:
        if os.path.exists(dst):
            if _sha(src) == _sha(dst):
                res["unchanged"].append(dst)
                continue
            if not force:
                res["refused"].append(dst)
                continue
        todo.append((src, dst))
    if res["refused"]:
        for dst in res["refused"]:
            out(f"REFUSED: {dst} already exists and differs from the new file (add --force to move it aside)")
        out("Nothing installed.")
        return res
    for src, dst in todo:
        if os.path.exists(dst):
            aside = _aside_name(dst, stamp)
            out(f"{'would move' if dry_run else 'moving'} aside: {dst} -> {os.path.basename(aside)}")
            if not dry_run:
                os.replace(dst, aside)
            res["moved_aside"].append((dst, aside))
        out(f"{'would copy' if dry_run else 'copy'}: {src} -> {dst}")
        if not dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        res["copied"].append(dst)
    for dst in res["unchanged"]:
        out(f"unchanged (identical file already there): {dst}")
    res["ok"] = True
    return res


# ---------------------------------------------------------------- scoring run
def run_score(league):
    """Run score.py --league <league> (a dry run: no --write) in a subprocess; returns
    {'returncode', 'seconds', 'peak_rss_mb', 'tail'}. Peak memory is getrusage(RUSAGE_CHILDREN).ru_maxrss
    (bytes on macOS, kilobytes on Linux); None where the resource module does not exist (Windows)."""
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "score.py"), "--league", league]
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                       errors="replace")
    secs = time.time() - t0
    rss = None
    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        rss = raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024
    except ImportError:
        pass
    return {"returncode": p.returncode, "seconds": secs, "peak_rss_mb": rss,
            "tail": p.stdout.strip().splitlines()[-12:]}


# ---------------------------------------------------------------- reporting
def report_basis(model_dir, v, out=log):
    """Print the version comparison and the load test of one verified basis in model_dir; return
    (clean, recorded) where clean = versions match and every model loads without a warning."""
    b = v["basis"]
    out(f"[{b}] library versions (trained vs this interpreter, {sys.executable}):")
    lines, bad = compare_versions(v["recorded"])
    for ln in lines:
        out(ln)
    out(f"[{b}] load test ({model_dir}):")
    results = load_test(model_dir, v["files"])
    for n, st, detail in results:
        out(f"  {st:<8} {n}" + (f"   {detail}" if detail else ""))
    n_ok = sum(1 for r in results if r[1] == "OK")
    out(f"[{b}] {n_ok} OK, {sum(1 for r in results if r[1] == 'warning')} warning, "
        f"{sum(1 for r in results if r[1] == 'error')} error of {len(results)} model files")
    return (not bad and n_ok == len(results)), v["recorded"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", help="the author's .dev_cache folder, its ml folder, or a folder with "
                                               "models/<BASIS>/ and data/schema_<BASIS>.json")
    ap.add_argument("--basis", choices=C.BASES, help="one basis (default: every basis found)")
    ap.add_argument("--dry-run", action="store_true", help="verify and show what would be copied; write nothing")
    ap.add_argument("--force", action="store_true", help="move existing destination files aside (.bak-<date>) "
                                                          "instead of refusing")
    ap.add_argument("--check", action="store_true", help="no copy: verify and load-test what is installed here")
    ap.add_argument("--score", metavar="LEAGUE", help="after installing, run score.py --league LEAGUE (dry run) and "
                                                      "report wall time and peak memory")
    ap.add_argument("--dest", default=C.ML_ROOT, help=argparse.SUPPRESS)      # tests: another .dev_cache/ml
    args = ap.parse_args(argv)
    if bool(args.src) == bool(args.check):
        ap.error("give exactly one of --from <dir> or --check")

    dest = os.path.abspath(args.dest)
    if args.check:
        root = dest
        bases = [args.basis] if args.basis else bases_in(root)
        if not bases:
            log(f"No models installed under {os.path.join(root, 'models')}.\n{PR.not_installed_hint('BLM')}")
            return 2
    else:
        src = os.path.abspath(args.src)
        root = find_ml_root(src)
        if root is None:
            log(f"No models/<BASIS>/peak_manifest.json found in or under {src} "
                f"(looked for {', '.join(C.BASES)}). Point --from at his .dev_cache folder.")
            return 2
        found = bases_in(root)
        bases = [args.basis] if args.basis else found
        if args.basis and args.basis not in found:
            log(f"No {args.basis} models under {root}/models (found: {', '.join(found) or 'none'}).")
            return 2
        log(f"source: {root}   bases: {', '.join(bases)}   destination: {dest}")
        if root == dest:
            log("source and destination are the same folder; use --check to verify an installed set.")
            return 2

    if args.check:
        vs = {b: verify(root, b) for b in bases}
        for b, v in vs.items():
            for e in v["errors"]:
                log(f"[{b}] ERROR: {e}")
        ok_all = not any(v["errors"] for v in vs.values())
        if not ok_all:
            log(PR.not_installed_hint(bases[0]))
            return 2
        where = root
    else:
        r = install(root, dest, bases, dry_run=args.dry_run, force=args.force)
        if not r["ok"]:
            return 2
        vs = r["verified"]
        where = root if args.dry_run else dest      # dry run: load-test the source files, nothing was copied
        log(("dry run: nothing written. " if args.dry_run else "") + f"{len(r['copied'])} file(s) "
            f"{'would be ' if args.dry_run else ''}copied, {len(r['unchanged'])} already identical, "
            f"{len(r['moved_aside'])} moved aside.")

    clean = True
    recipe = None
    for b, v in vs.items():
        c, rec = report_basis(os.path.join(where, "models", b), v)
        clean = clean and c
        if not c and recipe is None:
            recipe = venv_recipe(b, rec)
    if recipe:
        log("")
        for ln in recipe:
            log(ln)

    if args.score:
        if args.dry_run:
            log(f"--score {args.score} skipped: dry run installed nothing.")
        else:
            log(f"\nrunning score.py --league {args.score} (dry run, no --write) ...")
            s = run_score(args.score)
            rss = "n/a" if s["peak_rss_mb"] is None else f"{s['peak_rss_mb']:.0f} MB"
            log(f"score.py exit {s['returncode']}, wall time {s['seconds']:.1f} s, peak memory {rss} "
                "(largest child process)")
            for ln in s["tail"]:
                log("  | " + ln)
            if s["returncode"] != 0:
                clean = False
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())

"""
cleanup_clones.py — delete calibration clone leagues whose data is safely archived,
so they stop crowding the OOTP load screen. NEVER touches real/playable leagues.

A clone folder is deleted ONLY if ALL of these hold:
  1. its name matches the league's CLONE ALLOWLIST patterns (never bare names like
     'Baseline', 'BLM', 'TheGrandestSalami', 'New Game', or anything unrecognized),
  2. it is not the league's pristine master, not in winsim's PROTECTED set, not the
     save of any league in the settings (any type, enabled or not) and not the
     master of any profile,
  3. its name is recorded in the archive manifest (tgs-viz/engine/calib/<LG>/
     archived_clones.txt) — i.e. calibrate.py has secured its data — OR it is an
     INCOMPLETE clone (partial/no dumps: a failed or abandoned sim, useless by design)
     and --junk was given.

Usage:
    python ootp/cleanup_clones.py --league TGS            # list + confirm
    python ootp/cleanup_clones.py --league TGS --junk     # also offer incomplete clones
    python ootp/cleanup_clones.py --league BLM --yes      # no prompt
    python ootp/cleanup_clones.py --league TGS --junk --dry-run   # list only, delete nothing
A league added by New League (type clone) uses its own prefix: <prefix>NN.
"""
import os, re, sys, glob, json, stat, shutil, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import winsim  # noqa: E402  (game discovery + PROTECTED set)
ST = winsim.ST  # tgs-viz/tools/settings.py (winsim imports it)

PROFILES = winsim.load_profiles()   # leagues.json plus the profiles New League added

# name patterns that can EVER be deleted, per league (anchored, case-insensitive).
# TGS and BLM keep their own lists; any other clone league: <prefix> + digits.
ALLOW = {
    "TGS": [r"0tgs\d+", r"tgs-run\d+"],
    "BLM": [r"0blm\d+", r"blm-run\d+", r"[1-5]", r"baseline02"],
}
for _lg, _p in PROFILES.items():
    if _lg not in ALLOW and isinstance(_p, dict) and _p.get("prefix"):
        ALLOW[_lg] = [re.escape(str(_p["prefix"])) + r"\d+"]


def league_profile(lg):
    return PROFILES[lg]


def never_delete():
    """Lower-case save names no league's cleanup ever deletes: winsim.PROTECTED,
    every settings league's save (any type, enabled or not) and every profile's
    master. So BLM's [1-5] pattern can never take a dev league's save named 5."""
    masters = {str(p.get("master")).strip().lower() for p in PROFILES.values()
               if isinstance(p, dict) and p.get("master")}
    return set(winsim.PROTECTED) | ST.league_saves() | masters


def dump_years(lgdir):
    ys = []
    for d in glob.glob(os.path.join(lgdir, "dump", "dump_*_yearly")):
        m = re.search(r"dump_(\d+)_yearly", d)
        if m:
            ys.append(int(m.group(1)))
    return sorted(ys)


def rmtree_force(path):
    def onexc(fn, p, exc):
        os.chmod(p, stat.S_IWRITE)
        fn(p)
    shutil.rmtree(path, onerror=onexc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True,
                    choices=[lg for lg, p in PROFILES.items() if isinstance(p, dict) and p.get("prefix")])
    ap.add_argument("--junk", action="store_true",
                    help="also offer INCOMPLETE clones (failed/abandoned sims, data unusable)")
    ap.add_argument("--yes", action="store_true", help="delete without prompting")
    ap.add_argument("--dry-run", action="store_true", help="list what would be deleted, delete nothing")
    a = ap.parse_args()

    prof = league_profile(a.league)
    game = str(prof["game"])
    if game not in winsim.GAMES:
        raise SystemExit(f"OOTP {game} not found on this machine")
    saved = winsim.GAMES[game]["saved"]
    master = str(prof.get("master", "")).strip().lower()
    target_final = int(prof.get("target_year", 2026)) - 1

    manifest = os.path.join(REPO, "tgs-viz", "engine", "calib", a.league, "archived_clones.txt")
    archived = set()
    if os.path.exists(manifest):
        archived = {ln.strip() for ln in open(manifest) if ln.strip()}

    allow = [re.compile(rf"^(?:{p})\.lg$", re.I) for p in ALLOW[a.league]]
    keep = never_delete()
    candidates = []          # (name, reason, size_mb)
    for p in sorted(glob.glob(os.path.join(str(saved), "*.lg"))):
        name = os.path.basename(p)
        stem = name[:-3].strip().lower()
        if stem in keep or stem == master:
            continue
        if not any(rx.match(name) for rx in allow):
            continue                       # not a recognized clone name -> never touched
        ys = dump_years(p)
        complete = bool(ys) and ys[-1] >= target_final
        if name in archived:
            candidates.append((p, "archived (data secured in repo)", None))
        elif a.junk and not complete:
            candidates.append((p, f"incomplete junk (dumps: {ys[0]}-{ys[-1]}" if ys else "incomplete junk (no dumps", None))

    if not candidates:
        print(f"[{a.league}] nothing to clean up "
              f"({len(archived)} archived clone(s) known; none present on disk).")
        return

    print(f"[{a.league}] saved_games: {saved}")
    print(f"  will DELETE {len(candidates)} clone league(s):")
    total = 0
    sized = []
    for p, why, _ in candidates:
        mb = sum(os.path.getsize(os.path.join(dp, f))
                 for dp, _, fs in os.walk(p) for f in fs) / 1e6
        total += mb
        sized.append((p, why, mb))
        print(f"    {os.path.basename(p):20} {mb:7.0f} MB   {why}")
    others = sorted(keep - set(winsim.PROTECTED) - {master})
    print(f"  total: {total/1000:.1f} GB.  NOT touched: {master!r} (master), "
          f"{', '.join(sorted(winsim.PROTECTED))} (protected), "
          + (f"{', '.join(others)} (other league saves and masters), " if others else "")
          + "and any name outside the clone patterns.")

    if a.dry_run:
        print("  (dry run - nothing deleted)")
        return
    if not a.yes:
        try:
            resp = input(f"  Delete these {len(candidates)} folder(s)? [y/N] ").strip().lower()
        except EOFError:                   # no console to answer (a page job): no
            print("  skipped (no answer).")
            return
        if resp not in ("y", "yes"):
            print("  skipped (nothing deleted).")
            return
    for p, why, mb in sized:
        try:
            rmtree_force(p)
            print(f"  deleted {os.path.basename(p)}")
        except OSError as e:
            # the clone OOTP currently has LOADED is lock-protected — skip it, the
            # next cleanup pass gets it once OOTP has moved on (grind-loop friendly)
            print(f"  SKIPPED {os.path.basename(p)} (in use by OOTP: {e}) - next pass will get it")
    print(f"  done - freed ~{total/1000:.1f} GB, OOTP load screen decluttered.")


if __name__ == "__main__":
    main()

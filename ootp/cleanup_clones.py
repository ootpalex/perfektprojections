"""
cleanup_clones.py — delete calibration clone leagues whose data is safely archived,
so they stop crowding the OOTP load screen. NEVER touches real/playable leagues.

A clone folder is deleted ONLY if ALL of these hold:
  1. its name matches the league's CLONE ALLOWLIST patterns (never bare names like
     'Baseline', 'BLM', 'TheGrandestSalami', 'New Game', or anything unrecognized),
  2. it is not the league's pristine master and not in winsim's PROTECTED set,
  3. its name is recorded in the archive manifest (tgs-viz/engine/calib/<LG>/
     archived_clones.txt) — i.e. calibrate.py has secured its data — OR it is an
     INCOMPLETE clone (partial/no dumps: a failed or abandoned sim, useless by design)
     and --junk was given.

Usage:
    python ootp/cleanup_clones.py --league TGS            # list + confirm
    python ootp/cleanup_clones.py --league TGS --junk     # also offer incomplete clones
    python ootp/cleanup_clones.py --league BLM --yes      # no prompt
"""
import os, re, sys, glob, json, stat, shutil, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import winsim  # noqa: E402  (game discovery + PROTECTED set)

# name patterns that can EVER be deleted, per league (anchored, case-insensitive)
ALLOW = {
    "TGS": [r"0tgs\d+", r"tgs-run\d+"],
    "BLM": [r"0blm\d+", r"blm-run\d+", r"[1-5]", r"baseline02"],
}


def league_profile(lg):
    profiles = json.load(open(os.path.join(HERE, "leagues.json")))
    return profiles[lg]


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
    ap.add_argument("--league", required=True, choices=["TGS", "BLM"])
    ap.add_argument("--junk", action="store_true",
                    help="also offer INCOMPLETE clones (failed/abandoned sims, data unusable)")
    ap.add_argument("--yes", action="store_true", help="delete without prompting")
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
    candidates = []          # (name, reason, size_mb)
    for p in sorted(glob.glob(os.path.join(str(saved), "*.lg"))):
        name = os.path.basename(p)
        stem = name[:-3].strip().lower()
        if stem in winsim.PROTECTED or stem == master:
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
    print(f"  total: {total/1000:.1f} GB.  NOT touched: {master!r} (master), "
          f"{', '.join(sorted(winsim.PROTECTED))} (protected), and any name outside the clone patterns.")

    if not a.yes:
        resp = input(f"  Delete these {len(candidates)} folder(s)? [y/N] ").strip().lower()
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

"""
ingest_dumps.py - append a finished clone's OOTP career-dump CSVs into that league's
25 Regressions.xlsx, under the data that's already there.

APPEND-ONLY, NEVER REBUILD. The workbook pools many clone runs (e.g. BLM = 7), and some of
those clone leagues no longer exist on disk. Rebuilding from what's present would silently
destroy sample. So we only ever add rows.

What lands where (one Excel Table per sheet, all feeding the Power Pivot Data Model):
    Batting   <- dump/dump_<lastyear>_yearly/csv/players_career_batting_stats.csv   (33 cols, identical)
    Pitching  <- ...players_career_pitching_stats.csv                                (58 cols, identical)
    Fielding  <- ...players_career_fielding_stats.csv    (39 cols) + pa/pm table formulas (cols 40-41)

The dump CSV is a CAREER file: it holds every season 2016..<lastyear> for that clone. So one
clone = one complete sample, ingested exactly once. `ingested.json` records which clones have
been added so you cannot double-add.

Writes raw XML (extends each table's ref + autoFilter + the sheet dimension) so the
PivotTables, charts and Data Model survive untouched. openpyxl would destroy them.

AFTER RUNNING: open the workbook in Excel -> Data -> Refresh All (rebuilds the Data Model and
the regression pivots) -> Save. Then run `Sync Regressions.bat`.

Usage
    python ootp/ingest_dumps.py --league BLM --list
    python ootp/ingest_dumps.py --league BLM --all-new                 # dry-run
    python ootp/ingest_dumps.py --league BLM --all-new --write
    python ootp/ingest_dumps.py --league BLM --clones blm-run01 --write
"""
import os, re, csv, sys, json, shutil, zipfile, argparse, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MANIFEST = HERE / "ingested.json"

SHEETS = {
    "Batting":  dict(csv="players_career_batting_stats.csv",  extra=0),
    "Fielding": dict(csv="players_career_fielding_stats.csv", extra=2),
    "Pitching": dict(csv="players_career_pitching_stats.csv", extra=0),
}
NUM_RE = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def colletter(i):
    s = ""
    while i >= 0:
        s = chr(ord("A") + i % 26) + s
        i = i // 26 - 1
    return s


# ---------------------------------------------------------------- workbook plumbing
def sheet_paths(z):
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    relmap = dict(re.findall(r'Id="([^"]*)"[^>]*Target="([^"]*)"', rels))
    out = {}
    for name, rid in re.findall(r'<sheet[^>]*name="([^"]*)"[^>]*r:id="([^"]*)"', wb):
        t = relmap[rid]
        out[name] = t if t.startswith("xl/") else "xl/" + t
    return out


def table_parts(z):
    out = {}
    for n in z.namelist():
        if n.startswith("xl/tables/") and n.endswith(".xml"):
            x = z.read(n).decode("utf-8")
            m = re.search(r'<table[^>]*\bname="([^"]*)"', x)
            if m:
                out[m.group(1)] = n
    return out


def table_ref(z, part):
    x = z.read(part).decode("utf-8")
    m = re.search(r'<table[^>]*\bref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', x)
    if not m:
        raise RuntimeError(f"no ref in {part}")
    return m.group(1), int(m.group(2)), m.group(3), int(m.group(4))


def col_numeric_values(z, sheetpath, col="A"):
    """Set of string values in a column (numeric <v> cells). Small ratings sheets only."""
    x = z.read(sheetpath).decode("utf-8", "replace")
    return set(m.group(1) for m in
               re.finditer(rf'<c r="{col}\d+"[^>]*>(?:<f[^>]*>.*?</f>)?<v>([^<]*)</v>', x))


def clone_player_ids(csv_path):
    ids = set()
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh); next(rd)
        for rec in rd:
            if rec:
                ids.add(rec[0].strip())
    return ids


def header_of(z, sheetpath, ncols):
    """Read row 1 cell values (headers are inline? no - numeric sheets store headers as shared strings)."""
    x = z.read(sheetpath)
    i = x.find(b"</row>")
    row1 = x[:i].decode("utf-8", "replace")
    ss = None
    if 't="s"' in row1:
        ss = re.findall(r"<si>.*?</si>", z.read("xl/sharedStrings.xml").decode("utf-8"), re.S)
        ss = [re.sub(r"<.*?>", "", s) for s in ss]
    out = []
    for c in re.finditer(r'<c r="([A-Z]+)1"([^>]*)>(?:<v>([^<]*)</v>)?', row1):
        v = c.group(3)
        if 't="s"' in c.group(2) and ss is not None and v is not None:
            v = ss[int(v)]
        out.append(v)
    return out


# ---------------------------------------------------------------- row building
FIELDING_PA = ("IFERROR(Fielding[[#This Row],[opps_0]]+Fielding[[#This Row],[opps_1]]+"
               "Fielding[[#This Row],[opps_2]]+Fielding[[#This Row],[opps_3]]+"
               "Fielding[[#This Row],[opps_4]]+Fielding[[#This Row],[opps_5]],0)")
FIELDING_PM = ("IFERROR(Fielding[[#This Row],[opps_made_0]]+Fielding[[#This Row],[opps_made_1]]+"
               "Fielding[[#This Row],[opps_made_2]]+Fielding[[#This Row],[opps_made_3]]+"
               "Fielding[[#This Row],[opps_made_4]]+Fielding[[#This Row],[opps_made_5]],0)")


def build_rows(sheet, csv_path, start_row, ncols_total):
    """Return (xml_bytes, nrows). Cells are plain numeric <v>; Fielding gets its 2 <f> columns."""
    chunks = []
    n = 0
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh)
        next(rd)  # header
        for rec in rd:
            r = start_row + n
            cells = [f'<row r="{r}" spans="1:{ncols_total}">']
            for ci, val in enumerate(rec):
                v = val.strip()
                if v == "":
                    continue
                if not NUM_RE.match(v):
                    raise ValueError(f"{sheet} row {r} col {ci}: non-numeric value {v!r}")
                cells.append(f'<c r="{colletter(ci)}{r}"><v>{v}</v></c>')
            if sheet == "Fielding":
                cells.append(f'<c r="{colletter(len(rec))}{r}"><f>{FIELDING_PA}</f></c>')
                cells.append(f'<c r="{colletter(len(rec)+1)}{r}"><f>{FIELDING_PM}</f></c>')
            cells.append("</row>")
            chunks.append("".join(cells))
            n += 1
    return ("".join(chunks)).encode("utf-8"), n


# ---------------------------------------------------------------- zip rewrite (bounded memory)
TAIL = 1 << 16
CHUNK = 1 << 20


def rewrite(src_xlsx, dst_xlsx, sheet_edits, table_edits):
    """sheet_edits: {sheetpath: (new_rows_bytes, new_dimension)}   table_edits: {tablepart: new_ref}"""
    zin = zipfile.ZipFile(src_xlsx, "r")
    zout = zipfile.ZipFile(dst_xlsx, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
        zi.compress_type = item.compress_type
        zi.external_attr = item.external_attr
        zi.internal_attr = item.internal_attr
        zi.create_system = item.create_system

        if item.filename in table_edits:
            x = zin.read(item.filename).decode("utf-8")
            new = table_edits[item.filename]
            x = re.sub(r'(<table[^>]*\bref=")[^"]*(")', lambda m: m.group(1) + new + m.group(2), x, count=1)
            x = re.sub(r'(<autoFilter ref=")[^"]*(")', lambda m: m.group(1) + new + m.group(2), x, count=1)
            zout.writestr(zi, x.encode("utf-8"))
            continue

        if item.filename in sheet_edits:
            new_rows, new_dim = sheet_edits[item.filename]
            with zin.open(item) as src, zout.open(zi, "w") as dst:
                buf = b""
                first = True
                while True:
                    c = src.read(CHUNK)
                    if not c:
                        break
                    buf += c
                    if first:
                        buf = re.sub(rb'(<dimension ref=")[^"]*(")',
                                     lambda m: m.group(1) + new_dim.encode() + m.group(2), buf, count=1)
                        first = False
                    if len(buf) > TAIL:
                        dst.write(buf[:-TAIL]); buf = buf[-TAIL:]
                i = buf.rfind(b"</sheetData>")
                if i < 0:
                    raise RuntimeError(f"</sheetData> not in tail of {item.filename}")
                dst.write(buf[:i]); dst.write(new_rows); dst.write(buf[i:])
            continue

        with zin.open(item) as src, zout.open(zi, "w") as dst:
            shutil.copyfileobj(src, dst, CHUNK)
    zout.close(); zin.close()


# ---------------------------------------------------------------- clones
def load_profiles():
    p = HERE / "leagues.json"
    if not p.exists():
        raise SystemExit(f"missing {p} - run winsim.py once to create it")
    return json.loads(p.read_text(encoding="utf-8"))


def discover_saved(game):
    sys.path.insert(0, str(HERE))
    import winsim
    g = winsim.discover_games()
    if game not in g:
        raise SystemExit(f"OOTP {game} not found (have {', '.join(g)})")
    return g[game]["saved"]


def dump_years(lg):
    return sorted(int(p.name.split("_")[1]) for p in (lg / "dump").glob("dump_*_yearly")
                  if p.name.split("_")[1].isdigit())


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def save_manifest(m):
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Append clone dump CSVs into a league's 25 Regressions.xlsx")
    ap.add_argument("--league", required=True, help="profile name in leagues.json, e.g. BLM")
    ap.add_argument("--clones", default=None, help="comma list of clone league names to ingest")
    ap.add_argument("--all-new", action="store_true", help="every clone matching the profile prefix that has dumps and isn't ingested yet")
    ap.add_argument("--list", action="store_true", help="show clones and their ingest status")
    ap.add_argument("--mark-done", action="store_true", help="record all currently-simmed clones as "
                    "already-imported WITHOUT importing (run once if the sheet already holds them)")
    ap.add_argument("--write", action="store_true", help="apply (otherwise dry-run)")
    ap.add_argument("--force", action="store_true", help="skip the ratings-match safety check")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args()

    profiles = load_profiles()
    if a.league not in profiles:
        raise SystemExit(f"no profile {a.league!r}")
    prof = profiles[a.league]
    saved = discover_saved(prof["game"])
    wbpath = REPO / prof["workbook"]
    if not wbpath.exists():
        raise SystemExit(f"workbook not found: {wbpath}")

    man = manifest()
    key = prof["workbook"]
    done = set(man.get(key, {}).keys())

    # Candidate = any COMPLETE simmed league that isn't a real/protected league or the master.
    # "Complete" = it ran all the way to the final season (dump_<target_year-1> exists); a clone
    # you stopped early has partial data and must NOT be imported. Naming doesn't matter.
    import winsim
    master = str(prof.get("master") or "").strip().lower()
    final_year = int(prof.get("target_year", 2026)) - 1

    def status(stem):
        ys = dump_years(saved / f"{stem}.lg")
        if not ys:
            return "no-dumps", ys
        return ("complete" if final_year in ys else "incomplete"), ys

    simmed = [p.stem for p in saved.glob("*.lg")
              if p.is_dir() and dump_years(p)
              and p.stem.strip().lower() not in winsim.PROTECTED
              and p.stem.strip().lower() != master]
    cands = sorted(s for s in simmed if final_year in dump_years(saved / f"{s}.lg"))

    if a.list:
        print(f"{a.league}: OOTP {prof['game']} | {saved}")
        print(f"  workbook: {wbpath.name}  (complete = simmed through {final_year})")
        if not simmed:
            print(f"  (no simmed clone leagues found yet - sim one first)")
        for c in sorted(simmed):
            st, ys = status(c)
            tag = "INGESTED" if c in done else ("pending" if st == "complete" else "INCOMPLETE - skipped")
            print(f"  {c:16} dumps {ys[0]}-{ys[-1]}   {tag}")
        if done - set(cands):
            print(f"  already-ingested clones no longer on disk: {', '.join(sorted(done - set(cands)))}")
        return

    if a.mark_done:
        newly = [c for c in cands if c not in done]
        if not newly:
            print("  nothing to mark - all simmed clones already recorded."); return
        man.setdefault(key, {})
        for c in newly:
            man[key][c] = {"marked_done": True, "through_year": dump_years(saved / f"{c}.lg")[-1],
                           "when": datetime.datetime.now().isoformat(timespec="seconds")}
        save_manifest(man)
        print(f"  marked as already-in-the-sheet (won't be imported): {', '.join(newly)}")
        print(f"  -> future sims of NEW clones will import normally.")
        return

    if a.all_new:
        targets = [c for c in cands if c not in done]
        if not targets and cands:
            print("  all simmed clones are already imported/marked - nothing new."); return
        if targets and not done:
            print(f"  NOTE: {len(targets)} simmed clone(s) found and nothing is recorded as imported yet.")
            print(f"        If your sheet ALREADY contains these (pooled before this tool), stop and run")
            print(f"        with --mark-done first so they aren't double-added. If they're genuinely new, continue.\n")
    elif a.clones:
        targets = [s.strip() for s in a.clones.split(",") if s.strip()]
    else:
        raise SystemExit("pass --clones A,B or --all-new (or --list)")
    dup = [t for t in targets if t in done]
    if dup:
        raise SystemExit(f"already ingested (would double-add): {', '.join(dup)}\n  remove from {MANIFEST} to force")
    if not targets:
        print("nothing new to ingest."); return

    # gather csvs
    plan = []
    for c in targets:
        lg = saved / f"{c}.lg"
        ys = dump_years(lg)
        if not ys:
            raise SystemExit(f"{c}: no dumps - has it finished simming?")
        d = lg / "dump" / f"dump_{ys[-1]}_yearly" / "csv"
        files = {s: d / cfg["csv"] for s, cfg in SHEETS.items()}
        for s, f in files.items():
            if not f.exists():
                raise SystemExit(f"{c}: missing {f}")
        plan.append((c, ys[-1], files))

    z = zipfile.ZipFile(wbpath)
    sp = sheet_paths(z)
    tp = table_parts(z)
    print(f"{a.league}: {wbpath.name}")
    print(f"  clones to ingest: {', '.join(c for c, _, _ in plan)}")

    # SAFETY: the regression joins simmed stats -> the Hitters/Pitchers RATINGS tables on
    # player_id. Every clone must be a clone of THIS baseline (same players) or its stats
    # would never join. Check EACH clone on its own and DROP any that don't match, so a
    # stray non-baseline league can't ride in on the others.
    rated = col_numeric_values(z, sp["Hitters"]) | col_numeric_values(z, sp["Pitchers"])
    good = []
    for c, yr, files in plan:
        ids = clone_player_ids(files["Batting"])
        ov = len(ids & rated) / max(1, len(ids))
        ok = ov >= 0.90 or a.force
        print(f"  ratings check: {c:16} {ov*100:3.0f}% of {len(ids)} players match baseline ratings"
              f"  [{'OK' if ov >= 0.90 else ('FORCED' if a.force else 'MISMATCH -> SKIP')}]")
        if ok:
            good.append((c, yr, files))
        else:
            print(f"      not a clone of this baseline (different players) - not importing {c}")
    if not good:
        z.close()
        raise SystemExit("  nothing imported: no simmed league matched this workbook's baseline players.")
    plan = good

    sheet_edits, table_edits, summary = {}, {}, []
    for sheet, cfg in SHEETS.items():
        c0, r0, c1, r1 = table_ref(z, tp[sheet])
        ncols = len(header_of(z, sp[sheet], 0))
        parts, added, cur = [], 0, r1
        for c, yr, files in plan:
            b, n = build_rows(sheet, files[sheet], cur + 1, ncols)
            parts.append(b); cur += n; added += n
        newlast = r1 + added
        new_ref = f"{c0}{r0}:{c1}{newlast}"
        sheet_edits[sp[sheet]] = (b"".join(parts), new_ref)
        table_edits[tp[sheet]] = new_ref
        summary.append((sheet, r1 - 1, added, newlast - 1))
    z.close()

    print(f"  {'sheet':10} {'existing':>10} {'+added':>9} {'-> total':>10}")
    for s, ex, ad, tot in summary:
        print(f"  {s:10} {ex:>10,} {ad:>+9,} {tot:>10,}")

    if not a.write:
        print("\n  dry-run - re-run with --write to apply.")
        return
    if not a.yes:
        try:
            resp = input(f"  Add these {len(plan)} clone(s) to {wbpath.name}? [y/N] ").strip().lower()
        except EOFError:                   # no console to answer (a page job): no
            print("  skipped (no answer)."); return
        if resp not in ("y", "yes"):
            print("  skipped (not applied)."); return

    bak = wbpath.with_suffix(f".xlsx.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(wbpath, bak)
    print(f"\n  backup: {bak.name}")
    tmp = wbpath.with_suffix(".xlsx.tmp")
    rewrite(wbpath, tmp, sheet_edits, table_edits)
    os.replace(tmp, wbpath)
    print(f"  wrote {wbpath.name}")

    man.setdefault(key, {})
    for c, yr, _ in plan:
        man[key][c] = {"through_year": yr, "when": datetime.datetime.now().isoformat(timespec="seconds")}
    save_manifest(man)
    print(f"  manifest updated: {MANIFEST.name}")
    print("\n  NEXT: open the workbook in Excel -> Data -> Refresh All -> Save,")
    print("        then run Sync Regressions.bat")


if __name__ == "__main__":
    main()

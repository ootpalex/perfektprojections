"""Harmless step actions for the selftest.* tasks (DESIGN.md 4.9).

  python tgs-viz/tools/selftest_steps.py ok              5 lines (with non-ASCII), a partial line, then its end
  python tgs-viz/tools/selftest_steps.py print <text>    one line
  python tgs-viz/tools/selftest_steps.py exit <code>     exit with that code
  python tgs-viz/tools/selftest_steps.py sleep <s>       sleep, printing a line before and after
  python tgs-viz/tools/selftest_steps.py preview <n>     prints "  <n> cell(s) will change"
  python tgs-viz/tools/selftest_steps.py apply           prints "applied"
  python tgs-viz/tools/selftest_steps.py secret          reads TEST_SECRET and prints it (the log must mask it)
  python tgs-viz/tools/selftest_steps.py touch <file>    rewrites tgs-viz/public/data/<file> with the same bytes
  python tgs-viz/tools/selftest_steps.py corrupt <file>  breaks a data file for 8 s, then restores its bytes
  python tgs-viz/tools/selftest_steps.py stdin           calls input()
  python tgs-viz/tools/selftest_steps.py mark <path>     writes a marker file
  python tgs-viz/tools/selftest_steps.py mkdir <path>    creates a folder

Stdlib only. Writes only where the action says.
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "tgs-viz", "public", "data")


def out(text="", end="\n"):
    sys.stdout.write(text + end)
    sys.stdout.flush()


def data_path(rel):
    rel = rel.replace("/", os.sep).replace("\\", os.sep)
    p = os.path.abspath(os.path.join(DATA, rel))
    if not os.path.normcase(p).startswith(os.path.normcase(DATA + os.sep)):
        raise SystemExit(f"not a file under public/data: {rel}")
    return p


def replace_bytes(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    for i in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.2)


def job_dir():
    jid = os.environ.get("TGS_JOB_ID", "")
    root = os.environ.get("TGS_CONTROL_DIR", "").strip() or os.path.join(REPO, ".control")
    return os.path.join(os.path.abspath(root), "jobs", jid) if jid else None


def main(argv):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    if not argv:
        print(__doc__)
        return 2
    act, args = argv[0], argv[1:]
    if act == "ok":
        out("self test: line 1")
        out("self test: line 2 café")
        out("self test: line 3 ✓")
        out("self test: line 4")
        out("self test: line 5")
        out("self test: partial line ...", end="")
        time.sleep(1)
        out(" done")
        return 0
    if act == "print":
        out(" ".join(args))
        return 0
    if act == "exit":
        code = int(args[0]) if args else 1
        out(f"self test: exit {code}")
        return code
    if act == "sleep":
        secs = float(args[0]) if args else 1
        out(f"self test: sleep {args[0] if args else 1} s")
        time.sleep(secs)
        out("self test: awake")
        return 0
    if act == "preview":
        n = int(args[0]) if args else 3
        out("self test preview:")
        out(f"  {n} cell(s) will change (0 already current).")
        return 0
    if act == "apply":
        out("applied")
        return 0
    if act == "secret":
        s = os.environ.get("TEST_SECRET", "")
        out(f"secret received: {'yes' if s else 'no'}, length {len(s)}")
        out("whole: " + s)
        half = len(s) // 2
        sys.stdout.write("split: " + s[:half])
        sys.stdout.flush()
        time.sleep(0.2)
        sys.stdout.write(s[half:] + "\n")
        sys.stdout.flush()
        return 0
    if act == "touch":
        p = data_path(args[0] if args else "TGS/r5.json")
        with open(p, "rb") as f:
            data = f.read()
        replace_bytes(p, data)
        out(f"self test: rewrote {args[0] if args else 'TGS/r5.json'} with the same {len(data)} bytes")
        return 0
    if act == "corrupt":
        rel = args[0] if args else "RG/iafa.json"
        p = data_path(rel)
        with open(p, "rb") as f:
            data = f.read()
        jd = job_dir()
        if jd:
            os.makedirs(jd, exist_ok=True)
            with open(os.path.join(jd, "corrupt_backup.json"), "wb") as f:
                f.write(data)
        try:
            replace_bytes(p, b"[{bad")
            out(f"self test: broke {rel} for 8 s")
            time.sleep(8)
        finally:
            replace_bytes(p, data)
            out(f"self test: restored {rel}")
        return 0
    if act == "stdin":
        try:
            input("self test: type something: ")
            out("self test: got an answer")
        except EOFError:
            out("skipped (no answer)")
        return 0
    if act == "mark":
        p = args[0]
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("marked\n")
        out(f"self test: marked {p}")
        return 0
    if act == "mkdir":
        os.makedirs(args[0], exist_ok=True)
        out(f"self test: folder {args[0]}")
        return 0
    out(f"unknown self test action: {act}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

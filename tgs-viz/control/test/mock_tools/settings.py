"""Test double for tgs-viz/tools/settings.py CLI (DESIGN.md 3.2). Stdlib only.

Supports --json and set --patch-file. Writes only the file named by TGS_SETTINGS_LOCAL.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DEFAULTS = REPO / "tgs-viz" / "tools" / "settings.defaults.json"
SPEC_DEFAULTS = {"schema": 1, "python": {"main": ["python"], "ml": ["py", "-3.14"]}, "node": ["node"]}


def local_path():
    v = os.environ.get("TGS_SETTINGS_LOCAL")
    return Path(v) if v else REPO / "settings.local.json"


def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def load():
    try:
        defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    except Exception:
        defaults = SPEC_DEFAULTS
    lp = local_path()
    local = json.loads(lp.read_text(encoding="utf-8-sig")) if lp.exists() else {}
    return merge(defaults, local), local


def problems(merged):
    out = []
    for key in ("main", "ml"):
        v = (merged.get("python") or {}).get(key)
        if not (isinstance(v, list) and v and all(isinstance(s, str) and s for s in v)):
            out.append(f"python.{key} must be a list of words")
    return out


def main(argv):
    try:
        merged, local = load()
    except Exception as e:
        print(f"SettingsError: {local_path().name}: {e}", file=sys.stderr)
        return 2
    if argv == ["--json"]:
        print(json.dumps(merged))
        return 0
    if len(argv) == 3 and argv[0] == "set" and argv[1] == "--patch-file":
        patch = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        new_local = merge(local, patch)
        new_merged, _ = merge(merged, patch), None
        errs = problems(new_merged)
        if errs:
            print(json.dumps({"ok": False, "errors": errs}))
            return 2
        lp = local_path()
        lp.write_text(json.dumps(new_local, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "merged": new_merged}))
        return 0
    print("mock settings: unsupported arguments", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

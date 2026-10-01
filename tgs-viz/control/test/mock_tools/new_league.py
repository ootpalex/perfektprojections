"""Test double for tgs-viz/tools/new_league.py options/check --json (DESIGN.md 12.2). Writes nothing."""
import json
import sys
from pathlib import Path


def main(argv):
    if argv[:1] == ["options"]:
        print(json.dumps({"versions": [{"version": "27", "saved_games": "C:/mock", "exists": False}],
                          "saves": [], "bases": ["TGS", "BLM"], "argv": argv}))
        return 0
    if argv[:1] == ["check"]:
        spec = json.loads(Path(argv[argv.index("--spec") + 1]).read_text(encoding="utf-8"))
        errors = {}
        if not spec.get("id"):
            errors["id"] = "Pick an id."
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": [], "plan": [], "type": spec.get("type")}))
        return 0 if not errors else 2
    print("mock new_league: unsupported arguments", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

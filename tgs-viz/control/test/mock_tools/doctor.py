"""Test double for tgs-viz/tools/doctor.py --json (DESIGN.md 13.2). Reads nothing, writes nothing."""
import json
import sys

if __name__ == "__main__":
    print(json.dumps({"schema": 1, "ok": True, "checks": [
        {"id": "mock", "title": "Mock check", "status": "ok", "detail": "The mock doctor ran.", "fix": "", "task": None},
    ]}))
    sys.exit(0)

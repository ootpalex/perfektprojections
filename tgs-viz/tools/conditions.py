"""Condition evaluator for the task registry (DESIGN.md 4.4).

A condition is a JSON object with one key:
  {"no_token": "TGS"}            the league has no StatsPlus token
  {"no_token_input": "league"}   the league chosen in that input has no token
  {"input_nonblank": "sessionid"} the input is a non-empty string after strip
  {"exists": "rel\\path"}        the path exists under the repo root (Python only)
  {"flag": "stopafter"}          a runner flag is set (Python only)
  {"all": [...]}, {"any": [...]}, {"not": c}

The browser mirrors the first three and the logic keys in
src/lib/inputConditions.js. Both read tests/fixtures/conditions_cases.json.
"""
import os


class ConditionError(ValueError):
    pass


def evaluate(cond, tokens=None, inputs=None, flags=None, exists=None, repo=None):
    """True or False.

    tokens: {league_id: bool} (catalog state.tokens, or the probe flags in console mode)
    inputs: {name: value}
    flags:  {name: bool} or a set of set flag names
    exists: function(rel_path) -> bool; default checks the path under repo
    """
    if cond is None:
        return True
    tokens = tokens or {}
    inputs = inputs or {}
    if flags is None:
        flags = {}
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ConditionError(f"a condition must be an object with one key: {cond!r}")
    (key, arg), = cond.items()
    if key == "all":
        return all(evaluate(c, tokens, inputs, flags, exists, repo) for c in _list(arg, key))
    if key == "any":
        return any(evaluate(c, tokens, inputs, flags, exists, repo) for c in _list(arg, key))
    if key == "not":
        return not evaluate(arg, tokens, inputs, flags, exists, repo)
    if key == "no_token":
        return not bool(tokens.get(str(arg)))
    if key == "no_token_input":
        league = inputs.get(str(arg))
        if league is None or str(league).strip() == "":
            return True
        return not bool(tokens.get(str(league).strip().upper()))
    if key == "input_nonblank":
        v = inputs.get(str(arg))
        return isinstance(v, str) and v.strip() != ""
    if key == "exists":
        if exists is not None:
            return bool(exists(str(arg)))
        base = repo or os.getcwd()
        return os.path.exists(os.path.join(base, str(arg)))
    if key == "flag":
        if isinstance(flags, dict):
            return bool(flags.get(str(arg)))
        return str(arg) in flags
    raise ConditionError(f"unknown condition: {key}")


def _list(arg, key):
    if not isinstance(arg, list):
        raise ConditionError(f"'{key}' needs a list")
    return arg


def python_only(cond):
    """True when the condition uses a key the browser cannot evaluate."""
    if not isinstance(cond, dict):
        return False
    for key, arg in cond.items():
        if key in ("exists", "flag"):
            return True
        if key in ("all", "any") and any(python_only(c) for c in arg):
            return True
        if key == "not" and python_only(arg):
            return True
    return False

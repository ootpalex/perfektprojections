"""Tests for backtest/ml/install_models.py and the load-time version guard in predict.py.

  python -m pytest tgs-viz/tools/tests/test_install_models.py -q
  python tgs-viz/tools/tests/test_install_models.py

Everything happens in a temp folder with tiny fake manifests and tiny pickles (a
LinearRegression fit on a few synthetic rows); no real model, no network, and
the worktree's .dev_cache is never touched (the installer's destination is
passed as --dest / dest_root, predict's models folder is patched).
"""
import contextlib
import hashlib
import io
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(VIZ)
RUN = os.path.join(VIZ, "tools", "run_task.py")
ML = os.path.join(VIZ, "backtest", "ml")
sys.path.insert(0, ML)

import numpy as np  # noqa: E402
from sklearn.linear_model import LinearRegression  # noqa: E402

import common as C  # noqa: E402
import install_models as IM  # noqa: E402
import predict as PR  # noqa: E402

NOW = PR.installed_versions()
PEAK_FILES = {"H": {"gain_q10": "peak_H_gain_q10.pkl", "reach_mlb": "peak_H_reach_mlb.pkl"},
              "P": {"gain_q10": "peak_P_gain_q10.pkl", "reach_mlb": "peak_P_reach_mlb.pkl"}}
PATH_FILES = {"H": {"d1": "path_H_d1.pkl"}, "P": {"d1": "path_P_d1.pkl"}}


class Warny:
    """Unpickles with a UserWarning, like a model written by another library version."""
    def __getstate__(self):
        return {"x": 1}

    def __setstate__(self, state):
        warnings.warn("trained under another version", UserWarning)


def tiny_model():
    X = np.array([[0.0], [1.0], [2.0], [3.0]])
    return LinearRegression().fit(X, np.array([1.0, 3.0, 5.0, 7.0]))


def manifests(basis, sklearn_v=None, xgb_v=None, peak_basis=None, path_basis=None):
    sk = sklearn_v or NOW["sklearn"]
    pm = {"basis": peak_basis or basis, "sklearn": sk, "python": NOW["python"],
          "quantile_backend": f"xgboost {xgb_v} (trained on cpu)" if xgb_v else f"scikit-learn {sk}",
          "roles": {r: {"models": {t: {"file": f} for t, f in PEAK_FILES[r].items()}} for r in C.ROLES}}
    am = {"_meta": {"basis": path_basis or basis, "sklearn": sk, "python": NOW["python"]}}
    for r in C.ROLES:
        am[r] = {"models": {n: {"file": f} for n, f in PATH_FILES[r].items()}}
    return pm, am


def write_set(root, basis, schema=True, **kw):
    """A complete fake ml folder: root/models/<basis>/*.pkl + manifests, root/data/schema_<basis>.json."""
    pm, am = manifests(basis, **kw)
    d = os.path.join(root, "models", basis)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "peak_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(pm, fh)
    with open(os.path.join(d, "path_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(am, fh)
    for f in IM.listed_files(pm, am):
        with open(os.path.join(d, f), "wb") as fh:
            pickle.dump(tiny_model(), fh)
    if schema:
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        with open(os.path.join(root, "data", f"schema_{basis}.json"), "w", encoding="utf-8") as fh:
            json.dump({"basis": basis}, fh)
    return d


def tree_hash(root):
    """{relative path: sha1} of every file under root."""
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha1(fh.read()).hexdigest()
    return out


def run_main(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = IM.main(list(args))
    return rc, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="install-models-test-")
        self.src = os.path.join(self.tmp, "his", ".dev_cache", "ml")
        self.dest = os.path.join(self.tmp, "mine", "ml")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class Verify(Base):
    def test_complete_set_has_no_errors(self):
        write_set(self.src, "BLM")
        v = IM.verify(self.src, "BLM")
        self.assertEqual(v["errors"], [])
        # 2 manifests + 4 peak + 2 path pickles
        self.assertEqual(len(v["files"]), 8)
        self.assertEqual(v["recorded"]["sklearn"], NOW["sklearn"])
        self.assertIsNone(v["recorded"]["xgboost"])

    def test_missing_listed_file_detected(self):
        d = write_set(self.src, "BLM")
        os.remove(os.path.join(d, "peak_P_reach_mlb.pkl"))      # inside the temp copy only
        v = IM.verify(self.src, "BLM")
        self.assertTrue(any("peak_P_reach_mlb.pkl" in e and "missing" in e for e in v["errors"]), v["errors"])

    def test_missing_schema_and_manifest_detected(self):
        d = write_set(self.src, "BLM", schema=False)
        os.remove(os.path.join(d, "path_manifest.json"))
        errs = " | ".join(IM.verify(self.src, "BLM")["errors"])
        self.assertIn("schema is missing", errs)
        self.assertIn("path_manifest.json is missing", errs)

    def test_unparseable_manifest_detected(self):
        d = write_set(self.src, "BLM")
        with open(os.path.join(d, "peak_manifest.json"), "w") as fh:
            fh.write("{not json")
        self.assertTrue(any("does not parse" in e for e in IM.verify(self.src, "BLM")["errors"]))

    def test_basis_mismatch_detected(self):
        write_set(self.src, "BLM", peak_basis="TGS")
        errs = IM.verify(self.src, "BLM")["errors"]
        self.assertTrue(any("peak_manifest.json is for basis TGS, not BLM" in e for e in errs), errs)
        shutil.rmtree(self.src)
        write_set(self.src, "BLM", path_basis="TGS")
        errs = IM.verify(self.src, "BLM")["errors"]
        self.assertTrue(any("path_manifest.json is for basis TGS, not BLM" in e for e in errs), errs)

    def test_file_outside_model_folder_rejected(self):
        d = write_set(self.src, "BLM")
        p = os.path.join(d, "peak_manifest.json")
        pm = json.load(open(p))
        pm["roles"]["H"]["models"]["gain_q10"]["file"] = "../evil.pkl"
        json.dump(pm, open(p, "w"))
        self.assertTrue(any("outside the model folder" in e for e in IM.verify(self.src, "BLM")["errors"]))


class Versions(Base):
    def test_recorded_versions_read_from_manifests(self):
        pm, am = manifests("BLM", sklearn_v="1.7.2", xgb_v="3.4.1")
        rec = PR.recorded_versions(pm, am)
        self.assertEqual(rec, {"sklearn": "1.7.2", "python": NOW["python"], "xgboost": "3.4.1"})

    def test_path_manifest_is_the_fallback(self):
        pm, am = manifests("BLM", sklearn_v="1.7.2")
        del pm["sklearn"]
        self.assertEqual(PR.recorded_versions(pm, am)["sklearn"], "1.7.2")

    def test_version_mismatch_reported(self):
        rec = {"sklearn": "1.7.2", "python": "3.14.0", "xgboost": "3.4.1"}
        now = {"sklearn": "1.9.1", "python": "3.13.1", "xgboost": "3.4.1"}
        lines, bad = IM.compare_versions(rec, now)
        self.assertEqual(bad, [("sklearn", "1.7.2", "1.9.1")])
        text = "\n".join(lines)
        self.assertIn("trained 1.7.2, installed 1.9.1  MISMATCH", text)
        self.assertIn("different minor version", text)        # Python 3.14 vs 3.13: shown, not judged
        self.assertEqual(IM.compare_versions(dict(rec, sklearn="1.9.1"), now)[1], [])

    def test_xgboost_missing_here_is_a_mismatch(self):
        rec = {"sklearn": "1.9.1", "python": "3.13.1", "xgboost": "3.4.1"}
        bad = PR.version_mismatches(rec, {"sklearn": "1.9.1", "python": "3.13.1", "xgboost": None})
        self.assertEqual(bad, [("xgboost", "3.4.1", None)])

    def test_unrecorded_library_not_checked(self):
        self.assertEqual(PR.version_mismatches({"sklearn": None, "xgboost": None},
                                               {"sklearn": "9", "xgboost": "9"}), [])

    def test_recipe_pins_the_recorded_versions(self):
        text = "\n".join(IM.venv_recipe("BLM", {"sklearn": "1.7.2", "xgboost": "3.4.1", "python": "3.14.0"}))
        self.assertIn("python -m venv", text)
        self.assertIn("scikit-learn==1.7.2 numpy pandas xgboost==3.4.1", text)
        self.assertIn("python.ml", text)
        self.assertIn("settings.local.json", text)
        no_xgb = "\n".join(IM.venv_recipe("BLM", {"sklearn": "1.7.2", "xgboost": None, "python": "3.14.0"}))
        self.assertNotIn("xgboost", no_xgb)


class LoadTest(Base):
    def test_ok_warning_error(self):
        d = os.path.join(self.tmp, "m")
        os.makedirs(d)
        with open(os.path.join(d, "ok.pkl"), "wb") as fh:
            pickle.dump(tiny_model(), fh)
        with open(os.path.join(d, "warn.pkl"), "wb") as fh:
            pickle.dump(Warny(), fh)
        with open(os.path.join(d, "bad.pkl"), "wb") as fh:
            fh.write(b"not a pickle")
        res = {n: (st, detail) for n, st, detail in IM.load_test(d, ["ok.pkl", "warn.pkl", "bad.pkl", "m.json"])}
        self.assertEqual(sorted(res), ["bad.pkl", "ok.pkl", "warn.pkl"])      # the .json is not a model
        self.assertEqual(res["ok.pkl"][0], "OK")
        self.assertEqual(res["warn.pkl"][0], "warning")
        self.assertIn("UserWarning", res["warn.pkl"][1])
        self.assertEqual(res["bad.pkl"][0], "error")


class Install(Base):
    def test_find_ml_root_layouts(self):
        write_set(self.src, "BLM")
        whole = os.path.dirname(self.src)                     # his .dev_cache folder
        self.assertEqual(IM.find_ml_root(self.src), self.src)
        self.assertEqual(IM.find_ml_root(whole), self.src)
        self.assertEqual(IM.find_ml_root(os.path.dirname(whole)), self.src)        # the folder holding .dev_cache
        self.assertIsNone(IM.find_ml_root(self.tmp + "/nothing"))
        self.assertEqual(IM.bases_in(self.src), ["BLM"])

    def test_install_copies_and_leaves_source_untouched(self):
        write_set(self.src, "BLM")
        before = tree_hash(self.src)
        rc, out = run_main("--from", self.src, "--dest", self.dest)
        self.assertEqual(rc, 0, out)                          # versions match (manifests record this interpreter's)
        self.assertEqual(tree_hash(self.src), before)         # source unchanged
        mine = tree_hash(self.dest)
        self.assertEqual(len(mine), 9)                        # 2 manifests + 6 pickles + schema
        self.assertIn(os.path.join("data", "schema_BLM.json"), mine)
        self.assertEqual(mine[os.path.join("models", "BLM", "peak_manifest.json")],
                         before[os.path.join("models", "BLM", "peak_manifest.json")])
        self.assertIn("6 OK, 0 warning, 0 error of 6", out)

    def test_dry_run_writes_nothing(self):
        write_set(self.src, "BLM")
        before = tree_hash(self.src)
        rc, out = run_main("--from", self.src, "--dest", self.dest, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.dest))           # not even the folder
        self.assertEqual(tree_hash(self.src), before)
        self.assertIn("would copy", out)
        self.assertIn("nothing written", out)

    def test_no_overwrite_without_force(self):
        write_set(self.src, "BLM")
        write_set(self.dest, "BLM")
        victim = os.path.join(self.dest, "models", "BLM", "peak_H_gain_q10.pkl")
        with open(victim, "wb") as fh:
            fh.write(b"older author file")
        before = tree_hash(self.dest)
        rc, out = run_main("--from", self.src, "--dest", self.dest)
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", out)
        self.assertIn("--force", out)
        self.assertEqual(tree_hash(self.dest), before)        # nothing copied, nothing moved

    def test_identical_existing_files_are_not_a_conflict(self):
        write_set(self.src, "BLM")
        self.assertEqual(run_main("--from", self.src, "--dest", self.dest)[0], 0)
        rc, out = run_main("--from", self.src, "--dest", self.dest)
        self.assertEqual(rc, 0, out)
        self.assertIn("unchanged", out)

    def test_force_moves_aside_and_never_deletes(self):
        write_set(self.src, "BLM")
        write_set(self.dest, "BLM")
        victim = os.path.join(self.dest, "models", "BLM", "peak_H_gain_q10.pkl")
        with open(victim, "wb") as fh:
            fh.write(b"older author file")
        src_before = tree_hash(self.src)
        res = IM.install(self.src, self.dest, ["BLM"], force=True, stamp="20261004", out=lambda *_: None)
        self.assertTrue(res["ok"])
        aside = victim + ".bak-20261004"
        self.assertEqual(res["moved_aside"], [(victim, aside)])
        with open(aside, "rb") as fh:
            self.assertEqual(fh.read(), b"older author file")      # the old bytes survive
        with open(victim, "rb") as fh:
            self.assertNotEqual(fh.read(), b"older author file")   # and the new file is in place
        self.assertEqual(tree_hash(self.src), src_before)
        # a second forced run on the same day does not clobber the first backup
        with open(victim, "wb") as fh:
            fh.write(b"second older")
        IM.install(self.src, self.dest, ["BLM"], force=True, stamp="20261004", out=lambda *_: None)
        with open(aside, "rb") as fh:
            self.assertEqual(fh.read(), b"older author file")
        with open(victim + ".bak-20261004-2", "rb") as fh:
            self.assertEqual(fh.read(), b"second older")

    def test_bad_set_installs_nothing(self):
        d = write_set(self.src, "BLM")
        os.remove(os.path.join(d, "path_H_d1.pkl"))
        rc, out = run_main("--from", self.src, "--dest", self.dest)
        self.assertEqual(rc, 2)
        self.assertIn("path_H_d1.pkl", out)
        self.assertFalse(os.path.exists(self.dest))

    def test_basis_not_in_source(self):
        write_set(self.src, "BLM")
        rc, out = run_main("--from", self.src, "--dest", self.dest, "--basis", "TGS")
        self.assertEqual(rc, 2)
        self.assertIn("No TGS models", out)

    def test_version_mismatch_prints_recipe_and_exit_1(self):
        write_set(self.src, "BLM", sklearn_v="0.0.1", xgb_v="0.0.2")
        rc, out = run_main("--from", self.src, "--dest", self.dest)
        self.assertEqual(rc, 1)
        self.assertIn("trained 0.0.1", out)
        self.assertIn("MISMATCH", out)
        self.assertIn("scikit-learn==0.0.1 numpy pandas xgboost==0.0.2", out)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "models", "BLM", "peak_manifest.json")))

    def test_check_mode_reads_the_installed_set(self):
        write_set(self.dest, "BLM")
        rc, out = run_main("--check", "--dest", self.dest)
        self.assertEqual(rc, 0, out)
        rc, out = run_main("--check", "--dest", os.path.join(self.tmp, "empty"))
        self.assertEqual(rc, 2)
        self.assertIn("not installed on this machine", out)


class Guard(Base):
    """The load-time guard in predict.py."""

    def test_warns_on_sklearn_mismatch_and_names_both_versions(self):
        pm, am = manifests("BLM", sklearn_v="1.7.2")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            bad = PR.warn_versions("BLM", pm, am, now={"sklearn": "1.9.1", "python": "3.13.1", "xgboost": None})
        text = err.getvalue()
        self.assertEqual(bad, [("sklearn", "1.7.2", "1.9.1")])
        self.assertIn("scikit-learn 1.7.2", text)
        self.assertIn("1.9.1", text)
        self.assertIn("install_models.py", text)
        self.assertIn("BLM", text)

    def test_silent_when_versions_match(self):
        pm, am = manifests("BLM", sklearn_v="1.9.1", xgb_v="3.4.1")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            bad = PR.warn_versions("BLM", pm, am, now={"sklearn": "1.9.1", "python": "3.14.0", "xgboost": "3.4.1"})
        self.assertEqual((bad, err.getvalue()), ([], ""))

    def test_load_bundle_warns_but_still_loads(self):
        write_set(self.src, "BLM", sklearn_v="0.0.1")
        with mock.patch.object(C, "MODELS_ROOT", os.path.join(self.src, "models")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                bundle = PR.load_bundle("BLM")
        self.assertIn("scikit-learn 0.0.1", err.getvalue())
        self.assertEqual(sorted(bundle["models"]), ["H", "P"])           # scoring is not refused

    def test_load_bundle_silent_with_matching_versions(self):
        write_set(self.src, "BLM")
        with mock.patch.object(C, "MODELS_ROOT", os.path.join(self.src, "models")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                PR.load_bundle("BLM")
        self.assertEqual(err.getvalue(), "")

    def test_missing_manifest_message_keeps_old_text_and_adds_the_hint(self):
        with mock.patch.object(C, "MODELS_ROOT", os.path.join(self.src, "models")):
            with self.assertRaises(SystemExit) as cm:
                PR.load_bundle("BLM")
        msg = str(cm.exception)
        self.assertIn("no peak models for basis BLM", msg)
        self.assertIn("fit-final --basis BLM", msg)                       # his text, kept
        self.assertIn("models for basis BLM are not installed on this machine", msg)
        self.assertIn("install_models.py --from <dir>", msg)
        self.assertIn("training is not run on the Mac", msg)


class UpdateTaskSkip(Base):
    """The Update task skips ML scoring (instead of failing it) for a wizard-added league whose basis
    has no models installed; the bat-pinned leagues keep the step."""
    MODELS = "tgs-viz\\backtest\\.dev_cache\\ml\\models\\BLM\\peak_manifest.json"

    def plan(self, task, exists=None):
        loc = os.path.join(self.tmp, "settings.local.json")
        with open(loc, "w") as fh:
            json.dump({"leagues": {"ZQ": {"type": "statsplus", "name": "Wizard", "slug": "zq", "basis": "BLM",
                                          "ootp_version": "27"}}}, fh)
        env = dict(os.environ, TGS_SETTINGS_LOCAL=loc, TGS_CONTROL_DIR=os.path.join(self.tmp, "control"),
                   STATSPLUS_TOKEN_FILE=os.path.join(self.tmp, "tokens", "StatsPlus Tokens.txt"))
        env.pop("TGS_SELFTEST", None)
        cmd = [sys.executable, RUN, "--plan", task]
        if exists is not None:
            cmd += ["--assume-json", json.dumps({"exists": {self.MODELS: exists}})]
        cp = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        items = json.loads(cp.stdout)["items"]
        steps = [i["step_id"] for i in items if i["type"] == "command"]
        text = " ".join(" ".join(i["lines"]) for i in items if i["type"] == "echo")
        return steps, text

    def test_skipped_with_reason_when_no_models(self):
        steps, text = self.plan("update.ZQ", exists=False)
        self.assertIn("ml_rows", steps)
        self.assertNotIn("ml_score", steps)
        self.assertIn("No BLM models installed: skipping ZQ ML scores", text)
        self.assertIn("install_models.py", text)

    def test_runs_when_models_installed(self):
        steps, text = self.plan("update.ZQ", exists=True)
        self.assertIn("ml_score", steps)
        self.assertNotIn("No BLM models installed", text)

    def test_default_leagues_keep_the_step_their_bats_pin(self):
        for task in ("update.BLM", "update.RG"):
            steps, text = self.plan(task, exists=False)
            self.assertIn("ml_score", steps, task)
            self.assertNotIn("models installed", text, task)


if __name__ == "__main__":
    unittest.main()

# Installing the author's ML models (Phase 5)

The DEV machine-learning models are not trained on the Mac. The original author trains them
(`peak.py` / `path.py` fit-final; BLM with scikit-learn 1.7.2 on Python 3.14 under Windows) and
`score.py` only scores with them. Until his files are installed here, `score.py` stops and the app
keeps the cell method (no `dev_ml.json`).

## What to ask the author for

His `tgs-viz/backtest/.dev_cache/` folder, or just its `ml` subfolder. What scoring needs, for the
basis `<B>` (SSB and RG are scored with the BLM set, so `<B>` is `BLM`; TGS has its own set):

| File | Goes to |
| --- | --- |
| `ml/models/<B>/peak_manifest.json`, `path_manifest.json` and every `.pkl` they list | `tgs-viz/backtest/.dev_cache/ml/models/<B>/` |
| `ml/data/schema_<B>.json` | `tgs-viz/backtest/.dev_cache/ml/data/` |

Also ask which versions he trained with, and for his `pip freeze` (the manifests record scikit-learn,
xgboost and Python, but not numpy or pandas).

## Install

Run it with the interpreter that will score (`python.ml` in `settings.local.json`):

    .venv/bin/python tgs-viz/backtest/ml/install_models.py --from <his folder>            # every basis found
    .venv/bin/python tgs-viz/backtest/ml/install_models.py --from <his folder> --basis BLM --dry-run
    .venv/bin/python tgs-viz/backtest/ml/install_models.py --from <his folder> --force    # replace files already here
    .venv/bin/python tgs-viz/backtest/ml/install_models.py --check                        # re-check what is installed
    .venv/bin/python tgs-viz/backtest/ml/install_models.py --from <his folder> --score SSB  # then time a score.py dry run

`--from` takes his whole `.dev_cache`, its `ml` folder, or any folder holding `models/<B>/` and
`data/schema_<B>.json`. The script:

1. checks that the manifests parse, name the right basis, that every file they list exists, and that the schema is there;
2. copies the files (the source is only read). A different file already at the destination stops the
   run; `--force` moves it aside as `<name>.bak-<date>` and never deletes;
3. unpickles every model and prints OK / warning / error per file;
4. compares the scikit-learn, xgboost and Python versions in the manifests with the running interpreter.

Exit code 0 = installed and clean; 1 = installed but a version differs or a model warned or failed
to load; 2 = nothing installed.

## Matching versions

scikit-learn pickles are not portable across versions. This venv has scikit-learn 1.9.1; BLM was
trained with 1.7.2. If the script reports a mismatch or a load warning it prints the recipe; in short:

    python -m venv ~/venvs/ootp-ml
    ~/venvs/ootp-ml/bin/python -m pip install scikit-learn==<recorded> numpy pandas [xgboost==<recorded>]

then set `"python": {"ml": ["/Users/<you>/venvs/ootp-ml/bin/python"]}` in `settings.local.json` and run
`--check` with that interpreter. `predict.load_bundle` also prints a stderr warning naming both
versions whenever the loaded models and the interpreter differ; it warns only and still scores.

## What scoring then does

`score.py --league SSB --write` loads the BLM models, scores the rows `dataset.py --basis SSB
--score-only --write` built from the latest pull, and writes `public/data/SSB/dev_ml.json`. The app
uses it only when its pull id equals `dev_signals.json`'s (stale guard). The Update task runs both
steps. Without installed models its `ml_score` step is skipped with the note "No BLM models
installed" for a wizard-added league such as SSB (the bat-pinned TGS, BLM and RG tasks are
unchanged); `ml_rows` still runs.

## Findings: SSB scoring rows offline (2026-10-04, checked with sockets blocked)

- Nothing tried the network (a socket block that logs any non-loopback connect logged nothing).
- The empty fingerprint is fixed. The old rows (built 10:30) recorded `d41d8cd98f` (the md5 of no
  calibration files); a rebuild now records `3100568b98`, the fingerprint of BLM's calibration. It is
  the only line in `score_note_SSB.json` that changed besides the timestamp. The old files were moved
  to `*.bak-20261004`.
- Before the follow-up below, a `.waa_cache` existed for pull 575 only. `dataset.league_waa` only
  looks a cache up, and nothing built the latest pull's cache for an exported league:
  `growth_lenses._pair_waa` builds the older pull of a pair, and the Update task's `agecurve` step
  runs only when the league's basis is itself (`tasks.py`, `if basis == lid`).
- `agecurve_fit.py --league SSB --calib BLM` (without `--cache-only`) would not have helped: it tags
  its cache `<fingerprint>-BLM` (the DEV convention), while `growth_lenses` and `dataset.py` look for
  the plain `<fingerprint>`. RG (one vintage, no cache) has the same gap and is not changed here.

## Engine WAA cache for the latest pull (follow-up)

`agecurve_fit.py --league SSB --calib BLM --cache-only` runs the engine on every archived vintage
with BLM's calibration and fills `vintages/SSB/.waa_cache/<vintage>.<fingerprint>.json` under the
plain fingerprint. It measures and writes nothing else, works with a single vintage, and reuses
cached vintages, so a rerun prices only the new pull (about 4 s per vintage here). The Update task
runs it as the step "SSB engine WAA cache" right before the ML rows, for wizard-added leagues whose
basis is another league (not TGS, BLM or RG).

Checked on SSB (offline): pull 576 now has its cache; the existing pull 575 file is identical to a
fresh engine pass (13,991 players). After rebuilding the rows, the only columns that changed are
`cache_now_waa` and `cache_ceiling_waa` (filled for the latest pull; the app's current WAA matches
the cache's, correlation 0.997 over 14,003 players, mean difference -0.06). `d_now` and `d_ceiling`
are still NaN on every row: they are latest minus an earlier pull, and no earlier pull at least
0.1 game-years back exists (`from_pull` is None).

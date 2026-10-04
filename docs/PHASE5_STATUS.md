# Phase 5 status: ML on the Mac

*2026-10-04, branch `phase5-ml` (built on `phase4-app`). Plan: ootp-dashboard
`docs/migration-plan:docs/MIGRATION_PLAN.md` §6. Detail in `docs/phase5/ml_install.md`. The Mac
scores with the author's trained models and never trains (decision 2026-10-02). SSB scores with the
BLM model set (its basis).*

## Blocked on the author's files

Scoring SSB needs exactly two things from his `tgs-viz/backtest/.dev_cache/ml/`:

| File | Why |
|---|---|
| `models/BLM/` (`peak_manifest.json`, `path_manifest.json` and the pickles they list) | the models |
| `data/schema_BLM.json` | model facts `score.py` reads before scoring any BLM-basis league |

The DEV vintages, `waa_TGS`, `dev_mlb_pt` and the raw dumps are training inputs only. Also needed:
**his `pip freeze`**. The manifests record the scikit-learn, xgboost and Python versions but not numpy
or pandas, and pickles are not version-portable. His STATUS.md says BLM was trained with scikit-learn
1.7.2; this Mac's venv has 1.9.1 (not yet observed against real pickles).

## What was built

| Item | State |
|---|---|
| `backtest/ml/install_models.py` | Verifies a delivered folder (manifests, every listed file, schema, basis), compares recorded library versions with the ML Python, test-loads every pickle, copies (never moves the source; `--force` moves old files aside, never deletes). On a version mismatch it prints the steps for a matching venv and the `python.ml` setting. `--check` re-verifies an installed set; `--score SSB` times a dry scoring run and records peak memory. |
| Load-time version guard | `predict.load_bundle` warns when the installed scikit-learn / xgboost differ from the manifest's; still scores. |
| Missing-model message | His text kept, plus one line naming `install_models.py` (training is not run on the Mac). |
| Update task (SSB) | ML scoring is **skipped with a reason** until BLM models are installed, instead of failing every update. New step "SSB engine WAA cache" builds the latest pull's engine-WAA cache on BLM's calibration (`agecurve_fit.py --cache-only`), which the ML rows read. TGS / BLM / RG task lists unchanged. |
| SSB scoring rows | Rebuilt offline (no network attempted). They had been built before the basis-calibration fix (empty fingerprint); they now carry BLM's fingerprint, and `cache_now_waa` / `cache_ceiling_waa` are filled (were NaN on all 14,003 rows). |
| Tests | `tools/tests/test_install_models.py`, 36 tests; whole tools suite passing. |

**Still missing in SSB's rows:** the growth features `d_now` / `d_ceiling` are NaN on every row. They
compare the latest pull with one at least 0.1 game-years earlier, and SSB's archive holds two pulls
two days apart. They fill in as the archive grows; no change needed.

## When the files arrive

1. `install_models.py --from <his folder> --score SSB` (dry run first with `--dry-run`).
2. If it reports a version mismatch: build the venv it prints (needs your OK: it downloads packages)
   and point `python.ml` at it, or ask him to retrain on the current versions.
3. Run the SSB update; the ML step then scores and the app uses `dev_ml.json` instead of the cell
   method.

## Open question carried from the plan

Whether DEV priced with SSB's own league numbers differs enough from BLM's to justify an SSB model
set. Needs the DEV vintages from the author **and** SSB's own metadata (`metadata_inputs.py`: a small
set of StatsPlus reads, not yet run; needs your OK).

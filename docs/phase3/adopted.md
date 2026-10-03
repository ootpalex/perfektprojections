# Phase 3 - adopted as-is from the fork

Plan row: "Wrong-league guard, refusal typing, token age warning, honest pull report: absent in ours, present in his
- adopt his." Decision recorded: all four are adopted unchanged. This branch edits none of them.

Verified by reading the fork at this branch's base (`d251cca`) and our `218dd86`-era `model/`; none was run
(running them needs a live pull). I found no unit test for any of the four in `tgs-viz/tools/tests/`
(grep for `age_warning`, `StatsPlusRefused`, `PULL FAILED`, `_classify` in `tools/tests` finds none); their only
exercise is a real pull.

## Where each lives in his code

| Feature | What it does | Where (fork, `tgs-viz/ingest/`) |
|---|---|---|
| Wrong-league guard | Before anything is saved, joins the new ratings to the last saved pull by ID and name. With at least 200 joined players, fewer than half agreeing stops the pull (exit 6) with nothing written. | `refresh.py:306-335` (test at 326, exit at 331); exit-code table `refresh.py:28-40` |
| Refusal typing | StatsPlus replies are classified into eight kinds (`token_invalid`, `token_expired`, `login_required`, `daily_limit`, `too_soon`, `not_enabled`, `blocked`, `not_data`). Each has a plain-words reason and fix, the token is redacted. | kinds `statsplus.py:368`; `_classify` `:385`; `_why` `:399`; `StatsPlusRefused` `:443`; `RatingsFailure` `:474`; `_refused_reply` `:534`; `_http_refusal` `:555`; mapped to exit codes 2, 3, 7, 8 by `refresh.py:_not_pulled` `:223-247` |
| Token-age warning | The first day each token was seen is stored (not the token); more than 80 days old warns, tokens expire at 90. | `statsplus_token.py:41-42` (`EXPIRE_DAYS`, `WARN_DAYS`), `age_warning` `:280-286`, shown by `pull_report.py:68-78` and by `statsplus_token.py:461,472` |
| Honest pull report | Last step of a pull. Ignores what earlier steps claimed and reports each league's real file dates; "OK - updated this run" only when the files changed in the last 30 minutes; exit 1 when nothing updated. | `pull_report.py` (docstring `:1-27`, `main` `:95-165`); `refresh.py:_stop` `:216-220` |

## What ours does in the same places

| Feature | Ours (`model/`) | Verdict |
|---|---|---|
| Wrong-league guard | none. Our pulls are tokenless public endpoints keyed by the configured league URL, and nothing compares a new pull to the last one. | his is strictly more |
| Refusal typing | none. `statsplus.py:37-52` (`_fetch_csv`) catches every network error, prints one line and returns `[]`; `fetch_game_date` (`:224-262`) returns `None` on any error. | his is strictly more |
| Token-age warning | none. Ours uses no token (`draftpool.py:5,76` says "tokenless"). | not applicable to ours; his covers his tokened endpoints |
| Honest pull report | none. | his is strictly more |

Ours has one side effect his design avoids, noted so nobody carries it over: `model/main.py:355-359` is meant
to skip saving the cache when a fetch failed, but `_fetch_csv` swallows the failure and returns `[]`, so
`fetch_contracts` returns `{}` rather than raising. `contracts is not None` is then true and
`save_statsplus_cache` (`statsplus.py:308`) writes an empty cache keyed to that game date. Read from the code, not
reproduced. It disappears when the dashboard's StatsPlus calls go through his `statsplus.py` (Phase 3 contracts
and draft-pool rows).

## Conclusion

Ours has nothing in these four areas that his lacks. Nothing to port in either direction; the migration work is
routing our fetches through his client so they inherit the four features. No code in this branch touches them: the
roster-export hook in `refresh.py` sits after the contract/injury attach and before the mapping check, adds no
StatsPlus request of its own beyond the already-memoised `/date`, and never stops a pull.

import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, Info } from 'lucide-react';
import { getCellColorClass } from '../lib/columns';
import { registerInvalidator, useDataVersion } from '../lib/dataVersion';

/**
 * MakeItOddsPage: the odds that a young player with one given rating turns
 * into an MLB regular, by age and rating band. One table per rating, one
 * column per age, one row per 5-point band. The user asked for these tables
 * (2026-09-24): "for players age 18 with 25 BABIP, the % chance to be an MLB
 * regular, for different ages, ratings and attributes".
 *
 * Data: /data/dev_rating_odds.json, written by backtest/dev_rating_odds.py
 * from the DEV league (all-AI OOTP, true ratings). It is one file for every
 * league; nothing here depends on the league picked in the sidebar.
 *
 * INFORMATIONAL ONLY: nothing here feeds a projection.
 */

const STORE_KEY = 'tgs-make-it-odds';
const ROLES = [['H', 'Hitters'], ['P', 'Pitchers']];
// Peak outcomes in order: MLB regular (playing time), then the three peak
// bars. MLB level (-1 WAA, a 5th starter or bench bat) is the chance he is
// ever anything in the majors (user, 2026-09-24: "if they will ever be
// anything in the mlb first and foremost").
const OUTCOMES = [
  ['regular', 'MLB regular'],
  ['mlb', 'MLB level (-1 WAA)'],
  ['useful', 'Starter (0 WAA)'],
  ['good', 'Star (+1.5 WAA)'],
];
const BASES = [['current', 'Current rating'], ['potential', 'Potential rating']];
// The column of the app's Make it %, MLB %, Starter % and Star % that each
// outcome matches, so the cells take the same colors as the player tables.
const COLOR_COLUMN = { regular: 'Dev_Odds', mlb: 'Dev_PeakMlb', useful: 'Dev_PeakUseful', good: 'Dev_PeakGood' };
// Attributes come from the file (odds.attributes); this only names them.
// Contact is not in the file any more (user, 2026-09-24: "please remove
// contact from the list").
const ATTR_LABEL = {
  BABIP: 'BABIP', GAP: 'Gap', POW: 'Power', EYE: 'Eye', AvK: 'Avoid K',
  STU: 'Stuff', HRR: 'HRR', CON: 'Control', PBABIP: 'BABIP allowed',
  Ovr: 'Overall grade', Pot: 'Potential grade',
};

let oddsPromise = null;
/** Fetch the odds file once. Resolves to null when it is missing. */
function loadOdds() {
  if (!oddsPromise) {
    oddsPromise = fetch('/data/dev_rating_odds.json')
      .then(res => {
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) throw new Error(`dev_rating_odds.json ${res.status}`);
        return res.json();
      })
      .then(json => (json && json.tables ? json : null))
      .catch(() => null);
  }
  return oddsPromise;
}

// Live refresh: forget the loaded file, so the next load reads it again.
function resetOdds() {
  oddsPromise = null;
}
registerInvalidator('odds', resetOdds);

const has = (list, v) => list.some(([k]) => k === v);
function readChoices() {
  try {
    const s = JSON.parse(localStorage.getItem(STORE_KEY) || 'null') || {};
    return {
      role: has(ROLES, s.role) ? s.role : 'H',
      outcome: has(OUTCOMES, s.outcome) ? s.outcome : 'regular',
      basis: has(BASES, s.basis) ? s.basis : 'current',
    };
  } catch {
    return { role: 'H', outcome: 'regular', basis: 'current' };
  }
}
function saveChoices(c) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(c)); } catch { /* storage blocked: the choices last for the session */ }
}

const pct = v => `${Math.round(v * 100)}%`;
const fmtInt = v => Math.round(v).toLocaleString();

/**
 * The share and its sample for one outcome. Null when the cell is empty.
 * regular is a share of n; mlb, useful and good are shares of useful_n (the
 * players whose peak is realized).
 */
function pick(cell, outcome) {
  if (!cell) return null;
  const share = outcome === 'regular' ? cell.regular : outcome === 'mlb' ? cell.mlb
    : outcome === 'useful' ? cell.useful : cell.good;
  const n = outcome === 'regular' ? cell.n : cell.useful_n;
  if (typeof share !== 'number' || typeof n !== 'number' || n <= 0) return null;
  return { share, n, all: cell.n };
}

function Chips({ options, value, onChange }) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map(([k, label]) => (
        <button
          key={k}
          onClick={() => onChange(k)}
          className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${
            value === k ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function OddsTable({ attr, table, ages, bands, outcome, thinN, roleWord, outcomeWord }) {
  const label = ATTR_LABEL[attr] || attr;
  const rows = [...bands].sort((a, b) => b - a);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-800">
        <h3 className="text-sm font-bold text-slate-200">{label}{label !== attr && <span className="text-slate-600 font-normal"> {attr}</span>}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs whitespace-nowrap">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <th className="text-left px-3 py-1.5 sticky left-0 bg-slate-900 z-10">{label}</th>
              {ages.map(a => <th key={a} className="px-1.5 py-1.5 text-right min-w-[3.5rem]">Age {a}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(band => (
              <tr key={band} className="border-b border-slate-800/40 hover:bg-slate-800/30">
                <td className="px-3 py-1 text-slate-300 font-mono sticky left-0 bg-slate-900 z-10">{band}</td>
                {ages.map(a => {
                  const c = pick(table?.[String(band)]?.[String(a)], outcome);
                  if (!c) return <td key={a} className="px-1.5 py-1" title={`${label} ${band}, age ${a}: nobody`} />;
                  const thin = c.n < thinN;
                  const color = thin ? 'text-slate-500' : getCellColorClass(c.share, COLOR_COLUMN[outcome]);
                  const title = `${label} ${band}, age ${a}: ${pct(c.share)} of ${fmtInt(c.n)} ${roleWord} ${outcomeWord}`
                    + (outcome !== 'regular' && c.all !== c.n ? ` (${fmtInt(c.all)} seen at this age, ${fmtInt(c.n)} with a finished career)` : '')
                    + (thin ? `. Thin: under ${thinN}.` : '');
                  return (
                    <td key={a} className="px-1.5 py-1 text-right align-top leading-tight" title={title}>
                      <div className={`font-mono ${color}`}>{thin ? `(${pct(c.share)})` : pct(c.share)}</div>
                      <div className="text-[10px] text-slate-600">n {fmtInt(c.n)}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function MakeItOddsPage() {
  const [odds, setOdds] = useState(undefined);
  const [choices, setChoices] = useState(readChoices);
  const version = useDataVersion(null, 'odds');
  useEffect(() => {
    let on = true;
    loadOdds().then(d => {
      if (!on) return;
      // A reload that finds nothing keeps the old tables and tries again next time.
      if (d === null) resetOdds();
      setOdds(prev => (d === null && prev ? prev : d));
    });
    return () => { on = false; };
  }, [version]);
  const choose = patch => setChoices(prev => {
    const next = { ...prev, ...patch };
    saveChoices(next);
    return next;
  });

  const { role, outcome, basis } = choices;
  const tables = odds?.tables?.[role]?.[basis] || {};
  // Attributes in the file's order; a basis without a table for one (Ovr and
  // Pot have no potential basis) leaves it out.
  const attrs = useMemo(
    () => (odds?.attributes?.[role] || []).filter(a => tables[a]),
    [odds, role, tables]
  );
  const ages = odds?.ages || [];
  const bands = odds?.bands || [];
  const thinN = odds?.thin_n ?? 30;

  // The worked example in the explainer comes from the file itself.
  const example = useMemo(() => {
    const c = odds?.tables?.H?.current?.BABIP?.['25']?.['18'];
    return c && typeof c.regular === 'number' ? { share: c.regular, n: c.n } : null;
  }, [odds]);

  if (odds === undefined) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 size={18} className="animate-spin" /> Loading make-it odds...
      </div>
    );
  }
  if (!odds) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md text-slate-400 text-sm space-y-2">
          <p className="text-white font-bold">No make-it odds file yet</p>
          <p>The page reads /data/dev_rating_odds.json. Build it with:</p>
          <code className="block text-xs text-blue-400 bg-slate-900 rounded p-2">
            python tgs-viz/backtest/dev_rating_odds.py --write
          </code>
        </div>
      </div>
    );
  }

  const roleWord = role === 'P' ? 'pitchers' : 'hitters';
  const outcomeWord = outcome === 'regular' ? 'became MLB regulars'
    : outcome === 'mlb' ? 'peaked at -1 WAA or better (MLB level)'
    : outcome === 'useful' ? 'peaked at 0 WAA or better' : 'peaked at +1.5 WAA or better';
  const cohort = odds.cohort || {};
  const seasons = Array.isArray(odds.seasons) ? odds.seasons : null;

  return (
    <div className="h-full overflow-auto p-5 space-y-4">
      <div>
        <h1 className="text-xl font-black text-white">Make-it odds</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          DEV-league data (all-AI OOTP, true ratings), the same for every league. Informational only: nothing here feeds a projection.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 space-y-2">
        <p>
          Each cell is the share of DEV players who had that one rating at that age and went on to reach the outcome.
          {example
            ? <> Read it as: of DEV hitters who were 18 with a 25 BABIP, <span className="font-mono text-white">{pct(example.share)}</span> became MLB regulars (n {fmtInt(example.n)}).</>
            : <> Read it as: of DEV hitters who were 18 with a 25 BABIP, x% became MLB regulars.</>}
          {' '}The players are the {fmtInt(cohort.players || 0)} DEV players first seen at age 20 or younger
          ({fmtInt(cohort.hitters || 0)} hitters, {fmtInt(cohort.pitchers || 0)} pitchers){seasons ? `, seasons ${seasons[0]} to ${seasons[1]}` : ''},
          counted once at each age from 16 to 26 while in an organization.
        </p>
        <p>
          These are raw one-rating tables. Nothing else is held fixed: players in the same band differ in every other rating, so a cell says "players who looked like this in this one skill", not "players like this".
          {' '}Unlike these tables, the MLB %, Starter % and Star % on the player lists are conditional on the player's current WAA: the chance his peak reaches the bar from where he is now, so a player already there reads 100%.
        </p>
        <p>
          <span className="font-semibold text-white">MLB regular</span> = a season with 300 or more MLB PA (hitters) or 150 or more MLB BF (pitchers), at any point up to the last season. Every observation counts, so players still young at the last seasons count as not yet regular.{' '}
          <span className="font-semibold text-white">MLB level</span> = his best season by the engine WAA reached -1 (an MLB-level player: a 5th starter or bench bat), the chance he is ever anything in the majors.{' '}
          <span className="font-semibold text-white">Starter</span> = that peak reached 0 (an average starter).{' '}
          <span className="font-semibold text-white">Star</span> = that peak reached +1.5 WAA (a star). MLB level, Starter and Star count only players seen at 27 or older, so their n is smaller than the MLB-regular n.
        </p>
        <p>
          <span className="font-semibold text-white">Current rating</span> = the rating at that age (vs-R and vs-L averaged, rounded to the nearest 5). <span className="font-semibold text-white">Potential rating</span> = the potential rating of that skill at that age. Overall and Potential grade are the grades OOTP shows and come on the current basis only.
          {' '}n is the number of player-ages in the cell. A cell with n under {thinN} shows grey in parentheses: too few to trust. A blank cell means nobody was there.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span className="uppercase tracking-wider text-[10px] text-slate-500">Role</span>
          <Chips options={ROLES} value={role} onChange={v => choose({ role: v })} />
        </div>
        <div className="flex items-center gap-2">
          <span className="uppercase tracking-wider text-[10px] text-slate-500">Outcome</span>
          <Chips options={OUTCOMES} value={outcome} onChange={v => choose({ outcome: v })} />
        </div>
        <div className="flex items-center gap-2">
          <span className="uppercase tracking-wider text-[10px] text-slate-500">Basis</span>
          <Chips options={BASES} value={basis} onChange={v => choose({ basis: v })} />
        </div>
      </div>

      {attrs.length === 0 ? (
        <p className="text-sm text-slate-500">No tables for this choice.</p>
      ) : attrs.map(attr => (
        <OddsTable
          key={`${role}-${basis}-${attr}`}
          attr={attr} table={tables[attr]} ages={ages} bands={bands}
          outcome={outcome} thinN={thinN} roleWord={roleWord} outcomeWord={outcomeWord}
        />
      ))}

      <div className="flex items-start gap-2 text-[11px] text-slate-500">
        <Info size={13} className="shrink-0 mt-0.5" />
        <p>
          Built by backtest/dev_rating_odds.py{odds.generated ? ` on ${String(odds.generated).slice(0, 10)}` : ''} from the same cohort and outcomes as the DEV cell method, the fallback behind MLB %, Starter % and Star %.
          {' '}HRR here is the HRR column of the app (the HRA rating in OOTP), not the Movement composite.
        </p>
      </div>
    </div>
  );
}

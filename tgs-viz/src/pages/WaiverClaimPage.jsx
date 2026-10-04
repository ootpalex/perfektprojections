import React, { useState, useEffect, useMemo, useRef } from 'react';
import { buildClaimBoard, fortyManSpots, CLOCK_CLAIMABLE, CLOCK_CLEARED, CLOCK_DFA } from '../lib/waivers';
import { listOrgs } from '../lib/orgBuilder';
import { formatMoney } from '../lib/marketValue';
import { useAppConfig } from '../lib/controlApi';
import { posClass, levelKey } from '../lib/columns';
import { getProne } from '../lib/accessors';
import { intangiblesGrader, smartScore, sortBySmart } from '../lib/waiverSmartRank';

const fmt = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));
// Same bands as before the restyle (> 1, > 0, > -1.5, else); only the classes changed.
const valColor = (v) => (v === null || v === undefined ? 'ns-dim'
  : v > 1 ? 'ns-g70' : v > 0 ? 'ns-text-2' : v > -1.5 ? 'ns-g40' : 'ns-g20');

const PRONE_CLASS = {
  'Iron Man': 'ns-prone-iron-man', Durable: 'ns-prone-durable', Normal: 'ns-prone-normal',
  Fragile: 'ns-prone-fragile', Wrecked: 'ns-prone-wrecked',
};

function StatusChip({ e }) {
  // His three-way status colours as meaning: both flags bad, waivers caution, DFA neutral.
  const cls = e.onWaivers && e.dfa ? 'ns-bad' : e.onWaivers ? 'ns-warn' : 'ns-text-2';
  return <span className={`ns-chip ${cls}`}>{e.status}</span>;
}

// The live claim clock (ours' ladder): days left, ≤ 1 day in red; DFA has no clock yet.
function ClockCell({ e }) {
  if (e.clock === CLOCK_DFA) {
    return <span className="ns-muted" title="Designated for assignment, not yet placed on waivers: no claim clock is running">DFA</span>;
  }
  if (e.clock === CLOCK_CLEARED) {
    return <span className="ns-muted" title="0 days left: went unclaimed and cleared waivers">cleared</span>;
  }
  if (e.daysLeft === null) {
    return <span className="ns-dim" title="On waivers, but this league's data carries no claim clock">—</span>;
  }
  return (
    <span className={e.daysLeft <= 1 ? 'ns-bad font-bold' : 'ns-text'}
      title={`In-game days left on the claim clock, per StatsPlus${e.daysOn !== null ? ` (${e.daysOn} served)` : ''}`}>
      {e.daysLeft}d
    </span>
  );
}

function SummaryCard({ title, children }) {
  return (
    <div className="ns-card">
      <h3 className="ns-strip">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

// The decision cell: does claiming him improve OUR roster, and who goes.
function FitCell({ e }) {
  if (e.ownOrg) return <span className="ns-muted">already ours</span>;
  if (!e.fit || !e.fit.incumbent) {
    return <span className="ns-muted" title="this org has nobody at MLB level in that role to compare against">no MLB incumbent</span>;
  }
  const { gain, incumbent } = e.fit;
  return (
    <span className={gain > 0 ? 'ns-good' : 'ns-muted'}>
      {gain > 0 ? '+' : ''}{fmt(gain)} <span className="ns-muted">over {incumbent.name}</span>
    </span>
  );
}

function ClaimTable({ rows, smartOn, smartOf, gradeOf, emptyText }) {
  return (
    <div className="overflow-auto">
      <table className="ns-table">
        <thead>
          <tr>
            {smartOn && <th className="num" title="Above org repl, adjusted by the Smart rank toggles that are on">Smart</th>}
            <th>Status</th>
            <th className="num" title="Claim clock: in-game days left on waivers">Left</th>
            <th className="col-group-start">Player</th>
            <th>Pos</th>
            <th className="num">Age</th>
            <th>Lev</th>
            <th>Org</th>
            <th className="num col-group-start" title="value vs average, at the best spot he is eligible for">WAA</th>
            <th className="num" title="WAA plus the league's measured org (next-man-up) replacement offset">Above org repl</th>
            <th>Claim verdict</th>
            <th className="col-group-start">Prone</th>
            <th className="num" title="Intangibles: a 20-80 grade from work ethic, intelligence, leadership and loyalty, against this league">INTG</th>
            <th className="num col-group-start">Salary</th>
            <th className="num" title="contract year of total years">Ctr</th>
            <th className="num" title="MLB service years">Svc</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={smartOn ? 16 : 15} className="text-center ns-muted">{emptyText}</td></tr>
          )}
          {rows.map((e) => {
            const prone = getProne(e.player);
            const lvl = levelKey(e.level);
            const grade = gradeOf(e.player);
            const smart = smartOn ? smartOf(e) : null;
            return (
              <tr key={e.id}>
                {smartOn && <td className={`num font-bold ${valColor(smart)}`}>{fmt(smart)}</td>}
                <td><StatusChip e={e} /></td>
                <td className="num"><ClockCell e={e} /></td>
                <td className="col-group-start ns-text font-semibold">
                  {e.name}
                  {e.onDL && <span className="ml-1.5 text-[11px] ns-bad" title="on the disabled list right now">DL</span>}
                </td>
                <td className={posClass(e.pos || e.listedPos) || 'ns-text-2'}>{e.pos || e.listedPos || '—'}</td>
                <td className="num ns-text-2">{e.age ?? '—'}</td>
                <td>{lvl ? <span className="ns-chip" data-lvl={lvl}>{e.level}</span> : <span className={e.level ? 'ns-muted' : 'ns-dim'}>{e.level || '—'}</span>}</td>
                <td className="ns-text-2 truncate max-w-[150px]">{e.org || '—'}</td>
                <td className={`num col-group-start ${valColor(e.waa)}`}>{fmt(e.waa)}</td>
                <td className={`num ${valColor(e.vor)}`}>{fmt(e.vor)}</td>
                <td><FitCell e={e} /></td>
                <td className={`col-group-start ${PRONE_CLASS[prone] || 'ns-dim'}`}>{prone || '—'}</td>
                <td className={`num ${grade === null ? 'ns-dim' : 'ns-text-2'}`}>{grade ?? '—'}</td>
                <td className="num col-group-start ns-text-2">{e.salary === null ? '—' : formatMoney(e.salary)}</td>
                <td className="num ns-muted">
                  {e.contractYr ? `${e.contractYr}${e.contractYrs ? `/${e.contractYrs}` : ''}` : '—'}
                </td>
                <td className="num ns-muted">{e.svcYears ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Waiver / DFA claim board — every player the selected league has made
 * available, ranked by value above the ORG replacement level measured for THAT
 * league (leagueCalib.replacementOrg): the "next man up" floor, which is the
 * right zero for a claim because the alternative is our own depth.
 *
 * The live claim clock (WaiverDaysLeft) splits the board: players whose clock
 * ran out have cleared and sit in their own box below. Smart rank toggles
 * (ours' injury / intangibles adjustments) re-order the claimable board.
 *
 * The 40-man card shows the org's occupancy (On40Man) because a claim costs a
 * spot; the claim verdict itself does not price that spot.
 */
export default function WaiverClaimPage({ hitters, pitchers, league }) {
  const orgs = useMemo(() => listOrgs(hitters, pitchers), [hitters, pitchers]);
  const [org, setOrg] = useState('');
  // Default org: the league's my_org from the settings (app config), else the
  // first org matching /cub/i, else the first org. The config may arrive after
  // the rows. Once the user picks an org, only an org that left the list is fixed.
  const myOrg = useAppConfig()?.leagues?.[league]?.my_org;
  const pickedOrg = useRef(false);
  useEffect(() => {
    if (!orgs.length) return;
    if (pickedOrg.current && orgs.includes(org)) return;
    const want = orgs.find((o) => o === myOrg) || orgs.find((o) => /cub/i.test(o)) || orgs[0];
    if (want !== org) setOrg(want);
  }, [orgs, myOrg]); // eslint-disable-line react-hooks/exhaustive-deps

  const [onlyUpgrades, setOnlyUpgrades] = useState(false);
  const [smart, setSmart] = useState({ injury: false, intangibles: false });
  const smartOn = smart.injury || smart.intangibles;

  const board = useMemo(
    () => buildClaimBoard(hitters, pitchers, { league, org: org || undefined }),
    [hitters, pitchers, league, org]
  );

  // Intangibles grade against this league's whole population (ours' enrich step).
  const gradeOf = useMemo(() => intangiblesGrader([...(hitters || []), ...(pitchers || [])]), [hitters, pitchers]);
  const smartOf = (e) => smartScore(e, smart, gradeOf(e.player));

  // Claimable = clock running or DFA'd; cleared = the clock ran out.
  const liveAll = smartOn ? sortBySmart(board.live, smartOf) : board.live;
  const rows = onlyUpgrades ? liveAll.filter(e => e.fit && e.fit.improves) : liveAll;
  const upgrades = board.live.filter(e => e.fit && e.fit.improves).length;
  const aboveRepl = board.live.filter(e => e.vor > 0).length;
  const inc = board.incumbents || {};
  const onClock = board.live.filter(e => e.clock === CLOCK_CLAIMABLE).length;
  const forty = useMemo(() => fortyManSpots(hitters, pitchers, org), [hitters, pitchers, org]);

  return (
    <div className="ns-page overflow-auto">
      <header className="ns-page-head">
        <div>
          <h1>Waiver &amp; DFA Claim Board</h1>
          <p className="ns-page-sub max-w-4xl">
            Ranked by value above <b>org replacement</b> (next man up), measured for {league}:
            bat {board.offsets.hitter} · SP {board.offsets.sp} · RP {board.offsets.rp} wins.
            Value shown is WAA (vs average); the fit column prices him against the man he would push off.
          </p>
        </div>
        <div className="ns-head-actions">
          <label className="ns-label" htmlFor="waiver-org">Org</label>
          <select id="waiver-org" value={org} onChange={(e) => { pickedOrg.current = true; setOrg(e.target.value); }}
            className="ns-select min-w-[200px]">
            {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <SummaryCard title="Available now">
          <div className="text-[12.5px] ns-text">{board.counts.waivers} on waivers · {board.counts.dfa} designated for assignment</div>
          <div className="text-[12.5px] ns-text">
            {board.counts.claimable} claimable on the clock · {board.counts.cleared} cleared · {board.counts.dfaOnly} DFA, not yet on waivers
          </div>
          <div className="text-[11px] ns-muted">{board.counts.both} are both · {board.counts.total} players total</div>
          <div className="text-[11px] ns-muted">{board.counts.hitters} bats · {board.counts.sp} SP · {board.counts.rp} RP</div>
        </SummaryCard>
        <SummaryCard title="Worth a spot">
          <div className="text-[12.5px] ns-text">{aboveRepl} claimable clear org replacement</div>
          <div className="text-[12.5px] ns-text">{upgrades} claimable beat a body {org} has at MLB level</div>
          {forty ? (
            <div className="text-[12.5px] ns-text">
              40-man: <b>{forty.used}</b> of {forty.limit} used ·{' '}
              <span className={forty.open === 0 ? 'ns-bad font-semibold' : 'ns-good'}>{forty.open} open</span>
            </div>
          ) : (
            <div className="text-[11px] ns-muted">40-man occupancy unknown: this league's data carries no 40-man flag</div>
          )}
          <div className="text-[11px] ns-muted">a claim costs a 40-man spot; the verdict does not price it</div>
        </SummaryCard>
        <SummaryCard title={`Weakest ${org} MLB body`}>
          {['hitter', 'sp', 'rp'].map((r) => (
            <div key={r} className="text-[12.5px] ns-text flex justify-between gap-2">
              <span className="ns-muted w-10">{r === 'hitter' ? 'Bat' : r.toUpperCase()}</span>
              <span className="truncate">{inc[r] ? `${inc[r].name} (${inc[r].pos})` : '—'}</span>
              <span className={`w-12 text-right tabular-nums ${valColor(inc[r]?.waa ?? null)}`}>{fmt(inc[r]?.waa ?? null)}</span>
            </div>
          ))}
        </SummaryCard>
      </div>

      <section className="ns-box mb-4">
        <div className="ns-strip">
          <h2>Claimable now <span className="ns-count">({rows.length})</span></h2>
          <span className="ns-strip-right">
            {board.counts.clockKnown > 0
              ? <>{onClock} on the claim clock · {board.counts.dfaOnly} DFA</>
              : <>no claim clock in this league's data · every waiver flag reads as claimable</>}
          </span>
        </div>
        <div className="ns-toolbar">
          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={onlyUpgrades}
            onClick={() => setOnlyUpgrades(!onlyUpgrades)}>
            Only players who would improve {org || 'the roster'}
          </button>
          <span className="ns-label ml-2">Smart rank</span>
          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={smart.injury}
            title="Bonus for Iron Man / Durable, penalty for Fragile / Wrecked, in wins (Iron Man +0.5 … Wrecked −2.0; relievers at 0.375×)"
            onClick={() => setSmart((s) => ({ ...s, injury: !s.injury }))}>
            Injury proneness
          </button>
          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={smart.intangibles}
            title="Bonus for a high intangibles grade, penalty for a low one: 0.15 wins per 10 grade points from 50 (relievers at 0.375×)"
            onClick={() => setSmart((s) => ({ ...s, intangibles: !s.intangibles }))}>
            Intangibles
          </button>
          <span className="ml-auto text-[11px] ns-muted">{rows.length} shown</span>
        </div>
        <ClaimTable rows={rows} smartOn={smartOn} smartOf={smartOf} gradeOf={gradeOf}
          emptyText={`Nobody claimable in ${league} right now.`} />
      </section>

      {board.cleared.length > 0 && (
        <section className="ns-box mb-4">
          <div className="ns-strip">
            <h2>Cleared waivers, no longer claimable <span className="ns-count">({board.cleared.length})</span></h2>
          </div>
          <p className="ns-sub pb-2.5">
            Zero days left on the clock: these players went unclaimed and cleared. Their org can now outright or release them.
          </p>
          <ClaimTable rows={board.cleared} smartOn={false} smartOf={smartOf} gradeOf={gradeOf} emptyText="None." />
        </section>
      )}

      <p className="text-[11px] ns-muted max-w-4xl">
        Salary is the remaining deal's average annual value where the row carries one; players with no contract data
        show a dash rather than a guess. A claim verdict compares his WAA at his best eligible spot with the weakest
        MLB-level body this org holds in the same role — it does not model 40-man spots, option years, or claim
        priority. Smart rank adds the injury and intangibles adjustments, in wins, to the value above org replacement.
      </p>
    </div>
  );
}

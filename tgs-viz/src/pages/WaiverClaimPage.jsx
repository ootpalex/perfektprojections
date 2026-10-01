import React, { useState, useEffect, useMemo, useRef } from 'react';
import { buildClaimBoard } from '../lib/waivers';
import { listOrgs } from '../lib/orgBuilder';
import { formatMoney } from '../lib/marketValue';
import { useAppConfig } from '../lib/controlApi';
import { ClipboardList, ChevronDown, ArrowUpCircle, AlertTriangle, Users } from 'lucide-react';

const fmt = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2));
const valColor = (v) => (v === null || v === undefined ? 'text-slate-600'
  : v > 1 ? 'text-emerald-400' : v > 0 ? 'text-slate-200' : v > -1.5 ? 'text-amber-400/80' : 'text-rose-400/80');

function StatusChip({ e }) {
  const cls = e.onWaivers && e.dfa ? 'bg-rose-500/20 text-rose-300 border-rose-500/50'
    : e.onWaivers ? 'bg-amber-500/20 text-amber-300 border-amber-500/50'
    : 'bg-sky-500/15 text-sky-300 border-sky-500/40';
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border ${cls}`}>{e.status}</span>;
}

function SummaryCard({ title, icon, children }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-3 py-2 bg-slate-900 border-b border-slate-800 flex items-center gap-2">
        {icon}<span className="text-xs font-bold text-slate-300 uppercase tracking-wide">{title}</span>
      </div>
      <div className="p-3 space-y-1">{children}</div>
    </div>
  );
}

// The decision cell: does claiming him improve OUR roster, and who goes.
function FitCell({ e }) {
  if (e.ownOrg) return <span className="text-slate-600">already ours</span>;
  if (!e.fit || !e.fit.incumbent) {
    return <span className="text-slate-600" title="this org has nobody at MLB level in that role to compare against">no MLB incumbent</span>;
  }
  const { gain, incumbent } = e.fit;
  return (
    <span className={gain > 0 ? 'text-emerald-400' : 'text-slate-500'}>
      {gain > 0 ? '+' : ''}{fmt(gain)} <span className="text-slate-500">over {incumbent.name}</span>
    </span>
  );
}

/**
 * Waiver / DFA claim board — every player the selected league has made
 * available, ranked by value above the ORG replacement level measured for THAT
 * league (leagueCalib.replacementOrg): the "next man up" floor, which is the
 * right zero for a claim because the alternative is our own depth.
 *
 * No 40-man modelling: the shipped rows carry no 40-man flag, so the board
 * never claims to know whether a spot is open.
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

  const board = useMemo(
    () => buildClaimBoard(hitters, pitchers, { league, org: org || undefined }),
    [hitters, pitchers, league, org]
  );

  const rows = onlyUpgrades ? board.entries.filter(e => e.fit && e.fit.improves) : board.entries;
  const upgrades = board.entries.filter(e => e.fit && e.fit.improves).length;
  const aboveRepl = board.entries.filter(e => e.vor > 0).length;
  const inc = board.incumbents || {};

  return (
    <div className="h-full overflow-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <ClipboardList className="text-blue-400" size={22} />
          <div>
            <h1 className="text-xl font-black text-white">Waiver &amp; DFA Claim Board</h1>
            <p className="text-xs text-slate-500">
              Ranked by value above <span className="text-slate-300">org replacement</span> (next man up) — measured for {league}:
              bat {board.offsets.hitter} · SP {board.offsets.sp} · RP {board.offsets.rp} wins.
              Value shown is WAA (vs average); the fit column prices him against the man he would push off.
            </p>
          </div>
        </div>
        <div className="relative">
          <select value={org} onChange={(e) => { pickedOrg.current = true; setOrg(e.target.value); }}
            className="appearance-none bg-slate-800 text-white text-sm font-semibold rounded-lg px-3 py-2 pr-8 border border-slate-700 hover:border-blue-500 focus:outline-none cursor-pointer min-w-[200px]">
            {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        <SummaryCard title="Available now" icon={<AlertTriangle size={14} className="text-amber-400" />}>
          <div className="text-xs text-slate-300">{board.counts.waivers} on waivers · {board.counts.dfa} designated for assignment</div>
          <div className="text-[11px] text-slate-500">{board.counts.both} are both · {board.counts.total} players total</div>
          <div className="text-[11px] text-slate-500">{board.counts.hitters} bats · {board.counts.sp} SP · {board.counts.rp} RP</div>
        </SummaryCard>
        <SummaryCard title="Worth a spot" icon={<ArrowUpCircle size={14} className="text-emerald-400" />}>
          <div className="text-xs text-slate-300">{aboveRepl} clear org replacement</div>
          <div className="text-xs text-slate-300">{upgrades} beat a body {org} has at MLB level</div>
          <div className="text-[11px] text-slate-600">no 40-man flag ships, so roster-spot cost is not modelled</div>
        </SummaryCard>
        <SummaryCard title={`Weakest ${org} MLB body`} icon={<Users size={14} className="text-slate-400" />}>
          {['hitter', 'sp', 'rp'].map((r) => (
            <div key={r} className="text-xs text-slate-300 flex justify-between">
              <span className="uppercase text-slate-500 w-10">{r === 'hitter' ? 'bat' : r}</span>
              <span className="truncate">{inc[r] ? `${inc[r].name} (${inc[r].pos})` : '—'}</span>
              <span className={`w-12 text-right ${valColor(inc[r]?.waa ?? null)}`}>{fmt(inc[r]?.waa ?? null)}</span>
            </div>
          ))}
        </SummaryCard>
      </div>

      <div className="flex items-center gap-3 mb-2">
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={onlyUpgrades} onChange={(e) => setOnlyUpgrades(e.target.checked)}
            className="accent-blue-500" />
          Only players who would improve the {org} roster
        </label>
        <span className="text-[11px] text-slate-600">{rows.length} shown</span>
      </div>

      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-900 text-slate-500 uppercase text-[10px] tracking-wider">
            <tr>
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-left px-3 py-2">Player</th>
              <th className="text-left px-2 py-2">Pos</th>
              <th className="text-right px-2 py-2">Age</th>
              <th className="text-left px-2 py-2">Lev</th>
              <th className="text-left px-2 py-2">Org</th>
              <th className="text-right px-2 py-2" title="value vs average, at the best spot he is eligible for">WAA</th>
              <th className="text-right px-2 py-2" title="WAA plus the league's measured org (next-man-up) replacement offset">Above org repl</th>
              <th className="text-left px-3 py-2">Claim verdict</th>
              <th className="text-right px-2 py-2">Salary</th>
              <th className="text-right px-2 py-2" title="contract year of total years">Ctr</th>
              <th className="text-right px-2 py-2" title="MLB service years">Svc</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={12} className="px-3 py-6 text-center text-slate-600">
                Nobody is on waivers or designated for assignment in {league} right now.
              </td></tr>
            )}
            {rows.map((e) => (
              <tr key={e.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                <td className="px-3 py-1.5"><StatusChip e={e} /></td>
                <td className="px-3 py-1.5 text-slate-200 whitespace-nowrap">
                  {e.name}
                  {e.onDL && <span className="ml-1.5 text-[10px] text-rose-400/80" title="on the disabled list right now">DL</span>}
                </td>
                <td className="px-2 py-1.5 text-slate-400">{e.pos || e.listedPos || '—'}</td>
                <td className="px-2 py-1.5 text-right text-slate-400 tabular-nums">{e.age ?? '—'}</td>
                <td className="px-2 py-1.5 text-slate-500">{e.level || '—'}</td>
                <td className="px-2 py-1.5 text-slate-500 truncate max-w-[150px]">{e.org || '—'}</td>
                <td className={`px-2 py-1.5 text-right tabular-nums ${valColor(e.waa)}`}>{fmt(e.waa)}</td>
                <td className={`px-2 py-1.5 text-right tabular-nums ${valColor(e.vor)}`}>{fmt(e.vor)}</td>
                <td className="px-3 py-1.5 whitespace-nowrap"><FitCell e={e} /></td>
                <td className="px-2 py-1.5 text-right text-slate-400 tabular-nums">{e.salary === null ? '—' : formatMoney(e.salary)}</td>
                <td className="px-2 py-1.5 text-right text-slate-500 tabular-nums">
                  {e.contractYr ? `${e.contractYr}${e.contractYrs ? `/${e.contractYrs}` : ''}` : '—'}
                </td>
                <td className="px-2 py-1.5 text-right text-slate-500 tabular-nums">{e.svcYears ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[11px] text-slate-600 max-w-4xl">
        Salary is the remaining deal's average annual value where the row carries one; players with no contract data
        show a dash rather than a guess. A claim verdict compares his WAA at his best eligible spot with the weakest
        MLB-level body this org holds in the same role — it does not model 40-man spots, option years, or claim
        priority, none of which ship in the data.
      </p>
    </div>
  );
}

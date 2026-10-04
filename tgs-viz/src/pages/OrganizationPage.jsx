import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  LEVELS, LEVEL_RANK, buildRosters, listOrgs, chanceOf,
  isFillerBat, trainingNotes, TRAIN_PEAK_BAR, keepCmp,
} from '../lib/orgBuilder';
import { devAlreadyThere, devShareBasisWords, devIsMl, devMlWords, devMlRangeNote, fmtWaa } from '../lib/devSignals';
import { PositionalStrengthCard } from '../components/PositionalStrength';
import { LEAGUE_TEAMS } from './TeamStandingsPage';
import { resolveLeagueClubs } from '../lib/leagueClubs';
import { usePlayerData, usePlayersWithFV } from '../hooks/usePlayerData';
import { useAppConfig } from '../lib/controlApi';
import { Building2, ArrowUpCircle, ArrowDownCircle, AlertTriangle, ChevronDown, Zap, Users } from 'lucide-react';

const fmt = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(1));
const valColor = (v) => (v === null || v === undefined ? 'text-slate-600'
  : v > 1 ? 'text-emerald-400' : v > 0 ? 'text-slate-200' : v > -1.5 ? 'text-amber-400/80' : 'text-rose-400/80');
// wOBA (MLB-equivalent projection) — for ordering the batting lineup. Same color scale as
// the rest of the app; minor-leaguers read low because the values are MLB-equivalent.
const fmtWoba = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(3));
const wobaColor = (v) => (v === null || v === undefined ? 'text-slate-600'
  : v >= 0.400 ? 'text-purple-400 font-semibold' : v >= 0.360 ? 'text-cyan-400' : v >= 0.320 ? 'text-emerald-400'
  : v >= 0.300 ? 'text-slate-200' : v >= 0.280 ? 'text-amber-400/80' : 'text-rose-400/80');

// Display order for position players, matching OOTP's defensive-spectrum order.
// (The builder fills slots hardest-position-first for assignment quality; this only
// reorders how they're shown.)
const POS_ORDER = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];
const posRank = (pos) => { const i = POS_ORDER.indexOf(pos); return i < 0 ? POS_ORDER.length : i; };

function Badge({ children, cls, title }) {
  return <span title={title} className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border ${cls}`}>{children}</span>;
}

const LEVEL_NAME = { INT: 'the international complex', WL: 'winter ball', 'R-': 'R-', 'R+': 'R+', 'A-': 'A-', 'A+': 'A+', AA: 'AA', AAA: 'AAA', MLB: 'MLB' };

// Where the player is RIGHT NOW in the org (his current OOTP level), shown beside his
// name so he's easy to find in-game — the card itself is only where he *should* be.
// Green ↑ when his ability has slotted him above where he currently is (= promote him);
// muted "@" otherwise (he's at that level now — go find him there).
function LocChip({ p, cardLev }) {
  const lev = p['Lev'];
  if (!lev) return null;
  const aRank = LEVEL_RANK[lev], cRank = LEVEL_RANK[cardLev];
  const promote = aRank !== undefined && cRank !== undefined && aRank < cRank;
  return promote
    ? <Badge title={`promote — he's in ${LEVEL_NAME[lev] || lev} right now`} cls="bg-emerald-500/20 text-emerald-300 border-emerald-500/50">↑ {lev}</Badge>
    : <Badge title={`currently in ${LEVEL_NAME[lev] || lev} — find him there in OOTP`} cls="bg-slate-700/30 text-slate-400 border-slate-600/40">@ {lev}</Badge>;
}

// Other per-player tags. Captain = leadership + work ethic + loyalty: all three high
// is a lock (★); leadership & work ethic high with normal loyalty is a likely captain
// (☆). "prove it" flags an 18+ guy still stuck in the complex (promote-or-release).
function Tags({ p, cardLev }) {
  const U = (v) => String(v).toUpperCase();
  const L = U(p['Lead']), W = U(p['WrkEthic']), Lo = U(p['Loy']);
  const lock = L === 'H' && W === 'H' && Lo === 'H';
  const likely = !lock && L === 'H' && W === 'H' && Lo === 'N';
  const age = parseInt(p['Age'], 10);
  const proveIt = cardLev === 'INT' && Number.isFinite(age) && age >= 18;
  return (
    <>
      {lock && <Badge title="captain — high leadership, work ethic & loyalty" cls="bg-amber-500/20 text-amber-300 border-amber-500/50">★</Badge>}
      {likely && <Badge title="likely captain — leadership & work ethic high, loyalty normal" cls="bg-amber-500/10 text-amber-300/70 border-amber-500/30">☆</Badge>}
      {proveIt && <Badge title="18+ and still in the complex — prove it or lose it" cls="bg-orange-500/15 text-orange-300 border-orange-500/40">prove it</Badge>}
    </>
  );
}

// Training positions (user, 2026-09-24: "notate the positions they lack
// training by each of the prospects to work as a reminder. I forget all the
// time to change positions during the season in the minors for training").
// One amber chip per bat listing every position where he is 0 WAA or better
// if he reaches his potential but has not mastered (position rating
// current/potential, 0 = never trained), best first. The rule and the math
// live in orgBuilder.trainingNotes (the P WAA P line). Who gets it: on a
// minors card any bat who is not a filler (isFillerBat: a filler does not
// develop); on the MLB card any bat under 27 (he still trains). Pitchers
// never. The hover lists his WAA at each position at his potential.
function TrainChip({ h, lev }) {
  if (h.isPitcher) return null;
  const trains = lev === 'MLB' ? (h.age != null && h.age < 27) : !isFillerBat(h);
  if (!trains) return null;
  const notes = trainingNotes(h.p);
  if (!notes.length) return null;
  const signed = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
  const label = notes.map((n) => (n.untrained ? `${n.pos} new` : `${n.pos} ${n.cur}/${n.pot}`)).join(' · ');
  const peaks = notes.map((n) => `${n.pos} ${signed(n.peak)}`).join(', ');
  const title = `Positions where he is ${TRAIN_PEAK_BAR} WAA or better if he reaches his potential, but has not mastered (position rating current/potential; "new" = never trained there, his tools carry it). Set his training position in OOTP. His WAA there at his potential: ${peaks}.`;
  return <Badge title={title} cls="bg-amber-500/15 text-amber-300 border-amber-500/40 whitespace-nowrap">train {label}</Badge>;
}

// Parse a raw sheet value; null when the projection doesn't exist for that role.
const pnum = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

// MLB % on minors rows (user, 2026-09-24, "if they will ever be anything in
// the mlb first and foremost"): the chance the player's eventual peak
// reaches -1 WAA (an MLB-level player: a 5th starter or bench bat) from
// where he is now, from the ML model (devMl.js), else the share of his DEV
// lookalikes (same age, Pot, growth and a similar current) whose gain
// covered the distance; a player already at the bar reads 100% (user,
// 2026-09-24: "there are a ton of guys who are already at 0+ WAA that are
// getting like tagged as less than 100%").
// Starter % (0) and Star % (+1.5) sit in the hover. These, not Make it %,
// rank minors playing time (orgBuilder chanceOf: rotations, pens and
// lineups, chance first). A row with no DEV group at all (growth and
// pot-only cells both thin, or outside 16-26) shows the stand-in from Proj
// Potential with an asterisk. Hover wording matches the list columns
// (devSignals.js devShareTitle).
const pct = (v) => `${Math.round(v * 100)}%`;
const chanceRow = (x, lev) => (lev === 'MLB' ? null : (x.chance || chanceOf(x.p)));
const chanceText = (c) => (c === null ? '' : `${pct(c.mlb)}${c.source === 'stand-in' ? '*' : ''}`);
const chanceTitle = (c, p) => {
  const s = (v) => (v === null || v === undefined ? '?' : pct(v));
  const head = `MLB ${s(c.mlb)}${c.source === 'stand-in' ? '*' : ''} / Starter ${s(c.useful)} / Star ${s(c.good)}`;
  if (c.source === 'stand-in') return `${head}: * stand-in from Proj Potential, no DEV group at all (growth and pot-only cells both thin, or outside 16-26)`;
  const now = p ? p.Dev_ShareNow : null;
  if (devIsMl(p)) {
    // ML (2026-09-25): wording only; the chances the builder ranks on are
    // the same fields, now filled by the ML model (devMl.js).
    const cur = `${fmtWaa(now)}${p.Dev_Role === 'P' ? ', his better of SP and RP' : ''}`;
    const already = ['mlb', 'useful', 'good'].filter((k) => devAlreadyThere(p, k));
    const there = already.length ? ` Already ${already.map((k) => ({ mlb: 'at MLB level', useful: 'at starter level', good: 'a star' }[k])).join(', ')} (current ${cur}).` : '';
    const s = (v) => (v === null || v === undefined ? '?' : pct(v));
    return `${head}: chance his peak reaches -1 / 0 / +1.5 WAA from his current ${cur}, from ${devMlWords(p)}; cell method: ${s(p.Dev_CellMlb)} / ${s(p.Dev_CellUseful)} / ${s(p.Dev_CellGood)}${devMlRangeNote(p)}.${there}`;
  }
  if (now === null || now === undefined) return `${head}: share of DEV lookalikes whose peak reached -1 / 0 / +1.5 WAA; his current is unknown, so these are the group's shares, not his own chance`;
  const n = p.Dev_PeakN !== null && p.Dev_PeakN !== undefined ? `n ${p.Dev_PeakN}` : 'n unknown';
  const cell = p.Dev_PeakCell ? `, DEV cell ${p.Dev_PeakCell}` : '';
  const basis = devShareBasisWords(p);
  // A pitcher's current is the better of his SP and RP lines, not always
  // the line this row shows (a rotation row shows the SP line).
  const cur = `${fmtWaa(now)}${p.Dev_Role === 'P' ? ', his better of SP and RP' : ''}`;
  const already = ['mlb', 'useful', 'good'].filter((k) => devAlreadyThere(p, k));
  const there = already.length ? ` Already ${already.map((k) => ({ mlb: 'at MLB level', useful: 'at starter level', good: 'a star' }[k])).join(', ')} (current ${cur}).` : '';
  return `${head}: chance his peak reaches -1 / 0 / +1.5 WAA from his current ${cur}: the share of DEV players with his age, Pot, growth and a similar current whose gain covered the distance (${n}${cell}${basis ? `, ${basis}` : ''}).${there}`;
};

function PitcherLine({ x, lev, role }) {
  // Show the WAA of the ROLE this line slots him in (user rule: the value at
  // the position he's playing) — SP line in a rotation row, RP line in a pen
  // row — not his best-of-roles value, which made a −0.26 SP4 read as +0.1.
  const cur = role === 'SP' ? (pnum(x.p['WAA wtd']) ?? x.cur)
    : role === 'RP' ? (pnum(x.p['WAA wtd RP']) ?? x.cur) : x.cur;
  const pot = role === 'SP' ? (pnum(x.p['WAP']) ?? x.pot)
    : role === 'RP' ? (pnum(x.p['WAP RP']) ?? x.pot) : x.pot;
  const chance = chanceRow(x, lev);
  return (
    <div className="flex items-center justify-between px-2 py-1 border-t border-slate-800/50 text-xs">
      <span className="text-slate-200 truncate flex items-center gap-1">{x.p['Name']} <span className="text-slate-600">{x.p['T']}HP</span><LocChip p={x.p} cardLev={lev} /><Tags p={x.p} cardLev={lev} />
        {x._stretch && <Badge title={`roster filler — stretched up from ${x.ceiling} to complete the staff (no real future, so no harm)`} cls="bg-amber-500/15 text-amber-300/80 border-amber-500/30">stretch ↑ {x.ceiling}</Badge>}
        {x._devDepth && <Badge title="roster depth — fills the staff beyond the core 6 SP / 9 RP (young arms kept to develop, plus fillers to reach the roster cap)" cls="bg-sky-500/10 text-sky-300/70 border-sky-500/25">depth</Badge>}</span>
      <span className="flex items-center gap-2 tabular-nums">
        <span className="text-slate-500">{x.age ?? '—'}</span>
        <span className={valColor(cur)}>{fmt(cur)}</span>
        <span className="text-sky-300/70 w-8 text-right">{fmt(pot)}</span>
        {lev !== 'MLB' && <span className="w-8 text-right text-[10px] text-slate-500 whitespace-nowrap" title={chance === null ? undefined : chanceTitle(chance, x.p)}>{chanceText(chance)}</span>}
      </span>
    </div>
  );
}

// A surplus player who didn't make any affiliate roster — a possible-cut row. Shows
// where he is in OOTP (LocChip), his best position / role, age, wOBA (hitters), cur→pot.
function CutRow({ x }) {
  const isP = x.isPitcher;
  const pos = isP ? (x.role || x.p['POS']) : (x.bestPos || x.p['POS']);
  return (
    <div className="flex items-center justify-between px-2 py-1 border-t border-slate-800/40 text-xs">
      <span className="text-slate-300 truncate flex items-center gap-1">{x.p['Name']} <LocChip p={x.p} cardLev={x.p['Lev']} /><span className="text-slate-600">{pos}</span></span>
      <span className="flex items-center gap-2 tabular-nums">
        <span className="text-slate-500">{x.age ?? '—'}</span>
        {!isP && <span className={`w-12 text-right ${wobaColor(x.woba)}`}>{fmtWoba(x.woba)}</span>}
        <span className={valColor(x.cur)}>{fmt(x.cur)}</span>
        <span className="text-sky-300/70 w-8 text-right">{fmt(x.pot)}</span>
      </span>
    </div>
  );
}

function HitterRow({ h, lev, bench }) {
  const eff = h.ceiling === 'MLB' ? 'AAA' : h.ceiling;
  const split = eff && LEVEL_RANK[eff] > LEVEL_RANK[lev];
  // Young = under 27 (turn-27 rule, DEV data, 2026-09-24; was 25).
  const prospect = h.age != null && h.age < 27 && h.pot != null && h.cur != null && h.pot > h.cur + 1;
  const slot = h.slot || 'BN';
  const pos = h.slotPos || h.bestPos || h.p['POS'];
  // Value at the position he's PLAYING on this card (user rule) — a bat slotted
  // at 2B shows his 2B WAA, not his best-position number. Bench/role rows with
  // no assigned position keep the best-position value.
  const cur = h.slotPos ? (pnum(h.p[`${h.slotPos} WAA wtd`]) ?? h.cur) : h.cur;
  const pot = h.slotPos ? (pnum(h.p[`${h.slotPos} WAA P`]) ?? h.pot) : h.pot;
  const chance = chanceRow(h, lev);
  return (
    <tr className={`border-t border-slate-800/50 hover:bg-slate-800/30 ${bench ? 'opacity-70' : ''}`}>
      <td className="px-2 py-1"><Badge cls={bench ? 'bg-slate-800/40 text-slate-500 border-slate-700/40' : 'bg-slate-700/40 text-slate-300 border-slate-600/40'}>{slot}</Badge></td>
      <td className="px-2 py-1 text-slate-200 whitespace-nowrap"><span className="inline-flex items-center gap-1.5">{h.p['Name']} <LocChip p={h.p} cardLev={lev} /></span></td>
      <td className="px-2 py-1 text-slate-500 text-center">{h.age ?? '—'}</td>
      <td className="px-2 py-1 text-slate-400 text-center">{pos}</td>
      <td className={`px-2 py-1 text-right tabular-nums ${wobaColor(h.woba)}`}>{fmtWoba(h.woba)}</td>
      <td className={`px-2 py-1 text-right tabular-nums ${valColor(cur)}`}>{fmt(cur)}</td>
      <td className="px-2 py-1 text-right tabular-nums text-sky-300/70">{fmt(pot)}</td>
      {lev !== 'MLB' && <td className="px-1 py-1 text-right tabular-nums text-[10px] text-slate-500 whitespace-nowrap" title={chance === null ? undefined : chanceTitle(chance, h.p)}>{chanceText(chance)}</td>}
      <td className="px-2 py-1">
        <div className="flex gap-1 items-center">
          <Tags p={h.p} cardLev={lev} />
          {prospect && <Badge cls="bg-sky-500/15 text-sky-400 border-sky-500/30">prospect</Badge>}
          {split && <Badge cls="bg-violet-500/15 text-violet-300 border-violet-500/30">split ↓ from {eff}</Badge>}
          {h._stretch && <Badge title="roster filler — stretched up to cover a bench spot (no real future, no harm)" cls="bg-amber-500/15 text-amber-300/80 border-amber-500/30">stretch ↑ {h.ceiling}</Badge>}
          {h._devDepth && <Badge title="roster depth — fills the roster beyond the core lineup + bench (young bats kept to develop, plus fillers to reach the roster cap)" cls="bg-sky-500/10 text-sky-300/70 border-sky-500/25">depth</Badge>}
          <TrainChip h={h} lev={lev} />
        </div>
      </td>
    </tr>
  );
}

function LevelCard({ lev, data }) {
  const c = data.counts;
  const empty = data.SP.length + data.RP.length + data.hitters.length + (data.bench?.length || 0) === 0;
  // Position players shown in OOTP order (display-only — assignment is unchanged).
  // Starters sort by their lineup slot (C, 1B, …, DH); bench sits below, by position.
  const starters = [...data.hitters].sort((a, b) => posRank(a.slot) - posRank(b.slot));
  const bench = [...(data.bench || [])].sort((a, b) => posRank(a.slotPos || a.bestPos) - posRank(b.slotPos || b.bestPos));
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <span className="text-base font-black text-white w-12">{lev}</span>
          {!empty && <span className="text-xs text-slate-500 tabular-nums">{c.SP} SP · {c.RP} RP · {c.hitters} bats{c.bench ? ` (${c.bench} bench)` : ''} · {c.LHP} LHP</span>}
        </div>
        <div className="flex gap-1.5 flex-wrap justify-end">
          {data.gaps.map((g, i) => <Badge key={i} cls="bg-rose-500/15 text-rose-400 border-rose-500/30" title="every fill path was tried: the org has no eligible 27+ body left for this slot; sign a minor-league filler">{g}: sign a filler</Badge>)}
        </div>
      </div>
      {empty ? <div className="px-4 py-3 text-xs text-slate-600 italic">No players reach this level</div> : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-0">
          {/* pitching */}
          <div className="lg:col-span-2 border-r border-slate-800/60">
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-600 flex items-center gap-1"><Zap size={11} /> Rotation</div>
            {data.SP.map((x, i) => <PitcherLine key={i} x={x} lev={lev} role="SP" />)}
            {lev !== 'WL' && lev !== 'INT' && data.SP.length < (lev === 'MLB' ? 5 : 6) &&
              <div className="px-2 py-1 text-[11px] text-rose-400/70">{data.SP.length}/{lev === 'MLB' ? 5 : 6} SP — sign {(lev === 'MLB' ? 5 : 6) - data.SP.length} filler starter{(lev === 'MLB' ? 5 : 6) - data.SP.length > 1 ? 's' : ''}</div>}
            <div className="px-2 py-1 mt-1 text-[10px] uppercase tracking-wider text-slate-600">Bullpen</div>
            {data.RP.map((x, i) => <PitcherLine key={i} x={x} lev={lev} role="RP" />)}
            {lev !== 'WL' && lev !== 'INT' && data.RP.length < 8 &&
              <div className="px-2 py-1 text-[11px] text-rose-400/70">{data.RP.length}/8 RP — sign {8 - data.RP.length} filler reliever{8 - data.RP.length > 1 ? 's' : ''}</div>}
          </div>
          {/* hitters */}
          <div className="lg:col-span-3">
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-600 flex items-center gap-1"><Users size={11} /> Lineup</div>
            <table className="w-full text-xs">
              <thead><tr className="text-[10px] uppercase tracking-wider text-slate-600">
                <th className="px-2 py-0.5 text-left font-medium">Slot</th><th className="px-2 py-0.5 text-left font-medium">Player</th>
                <th className="px-2 py-0.5 font-medium">Age</th><th className="px-2 py-0.5 font-medium">Pos</th>
                <th className="px-2 py-0.5 text-right font-medium">wOBA</th>
                <th className="px-2 py-0.5 text-right font-medium">Cur</th><th className="px-2 py-0.5 text-right font-medium">Pot</th>
                {lev !== 'MLB' && <th className="px-1 py-0.5 text-right font-medium" title="MLB %: chance his peak reaches -1 WAA (an MLB-level player) from where he is now, from the ML model (the DEV cell method when the ML file is missing or stale). 100% when he is already there. Hover a row for Starter % and Star % (the 0 and +1.5 bars). * = stand-in from Proj Potential.">MLB</th>}
                <th /></tr></thead>
              <tbody>
                {starters.map((h, i) => <HitterRow key={`s${i}`} h={h} lev={lev} />)}
                {bench.length > 0 && (
                  <tr><td colSpan={lev === 'MLB' ? 8 : 9} className="px-2 pt-2 pb-0.5 text-[9px] uppercase tracking-wider text-slate-600">Bench</td></tr>
                )}
                {bench.map((h, i) => <HitterRow key={`b${i}`} h={h} lev={lev} bench />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ title, icon, children }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
      <div className="flex items-center gap-1.5 mb-2">{icon}<h3 className="text-xs font-bold text-slate-300 uppercase tracking-wide">{title}</h3></div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export default function OrganizationPage({ hitters: hittersIn = [], pitchers: pitchersIn = [], metadata, league, parkMode = 'neutral' }) {
  // The Org Builder ALWAYS reads the NEUTRAL park basis. Farm placement is a
  // normalized development question — the kid plays in minor-league parks, not
  // Wrigley — and a knife-edge player must not change LEVELS when the MLB park
  // lens flips (James Barbera cleared the AA bar by 0.01 neutral and missed by
  // 0.01 on My Park). Park-lens MLB context lives on the Roster Optimizer and
  // Team Projections pages. When the app toggle is already Neutral the app's
  // own lists ARE the neutral files, so this hook loads nothing and the page
  // uses the lists it was given.
  const { data: neutralData } = usePlayerData(league, 'neutral', parkMode !== 'neutral');
  const hittersNeutral = neutralData.hitters.length ? neutralData.hitters : hittersIn;
  const pitchersNeutral = neutralData.pitchers.length ? neutralData.pitchers : pitchersIn;
  // Proj Potential on every row (user, 2026-09-24: the Org tab must use what
  // we actually project). usePlayersWithFV stamps _potentialWAA, the same
  // number the lists show, onto the NEUTRAL rows above (the park basis stays
  // neutral). It loads the measured curve itself and needs nothing else from
  // this page. orgBuilder.potentialValue reads _potentialWAA first.
  const hitters = usePlayersWithFV(hittersNeutral);
  const pitchers = usePlayersWithFV(pitchersNeutral);

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

  // Same platoon-weight basis as the Roster Optimizer + Team Projections, so
  // the MLB card is the SAME roster those screens show.
  const vrShare = metadata?.matchups?.['OVR vR'];

  // One source of truth: buildRosters places everyone AND derives the promote / buried /
  // pipeline summaries from that same placement, so the panels match the level cards.
  const rosters = useMemo(
    () => (org ? buildRosters(org, hitters, pitchers, { league, vrShare }) : null),
    [org, hitters, pitchers, league, vrShare]
  );

  // Same club set the standings rank against, so "8th of 28" means the same
  // thing on both screens (the pull's metadata.clubs, else LEAGUE_TEAMS).
  // Unmapped leagues pass null and fall back to any org carrying a real roster.
  const knownTeams = useMemo(
    () => resolveLeagueClubs(metadata, LEAGUE_TEAMS[league]).known,
    [metadata, league]
  );

  // Surplus who didn't make any roster — possible cuts, MOST cuttable first (lowest
  // youth-weighted keep value, so old no-ceiling fillers top the list and any young arm
  // sinks to the bottom).
  const cuts = useMemo(() => {
    if (!rosters?.depth) return { H: [], P: [] };
    // orgBuilder's keepCmp reversed, the same order the depth pass keeps
    // players in (prospects by chance first, then fillers by keep value;
    // 2026-09-25), so the cuts list and the rosters agree: most cuttable first.
    const byKeep = (a, b) => keepCmp(b, a);
    return {
      H: rosters.depth.filter((x) => !x.isPitcher).sort(byKeep),
      P: rosters.depth.filter((x) => x.isPitcher).sort(byKeep),
    };
  }, [rosters]);

  return (
    <div className="h-full overflow-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <Building2 className="text-blue-400" size={22} />
          <div>
            <h1 className="text-xl font-black text-white">Organization Builder</h1>
            <p className="text-xs text-slate-500">Cards = where each player <span className="text-slate-300">should</span> be · <span className="text-slate-400">@ lvl</span> = where he is <span className="text-slate-300">now</span> in OOTP · <span className="text-emerald-300">↑ lvl</span> promote · <span className="text-orange-300">prove it</span> = 18+ in complex · <span className="text-amber-300">★</span> captain — {league}</p>
            <p className="text-xs text-slate-500"><span className="text-amber-300">train C 45/50 · RF new</span> = positions he projects at 0 WAA or better at peak but has not mastered (position rating current/potential; new = never trained there, his tools carry it): set his training position in OOTP · shown for minors bats who are not fillers and MLB bats under 27 · hover a chip for the projected peak at each position</p>
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

      {rosters && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
            <SummaryCard title="Pipeline gaps" icon={<AlertTriangle size={14} className="text-rose-400" />}>
              {rosters.needs.length === 0 ? <span className="text-xs text-emerald-400/80">Every position group has a prospect</span>
                : rosters.needs.map((n, i) => <div key={i} className="text-xs text-slate-300">{n.msg}</div>)}
              <div className="mt-2 text-[11px] text-slate-500">prospects — C{rosters.pipeline.C || 0} IF{rosters.pipeline.IF || 0} OF{rosters.pipeline.OF || 0} SP{rosters.pipeline.SP || 0} RP{rosters.pipeline.RP || 0}</div>
            </SummaryCard>
            <SummaryCard title="Promote candidates" icon={<ArrowUpCircle size={14} className="text-emerald-400" />}>
              {rosters.promote.length === 0 ? <span className="text-xs text-slate-600">None flagged</span>
                : rosters.promote.slice(0, 6).map((r, i) => <div key={i} className="text-xs text-slate-300 flex justify-between"><span>{r.p['Name']} <span className="text-slate-600">({r.lev} → {r.placed})</span></span><span className={valColor(r.cur)}>{fmt(r.cur)}</span></div>)}
            </SummaryCard>
            <SummaryCard title="Overmatched (buried)" icon={<ArrowDownCircle size={14} className="text-rose-400" />}>
              {rosters.buried.length === 0 ? <span className="text-xs text-slate-600">None flagged</span>
                : rosters.buried.slice(0, 6).map((r, i) => <div key={i} className="text-xs text-slate-300 flex justify-between"><span>{r.p['Name']} <span className="text-slate-600">({r.lev} → {r.placed})</span></span><span className={valColor(r.cur)}>{fmt(r.cur)}</span></div>)}
            </SummaryCard>
          </div>

          <div className="mb-5">
            <PositionalStrengthCard
              hitters={hitters} pitchers={pitchers}
              league={league} knownTeams={knownTeams} team={org}
            />
          </div>

          <div className="space-y-3">
            {[...LEVELS].reverse()
              // hide the WL card entirely for a league with no Winter League
              // (BLM) — an empty phantom card is noise, not information
              .filter((lev) => {
                const d = rosters.levels[lev];
                if (lev !== 'WL' || !d) return true;
                return d.SP.length + d.RP.length + d.hitters.length + (d.bench?.length || 0) > 0;
              })
              .map((lev) => <LevelCard key={lev} lev={lev} data={rosters.levels[lev]} />)}
          </div>

          {(cuts.H.length > 0 || cuts.P.length > 0) && (
            <div className="mt-4 bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-900 border-b border-slate-800 flex items-center gap-2">
                <ArrowDownCircle size={15} className="text-rose-400" />
                <span className="text-sm font-black text-rose-300">Possible Cuts</span>
                <span className="text-xs text-slate-500">{cuts.H.length + cuts.P.length} surplus: rosters are filled, these didn't make one (most cuttable first: fillers, then prospects with the lowest MLB %)</span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-0">
                <div className="border-r border-slate-800/60">
                  <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-600 flex items-center gap-1"><Users size={11} /> Hitters ({cuts.H.length})</div>
                  {cuts.H.length ? cuts.H.map((x, i) => <CutRow key={i} x={x} />) : <div className="px-2 py-1 text-[11px] text-slate-600">none</div>}
                </div>
                <div>
                  <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-600 flex items-center gap-1"><Zap size={11} /> Pitchers ({cuts.P.length})</div>
                  {cuts.P.length ? cuts.P.map((x, i) => <CutRow key={i} x={x} />) : <div className="px-2 py-1 text-[11px] text-slate-600">none</div>}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

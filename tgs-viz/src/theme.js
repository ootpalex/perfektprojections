// Copied verbatim from ootp-dashboard design/redo:app/src/theme.js (the Night Scorecard source of truth, upstream); do not hand-edit here — re-copy, then regenerate tokens.css.
// ============================================================================
// THEME — "Night Scorecard", graphite ground (batch 0 of the redesign,
// see app/docs/redesign/MIGRATION_PLAN.md). Every hex below traces to the
// graphite token block of the approved mockup (docs/redesign/mockup/night-scorecard.html) or to a colour-mix rule taken from that mockup; derived
// values say which rule in a trailing comment. Mixes are computed in OKLab to
// match the mockup's `color-mix(in oklab, …)` exactly (verified: zebra, tier
// 65 / 40+, z-heat 5…100 %, accent-bg 14 % / 8 % all reproduce the report).
//
// Contrast tables: docs/redesign/CHECKS.md (regenerate with docs/redesign/contrast.mjs).
// tokens.css is GENERATED from this file: node docs/redesign/gen-tokens-css.mjs > src/tokens.css
//
// ─── BREAKING CHANGES (vs the pre-redesign theme.js, commit 218dd86) ────────────────────────────────
//  1. FV_TIER_COLORS[tier] is now an object { bg, text }, not a hex string.
//     Call sites that concatenate or pass it as a colour break:
//       components/ProspectsView.jsx:239   `${FV_TIER_COLORS[id]}22` → "[object Object]22"
//       components/ProspectsView.jsx:334   same pattern
//       components/ProspectsView.jsx:376   same pattern
//       components/ProspectsView.jsx:494   `color: FV_TIER_COLORS[id]`
//       components/ProspectsView.jsx:524   Recharts `<Bar fill={FV_TIER_COLORS[id]}>`
//       components/ProspectsView.jsx:534   legend swatch `background: FV_TIER_COLORS[id]`
//     Fix: use tierChip(id) → { bg, text, border } (filled pill, ink text), or
//     FV_TIER_COLORS[id].bg where a plain hex is needed (Recharts fill, swatch).
//  2. zToColor(z).value / .label flip to ink (#141516) at |z| ≥ 2.0 because the
//     heat fill is light there; they are only readable ON zToColor(z).bg.
//       views/Org/PositionalStrengthTable.jsx:83   paints c.value / c.label on the
//         row ground (not on c.bg) → ink-on-panel is invisible for |z| ≥ 2.0.
//         Migrate the score/rank cells to filled heat cells (mockup `td.num[data-z]`)
//         or read zHeat(z).bar for text-on-panel.
//       views/Org/FortyManSubTab.jsx:113            text sits on colors.bg → OK as is.
//     Also: zToColor(null).bg is now an opaque panel hex (was a translucent rgba).
//  3. levelColor() as plain text compresses the ladder: the mockup encodes levels
//     as FILLED chips (MLB brightest → R darkest); below AA the fill is too dark
//     to be text on the panel (A+ 2.6:1), so levelColor returns the AA grey for
//     A+/A/R. Ordering MLB > AAA > AA is kept; A+/A/R read identically. These
//     12 text call sites keep working but lose three rungs — migrate to levelChip():
//       components/ProspectsView.jsx:347 · components/PlayerCompareView.jsx:40 ·
//       components/ScoutView.jsx:178,211 · components/Rule5Board.jsx:133 ·
//       components/WaiverWireView.jsx:93 · views/Org/OverviewSubTab.jsx:64 ·
//       views/Org/PositionalStrengthTable.jsx:114 · views/Org/FortyManSubTab.jsx:141 ·
//       components/PlayersView.jsx:156 · views/PlayerProfile/PlayerProfileModal.jsx:72
//  4. gradeStyle / warStyle / waaStyle now ALWAYS return a fontWeight (the
//     20/30→700 · 40–55→500 · 60→600 · 70→700 · 80→800 rule). Previously the
//     middle band returned no weight, so a caller's fontWeight written BEFORE the
//     spread survived; it is now overridden by 500 at these four sites:
//       views/PlayerProfile/PitchingTab.jsx:195 (700) · views/Org/FortyManSubTab.jsx:147 (700)
//       views/PlayerProfile/FieldingTab.jsx:248 (600) · views/PlayerProfile/FieldingTab.jsx:251 (800)
//     (17 other sites put fontWeight AFTER the spread — the caller still wins.)
//  5. S.th is no longer uppercase / letter-spaced and is Archivo Narrow 12px
//     600 on the panel-2 strip; S.td is cream `text` (was slate-400) on a
//     29px row; S.table is border-collapse:separate (mockup). No call site
//     overrides textTransform on S.th (0 found); callers that set their own
//     `border` on <td>/<tr> expecting collapsed borders should be eyeballed.
//  6. S.pillBtn: radius 20 → 3, Archivo Narrow, panel fill. The 35 call sites
//     that override borderColor/color with old slate/blue hexes still work but
//     keep the old colours until migrated (shared.jsx:65 PillBtn hardcodes
//     rgba(96,165,250,.2) / #93c5fd / #3b82f6 / #1e293b — migrate to
//     accentBg / accent / line2).
//  7. Fonts: Archivo + Archivo Narrow replace system-ui / JetBrains Mono.
//     index.html needs the Google Fonts <link> (see tokens.css header) or the
//     stacks fall back to Helvetica Neue / Arial / Arial Narrow.
//  NOT breaking, but note: gradeToColor returns a hex (was `rgb(r,g,b)`) — still
//  a string; no call site parses it. devPctColor / scoutingRatingColor bands
//  change (70/55/45/30 and 65/55/45/35 → ramp stops); pre-existing bug:
//  views/RosterPlanner/CompactPlayerRow.jsx:96 passes a 0–100 integer into
//  devPctColor (which expects 0–1), so it always hits the top band — unchanged here.
// ============================================================================

// ─── colour math (OKLab, to match the mockup's color-mix(in oklab, …)) ──────
const _clamp01 = (x) => Math.min(1, Math.max(0, x));
export const hexToRgb = (h) => { const s = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16) / 255); };
export const rgbToHex = (rgb) => "#" + rgb.map((c) => Math.round(_clamp01(c) * 255).toString(16).padStart(2, "0")).join("");
const _lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const _srgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
const _rgbToOklab = ([r, g, b]) => {
  const R = _lin(r), G = _lin(g), B = _lin(b);
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
};
const _oklabToRgb = ([L, a, b]) => {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [_srgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
          _srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
          _srgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)];
};
// mixOklab(A, p, B) === CSS `color-mix(in oklab, A p%, B)`; p in 0..1. Returns a hex.
export const mixOklab = (A, p, B) => {
  const a = _rgbToOklab(hexToRgb(A)), b = _rgbToOklab(hexToRgb(B));
  return rgbToHex(_oklabToRgb(a.map((v, i) => v * p + b[i] * (1 - p))));
};
// WCAG 2.x relative luminance + contrast ratio (used by CHECKS; exported for tests).
export const relLuminance = (h) => { const [r, g, b] = hexToRgb(h).map(_lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
export const contrastRatio = (a, b) => { const x = relLuminance(a), y = relLuminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

// ─── TOKENS ─────────────────────────────────────────────────────────────────
export const TOKENS = {
  // ground
  bg: "#141516",            // the desk
  bg2: "#111213",           // deeper desk (input wells sit on bg, scrims on bg2)
  panel: "#1b1c1e",         // card stock — every scorecard box
  panel2: "#212225",        // header strips, toolbars, th
  panel3: "#27292c",        // hover / pressed
  zebra: "#1e1f22",         // = mix(oklab, panel2 55%, panel) — the mockup's even-row stripe
  // ink
  text: "#ebe6da",          // cream ink (13.7:1 on panel)
  text2: "#b6b1a5",         // secondary (8.0:1)
  text3: "#8c887f",         // muted — labels, captions (4.8:1 on panel, 4.5:1 on panel2)
  textDisabled: "#67635b",  // disabled / "—" / placeholders only (2.9:1 — decorative)
  // rules
  line: "#303236",          // light hairline (row separators)
  line2: "#44474c",         // box rule (box borders, th bottom, column-group rules)
  lineInk: "#ebe6da",       // the h1 rule and hover borders (= text)
  // the one red pencil
  accent: "#e6655a",
  accentHover: "#ee7b70",
  accentText: "#141516",    // ink on the pencil (= bg)
  accentBg: "#352727",      // selected / NEED-row hover = mix(oklab, accent 14%, panel)
  accentBg2: "#2a2223",     // NEED-row tint          = mix(oklab, accent 8%, panel)
  accentBg2Even: "#282223", // NEED row on a zebra stripe = mix(oklab, accentBg2 80%, panel2) (mockup `.board tr[data-need]:nth-child(even)`)
  // semantic
  good: "#47a46e",          // = grade 50 stop
  goodSoft: "#3ea891",      // = grade 55 stop
  goodBg: "#212825",        // = mix(oklab, good 10%, panel)  (brief: good at 10% over panel)
  bad: "#e6655a",           // = accent
  badSoft: "#f98b80",       // = grade 20 stop
  badBg: "#2a2223",         // = accentBg2
  warn: "#c9a23a",
  warnBg: "#2a2823",        // = mix(oklab, warn 10%, panel)  (brief: warn at 10%)
  focus: "#82a7e0",         // desaturated blue ring, 6.9:1 on panel
  focusRing: "rgba(130,167,224,0.26)", // mockup: color-mix(in oklab, focus 26%, transparent), as an rgba for inline `boxShadow: 0 0 0 2px`
  scrim: "rgba(0,0,0,0.6)", // modal scrim (kept from the current app per the brief)
  // charts (Recharts needs literal colours)
  CHART: {
    series1: "#80acf0",     // = grade 70 blue — "Current"
    series2: "#47a46e",     // = grade 50 green — "Potential"
    series3: "#e6655a",     // = accent
    series4: "#c9a23a",     // = warn
    series5: "#b8a2f2",     // = position C violet
    series6: "#cfae92",     // = position RP tan
    grid: "#303236",        // = line
    axis: "#8c887f",        // = text3
    refLine: "#b6b1a5",     // reference / median lines = text2
    tooltipBg: "#212225",   // = panel2
    tooltipBorder: "#44474c", // = line2
    tooltipText: "#ebe6da", // = text
    // band fills = series mixed over panel at 18% (outer) / 35% (inner), OKLab
    bands: {
      series1: { outer: "#2c333f", inner: "#3c4a60" },
      series2: { outer: "#25322c", inner: "#2d4839" },
      series3: { outer: "#3c2a29", inner: "#5c3633" },
      series4: { outer: "#363227", inner: "#52472e" },
      series5: { outer: "#33313f", inner: "#4c4760" },
      series6: { outer: "#373331", inner: "#544a44" },
    },
  },
  fonts: {
    ui: '"Archivo", "Helvetica Neue", Arial, sans-serif',                       // body, numerals (tabular-nums)
    narrow: '"Archivo Narrow", "Arial Narrow", "Helvetica Neue", Arial, sans-serif', // headers, chips, nav, buttons, pagination
  },
  radius: 3,                // everywhere
  radiusPill: 10,           // FV tier pills only
  fontSize: 13,             // body
};
const T = TOKENS;
export const FONT_UI = T.fonts.ui;
export const FONT_NARROW = T.fonts.narrow;

// ─── ENCODINGS ──────────────────────────────────────────────────────────────
// 20–80 grade ramp as stat text. Ordered by luminance AND weight: ends brightest,
// 80 brightest of all, 45 dimmest. Every stop ≥ 5.1:1 on panel and zebra (CHECKS.md).
export const GRADE = {
  20: "#f98b80", 30: "#e08e52", 40: "#b38f34", 45: "#8d953e", 50: "#47a46e",
  55: "#3ea891", 60: "#49aac4", 70: "#80acf0", 80: "#bccdff",
};
const GRADE_STOPS = [20, 30, 40, 45, 50, 55, 60, 70, 80];
// Weight rule: 20/30 → 700, 40–55 → 500, 60 → 600, 70 → 700, 80 → 800.
export const GRADE_WEIGHT = { 20: 700, 30: 700, 40: 500, 45: 500, 50: 500, 55: 500, 60: 600, 70: 700, 80: 800 };

// FV tier pills — filled, 10px radius, ink text. 65 and 40+ are the mockup's
// mixes: 65 = mix(oklab, g70 50%, g60); 40+ = mix(oklab, g40 45%, g30).
export const FV_TIER_COLORS = {
  "80": { bg: GRADE[80], text: T.accentText },
  "70": { bg: GRADE[70], text: T.accentText },
  "65": { bg: "#67abda", text: T.accentText },
  "60": { bg: GRADE[60], text: T.accentText },
  "55": { bg: GRADE[55], text: T.accentText },
  "50": { bg: GRADE[50], text: T.accentText },
  "45+": { bg: GRADE[45], text: T.accentText },
  "45": { bg: GRADE[40], text: T.accentText },
  "40+": { bg: "#cc8f45", text: T.accentText },
  "40": { bg: GRADE[30], text: T.accentText },
  "35+": { bg: GRADE[20], text: T.accentText },
};

// Positions — text colour (bold Archivo Narrow in table cells) and chip
// { bg, text, border }: border = the hue, fill = mix(oklab, hue 10%, panel).
export const POS = {
  C:    { text: "#b8a2f2", chip: "#282830" },
  "1B": { text: "#f09485", chip: "#2d2727" },
  "2B": { text: "#dfb04c", chip: "#2b2924" },
  "3B": { text: "#b9c45c", chip: "#282a25" },
  SS:   { text: "#6ecf95", chip: "#232b29" },
  LF:   { text: "#5fcbc1", chip: "#232b2c" },
  CF:   { text: "#6fb6f0", chip: "#232930" },
  RF:   { text: "#98abf5", chip: "#262830" },
  DH:   { text: "#a9a59c", chip: "#272829" },
  SP:   { text: "#ebe6da", chip: "#2c2d2e" }, // = text
  RP:   { text: "#cfae92", chip: "#2a2928" },
};

// Levels — a filled luminance ladder (MLB brightest → R darkest), every chip
// ringed line2 so R stays visible; INT is an outlined dashed chip.
// `text` = chip ink; `plain` = the colour levelColor() returns for plain text on
// the panel (see BREAKING #3: the ladder compresses below AA there).
export const LEVEL = {
  MLB:  { bg: "#ebe6da", text: T.accentText, ring: T.line2, plain: "#ebe6da" },
  AAA:  { bg: "#bdb8ad", text: T.accentText, ring: T.line2, plain: "#bdb8ad" },
  AA:   { bg: "#8d8a82", text: T.accentText, ring: T.line2, plain: "#8d8a82" },
  "A+": { bg: "#5f5d57", text: T.text,       ring: T.line2, plain: "#8d8a82" }, // fill 2.6:1 as text → clamped to the AA grey (4.95:1)
  A:    { bg: "#45443f", text: T.text,       ring: T.line2, plain: "#8d8a82" }, // same clamp
  R:    { bg: "#323130", text: T.text,       ring: T.line2, plain: "#8d8a82" }, // same clamp
  INT:  { bg: "transparent", text: "#dfb04c", ring: "#dfb04c", dashed: true, plain: "#dfb04c" },
};

// Injury proneness (ends bold, as in the mockup).
export const PRONE = {
  "Iron Man": { color: GRADE[80], weight: 700 },
  Durable:    { color: GRADE[55], weight: 600 },
  Normal:     { color: T.text2,   weight: 400 },
  Fragile:    { color: GRADE[30], weight: 600 },
  Wrecked:    { color: GRADE[20], weight: 700 },
};

// Dev percentile bands (mockup `[data-dev]`): ≥70 → 70 stop · 55–69 → 55 · 45–54 → text2 · 30–44 → 40 · <30 → 30.
export const DEV_BANDS = [
  [70, GRADE[70], 700], [55, GRADE[55], 600], [45, T.text2, 400], [30, GRADE[40], 500], [-Infinity, GRADE[30], 700],
];

// z-heat: fill = mix(oklab, Z |z|/2.5, panel); Z = zneg (weak) / zpos (strong).
// Text is cream up to 79% and flips to ink (= bg) at ≥ 80%. Endpoints also draw the bars.
export const ZHEAT = { neg: "#e86c5f", pos: "#6193de", mid: T.panel, flipAt: 0.8, span: 2.5 };

// ─── helpers (string API kept; new chip helpers return objects) ─────────────
export const posColor = (pos) => (POS[pos] ? POS[pos].text : T.text2);
export const posChip = (pos) => { const p = POS[pos]; return p ? { bg: p.chip, text: p.text, border: p.text } : { bg: T.panel, text: T.text2, border: T.line2 }; };

export const levelColor = (lev) => (LEVEL[lev] ? LEVEL[lev].plain : T.textDisabled);
export const levelChip = (lev) => {
  const l = LEVEL[lev];
  if (!l) return { bg: T.panel, text: T.text2, border: T.line2 };
  return { bg: l.bg, text: l.text, border: l.ring, ...(l.dashed ? { borderStyle: "dashed" } : {}) };
};

export const tierChip = (tier) => { const t = FV_TIER_COLORS[tier]; return t ? { bg: t.bg, text: t.text, border: t.bg } : { bg: T.panel, text: T.text2, border: T.line2 }; };

export const proneColor = (p) => (PRONE[p] ? PRONE[p].color : T.text2);

// Signability — derived: good / goodSoft / text2 / warn / the 30-orange / bad.
export const signColor = (s) => ({ "Very Easy": T.good, Easy: T.goodSoft, Normal: T.text2, Hard: T.warn, "Extremely Hard": GRADE[30], Impossible: T.bad })[s] || T.text3;
export const signShort = (s) => ({ "Very Easy": "V.Easy", Easy: "Easy", Normal: "Normal", Hard: "Hard", "Extremely Hard": "Ext.Hard", Impossible: "Impos." })[s] || s;

// Continuous grade → hex: OKLab interpolation between adjacent ramp stops (so
// gradeToColor(65) === the tier-65 mix #67abda, and the ramp stays the mockup's
// U-shaped luminance curve between stops). Clamped to 20..80. Returns a hex.
export function gradeToColor(grade) {
  const g = Math.max(20, Math.min(80, Number(grade)));
  if (!Number.isFinite(g)) return T.textDisabled;
  for (let i = 0; i < GRADE_STOPS.length - 1; i++) {
    const g0 = GRADE_STOPS[i], g1 = GRADE_STOPS[i + 1];
    if (g <= g1) {
      if (g === g0) return GRADE[g0];
      if (g === g1) return GRADE[g1];
      return mixOklab(GRADE[g1], (g - g0) / (g1 - g0), GRADE[g0]);
    }
  }
  return GRADE[80];
}
// Weight of the nearest stop (ties round up: 65 → the 70 weight).
export function gradeWeight(grade) {
  const g = Math.max(20, Math.min(80, Number(grade)));
  let best = GRADE_STOPS[0];
  for (const s of GRADE_STOPS) if (Math.abs(s - g) <= Math.abs(best - g)) best = s;
  return GRADE_WEIGHT[best];
}

// WAA / WAR → 20–80 grade → colour + weight. Calibration unchanged from theme.js.
const WAA_MEAN = -0.25;
const WAA_STD = 1.49;
const WAR_MEAN_DEFAULT = 1.61;
const WAR_STD_DEFAULT = 1.88;
let _warMean = WAR_MEAN_DEFAULT;
let _warStd = WAR_STD_DEFAULT;
export function setWarCalibration(warColor) {
  const mean = warColor == null ? NaN : Number(warColor.mean);
  const std = warColor == null ? NaN : Number(warColor.std);
  _warMean = Number.isFinite(mean) ? mean : WAR_MEAN_DEFAULT;
  _warStd = Number.isFinite(std) && std > 0 ? std : WAR_STD_DEFAULT;
}
export const gradeStyle = (grade) => {
  if (grade == null || isNaN(grade)) return { color: T.textDisabled };
  return { color: gradeToColor(grade), fontWeight: gradeWeight(grade) };
};
export const waaStyle = (v) => (v == null || isNaN(v)) ? { color: T.textDisabled } : gradeStyle(50 + 10 * (v - WAA_MEAN) / WAA_STD);
export const warStyle = (v) => (v == null || isNaN(v)) ? { color: T.textDisabled } : gradeStyle(50 + 10 * (v - _warMean) / _warStd);

// Intangibles H / L / other → good / bad / muted.
export const intangibleColor = (v) => (v === "H" ? T.good : v === "L" ? T.bad : T.text3);

// Dev percentile (0..1) → text colour per DEV_BANDS.
export const devPctColor = (pct) => {
  if (pct == null || isNaN(pct)) return T.text3;
  const p = pct * 100;
  for (const [min, color] of DEV_BANDS) if (p >= min) return color;
  return GRADE[30];
};
export const devPctStyle = (pct) => {
  if (pct == null || isNaN(pct)) return { color: T.text3 };
  const p = pct * 100;
  for (const [min, color, weight] of DEV_BANDS) if (p >= min) return { color, fontWeight: weight };
  return { color: GRADE[30], fontWeight: 700 };
};

// Scouting 20–80 ratings (ceiling/floor/batting/pitching) — same five-band shape
// as the dev% rule, on the old 65/55/45/35 thresholds: ≥65 → 70 stop · 55–64 → 55 · 45–54 → text2 · 35–44 → 40 · <35 → 30.
export const scoutingRatingColor = (v) => {
  if (v == null || isNaN(v)) return T.text3;
  if (v >= 65) return GRADE[70];
  if (v >= 55) return GRADE[55];
  if (v >= 45) return T.text2;
  if (v >= 35) return GRADE[40];
  return GRADE[30];
};

// z-heat → { bg, text, bar }. bg is computed in OKLab (matches color-mix(in oklab)).
// Reference stops (mix = |z|/2.5): −2.5 #e86c5f · −2.0 #bb5c52 · −1.8 #aa564d · −1.0 #673c38
// · 0 #1b1c1e · +1.0 #364864 · +1.8 #4d6fa3 · +2.0 #5279b3 · +2.5 #6193de (see CHECKS.md).
export const zHeat = (z) => {
  if (z == null || isNaN(z)) return { bg: T.panel, text: T.text3, bar: T.line2 };
  const c = Math.max(-ZHEAT.span, Math.min(ZHEAT.span, z));
  const mix = Math.abs(c) / ZHEAT.span;
  const end = c < 0 ? ZHEAT.neg : ZHEAT.pos;
  return { bg: mix === 0 ? ZHEAT.mid : mixOklab(end, mix, ZHEAT.mid), text: mix >= ZHEAT.flipAt ? T.bg : T.text, bar: end };
};
// Legacy shape { bg, value, label, border } for the two existing call sites.
// value = heat text; label = secondary text on the heat fill (text2 while the
// fill is dark, then follows the flip); border = the bar / endpoint colour.
export const zToColor = (z) => {
  const h = zHeat(z);
  if (z == null || isNaN(z)) return { bg: h.bg, value: T.text2, label: T.text3, border: T.line2 };
  const mix = Math.min(Math.abs(z), ZHEAT.span) / ZHEAT.span;
  return { bg: h.bg, value: h.text, label: mix >= 0.4 ? h.text : T.text2, border: h.bar };
};

// ─── shared inline styles ───────────────────────────────────────────────────
const R = T.radius;
export const S = {
  // loader (first paint)
  loaderContainer: { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: T.bg, color: T.text, fontFamily: T.fonts.ui },
  loaderCard: { background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R, padding: 40, display: "flex", flexDirection: "column", alignItems: "center", gap: 24, width: 420 },
  dropZone: { border: `1.5px dashed ${T.line2}`, borderRadius: R, padding: "16px 20px", display: "flex", flexDirection: "column", alignItems: "center", cursor: "pointer", background: T.bg, transition: "border-color 0.15s" },
  loadBtn: { width: "100%", padding: "10px 20px", background: T.accent, border: `1px solid ${T.accent}`, borderRadius: R, color: T.accentText, fontSize: 14, fontWeight: 700, fontFamily: T.fonts.narrow, cursor: "pointer", transition: "background 0.15s" },
  errorBox: { background: T.badBg, border: `1px solid ${T.bad}`, borderRadius: R, padding: "8px 12px", color: T.badSoft, fontSize: 12, width: "100%" },
  // scorecard box (Section). Header strip + body are new keys; `section` keeps
  // its padding so existing Section children still sit inside a padded box.
  section: { background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R, padding: 16 },
  sectionTitle: { fontFamily: T.fonts.narrow, fontSize: 13.5, fontWeight: 700, letterSpacing: "0.01em", color: T.text, margin: 0 },
  box: { background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R },                                   // NEW: unpadded scorecard box
  boxHead: { borderTopLeftRadius: 2, borderTopRightRadius: 2, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, minHeight: 34, padding: "7px 12px", background: T.panel2, borderBottom: `1px solid ${T.line2}`, fontFamily: T.fonts.narrow, fontSize: 13.5, fontWeight: 700, letterSpacing: "0.01em", color: T.text }, // NEW: header strip
  boxHeadRight: { marginLeft: "auto", fontFamily: T.fonts.narrow, fontWeight: 500, fontSize: 12, color: T.text3 },                         // NEW
  boxSub: { color: T.text2, fontSize: 12.5, padding: "10px 12px 0" },                                                                     // NEW
  boxFoot: { fontFamily: T.fonts.narrow, fontSize: 12, color: T.text3, padding: "7px 12px 8px", borderTop: `1px solid ${T.line}` },      // NEW
  toolbar: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "8px 12px", background: T.panel2, borderBottom: `1px solid ${T.line2}` }, // NEW: filter row inside the header strip
  // positional-strength grid (kept)
  strengthGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(105px, 1fr))", gap: 8 },
  strengthCard: { borderRadius: R, padding: "12px 10px", textAlign: "center", border: `1px solid ${T.line2}`, background: T.panel },
  // buttons
  pillBtn: { padding: "4px 10px", borderRadius: R, border: "1px solid", borderColor: T.line2, fontSize: 12.5, fontWeight: 600, fontFamily: T.fonts.narrow, lineHeight: 1.2, cursor: "pointer", transition: "border-color 0.12s, background 0.12s", background: T.panel, color: T.text },
  pillBtnActive: { background: T.accentBg, borderColor: T.accent, color: T.text },                                                        // NEW: spread after pillBtn when active
  btn: { fontFamily: T.fonts.narrow, fontWeight: 600, fontSize: 13, borderRadius: R, padding: "6px 12px", lineHeight: 1.2, border: `1px solid ${T.line2}`, background: T.panel, color: T.text, cursor: "pointer" }, // NEW
  btnPrimary: { background: T.accent, borderColor: T.accent, color: T.accentText },                                                       // NEW: spread after btn
  pageBtn: { padding: "4px 10px", background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R, color: T.text, fontSize: 12.5, fontWeight: 600, fontFamily: T.fonts.narrow, cursor: "pointer" },
  // tables
  tableWrap: { overflowX: "auto", borderRadius: R, border: `1px solid ${T.line2}`, background: T.panel },
  table: { width: "100%", borderCollapse: "separate", borderSpacing: 0, fontSize: 12.5 },
  th: { padding: "6px 6px", textAlign: "left", fontFamily: T.fonts.narrow, fontSize: 12, fontWeight: 600, color: T.text2, borderBottom: `1px solid ${T.line2}`, background: T.panel2, whiteSpace: "nowrap", position: "sticky", top: 0, zIndex: 2 },
  thSorted: { color: T.text, boxShadow: `inset 0 -2px 0 ${T.accent}` },                                                                  // NEW: the red-pencil sort underline (inset, not a drop shadow)
  td: { padding: "0 6px", height: 29, color: T.text, whiteSpace: "nowrap", fontSize: 12.5, borderBottom: `1px solid ${T.line}`, fontVariantNumeric: "tabular-nums" },
  tdName: { fontWeight: 600, color: T.text },                                                                                             // NEW
  groupRule: { borderLeft: `1px solid ${T.line2}` },                                                                                      // NEW: column-group rule (first cell of a group)
  zebraRow: { background: T.zebra },                                                                                                      // NEW
  needRow: { background: T.accentBg2 },                                                                                                   // NEW
  needTag: { fontStyle: "normal", fontFamily: T.fonts.narrow, fontWeight: 700, fontSize: 11, letterSpacing: "0.03em", color: T.accent, border: `1px solid ${T.accent}`, borderRadius: 2, padding: "0 3px", lineHeight: "13px", display: "inline-block", verticalAlign: 1, marginLeft: 3 }, // NEW
  // inputs — sunken wells (bg) with a line2 border; selects are raised panel controls
  searchInput: { background: T.bg, border: `1px solid ${T.line2}`, borderRadius: R, color: T.text, padding: "5px 8px", fontSize: 12.5, fontFamily: "inherit", lineHeight: 1.2, height: 28, outline: "none", width: 190 },
  filterSelect: { background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R, color: T.text, padding: "5px 8px", fontSize: 13, fontFamily: T.fonts.narrow, fontWeight: 600, lineHeight: 1.2, height: 28, outline: "none", cursor: "pointer" },
  // chips
  badge: { display: "inline-block", fontFamily: T.fonts.narrow, fontWeight: 700, fontSize: 12, lineHeight: "17px", padding: "0 6px", borderRadius: R, border: "1px solid", minWidth: 26, textAlign: "center" }, // NEW: spread posChip/levelChip {bg,text,border} after it
  tierPill: { display: "inline-block", fontFamily: T.fonts.narrow, fontWeight: 700, fontSize: 12, lineHeight: "18px", minWidth: 30, padding: "0 6px", borderRadius: T.radiusPill, textAlign: "center" },         // NEW: spread tierChip after it
  zCell: { fontWeight: 600, textAlign: "right", fontVariantNumeric: "tabular-nums" },                                                     // NEW: spread zHeat {bg,text} as background/color
};

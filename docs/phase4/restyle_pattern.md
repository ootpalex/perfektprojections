# Phase 4 restyle pattern: his pages → Night Scorecard

This is the recipe every later page sweep copies. It was set on the shared table
(`PlayerTable.jsx`), the detail drawer (`PlayerDetail.jsx`), `PositionalStrength.jsx`,
`HittersPage.jsx` / `PitchersPage.jsx`, and the colour ladders in `lib/columns.js`.

The reference look is ootp-dashboard `app/docs/redesign/mockup/night-scorecard.html`.
The rules a page must pass are in `app/docs/redesign/CHECKS.md`.
The token values come from `app/src/theme.js` and reach this app as `tgs-viz/src/tokens.css`.

## Rules

1. **Change classes and markup only.** Hooks, props, state, data flow and every number
   stay byte-identical. Adding a presentational prop (`title`) or a presentational
   derivation (`groupStarts`) is fine. Changing a computation is not.
2. **Keep every threshold.** A colour ladder keeps its band edges. Only the class each
   band paints changes. `tests/client/cellColors.test.mjs` pins the edges for the main
   ladders. A one-off check compared every band of all 224 columns against the
   pre-restyle file. Each band still maps one-to-one to a class.
3. **Use no hex, no Tailwind palette class, no lucide icon.** Use the `ns-*` classes
   below, or a Tailwind arbitrary value bound to a token (`bg-[var(--panel)]`). Neutral
   Tailwind layout utilities (`flex`, `gap-*`, `p-*`, `w-*`, `text-[13px]`, `font-bold`,
   `tabular-nums`) are fine.
4. **Drop these from his visual language:**
   - `rounded-lg`, `rounded-xl` and `rounded-full`
   - `uppercase` and `tracking-wider` on labels
   - `shadow-*` and `backdrop-blur`
   - gradients
   - `font-mono` (it is Archivo now, so it does nothing)
   - text below 11px (`text-[9px]` and `text-[10px]` become `text-[11px]`)
5. **Recharts takes token strings.** Use `stroke="var(--chart-grid)"`,
   `fill="var(--zpos)"`, `tick={{ fill: 'var(--chart-axis)' }}`, and so on. CSS
   variables resolve in SVG attributes. This was confirmed on the drawer's line chart,
   whose computed stroke is `--chart-series-1`.

All `ns-*` classes live in `tgs-viz/src/index.css`, inside `@layer components`. They are
built only from token variables. Because they sit in a layer, a Tailwind utility on the
same element still wins. That is how `ns-box overflow-auto` overrides the box's
`overflow: hidden`.

## Class catalogue

| Class | What it is (mockup source) |
| --- | --- |
| `ns-page` | Page wrapper: full-height flex column with the 18/24px content padding. |
| `ns-page-head` + `h1` | Page header: 28px/800 title and a 2px cream rule (`.page-head`). |
| `ns-page-sub` (+ `b`) | Muted line under the title (`.page-sub`). |
| `ns-head-actions` | Right-hand cluster in the page head. |
| `ns-box` | Scorecard box: panel ground, line-2 border, 3px radius, no padding (`.panel`). |
| `ns-strip` | Header strip on the panel-2 ground, 13.5px/700 Archivo Narrow (`.panel > h2`). Put it on the heading itself (`<h3 className="ns-strip">`) or on a row that contains an `h2`/`h3`. |
| `ns-count` / `ns-strip-right` | Muted count after the title, and the right-aligned state text in the strip. |
| `ns-box-body` / `ns-sub` / `ns-foot` | Box padding, the sub line, and the footer note (`.panel-sub`, `.panel-foot`). |
| `ns-card` | A box that carries its own body padding, with a first-child `.ns-strip` that bleeds to the edges. Turns his `<div card><h3>…</h3>rows</div>` into a scorecard box by swapping two classes. |
| `ns-desk` | `--bg` ground behind boxes inside a modal or drawer. |
| `ns-toolbar` | Filter or control row under the strip (`.toolbar`). |
| `ns-label` / `ns-subhead` | Control label (narrow 12.5px/600, text-2), and an in-box subheading (narrow 12px/600, text-3). |
| `ns-rule-t` | 1px line-rule on top (replaces `border-t border-slate-700/50`). |
| `ns-scrim` | Modal scrim (`--scrim`). It replaces `bg-black/60 backdrop-blur-sm`. |
| `ns-btn`, `ns-btn-sm`, `ns-btn-primary` | Buttons (`.btn`, `.btn.primary`). |
| `ns-btn[aria-pressed]` | Toggle button. Off is a raised panel with a text-2 label. On has the accent-bg fill, the pencil border and a cream label. Always set `aria-pressed={bool}`. |
| `ns-link` | Text-only action ("reset"). |
| `ns-icon-btn` | 28px square button for a close mark (inline SVG). |
| `ns-input` | Text or number field as a sunken well on `--bg`, with a focus ring. |
| `ns-select` | Raised select with a caret drawn by two token-coloured gradients, so no icon. |
| `ns-search` (wrapper) + `svg` + `.ns-input` + `.ns-clear` | Search field with an inline stroke-SVG glass and a × clear button. |
| `data-table` | His sortable table, re-skinned: Archivo Narrow header, zebra rows, panel-3 hover, `th.sorted` red-pencil underline, `col-group-start` rule, `col-name`, `col-sticky`, `col-hide` ×. |
| `ns-table` | The same grammar for non-sortable tables, with `.num` right-aligned, `col-group-start` and `tr.selected`. |
| `ns-chip[data-pos="1B"]` | Position badge: the hue on a 10% tint of itself. `CL` reads as `RP`. |
| `ns-chip[data-lvl=<levelKey(lev)>]` | Level badge on the filled luminance ladder. `levelKey()` in `columns.js` maps R+ and R- to R, and A- to A. FA and AMA get no chip. |
| `ns-tier[data-tier="55"]` | FV tier pill: filled, ink text, 10px radius. |
| `ns-need` | Outlined NEED tag in the red pencil. |
| `ns-rchip` + a grade class | 20-80 rating chip: the grade colour on a 10% tint (`is-empty` when there is no value). |
| `ns-alert-bad` / `ns-alert-warn` | Callout box (bad-bg or warn-bg). |
| `ns-g20`, `ns-g30`, `ns-g40`, `ns-g45`, `ns-g50`, `ns-g55`, `ns-g60`, `ns-g70`, `ns-g80` | Grade-ramp text with the ramp's own weight (theme `GRADE_WEIGHT`). |
| `ns-text`, `ns-text-2`, `ns-muted`, `ns-dim` | Ink levels: text, text-2, text-3, and text-disabled. Use `ns-dim` only for decorative placeholders such as "—", because its contrast is 2.9:1. |
| `ns-good`, `ns-bad`, `ns-warn` | Meaning only. |
| `ns-series-1` | Chart-series-1 text, for a caption that acts as a legend. |
| `ns-prone-iron-man`, `ns-prone-durable`, `ns-prone-normal`, `ns-prone-fragile`, `ns-prone-wrecked` | Injury proneness (theme `PRONE`). |
| `ns-pos ns-pos-1b` (`posClass(v)`) | Position text in a cell: narrow bold in the position hue. |
| `ns-heat` + `style={heatVars(z)}`, with `ns-heat-sub` | z-heat cell from theme `zHeat`. The fill is `color-mix(oklab, zneg or zpos, \|z\|/2.5, panel)`, and the ink flips to `--bg` at an 80% mix. `heatVars` lives in `PositionalStrength.jsx`. Lift it to `lib/` when a second page needs it. |

## Colour translation (his palette → tokens)

Start by deciding what the colour means.

**Quality ladder.** This is three or more ordered bands that grade a rating, a value or a
rate. Translate by colour name, top to bottom:

| His class (any shade) | → |
| --- | --- |
| `purple`, `sky` | `ns-g80` |
| `cyan`, `emerald` | `ns-g70` |
| `green`, `lime` (as a band) | `ns-g55` |
| neutral middle band: `gray-300`, `slate-300`, `yellow` | `ns-text-2` |
| `amber` (as a band) | `ns-g40` |
| `orange` | `ns-g30` |
| `red`, `rose` | `ns-g20` |

The grade classes carry their own weight, so drop his `font-bold` and `font-semibold`
band markers. This translation is ours' five-band shape (theme `DEV_BANDS` and
`scoutingRatingColor`: g70, g55, text2, g40, g30) extended at both ends for his extra
tiers.

**Meaning.** This covers flags, good/neutral/bad splits, and money signs. Map:

- `green` to `ns-good`
- `red` to `ns-bad`
- a caution in amber, orange or yellow to `ns-warn`
- a neutral middle to `ns-text-2`

Keep his `font-*` weight here. Examples are `Dev_Flag`, `OnDL`, `NoTrade`, `_surplus`, the
Runs breakdown signs, and the rating-history deltas.

**Fixed encodings.** Some columns already have a theme encoding, so use it:

- proneness uses `ns-prone-*`
- positions use `posClass` or `ns-chip[data-pos]`
- levels use `ns-chip[data-lvl]`
- z-scores use `ns-heat`

His SP/RP role colours become the position hues.

**Greys** (text, not bands):

| His class | → |
| --- | --- |
| `white`, `slate-200`, `slate-300` | `ns-text` |
| `slate-400` | `ns-text-2` |
| `slate-500` | `ns-muted` |
| `slate-600` / `slate-700` used as readable small print | `ns-muted` |
| `slate-600` / `slate-700` used for a placeholder "—" | `ns-dim` |

**Grounds:**

| His class | → |
| --- | --- |
| `bg-slate-900` / `-950` (page) | the shell's `--bg` (nothing to set) |
| card `bg-slate-800/50 rounded-lg p-3` | `ns-card` |
| big container `bg-slate-900 border … rounded-xl` | `ns-box` |
| selected or highlighted row (`bg-blue-500/10`) | `tr.selected` (`--accent-bg`) |

## Before → after

**Page head**

```jsx
// before
<div className="p-4 pb-2"><h1 className="text-2xl font-bold text-white">Hitters</h1>
  <p className="text-sm text-slate-400 mt-1">{n} players | …</p></div>
// after
<div className="ns-page">
  <header className="ns-page-head"><div><h1>Hitters</h1>
    <p className="ns-page-sub"><b>{n}</b> players · …</p></div></header>
```

**Card with a heading (class swap only)**

```jsx
// before
<div className="bg-slate-800/50 rounded-lg p-3">
  <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Value Summary</h3>
// after
<div className="ns-card">
  <h3 className="ns-strip">Value Summary</h3>
```

**Toggle pill → toggle button**

```jsx
// before
<button className={`px-2.5 py-1 rounded-full text-xs ${on ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
// after
<button type="button" aria-pressed={on} className="ns-btn ns-btn-sm">
```

**Controls**

```jsx
// before
<select className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
<input className="… bg-slate-800 border border-slate-600 rounded-lg …" />
<Search size={14} className="absolute …" />
// after
<select className="ns-select">
<input className="ns-input" />
<div className="ns-search"><svg …stroke="currentColor"/><input className="ns-input" /></div>
```

**Sortable header**

```jsx
// before
<th onClick={…}>{label}{sorted && <ChevronDown size={12} />}<button className="col-hide"><X size={11} /></button></th>
// after
<th onClick={…} aria-sort={…} className={sorted ? 'sorted' : undefined}>
  {label}{sorted && <span className="text-[10px]" aria-hidden="true">▼</span>}<button className="col-hide">×</button></th>
```

**Ladder (`columns.js`)**

```js
// before
if (num >= 5) return 'text-purple-400 font-bold';
if (num >= 3) return 'text-cyan-400 font-semibold';
// after: same thresholds
if (num >= 5) return 'ns-g80';
if (num >= 3) return 'ns-g70';
```

**z-banded colour → heat**

```jsx
// before
<td className={`${zCell(z)}`}><div className={zText(z)}>{rank}</div><div className="text-[9px] text-slate-600">{waa}</div></td>
// after
<td className="ns-heat" style={heatVars(z)}><div>{rank}</div><div className="ns-heat-sub">{waa}</div></td>
```

**Modal or drawer**

```jsx
// before
<div className="fixed inset-0 bg-black/60 backdrop-blur-sm …"><div className="bg-slate-900 border … rounded-xl shadow-2xl">
// after
<div className="fixed inset-0 ns-scrim …"><div className="ns-box … overflow-auto">
  <div className="ns-strip sticky top-0 z-10 px-4 py-3">…</div><div className="ns-desk grid … p-4">cards…</div>
```

## Checklist per page

1. Run `grep -nE "slate|gray|zinc|blue-|green-|red-|amber|orange|yellow|cyan|purple|emerald|lime|sky|rose|rounded|uppercase|tracking-w|shadow|blur|lucide|#[0-9a-fA-F]{3,6}"`.
   Every hit is either converted or listed as unmapped in the report.
2. Change no logic. Check that `git diff` reads as class and markup changes only.
3. Run `npm run build`, the client tests, and the control tests.
4. Run `npx vite --port 31NN --strictPort` and load the page in a browser. Confirm there
   are no console errors, then stop the server.

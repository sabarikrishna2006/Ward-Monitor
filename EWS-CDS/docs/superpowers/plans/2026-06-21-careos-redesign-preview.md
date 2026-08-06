# Foqal CareOS Dashboard Redesign — Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `sabari_project/preview.html` — a standalone redesigned UI for the dashboard (n1), patient detail (n1b), and CCU→GW transfer (n_transfer) screens that the user can test before approving for integration into `index.html`.

**Architecture:** `preview.html` copies the HTML shell from `index.html` (same app shell element IDs so `app.js` binds correctly), replaces the `<link rel="stylesheet">` with an inline `<style>` block containing the complete redesigned CSS, imports `app.js` unchanged via `<script src="app.js">`, then adds a second `<script>` block that overrides `SCREENS.n1`, `SCREENS.n1b`, and `SCREENS.n_transfer` with redesigned HTML templates. All data fetching, navigation, modals, and other screens are untouched.

**Tech Stack:** Vanilla HTML/CSS/JS. Inter font via Google Fonts (already loaded). No build step. Backend: FastAPI on port 5175.

## Global Constraints

- Brand color `#800080` — used for primary CTA, active sidebar state, logo only. Never as a row fill or table background.
- Base font size: 14px (up from 13px in current styles.css).
- All app shell element IDs must be preserved exactly: `#app-shell`, `#main`, `#sidebar`, `#sidebar-wrap`, `#sidebar-overlay`, `#appbar`, `#hdr-role`, `#hdr-user`, `#hdr-ward`, `#topbar-line`, `#modal-overlay`, `#modal-box`.
- No changes to `index.html`, `app.js`, `styles.css`, or any backend file.
- AVPU removed from dashboard table display only — it appears in the Patient Detail vitals instrument grid.
- Two-column layouts collapse to stacked at `max-width: 768px`.
- All existing interactions (nav, escalate, ack, filter, refresh, false alarm, modal) must work identically.

---

### Task 1: Create `preview.html` — HTML shell + complete redesigned CSS + screen overrides

**Files:**
- Create: `sabari_project/preview.html`

**Interfaces:**
- Consumes: `app.js` (unchanged import) — provides `APP`, `SCREENS`, `NAV`, `renderAll()`, `renderEwsReason()`, `renderNews2Svg()`, `nav()`, `logout()`, `toggleSidebar()`, `openModal()`, `closeModal()`
- Produces: `SCREENS.n1`, `SCREENS.n1b`, `SCREENS.n_transfer` overrides written after `app.js` loads

**Design tokens:**
```css
--p: #800080       /* brand purple */
--pl: #faf5ff      /* purple ghost */
--t1: #dc2626      /* critical red */
--t1b: #fff1f2     /* critical bg */
--t2: #d97706      /* warning amber */
--t2b: #fffbeb     /* warning bg */
--t3: #059669      /* stable green */
--t3b: #f0fdf4     /* stable bg */
--ink: #0f172a     /* primary text */
--ink2: #475569    /* secondary text */
--muted: #94a3b8   /* muted/labels */
--border: #e8edf3  /* borders (lighter) */
--surf: #f7f9fc    /* page background */
--white: #ffffff   /* card surfaces */
```

**Signature element — severity bars:**
- Dashboard rows: white background, `box-shadow: inset 5px 0 0 <color>` on `td:first-child`. Critical = red, Warning = amber, Stable = green.
- Stats cards: `border-left: 5px solid <color>` (already set via inline style from app.js — CSS overrides the width to 5px with `!important`).
- NEWS2 score: pill badge (colored background, white bold text, border-radius: 20px).

**Instrument grid — Patient Detail vitals:**
- 3×2 CSS grid (`grid-template-columns: repeat(3, 1fr)`)
- Each cell: `.vital-cell` — label (11px muted uppercase), large value (28px bold), unit, flag/status
- Severity applied as `border-top: 3px solid <color>` and colored value text

**CCU→GW Transfer two-column layout:**
- `.transfer-layout`: `grid-template-columns: 2fr 3fr`
- Left: criteria checklist with `.criteria-row` / `.criteria-icon.met|unmet|info`
- Right: form with target ward select, rationale textarea, submit button
- Submit button `disabled` when `!e.eligible`

- [ ] **Step 1: Create `sabari_project/preview.html`**

Write the complete file with this structure:

```
<!DOCTYPE html>
<html lang="en">
<head>
  <!-- Session boot script (copied from index.html) -->
  <!-- Inter font link -->
  <style>
    /* All redesigned CSS — tokens, reset, layout, components, screen-specific */
  </style>
</head>
<body>
  <!-- App shell (same IDs as index.html) -->
  <script src="app.js"></script>
  <script>
    /* SCREENS.n1 override */
    /* SCREENS.n1b override */
    /* SCREENS.n_transfer override */
  </script>
</body>
</html>
```

Complete CSS to include (in order):

**Tokens + reset:**
```css
:root {
  --p:#800080; --pl:#faf5ff; --pm:#a855f7;
  --t1:#dc2626; --t1b:#fff1f2;
  --t2:#d97706; --t2b:#fffbeb;
  --t3:#059669; --t3b:#f0fdf4;
  --ink:#0f172a; --ink2:#475569; --muted:#94a3b8;
  --border:#e8edf3; --surf:#f7f9fc; --white:#ffffff;
  --font:'Inter',system-ui,sans-serif;
  --mono:'SF Mono','Menlo','Consolas',monospace;
  --sb:240px; --ab:58px; --tb:4px;
}
*,*::before,*::after { box-sizing:border-box; margin:0; padding:0 }
html,body { height:100%; overflow:hidden }
body { font-family:var(--font); color:var(--ink); background:var(--surf); font-size:14px; line-height:1.5; -webkit-font-smoothing:antialiased }
button { cursor:pointer; font-family:inherit; font-size:inherit }
input,select,textarea { font-family:inherit; font-size:inherit }
a { color:inherit; text-decoration:none }
```

**Layout (topbar, appbar, sidebar, content):**
```css
#topbar-line { height:var(--tb); background:var(--p); position:fixed; top:0; left:0; right:0; z-index:200 }
#appbar { height:var(--ab); background:var(--white); border-bottom:1px solid var(--border); position:fixed; top:var(--tb); left:0; right:0; z-index:190; display:flex; align-items:center; padding:0 20px; gap:12px }
.alogo { font-size:16px; font-weight:800; color:var(--p); letter-spacing:-0.5px }
.alogo em { color:var(--ink); font-style:normal; font-weight:500 }
.role-chip { padding:3px 10px; border-radius:20px; font-size:10px; font-weight:700; letter-spacing:0.5px; text-transform:uppercase; background:var(--surf); color:var(--muted); border:1px solid var(--border) }
#hdr-meta { display:flex; align-items:center; gap:8px; margin-left:8px; color:var(--ink2) }
#layout { display:flex; position:fixed; top:calc(var(--tb) + var(--ab)); left:0; right:0; bottom:0 }
#sidebar-wrap { width:var(--sb); background:var(--white); border-right:1px solid var(--border); display:flex; flex-direction:column; flex-shrink:0 }
.sb-header { padding:16px 16px 10px; font-size:10px; font-weight:800; letter-spacing:1.2px; color:var(--muted); text-transform:uppercase }
#sidebar { overflow-y:auto; flex:1; padding:4px 0 }
.sb-sep { padding:18px 16px 6px; font-size:9.5px; font-weight:800; text-transform:uppercase; letter-spacing:0.8px; color:var(--muted) }
.sb-item { display:flex; align-items:center; gap:8px; padding:9px 16px; font-size:13px; color:var(--ink2); cursor:pointer; border-left:3px solid transparent; transition:all 0.1s }
.sb-item:hover { background:var(--surf); color:var(--ink) }
.sb-item.active { background:var(--pl); color:var(--p); border-left-color:var(--p); font-weight:600 }
#content { flex:1; display:flex; flex-direction:column; overflow:hidden; min-width:0; background:var(--surf) }
#main { flex:1; overflow-y:auto; padding:28px 36px }
```

**Components (breadcrumb, header, tabs, buttons, badges, card, alert, table, form, modal, timeline, drug-lab flags):**
```css
.bc { display:flex; align-items:center; gap:6px; font-size:11.5px; color:var(--muted); margin-bottom:14px; flex-wrap:wrap }
.bc-link { color:var(--p); cursor:pointer; font-weight:500 }
.bc-link:hover { text-decoration:underline }
.bc-sep { color:var(--muted) }
.sh { display:flex; align-items:center; gap:12px; margin-bottom:24px; flex-wrap:wrap }
.sh-title { font-size:24px; font-weight:800; color:var(--ink); flex:1; min-width:200px; letter-spacing:-0.5px }
.sh-actions { display:flex; gap:10px; align-items:center }
.pid { font-family:var(--mono); font-size:11px; color:var(--muted); font-weight:500 }
.tab-strip { display:flex; margin-bottom:20px; border-bottom:2px solid var(--border) }
.tab-btn { background:none; border:none; padding:9px 18px; font-size:13px; font-weight:500; color:var(--muted); border-bottom:2px solid transparent; margin-bottom:-2px; transition:all 0.15s; cursor:pointer }
.tab-btn:hover { color:var(--ink) }
.tab-btn.active { color:var(--p); font-weight:700; border-bottom-color:var(--p) }
.btn { display:inline-flex; align-items:center; gap:6px; padding:8px 16px; border-radius:7px; font-size:13px; font-weight:600; border:1px solid transparent; cursor:pointer; transition:all 0.15s; white-space:nowrap }
.btn-pri { background:var(--p); color:#fff; border-color:var(--p) }
.btn-pri:hover { background:#6b006b }
.btn-sec { background:var(--white); color:var(--ink); border-color:var(--border) }
.btn-sec:hover { background:var(--surf) }
.btn-danger { background:var(--t1); color:#fff; border-color:var(--t1) }
.btn-danger:hover { background:#b91c1c }
.btn-warn { background:#fffbeb; color:#92400e; border-color:#fcd34d }
.btn-warn:hover { background:#fef3c7 }
.btn-sm { padding:6px 12px; font-size:12px }
.btn-xs { padding:4px 9px; font-size:11.5px }
.bd { display:inline-flex; align-items:center; padding:3px 9px; border-radius:20px; font-size:10.5px; font-weight:700 }
.bd-t1 { background:var(--t1b); color:var(--t1) }
.bd-t2 { background:var(--t2b); color:var(--t2) }
.bd-t3 { background:var(--t3b); color:var(--t3) }
.bd-gray { background:#f1f5f9; color:#475569 }
.card { background:var(--white); border:1px solid var(--border); border-radius:10px; padding:20px; box-shadow:0 1px 2px rgba(15,23,42,0.04) }
.card-title { font-size:13px; font-weight:700; color:var(--ink); margin-bottom:14px; letter-spacing:-0.2px }
.alert { padding:12px 16px; border-radius:8px; display:flex; align-items:flex-start; gap:10px; font-size:13px; margin-bottom:16px; line-height:1.5; border:1px solid transparent }
.al-err  { background:var(--t1b); color:var(--t1); border-color:#fca5a5 }
.al-warn { background:var(--t2b); color:#92400e; border-color:#fcd34d }
.al-ok   { background:var(--t3b); color:#065f46; border-color:#6ee7b7 }
.al-info { background:#eff6ff; color:#1e40af; border-color:#bfdbfe }
.tw { background:var(--white); border:1px solid var(--border); border-radius:10px; overflow:hidden; box-shadow:0 1px 2px rgba(15,23,42,0.04) }
table { width:100%; border-collapse:collapse }
th { padding:11px 16px; text-align:left; font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; background:var(--surf); border-bottom:1px solid var(--border); white-space:nowrap }
td { padding:13px 16px; border-bottom:1px solid var(--border); color:var(--ink); vertical-align:middle }
tr:last-child td { border-bottom:none }
tr { transition:background 0.12s }
tr:hover td { background:#f8fafc }
tr[onclick] { cursor:pointer }
.fg { margin-bottom:16px }
.fl { display:block; font-size:12px; font-weight:600; color:var(--ink2); margin-bottom:6px }
.fi { width:100%; padding:9px 12px; border:1px solid var(--border); border-radius:7px; font-size:14px; color:var(--ink); background:var(--white); transition:all 0.15s }
.fi:focus { outline:none; border-color:var(--p); box-shadow:0 0 0 3px rgba(128,0,128,0.1) }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px }
.grid3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px }
.flex-r { display:flex; align-items:center; gap:10px }
.mono { font-family:var(--mono) }
.muted { color:var(--muted) }
.small { font-size:11.5px }
.bold { font-weight:700 }
.v-crit { color:var(--t1); font-weight:700 }
.v-warn { color:var(--t2); font-weight:600 }
#modal-overlay { display:none; position:fixed; inset:0; background:rgba(15,23,42,0.5); z-index:300; align-items:center; justify-content:center; backdrop-filter:blur(4px) }
#modal-overlay.open { display:flex }
#modal-box { background:var(--white); border-radius:14px; padding:32px; width:520px; max-width:90vw; box-shadow:0 24px 48px rgba(0,0,0,0.18) }
.modal-t { font-size:18px; font-weight:800; color:var(--ink); margin-bottom:12px }
.modal-b { font-size:14px; color:var(--ink2); margin-bottom:24px; line-height:1.6 }
.modal-f { display:flex; justify-content:flex-end; gap:10px; margin-top:20px }
.tl { padding:8px 0; margin-bottom:16px }
.tl-item { display:flex; gap:14px; padding:12px 0; position:relative }
.tl-item:not(:last-child)::before { content:''; position:absolute; left:15px; top:38px; bottom:-12px; width:2px; background:var(--border) }
.tl-dot { width:32px; height:32px; border-radius:50%; background:var(--pl); border:2px solid var(--p); display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; color:var(--p); flex-shrink:0 }
.tl-dot.ok { background:var(--t3b); border-color:var(--t3); color:var(--t3) }
.tl-dot.err { background:var(--t1b); border-color:var(--t1); color:var(--t1) }
.tl-body { flex:1; padding-top:2px }
.tl-title { font-size:14px; font-weight:700; color:var(--ink) }
.tl-time { font-size:11.5px; color:var(--muted); margin-top:2px }
.tl-detail { font-size:13px; color:var(--ink2); margin-top:6px; line-height:1.5; background:var(--surf); padding:10px 14px; border:1px solid var(--border); border-radius:7px; display:inline-block }
.dlf { background:var(--white); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:12px; display:flex; gap:14px }
.dlf.t1 { border-left:5px solid var(--t1) }
.dlf.t2 { border-left:5px solid var(--t2) }
.dlf-bd { flex:1 }
.dlf-title { font-size:14px; font-weight:700; color:var(--ink) }
.dlf-desc { font-size:13px; color:var(--ink2); margin-top:6px; line-height:1.6 }
.dlf-link { font-size:12px; color:var(--p); font-weight:700; cursor:pointer; margin-top:8px; display:inline-block }
.dlf-link:hover { text-decoration:underline }
.check-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:12px; font-size:14px }
.check-row input[type=checkbox] { margin-top:3px; accent-color:var(--p); width:16px; height:16px; cursor:pointer }
.radio-row { display:flex; align-items:center; gap:10px; margin-bottom:10px; font-size:14px; cursor:pointer }
.radio-row input[type=radio] { accent-color:var(--p); width:16px; height:16px; cursor:pointer }
.src-tag { font-size:9.5px; color:var(--muted); font-weight:500 }
.ml-risk-num { font-size:44px; font-weight:800; line-height:1; letter-spacing:-1px }
.ml-bar-row { display:flex; align-items:center; gap:8px; margin-bottom:8px }
.ml-bar-lbl { font-size:11.5px; color:var(--ink2); width:140px; flex-shrink:0 }
.ml-bar { flex:1; height:6px; background:var(--surf); border-radius:4px; overflow:hidden }
.ml-bar-fill { height:100%; background:var(--p); border-radius:4px }
.ml-bar-pct { font-size:11px; font-weight:700; color:var(--muted); width:32px; text-align:right }
.ews-reason-td { min-width:160px; max-width:220px }
.ews-cell { display:flex; flex-direction:column; gap:2px; line-height:1.35 }
.ews-sigs { display:flex; flex-wrap:wrap; gap:4px 6px }
.ews-sig { font-size:12px; font-weight:800; white-space:nowrap }
.ews-flag { font-size:10.5px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:215px }
.ews-action { font-size:11px; font-weight:700 }
.ews-ok { font-size:11.5px; color:var(--t3); font-weight:600 }
.ews-ai { font-size:10px; color:var(--muted); font-weight:600; margin-top:1px }
.demo-tag { display:inline-block; background:var(--pl); color:var(--p); font-size:8.5px; font-weight:800; padding:0 4px; border-radius:4px; letter-spacing:0.3px; text-transform:uppercase; vertical-align:middle }
.dx-cell { font-size:12px; color:var(--ink2); max-width:140px }
.loc-tag { display:inline-block; font-size:9px; font-weight:800; padding:2px 6px; border-radius:4px; letter-spacing:0.4px }
.loc-ccu { background:var(--t1b); color:var(--t1) }
.loc-gw { background:var(--t3b); color:var(--t3) }
.due-label { font-size:10px; color:var(--muted); margin-top:3px; font-weight:600 }
.due-over { color:var(--t1); font-weight:800 }
.dx-banner { display:flex; gap:28px; flex-wrap:wrap; padding:14px 18px; border-radius:10px; margin-bottom:18px; border:1px solid var(--border); background:var(--white) }
.dx-banner.sev-t1 { background:var(--t1b); border-color:#fca5a5; border-left:5px solid var(--t1) }
.dx-banner.sev-t2 { background:var(--t2b); border-color:#fcd34d; border-left:5px solid var(--t2) }
.dx-banner.sev-t3 { background:var(--t3b); border-color:#6ee7b7; border-left:5px solid var(--t3) }
.dx-banner .dx-lbl { display:block; font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:3px }
.dx-banner b { font-size:13.5px; color:var(--ink) }
.action-card:hover { background:#fafbfc }
.action-card.selected-action { background:var(--pl); border-color:var(--p) }
.spinner { display:inline-block; width:12px; height:12px; border:2px solid rgba(255,255,255,0.4); border-top-color:#fff; border-radius:50%; animation:spin 0.6s linear infinite; margin-right:6px; vertical-align:middle }
@keyframes spin { to { transform:rotate(360deg) } }
```

**Screen-specific styles (severity bars, pill badge, instrument grid, transfer layout):**
```css
/* Stats bar */
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:24px }
.stat { background:var(--white); border:1px solid var(--border); border-radius:10px; padding:18px 20px; border-left-width:5px !important; transition:transform 0.12s,box-shadow 0.12s }
.stat:hover { transform:translateY(-1px); box-shadow:0 4px 12px rgba(15,23,42,0.08) }
.stat.active-filter { box-shadow:0 0 0 2px var(--p) }
.stat-v { font-size:40px; font-weight:800; line-height:1; letter-spacing:-1px; font-variant-numeric:tabular-nums }
.stat-l { font-size:11px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-top:8px }

/* Dashboard row severity bars — white rows + left inset shadow */
.row-crit td,.row-crit:hover td { background:var(--white) !important }
.row-warn td,.row-warn:hover td { background:var(--white) !important }
.row-crit td:first-child { box-shadow:inset 5px 0 0 var(--t1) }
.row-warn td:first-child { box-shadow:inset 5px 0 0 var(--t2) }
tr:not(.row-crit):not(.row-warn):not(.stale) td:first-child { box-shadow:inset 5px 0 0 var(--t3) }
tr.stale td { color:var(--muted); opacity:0.65 }
.acked-row td { opacity:0.75 }

/* NEWS2 pill badge */
.n2s { display:inline-block; min-width:36px; text-align:center; font-size:14px; font-weight:800; padding:4px 10px; border-radius:20px; font-variant-numeric:tabular-nums }
.n2s.hi  { background:var(--t1); color:#fff }
.n2s.med { background:var(--t2); color:#fff }
.n2s.lo  { background:var(--t3); color:#fff }

/* Vital instrument grid */
.vitals-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:16px }
.vital-cell { background:var(--white); border:1px solid var(--border); border-radius:10px; padding:16px 18px; position:relative }
.vital-cell.crit { border-top:3px solid var(--t1) }
.vital-cell.warn { border-top:3px solid var(--t2) }
.vital-cell.ok   { border-top:3px solid var(--t3) }
.vital-lbl { font-size:10.5px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px }
.vital-row { display:flex; align-items:baseline; gap:6px }
.vital-val { font-size:28px; font-weight:800; letter-spacing:-0.5px; font-variant-numeric:tabular-nums; color:var(--ink) }
.vital-val.crit { color:var(--t1) }
.vital-val.warn { color:var(--t2) }
.vital-val.ok   { color:var(--t3) }
.vital-unit { font-size:13px; color:var(--muted); font-weight:500 }
.vital-flag { font-size:11px; font-weight:700; margin-top:6px; min-height:16px }
.vital-flag.crit { color:var(--t1) }
.vital-flag.warn { color:var(--t2) }
.vital-flag.ok   { color:var(--t3) }
.vital-time { font-size:10px; color:var(--muted); margin-top:4px }

/* CCU→GW transfer layout */
.transfer-layout { display:grid; grid-template-columns:2fr 3fr; gap:20px; margin-bottom:20px; align-items:start }
.criteria-row { display:flex; align-items:flex-start; gap:12px; padding:10px 0; border-bottom:1px solid var(--border) }
.criteria-row:last-child { border-bottom:none }
.criteria-icon { width:22px; height:22px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:800; flex-shrink:0; margin-top:1px }
.criteria-icon.met   { background:var(--t3b); color:var(--t3) }
.criteria-icon.unmet { background:var(--t1b); color:var(--t1) }
.criteria-icon.info  { background:var(--t2b); color:var(--t2) }
.criteria-lbl { font-size:13px; font-weight:600; color:var(--ink) }
.criteria-detail { font-size:11.5px; color:var(--muted); margin-top:2px }
.transfer-ready-banner { background:var(--t3b); border:1px solid #6ee7b7; border-radius:10px; padding:14px 18px; margin-bottom:16px; font-size:14px; font-weight:600; color:#065f46; display:flex; align-items:center; gap:10px }

/* Mobile */
#sidebar-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); z-index:180 }
.ham-btn { display:none; background:none; border:none; padding:6px; cursor:pointer }
.ham-icon { display:flex; flex-direction:column; gap:4px }
.ham-icon span { display:block; width:20px; height:2px; background:var(--ink); border-radius:2px }
@media (max-width:768px) {
  #main { padding:16px }
  .sh-title { font-size:18px }
  #sidebar-wrap { position:fixed; left:-260px; top:0; bottom:0; z-index:185; transition:left 0.2s; width:var(--sb) }
  #sidebar-wrap.open { left:0 }
  #sidebar-overlay.open { display:block }
  .ham-btn { display:flex }
  .grid2,.transfer-layout { grid-template-columns:1fr }
  .vitals-grid { grid-template-columns:1fr 1fr }
  .stats { grid-template-columns:1fr 1fr }
}
```

**Complete `SCREENS.n1` override** (place after `<script src="app.js">`):

```javascript
SCREENS.n1 = () => {
  const patients = (APP.data.n1?.patients || []);
  patients.sort((a, b) => b.news2 - a.news2);
  let critCount = 0, medCount = 0, lowCount = 0, staleCount = 0;
  APP.n1_filter = APP.n1_filter || 'all';
  patients.forEach(p => {
    if (p.status === 'stale') staleCount++;
    else if (p.news2 >= 7) critCount++;
    else if (p.news2 >= 5) medCount++;
    else lowCount++;
  });
  const filtered = patients.filter(p => {
    if (APP.n1_filter === 'critical') return p.news2 >= 7 && p.status !== 'stale';
    if (APP.n1_filter === 'medium')   return p.news2 >= 5 && p.news2 < 7 && p.status !== 'stale';
    if (APP.n1_filter === 'low')      return p.news2 < 5 && p.status !== 'stale';
    if (APP.n1_filter === 'stale')    return p.status === 'stale';
    return true;
  });
  const refreshStr = APP.lastRefresh
    ? 'Updated ' + APP.lastRefresh.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}) + ' · auto 15m'
    : new Date().toLocaleString('en-IN',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});

  return `
<div class="bc"><span>${APP.role==='gw_nurse'?'General Ward':APP.role==='nurse'?'CCU · Ward 4B/4C':'Ward 4B/4C'}</span><span class="bc-sep">/</span><span>NEWS2 Dashboard</span></div>
<div class="sh">
  <h1 class="sh-title">${APP.role==='gw_nurse'?'General Ward':APP.role==='nurse'?'CCU':'Ward'} — NEWS2 Dashboard</h1>
  <div class="sh-actions">
    <span class="muted small">${refreshStr}</span>
    <button class="btn btn-sec btn-sm" onclick="refreshNow(false)">↻ Refresh</button>
    ${APP.role==='nurse'?`<button class="btn btn-pri btn-sm" onclick="nav('n_transfer')">CCU→GW Transfer</button>`:''}
    <button class="btn btn-sec btn-sm" onclick="nav('n6')">Shift Handoff</button>
  </div>
</div>
<div class="stats">
  <div class="stat ${APP.n1_filter==='critical'?'active-filter':''}" style="border-left:5px solid var(--t1);cursor:pointer" onclick="APP.n1_filter=APP.n1_filter==='critical'?'all':'critical';renderAll()">
    <div class="stat-v" style="color:var(--t1)">${critCount}</div><div class="stat-l">Critical ≥7</div>
  </div>
  <div class="stat ${APP.n1_filter==='medium'?'active-filter':''}" style="border-left:5px solid var(--t2);cursor:pointer" onclick="APP.n1_filter=APP.n1_filter==='medium'?'all':'medium';renderAll()">
    <div class="stat-v" style="color:var(--t2)">${medCount}</div><div class="stat-l">Medium 5–6</div>
  </div>
  <div class="stat ${APP.n1_filter==='low'?'active-filter':''}" style="border-left:5px solid var(--t3);cursor:pointer" onclick="APP.n1_filter=APP.n1_filter==='low'?'all':'low';renderAll()">
    <div class="stat-v" style="color:var(--t3)">${lowCount}</div><div class="stat-l">Low 1–4</div>
  </div>
  <div class="stat ${APP.n1_filter==='stale'?'active-filter':''}" style="border-left:5px solid var(--muted);cursor:pointer" onclick="APP.n1_filter=APP.n1_filter==='stale'?'all':'stale';renderAll()">
    <div class="stat-v" style="color:var(--muted)">${staleCount}</div><div class="stat-l">Stale Vitals</div>
  </div>
</div>
<div class="tw"><table>
  <thead><tr>
    <th>Patient</th><th>Diagnosis</th><th>Ward</th>
    <th>SpO₂ (%)</th><th>RR (/min)</th><th>BP (mmHg)</th><th>HR (bpm)</th><th>Temp (°C)</th>
    <th>NEWS2</th><th>EWS Signal</th><th>Status</th><th>Actions</th>
  </tr></thead>
  <tbody>
    ${filtered.map(p => {
      const isStale = p.status === 'stale';
      const score = p.news2 || 0;
      let rowClass = isStale ? 'stale' : score >= 7 ? 'row-crit' : score >= 5 ? 'row-warn' : '';
      if (p._acked) rowClass += ' acked-row';
      const scoreClass = isStale ? '' : score >= 7 ? 'n2s hi' : score >= 5 ? 'n2s med' : 'n2s lo';
      const statusBd  = isStale ? 'bd bd-gray' : score >= 7 ? 'bd bd-t1' : score >= 5 ? 'bd bd-t2' : 'bd bd-t3';
      const statusLbl = isStale ? 'Overdue' : score >= 7 ? 'Escalate' : score >= 5 ? 'Monitor' : 'Stable';
      const vc = (val,thres,op) => (!val||val==='--'||isStale)?'':((op==='<'&&val<thres)||(op==='>'&&val>thres))?'v-crit':'';
      const th = t => t ? `<br><span class="muted small">${t}</span>` : '';
      const bpVal = p.bp ? parseInt(p.bp) : '';
      const hr=isStale?'—':(p.hr||'—'), rr=isStale?'—':(p.rr||'—');
      const spo2=isStale?'—':(p.spo2||'—'), bp=isStale?'—':(p.bp||'—');
      const temp=isStale?'—':(p.temp||'—'), s=isStale?'—':score;
      const ackBtn = p._acked?'':`<button class="btn btn-sec btn-xs" onclick="event.stopPropagation();ackPatient(event,${p.id})">Ack</button>`;
      return `<tr class="${rowClass}" onclick="nav('n1b',${p.id})">
        <td><b>${p.name}</b><br><span class="pid">${p.patient_code||'PT-'+p.id}</span></td>
        <td class="dx-cell">${p.diagnosis_short||'—'}</td>
        <td>${p.ward.split(' ')[1]||p.ward}<br>${p.ward_location==='GENERAL_WARD'?'<span class="loc-tag loc-gw">GW</span>':'<span class="loc-tag loc-ccu">CCU</span>'}</td>
        <td class="${vc(p.spo2,92,'<')}">${spo2}${th(p.spo2_time)}</td>
        <td class="${vc(p.rr,21,'>')}">${rr}${th(p.rr_time)}</td>
        <td class="${vc(bpVal,90,'<')}">${bp}${th(p.bp_time)}</td>
        <td class="${vc(p.hr,110,'>')}">${hr}${th(p.hr_time)}</td>
        <td class="${vc(p.temp,38.0,'>')}">${temp}${th(p.temp_time)}</td>
        <td><span class="${scoreClass}">${s}</span></td>
        <td class="ews-reason-td">${renderEwsReason(p)}</td>
        <td><span class="${statusBd}">${statusLbl.toUpperCase()}</span>${p.dueLabel?`<div class="due-label${p.isOverdue?' due-over':''}">${p.dueLabel}</div>`:''}</td>
        <td>${isStale
          ?`<button class="btn btn-warn btn-xs" onclick="event.stopPropagation();nav('n_vitals',${p.id})">Enter Vitals</button>`
          :`${score>=5?`<button class="btn ${score>=7?'btn-danger':'btn-warn'} btn-xs" onclick="event.stopPropagation();nav('n2',${p.id})">${score>=7?'Escalate':'Monitor'}</button>`:''} ${ackBtn}`
        }</td>
      </tr>`;
    }).join('')}
  </tbody>
</table></div>`;
};
```

**Complete `SCREENS.n1b` override** (instrument grid vitals tab, other tabs unchanged):

```javascript
SCREENS.n1b = () => {
  const p = APP.data.n1b || {};
  const score = p.news2 || 0;
  const isCrit = score >= 7, isWarn = score >= 5 && score < 7;
  const bdClass = isCrit ? 'bd-t1' : isWarn ? 'bd-t2' : 'bd-t3';
  const lbl = isCrit ? 'CRITICAL' : isWarn ? 'WARNING' : 'STABLE';
  const sbp = p.bp ? parseInt(p.bp.split('/')[0]) : null;

  /* Instrument grid */
  const cells = [
    { lbl:'SpO₂', val:p.spo2!=null?p.spo2+'%':'—', unit:p.o2==='Oxygen'?'on O₂':'', sev:p.spo2<92?'crit':'ok', flag:p.spo2<92?'⚠ LOW — hypoxia':p.o2==='Oxygen'?'Supplemental O₂':'Within range', time:p.spo2_time },
    { lbl:'Resp Rate', val:p.rr!=null?p.rr:'—', unit:'/min', sev:p.rr>20?'crit':'ok', flag:p.rr>25?'⚠ HIGH — tachypnoea':p.rr>20?'↑ Elevated':'Within range', time:p.rr_time },
    { lbl:'Blood Pressure', val:p.bp||'—', unit:'mmHg', sev:sbp&&sbp<90?'crit':sbp&&sbp<100?'warn':'ok', flag:sbp&&sbp<90?'⚠ LOW — hypotension':'Within range', time:p.bp_time },
    { lbl:'Heart Rate', val:p.hr!=null?p.hr:'—', unit:'bpm', sev:p.hr>110?'crit':p.hr>100?'warn':p.hr<50?'crit':'ok', flag:p.hr>110?'⚠ HIGH — tachycardia':p.hr<50?'⚠ LOW — bradycardia':'Within range', time:p.hr_time },
    { lbl:'Temperature', val:p.temp!=null?p.temp+'°C':'—', unit:'', sev:p.temp>38.5?'crit':p.temp>37.5?'warn':'ok', flag:p.temp>38.5?'⚠ Fever':p.temp>37.5?'↑ Elevated':'Afebrile', time:p.temp_time },
    { lbl:'AVPU', val:p.avpu||'A', unit:'', sev:(p.avpu&&p.avpu!=='A')?'crit':'ok', flag:p.avpu==='C'?'⚠ Confused':p.avpu==='V'?'⚠ Voice response':p.avpu==='P'?'⚠ Pain response':p.avpu==='U'?'⚠ Unresponsive':'Alert', time:p.avpu_time },
  ];
  const vitalsGrid = `<div class="vitals-grid">${cells.map(c=>`
    <div class="vital-cell ${c.sev}">
      <div class="vital-lbl">${c.lbl}</div>
      <div class="vital-row"><div class="vital-val ${c.sev}">${c.val}</div>${c.unit?`<div class="vital-unit">${c.unit}</div>`:''}</div>
      <div class="vital-flag ${c.sev}">${c.flag}</div>
      ${c.time?`<div class="vital-time">${c.time}</div>`:''}
    </div>`).join('')}</div>`;

  /* NEWS2 summary card */
  const sevColor = isCrit?'var(--t1)':isWarn?'var(--t2)':'var(--t3)';
  const news2Card = `<div class="vital-cell ${isCrit?'crit':isWarn?'warn':'ok'}" style="margin-bottom:14px;display:flex;align-items:center;gap:20px">
    <div style="font-size:56px;font-weight:900;color:${sevColor};line-height:1;letter-spacing:-2px">${score}</div>
    <div>
      <div style="font-size:16px;font-weight:800;color:${sevColor}">${lbl}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:4px">${isCrit?'Escalate immediately':isWarn?'Increased monitoring':'Routine monitoring'}</div>
    </div>
  </div>`;

  /* Vitals history */
  const historyTable = `<div class="card" style="margin-top:16px">
    <div class="card-title">Vitals History — Last 6 Hours</div>
    <div class="tw" style="border:none"><table>
      <thead><tr><th>Time</th><th>SpO₂</th><th>RR</th><th>BP</th><th>HR</th><th>Temp</th><th>NEWS2</th></tr></thead>
      <tbody>${(p.recentVitals||[]).map(t=>{
        const bpStr=t.sbp&&t.dbp?t.sbp+'/'+t.dbp:'--/--';
        return `<tr>
          <td class="muted">${t.time}</td>
          <td class="${t.spo2<92?'v-crit':''}">${t.spo2}%</td>
          <td class="${t.rr>20?'v-crit':''}">${t.rr}</td>
          <td class="${t.sbp<90?'v-crit':''}">${bpStr}</td>
          <td class="${t.hr>110?'v-crit':''}">${t.hr}</td>
          <td>${t.temp||'—'}°C</td>
          <td><span class="${t.news2>=7?'n2s hi':t.news2>=5?'n2s med':'n2s lo'}">${t.news2}</span></td>
        </tr>`}).join('')}
        ${(!p.recentVitals||p.recentVitals.length===0)?'<tr><td colspan="7" class="muted small" style="text-align:center;padding:20px">No recent vitals.</td></tr>':''}
      </tbody>
    </table></div>
  </div>`;

  /* DCM card */
  const kLab=(p.recentLabs||[]).find(l=>l.test==='Potassium');
  const kNum=kLab?kLab.value:null;
  const kVal=kNum!=null?kNum+' mmol/L':'—';
  const kCol=kNum!=null&&(kNum<3.5||kNum>5.5)?'var(--t1)':kNum!=null&&kNum>5.0?'var(--t2)':'var(--ink)';
  const kFlag=kNum==null?'':kNum<3.5?'↓ Low':kNum>5.5?'⚠ High':kNum>5.0?'High-normal':'Normal';
  const hrNum=typeof p.hr==='number'?p.hr:parseInt(p.hr);
  const rhythm=isNaN(hrNum)?'—':hrNum>100?'Sinus tachycardia':hrNum<50?'Bradycardia':'Sinus rhythm';
  const fb=p.fluidBalance;
  const fbCol=fb>500?'var(--t1)':fb>0?'var(--t2)':'var(--ink)';
  const dcmCard = `<div class="card" style="margin-top:14px">
    <div class="card-title">Heart-Failure Watch — DCM Parameters</div>
    <table style="width:100%;font-size:13px"><tbody>
      <tr><td class="muted">Fluid Balance (24h) <span class="src-tag">(manual/HIS)</span></td><td style="font-weight:700;color:${fbCol}">${fb!=null?(fb>0?'+':'')+fb+' ml':'—'}</td><td style="font-size:11px;font-weight:600;color:${fbCol}">${fb>0?'⚠ Positive (overload)':fb!=null?'Balanced':''}</td></tr>
      <tr><td class="muted">Urine Output (4h) <span class="src-tag">(manual)</span></td><td style="font-weight:700">${p.urineOutput!=null?p.urineOutput+' ml':'—'}</td><td style="font-size:11px;font-weight:600;color:${p.urineOutput!=null&&p.urineOutput<200?'var(--t2)':'var(--muted)'}">${p.urineOutput!=null&&p.urineOutput<200?'↓ Low output':''}</td></tr>
      <tr><td class="muted">Serum K⁺ (last) <span class="src-tag">(lab/HIS)</span></td><td style="font-weight:700;color:${kCol}">${kVal}</td><td style="font-size:11px;font-weight:600;color:${kCol}">${kFlag}</td></tr>
      <tr><td class="muted">Rhythm (from HR) <span class="src-tag">(monitor)</span></td><td style="font-weight:700">${rhythm}</td><td></td></tr>
    </tbody></table>
    <div class="muted small" style="margin-top:8px">Fluid status, urine output and K⁺ are key bedside signals in decompensated heart failure.</div>
  </div>`;

  /* Drug-Lab tab */
  const dlAlerts=p.drugLabAlerts||[];
  const druglab=dlAlerts.length===0
    ?`<div class="alert al-ok">No active drug-lab interaction flags for this patient.</div>`
    :`<div class="alert al-info">Nurse awareness only — clinical actions are taken by the Attending Physician.</div>
    ${dlAlerts.map(a=>{const tier=a.severity==='CRITICAL'?'t1':'t2';return`<div class="dlf ${tier}"><div class="dlf-bd">
      <div class="flex-r"><div class="dlf-title">⚠ ${a.rule_name||a.severity}</div><span class="bd ${a.severity==='CRITICAL'?'bd-t1':'bd-t2'}">${a.severity}</span></div>
      <div class="dlf-desc"><b>Alert:</b> ${a.message}<br><b>Action:</b> ${a.action||''}</div>
      <div style="margin-top:6px;font-size:11px;color:var(--muted)">${a.guideline||''}</div>
    </div></div>`}).join('')}
    <div class="card" style="margin-top:12px">
      <div class="card-title">Monitor for — report immediately if observed</div>
      ${['Unusual bruising or petechiae','Black/tarry stools (melena)','Blood in urine (haematuria)','Prolonged bleeding from puncture sites','Sudden confusion or neurological change'].map(s=>`<div class="check-row"><input type="checkbox"> ${s}</div>`).join('')}
      <div style="margin-top:12px"><button class="btn btn-sec btn-sm" onclick="nav('n2')">Log in Escalation Form</button></div>
    </div>`;

  /* Labs tab */
  const labsHtml=`<div class="card"><div class="card-title">Recent Lab Results</div>
    <div class="tw" style="border:none"><table>
      <thead><tr><th>Time</th><th>Test</th><th>Result</th><th>Unit</th></tr></thead>
      <tbody>${(p.recentLabs||[]).map(l=>`<tr>
        <td class="muted">${l.time.split('T').join(' ').substring(0,16)}</td>
        <td>${l.test}</td><td style="font-weight:700">${l.value}</td><td class="muted">${l.unit}</td>
      </tr>`).join('')}
      ${(!p.recentLabs||p.recentLabs.length===0)?'<tr><td colspan="4" class="muted small" style="text-align:center;padding:20px">No recent labs.</td></tr>':''}
      </tbody></table></div></div>`;

  /* Meds tab */
  const medsHtml=`<div class="card"><div class="card-title">Active Medications</div>
    <div class="tw" style="border:none"><table>
      <thead><tr><th>Medication</th><th>Dose</th><th>Frequency</th></tr></thead>
      <tbody>${(p.medications||[]).map(m=>`<tr><td><b>${m.name}</b></td><td>${m.dose}</td><td class="muted">${m.frequency}</td></tr>`).join('')}
      ${(!p.medications||p.medications.length===0)?'<tr><td colspan="3" class="muted small" style="text-align:center;padding:20px">No active medications.</td></tr>':''}
      </tbody></table></div></div>`;

  /* ML Insights tab */
  const mlRiskCol=score>=7?'var(--t1)':score>=5?'var(--t2)':'var(--t3)';
  const mlContribs=(p.mlContributors||[]).map(c=>`<div class="ml-bar-row"><div class="ml-bar-lbl">${c.label}</div><div class="ml-bar"><div class="ml-bar-fill" style="width:${c.pct}%"></div></div><div class="ml-bar-pct">${c.pct}%</div></div>`).join('')||'<div class="muted small">No abnormal signals.</div>';
  const mlInsights=`<div class="alert al-info">🧪 <b>Illustrative</b> deterioration risk — predictive model in training (Sprint 4).</div>
    <div class="grid2">
      <div class="card"><div class="card-title">Deterioration Risk — Demo</div>
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:14px">
          <div class="ml-risk-num" style="color:${mlRiskCol}">${p.mlRisk!=null?p.mlRisk+'%':'—'}</div>
          <div><div style="font-size:13px;font-weight:600">${p.mlWindow||'6-12 hour'} window</div><div class="muted small">Heuristic demo</div></div>
        </div>${mlContribs}</div>
      <div class="card"><div class="card-title">What this means</div>
        <div style="font-size:13px;line-height:1.7">${p.mlExplanation||'—'}</div>
        <div class="card-title" style="margin-top:14px">Recommended action</div>
        <div style="font-size:13px;line-height:1.7">${p.recommendedAction||'—'}</div></div>
    </div>`;

  /* Vitals tab: trend → news2 card → instrument grid → history → DCM */
  const vitalsTab=`<div class="card" style="margin-bottom:16px">
    <div class="card-title">NEWS2 Trend — Last 6h <span class="muted small" style="font-weight:400">🔴 ≥7 · 🟡 ≥5</span></div>
    ${renderNews2Svg(p.recentVitals)}</div>
    ${news2Card}${vitalsGrid}${historyTable}${dcmCard}`;

  const tabContent=APP.n1b_tab==='ml'?mlInsights:APP.n1b_tab==='drug-lab'?druglab:APP.n1b_tab==='labs'?labsHtml:APP.n1b_tab==='meds'?medsHtml:vitalsTab;
  const sev=score>=7?'t1':score>=5?'t2':'t3';
  const sig=((p.ewsReason&&p.ewsReason.signals)||[]).map(s=>s.arrow+s.short).join('  ')||'✓ Stable';
  const locTag=p.ward_location==='GENERAL_WARD'?'loc-gw':'loc-ccu';
  const loc=p.ward_location==='GENERAL_WARD'?'General Ward':'CCU';

  return `
<div class="bc">
  <span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span>
  ${APP.role==='charge'?'<span class="bc-link" onclick="nav(\'n5\')">Escalation Queue</span><span class="bc-sep">/</span><span>Head Nurse Review</span>':'<span>Patient Detail</span>'}
</div>
<div class="sh">
  <h1 class="sh-title">${p.name||'Unknown'} <span class="pid" style="font-size:13px">${p.patient_code||'PT-'+(p.id||'')}</span></h1>
  <div class="sh-actions">
    <span class="bd ${bdClass}" style="font-size:12px;padding:5px 14px">NEWS2 ${score} — ${lbl}</span>
    ${score>=5?`<button class="btn ${isCrit?'btn-danger':'btn-warn'} btn-sm" onclick="nav('n2',${p.id})">Escalate Now</button>`:''}
  </div>
</div>
<div class="dx-banner sev-${sev}">
  <div><span class="dx-lbl">Diagnosis</span><b>${p.diagnosis_short||p.complaint||'—'}</b></div>
  <div><span class="dx-lbl">EWS Trigger</span><b>${sig}</b></div>
  <div><span class="dx-lbl">Ward · Bed</span><b>${p.ward||''} · Bed ${p.bed||''} <span class="loc-tag ${locTag}">${loc}</span></b></div>
  <div><span class="dx-lbl">Monitoring</span><b>${(p.monitoring&&p.monitoring.label)||'—'}${p.dueLabel?' · '+p.dueLabel:''}</b></div>
  <div><span class="dx-lbl">AI Risk <span class="demo-tag">demo</span></span><b style="color:var(--p)">${p.mlRisk!=null?p.mlRisk+'%':'—'}</b></div>
</div>
<div class="tab-strip">
  <button class="tab-btn${APP.n1b_tab==='vitals'||!APP.n1b_tab?' active':''}" onclick="APP.n1b_tab='vitals';renderAll()">Vital Signs</button>
  <button class="tab-btn${APP.n1b_tab==='ml'?' active':''}" onclick="APP.n1b_tab='ml';renderAll()">ML Insights</button>
  <button class="tab-btn${APP.n1b_tab==='drug-lab'?' active':''}" onclick="APP.n1b_tab='drug-lab';renderAll()">Drug-Lab Alerts</button>
  <button class="tab-btn${APP.n1b_tab==='labs'?' active':''}" onclick="APP.n1b_tab='labs';renderAll()">Lab Results</button>
  <button class="tab-btn${APP.n1b_tab==='meds'?' active':''}" onclick="APP.n1b_tab='meds';renderAll()">Medications</button>
</div>
${tabContent}
<div style="display:flex;gap:8px;margin-top:20px;flex-wrap:wrap">
  ${APP.role==='charge'
    ?`<button class="btn btn-sec btn-sm" onclick="nav('n5')">← Escalation Queue</button>
      <button class="btn btn-warn btn-sm" onclick="showFalseAlarmMenu()">Mark False Alarm ▾</button>
      ${score>=5?`<button class="btn btn-danger btn-sm" onclick="nav('n2',${p.id})">Escalate to Attending</button>`:''}`
    :`<button class="btn btn-sec btn-sm" onclick="nav('n1')">← Back to Dashboard</button>
      ${score>=5?`<button class="btn btn-danger btn-sm" onclick="nav('n2',${p.id})">Escalate Patient</button>`:''}`
  }
  ${p.ward_location==='CCU'?`<button class="btn btn-pri btn-sm" onclick="nav('n_transfer',${p.id})">CCU→GW Transfer →</button>`:''}
</div>
<div id="false-alarm-menu" style="display:none;margin-top:10px;background:var(--white);border:1px solid var(--border);border-radius:10px;padding:14px;max-width:420px">
  <div class="card-title" style="margin-bottom:8px">Reason for False Alarm</div>
  ${['Expected clinical variation','Data entry error','Post-procedure transient change','Medication effect','Other'].map(r=>`<button class="btn btn-sec btn-sm" style="margin:4px" onclick="submitFalseAlarm(${p.id},'${r}')">${r}</button>`).join('')}
</div>`;
};
```

**Complete `SCREENS.n_transfer` override** (two-column criteria + form):

```javascript
SCREENS.n_transfer = () => {
  const e=APP.data.n_transfer||{}, pid=APP.currentPatientId, pending=e.pendingTransfer;

  window.submitTransfer = async function() {
    const rationale=(document.getElementById('tr-rationale')?.value||'').trim();
    if(!rationale){alert('Please enter a clinical rationale.');return}
    const target=document.getElementById('tr-target')?.value||'General Ward';
    const btn=document.getElementById('tr-submit');
    if(btn){btn.disabled=true;btn.textContent='Submitting…'}
    try{
      const res=await fetch('/api/patients/'+pid+'/ccu-transfer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rationale,targetWard:target,recommendedBy:APP.user?APP.user.name:'Nurse'})});
      if(res.ok){nav('n_transfer',pid)}
      else{const d=await res.json().catch(()=>({}));alert('Could not submit: '+(d.detail||res.status));if(btn){btn.disabled=false;btn.textContent='Submit to Head Nurse →'}}
    }catch(err){alert('Network error: '+err.message);if(btn)btn.disabled=false}
  };
  window.withdrawTransfer = async function(tid) {
    if(!confirm('Withdraw this step-down recommendation?'))return;
    try{const res=await fetch('/api/ccu-transfers/'+tid+'/withdraw',{method:'POST'});if(res.ok)nav('n_transfer',pid)}
    catch(err){alert('Network error')}
  };

  const header=`<div class="bc"><span class="bc-link" onclick="nav('n1b',${pid})">Patient Detail</span><span class="bc-sep">/</span><span>CCU → GW Transfer</span></div>
  <div class="sh"><h1 class="sh-title">CCU → General Ward Step-Down</h1>
    <div class="sh-actions">${pending?'<span class="bd bd-t3" style="font-size:12px;padding:5px 14px">Submitted ✓</span>':e.eligible?'<span class="bd bd-t3" style="font-size:12px;padding:5px 14px">Eligible</span>':'<span class="bd bd-t2" style="font-size:12px;padding:5px 14px">Criteria Not Met</span>'}</div>
  </div>`;

  if(pending){return header+`
    <div class="alert al-ok">✅ Step-down recommendation submitted — Head Nurse review pending.</div>
    <div class="card" style="max-width:680px"><div class="card-title">Submitted Recommendation</div>
      <table style="width:100%;font-size:13px"><tbody>
        <tr><td class="muted">Patient</td><td class="bold">${e.name||''} <span class="pid">${e.patientCode||''}</span></td></tr>
        <tr><td class="muted">Diagnosis</td><td>${e.diagnosis||''}</td></tr>
        <tr><td class="muted">Transfer</td><td>CCU → ${pending.targetWard}</td></tr>
        <tr><td class="muted">NEWS2 at submit</td><td>${pending.news2AtSubmit}</td></tr>
        <tr><td class="muted">Stable window</td><td>${pending.stableWindowHours}h</td></tr>
        <tr><td class="muted">Recommended by</td><td>${pending.recommendedBy}</td></tr>
        <tr><td class="muted">Rationale</td><td>${pending.rationale}</td></tr>
        <tr><td class="muted">Submitted</td><td class="mono">${pending.submittedAt}</td></tr>
        <tr><td class="muted">Status</td><td><span class="bd bd-t2">Pending Head Nurse</span></td></tr>
      </tbody></table>
      <div style="display:flex;gap:8px;margin-top:16px">
        <button class="btn btn-sec" onclick="withdrawTransfer(${pending.id})">Withdraw</button>
        <button class="btn btn-pri" onclick="nav('n1')">← Dashboard</button>
      </div></div>`}

  const criteria=(e.criteria||[]).map(c=>{
    const state=c.met?'met':c.info?'info':'unmet';
    const icon=c.met?'✓':c.info?'!':'✗';
    return `<div class="criteria-row">
      <div class="criteria-icon ${state}">${icon}</div>
      <div class="criteria-body">
        <div class="criteria-lbl">${c.label}</div>
        <div class="criteria-detail">${c.detail||''}</div>
      </div></div>`;
  }).join('');

  return header+`
  ${e.eligible
    ?'<div class="transfer-ready-banner">✅ All step-down criteria met — ready to submit to Head Nurse.</div>'
    :'<div class="alert al-warn">⚠️ Step-down criteria not fully met. NEWS2 must be ≤ 2 sustained for 6h+.</div>'
  }
  <div class="transfer-layout">
    <div class="card">
      <div class="card-title">Step-Down Criteria</div>
      ${criteria||'<div class="muted small">No criteria available.</div>'}
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
        <div class="muted small">Patient: <b style="color:var(--ink)">${e.name||'—'} <span class="pid">${e.patientCode||''}</span></b></div>
        <div class="muted small" style="margin-top:4px">Current NEWS2: <b style="color:${e.news2>=7?'var(--t1)':e.news2>=5?'var(--t2)':'var(--t3)'}">${e.news2}</b> · Stable <b>${e.stableWindowHours}h</b></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Step-Down Recommendation Form</div>
      <div class="fg"><label class="fl">Transfer type</label><input class="fi" value="CCU → General Ward" readonly style="background:var(--surf);color:var(--muted)"></div>
      <div class="fg"><label class="fl">Target ward</label><select class="fi" id="tr-target"><option>General Ward</option><option>Step-Down Unit (HDU)</option></select></div>
      <div class="fg"><label class="fl">Recommending nurse</label><input class="fi" value="${APP.user?APP.user.name:'Nurse'}" readonly style="background:var(--surf);color:var(--muted)"></div>
      <div class="fg"><label class="fl">Clinical rationale <span style="color:var(--t1)">*</span></label>
        <textarea class="fi" id="tr-rationale" rows="4" placeholder="e.g. NEWS2 ≤ 2 sustained 8h+; haemodynamically stable; inotropes weaned.">${e.eligible?'NEWS2 ≤ 2 sustained '+(e.stableWindowHours||6)+'h; haemodynamically stable; no escalation in 24h.':''}</textarea>
      </div>
      <div style="display:flex;gap:10px;margin-top:4px">
        <button class="btn btn-sec" onclick="nav('n1b',${pid})">← Back</button>
        <button class="btn btn-pri" id="tr-submit" onclick="submitTransfer()" ${!e.eligible?'disabled style="opacity:0.5;cursor:not-allowed"':''}>Submit to Head Nurse →</button>
      </div>
      ${!e.eligible?'<div class="muted small" style="margin-top:8px">Locked until all criteria are met.</div>':''}
    </div>
  </div>`;
};
```

- [ ] **Step 2: Start the backend (if not running)**

```bash
cd sabari_project/backend
uvicorn main:app --reload --port 5175
```

Expected: `Application startup complete` in terminal.

- [ ] **Step 3: Open preview.html**

Navigate to `http://localhost:5175/preview.html`

Log in with nurse credentials (e.g., `ward_nurse` / `nurse123`).

- [ ] **Step 4: Verify dashboard (n1)**

Check each of these in the browser:

| Check | Expected |
|-------|----------|
| Stats cards | White cards, 5px left colored border (red/amber/green/grey), 40px numbers |
| Table rows | All white background — no red/amber row fills |
| Severity bars | Visible 5px colored inset on leftmost column of each row |
| Critical rows | Red bar on left, data still readable on white |
| NEWS2 column | Pill badges (red bg+white text for critical, amber for warning, green for stable) |
| Filter click | Clicking a stats card filters the table |

- [ ] **Step 5: Verify Patient Detail (n1b)**

Click any patient. Check:

| Check | Expected |
|-------|----------|
| NEWS2 trend chart | SVG chart visible above everything |
| NEWS2 card | Large 56px score number, colored, CRITICAL/WARNING/STABLE label |
| Vitals grid | 3×2 grid of vital cells, colored border-top, 28px value numbers |
| Abnormal vitals | Red/amber text on value AND cell border |
| Tab switching | Drug-Lab, Labs, Meds, ML tabs all render correctly |

- [ ] **Step 6: Verify CCU→GW Transfer (n_transfer)**

From a CCU patient detail, click "CCU→GW Transfer →". Check:

| Check | Expected |
|-------|----------|
| Layout | Two columns side by side (on desktop) |
| Criteria column | Each criterion has circular icon (green ✓, red ✗, amber !) |
| Form column | Transfer type, target ward, nurse, rationale, submit button |
| Ineligible | Submit button is disabled + muted |
| Eligible | Green banner "All step-down criteria met", submit button active |

- [ ] **Step 7: Verify mobile (resize to 768px)**

In DevTools, set viewport to 375px width. Check:
- Two-column layouts collapse to single column
- Stats cards go to 2×2 grid
- Vitals grid goes to 2-column
- Sidebar collapses (hamburger button appears)

- [ ] **Step 8: Commit**

```bash
git add sabari_project/preview.html docs/superpowers/plans/2026-06-21-careos-redesign-preview.md
git commit -m "feat: add Foqal CareOS redesign preview — severity bars, instrument vitals, two-column transfer"
```

---

## Self-Review

**Spec coverage:**
- ✅ Token system (colors, typography) — defined in CSS
- ✅ Dashboard severity bar system — `.row-crit td:first-child { box-shadow: inset 5px 0 0 var(--t1) }` + white row override
- ✅ Stats cards with 5px left border — `border-left-width: 5px !important`
- ✅ NEWS2 pill badge — `.n2s.hi/med/lo` with background + white text
- ✅ AVPU removed from dashboard table — not in column list; present in vitals grid
- ✅ Patient Detail instrument grid — `.vitals-grid` 3×2 with `.vital-cell`
- ✅ NEWS2 summary card above grid
- ✅ CCU→GW two-column layout — `.transfer-layout` grid
- ✅ Criteria icons — `.criteria-icon.met|unmet|info`
- ✅ Submit disabled when ineligible
- ✅ Mobile responsive — `@media (max-width: 768px)` collapses all two-column layouts
- ✅ All app shell IDs preserved
- ✅ No changes to `app.js`, `index.html`, `styles.css`

**No placeholders found.**

**Type consistency:** All CSS classes referenced in JS match definitions in the `<style>` block. `renderEwsReason()` and `renderNews2Svg()` are consumed from `app.js` without redefinition.

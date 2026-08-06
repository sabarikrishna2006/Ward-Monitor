# Foqal CareOS — Dashboard Redesign Spec

**Date:** 2026-06-21
**Surfaces:** Dashboard (n1), Patient Detail (n1b), CCU→GW Transfer (n_transfer)
**Deliverable:** Standalone `sabari_project/preview.html` — no changes to `index.html` or `app.js` until user approves
**Approach:** A — Elevated Table (refined clinical + clean and airy)

---

## Design Direction

Refined but breathable. Keep the functional density nurses rely on; reduce visual noise through lighter borders, more whitespace, and intentional use of brand color. The result should feel like a premium version of the existing tool, not a redesign that breaks mental models.

Brand color `#800080` is non-negotiable — used for primary actions, active states, and branding only (not as a background fill or table accent).

---

## Token System

### Colors
```
--p:        #800080   brand purple
--pl:       #faf5ff   purple ghost (hover, active sidebar bg)
--pm:       #a855f7   purple medium (focus rings)

--red:      #dc2626   critical severity
--red-bg:   #fff1f2   critical surface
--amber:    #d97706   warning severity
--amber-bg: #fffbeb   warning surface
--green:    #059669   stable severity
--green-bg: #f0fdf4   stable surface

--ink:      #0f172a   primary text
--ink2:     #475569   secondary text
--muted:    #94a3b8   labels, units, timestamps
--border:   #e8edf3   default borders (lighter than current)
--surf:     #f7f9fc   page background
--white:    #ffffff   card and table surfaces
```

### Typography
- **Font:** Inter (already loaded via Google Fonts)
- **Base size:** 14px (up from 13px — better legibility on hospital monitors)
- **Headlines:** Inter 800, `letter-spacing: -0.5px`
- **Body:** Inter 400/500
- **Vital values (Patient Detail):** Inter 700, 22px, `font-variant-numeric: tabular-nums`
- **Table column headers:** Inter 600, 11px uppercase, letter-spacing 0.5px
- **Codes / IDs:** Monospace only

---

## Signature Element

**The severity bar system.** Every patient row carries a `5px` solid left border in its NEWS2 severity color (red / amber / green) instead of the current full-row red/amber background fill. Rows stay white. A nurse can read the entire ward's severity state by scanning the left edge of the table — a faster visual path than hunting for colored rows. Critical rows additionally carry a subtle inset left shadow to ensure visibility even on low-contrast monitors.

This pattern applies consistently across the stats cards at the top of the dashboard and the criteria cards in the CCU→GW transfer screen.

---

## Surface 1 — Dashboard (n1)

### Stats Bar
- Four cards in a `4-column` grid (unchanged layout)
- Each card: `5px` left border in its severity color, white background, `40px` bold number, small uppercase label
- Cards are clickable filters — same behavior as current

### Table
**Columns (AVPU removed from main table view only — still present in Patient Detail):**
```
Patient | Diagnosis | SpO₂ | RR | BP | HR | Temp | NEWS2 | EWS Signal | Status | Actions
```
- AVPU is moved to Patient Detail (Vital Signs instrument grid) — it's rarely the sole escalation trigger and removing it from the table tightens each row without data loss
- Row background: white for all severity levels
- Row left border: `5px solid var(--red)` for critical, `5px solid var(--amber)` for warning, `5px solid var(--green)` for stable
- Critical rows additionally: `box-shadow: inset 5px 0 0 var(--red)` (extra visual weight without color fill)
- NEWS2 column: pill badge with colored background + white bold text
- Vital values: colored text only when abnormal (red for critical, amber for warning) — no background fill

### Behavior
- All current filter, sort, escalate, ack, and refresh behaviors preserved
- No structural changes to JS logic — only HTML template output changes

---

## Surface 2 — Patient Detail (n1b)

### Header Band
- Diagnosis banner stays — useful clinical summary
- Layout unchanged, typography elevated
- NEWS2 badge enlarged, severity color more prominent

### Tabs
- Same five tabs: Vital Signs, ML Insights, Drug-Lab Alerts, Lab Results, Medications
- Tab strip styling cleaned up — active tab uses `--p` underline + bold text

### Vital Signs Tab — Key Change
Replace the vitals table with a **3×2 instrument grid**:

```
[ SpO₂          ]  [ Resp Rate      ]  [ Blood Pressure ]
  94%   ⚠ LOW      24 /min  HIGH       88/60 mmHg

[ Heart Rate     ]  [ Temperature    ]  [ NEWS2 Score    ]
  112 bpm  HIGH     37.2 °C             9  CRITICAL
```

Each cell: white card, label top-left (11px muted), large value (22px bold), unit right of value (14px muted), flag below value (11px colored bold). Abnormal values get colored text. Normal values get `--ink` text.

NEWS2 trend chart stays above the grid (already SVG, just repositioned).
Vitals history table (last 6h) stays below as a compact secondary view.
DCM heart-failure card stays below history table.

### Other Tabs
- No layout changes — typography elevation only (Inter, 14px base, better spacing)

---

## Surface 3 — CCU → GW Transfer (n_transfer)

### Layout Change: Stacked → Two Columns

```
LEFT 40%                         RIGHT 60%
────────────────────────────────────────────────
Step-Down Criteria               Recommendation Form
  ✓ NEWS2 ≤ 2 (8h+)               Transfer type  [readonly]
  ✓ Haemodynamically stable        Target ward    [select]
  ✗ Inotropes weaned               Recommending   [readonly]
  ✓ No escalation 24h              Clinical rationale
                                   [textarea]

                                   [Submit button]
```

- Two-column layout collapses to stacked on mobile (≤768px) — consistent with existing mobile-responsive breakpoints
- Criteria card (left): each criterion is a row with met/not-met icon, label, and detail. Met = green check + `--green` text. Not met = red cross + `--red` text.
- When **all criteria are met**: green success banner appears above the form — "All step-down criteria met — ready to submit."
- When criteria are not met: Submit button is `disabled` with muted styling; no tooltip needed (the criteria card makes the reason obvious).
- Pending state (already submitted): same confirmation card, elevated typography.

---

## What Does Not Change

- All JavaScript logic, API calls, and data flow — `preview.html` imports `app.js` unchanged
- Sidebar structure, navigation tree, role-based routing
- Modal behavior
- Drug-Lab screens (dl1, dl3, dlcosign) — out of scope
- Escalation flow screens (n2, n3, n4, n4b, n5, n6) — out of scope for this pass
- Backend / FastAPI / SQLite — untouched

---

## Deliverable

Single file: `sabari_project/preview.html`
- Self-contained HTML with inline `<style>` block replacing `styles.css` rules
- Same `<script src="app.js">` import — all behavior preserved
- Must preserve all app shell element IDs that `app.js` binds to: `#app-shell`, `#main`, `#sidebar`, `#sidebar-wrap`, `#sidebar-overlay`, `#appbar`, `#hdr-role`, `#hdr-user`, `#hdr-ward`, `#topbar-line`, `#modal-overlay`, `#modal-box`
- User tests it at the same dev server URL, approves, then styles migrate to `styles.css` and `index.html`

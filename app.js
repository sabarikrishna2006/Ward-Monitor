/* ═══════════════════════════════════════════════════════════════
   Foqal CareOS · Ward Monitor — Production App
   Personas: Bedside Nurse · Charge Nurse
   Modules:  NEWS2 Early Warning · Drug-Lab Interactions
   ═══════════════════════════════════════════════════════════════ */

/* ─── GLOBAL STATE ─── */
const APP = {
  screen: null,
  role: null,
  user: null,
  history: [],

  /* screen-level sub-states */
  n1b_tab: 'vitals',   /* 'vitals' | 'drug-lab' */
  n5_state: 'active',  /* 'active' | 'empty'    */
  dl2_action: 'hold',  /* 'override' | 'hold' | 'pharmacist' */
  data: {},            /* Fetched data */
  currentPatientId: null,
};

/* ─── NAV TREE per role ─── */
const NAV = {
  nurse: [
    { id: 'n1',   label: 'NEWS2 Dashboard' },
    { id: 'n1b',  label: 'Patient Detail'  },
    { id: 'n2',   label: 'Escalation Form' },
    { id: 'n3',   label: 'Post-Escalation' },
    { id: 'n4',   label: 'Status Log'      },
    { id: 'n4b',  label: 'Post-Resolution' },
    { id: 'n6',   label: 'Shift Handoff'   },
    { id: 'n6b',  label: 'Handoff Complete'},
    { separator: true, label: 'Drug-Lab Awareness' },
    { id: 'dl3',  label: 'Active DL Flags' },
    { separator: true, label: 'Demo' },
    { id: 'n_demo_replay', label: 'Patient Arc Replay' },
  ],
  gw_nurse: [
    { id: 'n1',   label: 'GW Dashboard'    },
    { id: 'n1b',  label: 'Patient Detail'  },
    { id: 'n2',   label: 'Escalation Form' },
    { id: 'n4',   label: 'Status Log'      },
    { id: 'n6',   label: 'Shift Handoff'   },
    { separator: true, label: 'Drug-Lab Awareness' },
    { id: 'dl3',  label: 'Active DL Flags' },
    { separator: true, label: 'Demo' },
    { id: 'n_demo_replay', label: 'Patient Arc Replay' },
  ],
  charge: [
    { id: 'n5',   label: 'Escalation Queue' },
    { id: 'n5b',  label: 'Threshold Config' },
    { separator: true, label: 'Drug-Lab Co-Sign' },
    { id: 'dl1',  label: 'DL Flag Overview' },
    { id: 'dlcosign', label: 'Tier 1 Co-Sign' },
    { separator: true, label: 'Demo' },
    { id: 'n_demo_replay', label: 'Patient Arc Replay' },
  ]
};

/* ─── MOBILE SIDEBAR DRAWER ─── */
window.toggleSidebar = function() {
  const sw = document.getElementById('sidebar-wrap');
  const ov = document.getElementById('sidebar-overlay');
  if (!sw) return;
  const isOpen = sw.classList.toggle('open');
  if (ov) ov.classList.toggle('open', isOpen);
};

function closeSidebar() {
  const sw = document.getElementById('sidebar-wrap');
  const ov = document.getElementById('sidebar-overlay');
  if (sw) sw.classList.remove('open');
  if (ov) ov.classList.remove('open');
}

/* ─── NAVIGATION ─── */
async function nav(id, param = null) {
  closeSidebar();
  if (APP.screen && APP.screen !== id) APP.history.push(APP.screen);
  APP.screen = id;
  if (param !== null) APP.currentPatientId = param;

  try {
    if (id === 'n1') {
      // CCU nurse → CCU patients; GW nurse → General Ward; charge → all
      const loc = APP.role === 'nurse' ? 'CCU' : APP.role === 'gw_nurse' ? 'GENERAL_WARD' : 'All';
      const res = await fetch('/api/ward-data?location=' + loc);
      if (res.ok) APP.data.n1 = await res.json();
    } else if (id === 'dl1') {
      const res = await fetch('/api/ward-data?ward=All');
      if (res.ok) APP.data.n1 = await res.json();
    } else if ((id === 'n1b' || id === 'n2' || id === 'n4' || id === 'n4b') && APP.currentPatientId) {
      const res = await fetch(`/api/patients/${APP.currentPatientId}`);
      if (res.ok) APP.data.n1b = await res.json();
    } else if (id === 'n_vitals' && APP.currentPatientId) {
      try {
        const [pRes, vRes] = await Promise.all([
          fetch(`/api/patients/${APP.currentPatientId}`),
          fetch(`/api/patients/${APP.currentPatientId}/vitals/latest`)
        ]);
        if (pRes.ok) APP.data.n_vitals_patient = await pRes.json();
        if (vRes.ok) APP.data.n_vitals_latest = await vRes.json();
        else APP.data.n_vitals_latest = null;
      } catch { APP.data.n_vitals_latest = null; }
    } else if (id === 'n_transfer' && APP.currentPatientId) {
      const res = await fetch(`/api/patients/${APP.currentPatientId}/transfer-eligibility`);
      if (res.ok) APP.data.n_transfer = await res.json();
    } else if (id === 'n_demo_replay') {
      // Load DCM patient list for the picker; replay data loaded on patient selection
      const res = await fetch('/api/mimic/dcm-patients');
      if (res.ok) APP.data.n_demo_patients = (await res.json()).patients || [];
      APP.data.n_demo_replay = null;        // reset replay data
      APP.data.n_demo_frame = 0;
      APP.data.n_demo_playing = false;
    } else if (id === 'n5') {
      const [eRes, tRes] = await Promise.all([
        fetch('/api/escalations'),
        fetch('/api/ccu-transfers?status=pending')
      ]);
      if (eRes.ok) APP.data.n5 = await eRes.json();
      if (tRes.ok) APP.data.n5_transfers = await tRes.json();
      // 15-min SLA: auto re-escalate breached, unattended alerts (once each), then re-pull
      if (await autoReescalateBreaches()) {
        const r = await fetch('/api/escalations');
        if (r.ok) APP.data.n5 = await r.json();
      }
    }
    APP.lastRefresh = new Date();
  } catch (err) {
    console.error('Fetch error:', err);
  }

  renderAll();
  document.getElementById('main').scrollTop = 0;
}
function goBack() {
  const prev = APP.history.pop();
  if (prev) { APP.screen = prev; renderAll(); }
}

/* ─── AUTO-REFRESH (15 min) + AUTO RE-ESCALATION ─── */
let _refreshTimer = null;
const REFRESH_MS = 15 * 60 * 1000;          // 15-minute polling cadence
const REFRESHABLE = ['n1', 'n5', 'n1b', 'dl1'];   // read-only screens (never a form mid-entry)

function startAutoRefresh() {
  if (_refreshTimer) clearInterval(_refreshTimer);
  _refreshTimer = setInterval(() => refreshNow(true), REFRESH_MS);
}
function stopAutoRefresh() { if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; } }
async function refreshNow(auto) {
  if (!REFRESHABLE.includes(APP.screen)) return;   // do not clobber an open form
  await nav(APP.screen, APP.currentPatientId);
}

/* Auto-bump escalations that breached the 15-min SLA and were never re-escalated (once each). */
async function autoReescalateBreaches() {
  const escs = (APP.data.n5?.escalations || []).filter(e => e.slaBreached && !e.reescalatedAt && e.status === 'active');
  if (escs.length === 0) return false;
  for (const e of escs) {
    try {
      await fetch(`/api/escalations/${e.id}/reescalate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: '', auto: true })
      });
    } catch (_) { /* ignore */ }
  }
  return true;
}

/* ─── ACTIONS ─── */
window.ackPatient = function(event, patientId) {
  event.stopPropagation();
  if (APP.data.n1 && APP.data.n1.patients) {
    const p = APP.data.n1.patients.find(x => x.id == patientId);
    if (p) { p._acked = true; renderAll(); }
  }
}

window.showFalseAlarmMenu = function() {
  const menu = document.getElementById('false-alarm-menu');
  if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

window.submitFalseAlarm = async function(patientId, reason) {
  // Find the active escalation for this patient
  const escs = APP.data.n5 && APP.data.n5.escalations
    ? APP.data.n5.escalations.filter(e => e.patientId == patientId && e.status === 'active')
    : [];

  if (escs.length === 0) {
    alert('No active escalation found for this patient.');
    return;
  }
  const escId = escs[0].id;

  try {
    const res = await fetch(`/api/escalations/${escId}/false-alarm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
    if (res.ok) {
      alert(`Marked as false alarm: "${reason}"`);
      const menu = document.getElementById('false-alarm-menu');
      if (menu) menu.style.display = 'none';
      nav('n5');
    } else {
      alert('Failed to mark false alarm — check backend.');
    }
  } catch (e) { alert('Network error: ' + e.message); }
}

/* ─── LOGIN ─── */
/* Called by index.html after credentials are verified */
window.onFoqalLogin = function(user) {
  APP.role = user.role;   // 'nurse' (CCU) | 'gw_nurse' (General Ward) | 'charge' (Head Nurse)
  APP.user = {
    name:  user.name,
    role:  user.roleLabel,
    shift: user.shift,
    ward:  user.ward,
    empId: user.empId,
  };
  // Route to the correct first screen by role (charge → escalation queue; nurses → dashboard)
  nav(user.role === 'charge' ? 'n5' : 'n1');
  startAutoRefresh();   // 15-min data refresh + SLA re-check
};

function logout() {
  stopAutoRefresh();
  APP.role = null; APP.user = null; APP.screen = null; APP.history = [];
  sessionStorage.removeItem('foqal_token');
  sessionStorage.removeItem('foqal_user');
  document.documentElement.removeAttribute('data-authed');

  // Since Sabari's standalone login is completely removed, redirect to Ashmit's unified login
  const fromServer = (location.port === '5175' || location.port === '80' || location.port === '');
  if (fromServer) {
    window.location.href = `http://${location.hostname}:5180/`;
  } else {
    document.body.innerHTML = '<div style="padding:40px;text-align:center;font-family:sans-serif">Logged out.<br><br><a href="http://localhost:5180/">Go to Unified Login</a></div>';
  }
}

// Re-hydrate session on page refresh (if token still exists)
(function() {
  const raw = sessionStorage.getItem('foqal_user');
  if (!raw) {
    const fromServer = (location.port === '5175' || location.port === '80' || location.port === '');
    if (fromServer) {
      window.location.href = `http://${location.hostname}:5180/`;
    }
    return;
  }
  try {
    const user = JSON.parse(raw);
    const loginWrap = document.getElementById('login-wrap');
    if (loginWrap) loginWrap.style.display = 'none';
    document.getElementById('app-shell').style.display  = '';
    document.body.classList.remove('login-mode');
    window.onFoqalLogin(user);
  } catch(e) { /* ignore */ }
})();


/* ─── RENDER ENGINE ─── */
function renderAll() {
  renderSidebar();
  renderHeader();
  const fn = SCREENS[APP.screen];
  document.getElementById('main').innerHTML = fn
    ? fn()
    : `<div style="padding:60px;text-align:center;color:var(--muted)">Screen not found.</div>`;
}

function renderHeader() {
  const u = APP.user;
  document.getElementById('hdr-role').textContent  = u ? u.role  : '';
  document.getElementById('hdr-user').textContent  = u ? u.name  : '';
  document.getElementById('hdr-ward').textContent  = u ? u.ward  : '';
}

function renderSidebar() {
  const items = NAV[APP.role] || [];
  document.getElementById('sidebar').innerHTML = items.map(it => {
    if (it.separator) return `<div class="sb-sep">${it.label}</div>`;
    return `<div class="sb-item${APP.screen === it.id ? ' active' : ''}" onclick="nav('${it.id}')">${it.label}</div>`;
  }).join('');
}

/* ─── MODAL ─── */
function openModal(id) {
  const fn = MODALS[id];
  if (!fn) return;
  document.getElementById('modal-box').innerHTML = fn();
  document.getElementById('modal-overlay').classList.add('open');
}
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

const MODALS = {
  reescalate: () => `
    <div class="modal-t">Re-escalate Patient</div>
    <div class="modal-b">Priya Sharma (PT-24-0092) has not been attended within SLA. Re-escalate to a higher level?</div>
    <div class="fg"><label class="fl">Escalate to</label>
      <select class="fi"><option>On-call Consultant — Dr. Vikas Malhotra</option><option>Code Blue Team</option></select>
    </div>
    <div class="fg"><label class="fl">Reason for re-escalation</label>
      <textarea class="fi" rows="2">Attending response time exceeded 15 min SLA. NEWS2 remains critical at 9.</textarea>
    </div>
    <div class="modal-f">
      <button class="btn btn-sec" onclick="closeModal()">Cancel</button>
      <button class="btn btn-danger" onclick="closeModal()">Re-escalate Now</button>
    </div>`,
  cosign_confirm: () => `
    <div class="modal-t">Co-Sign Override Complete</div>
    <div class="modal-b" style="color:var(--t3)">✅ Override successfully co-signed and recorded in the NABH audit trail.</div>
    <div class="modal-f"><button class="btn btn-pri" onclick="closeModal();nav('dl1')">Back to DL Flags</button></div>`,
};

/* ═══════════════════════════════════════════════════════════════
   SCREENS
   ═══════════════════════════════════════════════════════════════ */
const SCREENS = {};

/* ── Plain-language EWS reason cell (colored vital arrows + flag + action) ── */
function sevColor(s) { return s === 'crit' ? 'var(--t1)' : s === 'warn' ? 'var(--t2)' : 'var(--muted)'; }

function renderEwsReason(p, compact) {
  const r = p.ewsReason || {};
  const signals = (r.signals || []).map(s =>
    `<span class="ews-sig" style="color:${sevColor(s.sev)}" title="${(s.plain||'').replace(/"/g,'')}">${s.arrow}${s.short}</span>`
  ).join('');
  const flag = r.flag
    ? `<div class="ews-flag" style="color:${sevColor(r.flag.sev)}" title="${(r.flag.text||'').replace(/"/g,'')}">&#128138; ${r.flag.text}</div>`
    : '';
  const toneCol = r.tone === 'crit' ? 'var(--t1)' : r.tone === 'warn' ? 'var(--t2)'
                 : r.tone === 'stable' ? 'var(--t3)' : 'var(--muted)';
  const action = r.action ? `<div class="ews-action" style="color:${toneCol}">&rarr; ${r.action}</div>` : '';
  const ok = (!signals && !flag) ? `<span class="ews-ok">&#10003; All parameters normal</span>` : '';
  const ai = (p.mlRisk != null && !compact)
    ? `<div class="ews-ai" title="Illustrative deterioration risk — predictive model in training (Sprint 4)">AI ${p.mlRisk}% <span class="demo-tag">demo</span></div>`
    : '';
  return `<div class="ews-cell">${signals ? `<div class="ews-sigs">${signals}</div>` : ''}${flag}${ok}${action}${ai}</div>`;
}

/* ── NEWS2 trend mini-chart (SVG) built from real recentVitals ── */
function renderNews2Svg(recent) {
  const pts = (recent || []).filter(r => typeof r.news2 === 'number');
  if (pts.length < 2) return '<div class="muted small" style="padding:14px 0">Not enough data for a trend.</div>';
  const W = 480, H = 92, pad = 22;
  const maxScore = Math.max(9, ...pts.map(p => p.news2));
  const x = i => pad + i * ((W - 2 * pad) / (pts.length - 1));
  const y = v => H - 16 - (v / maxScore) * (H - 30);
  const col = v => v >= 7 ? 'var(--t1)' : v >= 5 ? 'var(--t2)' : 'var(--t3)';
  const line = pts.map((p, i) => `${x(i).toFixed(0)},${y(p.news2).toFixed(0)}`).join(' ');
  const dots = pts.map((p, i) =>
    `<circle cx="${x(i).toFixed(0)}" cy="${y(p.news2).toFixed(0)}" r="3.5" fill="${col(p.news2)}"/>` +
    `<text x="${x(i).toFixed(0)}" y="${(y(p.news2) - 6).toFixed(0)}" font-size="9" fill="${col(p.news2)}" text-anchor="middle" font-weight="700">${p.news2}</text>`
  ).join('');
  const labels = pts.map((p, i) =>
    `<text x="${x(i).toFixed(0)}" y="${H - 2}" font-size="8" fill="var(--muted)" text-anchor="middle">${p.time}</text>`
  ).join('');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:92px;display:block">
    <line x1="0" y1="${y(7).toFixed(0)}" x2="${W}" y2="${y(7).toFixed(0)}" stroke="var(--t1)" stroke-width="1" stroke-dasharray="4,3" opacity="0.4"/>
    <line x1="0" y1="${y(5).toFixed(0)}" x2="${W}" y2="${y(5).toFixed(0)}" stroke="var(--t2)" stroke-width="1" stroke-dasharray="4,3" opacity="0.4"/>
    <text x="3" y="${(y(7) - 2).toFixed(0)}" font-size="8" fill="var(--t1)">&#8805;7</text>
    <text x="3" y="${(y(5) - 2).toFixed(0)}" font-size="8" fill="var(--t2)">&#8805;5</text>
    <polyline points="${line}" fill="none" stroke="var(--p)" stroke-width="2.5" stroke-linejoin="round"/>
    ${dots}${labels}
  </svg>`;
}

/* ── N1 — NEWS2 PRIORITY DASHBOARD ─────────────────────────── */
SCREENS.n1 = () => {
  const patients = (APP.data.n1?.patients || []);
  patients.sort((a, b) => b.news2 - a.news2); // Sort by highest acuity first
  let critCount = 0, medCount = 0, lowCount = 0, staleCount = 0;
  
  APP.n1_filter = APP.n1_filter || 'all';

  patients.forEach(p => {
    if (p.status === 'stale') staleCount++;
    else if (p.news2 >= 7) critCount++;
    else if (p.news2 >= 5) medCount++;
    else lowCount++;
  });

  const filteredPatients = patients.filter(p => {
    if (APP.n1_filter === 'critical') return p.news2 >= 7 && p.status !== 'stale';
    if (APP.n1_filter === 'medium') return p.news2 >= 5 && p.news2 < 7 && p.status !== 'stale';
    if (APP.n1_filter === 'low') return p.news2 < 5 && p.status !== 'stale';
    if (APP.n1_filter === 'stale') return p.status === 'stale';
    return true;
  });

  const nowStr = new Date().toLocaleString('en-IN', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'});

  return `
<div class="bc"><span>${APP.role==='gw_nurse'?'General Ward':APP.role==='nurse'?'CCU · Ward 4B/4C':'Ward 4B/4C'}</span><span class="bc-sep">/</span><span>NEWS2 Dashboard</span></div>
<div class="sh">
  <h1 class="sh-title">${APP.role==='gw_nurse'?'General Ward — NEWS2 Dashboard':APP.role==='nurse'?'CCU — NEWS2 Dashboard':'NEWS2 Priority Dashboard'}</h1>
  <div class="sh-actions">
    <span class="muted small">${APP.lastRefresh ? 'Updated ' + APP.lastRefresh.toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'}) + ' · auto 15m' : nowStr}</span>
    <button class="btn btn-sec btn-sm" onclick="refreshNow(false)" title="Refresh now">↻</button>
    ${APP.role === 'nurse' ? `<button class="btn btn-pri btn-sm" style="background:var(--p)" onclick="nav('n_transfer')">CCU GW Transfer</button>` : ''}
    <button class="btn btn-sec btn-sm" onclick="nav('n6')">Shift Handoff</button>
  </div>
</div>

<div class="stats">
  <div class="stat ${APP.n1_filter==='critical'?'active-filter':''}" style="border-left:3px solid var(--t1); cursor:pointer;" onclick="APP.n1_filter = APP.n1_filter==='critical' ? 'all' : 'critical'; renderAll()">
    <div class="stat-v" style="color:var(--t1)">${critCount}</div>
    <div class="stat-l">Critical ≥7</div>
  </div>
  <div class="stat ${APP.n1_filter==='medium'?'active-filter':''}" style="border-left:3px solid var(--t2); cursor:pointer;" onclick="APP.n1_filter = APP.n1_filter==='medium' ? 'all' : 'medium'; renderAll()">
    <div class="stat-v" style="color:var(--t2)">${medCount}</div>
    <div class="stat-l">Medium 5–6</div>
  </div>
  <div class="stat ${APP.n1_filter==='low'?'active-filter':''}" style="border-left:3px solid var(--t3); cursor:pointer;" onclick="APP.n1_filter = APP.n1_filter==='low' ? 'all' : 'low'; renderAll()">
    <div class="stat-v" style="color:var(--t3)">${lowCount}</div>
    <div class="stat-l">Low 1–4</div>
  </div>
  <div class="stat ${APP.n1_filter==='stale'?'active-filter':''}" style="cursor:pointer;" onclick="APP.n1_filter = APP.n1_filter==='stale' ? 'all' : 'stale'; renderAll()">
    <div class="stat-v" style="color:var(--muted)">${staleCount}</div>
    <div class="stat-l">Stale Vitals</div>
  </div>
</div>

<div class="tw"><table class="tbl-stack">
  <thead><tr>
    <th>Patient</th><th>Diagnosis</th><th>Ward</th><th>SpO₂ (%)</th><th>RR (/min)</th><th>BP (mmHg)</th>
    <th>HR (bpm)</th><th>Temp (°C)</th><th>AVPU</th><th>NEWS2</th><th>EWS Reason</th><th>Status</th><th>Actions</th>
  </tr></thead>
  <tbody>
    ${filteredPatients.map(p => {
      const isStale = p.status === 'stale';
      const score = p.news2 || 0;
      
      let rowClass = score >= 7 ? 'row-crit' : score >= 5 ? 'row-warn' : '';
      if (isStale) rowClass = 'stale'; // defined in css for faded row
      if (p._acked) rowClass += ' acked-row';

      const scoreClass = isStale ? 'muted' : score >= 7 ? 'n2s hi' : score >= 5 ? 'n2s med' : 'n2s lo';
      const statusBd = isStale ? 'bd bd-muted' : score >= 7 ? 'bd bd-t1' : score >= 5 ? 'bd bd-t2' : 'bd bd-t3';
      
      // Calculate stale minutes for UI
      const statusLbl = isStale ? 'Overdue' : score >= 7 ? 'Escalate' : score >= 5 ? 'Monitor' : 'Stable';
      
      const valCrit = (val, thres, op) => {
        if (!val || val === '--' || isStale) return '';
        if (op === '<' && val < thres) return 'v-crit';
        if (op === '>' && val > thres) return 'v-crit';
        return '';
      };
      
      const timeHtml = t => t ? `<br><span class="muted small">${t}</span>` : '';
      const bpVal = p.bp ? p.bp.split('/')[0] : '';
      
      // If stale, show dashes instead of old values
      const hr = isStale ? '-' : (p.hr || '-');
      const rr = isStale ? '-' : (p.rr || '-');
      const spo2 = isStale ? '-' : (p.spo2 || '-');
      const bp = isStale ? '-' : (p.bp || '-');
      const temp = isStale ? '-' : (p.temp || '-');
      const avpu = isStale ? '-' : (p.avpu || 'A');
      const s = isStale ? '-' : score;
      
      const ackBtn = p._acked ? '' : `<button class="btn btn-sec btn-xs" onclick="event.stopPropagation();ackPatient(event, ${p.id})">Ack</button>`;
      
      return `
        <tr class="${rowClass}" onclick="nav('n1b', ${p.id})">
          <td data-label="Patient"><b>${p.name}</b><br><span class="pid">${p.patient_code || 'PT-' + p.id}</span></td>
          <td data-label="Diagnosis" class="dx-cell">${p.diagnosis_short || '—'}</td>
          <td data-label="Ward">${p.ward.split(' ')[1] || p.ward}${p.ward_location === 'GENERAL_WARD' ? '<br><span class="loc-tag loc-gw">GW</span>' : '<br><span class="loc-tag loc-ccu">CCU</span>'}</td>
          <td data-label="SpO₂" class="${valCrit(p.spo2, 92, '<')}">${spo2} ${timeHtml(p.spo2_time)}</td>
          <td data-label="RR" class="${valCrit(p.rr, 21, '>')}">${rr} ${timeHtml(p.rr_time)}</td>
          <td data-label="BP" class="${valCrit(bpVal, 90, '<')}">${bp} ${timeHtml(p.bp_time)}</td>
          <td data-label="HR" class="${valCrit(p.hr, 110, '>')}">${hr} ${timeHtml(p.hr_time)}</td>
          <td data-label="Temp" class="${valCrit(p.temp, 38.0, '>')}">${temp} ${timeHtml(p.temp_time)}</td>
          <td data-label="AVPU">${avpu} ${timeHtml(p.avpu_time)}</td>
          <td data-label="NEWS2"><span class="${scoreClass}">${s}</span></td>
          <td data-label="EWS Reason" class="ews-reason-td">${renderEwsReason(p)}</td>
          <td data-label="Status"><span class="${statusBd}" style="${isStale?'color:var(--muted)':''}">${statusLbl.toUpperCase()}</span>${p.dueLabel ? `<div class="due-label ${p.isOverdue ? 'due-over' : ''}">${p.dueLabel}</div>` : ''}</td>
          <td data-label="Actions">
            ${isStale ?
              `<button class="btn btn-warn btn-xs" style="color:#000" onclick="event.stopPropagation();nav('n_vitals', ${p.id})">Enter Vitals</button>`
            :
              `${score >= 5 ? `<button class="btn ${score >= 7 ? 'btn-danger' : 'btn-warn'} btn-xs" onclick="event.stopPropagation();nav('n2', ${p.id})">Escalate</button>` : ''}
              ${ackBtn}`
            }
          </td>
        </tr>
      `;
    }).join('')}
  </tbody>
</table></div>`;
};

/* ── N1b — PATIENT DETAIL ───────────────────────────────────── */
SCREENS.n1b = () => {
  const p = APP.data.n1b || {};
  const v = p.vitals || {};
  const score = p.news2 || 0;
  const isCrit = score >= 7;
  const isWarn = score >= 5 && score < 7;
  const bdClass = isCrit ? 'bd-t1' : isWarn ? 'bd-t2' : 'bd-t3';
  const lbl = isCrit ? 'CRITICAL' : isWarn ? 'WARNING' : 'STABLE';

  const valCrit = (val, thres, op) => {
    if (!val) return '';
    if (op === '<' && val < thres) return 'v-crit';
    if (op === '>' && val > thres) return 'v-crit';
    return '';
  };

  // DCM heart-failure params (with data-source tags) + NEWS2 trend chart
  const dcmRow = (l, val, sev, f, src) => `<tr><td class="muted">${l} <span class="src-tag">(${src})</span></td><td class="bold" style="color:${sev==='crit'?'var(--t1)':sev==='warn'?'var(--t2)':'var(--ink)'}">${val}</td><td class="small" style="font-weight:600;color:${sev==='crit'?'var(--t1)':'var(--t2)'}">${f||''}</td></tr>`;
  const kLab = (p.recentLabs || []).find(l => l.test === 'Potassium');
  const kNum = kLab ? kLab.value : null;
  const kVal = kNum != null ? kNum + ' mmol/L' : '—';
  const kSev = kNum != null && (kNum < 3.5 || kNum > 5.5) ? 'crit' : (kNum != null && kNum > 5.0 ? 'warn' : '');
  const kFlag = kNum == null ? '' : kNum < 3.5 ? '↓ Low' : kNum > 5.5 ? '⚠ High' : kNum > 5.0 ? 'High-normal' : 'Normal';
  const hrNum = typeof p.hr === 'number' ? p.hr : parseInt(p.hr);
  const rhythm = isNaN(hrNum) ? '—' : hrNum > 100 ? 'Sinus tachycardia' : hrNum < 50 ? 'Bradycardia' : 'Sinus rhythm';
  const fb = p.fluidBalance;
  const trendSvg = `<div class="card" style="margin-bottom:14px"><div class="card-title">NEWS2 Trend — Last 6h <span class="muted small" style="font-weight:400">🔴 ≥7 · 🟡 ≥5</span></div>${renderNews2Svg(p.recentVitals)}</div>`;
  const dcmCard = `<div class="card" style="margin-top:14px">
      <div class="card-title">Heart-Failure Watch — DCM-specific</div>
      <table style="width:100%;font-size:12.5px"><tbody>
        ${dcmRow('Fluid Balance (24h)', fb != null ? (fb > 0 ? '+' : '') + fb + ' ml' : '—', fb > 500 ? 'crit' : fb > 0 ? 'warn' : '', fb > 0 ? '⚠ Positive (overload)' : fb != null ? 'Balanced' : '', 'manual / HIS')}
        ${dcmRow('Urine Output (4h)', p.urineOutput != null ? p.urineOutput + ' ml' : '—', p.urineOutput != null && p.urineOutput < 200 ? 'warn' : '', p.urineOutput != null && p.urineOutput < 200 ? '↓ Low output' : '', 'manual')}
        ${dcmRow('Serum K⁺ (last)', kVal, kSev, kFlag, 'lab / HIS')}
        ${dcmRow('Rhythm (from HR)', rhythm, '', '', 'monitor')}
      </tbody></table>
      <div class="muted small" style="margin-top:6px">Fluid status, urine output and K⁺ are the key bedside signals in decompensated heart failure.</div>
    </div>`;

  const vitals = trendSvg + `
    <div class="grid2">
      <div class="card">
        <div class="card-title">Current Vitals <span class="muted" style="font-weight:400;font-size:11px">${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
        <table style="width:100%;font-size:12.5px"><tbody>
          ${(() => {
            const sbp = p.bp ? parseInt(p.bp.split('/')[0]) : null;
            return [
            ['SpO₂',             (p.spo2 || '-') + '%' + (p.o2 === 'Oxygen' ? ' (on O₂)' : ''), valCrit(p.spo2, 92, '<'), p.spo2 < 92 ? '⚠ LOW' : (p.o2 === 'Oxygen' ? 'On oxygen' : '')],
            ['Respiratory Rate', (p.rr || '-') + ' /min',             valCrit(p.rr, 21, '>'), p.rr > 21 ? '⚠ HIGH' : ''],
            ['Blood Pressure',   (p.bp || '-/-') + ' mmHg',           valCrit(sbp, 90, '<'), (sbp && sbp < 90) ? '⚠ LOW' : ''],
            ['Heart Rate',       (p.hr || '-') + ' bpm',              valCrit(p.hr, 110, '>'), p.hr > 110 ? '⚠ HIGH' : ''],
            ['Temperature',      (p.temp || '-') + '°C',              valCrit(p.temp, 38.0, '>'), p.temp > 38.0 ? '⚠ ELEVATED' : ''],
            ['AVPU',             p.avpu || 'A',                       (p.avpu && p.avpu !== 'A') ? 'v-crit' : '', (p.avpu && p.avpu !== 'A') ? ('⚠ ' + ({C:'Confused',V:'Voice',P:'Pain',U:'Unresponsive'}[p.avpu] || p.avpu)) : ''],
            ['NEWS2 Score',      score,                  isCrit ? 'v-crit' : '', isCrit ? '🔴 CRITICAL' : ''],
          ] })().map(([lbl,val,cls,f]) => `
            <tr>
              <td class="muted">${lbl}</td>
              <td class="${cls}" style="font-weight:700">${val}</td>
              <td style="font-size:11px;font-weight:600;color:var(--t1)">${f}</td>
            </tr>`).join('')}
        </tbody></table>
      </div>
      <div class="card">
        <div class="card-title">Vitals Trend — Last 6 Hours</div>
        <div class="tw" style="border:none"><table>
          <thead><tr><th>Time</th><th>SpO₂</th><th>RR</th><th>BP</th><th>HR</th><th>NEWS2</th></tr></thead>
          <tbody>
            ${(p.recentVitals || []).map(t => {
              const bpStr = t.sbp && t.dbp ? t.sbp + '/' + t.dbp : '--/--';
              return `
              <tr>
                <td class="muted">${t.time}</td>
                <td class="${valCrit(t.spo2, 92, '<')}">${t.spo2}%</td>
                <td class="${valCrit(t.rr, 21, '>')}">${t.rr}</td>
                <td class="${valCrit(t.sbp, 90, '<')}">${bpStr}</td>
                <td class="${valCrit(t.hr, 110, '>')}">${t.hr}</td>
                <td class="${t.news2 >= 5 ? 'v-crit' : ''}">${t.news2}</td>
              </tr>
            `}).join('')}
            ${(!p.recentVitals || p.recentVitals.length === 0) ? `<tr><td colspan="6" class="muted small text-center" style="padding: 20px">No recent vitals recorded.</td></tr>` : ''}
          </tbody>
        </table></div>
      </div>
    </div>` + dcmCard;

  // ── ML Insights (DEMO placeholder — predictive model in training) ──
  const mlContribs = (p.mlContributors || []).map(c =>
    `<div class="ml-bar-row"><div class="ml-bar-lbl">${c.label}</div><div class="ml-bar"><div class="ml-bar-fill" style="width:${c.pct}%"></div></div><div class="ml-bar-pct">${c.pct}%</div></div>`
  ).join('') || '<div class="muted small">No abnormal signals contributing.</div>';
  const mlRiskCol = score >= 7 ? 'var(--t1)' : score >= 5 ? 'var(--t2)' : 'var(--t3)';
  const mlInsights = `
    <div class="alert al-info">🧪 <b>Illustrative</b> deterioration risk — the predictive model is in training (Sprint 4). These values are placeholders for demonstration and will be replaced by the trained model's output.</div>
    <div class="grid2">
      <div class="card">
        <div class="card-title">Deterioration Risk — Demo Prediction</div>
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:12px">
          <div class="ml-risk-num" style="color:${mlRiskCol}">${p.mlRisk != null ? p.mlRisk + '%' : '—'}</div>
          <div><div style="font-size:12.5px;font-weight:600">${p.mlWindow || '6-12 hour'} deterioration window</div>
          <div class="muted small">Heuristic demo · recomputed on each vitals entry</div></div>
        </div>
        <b class="small">Top contributing signals (from NEWS2):</b>
        <div style="margin-top:8px">${mlContribs}</div>
      </div>
      <div class="card">
        <div class="card-title">What this means</div>
        <div class="small" style="line-height:1.7">${p.mlExplanation || '—'}</div>
        <div class="card-title" style="margin-top:14px">Recommended action</div>
        <div class="small" style="line-height:1.7">${p.recommendedAction || '—'}</div>
      </div>
    </div>`;

  const dlAlerts = p.drugLabAlerts || [];
  const druglab = dlAlerts.length === 0
    ? `<div class="alert al-ok">No active drug-lab interaction flags for this patient.</div>`
    : `<div class="alert al-info">Nurse awareness only — clinical actions are taken by the Attending Physician. Log any adverse observations in the escalation form.</div>
    ${dlAlerts.map(a => {
      const tier = a.severity === 'CRITICAL' ? 't1' : 't2';
      const badge = a.severity === 'CRITICAL' ? 'bd-t1' : 'bd-t2';
      return `<div class="dlf ${tier}" style="margin-bottom:10px"><div class="dlf-bd">
        <div class="flex-r"><div class="dlf-title">&#9888; ${a.rule_name || a.severity}</div><span class="bd ${badge}">${a.severity}</span></div>
        <div class="dlf-desc"><b>Alert:</b> ${a.message}<br><b>Action:</b> ${a.action || ''}</div>
        <div style="margin-top:6px;font-size:11px;color:var(--muted)">${a.guideline || ''}</div>
      </div></div>`;
    }).join('')}
    <div class="card" style="margin-top:12px">
      <div class="card-title">Monitor for — report immediately if observed</div>
      ${['Unusual bruising or petechiae','Black/tarry stools (melena)','Blood in urine (haematuria)','Prolonged bleeding from puncture sites','Sudden confusion or neurological change'].map(s=>`<div class="check-row"><input type="checkbox"> ${s}</div>`).join('')}
      <div style="margin-top:12px"><button class="btn btn-sec btn-sm" onclick="nav('n2')">Log in Escalation Form</button></div>
    </div>
    <div style="margin-top:10px;padding:10px 0;border-top:1px solid var(--border)">
      ${APP.role === 'nurse' ? `<div class="muted small" style="margin-bottom:8px">Nurse view — read only. Attending resolution required.</div>` : ''}
      <button class="btn btn-sec btn-sm" onclick="nav('${APP.role === 'charge' ? 'dl1' : 'dl3'}', ${p.id})">View Drug-Lab Details →</button>
    </div>`;

  const labsHtml = `
    <div class="card">
      <div class="card-title">Recent Lab Results</div>
      <div class="tw" style="border:none"><table>
        <thead><tr><th>Time</th><th>Test</th><th>Result</th><th>Unit</th></tr></thead>
        <tbody>
          ${(p.recentLabs || []).map(l => `
            <tr>
              <td class="muted">${l.time.split('T').join(' ').substring(0,16)}</td>
              <td>${l.test}</td>
              <td style="font-weight:bold">${l.value}</td>
              <td class="muted">${l.unit}</td>
            </tr>
          `).join('')}
          ${(!p.recentLabs || p.recentLabs.length === 0) ? `<tr><td colspan="4" class="muted small text-center" style="padding: 20px">No recent labs.</td></tr>` : ''}
        </tbody>
      </table></div>
    </div>`;

  const medsHtml = `
    <div class="card">
      <div class="card-title">Active Medications</div>
      <div class="tw" style="border:none"><table>
        <thead><tr><th>Medication</th><th>Dose</th><th>Frequency</th></tr></thead>
        <tbody>
          ${(p.medications || []).map(m => `
            <tr>
              <td><b>${m.name}</b></td>
              <td>${m.dose}</td>
              <td class="muted">${m.frequency}</td>
            </tr>
          `).join('')}
          ${(!p.medications || p.medications.length === 0) ? `<tr><td colspan="3" class="muted small text-center" style="padding: 20px">No active medications.</td></tr>` : ''}
        </tbody>
      </table></div>
    </div>`;

  return `
<div class="bc">
  <span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span>
  <span class="bc-sep">/</span>
  ${APP.role === 'charge' ? '<span class="bc-link" onclick="nav(\'n5\')">Escalation Queue</span><span class="bc-sep">/</span><span>Head Nurse Review</span>' : '<span>Patient Detail</span>'}
</div>
<div class="sh">
  <h1 class="sh-title">${p.name || 'Unknown'} <span class="pid" style="font-size:13px">${p.patient_code || 'PT-' + (p.id || '')}</span></h1>
  <div class="sh-actions">
    <span class="bd ${bdClass}" style="font-size:12px;padding:5px 12px">NEWS2: ${score} — ${lbl}</span>
    ${score >= 5 ? `<button class="btn ${isCrit ? 'btn-danger' : 'btn-warn'} btn-sm" onclick="nav('n2', ${p.id})">Escalate Now</button>` : ''}
  </div>
</div>

${(() => {
  const sev = score >= 7 ? 't1' : score >= 5 ? 't2' : 't3';
  const sig = ((p.ewsReason && p.ewsReason.signals) || []).map(s => s.arrow + s.short).join('  ') || '✓ Stable';
  const loc = p.ward_location === 'GENERAL_WARD' ? 'General Ward' : 'CCU';
  const locTag = p.ward_location === 'GENERAL_WARD' ? 'loc-gw' : 'loc-ccu';
  return `<div class="dx-banner sev-${sev}">
    <div><span class="dx-lbl">Diagnosis</span><b>${p.diagnosis_short || p.complaint || '—'}</b></div>
    <div><span class="dx-lbl">EWS Trigger</span><b>${sig}</b></div>
    <div><span class="dx-lbl">Ward · Bed</span><b>${p.ward || ''} · Bed ${p.bed || ''} <span class="loc-tag ${locTag}">${loc}</span></b></div>
    <div><span class="dx-lbl">Monitoring</span><b>${(p.monitoring && p.monitoring.label) || '—'}${p.dueLabel ? ' · ' + p.dueLabel : ''}</b></div>
    <div><span class="dx-lbl">AI risk <span class="demo-tag">demo</span></span><b style="color:var(--p)">${p.mlRisk != null ? p.mlRisk + '%' : '—'}</b></div>
  </div>`;
})()}

<div class="tab-strip">
  <button class="tab-btn${APP.n1b_tab==='vitals'?' active':''}" onclick="APP.n1b_tab='vitals';renderAll()">Vital Signs</button>
  <button class="tab-btn${APP.n1b_tab==='ml'?' active':''}" onclick="APP.n1b_tab='ml';renderAll()">ML Insights</button>
  <button class="tab-btn${APP.n1b_tab==='drug-lab'?' active':''}" onclick="APP.n1b_tab='drug-lab';renderAll()">Drug-Lab Alerts</button>
  <button class="tab-btn${APP.n1b_tab==='labs'?' active':''}" onclick="APP.n1b_tab='labs';renderAll()">Lab Results</button>
  <button class="tab-btn${APP.n1b_tab==='meds'?' active':''}" onclick="APP.n1b_tab='meds';renderAll()">Medications</button>
</div>

${APP.n1b_tab === 'ml' ? mlInsights : APP.n1b_tab === 'drug-lab' ? druglab : APP.n1b_tab === 'labs' ? labsHtml : APP.n1b_tab === 'meds' ? medsHtml : vitals}

<div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
  ${APP.role === 'charge' ? `
    <button class="btn btn-sec btn-sm" onclick="nav('n5')">← Back to Escalation Queue</button>
    <button class="btn btn-warn btn-sm" onclick="showFalseAlarmMenu()">Mark False Alarm ▾</button>
    ${score >= 5 ? `<button class="btn btn-danger btn-sm" onclick="nav('n2', ${p.id})">Escalate to Attending</button>` : ''}
  ` : `
    <button class="btn btn-sec btn-sm" onclick="nav('n1')">← Back to Dashboard</button>
    ${score >= 5 ? `<button class="btn btn-danger btn-sm" onclick="nav('n2', ${p.id})">Escalate Patient</button>` : ''}
  `}
  ${p.ward_location === 'CCU' ? `<button class="btn btn-pri btn-sm" style="background:var(--p)" onclick="nav('n_transfer', ${p.id})">CCU→GW Transfer →</button>` : ''}
</div>
<div id="false-alarm-menu" style="display:none;margin-top:8px;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;max-width:400px">
  <div class="card-title" style="margin-bottom:8px">Reason for False Alarm</div>
  ${['Expected clinical variation','Data entry error','Post-procedure transient change','Medication effect','Other'].map(r =>
    `<button class="btn btn-sec btn-sm" style="margin:4px;display:inline-block" onclick="submitFalseAlarm(${p.id}, '${r}')">${r}</button>`
  ).join('')}
</div>`;
};

/* ── N_TRANSFER — CCU → GENERAL WARD STEP-DOWN ──────────────── */
SCREENS.n_transfer = () => {
  const e = APP.data.n_transfer || {};
  const pid = APP.currentPatientId;
  const pending = e.pendingTransfer;

  window.submitTransfer = async function() {
    const rationale = (document.getElementById('tr-rationale')?.value || '').trim();
    if (!rationale) { alert('Please enter a clinical rationale.'); return; }
    const target = document.getElementById('tr-target')?.value || 'General Ward';
    const btn = document.getElementById('tr-submit'); if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
    try {
      const res = await fetch(`/api/patients/${pid}/ccu-transfer`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rationale, targetWard: target, recommendedBy: APP.user ? APP.user.name : 'Nurse' })
      });
      if (res.ok) { nav('n_transfer', pid); }
      else { const d = await res.json().catch(() => ({})); alert('Could not submit: ' + (d.detail || res.status)); if (btn) { btn.disabled = false; btn.textContent = 'Submit to Head Nurse →'; } }
    } catch (err) { alert('Network error: ' + err.message); if (btn) { btn.disabled = false; } }
  };
  window.withdrawTransfer = async function(tid) {
    if (!confirm('Withdraw this step-down recommendation?')) return;
    try { const res = await fetch(`/api/ccu-transfers/${tid}/withdraw`, { method: 'POST' }); if (res.ok) nav('n_transfer', pid); }
    catch (err) { alert('Network error'); }
  };

  const header = `<div class="bc"><span class="bc-link" onclick="nav('n1b', ${pid})">Patient Detail</span><span class="bc-sep">/</span><span>CCU&rarr;GW Transfer</span></div>
  <div class="sh"><h1 class="sh-title">CCU → General Ward Step-Down</h1><div class="sh-actions">${pending ? '<span class="bd bd-t3">Submitted ✓</span>' : (e.eligible ? '<span class="bd bd-t3">Eligible</span>' : '<span class="bd bd-t2">Criteria not fully met</span>')}</div></div>`;

  if (pending) {
    return header + `
      <div class="alert al-ok">✅ Step-down recommendation submitted — Head Nurse review pending. Patient remains in CCU until approval.</div>
      <div class="card" style="max-width:660px"><div class="card-title">Submitted Recommendation</div>
      <table style="width:100%;font-size:12.5px"><tbody>
        <tr><td class="muted">Patient</td><td class="bold">${e.name || ''} <span class="pid">${e.patientCode || ''}</span></td></tr>
        <tr><td class="muted">Diagnosis</td><td>${e.diagnosis || ''}</td></tr>
        <tr><td class="muted">Transfer</td><td>CCU → ${pending.targetWard}</td></tr>
        <tr><td class="muted">NEWS2 at submit</td><td>${pending.news2AtSubmit}</td></tr>
        <tr><td class="muted">Stable window</td><td>${pending.stableWindowHours}h</td></tr>
        <tr><td class="muted">Recommended by</td><td>${pending.recommendedBy}</td></tr>
        <tr><td class="muted">Rationale</td><td>${pending.rationale}</td></tr>
        <tr><td class="muted">Submitted</td><td class="mono">${pending.submittedAt}</td></tr>
        <tr><td class="muted">Status</td><td><span class="bd bd-t2">Pending Head Nurse</span></td></tr>
      </tbody></table>
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn btn-sec" onclick="withdrawTransfer(${pending.id})">Withdraw Recommendation</button>
        <button class="btn btn-pri" onclick="nav('n1', ${pid})">← Back to Dashboard</button>
      </div></div>`;
  }

  const criteria = (e.criteria || []).map(c => {
    const col = c.met ? 'var(--t3)' : (c.info ? 'var(--t2)' : 'var(--t1)');
    const mark = c.met ? '✓ Met' : (c.info ? '⚠ ' + (c.detail || '') : '✗ Not met');
    return `<tr><td style="padding:5px 0">${c.label}<div class="muted small">${c.detail || ''}</div></td><td style="text-align:right;font-weight:700;color:${col};white-space:nowrap;vertical-align:top">${mark}</td></tr>`;
  }).join('');

  return header + `
    ${e.eligible ? '<div class="alert al-ok">✅ Step-down criteria met — you can submit this recommendation to the Head Nurse.</div>' : '<div class="alert al-warn">⚠️ Not all step-down criteria are met. NEWS2 must be ≤ 2 sustained for 6h+ before transfer.</div>'}
    <div class="grid2" style="margin-bottom:14px">
      <div class="card"><div class="card-title">Step-Down Criteria (computed live)</div>
        <table style="width:100%;font-size:12.5px"><tbody>${criteria}</tbody></table>
      </div>
      <div class="card"><div class="card-title">Patient Summary</div>
        <table style="width:100%;font-size:12.5px"><tbody>
          <tr><td class="muted">Patient</td><td class="bold">${e.name || ''} <span class="pid">${e.patientCode || ''}</span></td></tr>
          <tr><td class="muted">Diagnosis</td><td>${e.diagnosis || ''}</td></tr>
          <tr><td class="muted">Current location</td><td>${e.wardLocation === 'GENERAL_WARD' ? 'General Ward' : 'CCU'} · Bed ${e.bed || ''}</td></tr>
          <tr><td class="muted">Admitted</td><td>${e.admitted || ''}</td></tr>
          <tr><td class="muted">Current NEWS2</td><td class="bold">${e.news2}</td></tr>
          <tr><td class="muted">Stable window</td><td>${e.stableWindowHours}h</td></tr>
        </tbody></table>
      </div>
    </div>
    <div class="card" style="margin-bottom:14px"><div class="card-title">Step-Down Recommendation Form</div>
      <div class="frow">
        <div class="fg"><label class="fl">Transfer type</label><input class="fi" value="CCU → General Ward" readonly style="background:var(--surf)"></div>
        <div class="fg"><label class="fl">Target ward</label><select class="fi" id="tr-target"><option>General Ward</option><option>Step-Down Unit (HDU)</option></select></div>
      </div>
      <div class="fg"><label class="fl">Recommending nurse</label><input class="fi" value="${APP.user ? APP.user.name : 'Nurse'}" readonly style="background:var(--surf)"></div>
      <div class="fg"><label class="fl">Clinical rationale <span style="color:var(--t1)">*</span></label>
        <textarea class="fi" id="tr-rationale" rows="3" placeholder="e.g. NEWS2 ≤2 sustained 8h+; haemodynamically stable; inotropes weaned; no escalation in 24h.">${e.eligible ? 'NEWS2 ≤ 2 sustained ' + (e.stableWindowHours || 6) + 'h; haemodynamically stable; no escalation in 24h.' : ''}</textarea>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-pri" id="tr-submit" onclick="submitTransfer()" ${e.eligible ? '' : 'disabled title="Criteria not met"'}>Submit to Head Nurse →</button>
        <button class="btn btn-sec" onclick="nav('n1b', ${pid})">Cancel</button>
      </div>
    </div>`;
};

/* ── N2 — ESCALATION FORM ───────────────────────────────────── */
SCREENS.n2 = () => {
  const p = APP.data.n1b || {};
  const v = p.vitals || {};
  const score = p.news2 || 0;
  
  // Submit function to API — saves response to APP.data.lastEscalation for N3 screen
  window.submitEscalation = async function() {
    const lvlEl = document.querySelector('input[name="lvl"]:checked');
    const level = lvlEl ? lvlEl.value : 'doctor';
    const attending = document.getElementById('esc-attending').value;
    const observations = document.getElementById('esc-obs').value;
    const interventions = document.getElementById('esc-int').value;

    const payload = {
      patientId: APP.currentPatientId,
      level, attending, observations, interventions,
      escalatedBy: APP.user ? APP.user.name : 'Nurse'
    };

    try {
      const res = await fetch('/api/escalations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        APP.data.lastEscalation = await res.json();
        nav('n3');
      } else {
        alert('Failed to submit escalation — please check backend is running.');
      }
    } catch(e) { console.error(e); alert('Network error: ' + e.message); }
  };

  return `
<div class="bc"><span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span><span>Escalation</span></div>
<div class="sh"><h1 class="sh-title">Raise Escalation — ${p.patient_code || 'PT-' + p.id}</h1></div>
<div class="alert al-err">🔴 NEWS2 Score: ${score} — CRITICAL · ${p.name} · ${p.ward}</div>

<div style="max-width:580px">
  <div class="card" style="margin-bottom:12px">
    <div class="card-title">Vitals at Time of Escalation</div>
    <div class="grid3">
      <div><div class="muted small">SpO₂</div><div class="bold v-crit">${p.spo2||'-'}%</div></div>
      <div><div class="muted small">RR</div><div class="bold v-crit">${p.rr||'-'} /min</div></div>
      <div><div class="muted small">BP</div><div class="bold v-crit">${p.bp||'-/-'}</div></div>
      <div><div class="muted small">HR</div><div class="bold v-crit">${p.hr||'-'} bpm</div></div>
      <div><div class="muted small">Temp</div><div class="bold">${p.temp||'-'}°C</div></div>
      <div><div class="muted small">AVPU</div><div class="bold">A</div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Escalation Details</div>
    <div class="fg"><label class="fl">Escalation Level</label>
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:4px">
        <label class="radio-row"><input type="radio" name="lvl" value="nurse"> Nurse-to-Nurse (Senior Nurse)</label>
        <label class="radio-row"><input type="radio" name="lvl" value="doctor" checked> Nurse-to-Doctor (Attending)</label>
        <label class="radio-row"><input type="radio" name="lvl" value="code_blue"> Code Blue (Cardiac Arrest Team)</label>
      </div>
    </div>
    <div class="fg"><label class="fl">Attending to Notify</label>
      <select class="fi" id="esc-attending">
        <option value="Dr. Anand Sharma">Dr. Anand Sharma (On-call, Cardiology)</option>
        <option value="Dr. Priya Mehta">Dr. Priya Mehta</option>
        <option value="Dr. Deepak Rao">Dr. Deepak Rao</option>
      </select>
    </div>
    <div class="fg"><label class="fl">Clinical Observations</label>
      <textarea class="fi" id="esc-obs" rows="3">Patient increasingly short of breath, oxygen requirement escalating. Responsive to voice but lethargic.</textarea>
    </div>
    <div class="fg"><label class="fl">Interventions Already Taken</label>
      <textarea class="fi" id="esc-int" rows="2">O₂ titrated. Head of bed elevated 45°.</textarea>
    </div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-sec" onclick="nav('n1')">Cancel</button>
      <button class="btn btn-danger" onclick="submitEscalation()">Submit Escalation →</button>
    </div>
  </div>
</div>`;
};

/* ── N3 — POST-ESCALATION (shows real submitted escalation) ─── */
SCREENS.n3 = () => {
  const e = APP.data.lastEscalation || {};
  const p = APP.data.n1b || {};
  const v = p.vitals || {};
  const hasData = !!e.id;
  return `
<div class="bc"><span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span><span>Escalation Recorded</span></div>
<div class="sh"><h1 class="sh-title">Escalation Recorded</h1></div>
<div class="alert al-ok">Escalation submitted · ${hasData ? e.escalatedAt : new Date().toLocaleString('en-IN')} · ${hasData ? e.attending : 'Attending'} notified via secure pager</div>

<div class="card" style="max-width:560px;margin-bottom:16px">
  <div class="card-title">Escalation Summary</div>
  <div class="tw" style="border:none"><table><tbody>
    <tr><td class="muted">Patient</td><td class="bold">${hasData ? e.patientName : (p.name || 'Unknown')}</td></tr>
    <tr><td class="muted">Ward / Bed</td><td>${hasData ? (e.ward + ' / ' + e.bed) : (p.ward || '--')}</td></tr>
    <tr><td class="muted">NEWS2 at escalation</td><td><span class="n2s hi">${hasData ? e.news2 : (p.news2 || '--')}</span></td></tr>
    <tr><td class="muted">Attending notified</td><td>${hasData ? e.attending : '--'}</td></tr>
    <tr><td class="muted">Escalated at</td><td class="mono">${hasData ? e.escalatedAt : '--'}</td></tr>
    <tr><td class="muted">Reference ID</td><td class="mono">ESC-${hasData ? String(e.id).padStart(4,'0') : '----'}</td></tr>
  </tbody></table></div>
</div>

${p.spo2 ? `<div class="card" style="max-width:560px;margin-bottom:16px">
  <div class="card-title">Vitals at Time of Escalation</div>
  <div class="grid3">
    <div><div class="muted small">SpO2</div><div class="bold ${(p.spo2||99)<92?'v-crit':''}">` + (p.spo2||'--') + `%</div></div>
    <div><div class="muted small">RR</div><div class="bold">` + (p.rr||'--') + ` /min</div></div>
    <div><div class="muted small">BP</div><div class="bold">` + (p.bp||'--') + `</div></div>
    <div><div class="muted small">HR</div><div class="bold">` + (p.hr||'--') + ` bpm</div></div>
    <div><div class="muted small">Temp</div><div class="bold">` + (p.temp||'--') + `&deg;C</div></div>
    <div><div class="muted small">AVPU</div><div class="bold">A</div></div>
  </div>
</div>` : ''}
<div style="display:flex;gap:8px">
  <button class="btn btn-sec" onclick="nav('n4')">View Status Log</button>
  <button class="btn btn-pri" onclick="nav('n1')">Back to Dashboard</button>
</div>`;
};

/* ── N4 — STATUS LOG ────────────────────────────────────────── */
SCREENS.n4 = () => `
<div class="bc"><span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span><span>Escalation Status</span></div>
<div class="sh">
  <h1 class="sh-title">Escalation Status — PT-24-0092</h1>
  <div class="sh-actions">
    <button class="btn btn-pri btn-sm" onclick="nav('n4b')">Doctor Acknowledges →</button>
  </div>
</div>
<div class="tl">
  ${[
    ['14:28','Vitals Recorded',      'NEWS2: 9. SpO₂ 91%, BP 88/52, RR 22. Recorded by Nurse Rekha Devi.',         ''],
    ['14:29','Escalation Raised',    'To Dr. Anand Sharma (Attending). Level: Nurse-to-Doctor.',                    'err'],
    ['14:30','Notification Sent',    'Secure non-PHI push alert: "Escalation raised — patient requires attention"', ''],
    ['14:32','Doctor Acknowledged',  'Dr. Anand Sharma confirmed — en route to ward.',                              'ok'],
    ['14:37','Doctor at Bedside',    'Bedside assessment initiated. Team assembled.',                                'ok'],
    ['14:45','Intervention Given',   'IV Furosemide 80mg bolus. O₂ via NRM mask 15L/min.',                         ''],
    ['14:50','Repeat Vitals',        'SpO₂ 93%, BP 94/60, HR 106. Improving.',                                     'ok'],
    ['15:10','Patient Stabilised',   'NEWS2 reduced to 4. Ongoing Q1h monitoring ordered.',                         'ok'],
  ].map(([t,e,d,cls]) => `
  <div class="tl-item">
    <div class="tl-dot ${cls}">${cls==='ok'?'✓':cls==='err'?'!':'●'}</div>
    <div class="tl-body">
      <div class="tl-title">${e}</div>
      <div class="tl-time">${t} · 02 Jun 2026</div>
      <div class="tl-detail">${d}</div>
    </div>
  </div>`).join('')}
</div>
<div class="card" style="margin-top:16px">
  <div class="card-title">De-escalation Criteria</div>
  <div class="check-row"><input type="checkbox" checked> SpO₂ ≥ 94% sustained 30 min</div>
  <div class="check-row"><input type="checkbox" checked> Systolic BP ≥ 90 mmHg</div>
  <div class="check-row"><input type="checkbox" checked> NEWS2 ≤ 4 for 60 minutes</div>
  <div class="check-row"><input type="checkbox"> Doctor confirmed de-escalation</div>
</div>`;

/* ── N4b — POST RESOLUTION ──────────────────────────────────── */
SCREENS.n4b = () => {
  const p = APP.data.n1b || {};
  const score = p.news2 != null ? p.news2 : '--';
  const sc = typeof score === 'number' ? (score >= 7 ? 'hi' : score >= 5 ? 'med' : 'lo') : 'lo';
  const who = APP.user ? APP.user.name : 'Clinical team';
  return `
<div class="bc"><span class="bc-link" onclick="nav('n4')">Status Log</span><span class="bc-sep">/</span><span>Resolved</span></div>
<div class="sh"><h1 class="sh-title">Escalation Resolved — ${p.name || 'Patient'} <span class="pid" style="font-size:13px">${p.patient_code || ''}</span></h1></div>
<div class="alert al-ok">✅ ${who} marked the escalation resolved. Continue routine monitoring per NEWS2 cadence (${(p.monitoring && p.monitoring.label) || 'as indicated'}).</div>
<div class="tw"><table>
  <thead><tr><th>Patient</th><th>SpO₂</th><th>RR</th><th>BP</th><th>HR</th><th>NEWS2</th><th>Status</th></tr></thead>
  <tbody>
    <tr>
      <td><b>${p.name || '—'}</b><br><span class="pid">${p.patient_code || ''}</span></td>
      <td style="color:var(--t3)">${p.spo2 != null ? p.spo2 + '%' : '--'}</td>
      <td>${p.rr != null ? p.rr : '--'}</td>
      <td>${p.bp || '--'}</td>
      <td>${p.hr != null ? p.hr : '--'}</td>
      <td><span class="n2s ${sc}">${score}</span></td>
      <td><span class="bd bd-t3">✓ Resolved</span></td>
    </tr>
  </tbody>
</table></div>
<div style="display:flex;gap:8px;margin-top:12px">
  <button class="btn btn-pri" onclick="nav('n1')">← Back to Dashboard</button>
</div>`;
};

/* ── N5 — CHARGE NURSE QUEUE ────────────────────────────────── */
SCREENS.n5 = () => {
  const allEsc = (APP.data.n5?.escalations || []);
  const escalations = allEsc.filter(e => e.status === 'active');
  const transfers = (APP.data.n5_transfers?.transfers || []);
  const emptyState = `<div style="text-align:center;padding:48px 24px;color:var(--muted)">
    <div style="font-size:44px;margin-bottom:14px">&#10003;</div>
    <div style="font-size:15px;font-weight:700;color:var(--t3);margin-bottom:6px">No Active Escalations</div>
    <div style="font-size:12.5px">All patients in Ward 4B/4C are within normal NEWS2 thresholds.</div>
  </div>`;
  const levelLabel = l => ({nurse:'Head Nurse', doctor:'Attending', consultant:'Consultant', code_blue:'Code Blue'}[l] || l || '--');
  const fmtTime = ts => { if (!ts) return '--'; try { return new Date(ts).toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'}); } catch (e) { return ts; } };

  window.reescalateEsc = async function(id) {
    try { const res = await fetch(`/api/escalations/${id}/reescalate`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason:''})});
      if (res.ok) { const d = await res.json(); alert('Re-escalated to ' + d.newLevelLabel); nav('n5'); } else alert('Re-escalation failed.'); } catch (e) { alert('Network error'); }
  };
  window.approveTransfer = async function(id) {
    try { const res = await fetch(`/api/ccu-transfers/${id}/approve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decidedBy: APP.user?APP.user.name:'Head Nurse'})});
      if (res.ok) { alert('Transfer approved — patient moved to General Ward.'); nav('n5'); } else alert('Approval failed.'); } catch (e) { alert('Network error'); }
  };
  window.rejectTransfer = async function(id) {
    if (!confirm('Reject this step-down recommendation?')) return;
    try { const res = await fetch(`/api/ccu-transfers/${id}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decidedBy: APP.user?APP.user.name:'Head Nurse'})});
      if (res.ok) nav('n5'); } catch (e) { alert('Network error'); }
  };

  return `
<div class="bc"><span>Ward 4B / 4C</span><span class="bc-sep">/</span><span>Escalation Queue</span></div>
<div class="sh">
  <h1 class="sh-title">Escalation Queue</h1>
  <div class="sh-actions">
    <span class="muted small">${new Date().toLocaleString('en-IN', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'})}</span>
    <button class="btn btn-warn btn-sm" style="color:#000" onclick="nav('dl1')">Drug-Lab Overview</button>
    <button class="btn btn-sec btn-sm" onclick="nav('n5b')">Threshold Config</button>
  </div>
</div>

<div class="stats">
  <div class="stat" style="border-left:3px solid var(--t1)"><div class="stat-v" style="color:var(--t1)">${escalations.filter(e=>e.level==='code_blue').length}</div><div class="stat-l">Code Blue</div></div>
  <div class="stat" style="border-left:3px solid var(--t2)"><div class="stat-v" style="color:var(--t2)">${escalations.filter(e=>e.level==='doctor').length}</div><div class="stat-l">To Doctor</div></div>
  <div class="stat" style="border-left:3px solid var(--t3)"><div class="stat-v" style="color:var(--t3)">${escalations.filter(e=>e.level==='nurse').length}</div><div class="stat-l">To Sr. Nurse</div></div>
  <div class="stat"><div class="stat-v" style="color:var(--muted)">${allEsc.filter(e=>e.status==='resolved').length}</div><div class="stat-l">Resolved Today</div></div>
</div>

${escalations.length === 0 ? emptyState : `
<div class="tw" style="margin-bottom:14px"><table class="tbl-stack">
  <thead><tr><th>Patient</th><th>Ward</th><th>NEWS2</th><th>Level</th><th>Escalated</th><th>By</th><th>Status / SLA</th><th>Action</th></tr></thead>
  <tbody>
    ${escalations.map(e => {
      const breached = e.slaBreached;
      const slaCell = e.reescalatedAt
        ? `<span class="bd bd-t1">⏱ Re-escalated</span><div class="muted small">${e.reescalationNote || ''}</div>`
        : breached
          ? `<span class="bd bd-t1">⏱ SLA BREACHED</span><div class="due-over small">${e.minsElapsed}m unattended</div>`
          : `<span class="bd bd-t2">Active</span>${e.slaRemaining != null ? `<div class="muted small">${e.slaRemaining}m to SLA</div>` : ''}`;
      return `
        <tr class="${breached ? 'row-crit' : ''}">
          <td data-label="Patient"><b>${e.patientName}</b><br><span class="pid">PT-${e.patientId}</span></td>
          <td data-label="Ward">${e.ward} / Bed ${e.bed}</td>
          <td data-label="NEWS2"><span class="n2s ${e.news2 >= 7 ? 'hi' : 'med'}">${e.news2}</span></td>
          <td data-label="Level" class="small">${levelLabel(e.level)}</td>
          <td data-label="Escalated" class="mono">${fmtTime(e.escalatedAt)}</td>
          <td data-label="By">${e.escalatedBy || '--'}</td>
          <td data-label="Status / SLA">${slaCell}</td>
          <td data-label="Action"><div style="display:flex;gap:4px;flex-wrap:wrap">
            <button class="btn ${breached ? 'btn-danger' : 'btn-sec'} btn-xs" onclick="reescalateEsc(${e.id})">Re-escalate ↑</button>
            <button class="btn btn-sec btn-xs" onclick="nav('n1b', ${e.patientId})">Review</button>
          </div></td>
        </tr>
      `;
    }).join('')}
  </tbody>
</table></div>
`}

<div class="card" style="margin-top:14px">
  <div class="card-title">CCU → General Ward Transfer Approvals ${transfers.length ? `<span class="bd bd-t2" style="margin-left:8px">${transfers.length} Pending</span>` : ''}</div>
  ${transfers.length === 0
    ? '<div class="muted small" style="padding:8px 0">No pending step-down recommendations.</div>'
    : `<div class="tw" style="border:none"><table class="tbl-stack">
        <thead><tr><th>Patient</th><th>Recommended By</th><th>NEWS2</th><th>Stable Window</th><th>Submitted</th><th>Actions</th></tr></thead>
        <tbody>${transfers.map(t => `
          <tr>
            <td data-label="Patient"><b>${t.patientName}</b><br><span class="pid">${t.diagnosis || ''}</span></td>
            <td data-label="Recommended By">${t.recommendedBy}</td>
            <td data-label="NEWS2"><span class="n2s lo">${t.news2AtSubmit}</span></td>
            <td data-label="Stable Window" style="color:var(--t3);font-weight:700">${t.stableWindowHours}h ✓</td>
            <td data-label="Submitted" class="mono">${fmtTime(t.submittedAt)}</td>
            <td data-label="Actions"><div style="display:flex;gap:6px">
              <button class="btn btn-pri btn-xs" onclick="approveTransfer(${t.id})">Approve →</button>
              <button class="btn btn-sec btn-xs" onclick="rejectTransfer(${t.id})">Reject</button>
            </div></td>
          </tr>`).join('')}</tbody></table></div>
       <div class="muted small" style="margin-top:6px">Approval moves the patient CCU → General Ward (ward_location change). Requires charge-nurse credentials; cannot be undone without re-admission.</div>`}
</div>
`;
};

/* ── N5b — THRESHOLD CONFIG ─────────────────────────────────── */
SCREENS.n5b = () => `
<div class="bc"><span class="bc-link" onclick="nav('n5')">Escalation Queue</span><span class="bc-sep">/</span><span>Threshold Config</span></div>
<div class="sh"><h1 class="sh-title">NEWS2 Threshold Configuration — Ward 4B/4C</h1></div>
<div class="alert al-warn">⚠️ Changes require Charge Nurse sign-off and are logged in the NABH audit trail. They propagate to all bedside dashboards in this ward.</div>

<div class="card" style="max-width:640px">
  <div class="card-title">Ward-level Overrides</div>
  <div class="tw" style="border:none;margin-bottom:16px"><table>
    <thead><tr><th>Parameter</th><th>Global Default</th><th>Ward Override</th><th>Rationale</th></tr></thead>
    <tbody>
      ${[
        ['SpO₂ low alert',          '< 88%',    '< 90%',   'Post-PCI patients require stricter threshold'],
        ['RR high alert',           '> 25/min', '> 22/min','Ward cardiology protocol'],
        ['HR high alert',           '> 130/min','> 120/min','Post-arrhythmia patients'],
        ['NEWS2 escalate trigger',  '≥ 7',      '≥ 5',     'Proactive escalation policy'],
        ['Stale vitals warning',    '> 60 min', '> 45 min','Ward safety policy'],
      ].map(([p,g,w,r]) => `
      <tr>
        <td class="bold">${p}</td>
        <td class="muted">${g}</td>
        <td style="color:var(--p)"><input class="fi" style="width:90px;display:inline;padding:3px 8px;font-size:11.5px" value="${w}"></td>
        <td class="muted small">${r}</td>
      </tr>`).join('')}
    </tbody>
  </table></div>
  <div class="fg"><label class="fl">Charge Nurse Password (required to save)</label>
    <input class="fi" type="password" placeholder="Enter credentials to sign off">
  </div>
  <div style="display:flex;gap:8px;justify-content:flex-end">
    <button class="btn btn-sec" onclick="nav('n5')">Cancel</button>
    <button class="btn btn-pri">Save & Sign Off</button>
  </div>
</div>`;

/* ── N6 — SHIFT HANDOFF ─────────────────────────────────────── */
SCREENS.n6 = () => `
<div class="bc"><span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span><span>Shift Handoff</span></div>
<div class="sh"><h1 class="sh-title">Shift Handoff — Ward 4B/4C</h1></div>

<div class="grid2" style="margin-bottom:12px">
  <div class="card">
    <div class="card-title">Handoff Details</div>
    <div class="frow">
      <div class="fg"><label class="fl">Outgoing Nurse</label>
        <input class="fi" value="Nurse Rekha Devi" readonly style="background:var(--surf)">
      </div>
      <div class="fg"><label class="fl">Shift</label>
        <input class="fi" value="Day Shift  07:00 – 19:00" readonly style="background:var(--surf)">
      </div>
    </div>
    <div class="fg"><label class="fl">Incoming Nurse</label>
      <select class="fi"><option>Nurse Prathima M (Night Shift)</option></select>
    </div>
    <div class="fg"><label class="fl">Handoff Time</label>
      <input class="fi" value="19:00, 02 Jun 2026" readonly style="background:var(--surf)">
    </div>
  </div>
  <div class="card">
    <div class="card-title">Patient Summary</div>
    <div class="tw" style="border:none"><table>
      <thead><tr><th>Patient</th><th>NEWS2</th><th>Priority Note</th></tr></thead>
      <tbody>
        <tr class="row-warn"><td><b>PT-24-0092</b> Priya Sharma</td><td><span class="n2s med">3</span></td><td>Escalation resolved 15:10. Watch overnight.</td></tr>
        <tr><td><b>PT-24-0087</b> Rajesh Kumar</td><td><span class="n2s med">4</span></td><td>Stable. Discharge expected tomorrow.</td></tr>
        <tr><td><b>PT-24-0103</b> Arun Verma</td><td><span class="n2s med">6</span></td><td>Still elevated — Q2h monitoring.</td></tr>
        <tr><td><b>PT-24-0095</b> Mohan Singh</td><td><span class="n2s lo">1</span></td><td>Stable for discharge tomorrow.</td></tr>
      </tbody>
    </table></div>
  </div>
</div>

<div class="card">
  <div class="card-title">Pending Tasks for Night Shift</div>
  <div class="check-row"><input type="checkbox"> PT-24-0103: Vitals every 2h per doctor order</div>
  <div class="check-row"><input type="checkbox"> PT-24-0087: IV Furosemide dose at 22:00</div>
  <div class="check-row"><input type="checkbox"> PT-24-0092: INR result review (lab report at 22:00)</div>
  <div class="check-row"><input type="checkbox"> All patients: NEWS2 entry by 23:00</div>
  <div class="fg" style="margin-top:12px"><label class="fl">Additional Handoff Notes</label>
    <textarea class="fi" rows="3">PT-24-0092 family present overnight. Dr. Sharma on call — pager 2201. Active Drug-Lab T1 flag for PT-24-0092 — see Drug-Lab tab.</textarea>
  </div>
  <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
    <button class="btn btn-sec" onclick="nav('n1')">Cancel</button>
    <button class="btn btn-pri" onclick="nav('n6b')">Complete Handoff</button>
  </div>
</div>`;

/* ── N6b — HANDOFF COMPLETE ─────────────────────────────────── */
SCREENS.n6b = () => `
<div class="bc"><span class="bc-link" onclick="nav('n6')">Shift Handoff</span><span class="bc-sep">/</span><span>Complete</span></div>
<div class="sh"><h1 class="sh-title">Shift Handoff Complete</h1></div>
<div class="card" style="max-width:440px;margin:0 auto;text-align:center;padding:36px">
  <div style="font-size:44px;margin-bottom:14px">🤝</div>
  <div style="font-size:16px;font-weight:800;color:var(--t3);margin-bottom:16px">Handoff Complete</div>
  <div class="tw" style="text-align:left;margin-bottom:20px"><table><tbody>
    <tr><td class="muted">Outgoing</td><td class="bold">Nurse Rekha Devi</td></tr>
    <tr><td class="muted">Incoming</td><td class="bold">Nurse Prathima M</td></tr>
    <tr><td class="muted">Shift end</td><td class="mono">19:02, 02 Jun 2026</td></tr>
    <tr><td class="muted">Reference</td><td class="mono">HO-4B-2026-0602-19</td></tr>
    <tr><td class="muted">Acknowledged</td><td style="color:var(--t3)">✓ Nurse Prathima M</td></tr>
  </tbody></table></div>
  <button class="btn btn-pri" style="width:100%;justify-content:center" onclick="nav('n1')">← Return to Dashboard</button>
</div>`;

/* ══════════════════════════════════════════════════════════════
   DRUG-LAB SCREENS
   ══════════════════════════════════════════════════════════════ */

/* ── DL3 — NURSE AWARENESS (read-only) ──────────────────────── */
SCREENS.dl3 = () => {
  const p = APP.data.n1b || {};
  const alerts = p.drugLabAlerts || [];
  return `
<div class="bc"><span class="bc-link" onclick="nav('n1b', ${p.id})">Patient Detail</span><span class="bc-sep">/</span><span>Drug-Lab Awareness</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Awareness — ${p.name || 'Patient'}</h1><div class="sh-actions"><span class="pid">${p.patient_code || ''}</span></div></div>
<div class="alert al-info">Nurse awareness only — clinical actions (override / hold / consult) are taken by the Head Nurse / Attending. Document any adverse observations in the escalation form.</div>

${alerts.length === 0
  ? '<div class="alert al-ok">No active drug-lab flags for this patient.</div>'
  : alerts.map(a => {
      const tier = a.severity === 'CRITICAL' ? 't1' : 't2';
      return `<div class="dlf ${tier}" style="margin-bottom:10px"><div class="dlf-bd">
        <div class="flex-r"><div class="dlf-title">&#9888; ${a.severity} — ${a.rule_name || ''}</div><span class="bd ${a.severity==='CRITICAL'?'bd-t1':'bd-t2'}">${a.severity}</span></div>
        <div class="dlf-desc"><b>Alert:</b> ${a.message || ''}<br><b>Watch / action:</b> ${a.action || ''}</div>
        ${a.guideline ? `<div class="muted small" style="margin-top:4px">${a.guideline}</div>` : ''}
      </div></div>`;
    }).join('')}

<div class="card">
  <div class="card-title">Observation Checklist — report immediately if any observed</div>
  ${['Unusual bruising or petechiae','Black or tarry stools (melena)','Blood in urine (haematuria)','Haematemesis (blood in vomit)','Prolonged bleeding from puncture sites','Sudden confusion or neurological change'].map(s => `<div class="check-row"><input type="checkbox"> ${s}</div>`).join('')}
  <div style="margin-top:12px;display:flex;gap:8px">
    <button class="btn btn-sec btn-sm" onclick="nav('n1b', ${p.id})">← Back to Patient</button>
    <button class="btn btn-sec btn-sm" onclick="nav('n2', ${p.id})">Log in Escalation</button>
  </div>
</div>`;
};

/* ── DL1 — DL FLAG OVERVIEW (Charge Nurse — live from ward data) ──── */
SCREENS.dl1 = () => {
  const patients = APP.data.n1?.patients || [];
  const allFlags = [];
  patients.forEach(p => {
    (p.drugLabAlerts || []).forEach(a => {
      allFlags.push({ ...a, patientName: p.name, patientId: p.id, ward: p.ward, bed: p.bed });
    });
  });
  const critFlags = allFlags.filter(f => f.severity === 'CRITICAL');
  const warnFlags = allFlags.filter(f => f.severity === 'WARNING');

  return `
<div class="bc"><span>Drug-Lab</span><span class="bc-sep">/</span><span>Active Flags</span></div>
<div class="sh"><h1 class="sh-title">Active Drug-Lab Flags &mdash; Ward 4B/4C</h1></div>
<div class="alert al-warn">Flags are computed live from patient medication &amp; lab records. CRITICAL flags require attending action and charge nurse co-sign for override.</div>

<div class="stats">
  <div class="stat" style="border-left:3px solid var(--t1)"><div class="stat-v" style="color:var(--t1)">${critFlags.length}</div><div class="stat-l">CRITICAL Flags</div></div>
  <div class="stat" style="border-left:3px solid var(--t2)"><div class="stat-v" style="color:var(--t2)">${warnFlags.length}</div><div class="stat-l">WARNING Flags</div></div>
  <div class="stat"><div class="stat-v" style="color:var(--muted)">${patients.length}</div><div class="stat-l">Patients Checked</div></div>
</div>

${allFlags.length === 0
  ? `<div class="alert al-ok">No active drug-lab interaction flags across all ward patients.</div>`
  : allFlags.map(a => {
      const tier = a.severity === 'CRITICAL' ? 't1' : 't2';
      const badge = a.severity === 'CRITICAL' ? 'bd-t1' : 'bd-t2';
      return `<div class="dlf ${tier}" style="margin-bottom:10px"><div class="dlf-bd">
        <div class="flex-r">
          <div class="dlf-title">&#9888; ${a.rule_name || a.severity} &mdash; ${a.patientName} (${a.ward}, Bed ${a.bed})</div>
          <span class="bd ${badge}">${a.severity}</span>
        </div>
        <div class="dlf-desc">${a.message}</div>
        <div style="margin-top:6px;font-size:11.5px;color:var(--ink2)"><b>Action:</b> ${a.action || ''}</div>
        <div style="margin-top:4px;font-size:11px;color:var(--muted)">${a.guideline || ''}</div>
        <div style="margin-top:8px;display:flex;align-items:center;gap:12px">
          <span class="dlf-link" onclick="openDl2('${a.patientId}', '${(a.rule_name||'').replace(/'/g,"\\'")}')">View detail &amp; take action &rarr;</span>
        </div>
      </div></div>`;
    }).join('')}`;
};

/* Open the real flag a user clicked, then route to DL2 (Flag Detail & Action) */
window.openDl2 = function(pid, ruleName) {
  const pats = APP.data.n1?.patients || [];
  for (const p of pats) {
    if (p.id == pid) {
      const a = (p.drugLabAlerts || []).find(x => x.rule_name === ruleName) || (p.drugLabAlerts || [])[0];
      if (a) {
        APP.dl2_flag = { ...a, patientName: p.name, patientId: p.id, patientCode: p.patient_code, ward: p.ward, bed: p.bed, diagnosis: p.diagnosis_short };
        APP.dl2_action = 'hold';
        APP.dl2_justification = '';
        nav('dl2');
        return;
      }
    }
  }
  alert('Flag details unavailable — refresh the dashboard.');
};

/* Persist a Drug-Lab action (DL2/dlcosign → DL2b) to the NABH audit trail */
window.recordDlAction = async function(cosignedBy) {
  const f = APP.dl2_flag;
  if (!f) { alert('No flag selected.'); return; }
  const noteEl = document.getElementById('dl2-note');
  if (noteEl) APP.dl2_justification = noteEl.value;
  try {
    const res = await fetch('/api/drug-lab-actions', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subjectId: f.patientId, ruleName: f.rule_name, severity: f.severity,
        action: APP.dl2_action, justification: APP.dl2_justification || '',
        recordedBy: APP.user ? APP.user.name : 'Charge Nurse', cosignedBy: cosignedBy || null
      })
    });
    if (res.ok) {
      APP.dl2_result = await res.json();
      APP.dl2_result.patientName = f.patientName;
      APP.dl2_result.diagnosis = f.diagnosis;
      nav('dl2b');
    } else { alert('Could not record action.'); }
  } catch (e) { alert('Network error: ' + e.message); }
};

/* ── DL2 — FLAG DETAIL & ACTION (data-driven from the clicked flag) ── */
SCREENS.dl2 = () => {
  const f = APP.dl2_flag;
  if (!f) return `<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span></div>
    <div class="alert al-warn">No flag selected. <span class="bc-link" onclick="nav('dl1')">← Back to Drug-Lab flags</span></div>`;
  const isCrit = f.severity === 'CRITICAL';
  const tier = isCrit ? 't1' : 't2';

  window.submitDl2 = function() {
    const noteEl = document.getElementById('dl2-note');
    if (noteEl) APP.dl2_justification = noteEl.value;
    if (APP.dl2_action === 'override' && isCrit) { nav('dlcosign'); return; }  // T1 override needs co-sign
    recordDlAction(null);
  };
  const actCard = (key, title, desc, badge) => `
    <div class="card action-card${APP.dl2_action===key?' selected-action':''}" style="border:2px solid ${APP.dl2_action===key?'var(--p)':'var(--border)'};cursor:pointer" onclick="APP.dl2_action='${key}';renderAll()">
      <div class="flex-r" style="margin-bottom:4px"><input type="radio" name="dl-action" ${APP.dl2_action===key?'checked':''}> <b>${title}</b>${badge?`<span class="bd bd-t1" style="margin-left:auto">${badge}</span>`:''}</div>
      <div style="font-size:11.5px;color:var(--ink2)">${desc}</div>
    </div>`;

  return `
<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span><span class="bc-sep">/</span><span>Flag Detail</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Flag Detail</h1><div class="sh-actions"><span class="bd ${isCrit?'bd-t1':'bd-t2'}">${f.severity}</span></div></div>

<div class="grid2">
  <div>
    <div class="dlf ${tier}" style="margin-bottom:12px">
      <div class="dlf-bd">
        <div class="dlf-title">&#9888; ${f.severity} — ${f.rule_name || ''}</div>
        <div class="dlf-desc" style="margin-top:8px;line-height:1.7">
          <b>Patient:</b> ${f.patientName} <span class="pid">${f.patientCode || ''}</span> · ${f.diagnosis || ''} · ${f.ward}, Bed ${f.bed}<br>
          <b>Alert:</b> ${f.message || ''}<br>
          <b>Recommended action:</b> ${f.action || ''}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Evidence</div>
      <div class="tw" style="border:none"><table><tbody>
        <tr><td class="muted">Rule</td><td class="bold">${f.rule_name || ''}</td></tr>
        <tr><td class="muted">Severity</td><td style="color:${isCrit?'var(--t1)':'var(--t2)'};font-weight:700">${f.severity}</td></tr>
        <tr><td class="muted">Clinical basis</td><td>${f.message || ''}</td></tr>
        <tr><td class="muted">Guideline</td><td>${f.guideline || '—'}</td></tr>
      </tbody></table></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Required Action — Choose One</div>
    <div style="display:flex;flex-direction:column;gap:10px">
      ${actCard('override', 'Override with clinical justification', 'Document why the regimen is clinically necessary.' + (isCrit?' Head-Nurse co-sign required for a CRITICAL (T1) override.':''), isCrit?'Requires T1 Co-sign':'')}
      ${actCard('hold', 'Hold implicated drug — pending review', 'Suspend the implicated drug until specialist/haematology review. Monitor relevant labs.')}
      ${actCard('pharmacist', 'Consult Clinical Pharmacist', 'Refer for formal medication review. Action pending pharmacist recommendation.')}
    </div>
    <div class="fg" style="margin-top:12px"><label class="fl">Clinical note (optional)</label>
      <textarea class="fi" id="dl2-note" rows="2" placeholder="Add any context for the audit trail…">${APP.dl2_justification||''}</textarea>
    </div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-sec" onclick="nav('dl1')">← Back</button>
      <button class="btn btn-pri" onclick="submitDl2()">${APP.dl2_action==='override'&&isCrit?'Continue to Co-Sign →':'Submit Action →'}</button>
    </div>
  </div>
</div>`;
};

/* ── DL2b — DL ACTION CONFIRMATION (data-driven from the persisted record) ── */
SCREENS.dl2b = () => {
  const r = APP.dl2_result;
  if (!r) return `<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span></div>
    <div class="alert al-warn">No action on record. <span class="bc-link" onclick="nav('dl1')">← Back to flags</span></div>`;
  const labels = { override: 'Override with clinical justification', hold: 'Hold implicated drug — pending review', pharmacist: 'Consult Clinical Pharmacist' };
  return `
<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span><span class="bc-sep">/</span><span>Confirmation</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Action Recorded</h1></div>
<div class="alert al-ok">✅ Action recorded for ${r.patientName || 'patient'}: <b>${labels[r.action] || r.action}</b></div>
<div class="card" style="max-width:560px">
  <div class="tw" style="border:none;margin-bottom:14px"><table><tbody>
    <tr><td class="muted">Patient</td><td class="bold">${r.patientName || ''} ${r.diagnosis ? '· ' + r.diagnosis : ''}</td></tr>
    <tr><td class="muted">Flag</td><td>${r.ruleName || ''} <span class="bd ${r.severity==='CRITICAL'?'bd-t1':'bd-t2'}">${r.severity}</span></td></tr>
    <tr><td class="muted">Action taken</td><td class="bold">${labels[r.action] || r.action}</td></tr>
    ${r.justification ? `<tr><td class="muted">Justification</td><td>${r.justification}</td></tr>` : ''}
    <tr><td class="muted">Recorded by</td><td>${r.recordedBy || ''}</td></tr>
    ${r.cosignedBy ? `<tr><td class="muted">Co-signed by</td><td>${r.cosignedBy} (Head Nurse)</td></tr>` : ''}
    <tr><td class="muted">Timestamp</td><td class="mono">${r.recordedAt || ''}</td></tr>
    <tr><td class="muted">Status</td><td><span class="bd bd-t3">Resolved</span></td></tr>
  </tbody></table></div>
  <div class="alert al-info">ℹ️ Recorded in the NABH audit trail (<span class="mono">/api/drug-lab-actions</span>).</div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-sec" onclick="nav('dl1')">← Back to Flags</button>
  </div>
</div>`;
};

/* ── N_VITALS — NURSE VITALS ENTRY SCREEN ───────────────────── */
SCREENS.n_vitals = () => {
  const p = APP.data.n_vitals_patient || {};
  const latest = APP.data.n_vitals_latest;
  const staleMins = latest ? latest.stale_mins : null;
  const isStale = latest ? latest.is_stale : true;
  const staleWarning = isStale && staleMins !== null
    ? '<div class="alert al-warn">⚠ Last vitals recorded ' + staleMins + ' min ago — entry required.</div>'
    : staleMins !== null
      ? '<div class="alert al-ok">Last vitals recorded ' + staleMins + ' min ago.</div>'
      : '<div class="alert al-warn">⚠ No vitals on record for this patient.</div>';

  window.submitVitals = async function() {
    const get = id => document.getElementById(id)?.value;
    const spo2 = parseFloat(get('v-spo2'));
    const rr   = parseFloat(get('v-rr'));
    const hr   = parseFloat(get('v-hr'));
    const sbp  = parseFloat(get('v-sbp'));
    const dbp  = parseFloat(get('v-dbp'));
    const temp = parseFloat(get('v-temp'));
    const consciousness = get('v-avpu') || 'A';
    const air_or_oxygen = get('v-air') || 'Air';

    if ([spo2, rr, hr, sbp, dbp, temp].some(isNaN)) {
      alert('All fields are required and must be valid numbers.');
      return;
    }
    if (spo2 < 70 || spo2 > 100)   { alert('SpO2 must be 70-100%'); return; }
    if (rr < 5   || rr > 60)       { alert('Resp Rate must be 5-60'); return; }
    if (hr < 20  || hr > 250)      { alert('Heart Rate must be 20-250'); return; }
    if (sbp < 50 || sbp > 250)     { alert('SBP must be 50-250'); return; }
    if (dbp < 30 || dbp > 150)     { alert('DBP must be 30-150'); return; }
    if (temp < 33 || temp > 42)    { alert('Temp must be 33-42 C'); return; }

    const btn = document.getElementById('submit-vitals-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }

    try {
      const res = await fetch('/api/patients/' + APP.currentPatientId + '/vitals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spo2, resp_rate: rr, heart_rate: hr, sbp, dbp, temperature: temp, consciousness, air_or_oxygen })
      });
      if (res.ok) {
        const data = await res.json();
        const score = data.news2_score;
        const level = data.risk_level;
        const badgeClass = level === 'critical' ? 'bd-t1' : level === 'warning' ? 'bd-t2' : 'bd-t3';
        const factors = (data.factors || []).map(function(f) { return f.name + ': +' + f.score; }).join(' - ') || 'All parameters within range';
        const el = document.getElementById('vitals-result');
        if (el) {
          el.innerHTML = '<div class="alert al-ok" style="margin-top:16px">' +
            '✓ Vitals saved - NEWS2 score: <span class="bd ' + badgeClass + '" style="font-size:13px;padding:3px 10px">' + score + ' — ' + level.toUpperCase() + '</span>' +
            '<br><span class="muted small">' + factors + '</span></div>';
        }
        setTimeout(function() { nav('n1b', APP.currentPatientId); }, 2000);
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Submit Vitals'; }
        alert('Failed to save vitals - check backend is running.');
      }
    } catch(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Submit Vitals'; }
      alert('Network error: ' + e.message);
    }
  };

  const pid = APP.currentPatientId;
  const patName = p.patient_code || p.name || 'Patient';
  const patSubname = p.name || '';
  return '<div class="bc">' +
    '<span class="bc-link" onclick="nav(\'n1\')">NEWS2 Dashboard</span>' +
    '<span class="bc-sep">/</span>' +
    '<span class="bc-link" onclick="nav(\'n1b\',' + pid + ')">Patient Detail</span>' +
    '<span class="bc-sep">/</span>' +
    '<span>Enter Vitals</span>' +
    '</div>' +
    '<div class="sh"><h1 class="sh-title">Enter Vitals — ' + patName + '</h1>' +
    '<div class="sh-actions"><span class="muted small">' + patSubname + '</span></div></div>' +
    staleWarning +
    '<div class="card" style="max-width:560px">' +
    '<div class="card-title">Vital Signs Entry</div>' +
    '<div class="grid3" style="gap:12px;margin-bottom:16px">' +
    '<div class="fg"><label class="fl">SpO2 (%)</label><input class="fi" id="v-spo2" type="number" min="70" max="100" step="0.1" placeholder="e.g. 96"></div>' +
    '<div class="fg"><label class="fl">Resp Rate (/min)</label><input class="fi" id="v-rr" type="number" min="5" max="60" placeholder="e.g. 18"></div>' +
    '<div class="fg"><label class="fl">Heart Rate (bpm)</label><input class="fi" id="v-hr" type="number" min="20" max="250" placeholder="e.g. 88"></div>' +
    '<div class="fg"><label class="fl">BP Systolic (mmHg)</label><input class="fi" id="v-sbp" type="number" min="50" max="250" placeholder="e.g. 118"></div>' +
    '<div class="fg"><label class="fl">BP Diastolic (mmHg)</label><input class="fi" id="v-dbp" type="number" min="30" max="150" placeholder="e.g. 76"></div>' +
    '<div class="fg"><label class="fl">Temperature (C)</label><input class="fi" id="v-temp" type="number" min="33" max="42" step="0.1" placeholder="e.g. 37.0"></div>' +
    '<div class="fg"><label class="fl">AVPU</label><select class="fi" id="v-avpu"><option value="A">Alert</option><option value="V">Voice</option><option value="P">Pain</option><option value="U">Unresponsive</option></select></div>' +
    '<div class="fg"><label class="fl">Air / O2</label><select class="fi" id="v-air"><option value="Air">Air</option><option value="Oxygen">Oxygen</option></select></div>' +
    '</div>' +
    '<div style="display:flex;gap:8px;align-items:center">' +
    '<button class="btn btn-sec btn-sm" onclick="nav(\'n1b\',' + pid + ')">Cancel</button>' +
    '<button class="btn btn-pri" id="submit-vitals-btn" onclick="submitVitals()">Submit Vitals</button>' +
    '</div></div>' +
    '<div id="vitals-result"></div>';
};

/* ── DL CO-SIGN (Tier-1 override, data-driven) ──────────────── */
SCREENS.dlcosign = () => {
  const f = APP.dl2_flag;
  if (!f) return `<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span></div>
    <div class="alert al-warn">No flag selected. <span class="bc-link" onclick="nav('dl1')">← Back to flags</span></div>`;
  window.submitCosign = function() {
    APP.dl2_justification = document.getElementById('co-just')?.value || '';
    APP.dl2_action = 'override';
    const cosigner = document.getElementById('co-name')?.value || (APP.user ? APP.user.name : 'Head Nurse');
    recordDlAction(cosigner);
  };
  return `
<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span><span class="bc-sep">/</span><span class="bc-link" onclick="nav('dl2')">Flag Detail</span><span class="bc-sep">/</span><span>Tier 1 Co-Sign</span></div>
<div class="sh"><h1 class="sh-title">Tier 1 Override — Co-Sign Required</h1><div class="sh-actions"><span class="bd bd-t1">${f.severity}</span></div></div>
<div class="alert al-err">🔐 Overriding a CRITICAL (T1) Drug-Lab flag requires a second sign-off — an NABH mandatory safety requirement.</div>
<div class="alert al-info">Flag: <b>${f.rule_name || ''}</b> — ${f.patientName} <span class="pid">${f.patientCode || ''}</span>. ${f.message || ''}</div>

<div class="grid2">
  <div class="card">
    <div class="card-title">Override Justification</div>
    <div class="fg"><label class="fl">Clinical Justification <span style="color:var(--t1)">*</span></label>
      <textarea class="fi" id="co-just" rows="5" placeholder="Document why this regimen must continue despite the flag…">${APP.dl2_justification || ''}</textarea>
    </div>
    <div class="fg"><label class="fl">Recorded by</label>
      <input class="fi" value="${APP.user ? APP.user.name : 'Charge Nurse'}" readonly style="background:var(--surf)">
    </div>
  </div>
  <div class="card">
    <div class="card-title">Head Nurse Co-Sign</div>
    <div class="muted small" style="margin-bottom:12px">A second senior nurse must verify the justification and provide credentials to complete the override.</div>
    <div class="fg"><label class="fl">Co-signing Head Nurse</label><input class="fi" id="co-name" value="Sister Leena Kurup"></div>
    <div class="fg"><label class="fl">Employee ID</label><input class="fi" placeholder="EMP-XXXX"></div>
    <div class="fg"><label class="fl">Password</label><input class="fi" type="password" placeholder="Enter credentials"></div>
    <div class="alert al-warn" style="margin-top:10px">⚠️ By co-signing, you accept oversight responsibility for this override.</div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-sec" onclick="nav('dl2')">← Back</button>
      <button class="btn btn-pri" onclick="submitCosign()">Co-Sign Override ✓</button>
    </div>
  </div>
</div>`;
};

/* ══════════════════════════════════════════════════════════════════════════
   PATIENT ARC REPLAY DEMO  (n_demo_replay)
   Stakeholder-facing: plays the real MIMIC clinical arc frame by frame.
   Fetches from GET /api/demo/replay/{hadm_id}
   ══════════════════════════════════════════════════════════════════════════ */

let _replayTimer = null;

window._replayLoadPatient = async function(hadmId) {
  if (!hadmId) return;
  const loadBtn = document.getElementById('replay-load-btn');
  if (loadBtn) loadBtn.textContent = 'Loading…';
  try {
    const res = await fetch(`/api/demo/replay/${hadmId}`);
    if (!res.ok) throw new Error(await res.text());
    APP.data.n_demo_replay = await res.json();
    APP.data.n_demo_frame = 0;
    APP.data.n_demo_playing = false;
    if (_replayTimer) { clearInterval(_replayTimer); _replayTimer = null; }
  } catch (e) {
    alert('Could not load replay: ' + e.message);
  }
  renderAll();
};

window._replayStep = function(delta) {
  const d = APP.data.n_demo_replay;
  if (!d) return;
  const max = d.frames.length - 1;
  APP.data.n_demo_frame = Math.max(0, Math.min(max, (APP.data.n_demo_frame || 0) + delta));
  renderAll();
};

window._replayTogglePlay = function(speedMs) {
  const d = APP.data.n_demo_replay;
  if (!d) return;
  if (_replayTimer) {
    clearInterval(_replayTimer);
    _replayTimer = null;
    APP.data.n_demo_playing = false;
    renderAll();
    return;
  }
  APP.data.n_demo_playing = true;
  renderAll();
  _replayTimer = setInterval(() => {
    const max = d.frames.length - 1;
    const next = (APP.data.n_demo_frame || 0) + 1;
    if (next > max) {
      clearInterval(_replayTimer);
      _replayTimer = null;
      APP.data.n_demo_playing = false;
    } else {
      APP.data.n_demo_frame = next;
    }
    renderAll();
  }, speedMs);
};

SCREENS['n_demo_replay'] = function() {
  const patients = APP.data.n_demo_patients || [];
  const replay   = APP.data.n_demo_replay;
  const frame_i  = APP.data.n_demo_frame || 0;
  const playing  = APP.data.n_demo_playing;

  const NEWS2_COLOR = (n) => n >= 7 ? 'var(--t1)' : n >= 5 ? 'var(--t2)' : 'var(--t3)';
  const NYHA_LABEL = (n) => ['', 'NYHA I', 'NYHA II', 'NYHA III', 'NYHA IV'][n] || '—';
  const EVENT_ICON = (t) => ({escalation:'🚨', drug_flag:'⚠️', admission:'🏥', treatment:'💊', stable:'✅', discharge:'🚪'})[t] || '•';

  const pickerHtml = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title" style="margin-bottom:10px">Select DCM Patient for Replay</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <select id="replay-picker" class="fi" style="max-width:320px;flex:1">
          <option value="">— select hadm_id —</option>
          ${patients.map(p => {
            const inDb = p.in_active_patients ? '✓' : '○';
            return '<option value="' + p.hadm_id + '">' + inDb + ' ' + p.hadm_id + ' · ' + (p.diagnosis||'DCM') + ' · Age ' + p.age + (p.gender||'') + '</option>';
          }).join('')}
        </select>
        <button class="btn btn-pri" id="replay-load-btn"
          onclick="_replayLoadPatient(document.getElementById('replay-picker').value)">Load Arc</button>
      </div>
      ${patients.length === 0 ? '<div class="muted small" style="margin-top:8px">No DCM patients found in Cloud SQL.</div>' : ''}
    </div>`;

  if (!replay) {
    return '<div class="bc"><span>Demo</span><span class="bc-sep">/</span><span>Patient Arc Replay</span></div>' +
      '<div class="sh"><h1 class="sh-title">Patient Arc Replay</h1>' +
      '<p class="muted small" style="margin-top:4px">Real MIMIC-IV DCM patient trajectory: Admission → Deterioration → Intervention → Discharge</p></div>' +
      '<div class="content">' + pickerHtml +
      '<div class="card" style="text-align:center;padding:40px;color:var(--muted)">Select a patient above to view their clinical arc.</div></div>';
  }

  const pt    = replay.patient;
  const frames = replay.frames;
  const frame  = frames[frame_i] || frames[0];
  const v = frame.vitals || {};
  const labs = frame.labs || {};
  const events = frame.events || [];
  const bpStr = (v.sbp && v.dbp) ? v.sbp + '/' + v.dbp : '--/--';
  const news2  = frame.news2 || 0;
  const nyha   = frame.nyha  || 1;
  const bnp    = frame.bnp;

  const timelineHtml = '<div style="display:flex;align-items:flex-start;gap:0;margin:16px 0 8px;overflow-x:auto;padding-bottom:4px">' +
    frames.map((f, i) => {
      const active = i === frame_i;
      const nc = NEWS2_COLOR(f.news2 || 0);
      return '<div style="flex:1;min-width:80px;text-align:center;cursor:pointer;position:relative" onclick="APP.data.n_demo_frame=' + i + ';renderAll()">' +
        '<div style="width:28px;height:28px;border-radius:50%;background:' + nc + ';color:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;margin:0 auto 4px;border:3px solid ' + (active ? '#fff' : 'transparent') + ';box-shadow:' + (active ? '0 0 0 3px ' + nc : 'none') + ';transition:all .2s">' +
        (f.news2 ?? '?') + '</div>' +
        '<div style="font-size:10px;color:' + (active ? '#fff' : 'var(--muted)') + ';background:' + (active ? nc : 'transparent') + ';border-radius:4px;padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:84px;margin:0 auto">' +
        f.label.replace(' · ', ' ') + '</div>' +
        (i < frames.length - 1 ? '<div style="position:absolute;top:13px;right:-1px;width:100%;height:2px;background:var(--border);z-index:-1"></div>' : '') +
        '</div>';
    }).join('') + '</div>';

  const eventsHtml = events.length > 0 ? events.map(e => {
    const border = e.severity === 'CRITICAL' ? 'var(--t1)' : e.type === 'escalation' ? 'var(--t2)' : 'var(--t3)';
    return '<div class="alert" style="border-left:4px solid ' + border + ';margin-bottom:8px;padding:10px 12px">' +
      '<div style="font-weight:600">' + EVENT_ICON(e.type) + ' ' + e.type.replace('_',' ').toUpperCase() + '</div>' +
      '<div style="margin-top:4px">' + e.text + '</div>' +
      (e.news2 !== undefined ? '<div class="muted small" style="margin-top:2px">NEWS2 at event: ' + e.news2 + '</div>' : '') +
      '</div>';
  }).join('') : '<div class="muted small" style="padding:16px 0">No clinical events in this frame.</div>';

  const controlsHtml =
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:16px">' +
    '<button class="btn btn-sec" onclick="_replayStep(-1)" ' + (frame_i === 0 ? 'disabled' : '') + '>← Prev</button>' +
    '<button class="btn ' + (playing ? 'btn-danger' : 'btn-pri') + '" onclick="_replayTogglePlay(2000)">' + (playing ? '⏸ Pause' : '▶ Play (2s/frame)') + '</button>' +
    '<button class="btn btn-sec" onclick="_replayTogglePlay(800)">⚡ Fast</button>' +
    '<button class="btn btn-sec" onclick="_replayStep(1)" ' + (frame_i === frames.length - 1 ? 'disabled' : '') + '>Next →</button>' +
    '<span class="muted small" style="margin-left:auto">Frame ' + (frame_i + 1) + ' of ' + frames.length + ' · ' + (frame.vital_count || 0) + ' vitals</span>' +
    '</div>';

  return '<div class="bc"><span>Demo</span><span class="bc-sep">/</span><span>Patient Arc Replay</span></div>' +
    '<div class="sh"><h1 class="sh-title">Patient Arc Replay</h1>' +
    '<span class="muted small">Real MIMIC-IV DCM · ' + pt.diagnosis + ' · Age ' + pt.age + (pt.gender||'') + '</span></div>' +
    '<div class="content">' + pickerHtml +
    '<div class="card" style="margin-bottom:16px">' +
      '<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:8px">' +
        '<div><div class="muted small">Patient</div><div style="font-weight:600">' + (pt.name || 'MIMIC Patient') + ' · HADM ' + pt.hadm_id + '</div></div>' +
        '<div><div class="muted small">Admission NYHA</div><div style="font-weight:600">' + NYHA_LABEL(pt.nyha_at_admission) + '</div></div>' +
        (pt.bnp_at_admission ? '<div><div class="muted small">Admission BNP</div><div style="font-weight:600">' + pt.bnp_at_admission + ' pg/mL</div></div>' : '') +
        (pt.lvef ? '<div><div class="muted small">LVEF</div><div style="font-weight:600">' + pt.lvef + '%</div></div>' : '') +
        '<div style="margin-left:auto;text-align:center"><div style="font-size:38px;font-weight:800;color:' + NEWS2_COLOR(news2) + ';line-height:1">' + news2 + '</div><div class="muted small">NEWS2</div></div>' +
        '<div style="text-align:center"><div style="font-size:22px;font-weight:700;color:var(--accent)">' + NYHA_LABEL(nyha) + '</div>' + (bnp ? '<div class="muted small">BNP ' + bnp + ' pg/mL</div>' : '<div class="muted small">No BNP</div>') + '</div>' +
      '</div>' +
      '<div style="background:var(--surf);border-radius:6px;padding:8px 0">' +
        '<div style="font-weight:600;padding:0 12px 8px">' + frame.label + '</div>' +
        timelineHtml +
      '</div>' +
      controlsHtml +
    '</div>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
      '<div class="card"><div class="card-title" style="margin-bottom:12px">Vitals at Frame</div>' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px"><tbody>' +
        '<tr><td class="muted">Heart Rate</td><td style="text-align:right;font-weight:600">' + (v.hr ?? '--') + ' bpm</td></tr>' +
        '<tr><td class="muted">Resp Rate</td><td style="text-align:right;font-weight:600">' + (v.rr ?? '--') + ' /min</td></tr>' +
        '<tr><td class="muted">SpO2</td><td style="text-align:right;font-weight:600">' + (v.spo2 ?? '--') + '%</td></tr>' +
        '<tr><td class="muted">Blood Pressure</td><td style="text-align:right;font-weight:600">' + bpStr + ' mmHg</td></tr>' +
        '<tr><td class="muted">Temperature</td><td style="text-align:right;font-weight:600">' + (v.temp ?? '--') + ' °C</td></tr>' +
        '<tr><td class="muted">Consciousness</td><td style="text-align:right;font-weight:600">' + (v.avpu || 'A') + '</td></tr>' +
        (v.urine_output != null ? '<tr><td class="muted">Urine Output</td><td style="text-align:right;font-weight:600">' + v.urine_output + ' mL</td></tr>' : '') +
        (v.weight_kg ? '<tr><td class="muted">Weight</td><td style="text-align:right;font-weight:600">' + v.weight_kg + ' kg</td></tr>' : '') +
        '</tbody></table></div>' +
      '<div class="card"><div class="card-title" style="margin-bottom:12px">Labs at Frame</div>' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px"><tbody>' +
        (labs.potassium ? '<tr><td class="muted">Potassium</td><td style="text-align:right;font-weight:600">' + labs.potassium + ' mmol/L</td></tr>' : '') +
        (labs.creatinine ? '<tr><td class="muted">Creatinine</td><td style="text-align:right;font-weight:600">' + labs.creatinine + ' mg/dL</td></tr>' : '') +
        (labs.sodium ? '<tr><td class="muted">Sodium</td><td style="text-align:right;font-weight:600">' + labs.sodium + ' mmol/L</td></tr>' : '') +
        (labs.hemoglobin ? '<tr><td class="muted">Hemoglobin</td><td style="text-align:right;font-weight:600">' + labs.hemoglobin + ' g/dL</td></tr>' : '') +
        (labs.lactate ? '<tr><td class="muted">Lactate</td><td style="text-align:right;font-weight:600">' + labs.lactate + ' mmol/L</td></tr>' : '') +
        (labs.bnp ? '<tr><td class="muted">BNP</td><td style="text-align:right;font-weight:600">' + labs.bnp + ' pg/mL</td></tr>' : '') +
        (labs.troponin ? '<tr><td class="muted">Troponin T</td><td style="text-align:right;font-weight:600">' + labs.troponin + ' ng/mL</td></tr>' : '') +
        (labs.inr ? '<tr><td class="muted">INR</td><td style="text-align:right;font-weight:600">' + labs.inr + '</td></tr>' : '') +
        (Object.keys(labs).length === 0 ? '<tr><td colspan="2" class="muted">No labs in this frame</td></tr>' : '') +
        '</tbody></table></div>' +
    '</div>' +
    '<div class="card" style="margin-top:12px"><div class="card-title" style="margin-bottom:12px">Clinical Events — ' + frame.label + '</div>' +
      eventsHtml +
    '</div>' +
    '</div>';
};

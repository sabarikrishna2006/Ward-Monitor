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
  ],
  charge: [
    { id: 'n5',   label: 'Escalation Queue' },
    { id: 'n5b',  label: 'Threshold Config' },
    { separator: true, label: 'Drug-Lab Co-Sign' },
    { id: 'dl1',  label: 'DL Flag Overview' },
    { id: 'dlcosign', label: 'Tier 1 Co-Sign' },
  ]
};

/* ─── NAVIGATION ─── */
async function nav(id, param = null) {
  if (APP.screen && APP.screen !== id) APP.history.push(APP.screen);
  APP.screen = id;
  if (param !== null) APP.currentPatientId = param;

  try {
    if (id === 'n1') {
      const res = await fetch('/api/ward-data?ward=All');
      if (res.ok) APP.data.n1 = await res.json();
    } else if ((id === 'n1b' || id === 'n2') && APP.currentPatientId) {
      const res = await fetch(`/api/patients/${APP.currentPatientId}`);
      if (res.ok) APP.data.n1b = await res.json();
    } else if (id === 'n5') {
      const res = await fetch('/api/escalations');
      if (res.ok) APP.data.n5 = await res.json();
    }
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

/* ─── LOGIN ─── */
/* Called by index.html after credentials are verified */
window.onFoqalLogin = function(user) {
  APP.role = user.role;   // 'nurse' | 'charge'
  APP.user = {
    name:  user.name,
    role:  user.roleLabel,
    shift: user.shift,
    ward:  user.ward,
    empId: user.empId,
  };
  // Route to the correct first screen by role
  nav(user.role === 'nurse' ? 'n1' : 'n5');
};

function logout() {
  APP.role = null; APP.user = null; APP.screen = null; APP.history = [];
  sessionStorage.removeItem('foqal_token');
  sessionStorage.removeItem('foqal_user');
  document.body.classList.add('login-mode');
  document.getElementById('app-shell').style.display  = 'none';
  document.getElementById('login-wrap').style.display = '';
}

// Re-hydrate session on page refresh (if token still exists)
(function() {
  const raw = sessionStorage.getItem('foqal_user');
  if (!raw) return;
  try {
    const user = JSON.parse(raw);
    document.getElementById('login-wrap').style.display = 'none';
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

/* ── N1 — NEWS2 PRIORITY DASHBOARD ─────────────────────────── */
SCREENS.n1 = () => {
  const patients = (APP.data.n1?.patients || []);
  let critCount = 0, medCount = 0, lowCount = 0, staleCount = 0;
  
  APP.n1_filter = APP.n1_filter || 'all';

  patients.forEach(p => {
    if (p.news2 >= 7) critCount++;
    else if (p.news2 >= 5) medCount++;
    else lowCount++;
    
    // Naive stale check (older than 6 hrs or missing)
    if (!p.vitals || !p.vitals.bp_time) staleCount++;
  });

  const filteredPatients = patients.filter(p => {
    if (APP.n1_filter === 'critical') return p.news2 >= 7;
    if (APP.n1_filter === 'medium') return p.news2 >= 5 && p.news2 < 7;
    if (APP.n1_filter === 'low') return p.news2 < 5;
    if (APP.n1_filter === 'stale') return !p.vitals || !p.vitals.bp_time;
    return true;
  });

  const nowStr = new Date().toLocaleString('en-IN', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'});

  return `
<div class="bc"><span>Ward 4B / 4C</span><span class="bc-sep">/</span><span>NEWS2 Priority Dashboard</span></div>
<div class="sh">
  <h1 class="sh-title">NEWS2 Priority Dashboard</h1>
  <div class="sh-actions">
    <span class="muted small">${nowStr}</span>
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

<div class="tw"><table>
  <thead><tr>
    <th>Patient</th><th>Ward</th><th>SpO₂</th><th>RR</th><th>BP</th>
    <th>HR</th><th>Temp</th><th>AVPU</th><th>NEWS2</th><th>Status</th><th>Actions</th>
  </tr></thead>
  <tbody>
    ${filteredPatients.map(p => {
      const score = p.news2 || 0;
      const rowClass = score >= 7 ? 'row-crit' : score >= 5 ? 'row-warn' : '';
      const scoreClass = score >= 7 ? 'n2s hi' : score >= 5 ? 'n2s med' : 'n2s lo';
      const statusBd = score >= 7 ? 'bd bd-t1' : score >= 5 ? 'bd bd-t2' : 'bd bd-t3';
      const statusLbl = score >= 7 ? 'Escalate' : score >= 5 ? 'Monitor' : 'Stable';
      
      const valCrit = (val, thres, op) => {
        if (!val || val === '--') return '';
        if (op === '<' && val < thres) return 'v-crit';
        if (op === '>' && val > thres) return 'v-crit';
        return '';
      };
      
      const timeHtml = t => t ? `<br><span class="muted small">${t}</span>` : '';
      const bpVal = p.bp ? p.bp.split('/')[0] : '';
      
      return `
        <tr class="${rowClass}" onclick="nav('n1b', ${p.id})">
          <td><b>${p.name}</b><br><span class="pid">PT-${p.id}</span></td>
          <td>${p.ward.split(' ')[1] || p.ward}</td>
          <td class="${valCrit(p.spo2, 92, '<')}">${p.spo2 || '-'}% ${timeHtml(p.spo2_time)}</td>
          <td class="${valCrit(p.rr, 21, '>')}">${p.rr || '-'} /m ${timeHtml(p.rr_time)}</td>
          <td class="${valCrit(bpVal, 90, '<')}">${p.bp || '-'} mmHg ${timeHtml(p.bp_time)}</td>
          <td class="${valCrit(p.hr, 110, '>')}">${p.hr || '-'} bpm ${timeHtml(p.hr_time)}</td>
          <td class="${valCrit(p.temp, 38.0, '>')}">${p.temp || '-'}°C ${timeHtml(p.temp_time)}</td>
          <td>${p.avpu || 'A'} ${timeHtml(p.avpu_time)}</td>
          <td><span class="${scoreClass}">${score}</span></td>
          <td><span class="${statusBd}">${statusLbl}</span></td>
          <td>
            ${score >= 5 ? `<button class="btn ${score >= 7 ? 'btn-danger' : 'btn-warn'} btn-xs" onclick="event.stopPropagation();nav('n2', ${p.id})">Escalate</button>` : ''}
            <button class="btn btn-sec btn-xs" onclick="event.stopPropagation()">Ack</button>
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

  const vitals = `
    <div class="grid2">
      <div class="card">
        <div class="card-title">Current Vitals <span class="muted" style="font-weight:400;font-size:11px">${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
        <table style="width:100%;font-size:12.5px"><tbody>
          ${[
            ['SpO₂',             (v.spo2 || '-') + '%',               valCrit(v.spo2, 92, '<'), v.spo2 < 92 ? '⚠ LOW' : ''],
            ['Respiratory Rate', (v.resp_rate || '-') + ' /min',      valCrit(v.resp_rate, 21, '>'), v.resp_rate > 21 ? '⚠ HIGH' : ''],
            ['Blood Pressure',   (v.sbp || '-') + '/' + (v.dbp || '-') + ' mmHg', valCrit(v.sbp, 90, '<'), v.sbp < 90 ? '⚠ LOW' : ''],
            ['Heart Rate',       (v.heart_rate || '-') + ' bpm',      valCrit(v.heart_rate, 110, '>'), v.heart_rate > 110 ? '⚠ HIGH' : ''],
            ['Temperature',      (v.temperature || '-') + '°C',       valCrit(v.temperature, 38.0, '>'), v.temperature > 38.0 ? '⚠ ELEVATED' : ''],
            ['AVPU',             v.consciousness || 'A',          '',       ''],
            ['NEWS2 Score',      score,                  isCrit ? 'v-crit' : '', isCrit ? '🔴 CRITICAL' : ''],
          ].map(([lbl,val,cls,f]) => `
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
            ${(p.trajectory || []).map(t => `
              <tr>
                <td class="muted">${t.time}</td>
                <td>${t.spo2}%</td>
                <td>${t.rr}</td>
                <td>${t.bp}</td>
                <td>${t.hr}</td>
                <td>--</td>
              </tr>
            `).join('')}
            ${(!p.trajectory || p.trajectory.length === 0) ? `<tr><td colspan="6" class="muted small text-center" style="padding: 20px">Trends dynamically loaded from timeseries...</td></tr>` : ''}
          </tbody>
        </table></div>
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
    </div>`;

  return `
<div class="bc"><span class="bc-link" onclick="nav('n1')">NEWS2 Dashboard</span><span class="bc-sep">/</span><span>Patient Detail</span></div>
<div class="sh">
  <h1 class="sh-title">${p.name || 'Unknown'} <span class="pid" style="font-size:13px">PT-${p.id || ''}</span></h1>
  <div class="sh-actions">
    <span class="bd ${bdClass}" style="font-size:12px;padding:5px 12px">NEWS2: ${score} — ${lbl}</span>
    ${score >= 5 ? `<button class="btn ${isCrit ? 'btn-danger' : 'btn-warn'} btn-sm" onclick="nav('n2', ${p.id})">Escalate Now</button>` : ''}
  </div>
</div>

<div class="tab-strip">
  <button class="tab-btn${APP.n1b_tab==='vitals'?' active':''}" onclick="APP.n1b_tab='vitals';renderAll()">Vital Signs</button>
  <button class="tab-btn${APP.n1b_tab==='drug-lab'?' active':''}" onclick="APP.n1b_tab='drug-lab';renderAll()">Drug-Lab Alerts</button>
</div>

${APP.n1b_tab === 'vitals' ? vitals : druglab}

<div style="display:flex;gap:8px;margin-top:16px">
  <button class="btn btn-sec btn-sm" onclick="nav('n1')">← Back to Dashboard</button>
  ${score >= 5 ? `<button class="btn btn-danger btn-sm" onclick="nav('n2', ${p.id})">Escalate Patient</button>` : ''}
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
<div class="sh"><h1 class="sh-title">Raise Escalation — PT-${p.id}</h1></div>
<div class="alert al-err">🔴 NEWS2 Score: ${score} — CRITICAL · ${p.name} · ${p.ward}</div>

<div style="max-width:580px">
  <div class="card" style="margin-bottom:12px">
    <div class="card-title">Vitals at Time of Escalation</div>
    <div class="grid3">
      <div><div class="muted small">SpO₂</div><div class="bold v-crit">${v.spo2||'-'}%</div></div>
      <div><div class="muted small">RR</div><div class="bold v-crit">${v.resp_rate||'-'} /min</div></div>
      <div><div class="muted small">BP</div><div class="bold v-crit">${v.sbp||'-'}/${v.dbp||'-'}</div></div>
      <div><div class="muted small">HR</div><div class="bold v-crit">${v.heart_rate||'-'} bpm</div></div>
      <div><div class="muted small">Temp</div><div class="bold">${v.temperature||'-'}°C</div></div>
      <div><div class="muted small">AVPU</div><div class="bold">${v.consciousness||'A'}</div></div>
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

${v.spo2 ? `<div class="card" style="max-width:560px;margin-bottom:16px">
  <div class="card-title">Vitals at Time of Escalation</div>
  <div class="grid3">
    <div><div class="muted small">SpO2</div><div class="bold ${(v.spo2||99)<92?'v-crit':''}">` + (v.spo2||'--') + `%</div></div>
    <div><div class="muted small">RR</div><div class="bold">` + (v.resp_rate||'--') + ` /min</div></div>
    <div><div class="muted small">BP</div><div class="bold">` + (v.sbp||'--') + `/` + (v.dbp||'--') + `</div></div>
    <div><div class="muted small">HR</div><div class="bold">` + (v.heart_rate||'--') + ` bpm</div></div>
    <div><div class="muted small">Temp</div><div class="bold">` + (v.temperature||'--') + `&deg;C</div></div>
    <div><div class="muted small">AVPU</div><div class="bold">` + (v.consciousness||'A') + `</div></div>
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
SCREENS.n4b = () => `
<div class="bc"><span class="bc-link" onclick="nav('n4')">Status Log</span><span class="bc-sep">/</span><span>Resolved</span></div>
<div class="sh"><h1 class="sh-title">Escalation Resolved — PT-24-0092</h1></div>
<div class="alert al-ok">✅ Dr. Anand Sharma marked escalation resolved — 02 Jun 2026, 15:10</div>
<div class="tw"><table>
  <thead><tr><th>Patient</th><th>SpO₂</th><th>RR</th><th>BP</th><th>HR</th><th>NEWS2</th><th>Status</th></tr></thead>
  <tbody>
    <tr>
      <td><b>Priya Sharma</b><br><span class="pid">PT-24-0092</span> <span style="font-size:10px;color:var(--t3)">Resolved 15:10</span></td>
      <td style="color:var(--t3)">96%</td><td>16</td><td>108/70</td><td>88</td>
      <td><span class="n2s lo">3</span></td><td><span class="bd bd-t3">✓ Resolved</span></td>
    </tr>
    <tr class="row-warn"><td><b>Arun Verma</b><br><span class="pid">PT-24-0103</span></td><td class="v-warn">93%</td><td class="v-warn">20</td><td>96/60</td><td>108</td><td><span class="n2s med">6</span></td><td><span class="bd bd-t2">Monitor</span></td></tr>
    <tr><td><b>Rajesh Kumar</b><br><span class="pid">PT-24-0087</span></td><td>94%</td><td>18</td><td>102/68</td><td>96</td><td><span class="n2s med">4</span></td><td><span class="bd bd-t2">Watch</span></td></tr>
    <tr><td><b>Mohan Singh</b><br><span class="pid">PT-24-0095</span></td><td style="color:var(--t3)">97%</td><td>14</td><td>118/76</td><td>82</td><td><span class="n2s lo">1</span></td><td><span class="bd bd-t3">Stable</span></td></tr>
  </tbody>
</table></div>
<div style="display:flex;gap:8px;margin-top:12px">
  <button class="btn btn-pri" onclick="nav('n1')">← Back to Dashboard</button>
</div>`;

/* ── N5 — CHARGE NURSE QUEUE ────────────────────────────────── */
SCREENS.n5 = () => {
  const allEsc = (APP.data.n5?.escalations || []);
  const escalations = allEsc.filter(e => e.status === 'active');
  const emptyState = `<div style="text-align:center;padding:72px 24px;color:var(--muted)">
    <div style="font-size:44px;margin-bottom:14px">&#10003;</div>
    <div style="font-size:15px;font-weight:700;color:var(--t3);margin-bottom:6px">No Active Escalations</div>
    <div style="font-size:12.5px">All patients in Ward 4B/4C are within normal NEWS2 thresholds.</div>
  </div>`;

  return `
<div class="bc"><span>Ward 4B / 4C</span><span class="bc-sep">/</span><span>Escalation Queue</span></div>
<div class="sh">
  <h1 class="sh-title">Escalation Queue</h1>
  <div class="sh-actions">
    <span class="muted small">${new Date().toLocaleString('en-IN', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'})}</span>
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
<div class="tw" style="margin-bottom:14px"><table>
  <thead><tr><th>Patient</th><th>Ward</th><th>NEWS2</th><th>Escalated At</th><th>Escalated By</th><th>Attending</th><th>Status / SLA</th><th>Action</th></tr></thead>
  <tbody>
    ${escalations.map(e => {
      const isBreached = false;
      return `
        <tr class="${isBreached ? 'row-crit' : ''}">
          <td><b>${e.patientName}</b><br><span class="pid">PT-${e.patientId}</span></td>
          <td>${e.ward} / Bed ${e.bed}</td>
          <td><span class="n2s ${e.news2 >= 7 ? 'hi' : 'med'}">${e.news2}</span></td>
          <td class="mono">${e.escalatedAt || '--'}</td>
          <td>${e.escalatedBy || '--'}</td>
          <td>${e.attending || '--'}</td>
          <td><span class="bd bd-t2">Active</span></td>
          <td>
            <button class="btn btn-sec btn-xs" onclick="openModal('reescalate')">Review</button>
          </td>
        </tr>
      `;
    }).join('')}
  </tbody>
</table></div>
<div class="alert al-info">Charge Nurse has oversight of all ward escalations. Re-escalation routes to the on-call consultant or Code Blue team.</div>
`}`;
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
SCREENS.dl3 = () => `
<div class="bc"><span class="bc-link" onclick="nav('n1b')">Patient Detail</span><span class="bc-sep">/</span><span>Drug-Lab Awareness</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Awareness — Nurse View</h1></div>
<div class="alert al-info">Nurse awareness only — clinical actions (override / hold / consult) must be taken by the Attending Physician. Document any adverse observations in the escalation form.</div>

<div class="dlf t1">
  <div class="dlf-bd">
    <div class="flex-r">
      <div class="dlf-title">⚠ T1 — Warfarin + Aspirin (PT-24-0087 Rajesh Kumar)</div>
      <span class="bd bd-t1">T1 CRITICAL</span>
    </div>
    <div class="dlf-desc"><b>Risk:</b> HIGH BLEEDING RISK. Monitor for signs of GI bleed (melena, haematemesis), unusual bruising, blood in urine. <b>Attending action taken:</b> Warfarin held pending haematology review.</div>
    <div style="font-size:11.5px;color:var(--t3);font-weight:600;margin-top:6px">✓ Attending action recorded — monitoring in place</div>
  </div>
</div>

<div class="dlf t1" style="margin-bottom:12px">
  <div class="dlf-bd">
    <div class="flex-r">
      <div class="dlf-title">⚠ T1 — Heparin + Aspirin (PT-24-0092 Priya Sharma)</div>
      <span class="bd bd-t1">T1 CRITICAL</span>
    </div>
    <div class="dlf-desc"><b>Risk:</b> Post-PCI anticoagulation risk. Monitor bleeding sites, puncture site haematoma, neurological changes. Alert attending immediately if any bleed signs observed.</div>
    <div style="font-size:11.5px;color:var(--t2);font-weight:600;margin-top:6px">⏳ Pending attending action</div>
  </div>
</div>

<div class="card">
  <div class="card-title">Observation Checklist — report immediately if any observed</div>
  <div class="check-row"><input type="checkbox"> Unusual bruising or petechiae</div>
  <div class="check-row"><input type="checkbox"> Black or tarry stools (melena)</div>
  <div class="check-row"><input type="checkbox"> Blood in urine (haematuria)</div>
  <div class="check-row"><input type="checkbox"> Haematemesis (blood in vomit)</div>
  <div class="check-row"><input type="checkbox"> Prolonged bleeding from puncture sites</div>
  <div class="check-row"><input type="checkbox"> Sudden confusion or neurological change</div>
  <div style="margin-top:12px;display:flex;gap:8px">
    <button class="btn btn-sec btn-sm" onclick="nav('n2')">Log in Escalation</button>
  </div>
</div>`;

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
          <span style="font-size:11px;color:var(--t2);font-weight:600">Pending attending action</span>
          ${a.severity === 'CRITICAL' ? `<span class="dlf-link" onclick="nav('dlcosign')">T1 Co-Sign Required &rarr;</span>` : ''}
        </div>
      </div></div>`;
    }).join('')}`;
};

/* ── DL2 — FLAG DETAIL & ACTION (via Attending — accessible to Charge Nurse) ── */
SCREENS.dl2 = () => `
<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span><span class="bc-sep">/</span><span>Flag Detail</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Flag Detail — T1 Warfarin + Aspirin</h1></div>

<div class="grid2">
  <div>
    <div class="dlf t1" style="margin-bottom:12px">
      <div class="dlf-bd">
        <div class="dlf-title">⚠ T1 CRITICAL — Warfarin 5mg OD + Aspirin 75mg OD</div>
        <div class="dlf-desc" style="margin-top:8px;line-height:1.8">
          <b>Risk:</b> HIGH BLEEDING RISK<br>
          <b>INR:</b> 3.2 (therapeutic target: 2.0–3.0 — currently supratherapeutic)<br>
          <b>Indication for Aspirin:</b> Coronary artery disease (documented)<br>
          <b>Indication for Warfarin:</b> Dilated cardiomyopathy, EF 28% (thromboembolic prophylaxis)<br>
          <b>Risk level:</b> Combined anticoagulation increases annual GI bleed risk by 3.2× (ESC 2023)<br>
          <b>Guideline:</b> ACCP 2022 — Avoid dual antithrombotic in DCM unless mechanical valve or AF with PCI
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Evidence</div>
      <div class="tw" style="border:none"><table><tbody>
        <tr><td class="muted">Lab: INR</td><td class="bold" style="color:var(--t1)">3.2 (02 Jun 2026)</td></tr>
        <tr><td class="muted">Warfarin dose</td><td>5mg OD (oral)</td></tr>
        <tr><td class="muted">Aspirin dose</td><td>75mg OD (oral)</td></tr>
        <tr><td class="muted">Rule</td><td class="mono">R-001 — Warfarin + Aspirin · T1</td></tr>
        <tr><td class="muted">Reference</td><td>ESC Heart Failure Guidelines 2023</td></tr>
      </tbody></table></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Required Action — Choose One</div>
    <div style="display:flex;flex-direction:column;gap:10px">
      <div class="card action-card${APP.dl2_action==='override'?' selected-action':''}" style="border:2px solid ${APP.dl2_action==='override'?'var(--t1)':'var(--border)'};cursor:pointer" onclick="APP.dl2_action='override';renderAll();nav('dlcosign')">
        <div class="flex-r" style="margin-bottom:4px">
          <input type="radio" name="dl-action" ${APP.dl2_action==='override'?'checked':''}> <b>Override with clinical justification</b> <span class="bd bd-t1" style="margin-left:auto">Requires T1 Co-sign</span>
        </div>
        <div style="font-size:11.5px;color:var(--ink2)">Document why both drugs are clinically necessary. Charge Nurse co-sign required for T1 override.</div>
      </div>
      <div class="card action-card${APP.dl2_action==='hold'?' selected-action':''}" style="border:2px solid ${APP.dl2_action==='hold'?'var(--p)':'var(--border)'};cursor:pointer" onclick="APP.dl2_action='hold';renderAll()">
        <div class="flex-r" style="margin-bottom:4px">
          <input type="radio" name="dl-action" ${APP.dl2_action==='hold'?'checked':''}> <b>Hold Warfarin — pending haematology review</b>
        </div>
        <div style="font-size:11.5px;color:var(--ink2)">Suspend Warfarin until haematology consultation. Aspirin continues as primary antithrombotic. INR monitoring in 5 days.</div>
      </div>
      <div class="card action-card${APP.dl2_action==='pharmacist'?' selected-action':''}" style="border:2px solid ${APP.dl2_action==='pharmacist'?'var(--p)':'var(--border)'};cursor:pointer" onclick="APP.dl2_action='pharmacist';renderAll()">
        <div class="flex-r" style="margin-bottom:4px">
          <input type="radio" name="dl-action" ${APP.dl2_action==='pharmacist'?'checked':''}> <b>Consult Clinical Pharmacist</b>
        </div>
        <div style="font-size:11.5px;color:var(--ink2)">Refer to clinical pharmacist for formal medication review. Action pending pharmacist recommendation.</div>
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px">
      <button class="btn btn-sec" onclick="nav('dl1')">← Back</button>
      <button class="btn btn-pri" onclick="nav('dl2b')">Submit Action →</button>
    </div>
  </div>
</div>`;

/* ── DL2b — DL ACTION CONFIRMATION ─────────────────────────── */
SCREENS.dl2b = () => `
<div class="bc"><span class="bc-link" onclick="nav('dl2')">Flag Detail</span><span class="bc-sep">/</span><span>Confirmation</span></div>
<div class="sh"><h1 class="sh-title">Drug-Lab Action Recorded</h1></div>
<div class="alert al-ok">✅ Action recorded: Warfarin held pending haematology review</div>
<div class="card" style="max-width:500px">
  <div class="tw" style="border:none;margin-bottom:14px"><table><tbody>
    <tr><td class="muted">Flag</td><td>Warfarin + Aspirin — T1</td></tr>
    <tr><td class="muted">Action taken</td><td class="bold">Hold Warfarin — haematology review</td></tr>
    <tr><td class="muted">Recorded by</td><td>Dr. Anand Sharma (Attending)</td></tr>
    <tr><td class="muted">Timestamp</td><td class="mono">02 Jun 2026, 14:20</td></tr>
    <tr><td class="muted">Status</td><td><span class="bd bd-t3">Resolved</span></td></tr>
    <tr><td class="muted">NABH audit</td><td>Logged · Haematology referral queued</td></tr>
  </tbody></table></div>
  <div class="alert al-info">ℹ️ This action is recorded in the NABH audit trail. The flag will no longer block the discharge summary signing flow.</div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-sec" onclick="nav('dl1')">← Back to Flags</button>
  </div>
</div>`;

/* ── DL CO-SIGN (Charge Nurse action) ───────────────────────── */
SCREENS.dlcosign = () => `
<div class="bc"><span class="bc-link" onclick="nav('dl1')">DL Flags</span><span class="bc-sep">/</span><span>Tier 1 Co-Sign</span></div>
<div class="sh"><h1 class="sh-title">Tier 1 Override — Charge Nurse Co-Sign Required</h1></div>
<div class="alert al-err">🔐 Overriding a T1 Drug-Lab flag requires a second sign-off from the Charge Nurse. This is an NABH mandatory safety requirement.</div>

<div class="grid2">
  <div class="card">
    <div class="card-title">Override Justification (Attending)</div>
    <div class="fg"><label class="fl">Clinical Justification</label>
      <textarea class="fi" rows="5">Patient has dilated cardiomyopathy with EF 28% (high thromboembolic risk — Warfarin mandatory) AND documented triple vessel CAD requiring antiplatelet therapy. Short-term dual therapy acceptable with close INR monitoring. Target INR 2.0–2.5. Haematology review scheduled.</textarea>
    </div>
    <div class="fg"><label class="fl">Attending Signature</label>
      <input class="fi" value="Dr. Anand Sharma · MCI-98765-DL">
    </div>
    <div class="fg"><label class="fl">Timestamp</label>
      <input class="fi" value="02 Jun 2026, 14:22" readonly style="background:var(--surf)">
    </div>
  </div>
  <div class="card">
    <div class="card-title">Charge Nurse Co-Sign</div>
    <div class="muted small" style="margin-bottom:12px">Charge Nurse Leena Kurup must verify the justification and provide credentials to complete the override.</div>
    <div class="fg"><label class="fl">Charge Nurse Name</label>
      <input class="fi" value="Sister Leena Kurup">
    </div>
    <div class="fg"><label class="fl">Employee ID</label>
      <input class="fi" placeholder="EMP-XXXX">
    </div>
    <div class="fg"><label class="fl">Password</label>
      <input class="fi" type="password" placeholder="Enter credentials">
    </div>
    <div class="alert al-warn" style="margin-top:10px">⚠️ By co-signing, you acknowledge the clinical justification and accept oversight responsibility for this override.</div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-sec" onclick="nav('dl1')">← Back</button>
      <button class="btn btn-pri" onclick="openModal('cosign_confirm')">Co-Sign Override ✓</button>
    </div>
  </div>
</div>`;

// Screen — Doctor Dashboard (Signing Queue)

// Deterministic synthetic name — same seed algorithm as dashboard.html / upload.html
function _ddSeeded(hadmId, max) {
  let h = parseInt(hadmId) || 0;
  h = ((h >> 16) ^ h) * 0x45d9f3b;
  h = ((h >> 16) ^ h) * 0x45d9f3b;
  h = (h >> 16) ^ h;
  return Math.abs(h) % max;
}
function _ddSeeded2(hadmId, salt, max) { return _ddSeeded(hadmId * 31 + salt, max); }
const _DD_NAMES_M = ['Rajesh','Mohan','Dinesh','Arun','Suresh','Vijay','Sanjay','Ramesh','Deepak','Nitin',
                     'Ashok','Prakash','Anil','Manoj','Rakesh','Vinod','Sunil','Ravi','Ajay','Amit'];
const _DD_NAMES_F = ['Priya','Kavita','Sunita','Anjali','Leela','Rekha','Suman','Anita','Meena','Geeta',
                     'Pooja','Neha','Divya','Shalini','Radha','Usha','Lata','Nisha','Swati','Kiran'];
const _DD_SURNAMES = ['Kumar','Singh','Joshi','Verma','Patel','Malhotra','Gupta','Sharma','Rao','Jain',
                      'Iyer','Menon','Nair','Desai','Varma','Devi','Reddy','Chatterjee','Mehta','Kapoor',
                      'Choudhary','Pillai','Krishnan','Bose','Agarwal','Bhatia','Saxena','Trivedi','Bhosale','Kulkarni'];
function _ddSynthName(hadmId) {
  const isMale = _ddSeeded(hadmId, 2) === 0;
  const first   = isMale ? _DD_NAMES_M[_ddSeeded(hadmId, _DD_NAMES_M.length)]
                         : _DD_NAMES_F[_ddSeeded2(hadmId, 7, _DD_NAMES_F.length)];
  const last    = _DD_SURNAMES[_ddSeeded2(hadmId, 17, _DD_SURNAMES.length)];
  return `${first} ${last}`;
}

let _dd = { encounters: null, loading: false, error: null, attempt: 0, errorStats: null, tab: 'queue', dlPanelHadmId: null, statusFilter: 'all' };

window.ddInvalidate = () => { _dd.encounters = null; _dd.attempt = 0; _dd.errorStats = null; _dd.statusFilter = 'all'; };

// ── Regen poller — polls every 5s while any encounter is Processing ──────────
let _ddRegenPollTimer = null;
function _ddStartRegenPoll() {
  if (_ddRegenPollTimer) return;
  _ddRegenPollTimer = setInterval(async () => {
    const processing = (_dd.encounters || []).filter(e => e.status === 'Processing');
    if (!processing.length) { clearInterval(_ddRegenPollTimer); _ddRegenPollTimer = null; return; }
    try {
      const base = window.FOQAL_API_BASE || 'http://localhost:6010';
      const fresh = await fetch(`${base}/api/encounters`).then(r => r.ok ? r.json() : null);
      if (!fresh) return;
      const freshList = Array.isArray(fresh) ? fresh : (fresh.encounters || []);
      let changed = false;
      const staleOnes = [];
      (_dd.encounters || []).forEach(enc => {
        const updated = freshList.find(f => f.hadm_id === enc.hadm_id || f.id === enc.id);
        if (updated && updated.status !== enc.status) {
          // Merge every server field, not just status -- otherwise a stale
          // rejection_count/revision_reason left over from before this
          // Processing run keeps mislabelling the row as "Regenerating".
          Object.assign(enc, updated);
          staleOnes.push(enc);
          changed = true;
        }
      });
      if (staleOnes.length) {
        // The encounter just finished Processing -- its summary (T1/T2/T3/DL
        // counts, content) was only just written, so refetch it too. Without
        // this the row showed zeroed badges and blocked signing until a
        // manual page reload.
        await Promise.all(staleOnes.map(async enc => {
          const sum = await fetchSummary(enc.id).catch(() => null);
          if (sum) enc.summary = sum;
        }));
      }
      if (changed) renderApp();
      // Stop if none left Processing
      if (!(_dd.encounters || []).some(e => e.status === 'Processing')) {
        clearInterval(_ddRegenPollTimer); _ddRegenPollTimer = null;
      }
    } catch (_) {}
  }, 5000);
}
function _ddMaybeStartPoll() {
  if ((_dd.encounters || []).some(e => e.status === 'Processing')) _ddStartRegenPoll();
}
function _ddMaybeStopPoll() {
  if (_ddLivePollTimer) { clearTimeout(_ddLivePollTimer); _ddLivePollTimer = null; }
  if (_ddRegenPollTimer) { clearInterval(_ddRegenPollTimer); _ddRegenPollTimer = null; }
}

async function ddLoad() {
  if (_dd.loading) return;
  _dd.loading = true;
  _dd.error   = null;
  _dd.attempt = (_dd.attempt || 0) + 1;
  renderApp();
  try {
    const raw  = await (typeof _fetchWithTimeout === "function"
      ? _fetchWithTimeout(() => fetchEncounters(), 45000)
      : fetchEncounters());
    const encs = Array.isArray(raw) ? raw : (raw.encounters || []);
    const withSummaries = await Promise.all(encs.map(async e => {
      const sum = await fetchSummary(e.id).catch(() => null);
      return { ...e, summary: sum || null };
    }));
    _dd.encounters = withSummaries;
    _ddMaybeStartPoll();
    // Fetch error stats for gate widget (non-blocking)
    apiGetErrorStats().then(s => { _dd.errorStats = s; renderApp(); }).catch(() => {});
  } catch (err) {
    if (_dd.attempt < 3) {
      _dd.loading = false;
      setTimeout(ddLoad, _dd.attempt * 4000);
      return;
    }
    _dd.error      = err.message;
    _dd.encounters = [];
  }
  _dd.loading = false;
  renderApp();
  _ddLivePoll();
}

// ── General background poll — catches all status changes every 8s ─────────────
let _ddLivePollTimer = null;
function _ddLivePoll() {
  clearTimeout(_ddLivePollTimer);
  _ddLivePollTimer = setTimeout(async () => {
    try {
      const base = window.FOQAL_API_BASE || 'http://localhost:6010';
      const fresh = await fetch(`${base}/api/encounters`).then(r => r.ok ? r.json() : null);
      if (fresh) {
        const freshList = Array.isArray(fresh) ? fresh : (fresh.encounters || []);
        let changed = false;
        const staleOnes = [];
        (_dd.encounters || []).forEach(enc => {
          const updated = freshList.find(f => f.hadm_id === enc.hadm_id || f.id === enc.id);
          if (updated && updated.status !== enc.status) {
            // Merge every field the server has (status, rejection_count,
            // revision_reason, ...) -- patching .status alone left stale
            // rejection_count/revision_reason on the cached object, which is
            // why a patient could keep showing "Regenerating" long after
            // that was no longer true.
            Object.assign(enc, updated);
            staleOnes.push(enc);
            changed = true;
          }
        });
        // The encounter's summary (T1/T2/T3/DL counts, content) is fetched
        // separately from /api/encounters -- a status change means the
        // summary just got written/updated server-side too, so refetch it.
        // Without this the row kept showing zeroed badges and blocked
        // signing until a manual page reload.
        if (staleOnes.length) {
          await Promise.all(staleOnes.map(async enc => {
            const sum = await fetchSummary(enc.id).catch(() => null);
            if (sum) enc.summary = sum;
          }));
        }
        // Pick up brand-new encounters (e.g. a resident just submitted one for
        // review) -- the loop above only updates encounters already known
        // locally, so without this a new patient only ever showed up after a
        // manual page reload.
        const known = new Set((_dd.encounters || []).map(e => e.hadm_id));
        const newOnes = freshList.filter(f => !known.has(f.hadm_id));
        if (newOnes.length) {
          const withSummaries = await Promise.all(newOnes.map(async e => {
            const sum = await fetchSummary(e.id).catch(() => null);
            return { ...e, summary: sum || null };
          }));
          _dd.encounters = [...(_dd.encounters || []), ...withSummaries];
          changed = true;
        }
        if (changed) {
          _ddMaybeStartPoll();
          renderApp();
        }
      }
    } catch (_) {}
    _ddLivePoll();
  }, 8000);
}

// Takes full encounter object so we can read hadm_id for gap-count lookup
function _ddFlags(enc) {
  const summary = enc?.summary ?? enc; // backward-compat: accept either enc or summary
  // 1. Prefer gap counts persisted to DB at generate time (reliable across sessions/browsers)
  if (summary?.gap_t1 != null || summary?.gap_t2 != null) {
    return { t1: summary.gap_t1 || 0, t2: summary.gap_t2 || 0, t3: summary.gap_t3 || 0 };
  }
  // 2. Fall back to localStorage (same browser session as upload)
  try {
    const hadmId = enc?.hadm_id || enc?.hadmId;
    if (hadmId) {
      const raw = localStorage.getItem('gap_counts_' + hadmId);
      if (raw) {
        const gc = JSON.parse(raw);
        if (gc.t1 > 0 || gc.t2 > 0 || gc.t3 > 0) return { t1: gc.t1 || 0, t2: gc.t2 || 0, t3: gc.t3 || 0 };
      }
    }
  } catch {}
  // 3. Fall back to NLI support-score counting from parsed summary
  if (!summary?.content) return { t1: 0, t2: 0, t3: 0 };
  try {
    if (typeof rv2ParseSummary !== "function") return { t1: 0, t2: 0, t3: 0 };
    const secs = rv2ParseSummary(summary.content);
    let t1 = 0, t2 = 0;
    for (const s of secs) {
      for (const p of (s.passages || [])) {
        if (p.support === "unsupported") t1++;
        else if (p.support === "uncertain") t2++;
      }
    }
    return { t1, t2, t3: 0 };
  } catch { return { t1: 0, t2: 0, t3: 0 }; }
}

// Inject spin keyframe for regen spinner (once)
if (!document.getElementById('_dd-spin-style')) {
  const _s = document.createElement('style');
  _s.id = '_dd-spin-style';
  _s.textContent = '@keyframes ddSpin{to{transform:rotate(360deg)}}';
  document.head.appendChild(_s);
}

// Prototype-exact badge helper (translates S4a .bd classes)
const _BD = "display:inline-flex;align-items:center;padding:2px 7px;border-radius:10px;font-size:10.5px;font-weight:700";
const _BD_STYLES = {
  t1:   "background:#fef9c3;color:#854d0e",   // T1 Minor — light yellow
  t2:   "background:#fffbeb;color:#d97706",   // T2 Medication — amber
  t3:   "background:#fef2f2;color:#dc2626",   // T3 Critical — red
  blue: "background:#eff6ff;color:#1e40af",
  gray: "background:#f3f4f6;color:#4b5563",
  red:  "background:#fef2f2;color:#dc2626",
};
function _ddbadge(type, text) {
  return `<span style="${_BD};${_BD_STYLES[type]||_BD_STYLES.gray}">${text}</span>`;
}

// Returns { t1, t2, t3, gaps: [{tier, section, reason}] } from Pass 3 verification results.
function _ddGaps(enc) {
  const summary = enc?.summary;
  const rows = Array.isArray(summary?.gap_rows) ? summary.gap_rows : [];
  // Filter out stale pre-generation file-gap predictions (contain upload-analysis phrases)
  const _stalePatterns = ['not uploaded', 'not found in uploaded', 'AI will write generic', 'AI may fabricate', 'AI may miss'];
  const _isStale = r => _stalePatterns.some(p => (r.missing || '').includes(p));
  const p3rows = rows.filter(r => !_isStale(r));
  const gaps = p3rows.map(r => {
    const issues = Array.isArray(r.issues) ? r.issues.map(i => typeof i === 'string' ? i : (i.description || '')).filter(Boolean) : [];
    return { tier: r.tier, section: r.title, reason: issues.join('; ') || r.missing || '' };
  });
  return {
    t1: summary?.gap_t1 || 0,
    t2: summary?.gap_t2 || 0,
    t3: summary?.gap_t3 || 0,
    gaps,
  };
}

// Prototype-exact button base
const _BTNBASE = "display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;font-size:11.5px;font-weight:500;cursor:pointer;white-space:nowrap;font-family:inherit;border:1px solid transparent";

SCREEN_RENDERERS["doctor-dashboard"] = function renderDoctorDashboard() {
  const user       = getUser();
  const _rawDoctorName = user?.full_name || user?.name || "Doctor";
  const doctorName = /^Dr\.?\s/i.test(_rawDoctorName) ? _rawDoctorName.replace(/^Dr\.?\s*/i, "") : _rawDoctorName;

  // Loading skeleton
  if (_dd.encounters === null || _dd.loading) {
    if (!_dd.loading) ddLoad();
    return `
      <div class="app-shell">
        <div class="main">
          ${renderTopbar({ user, crumbs:["Clinician","Signing Queue"] })}
          <div class="content">
            <div class="skeleton" style="height:13px;width:200px;border-radius:4px;margin-bottom:14px"></div>
            <div class="skeleton" style="height:26px;width:150px;border-radius:6px;margin-bottom:20px"></div>
            <div style="display:flex;gap:10px;margin-bottom:18px">
              ${[0,1,2].map(()=>`<div class="skeleton" style="flex:1;height:68px;border-radius:8px"></div>`).join("")}
            </div>
            <div class="skeleton" style="height:280px;border-radius:8px"></div>
          </div>
        </div>
      </div>`;
  }

  // Error state
  if (_dd.error) {
    return `
      <div class="app-shell">
        <div class="main">
          ${renderTopbar({ user, crumbs:["Clinician","Signing Queue"] })}
          <div class="content" style="display:flex;align-items:center;justify-content:center;min-height:50vh">
            <div style="text-align:center;padding:48px 32px;background:#fff;border-radius:8px;border:1px solid #e5e7eb;max-width:380px">
              <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:8px">Failed to load queue</div>
              <div style="font-size:13px;color:#6b7280;margin-bottom:20px">${_dd.error}</div>
              <button id="dd-refresh" style="${_BTNBASE};background:#fff;color:#111827;border-color:#e5e7eb">Try again</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  const encs = _dd.encounters;

  function _ddEncStatusKey(enc) {
    if (enc.status === "Processing") return 'processing';
    if (enc.status === "revision_requested" || enc.status === "Revision Requested") return 'revision_requested';
    if (enc.status === "Amendment Requested") return 'amendment_requested';
    if (enc.status === "Awaiting Review") {
      if ((enc.rejection_count || 0) > 0 || !!enc.revision_reason) return 'regenerated';
      if (enc.summary?.draft_saved_at) return 'draft';
      if (_ddFlags(enc).t1 === 0 && enc.summary?.content) return 'ready_to_sign';
      return 'in_review';
    }
    return 'all';
  }

  const _KEY_PRIO = { regenerated: 0, ready_to_sign: 1, draft: 2, processing: 3, in_review: 3, revision_requested: 4, amendment_requested: 4 };
  const activeEncs = encs
    .filter(e => ["Awaiting Review","revision_requested","Revision Requested","Amendment Requested","Processing"].includes(e.status))
    .sort((a, b) => {
      const d = (_KEY_PRIO[_ddEncStatusKey(a)] ?? 9) - (_KEY_PRIO[_ddEncStatusKey(b)] ?? 9);
      return d !== 0 ? d : new Date(a.created_at || 0) - new Date(b.created_at || 0);
    });
  // Once billing has fully closed the case out (paid / claim submitted /
  // TPA settled), it no longer needs to sit in the doctor's Completed queue
  // -- that's meant for recently-signed cases, not a permanent archive of
  // every discharge ever, regardless of what billing does with it afterward.
  const _BILLING_CLOSED = ['paid', 'claim_submitted', 'tpa_settled'];
  const completedEncs = encs.filter(e => e.status === "Signed Off" && !_BILLING_CLOSED.includes(e.billing_phase));
  const isCompleted   = _dd.tab === 'completed';

  const readyToSign       = activeEncs.filter(e => _ddEncStatusKey(e) === 'ready_to_sign').length;
  const sentForRevision   = activeEncs.filter(e => _ddEncStatusKey(e) === 'revision_requested').length;
  const sentForAmendment  = activeEncs.filter(e => _ddEncStatusKey(e) === 'amendment_requested').length;
  const draftCount        = activeEncs.filter(e => _ddEncStatusKey(e) === 'draft').length;

  const fmtDate = iso => iso
    ? new Date(iso).toLocaleDateString("en-IN", { day:"numeric", month:"short" })
    : "—";

  const filteredEncs = _dd.statusFilter === 'all'
    ? activeEncs
    : activeEncs.filter(e => _ddEncStatusKey(e) === _dd.statusFilter);

  const TD = "padding:10px 14px;border-bottom:1px solid #e5e7eb;color:#374151;vertical-align:middle";

  let firstActionIdx = -1;
  const rows = filteredEncs.map((enc, idx) => {
    const flags      = _ddFlags(enc);
    const gapInfo    = _ddGaps(enc);
    const hasSummary = !!enc.summary?.content;
    const draftAt    = enc.summary?.draft_saved_at;
    const isActive   = enc.status === "Awaiting Review" && hasSummary;

    if (isActive && firstActionIdx === -1) firstActionIdx = idx;
    const hl = idx === firstActionIdx;

    // T1/T2/T3/DL badges with hover tooltip reasons
    const t1Tip = gapInfo.gaps.filter(g=>g.tier==='T1').map(g=>g.section+': '+g.reason).join('&#10;');
    const t2Tip = gapInfo.gaps.filter(g=>g.tier==='T2').map(g=>g.section+': '+g.reason).join('&#10;');
    const t3Tip = gapInfo.gaps.filter(g=>g.tier==='T3').map(g=>g.section+': '+g.reason).join('&#10;');
    const t1Badge = gapInfo.t1 > 0
      ? `<span class="dd-tier-badge" data-tip="${t1Tip}" style="${_BD};${_BD_STYLES.t1};cursor:help">T1</span>`
      : `<span style="${_BD};${_BD_STYLES.gray}">T1</span>`;
    const t2Badge = gapInfo.t2 > 0
      ? `<span class="dd-tier-badge" data-tip="${t2Tip}" style="${_BD};${_BD_STYLES.t2};cursor:help">T2</span>`
      : `<span style="${_BD};${_BD_STYLES.gray}">T2</span>`;
    const t3Badge = gapInfo.t3 > 0
      ? `<span class="dd-tier-badge" data-tip="${t3Tip}" style="${_BD};${_BD_STYLES.t3};cursor:help">T3</span>`
      : `<span style="${_BD};${_BD_STYLES.gray}">T3</span>`;
    // dl_flags = total flagged sections count; tooltip and inline panel from gap_rows
    const dlCount = enc.summary?.dl_flags || 0;
    const _dlRows = Array.isArray(enc.summary?.gap_rows) ? enc.summary.gap_rows : [];
    const dlTip = _dlRows.map(r => {
      const _iss = Array.isArray(r.issues) ? r.issues.map(i=>typeof i==='string'?i:(i.description||'')).filter(Boolean) : [];
      return (r.title||r.sec||'') + ': ' + (_iss.join('; ')||r.missing||'');
    }).join('&#10;') || 'No detail available';
    const _dlOpen = _dd.dlPanelHadmId === enc.hadm_id;
    const dlBadge = dlCount > 0
      ? `<button class="dd-dl-btn dd-tier-badge" data-hadm-id="${enc.hadm_id}" data-tip="${dlTip}" style="${_BTNBASE};background:${_dlOpen?'#1e40af':'#eff6ff'};color:${_dlOpen?'#fff':'#1e40af'};border-color:#bfdbfe;font-size:10.5px;font-weight:700">${dlCount} DL</button>`
      : `<span style="${_BD};${_BD_STYLES.gray}">0 DL</span>`;

    const isRegen = (enc.rejection_count || 0) > 0 || !!enc.revision_reason;
    let statusBadge, actionBtn;

    if (enc.status === "Processing") {
      const _procLabel = isRegen ? "Regenerating…" : "Generating…";
      statusBadge = `<span style="display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:700;color:#1d4ed8;background:#eff6ff;border:1px solid #bfdbfe;border-radius:4px;padding:2px 8px"><span style="width:8px;height:8px;border:2px solid #93c5fd;border-top-color:#1d4ed8;border-radius:50%;display:inline-block;animation:ddSpin .8s linear infinite"></span>${_procLabel}</span>`;
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#fff;color:#6b7280;border-color:#e5e7eb;opacity:.6;cursor:default" disabled>In progress…</button>`;
    } else if (enc.status === "revision_requested" || enc.status === "Revision Requested") {
      statusBadge = _ddbadge("red", "Sent for Revision");
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#fff;color:#6b7280;border-color:#e5e7eb;opacity:.7;cursor:default" disabled>Waiting…</button>`;
    } else if (enc.status === "Amendment Requested") {
      statusBadge = `<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;color:#92400E;background:#FFF7ED;border:1px solid #F59E0B;border-radius:4px;padding:2px 8px">📝 Sent for Amendment</span>`;
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#fff;color:#6b7280;border-color:#e5e7eb;opacity:.7;cursor:default" disabled>Waiting…</button>`;
    } else if (isRegen) {
      statusBadge = `<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;color:#92400E;background:#FFF7ED;border:1px solid #F59E0B;border-radius:4px;padding:2px 8px">↺ Regenerated</span>`;
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#F59E0B;color:#fff;border-color:#F59E0B">${hasSummary ? "Review Regen →" : "Awaiting…"}</button>`;
    } else if (draftAt) {
      const _vNum = enc.summary?.version_num ? `V${enc.summary.version_num}` : 'Draft';
      statusBadge = _ddbadge("gray", _vNum);
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#fff;color:#111827;border-color:#e5e7eb">Review</button>`;
    } else if (flags.t1 === 0) {
      statusBadge = _ddbadge("t3", "Ready to Sign");
      actionBtn   = `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#800080;color:#fff;border-color:#800080">Sign →</button>`;
    } else {
      statusBadge = _ddbadge("blue", "In Review");
      actionBtn   = hl
        ? `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#800080;color:#fff;border-color:#800080">Review →</button>`
        : `<button class="dd-review-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#fff;color:#111827;border-color:#e5e7eb">Review</button>`;
    }

    const _dlPanel = _dlOpen && _dlRows.length > 0 ? `
      <tr><td colspan="8" style="padding:0;border-top:none">
        <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:0 0 8px 8px;padding:12px 18px;margin:0 4px 4px">
          <div style="font-size:11px;font-weight:700;color:#1e40af;margin-bottom:8px">Flagged Sections (Pass 3)</div>
          ${_dlRows.map(r => {
            const _tc = r.tier==='T3'?'#DC2626':r.tier==='T2'?'#92400E':'#854D0E';
            const _iss = Array.isArray(r.issues)?r.issues.map(i=>typeof i==='string'?i:(i.description||'')).filter(Boolean):[];
            return `<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px;font-size:12px">
              <span style="flex-shrink:0;font-weight:700;color:${_tc}">${r.tier||'?'}</span>
              <span><b style="color:#111827">${r.title||r.sec||''}</b>${_iss.length?' — '+_iss.join('; '): r.missing ? ' — '+r.missing : ''}</span>
            </div>`;
          }).join('')}
        </div>
      </td></tr>` : '';

    return `
      <tr class="dd-row" data-hadm-id="${enc.hadm_id}"
          style="${hl ? "background:#f7edf7;" : ""}cursor:${hasSummary ? "pointer" : "default"}">
        <td style="${TD}">
          <b style="font-size:13px;color:#111827">${enc.patient_name || _ddSynthName(enc.hadm_id)}</b><br>
          <span style="font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#6b7280">${fmtPid(enc.hadm_id, enc.display_id)}</span>
        </td>
        <td style="${TD}">${fmtDate(enc.created_at)}</td>
        <td style="${TD}">${t1Badge}</td>
        <td style="${TD}">${t2Badge}</td>
        <td style="${TD}">${t3Badge}</td>
        <td style="${TD}">${dlBadge}</td>
        <td style="${TD}">${statusBadge}</td>
        <td style="${TD}">${actionBtn}</td>
      </tr>${_dlPanel}`;
  }).join("");

  const emptyRow = _dd.statusFilter !== 'all'
    ? `<tr><td colspan="8" style="${TD};padding:64px 24px;text-align:center">
        <div style="font-size:32px;margin-bottom:10px">🔍</div>
        <div style="font-size:15px;font-weight:700;color:#374151;margin-bottom:4px">No matching cases</div>
        <div style="font-size:13px;color:#6b7280">No summaries match the selected filter.</div>
      </td></tr>`
    : `<tr><td colspan="8" style="${TD};padding:64px 24px;text-align:center">
        <div style="font-size:32px;margin-bottom:10px">✅</div>
        <div style="font-size:15px;font-weight:700;color:#059669;margin-bottom:4px">You're all caught up</div>
        <div style="font-size:13px;color:#6b7280">No summaries awaiting your review right now.</div>
      </td></tr>`;

  const completedRows = completedEncs.map((enc, idx) => {
    const signedAt = enc.summary?.signed_at || enc.updated_at || enc.created_at;
    return `
      <tr class="dd-completed-row" data-hadm-id="${enc.hadm_id}" style="cursor:pointer">
        <td style="${TD}">
          <b style="font-size:13px;color:#111827">${enc.patient_name || _ddSynthName(enc.hadm_id)}</b><br>
          <span style="font-family:'JetBrains Mono',monospace;font-size:9.5px;color:#6b7280">${fmtPid(enc.hadm_id, enc.display_id)}</span>
        </td>
        <td style="${TD}">${fmtDate(enc.created_at)}</td>
        <td style="${TD}">${fmtDate(signedAt)}</td>
        <td style="${TD}">${_ddbadge("t3","Signed Off")}</td>
        <td style="${TD}"><button class="dd-open-signed-btn" data-hadm-id="${enc.hadm_id}" style="${_BTNBASE};background:#f0fdf4;color:#059669;border-color:#bbf7d0">View Summary →</button></td>
      </tr>`;
  }).join("");

  const emptyCompletedRow = `
    <tr><td colspan="5" style="${TD};padding:64px 24px;text-align:center">
      <div style="font-size:32px;margin-bottom:10px">📋</div>
      <div style="font-size:15px;font-weight:700;color:#374151;margin-bottom:4px">No completed cases yet</div>
      <div style="font-size:13px;color:#6b7280">Signed summaries will appear here.</div>
    </td></tr>`;

  return `
    <div class="app-shell">
      <div class="main">
        ${renderTopbar({ user, crumbs:["Clinician","Signing Queue"] })}
        <div class="content">

          <!-- Screen header -->
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
            <h1 style="font-size:17px;font-weight:800;color:#111827;flex:1;margin:0">${isCompleted ? 'Completed' : 'Signing Queue'}</h1>
            <div style="display:flex;gap:8px;align-items:center">
              <span style="font-size:12px;color:#6b7280">Dr. ${doctorName}</span>
              <button id="dd-refresh" style="${_BTNBASE};background:#fff;color:#6b7280;border-color:#e5e7eb">${iconSVG("refresh",12)} Refresh</button>
            </div>
          </div>

          <!-- Tab bar -->
          <div style="display:flex;gap:2px;border-bottom:2px solid #e5e7eb;margin-bottom:18px">
            <button id="dd-tab-queue" style="padding:8px 16px;border:none;background:none;font-size:12.5px;font-weight:${!isCompleted?'700':'500'};color:${!isCompleted?'#800080':'#6b7280'};border-bottom:${!isCompleted?'2px solid #800080':'2px solid transparent'};cursor:pointer;margin-bottom:-2px">
              Queue <span style="font-size:10px;font-weight:700;padding:1px 6px;border-radius:10px;background:${!isCompleted?'#800080':'#e5e7eb'};color:${!isCompleted?'#fff':'#6b7280'};margin-left:4px">${activeEncs.length}</span>
            </button>
            <button id="dd-tab-completed" style="padding:8px 16px;border:none;background:none;font-size:12.5px;font-weight:${isCompleted?'700':'500'};color:${isCompleted?'#059669':'#6b7280'};border-bottom:${isCompleted?'2px solid #059669':'2px solid transparent'};cursor:pointer;margin-bottom:-2px">
              Completed <span style="font-size:10px;font-weight:700;padding:1px 6px;border-radius:10px;background:${isCompleted?'#059669':'#e5e7eb'};color:${isCompleted?'#fff':'#6b7280'};margin-left:4px">${completedEncs.length}</span>
            </button>
          </div>

          <!-- Stats row -->
          <div style="display:flex;gap:10px;margin-bottom:10px">
            <div style="flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px">
              <div style="font-size:28px;font-weight:800;line-height:1;color:#059669">${readyToSign}</div>
              <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">Ready to Sign</div>
            </div>
            <div style="flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px">
              <div style="font-size:28px;font-weight:800;line-height:1;color:#dc2626">${sentForRevision}</div>
              <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">Sent for Revision</div>
            </div>
            <div style="flex:1;background:#fff;border:1px solid #fde68a;border-radius:8px;padding:12px 16px">
              <div style="font-size:28px;font-weight:800;line-height:1;color:#d97706">${sentForAmendment}</div>
              <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">Sent for Amendment</div>
            </div>
            <div style="flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px">
              <div style="font-size:28px;font-weight:800;line-height:1;color:#800080">${draftCount}</div>
              <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">Draft</div>
            </div>
          </div>

          <!-- Status Filter (queue tab only) -->
          ${!isCompleted ? (() => {
            const _SF_FILTERS = [
              { key: 'all',                label: 'All' },
              { key: 'ready_to_sign',      label: 'Ready to Sign' },
              { key: 'draft',              label: 'Draft' },
              { key: 'regenerated',        label: 'Regenerated' },
              { key: 'revision_requested', label: 'Sent for Revision' },
              { key: 'amendment_requested',label: 'Sent for Amendment' },
            ];
            return `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px">
              ${_SF_FILTERS.map(f => {
                const isActive = _dd.statusFilter === f.key;
                return `<button class="dd-sf-btn" data-sf="${f.key}" style="padding:4px 12px;border-radius:99px;font-size:11.5px;font-weight:${isActive?'700':'500'};border:1.5px solid ${isActive?'#800080':'#e5e7eb'};background:${isActive?'#800080':'#fff'};color:${isActive?'#fff':'#374151'};cursor:pointer;font-family:inherit">${f.label}</button>`;
              }).join('')}
            </div>`;
          })() : ''}

          <!-- Table — switches between Queue and Completed -->
          <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
            <table style="width:100%;border-collapse:collapse">
              <thead>
                <tr>
                  ${(isCompleted
                    ? ["Patient","Admitted","Signed On","Status","Action"]
                    : ["Patient","Date","T1 Minor","T2 Medication","T3 Critical","DL Flags","Status","Action"]
                  ).map(h =>
                    `<th style="padding:9px 14px;text-align:left;font-size:10.5px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;background:#f9fafb;border-bottom:1px solid #e5e7eb;white-space:nowrap">${h}</th>`
                  ).join("")}
                </tr>
              </thead>
              <tbody>
                ${isCompleted ? (completedRows || emptyCompletedRow) : (rows || emptyRow)}
              </tbody>
            </table>
          </div>

        </div>
      </div>
    </div>`;
};

SCREEN_SETUP["doctor-dashboard"] = function setupDoctorDashboard() {
  if (_dd.encounters === null) ddLoad();

  // Custom tooltip for tier badges (replaces ugly native browser title tooltip)
  const _ddTipEl = (() => {
    let el = document.getElementById("dd-float-tip");
    if (!el) {
      el = document.createElement("div");
      el.id = "dd-float-tip";
      el.style.cssText = [
        "position:fixed","display:none","max-width:300px",
        "background:#1e1b2e","color:#e2e8f0","font-size:11.5px",
        "line-height:1.55","padding:10px 14px","border-radius:10px",
        "border:1px solid rgba(255,255,255,0.12)",
        "box-shadow:0 6px 24px rgba(0,0,0,0.4)",
        "z-index:9999","pointer-events:none","white-space:normal",
      ].join(";");
      document.body.appendChild(el);
    }
    return el;
  })();

  document.querySelectorAll(".dd-tier-badge").forEach(el => {
    el.addEventListener("mouseenter", () => {
      const raw = (el.dataset.tip || "").trim();
      if (!raw) return;
      const lines = raw.split("&#10;").filter(Boolean);
      _ddTipEl.innerHTML = lines.map(line => {
        const colon = line.indexOf(": ");
        if (colon > 0) {
          const sec = line.slice(0, colon);
          const reason = line.slice(colon + 2);
          return `<div style="margin-bottom:4px"><span style="color:#c4b5fd;font-weight:700">${sec}</span><br><span style="color:#cbd5e1">${reason}</span></div>`;
        }
        return `<div style="margin-bottom:4px;color:#cbd5e1">${line}</div>`;
      }).join("");
      _ddTipEl.style.display = "block";
      const rect = el.getBoundingClientRect();
      const tipW = 300;
      const left = Math.min(rect.left, window.innerWidth - tipW - 12);
      _ddTipEl.style.left = Math.max(8, left) + "px";
      _ddTipEl.style.top  = (rect.bottom + 6) + "px";
    });
    el.addEventListener("mouseleave", () => { _ddTipEl.style.display = "none"; });
  });

  document.getElementById("dd-refresh")?.addEventListener("click", () => {
    _dd.encounters = null;
    _dd.attempt    = 0;
    ddLoad();
  });

  document.getElementById("dd-tab-queue")?.addEventListener("click", () => {
    _dd.tab = 'queue'; renderApp();
  });
  document.getElementById("dd-tab-completed")?.addEventListener("click", () => {
    _dd.tab = 'completed'; _dd.statusFilter = 'all'; renderApp();
  });

  document.querySelectorAll(".dd-sf-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      _dd.statusFilter = btn.dataset.sf;
      renderApp();
    });
  });

  document.querySelectorAll(".dd-open-signed-btn, .dd-completed-row").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation();
      const row    = el.closest(".dd-completed-row") || el.parentElement?.closest(".dd-completed-row") || el.parentElement;
      const hadmId = parseInt((el.dataset.hadmId ?? row?.dataset.hadmId) || "0", 10);
      const enc    = (_dd.encounters || []).find(e => e.hadm_id === hadmId);
      if (!enc) return;
      APP.reviewData = {
        encounter:     enc,
        hadmId:        enc.hadm_id,
        patient:       enc.patient_name ? { full_name: enc.patient_name, age: enc.anchor_age, gender: enc.gender } : (enc.patient || null),
        admission:     enc.admission,
        summaryId:     enc.summary?.id,
        content:       enc.summary?.content,
        dischargeType: enc.discharge_type || "Standard",
        docSections:   enc.summary?.content ? rv2ParseSummary(enc.summary.content) : [],
        sectionsJson:  enc.summary?.sections_json || null,
      };
      navigate("signed");
    });
  });

  document.querySelectorAll(".dd-review-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const hadmId = parseInt(btn.dataset.hadmId, 10);
      const enc = (_dd.encounters || []).find(e => e.hadm_id === hadmId);
      if (!enc?.summary?.content) return;

      APP.reviewData = {
        encounter:      enc,
        hadmId:         enc.hadm_id,
        patient:        enc.patient_name ? { full_name: enc.patient_name, age: enc.anchor_age, gender: enc.gender } : (enc.patient || null),
        admission:      enc.admission,
        summaryId:      enc.summary.id,
        content:        enc.summary.content,
        dischargeType:  enc.discharge_type || "Standard",
        docSections:    rv2ParseSummary(enc.summary.content),
        sectionsJson:   enc.summary.sections_json || null,
        summaryVersion: enc.summary.summary_version || 1,
      };

      const savedResolved = enc.summary?.draft_edits?.resolved || [];
      Object.assign(_rv2, {
        auditMode:false, selectedId:null, editingId:null, editText:"",
        edits:{}, comments:{}, commentingId:null, commentText:"",
        sourceId:null, sourceTechOpen:false, revisionId:null,
        revisionText:"", resolved:new Set(savedResolved), bannerDone:false,
        clinicalCtx:null, ctxLoading:false, ctxError:null, ctxHadmId:null,
        activeSectionId:null, fullscreen:null,
        historyOpen:false, historyVersions:null, historyLoading:false, historyError:null,
        viewingVersionId:null, viewingVersion:null,
        compareMode:false, compareSelA:null, compareSelB:null,
        comparePending:false, compareDataA:null, compareDataB:null,
      });

      // Amendment case — show amendment banner, suppress stale rejection banner
      if ((enc.amendment_count || 0) > 0) {
        APP.rejFlow = null;
        try { localStorage.removeItem('rejFlow_active'); } catch(_) {}
        fetch(`${API_BASE}/api/amendments/${enc.id}`)
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (data?.amendment) {
              APP.amdFlow = {
                hadmId:   enc.hadm_id,
                reason:   data.amendment.reason   || '',
                section:  data.amendment.section  || '',
                details:  data.amendment.details  || '',
                requestedBy: data.amendment.submitted_by_name || 'Billing team',
              };
            }
          }).catch(() => {});
      } else {
        // For regenerated summaries, ensure APP.rejFlow is populated for the amber banner.
        APP.amdFlow = null;
        if ((enc.rejection_count || 0) > 0) {
          fetch(`${API_BASE}/api/encounters/${enc.hadm_id}/rejection_log`)
            .then(r => r.ok ? r.json() : null)
            .then(data => {
              const entry = data?.rejections?.[0];
              if (entry) {
                APP.rejFlow = {
                  hadmId: enc.hadm_id, patName: null,
                  rejectionReason: entry.rejection_reason,
                  rejectedAt: entry.rejected_at,
                  rejectionLogId: entry.id,
                };
                try { localStorage.setItem('rejFlow_active', JSON.stringify(APP.rejFlow)); } catch(_) {}
              }
            }).catch(() => {});
        }
      }

      navigate("review");
    });
  });

  // DL Flags — toggle inline detail panel (no navigation)
  document.querySelectorAll(".dd-dl-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const hadmId = parseInt(btn.dataset.hadmId, 10);
      _dd.dlPanelHadmId = _dd.dlPanelHadmId === hadmId ? null : hadmId;
      renderScreen();
    });
  });

  // Row hover + click-through
  // Find the hadm_id of the first actionable Awaiting Review row for the highlight.
  const firstHlHadmId = (_dd.encounters || [])
    .filter(e => ["Awaiting Review","revision_requested","Revision Requested"].includes(e.status))
    .sort((a, b) => {
      const P = { "Awaiting Review":0, "Revision Requested":1, "revision_requested":1 };
      const d = ((P[a.status]??9) - (P[b.status]??9));
      return d !== 0 ? d : new Date(a.created_at||0) - new Date(b.created_at||0);
    })
    .find(e => e.status === "Awaiting Review" && e.summary?.content)?.hadm_id ?? -1;

  document.querySelectorAll(".dd-row").forEach(row => {
    const isHl = parseInt(row.dataset.hadmId, 10) === firstHlHadmId;
    row.addEventListener("mouseenter", () => { row.style.background = isHl ? "#ede4f4" : "#fcfcfc"; });
    row.addEventListener("mouseleave", () => { row.style.background = isHl ? "#f7edf7" : ""; });
    row.addEventListener("click",      () => { row.querySelector(".dd-review-btn")?.click(); });
  });
};

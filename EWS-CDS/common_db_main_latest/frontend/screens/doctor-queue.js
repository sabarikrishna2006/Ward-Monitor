// Screen — Doctor: My Review Queue

let _dq = { encounters: null, loading: false, error: null, attempt: 0, errorStats: null, regenToasts: [], slaToasts: [], _pollTimer: null, _rejCounts: {} };

// Open the review screen for an encounter — shared by regen toasts, SLA-alert
// toasts, and the "Review" button on each queue card.
function _dqOpenReviewForEnc(enc) {
  if (!enc?.summary?.content) return false;
  APP.reviewData = {
    encounter:     enc,
    hadmId:        enc.hadm_id,
    patient:       enc.patient,
    admission:     enc.admission,
    summaryId:     enc.summary.id,
    content:       enc.summary.content,
    dischargeType: enc.discharge_type || "Standard",
    docSections:   rv2ParseSummary(enc.summary.content),
    sectionsJson:  enc.summary.sections_json || null,
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
  // For regenerated summaries, populate APP.rejFlow from rejection_log so the
  // amber banner shows in review-v2.js regardless of localStorage state.
  if ((enc.rejection_count || 0) > 0) {
    fetch(`${API_BASE}/api/encounters/${enc.hadm_id}/rejection_log`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const entry = data?.rejections?.[0];
        if (entry) {
          APP.rejFlow = { hadmId: enc.hadm_id, patName: null,
            rejectionReason: entry.rejection_reason, rejectedAt: entry.rejected_at,
            rejectionLogId: entry.id };
          try { localStorage.setItem('rejFlow_active', JSON.stringify(APP.rejFlow)); } catch(_) {}
          if (!entry.re_reviewed_at) {
            fetch(`${API_BASE}/api/rejection_logs/${entry.id}`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ re_reviewed_at: new Date().toISOString() }),
            }).catch(() => {});
          }
        }
      }).catch(() => {});
  }
  navigate("review");
  return true;
}

// Poll the audit log for SLA-breach alerts a ward admin sent for cases in this
// doctor's queue, and surface them as a toast (dedup'd via localStorage).
async function _dqCheckSlaAlerts() {
  try {
    const rows = await fetch(`${API_BASE}/api/audit_log?limit=30`).then(r => r.ok ? r.json() : []);
    if (!Array.isArray(rows)) return;
    let seen = {};
    try { seen = JSON.parse(localStorage.getItem("dq_sla_seen") || "{}"); } catch(_) {}
    const myHadmIds = new Set((_dq.encounters || []).map(e => e.hadm_id));
    for (const r of rows) {
      if (r.action !== "SLA_ALERT_SENT") continue;
      if (!myHadmIds.has(r.hadm_id)) continue;
      if (seen[r.id]) continue;
      if (_dq.slaToasts.find(t => t.id === r.id)) continue;
      _dq.slaToasts.push({ id: r.id, hadm_id: r.hadm_id });
    }
  } catch(_) {}
}

function _dqDismissSlaToast(idx) {
  const t = _dq.slaToasts[idx];
  if (!t) return;
  let seen = {};
  try { seen = JSON.parse(localStorage.getItem("dq_sla_seen") || "{}"); } catch(_) {}
  seen[t.id] = true;
  try { localStorage.setItem("dq_sla_seen", JSON.stringify(seen)); } catch(_) {}
  _dq.slaToasts.splice(idx, 1);
  renderApp();
}

function _dqBuildRegenToasts(encs) {
  const regenEncs = encs.filter(e => (e.rejection_count || 0) > 0 && e.status === "Awaiting Review");
  let notified = {};
  try { notified = JSON.parse(localStorage.getItem("dq_regen_notified") || "{}"); } catch(_) {}
  // Clear dismissal flag when rejection_count increased (new rejection cycle happened)
  for (const e of regenEncs) {
    const prev = _dq._rejCounts[e.hadm_id] || 0;
    if ((e.rejection_count || 0) > prev && notified[e.hadm_id]) {
      delete notified[e.hadm_id];
      try { localStorage.setItem("dq_regen_notified", JSON.stringify(notified)); } catch(_) {}
    }
  }
  // Update stored rejection counts
  for (const e of encs) _dq._rejCounts[e.hadm_id] = e.rejection_count || 0;
  _dq.regenToasts = regenEncs.filter(e => !notified[e.hadm_id]).map(e => ({ hadm_id: e.hadm_id, enc: e }));
}

function _dqDismissToast(idx) {
  const t = _dq.regenToasts[idx];
  if (!t) return;
  let notified = {};
  try { notified = JSON.parse(localStorage.getItem("dq_regen_notified") || "{}"); } catch(_) {}
  notified[t.hadm_id] = true;
  try { localStorage.setItem("dq_regen_notified", JSON.stringify(notified)); } catch(_) {}
  _dq.regenToasts.splice(idx, 1);
  renderApp();
}

async function _fetchWithTimeout(fn, ms) {
  return Promise.race([
    fn(),
    new Promise((_, rej) => setTimeout(() => rej(new Error("Request timed out")), ms)),
  ]);
}

async function dqLoad() {
  if (_dq.loading) return;
  _dq.loading = true;
  _dq.error   = null;
  _dq.attempt = (_dq.attempt || 0) + 1;
  renderApp();
  try {
    const raw  = await _fetchWithTimeout(() => fetchEncounters({ status: "Awaiting Review" }), 45000);
    // Normalise — API may return plain array or { encounters: [...] }
    const encs = Array.isArray(raw) ? raw : (raw.encounters || []);
    // Fetch summary for each encounter in parallel
    const withSummaries = await Promise.all(encs.map(async e => {
      const sum = await fetchSummary(e.id).catch(() => null);
      return { ...e, admission: null, patient: e.patient_name ? { full_name: e.patient_name, age: e.anchor_age, gender: e.gender } : null, summary: sum || null };
    }));
    _dq.encounters = withSummaries;
    _dqBuildRegenToasts(withSummaries);
    await _dqCheckSlaAlerts();
    // Fetch error stats for gate widget (non-blocking)
    apiGetErrorStats().then(s => { _dq.errorStats = s; renderApp(); }).catch(() => {});
  } catch (err) {
    if (_dq.attempt < 3) {
      // Auto-retry up to 3 times
      _dq.loading = false;
      setTimeout(dqLoad, _dq.attempt * 4000);
      return;
    }
    _dq.error = err.message;
    _dq.encounters = [];
  }
  _dq.loading = false;
  renderApp();
  // Live poll every 8s while on queue/dashboard screen
  function _dqLivePoll() {
    clearTimeout(_dq._pollTimer);
    _dq._pollTimer = setTimeout(async () => {
      if (APP.screen !== "doctor-queue" && APP.screen !== "doctor-dashboard") {
        _dqLivePoll(); return; // keep scheduling even off-screen so it catches up on navigate
      }
      try {
        const raw  = await _fetchWithTimeout(() => fetchEncounters({ status: "Awaiting Review" }), 15000);
        const encs = Array.isArray(raw) ? raw : (raw.encounters || []);
        const prev = (_dq.encounters || []).map(e => e.hadm_id + ':' + e.status).sort().join(',');
        const next = encs.map(e => e.hadm_id + ':' + e.status).sort().join(',');
        if (prev !== next) {
          const withSummaries = await Promise.all(encs.map(async e => {
            const sum = await fetchSummary(e.id).catch(() => null);
            return { ...e, admission: null, patient: e.patient_name ? { full_name: e.patient_name } : null, summary: sum || null };
          }));
          _dq.encounters = withSummaries;
          _dqBuildRegenToasts(withSummaries);
          withSummaries.forEach(e => {
            if (e.status === 'Awaiting Review') localStorage.removeItem('wa_regen_' + e.hadm_id);
          });
        }
        const prevSlaCount = _dq.slaToasts.length;
        await _dqCheckSlaAlerts();
        if (prev !== next || _dq.slaToasts.length !== prevSlaCount) renderApp();
      } catch(_) {}
      _dqLivePoll();
    }, 8000);
  }
  _dqLivePoll();
}

window.dqInvalidate = () => {
  clearTimeout(_dq._pollTimer);
  _dq.encounters = null;
  _dq.attempt = 0;
};

SCREEN_RENDERERS["doctor-queue"] = function renderDoctorQueue() {
  const user = getUser();

  if (_dq.encounters === null || _dq.loading) {
    if (!_dq.loading && !_dq.error) dqLoad();
    const skeletonCard = `
      <div style="background:white;border:1px solid var(--border);border-top:3px solid var(--border);border-radius:12px;padding:18px 20px;box-shadow:var(--shadow-sm)">
        <div class="skeleton" style="height:11px;width:55px;border-radius:3px;margin-bottom:10px"></div>
        <div class="skeleton" style="height:26px;width:160px;border-radius:5px;margin-bottom:14px"></div>
        <div class="skeleton" style="height:18px;width:110px;border-radius:4px;margin-bottom:18px"></div>
        <div class="skeleton" style="height:40px;border-radius:8px"></div>
      </div>`;
    return `
      <div class="app-shell">
        ${renderSidebar("doctor","my-queue")}
        <div class="main">
          ${renderTopbar({ user, hideBrand:true, crumbs:["Clinician","My Queue"] })}
          <div class="content">
            <div style="height:24px;width:200px" class="skeleton" style="border-radius:4px;margin-bottom:22px"></div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px">
              ${Array(4).fill(skeletonCard).join("")}
            </div>
          </div>
        </div>
      </div>`;
  }

  if (_dq.error) {
    return `
      <div class="app-shell">
        ${renderSidebar("doctor","my-queue")}
        <div class="main">
          ${renderTopbar({ user, hideBrand:true, crumbs:["Clinician","My Queue"] })}
          <div class="content" style="display:flex;align-items:center;justify-content:center;min-height:50vh">
            <div style="text-align:center;padding:48px 32px;background:white;border-radius:16px;border:1px solid var(--red-border);max-width:380px;box-shadow:var(--shadow-sm)">
              <div style="width:48px;height:48px;border-radius:12px;background:var(--red-soft);display:grid;place-items:center;margin:0 auto 16px">${iconSVG("alert",22)}</div>
              <div style="font-size:15px;font-weight:700;color:var(--ink-2);margin-bottom:8px">Failed to load queue</div>
              <div style="font-size:13px;color:var(--ink-4);margin-bottom:20px;line-height:1.6">${_dq.error}</div>
              <button class="btn btn-outline" id="dq-refresh">Try again</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  const encs       = _dq.encounters;
  const today      = new Date().toLocaleDateString("en-IN", { weekday:"long", day:"numeric", month:"long", year:"numeric" });
  const _rawDoctorName = user?.full_name || "Doctor";
  const doctorName = /^Dr\.?\s/i.test(_rawDoctorName) ? _rawDoctorName.replace(/^Dr\.?\s*/i, "") : _rawDoctorName;
  const hour       = new Date().getHours();
  const greeting   = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const statusInfo = (enc) => {
    const s = enc.status || "";
    const isRegen = ((enc.rejection_count || 0) > 0) || !!enc.revision_reason;
    const waRegen = !!localStorage.getItem('wa_regen_' + enc.hadm_id);
    if (s === "Signed Off")       return { label:"Signed",              cls:"pill-green",  dot:"#059669", animated:false };
    if (s === "Awaiting Review")  return isRegen
                                    ? { label:"Regenerated",            cls:"pill-amber",  dot:"#F59E0B", animated:true  }
                                    : { label:"Ready for Review",       cls:"pill-teal",   dot:"#800080", animated:true  };
    if (s === "Processing")       return waRegen
                                    ? { label:"Regenerating",           cls:"pill-blue",   dot:"#6366F1", animated:true  }
                                    : { label:"AI Processing",          cls:"pill-blue",   dot:"#A020A0", animated:true  };
    if (s === "Revision Requested")  return { label:"Revision Requested",  cls:"pill-amber",  dot:"#D97706", animated:false };
    return                                  { label:"Upload Pending",       cls:"pill-slate",  dot:"#7A3A7A", animated:false };
  };

  const timeAgo = (dateStr) => {
    if (!dateStr) return "";
    const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 60000);
    if (diff < 1)   return "just now";
    if (diff < 60)  return `${diff}m ago`;
    if (diff < 1440) return `${Math.floor(diff/60)}h ago`;
    return new Date(dateStr).toLocaleDateString("en-IN", {day:"numeric",month:"short"});
  };

  const cards = encs.map((enc, idx) => {
    const si          = statusInfo(enc);
    const hasSummary  = !!enc.summary?.content;
    const draftAt     = enc.summary?.draft_saved_at;
    const genTime     = enc.summary?.created_at || enc.created_at;
    const isRegen     = (((enc.rejection_count || 0) > 0) || !!enc.revision_reason) && enc.status === "Awaiting Review";
    const dotHTML     = si.animated
      ? `<span class="pulse-dot" style="color:${si.dot}"></span>`
      : `<span class="ldot" style="background:${si.dot}"></span>`;
    const accentColor = isRegen ? "#F59E0B" : draftAt ? "#800080" : si.dot;
    const cardBorder  = isRegen ? "rgba(245,158,11,.35)" : draftAt ? "rgba(128,0,128,.25)" : si.dot + "35";
    return `
      <div style="background:white;border:1.5px solid ${cardBorder};border-top:3px solid ${accentColor};border-radius:14px;padding:18px 20px;box-shadow:var(--shadow-sm);transition:box-shadow .2s,transform .2s;cursor:${hasSummary?"pointer":"default"};position:relative;overflow:hidden"
           class="dq-card" data-enc-idx="${idx}">
        <!-- ambient corner glow -->
        <div style="position:absolute;right:-20px;top:-20px;width:80px;height:80px;border-radius:50%;background:radial-gradient(circle,${accentColor}12,transparent 70%);pointer-events:none"></div>
        <!-- Header row -->
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px;position:relative">
          <div>
            <div style="font-size:10px;font-weight:800;color:var(--ink-5);letter-spacing:.14em;text-transform:uppercase;margin-bottom:4px">Patient</div>
            <div style="font-weight:800;font-size:18px;color:var(--ink);letter-spacing:-.02em;line-height:1">${fmtPid(enc.hadm_id, enc.display_id)}</div>
            <div style="font-size:13px;color:#6B7280;margin-top:4px">
              ${enc.patient?.full_name || ''} ${enc.patient?.age ? '· ' + enc.patient.age + 'y' : ''}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px">
            <span class="pill ${si.cls}" style="font-size:10.5px">${dotHTML}${si.label}</span>
            ${isRegen ? `<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;color:#92400E;background:#FFF7ED;border:1px solid #F59E0B;border-radius:6px;padding:2px 8px">↺ Regenerated Summary</span>` : ""}
          </div>
        </div>
        <!-- Meta row -->
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;min-height:22px;flex-wrap:wrap">
          ${draftAt
            ? `<span style="display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--brand-dark);background:var(--brand-soft);border:1px solid var(--brand-mid);border-radius:8px;padding:4px 10px">${iconSVG("doc",11)} Draft · ${timeAgo(draftAt)}</span>`
            : hasSummary
              ? `<span style="font-size:12px;color:var(--ink-4);display:flex;align-items:center;gap:5px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:3px 9px">${iconSVG("doc",11)} Generated · ${timeAgo(genTime)}</span>`
              : `<span style="font-size:12px;color:var(--ink-5);background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:3px 9px">Awaiting generation</span>`
          }
        </div>
        <!-- CTA -->
        <button class="btn ${hasSummary?"btn-primary":"btn-outline"} dq-review-btn" data-enc-idx="${idx}"
                style="width:100%;padding:10px;font-size:13px;font-weight:600;justify-content:center;border-radius:9px;${isRegen?"background:#F59E0B;border-color:#F59E0B;":""}" ${hasSummary?"":"disabled"}>
          ${hasSummary ? `${draftAt ? "Continue Draft" : isRegen ? "Review Regenerated Summary" : "Review Summary"} ${iconSVG("chevR",13)}` : "Awaiting Generation"}
        </button>
      </div>`;
  }).join("");

  return `
    <div class="app-shell">
      ${renderSidebar("doctor","my-queue")}
      <div class="main">
        ${renderTopbar({ user, hideBrand:true, crumbs:["Clinician","Good Morning"] })}
        <div class="content">

          <!-- Morning header banner -->
          <div style="background:linear-gradient(135deg,#0A000A 0%,#200020 50%,#0E000E 100%);border-radius:16px;padding:28px 32px;margin-bottom:24px;position:relative;overflow:hidden;box-shadow:0 8px 32px rgba(128,0,128,.25)">
            <!-- orb glow -->
            <div style="position:absolute;right:-60px;top:-60px;width:280px;height:280px;border-radius:50%;background:radial-gradient(circle,rgba(192,64,192,.22) 0%,transparent 70%);pointer-events:none"></div>
            <div style="position:absolute;left:-40px;bottom:-40px;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle,rgba(128,0,128,.14) 0%,transparent 70%);pointer-events:none"></div>
            <div style="position:relative;z-index:1;display:flex;align-items:flex-end;flex-wrap:wrap;gap:12px">
              <div style="flex:1;min-width:0">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:.18em;color:#603060;font-weight:800;margin-bottom:8px">${today}</div>
                <div style="font-size:22px;font-weight:800;color:#F0D8F0;letter-spacing:-.02em;line-height:1.2;margin-bottom:8px">${greeting}, Dr. ${doctorName}.</div>
                <div style="font-size:13px;color:#7A5A7A">
                  ${encs.length === 0
                    ? "Your queue is clear — no summaries awaiting review."
                    : `You have <strong style="color:#D090D0">${encs.length} ${encs.length===1?"summary":"summaries"}</strong> awaiting review.`}
                </div>
              </div>
              <button class="btn" id="dq-refresh" style="display:flex;align-items:center;gap:6px;flex-shrink:0;background:rgba(128,0,128,.18);border:1px solid rgba(192,64,192,.3);color:#D090D0;font-size:12.5px">${iconSVG("refresh",13)} Refresh</button>
            </div>
            <!-- status pills row -->
            <div style="display:flex;gap:8px;margin-top:18px;flex-wrap:wrap;position:relative;z-index:1">
              ${[
                { label:"Ready for Review", count: encs.filter(e=>e.status==="Awaiting Review").length, bg:"rgba(128,0,128,.22)", color:"#D090D0", border:"rgba(192,64,192,.35)" },
                { label:"Signed Off",       count: encs.filter(e=>e.status==="Signed Off").length,      bg:"rgba(5,150,105,.15)", color:"#34D399", border:"rgba(5,150,105,.3)"  },
              ].map(s=>`<span style="display:inline-flex;align-items:center;gap:6px;background:${s.bg};border:1px solid ${s.border};color:${s.color};padding:4px 12px;border-radius:99px;font-size:11.5px;font-weight:700;letter-spacing:.04em">${s.label}: <strong>${s.count}</strong></span>`).join("")}
            </div>
          </div>

          <!-- 3-Tier Accuracy Gate Widget -->
          ${(() => {
            const es = _dq.errorStats;
            if (!es) return "";
            const rate    = parseFloat(es.tier3_rate_pct) || 0;
            const total   = es.total_errors || 0;
            const t3      = es.tier3_count || 0;
            const isPause = rate > 25;
            const isWarn  = rate > 15 && !isPause;
            const gateColor  = isPause ? "#dc2626" : isWarn ? "#d97706" : "#059669";
            const gateBg     = isPause ? "#fef2f2" : isWarn ? "#fffbeb" : "#f0fdf4";
            const gateBorder = isPause ? "#fca5a5" : isWarn ? "#fde68a" : "#bbf7d0";
            const gateLabel  = isPause ? "⛔ PILOT PAUSE THRESHOLD EXCEEDED"
                             : isWarn  ? "⚠ Approaching Pause Threshold"
                             : "✓ Within Launch Gate";
            const byTier = es.by_tier || [];
            const t1c = (byTier.find(x => x.tier === 1) || {}).count || 0;
            const t2c = (byTier.find(x => x.tier === 2) || {}).count || 0;
            return `
            <div style="background:${gateBg};border:1px solid ${gateBorder};border-radius:8px;padding:10px 16px;margin-bottom:18px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
              <div style="display:flex;gap:12px;flex-shrink:0">
                <div style="text-align:center"><div style="font-size:10px;color:#6b7280">T1 Minor</div><div style="font-size:17px;font-weight:800;color:${gateColor}">${t1c}</div></div>
                <div style="text-align:center"><div style="font-size:10px;color:#6b7280">T2 Medication</div><div style="font-size:17px;font-weight:800;color:${gateColor}">${t2c}</div></div>
                <div style="text-align:center"><div style="font-size:10px;color:#6b7280">T3 Critical</div><div style="font-size:17px;font-weight:800;color:${gateColor}">${t3}</div></div>
              </div>
            </div>`;
          })()}

          <!-- Patient cards grid -->
          ${encs.length === 0
            ? `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 24px;background:white;border-radius:16px;border:1px solid var(--border);box-shadow:var(--shadow-sm)">
                 <div style="width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,var(--green-soft),#DCFCE7);display:grid;place-items:center;margin-bottom:20px;box-shadow:0 4px 16px rgba(5,150,105,.15)">${iconSVG("check",28)}</div>
                 <div style="font-size:18px;font-weight:800;color:var(--ink);margin-bottom:8px;letter-spacing:-.01em">You're all caught up</div>
                 <div style="font-size:13.5px;color:var(--ink-4);max-width:280px;text-align:center;line-height:1.65">No summaries awaiting your review right now. Check back when new summaries are generated.</div>
               </div>`
            : `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(272px,1fr));gap:18px">
                 ${cards}
               </div>`}

        </div>
      </div>

      ${_dq.slaToasts.length > 0 ? `
        <div style="position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;gap:8px;width:min(92vw,480px)">
          ${_dq.slaToasts.map((t, i) => `
            <div class="dq-sla-toast" data-toast-idx="${i}"
                 style="background:#FEF2F2;border:1.5px solid #FCA5A5;border-left:4px solid #DC2626;border-radius:10px;padding:12px 16px;box-shadow:0 8px 28px rgba(220,38,38,.28);cursor:pointer;display:flex;align-items:center;gap:10px;animation:fadeUp .25s ease">
              <span style="font-size:18px;flex-shrink:0;line-height:1">⚠</span>
              <div style="flex:1;min-width:0">
                <div style="font-size:13px;font-weight:700;color:#991B1B">SLA Breach Noticed</div>
                <div style="font-size:12px;color:#7F1D1D;margin-top:2px">${fmtPid(t.hadm_id)} &middot; Ward Admin flagged this case &mdash; tap to review</div>
              </div>
              <button class="dq-sla-toast-dismiss" data-toast-idx="${i}"
                      style="background:none;border:none;cursor:pointer;padding:0 2px;color:#DC2626;font-size:15px;line-height:1;flex-shrink:0">✕</button>
            </div>
          `).join("")}
        </div>` : ""}

      ${_dq.regenToasts.length > 0 ? `
        <div style="position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:10px;max-width:320px">
          ${_dq.regenToasts.map((t, i) => `
            <div class="dq-regen-toast" data-toast-idx="${i}"
                 style="background:#FFFBEB;border:1.5px solid #F59E0B;border-left:4px solid #D97706;border-radius:10px;padding:14px 16px;box-shadow:0 4px 20px rgba(245,158,11,.3);cursor:pointer;display:flex;align-items:flex-start;gap:10px;animation:slideInRight .25s ease">
              <span style="font-size:20px;flex-shrink:0;line-height:1">↺</span>
              <div style="flex:1;min-width:0">
                <div style="font-size:13px;font-weight:700;color:#92400E">Regenerated Summary Ready</div>
                <div style="font-size:12px;color:#78350F;margin-top:3px">${fmtPid(t.hadm_id, t.display_id)} &middot; Tap to open for review</div>
              </div>
              <button class="dq-regen-toast-dismiss" data-toast-idx="${i}"
                      style="background:none;border:none;cursor:pointer;padding:0 2px;color:#D97706;font-size:15px;line-height:1;flex-shrink:0">✕</button>
            </div>
          `).join("")}
        </div>` : ""}

    </div>`;
};

SCREEN_SETUP["doctor-queue"] = function setupDoctorQueue() {
  if (_dq.encounters === null) dqLoad();

  document.getElementById("dq-refresh")?.addEventListener("click", () => {
    _dq.encounters = null;
    _dq.attempt = 0;
    dqLoad();
  });

  // Card hover effect
  document.querySelectorAll(".dq-card").forEach(card => {
    card.addEventListener("mouseenter", () => { card.style.boxShadow = "var(--shadow-md)"; card.style.transform = "translateY(-2px)"; });
    card.addEventListener("mouseleave", () => { card.style.boxShadow = "var(--shadow-sm)"; card.style.transform = ""; });
  });

  // SLA-breach alert toasts (sent by ward admin from the Kanban pipeline)
  document.querySelectorAll(".dq-sla-toast-dismiss").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      _dqDismissSlaToast(parseInt(btn.dataset.toastIdx, 10));
    });
  });
  document.querySelectorAll(".dq-sla-toast").forEach(toast => {
    toast.addEventListener("click", e => {
      if (e.target.classList.contains("dq-sla-toast-dismiss")) return;
      const idx = parseInt(toast.dataset.toastIdx, 10);
      const t = _dq.slaToasts[idx];
      const enc = (_dq.encounters || []).find(x => x.hadm_id === t?.hadm_id);
      _dqDismissSlaToast(idx);
      _dqOpenReviewForEnc(enc);
    });
  });

  // Regen notification toasts
  document.querySelectorAll(".dq-regen-toast-dismiss").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      _dqDismissToast(parseInt(btn.dataset.toastIdx, 10));
    });
  });
  document.querySelectorAll(".dq-regen-toast").forEach(toast => {
    toast.addEventListener("click", e => {
      if (e.target.classList.contains("dq-regen-toast-dismiss")) return;
      const idx = parseInt(toast.dataset.toastIdx, 10);
      const t = _dq.regenToasts[idx];
      _dqDismissToast(idx);
      _dqOpenReviewForEnc(t?.enc);
    });
  });

  document.querySelectorAll(".dq-review-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.encIdx, 10);
      const enc = _dq.encounters[idx];
      _dqOpenReviewForEnc(enc);
    });
  });

};

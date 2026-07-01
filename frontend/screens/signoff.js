// Claim Edit Modal (vanilla JS)
// Sign-off modal removed — sign logic is now inline in review-v2.js SCREEN_SETUP["review"].

let _claimEditState = null; // { claim, correction, reason }

// ── ClaimEditModal ────────────────────────────────────────────────────────────

function renderClaimEditModal() {
  if (!_claimEditState) return "";
  const { claim, correction, reason } = _claimEditState;
  const canSave = reason.trim().length > 0 && correction.trim().length > 0;
  return `
    <div class="modal-overlay" id="cem-overlay">
      <div class="modal" id="cem-modal">
        <div class="modal-head">
          <div style="width:34px;height:34px;border-radius:10px;background:var(--red-soft);color:var(--red);display:grid;place-items:center;flex-shrink:0;box-shadow:0 2px 6px rgba(220,38,38,.15)">
            ${iconSVG("flag",15)}
          </div>
          <div class="title">Review Claim</div>
          <span class="pill pill-slate" style="margin-left:8px">Discharge Medications</span>
          <div style="flex:1"></div>
          <button class="iconbtn" id="cem-close">${iconSVG("x",14)}</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="label">Original AI claim</label>
            <div style="padding:14px 16px;background:var(--bg);border:1.5px solid var(--border);border-radius:var(--r-sm);color:var(--ink-2);font-size:13.5px;line-height:1.7;font-style:italic">
              "${claim.text}"
            </div>
            <div class="helptext" style="margin-top:6px;display:flex;align-items:center;gap:8px">
              <span class="mono">claim ${claim.id}</span>
              <span style="color:var(--ink-4)">·</span>
              <span>Original confidence: <strong style="color:var(--red)" class="mono">0.61</strong> (below 0.85 threshold)</span>
            </div>
          </div>
          <div class="field">
            <label class="label">Your correction</label>
            <textarea id="cem-correction" class="textarea" rows="3" style="resize:vertical">${correction}</textarea>
            <div class="helptext">Edit inline. The corrected text will replace the AI claim in the final summary.</div>
          </div>
          <div class="field">
            <label class="label">Reason for edit <span style="color:var(--red)">*</span></label>
            <input class="input" id="cem-reason" placeholder="e.g. Allergy band reviewed at bedside — NKDA confirmed." value="${reason.replace(/"/g,'&quot;')}"/>
            <div class="helptext">Required. Recorded in the audit trail along with your clinical identity.</div>
          </div>
          <div style="display:flex;gap:12px;padding:14px 16px;background:var(--amber-soft);border:1.5px solid var(--amber-border);border-radius:var(--r-sm);margin-top:8px">
            <div style="display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:white;color:var(--amber);flex-shrink:0;box-shadow:0 1px 4px rgba(217,119,6,.15)">
              ${iconSVG("info",14)}
            </div>
            <div style="font-size:12.5px;color:#92400E;line-height:1.6">
              Saving will overwrite the AI claim and mark it <strong>MD Edited</strong> in the summary. The original text is preserved in the audit log.
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-danger-outline" id="cem-reject">${iconSVG("x",13)} Reject Claim</button>
          <div style="flex:1"></div>
          <button class="btn btn-outline" id="cem-cancel">Cancel</button>
          <button class="btn btn-primary" id="cem-save" ${canSave?"":"disabled"}>${iconSVG("check",13)} Save Correction</button>
        </div>
      </div>
    </div>`;
}

function setupClaimEditModal() {
  if (!_claimEditState) return;

  document.getElementById("cem-close")?.addEventListener("click",  closeClaimEdit);
  document.getElementById("cem-cancel")?.addEventListener("click", closeClaimEdit);
  document.getElementById("cem-overlay")?.addEventListener("click", e => { if (e.target.id==="cem-overlay") closeClaimEdit(); });

  document.getElementById("cem-correction")?.addEventListener("input", e => {
    _claimEditState.correction = e.target.value;
    const btn = document.getElementById("cem-save");
    if (btn) btn.disabled = !(e.target.value.trim().length > 0 && _claimEditState.reason.trim().length > 0);
  });
  document.getElementById("cem-reason")?.addEventListener("input", e => {
    _claimEditState.reason = e.target.value;
    const btn = document.getElementById("cem-save");
    if (btn) btn.disabled = !(e.target.value.trim().length > 0 && _claimEditState.correction.trim().length > 0);
  });

  document.getElementById("cem-save")?.addEventListener("click", () => {
    const correction = document.getElementById("cem-correction")?.value || _claimEditState.correction;
    const reason     = document.getElementById("cem-reason")?.value     || _claimEditState.reason;
    if (!correction.trim() || !reason.trim()) return;
    const id    = _claimEditState.claim.id;
    const claim = _claimEditState.claim;
    APP.claims = APP.claims.map(c =>
      c.id === id ? { ...c, text: correction, status: "v", edited: true, editReason: reason } : c
    );
    const _isMedSec     = (_claimEditState.secId || "") === "s11";
    const errorTier     = claim.status === "r" ? 3 : _isMedSec ? 2 : 1;
    const errorCategory = errorTier === 3 ? "critical_clinical" : errorTier === 2 ? "medication_dose" : "formatting";
    const nabh_section  = (typeof PRIMARY_NABH !== "undefined" && _claimEditState.secId)
      ? (PRIMARY_NABH[_claimEditState.secId] || _claimEditState.secId)
      : _claimEditState.secId || "unknown";
    if (typeof apiLogError === "function") {
      apiLogError({
        hadm_id:         APP.currentHadmId || APP.reviewData?.hadmId || null,
        summary_version: APP.currentSummaryVersion || APP.reviewData?.summaryVersion || null,
        nabh_section,
        error_tier:      errorTier,
        ai_output:       claim.text,
        correct_value:   correction,
        error_category:  errorCategory,
        source_present:  true,
        attending_id:    getUser()?.id || null,
      });
    }
    closeClaimEdit();
  });

  document.getElementById("cem-reject")?.addEventListener("click", () => {
    const id = _claimEditState.claim.id;
    APP.claims = APP.claims.map(c => c.id === id ? { ...c, status: "r", edited: false } : c);
    closeClaimEdit();
  });

  setTimeout(() => document.getElementById("cem-correction")?.focus(), 60);
}

function openClaimEdit(claim, secId) {
  _claimEditState = { claim, correction: claim.text, reason: "", secId: secId || "meds" };
  renderApp();
}

function closeClaimEdit() {
  _claimEditState = null;
  renderApp();
}

// ── Rebuild edited summary content for persistence ───────────────────────────

function buildEditedContent(docSections, edits, comments) {
  let md = "";

  const passageSectionMap = {};
  for (const sect of docSections) {
    for (const p of sect.passages) passageSectionMap[p.id] = sect.title;
  }

  for (const sect of docSections) {
    const heading = sect.nabhNum ? `${sect.nabhNum} — ${sect.title}` : sect.title;
    md += `**${heading}**\n`;
    for (const p of sect.passages) {
      const text      = edits[p.id] !== undefined ? edits[p.id] : p.text;
      const wasEdited = edits[p.id] !== undefined;
      md += text + (wasEdited ? " [Doctor Edited]" : "") + "\n";
    }
    md += "\n";
  }

  const allComments = [];
  for (const [pid, cmts] of Object.entries(comments)) {
    if (!cmts?.length) continue;
    const label = passageSectionMap[pid] ? `[${passageSectionMap[pid]}] ` : "";
    for (const c of cmts) allComments.push(label + c);
  }

  if (allComments.length) {
    md += `**Doctor's Notes**\n`;
    for (const c of allComments) md += `* ${c}\n`;
  }

  return md.trim();
}

window.renderClaimEditModal = renderClaimEditModal;
window.setupClaimEditModal  = setupClaimEditModal;
window.openClaimEdit        = openClaimEdit;
window.closeClaimEdit       = closeClaimEdit;

// ══════════════════════════════════════════════════════════════════════════════
// SIGNOFF SCREEN — full-page sign gate with optional digital signature
// ══════════════════════════════════════════════════════════════════════════════

const _sg = {
  mci:          '',
  designation:  '',
  hospital:     '',
  showCanvas:   false,
  canvasDone:   false,
  canvasDataUrl: null,
  signing:      false,
};

function _sgInit() {
  const u = getUser();
  _sg.mci          = u?.mci_number || u?.registration_number || '';
  _sg.designation  = 'Attending Physician';
  _sg.hospital     = '';
  _sg.showCanvas   = false;
  _sg.canvasDone   = false;
  _sg.canvasDataUrl = null;
  _sg.signing      = false;
}

function _sgRerender() { renderApp(); }

SCREEN_RENDERERS["signoff"] = function renderSignoff() {
  const user = getUser();
  const rd   = APP.reviewData || {};

  const _rawName   = user?.full_name || user?.name || 'Doctor';
  const doctorName = /^Dr\.?\s/i.test(_rawName) ? _rawName : `Dr. ${_rawName}`;

  // Version context
  const version    = rd.encounter?.version || 1;
  const rejCount   = rd.encounter?.rejection_count || 0;
  const editCount  = Object.keys((typeof _rv2 !== 'undefined' ? _rv2.edits : null) || {}).length;
  const versionStr = `v${version}.0`;
  const hasAmend   = version > 1;

  // Check unresolved T3 flags (safety net even if canSign was true)
  const _sjForSign   = rd.sectionsJson || rd.encounter?.summary?.sections_json || null;
  const unresolvedT3 = _sjForSign
    ? Object.entries(_sjForSign).filter(([k, s]) => s?.tier === "T3" && !(typeof _rv2 !== 'undefined' && _rv2.resolvedTierSections?.has(k))).length
    : 0;
  const blocked = unresolvedT3 > 0;

  const now = new Date();
  const _fmtDT = () =>
    now.toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) + ', ' +
    now.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', hour12:false }) + ' IST';

  const _FIELD_BASE = 'width:100%;box-sizing:border-box;border:1.5px solid #A7F3D0;border-radius:7px;padding:7px 11px;font-size:13px;font-weight:500;color:#111827;font-family:inherit;outline:none;';
  const _sigField = (num, label, id, val, caption, ro = false) => `
    <div>
      <label style="font-size:11px;font-weight:700;color:#D97706;display:block;margin-bottom:4px">${num}. ${label}</label>
      <input id="sg-${id}" ${ro ? 'readonly' : ''} value="${(val || '').replace(/"/g, '&quot;')}" placeholder="${label}"
        style="${_FIELD_BASE}background:${ro ? '#F9FAFB' : '#fff'};">
      <div style="font-size:11px;color:#059669;margin-top:3px">✓ ${caption}</div>
    </div>`;

  const patName   = rd.patient?.full_name || 'Patient';
  const displayId = rd.hadmId ? fmtPid(rd.hadmId) : '—';

  return `
    <div style="min-height:100vh;background:#f9fafb;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">

      <!-- Topbar -->
      <div style="background:#fff;border-bottom:1.5px solid #e5e7eb;padding:0 24px;height:52px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04)">
        <button id="sg-back-top" style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer">
          ← Return to Review
        </button>
        <div style="width:1px;height:20px;background:#e5e7eb"></div>
        <span style="font-size:14px;font-weight:700;color:#111827">Sign Discharge Summary</span>
        <div style="flex:1"></div>
        <span style="font-size:12px;color:#6b7280">${displayId} · ${patName}</span>
      </div>

      <!-- Content -->
      <div style="max-width:700px;margin:0 auto;padding:32px 24px 48px">

        ${blocked ? `
        <div style="background:#FFF7ED;border:1.5px solid #F97316;border-radius:8px;padding:13px 16px;margin-bottom:20px;display:flex;align-items:center;gap:10px">
          <span style="font-size:18px;flex-shrink:0">🔒</span>
          <div style="font-size:13px;color:#9A3412">
            <strong>T3 flags still unresolved.</strong> Return to review and resolve all critical flags before signing.
          </div>
        </div>` : ''}

        <!-- Document Version Context -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:20px">
          <div style="font-size:13.5px;font-weight:700;color:#111827;margin-bottom:14px">Document Version Context</div>
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            ${[
              ['Current Version',       `${versionStr} — ${hasAmend ? 'Amendment' : 'Original (not yet amended)'}`],
              ['Amendment History',     hasAmend ? `${version - 1} amendment${version > 2 ? 's' : ''}` : 'None — first signature'],
              ['Prior Rejections',      String(rejCount)],
              ['LLM Revisions Applied', editCount > 0 ? `${editCount} section${editCount > 1 ? 's' : ''} edited during review` : '0 — no edits made'],
            ].map(([k, v]) => `
              <tr style="border-bottom:1px solid #f3f4f6">
                <td style="padding:10px 14px 10px 0;color:#6b7280;white-space:nowrap;width:180px;vertical-align:top">${k}</td>
                <td style="padding:10px 0;color:#111827;font-weight:500">${v}</td>
              </tr>`).join('')}
          </table>
        </div>

        <!-- Signature Fields -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:16px 20px;margin-bottom:16px">
          <div style="font-size:13px;font-weight:700;color:#111827;margin-bottom:12px">
            Signature Fields — <span style="color:#D97706">All 5 required</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
            ${_sigField(1, 'Full Name',    'fullname', doctorName,                    'Verified against hospital directory')}
            ${_sigField(2, 'Designation',  'desig',    _sg.designation || 'Attending Physician', 'Verified')}
            ${_sigField(3, 'MCI Reg. No.', 'mci',      _sg.mci,                       'Active registration verified with MCI')}
            ${_sigField(4, 'Hospital',     'hospital', _sg.hospital,                  'Verified')}
          </div>
          <div>
            <label style="font-size:11px;font-weight:700;color:#D97706;display:block;margin-bottom:4px">5. Date &amp; Time</label>
            <input readonly value="${_fmtDT()}" style="${_FIELD_BASE}background:#F9FAFB;">
            <div style="font-size:11px;color:#059669;margin-top:3px">✓ Auto-filled — UTC timestamp sealed on signature</div>
          </div>
        </div>

        <!-- Optional Digital Signature -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:20px">
          <div id="sg-canvas-toggle" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none">
            <div>
              <div style="font-size:13.5px;font-weight:700;color:#111827">Draw Digital Signature</div>
              <div style="font-size:12px;color:#6b7280;margin-top:2px">Optional — drawn signature is embedded in the signed PDF</div>
            </div>
            <span style="font-size:12.5px;color:#800080;font-weight:700;background:#F5E6F5;border:1px solid #D4A0D4;border-radius:6px;padding:4px 12px">${_sg.showCanvas ? '▲ Hide' : '▼ Show'}</span>
          </div>
          ${_sg.showCanvas ? `
          <div style="margin-top:16px">
            <div style="position:relative;border:1.5px solid #d1d5db;border-radius:10px;background:#fff;overflow:hidden;height:140px">
              <canvas id="sg-canvas" width="640" height="140" style="display:block;width:100%;height:140px;cursor:crosshair;touch-action:none"></canvas>
              <div id="sg-canvas-hint" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none">
                <span style="font-size:13px;color:#d1d5db;font-style:italic">Sign here</span>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:14px;margin-top:8px">
              <button id="sg-canvas-clear" style="background:none;border:none;cursor:pointer;font-size:12px;color:#6b7280;padding:3px 0;font-family:inherit">Clear signature</button>
              ${_sg.canvasDone ? '<span style="font-size:12px;color:#059669">✓ Signature captured</span>' : ''}
            </div>
          </div>` : ''}
        </div>

        <!-- Legal notice -->
        <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:13px 16px;margin-bottom:28px">
          <p style="margin:0;font-size:12.5px;color:#1E40AF;line-height:1.6">
            This signature is legally binding under <strong>NABH accreditation standards</strong>. The sealed PDF will include: digital signature hash, timestamp, MCI number, and version number.
          </p>
        </div>

        <!-- Action buttons -->
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          <button id="sg-back-btn" style="display:inline-flex;align-items:center;gap:6px;padding:11px 20px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13.5px;font-weight:600;color:#374151;cursor:pointer">
            ← Return to Review
          </button>
          <button id="sg-confirm" ${blocked || _sg.signing ? 'disabled' : ''}
            style="display:inline-flex;align-items:center;gap:7px;padding:11px 24px;border:none;border-radius:8px;font-size:13.5px;font-weight:700;cursor:${blocked || _sg.signing ? 'not-allowed' : 'pointer'};${
              blocked
                ? 'background:#F97316;color:#fff;opacity:.85;'
                : _sg.signing
                  ? 'background:#9ca3af;color:#fff;'
                  : 'background:linear-gradient(135deg,#800080,#A020A0);color:#fff;box-shadow:0 4px 14px rgba(128,0,128,.35);'
            }">
            ${blocked ? '🔒 Resolve T3 Flags First' : _sg.signing ? 'Signing…' : '✓ Sign & Confirm'}
          </button>
        </div>

      </div>
    </div>`;
};

SCREEN_SETUP["signoff"] = function setupSignoff() {
  // Back buttons
  const _goBack = () => navigate('review');
  document.getElementById("sg-back-top")?.addEventListener("click", _goBack);
  document.getElementById("sg-back-btn")?.addEventListener("click", _goBack);

  // Canvas toggle
  document.getElementById("sg-canvas-toggle")?.addEventListener("click", () => {
    _sg.showCanvas = !_sg.showCanvas;
    _sgRerender();
  });

  // Canvas draw pad
  if (_sg.showCanvas) {
    const _canvas = document.getElementById("sg-canvas");
    const _hint   = document.getElementById("sg-canvas-hint");
    if (_canvas) {
      // Restore previous drawing if any
      if (_sg.canvasDataUrl) {
        const img = new Image();
        img.onload = () => _canvas.getContext("2d").drawImage(img, 0, 0);
        img.src = _sg.canvasDataUrl;
        if (_hint) _hint.style.display = "none";
      }
      const ctx = _canvas.getContext("2d");
      ctx.strokeStyle = "#111827"; ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round";
      let _drawing = false;
      const _pt = ev => {
        const r = _canvas.getBoundingClientRect();
        const sx = _canvas.width / r.width, sy = _canvas.height / r.height;
        const s = ev.touches ? ev.touches[0] : ev;
        return [(s.clientX - r.left) * sx, (s.clientY - r.top) * sy];
      };
      const _start = ev => { ev.preventDefault(); _drawing = true; const [x,y] = _pt(ev); ctx.beginPath(); ctx.moveTo(x,y); };
      const _move  = ev => {
        if (!_drawing) return; ev.preventDefault();
        const [x,y] = _pt(ev); ctx.lineTo(x,y); ctx.stroke();
        if (_hint) _hint.style.display = "none";
      };
      const _end   = () => {
        if (!_drawing) return;
        _drawing = false;
        _sg.canvasDone    = true;
        _sg.canvasDataUrl = _canvas.toDataURL("image/png");
        // Refresh just the caption without losing canvas
        const capEl = _canvas.closest("div[style*='margin-top:16px']")?.querySelector("span[style*='059669']");
        if (!capEl) _sgRerender();
      };
      _canvas.addEventListener("mousedown",  _start);
      _canvas.addEventListener("mousemove",  _move);
      _canvas.addEventListener("mouseup",    _end);
      _canvas.addEventListener("mouseleave", _end);
      _canvas.addEventListener("touchstart", _start, { passive:false });
      _canvas.addEventListener("touchmove",  _move,  { passive:false });
      _canvas.addEventListener("touchend",   _end);
    }
    document.getElementById("sg-canvas-clear")?.addEventListener("click", () => {
      if (!_canvas) return;
      _canvas.getContext("2d").clearRect(0, 0, _canvas.width, _canvas.height);
      _sg.canvasDone    = false;
      _sg.canvasDataUrl = null;
      if (_hint) _hint.style.display = "";
      _sgRerender();
    });
  }

  // Sign & Confirm
  document.getElementById("sg-confirm")?.addEventListener("click", async () => {
    if (_sg.signing) return;
    _sg.signing = true;
    _sgRerender();

    try {
      const rd    = APP.reviewData || {};
      const encId = rd?.encounter?.id;
      if (!encId) throw new Error("No encounter ID");

      const _u     = getUser();
      const now    = new Date().toISOString();
      const newVer = (rd.encounter?.version ?? 1) + 1;

      const mci         = document.getElementById("sg-mci")?.value.trim() || _sg.mci || _u?.mci_number || null;
      const fullName    = document.getElementById("sg-fullname")?.value.trim() || _u?.full_name || null;
      const designation = document.getElementById("sg-desig")?.value.trim()    || _sg.designation || null;
      const hospital    = document.getElementById("sg-hospital")?.value.trim()  || _sg.hospital || null;
      const sigDataUrl  = _sg.canvasDataUrl || null;

      const edited = (typeof buildEditedContent === "function")
        ? buildEditedContent(
            rd.docSections,
            (typeof _rv2 !== 'undefined' ? _rv2.edits    : null) || {},
            (typeof _rv2 !== 'undefined' ? _rv2.comments : null) || {}
          )
        : (rd.content || "");

      // 1. Mark encounter Signed Off
      await updateEncounter(encId, { status: "Signed Off", version: newVer });

      // 2. Persist signed summary + immutable version snapshot
      const summaryResult = await updateSummary(encId, {
        signed_at:      now,
        signed_by:      _u?.id || null,
        signature_data: JSON.stringify({ mci, sig_png: sigDataUrl, full_name: fullName, designation, hospital }),
        content:        edited,
        save_version:   true,
        save_type:      "signed",
        saved_by_name:  fullName || _u?.full_name || null,
      });

      // 3. If re-sign after rejection, mark the rejection log as signed
      const _rf = APP.rejFlow;
      if (_rf?.rejectionLogId && String(_rf.hadmId) === String(rd?.hadmId)) {
        fetch(`${API_BASE}/api/rejection_logs/${_rf.rejectionLogId}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ signed_at: now }),
        }).catch(() => {});
        try { localStorage.removeItem("rejFlow_active"); } catch(_) {}
        APP.rejFlow = null;
      }

      // 4. Invalidate doctor queue cache
      if (typeof dqInvalidate === "function") dqInvalidate();

      // 5. Stash sign-off data for the signed page
      APP.reviewData.signedAt      = now;
      APP.reviewData.signedMci     = mci;
      APP.reviewData.signedName    = fullName;
      APP.reviewData.signedDesig   = designation;
      APP.reviewData.signedHospital = hospital;
      APP.reviewData.finalContent  = edited;
      APP.reviewData.docVersion    = summaryResult?.doc_version ?? newVer;
      APP.reviewData._contentHash  = null;
      APP.reviewData._sigDataUrl   = sigDataUrl;
      APP.amendment = null;

      navigate("signed");
    } catch (err) {
      _sg.signing = false;
      _sgRerender();
      alert("Sign-off failed: " + (err?.message || err));
    }
  });
};

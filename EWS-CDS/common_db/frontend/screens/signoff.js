// Claim Edit Modal + Sign-Off Modal (vanilla JS)

let _claimEditState = null; // { claim, correction, reason }
let _signOffState   = null; // { mode, name, confirming }

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
    // update save button state without full re-render
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
    // Log attending edit to error_log table (retraining dataset).
    // nabh_section is derived from the actual section the claim belongs to,
    // not hardcoded — so future prompts learn from the right section's failures.
    // T3=Critical (rejected claim = wrong fact), T2=Medication (amended s11), T1=Minor (other amendments)
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

  // Focus textarea
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

  // Build a map of passageId → sectionTitle for comment labelling
  const passageSectionMap = {};
  for (const sect of docSections) {
    for (const p of sect.passages) passageSectionMap[p.id] = sect.title;
  }

  for (const sect of docSections) {
    // Keep the "S6 — " NABH prefix so re-parsing maps back to the right section id
    // (otherwise S6 labs / S14 condition lose their table formatting on reload).
    const heading = sect.nabhNum ? `${sect.nabhNum} — ${sect.title}` : sect.title;
    md += `**${heading}**\n`;
    for (const p of sect.passages) {
      const text      = edits[p.id] !== undefined ? edits[p.id] : p.text;
      const wasEdited = edits[p.id] !== undefined;
      md += text + (wasEdited ? " [Doctor Edited]" : "") + "\n";
    }
    md += "\n";
  }

  // Collect ALL comments directly from _rv2.comments — don't rely on passage loop
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

// ── SignOffModal ──────────────────────────────────────────────────────────────

function renderSignOffModal() {
  if (!_signOffState) return "";
  const { mode, name, confirming, patientAckConfirmed } = _signOffState;
  const CHECK_ITEMS = [
    "All flagged sections have been reviewed",
    "Medications and allergies verified",
    "Discharge instructions confirmed",
  ];
  const sigBox = mode === "type"
    ? `<div class="sigbox typed">${name}</div><input class="input" id="sof-name" value="${name.replace(/"/g,'&quot;')}" style="margin-top:10px"/>`
    : `<div style="display:flex;flex-direction:column;gap:8px">
        <canvas id="sof-canvas" width="480" height="120"
          style="border:1px solid var(--border);border-radius:6px;background:white;cursor:crosshair;touch-action:none;width:100%;display:block"></canvas>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-size:11px;color:var(--ink-4)">Draw your signature above</span>
          <button type="button" id="sof-clear" class="btn btn-ghost btn-sm" style="font-size:11px;padding:3px 10px">Clear</button>
        </div>
      </div>`;
  const rd  = APP.reviewData;
  const pat = rd?.patient;
  const adm = rd?.admission;
  const fmtDate = d => d ? new Date(d).toLocaleDateString("en-IN",{day:"numeric",month:"short",year:"numeric"}) : "—";
  const patCols = [
    ["Patient",    pat?.full_name || _ddSynthName(rd?.hadmId) || "Not recorded"],
    ["Patient ID",  fmtPid(rd?.hadmId, rd?.encounter?.display_id) || "—"],
    ["Admitted",   fmtDate(adm?.admittime)],
    ["Discharged", fmtDate(adm?.dischtime)],
  ];

  return `
    <div class="modal-overlay" id="sof-overlay">
      <div class="modal wide" id="sof-modal">
        <div class="modal-head">
          <div style="width:30px;height:30px;background:var(--green-soft);color:var(--green);display:grid;place-items:center">
            ${iconSVG("shield",15)}
          </div>
          <div class="title">Approve Discharge Summary</div>
          <div style="flex:1"></div>
          <button class="iconbtn" id="sof-close">${iconSVG("x",14)}</button>
        </div>
        <div class="modal-body">
          ${(() => {
            const amd = APP.amendment;
            if (!amd || amd.version !== "v1.1") return "";
            const _amdReasonLabel = {
              factual:"Factual correction", diagnosis:"Diagnosis update",
              medication:"Medication dose change", procedure:"Procedure clarification", other:"Other"
            };
            return `<div style="border:1.5px solid #f59e0b;border-radius:8px;background:#fffbeb;padding:14px 16px;margin-bottom:18px">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
                <div style="padding:2px 8px;background:#d97706;color:#fff;font-size:10px;font-weight:800;border-radius:4px;font-family:var(--mono)">S5</div>
                <div style="font-size:13px;font-weight:700;color:#92400e">Signing Amendment ${amd.version}</div>
              </div>
              <div style="display:grid;gap:5px;font-size:12px;color:#78350f;margin-bottom:10px">
                <div><b>Section:</b> ${amd.section || '—'}</div>
                <div><b>Reason:</b> ${_amdReasonLabel[amd.reason] || amd.reason || '—'}</div>
                <div><b>Change:</b> <em>"${(amd.details||'').slice(0,200)}${(amd.details||'').length>200?'…':''}"</em></div>
              </div>
              <div style="display:flex;align-items:center;gap:6px;font-size:11.5px;color:#166534;font-weight:600">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                Original v1.0 preserved in audit trail (NABH compliant)
              </div>
            </div>`;
          })()}
          <div style="display:flex;background:#FAFBFD;border:1px solid var(--border-soft);margin-bottom:22px">
            ${patCols.map((c,i) => `
              <div style="flex:1;padding:12px 14px;border-right:${i<3?"1px solid var(--border-soft)":"none"}">
                <div class="eyebrow" style="font-size:10px">${c[0]}</div>
                <div style="font-size:12.5px;margin-top:3px;font-weight:500">${c[1]}</div>
              </div>`).join("")}
          </div>
          <!-- NABH MN4 Hard Gate — Patient Acknowledgement -->
          <div style="background:${patientAckConfirmed?"#F0FDF4":"#FEF2F2"};border:2px solid ${patientAckConfirmed?"#86EFAC":"#FCA5A5"};border-radius:8px;padding:14px 16px;margin-bottom:18px">
            <label style="display:flex;align-items:flex-start;gap:12px;cursor:pointer">
              <input type="checkbox" id="sof-patient-ack" ${patientAckConfirmed?"checked":""} style="width:16px;height:16px;margin-top:2px;accent-color:#1A56DB;flex-shrink:0"/>
              <div>
                <div style="font-weight:700;font-size:12.5px;color:${patientAckConfirmed?"#166534":"#DC2626"}">
                  NABH MN4 — Patient / Attendant Acknowledgement
                  ${!patientAckConfirmed ? `<span style="background:#FEE2E2;color:#DC2626;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700;margin-left:6px">Required</span>` : `<span style="background:#DCFCE7;color:#166534;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700;margin-left:6px">Confirmed</span>`}
                </div>
                <div style="font-size:12px;color:#374151;margin-top:4px;line-height:1.5">
                  I confirm that the patient or their attendant has been informed of and has acknowledged this discharge summary. Their signature and timestamp have been recorded in the physical patient file.
                </div>
                ${!patientAckConfirmed ? `<div style="font-size:11px;color:#DC2626;margin-top:4px;font-weight:500">⚠ E-sign is disabled until this is confirmed.</div>` : ""}
              </div>
            </label>
          </div>

          <div class="eyebrow" style="margin-bottom:10px">Before you sign</div>
          <div style="margin-bottom:24px">
            ${CHECK_ITEMS.map(item => `
              <div class="chkitem">
                <div class="ck">${iconSVG("check",12)}</div>${item}
              </div>`).join("")}
          </div>
          <div class="eyebrow" style="margin-bottom:10px">Signature</div>
          <div class="hstack" style="margin-bottom:10px">
            <div class="seg">
              <button id="sof-type" ${mode==="type"?'class="on"':""}>Type</button>
              <button id="sof-draw" ${mode==="draw"?'class="on"':""}>Draw</button>
            </div>
            <div class="muted" style="font-size:12px">Tied to your clinical identity</div>
          </div>
          ${sigBox}
          <div style="display:flex;gap:12px;padding:14px;background:#F1F8F8;border:1px solid #C8E0E2;margin-top:20px">
            <div style="width:28px;height:28px;background:var(--teal-soft);color:var(--teal-deep);display:grid;place-items:center;flex-shrink:0">${iconSVG("info",14)}</div>
            <div style="font-size:12.5px;color:var(--ink-2);line-height:1.6">
              <strong style="color:var(--ink)">What happens next:</strong> this summary will be locked, timestamped, and added to the patient record. A formatted PDF will be auto-generated and dispatched to the discharge desk.
            </div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-outline" id="sof-cancel">Cancel</button>
          <button class="btn btn-navy" id="sof-confirm" ${confirming||!patientAckConfirmed?"disabled":""} title="${!patientAckConfirmed?"Confirm patient acknowledgement (NABH MN4) before signing":""}">
            ${confirming ? `<span class="spinner"></span> Signing…` : `${iconSVG("check",14)} Confirm &amp; Sign`}
          </button>
        </div>
      </div>
    </div>`;
}

function setupSignOffModal() {
  if (!_signOffState) return;
  document.getElementById("sof-close")?.addEventListener("click",  closeSignOff);
  document.getElementById("sof-cancel")?.addEventListener("click", closeSignOff);
  document.getElementById("sof-overlay")?.addEventListener("click", e => { if (e.target.id==="sof-overlay") closeSignOff(); });
  document.getElementById("sof-type")?.addEventListener("click", () => { _signOffState.mode = "type"; renderApp(); });
  document.getElementById("sof-draw")?.addEventListener("click", () => { _signOffState.mode = "draw"; renderApp(); });
  document.getElementById("sof-name")?.addEventListener("input",  e => { _signOffState.name = e.target.value; });

  // NABH MN4 — patient acknowledgement gate
  document.getElementById("sof-patient-ack")?.addEventListener("change", e => {
    _signOffState.patientAckConfirmed = e.target.checked;
    const btn = document.getElementById("sof-confirm");
    if (btn) btn.disabled = !e.target.checked || _signOffState.confirming;
    renderApp();
  });

  // Canvas signature pad
  const canvas = document.getElementById("sof-canvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    ctx.strokeStyle = "#1e3a5f";
    ctx.lineWidth   = 2;
    ctx.lineCap     = "round";
    ctx.lineJoin    = "round";
    let drawing = false;

    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      const sx = canvas.width  / r.width;
      const sy = canvas.height / r.height;
      const src = e.touches ? e.touches[0] : e;
      return [(src.clientX - r.left) * sx, (src.clientY - r.top) * sy];
    };

    canvas.addEventListener("pointerdown", e => {
      drawing = true;
      ctx.beginPath();
      ctx.moveTo(...pos(e));
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", e => {
      if (!drawing) return;
      ctx.lineTo(...pos(e));
      ctx.stroke();
    });
    canvas.addEventListener("pointerup",   () => { drawing = false; _signOffState.signatureDataUrl = canvas.toDataURL(); });
    canvas.addEventListener("pointerleave",() => { drawing = false; });

    document.getElementById("sof-clear")?.addEventListener("click", () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      _signOffState.signatureDataUrl = null;
    });
  }
  document.getElementById("sof-confirm")?.addEventListener("click", async () => {
    // Capture canvas now — renderApp() will destroy the DOM element
    if (_signOffState.mode === "draw") {
      const cv = document.getElementById("sof-canvas");
      if (cv) _signOffState.signatureDataUrl = cv.toDataURL();
    }
    _signOffState.confirming = true;
    renderApp();
    try {
      const rd  = APP.reviewData;
      const now = new Date().toISOString();
      if (rd?.encounter?.id) {
        const newVer = (rd.encounter.version ?? 1) + 1;
        await updateEncounter(rd.encounter.id, { status: "Signed Off", version: newVer });
      }
      if (rd?.summaryId) {
        const upd = { signed_at: now };
        if (APP.currentUser?.id) upd.signed_by = APP.currentUser.id;
        upd.signature_mode = _signOffState.mode || "type";
        if (_signOffState.mode === "draw" && _signOffState.signatureDataUrl) {
          upd.signature_data = _signOffState.signatureDataUrl;
        }
        if (rd.docSections) {
          const edited = buildEditedContent(
            rd.docSections,
            (typeof _rv2 !== "undefined" && _rv2.edits)    || {},
            (typeof _rv2 !== "undefined" && _rv2.comments) || {}
          );
          if (edited) {
            upd.content = edited;
            if (APP.reviewData) APP.reviewData.finalContent = edited;
          }
        }
        const _sofUser = getUser();
        await updateSummary(rd.encounter.id, {
          ...upd,
          save_version:  true,
          save_type:     "signed",
          saved_by_name: _sofUser?.full_name || _sofUser?.name || null,
        });
      }
      if (APP.reviewData) {
        APP.reviewData.signedAt       = now;
        APP.reviewData.signatureMode  = _signOffState.mode || "type";
        APP.reviewData.signatureData  = _signOffState.signatureDataUrl || null;
      }
      // Step 7: write signed_at to rejection_log if this was a re-sign after rejection
      const _rf = APP.rejFlow;
      if (_rf?.rejectionLogId && String(_rf.hadmId) === String(rd?.hadmId)) {
        fetch(`${API_BASE}/api/rejection_logs/${_rf.rejectionLogId}`, {
          method: "PATCH", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ signed_at: now }),
        }).catch(() => {});
        // Clear rejFlow state — this loop is complete
        try { localStorage.removeItem('rejFlow_active'); } catch(e) {}
        APP.rejFlow = null;
      }
    } catch (e) {
      console.error("Sign-off save failed:", e);
      _signOffState.confirming = false;
      renderApp();
      return;
    }
    if (typeof dqInvalidate === "function") dqInvalidate();
    _signOffState = null;
    // Show usability rating modal before navigating away
    _openUsabilityRating(APP.reviewData?.encounter?.id, APP.reviewData?.hadmId);
  });
}

function openSignOff() {
  const user = getUser();
  const name = user?.full_name ? `Dr. ${user.full_name}` : (user?.name || "Doctor");
  _signOffState = { mode: "type", name, confirming: false, patientAckConfirmed: false };
  renderApp();
}

function closeSignOff() {
  _signOffState = null;
  renderApp();
}

window.renderClaimEditModal  = renderClaimEditModal;
window.setupClaimEditModal   = setupClaimEditModal;
window.openClaimEdit         = openClaimEdit;
window.closeClaimEdit        = closeClaimEdit;
window.renderSignOffModal    = renderSignOffModal;
window.setupSignOffModal     = setupSignOffModal;
window.openSignOff           = openSignOff;
window.closeSignOff          = closeSignOff;

// ── Usability Rating Modal ────────────────────────────────────────────────────
// Shown immediately after sign-off. 5-point scale, optional text, skip allowed.

let _urEncounterId = null;
let _urHadmId = null;
let _urSelected = 0;

function _openUsabilityRating(encounterId, hadmId) {
  _urEncounterId = encounterId || null;
  _urHadmId      = hadmId || null;
  _urSelected    = 0;

  const LABELS = ["", "Very Difficult", "Difficult", "Neutral", "Easy", "Very Easy"];

  const overlay = document.createElement("div");
  overlay.id = "ur-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px";

  function _renderModal() {
    overlay.innerHTML = `
      <div style="background:#fff;border-radius:16px;padding:28px 32px;max-width:420px;width:100%;box-shadow:0 24px 48px rgba(0,0,0,.18)">
        <div style="font-size:17px;font-weight:700;color:#1e293b;margin-bottom:4px">How easy was this summary to review?</div>
        <div style="font-size:13px;color:#64748b;margin-bottom:20px">Physician Usability Scale · 1 = Very Difficult → 5 = Very Easy (target ≥4.0)</div>
        <div style="display:flex;gap:10px;justify-content:center;margin-bottom:12px">
          ${[1,2,3,4,5].map(n => `
            <button class="ur-star" data-val="${n}" style="
              width:52px;height:52px;border-radius:12px;border:2px solid ${_urSelected===n?'#7c3aed':'#e2e8f0'};
              background:${_urSelected===n?'#f5f3ff':'#f8fafc'};font-size:22px;cursor:pointer;
              display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;
              color:${_urSelected===n?'#7c3aed':'#94a3b8'};font-weight:700;transition:all .12s">
              ${n}
            </button>
          `).join("")}
        </div>
        <div style="text-align:center;font-size:13px;font-weight:600;color:#7c3aed;min-height:18px;margin-bottom:14px">
          ${_urSelected ? LABELS[_urSelected] : ""}
        </div>
        <textarea id="ur-feedback" placeholder="Optional — what made it harder or easier?" style="width:100%;border:1px solid #e2e8f0;border-radius:8px;padding:9px 12px;font-size:13px;font-family:inherit;color:#1e293b;resize:vertical;min-height:60px;box-sizing:border-box;outline:none"></textarea>
        <div style="display:flex;gap:10px;margin-top:16px">
          <button id="ur-skip" style="flex:1;padding:10px;border:1.5px solid #e2e8f0;border-radius:8px;background:#f8fafc;font-size:13px;color:#64748b;cursor:pointer;font-family:inherit">Skip</button>
          <button id="ur-submit" style="flex:2;padding:10px;border:none;border-radius:8px;background:${_urSelected?'linear-gradient(135deg,#7c3aed,#a855f7)':'#e2e8f0'};color:${_urSelected?'#fff':'#94a3b8'};font-size:13px;font-weight:600;cursor:${_urSelected?'pointer':'default'};font-family:inherit" ${_urSelected?'':'disabled'}>Submit Rating</button>
        </div>
      </div>`;

    overlay.querySelectorAll(".ur-star").forEach(btn => {
      btn.addEventListener("click", () => {
        _urSelected = parseInt(btn.dataset.val);
        _renderModal();
      });
    });

    overlay.querySelector("#ur-skip")?.addEventListener("click", () => {
      document.body.removeChild(overlay);
      APP.amendment = null;
      navigate("signed");
    });

    overlay.querySelector("#ur-submit")?.addEventListener("click", async () => {
      if (!_urSelected) return;
      const fb = overlay.querySelector("#ur-feedback")?.value?.trim() || null;
      document.body.removeChild(overlay);
      // Fire and forget — don't block navigation
      if (typeof apiSubmitUsabilityRating === "function") {
        apiSubmitUsabilityRating({
          encounter_id: _urEncounterId,
          hadm_id:      _urHadmId ? parseInt(_urHadmId) : null,
          attending_id: (typeof getUser === "function" ? getUser()?.id : null) || null,
          rating:       _urSelected,
          feedback:     fb,
        }).catch(() => {});
      }
      APP.amendment = null;
      navigate("signed");
    });
  }

  _renderModal();
  document.body.appendChild(overlay);
}

window._openUsabilityRating = _openUsabilityRating;

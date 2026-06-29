// Screens — Amendment Form · Amendment Submitted

let _amd = {
  reason:    "",   // 'factual'|'diagnosis'|'medication'|'procedure'|'other'
  section:   "",
  details:   "",
  docName:   "",
  submitting: false,
  error:     "",
};

const _amdSections = [
  "§1 — Patient Identification & Admission",
  "§2 — Chief Complaint",
  "§3 — History of Presenting Illness",
  "§4 — Significant Past History",
  "§5 — Examination Findings",
  "§6 — Laboratory Investigations",
  "§7 — Imaging & Procedure Findings",
  "§8 — Working Diagnosis",
  "§9 — Hospital Course",
  "§10 — Procedures Performed",
  "§11 — Discharge Medications",
  "§12 — Follow-up & Discharge Advice",
  "§13 — Discharge Diagnosis",
  "§14 — Condition at Discharge",
  "§15 — Patient Acknowledgement",
];

const _amdReasons = [
  { value: "factual",    label: "Factual correction"      },
  { value: "diagnosis",  label: "Diagnosis update"        },
  { value: "medication", label: "Medication dose change"  },
  { value: "procedure",  label: "Procedure clarification" },
  { value: "other",      label: "Other"                   },
];

// ── Amendment Form ────────────────────────────────────────────────────────────

SCREEN_RENDERERS["amendment"] = function renderAmendment() {
  const rd       = APP.reviewData || {};
  const patName  = rd.patient?.full_name || "Patient";
  const displayId = rd.encounter?.display_id || rd.hadmId || "—";
  const version  = `v${rd.docVersion || 1}.0`;

  const canSubmit = _amd.reason && _amd.details.trim().length >= 10;

  const _RADIO = (r) => {
    const active = _amd.reason === r.value;
    return `<label style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:8px;cursor:pointer;border:1.5px solid ${active ? '#EA580C' : '#e5e7eb'};background:${active ? '#FFF7ED' : '#fff'};font-size:13px;font-weight:${active ? '600' : '400'};color:${active ? '#C2410C' : '#374151'}">
      <input type="radio" name="amd-reason" value="${r.value}" ${active ? 'checked' : ''} style="accent-color:#EA580C;width:14px;height:14px;flex-shrink:0">
      ${r.label}
    </label>`;
  };

  return `
    <div style="min-height:100vh;background:#f9fafb;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">

      <!-- Topbar -->
      <div style="background:#fff;border-bottom:1.5px solid #e5e7eb;padding:0 24px;height:52px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04)">
        <button id="amd-cancel" style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer">
          ← Back to Signed
        </button>
        <div style="width:1px;height:20px;background:#e5e7eb"></div>
        <span style="font-size:14px;font-weight:700;color:#111827">Request Amendment</span>
        <div style="flex:1"></div>
        <span style="font-size:12px;color:#6b7280">${displayId} · ${patName} · ${version}</span>
      </div>

      <!-- Content -->
      <div style="max-width:680px;margin:0 auto;padding:32px 24px 48px">

        <!-- NABH notice -->
        <div style="background:#FFFBEB;border:1px solid #FCD34D;border-radius:8px;padding:13px 16px;margin-bottom:24px;display:flex;align-items:flex-start;gap:10px">
          <span style="font-size:16px;flex-shrink:0">⚠️</span>
          <div style="font-size:13px;color:#78350F;line-height:1.6">
            <strong>NABH Compliance:</strong> ${version} is preserved in the audit trail. This amendment will create ${version.replace(/\.\d+$/, '.1')} and require re-signature.
          </div>
        </div>

        <!-- Reason -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:16px">
          <div style="font-size:13.5px;font-weight:700;color:#111827;margin-bottom:14px">
            Reason for Amendment <span style="color:#DC2626">*</span>
          </div>
          <div style="display:flex;flex-direction:column;gap:7px" id="amd-reason-group">
            ${_amdReasons.map(_RADIO).join('')}
          </div>
        </div>

        <!-- Details -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:16px">
          <div style="font-size:13.5px;font-weight:700;color:#111827;margin-bottom:12px">
            Amendment Details <span style="color:#DC2626">*</span>
          </div>
          <textarea id="amd-details" placeholder="Describe what needs to change — e.g. §5 ECG finding showing new-onset LBBB was missed in the original generation."
            style="width:100%;padding:10px 12px;border:1.5px solid #e5e7eb;border-radius:8px;font-size:13px;color:#111827;resize:vertical;min-height:100px;font-family:inherit;outline:none;box-sizing:border-box;line-height:1.7">${_amd.details.replace(/</g, '&lt;')}</textarea>
          <div style="font-size:11.5px;color:#9ca3af;margin-top:6px">Minimum 10 characters required.</div>
        </div>

        <!-- Supporting document -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:24px">
          <div style="font-size:13.5px;font-weight:700;color:#111827;margin-bottom:12px">
            Supporting Document <span style="font-size:12px;font-weight:400;color:#9ca3af">(optional)</span>
          </div>
          <div id="amd-drop-zone" style="border:2px dashed #D1D5DB;border-radius:8px;padding:24px;text-align:center;cursor:pointer;background:#F9FAFB">
            ${_amd.docName
              ? `<div style="font-size:13px;font-weight:600;color:#15803D">✓ ${_amd.docName}</div>
                 <button id="amd-remove-doc" style="margin-top:6px;font-size:11.5px;color:#9ca3af;background:none;border:none;cursor:pointer;text-decoration:underline">Remove</button>`
              : `<div style="font-size:22px;margin-bottom:8px">📎</div>
                 <div style="font-size:13px;font-weight:600;color:#374151">Attach supporting document</div>
                 <div style="font-size:11.5px;color:#9ca3af;margin-top:4px">PDF, DOCX, image</div>`
            }
          </div>
          <input type="file" id="amd-file-input" accept=".pdf,.docx,.doc,.png,.jpg,.jpeg" style="display:none">
        </div>

        ${_amd.error ? `<div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12.5px;color:#DC2626">${_amd.error}</div>` : ''}

        <!-- Actions -->
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          <button id="amd-cancel-btn" style="display:inline-flex;align-items:center;gap:6px;padding:11px 20px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13.5px;font-weight:600;color:#374151;cursor:pointer">
            ← Back
          </button>
          <button id="amd-submit" ${canSubmit && !_amd.submitting ? '' : 'disabled'}
            style="display:inline-flex;align-items:center;gap:7px;padding:11px 24px;border:none;border-radius:8px;font-size:13.5px;font-weight:700;cursor:${canSubmit && !_amd.submitting ? 'pointer' : 'not-allowed'};${canSubmit && !_amd.submitting ? 'background:#EA580C;color:#fff;box-shadow:0 4px 12px rgba(234,88,12,.3);' : 'background:#f3f4f6;color:#9ca3af;'}">
            ${_amd.submitting
              ? '<span style="width:14px;height:14px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin 0.7s linear infinite;display:inline-block"></span> Submitting…'
              : '📝 Submit Amendment'}
          </button>
        </div>

      </div>
    </div>`;
};

SCREEN_SETUP["amendment"] = function setupAmendment() {
  const _goBack = () => {
    _amd = { reason:"", section:"", details:"", docName:"", submitting:false, error:"" };
    navigate("signed");
  };
  document.getElementById("amd-cancel")?.addEventListener("click",     _goBack);
  document.getElementById("amd-cancel-btn")?.addEventListener("click", _goBack);

  document.querySelectorAll('input[name="amd-reason"]').forEach(radio => {
    radio.addEventListener("change", e => { _amd.reason = e.target.value; renderApp(); });
  });

  document.getElementById("amd-details")?.addEventListener("input", e => {
    _amd.details = e.target.value;
    const btn = document.getElementById("amd-submit");
    if (btn) {
      const can = _amd.reason && e.target.value.trim().length >= 10;
      btn.disabled = !can;
      btn.style.background  = can ? "#EA580C" : "#f3f4f6";
      btn.style.color       = can ? "#fff"    : "#9ca3af";
      btn.style.cursor      = can ? "pointer" : "not-allowed";
      btn.style.boxShadow   = can ? "0 4px 12px rgba(234,88,12,.3)" : "none";
    }
  });

  const dropZone  = document.getElementById("amd-drop-zone");
  const fileInput = document.getElementById("amd-file-input");
  dropZone?.addEventListener("click", () => { if (!_amd.docName) fileInput?.click(); });
  dropZone?.addEventListener("dragover",  e => { e.preventDefault(); dropZone.style.borderColor = "#EA580C"; dropZone.style.background = "#FFF7ED"; });
  dropZone?.addEventListener("dragleave", ()  => { dropZone.style.borderColor = "#D1D5DB"; dropZone.style.background = "#F9FAFB"; });
  dropZone?.addEventListener("drop", e => { e.preventDefault(); const f = e.dataTransfer?.files[0]; if (f) { _amd.docName = f.name; renderApp(); } });
  fileInput?.addEventListener("change", e => { const f = e.target.files?.[0]; if (f) { _amd.docName = f.name; renderApp(); } });
  document.getElementById("amd-remove-doc")?.addEventListener("click", e => {
    e.stopPropagation(); _amd.docName = ""; if (fileInput) fileInput.value = ""; renderApp();
  });

  document.getElementById("amd-submit")?.addEventListener("click", async () => {
    if (!(_amd.reason && _amd.details.trim().length >= 10)) return;
    _amd.submitting = true; _amd.error = ""; renderApp();

    try {
      const encId = APP.reviewData?.encounter?.id;
      const body  = {
        reason:            _amd.reason,
        section:           _amd.section,
        details:           _amd.details,
        doc_name:          _amd.docName || null,
        submitted_by_name: getUser()?.full_name || "",
        from_version:      `v${APP.reviewData?.docVersion || 1}.0`,
      };
      const res  = await fetch(`${API_BASE}/api/amendments/${encId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Amendment save failed");

      APP.amendment = {
        id:          data.amendment_ref,
        version:     "v1.1",
        fromVersion: `v${APP.reviewData?.docVersion || 1}.0`,
        reason:      _amd.reason,
        section:     _amd.section,
        details:     _amd.details,
        docName:     _amd.docName || null,
        submittedBy: getUser()?.full_name || "",
        submittedAt: new Date().toISOString(),
        status:      "Pending Re-sign",
        _dbId:       data.id,
      };
      APP.amendmentCount = (APP.amendmentCount || 0) + 1;

      fetch(`${API_BASE}/api/encounters/${encId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + (sessionStorage.getItem("foqal_token") || "") },
        body: JSON.stringify({ status: "Amendment Requested" }),
      }).catch(() => {});
    } catch (err) {
      _amd.submitting = false; _amd.error = err.message; renderApp(); return;
    }

    _amd.submitting = false;
    navigate("amendment-submitted");
  });
};

// ── Amendment Submitted ───────────────────────────────────────────────────────

SCREEN_RENDERERS["amendment-submitted"] = function renderAmendmentSubmitted() {
  const amd       = APP.amendment || {};
  const rd        = APP.reviewData || {};
  const patName   = rd.patient?.full_name || "Patient";
  const displayId = rd.encounter?.display_id || rd.hadmId || "—";
  const _fmtDT    = d => d ? new Date(d).toLocaleString("en-IN", { day:"2-digit", month:"short", year:"numeric", hour:"2-digit", minute:"2-digit", hour12:false }) + " IST" : "—";

  return `
    <div style="min-height:100vh;background:#f9fafb;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">

      <!-- Topbar -->
      <div style="background:#fff;border-bottom:1.5px solid #e5e7eb;padding:0 24px;height:52px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04)">
        <button onclick="window.location.href='/doctor-queue.html'" style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer">
          ← My Queue
        </button>
        <div style="width:1px;height:20px;background:#e5e7eb"></div>
        <span style="font-size:14px;font-weight:700;color:#111827">Amendment Submitted</span>
        <div style="flex:1"></div>
        <span style="font-size:12px;color:#6b7280">${displayId} · ${patName}</span>
      </div>

      <!-- Content -->
      <div style="max-width:680px;margin:0 auto;padding:32px 24px 48px">

        <!-- Success banner -->
        <div style="background:#F0FDF4;border:1.5px solid #86EFAC;border-radius:10px;padding:14px 20px;margin-bottom:24px;display:flex;align-items:center;gap:12px">
          <div style="width:30px;height:30px;border-radius:50%;background:#16A34A;display:grid;place-items:center;flex-shrink:0">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <div>
            <div style="font-size:13.5px;font-weight:700;color:#15803D">Amendment Request Submitted</div>
            <div style="font-size:12.5px;color:#16A34A;margin-top:1px">${amd.version || 'v1.1'} pending re-signature · Original ${amd.fromVersion || 'v1.0'} preserved in audit log</div>
          </div>
        </div>

        <!-- Amendment details card -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;margin-bottom:20px">
          <div style="font-size:13.5px;font-weight:700;color:#111827;margin-bottom:16px">Amendment Details</div>
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            ${[
              ["Amendment ID",  `<span style="font-family:monospace;font-size:12px">${amd.id || '—'}</span>`],
              ["Version",       `${amd.version || 'v1.1'} (from ${amd.fromVersion || 'v1.0'})`],
              ["Submitted by",  amd.submittedBy || getUser()?.full_name || '—'],
              ["Time",          _fmtDT(amd.submittedAt)],
              ["Section",       amd.section || '—'],
              ["Reason",        _amdReasons.find(r => r.value === amd.reason)?.label || amd.reason || '—'],
              ["Status",        `<span style="display:inline-flex;align-items:center;gap:5px"><span style="width:7px;height:7px;border-radius:50%;background:#D97706;display:inline-block"></span><span style="color:#92400E;font-weight:600">${amd.status || 'Pending Re-sign'}</span></span>`],
            ].map(([k, v]) => `
              <tr style="border-bottom:1px solid #f3f4f6">
                <td style="padding:10px 14px 10px 0;color:#6b7280;white-space:nowrap;width:130px;vertical-align:top">${k}</td>
                <td style="padding:10px 0;color:#111827;font-weight:500">${v}</td>
              </tr>`).join('')}
          </table>
          ${amd.details ? `
          <div style="margin-top:14px;padding-top:14px;border-top:1px solid #f3f4f6">
            <div style="font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Details</div>
            <div style="font-size:13px;color:#374151;line-height:1.7">${amd.details.replace(/</g, '&lt;')}</div>
          </div>` : ''}
        </div>

        <!-- Actions -->
        <div style="display:flex;align-items:center;gap:12px">
          <button onclick="window.location.href='/doctor-queue.html'" style="display:inline-flex;align-items:center;gap:6px;padding:11px 20px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13.5px;font-weight:600;color:#374151;cursor:pointer">
            ← My Queue
          </button>
        </div>

      </div>
    </div>`;
};

SCREEN_SETUP["amendment-submitted"] = function setupAmendmentSubmitted() {
  if (!APP.amendment && APP.reviewData?.encounter?.id) {
    fetch(`${API_BASE}/api/amendments/${APP.reviewData.encounter.id}`)
      .then(r => r.json())
      .then(d => {
        if (d.amendment) APP.amendment = d.amendment;
        if (d.amendment_count != null) APP.amendmentCount = d.amendment_count;
        renderApp();
      })
      .catch(() => {});
  }

};

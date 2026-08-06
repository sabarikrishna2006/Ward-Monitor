// Screens — S7 Amendment Form · S7b Amendment Submitted

let _amd = {
  reason:    "",      // 'factual'|'diagnosis'|'medication'|'procedure'|'other'
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
  { value: "factual",     label: "Factual correction"       },
  { value: "diagnosis",   label: "Diagnosis update"         },
  { value: "medication",  label: "Medication dose change"   },
  { value: "procedure",   label: "Procedure clarification"  },
  { value: "other",       label: "Other"                    },
];

// ── S7 — Amendment Form ───────────────────────────────────────────────────────

SCREEN_RENDERERS["amendment"] = function renderAmendment() {
  const user  = getUser();
  const rd    = APP.reviewData || {};
  const hadmId = rd.hadmId || "24181354";
  const patName = (rd.patient || {}).full_name || "Patient";
  const version = "v1.0";

  const radioBtnStyle = (val) => `
    display:flex;align-items:center;gap:8px;padding:9px 14px;border-radius:8px;cursor:pointer;
    border:1.5px solid ${_amd.reason===val?'#EA580C':'#E5E7EB'};
    background:${_amd.reason===val?'#FFF7ED':'white'};
    font-size:13px;font-weight:${_amd.reason===val?'600':'400'};color:${_amd.reason===val?'#C2410C':'#374151'};
    transition:all .12s;`;

  const canSubmit = _amd.reason && _amd.section && _amd.details.trim().length >= 10;

  return `
    <div class="app-shell">
      ${renderSidebar("doctor","my-queue")}
      <div class="main">
        ${renderTopbar({ user, crumbs:["My Queue","Signed Summary","Amendment"] })}

        <div class="content" style="max-width:720px">
          <!-- Header -->
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px">
            <div style="padding:3px 8px;background:#F97316;color:white;font-size:10px;font-weight:800;border-radius:4px;font-family:var(--mono)">S7</div>
            <div style="font-size:17px;font-weight:800;color:var(--ink)">Amendment Request — ${hadmId}</div>
            <div style="font-size:12px;color:var(--muted);font-family:var(--mono)">${version}</div>
          </div>

          <!-- NABH warning -->
          <div style="background:#FFFBEB;border:1px solid #FCD34D;border-radius:8px;padding:12px 16px;margin-bottom:20px;display:flex;align-items:flex-start;gap:10px">
            <span style="font-size:16px;flex-shrink:0">⚠️</span>
            <div>
              <div style="font-size:12.5px;font-weight:700;color:#92400E">NABH Compliance:</div>
              <div style="font-size:12px;color:#78350F;margin-top:2px;line-height:1.6">
                Original ${version} is preserved in the audit trail. This amendment will create v1.1 and require re-signature.
              </div>
            </div>
          </div>

          <!-- Reason for Amendment -->
          <div class="card" style="margin-bottom:16px">
            <div style="font-size:13px;font-weight:700;color:var(--ink);margin-bottom:12px">Reason for Amendment <span style="color:#DC2626">*</span></div>
            <div style="display:flex;flex-direction:column;gap:6px" id="amd-reason-group">
              ${_amdReasons.map(r => `
                <label style="${radioBtnStyle(r.value)}">
                  <input type="radio" name="amd-reason" value="${r.value}" ${_amd.reason===r.value?'checked':''} style="accent-color:#EA580C;width:14px;height:14px">
                  ${r.label}
                </label>
              `).join('')}
            </div>
          </div>

          <!-- Section to Amend -->
          <div class="card" style="margin-bottom:16px">
            <div style="font-size:13px;font-weight:700;color:var(--ink);margin-bottom:10px">Section to Amend <span style="color:#DC2626">*</span></div>
            <select id="amd-section" style="width:100%;padding:9px 12px;border:1.5px solid ${_amd.section?'#EA580C':'#E5E7EB'};border-radius:8px;font-size:13px;color:var(--ink);background:white;font-family:inherit;outline:none;cursor:pointer">
              <option value="">Select a section…</option>
              ${_amdSections.map(s => `<option value="${s}" ${_amd.section===s?'selected':''}>${s}</option>`).join('')}
            </select>
          </div>

          <!-- Amendment Details -->
          <div class="card" style="margin-bottom:16px">
            <div style="font-size:13px;font-weight:700;color:var(--ink);margin-bottom:10px">Amendment Details <span style="color:#DC2626">*</span></div>
            <textarea id="amd-details" placeholder="Describe the amendment clearly — e.g. §5 — Adding new-onset LBBB finding from ECG report that was missed in original generation."
              style="width:100%;padding:10px 12px;border:1.5px solid #E5E7EB;border-radius:8px;font-size:13px;color:var(--ink);resize:vertical;min-height:100px;font-family:inherit;outline:none;box-sizing:border-box;line-height:1.7">${_amd.details.replace(/</g,'&lt;')}</textarea>
            <div style="font-size:11px;color:var(--muted);margin-top:6px">Minimum 10 characters required.</div>
          </div>

          <!-- Supporting Document -->
          <div class="card" style="margin-bottom:24px">
            <div style="font-size:13px;font-weight:700;color:var(--ink);margin-bottom:10px">Supporting Document <span style="font-weight:400;color:var(--muted)">(optional)</span></div>
            <div id="amd-drop-zone" style="border:2px dashed #D1D5DB;border-radius:8px;padding:24px;text-align:center;cursor:pointer;transition:border-color .12s;background:#F9FAFB">
              ${_amd.docName
                ? `<div style="font-size:13px;font-weight:600;color:#15803D">✓ ${_amd.docName}</div>
                   <button id="amd-remove-doc" style="margin-top:6px;font-size:11.5px;color:var(--muted);background:none;border:none;cursor:pointer;text-decoration:underline">Remove</button>`
                : `<div style="font-size:22px;margin-bottom:8px">📎</div>
                   <div style="font-size:13px;font-weight:600;color:var(--ink)">Attach supporting document</div>
                   <div style="font-size:11.5px;color:var(--muted);margin-top:4px">PDF, DOCX, image</div>`
              }
            </div>
            <input type="file" id="amd-file-input" accept=".pdf,.docx,.doc,.png,.jpg,.jpeg" style="display:none">
          </div>

          ${_amd.error ? `<div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12.5px;color:#DC2626">${_amd.error}</div>` : ''}

          <!-- Actions -->
          <div style="display:flex;gap:10px;justify-content:flex-end;margin-bottom:32px">
            <button id="amd-cancel" class="btn btn-outline">Cancel</button>
            <button id="amd-submit" class="btn btn-navy" ${canSubmit&&!_amd.submitting?'':'disabled'} style="${canSubmit&&!_amd.submitting?'background:#EA580C;border-color:#EA580C;':'opacity:0.5;'}display:flex;align-items:center;gap:7px">
              ${_amd.submitting?'<span style="width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:white;border-radius:50%;animation:spin 0.7s linear infinite;display:inline-block"></span> Submitting…':'📝 Submit Amendment'}
            </button>
          </div>
        </div>
      </div>
    </div>`;
};

SCREEN_SETUP["amendment"] = function setupAmendment() {
  // Reason radio buttons
  document.querySelectorAll('input[name="amd-reason"]').forEach(radio => {
    radio.addEventListener("change", e => {
      _amd.reason = e.target.value;
      renderApp();
    });
  });

  // Section dropdown
  document.getElementById("amd-section")?.addEventListener("change", e => {
    _amd.section = e.target.value;
    renderApp();
  });

  // Details textarea — no rerender on input, just update state
  document.getElementById("amd-details")?.addEventListener("input", e => {
    _amd.details = e.target.value;
    // Re-enable submit button live without full rerender
    const btn = document.getElementById("amd-submit");
    if (btn) {
      const can = _amd.reason && _amd.section && e.target.value.trim().length >= 10;
      btn.disabled = !can;
      btn.style.opacity = can ? "1" : "0.5";
    }
  });

  // File upload
  const dropZone  = document.getElementById("amd-drop-zone");
  const fileInput = document.getElementById("amd-file-input");

  dropZone?.addEventListener("click", () => {
    if (!_amd.docName) fileInput?.click();
  });
  dropZone?.addEventListener("dragover", e => {
    e.preventDefault();
    dropZone.style.borderColor = "#EA580C";
    dropZone.style.background  = "#FFF7ED";
  });
  dropZone?.addEventListener("dragleave", () => {
    dropZone.style.borderColor = "#D1D5DB";
    dropZone.style.background  = "#F9FAFB";
  });
  dropZone?.addEventListener("drop", e => {
    e.preventDefault();
    const f = e.dataTransfer?.files[0];
    if (f) { _amd.docName = f.name; renderApp(); }
  });
  fileInput?.addEventListener("change", e => {
    const f = e.target.files?.[0];
    if (f) { _amd.docName = f.name; renderApp(); }
  });

  document.getElementById("amd-remove-doc")?.addEventListener("click", e => {
    e.stopPropagation();
    _amd.docName = "";
    if (fileInput) fileInput.value = "";
    renderApp();
  });

  // Cancel
  document.getElementById("amd-cancel")?.addEventListener("click", () => {
    _amd = { reason:"", section:"", details:"", docName:"", submitting:false, error:"" };
    navigate("signed");
  });

  // Submit
  document.getElementById("amd-submit")?.addEventListener("click", async () => {
    if (!(_amd.reason && _amd.section && _amd.details.trim().length >= 10)) return;
    _amd.submitting = true;
    _amd.error = "";
    renderApp();

    try {
      const encId = APP.reviewData?.encounter?.id;
      const body = {
        reason:            _amd.reason,
        section:           _amd.section,
        details:           _amd.details,
        doc_name:          _amd.docName || null,
        submitted_by_name: getUser()?.full_name || "",
        from_version:      "v1.0",
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
        fromVersion: "v1.0",
        reason:      _amd.reason,
        section:     _amd.section,
        details:     _amd.details,
        docName:     _amd.docName || null,
        submittedBy: getUser()?.full_name || "",
        submittedAt: new Date().toISOString(),
        status:      "Pending Re-sign",
        _dbId:       data.id,
      };

      // Flag encounter so resident sees the amendment card and Kanban shows it
      fetch(`${API_BASE}/api/encounters/${encId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json",
                   "Authorization": "Bearer " + (sessionStorage.getItem("foqal_token") || "") },
        body: JSON.stringify({ status: "Amendment Requested" }),
      }).catch(() => {});
    } catch (err) {
      _amd.submitting = false;
      _amd.error = err.message;
      renderApp();
      return;
    }

    _amd.submitting = false;
    navigate("amendment-submitted");
  });
};

// ── S7b — Amendment Submitted ─────────────────────────────────────────────────

SCREEN_RENDERERS["amendment-submitted"] = function renderAmendmentSubmitted() {
  const user   = getUser();
  const amd    = APP.amendment || {};
  const fmtDT  = d => d ? new Date(d).toLocaleString("en-IN", {day:"numeric",month:"long",year:"numeric",hour:"2-digit",minute:"2-digit"}) : "—";

  return `
    <div class="app-shell">
      ${renderSidebar("doctor","my-queue")}
      <div class="main">
        ${renderTopbar({ user, crumbs:["My Queue","Signed Summary","Amendment Submitted"] })}

        <div class="content" style="max-width:640px">
          <!-- Header -->
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px">
            <div style="padding:3px 8px;background:#059669;color:white;font-size:10px;font-weight:800;border-radius:4px;font-family:var(--mono)">S7b</div>
            <div style="font-size:17px;font-weight:800;color:var(--ink)">Amendment Submitted</div>
          </div>

          <!-- Status card -->
          <div class="card" style="margin-bottom:16px;text-align:center;padding:32px">
            <div style="font-size:48px;margin-bottom:12px">📝</div>
            <div style="font-size:16px;font-weight:800;color:var(--ink);margin-bottom:4px">Amendment ${amd.version || 'v1.1'} Pending Re-sign</div>
            <div style="font-size:12.5px;color:var(--muted);line-height:1.6">Original v1.0 preserved in audit log — NABH compliant</div>
          </div>

          <!-- Details -->
          <div class="card" style="margin-bottom:16px">
            <div style="display:grid;grid-template-columns:130px 1fr;gap:8px 12px;font-size:13px">
              <span style="color:var(--muted);font-weight:600">Amendment ID</span>
              <span style="font-family:var(--mono);font-size:11.5px;color:var(--ink)">${amd.id || 'AMD-2026-0087-01'}</span>

              <span style="color:var(--muted);font-weight:600">Version</span>
              <span style="color:var(--ink)">${amd.version || 'v1.1'} (from ${amd.fromVersion || 'v1.0'})</span>

              <span style="color:var(--muted);font-weight:600">Submitted by</span>
              <span style="color:var(--ink)">${amd.submittedBy || (getUser()?.full_name || 'Dr. Anand Sharma')}</span>

              <span style="color:var(--muted);font-weight:600">Time</span>
              <span style="color:var(--ink)">${fmtDT(amd.submittedAt)}</span>

              <span style="color:var(--muted);font-weight:600">Section</span>
              <span style="color:var(--ink)">${amd.section || '—'}</span>

              <span style="color:var(--muted);font-weight:600">Status</span>
              <span style="display:inline-flex;align-items:center;gap:5px">
                <span style="width:7px;height:7px;border-radius:50%;background:#D97706;display:inline-block"></span>
                <span style="color:#92400E;font-weight:600">${amd.status || 'Pending Re-sign'}</span>
              </span>
            </div>

            ${amd.details ? `
              <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">
                <div style="font-size:11.5px;font-weight:600;color:var(--muted);margin-bottom:5px;text-transform:uppercase;letter-spacing:.05em">Amendment Details</div>
                <div style="font-size:13px;color:var(--ink);line-height:1.7">${amd.details.replace(/</g,'&lt;')}</div>
              </div>
            ` : ''}
          </div>

          <!-- Actions -->
          <div style="display:flex;gap:10px;justify-content:flex-end;margin-bottom:32px;flex-wrap:wrap">
            <button id="amdsub-audit" class="btn btn-outline">View Audit Log</button>
            <button id="amdsub-resign" class="btn btn-navy" style="display:flex;align-items:center;gap:6px">Re-sign ${amd.version || 'v1.1'} →</button>
          </div>
        </div>
      </div>
    </div>`;
};

SCREEN_SETUP["amendment-submitted"] = function setupAmendmentSubmitted() {
  // If APP.amendment is missing (page refresh), reload from DB
  if (!APP.amendment && APP.reviewData?.encounter?.id) {
    fetch(`${API_BASE}/api/amendments/${APP.reviewData.encounter.id}`)
      .then(r => r.json())
      .then(d => { if (d.amendment) { APP.amendment = d.amendment; renderApp(); } })
      .catch(() => {});
  }

  document.getElementById("amdsub-audit")?.addEventListener("click", () => {
    alert("Audit log — NABH compliant record:\n\n" +
      "v1.0 Original signed\n" +
      "Amendment requested: " + (APP.amendment?.reason || "factual") + "\n" +
      "v1.1 Amendment submitted — Pending Re-sign");
  });

  document.getElementById("amdsub-resign")?.addEventListener("click", () => {
    // Reset amendment state and go back to review to re-sign
    _amd = { reason:"", section:"", details:"", docName:"", submitting:false, error:"" };
    navigate("review");
  });
};

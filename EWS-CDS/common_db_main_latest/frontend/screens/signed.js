// Screen — Discharge Summary Signed confirmation page

// Rehydrate signature metadata (mci, sig_png, designation, hospital, full_name) that was
// persisted to app_summaries.signature_data at sign-off — needed when this screen is opened
// in a fresh session (e.g. from the Completed tab) rather than right after signing, since
// APP.reviewData._sigDataUrl / signedMci / etc. only exist in the signing session's memory.
function _sgSignatureData(rd) {
  try { return JSON.parse(rd?.encounter?.summary?.signature_data || "{}"); }
  catch { return {}; }
}

// Stable per-document Doctor ID — seeded from the doctor name + hadm_id so it
// stays the same across re-renders/reloads of the same signed document
// instead of jumping around on every render.
function _sgDoctorId(name, hadmId) {
  const s = String(name || "") + "|" + String(hadmId || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return "DOC-" + String(10000 + (Math.abs(h) % 90000));
}

// Convert stored markdown ("**Section**\nbody...") into readable section HTML —
// shared by the on-page summary view and the print/download window.
function _sgSectionsHTML(content) {
  return (content || "").split(/\n\n(?=\*\*)/).filter(Boolean).map(chunk => {
    const lines    = chunk.split('\n');
    const rawHeader = lines[0].replace(/\*\*/g, '').trim();
    // Strip the leading "S1 — " / "S12 - " NABH section-number prefix — the
    // doctor-facing signed view just needs the heading text, not the code.
    const header    = rawHeader.replace(/^S\d+\s*[—–-]\s*/i, '').trim();
    const body   = lines.slice(1).join('\n').trim()
      .replace(/\s*\[Doctor Edited\]/g, '')
      .replace(/\n/g, '<br>');
    if (!header) return '';
    return `<div style="margin-bottom:22px;page-break-inside:avoid">
      <div style="font-size:11px;font-weight:800;color:#800080;text-transform:uppercase;letter-spacing:.05em;border-left:3px solid #800080;padding-left:9px;margin-bottom:6px">${header}</div>
      <div style="font-size:13px;line-height:1.75;color:#1f2937;padding-left:12px">${body || '<em style="color:#9ca3af">—</em>'}</div>
    </div>`;
  }).join('');
}

// ── Signed page renderer ──────────────────────────────────────────────────────
SCREEN_RENDERERS["signed"] = function renderSigned() {
  const user = getUser();
  const rd   = APP.reviewData || {};
  const pat  = rd.patient   || {};
  const sig  = _sgSignatureData(rd);

  const patName    = pat.full_name || "Patient";
  const displayId  = rd.hadmId ? fmtPid(rd.hadmId) : "—";

  // Doctor name: prefer what was persisted on sign-off, fall back to current user
  const _rawName   = rd.encounter?.summary?.saved_by_name || sig.full_name || user?.full_name || user?.name || "Doctor";
  const doctorName = /^Dr\.?\s/i.test(_rawName) ? _rawName : `Dr. ${_rawName}`;
  const doctorId   = _sgDoctorId(doctorName, rd.hadmId);

  // Timestamps — rd.signedAt only exists in the signing session's memory;
  // reopening from the Completed tab needs the persisted column instead, or
  // this silently shows "right now" for a document signed days ago.
  const signedAt   = rd.signedAt || rd.encounter?.summary?.signed_at || new Date().toISOString();
  const _fmtDate = iso => {
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { day:"2-digit", month:"short", year:"numeric" }) + ", " +
           d.toLocaleTimeString("en-IN", { hour:"2-digit", minute:"2-digit", hour12:false }) + " IST";
  };
  const _fmtIso = iso => iso ? iso.replace("Z", "+05:30") : "—";

  // Version
  const docVersion  = rd.docVersion ?? rd.encounter?.version ?? 1;
  const versionStr  = `v${docVersion}.0`;
  const versionLabel = docVersion === 1 ? "Original" : "Amendment";

  // PDF filename + page estimate
  const safePat   = patName.replace(/\s+/g, "_");
  const pdfName   = `${displayId}_${safePat}_DS_${versionStr}.pdf`;
  const content   = rd.finalContent || rd.content || "";
  const pageCount = Math.max(8, Math.ceil(content.length / 280));

  const sectionsHTML = _sgSectionsHTML(content);

  return `
    <div style="min-height:100vh;background:#f9fafb;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">

      <!-- Simple top bar: no sidebar -->
      <div style="background:#fff;border-bottom:1.5px solid #e5e7eb;padding:0 24px;height:52px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;box-shadow:0 1px 4px rgba(0,0,0,.04)">
        <button onclick="window.location.href='/doctor-queue.html'" style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
          My Queue
        </button>
        <div style="width:1px;height:20px;background:#e5e7eb"></div>
        <span style="font-size:14px;font-weight:700;color:#111827">Discharge Summary Signed</span>
        <div style="flex:1"></div>
        <span style="font-size:12px;color:#6b7280">${displayId} · ${patName}</span>
      </div>

      <!-- Page content -->
      <div style="max-width:900px;margin:0 auto;padding:32px 24px 56px">

        <!-- Green success banner -->
        <div style="background:#F0FDF4;border:1.5px solid #86EFAC;border-radius:10px;padding:14px 20px;margin-bottom:20px;display:flex;align-items:center;gap:12px">
          <div style="width:30px;height:30px;border-radius:50%;background:#16A34A;display:grid;place-items:center;flex-shrink:0">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <div>
            <div style="font-size:13.5px;font-weight:700;color:#15803D">Summary Signed Successfully</div>
            <div style="font-size:12.5px;color:#16A34A;margin-top:2px">
              ${displayId} — ${patName} &nbsp;·&nbsp; ${doctorName} &nbsp;·&nbsp; ${_fmtDate(signedAt)} &nbsp;·&nbsp; ${versionStr}
            </div>
          </div>
        </div>

        <!-- Single document card: full summary + signature footer + actions -->
        <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;overflow:hidden">

          <!-- Document header -->
          <div style="padding:18px 28px;border-bottom:1.5px solid #f3f4f6;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
            <div>
              <div style="font-size:14.5px;font-weight:800;color:#111827">Discharge Summary — ${versionStr}</div>
              <div style="font-size:12px;color:#6b7280;margin-top:2px;word-break:break-all">${pdfName} &nbsp;·&nbsp; ${pageCount} pages &nbsp;·&nbsp; NABH Compliant</div>
            </div>
            <span style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;background:#F0FDF4;color:#15803D;border:1px solid #86EFAC;font-size:11px;font-weight:700;white-space:nowrap">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              Signed
            </span>
          </div>

          <!-- Full summary content -->
          <div style="padding:26px 28px;max-height:640px;overflow-y:auto">
            ${sectionsHTML || '<div style="color:#9ca3af;font-style:italic;text-align:center;padding:30px">No content available.</div>'}
          </div>

          <!-- Signature metadata footer strip -->
          <div style="padding:18px 28px;border-top:1.5px solid #f3f4f6;background:#FAFAFB;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px">
            ${[
              ["Signed by",    doctorName,             ""],
              ["Doctor ID",    doctorId,               "font-family:monospace"],
              ["Timestamp",    _fmtIso(signedAt),      "font-family:monospace;font-size:11px"],
              ["Version",      `${versionStr} — ${versionLabel}`, ""],
            ].map(([label, value, valStyle]) => `
              <div>
                <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">${label}</div>
                <div style="font-size:12.5px;color:#111827;font-weight:600;${valStyle};word-break:break-all">${value}</div>
              </div>`).join("")}
          </div>

          <!-- Action bar -->
          <div style="padding:16px 28px;border-top:1.5px solid #e5e7eb;display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap">
            <button id="signed-amend" style="display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer">
              Request Amendment →
            </button>
            <button id="signed-download-pdf" style="display:inline-flex;align-items:center;gap:7px;padding:10px 22px;border:none;border-radius:8px;background:linear-gradient(135deg,#800080,#A020A0);color:#fff;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(128,0,128,.25)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download PDF
            </button>
          </div>

        </div>
      </div>
    </div>`;
};

// ── Setup ─────────────────────────────────────────────────────────────────────
SCREEN_SETUP["signed"] = async function setupSigned() {
  document.getElementById("signed-download-pdf")?.addEventListener("click", () => {
    const rd       = APP.reviewData || {};
    const sig      = _sgSignatureData(rd);
    const content  = rd.finalContent || rd.content || '';
    const patName  = rd.patient?.full_name || 'Patient';
    const _raw     = rd.signedName || rd.encounter?.summary?.saved_by_name || sig.full_name || getUser()?.full_name || 'Doctor';
    const docName  = /^Dr\.?\s/i.test(_raw) ? _raw : `Dr. ${_raw}`;
    const docId    = _sgDoctorId(docName, rd.hadmId);
    const desig      = rd.signedDesig || sig.designation || 'Attending Physician';
    const _signedRaw = rd.signedAt || rd.encounter?.summary?.signed_at;
    const signedAt   = _signedRaw
      ? new Date(_signedRaw).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:false }) + ' IST'
      : '—';
    const version   = `v${rd.docVersion || 1}.0`;
    const displayId = rd.hadmId ? fmtPid(rd.hadmId) : '—';
    const sigImg    = rd._sigDataUrl || sig.sig_png || null;

    // Convert stored markdown to readable HTML sections
    const _secHTML = _sgSectionsHTML(content);

    const win = window.open('', '_blank', 'width=900,height=700');
    if (!win) { alert('Please allow pop-ups to download the PDF.'); return; }
    win.document.write(`<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Discharge Summary ${displayId}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#fff;color:#111;padding:48px 56px;max-width:860px;margin:0 auto}
@media print{body{padding:24px 32px}@page{margin:2cm}}
</style></head><body>
<div style="display:flex;align-items:flex-start;justify-content:space-between;border-bottom:2.5px solid #800080;padding-bottom:16px;margin-bottom:28px">
  <div>
    <div style="font-size:20px;color:#800080;font-weight:800;margin-bottom:4px">Discharge Summary</div>
    <div style="font-size:12px;color:#6b7280;line-height:1.7"><strong>${patName}</strong> &nbsp;·&nbsp; ${displayId} &nbsp;·&nbsp; ${version}<br>Signed: ${signedAt}</div>
  </div>
  <div style="text-align:right;font-size:11px;color:#6b7280"><div style="font-size:10px;font-weight:800;color:#800080;letter-spacing:.08em;margin-bottom:2px">FOQAL CAREOS</div>NABH Compliant · AI-Generated · Doctor Reviewed</div>
</div>
${_secHTML || '<p style="color:#9ca3af;font-style:italic">No content available.</p>'}
<div style="margin-top:40px;padding-top:20px;border-top:2px solid #e5e7eb;display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
  <div>
    <div style="font-size:10px;font-weight:800;background:#800080;color:#fff;display:inline-block;padding:2px 8px;border-radius:3px;margin-bottom:12px;letter-spacing:.05em">DIGITALLY SIGNED</div>
    ${[['Signed by', docName, ''], ['Designation', desig, ''], ['Doctor ID', docId, 'font-family:monospace;font-size:12px'], ['Timestamp', signedAt, 'font-family:monospace;font-size:11px']].map(([l,v,s])=>`
    <div style="margin-bottom:9px"><div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px">${l}</div><div style="font-size:13px;font-weight:600;color:#111;${s}">${v}</div></div>`).join('')}
  </div>
  ${sigImg ? `<div><div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px">Doctor Signature</div><img src="${sigImg}" style="max-width:220px;border:1.5px solid #e5e7eb;border-radius:6px;padding:8px"></div>` : '<div></div>'}
</div>
<div style="margin-top:20px;font-size:10px;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:12px">This document was generated by Foqal CareOS and is legally binding under NABH accreditation standards.</div>
</body></html>`);
    win.document.close();
    setTimeout(() => { win.focus(); win.print(); }, 400);
  });
  document.getElementById("signed-amend")?.addEventListener("click", () => navigate("amendment"));
};

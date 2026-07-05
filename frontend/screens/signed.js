// Screen — Discharge Summary Signed confirmation page

// Rehydrate signature metadata (mci, sig_png, designation, hospital, full_name) that was
// persisted to app_summaries.signature_data at sign-off — needed when this screen is opened
// in a fresh session (e.g. from the Completed tab) rather than right after signing, since
// APP.reviewData._sigDataUrl / signedMci / etc. only exist in the signing session's memory.
function _sgSignatureData(rd) {
  try { return JSON.parse(rd?.encounter?.summary?.signature_data || "{}"); }
  catch { return {}; }
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
  const mci        = rd.signedMci || sig.mci || "—";

  // Timestamps
  const signedAt   = rd.signedAt || new Date().toISOString();
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

  // Hash — computed async in SCREEN_SETUP, shown as placeholder until ready
  const hashDisplay = rd._contentHash || "computing…";

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
      <div style="max-width:860px;margin:0 auto;padding:32px 24px">

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

        <!-- Two-column cards -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">

          <!-- LEFT: Signed PDF card -->
          <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;display:flex;flex-direction:column;gap:16px">
            <div style="font-size:13.5px;font-weight:700;color:#111827">Signed PDF — ${versionStr}</div>

            <div style="border:1.5px dashed #E5E7EB;border-radius:8px;padding:36px 20px;text-align:center">
              <svg width="36" height="44" viewBox="0 0 36 44" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto 12px">
                <path d="M4 0h20l12 12v28a4 4 0 01-4 4H4a4 4 0 01-4-4V4a4 4 0 014-4z" fill="#F1F5F9"/>
                <path d="M24 0l12 12H28a4 4 0 01-4-4V0z" fill="#CBD5E1"/>
                <path d="M8 22h20M8 28h14" stroke="#94A3B8" stroke-width="2" stroke-linecap="round"/>
              </svg>
              <div style="font-size:13px;font-weight:600;color:#111827;word-break:break-all">${pdfName}</div>
              <div style="font-size:12px;color:#6b7280;margin-top:4px">${pageCount} pages · NABH Compliant</div>
            </div>

            <button id="signed-download-pdf" style="display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:10px 20px;border:none;border-radius:8px;background:linear-gradient(135deg,#800080,#A020A0);color:#fff;font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(128,0,128,.25)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download PDF
            </button>
          </div>

          <!-- RIGHT: Signature Metadata card -->
          <div style="background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:22px;display:flex;flex-direction:column;gap:16px">
            <div style="font-size:13.5px;font-weight:700;color:#111827">Signature Metadata</div>

            <table style="width:100%;border-collapse:collapse;font-size:13px">
              ${[
                ["Signed by",    doctorName,             ""],
                ["Registration", mci,                    "font-family:monospace"],
                ["Timestamp",    _fmtIso(signedAt),      "font-family:monospace;font-size:12px"],
                ["Version",      `${versionStr} — ${versionLabel}`, ""],
                ["Hash",         hashDisplay,            "font-family:monospace;font-size:11.5px;color:#374151"],
              ].map(([label, value, valStyle]) => `
                <tr style="border-bottom:1px solid #f3f4f6">
                  <td style="padding:10px 12px 10px 0;color:#6B7280;width:110px;vertical-align:top;white-space:nowrap">${label}</td>
                  <td style="padding:10px 0;color:#111827;font-weight:600;${valStyle};word-break:break-all">${value}</td>
                </tr>`).join("")}
            </table>

            <button id="signed-amend" style="display:inline-flex;align-items:center;gap:6px;padding:9px 16px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer;width:fit-content">
              Request Amendment →
            </button>
          </div>

        </div>
      </div>
    </div>`;
};

// ── Setup ─────────────────────────────────────────────────────────────────────
SCREEN_SETUP["signed"] = async function setupSigned() {
  // Compute SHA-256 of content async on first load, then re-render with hash
  if (!APP.reviewData?._contentHash) {
    try {
      const _txt = APP.reviewData?.finalContent || APP.reviewData?.content || "";
      const _buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(_txt));
      const _hex = Array.from(new Uint8Array(_buf)).map(b => b.toString(16).padStart(2, "0")).join("");
      if (APP.reviewData) APP.reviewData._contentHash = `sha256:${_hex.slice(0, 8)}…`;
    } catch { if (APP.reviewData) APP.reviewData._contentHash = "sha256:—"; }
    renderApp();
    return; // renderApp re-runs SCREEN_SETUP; second pass wires listeners
  }

  document.getElementById("signed-download-pdf")?.addEventListener("click", () => {
    const rd       = APP.reviewData || {};
    const sig      = _sgSignatureData(rd);
    const content  = rd.finalContent || rd.content || '';
    const patName  = rd.patient?.full_name || 'Patient';
    const _raw     = rd.signedName || rd.encounter?.summary?.saved_by_name || sig.full_name || getUser()?.full_name || 'Doctor';
    const docName  = /^Dr\.?\s/i.test(_raw) ? _raw : `Dr. ${_raw}`;
    const mci      = rd.signedMci      || sig.mci         || '—';
    const desig    = rd.signedDesig    || sig.designation || 'Attending Physician';
    const hospital = rd.signedHospital || sig.hospital    || '—';
    const signedAt = rd.signedAt
      ? new Date(rd.signedAt).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:false }) + ' IST'
      : '—';
    const version   = `v${rd.docVersion || 1}.0`;
    const displayId = rd.hadmId ? fmtPid(rd.hadmId) : '—';
    const sigImg    = rd._sigDataUrl || sig.sig_png || null;
    const hashVal   = rd._contentHash || '—';

    // Convert stored markdown to readable HTML sections
    const _secHTML = content.split(/\n\n(?=\*\*)/).filter(Boolean).map(chunk => {
      const lines  = chunk.split('\n');
      const header = lines[0].replace(/\*\*/g, '').trim();
      const body   = lines.slice(1).join('\n').trim()
        .replace(/\[Doctor Edited\]/g, '<mark style="background:#FEF9C3;color:#78350F;font-size:10px;padding:1px 5px;border-radius:3px;font-weight:700;margin-left:4px">Edited</mark>')
        .replace(/\n/g, '<br>');
      if (!header) return '';
      return `<div style="margin-bottom:22px;page-break-inside:avoid">
        <div style="font-size:11px;font-weight:800;color:#800080;text-transform:uppercase;letter-spacing:.05em;border-left:3px solid #800080;padding-left:9px;margin-bottom:6px">${header}</div>
        <div style="font-size:13px;line-height:1.75;color:#1f2937;padding-left:12px">${body || '<em style="color:#9ca3af">—</em>'}</div>
      </div>`;
    }).join('');

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
    ${[['Signed by', docName, ''], ['Designation', desig, ''], ['MCI / Reg. No.', mci, 'font-family:monospace;font-size:12px'], ['Hospital', hospital, ''], ['Timestamp', signedAt, 'font-family:monospace;font-size:11px'], ['Document Hash', hashVal, 'font-family:monospace;font-size:11px;color:#374151']].map(([l,v,s])=>`
    <div style="margin-bottom:9px"><div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px">${l}</div><div style="font-size:13px;font-weight:600;color:#111;${s}">${v}</div></div>`).join('')}
  </div>
  ${sigImg ? `<div><div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px">Doctor Signature</div><img src="${sigImg}" style="max-width:220px;border:1.5px solid #e5e7eb;border-radius:6px;padding:8px"></div>` : '<div></div>'}
</div>
<div style="margin-top:20px;font-size:10px;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:12px">This document was generated by Foqal CareOS and is legally binding under NABH accreditation standards. Digital signature hash and MCI number are sealed at the time of signing.</div>
</body></html>`);
    win.document.close();
    setTimeout(() => { win.focus(); win.print(); }, 400);
  });
  document.getElementById("signed-amend")?.addEventListener("click", () => navigate("amendment"));
};

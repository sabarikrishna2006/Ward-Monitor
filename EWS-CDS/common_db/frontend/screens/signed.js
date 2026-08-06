// Screen — Signed Summary (read-only) with S6 PDF actions, S7 amendment entry

function signedSection(title, bodyHTML) {
  return `
    <div style="margin-bottom:22px">
      <h3 style="font-size:13px;font-weight:600;color:var(--navy);text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:10px;margin-top:0">${title}</h3>
      <div style="font-size:13.5px;line-height:1.65;color:var(--ink)">${bodyHTML}</div>
    </div>`;
}

// ── S6 Helper: HL7 modal HTML ─────────────────────────────────────────────────
let _signedHl7Open = false;
let _signedHl7Copied = false;

function renderHl7Modal(hadmId, patName, signedAt) {
  if (!_signedHl7Open) return "";
  const ts = new Date(signedAt).toISOString();
  const hl7Json = JSON.stringify({
    resourceType: "Bundle",
    type: "document",
    identifier: { value: _pid },
    timestamp: ts,
    entry: [
      { resource: { resourceType: "Composition", title: "Discharge Summary", status: "final",
          subject: { reference: `Patient/${hadmId}`, display: patName },
          date: ts, author: [{ display: "Foqal CareOS · AI-Assisted" }] } }
    ]
  }, null, 2);
  return `
    <div id="hl7-overlay" style="position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,.7);display:flex;align-items:center;justify-content:center;padding:20px">
      <div style="background:white;border-radius:12px;width:580px;max-width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.3)">
        <div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px">
          <div style="width:36px;height:36px;border-radius:8px;background:#EFF6FF;display:grid;place-items:center;flex-shrink:0;font-size:16px">🔗</div>
          <div>
            <div style="font-size:14px;font-weight:700;color:var(--ink)">HL7 FHIR Share</div>
            <div style="font-size:12px;color:var(--muted)">FHIR R4 Bundle — ready for hospital EMR integration</div>
          </div>
          <button id="hl7-close" style="margin-left:auto;background:none;border:none;cursor:pointer;font-size:18px;color:var(--muted);padding:4px 8px;border-radius:4px">×</button>
        </div>
        <div style="padding:16px 22px;overflow-y:auto;flex:1">
          <pre style="font-family:'SF Mono','Menlo',monospace;font-size:11.5px;line-height:1.7;color:#1E293B;background:#F8FAFC;border:1px solid var(--border);border-radius:8px;padding:14px;white-space:pre-wrap;word-break:break-all;margin:0">${hl7Json.replace(/</g,'&lt;')}</pre>
        </div>
        <div style="padding:14px 22px;border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end">
          <button id="hl7-copy" class="btn btn-outline">${_signedHl7Copied ? '✓ Copied!' : '⎘ Copy to Clipboard'}</button>
          <button id="hl7-close2" class="btn btn-navy">Done</button>
        </div>
      </div>
    </div>`;
}

SCREEN_RENDERERS["signed"] = function renderSigned() {
  const user = getUser();
  const rd   = APP.reviewData || {};
  const pat  = rd.patient   || {};
  const adm  = rd.admission || {};

  const doctorName  = user?.full_name ? `Dr. ${user.full_name}` : (user?.name || "Doctor");
  const doctorReg   = "MCI-98765-DL";
  const fmtDate     = d => d ? new Date(d).toLocaleDateString("en-IN", {day:"numeric",month:"short",year:"numeric"}) : "—";
  const fmtDateTime = d => d ? new Date(d).toLocaleString("en-IN", {day:"numeric",month:"long",year:"numeric",hour:"2-digit",minute:"2-digit"}) : "—";
  const fmtDateTimeISO = d => d ? new Date(d).toLocaleString("en-IN", {day:"numeric",month:"long",year:"numeric",hour:"2-digit",minute:"2-digit",timeZoneName:"short"}) : "—";
  const signedAt    = rd.signedAt || new Date().toISOString();
  const version     = "v1.0";
  const hadmId      = rd.hadmId || "24181354";
  const _pid        = fmtPid(hadmId, rd.encounter?.display_id);
  const patName     = pat.full_name || "Patient";
  const pdfName     = `${hadmId}_${patName.replace(/\s+/g,'_')}_DS_${version}.pdf`;
  const shortHash   = "sha256:a4f9e2c8b1d3e5f7a2b4c6d8e1f3a5b7";

  const mdToHtml = t => t
    .replace(/\*\*Doctor's Notes\*\*/g,
      `<div style="margin-top:20px;padding-top:10px;border-top:2px solid var(--navy);font-size:13px;font-weight:700;color:var(--navy);margin-bottom:6px">Doctor's Notes</div>`)
    .replace(/\*\*(.+?)\*\*/g,
      `<div style="margin-top:18px;margin-bottom:5px;font-size:11px;font-weight:700;color:var(--navy);text-transform:uppercase;letter-spacing:0.07em;border-bottom:1px solid var(--border);padding-bottom:4px">$1</div>`)
    .replace(/^\*\s+/gm, "&bull;&nbsp;")
    .replace(/ \[Doctor Edited\]/g, ` <span style="font-size:11px;color:var(--teal);font-style:italic">[Doctor Edited]</span>`)
    .replace(/\n/g, "<br/>");

  const content = rd.finalContent || rd.content || "";
  const bodyHTML = content
    ? `<div style="font-size:13.5px;line-height:1.75;color:var(--ink)">${mdToHtml(content)}</div>`
    : `<div style="color:var(--ink-3);font-size:13px">No content available.</div>`;

  return `
    <div class="app-shell">
      ${renderSidebar("doctor","my-queue")}
      <div class="main">
        ${renderTopbar({ user, crumbs:["My Queue","Signed Summary"] })}

        <div class="signed-banner">
          ${iconSVG("check",14)}
          <span><strong>Signed by ${doctorName}</strong> · ${fmtDateTime(signedAt)} · Summary locked</span>
          <div style="flex:1"></div>
          <span class="mono" style="font-size:11px;opacity:.85">LOCKED · ${_pid}</span>
        </div>

        <div class="content">
          <!-- Billing team notification -->
          <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:10px 16px;margin-bottom:16px;display:flex;align-items:flex-start;gap:10px">
            <span style="font-size:16px;flex-shrink:0;margin-top:1px">ℹ️</span>
            <div style="flex:1">
              <div style="font-size:12.5px;font-weight:700;color:#1E40AF">Billing notified — CE4 populated with §8 (Procedures), §11 (Discharge Medications) &amp; §10 (Hospital Course) data from this summary.</div>
              <div style="font-size:12px;color:#1E40AF;margin-top:6px;display:flex;align-items:center;gap:12px">
                <span>Patient must settle balance before discharge.</span>
                <a href="/billing.html" target="_blank"
                   style="font-size:11.5px;font-weight:700;color:#1D4ED8;text-decoration:none;
                          border:1px solid #93C5FD;border-radius:6px;padding:3px 10px;
                          background:#DBEAFE;white-space:nowrap;flex-shrink:0">View CE4 →</a>
              </div>
            </div>
          </div>

          <div style="display:flex;align-items:flex-end;margin-bottom:18px">
            <div>
              <div class="eyebrow">Discharge Summary · Read-only</div>
              <div class="section-title" style="margin-top:6px">${patName}</div>
              <div class="mono" style="font-size:12px;color:var(--ink-3);margin-top:2px">
                ${_pid} · ${fmtDate(adm.admittime)} → ${fmtDate(adm.dischtime)}
              </div>
            </div>
            <div style="flex:1"></div>
            <div class="hstack" style="gap:10px">
              <button class="btn btn-outline" id="signed-back">${iconSVG("chevL",13)} Back to Queue</button>
            </div>
          </div>

          <!-- ── Main summary card ── -->
          <div class="card" style="padding:40px 52px;max-width:860px;margin:0 auto;box-shadow:var(--shadow-lg)">
            <!-- Letterhead -->
            <div style="display:flex;align-items:center;gap:18px;padding-bottom:20px;border-bottom:2px solid var(--navy);margin-bottom:24px">
              <div style="width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#800080,#C040C0);display:grid;place-items:center;flex-shrink:0;box-shadow:0 4px 14px rgba(128,0,128,.4)">
                <span style="font-size:13px;font-weight:900;color:white;letter-spacing:.02em">FQ</span>
              </div>
              <div style="flex:1">
                <div style="font-size:18px;font-weight:800;color:var(--navy);letter-spacing:-.02em">Foqal Healthcare</div>
                <div style="font-size:11px;color:var(--ink-4);margin-top:2px">Cardiac &amp; Surgical Wing · Chennai, Tamil Nadu</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.10em;color:var(--navy)">Discharge Summary</div>
                <div style="font-size:10.5px;color:var(--ink-4);margin-top:3px;font-family:var(--mono)">${_pid} · ${version}</div>
              </div>
            </div>
            <!-- Patient strip -->
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;padding:14px 18px;background:var(--bg);border-radius:var(--r-sm);border:1px solid var(--border);margin-bottom:28px">
              ${[["Patient",patName],["Patient ID",_pid],["Admitted",fmtDate(adm.admittime)],["Discharged",fmtDate(adm.dischtime)]].map(([k,v])=>`
                <div>
                  <div style="font-size:9.5px;font-weight:700;color:var(--ink-5);text-transform:uppercase;letter-spacing:.12em;margin-bottom:3px">${k}</div>
                  <div style="font-size:13px;font-weight:600;color:var(--ink)">${v}</div>
                </div>`).join("")}
            </div>

            ${bodyHTML}

            <!-- Signature block -->
            <div style="margin-top:48px;border-top:2px solid var(--navy);padding-top:20px;display:flex;justify-content:space-between;align-items:flex-end">
              <div>
                <div style="font-size:11px;color:var(--ink-3);margin-bottom:6px">Authorised &amp; Signed by</div>
                ${rd.signatureMode === "draw" && rd.signatureData
                  ? `<img src="${rd.signatureData}" style="height:60px;display:block;border-bottom:1px solid var(--navy);padding-bottom:4px;min-width:220px"/>`
                  : `<div style="font-family:'Caveat',cursive;font-size:30px;color:var(--navy);border-bottom:1px solid var(--navy);padding-bottom:4px;min-width:220px">${doctorName}</div>`
                }
                <div style="font-size:12px;font-weight:600;margin-top:6px">${doctorName}</div>
                <div style="font-size:11px;color:var(--ink-3)">Attending Physician · Foqal Healthcare</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:11px;color:var(--ink-3)">Date &amp; Time of Sign-off</div>
                <div style="font-size:12px;font-weight:600;margin-top:4px">${fmtDateTime(signedAt)}</div>
              </div>
            </div>

            <!-- Signature Metadata (S6) -->
            <div style="margin-top:24px;padding:14px 18px;background:#F8FAFC;border:1px solid var(--border);border-radius:8px">
              <div style="font-size:10.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px">Signature Metadata</div>
              <div style="display:grid;grid-template-columns:120px 1fr;gap:5px 12px;font-size:12.5px">
                <span style="color:var(--muted)">Signed by</span>   <span style="color:var(--ink);font-weight:600">${doctorName}</span>
                <span style="color:var(--muted)">Registration</span> <span style="color:var(--ink)">${doctorReg}</span>
                <span style="color:var(--muted)">Timestamp</span>    <span style="color:var(--ink);font-family:var(--mono);font-size:11.5px">${new Date(signedAt).toISOString()}</span>
                <span style="color:var(--muted)">Version</span>      <span style="color:var(--ink)">${version} — Original</span>
                <span style="color:var(--muted)">Hash</span>         <span style="color:var(--ink);font-family:var(--mono);font-size:11px">${shortHash}</span>
              </div>
            </div>
          </div>

          <!-- ── S6 PDF actions card ── -->
          <div class="card" style="max-width:860px;margin:16px auto 0;padding:20px 24px">
            <div style="font-size:12.5px;font-weight:700;color:var(--ink);margin-bottom:14px;display:flex;align-items:center;gap:8px">
              <span style="font-size:18px">📄</span>
              Signed PDF — ${version}
            </div>
            <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;background:#F8FAFC;border:1px solid var(--border);border-radius:8px;margin-bottom:14px">
              <span style="font-size:24px">📄</span>
              <div style="flex:1">
                <div style="font-size:13px;font-weight:600;color:var(--ink)">${pdfName}</div>
                <div style="font-size:11.5px;color:var(--muted);margin-top:2px">2.4 MB · 18 pages · NABH Compliant</div>
              </div>
            </div>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button id="signed-download-pdf" class="btn btn-navy" style="display:flex;align-items:center;gap:6px">⬇ Download PDF</button>
              <button id="signed-hl7" class="btn btn-outline" style="display:flex;align-items:center;gap:6px">🔗 HL7 Share</button>
              <button id="signed-print" class="btn btn-outline" style="display:flex;align-items:center;gap:6px">🖨 Print</button>
            </div>
          </div>

          <!-- ── Amendment action row ── -->
          <div style="max-width:860px;margin:12px auto 32px;display:flex;gap:10px;flex-wrap:wrap">
            <button id="signed-amend" class="btn btn-outline" style="display:flex;align-items:center;gap:6px;border-color:#F97316;color:#C2410C">📝 Request Amendment →</button>
          </div>

          <div style="text-align:center;margin-top:0;margin-bottom:24px;font-size:11px;color:var(--ink-3)">
            This document is system-generated, doctor-verified and digitally signed.
          </div>
        </div>
      </div>
    </div>
    ${renderHl7Modal(hadmId, patName, signedAt)}`;
};

SCREEN_SETUP["signed"] = function setupSigned() {
  document.getElementById("signed-back")?.addEventListener("click", () => navigate("doctor-queue"));

  document.getElementById("signed-download-pdf")?.addEventListener("click", () => {
    window.print();
  });

  document.getElementById("signed-print")?.addEventListener("click", () => {
    window.print();
  });

  document.getElementById("signed-hl7")?.addEventListener("click", () => {
    _signedHl7Open = true;
    _signedHl7Copied = false;
    renderApp();
    setTimeout(() => {
      document.getElementById("hl7-close")?.addEventListener("click",  () => { _signedHl7Open = false; renderApp(); });
      document.getElementById("hl7-close2")?.addEventListener("click", () => { _signedHl7Open = false; renderApp(); });
      document.getElementById("hl7-overlay")?.addEventListener("click", e => {
        if (e.target.id === "hl7-overlay") { _signedHl7Open = false; renderApp(); }
      });
      document.getElementById("hl7-copy")?.addEventListener("click", async () => {
        const pre = document.querySelector("#hl7-overlay pre");
        if (pre) {
          try { await navigator.clipboard.writeText(pre.textContent); } catch(e) {}
          _signedHl7Copied = true;
          renderApp();
        }
      });
    }, 60);
  });

  document.getElementById("signed-amend")?.addEventListener("click", () => {
    navigate("amendment");
  });

};

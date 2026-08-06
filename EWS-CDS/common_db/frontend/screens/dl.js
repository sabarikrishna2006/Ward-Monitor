// Screen — Drug-Lab Interaction Review (Module D, dl1)

let _dl = { loading: false, result: null, error: null };

const _DL_BACK_SCREEN = () => APP.prevScreen === "review" ? "review" : "doctor-dashboard";

SCREEN_RENDERERS["dl1"] = function renderDL1() {
  const user  = getUser();
  const enc    = APP.dlEncounter;
  const hadmId = enc?.hadm_id || enc?.hadmId;
  const _pid   = fmtPid(hadmId, enc?.display_id);

  // Synthetic name helper (same seed as doctor-dashboard)
  function _dlSynthName(id) {
    let h = parseInt(id) || 0;
    h = ((h >> 16) ^ h) * 0x45d9f3b; h = ((h >> 16) ^ h) * 0x45d9f3b; h = (h >> 16) ^ h;
    const isMale = Math.abs(h) % 2 === 0;
    const M = ['Rajesh Kumar','Mohan Singh','Dinesh Joshi','Arun Verma','Suresh Patel','Vijay Malhotra','Sanjay Gupta','Ramesh Sharma','Deepak Rao','Nitin Jain'];
    const F = ['Priya Sharma','Kavita Patel','Sunita Rao','Anjali Desai','Leela Varma','Rekha Devi','Suman Jain','Anita Gupta','Meena Singh','Geeta Mehta'];
    const arr = isMale ? M : F;
    return arr[Math.abs(h) % arr.length];
  }

  const patName = enc ? _dlSynthName(hadmId) : "Unknown Patient";

  const SHELL_STYLE  = "display:flex;flex-direction:column;min-height:100vh;background:#f8f5ff;font-family:inherit";
  const MAIN_WRAP   = "max-width:860px;margin:0 auto;padding:28px 24px 48px";
  const CARD_BASE   = "background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:20px 24px;margin-bottom:16px";

  // Header bar
  const header = `
    <div style="background:#0A000A;border-bottom:1px solid #2A002A;padding:12px 24px;display:flex;align-items:center;gap:14px">
      <button id="dl-back-btn" style="display:flex;align-items:center;gap:6px;background:rgba(128,0,128,.18);border:1px solid rgba(192,64,192,.3);color:#D090D0;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit">
        ← Back
      </button>
      <div style="flex:1">
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:#603060;font-weight:800">Module D — Drug-Lab Interaction Engine</div>
        <div style="font-size:15px;font-weight:800;color:#F0D8F0;margin-top:1px">${patName} · ${_pid || "—"}</div>
      </div>
      <div style="font-size:11px;color:#7A5A7A">Powered by CSI / ESC / CDSCO guidelines</div>
    </div>`;

  // Loading state
  if (_dl.loading) {
    return `<div style="${SHELL_STYLE}">${header}<div style="${MAIN_WRAP}">
      <div style="display:flex;align-items:center;gap:12px;margin-top:32px;color:#6b7280">
        <div style="width:20px;height:20px;border:3px solid #e5e7eb;border-top-color:#800080;border-radius:50%;animation:dlSpin .8s linear infinite;flex-shrink:0"></div>
        Checking drug-lab interactions…
      </div></div></div>`;
  }

  // Error state
  if (_dl.error) {
    return `<div style="${SHELL_STYLE}">${header}<div style="${MAIN_WRAP}">
      <div style="${CARD_BASE};border-color:#fca5a5;background:#fef2f2;margin-top:24px">
        <div style="font-size:13px;font-weight:700;color:#dc2626;margin-bottom:6px">Failed to load drug-lab data</div>
        <div style="font-size:12px;color:#6b7280">${_dl.error}</div>
        <button id="dl-retry-btn" style="margin-top:12px;padding:6px 14px;background:#dc2626;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">Retry</button>
      </div></div></div>`;
  }

  // No data yet (shouldn't normally reach here, but guard)
  if (!_dl.result) {
    return `<div style="${SHELL_STYLE}">${header}<div style="${MAIN_WRAP}">
      <div style="${CARD_BASE};margin-top:24px;color:#6b7280;font-size:13px">No data loaded. Please go back and click DL again.</div>
    </div></div>`;
  }

  const res = _dl.result;
  const alerts = res.alerts || [];
  const criticals = alerts.filter(a => a.severity === "CRITICAL");
  const warnings  = alerts.filter(a => a.severity === "WARNING");

  // Summary banner
  const bannerColor = criticals.length > 0 ? "#dc2626" : warnings.length > 0 ? "#d97706" : "#059669";
  const bannerBg    = criticals.length > 0 ? "#fef2f2" : warnings.length > 0 ? "#fffbeb" : "#f0fdf4";
  const bannerBorder= criticals.length > 0 ? "#fca5a5" : warnings.length > 0 ? "#fde68a" : "#bbf7d0";
  const bannerIcon  = criticals.length > 0 ? "⛔" : warnings.length > 0 ? "⚠" : "✓";
  const bannerText  = alerts.length === 0
    ? "No drug-lab interactions detected for this patient."
    : `${alerts.length} interaction${alerts.length > 1 ? "s" : ""} detected — ${criticals.length} critical, ${warnings.length} warning`;

  const summaryBanner = `
    <div style="background:${bannerBg};border:1px solid ${bannerBorder};border-radius:10px;padding:14px 18px;margin-bottom:20px;display:flex;align-items:center;gap:14px;margin-top:24px">
      <div style="font-size:22px">${bannerIcon}</div>
      <div style="flex:1">
        <div style="font-size:14px;font-weight:700;color:${bannerColor}">${bannerText}</div>
        <div style="font-size:11px;color:#6b7280;margin-top:3px">
          Checked ${res.med_count || 0} medications · ${Object.keys(res.checked_labs || {}).length} lab values
          ${res.checked_labs ? ' · Labs: ' + Object.entries(res.checked_labs).map(([k,v]) => `${k}=${v}`).join(', ') : ''}
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0">
        <span style="background:#fef2f2;color:#dc2626;border:1px solid #fecaca;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:700">CRITICAL: ${criticals.length}</span>
        <span style="background:#fffbeb;color:#d97706;border:1px solid #fde68a;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:700">WARNING: ${warnings.length}</span>
      </div>
    </div>`;

  // Alert cards
  function renderAlert(a, idx) {
    const isCrit = a.severity === "CRITICAL";
    const accentColor = isCrit ? "#dc2626" : "#d97706";
    const softBg      = isCrit ? "#fef2f2" : "#fffbeb";
    const borderColor = isCrit ? "#fca5a5" : "#fde68a";
    const badgeBg     = isCrit ? "#dc2626" : "#d97706";
    const meds = (a.triggering_meds || []).slice(0, 8).join(", ") || "—";
    return `
      <div style="background:#fff;border:1px solid ${borderColor};border-left:4px solid ${accentColor};border-radius:10px;padding:18px 20px;margin-bottom:14px">
        <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:12px">
          <span style="background:${badgeBg};color:#fff;font-size:10px;font-weight:800;padding:3px 9px;border-radius:20px;white-space:nowrap;flex-shrink:0;letter-spacing:.06em">${a.severity}</span>
          <div style="font-size:13.5px;font-weight:700;color:#111827;line-height:1.3">${a.name || ""}</div>
        </div>
        <div style="background:${softBg};border-radius:7px;padding:10px 14px;margin-bottom:12px">
          <div style="font-size:12.5px;color:${accentColor};font-weight:600;line-height:1.5">${a.message || ""}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div>
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#9ca3af;letter-spacing:.08em;margin-bottom:3px">Triggering Lab</div>
            <div style="font-size:12.5px;color:#374151;font-weight:600">${a.lab_name || a.trigger?.lab || "—"} = <span style="color:${accentColor}">${a.lab_value != null ? a.lab_value : "—"}</span></div>
          </div>
          <div>
            <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#9ca3af;letter-spacing:.08em;margin-bottom:3px">Matching Medications</div>
            <div style="font-size:12px;color:#374151">${meds}</div>
          </div>
        </div>
        <div style="border-top:1px solid #f3f4f6;padding-top:10px">
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;color:#9ca3af;letter-spacing:.08em;margin-bottom:5px">Recommended Action</div>
          <div style="font-size:12.5px;color:#1f2937;line-height:1.6">${a.action || "—"}</div>
          ${a.guideline ? `<div style="margin-top:6px;font-size:10.5px;color:#6b7280;font-style:italic">Reference: ${a.guideline}</div>` : ""}
        </div>
      </div>`;
  }

  const alertHTML = alerts.length === 0
    ? `<div style="${CARD_BASE};text-align:center;padding:48px;color:#6b7280">
         <div style="font-size:32px;margin-bottom:10px">✅</div>
         <div style="font-size:15px;font-weight:700;color:#059669;margin-bottom:4px">No interactions detected</div>
         <div style="font-size:13px">No drug-lab interaction rules were triggered for this patient's current medications and lab results.</div>
       </div>`
    : `<div style="margin-top:4px">
         ${criticals.length > 0 ? `<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#dc2626;letter-spacing:.1em;margin-bottom:8px">Critical Alerts</div>${criticals.map(renderAlert).join("")}` : ""}
         ${warnings.length > 0 ? `<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#d97706;letter-spacing:.1em;margin-bottom:8px;${criticals.length>0?"margin-top:20px":""}">Warnings</div>${warnings.map(renderAlert).join("")}` : ""}
       </div>`;

  return `
    <style>@keyframes dlSpin{to{transform:rotate(360deg)}}</style>
    <div style="${SHELL_STYLE}">
      ${header}
      <div style="${MAIN_WRAP}">
        ${summaryBanner}
        ${alertHTML}
      </div>
    </div>`;
};

SCREEN_SETUP["dl1"] = function setupDL1() {
  // Back button
  document.getElementById("dl-back-btn")?.addEventListener("click", () => {
    navigate(_DL_BACK_SCREEN());
  });

  // Retry button
  document.getElementById("dl-retry-btn")?.addEventListener("click", () => {
    _dl.error = null;
    _dl.result = null;
    _dlLoad();
  });

  // Kick off load if not already loaded for this patient
  const hadmId = APP.dlEncounter?.hadm_id || APP.dlEncounter?.hadmId;
  if (!_dl.loading && (_dl.result === null || _dl.result?.hadm_id !== hadmId)) {
    _dlLoad();
  }
};

async function _dlLoad() {
  const hadmId = APP.dlEncounter?.hadm_id || APP.dlEncounter?.hadmId;
  if (!hadmId) {
    _dl.error = "No encounter selected.";
    renderApp();
    return;
  }
  _dl.loading = true;
  _dl.error   = null;
  renderApp();
  try {
    const res = await fetchDLCheck(hadmId);
    if (!res) throw new Error("No response from server.");
    _dl.result  = res;
    _dl.loading = false;
  } catch (e) {
    _dl.error   = e.message || "Unknown error";
    _dl.loading = false;
  }
  renderApp();
}

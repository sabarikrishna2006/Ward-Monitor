// ── Foqal CareOS — central service config ─────────────────────────────────────
// Change ports HERE ONLY. Every HTML/JS file reads from this one place.
window.FOQAL_CONFIG = {
  API_PORT:    4002,   // main FastAPI backend
  DATA_PORT:   4003,   // data server (BigQuery / MIMIC tabs)
  WARD_PORT:   8006,   // Sabari ward monitor backend
  FE_PORT:     5180,   // Ashmit Vite dev server
  SABARI_PORT: 5175,   // Sabari Vite dev server
};
const _h = location.hostname;
window.FOQAL_API_BASE  = `http://${_h}:${window.FOQAL_CONFIG.API_PORT}`;
window.FOQAL_DATA_BASE = `http://${_h}:${window.FOQAL_CONFIG.DATA_PORT}`;

// ── Patient ID formatter ───────────────────────────────────────────────────────
// Uses display_id from encounter (e.g. PT-24-0087) when available.
// Falls back to HADM-XXXXXXX for backward compatibility.
window.fmtPid = function(hadmId, displayId) {
  return displayId || ('HADM-' + hadmId);
};

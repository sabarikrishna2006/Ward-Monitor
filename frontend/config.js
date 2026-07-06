// ── Foqal CareOS — central service config ─────────────────────────────────────
// Change ports HERE ONLY. Every HTML/JS file reads from this one place.
window.FOQAL_CONFIG = {
  API_PORT:    6010,   // main FastAPI backend (local dev)
  DATA_PORT:   6020,   // data server (local dev)
  WARD_PORT:   6030,   // Sabari ward monitor backend
  FE_PORT:     6000,   // Ashmit Vite dev server
  SABARI_PORT: 6040,   // Sabari Vite dev server
};
const _h = location.hostname;
window.FOQAL_API_BASE  = `http://${_h}:${window.FOQAL_CONFIG.API_PORT}`;
window.FOQAL_DATA_BASE = `http://${_h}:${window.FOQAL_CONFIG.DATA_PORT}`;
window.FOQAL_WARD_BASE = `http://${_h}:${window.FOQAL_CONFIG.WARD_PORT}`;

// ── Patient ID formatter ───────────────────────────────────────────────────────
// Always PT-{hadm_id} — the real hospital admission ID, not the internal
// sequential display_id counter, so it stays identical to what was used at
// GW/billing admission.
window.fmtPid = function(hadmId, displayId) {
  return 'PT-' + hadmId;
};

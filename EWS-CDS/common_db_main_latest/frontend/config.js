// Change ports HERE ONLY. Every HTML/JS file reads from this one place.
// Auto-detect environment based on port or hostname to support both Local Dev and Production Server without code changes.
const isLocalDev = ['4990', '4985'].includes(location.port) || location.hostname === 'localhost' || location.hostname === '127.0.0.1';

window.FOQAL_CONFIG = isLocalDev ? {
  API_PORT:    7015,   // main FastAPI backend (local dev)
  DATA_PORT:   7016,   // data server (local dev)
  WARD_PORT:   7816,   // Sabari ward monitor backend (local dev)
  FE_PORT:     4990,   // Ashmit Vite dev server (local dev)
  SABARI_PORT: 4985,   // Sabari Vite dev server (local dev)
} : {
  API_PORT:    6010,   // main FastAPI backend (production server)
  DATA_PORT:   6020,   // data server (production server)
  WARD_PORT:   6030,   // Sabari ward monitor backend (production server)
  FE_PORT:     6001,   // Ashmit Vite dev server (production server)
  SABARI_PORT: 6040,   // Sabari Vite dev server (production server)
};



const _h = location.hostname;
window.FOQAL_API_BASE  = `http://${_h}:${window.FOQAL_CONFIG.API_PORT}`;
window.FOQAL_DATA_BASE = `http://${_h}:${window.FOQAL_CONFIG.DATA_PORT}`;
window.FOQAL_WARD_BASE = `http://${_h}:${window.FOQAL_CONFIG.WARD_PORT}`;


// Patient id formatter
window.fmtPid = function(hadmId, displayId) {
  return 'PT-' + hadmId;
};

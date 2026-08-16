// Change ports HERE ONLY. Every HTML/JS file reads from this one place.
window.FOQAL_CONFIG = {
  API_PORT:    6017,   // main FastAPI backend (local dev)
  DATA_PORT:   6027,   // data server (local dev)
  WARD_PORT:   6037,   // Sabari ward monitor backend
  FE_PORT:     6008,   // Ashmit Vite dev server
  SABARI_PORT: 6047,   // Sabari Vite dev server
};



const _h = location.hostname;
window.FOQAL_API_BASE  = `http://${_h}:${window.FOQAL_CONFIG.API_PORT}`;
window.FOQAL_DATA_BASE = `http://${_h}:${window.FOQAL_CONFIG.DATA_PORT}`;
window.FOQAL_WARD_BASE = `http://${_h}:${window.FOQAL_CONFIG.WARD_PORT}`;


// Patient id formatter
window.fmtPid = function(hadmId, displayId) {
  return 'PT-' + hadmId;
};

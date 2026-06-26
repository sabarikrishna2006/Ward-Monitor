// API Client — split backend architecture
// UI Server  (port 8001): auth, encounters CRUD, generate summary, settings
// Data Server (port 8002): patient data, lazy tabs, MIMIC browse, caching
// On server: data calls go through /data-proxy/ on port 8001 (8002 may be firewalled)

const _local    = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE  = (window.FOQAL_API_BASE)  || `http://${location.hostname}:7005`;
const DATA_BASE = _local
  ? ((window.FOQAL_DATA_BASE) || `http://${location.hostname}:7006`)
  : `${API_BASE}/data-proxy`;
// Expose for SPA screen scripts that can't import modules
window.API_BASE  = API_BASE;
window.DATA_BASE = DATA_BASE;

async function _api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API_BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────
async function apiLogin(hospital_email, password, role) {
  return _api("POST", "/api/auth/login", { hospital_email, password, role });
}
async function apiRegister(fields) {
  return _api("POST", "/api/auth/register", fields);
}
async function apiForgotPassword(hospital_email) {
  return _api("POST", "/api/auth/forgot-password", { hospital_email });
}
async function apiResetPassword(email, token, new_password) {
  return _api("POST", "/api/auth/reset-password", { email, token, new_password });
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
async function fetchDashboardStats() {
  const data = await _api("GET", "/api/dashboard");
  return data.cards ?? data;
}

// ── Encounters ────────────────────────────────────────────────────────────────
async function fetchEncounters(params = {}) {
  const qs = Object.entries(params).filter(([,v]) => v != null).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return _api("GET", `/api/encounters${qs ? "?" + qs : ""}`);
}
async function fetchSummaries() {
  return _api("GET", "/api/summaries");
}
async function fetchEncounterByHadm(hadm_id) {
  return _api("GET", `/api/encounters/${hadm_id}/encounter`).catch(() => null);
}
async function createEncounter(hadm_id, full_name, ward, admission_date, assigned_doctor_id) {
  return _api("POST", "/api/encounters", { hadm_id, full_name, ward, admission_date, assigned_doctor_id });
}
async function updateEncounter(encounter_id, fields) {
  return _api("PATCH", `/api/encounters/${encounter_id}`, fields);
}

// ── Summaries ─────────────────────────────────────────────────────────────────
async function fetchSummary(encounter_id) {
  return _api("GET", `/api/encounters/${encounter_id}/summary`).catch(() => null);
}
async function updateSummary(encounter_id, fields) {
  return _api("PATCH", `/api/summaries/${encounter_id}`, fields);
}

async function fetchDLCheck(hadm_id) {
  return _api("GET", `/api/encounters/${hadm_id}/dl_check`).catch(() => null);
}
async function fetchSummaryVersions(encounter_id) {
  return _api("GET", `/api/summaries/${encounter_id}/versions`).catch(() => []);
}
async function fetchSummaryVersion(version_id) {
  return _api("GET", `/api/summaries/versions/${version_id}`).catch(() => null);
}

// ── Patient data (BigQuery → Cloud SQL) — served by data server ──────────────
async function fetchPatientData(hadm_id, source) {
  // Route through UI server so encounter metadata gets merged in
  const qs = source ? `?source=${source}` : "";
  return _api("GET", `/api/encounters/${hadm_id}/patient_data${qs}`);
}

async function fetchLazyTab(hadm_id, tab_name) {
  const res = await fetch(`${DATA_BASE}/api/patient/${hadm_id}/tab/${tab_name}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function fetchCachedPatients() {
  return _api("GET", "/api/cache/patients").catch(() => ({ active: [] }));
}

// ── Uploaded files ────────────────────────────────────────────────────────────
async function fetchUploadedFiles(encounter_id) {
  return _api("GET", `/api/encounters/${encounter_id}/files`);
}
async function fetchUploadedClinicalData(hadm_id) {
  return _api("GET", `/api/encounters/${hadm_id}/uploaded_clinical_data`).catch(() => ({}));
}
async function deleteUploadedFile(file_id, file_type, hadm_id) {
  return fetch(`${API_BASE}/api/uploaded_files/${file_id}?file_type=${encodeURIComponent(file_type)}&hadm_id=${hadm_id}`, { method: "DELETE" }).then(r => r.json());
}

// ── Users ──────────────────────────────────────────────────────────────────────
async function fetchDoctors() {
  return _api("GET", "/api/users/doctors");
}
async function fetchUsers() {
  return _api("GET", "/api/users");
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function fetchSettings() {
  return _api("GET", "/api/settings");
}
async function saveSettings(fields) {
  return _api("PATCH", "/api/settings", fields);
}

// ── Audit log ─────────────────────────────────────────────────────────────────
async function fetchAuditLog(limit = 15) {
  return _api("GET", `/api/audit_log?limit=${limit}`);
}

// ── HADM IDs ──────────────────────────────────────────────────────────────────
async function fetchHadmIds() {
  return _api("GET", "/api/hadm_ids");
}
async function fetchMimicAdmissions(page = 1, perPage = 20, search = "") {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), 30000);
  try {
    const res = await fetch(
      `${DATA_BASE}/api/mimic/admissions?page=${page}&per_page=${perPage}&search=${encodeURIComponent(search)}`,
      { signal: ctrl.signal }
    );
    clearTimeout(tid);
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  } catch (e) {
    clearTimeout(tid);
    if (e.name === "AbortError") throw new Error("Data server not ready — restart it and try again");
    throw e;
  }
}

// ── Generate summary ──────────────────────────────────────────────────────────
async function generateSummary(hadm_id, source = "bq") {
  return fetch(`${API_BASE}/api/encounters/${hadm_id}/generate_summary?source=${source}`, { method: "POST" }).then(r => r.json());
}

// ── Regenerate single section based on doctor feedback ────────────────────────
async function apiRegenerateSection(hadm_id, section_id, section_label, doctor_feedback, current_text) {
  return _api("POST", `/api/encounters/${hadm_id}/regenerate_section`, {
    section_id, section_label, doctor_feedback, current_text,
  });
}

// ── Global exports ────────────────────────────────────────────────────────────
window.apiLogin                = apiLogin;
window.apiRegister             = apiRegister;
window.apiForgotPassword       = apiForgotPassword;
window.apiResetPassword        = apiResetPassword;
window.fetchDashboardStats     = fetchDashboardStats;
window.fetchEncounters         = fetchEncounters;
window.fetchSummaries          = fetchSummaries;
window.fetchEncounterByHadm    = fetchEncounterByHadm;
window.createEncounter         = createEncounter;
window.updateEncounter         = updateEncounter;
window.fetchSummary            = fetchSummary;
window.updateSummary           = updateSummary;
window.fetchDLCheck            = fetchDLCheck;
window.fetchSummaryVersions    = fetchSummaryVersions;
window.fetchSummaryVersion     = fetchSummaryVersion;
window.fetchPatientData        = fetchPatientData;
window.fetchLazyTab            = fetchLazyTab;
window.fetchUploadedFiles          = fetchUploadedFiles;
window.fetchUploadedClinicalData   = fetchUploadedClinicalData;
window.deleteUploadedFile          = deleteUploadedFile;
window.fetchDoctors            = fetchDoctors;
window.fetchUsers              = fetchUsers;
window.fetchSettings           = fetchSettings;
window.saveSettings            = saveSettings;
window.fetchAuditLog           = fetchAuditLog;
window.fetchHadmIds            = fetchHadmIds;
window.fetchMimicAdmissions    = fetchMimicAdmissions;
window.fetchCachedPatients     = fetchCachedPatients;
async function apiSendRevision(hadm_id, reason) {
  return _api("POST", `/api/encounters/${hadm_id}/send_revision`, { reason });
}

// ── Error Log (3-Tier Accuracy Framework) ─────────────────────────────────────
async function apiLogError(fields) {
  return _api("POST", "/api/errors", fields).catch(() => null);
}
async function apiGetErrorStats() {
  return _api("GET", "/api/errors/stats").catch(() => ({ tier3_count: 0, total_errors: 0, tier3_rate_pct: 0, by_tier: [], by_section: [] }));
}
async function apiSubmitUsabilityRating(fields) {
  return _api("POST", "/api/usability_rating", fields).catch(() => null);
}
async function apiGetUsabilityStats() {
  return _api("GET", "/api/usability_rating/stats").catch(() => ({ total_ratings: 0, avg_rating: 0, distribution: {}, target: 4.0 }));
}
async function apiGetPromptVersionLog() {
  return _api("GET", "/api/prompt_version_log").catch(() => ({ versions: [] }));
}
async function apiGetDemoCases() {
  return _api("GET", "/api/demo/cases").catch(() => ({ cases: [] }));
}

window.generateSummary             = generateSummary;
window.apiRegenerateSection        = apiRegenerateSection;
window.apiSendRevision             = apiSendRevision;
window.apiLogError                 = apiLogError;
window.apiGetErrorStats            = apiGetErrorStats;
window.apiSubmitUsabilityRating    = apiSubmitUsabilityRating;
window.apiGetUsabilityStats        = apiGetUsabilityStats;
window.apiGetPromptVersionLog      = apiGetPromptVersionLog;
window.apiGetDemoCases             = apiGetDemoCases;

// ── Medication localization  (US MIMIC names → Indian brand names) ─────────────
// Results cached in sessionStorage so the LLM is only called once per session
// per unique drug name.
const _MED_LOC_STORE_KEY = "foqal_drug_map";

function _getMedCache() {
  try { return JSON.parse(sessionStorage.getItem(_MED_LOC_STORE_KEY) || "{}"); }
  catch { return {}; }
}
function _setMedCache(map) {
  try { sessionStorage.setItem(_MED_LOC_STORE_KEY, JSON.stringify(map)); } catch {}
}

/**
 * Localize an array of raw US drug name strings to Indian brand names.
 * Returns a plain object: { "ASPIRIN": "Ecosprin", ... }
 * Cached in sessionStorage; unknown names fall back to the original.
 */
async function localizeMeds(drugNames) {
  if (!drugNames || !drugNames.length) return {};
  const cache   = _getMedCache();
  const missing = [...new Set(drugNames.filter(n => n && n !== "—" && !cache[n]))];

  if (missing.length) {
    try {
      const res  = await fetch(`${API_BASE}/api/localize/medications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ drugs: missing }),
      });
      if (res.ok) {
        const { mapping } = await res.json();
        Object.assign(cache, mapping);
        _setMedCache(cache);
      }
    } catch { /* network down — fall through to cache/raw names */ }
  }

  const result = {};
  for (const n of drugNames) {
    result[n] = (n && cache[n]) ? cache[n] : (n || "—");
  }
  return result;
}

window.localizeMeds = localizeMeds;

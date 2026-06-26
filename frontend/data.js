// Mock clinical data — realistic for an Indian hospital discharge context

// Encounters queue (Admin)
const ADMIN_ENCOUNTERS = [
  { pid: "HADM 24181354", date: "16 Mar 2026", ward: "Cardiac",  complexity: "High",   status: "review",           doctor: "Dr. A. Mehta" },
  { pid: "HADM 24180921", date: "16 Mar 2026", ward: "Surgical", complexity: "Medium", status: "awaiting_confirm",  doctor: "Dr. R. Iyer"  },
  { pid: "HADM 24180764", date: "15 Mar 2026", ward: "ICU",      complexity: "High",   status: "ready",            doctor: "Dr. A. Mehta" },
  { pid: "HADM 24180510", date: "15 Mar 2026", ward: "General",  complexity: "Low",    status: "signed",           doctor: "Dr. S. Kapoor" },
  { pid: "HADM 24180488", date: "15 Mar 2026", ward: "OMED",     complexity: "Medium", status: "verifying",        doctor: "Dr. R. Iyer" },
  { pid: "HADM 24180271", date: "14 Mar 2026", ward: "ICU",      complexity: "High",   status: "incomplete",       doctor: "—" },
];

const STATUS_MAP = {
  pending:          { label: "Data being ingested",    cls: "pill-blue",   animated: true },
  processing:       { label: "Data being ingested",    cls: "pill-blue",   animated: true },
  uploading:        { label: "Uploading",              cls: "pill-blue",   animated: true },
  ingesting:        { label: "Ingesting",              cls: "pill-blue",   animated: true },
  chunking:         { label: "Chunking & Indexing",    cls: "pill-blue",   animated: true },
  indexed:          { label: "Indexed",                cls: "pill-slate" },
  awaiting_confirm: { label: "Awaiting Confirmation",  cls: "pill-orange" },
  generating:       { label: "Generating Summary",     cls: "pill-blue",   animated: true },
  verifying:        { label: "Verifying Claims",       cls: "pill-blue",   animated: true },
  review:           { label: "Awaiting Review",        cls: "pill-amber" },
  sent_for_review:    { label: "Sent for Review",     cls: "pill-teal"  },
  summary_generated:  { label: "Summary Generated",   cls: "pill-green" },
  incomplete:         { label: "Data Incomplete",      cls: "pill-red" },
  signed:              { label: "Signed Off",           cls: "pill-green" },
  ready:               { label: "Ready for Review",    cls: "pill-teal"  },
  revision_requested:  { label: "Returned for Revision", cls: "pill-red" },
};

// Doctor review queue
const DOCTOR_QUEUE = [
  { pid: "HADM 24181354", name: "Patel, Rohan",   ward: "Cardiac",  submitted: "16 Mar · 09:42", complexity: "High",   verified: 141, needs: 4, failed: 3, total: 148, active: true  },
  { pid: "HADM 24180764", name: "Sharma, Anjali", ward: "ICU",      submitted: "15 Mar · 18:12", complexity: "High",   verified: 92,  needs: 2, failed: 0, total: 94 },
  { pid: "HADM 24180312", name: "Khan, Imran",    ward: "General",  submitted: "15 Mar · 11:30", complexity: "Medium", verified: 67,  needs: 1, failed: 0, total: 68 },
];

// === SCREEN 6: Claims (Discharge Medications + other section stubs) ===
// Each claim: id, text, status (v/a/r), chunkId (citation), reason (for red)
const CLAIMS_INITIAL = [
  {
    id: "c041",
    text: "Patient underwent laparoscopic cholecystectomy on 14 March 2026 under general anaesthesia, with no intra-operative complications.",
    status: "v", chunkId: "c041"
  },
  {
    id: "c043",
    text: "Discharge on Tab. Pantoprazole 40 mg, 1-0-0 (before breakfast) for 14 days.",
    status: "v", chunkId: "c043"
  },
  {
    id: "c047",
    text: "Discharge on Tab. Metoprolol 50 mg, 1-0-1 for 30 days; review blood pressure after one week.",
    status: "a", chunkId: "c047",
    reason: "Frequency notation differs: source uses BID (morning & night), summary uses 1-0-1 format. Semantically equivalent — please confirm notation is correct for your hospital discharge format."
  },
  {
    id: "c049",
    text: "Tab. Amoxicillin-Clavulanate 625 mg, 1-0-1 for 5 days; review wound healing on day 7.",
    status: "v", chunkId: "c049"
  },
  {
    id: "c052",
    text: "Patient is allergic to Penicillin.",
    status: "r", chunkId: "c052",
    reason: "Conflicting records: admission note documents NKDA confirmed by patient, but summary states penicillin allergy. A historical note from 2023 references a self-reported penicillin rash that was never formally recorded. Please verify allergy status directly with patient before signing."
  },
  {
    id: "c055",
    text: "Continue regular medications for hypertension and diabetes as previously prescribed by primary physician.",
    status: "r", chunkId: "c055",
    reason: "No prior medication list was provided at admission. This sentence is not supported by any uploaded record. Please verify with the patient or their GP, or remove from the summary."
  },
  {
    id: "c058",
    text: "Tab. Paracetamol 500 mg, SOS (max 4 doses / day) for post-operative pain.",
    status: "a", chunkId: "c058",
    reason: "Source prescription specifies SOS only if pain ≥ 4/10. Summary correctly states max 4 doses per day but omits the pain score condition. Core prescription details are correct — consider adding the pain threshold for completeness."
  }
];

// Source chunks (right panel + left panel highlighting)
const CHUNKS = {
  c041: {
    id: "c041",
    type: "Operative Note",
    section: "Hospital Course",
    timestamp: "14 Mar 2026, 11:20",
    author: "Dr. R. Iyer, Surgical Lead",
    text: "Patient taken up for elective laparoscopic cholecystectomy. GA induction uneventful. 4-port technique. Gallbladder dissected from liver bed without difficulty. No bile spill. Calot's triangle clear. Operative time 47 min. EBL <30 ml. Transferred to ward in stable condition.",
    highlight: "elective laparoscopic cholecystectomy",
    nli: { judge: "DeBERTa-v3", score: 0.94, status: "PASS" },
    tab: "progress"
  },
  c043: {
    id: "c043",
    type: "Medication Order",
    section: "Discharge Medications",
    timestamp: "16 Mar 2026, 14:18",
    author: "Dr. A. Mehta, Attending",
    text: "RX: Pantoprazole 40 mg PO\nFrequency: 1-0-0 (pre-breakfast)\nDuration: 14 days\nIndication: GI prophylaxis post-op\nApproved & e-signed.",
    highlight: "Pantoprazole 40 mg",
    nli: { judge: "DeBERTa-v3", score: 0.96, status: "PASS" },
    tab: "meds"
  },
  c047: {
    id: "c047",
    type: "Medication Order",
    section: "Discharge Medications",
    timestamp: "16 Mar 2026, 14:30",
    author: "Dr. A. Mehta, Attending",
    text: "RX: Metoprolol Succinate 50 mg PO\nFrequency: BID (morning & night)\nDuration: 30 days\nReview: BP at 1 week, titrate to target <130/80.",
    highlight: "Metoprolol Succinate 50 mg",
    nli: { judge: "DeBERTa-v3", score: 0.74, status: "REVIEW" },
    note: "Frequency uses BID notation in the order entry; the summary expresses it as 1-0-1. Semantically equivalent but flagged for confirmation.",
    tab: "meds"
  },
  c049: {
    id: "c049",
    type: "Medication Order",
    section: "Discharge Medications",
    timestamp: "16 Mar 2026, 14:32",
    author: "Dr. A. Mehta, Attending",
    text: "RX: Amoxicillin-Clavulanate 625 mg PO\nFrequency: 1-0-1\nDuration: 5 days\nReview: wound check on day 7.",
    highlight: "Amoxicillin-Clavulanate 625 mg",
    nli: { judge: "DeBERTa-v3", score: 0.92, status: "PASS" },
    tab: "meds"
  },
  c052: {
    id: "c052",
    type: "Allergy Record",
    section: "Allergies",
    timestamp: "12 Mar 2026, 08:05",
    author: "Nurse R. Joshi (admission)",
    text: "Admission allergy review:\n- NKDA (no known drug allergies) confirmed by patient.\n- Patient allergy band: blank.\n\n⚠ Conflict: A historical note from 2023 references a self-reported \"penicillin rash\" but no formal allergy was documented at this admission.",
    highlight: "NKDA (no known drug allergies)",
    nli: { judge: "DeBERTa-v3", score: 0.61, status: "REVIEW" },
    note: "Consider retrieving additional evidence from prior visits, or clarify with patient before sign-off.",
    tab: "progress"
  },
  c055: {
    id: "c055",
    type: "Past History",
    section: "Past Medical History",
    timestamp: "12 Mar 2026, 08:10",
    author: "Admission Resident",
    text: "Past history: Hypertension (5 years), Type 2 Diabetes Mellitus (3 years).\nHome medication list: NOT PROVIDED on admission.\nPatient advised to bring previous prescriptions at next OPD review.",
    highlight: "Home medication list: NOT PROVIDED on admission.",
    nli: { judge: "DeBERTa-v3", score: 0.58, status: "REVIEW" },
    note: "No prior medication list found in uploaded records — the discharge claim about 'continuing regular medications' lacks source grounding.",
    tab: "progress"
  },
  c058: {
    id: "c058",
    type: "Medication Order",
    section: "Discharge Medications",
    timestamp: "16 Mar 2026, 14:36",
    author: "Dr. A. Mehta, Attending",
    text: "RX: Paracetamol 500 mg PO\nFrequency: SOS — only if pain ≥ 4/10\nMax: 4 doses per 24 hr\nDuration: as required.",
    highlight: "SOS — only if pain ≥ 4/10",
    nli: { judge: "DeBERTa-v3", score: 0.63, status: "REVIEW" },
    note: "Summary expresses SOS as \"max 4 doses/day\" but the prescription is conditional on a pain score threshold.",
    tab: "meds"
  }
};

// Sections of the AI-generated summary (10 total, Discharge Medications expanded)
// Sections displayed in S4b review screen — NO tier/issues here; those are
// derived live from the LLM's sections_json output via getSectionTier().
const SUMMARY_SECTIONS = [
  { id: "pid",    title: "Patient Identification",  count: 6  },
  { id: "adm",    title: "Reason for Admission",    count: 4  },
  { id: "pmh",    title: "Past Medical History",    count: 8  },
  { id: "exam",   title: "Examination Findings",    count: 11 },
  { id: "inv",    title: "Investigations",          count: 22 },
  { id: "course", title: "Hospital Course",         count: 14 },
  { id: "proc",   title: "Procedures Performed",    count: 7  },
  { id: "meds",   title: "Discharge Medications",   count: 7,  expanded: true },
  { id: "fup",    title: "Follow-up Instructions",  count: 5  },
  { id: "advice", title: "Lifestyle Advice",        count: 4  },
];

// Maps each frontend section ID to the NABH section keys (s1–s15) that cover it.
// Worst tier among all mapped keys is used for the section badge.
const SEC_TO_NABH = {
  pid:    ["s1"],
  adm:    ["s2", "s3"],
  pmh:    ["s4"],
  exam:   ["s5"],
  inv:    ["s6", "s7"],
  course: ["s8", "s9"],
  proc:   ["s10"],
  meds:   ["s11"],
  fup:    ["s12", "s13"],
  advice: ["s14", "s15"],
};

// Primary NABH key for each frontend section (used as nabh_section in error_log).
const PRIMARY_NABH = {
  pid: "s1", adm: "s2", pmh: "s4", exam: "s5",
  inv: "s6", course: "s9", proc: "s10", meds: "s11",
  fup: "s12", advice: "s14",
};

// Derives tier + issues for a frontend section from live LLM sections_json.
// sectionsJson: the sections_json object from the summary API (keyed s1–s15).
// Each value is { text, confidence, tier, issues, passed } from Pass 2.
// Returns { tier, issues } — tier is the worst across all mapped NABH keys.
function getSectionTier(secId, sectionsJson) {
  if (!sectionsJson || typeof sectionsJson !== "object") return { tier: null, issues: [] };
  const nabhs   = SEC_TO_NABH[secId] || [];
  const tierRank = { T3: 3, T2: 2, T1: 1 };
  let worstTier = null;
  const allIssues = [];
  for (const key of nabhs) {
    const sec = sectionsJson[key];
    if (!sec || typeof sec !== "object") continue;
    const t = sec.tier || "T3";
    if (worstTier === null || (tierRank[t] || 0) > (tierRank[worstTier] || 0)) worstTier = t;
    if (Array.isArray(sec.issues)) allIssues.push(...sec.issues);
  }
  return { tier: worstTier, issues: allIssues };
}

window.SEC_TO_NABH        = SEC_TO_NABH;
window.PRIMARY_NABH       = PRIMARY_NABH;
window.getSectionTier     = getSectionTier;

// === Left panel: raw source per tab ===
const LEFT_SOURCES = {
  labs: [
    { id: "lab-1", title: "Complete Blood Count · 15 Mar 06:00",
      lines: ["Hb 12.4 g/dL (Ref 13–17)", "WBC 9.8 × 10³/µL (Ref 4–11)", "Platelets 248 × 10³/µL", "ESR 14 mm/hr"] },
    { id: "lab-2", title: "Renal Function · 15 Mar 06:00",
      lines: ["Urea 28 mg/dL", "Creatinine 0.9 mg/dL", "Na+ 138 / K+ 4.1 / Cl- 103 mEq/L", "eGFR 92 ml/min/1.73m²"] },
    { id: "lab-3", title: "Liver Function · 15 Mar 06:00",
      lines: ["Total Bilirubin 0.8 mg/dL", "AST 22 / ALT 27 U/L", "ALP 84 U/L", "Total Protein 7.1 g/dL · Albumin 4.0 g/dL"] },
    { id: "lab-4", title: "Coagulation · 14 Mar 04:30",
      lines: ["PT 12.4 s · INR 1.1", "aPTT 28 s", "Bleeding time 2 min"] },
  ],
  meds: [
    { id: "med-c043", chunkId: "c043", title: "Discharge Rx · Pantoprazole",
      lines: ["Tab. Pantoprazole 40 mg", "Frequency: 1-0-0 · pre-breakfast", "Duration: 14 days · GI prophylaxis"], hl: "Pantoprazole 40 mg" },
    { id: "med-c047", chunkId: "c047", title: "Discharge Rx · Metoprolol",
      lines: ["Tab. Metoprolol Succinate 50 mg", "Frequency: BID (morning & night)", "Duration: 30 days", "Review: BP @ 1 week, target <130/80"], hl: "Metoprolol Succinate 50 mg" },
    { id: "med-c049", chunkId: "c049", title: "Discharge Rx · Amoxiclav",
      lines: ["Tab. Amoxicillin-Clavulanate 625 mg", "Frequency: 1-0-1", "Duration: 5 days · wound check day 7"], hl: "Amoxicillin-Clavulanate 625 mg" },
    { id: "med-c058", chunkId: "c058", title: "Discharge Rx · Paracetamol",
      lines: ["Tab. Paracetamol 500 mg", "Frequency: SOS — only if pain ≥ 4/10", "Max 4 doses per 24 hr"], hl: "SOS — only if pain ≥ 4/10" },
  ],
  progress: [
    { id: "prog-1", chunkId: "c041", title: "OT Note · 14 Mar 11:20",
      lines: ["Lap. cholecystectomy under GA. 4-port technique.", "Calot's triangle dissected; no bile spill.", "Operative time 47 min · EBL <30 ml.", "Transferred to ward in stable condition."], hl: "Lap. cholecystectomy" },
    { id: "prog-2", chunkId: "c052", title: "Admission Allergy Note · 12 Mar 08:05",
      lines: ["NKDA confirmed by patient.", "Allergy band: blank.", "⚠ 2023 visit mentions self-reported \"penicillin rash\" — not formally documented."], hl: "NKDA" },
    { id: "prog-3", chunkId: "c055", title: "Admission History · 12 Mar 08:10",
      lines: ["Past history: HTN (5y), T2DM (3y).", "Home medication list: NOT PROVIDED on admission.", "Patient asked to bring prior Rx at next OPD."], hl: "Home medication list: NOT PROVIDED" },
    { id: "prog-4", title: "POD 1 Note · 15 Mar 09:00",
      lines: ["Tolerating oral diet. Pain 2/10.", "Wound dressing dry, no soakage.", "Plan: discharge planning for 16 Mar."] },
  ],
  vitals: [
    { id: "v-1", title: "POD 2 · 16 Mar 06:00",
      lines: ["HR 76 bpm · BP 128/82 mmHg", "Temp 98.4°F · SpO₂ 99% RA", "RR 14 /min · Pain 1/10"] },
    { id: "v-2", title: "POD 1 · 15 Mar 06:00",
      lines: ["HR 82 bpm · BP 132/86 mmHg", "Temp 99.1°F · SpO₂ 98% RA", "RR 16 /min · Pain 3/10"] },
    { id: "v-3", title: "Post-op Recovery · 14 Mar 13:00",
      lines: ["HR 88 bpm · BP 134/88 mmHg", "Temp 98.8°F · SpO₂ 98% on 2L O₂", "Pain 4/10 — Inj. Tramadol 50 mg IV given."] },
  ],
  radiology: [
    { id: "r-1", title: "USG Abdomen · 11 Mar 2026",
      lines: ["Gallbladder distended, wall 4 mm.", "Multiple calculi, largest 12 mm.", "No pericholecystic fluid. CBD 5 mm.", "Impression: Cholelithiasis."] },
    { id: "r-2", title: "Chest X-Ray PA · 12 Mar 2026",
      lines: ["Lung fields clear bilaterally.", "CT ratio normal. No active disease."] },
  ],
};

window.ADMIN_ENCOUNTERS = ADMIN_ENCOUNTERS;
window.STATUS_MAP = STATUS_MAP;
window.DOCTOR_QUEUE = DOCTOR_QUEUE;
window.CLAIMS_INITIAL = CLAIMS_INITIAL;
window.CHUNKS = CHUNKS;
window.SUMMARY_SECTIONS = SUMMARY_SECTIONS;

// ── Browser-side patient cache (localStorage, 24h TTL) ────────────────────────
// Stores lightweight metadata per patient so "Active" badge survives page refresh.
// Full clinical data still fetched from server (server has its own 24h disk cache).

const _PAT_CACHE_PREFIX = "foqal_pat_";
const _PAT_CACHE_TTL    = 24 * 60 * 60 * 1000; // 24 hours in ms

function patCachePut(hadm_id, meta) {
  try {
    // _forceTs: override to correct corrupted ts (e.g. from enc.created_at)
    // Otherwise preserve original ts so 24h TTL counts from FIRST open
    const existing = patCacheGet(hadm_id);
    const ts = meta._forceTs ?? (existing ? existing.ts : Date.now());
    localStorage.setItem(_PAT_CACHE_PREFIX + hadm_id, JSON.stringify({
      hadm_id:        Number(hadm_id),
      subject_id:     meta.subject_id    || null,
      admission_type: meta.admission_type || null,
      admittime:      meta.admittime     || null,
      dischtime:      meta.dischtime     || null,
      loading:        meta.loading       ?? false,
      ts,
    }));
  } catch (e) {
    // localStorage full — prune expired entries first then retry
    patCachePrune();
    try {
      const existing = patCacheGet(hadm_id);
      const ts = existing ? existing.ts : Date.now();
      localStorage.setItem(_PAT_CACHE_PREFIX + hadm_id, JSON.stringify({ hadm_id: Number(hadm_id), ts }));
    } catch (_) {}
  }
}

function patCacheGet(hadm_id) {
  try {
    const raw = localStorage.getItem(_PAT_CACHE_PREFIX + hadm_id);
    if (!raw) return null;
    const item = JSON.parse(raw);
    if (Date.now() - item.ts > _PAT_CACHE_TTL) {
      localStorage.removeItem(_PAT_CACHE_PREFIX + hadm_id);
      return null;
    }
    return item;
  } catch (e) { return null; }
}

function patCachePrune() {
  Object.keys(localStorage).forEach(k => {
    if (!k.startsWith(_PAT_CACHE_PREFIX)) return;
    try {
      const item = JSON.parse(localStorage.getItem(k));
      if (Date.now() - item.ts > _PAT_CACHE_TTL) { localStorage.removeItem(k); return; }
      // loading is session-only — clear stale flag so cached patients don't show "Fetching data…" on reload
      if (item.loading) { item.loading = false; localStorage.setItem(k, JSON.stringify(item)); }
    } catch (_) { localStorage.removeItem(k); }
  });
}

function patCacheActiveIds() {
  const ids = new Set();
  Object.keys(localStorage).forEach(k => {
    if (!k.startsWith(_PAT_CACHE_PREFIX)) return;
    try {
      const item = JSON.parse(localStorage.getItem(k));
      if (Date.now() - item.ts <= _PAT_CACHE_TTL) {
        ids.add(Number(item.hadm_id));
      } else {
        localStorage.removeItem(k); // clean up while we're here
      }
    } catch (_) { localStorage.removeItem(k); }
  });
  return ids;
}

function patCacheTtlLeft(hadm_id) {
  const item = patCacheGet(hadm_id);
  if (!item) return 0;
  return Math.max(0, _PAT_CACHE_TTL - (Date.now() - item.ts));
}

// Auto-prune on load so old entries don't linger in RAM
patCachePrune();

window.patCachePut        = patCachePut;
window.patCacheGet        = patCacheGet;
window.patCachePrune      = patCachePrune;
window.patCacheActiveIds  = patCacheActiveIds;
window.patCacheTtlLeft    = patCacheTtlLeft;

// encHistoryPut / encHistoryGet removed — Cloud SQL is source of truth for encounter state.
// All staff see live updates because uploads/generate/delete all write to Cloud SQL via backend.
// localStorage only tracks the 24h active RAM cache (foqal_pat_).
function encHistoryPut() {}
function encHistoryGet() { return null; }
window.encHistoryPut = encHistoryPut;
window.encHistoryGet = encHistoryGet;
window.LEFT_SOURCES = LEFT_SOURCES;
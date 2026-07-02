"""
clinical_enrichment.py
Shared enrichment engine used by all three mapping pipelines
(procedures, medicines, labs).

Design principles:
- Enrichment is purely factual (unknown > hallucinated)
- All results are cached to disk (never re-call the API for same input)
- Enriched strings are deterministic and reproducible
"""

import os
import re
import json
import time
import google.generativeai as genai

# ─── Shared Abbreviation Expansions ───────────────────────────────────────────
ABBREV = {
    # Procedures
    "CABG": "Coronary Artery Bypass Graft",
    "PCI":  "Percutaneous Coronary Intervention",
    "PTCA": "Percutaneous Transluminal Coronary Angioplasty",
    "AVR":  "Aortic Valve Replacement",
    "MVR":  "Mitral Valve Replacement",
    "AICD": "Automated Implantable Cardioverter Defibrillator",
    "ICD":  "Implantable Cardioverter Defibrillator",
    "CRT":  "Cardiac Resynchronization Therapy",
    "ERCP": "Endoscopic Retrograde Cholangiopancreatography",
    "TURP": "Transurethral Resection of Prostate",
    "CEA":  "Carotid Endarterectomy",
    "AVM":  "Arteriovenous Malformation",
    "DES":  "Drug Eluting Stent",
    "BMS":  "Bare Metal Stent",
    "LAP":  "Laparoscopic",
    # Medicines
    "PO":   "Oral",
    "IV":   "Intravenous",
    "IM":   "Intramuscular",
    "SC":   "Subcutaneous",
    "SL":   "Sublingual",
    "SR":   "Sustained Release",
    "XR":   "Extended Release",
    "ER":   "Extended Release",
    "LA":   "Long Acting",
    "SA":   "Short Acting",
    "TAB":  "Tablet",
    "CAP":  "Capsule",
    "INJ":  "Injection",
    "SOL":  "Solution",
    "SYR":  "Syrup",
    "MDI":  "Metered Dose Inhaler",
    # Labs
    "CBC":  "Complete Blood Count",
    "BMP":  "Basic Metabolic Panel",
    "CMP":  "Comprehensive Metabolic Panel",
    "LFT":  "Liver Function Test",
    "RFT":  "Renal Function Test",
    "TSH":  "Thyroid Stimulating Hormone",
    "BNP":  "B-type Natriuretic Peptide",
    "ABG":  "Arterial Blood Gas",
    "ECG":  "Electrocardiogram",
    "EEG":  "Electroencephalogram",
    "HbA1c": "Glycated Haemoglobin A1c",
    "PT":   "Prothrombin Time",
    "INR":  "International Normalised Ratio",
    "PTT":  "Partial Thromboplastin Time",
    "ESR":  "Erythrocyte Sedimentation Rate",
    "CRP":  "C-Reactive Protein",
}

# ─── Prompts (one per domain) ─────────────────────────────────────────────────
PROCEDURE_ENRICHMENT_PROMPT = """You are a clinical ontology expert. Your task is to describe a medical procedure accurately.

Procedure: "{title}"

Return ONLY a JSON object with these exact keys. If you are not confident about a field, use "Unknown" — do NOT guess or hallucinate.

"specialty": (e.g., "Cardiology", "Neurology", "Orthopedics", "General Surgery")
"organ_system": (e.g., "Cardiovascular", "Central Nervous System", "Musculoskeletal")
"intent": either "Diagnostic" or "Therapeutic" or "Unknown"
"invasiveness": one of "Non-invasive", "Minimally invasive", "Invasive", "Major surgery", "Unknown"
"typical_indication": (brief phrase for why this procedure is performed, or "Unknown")
"clinical_description": (1 sentence factual description of what this procedure does, or "Unknown")

JSON only:"""

MEDICINE_ENRICHMENT_PROMPT = """You are a clinical pharmacologist. Your task is to describe a medication accurately.

Medicine: "{title}"

Return ONLY a JSON object with these exact keys. If you are not confident about a field, use "Unknown" — do NOT guess or hallucinate.

"active_ingredient": (e.g., "Metoprolol", "Aspirin", or "Unknown")
"drug_class": (e.g., "Beta-blocker", "Antiplatelet", "ACE Inhibitor", or "Unknown")
"mechanism_category": (e.g., "Antihypertensive", "Anticoagulant", "Diuretic", or "Unknown")
"route": (e.g., "Oral", "Intravenous", "Subcutaneous", or "Unknown")
"common_indication": (brief phrase, e.g., "Heart failure", "Hypertension", or "Unknown")
"patient_population": (e.g., "Adult", "Pediatric", "Both", or "Unknown")

JSON only:"""

LAB_ENRICHMENT_PROMPT = """You are a clinical laboratory expert. Your task is to describe a laboratory test accurately.

Lab Test: "{title}"

Return ONLY a JSON object with these exact keys. If you are not confident about a field, use "Unknown" — do NOT guess or hallucinate.

"standardized_name": (canonical name of this test, e.g., "Serum Sodium", or "Unknown")
"category": (e.g., "Haematology", "Chemistry", "Microbiology", "Hormones", "Coagulation", "Immunology", or "Unknown")
"sample_type": (e.g., "Blood", "Urine", "CSF", "Tissue", or "Unknown")
"organ_system": (e.g., "Renal", "Hepatic", "Cardiovascular", "Endocrine", or "Unknown")
"clinical_purpose": (brief phrase, e.g., "Electrolyte monitoring", "Cardiac injury marker", or "Unknown")

JSON only:"""

PROMPTS = {
    "procedure": PROCEDURE_ENRICHMENT_PROMPT,
    "medicine":  MEDICINE_ENRICHMENT_PROMPT,
    "lab":       LAB_ENRICHMENT_PROMPT,
}

# ─── Enriched string builders ──────────────────────────────────────────────────
def build_enriched_procedure(title: str, ctx: dict) -> str:
    return (
        f"Procedure: {title}. "
        f"Specialty: {ctx.get('specialty','Unknown')}. "
        f"Organ: {ctx.get('organ_system','Unknown')}. "
        f"Intent: {ctx.get('intent','Unknown')}. "
        f"Invasiveness: {ctx.get('invasiveness','Unknown')}. "
        f"Indication: {ctx.get('typical_indication','Unknown')}. "
        f"Description: {ctx.get('clinical_description','Unknown')}"
    )

def build_enriched_medicine(title: str, ctx: dict) -> str:
    return (
        f"Medicine: {title}. "
        f"Active Ingredient: {ctx.get('active_ingredient','Unknown')}. "
        f"Drug Class: {ctx.get('drug_class','Unknown')}. "
        f"Category: {ctx.get('mechanism_category','Unknown')}. "
        f"Route: {ctx.get('route','Unknown')}. "
        f"Indication: {ctx.get('common_indication','Unknown')}. "
        f"Population: {ctx.get('patient_population','Unknown')}"
    )

def build_enriched_lab(title: str, ctx: dict) -> str:
    return (
        f"Lab Test: {title}. "
        f"Standardized Name: {ctx.get('standardized_name','Unknown')}. "
        f"Category: {ctx.get('category','Unknown')}. "
        f"Sample: {ctx.get('sample_type','Unknown')}. "
        f"Organ System: {ctx.get('organ_system','Unknown')}. "
        f"Purpose: {ctx.get('clinical_purpose','Unknown')}"
    )

BUILDERS = {
    "procedure": build_enriched_procedure,
    "medicine":  build_enriched_medicine,
    "lab":       build_enriched_lab,
}

# ─── Normalisation ─────────────────────────────────────────────────────────────
def normalize(title: str, domain: str = "procedure") -> str:
    t = str(title).strip()
    # Remove parenthetical noise for all domains
    t = re.sub(r'\(.*?\)', '', t)
    if domain == "procedure":
        t = re.sub(r'\b(with|using|without|other|unspecified|nos|nec)\b', '', t, flags=re.IGNORECASE)
    if domain == "medicine":
        # Remove dosage noise
        t = re.sub(r'\b\d+(\.\d+)?\s*(mg|mcg|ug|ml|g|iu|meq|mmol|units?)\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\b(tablet|capsule|injection|solution|syrup|cream|ointment|patch|inhaler|drops?|spray|vial|amp|ampule)\b', '', t, flags=re.IGNORECASE)
    if domain == "lab":
        # Remove specimen noise already in category
        t = re.sub(r'\b(serum|plasma|whole blood|urine|csf|stool|swab)\b', '', t, flags=re.IGNORECASE)
    # Expand abbreviations
    for abbr, expansion in ABBREV.items():
        t = re.sub(rf'\b{re.escape(abbr)}\b', expansion, t, flags=re.IGNORECASE)
    return ' '.join(t.split())

# ─── Cache helpers ─────────────────────────────────────────────────────────────
def load_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A prior process kill mid-write can truncate this file. Salvage
        # every complete top-level entry instead of losing the whole cache.
        idx = raw.rfind('\n  },\n')
        if idx == -1:
            print(f"   WARNING: {path} is corrupted and unrecoverable — starting with an empty cache")
            return {}
        repaired = raw[:idx] + '\n  }\n}\n'
        data = json.loads(repaired)
        print(f"   WARNING: {path} was truncated (likely a prior kill) — recovered {len(data)} entries, resaving repaired copy")
        save_cache(path, data)
        return data

def save_cache(path: str, data: dict):
    # Write to a temp file then atomically replace — a kill mid-write to the
    # real path was leaving enrichment_cache.json truncated/corrupted, which
    # crashes every subsequent restart's load_cache() with a JSONDecodeError.
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)

# ─── Resumable embedding ────────────────────────────────────────────────────────
def embed_resumable(embedder, texts: list, cache_path: str,
                     embed_batch: int = 16, save_every: int = 200):
    """
    Encode texts in small batches, checkpointing progress to disk (a memory-mapped
    .npy file + a tiny meta.json) as it goes. If the process is killed mid-run
    (e.g. out of memory), re-running picks up from the last checkpoint instead of
    re-embedding everything from scratch.
    """
    import numpy as np
    meta_path = cache_path + ".meta.json"
    n = len(texts)

    probe = embedder.encode([texts[0]], show_progress_bar=False, batch_size=1)
    dim = probe.shape[1]

    done = 0
    if os.path.exists(cache_path) and os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        if meta.get("total") == n and meta.get("dim") == dim:
            done = meta.get("done", 0)

    mode = 'r+' if done > 0 else 'w+'
    emb = np.memmap(cache_path, dtype=np.float32, mode=mode, shape=(n, dim))
    if done == 0:
        emb[0] = probe[0]
        done = 1
        emb.flush()
        with open(meta_path, 'w') as f:
            json.dump({"total": n, "dim": dim, "done": done}, f)
    elif done > 1:
        print(f"   resuming embedding from checkpoint: {done}/{n} already done")

    while done < n:
        end = min(done + embed_batch, n)
        batch = embedder.encode(texts[done:end], show_progress_bar=False, batch_size=embed_batch)
        emb[done:end] = batch
        done = end
        if done % save_every < embed_batch or done == n:
            emb.flush()
            with open(meta_path, 'w') as f:
                json.dump({"total": n, "dim": dim, "done": done}, f)
            print(f"   embedded {done}/{n}")
    emb.flush()
    return emb

# ─── Resumable per-item results checkpoint ──────────────────────────────────────
def load_results_checkpoint(path: str) -> dict:
    """Loads a previous run's partial (results, audit) lists so a matching loop can
    skip already-processed items after a crash instead of redoing them."""
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            ckpt = json.load(f)
        if ckpt.get("done", 0) > 0:
            print(f"   resuming matching loop from checkpoint: {ckpt['done']} already done")
        return ckpt
    return {"results": [], "audit": [], "done": 0}

def save_results_checkpoint(path: str, results: list, audit: list, done: int):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({"results": results, "audit": audit, "done": done}, f)

# ─── Core enrichment function ─────────────────────────────────────────────────
def enrich(title: str, domain: str, cache: dict, cache_path: str, llm) -> dict:
    """
    Enrich a clinical entity title with a structured context card.
    - Checks cache first (no API call if already enriched)
    - Returns dict with clinical fields
    - Uses 'Unknown' for uncertain fields (never hallucinates)
    """
    key = f"{domain}::{title.strip().lower()}"
    if key in cache:
        return cache[key]

    prompt = PROMPTS[domain].format(title=title)
    for attempt in range(3):
        try:
            resp = llm.generate_content(
                prompt,
                generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
                request_options={"timeout": 30}
            )
            data = json.loads(resp.text)
            # Safety: ensure all values are strings and replace empty with "Unknown"
            data = {k: (str(v).strip() if v else "Unknown") for k, v in data.items()}
            cache[key] = data
            save_cache(cache_path, cache)
            return data
        except Exception as e:
            time.sleep(2)

    # All attempts failed — return safe Unknown card
    unknown_card = {
        "procedure": {
            "specialty": "Unknown", "organ_system": "Unknown", "intent": "Unknown",
            "invasiveness": "Unknown", "typical_indication": "Unknown", "clinical_description": title
        },
        "medicine": {
            "active_ingredient": "Unknown", "drug_class": "Unknown", "mechanism_category": "Unknown",
            "route": "Unknown", "common_indication": "Unknown", "patient_population": "Unknown"
        },
        "lab": {
            "standardized_name": title, "category": "Unknown", "sample_type": "Unknown",
            "organ_system": "Unknown", "clinical_purpose": "Unknown"
        },
    }[domain]
    cache[key] = unknown_card
    save_cache(cache_path, cache)
    return unknown_card

def build_enriched_string(title: str, ctx: dict, domain: str) -> str:
    return BUILDERS[domain](title, ctx)

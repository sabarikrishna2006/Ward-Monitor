"""
CIMS Drug Name Mapping — US Generic → Indian Brand Name
=======================================================
Maps MIMIC-IV US drug names (Metoprolol, Atorvastatin, etc.) to their
common Indian trade names per CIMS India / drug formularies.

Usage:
    from .cims_drug_map import indianise_drug_name, indianise_medications

Rules:
- Lookup is case-insensitive on the generic/active ingredient.
- If no match found, original name is returned unchanged.
- Multi-ingredient combos: match on first ingredient.
- Prefer the most widely stocked brand in Indian tier-2/3 hospitals.
"""

from typing import Optional

# ── Core lookup table ─────────────────────────────────────────────────────────
# Key: lowercase generic name (or leading ingredient for combos)
# Value: Indian brand name (most common stocking across private hospitals)
_MAP: dict[str, str] = {
    # ── Antiplatelets ─────────────────────────────────────────────────────────
    "aspirin":                       "Ecosprin",
    "acetylsalicylic acid":          "Ecosprin",
    "clopidogrel":                   "Clopivas",
    "ticagrelor":                    "Brilinta",
    "prasugrel":                     "Practi",
    "aspirin-clopidogrel":           "Ecosprin-Gold",
    "aspirin/clopidogrel":           "Ecosprin-Gold",

    # ── Anticoagulants ────────────────────────────────────────────────────────
    "heparin":                       "Heparin",
    "enoxaparin":                    "Clexane",
    "fondaparinux":                  "Arixtra",
    "warfarin":                      "Warf",
    "rivaroxaban":                   "Xarelto",
    "apixaban":                      "Eliquis",
    "dabigatran":                    "Pradaxa",

    # ── Beta-blockers ─────────────────────────────────────────────────────────
    "metoprolol":                    "Metolar XR",
    "metoprolol succinate":          "Metolar XR",
    "metoprolol tartrate":           "Metolar",
    "bisoprolol":                    "Concor",
    "carvedilol":                    "Cardivas",
    "atenolol":                      "Tenormin",
    "propranolol":                   "Inderal",
    "nebivolol":                     "Nebicard",

    # ── ACE Inhibitors ────────────────────────────────────────────────────────
    "ramipril":                      "Cardace",
    "lisinopril":                    "Listril",
    "enalapril":                     "Envas",
    "perindopril":                   "Coversyl",
    "captopril":                     "Capoten",
    "trandolapril":                  "Gopten",
    "fosinopril":                    "Fovas",

    # ── ARBs ──────────────────────────────────────────────────────────────────
    "losartan":                      "Cosart",
    "valsartan":                     "Valzaar",
    "candesartan":                   "Candesar",
    "olmesartan":                    "Olsar",
    "irbesartan":                    "Irbetan",
    "telmisartan":                   "Telma",
    "azilsartan":                    "Azilide",

    # ── ARNI ──────────────────────────────────────────────────────────────────
    "sacubitril":                    "Vymada",
    "sacubitril/valsartan":          "Vymada",
    "sacubitril-valsartan":          "Vymada",
    "entresto":                      "Vymada",

    # ── Calcium channel blockers ──────────────────────────────────────────────
    "amlodipine":                    "Stamlo",
    "diltiazem":                     "Dilzem",
    "verapamil":                     "Calaptin",
    "nifedipine":                    "Nicardia",
    "felodipine":                    "Plendil",

    # ── Statins ───────────────────────────────────────────────────────────────
    "atorvastatin":                  "Atorva",
    "rosuvastatin":                  "Rozavel",
    "simvastatin":                   "Simvotin",
    "pravastatin":                   "Pravator",
    "pitavastatin":                  "Livalo",
    "lovastatin":                    "Lova",
    "fluvastatin":                   "Lescol",

    # ── MRA / Diuretics ──────────────────────────────────────────────────────
    "spironolactone":                "Aldactone",
    "eplerenone":                    "Inspra",
    "furosemide":                    "Lasix",
    "frusemide":                     "Lasix",
    "torsemide":                     "Dytor",
    "torasemide":                    "Dytor",
    "bumetanide":                    "Burinex",
    "hydrochlorothiazide":           "Hydrochlorothiazide",
    "indapamide":                    "Natrilix SR",
    "metolazone":                    "Zaroxolyn",

    # ── Nitrates ─────────────────────────────────────────────────────────────
    "nitroglycerin":                 "Nitrocontin",
    "glyceryl trinitrate":           "Nitrocontin",
    "isosorbide dinitrate":          "Sorbitrate",
    "isosorbide mononitrate":        "Monotrate",
    "isosorbide":                    "Sorbitrate",

    # ── Antianginals ─────────────────────────────────────────────────────────
    "nicorandil":                    "Nikoran",
    "trimetazidine":                 "Vastarel MR",
    "ranolazine":                    "Ranolaz",
    "ivabradine":                    "Coralan",

    # ── SGLT2 Inhibitors (heart failure) ─────────────────────────────────────
    "empagliflozin":                 "Jardiance",
    "dapagliflozin":                 "Forxiga",
    "canagliflozin":                 "Invokana",

    # ── Antiarrhythmics ───────────────────────────────────────────────────────
    "amiodarone":                    "Cordarone",
    "sotalol":                       "Sotalol",
    "flecainide":                    "Flecaine",
    "digoxin":                       "Lanoxin",
    "adenosine":                     "Adenocor",
    "lidocaine":                     "Xylocard",
    "lignocaine":                    "Xylocard",

    # ── Antihypertensives / other ─────────────────────────────────────────────
    "hydralazine":                   "Nepresol",
    "clonidine":                     "Catapres",
    "prazosin":                      "Minipress",
    "doxazosin":                     "Cardura",

    # ── GPI / Thrombolytics ───────────────────────────────────────────────────
    "tirofiban":                     "Tirofiban",
    "eptifibatide":                  "Integrilin",
    "abciximab":                     "Reopro",
    "streptokinase":                 "Streptokinase",
    "alteplase":                     "Actilyse",
    "tenecteplase":                  "Metalyse",

    # ── Diabetes (often co-morbid) ────────────────────────────────────────────
    "metformin":                     "Glycomet",
    "insulin glargine":              "Basalog",
    "insulin detemir":               "Levemir",
    "insulin aspart":                "Novorapid",
    "insulin lispro":                "Humalog",
    "sitagliptin":                   "Januvia",
    "vildagliptin":                  "Galvus",
    "saxagliptin":                   "Onglyza",

    # ── PPIs (gastroprotection) ───────────────────────────────────────────────
    "pantoprazole":                  "Pan",
    "omeprazole":                    "Omez",
    "rabeprazole":                   "Razo",
    "lansoprazole":                  "Lanzol",
    "esomeprazole":                  "Nexpro",

    # ── Potassium supplements ─────────────────────────────────────────────────
    "potassium chloride":            "Potklor",
    "potassium":                     "Potklor",

    # ── Analgesics / supportive ───────────────────────────────────────────────
    "paracetamol":                   "Calpol",
    "acetaminophen":                 "Calpol",
    "tramadol":                      "Ultracet",
    "morphine":                      "Morphine",
    "fentanyl":                      "Fentanyl",
    "ketorolac":                     "Toradol",

    # ── Anxiolytics (pre-procedure) ───────────────────────────────────────────
    "midazolam":                     "Dormicum",
    "diazepam":                      "Calmpose",
    "lorazepam":                     "Ativan",

    # ── Antibiotics (prophylaxis) ─────────────────────────────────────────────
    "cefazolin":                     "Reflin",
    "cephalexin":                    "Sporidex",
    "amoxicillin-clavulanate":       "Augmentin",
    "amoxicillin/clavulanate":       "Augmentin",
}


def indianise_drug_name(generic_name: str) -> str:
    """
    Return the Indian brand name for a given US generic drug name.
    Falls back to original if not in the CIMS map.
    """
    if not generic_name:
        return generic_name
    key = generic_name.strip().lower()
    # Direct match
    if key in _MAP:
        return _MAP[key]
    # Match on first word (active ingredient prefix)
    first_word = key.split()[0] if " " in key else key
    if first_word in _MAP:
        return _MAP[first_word]
    # Check if any map key is a prefix of the drug name (e.g. "metoprolol succinate er")
    for map_key, brand in _MAP.items():
        if key.startswith(map_key):
            return brand
    return generic_name  # no match — return as-is; Pass 2 prompt notes "verify brand name"


def indianise_medications(medications: list[dict]) -> list[dict]:
    """
    Apply CIMS mapping to a list of medication dicts from Pass 1 JSON.
    Each dict has `drug_name_source` (the raw MIMIC name).
    Returns a new list with `drug_name_source` mapped to Indian brand.
    Original generic name preserved in `drug_generic_name`.
    """
    result = []
    for med in medications:
        med = dict(med)
        raw = med.get("drug_name_source") or ""
        indian = indianise_drug_name(raw)
        if indian != raw:
            med["drug_generic_name"] = raw
            med["drug_name_source"] = indian
        result.append(med)
    return result

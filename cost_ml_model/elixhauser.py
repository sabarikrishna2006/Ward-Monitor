"""
Elixhauser comorbidity scoring (manual implementation — no ready-made package).

Standard 31-category Elixhauser comorbidity index, scored using the Van Walraven
(2009) weighted point system. Covers both ICD-9-CM and ICD-10-CM diagnosis codes
since the DCM cohort spans both coding eras in MIMIC-IV.

Not a perfect/exhaustive AHRQ implementation, but present and consistent for
every patient (per the project plan) — good enough for a first working model.
"""
import re

# category -> Van Walraven (2009) weight
VAN_WALRAVEN_WEIGHTS = {
    "chf": 7, "arrhythmia": 5, "valvular": -1, "pulm_circ": 4, "pvd": 2,
    "hypertension_uncomp": 0, "hypertension_comp": 0, "paralysis": 7,
    "neuro_other": 6, "chronic_pulm": 3, "diabetes_uncomp": 0, "diabetes_comp": 0,
    "hypothyroid": 0, "renal_failure": 5, "liver_disease": 11, "pud": 0,
    "aids": 0, "lymphoma": 9, "metastatic_cancer": 12, "solid_tumor": 4,
    "rheumatoid": 0, "coagulopathy": 3, "obesity": -4, "weight_loss": 6,
    "fluid_electrolyte": 5, "blood_loss_anemia": -2, "deficiency_anemia": -2,
    "alcohol_abuse": 0, "drug_abuse": -7, "psychoses": 0, "depression": -3,
}

# category -> regex patterns matching the START of an ICD-10-CM code (no dot)
ICD10_PATTERNS = {
    "chf": [r"^I0?9?[0-9]?$", r"^I110", r"^I130", r"^I132", r"^I255", r"^I420-I429", r"^I43", r"^I50"],
    "arrhythmia": [r"^I44[1-3]", r"^I456", r"^I459", r"^I47", r"^I48", r"^I49", r"^R000", r"^R001", r"^R008", r"^T821", r"^Z450", r"^Z950"],
    "valvular": [r"^A520", r"^I0[5-8]", r"^I091", r"^I098", r"^I34", r"^I35", r"^I36", r"^I37", r"^I38", r"^I39", r"^Q23", r"^Z952", r"^Z953", r"^Z954"],
    "pulm_circ": [r"^I26", r"^I27", r"^I280", r"^I288", r"^I289"],
    "pvd": [r"^I70", r"^I71", r"^I731", r"^I738", r"^I739", r"^I771", r"^I790", r"^I792", r"^K551", r"^K558", r"^K559", r"^Z958", r"^Z959"],
    "hypertension_uncomp": [r"^I10"],
    "hypertension_comp": [r"^I1[1-5]"],
    "paralysis": [r"^G041", r"^G114", r"^G80", r"^G81", r"^G82", r"^G83"],
    "neuro_other": [r"^G1[0-3]", r"^G2[0-2]", r"^G254", r"^G255", r"^G3[0-2]", r"^G3[5-7]", r"^G40", r"^G41", r"^G93[1-4]", r"^R470", r"^R56"],
    "chronic_pulm": [r"^I27[89]", r"^J4[0-7]", r"^J6[0-7]", r"^J68[4]", r"^J701", r"^J703"],
    "diabetes_uncomp": [r"^E1[0-4][01].?$", r"^E1[0-4]9"],
    "diabetes_comp": [r"^E1[0-4][2-8]"],
    "hypothyroid": [r"^E0[0-3]", r"^E890"],
    "renal_failure": [r"^I120", r"^I131", r"^N18", r"^N19", r"^N25", r"^Z49", r"^Z940", r"^Z992"],
    "liver_disease": [r"^B18", r"^I85", r"^I864", r"^I982", r"^K70", r"^K711", r"^K713", r"^K714", r"^K715", r"^K717", r"^K7[2-4]", r"^K760", r"^K76[2-9]", r"^Z944"],
    "pud": [r"^K25", r"^K26", r"^K27", r"^K28"],
    "aids": [r"^B2[0-4]"],
    "lymphoma": [r"^C8[1-5]", r"^C88", r"^C9[0-6]"],
    "metastatic_cancer": [r"^C7[7-9]", r"^C80"],
    "solid_tumor": [r"^C[0-4][0-9]", r"^C5[0-8]", r"^C6[0-9]", r"^C7[0-6]", r"^C97"],
    "rheumatoid": [r"^L94[0-3]", r"^M0[5-6]", r"^M08", r"^M1[2-3]5", r"^M30", r"^M3[1-6]", r"^M45", r"^M46"],
    "coagulopathy": [r"^D6[5-9]"],
    "obesity": [r"^E66"],
    "weight_loss": [r"^E4[0-6]", r"^R634", r"^R64"],
    "fluid_electrolyte": [r"^E22[2]", r"^E86", r"^E87"],
    "blood_loss_anemia": [r"^D500"],
    "deficiency_anemia": [r"^D50[89]", r"^D5[1-3]"],
    "alcohol_abuse": [r"^F10", r"^E52", r"^G621", r"^I426", r"^K292", r"^K700", r"^K703", r"^K709", r"^T51", r"^Z502", r"^Z714", r"^Z721"],
    "drug_abuse": [r"^F1[1-6]", r"^F18", r"^F19", r"^Z715", r"^Z722"],
    "psychoses": [r"^F2[0-9]", r"^F3[01]2", r"^F312", r"^F314", r"^F315"],
    "depression": [r"^F204", r"^F3[12]", r"^F3[34]1", r"^F4131"],
}

# category -> regex patterns matching the START of an ICD-9-CM code (no dot)
ICD9_PATTERNS = {
    "chf": [r"^39891", r"^4022", r"^4028", r"^40[34][01]", r"^42[89]"],
    "arrhythmia": [r"^4260", r"^42613", r"^4267", r"^4269", r"^427[0-46-9]", r"^7850", r"^V450", r"^V533"],
    "valvular": [r"^093", r"^394", r"^395", r"^396", r"^397", r"^424", r"^7463", r"^V422", r"^V433"],
    "pulm_circ": [r"^415[01]", r"^416", r"^4179"],
    "pvd": [r"^093", r"^4373", r"^44[019]", r"^443[1-9]", r"^557", r"^V434"],
    "hypertension_uncomp": [r"^401"],
    "hypertension_comp": [r"^40[2-5]"],
    "paralysis": [r"^342", r"^343", r"^344"],
    "neuro_other": [r"^331[19]", r"^332", r"^333", r"^33[45]", r"^340", r"^341", r"^345", r"^3481", r"^3483", r"^7803", r"^7843"],
    "chronic_pulm": [r"^490", r"^49[1-6]", r"^500", r"^50[1-5]", r"^5064", r"^5081", r"^5088"],
    "diabetes_uncomp": [r"^250[0-3]"],
    "diabetes_comp": [r"^250[4-9]"],
    "hypothyroid": [r"^24[0-6]"],
    "renal_failure": [r"^403", r"^404", r"^58[5-9]", r"^V4[25]6", r"^V56"],
    "liver_disease": [r"^070[23]", r"^0706", r"^45[07]0", r"^570", r"^5713", r"^57[14-8]", r"^V427"],
    "pud": [r"^53[1-4]"],
    "aids": [r"^042", r"^043", r"^044"],
    "lymphoma": [r"^20[01]", r"^202", r"^2030", r"^2386"],
    "metastatic_cancer": [r"^19[6-9]"],
    "solid_tumor": [r"^1[4-9][0-9]", r"^2[01][0-9]"],
    "rheumatoid": [r"^446", r"^7010", r"^71[0-3]", r"^714", r"^7193", r"^725"],
    "coagulopathy": [r"^286", r"^2871"],
    "obesity": [r"^2780"],
    "weight_loss": [r"^260", r"^261", r"^262", r"^263"],
    "fluid_electrolyte": [r"^2536", r"^276"],
    "blood_loss_anemia": [r"^2800"],
    "deficiency_anemia": [r"^280[1-9]", r"^281"],
    "alcohol_abuse": [r"^291", r"^303", r"^3050"],
    "drug_abuse": [r"^292", r"^304", r"^305[1-9]"],
    "psychoses": [r"^295", r"^297", r"^298"],
    "depression": [r"^296[235]", r"^3004", r"^309[01]", r"^311"],
}

_ICD10_COMPILED = {cat: [re.compile(p) for p in pats] for cat, pats in ICD10_PATTERNS.items()}
_ICD9_COMPILED  = {cat: [re.compile(p) for p in pats] for cat, pats in ICD9_PATTERNS.items()}


def categories_for_code(icd_code: str, icd_version: int) -> set:
    """Return the set of Elixhauser categories a single ICD code falls into."""
    code = str(icd_code).upper().replace(".", "")
    patterns = _ICD10_COMPILED if int(icd_version) == 10 else _ICD9_COMPILED
    hits = set()
    for cat, regexes in patterns.items():
        if any(r.match(code) for r in regexes):
            hits.add(cat)
    return hits


def score_patient(icd_codes: list) -> dict:
    """
    icd_codes: list of (icd_code, icd_version) tuples for ONE admission (all
    diagnoses, not just primary).
    Returns {"elixhauser_score": int, "categories": [...]}.
    Applies the standard hierarchy exclusions: complicated diabetes overrides
    uncomplicated; metastatic cancer overrides solid tumor; complicated
    hypertension overrides uncomplicated.
    """
    cats = set()
    for code, version in icd_codes:
        cats |= categories_for_code(code, version)

    if "diabetes_comp" in cats:
        cats.discard("diabetes_uncomp")
    if "metastatic_cancer" in cats:
        cats.discard("solid_tumor")
    if "hypertension_comp" in cats:
        cats.discard("hypertension_uncomp")

    score = sum(VAN_WALRAVEN_WEIGHTS.get(c, 0) for c in cats)
    return {"elixhauser_score": score, "categories": sorted(cats)}

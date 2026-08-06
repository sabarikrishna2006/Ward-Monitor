"""
Charlson Comorbidity Index from ICD-9 / ICD-10 codes (Quan et al. 2005 mapping).

A static, per-admission covariate for the survival model — it is *not* derived
from the vitals we predict, so it adds genuine (non-circular) prognostic signal
about baseline comorbidity burden. MIMIC-IV `diagnoses_icd.icd_code` is stored
WITHOUT dots (e.g. 'I420', '4254'), which matches the dot-less prefix lists below.

Reference: Quan H, et al. "Coding algorithms for defining comorbidities in
ICD-9-CM and ICD-10 administrative data." Med Care. 2005;43(11):1130-9.
Weights are the original Charlson (1987) weights.
"""
from __future__ import annotations

# category -> (weight, icd10_prefixes, icd9_prefixes)
_CHARLSON: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
    "mi":            (1, ("I21", "I22", "I252"), ("410", "412")),
    "chf":           (1, ("I099", "I110", "I130", "I132", "I255", "I420", "I425", "I426",
                          "I427", "I428", "I429", "I43", "I50", "P290"),
                         ("39891", "40201", "40211", "40291", "40401", "40403", "40411",
                          "40413", "40491", "40493", "4254", "4255", "4257", "4258",
                          "4259", "428")),
    "pvd":           (1, ("I70", "I71", "I731", "I738", "I739", "I771", "I790", "I792",
                          "K551", "K558", "K559", "Z958", "Z959"),
                         ("093", "4373", "440", "441", "4431", "4432", "4433", "4434",
                          "4435", "4436", "4437", "4438", "4439", "4471", "5571", "5579", "V434")),
    "cvd":           (1, ("G45", "G46", "H340", "I60", "I61", "I62", "I63", "I64", "I65",
                          "I66", "I67", "I68", "I69"),
                         ("36234", "430", "431", "432", "433", "434", "435", "436", "437", "438")),
    "dementia":      (1, ("F00", "F01", "F02", "F03", "F051", "G30", "G311"),
                         ("290", "2941", "3312")),
    "copd":          (1, ("I278", "I279", "J40", "J41", "J42", "J43", "J44", "J45", "J46",
                          "J47", "J60", "J61", "J62", "J63", "J64", "J65", "J66", "J67",
                          "J684", "J701", "J703"),
                         ("4168", "4169", "490", "491", "492", "493", "494", "495", "496",
                          "500", "501", "502", "503", "504", "505", "5064", "5081", "5088")),
    "rheum":         (1, ("M05", "M06", "M315", "M32", "M33", "M34", "M351", "M353", "M360"),
                         ("4465", "7100", "7101", "7102", "7103", "7104", "7140", "7141",
                          "7142", "7148", "725")),
    "pud":           (1, ("K25", "K26", "K27", "K28"), ("531", "532", "533", "534")),
    "mild_liver":    (1, ("B18", "K700", "K701", "K702", "K703", "K709", "K713", "K714",
                          "K715", "K717", "K73", "K74", "K760", "K762", "K763", "K764",
                          "K768", "K769", "Z944"),
                         ("07022", "07023", "07032", "07033", "07044", "07054", "0706",
                          "0709", "570", "571", "5733", "5734", "5738", "5739", "V427")),
    "diab":          (1, ("E100", "E101", "E106", "E108", "E109", "E110", "E111", "E116",
                          "E118", "E119", "E120", "E121", "E126", "E128", "E129", "E130",
                          "E131", "E136", "E138", "E139", "E140", "E141", "E146", "E148", "E149"),
                         ("2500", "2501", "2502", "2503", "2508", "2509")),
    "diab_comp":     (2, ("E102", "E103", "E104", "E105", "E107", "E112", "E113", "E114",
                          "E115", "E117", "E122", "E123", "E124", "E125", "E127", "E132",
                          "E133", "E134", "E135", "E137", "E142", "E143", "E144", "E145", "E147"),
                         ("2504", "2505", "2506", "2507")),
    "para":          (2, ("G041", "G114", "G801", "G802", "G81", "G82", "G830", "G831",
                          "G832", "G833", "G834", "G839"),
                         ("3341", "342", "343", "3440", "3441", "3442", "3443", "3444",
                          "3445", "3446", "3449")),
    "renal":         (2, ("I120", "I131", "N032", "N033", "N034", "N035", "N036", "N037",
                          "N052", "N053", "N054", "N055", "N056", "N057", "N18", "N19",
                          "N250", "Z490", "Z491", "Z492", "Z940", "Z992"),
                         ("40301", "40311", "40391", "40402", "40403", "40412", "40413",
                          "40492", "40493", "582", "5830", "5831", "5832", "5834", "5836",
                          "5837", "585", "586", "5880", "V420", "V451", "V56")),
    "malignancy":    (2, ("C0", "C1", "C20", "C21", "C22", "C23", "C24", "C25", "C26",
                          "C30", "C31", "C32", "C33", "C34", "C37", "C38", "C39", "C40",
                          "C41", "C43", "C45", "C46", "C47", "C48", "C49", "C50", "C51",
                          "C52", "C53", "C54", "C55", "C56", "C57", "C58", "C6", "C70",
                          "C71", "C72", "C73", "C74", "C75", "C76", "C81", "C82", "C83",
                          "C84", "C85", "C88", "C90", "C91", "C92", "C93", "C94", "C95",
                          "C96", "C97"),
                         ("14", "15", "16", "17", "18", "190", "191", "192", "193", "194",
                          "1950", "1951", "1952", "1953", "1954", "1955", "1958", "200",
                          "201", "202", "203", "204", "205", "206", "207", "208", "2386")),
    "severe_liver":  (3, ("I850", "I859", "I864", "I982", "K704", "K711", "K721", "K729",
                          "K765", "K766", "K767"),
                         ("4560", "4561", "4562", "5722", "5723", "5724", "5728")),
    "mets":          (6, ("C77", "C78", "C79", "C80"), ("196", "197", "198", "199")),
    "hiv":           (6, ("B20", "B21", "B22", "B24"), ("042", "043", "044")),
}

# hierarchy: if the more-severe category is present, drop the milder one.
_HIERARCHY = {"diab": "diab_comp", "mild_liver": "severe_liver", "malignancy": "mets"}


def _present(categories: set[str], codes_by_version: dict[int, set[str]]) -> set[str]:
    icd10 = codes_by_version.get(10, set())
    icd9 = codes_by_version.get(9, set())
    hits = set()
    for cat, (_w, p10, p9) in _CHARLSON.items():
        if any(c.startswith(p10) for c in icd10) or any(c.startswith(p9) for c in icd9):
            hits.add(cat)
    return hits


def charlson_score(icd_codes: list[tuple[str, int]]) -> int:
    """icd_codes = list of (code, icd_version). Returns the weighted Charlson index."""
    by_ver: dict[int, set[str]] = {9: set(), 10: set()}
    for code, ver in icd_codes:
        if code is None:
            continue
        by_ver.setdefault(int(ver), set()).add(str(code).strip().upper())
    hits = _present(set(), by_ver)
    # apply hierarchy (drop milder when severe present)
    for milder, severe in _HIERARCHY.items():
        if severe in hits:
            hits.discard(milder)
    return sum(_CHARLSON[c][0] for c in hits)

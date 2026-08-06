"""
Synthetic Indian Cardiology Demo Patients
==========================================
Five fully-populated Pass 1 JSON cases — one per discharge type.
Use these when BigQuery is unavailable or for always-on demos.

All patients use Indian names, Indian drug brands (CIMS-mapped),
and realistic Indian urban cardiology demographics.

Access: get_demo_case(discharge_type) → dict (Pass 1 JSON)
        list_demo_cases() → list[{discharge_type, hadm_id, patient_name}]
"""

_DEMO_CASES: dict[str, dict] = {

    # ── Standard — STEMI with PCI ─────────────────────────────────────────────
    "Standard": {
        "patient": {
            "name": "Rajesh Kumar", "age": 58, "dob": "1966-03-12",
            "sex": "Male", "uhid": "DEMO-STD-001", "admission_date": "2026-06-01",
            "discharge_date": "2026-06-06", "admission_mode": "Emergency",
            "referral_source": "Self-referral via casualty",
            "attending_physician": "Dr. Pradeep Nair", "attending_mci_reg": "MCI-MH-45231",
            "ward": "CCU", "bed_number": "CCU-04",
            "next_of_kin": {"name": "Sunita Kumar", "relationship": "Wife", "contact": "9876543210"},
        },
        "chief_complaint": "Acute chest pain radiating to left arm, onset 3 hours prior to admission",
        "duration_of_symptoms": "3 hours",
        "hpi": (
            "Mr. Rajesh Kumar, 58-year-old male, presented to casualty with severe crushing chest pain "
            "radiating to the left arm and jaw, associated with diaphoresis and dyspnoea. "
            "Onset 3 hours before presentation. No prior similar episodes. Known hypertensive for 12 years, "
            "diabetic for 8 years. Smoker (20 pack-years, quit 2 years ago). "
            "ECG on admission showed ST elevation in leads II, III, aVF — inferior STEMI pattern. "
            "Activated cardiac catheterisation lab immediately on arrival."
        ),
        "pmh": {
            "comorbidities": ["Hypertension (12 years)", "Type 2 Diabetes Mellitus (8 years)"],
            "prior_cardiac_interventions": [],
            "surgical_history": ["Appendicectomy (2005)"],
            "allergies": ["Penicillin — rash"],
            "family_history": "Father — MI at age 62. Mother — hypertension.",
            "smoking": "Ex-smoker (20 pack-years, quit 2 years ago)",
            "alcohol": "Occasional social use",
        },
        "vitals_on_admission": {
            "bp_systolic": 148, "bp_diastolic": 92, "heart_rate": 104, "rhythm": "Sinus tachycardia",
            "spo2": 94, "respiratory_rate": 22, "temperature": 37.1, "gcs": 15,
            "jvp": "Not elevated", "heart_sounds": "S1 S2 heard, S4 present",
            "murmurs": "None", "breath_sounds": "Bilateral clear", "pedal_oedema": "Absent",
        },
        "labs": {
            "troponin_t_peak": 4.82, "troponin_unit": "ng/mL",
            "troponin_serial": [
                {"time": "2026-06-01 08:00", "value": 0.24, "unit": "ng/mL"},
                {"time": "2026-06-01 14:00", "value": 2.10, "unit": "ng/mL"},
                {"time": "2026-06-01 20:00", "value": 4.82, "unit": "ng/mL"},
            ],
            "bnp_or_ntprobnp": 680, "hemoglobin": 13.4, "wbc": 11.2, "platelets": 218,
            "creatinine": 1.1, "egfr": 72, "urea": 38, "sodium": 138, "potassium": 4.1, "magnesium": 0.9,
            "hba1c": 7.8, "fasting_glucose": 162,
            "lipid_profile": {"ldl": 142, "hdl": 38, "triglycerides": 198, "total_cholesterol": 218},
            "inr": 1.0, "pt": 12.4,
        },
        "ecg_findings": (
            "ST elevation 2–4 mm in leads II, III, aVF. Reciprocal ST depression in I and aVL. "
            "Sinus tachycardia at 104 bpm. No bundle branch block."
        ),
        "echo": {
            "lvef_percent": 48, "wall_motion_abnormality": "Inferior and inferolateral hypokinesia",
            "valvular_findings": "Mild MR — trivial jet", "pericardial_findings": "No effusion",
        },
        "cath_lab": {
            "lad_stenosis_percent": 30, "lcx_stenosis_percent": 20,
            "rca_stenosis_percent": 99,
            "intervention_performed": "Primary PCI to RCA with drug-eluting stent placement",
            "stent_details": "Synergy DES 3.0 × 28 mm — RCA mid-segment",
            "timi_flow_post": "TIMI 3",
            "chest_xray_findings": "Mild cardiomegaly. No pulmonary oedema.",
        },
        "risk_scores": {"grace_score": 148, "grace_risk": "High", "timi_score": 5},
        "hospital_course": (
            "Patient underwent primary PCI within 90 minutes of arrival (door-to-balloon time: 68 minutes). "
            "Successful recanalisation of RCA with TIMI 3 flow achieved post-stenting. "
            "Post-procedure haemodynamically stable. Commenced on dual antiplatelet therapy, "
            "high-intensity statin, ACE inhibitor, and beta-blocker. "
            "Glycaemic control managed with insulin sliding scale; transitioned to oral agents on day 3. "
            "Cardiology review on day 4 — repeat ECG showed resolving ST changes. "
            "No rhythm disturbances. No bleeding complications. "
            "Patient counselled on lifestyle modification, DAPT adherence, and cardiac rehabilitation."
        ),
        "complications": [],
        "procedures": [
            {
                "name": "Primary PCI — RCA with DES", "date": "2026-06-01",
                "operator": "Dr. Pradeep Nair", "outcome": "TIMI 3 flow achieved",
                "icd_pcs_code": "027L0DZ",
            }
        ],
        "discharge_medications": [
            {"drug_name_source": "Ecosprin", "dose": "75 mg", "frequency": "Once daily", "route": "Oral", "duration": "Lifelong", "high_risk_flag": None},
            {"drug_name_source": "Clopilet", "dose": "75 mg", "frequency": "Once daily", "route": "Oral", "duration": "12 months", "high_risk_flag": "DAPT — high-risk if interrupted"},
            {"drug_name_source": "Atorva", "dose": "80 mg", "frequency": "Once at night", "route": "Oral", "duration": "Lifelong", "high_risk_flag": None},
            {"drug_name_source": "Metolar XR", "dose": "50 mg", "frequency": "Once daily", "route": "Oral", "duration": "Lifelong", "high_risk_flag": None},
            {"drug_name_source": "Cardace", "dose": "5 mg", "frequency": "Once daily", "route": "Oral", "duration": "Lifelong", "high_risk_flag": None},
            {"drug_name_source": "Pan", "dose": "40 mg", "frequency": "Once daily", "route": "Oral", "duration": "12 months", "high_risk_flag": None},
            {"drug_name_source": "Glycomet", "dose": "500 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
        ],
        "dapt_months": 12,
        "stopped_medications": [],
        "discharge_diagnosis_clinical": "Inferior ST Elevation Myocardial Infarction (STEMI)",
        "icd10_codes": ["I21.1 — ST elevation myocardial infarction of inferior wall"],
        "icd10_pcs_codes": ["027L0DZ — Dilation of right coronary artery with drug-eluting intraluminal device"],
        "discharge_type": "Standard",
        "condition_at_discharge": "Haemodynamically stable. Improving.",
        "nyha_class": "NYHA Class II",
        "discharge_vitals": {"bp_systolic": 122, "bp_diastolic": 76, "heart_rate": 68, "spo2": 98, "weight_kg": 74},
        "followup": {
            "date": "2026-06-20", "physician": "Dr. Pradeep Nair",
            "clinic": "Cardiology OPD — Foqal Heart Institute",
            "investigations_ordered": ["ECG", "Fasting Lipid Profile", "HbA1c", "Renal Function Tests"],
            "diet_instructions": "Low-sodium, low-fat, diabetic diet. Avoid saturated fats and processed foods.",
            "activity_restrictions": "No heavy exertion for 4 weeks. Gradual ambulation. No driving for 2 weeks.",
            "emergency_return_criteria": ["Recurrent chest pain", "Dyspnoea at rest", "Palpitations", "Syncope", "Bleeding from any site"],
            "warnings": ["Do not stop DAPT without cardiologist consultation — risk of stent thrombosis"],
        },
        "patient_acknowledgement": {"confirmed": True, "confirmed_by": "Sunita Kumar", "relationship_to_patient": "Wife", "timestamp": "2026-06-06 14:30"},
    },

    # ── LAMA — Unstable Angina, Patient Refused Further Workup ───────────────
    "LAMA": {
        "patient": {
            "name": "Vikram Singh", "age": 52, "dob": "1974-01-08",
            "sex": "Male", "uhid": "DEMO-LAMA-002", "admission_date": "2026-06-04",
            "discharge_date": "2026-06-05", "admission_mode": "Emergency",
            "referral_source": "Referred from primary care physician",
            "attending_physician": "Dr. Suresh Pillai", "attending_mci_reg": "MCI-KA-22145",
            "ward": "Cardiology Ward B", "bed_number": "B-12",
            "next_of_kin": {"name": "Anita Singh", "relationship": "Wife", "contact": "9845001234"},
        },
        "chief_complaint": "Episodic chest tightness on exertion, 2 weeks duration",
        "duration_of_symptoms": "2 weeks",
        "hpi": (
            "Mr. Vikram Singh, 52-year-old male, presented with 2-week history of exertional chest tightness "
            "and dyspnoea on climbing stairs. No rest pain. No diaphoresis. Hypertensive, non-diabetic. "
            "ECG showed non-specific ST changes in V4-V6. Troponin T negative at 0 and 6 hours. "
            "Planned for stress test and coronary angiography workup. "
            "Patient refused further investigations citing personal reasons and demanded discharge."
        ),
        "pmh": {
            "comorbidities": ["Hypertension (6 years)"],
            "prior_cardiac_interventions": [],
            "surgical_history": [],
            "allergies": [],
            "family_history": "Brother — CABG at age 55.",
            "smoking": "Current smoker — 10 cigarettes/day",
            "alcohol": "None",
        },
        "vitals_on_admission": {
            "bp_systolic": 152, "bp_diastolic": 96, "heart_rate": 88, "rhythm": "Sinus rhythm",
            "spo2": 97, "respiratory_rate": 18, "temperature": 36.8, "gcs": 15,
            "jvp": "Not elevated", "heart_sounds": "S1 S2 heard, no added sounds",
            "murmurs": "None", "breath_sounds": "Bilateral clear", "pedal_oedema": "Absent",
        },
        "labs": {
            "troponin_t_peak": 0.008, "troponin_unit": "ng/mL",
            "troponin_serial": [
                {"time": "2026-06-04 10:00", "value": 0.006, "unit": "ng/mL"},
                {"time": "2026-06-04 16:00", "value": 0.008, "unit": "ng/mL"},
            ],
            "bnp_or_ntprobnp": 120, "hemoglobin": 14.1, "wbc": 8.4, "platelets": 242,
            "creatinine": 0.9, "egfr": 88, "urea": 28, "sodium": 140, "potassium": 3.9, "magnesium": 0.85,
            "hba1c": None, "fasting_glucose": 98,
            "lipid_profile": {"ldl": 156, "hdl": 42, "triglycerides": 168, "total_cholesterol": 226},
            "inr": None, "pt": None,
        },
        "ecg_findings": "Sinus rhythm at 88 bpm. Non-specific ST depression V4-V6 (≤1 mm). No acute changes.",
        "echo": {
            "lvef_percent": 58, "wall_motion_abnormality": "None identified",
            "valvular_findings": "No significant valvular disease", "pericardial_findings": "No effusion",
        },
        "cath_lab": {
            "lad_stenosis_percent": None, "lcx_stenosis_percent": None, "rca_stenosis_percent": None,
            "intervention_performed": "Angiography not performed — patient refused",
            "stent_details": None, "timi_flow_post": None, "chest_xray_findings": "Normal cardiac silhouette.",
        },
        "risk_scores": {"grace_score": None, "grace_risk": None, "timi_score": 2},
        "hospital_course": (
            "Patient admitted for evaluation of unstable angina. Serial troponins negative. "
            "Echo showed preserved LV function. Commenced on antiplatelet, statin, and beta-blocker. "
            "Planned stress ECG test and coronary angiography on day 2. "
            "Patient refused both investigations and demanded immediate discharge against medical advice. "
            "Risks explained clearly including risk of undetected obstructive coronary artery disease "
            "and potential for myocardial infarction. Patient acknowledged risks. AMA Declaration signed."
        ),
        "complications": [],
        "procedures": [],
        "discharge_medications": [
            {"drug_name_source": "Ecosprin", "dose": "75 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Atorva", "dose": "40 mg", "frequency": "Once at night", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Concor", "dose": "5 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Catapres", "dose": "0.1 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Pan", "dose": "40 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
        ],
        "dapt_months": None,
        "stopped_medications": [],
        "discharge_diagnosis_clinical": "Unstable Angina — incomplete workup (LAMA)",
        "icd10_codes": ["I20.0 — Unstable angina"],
        "icd10_pcs_codes": [],
        "discharge_type": "LAMA",
        "condition_at_discharge": "Clinically stable. Workup incomplete. AMA departure.",
        "nyha_class": "NYHA Class II",
        "discharge_vitals": {"bp_systolic": 148, "bp_diastolic": 92, "heart_rate": 82, "spo2": 97, "weight_kg": 82},
        "followup": {
            "date": "2026-06-12", "physician": "Dr. Suresh Pillai",
            "clinic": "Cardiology OPD",
            "investigations_ordered": ["Stress ECG", "Coronary Angiography"],
            "diet_instructions": "Low-fat, low-salt diet. Stop smoking immediately.",
            "activity_restrictions": "Avoid strenuous exertion until cardiologist review.",
            "emergency_return_criteria": ["Chest pain at rest", "Severe dyspnoea", "Syncope", "Diaphoresis"],
            "warnings": ["Risk of major adverse cardiac event if coronary artery disease left uninvestigated"],
        },
        "patient_acknowledgement": {"confirmed": True, "confirmed_by": "Vikram Singh", "relationship_to_patient": "Self", "timestamp": "2026-06-05 11:15"},
    },

    # ── Death — Massive STEMI with Cardiogenic Shock ──────────────────────────
    "Death": {
        "patient": {
            "name": "Mohan Prasad", "age": 72, "dob": "1954-09-21",
            "sex": "Male", "uhid": "DEMO-DTH-003", "admission_date": "2026-06-03",
            "discharge_date": "2026-06-04", "admission_mode": "Emergency",
            "referral_source": "Brought by family — collapsed at home",
            "attending_physician": "Dr. Kavitha Rajan", "attending_mci_reg": "MCI-TN-18823",
            "ward": "CCU", "bed_number": "CCU-01",
            "next_of_kin": {"name": "Rama Prasad", "relationship": "Son", "contact": "9123456789"},
        },
        "chief_complaint": "Sudden collapse with loss of consciousness — cardiac arrest in field",
        "duration_of_symptoms": "Acute onset — witnessed collapse",
        "hpi": (
            "Mr. Mohan Prasad, 72-year-old male, brought in by ambulance after witnessed cardiac arrest at home. "
            "ROSC achieved after 12 minutes of CPR at scene. "
            "On arrival: BP 70/40 mmHg, HR 110 bpm irregular, SpO2 78% on room air. "
            "ECG — massive anterior STEMI: ST elevation V1-V6 with LBBB morphology. "
            "Known diabetes, hypertension, CKD Stage 3. Previous CABG in 2018. "
            "Emergent intubation and mechanical ventilation commenced. "
            "Cardiology and ICU review: high-risk for PCI given haemodynamic instability. "
            "IABP placed. Patient deteriorated despite maximal vasopressor support. "
            "Death declared at 14:22 hrs on 2026-06-04."
        ),
        "pmh": {
            "comorbidities": ["Type 2 Diabetes Mellitus (20 years)", "Hypertension (18 years)", "CKD Stage 3", "Dyslipidaemia"],
            "prior_cardiac_interventions": ["CABG — 3-vessel (2018)"],
            "surgical_history": ["CABG 2018"],
            "allergies": [],
            "family_history": "Brother died of MI at age 68.",
            "smoking": "Ex-smoker (30 pack-years, quit 10 years ago)",
            "alcohol": "None",
        },
        "vitals_on_admission": {
            "bp_systolic": 70, "bp_diastolic": 40, "heart_rate": 110, "rhythm": "Irregular — AF with rapid ventricular response",
            "spo2": 78, "respiratory_rate": 28, "temperature": 36.4, "gcs": 6,
            "jvp": "Markedly elevated", "heart_sounds": "Distant heart sounds",
            "murmurs": "Unable to assess", "breath_sounds": "Bilateral crepitations", "pedal_oedema": "Bilateral 2+ pitting",
        },
        "labs": {
            "troponin_t_peak": 28.4, "troponin_unit": "ng/mL",
            "troponin_serial": [
                {"time": "2026-06-03 16:00", "value": 8.2, "unit": "ng/mL"},
                {"time": "2026-06-03 22:00", "value": 28.4, "unit": "ng/mL"},
            ],
            "bnp_or_ntprobnp": 4200, "hemoglobin": 10.8, "wbc": 18.4, "platelets": 142,
            "creatinine": 2.8, "egfr": 24, "urea": 82, "sodium": 134, "potassium": 5.6, "magnesium": 0.72,
            "hba1c": 9.2, "fasting_glucose": 288,
            "lipid_profile": {"ldl": None, "hdl": None, "triglycerides": None, "total_cholesterol": None},
            "inr": 1.8, "pt": 22.4,
        },
        "ecg_findings": "ST elevation 4–8 mm V1-V6. LBBB. Atrial fibrillation with rapid ventricular response.",
        "echo": {
            "lvef_percent": 18, "wall_motion_abnormality": "Extensive anterior and anterolateral akinesia",
            "valvular_findings": "Moderate MR", "pericardial_findings": "Small pericardial effusion",
        },
        "cath_lab": {
            "lad_stenosis_percent": None, "lcx_stenosis_percent": None, "rca_stenosis_percent": None,
            "intervention_performed": "IABP placement only — PCI not feasible due to haemodynamic instability",
            "stent_details": None, "timi_flow_post": None, "chest_xray_findings": "Pulmonary oedema. Massive cardiomegaly.",
        },
        "risk_scores": {"grace_score": 260, "grace_risk": "Very High", "timi_score": 7},
        "hospital_course": (
            "Despite ROSC and emergent resuscitation, patient remained in cardiogenic shock refractory to maximal vasopressor support "
            "(noradrenaline + dobutamine). IABP placed in CCU. Mechanical ventilation maintained. "
            "Repeat echo confirmed LVEF 18% with extensive wall motion abnormality. "
            "Family counselled regarding prognosis — very poor. End-of-life discussion held. "
            "Patient declared dead at 14:22 hrs on 04 June 2026. "
            "Cause of death: Cardiogenic shock secondary to massive anterior STEMI with prior CABG."
        ),
        "complications": ["Cardiogenic shock", "Respiratory failure", "Acute kidney injury on CKD"],
        "procedures": [
            {"name": "Intra-aortic balloon pump placement", "date": "2026-06-03", "operator": "Dr. Kavitha Rajan", "outcome": "Placed — insufficient haemodynamic support", "icd_pcs_code": None}
        ],
        "discharge_medications": [],
        "dapt_months": None,
        "stopped_medications": [],
        "discharge_diagnosis_clinical": "Massive Anterior STEMI with Cardiogenic Shock — Death",
        "icd10_codes": ["I21.0 — ST elevation myocardial infarction of anterior wall", "I50.1 — Left ventricular failure", "R57.0 — Cardiogenic shock"],
        "icd10_pcs_codes": [],
        "discharge_type": "Death",
        "condition_at_discharge": "Deceased — 14:22 hrs, 04 June 2026",
        "nyha_class": None,
        "discharge_vitals": {"bp_systolic": None, "bp_diastolic": None, "heart_rate": None, "spo2": None, "weight_kg": None},
        "followup": {
            "date": None, "physician": None, "clinic": None,
            "investigations_ordered": [],
            "diet_instructions": None, "activity_restrictions": None,
            "emergency_return_criteria": [],
            "warnings": ["Death certificate to be completed by Dr. Kavitha Rajan. Coroner notification per institutional protocol."],
        },
        "patient_acknowledgement": {"confirmed": False, "confirmed_by": "Rama Prasad", "relationship_to_patient": "Son", "timestamp": None},
    },

    # ── Referral — Decompensated Heart Failure for Tertiary Care ─────────────
    "Referral": {
        "patient": {
            "name": "Priya Nair", "age": 44, "dob": "1982-07-15",
            "sex": "Female", "uhid": "DEMO-REF-004", "admission_date": "2026-06-02",
            "discharge_date": "2026-06-05", "admission_mode": "Emergency",
            "referral_source": "Referred from district hospital",
            "attending_physician": "Dr. Arun Menon", "attending_mci_reg": "MCI-KL-31082",
            "ward": "Cardiology Ward A", "bed_number": "A-08",
            "next_of_kin": {"name": "Sunil Nair", "relationship": "Husband", "contact": "9847123456"},
        },
        "chief_complaint": "Progressive dyspnoea at rest, bilateral leg swelling — 5 days",
        "duration_of_symptoms": "5 days worsening",
        "hpi": (
            "Mrs. Priya Nair, 44-year-old female, presented with 5-day worsening dyspnoea now at rest, "
            "orthopnoea, bilateral leg swelling, and reduced urine output. "
            "Known dilated cardiomyopathy (diagnosed 2 years ago) with LVEF 28% on last echo. "
            "On optimal medical therapy. CXR — massive cardiomegaly with pulmonary oedema. "
            "Initial stabilisation with IV Lasix and O2. "
            "Cardiology review: patient requires ICD implantation and cardiac transplant evaluation "
            "not available at this centre — referral to Amrita Institute of Medical Sciences, Kochi."
        ),
        "pmh": {
            "comorbidities": ["Dilated Cardiomyopathy (2 years)", "NYHA Class III–IV Heart Failure"],
            "prior_cardiac_interventions": [],
            "surgical_history": [],
            "allergies": ["Sulfa drugs — rash"],
            "family_history": "No cardiac family history known.",
            "smoking": "None", "alcohol": "None",
        },
        "vitals_on_admission": {
            "bp_systolic": 98, "bp_diastolic": 64, "heart_rate": 112, "rhythm": "Sinus tachycardia",
            "spo2": 88, "respiratory_rate": 28, "temperature": 36.6, "gcs": 15,
            "jvp": "Elevated — 12 cmH2O", "heart_sounds": "S1 S2, loud S3 gallop",
            "murmurs": "Pansystolic murmur grade 3/6 at apex — MR", "breath_sounds": "Bilateral basal crepitations", "pedal_oedema": "Bilateral pitting 3+",
        },
        "labs": {
            "troponin_t_peak": 0.082, "troponin_unit": "ng/mL",
            "troponin_serial": [],
            "bnp_or_ntprobnp": 8800, "hemoglobin": 11.2, "wbc": 7.8, "platelets": 196,
            "creatinine": 1.6, "egfr": 44, "urea": 58, "sodium": 130, "potassium": 4.8, "magnesium": 0.78,
            "hba1c": None, "fasting_glucose": 88,
            "lipid_profile": {"ldl": 72, "hdl": 44, "triglycerides": 142, "total_cholesterol": 148},
            "inr": 1.4, "pt": 16.2,
        },
        "ecg_findings": "Sinus tachycardia 112 bpm. LBBB. QRS 160 ms. Prolonged QTc.",
        "echo": {
            "lvef_percent": 22, "wall_motion_abnormality": "Global hypokinesia",
            "valvular_findings": "Severe MR — functional. Moderate TR.",
            "pericardial_findings": "No effusion",
        },
        "cath_lab": {
            "lad_stenosis_percent": None, "lcx_stenosis_percent": None, "rca_stenosis_percent": None,
            "intervention_performed": "None — non-ischaemic cardiomyopathy",
            "stent_details": None, "timi_flow_post": None,
            "chest_xray_findings": "Massive cardiomegaly. Pulmonary oedema. Bilateral pleural effusions.",
        },
        "risk_scores": {"grace_score": None, "grace_risk": None, "timi_score": None},
        "hospital_course": (
            "IV furosemide 80 mg BD commenced — 3.2 litres diuresed in first 24 hours. "
            "Dobutamine infusion initiated for low-output state. "
            "Sacubitril-valsartan dose optimised. Spironolactone and empagliflozin added. "
            "CRT-D evaluation recommended — beyond capabilities of current centre. "
            "Cardiac transplant referral: patient listed for evaluation at Amrita IMS, Kochi. "
            "Patient stabilised on day 3 — tolerated upright sitting. "
            "Referral arranged with transport team. Documents prepared."
        ),
        "complications": ["Acute-on-chronic kidney injury"],
        "procedures": [],
        "discharge_medications": [
            {"drug_name_source": "Vymada", "dose": "49/51 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": "ARNI — monitor BP and renal function"},
            {"drug_name_source": "Concor", "dose": "3.125 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Aldactone", "dose": "25 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Dytor", "dose": "20 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Forxiga", "dose": "10 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Warf", "dose": "3 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": "Anticoagulant — INR monitoring required"},
            {"drug_name_source": "Potklor", "dose": "1200 mg", "frequency": "Twice daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
        ],
        "dapt_months": None,
        "stopped_medications": ["Furosemide IV converted to Dytor oral on discharge"],
        "discharge_diagnosis_clinical": "Decompensated Dilated Cardiomyopathy with NYHA Class IV Heart Failure",
        "icd10_codes": ["I42.0 — Dilated cardiomyopathy", "I50.1 — Left ventricular failure"],
        "icd10_pcs_codes": [],
        "discharge_type": "Referral",
        "condition_at_discharge": "Partially stabilised. Transferred to tertiary centre for CRT-D and transplant evaluation.",
        "nyha_class": "NYHA Class III (improved from IV)",
        "discharge_vitals": {"bp_systolic": 102, "bp_diastolic": 68, "heart_rate": 84, "spo2": 95, "weight_kg": 58},
        "followup": {
            "date": "2026-06-10", "physician": "Cardiology Team — Amrita IMS Kochi",
            "clinic": "Heart Failure and Transplant Clinic",
            "investigations_ordered": ["Echo", "6-minute walk test", "BNP", "Renal function", "INR"],
            "diet_instructions": "Strict 1.5 L fluid restriction daily. Low-sodium diet (<2 g/day). Daily weight monitoring.",
            "activity_restrictions": "Strict bed rest during transit. Minimal exertion until specialist review.",
            "emergency_return_criteria": ["Acute dyspnoea", "Weight gain >1 kg in 24h", "Syncope", "Bleeding"],
            "warnings": ["INR target 2–3. Warfarin dose adjusted at receiving centre. Do not alter medications without cardiologist review."],
        },
        "patient_acknowledgement": {"confirmed": True, "confirmed_by": "Sunil Nair", "relationship_to_patient": "Husband", "timestamp": "2026-06-05 10:00"},
    },

    # ── DAMA — AF with RVR, Self-Requested Early Discharge ───────────────────
    "DAMA": {
        "patient": {
            "name": "Arjun Malhotra", "age": 61, "dob": "1965-02-28",
            "sex": "Male", "uhid": "DEMO-DAMA-005", "admission_date": "2026-06-05",
            "discharge_date": "2026-06-06", "admission_mode": "Emergency",
            "referral_source": "Self-referral",
            "attending_physician": "Dr. Meera Iyer", "attending_mci_reg": "MCI-MH-50312",
            "ward": "Cardiology Ward C", "bed_number": "C-03",
            "next_of_kin": {"name": "Ritu Malhotra", "relationship": "Wife", "contact": "9922334455"},
        },
        "chief_complaint": "Palpitations with fast heart rate — sudden onset 6 hours ago",
        "duration_of_symptoms": "6 hours",
        "hpi": (
            "Mr. Arjun Malhotra, 61-year-old male, presented with sudden-onset palpitations and mild dyspnoea. "
            "No chest pain. No syncope. ECG confirmed AF with RVR at 148 bpm. "
            "Commenced on rate control with IV diltiazem. Rhythm converted to sinus after 4 hours. "
            "Thyroid function normal. Echocardiogram performed — LVEF 55%, no structural abnormality. "
            "Anticoagulation initiated with rivaroxaban. Patient requested discharge on day 2, "
            "citing work commitments. Medical team advised minimum 48-hour observation and rhythm monitoring. "
            "Patient accepted risks and signed DAMA form after hospital administrator co-signature obtained."
        ),
        "pmh": {
            "comorbidities": ["Hypertension (4 years)", "Paroxysmal AF (first episode)"],
            "prior_cardiac_interventions": [],
            "surgical_history": [],
            "allergies": [],
            "family_history": "No cardiac family history.",
            "smoking": "Non-smoker", "alcohol": "Social — 2–3 units/week",
        },
        "vitals_on_admission": {
            "bp_systolic": 136, "bp_diastolic": 88, "heart_rate": 148, "rhythm": "Atrial fibrillation with rapid ventricular response",
            "spo2": 96, "respiratory_rate": 20, "temperature": 36.9, "gcs": 15,
            "jvp": "Not elevated", "heart_sounds": "Irregularly irregular",
            "murmurs": "None", "breath_sounds": "Clear", "pedal_oedema": "Absent",
        },
        "labs": {
            "troponin_t_peak": 0.012, "troponin_unit": "ng/mL",
            "troponin_serial": [],
            "bnp_or_ntprobnp": 210, "hemoglobin": 14.8, "wbc": 7.2, "platelets": 280,
            "creatinine": 0.88, "egfr": 94, "urea": 22, "sodium": 141, "potassium": 4.0, "magnesium": 0.92,
            "hba1c": None, "fasting_glucose": 104,
            "lipid_profile": {"ldl": 118, "hdl": 52, "triglycerides": 140, "total_cholesterol": 192},
            "inr": None, "pt": None,
        },
        "ecg_findings": "Initial: AF with RVR at 148 bpm. Post-cardioversion: Sinus rhythm 72 bpm, normal axis, no ST changes.",
        "echo": {
            "lvef_percent": 55, "wall_motion_abnormality": "None",
            "valvular_findings": "Trivial MR only", "pericardial_findings": "No effusion",
        },
        "cath_lab": {
            "lad_stenosis_percent": None, "lcx_stenosis_percent": None, "rca_stenosis_percent": None,
            "intervention_performed": None, "stent_details": None, "timi_flow_post": None,
            "chest_xray_findings": "Normal cardiac silhouette and lung fields.",
        },
        "risk_scores": {"grace_score": None, "grace_risk": None, "timi_score": None},
        "hospital_course": (
            "IV diltiazem 20 mg over 2 minutes — rate controlled within 2 hours. "
            "Spontaneous cardioversion to sinus rhythm at hour 4. "
            "Rivaroxaban initiated (CHA₂DS₂-VASc score 2). "
            "Holter monitor planned for 24-hour rhythm surveillance. "
            "Patient insisted on discharge on day 2 — risks of early discharge explained. "
            "DAMA form completed with hospital administrator co-signature. "
            "Discharged in sinus rhythm."
        ),
        "complications": [],
        "procedures": [],
        "discharge_medications": [
            {"drug_name_source": "Xarelto", "dose": "20 mg", "frequency": "Once daily with evening meal", "route": "Oral", "duration": "Ongoing", "high_risk_flag": "Anticoagulant — bleeding risk"},
            {"drug_name_source": "Concor", "dose": "5 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Cosart", "dose": "50 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
            {"drug_name_source": "Pan", "dose": "40 mg", "frequency": "Once daily", "route": "Oral", "duration": "Ongoing", "high_risk_flag": None},
        ],
        "dapt_months": None,
        "stopped_medications": ["IV Dilzem (discontinued on cardioversion)"],
        "discharge_diagnosis_clinical": "Paroxysmal Atrial Fibrillation with Rapid Ventricular Response — DAMA",
        "icd10_codes": ["I48.0 — Paroxysmal atrial fibrillation"],
        "icd10_pcs_codes": [],
        "discharge_type": "DAMA",
        "condition_at_discharge": "Sinus rhythm restored. Patient in sinus at discharge. DAMA.",
        "nyha_class": "NYHA Class I",
        "discharge_vitals": {"bp_systolic": 128, "bp_diastolic": 80, "heart_rate": 72, "spo2": 98, "weight_kg": 86},
        "followup": {
            "date": "2026-06-13", "physician": "Dr. Meera Iyer",
            "clinic": "Cardiology OPD — Rhythm Clinic",
            "investigations_ordered": ["24-hour Holter", "Thyroid Function Test", "Fasting Lipids"],
            "diet_instructions": "Avoid caffeine and alcohol. Low-salt diet.",
            "activity_restrictions": "Avoid driving until Holter review confirms sustained sinus rhythm.",
            "emergency_return_criteria": ["Recurrence of fast palpitations", "Dyspnoea", "Syncope", "Bleeding"],
            "warnings": ["Rivaroxaban must not be missed — take at same time daily with food. Do not stop without cardiology advice."],
        },
        "patient_acknowledgement": {"confirmed": True, "confirmed_by": "Arjun Malhotra", "relationship_to_patient": "Self", "timestamp": "2026-06-06 09:30"},
    },
}

# Assign synthetic HADM IDs for demo routing
_DEMO_HADM_IDS: dict[str, int] = {
    "Standard": 9900001,
    "LAMA":     9900002,
    "Death":    9900003,
    "Referral": 9900004,
    "DAMA":     9900005,
}

_HADM_TO_TYPE: dict[int, str] = {v: k for k, v in _DEMO_HADM_IDS.items()}


def get_demo_case(discharge_type: str) -> dict:
    """Return the synthetic Pass 1 JSON dict for the given discharge type."""
    case = _DEMO_CASES.get(discharge_type)
    if not case:
        raise ValueError(f"No demo case for discharge_type={discharge_type!r}. "
                         f"Valid values: {list(_DEMO_CASES)}")
    return dict(case)


def get_demo_case_by_hadm(hadm_id: int) -> dict | None:
    """Return demo case dict by synthetic HADM ID, or None if not a demo patient."""
    dt = _HADM_TO_TYPE.get(hadm_id)
    return get_demo_case(dt) if dt else None


def is_demo_hadm(hadm_id: int) -> bool:
    """True if hadm_id belongs to a synthetic demo patient."""
    return hadm_id in _HADM_TO_TYPE


def list_demo_cases() -> list[dict]:
    """Metadata list for all demo cases (used by admin panel)."""
    return [
        {
            "discharge_type": dt,
            "hadm_id": _DEMO_HADM_IDS[dt],
            "patient_name": _DEMO_CASES[dt]["patient"]["name"],
            "primary_diagnosis": _DEMO_CASES[dt]["discharge_diagnosis_clinical"],
        }
        for dt in _DEMO_CASES
    ]

"""
Synthetic OPD (never-admitted) patients
========================================
Patients who came in for a consultation/test but were never a formal
inpatient admission. Reserved hadm_id range 9910001-9910005 - distinct
from real MIMIC admissions (>=20,000,000) and the discharge-summary demo
range used by synthetic_demo.py (9900001-9900005).

Seeded idempotently at backend startup (see main.py). A mix of billing
phases so the OPD Patients tab has both "Awaiting Final Bill" and
"Bill Finalized" rows to demo immediately.
"""

OPD_PATIENTS: list[dict] = [
    {
        "hadm_id": 9910001, "patient_name": "Kavita Rao", "gender": "F", "anchor_age": 34,
        "primary_diagnosis_title": "OPD Consultation — Routine ECG & Lipid Profile",
        "visit_date": "2026-06-20",
        "billing_phase": "paid", "insurance_co": None, "payment_mode": "Self-pay", "policy_number": None,
        "expected_est": 2400, "actual_charges": 2400, "insurance_paid": 0, "advance_paid": 2400, "balance_due": 0,
        "line_items": [
            {"name": "Consultation Fee", "amount": 800},
            {"name": "Diagnostics / Tests", "amount": 1200},
            {"name": "Medicines", "amount": 400},
        ],
    },
    {
        "hadm_id": 9910002, "patient_name": "Suresh Iyer", "gender": "M", "anchor_age": 61,
        "primary_diagnosis_title": "OPD Consultation — Echocardiography Follow-up",
        "visit_date": "2026-06-25",
        "billing_phase": "paid", "insurance_co": "Star Health", "payment_mode": "Cashless",
        "policy_number": "SH-2025-11023",
        "expected_est": 6800, "actual_charges": 6800, "insurance_paid": 6800, "advance_paid": 0, "balance_due": 0,
        "line_items": [
            {"name": "Consultation Fee", "amount": 1500},
            {"name": "Diagnostics / Tests", "amount": 4500},
            {"name": "Medicines", "amount": 800},
        ],
    },
    {
        "hadm_id": 9910003, "patient_name": "Anjali Deshpande", "gender": "F", "anchor_age": 48,
        "primary_diagnosis_title": "OPD Consultation — Holter Monitor Review",
        "visit_date": "2026-07-01",
        "billing_phase": "initial_estimate", "insurance_co": "HDFC Ergo", "payment_mode": "Reimbursement",
        "policy_number": "HE-2024-88213",
        "expected_est": 5200, "actual_charges": None, "insurance_paid": None, "advance_paid": None, "balance_due": None,
        "line_items": [
            {"name": "Consultation Fee", "amount": 1200},
            {"name": "Diagnostics / Tests", "amount": 3500},
            {"name": "Medicines", "amount": 500},
        ],
    },
    {
        "hadm_id": 9910004, "patient_name": "Mahesh Patil", "gender": "M", "anchor_age": 55,
        "primary_diagnosis_title": "OPD Consultation — Minor Procedure (Holter Placement)",
        "visit_date": "2026-07-03",
        "billing_phase": "initial_estimate", "insurance_co": None, "payment_mode": "Self-pay", "policy_number": None,
        "expected_est": 4100, "actual_charges": None, "insurance_paid": None, "advance_paid": None, "balance_due": None,
        "line_items": [
            {"name": "Consultation Fee", "amount": 1000},
            {"name": "Diagnostics / Tests", "amount": 2600},
            {"name": "Medicines", "amount": 500},
        ],
    },
    {
        "hadm_id": 9910005, "patient_name": "Geeta Krishnan", "gender": "F", "anchor_age": 39,
        "primary_diagnosis_title": "OPD Consultation — Cardiology Follow-up & Stress Test",
        "visit_date": "2026-07-05",
        "billing_phase": "initial_estimate", "insurance_co": "ICICI Lombard", "payment_mode": "Cashless",
        "policy_number": "IL-2025-30044",
        "expected_est": 7800, "actual_charges": None, "insurance_paid": None, "advance_paid": None, "balance_due": None,
        "line_items": [
            {"name": "Consultation Fee", "amount": 1500},
            {"name": "Diagnostics / Tests", "amount": 5500},
            {"name": "Medicines", "amount": 800},
        ],
    },
]

_OPD_HADM_IDS = {p["hadm_id"] for p in OPD_PATIENTS}


def is_opd_hadm(hadm_id: int) -> bool:
    return hadm_id in _OPD_HADM_IDS

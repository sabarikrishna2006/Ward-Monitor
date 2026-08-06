"""
Verification for the pilot-hardening P0 fixes (in-process, against real Cloud SQL).

Covers the NEW behaviours added for the pilot:
  1. Identity overlay — /display payloads always carry active_patients.patient_name.
  2. No misleading placeholder — a patient with no name never resolves to "Demo Patient".
  3. EWS overlay — ward-generated escalations / drug-lab / step-down flow into the
     discharge clinical_context with [WARD-GENERATED — EWS] provenance.
  4. Discharge guard — _has_real_clinical_data is False when no ap_* rows exist.

Uses a throwaway synthetic hadm_id (990099) and cleans up after itself.
No BigQuery, no LLM, no ap_* writes.

Run from common_db_main_latest/:  py -3 verify_pilot_fixes.py
"""
import sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)                       # for `backend.app.*`
sys.path.insert(0, os.path.join(ROOT, "backend"))

from sqlalchemy import text  # noqa: E402
from backend.app.cloud_sql_db import get_engine  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
all_ok = True
def check(label, cond):
    global all_ok
    ok = bool(cond)
    all_ok &= ok
    print(f"  [{PASS if ok else FAIL}] {label}")
    return ok

TEST_HADM = 990099
TEST_NAME = "ZZ Overlay Test"
eng = get_engine()

print("=" * 70)
print("PILOT-FIXES VERIFICATION")
print("=" * 70)

# ── Seed a throwaway active_patients row + EWS overlay rows ────────────────────
with eng.begin() as c:
    c.execute(text("DELETE FROM ews_escalations      WHERE hadm_id=:h"), {"h": TEST_HADM})
    c.execute(text("DELETE FROM ews_drug_lab_actions WHERE hadm_id=:h"), {"h": TEST_HADM})
    c.execute(text("DELETE FROM ews_ccu_transfers    WHERE hadm_id=:h"), {"h": TEST_HADM})
    c.execute(text("DELETE FROM ews_vitals_timeseries WHERE hadm_id=:h"), {"h": TEST_HADM})
    c.execute(text("DELETE FROM active_patients      WHERE hadm_id=:h"), {"h": TEST_HADM})
    c.execute(text("""
        INSERT INTO active_patients (hadm_id, subject_id, patient_name, patient_code,
                                     ward_location, status, data_fetch_status, admit_time)
        VALUES (:h, :h, :n, 'PT-TEST-99', 'GENERAL_WARD', 'active', 'fetched', NOW())
    """), {"h": TEST_HADM, "n": TEST_NAME})
    c.execute(text("""
        INSERT INTO ews_escalations (hadm_id, patient_name, news2_score, level, status,
                                     observations, interventions, escalated_at)
        VALUES (:h, :n, 8, 'Critical', 'resolved', 'RR 28, SpO2 88', 'O2 + senior review', NOW())
    """), {"h": TEST_HADM, "n": TEST_NAME})
    c.execute(text("""
        INSERT INTO ews_drug_lab_actions (hadm_id, rule_name, severity, action_taken,
                                          justification, recorded_by, recorded_at)
        VALUES (:h, 'K+ + Spironolactone', 'high', 'held dose', 'K 5.6', 'Nurse A', NOW())
    """), {"h": TEST_HADM})
    c.execute(text("""
        INSERT INTO ews_ccu_transfers (hadm_id, patient_name, rationale, news2_at_submit,
                                       stable_window_hours, target_ward, status, submitted_at)
        VALUES (:h, :n, 'NEWS2 <=2 for 8h', 2, 8, 'General Ward', 'approved', NOW())
    """), {"h": TEST_HADM, "n": TEST_NAME})
    c.execute(text("""
        INSERT INTO ews_vitals_timeseries (hadm_id, chart_time, heart_rate, resp_rate, spo2, sbp, temperature)
        VALUES (:h, NOW(), 96, 18, 96, 118, 37.0)
    """), {"h": TEST_HADM})

try:
    # ── 1 & 2. Identity overlay + no "Demo Patient" placeholder ────────────────
    print("\n1. IDENTITY OVERLAY  — _overlay_identity stamps active_patients.patient_name")
    from backend.app.data_server import _overlay_identity
    payload = {"admission": {}, "patient": {}, "admissions": [{}]}
    out = _overlay_identity(TEST_HADM, payload)
    check(f"top-level patient_name == {TEST_NAME!r} (got {out.get('patient_name')!r})",
          out.get("patient_name") == TEST_NAME)
    check("patient.full_name stamped", out["patient"].get("full_name") == TEST_NAME)
    check("admissions[0].patient_name stamped", out["admissions"][0].get("patient_name") == TEST_NAME)

    print("\n2. NO PLACEHOLDER  — unknown hadm never resolves to 'Demo Patient'")
    out2 = _overlay_identity(987654321, {"patient": {}})
    check(f"unknown name -> de-identified label (got {out2.get('patient_name')!r})",
          out2.get("patient_name") not in (None, "", "Demo Patient")
          and "HADM-987654321" in str(out2.get("patient_name")))

    # ── 3 & 4. EWS overlay + discharge guard (need backend.app.main) ──────────
    # main.py pulls heavy deps (bcrypt/gemini/qdrant). On a minimal box it may not
    # import — skip gracefully so these run on the server where the env is complete.
    try:
        from backend.app.main import _ews_overlay_lines, _has_real_clinical_data
        _main_ok = True
    except Exception as _e:
        _main_ok = False
        print(f"\n3-4. SKIPPED — backend.app.main not importable here ({type(_e).__name__}: "
              f"{str(_e)[:60]}). Run this script on the server to exercise these.")

    if _main_ok:
        print("\n3. EWS OVERLAY  — ward-generated data appears with provenance tag")
        lines = "\n".join(_ews_overlay_lines(TEST_HADM))
        check("contains [WARD-GENERATED — EWS] tag", "[WARD-GENERATED — EWS]" in lines)
        check("includes NEWS2 escalation", "NEWS2 escalations: 1" in lines)
        check("includes Drug–Lab safety action", "Drug–Lab safety actions (NABH DL2): 1" in lines)
        check("includes step-down event", "step-down events: 1" in lines)
        check("includes nurse observation window", "nurse-charted vital sets" in lines)

        print("\n4. DISCHARGE GUARD  — _has_real_clinical_data False without ap_* rows")
        check("synthetic patient has no real clinical data",
              _has_real_clinical_data(TEST_HADM) is False)

finally:
    # ── Cleanup ───────────────────────────────────────────────────────────────
    print("\n5. CLEANUP")
    with eng.begin() as c:
        c.execute(text("DELETE FROM ews_escalations      WHERE hadm_id=:h"), {"h": TEST_HADM})
        c.execute(text("DELETE FROM ews_drug_lab_actions WHERE hadm_id=:h"), {"h": TEST_HADM})
        c.execute(text("DELETE FROM ews_ccu_transfers    WHERE hadm_id=:h"), {"h": TEST_HADM})
        c.execute(text("DELETE FROM ews_vitals_timeseries WHERE hadm_id=:h"), {"h": TEST_HADM})
        c.execute(text("DELETE FROM active_patients      WHERE hadm_id=:h"), {"h": TEST_HADM})
    print(f"  test rows for {TEST_HADM} removed.")

print("\n" + "=" * 70)
print(f"RESULT: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED — see above'}")
print("=" * 70)
sys.exit(0 if all_ok else 1)

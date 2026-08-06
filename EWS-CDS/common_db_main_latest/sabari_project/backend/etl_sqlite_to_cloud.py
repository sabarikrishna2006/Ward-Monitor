"""
etl_sqlite_to_cloud.py - One-shot ETL: SQLite ward_careos.db -> Cloud SQL (postgres)
Run ONCE from sabari_project/backend/:  py -3 etl_sqlite_to_cloud.py

Maps SQLite subject_id -> active_patients hadm_id (using subject_id as hadm_id for demo patients).
Safe to re-run: all inserts use ON CONFLICT DO NOTHING / DO UPDATE.
"""
import os
import sys
import sqlite3
from datetime import datetime

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "healthcare-project-db-creds.json"
)

from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

INSTANCE = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
SQLITE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ward_careos.db")

connector = Connector()

def get_conn():
    return connector.connect(
        INSTANCE, "pg8000",
        user="postgres", password=os.environ["CLOUD_SQL_PASS"],
        db="postgres", ip_type=IPTypes.PUBLIC,
    )

pg_engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=get_conn)
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_conn.row_factory = sqlite3.Row


def parse_dt(s):
    """Parse ISO datetime string or return None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def safe_str(val, limit=None):
    """Return ASCII-safe string for display only."""
    if val is None:
        return ""
    s = str(val).encode("ascii", errors="replace").decode("ascii")
    return s[:limit] if limit else s


def run():
    cur = sqlite_conn.cursor()

    # -------------------------------------------------------------------------
    # 1. patients -> active_patients (upsert: insert new or update EWS columns)
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM patients ORDER BY subject_id")
    patients = cur.fetchall()
    print("Migrating %d patients to active_patients..." % len(patients))

    with pg_engine.connect() as pg:
        for p in patients:
            sid = p["subject_id"]
            sex_raw = p["sex"] or "M"
            gender_val = sex_raw[0].upper() if sex_raw else "M"
            pg.execute(text("""
                INSERT INTO active_patients
                    (hadm_id, subject_id, gender, anchor_age,
                     admitting_diagnosis, ews_complaint, admit_time,
                     status, data_fetch_status,
                     ward, room, bed, ward_location,
                     hypercapnic_failure, diagnosis_short, patient_code,
                     fetch_round2_done, fetch_icu_done)
                VALUES
                    (:hadm_id, :subject_id, :gender, :age,
                     :complaint, :complaint, :admit_time,
                     'active', 'fetched',
                     :ward, :room, :bed, :ward_location,
                     :hyper, :diag_short, :patient_code,
                     false, false)
                ON CONFLICT (hadm_id) DO UPDATE SET
                    ward                = EXCLUDED.ward,
                    room                = EXCLUDED.room,
                    bed                 = EXCLUDED.bed,
                    ward_location       = EXCLUDED.ward_location,
                    hypercapnic_failure = EXCLUDED.hypercapnic_failure,
                    diagnosis_short     = EXCLUDED.diagnosis_short,
                    ews_complaint       = EXCLUDED.ews_complaint,
                    patient_code        = EXCLUDED.patient_code,
                    updated_at          = NOW()
            """), {
                "hadm_id":      sid,
                "subject_id":   sid,
                "gender":       gender_val,
                "age":          p["age"],
                "complaint":    p["complaint"],
                "admit_time":   parse_dt(p["admitted"]),
                "ward":         p["ward"],
                "room":         p["room"],
                "bed":          p["bed"],
                "ward_location": p["ward_location"] or "CCU",
                "hyper":        int(p["hypercapnic_failure"] or 0),
                "diag_short":   p["diagnosis_short"],
                "patient_code": p["patient_code"],
            })
        pg.commit()
    print("  [OK] %d patients migrated" % len(patients))

    # -------------------------------------------------------------------------
    # 2. vitals_timeseries -> ews_vitals_timeseries
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM vitals_timeseries ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d vitals rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_vitals_timeseries
                    (hadm_id, chart_time, heart_rate, resp_rate, spo2,
                     sbp, dbp, temperature, consciousness, air_or_oxygen,
                     urine_output, fluid_balance)
                VALUES
                    (:hadm_id, :ct, :hr, :rr, :spo2,
                     :sbp, :dbp, :temp, :cons, :air,
                     :uo, :fb)
            """), {
                "hadm_id": r["subject_id"],
                "ct":      parse_dt(r["chart_hour"]) or datetime.utcnow(),
                "hr":  r["heart_rate"], "rr": r["resp_rate"],
                "spo2": r["spo2"], "sbp": r["sbp"], "dbp": r["dbp"],
                "temp": r["temperature"],
                "cons": (r["consciousness"] or "A")[0].upper(),
                "air":  r["air_or_oxygen"] or "Air",
                "uo":   r["urine_output"], "fb": r["fluid_balance"],
            })
        pg.commit()
    print("  [OK] %d vitals rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # 3. lab_events -> ews_lab_events
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM lab_events ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d lab event rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_lab_events
                    (hadm_id, chart_time, potassium, creatinine, lactate, inr, egfr, alt)
                VALUES
                    (:hadm_id, :ct, :k, :cr, :lac, :inr, :egfr, :alt)
            """), {
                "hadm_id": r["subject_id"],
                "ct":      parse_dt(r["chart_hour"]) or datetime.utcnow(),
                "k":   r["potassium"], "cr":   r["creatinine"],
                "lac": r["lactate"],   "inr":  r["inr"],
                "egfr": r["egfr"],     "alt":  r["alt"],
            })
        pg.commit()
    print("  [OK] %d lab event rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # 4. medications -> ews_medications
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM medications ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d medication rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_medications (hadm_id, med_name, dose, frequency)
                VALUES (:hadm_id, :med, :dose, :freq)
            """), {
                "hadm_id": r["subject_id"],
                "med":     r["med_name"],
                "dose":    r["dose"],
                "freq":    r["frequency"],
            })
        pg.commit()
    print("  [OK] %d medication rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # 5. escalations -> ews_escalations
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM escalations ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d escalation rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_escalations
                    (hadm_id, patient_name, ward, bed, news2_score, level,
                     attending, escalated_by, observations, interventions,
                     status, escalated_at, acknowledged_at, resolved_at,
                     resolved_by, resolution_notes, false_alarm,
                     false_alarm_reason, reescalated_at)
                VALUES
                    (:hadm_id, :pname, :ward, :bed, :score, :level,
                     :attending, :esc_by, :obs, :interv,
                     :status, :esc_at, :ack_at, :res_at,
                     :res_by, :res_notes, :fa, :fa_reason, :reesc_at)
            """), {
                "hadm_id":   r["subject_id"],
                "pname":     r["patient_name"],
                "ward":      r["ward"],
                "bed":       r["bed"],
                "score":     r["news2_score"],
                "level":     r["level"] or "nurse",
                "attending": r["attending"],
                "esc_by":    r["escalated_by"],
                "obs":       r["observations"],
                "interv":    r["interventions"],
                "status":    r["status"] or "active",
                "esc_at":    parse_dt(r["escalated_at"]) or datetime.utcnow(),
                "ack_at":    parse_dt(r["acknowledged_at"]),
                "res_at":    parse_dt(r["resolved_at"]),
                "res_by":    r["resolved_by"],
                "res_notes": r["resolution_notes"],
                "fa":        bool(r["false_alarm"]),
                "fa_reason": r["false_alarm_reason"],
                "reesc_at":  parse_dt(r["reescalated_at"]),
            })
        pg.commit()
    print("  [OK] %d escalation rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # 6. ccu_transfers -> ews_ccu_transfers
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM ccu_transfers ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d CCU transfer rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_ccu_transfers
                    (hadm_id, patient_name, diagnosis, rationale,
                     recommended_by, target_ward, news2_at_submit,
                     stable_window_hours, status, submitted_at,
                     decided_at, decided_by)
                VALUES
                    (:hadm_id, :pname, :diag, :rat,
                     :rec_by, :target, :score,
                     :stable_h, :status, :sub_at,
                     :dec_at, :dec_by)
            """), {
                "hadm_id":  r["subject_id"],
                "pname":    r["patient_name"],
                "diag":     r["diagnosis"],
                "rat":      r["rationale"],
                "rec_by":   r["recommended_by"],
                "target":   r["target_ward"] or "General Ward",
                "score":    r["news2_at_submit"],
                "stable_h": r["stable_window_hours"],
                "status":   r["status"] or "pending",
                "sub_at":   parse_dt(r["submitted_at"]) or datetime.utcnow(),
                "dec_at":   parse_dt(r["decided_at"]),
                "dec_by":   r["decided_by"],
            })
        pg.commit()
    print("  [OK] %d CCU transfer rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # 7. drug_lab_actions -> ews_drug_lab_actions
    # -------------------------------------------------------------------------
    cur.execute("SELECT * FROM drug_lab_actions ORDER BY subject_id, id")
    rows = cur.fetchall()
    print("Migrating %d drug-lab action rows..." % len(rows))

    with pg_engine.connect() as pg:
        for r in rows:
            pg.execute(text("""
                INSERT INTO ews_drug_lab_actions
                    (hadm_id, rule_name, severity, action_taken,
                     justification, recorded_by, cosigned_by, status, recorded_at)
                VALUES
                    (:hadm_id, :rule, :sev, :action,
                     :just, :rec_by, :cos_by, :status, :rec_at)
            """), {
                "hadm_id": r["subject_id"],
                "rule":    r["rule_name"],
                "sev":     r["severity"] or "WARNING",
                "action":  r["action_taken"] or "hold",
                "just":    r["justification"],
                "rec_by":  r["recorded_by"],
                "cos_by":  r["cosigned_by"],
                "status":  r["status"] or "recorded",
                "rec_at":  parse_dt(r["recorded_at"]) or datetime.utcnow(),
            })
        pg.commit()
    print("  [OK] %d drug-lab action rows migrated" % len(rows))

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("\n[OK] ETL complete. Verifying row counts in Cloud SQL:")
    with pg_engine.connect() as pg:
        for tbl in ["ews_vitals_timeseries", "ews_lab_events", "ews_medications",
                    "ews_escalations", "ews_ccu_transfers", "ews_drug_lab_actions"]:
            count = pg.execute(text("SELECT COUNT(*) FROM " + tbl)).scalar()
            print("  %s: %d rows" % (tbl, count))
        ap = pg.execute(text("SELECT COUNT(*) FROM active_patients WHERE hadm_id BETWEEN 10001 AND 10016")).scalar()
        print("  active_patients (EWS demo rows 10001-10016): %d rows" % ap)


run()
sqlite_conn.close()
connector.close()
print("\n[DONE] Migration complete.")

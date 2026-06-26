"""
Cloud SQL App Database
======================
All app-level tables read/write directly to Cloud SQL (PostgreSQL).

Tables used:
  app_users, app_reset_tokens, app_encounters, app_summaries,
  app_uploaded_files, app_clinical_rows, app_audit_log, app_settings

Run backend/app/migrations/001_new_tables.sql once before first use.
"""
import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from .cloud_sql_db import get_engine

log = logging.getLogger(__name__)

# Maps display labels → schema keys for file_type
_LABEL_TO_KEY: Dict[str, str] = {
    "Labs": "labs",
    "Medications": "meds",
    "Clinical Notes": "notes",
    "Diagnoses": "diagnoses",
    "Procedures": "procedures",
    "ICU Events": "icu",
    "Microbiology": "microbiology",
    "Transfers": "transfers",
    "ICU Stays": "icustays",
    "Pharmacy": "pharmacy",
    "Physician Orders": "poe",
    "Fluids I/O": "fluids",
    "Vitals": "vitals",
}

_FILE_TYPE_TO_TABLE: Dict[str, str] = {
    "labs": "labs", "meds": "meds", "notes": "notes",
    "diagnoses": "diagnoses", "procedures": "procedures",
    "icu": "icu", "microbiology": "microbiology",
    "transfers": "transfers", "icustays": "icustays",
    "pharmacy": "pharmacy", "poe": "poe", "fluids": "fluids",
    "vitals": "vitals",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _row_to_dict(row) -> Optional[Dict]:
    if row is None:
        return None
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
    return d


def _sanitize_user(u: Dict) -> Dict:
    return {k: v for k, v in u.items() if k != "password_hash"}


def _normalize_file_type(ft: str) -> str:
    if ft in _LABEL_TO_KEY:
        return _LABEL_TO_KEY[ft]
    key = ft.lower().replace(" ", "_")
    return key if key in _FILE_TYPE_TO_TABLE else "labs"


# ═══════════════════════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════════════════════

def create_user(email: str, password_hash: str, role: str, full_name: str = "") -> Dict:
    uid = _new_id()
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO app_users (id, hospital_email, password_hash, role, full_name)
            VALUES (:id, :email, :ph, :role, :fn)
        """), {"id": uid, "email": email, "ph": password_hash, "role": role, "fn": full_name})
        row = conn.execute(
            text("SELECT * FROM app_users WHERE id = :id"), {"id": uid}
        ).fetchone()
    return _sanitize_user(_row_to_dict(row))


def get_user_by_email_role(email: str, role: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_users WHERE hospital_email = :e AND role = :r AND is_active = TRUE"),
            {"e": email, "r": role}
        ).fetchone()
    return _row_to_dict(row)  # includes password_hash — needed by login


def get_user_by_id(uid: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_users WHERE id = :id"), {"id": uid}
        ).fetchone()
    return _row_to_dict(row)  # includes password_hash — needed by reset-password


def update_user(uid: str, fields: Dict) -> Optional[Dict]:
    allowed = {"password_hash", "full_name", "session_token", "is_active", "role"}
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return get_user_by_id(uid)
    params = {k: v for k, v in fields.items() if k in allowed}
    params["id"] = uid
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE app_users SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = :id"),
            params
        )
        row = conn.execute(text("SELECT * FROM app_users WHERE id = :id"), {"id": uid}).fetchone()
    return _row_to_dict(row)


def list_users(role: Optional[str] = None) -> List[Dict]:
    sql = "SELECT * FROM app_users WHERE is_active = TRUE"
    params: Dict = {}
    if role:
        sql += " AND role = :role"
        params["role"] = role
    sql += " ORDER BY full_name"
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [_sanitize_user(_row_to_dict(r)) for r in rows]


def user_exists(email: str) -> bool:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM app_users WHERE hospital_email = :e AND is_active = TRUE LIMIT 1"),
            {"e": email}
        ).fetchone()
    return row is not None


# ═══════════════════════════════════════════════════════════════════════════════
# RESET TOKENS  (app_reset_tokens — added in migration 001)
# ═══════════════════════════════════════════════════════════════════════════════

def create_reset_token(user_id: str, token: str, expiry: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO app_reset_tokens (token, user_id, expiry)
            VALUES (:t, :uid, :exp)
            ON CONFLICT (token) DO UPDATE SET expiry = EXCLUDED.expiry
        """), {"t": token, "uid": user_id, "exp": expiry})


def get_reset_token(token: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_reset_tokens WHERE token = :t"), {"t": token}
        ).fetchone()
    return _row_to_dict(row)


def delete_reset_token(token: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM app_reset_tokens WHERE token = :t"), {"t": token})


# ═══════════════════════════════════════════════════════════════════════════════
# ENCOUNTERS
# ═══════════════════════════════════════════════════════════════════════════════

VALID_STATUSES = {
    "Pending Ingestion", "Processing", "Data Incomplete",
    "Ready for Review", "Awaiting Confirmation",
    "Verifying Claims", "Awaiting Review", "Signed Off", "Revision Requested",
    "Files Ready",
}

# Normalize any case variant a caller might send → canonical DB value
_STATUS_ALIASES: Dict[str, str] = {
    "revision_requested":  "Revision Requested",
    "revision requested":  "Revision Requested",
    "awaiting_review":     "Awaiting Review",
    "awaiting review":     "Awaiting Review",
    "signed_off":          "Signed Off",
    "signed off":          "Signed Off",
    "pending_ingestion":   "Pending Ingestion",
    "pending ingestion":   "Pending Ingestion",
    "data_incomplete":     "Data Incomplete",
    "data incomplete":     "Data Incomplete",
    "ready_for_review":    "Ready for Review",
    "ready for review":    "Ready for Review",
    "awaiting_confirmation": "Awaiting Confirmation",
    "verifying_claims":    "Verifying Claims",
    "files_ready":         "Files Ready",
    "files ready":         "Files Ready",
}

def _normalize_status(s: str) -> str:
    return _STATUS_ALIASES.get(s.lower(), s) if s else s


def _next_display_id(conn, year: int) -> str:
    prefix = f"PT-{year % 100:02d}-"
    row = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(SUBSTRING(display_id FROM 7) AS INTEGER)), 0) "
        "FROM app_encounters WHERE display_id LIKE :p"
    ), {"p": f"{prefix}%"}).fetchone()
    seq = (row[0] if row else 0) + 1
    return f"{prefix}{seq:04d}"


def create_encounter(hadm_id: int, status: str = "Pending Ingestion",
                     assigned_to: Optional[str] = None) -> Dict:
    eid = _new_id()
    from datetime import datetime as _dt
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO active_patients (hadm_id, subject_id)
            VALUES (:h, 0)
            ON CONFLICT (hadm_id) DO NOTHING
        """), {"h": hadm_id})
        _did = _next_display_id(conn, _dt.now().year)
        conn.execute(text("""
            INSERT INTO app_encounters (id, hadm_id, status, assigned_to, display_id)
            VALUES (:id, :h, :s, :a, :did)
            ON CONFLICT (hadm_id) DO NOTHING
        """), {"id": eid, "h": hadm_id, "s": status, "a": assigned_to, "did": _did})
        row = conn.execute(
            text("SELECT * FROM app_encounters WHERE hadm_id = :h"), {"h": hadm_id}
        ).fetchone()
    return _row_to_dict(row)


def get_encounter_by_id(eid: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_encounters WHERE id = :id"), {"id": eid}
        ).fetchone()
    return _row_to_dict(row)


def get_encounter_by_hadm(hadm_id: int) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_encounters WHERE hadm_id = :h"), {"h": hadm_id}
        ).fetchone()
    return _row_to_dict(row)


def update_encounter(eid: str, fields: Dict) -> Optional[Dict]:
    allowed = {"status", "complexity", "assigned_to", "version", "last_accessed_at",
               "discharge_type", "revision_reason", "revision_at", "rejection_count"}
    # Normalize status casing before hitting the DB check constraint
    if "status" in fields and fields["status"]:
        fields = {**fields, "status": _normalize_status(fields["status"])}
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return get_encounter_by_id(eid)
    params = {k: v for k, v in fields.items() if k in allowed}
    params["id"] = eid
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE app_encounters SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = :id"),
            params
        )
        row = conn.execute(
            text("SELECT * FROM app_encounters WHERE id = :id"), {"id": eid}
        ).fetchone()
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════════════════════════
# REJECTION LOG  (rejection_log table — added in migration 012)
# ═══════════════════════════════════════════════════════════════════════════════

def create_rejection_log(encounter_id: str, hadm_id: int, rejected_by: Optional[str],
                          reason: str, prev_t1: int = 0, version: int = 1) -> Dict:
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            INSERT INTO rejection_log
                (encounter_id, hadm_id, rejected_by, rejection_reason, prev_t1_count, rejection_version)
            VALUES (:eid, :h, :rb, :r, :t1, :v)
            RETURNING *
        """), {"eid": encounter_id, "h": hadm_id, "rb": rejected_by,
               "r": reason, "t1": prev_t1, "v": version}).fetchone()
    return _row_to_dict(row) if row else {}


def update_rejection_log(log_id: int, fields: Dict) -> Dict:
    allowed = {"regeneration_triggered_at", "regenerated_at", "notification_sent_at",
               "re_reviewed_at", "signed_at", "new_t1_count", "auto_resolved_sections",
               "files_ready_at"}
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return {}
    params = {k: v for k, v in fields.items() if k in allowed}
    params["id"] = log_id
    with get_engine().begin() as conn:
        row = conn.execute(
            text(f"UPDATE rejection_log SET {', '.join(set_parts)} WHERE id = :id RETURNING *"),
            params,
        ).fetchone()
    return _row_to_dict(row) if row else {}


def get_rejection_log(encounter_id: str) -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM rejection_log WHERE encounter_id = :eid ORDER BY rejected_at DESC"),
            {"eid": encounter_id},
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_latest_rejection_log_with_user(encounter_id: str) -> Optional[Dict]:
    """Return most recent rejection_log row joined with rejected_by user name."""
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT rl.*,
                   au.full_name AS rejected_by_name
            FROM   rejection_log rl
            LEFT JOIN app_users au ON rl.rejected_by = au.id
            WHERE  rl.encounter_id = :eid
            ORDER  BY rl.rejected_at DESC
            LIMIT  1
        """), {"eid": encounter_id}).mappings().fetchone()
    return dict(row) if row else None


def list_rejection_logs(limit: int = 50) -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT rl.*,
                   ae.hadm_id            AS hadm_id_enc,
                   au.full_name          AS rejected_by_name
            FROM   rejection_log rl
            JOIN   app_encounters ae ON rl.encounter_id = ae.id
            LEFT JOIN app_users   au ON rl.rejected_by  = au.id
            ORDER  BY rl.rejected_at DESC
            LIMIT  :lim
        """), {"lim": limit}).mappings().fetchall()
    return [dict(r) for r in rows]


def create_amendment(encounter_id: str, hadm_id: int, amendment_ref: str,
                     reason: str, section: str, details: str,
                     doc_name: Optional[str], submitted_by_name: str,
                     from_version: str = "v1.0", to_version: str = "v1.1") -> Dict:
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            INSERT INTO amendment_log
                (encounter_id, hadm_id, amendment_ref, from_version, to_version,
                 reason, section, details, doc_name, submitted_by_name, status)
            VALUES
                (:eid, :h, :ref, :fv, :tv, :reason, :sec, :det, :doc, :name, 'Pending Re-sign')
            RETURNING *
        """), {"eid": encounter_id, "h": hadm_id, "ref": amendment_ref,
               "fv": from_version, "tv": to_version, "reason": reason,
               "sec": section, "det": details, "doc": doc_name,
               "name": submitted_by_name}).fetchone()
    return _row_to_dict(row) if row else {}


def get_latest_amendment(encounter_id: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT * FROM amendment_log
            WHERE encounter_id = :eid
            ORDER BY created_at DESC LIMIT 1
        """), {"eid": encounter_id}).fetchone()
    return _row_to_dict(row) if row else None


def count_amendments(encounter_id: str) -> int:
    with get_engine().connect() as conn:
        row = conn.execute(text(
            "SELECT COUNT(*) FROM amendment_log WHERE encounter_id = :eid"
        ), {"eid": encounter_id}).fetchone()
    return row[0] if row else 0


def list_encounters(status: Optional[str] = None,
                    assigned_to: Optional[str] = None,
                    exclude_status: Optional[str] = None) -> List[Dict]:
    sql = """
        SELECT ae.*, ap.primary_diagnosis_title, ap.patient_name, ap.anchor_age, ap.gender
        FROM app_encounters ae
        LEFT JOIN active_patients ap ON ap.hadm_id = ae.hadm_id
        WHERE TRUE
    """
    params: Dict = {}
    if status:
        sql += " AND ae.status = :status"
        params["status"] = status
    if exclude_status:
        sql += " AND ae.status != :excl"
        params["excl"] = exclude_status
    if assigned_to:
        sql += " AND ae.assigned_to = :assigned_to"
        params["assigned_to"] = assigned_to
    sql += " ORDER BY ae.created_at DESC"
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [_row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARIES
# ═══════════════════════════════════════════════════════════════════════════════

def upsert_summary(encounter_id: str, content: str,
                   nli_score: Optional[float] = None,
                   clinical_context: Optional[str] = None,
                   pass1_latency_s: Optional[float] = None,
                   pass2_latency_s: Optional[float] = None,
                   total_latency_s: Optional[float] = None,
                   rouge1: Optional[float] = None,
                   rouge2: Optional[float] = None,
                   rougeL: Optional[float] = None,
                   summary_version: Optional[int] = None,
                   pass1_version: Optional[str] = None,
                   pass2_version: Optional[str] = None,
                   sections_json: Optional[dict] = None) -> Dict:
    import json as _j
    with get_engine().begin() as conn:
        enc_row = conn.execute(
            text("SELECT hadm_id FROM app_encounters WHERE id = :id"), {"id": encounter_id}
        ).fetchone()
        hadm_id = enc_row[0] if enc_row else 0
        sid = _new_id()
        _sj = _j.dumps(sections_json) if sections_json else None
        conn.execute(text("""
            INSERT INTO app_summaries
                (id, encounter_id, hadm_id, content, nli_score, clinical_context,
                 pass1_latency_s, pass2_latency_s, total_latency_s,
                 rouge1, rouge2, "rougeL", summary_version, pass1_version, pass2_version, sections_json)
            VALUES (:id, :enc, :hadm, :content, :nli, :ctx,
                    :p1, :p2, :tot, :r1, :r2, :rl, :sv, :pv1, :pv2, :sj)
            ON CONFLICT (encounter_id) DO UPDATE SET
                content          = EXCLUDED.content,
                nli_score        = COALESCE(EXCLUDED.nli_score, app_summaries.nli_score),
                clinical_context = COALESCE(EXCLUDED.clinical_context, app_summaries.clinical_context),
                pass1_latency_s  = COALESCE(EXCLUDED.pass1_latency_s, app_summaries.pass1_latency_s),
                pass2_latency_s  = COALESCE(EXCLUDED.pass2_latency_s, app_summaries.pass2_latency_s),
                total_latency_s  = COALESCE(EXCLUDED.total_latency_s, app_summaries.total_latency_s),
                rouge1           = COALESCE(EXCLUDED.rouge1, app_summaries.rouge1),
                rouge2           = COALESCE(EXCLUDED.rouge2, app_summaries.rouge2),
                "rougeL"         = COALESCE(EXCLUDED."rougeL", app_summaries."rougeL"),
                summary_version  = COALESCE(EXCLUDED.summary_version, app_summaries.summary_version),
                pass1_version    = COALESCE(EXCLUDED.pass1_version, app_summaries.pass1_version),
                pass2_version    = COALESCE(EXCLUDED.pass2_version, app_summaries.pass2_version),
                sections_json    = COALESCE(EXCLUDED.sections_json, app_summaries.sections_json),
                updated_at       = NOW()
        """), {
            "id": sid, "enc": encounter_id, "hadm": hadm_id,
            "content": content, "nli": nli_score, "ctx": clinical_context,
            "p1": pass1_latency_s, "p2": pass2_latency_s, "tot": total_latency_s,
            "r1": rouge1, "r2": rouge2, "rl": rougeL, "sv": summary_version,
            "pv1": pass1_version, "pv2": pass2_version, "sj": _sj,
        })
        row = conn.execute(
            text("SELECT * FROM app_summaries WHERE encounter_id = :enc"), {"enc": encounter_id}
        ).fetchone()
    return _row_to_dict(row)


def get_summary_by_encounter(encounter_id: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_summaries WHERE encounter_id = :enc"), {"enc": encounter_id}
        ).fetchone()
    return _row_to_dict(row)


def update_summary(encounter_id: str, fields: Dict) -> Optional[Dict]:
    allowed = {"content", "nli_score", "clinical_context",
               "claim_verification_status", "signed_by", "signed_at",
               "gap_t1", "gap_t2", "gap_t3", "dl_flags", "gap_rows",
               "sections_json", "draft_saved_at", "draft_edits", "doc_version",
               "llm_edits_count"}
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return get_summary_by_encounter(encounter_id)
    _json_fields = {"draft_edits", "gap_rows", "sections_json"}
    params = {k: (json.dumps(v) if k in _json_fields and isinstance(v, (dict, list)) else v)
              for k, v in fields.items() if k in allowed}
    params["enc"] = encounter_id
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE app_summaries SET {', '.join(set_parts)}, updated_at = NOW() "
                 f"WHERE encounter_id = :enc"),
            params
        )
        row = conn.execute(
            text("SELECT * FROM app_summaries WHERE encounter_id = :enc"), {"enc": encounter_id}
        ).fetchone()
    return _row_to_dict(row)


# ── Summary Version History ────────────────────────────────────────────────────

def create_summary_version(summary_id: str, encounter_id: str, hadm_id: int,
                           content: str, sections_json=None, saved_by: Optional[str] = None,
                           saved_by_name: Optional[str] = None,
                           save_type: str = "draft") -> Dict:
    with get_engine().begin() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM summary_versions WHERE encounter_id = :e"),
            {"e": encounter_id}
        ).scalar() or 0
        version_num = int(count) + 1
        row = conn.execute(
            text("""INSERT INTO summary_versions
                    (summary_id, encounter_id, hadm_id, version_num, content,
                     sections_json, saved_by, saved_by_name, save_type)
                    VALUES (:sid, :enc, :hadm, :vn, :content,
                            CAST(:sj AS jsonb), :sb, :sbn, :st)
                    RETURNING *"""),
            {"sid": summary_id, "enc": encounter_id, "hadm": hadm_id,
             "vn": version_num, "content": content,
             "sj": json.dumps(sections_json) if sections_json else None,
             "sb": saved_by, "sbn": saved_by_name, "st": save_type}
        ).fetchone()
    return _row_to_dict(row)


def list_summary_versions(encounter_id: str) -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""SELECT id, version_num, saved_by_name, save_type, created_at
                    FROM summary_versions WHERE encounter_id = :e
                    ORDER BY version_num DESC"""),
            {"e": encounter_id}
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_summary_version(version_id: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM summary_versions WHERE id = :id"),
            {"id": version_id}
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_summaries() -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM app_summaries ORDER BY created_at DESC")
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# UPLOADED FILES
# ═══════════════════════════════════════════════════════════════════════════════

def create_file_record(encounter_id: str, file_type: str,
                       file_name: str, file_size: int = 0) -> Dict:
    fid = _new_id()
    ft_key = _normalize_file_type(file_type)
    with get_engine().begin() as conn:
        enc_row = conn.execute(
            text("SELECT hadm_id FROM app_encounters WHERE id = :id"), {"id": encounter_id}
        ).fetchone()
        hadm_id = enc_row[0] if enc_row else 0
        conn.execute(text("""
            INSERT INTO app_uploaded_files
                (id, hadm_id, encounter_id, file_type, file_name, file_size,
                 indexed_status, upload_date)
            VALUES
                (:id, :hadm, :enc, :ft, :fn, :fs, 'pending', CURRENT_DATE)
        """), {
            "id": fid, "hadm": hadm_id, "enc": encounter_id,
            "ft": ft_key, "fn": file_name, "fs": file_size,
        })
        row = conn.execute(
            text("SELECT * FROM app_uploaded_files WHERE id = :id"), {"id": fid}
        ).fetchone()
    return _row_to_dict(row)


def list_files_by_encounter(encounter_id: str) -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM app_uploaded_files WHERE encounter_id = :enc ORDER BY uploaded_at DESC"),
            {"enc": encounter_id}
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_file_by_id(fid: str) -> Optional[Dict]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_uploaded_files WHERE id = :id"), {"id": fid}
        ).fetchone()
    return _row_to_dict(row)


def update_file_record(fid: str, fields: Dict) -> Optional[Dict]:
    if "indexed_status" in fields:
        v = fields["indexed_status"]
        if v is True:
            fields["indexed_status"] = "indexed"
        elif v is False:
            fields["indexed_status"] = "pending"
    allowed = {"indexed_status", "gcs_path", "file_size", "uploaded_by"}
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return get_file_by_id(fid)
    params = {k: v for k, v in fields.items() if k in allowed}
    params["id"] = fid
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE app_uploaded_files SET {', '.join(set_parts)} WHERE id = :id"),
            params
        )
        row = conn.execute(
            text("SELECT * FROM app_uploaded_files WHERE id = :id"), {"id": fid}
        ).fetchone()
    return _row_to_dict(row)


def delete_file_record(fid: str) -> bool:
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM app_uploaded_files WHERE id = :id"), {"id": fid})
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════

def log_action(action: str, hadm_id: Optional[int] = None,
               user_id: Optional[str] = None, details: Optional[Dict] = None):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO app_audit_log (action, hadm_id, user_id, details)
                VALUES (:a, :h, :u, :d)
            """), {
                "a": action, "h": hadm_id, "u": user_id,
                "d": json.dumps(details or {}),
            })
    except Exception as e:
        log.warning(f"audit_log write failed: {e}")


def list_audit_log(limit: int = 100) -> List[Dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM app_audit_log ORDER BY created_at DESC LIMIT :lim"),
            {"lim": limit}
        ).fetchall()
    result = []
    for r in rows:
        d = _row_to_dict(r)
        if d and isinstance(d.get("details"), str):
            try:
                d["details"] = json.loads(d["details"])
            except Exception:
                pass
        result.append(d)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "hospital_name":            "Apollo Hospitals",
    "wing":                     "Cardiac & Surgical Wing",
    "city":                     "Chennai, Tamil Nadu",
    "mci_nabh_number":          "MCI-NABH-TR-2024-0041",
    "footer_disclaimer":        "This is a system-generated, physician-verified discharge summary.",
    "nli_entailment_threshold": 0.85,
    "k_retrieved_chunks":       6,
    "dense_retrieval_weight":   0.6,
    "auto_notify_doctor":       True,
}


def get_settings() -> Dict:
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT * FROM app_settings WHERE id = 1")).fetchone()
    if not row:
        return _DEFAULT_SETTINGS.copy()
    d = _row_to_dict(row)
    d.pop("id", None)
    d.pop("updated_at", None)
    return {**_DEFAULT_SETTINGS, **{k: v for k, v in d.items() if v is not None}}


def update_settings(fields: Dict) -> Dict:
    allowed = {
        "hospital_name", "wing", "city", "mci_nabh_number", "footer_disclaimer",
        "nli_entailment_threshold", "k_retrieved_chunks",
        "dense_retrieval_weight", "auto_notify_doctor",
    }
    set_parts = [f"{k} = :{k}" for k in fields if k in allowed]
    if not set_parts:
        return get_settings()
    params = {k: v for k, v in fields.items() if k in allowed}
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE app_settings SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = 1"),
            params
        )
    return get_settings()


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM HEALTH  (computed live — no GCS dependency)
# ═══════════════════════════════════════════════════════════════════════════════

def get_system_health() -> Dict:
    import time as _time
    sql_ok = "ok"
    db_ping_ms = None
    ds_last_at = None
    ds_count_7d = 0
    audit_count_7d = 0
    upload_count_7d = 0
    try:
        _t0 = _time.monotonic()
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ping_ms = round((_time.monotonic() - _t0) * 1000)
            # Last DS generation (content written)
            _r = conn.execute(text(
                "SELECT MAX(updated_at) AS last_at FROM app_summaries WHERE content IS NOT NULL"
            )).fetchone()
            ds_last_at = str(_r[0]) if _r and _r[0] else None
            # DS generations in last 7 days
            _r2 = conn.execute(text(
                "SELECT COUNT(*) FROM app_summaries WHERE content IS NOT NULL "
                "AND updated_at >= NOW() - INTERVAL '7 days'"
            )).fetchone()
            ds_count_7d = int(_r2[0]) if _r2 else 0
            # Audit events in last 7 days
            _r3 = conn.execute(text(
                "SELECT COUNT(*) FROM app_audit_log WHERE created_at >= NOW() - INTERVAL '7 days'"
            )).fetchone()
            audit_count_7d = int(_r3[0]) if _r3 else 0
            # Uploads in last 7 days
            _r4 = conn.execute(text(
                "SELECT COUNT(*) FROM app_uploaded_files WHERE created_at >= NOW() - INTERVAL '7 days'"
            )).fetchone()
            upload_count_7d = int(_r4[0]) if _r4 else 0
    except Exception:
        sql_ok = "error"
    return {
        "cloud_sql_status":          sql_ok,
        "db_ping_ms":                db_ping_ms,
        "ds_last_generated_at":      ds_last_at,
        "ds_count_7d":               ds_count_7d,
        "audit_event_count_7d":      audit_count_7d,
        "upload_count_7d":           upload_count_7d,
        "last_updated":              _now(),
    }


def update_system_health(fields: Dict) -> Dict:
    return get_system_health()


# ═══════════════════════════════════════════════════════════════════════════════
# CLINICAL DATA  (uploaded CSV rows — app_clinical_rows table from migration 001)
# ═══════════════════════════════════════════════════════════════════════════════

def store_clinical_rows(hadm_id: int, file_type: str, file_id: str, rows: List[Dict]):
    ft_key = _normalize_file_type(file_type)
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO app_clinical_rows (hadm_id, file_type, file_id, rows)
            VALUES (:h, :ft, :fid, :rows)
            ON CONFLICT (hadm_id, file_type, file_id)
            DO UPDATE SET rows = EXCLUDED.rows
        """), {
            "h": hadm_id, "ft": ft_key, "fid": file_id,
            "rows": json.dumps(rows, default=str),
        })


def delete_clinical_rows(hadm_id: int, file_type: str, file_id: str):
    ft_key = _normalize_file_type(file_type)
    with get_engine().begin() as conn:
        conn.execute(text("""
            DELETE FROM app_clinical_rows
            WHERE hadm_id = :h AND file_type = :ft AND file_id = :fid
        """), {"h": hadm_id, "ft": ft_key, "fid": file_id})


def purge_all_clinical_rows(hadm_id: int, file_type: str) -> int:
    ft_key = _normalize_file_type(file_type)
    with get_engine().begin() as conn:
        result = conn.execute(text("""
            DELETE FROM app_clinical_rows WHERE hadm_id = :h AND file_type = :ft
        """), {"h": hadm_id, "ft": ft_key})
    return result.rowcount


def load_clinical_table(hadm_id: int, file_type: str) -> List[Dict]:
    ft_key = _normalize_file_type(file_type)
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT rows FROM app_clinical_rows
            WHERE hadm_id = :h AND file_type = :ft
            ORDER BY created_at
        """), {"h": hadm_id, "ft": ft_key}).fetchall()
    all_rows: List[Dict] = []
    for r in rows:
        data = r[0]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                continue
        if isinstance(data, list):
            all_rows.extend(data)
    return all_rows


def fetch_all_uploaded_clinical_data(hadm_id: int) -> Dict[str, List[Dict]]:
    # Single query for all file types — avoids 13 round-trips (~25 s → <1 s)
    result: Dict[str, List[Dict]] = {tbl: [] for tbl in _FILE_TYPE_TO_TABLE.values()}
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT file_type, rows FROM app_clinical_rows
            WHERE hadm_id = :h
            ORDER BY file_type, created_at
        """), {"h": hadm_id}).fetchall()
    for r in rows:
        ft_key = _normalize_file_type(r[0])
        tbl = _FILE_TYPE_TO_TABLE.get(ft_key)
        if not tbl:
            continue
        data = r[1]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                continue
        if isinstance(data, list):
            result[tbl].extend(data)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR LOG  (3-Tier Accuracy Framework)
# ═══════════════════════════════════════════════════════════════════════════════

def log_error(
    hadm_id:          Optional[str],
    error_tier:       int,
    nabh_section:     Optional[str]  = None,
    ai_output:        Optional[str]  = None,
    correct_value:    Optional[str]  = None,
    error_category:   Optional[str]  = None,
    source_present:   Optional[bool] = None,
    attending_id:     Optional[str]  = None,
    summary_version:  Optional[str]  = None,
) -> Dict:
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            INSERT INTO error_log
                (hadm_id, summary_version, nabh_section, error_tier,
                 ai_output, correct_value, error_category, source_present, attending_id)
            VALUES
                (:hadm_id, :sv, :section, :tier,
                 :ai_out, :correct, :cat, :src_present, :att_id)
            RETURNING *
        """), {
            "hadm_id":     str(hadm_id) if hadm_id else None,
            "sv":          summary_version,
            "section":     nabh_section,
            "tier":        error_tier,
            "ai_out":      ai_output,
            "correct":     correct_value,
            "cat":         error_category,
            "src_present": source_present,
            "att_id":      attending_id,
        }).fetchone()
    return _row_to_dict(row)


def get_error_stats() -> Dict:
    """Accuracy gate stats from Pass 3 verification results in app_summaries.gap_t1/t2/t3.
    Counts summaries whose encounter status shows generation completed
    (Ready for Review, Awaiting Review, Signed Off, Amendment Requested, Revision Requested).
    T3 rate = T3 errors / total generated summaries."""
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT
                COALESCE(SUM(s.gap_t1), 0)  AS t1_count,
                COALESCE(SUM(s.gap_t2), 0)  AS t2_count,
                COALESCE(SUM(s.gap_t3), 0)  AS t3_count,
                COUNT(*)                      AS total_summaries
            FROM app_summaries s
            JOIN app_encounters e ON e.id = s.encounter_id
            WHERE e.status IN (
                'Ready for Review', 'Awaiting Review',
                'Signed Off', 'Amendment Requested', 'Revision Requested'
            )
        """)).fetchone()
    t1    = int(row[0] or 0)
    t2    = int(row[1] or 0)
    t3    = int(row[2] or 0)
    total_summaries = int(row[3] or 0)
    total_errors    = t1 + t2 + t3
    # Rate = T3 errors per summary reviewed (clinically meaningful denominator)
    rate  = round(t3 / total_summaries * 100, 1) if total_summaries > 0 else 0.0
    return {
        "tier3_count":      t3,
        "total_errors":     total_errors,
        "total_summaries":  total_summaries,
        "tier3_rate_pct":   rate,
        "by_tier": [
            {"tier": 1, "count": t1},
            {"tier": 2, "count": t2},
            {"tier": 3, "count": t3},
        ],
        "by_section": [],
    }


def get_recent_errors(examples_per_pattern: int = 3) -> List[Dict]:
    """Return ALL error patterns grouped by (nabh_section, error_category), sorted by
    total occurrence count descending.

    High-frequency patterns carry more weight in the prompt — the LLM sees multiple
    examples of the same failure type, giving it richer signal than a single unique
    example ever could. A mistake that happened 40 times appears before one that
    happened twice, and includes up to `examples_per_pattern` diverse examples so the
    model generalises the fix rather than memorising one instance.

    This means the prompt grows richer with every attending correction and the LLM's
    avoidance of each pattern strengthens continuously over time.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            WITH counted AS (
                SELECT
                    nabh_section,
                    error_tier,
                    error_category,
                    ai_output,
                    correct_value,
                    created_at,
                    COUNT(*) OVER (
                        PARTITION BY nabh_section, error_category
                    ) AS occurrence_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY nabh_section, error_category
                        ORDER BY created_at DESC
                    ) AS rn
                FROM error_log
                WHERE error_tier IN (1, 2, 3)
                  AND nabh_section IS NOT NULL
                  AND ai_output    IS NOT NULL
            )
            SELECT
                nabh_section, error_tier, error_category,
                ai_output, correct_value, occurrence_count
            FROM counted
            WHERE rn <= :per_pat
            ORDER BY error_tier DESC, occurrence_count DESC, nabh_section, rn
        """), {"per_pat": examples_per_pattern}).fetchall()

    # Group the flat rows back into per-pattern dicts
    from collections import OrderedDict as _OD
    grouped: dict = _OD()
    for r in rows:
        key = (r[0], r[2])  # (nabh_section, error_category)
        if key not in grouped:
            grouped[key] = {
                "nabh_section":    r[0],
                "error_tier":      r[1],
                "error_category":  r[2],
                "occurrence_count": r[5],
                "examples": [],
            }
        grouped[key]["examples"].append({
            "ai_output":    r[3],
            "correct_value": r[4],
        })

    return list(grouped.values())


# ═══════════════════════════════════════════════════════════════════════════════
# USABILITY RATINGS
# ═══════════════════════════════════════════════════════════════════════════════

def log_usability_rating(encounter_id: Optional[str], hadm_id: Optional[int],
                          attending_id: Optional[str], rating: int,
                          feedback: Optional[str] = None) -> Dict:
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO usability_ratings
                (encounter_id, hadm_id, attending_id, rating, feedback)
            VALUES (:enc, :hadm, :att, :rat, :fb)
        """), {
            "enc": encounter_id, "hadm": hadm_id,
            "att": attending_id, "rat": rating, "fb": feedback,
        })
        row = conn.execute(text(
            "SELECT * FROM usability_ratings ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
    return _row_to_dict(row)


def get_usability_stats() -> Dict:
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT
                COUNT(*)                                   AS total_ratings,
                ROUND(AVG(rating)::numeric, 2)             AS avg_rating,
                COUNT(*) FILTER (WHERE rating = 5)         AS r5,
                COUNT(*) FILTER (WHERE rating = 4)         AS r4,
                COUNT(*) FILTER (WHERE rating = 3)         AS r3,
                COUNT(*) FILTER (WHERE rating = 2)         AS r2,
                COUNT(*) FILTER (WHERE rating = 1)         AS r1
            FROM usability_ratings
        """)).fetchone()
    r = dict(row._mapping) if row else {}
    return {
        "total_ratings": r.get("total_ratings", 0),
        "avg_rating":    float(r.get("avg_rating") or 0),
        "distribution":  {
            "5": r.get("r5", 0), "4": r.get("r4", 0), "3": r.get("r3", 0),
            "2": r.get("r2", 0), "1": r.get("r1", 0),
        },
        "target": 4.0,
    }


def get_prompt_version_log() -> Dict:
    """Return per-prompt-version row with Tier 3 rate — powers the PM version log table."""
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT
                s.pass1_version,
                s.pass2_version,
                COUNT(DISTINCT s.encounter_id)                                         AS total_summaries,
                COUNT(el.id)                                                           AS total_errors,
                COUNT(el.id) FILTER (WHERE el.tier = 'T3')                            AS tier3_count,
                CASE WHEN COUNT(el.id) > 0
                    THEN ROUND(
                        COUNT(el.id) FILTER (WHERE el.tier = 'T3')::numeric
                        * 100.0 / COUNT(el.id), 1)
                    ELSE NULL
                END                                                                    AS tier3_rate_pct
            FROM app_summaries s
            LEFT JOIN error_log el ON el.encounter_id = s.encounter_id
            WHERE s.pass1_version IS NOT NULL
            GROUP BY s.pass1_version, s.pass2_version
            ORDER BY s.pass1_version, s.pass2_version
        """)).fetchall()
    versions = []
    for r in rows:
        rd = dict(r._mapping)
        versions.append({
            "pass1_version":    rd.get("pass1_version"),
            "pass2_version":    rd.get("pass2_version"),
            "total_summaries":  rd.get("total_summaries", 0),
            "total_errors":     rd.get("total_errors", 0),
            "tier3_count":      rd.get("tier3_count", 0),
            "tier3_rate_pct":   float(rd["tier3_rate_pct"]) if rd.get("tier3_rate_pct") is not None else None,
        })
    return {"versions": versions}

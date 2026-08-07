import os
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2 import service_account
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREDS_PATH = os.path.join(_HERE, "..", "..", "healthcare-project-db-creds.json")

_INSTANCE = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
_DB_USER  = "postgres"
_DB_PASS  = os.environ["CLOUD_SQL_PASS"]
_DB_NAME  = "postgres"

_sa_credentials = service_account.Credentials.from_service_account_file(
    _CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
_connector = Connector(credentials=_sa_credentials)

def _make_connection():
    return _connector.connect(
        _INSTANCE, "pg8000",
        user=_DB_USER, password=_DB_PASS, db=_DB_NAME,
        ip_type=IPTypes.PUBLIC,
    )

engine = create_engine(
    "postgresql+pg8000://",
    creator=_make_connection,
    # This Cloud SQL instance's max_connections is 25 (checked directly via
    # `SHOW max_connections` — it's the smallest tier). ~4 of those are
    # reserved for GCP's own cloudsqladmin/cloudsqlagent, leaving ~21 for all
    # application connections combined. Three backend processes run against
    # this same instance (this ward API, Ashmit's main API, Ashmit's data
    # server) — at the previous pool_size=5/max_overflow=10, each process
    # could alone claim up to 15 connections, so all three together could
    # legitimately request 45, blowing well past the real ceiling and
    # producing "FATAL 53300: remaining connection slots are reserved" for
    # whichever request loses the race. Observed this directly: 23/25
    # connections in use with only light manual testing running, and a batch
    # of 5 concurrent requests to one endpoint immediately hit the error.
    # 2+3 per service (max 5) keeps three services' combined ceiling at 15,
    # comfortably under the ~21 actually available.
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,   # test connection health on checkout; drops broken ones before they cause 25P02
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # Tables already exist in Cloud SQL — this is otherwise a no-op, kept for
    # startup compatibility, EXCEPT for these two indexes: mimic_sync.py's
    # real-data insert paths rely on ON CONFLICT (hadm_id, chart_time) DO
    # NOTHING to survive concurrent syncs, but Postgres requires a real unique
    # index to back that clause — without it every insert on that path throws
    # "42P10: no unique or exclusion constraint matching ON CONFLICT" and the
    # sync silently fails. These were created ad hoc directly on the shared
    # instance and never captured in a migration, so if this database is ever
    # recreated or pointed at a fresh instance, the exact same crash returns
    # silently. CREATE ... IF NOT EXISTS makes this safe to run on every
    # startup.
    from sqlalchemy import text as _t
    with engine.begin() as conn:
        conn.execute(_t(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ews_vitals_hadm_time "
            "ON ews_vitals_timeseries (hadm_id, chart_time)"
        ))
        conn.execute(_t(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ews_labs_hadm_time "
            "ON ews_lab_events (hadm_id, chart_time)"
        ))
        # Early Warning panel ack/dismiss -- workflow-only state, never read
        # by escalation_model.predict(). See models.AiAlertAck's docstring.
        conn.execute(_t(
            "CREATE TABLE IF NOT EXISTS ews_ai_alert_ack ("
            "  id SERIAL PRIMARY KEY,"
            "  hadm_id INTEGER UNIQUE NOT NULL,"
            "  acknowledged_at TIMESTAMP,"
            "  acknowledged_by VARCHAR,"
            "  dismissed_until TIMESTAMP,"
            "  updated_at TIMESTAMP"
            ")"
        ))

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

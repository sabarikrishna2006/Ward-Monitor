"""
Cloud SQL (PostgreSQL 18) connection pool.
Uses cloud-sql-python-connector + pg8000 + SQLAlchemy.
Instance: healthcare-project-496207:asia-south1:healthcare-project-496207-instance
"""
import os
from google.oauth2 import service_account
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

# ── credentials ───────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CREDS_PATH   = os.getenv(
    "CLOUD_SQL_CREDS",
    os.path.join(_PROJECT_ROOT, "foqal-healthcare-project-google.json")
)
_INSTANCE     = os.getenv(
    "CLOUD_SQL_INSTANCE",
    "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
)
_DB_NAME      = os.getenv("CLOUD_SQL_DB",   "postgres")
_DB_USER      = os.getenv("CLOUD_SQL_USER", "postgres")
_DB_PASS      = os.environ["CLOUD_SQL_PASS"]

# ── module-level singletons ───────────────────────────────────────────────────
_connector: Connector | None = None
_engine = None


def _get_sa_credentials():
    return service_account.Credentials.from_service_account_file(
        _CREDS_PATH,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _make_connection():
    """Factory called by SQLAlchemy pool for each new connection."""
    global _connector
    if _connector is None:
        _connector = Connector(credentials=_get_sa_credentials())
    return _connector.connect(
        _INSTANCE,
        "pg8000",
        user=_DB_USER,
        password=_DB_PASS,
        db=_DB_NAME,
        ip_type=IPTypes.PUBLIC,
    )


def get_engine():
    """Return (and lazily create) the shared SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            "postgresql+pg8000://",
            creator=_make_connection,
            poolclass=QueuePool,
            # This Cloud SQL instance's max_connections is 25 (smallest tier),
            # ~4 reserved for GCP's own cloudsqladmin/cloudsqlagent. Three
            # separate backend processes share this instance (this main API,
            # this data server — each gets its OWN pool from this same
            # get_engine() singleton since they're separate processes — plus
            # the ward API's own engine in sabari_project/backend/database.py).
            # At pool_size=5/max_overflow=10, three processes could together
            # legitimately request 45 connections against a ~21-connection
            # budget. Reproduced directly: 23/25 in use with only light manual
            # testing, and 5 concurrent requests to one endpoint immediately
            # hit "FATAL 53300: remaining connection slots are reserved".
            # 2+3 per process keeps the three-service combined ceiling at 15.
            pool_size=2,
            max_overflow=3,
            pool_timeout=30,
            pool_pre_ping=True,      # evict stale connections automatically
        )
    return _engine


def get_conn():
    """Context-manager-friendly raw connection from the pool."""
    return get_engine().connect()


def close():
    """Graceful shutdown — call once at app exit."""
    global _connector, _engine
    if _engine:
        _engine.dispose()
        _engine = None
    if _connector:
        _connector.close()
        _connector = None


def ping():
    """Quick connectivity test. Returns True if Cloud SQL is reachable."""
    try:
        with get_conn() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[cloud_sql_db] ping failed: {e}")
        return False

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
_DB_PASS      = os.getenv("CLOUD_SQL_PASS", "foqalAnalyticsHealthcareDB2026")

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
            pool_size=5,
            max_overflow=10,
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

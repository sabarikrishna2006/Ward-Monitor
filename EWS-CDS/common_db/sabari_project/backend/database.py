import os
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(_HERE, "..", "..", "healthcare-project-db-creds.json")
)

_INSTANCE = "healthcare-project-496207:us-central1:foqal-healthcare-cloud-sql-db"
_DB_USER  = "postgres"
_DB_PASS  = "foqalAnalyticsHealthcareDB2026"
_DB_NAME  = "postgres"

_connector = Connector()

def _make_connection():
    return _connector.connect(
        _INSTANCE, "pg8000",
        user=_DB_USER, password=_DB_PASS, db=_DB_NAME,
        ip_type=IPTypes.PUBLIC,
    )

engine = create_engine(
    "postgresql+pg8000://",
    creator=_make_connection,
    pool_size=5,
    max_overflow=10,
    # Cloud SQL is in us-central1; from India each round-trip is ~300-400ms and a
    # fresh connection handshake is ~1.8s. pool_pre_ping added an extra SELECT-1
    # round-trip on EVERY checkout (~350ms). We drop it and instead recycle
    # connections older than 30 min so stale ones are refreshed proactively.
    pool_recycle=1800,
    pool_reset_on_return=None,   # Session.close() already rolls back — skip the duplicate round-trip
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # Tables already exist in Cloud SQL — no-op kept for startup compatibility
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

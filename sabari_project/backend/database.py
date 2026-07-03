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
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # test connection health on checkout; drops broken ones before they cause 25P02
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # Tables already exist in Cloud SQL — no-op kept for startup compatibility
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

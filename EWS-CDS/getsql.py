import os
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

# Authentication
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "healthcare-project-db-creds.json"

# Cloud SQL details
INSTANCE_CONNECTION_NAME = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
DB_USER = "postgres"
DB_PASS = "foqalAnalyticsHealthcareDB2026"
DB_NAME = "postgres"

# Initialize connector
connector = Connector()

def get_conn():
    return connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        ip_type=IPTypes.PUBLIC,
    )

# SQLAlchemy engine
engine = sqlalchemy.create_engine(
    "postgresql+pg8000://",
    creator=get_conn,
)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, username, email, created_at
            FROM users
            ORDER BY id;
        """))

        users = result.fetchall()

        print(f"Found {len(users)} users:\n")

        for user in users:
            print(
                f"ID: {user.id}, "
                f"Username: {user.username}, "
                f"Email: {user.email}, "
                f"Created: {user.created_at}"
            )

except Exception as e:
    print(f"Error retrieving users: {e}")

finally:
    connector.close()
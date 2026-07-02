import os
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

# 1. Set your environment variable for GCP authentication
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "healthcare-project-db-creds.json"

# 2. Define your Cloud SQL Instance details
# Found on the Cloud SQL Overview page (Format: project:region:instance-name)
INSTANCE_CONNECTION_NAME = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
DB_USER = "postgres"  # Default user for PostgreSQL
DB_PASS = "foqalAnalyticsHealthcareDB2026"
DB_NAME = "postgres"  # Default database name

# 3. Initialize the Cloud SQL Connector
connector = Connector()

def get_conn():
    # Establishes a secure connection using IAM permissions
    conn = connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        ip_type=IPTypes.PUBLIC  # Uses Cloud SQL Auth Proxy logic over public IP
    )
    return conn

# 4. Create an SQLAlchemy Engine
pool = sqlalchemy.create_engine(
    "postgresql+pg8000://",
    creator=get_conn,
)

# 5. Connect and Execute SQL to Create a Table
try:
    with pool.connect() as db_conn:
        # Create a sample table
        db_conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # Insert a sample row
        db_conn.execute(text("""
            INSERT INTO users (username, email) 
            VALUES ('firebase_user', 'user@example.com')
            ON CONFLICT (email) DO NOTHING;
        """))
        
        # Commit the transaction
        db_conn.commit()
        print("Success: Table created and data inserted successfully!")

        # Query and print the results
        result = db_conn.execute(text("SELECT * FROM users;"))
        for row in result:
            print(f"User Found: ID: {row[0]}, Name: {row[1]}, Email: {row[2]}")

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # Clean up and close background connector threads
    connector.close()

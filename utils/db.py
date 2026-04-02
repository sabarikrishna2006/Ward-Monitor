"""SQLite database helpers."""
import sqlite3
import os

from config import DATABASE


def get_db():
    """Get a database connection."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def query_db(query, args=(), one=False):
    """Execute a query and return results as dicts."""
    db = get_db()
    cur = db.execute(query, args)
    rows = cur.fetchall()
    db.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]


def init_db():
    """Initialize the database — seed if it doesn't exist."""
    if not os.path.exists(DATABASE):
        from utils.seed import seed_database
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        seed_database(DATABASE)

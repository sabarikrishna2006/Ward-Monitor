"""
Apply a numbered SQL migration to Cloud SQL, recording it in a ledger.

Usage:
    python backend/apply_migration.py 001              # apply migration 001
    python backend/apply_migration.py --status          # what has / hasn't run
    python backend/apply_migration.py --baseline        # mark ALL as applied, without running
    python backend/apply_migration.py --baseline 001 002  # mark only these
    python backend/apply_migration.py 001 --force       # re-run an applied one

Each migration runs as a single all-or-nothing transaction: the whole file plus
its schema_migrations ledger row commit together, or nothing does.

CLOUD_SQL_PASS is read from the environment, falling back to <repo>/.env.secrets
then <repo>/.env — so this works on a dev machine without exporting anything.
"""
import hashlib
import getpass
import os
import sys

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# ── env bootstrap ─────────────────────────────────────────────────────────────
# Must happen BEFORE importing cloud_sql_db, which reads os.environ at import
# time. deploy.sh sources .env.secrets itself; this makes manual runs work too.
from dotenv import load_dotenv  # noqa: E402

for _envfile in (_REPO / ".env.secrets", _REPO / ".env"):
    if _envfile.exists():
        load_dotenv(_envfile, override=False)

MIGRATIONS_DIR = _REPO / "backend" / "app" / "migrations"

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    VARCHAR(20)  PRIMARY KEY,
    filename   VARCHAR(200) NOT NULL,
    checksum   CHAR(64)     NOT NULL,
    applied_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    applied_by VARCHAR(100)
);
"""


def _sql_files():
    """All real migrations, sorted by version. Skips *.sql.disabled."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _version_of(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_password():
    if not os.getenv("CLOUD_SQL_PASS"):
        print("ERROR: CLOUD_SQL_PASS is not set.")
        print(f"       Create {_REPO / '.env.secrets'} containing:")
        print('         export CLOUD_SQL_PASS="<postgres password>"')
        print("       (that file is gitignored — see .env.secrets.example)")
        sys.exit(1)


def _connect():
    _require_password()
    from backend.app.cloud_sql_db import get_engine, ping
    if not ping():
        print("ERROR: Cannot reach Cloud SQL")
        sys.exit(1)
    return get_engine()


def _applied(engine) -> dict:
    """version -> ledger row. Creates the ledger table if absent."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(LEDGER_DDL))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT version, filename, checksum, applied_at, applied_by "
            "FROM schema_migrations"
        )).fetchall()
    return {r[0]: r for r in rows}


def cmd_status(engine) -> int:
    applied = _applied(engine)
    files = _sql_files()
    disabled = sorted(MIGRATIONS_DIR.glob("*.sql.disabled"))

    print(f"{'VER':<5} {'STATE':<12} {'APPLIED AT':<22} FILE")
    print("-" * 78)
    pending = 0
    for f in files:
        v = _version_of(f)
        row = applied.get(v)
        if row is None:
            state, when = "PENDING", ""
            pending += 1
        elif row[2] != _checksum(f):
            state, when = "CHANGED!", str(row[3])[:19]
        else:
            state, when = "applied", str(row[3])[:19]
        print(f"{v:<5} {state:<12} {when:<22} {f.name}")
    for f in disabled:
        print(f"{_version_of(f):<5} {'disabled':<12} {'':<22} {f.name}")

    orphans = set(applied) - {_version_of(f) for f in files}
    if orphans:
        print("\nIn ledger but no file present: " + ", ".join(sorted(orphans)))

    print(f"\n{len(files) - pending}/{len(files)} applied, {pending} pending")
    if any(applied.get(_version_of(f)) and applied[_version_of(f)][2] != _checksum(f)
           for f in files):
        print("CHANGED! = file edited after it was applied — the DB does not "
              "match the file.")
    return 0


def cmd_baseline(engine, only: list) -> int:
    """Record migrations as applied WITHOUT executing them.

    For an existing database whose schema was built before this ledger existed.
    Pass specific versions to baseline only those — important when some
    migrations demonstrably did NOT take effect (e.g. 014's DROP TABLEs never
    ran: ap_emar, ap_emar_detail, ap_drgcodes, ap_services and
    ap_datetimeevents are all still live). Baselining such a file would record
    a lie.
    """
    from sqlalchemy import text
    applied = _applied(engine)
    files = _sql_files()
    todo = [f for f in files if _version_of(f) not in applied]
    if only:
        unknown = set(only) - {_version_of(f) for f in files}
        if unknown:
            print(f"No migration file for version(s): {', '.join(sorted(unknown))}")
            return 1
        todo = [f for f in todo if _version_of(f) in only]
    if not todo:
        print("Nothing to baseline (already in ledger, or no version matched).")
        return 0

    print("This will MARK AS APPLIED, without running, the following:")
    for f in todo:
        print(f"  {_version_of(f)}  {f.name}")
    print("\nOnly do this if the schema these files describe is already live.")
    if input("Type 'baseline' to confirm: ").strip() != "baseline":
        print("Aborted.")
        return 1

    user = getpass.getuser()
    with engine.begin() as conn:
        for f in todo:
            conn.execute(text(
                "INSERT INTO schema_migrations "
                "(version, filename, checksum, applied_by) "
                "VALUES (:v, :f, :c, :u) ON CONFLICT (version) DO NOTHING"
            ), {"v": _version_of(f), "f": f.name,
                "c": _checksum(f), "u": f"{user} (baseline)"})
    print(f"\nBaselined {len(todo)} migration(s). "
          f"Run --status to confirm.")
    return 0


def cmd_apply(engine, num: str, force: bool) -> int:
    matches = sorted(MIGRATIONS_DIR.glob(f"{num}_*.sql"))
    if not matches:
        print(f"No migration file matching {num}_*.sql in {MIGRATIONS_DIR}")
        return 1
    sql_file = matches[0]
    version = _version_of(sql_file)
    checksum = _checksum(sql_file)

    applied = _applied(engine)
    if version in applied and not force:
        row = applied[version]
        print(f"Migration {version} already applied at {row[3]} by {row[4]}.")
        if row[2] != checksum:
            print("WARNING: the file has CHANGED since it was applied.")
            print("         Its current contents are NOT in the database.")
        print("Use --force to run it again.")
        return 0

    print(f"Applying migration: {sql_file.name}")
    sql = sql_file.read_text(encoding="utf-8")
    user = getpass.getuser()

    # One transaction for the migration AND its ledger row. pg8000 accepts a
    # multi-statement string here (verified against this instance), so the file
    # is sent as-is rather than being split on ';' — which would corrupt the
    # DO $$ ... $$ blocks in 015_unified_staff_auth.sql.
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        cur.execute(
            "INSERT INTO schema_migrations "
            "(version, filename, checksum, applied_by) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (version) DO UPDATE SET "
            "filename = EXCLUDED.filename, checksum = EXCLUDED.checksum, "
            "applied_at = NOW(), applied_by = EXCLUDED.applied_by",
            (version, sql_file.name, checksum, user),
        )
        raw.commit()
        cur.close()
        print(f"Migration {sql_file.name} applied successfully and recorded.")
        return 0
    except Exception as e:
        raw.rollback()
        print(f"ERROR: {e}")
        print("Rolled back — neither the schema nor the ledger was changed.")
        return 1
    finally:
        raw.close()


def main():
    args = [a for a in sys.argv[1:]]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if not args:
        print(__doc__.strip())
        sys.exit(1)

    cmd = args[0]
    engine = _connect()

    if cmd == "--status":
        sys.exit(cmd_status(engine))
    if cmd == "--baseline":
        sys.exit(cmd_baseline(engine, args[1:]))
    if cmd.startswith("--"):
        print(f"Unknown option {cmd}\n")
        print(__doc__.strip())
        sys.exit(1)
    sys.exit(cmd_apply(engine, cmd, force))


if __name__ == "__main__":
    main()

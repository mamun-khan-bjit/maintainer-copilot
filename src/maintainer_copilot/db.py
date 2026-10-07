from pathlib import Path

import psycopg

from maintainer_copilot.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db"


def connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url)


def migrate() -> None:
    """Apply every db/*.sql file that hasn't been applied yet, in filename order."""
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            print(f"applied {path.name}")


if __name__ == "__main__":
    migrate()

from pathlib import Path

import psycopg

from maintainer_copilot.config import settings

# <repo root>/db: this file is src/maintainer_copilot/db.py, so go up two parents from its folder.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db"


def connect() -> psycopg.Connection:
    # Open a new connection. Use it as `with connect() as conn:` so it commits on success,
    # rolls back on an exception, and closes either way.
    return psycopg.connect(settings.database_url)


def record_llm_call(call: dict) -> None:
    # Log one LLM request (tokens, cost, latency) in its own short transaction.
    with connect() as conn:
        conn.execute(
            "INSERT INTO llm_calls (request_id, task, model, input_tokens, output_tokens, cost_usd, latency_ms, attempt)"
            " VALUES (%(request_id)s, %(task)s, %(model)s, %(input_tokens)s, %(output_tokens)s, %(cost_usd)s,"
            " %(latency_ms)s, %(attempt)s)",
            call,  # named placeholders are filled from this dict's keys
        )


def cost_for_request(request_id: str) -> tuple[int, float | None]:
    """Return (number of LLM calls, total USD) for one request.

    The total is None if any call had an unknown price: SQL's sum() silently skips NULLs,
    which would under-report the cost.
    """
    with connect() as conn:
        calls, priced, total = conn.execute(
            "SELECT count(*), count(cost_usd), sum(cost_usd) FROM llm_calls WHERE request_id = %s",
            (request_id,),
        ).fetchone()
    if calls == 0 or priced < calls:
        return calls, None
    return calls, float(total)


def migrate() -> None:
    """Apply every db/*.sql file that hasn't been applied yet, in filename order."""
    with connect() as conn:
        # Bookkeeping table: one row per migration file already run.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}

        # Numeric prefixes (001_, 002_, ...) make filename order the apply order.
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            # Run the whole file (it may hold several statements), then mark it as applied.
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            print(f"applied {path.name}")
        # Everything above is one transaction: if any file fails, none of this run's migrations stick.


if __name__ == "__main__":
    migrate()

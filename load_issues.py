import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

IN_FILE = Path("data/issues.jsonl")

load_dotenv()
database_url = os.environ["DATABASE_URL"]

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS issues (
    number       integer PRIMARY KEY,
    title        text NOT NULL,
    body         text NOT NULL,
    state        text NOT NULL,
    state_reason text,
    labels       text[] NOT NULL,
    author       text,
    comments     integer NOT NULL,
    created_at   timestamptz NOT NULL,
    closed_at    timestamptz,
    url          text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
)
"""

# Insert a new issue, or overwrite the existing row with the same number.
UPSERT = """
INSERT INTO issues (number, title, body, state, state_reason, labels,
                    author, comments, created_at, closed_at, url)
VALUES (%(number)s, %(title)s, %(body)s, %(state)s, %(state_reason)s, %(labels)s,
        %(author)s, %(comments)s, %(created_at)s, %(closed_at)s, %(url)s)
ON CONFLICT (number) DO UPDATE SET
    title        = EXCLUDED.title,
    body         = EXCLUDED.body,
    state        = EXCLUDED.state,
    state_reason = EXCLUDED.state_reason,
    labels       = EXCLUDED.labels,
    comments     = EXCLUDED.comments,
    closed_at    = EXCLUDED.closed_at,
    updated_at   = now()
"""


def read_issues():
    with IN_FILE.open() as f:
        for line in f:
            issue = json.loads(line)
            # Postgres text can't store NUL bytes, and a few issue bodies contain them.
            issue["title"] = issue["title"].replace("\x00", "")
            issue["body"] = issue["body"].replace("\x00", "")
            yield issue


with psycopg.connect(database_url) as conn:
    conn.execute(CREATE_TABLE)
    with conn.cursor() as cur:
        cur.executemany(UPSERT, read_issues())
    total = conn.execute("SELECT count(*) FROM issues").fetchone()[0]

print(f"issues table now has {total} rows")

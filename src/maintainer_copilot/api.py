import psycopg
from fastapi import FastAPI, Response

from maintainer_copilot.config import settings

app = FastAPI(title="Maintainer Copilot")


@app.get("/health")
def health(response: Response):
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        db = "ok"
    except psycopg.Error:
        db = "unreachable"
        response.status_code = 503
    return {"status": "ok" if db == "ok" else "degraded", "db": db}

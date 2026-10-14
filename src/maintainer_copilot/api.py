import re

import psycopg
import structlog
from fastapi import FastAPI, Request, Response

from maintainer_copilot.config import settings
from maintainer_copilot.log_config import configure_logging, new_request_id

configure_logging()
log = structlog.get_logger()

app = FastAPI(title="Maintainer Copilot")

# A caller may pass its own X-Request-ID so logs can be followed across services.
# Accept only short, plain ids: anything else could inject fake fields or newlines into our logs.
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if SAFE_REQUEST_ID.fullmatch(incoming) else new_request_id()

    structlog.contextvars.clear_contextvars()  # never leak the previous request's context
    structlog.contextvars.bind_contextvars(request_id= request_id)

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    log.info("http.request", method=request.method, path=request.url.path, status=response.status_code)
    return response


@app.get("/health")
def health(response: Response):
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        db = "ok"
    except psycopg.Error:
        db = "unreachable"
        response.status_code = 503
        log.warning("health.db_unreachable")
    return {"status": "ok" if db == "ok" else "degraded", "db": db}

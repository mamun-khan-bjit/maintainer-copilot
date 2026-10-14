import re

import httpx
import psycopg
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from openai import LengthFinishReasonError
from pydantic import BaseModel, ValidationError

from maintainer_copilot.config import settings
from maintainer_copilot.db import cost_for_request
from maintainer_copilot.gateway.llm import LLMGateway
from maintainer_copilot.github import GitHubClient
from maintainer_copilot.log_config import configure_logging, new_request_id
from maintainer_copilot.triage import TriageResult, fetch_labels, triage_issue

configure_logging()
log = structlog.get_logger()

app = FastAPI(title="Maintainer Copilot")

# A caller may pass its own X-Request-ID so logs can be followed across services.
# Accept only short, plain ids: anything else could inject fake fields or newlines into our logs.
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")

# We never fetch the URL the caller sends (that would let anyone make our server request
# internal addresses: SSRF). We only read the repo and issue number out of it.
ISSUE_URL = re.compile(r"https://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/(?P<number>\d+)/?")


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if SAFE_REQUEST_ID.fullmatch(incoming) else new_request_id()

    structlog.contextvars.clear_contextvars()  # never leak the previous request's context
    structlog.contextvars.bind_contextvars(request_id=request_id)

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


class DryRunRequest(BaseModel):
    issue_url: str


class DryRunResponse(BaseModel):
    request_id: str
    issue: int
    triage: TriageResult
    checks: dict
    llm_calls: int
    cost_usd: float | None


# Dependencies: tests replace these with fakes via app.dependency_overrides.
def get_gateway() -> LLMGateway:
    return LLMGateway()


def get_github() -> GitHubClient:
    return GitHubClient(settings.github_token)


@app.post("/triage/dry-run", response_model=DryRunResponse)
def triage_dry_run(
    body: DryRunRequest,
    gateway: LLMGateway = Depends(get_gateway),
    gh: GitHubClient = Depends(get_github),
):
    """Triage one issue and show the result. Nothing is written to GitHub."""
    match = ISSUE_URL.fullmatch(body.issue_url.strip())
    if not match:
        raise HTTPException(400, "expected https://github.com/<owner>/<repo>/issues/<number>")
    repo, number = match["repo"], int(match["number"])
    if repo != settings.target_repo:
        raise HTTPException(400, f"only {settings.target_repo} issues are supported")

    try:
        issue, _ = gh.get(f"/repos/{repo}/issues/{number}")
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise HTTPException(404, f"issue #{number} not found") from error
        raise
    if "pull_request" in issue:
        raise HTTPException(400, f"#{number} is a pull request, not an issue")

    labels = fetch_labels(gh, repo)
    try:
        result, checks = triage_issue(gateway, issue["title"], issue["body"] or "", labels)
    except (ValidationError, LengthFinishReasonError) as error:
        # The model answered, but not in the TriageResult shape: an upstream failure, so 502.
        raise HTTPException(502, "the model's output did not match the triage schema") from error

    request_id = structlog.contextvars.get_contextvars()[ "request_id" ]
    llm_calls, cost = cost_for_request(request_id)
    return DryRunResponse(
        request_id=request_id, issue=number, triage=result, checks=checks, llm_calls=llm_calls, cost_usd=cost
    )

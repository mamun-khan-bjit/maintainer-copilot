import json
import sys
from functools import cache
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from maintainer_copilot.config import settings
from maintainer_copilot.db import connect
from maintainer_copilot.gateway.llm import LLMGateway
from maintainer_copilot.github import GitHubClient

PROMPT_VERSION = "v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / f"triage.{PROMPT_VERSION}.md"
EXAMPLES_PATH = PROMPT_PATH.parent / f"triage.examples.{PROMPT_VERSION}.json"
MAX_BODY_CHARS = 6000  # keep the prompt inside a small local model's context window
log = structlog.get_logger()


class TriageResult(BaseModel):
    kind: Literal["bug", "feature", "question", "docs", "other"]
    summary: str = Field(description="One sentence describing the issue")
    labels: list[str] = Field(description="Labels copied exactly from the allowed list")
    missing_info: list[str] = Field(description="Information maintainers need but the issue lacks")
    evidence_quote: str = Field(description="Exact text copied from the issue that supports the kind")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence from 0.0 to 1.0")


def fetch_labels(gh: GitHubClient, repo: str) -> list[str]:
    return [label["name"] for label in gh.paginate(f"/repos/{repo}/labels", params={"per_page": 100})]


def issue_message(title: str, body: str, labels: list[str]) -> dict:
    issue_text = f"Title: {title}\n\n{body[:MAX_BODY_CHARS]}"
    content = (
        "<labels>\n" + "\n".join(labels) + "\n</labels>\n\n"
        "<issue>\n" + issue_text + "\n</issue>"
    )
    return {"role": "user", "content": content}


@cache
def load_examples() -> list[dict]:
    """Attach each example's issue text from the local DB.

    The examples file stores only issue numbers and the ideal outputs, so the repository never
    redistributes other people's issue text (see "Data sources and licensing" in the README).
    """
    examples = json.loads(EXAMPLES_PATH.read_text())
    numbers = [example["source_issue"] for example in examples]
    with connect() as conn:
        rows = conn.execute(
            "SELECT i.number, i.title, i.body FROM issues i JOIN repos r ON r.id = i.repo_id"
            " WHERE r.full_name = %s AND i.number = ANY(%s)",
            (settings.target_repo, numbers),
        ).fetchall()
    texts = {number: (title, body) for number, title, body in rows}

    missing = [number for number in numbers if number not in texts]
    if missing:
        raise RuntimeError(f"few-shot issues {missing} are not in the database; run maintainer_copilot.sync first")
    return [{**example, "title": texts[n][0], "body": texts[n][1]} for example, n in zip(examples, numbers)]


def build_messages(title: str, body: str, labels: list[str]) -> list[dict]:
    messages = [{"role": "system", "content": PROMPT_PATH.read_text()}]
    # Few-shot: show the model two worked examples as an earlier conversation.
    for example in load_examples():
        messages.append(issue_message(example["title"], example["body"], labels))
        messages.append({"role": "assistant", "content": json.dumps(example["output"])})
    messages.append(issue_message(title, body, labels))
    return messages


def normalize(text: str) -> str:
    """Collapse all whitespace so line breaks and double spaces don't break quote matching."""
    return " ".join(text.split())


def validate(result: TriageResult, title: str, body: str, allowed_labels: list[str]) -> dict:
    """Fix what the model got wrong and report it. The prompt asks nicely; this enforces."""
    allowed = set(allowed_labels)
    dropped = [label for label in result.labels if label not in allowed]
    result.labels = [label for label in result.labels if label in allowed]

    quote = normalize(result.evidence_quote)
    evidence_ok = bool(quote) and quote in normalize(f"{title} {body}")
    if not evidence_ok:
        result.evidence_quote = ""

    if dropped:
        log.warning("triage.labels_dropped", dropped=dropped)
    if not evidence_ok:
        log.warning("triage.evidence_not_found", quote=quote[:120])
    return {"dropped_labels": dropped, "evidence_ok": evidence_ok}


def triage_issue(gateway: LLMGateway, title: str, body: str, labels: list[str]):
    result = gateway.parse(build_messages(title, body, labels), TriageResult)
    checks = validate(result, title, body, labels)
    return result, checks


if __name__ == "__main__":
    number = int(sys.argv[1])
    with connect() as conn:
        title, body = conn.execute("SELECT title, body FROM issues WHERE number = %s", (number,)).fetchone()

    labels = fetch_labels(GitHubClient(settings.github_token), settings.target_repo)
    result, checks = triage_issue(LLMGateway(), title, body, labels)
    print(result.model_dump_json(indent=2))
    print("checks:", checks)
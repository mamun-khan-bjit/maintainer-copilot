import json
import time
from datetime import UTC, datetime
from pathlib import Path

from openai import LengthFinishReasonError
from pydantic import ValidationError

from maintainer_copilot.config import settings
from maintainer_copilot.db import connect
from maintainer_copilot.gateway.llm import LLMGateway
from maintainer_copilot.github import GitHubClient
from maintainer_copilot.triage import EXAMPLES_PATH, PROMPT_VERSION, fetch_labels, triage_issue

SAMPLE_SIZE = 10
TUNING_ISSUES = [13868]  # used while writing the prompt; testing on it would flatter the results
OUT_DIR = Path("data/eval")

# md5(number) gives a stable pseudo-random order: the same 10 issues every run, so runs are comparable.
SAMPLE_QUERY = """
SELECT number, title, body, labels FROM issues
WHERE NOT (number = ANY(%s))
ORDER BY md5(number::text)
LIMIT %s
"""


def main():
    excluded = [ex["source_issue"] for ex in json.loads(EXAMPLES_PATH.read_text())] + TUNING_ISSUES
    labels = fetch_labels(GitHubClient(settings.github_token), settings.target_repo)
    gateway = LLMGateway()
    with connect() as conn:
        issues = conn.execute(SAMPLE_QUERY, (excluded, SAMPLE_SIZE)).fetchall()

    rows = []
    for number, title, body, human_labels in issues:
        started = time.perf_counter()
        try:
            result, checks = triage_issue(gateway, title, body, labels)
            row = {"number": number, "schema_ok": True, "kind": result.kind, "labels": result.labels, **checks}
        except (ValidationError, LengthFinishReasonError) as error:
            # The model's output didn't fit TriageResult: this is a schema failure.
            row = {"number": number, "schema_ok": False, "error": type(error).__name__}
        row["human_labels"] = human_labels
        row["seconds"] = round(time.perf_counter() - started, 1)
        rows.append(row)
        print(row)

    ok = [r for r in rows if r["schema_ok"]]
    schema_failures = len(rows) - len(ok)
    evidence_ok = sum(1 for r in ok if r["evidence_ok"])
    dropped = sum(len(r["dropped_labels"]) for r in ok)
    label_overlap = sum(1 for r in ok if set(r["labels"]) & set(r["human_labels"]))

    print()
    print(f"prompt:            triage.{PROMPT_VERSION} + {len(excluded) - len(TUNING_ISSUES)} examples")
    print(f"schema failures:   {schema_failures}/{len(rows)}")
    print(f"evidence verified: {evidence_ok}/{len(ok)}")
    print(f"labels dropped:    {dropped}")
    print(f"shares a label with maintainers: {label_overlap}/{len(ok)}")
    print(f"total time:        {sum(r['seconds'] for r in rows):.0f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"triage_{PROMPT_VERSION}_{datetime.now(UTC):%Y%m%d_%H%M%S}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"saved:             {out}")


if __name__ == "__main__":
    main()

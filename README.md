# Maintainer Copilot

An AI assistant for open-source maintainers: answers questions with citations from docs and past
issues, flags duplicate and incomplete issues, drafts labels and replies, and asks the maintainer
for approval before writing anything to GitHub.

This is a learning project, built step by step.

## Run locally

Prerequisites: [Docker](https://www.docker.com/), [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/) with the model pulled (`ollama pull qwen2.5:3b`).

```bash
cp .env.example .env                       # then set GITHUB_TOKEN (read-only, public repos)
docker compose up -d --build               # Postgres + pgvector and the API on :8000
uv run python -m maintainer_copilot.sync   # create tables, pull 500 issues, comments and docs/
```

Try it (nothing is written to GitHub):

```bash
curl -s -X POST localhost:8000/triage/dry-run -H 'content-type: application/json' \
  -d '{"issue_url": "https://github.com/pydantic/pydantic/issues/12223"}'
```

The first sync takes about 5 minutes. Run the tests with `uv run pytest`.

Design decisions are recorded in [`docs/adr/`](docs/adr/), eval results in
[`docs/evals.md`](docs/evals.md).

## Data sources and licensing

Target repository: [`pydantic/pydantic`](https://github.com/pydantic/pydantic).

| Data | Where it comes from | License / terms |
|---|---|---|
| Documentation (`docs/**/*.md`) | pydantic repository | MIT, © Pydantic Services Inc. and contributors |
| Issues and comments | GitHub REST API | Written by individual GitHub users; covered by the [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service), **not** by the repository's MIT license |

Public data does not mean "anything goes". This project follows these rules:

- Data is stored locally for research and learning only. The raw dataset (`data/`, the database)
  is never committed, published, or redistributed.
- Answers quote only short excerpts and always link back to the original issue, comment, or doc.
- Usernames are kept only to attribute quotes and to distinguish maintainer answers
  (`author_association`); no other personal data is collected or profiled.
- Issues marked `visibility = 'security'` are never used as retrieval context or quoted.
- Access uses a read-only, fine-grained token. The bot writes only to the sandbox repository
  [`maintainer-copilot-sandbox`](https://github.com/mamun-khan-bjit/maintainer-copilot-sandbox),
  and only after a maintainer approves.
- The GitHub API is called politely: conditional requests (ETag) and rate-limit backoff.

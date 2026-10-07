# Maintainer Copilot

An AI assistant for open-source maintainers: answers questions with citations from docs and past
issues, flags duplicate and incomplete issues, drafts labels and replies, and asks the maintainer
for approval before writing anything to GitHub.

This is a learning project, built step by step.

## Running locally

```bash
cp .env.example .env            # then fill in the values
docker compose up -d            # Postgres + pgvector and the API
uv run python -m maintainer_copilot.db     # apply db/*.sql migrations
uv run python -m maintainer_copilot.sync   # pull issues, comments and docs/
curl localhost:8000/health
```

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

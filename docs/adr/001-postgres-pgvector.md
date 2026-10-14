# ADR 001: Store embeddings in Postgres with pgvector, not a separate vector database

- Status: Accepted
- Date: 2026-10-14

## Context

The bot must search issues, maintainer comments and docs by meaning, so we will store an
embedding (a vector of 1024 numbers from `bge-m3`) for each of them. Today that is about
1,800 items (500 issues, 1,221 comments, 91 doc pages); indexing every pydantic issue would
still be well under 100,000 vectors once docs are split into chunks.

Everything else the bot knows already lives in Postgres: issues, comments, docs, the audit log and
LLM call records. Every search must also apply filters that come from those tables: the right
`repo_id`, and never return an issue whose `visibility` is `'security'`.

## Options considered

1. **Postgres + pgvector**: the database we already run.
2. **A dedicated vector database** (e.g. Qdrant, Weaviate, Pinecone).

## Decision

Use pgvector in our existing Postgres, because the security filter and the similarity search then
run in a single query against a single source of truth.

## Consequences

### Good

- **Safety filters can't drift.** `WHERE visibility = 'public' ORDER BY embedding <=> $1` is one
  query. With a separate vector store, every issue's visibility would have to be copied there and
  kept in sync; until a sync caught up, a newly flagged security issue could still be retrieved
  and quoted.
- **Transactions.** Updating an issue, its embedding and its visibility happens in one transaction,
  so search never sees a half-updated issue.
- **One less service** to run, back up, secure and pay for. Local development stays a single
  `docker compose up`.
- **Plain SQL joins** between search results and issues, comments, labels and `llm_calls`, which
  helps evals and debugging.

### Bad / risks

- **Scale ceiling.** Dedicated vector databases are built for tens of millions of vectors with
  sharding and replication; at that size pgvector needs much more tuning and hardware.
- **Index care is ours.** HNSW indexes use memory and their settings (`m`, `ef_construction`,
  `ef_search`) trade recall against speed. We have to measure and tune them ourselves.
- **Fewer built-in extras.** Features like managed hybrid search or multi-tenancy that some vector
  databases provide out of the box must be built with SQL (e.g. combining full-text search and
  vector similarity ourselves).

## When to revisit

Reconsider this decision if any of these become true:

- more than 5 million vectors are indexed, or
- p95 latency of a filtered similarity search exceeds 200 ms after HNSW tuning, or
- the vector index no longer fits in the database server's memory.

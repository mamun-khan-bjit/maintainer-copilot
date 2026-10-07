CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE repos (
    id             serial PRIMARY KEY,
    full_name      text NOT NULL UNIQUE,
    license        text,
    default_branch text NOT NULL,
    synced_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE issues (
    repo_id        integer NOT NULL REFERENCES repos (id),
    number         integer NOT NULL,
    title          text NOT NULL,
    body           text NOT NULL,
    state          text NOT NULL,
    state_reason   text,
    labels         text[] NOT NULL DEFAULT '{}',
    author         text,
    comments_count integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL,
    updated_at     timestamptz NOT NULL,
    closed_at      timestamptz,
    url            text NOT NULL,
    -- 'security' issues must never be used as retrieval context or quoted in replies (Week 4).
    visibility     text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'security')),
    synced_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_id, number)
);

CREATE TABLE comments (
    id                 bigint PRIMARY KEY,
    repo_id            integer NOT NULL,
    issue_number       integer NOT NULL,
    author             text,
    -- OWNER / MEMBER / COLLABORATOR comments are maintainer answers, the most useful evidence.
    author_association text NOT NULL,
    body               text NOT NULL,
    created_at         timestamptz NOT NULL,
    updated_at         timestamptz NOT NULL,
    url                text NOT NULL,
    synced_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (repo_id, issue_number) REFERENCES issues (repo_id, number) ON DELETE CASCADE
);

CREATE INDEX comments_issue_idx ON comments (repo_id, issue_number);

CREATE TABLE docs (
    repo_id   integer NOT NULL REFERENCES repos (id),
    path      text NOT NULL,
    sha       text NOT NULL,
    content   text NOT NULL,
    url       text NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_id, path)
);

CREATE TABLE audit_events (
    id          bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,
    action      text NOT NULL,
    target      text,
    details     jsonb NOT NULL DEFAULT '{}'
);

-- The audit log is evidence: rows may be added, never changed or removed.
CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();

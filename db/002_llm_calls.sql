-- One row per successful LLM call: what it cost, how long it took, and which request it belonged to.
CREATE TABLE llm_calls (
    id            bigserial PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    request_id    text,
    task          text NOT NULL,
    model         text NOT NULL,
    input_tokens  integer NOT NULL,
    output_tokens integer NOT NULL,
    -- Money: exact decimal, not floating point. NULL means "price unknown", never "free".
    cost_usd      numeric(12, 6),
    latency_ms    integer NOT NULL,
    attempt       integer NOT NULL
);

CREATE INDEX llm_calls_request_id_idx ON llm_calls (request_id);
CREATE INDEX llm_calls_created_at_idx ON llm_calls (created_at);
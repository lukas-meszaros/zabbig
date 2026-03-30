-- 01_schema.sql — Create demo tables for integration tests
-- Executed automatically when the postgres-test container starts.

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(64) NOT NULL,
    email       VARCHAR(128) NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount      NUMERIC(10,2) NOT NULL,
    status      VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    started_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMP
);

-- Metric used by collector tests: a single-row, single-column int table
CREATE TABLE IF NOT EXISTS metrics_test (
    key         VARCHAR(64) PRIMARY KEY,
    value       NUMERIC NOT NULL,
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

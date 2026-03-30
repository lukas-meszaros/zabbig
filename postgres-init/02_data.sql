-- 02_data.sql — Seed demo data for integration tests

-- Users (mix of active and inactive)
INSERT INTO users (username, email, active) VALUES
    ('alice',   'alice@example.com',   TRUE),
    ('bob',     'bob@example.com',     TRUE),
    ('charlie', 'charlie@example.com', FALSE),
    ('diana',   'diana@example.com',   TRUE)
ON CONFLICT DO NOTHING;

-- Orders
INSERT INTO orders (user_id, amount, status) VALUES
    (1, 99.99,  'completed'),
    (1, 149.50, 'completed'),
    (2, 29.00,  'pending'),
    (3, 75.00,  'cancelled'),
    (4, 200.00, 'completed'),
    (4, 50.00,  'pending')
ON CONFLICT DO NOTHING;

-- Sessions (some open, some closed)
INSERT INTO sessions (user_id, started_at, ended_at) VALUES
    (1, NOW() - INTERVAL '2 hours',  NOW() - INTERVAL '1 hour'),
    (2, NOW() - INTERVAL '30 minutes', NULL),
    (4, NOW() - INTERVAL '10 minutes', NULL)
ON CONFLICT DO NOTHING;

-- Metric counters for collector tests
INSERT INTO metrics_test (key, value) VALUES
    ('active_users',    3),
    ('pending_orders',  2),
    ('open_sessions',   2),
    ('error_count',     0)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

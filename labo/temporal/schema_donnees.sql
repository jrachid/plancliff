DROP TABLE IF EXISTS tasks;
CREATE TABLE tasks (range_hash BIGINT NOT NULL, task_queue_id BYTEA NOT NULL, task_id BIGINT NOT NULL, data BYTEA NOT NULL, data_encoding VARCHAR(16) NOT NULL, PRIMARY KEY (range_hash, task_queue_id, task_id));
INSERT INTO tasks SELECT q, ('\x00'::bytea || int4send(q)), t, '\x00', 'Proto3' FROM generate_series(1, 2000) q, generate_series(1, 20) t;
INSERT INTO tasks SELECT 0, '\x00ff'::bytea, t, '\x00', 'Proto3' FROM generate_series(1, 200000) t;
ANALYZE tasks;

DROP TABLE IF EXISTS tuple;
CREATE TABLE tuple (
    store TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    _user TEXT NOT NULL,
    user_type TEXT NOT NULL,
    ulid TEXT NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL,
    condition_name TEXT,
    condition_context BYTEA,
    PRIMARY KEY (store, object_type, object_id, relation, _user)
);
CREATE INDEX idx_tuple_partial_user ON tuple (store, object_type, object_id, relation, _user) WHERE user_type = 'user';
CREATE INDEX idx_tuple_partial_userset ON tuple (store, object_type, object_id, relation, _user) WHERE user_type = 'userset';
CREATE UNIQUE INDEX idx_tuple_ulid ON tuple (ulid);
CREATE INDEX idx_user_lookup ON tuple (store, _user, relation, object_type, object_id COLLATE "C");

INSERT INTO tuple
SELECT 'store1',
       CASE WHEN g <= 400000 THEN 'document' ELSE 'type' || (g % 40) END,
       'obj' || g,
       CASE WHEN g <= 400000 THEN 'viewer' ELSE 'rel' || (g % 25) END,
       CASE WHEN g <= 400000 THEN 'group:hot' || (g % 4) || '#member' ELSE 'user:u' || g END,
       CASE WHEN g <= 400000 THEN 'userset' ELSE 'user' END,
       'ulid' || g,
       now()
FROM generate_series(1, 600000) g;
ANALYZE tuple;

ALTER TABLE tasks ADD COLUMN request_original TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN result_text TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN error_text TEXT NOT NULL DEFAULT '';
CREATE TABLE operations (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tool TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    error_text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX operations_task_id ON operations(task_id);
PRAGMA user_version = 2;

-- gorgon-tracker schema (migration 1)
-- All timestamps are UTC epoch milliseconds (INTEGER).

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    platform TEXT NOT NULL DEFAULT 'linux',
    config_snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    source TEXT NOT NULL,
    captured_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    dedup_hash TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_events_session ON raw_events(session_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_source ON raw_events(source);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL,
    monster TEXT NOT NULL,
    can_skin INTEGER NOT NULL DEFAULT 0,
    can_butcher INTEGER NOT NULL DEFAULT 0,
    can_extract INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sources_session ON sources(session_id, captured_at);

CREATE TABLE IF NOT EXISTS loot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL,
    item TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_loot_session ON loot(session_id, captured_at);

CREATE TABLE IF NOT EXISTS burials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_burials_session ON burials(session_id, captured_at);

CREATE TABLE IF NOT EXISTS target_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL,
    target_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_target_sightings_session ON target_sightings(session_id, captured_at);

CREATE TABLE IF NOT EXISTS zone_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL,
    zone_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_zone_changes_session ON zone_changes(session_id, captured_at);

CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    encounter_uuid TEXT NOT NULL,
    monster TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_encounters_session ON encounters(session_id, started_at);

CREATE TABLE IF NOT EXISTS loot_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    encounter_id INTEGER REFERENCES encounters(id),
    captured_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    item TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 1,
    activity TEXT NOT NULL DEFAULT 'Looting',
    zone TEXT NOT NULL DEFAULT 'Unknown',
    status TEXT NOT NULL DEFAULT 'Linked',
    lag_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_loot_drops_session ON loot_drops(session_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_loot_drops_encounter ON loot_drops(encounter_id);

CREATE VIEW IF NOT EXISTS v_sessions AS
SELECT id,
       uuid,
       started_at,
       ended_at,
       ended_at - started_at AS duration_ms,
       platform
FROM sessions;

CREATE VIEW IF NOT EXISTS v_summary AS
SELECT ld.zone,
       ld.source AS monster,
       ld.activity,
       ld.item,
       SUM(ld.amount) AS total_quantity,
       COUNT(*) AS drop_count
FROM loot_drops ld
WHERE ld.status = 'Linked'
GROUP BY ld.zone, ld.source, ld.activity, ld.item;

CREATE VIEW IF NOT EXISTS v_drop_rates AS
WITH encounter_counts AS (
    SELECT source AS monster, COUNT(DISTINCT encounter_id) AS encounter_count
    FROM loot_drops
    WHERE status = 'Linked' AND encounter_id IS NOT NULL
    GROUP BY source
)
SELECT ld.source AS monster,
       ld.item,
       COUNT(*) AS drops,
       SUM(ld.amount) AS quantity,
       COALESCE(e.encounter_count, 0) AS encounters,
       ROUND(CAST(COUNT(*) AS REAL) / NULLIF(COALESCE(e.encounter_count, 0), 0), 4) AS drop_rate
FROM loot_drops ld
LEFT JOIN encounter_counts e ON e.monster = ld.source
WHERE ld.status = 'Linked'
GROUP BY ld.source, ld.item;
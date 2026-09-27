"""Public read-only web surface: read API + public SPA + optional token ingest.

Deployed with ``gorgon-tracker serve``, this is the immutable public face of the
tool. It mounts only the read router, the read-only public SPA, and — when
``[serve]`` configures it — a single write-only ingest endpoint that accepts
verified loot rows published from a local capture tool. No control endpoints
(config, daemon, overrides, replay, calibrate) are ever mounted here.

Public payloads use the same schema as the local database; published rows are
attached to a stable synthetic session so every existing read query and SSE
stream works unchanged. Insert is an upsert on the natural key
``(captured_at, source, item, amount)``, so re-publishing a corrected row
replaces the public copy. See ``docs/specs/publish.md``.
"""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import config_write as config_write_mod
from . import db as db_mod
from .publish import PUBLISH_FIELDS
from .serve import build_read_router
from .spa import mount_spa

_APP_ROOT = Path(__file__).resolve().parent
_STATIC_DIR = _APP_ROOT / "static" / "public"

_PUBLISHED_SESSION_UUID = "published"

_REQUIRED_FIELDS = ("captured_at", "source", "item", "amount")

_DEFAULTS: dict[str, Any] = {
    "activity": "Looting",
    "zone": "Unknown",
    "status": "Linked",
    "lag_ms": 0,
    "linked_via": "monster",
    "corroborated_by_search": False,
    "missed": False,
}


class IngestBody(BaseModel):
    rows: list[dict[str, Any]]


def ensure_published_schema(db_path: str, *, publish_indexes: bool = False) -> None:
    """Migrate the DB, seed the catalog, and (optionally) add publish constraints.

    The unique index on the publish natural key makes the ingest upsert
    well-defined. It exists only on the ingest database, so ``publish_indexes``
    is true only when ``serve`` has ingest enabled. A plain read-only ``serve``
    (the default) must work against any gorgon-tracker database, including a
    local capture DB that records duplicate same-second drops.
    """
    conn = db_mod.connect(db_path)
    try:
        db_mod.migrate(conn)
        db_mod.seed_from_catalog(conn)
        if not publish_indexes:
            return
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_loot_drops_publish_key"
                " ON loot_drops(captured_at, source, item, amount)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_encounters_publish_uuid ON encounters(encounter_uuid)"
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "the ingest database already contains duplicate (captured_at, source, item, amount) rows. "
                "Point serve at an empty public database and plain local capture DB for staging."
            ) from exc
        conn.commit()
    finally:
        conn.close()


def _published_session_id(conn: Any) -> int:
    row = conn.execute("SELECT id FROM sessions WHERE uuid = ?", (_PUBLISHED_SESSION_UUID,)).fetchone()
    if row is not None:
        return int(row["id"])
    return db_mod.new_session(conn, platform="public", config_snapshot={"source": _PUBLISHED_SESSION_UUID})


def _validate_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one incoming publish payload; returns a normalized row."""
    if not isinstance(raw, dict):
        raise ValueError("each row must be an object")
    unknown = set(raw) - set(PUBLISH_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ValueError(f"missing required field: {field}")

    row: dict[str, Any] = dict(raw)
    for field in PUBLISH_FIELDS:
        if field not in row and field not in _REQUIRED_FIELDS and field in _DEFAULTS:
            row[field] = _DEFAULTS[field]
    for field in PUBLISH_FIELDS:
        row.setdefault(field, None)

    if not isinstance(row["captured_at"], int) or isinstance(row["captured_at"], bool) or row["captured_at"] <= 0:
        raise ValueError("captured_at must be a positive integer (ms)")
    for field in ("source", "item"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if not isinstance(row["amount"], int) or isinstance(row["amount"], bool) or row["amount"] < 1:
        raise ValueError("amount must be a positive integer")

    for field, expected in PUBLISH_FIELDS.items():
        value = row.get(field)
        if field in ("captured_at", "source", "item", "amount"):
            continue
        if value is None:
            continue
        if field in ("corroborated_by_search", "missed"):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
            continue
        if field == "encounter_activities":
            if not isinstance(value, list):
                raise ValueError("encounter_activities must be a list")
            for entry in value:
                if not isinstance(entry, dict):
                    raise ValueError("each encounter activity must be an object")
                if not isinstance(entry.get("activity"), str) or not entry["activity"].strip():
                    raise ValueError("each encounter activity needs a non-empty 'activity'")
                performed = entry.get("performed_at")
                if not isinstance(performed, int) or isinstance(performed, bool) or performed <= 0:
                    raise ValueError("each encounter activity needs a positive integer 'performed_at'")
            continue
        if expected in ("int", "int|None"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field} must be {expected}")
        elif expected in ("str", "str|None") and not isinstance(value, str):
            raise ValueError(f"{field} must be {expected}")
    if row["status"] not in ("Linked", "Orphaned"):
        raise ValueError("status must be 'Linked' or 'Orphaned'")
    if not row.get("linked_via"):
        raise ValueError("linked_via must be a non-empty string")
    return row


def _ingest_row(conn: Any, session_id: int, row: dict[str, Any]) -> str:
    """Insert or replace one published row; returns 'created' or 'replaced'."""
    encounter_id: int | None = None
    encounter_uuid = row.get("encounter_uuid")
    if encounter_uuid:
        conn.execute(
            "INSERT OR IGNORE INTO encounters (session_id, encounter_uuid, monster, started_at, zone)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, encounter_uuid, row["source"], row["captured_at"], row["zone"]),
        )
        found = conn.execute(
            "SELECT id FROM encounters WHERE encounter_uuid = ?", (encounter_uuid,)
        ).fetchone()
        if found is not None:
            encounter_id = int(found["id"])
            for entry in row.get("encounter_activities") or []:
                db_mod.insert_encounter_activity(
                    conn,
                    session_id,
                    encounter_id,
                    entry["activity"],
                    entry["performed_at"],
                )

    existing = conn.execute(
        "SELECT id FROM loot_drops WHERE captured_at = ? AND source = ? AND item = ? AND amount = ?",
        (row["captured_at"], row["source"], row["item"], row["amount"]),
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE loot_drops SET encounter_id = ?, activity = ?, zone = ?, status = ?, lag_ms = ?,"
            " linked_via = ?, monster_name = ?, monster_lag_ms = ?, target_name = ?,"
            " target_lag_ms = ?, corroborated_by_search = ?, instance_id = ?, entity_id = ?,"
            " item_code_id = ?, item_display = ?, missed = ?, killer_json = ? WHERE id = ?",
            (
                encounter_id, row["activity"], row["zone"], row["status"], row["lag_ms"],
                row["linked_via"], row["monster_name"], row["monster_lag_ms"],
                row["target_name"], row["target_lag_ms"],
                row["corroborated_by_search"], row["instance_id"], row["entity_id"],
                row["item_code_id"], row["item_display"], row["missed"], row["killer_json"],
                existing["id"],
            ),
        )
        return "replaced"

    conn.execute(
        "INSERT INTO loot_drops (session_id, encounter_id, captured_at, source, item, amount,"
        " activity, zone, status, lag_ms, linked_via, monster_name, monster_lag_ms, target_name,"
        " target_lag_ms, corroborated_by_search, instance_id, entity_id, item_code_id,"
        " item_display, missed, killer_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, encounter_id, row["captured_at"], row["source"], row["item"],
            row["amount"], row["activity"], row["zone"], row["status"], row["lag_ms"],
            row["linked_via"], row["monster_name"], row["monster_lag_ms"], row["target_name"],
            row["target_lag_ms"], row["corroborated_by_search"], row["instance_id"],
            row["entity_id"], row["item_code_id"], row["item_display"], row["missed"],
            row["killer_json"],
        ),
    )
    return "created"


def build_ingest_router(db_path: str, token: str) -> APIRouter:
    """The write-only ingest surface. Refuses to mount without a token."""
    router = APIRouter(prefix="/api")

    def _authorized(authorization: str | None) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            return False
        provided = authorization[len("Bearer "):].strip()
        return secrets.compare_digest(provided, token)

    @router.post("/ingest/loot")
    def ingest_loot(
        body: IngestBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="invalid or missing publish token")
        if not body.rows or len(body.rows) > 500:
            raise HTTPException(status_code=422, detail="'rows' must contain 1..500 rows")
        try:
            normalized = [_validate_row(r) for r in body.rows]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        conn = db_mod.connect(db_path)
        db_mod.migrate(conn)
        try:
            session_id = _published_session_id(conn)
            with conn:
                actions = [_ingest_row(conn, session_id, row) for row in normalized]
        finally:
            conn.close()
        created = sum(1 for a in actions if a == "created")
        replaced = sum(1 for a in actions if a == "replaced")
        return {"received": len(actions), "created": created, "replaced": replaced, "actions": actions}

    return router


def build_public_app(
    db_path: str,
    config_path: str | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Create the public FastAPI app used by ``serve``."""
    cfg = config_write_mod.load_config_path(config_path)
    spa_dir = static_dir or _STATIC_DIR
    read_router, _ = build_read_router(db_path, include_index=not spa_dir.is_dir())
    app = FastAPI(
        title="gorgon-tracker public",
        version="0.1.0",
        description="Project Gorgon loot data (read-only)",
    )
    app.include_router(read_router)
    if cfg.serve.ingest_enabled:
        if not cfg.serve.ingest_token:
            raise ValueError("serve.ingest_enabled requires serve.ingest_token")
        app.include_router(build_ingest_router(db_path, cfg.serve.ingest_token))
    ensure_published_schema(db_path, publish_indexes=cfg.serve.ingest_enabled)
    if spa_dir.is_dir():
        mount_spa(app, spa_dir)
    return app


def run_public(
    db_path: str,
    config_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    import uvicorn

    uvicorn.run(build_public_app(db_path, config_path), host=host, port=port)
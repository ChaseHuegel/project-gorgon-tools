"""Local publish client: push verified loot rows to a public server.

The local tool (``web``) is the capture/staging/audit side. A user reviews and
fixes rows in the Loot page, checks the ones to publish, and clicks Publish.
This module builds the *effective* (override-merged) payload for each selected
row, POSTs batches to the public server's ``POST /api/ingest/loot`` endpoint,
and records the outcome in ``loot_publications`` for the audit trail.

The server-side ingest contract lives at ``docs/specs/publish.md``. Natural-key
re-place semantics: a remote row with the same ``(captured_at, source, item,
amount)`` is replaced by the freshly published copy (see ``public.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, cast
from urllib import error as urlerror
from urllib.request import Request, urlopen

from .timeutil import utc_now_ms

MAX_BATCH = 500

# Canonical publish payload fields and their wire types. The server-side ingest
# validator in ``public.py`` applies the same contract.
PUBLISH_FIELDS: dict[str, str] = {
    "captured_at": "int",
    "source": "str",
    "item": "str",
    "amount": "int",
    "activity": "str",
    "zone": "str",
    "status": "str",
    "lag_ms": "int",
    "linked_via": "str",
    "monster_name": "str|None",
    "monster_lag_ms": "int|None",
    "target_name": "str|None",
    "target_lag_ms": "int|None",
    "corroborated_by_search": "bool",
    "instance_id": "int|None",
    "entity_id": "int|None",
    "item_code_id": "int|None",
    "item_display": "str|None",
    "missed": "bool",
    "killer_json": "str|None",
    "encounter_uuid": "str|None",
    "encounter_activities": "list|None",
}

_SELECT_SQL = (
    "SELECT ld.id, ld.captured_at, ld.source, ld.item, ld.amount, ld.activity, ld.zone,"
    " ld.status, ld.lag_ms, ld.linked_via, ld.monster_name, ld.monster_lag_ms,"
    " ld.target_name, ld.target_lag_ms, ld.corroborated_by_search,"
    " ld.instance_id, ld.entity_id, ld.item_code_id, ld.item_display,"
    " ld.missed, ld.killer_json, e.encounter_uuid, e.id AS encounter_id,"
    " ov.source AS ov_source, ov.status AS ov_status, ov.activity AS ov_activity"
    " FROM loot_drops ld"
    " LEFT JOIN encounters e ON e.id = ld.encounter_id"
    " LEFT JOIN loot_overrides ov ON ov.loot_drop_id = ld.id"
    " WHERE ld.id IN ({marks})"
)

_UPSERT_PUBLICATION_SQL = """
INSERT INTO loot_publications
    (loot_drop_id, published_at, payload_json, remote_batch, status, message, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(loot_drop_id) DO UPDATE SET
    published_at = excluded.published_at,
    payload_json = excluded.payload_json,
    remote_batch = excluded.remote_batch,
    status = excluded.status,
    message = excluded.message
"""


def _chunked(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def plan_payload(conn: Any, ids: list[int]) -> list[dict[str, Any]]:
    """Build the effective publish payload for each selected loot drop."""
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(_SELECT_SQL.format(marks=marks), ids).fetchall()
    by_id = {int(r["id"]): r for r in rows}

    enc_ids = sorted({int(r["encounter_id"]) for r in rows if r["encounter_id"] is not None})
    activities_by_enc: dict[int, list[dict[str, Any]]] = {}
    if enc_ids:
        enc_marks = ",".join("?" for _ in enc_ids)
        for act in conn.execute(
            "SELECT encounter_id, activity, performed_at FROM encounter_activities"
            f" WHERE encounter_id IN ({enc_marks}) ORDER BY performed_at",
            enc_ids,
        ):
            activities_by_enc.setdefault(int(act["encounter_id"]), []).append(
                {"activity": act["activity"], "performed_at": act["performed_at"]}
            )

    planned: list[dict[str, Any]] = []
    for loot_drop_id in ids:
        r = by_id.get(loot_drop_id)
        if r is None:
            continue
        payload: dict[str, Any] = {
            "captured_at": r["captured_at"],
            "source": r["ov_source"] or r["source"],
            "item": r["item"],
            "amount": r["amount"],
            "activity": r["ov_activity"] or r["activity"],
            "zone": r["zone"],
            "status": r["ov_status"] or r["status"],
            "lag_ms": r["lag_ms"],
            "linked_via": r["linked_via"],
            "monster_name": r["monster_name"],
            "monster_lag_ms": r["monster_lag_ms"],
            "target_name": r["target_name"],
            "target_lag_ms": r["target_lag_ms"],
            "corroborated_by_search": bool(r["corroborated_by_search"]),
            "instance_id": r["instance_id"],
            "entity_id": r["entity_id"],
            "item_code_id": r["item_code_id"],
            "item_display": r["item_display"],
            "missed": bool(r["missed"]),
            "killer_json": r["killer_json"],
        }
        if r["encounter_uuid"]:
            payload["encounter_uuid"] = r["encounter_uuid"]
            if r["encounter_id"] is not None:
                payload["encounter_activities"] = activities_by_enc.get(int(r["encounter_id"]), [])
        planned.append({"loot_drop_id": loot_drop_id, "payload": payload})
    return planned


def push_batch(url: str, token: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """POST one payload batch to the public ingest endpoint; returns its summary."""
    base = url.rstrip("/")
    req = Request(
        f"{base}/api/ingest/loot",
        data=json.dumps({"rows": rows}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"publish server {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"publish server unreachable: {exc.reason}") from exc


def record_publication(
    conn: Any,
    loot_drop_id: int,
    payload: dict[str, Any],
    *,
    remote_batch: str | None,
    status: str,
    message: str | None,
) -> None:
    now = utc_now_ms()
    conn.execute(
        _UPSERT_PUBLICATION_SQL,
        (
            loot_drop_id,
            now,
            json.dumps(payload),
            remote_batch,
            status,
            message,
            now,
        ),
    )


def publish_rows(conn: Any, url: str, token: str, ids: list[int]) -> list[dict[str, Any]]:
    """Publish the selected rows and record each outcome; returns per-row results."""
    planned = plan_payload(conn, ids)
    results: list[dict[str, Any]] = []
    batch_no = 0
    with conn:
        for chunk in _chunked(planned, MAX_BATCH):
            batch_no += 1
            batch_id = f"batch-{batch_no}-{utc_now_ms()}"
            try:
                summary = push_batch(url, token, [item["payload"] for item in chunk])
                actions = summary.get("actions") or []
            except RuntimeError as exc:
                for item in chunk:
                    record_publication(
                        conn, item["loot_drop_id"], item["payload"],
                        remote_batch=batch_id, status="failed", message=str(exc),
                    )
                    results.append({
                        "loot_drop_id": item["loot_drop_id"], "status": "failed",
                        "remote_action": None, "message": str(exc),
                    })
                continue
            for index, item in enumerate(chunk):
                action = actions[index] if index < len(actions) else "created"
                message = f"{action} on remote"
                record_publication(
                    conn, item["loot_drop_id"], item["payload"],
                    remote_batch=batch_id, status="ok", message=message,
                )
                results.append({
                    "loot_drop_id": item["loot_drop_id"], "status": "ok",
                    "remote_action": action, "message": message,
                })
    return results
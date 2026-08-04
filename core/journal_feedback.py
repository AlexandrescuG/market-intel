"""Система обратной связи: виджет-кружок, взвешенные голоса, кластеры, site_copy."""
import base64
import json
import sqlite3
import time
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "journal.db"
_SCREENSHOTS = Path(__file__).parent.parent / "data" / "screenshots"
_SCREENSHOTS.mkdir(exist_ok=True)

_VALID_KINDS   = {"bug", "idea", "other"}
_VALID_STATUS  = {"new", "grouped", "planned", "done", "rejected"}
_MAX_SCREENSHOT_BYTES = 3_000_000  # 3 MB base64 decode limit

# Rate-limit state (in-process, per identifier)
_rate_state: dict[str, list[float]] = {}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_schema() -> None:
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS feedback (
            id              TEXT PRIMARY KEY
                                DEFAULT (lower(hex(randomblob(8)))),
            user_id         TEXT,
            level_at_submit INTEGER NOT NULL DEFAULT 1,
            kind            TEXT NOT NULL DEFAULT 'other'
                                CHECK(kind IN ('bug','idea','other')),
            comment         TEXT NOT NULL DEFAULT '',
            page_url        TEXT NOT NULL DEFAULT '',
            screenshot_path TEXT,
            ua              TEXT,
            viewport        TEXT,
            created_ts      TEXT NOT NULL
                                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            cluster_id      TEXT,
            status          TEXT NOT NULL DEFAULT 'new'
                                CHECK(status IN ('new','grouped','planned','done','rejected'))
        );
        CREATE TABLE IF NOT EXISTS feedback_votes (
            cluster_id TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            weight     INTEGER NOT NULL DEFAULT 1,
            ts         TEXT NOT NULL
                           DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            UNIQUE(cluster_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS feedback_clusters (
            id           TEXT PRIMARY KEY
                             DEFAULT (lower(hex(randomblob(6)))),
            title        TEXT NOT NULL DEFAULT '',
            tags         TEXT NOT NULL DEFAULT '[]',
            total_weight INTEGER NOT NULL DEFAULT 0,
            voters       INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'new'
                             CHECK(status IN ('new','grouped','planned','done','rejected')),
            updated_ts   TEXT NOT NULL
                             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE TABLE IF NOT EXISTS site_copy (
            copy_id      TEXT PRIMARY KEY,
            page         TEXT NOT NULL DEFAULT '',
            text_current TEXT NOT NULL DEFAULT '',
            text_default TEXT NOT NULL DEFAULT '',
            updated_by   TEXT,
            updated_ts   TEXT NOT NULL
                             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            user_id TEXT PRIMARY KEY,
            role    TEXT NOT NULL DEFAULT 'admin'
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_cluster  ON feedback(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_created  ON feedback(created_ts);
        CREATE INDEX IF NOT EXISTS idx_fvotes_cluster    ON feedback_votes(cluster_id);
        CREATE INDEX IF NOT EXISTS idx_clusters_weight   ON feedback_clusters(total_weight DESC);
    """)
    c.commit()
    c.close()


def check_rate_limit(identifier: str, limit: int = 5, window: int = 3600) -> bool:
    """True если в пределах лимита, False если превышен."""
    now = time.time()
    times = _rate_state.get(identifier, [])
    times = [t for t in times if now - t < window]
    if len(times) >= limit:
        _rate_state[identifier] = times
        return False
    times.append(now)
    _rate_state[identifier] = times
    return True


def _get_user_level(user_id: str | None) -> int:
    """Берёт уровень из xp_events той же БД."""
    if not user_id:
        return 1
    try:
        c = _conn()
        row = c.execute(
            "SELECT level FROM xp_events WHERE user_id=? ORDER BY ts DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        c.close()
        if row:
            return max(1, int(row["level"]))
        # Если xp_events нет уровня — попробуем через gamification aggregate
        c = _conn()
        row = c.execute(
            "SELECT level FROM gamification_state WHERE user_id=? LIMIT 1",
            (user_id,),
        ).fetchone()
        c.close()
        if row:
            return max(1, int(row["level"]))
    except Exception:
        pass
    return 1


def submit_feedback(
    *,
    user_id: str | None,
    kind: str,
    comment: str,
    page_url: str,
    screenshot_b64: str | None,
    ua: str,
    viewport: str,
) -> dict:
    kind = kind if kind in _VALID_KINDS else "other"
    comment = (comment or "").strip()[:2000]
    level = _get_user_level(user_id)

    screenshot_path: str | None = None
    if screenshot_b64:
        raw = screenshot_b64
        if "," in raw:
            raw = raw.split(",", 1)[1]
        if len(raw) > _MAX_SCREENSHOT_BYTES:
            raw = raw[:_MAX_SCREENSHOT_BYTES]
        try:
            img_bytes = base64.b64decode(raw + "==")
            # Генерируем временный ID для имени файла
            import secrets
            fid = secrets.token_hex(8)
            fpath = _SCREENSHOTS / f"{fid}.jpg"
            fpath.write_bytes(img_bytes)
            screenshot_path = f"screenshots/{fid}.jpg"
        except Exception:
            screenshot_path = None

    c = _conn()
    cur = c.execute(
        """INSERT INTO feedback
           (user_id, level_at_submit, kind, comment, page_url,
            screenshot_path, ua, viewport)
           VALUES (?,?,?,?,?,?,?,?)""",
        (user_id, level, kind, comment, page_url,
         screenshot_path, ua, viewport),
    )
    feedback_id = cur.lastrowid
    # Получаем сгенерированный ID
    row = c.execute(
        "SELECT id FROM feedback WHERE rowid=?", (feedback_id,)
    ).fetchone()
    rid = row["id"] if row else str(feedback_id)
    c.commit()
    c.close()
    return {"ok": True, "id": rid, "level_at_submit": level}


def vote_on_cluster(cluster_id: str, user_id: str, weight: int) -> dict:
    """Голос 'у меня тоже'. Idempotent через UNIQUE(cluster_id,user_id)."""
    weight = max(1, min(weight, 8))
    c = _conn()
    try:
        c.execute(
            "INSERT OR IGNORE INTO feedback_votes(cluster_id,user_id,weight) VALUES(?,?,?)",
            (cluster_id, user_id, weight),
        )
        if c.execute("SELECT changes()").fetchone()[0] == 0:
            c.close()
            return {"ok": False, "error": "already_voted"}
        c.execute(
            """UPDATE feedback_clusters
               SET total_weight = total_weight + ?,
                   voters       = voters + 1,
                   updated_ts   = strftime('%Y-%m-%dT%H:%M:%S','now')
               WHERE id = ?""",
            (weight, cluster_id),
        )
        c.commit()
        row = c.execute(
            "SELECT total_weight, voters FROM feedback_clusters WHERE id=?",
            (cluster_id,),
        ).fetchone()
        c.close()
        return {"ok": True, "total_weight": row["total_weight"] if row else 0}
    except Exception as e:
        c.close()
        return {"ok": False, "error": str(e)}


def get_clusters(
    status: str | None = None,
    kind: str | None = None,
    page_url: str | None = None,
    limit: int = 100,
) -> list[dict]:
    c = _conn()
    q = """
        SELECT cl.*,
               (SELECT COUNT(*) FROM feedback f WHERE f.cluster_id = cl.id) AS item_count
        FROM feedback_clusters cl
        WHERE 1=1
    """
    args: list = []
    if status:
        q += " AND cl.status=?"; args.append(status)
    q += " ORDER BY cl.total_weight DESC LIMIT ?"
    args.append(limit)
    rows = c.execute(q, args).fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        result.append(d)
    return result


def get_cluster_feedbacks(cluster_id: str) -> list[dict]:
    c = _conn()
    rows = c.execute(
        """SELECT id, user_id, level_at_submit, kind, comment,
                  page_url, screenshot_path, ua, viewport, created_ts, status
           FROM feedback WHERE cluster_id=? ORDER BY created_ts DESC""",
        (cluster_id,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_unassigned_feedback(limit: int = 200) -> list[dict]:
    c = _conn()
    rows = c.execute(
        """SELECT id, user_id, level_at_submit, kind, comment,
                  page_url, created_ts
           FROM feedback WHERE cluster_id IS NULL ORDER BY created_ts DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def update_cluster_status(cluster_id: str, status: str, updated_by: str = "") -> dict:
    if status not in _VALID_STATUS:
        return {"ok": False, "error": "invalid status"}
    c = _conn()
    c.execute(
        """UPDATE feedback_clusters
           SET status=?, updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now')
           WHERE id=?""",
        (status, cluster_id),
    )
    changed = c.execute("SELECT changes()").fetchone()[0]
    c.commit()
    c.close()
    return {"ok": bool(changed)}


def merge_clusters(source_id: str, target_id: str, updated_by: str = "") -> dict:
    """Переносит все feedback из source в target, удаляет source."""
    if source_id == target_id:
        return {"ok": False, "error": "same cluster"}
    c = _conn()
    c.execute(
        "UPDATE feedback SET cluster_id=? WHERE cluster_id=?",
        (target_id, source_id),
    )
    moved = c.execute("SELECT changes()").fetchone()[0]
    # Пересчитать total_weight для target
    row = c.execute(
        """SELECT COALESCE(SUM(f.level_at_submit),0) + COALESCE(v.vw,0) AS tw,
                  COALESCE(fc,0) + COALESCE(vc,0) AS voters
           FROM (SELECT SUM(level_at_submit) AS sw, COUNT(*) AS fc
                 FROM feedback WHERE cluster_id=?) ff
           LEFT JOIN (SELECT SUM(weight) AS vw, COUNT(*) AS vc
                      FROM feedback_votes WHERE cluster_id=?) vv ON 1=1""",
        (target_id, target_id),
    ).fetchone()
    tw = row[0] if row else 0
    voters = row[1] if row else 0
    c.execute(
        "UPDATE feedback_clusters SET total_weight=?, voters=?, updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id=?",
        (tw, voters, target_id),
    )
    c.execute("DELETE FROM feedback_votes WHERE cluster_id=?", (source_id,))
    c.execute("DELETE FROM feedback_clusters WHERE id=?", (source_id,))
    c.commit()
    c.close()
    return {"ok": True, "moved": moved}


def split_feedback_from_cluster(feedback_id: str, updated_by: str = "") -> dict:
    """Создаёт новый кластер из одной заявки, отвязывает её от старого."""
    c = _conn()
    row = c.execute(
        "SELECT cluster_id, level_at_submit, comment FROM feedback WHERE id=?",
        (feedback_id,),
    ).fetchone()
    if not row:
        c.close()
        return {"ok": False, "error": "not found"}
    old_cluster = row["cluster_id"]
    level = row["level_at_submit"]
    title = (row["comment"] or "")[:80] or "Без заголовка"

    # Создаём новый кластер
    cur = c.execute(
        "INSERT INTO feedback_clusters(title, total_weight, voters) VALUES(?,?,1)",
        (title, level),
    )
    c.execute(
        "SELECT id FROM feedback_clusters WHERE rowid=?", (cur.lastrowid,)
    )
    new_row = c.execute(
        "SELECT id FROM feedback_clusters WHERE rowid=?", (cur.lastrowid,)
    ).fetchone()
    new_id = new_row["id"] if new_row else None

    c.execute("UPDATE feedback SET cluster_id=? WHERE id=?", (new_id, feedback_id))

    # Пересчитать старый кластер
    if old_cluster:
        row2 = c.execute(
            "SELECT COALESCE(SUM(level_at_submit),0) AS sw, COUNT(*) AS fc FROM feedback WHERE cluster_id=?",
            (old_cluster,),
        ).fetchone()
        row3 = c.execute(
            "SELECT COALESCE(SUM(weight),0) AS vw, COUNT(*) AS vc FROM feedback_votes WHERE cluster_id=?",
            (old_cluster,),
        ).fetchone()
        tw = (row2["sw"] if row2 else 0) + (row3["vw"] if row3 else 0)
        voters = (row2["fc"] if row2 else 0) + (row3["vc"] if row3 else 0)
        c.execute(
            "UPDATE feedback_clusters SET total_weight=?, voters=?, updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id=?",
            (tw, voters, old_cluster),
        )

    c.commit()
    c.close()
    return {"ok": True, "new_cluster_id": new_id}


def create_cluster_from_feedbacks(feedback_ids: list[str], title: str = "") -> dict:
    """Создать кластер вручную из набора незакреплённых заявок."""
    if not feedback_ids:
        return {"ok": False, "error": "empty"}
    c = _conn()
    rows = c.execute(
        "SELECT level_at_submit, comment FROM feedback WHERE id IN ({})".format(
            ",".join("?" * len(feedback_ids))
        ),
        feedback_ids,
    ).fetchall()
    total_weight = sum(r["level_at_submit"] for r in rows)
    if not title and rows:
        title = (rows[0]["comment"] or "")[:80]

    cur = c.execute(
        "INSERT INTO feedback_clusters(title, total_weight, voters) VALUES(?,?,?)",
        (title, total_weight, len(rows)),
    )
    new_row = c.execute(
        "SELECT id FROM feedback_clusters WHERE rowid=?", (cur.lastrowid,)
    ).fetchone()
    new_id = new_row["id"] if new_row else None
    c.execute(
        "UPDATE feedback SET cluster_id=? WHERE id IN ({})".format(
            ",".join("?" * len(feedback_ids))
        ),
        [new_id] + feedback_ids,
    )
    c.commit()
    c.close()
    return {"ok": True, "cluster_id": new_id, "total_weight": total_weight}


def update_cluster_title(cluster_id: str, title: str, tags: list | None = None) -> dict:
    c = _conn()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    c.execute(
        "UPDATE feedback_clusters SET title=?, tags=?, updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id=?",
        (title[:200], tags_json, cluster_id),
    )
    c.commit()
    c.close()
    return {"ok": True}


# ── site_copy ────────────────────────────────────────────────────────────────

def get_copy(copy_id: str) -> str | None:
    c = _conn()
    row = c.execute(
        "SELECT text_current FROM site_copy WHERE copy_id=?", (copy_id,)
    ).fetchone()
    c.close()
    return row["text_current"] if row else None


def upsert_copy(copy_id: str, text: str, page: str = "", default: str = "",
                updated_by: str = "") -> dict:
    c = _conn()
    c.execute(
        """INSERT INTO site_copy(copy_id, page, text_current, text_default, updated_by)
           VALUES(?,?,?,?,?)
           ON CONFLICT(copy_id) DO UPDATE SET
             text_current=excluded.text_current,
             updated_by=excluded.updated_by,
             updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now')""",
        (copy_id, page, text, default or text, updated_by),
    )
    c.commit()
    c.close()
    return {"ok": True}


def reset_copy_to_default(copy_id: str) -> dict:
    c = _conn()
    c.execute(
        "UPDATE site_copy SET text_current=text_default, updated_ts=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE copy_id=?",
        (copy_id,),
    )
    c.commit()
    c.close()
    return {"ok": True}


def get_all_copy() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT copy_id, page, text_current, text_default, updated_by, updated_ts FROM site_copy ORDER BY page, copy_id"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ── admin_users ──────────────────────────────────────────────────────────────

def is_admin(user_id: str | None) -> bool:
    if not user_id:
        return False
    c = _conn()
    row = c.execute(
        "SELECT 1 FROM admin_users WHERE user_id=?", (user_id,)
    ).fetchone()
    c.close()
    return bool(row)


def add_admin(user_id: str, role: str = "admin") -> dict:
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO admin_users(user_id, role) VALUES(?,?)",
        (user_id, role),
    )
    c.commit()
    c.close()
    return {"ok": True}


def remove_admin(user_id: str) -> dict:
    c = _conn()
    c.execute("DELETE FROM admin_users WHERE user_id=?", (user_id,))
    c.commit()
    c.close()
    return {"ok": True}


def bootstrap_admin(user_id: str) -> dict:
    """Назначить первого администратора только если admin_users пуст."""
    c = _conn()
    count = c.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
    if count > 0:
        c.close()
        return {"ok": False, "error": "admins_exist"}
    c.execute("INSERT INTO admin_users(user_id, role) VALUES(?,?)", (user_id, "admin"))
    c.commit()
    c.close()
    return {"ok": True, "user_id": user_id}


ensure_schema()

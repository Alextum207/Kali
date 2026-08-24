import sqlite3
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    url TEXT NOT NULL,
    category TEXT NOT NULL,
    crawled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id),
    pattern_type TEXT NOT NULL,
    target_norm TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_page_id_column(conn: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN isn't idempotent like CREATE TABLE IF NOT
    EXISTS — guard it so init_db can run safely on every app startup."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(findings)")]
    if "page_id" not in cols:
        conn.execute("ALTER TABLE findings ADD COLUMN page_id INTEGER REFERENCES pages(id)")


def _ensure_scan_status_columns(conn: sqlite3.Connection) -> None:
    """Same idempotency guard as _ensure_page_id_column, for DBs created
    before status/finished_at existed."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(scans)")]
    if "status" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN status TEXT NOT NULL DEFAULT 'running'")
    if "finished_at" not in cols:
        conn.execute("ALTER TABLE scans ADD COLUMN finished_at TEXT")


def _ensure_human_review_column(conn: sqlite3.Connection) -> None:
    """Same idempotency guard as _ensure_page_id_column, for DBs created
    before human_review existed. NULL = ungeprüft, else "confirmed"/"dismissed"."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(findings)")]
    if "human_review" not in cols:
        conn.execute("ALTER TABLE findings ADD COLUMN human_review TEXT")


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_page_id_column(conn)
    _ensure_scan_status_columns(conn)
    _ensure_human_review_column(conn)
    conn.commit()
    return conn


def insert_scan(conn: sqlite3.Connection, url: str) -> int:
    cur = conn.execute("INSERT INTO scans (url) VALUES (?)", (url,))
    conn.commit()
    return cur.lastrowid


def mark_scan_status(conn: sqlite3.Connection, scan_id: int, status: str) -> None:
    conn.execute(
        "UPDATE scans SET status = ?, finished_at = datetime('now') WHERE id = ?",
        (status, scan_id),
    )
    conn.commit()


def set_human_review(conn: sqlite3.Connection, finding_id: int, value: str) -> None:
    conn.execute("UPDATE findings SET human_review = ? WHERE id = ?", (value, finding_id))
    conn.commit()


def insert_page(conn: sqlite3.Connection, scan_id: int, url: str, category: str) -> int:
    cur = conn.execute(
        "INSERT INTO pages (scan_id, url, category) VALUES (?, ?, ?)",
        (scan_id, url, category),
    )
    conn.commit()
    return cur.lastrowid


def get_pages(conn: sqlite3.Connection, scan_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pages WHERE scan_id = ? ORDER BY id", (scan_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def insert_finding(conn: sqlite3.Connection, scan_id: int, finding: dict, page_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO findings (scan_id, pattern_type, target_norm, confidence_score, evidence_json, page_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            scan_id,
            finding["pattern_type"],
            finding["target_norm"],
            finding["confidence_score"],
            json.dumps(finding.get("evidence_data", {})),
            page_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_findings(conn: sqlite3.Connection, scan_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE scan_id = ? ORDER BY id", (scan_id,)
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["evidence_data"] = json.loads(d.pop("evidence_json"))
        result.append(d)
    return result


def get_page_findings(conn: sqlite3.Connection, page_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE page_id = ? ORDER BY id", (page_id,)
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["evidence_data"] = json.loads(d.pop("evidence_json"))
        result.append(d)
    return result


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None


def list_scans(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM scans ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def list_scans_by_url(conn: sqlite3.Connection, url: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM scans WHERE url = ? ORDER BY id DESC", (url,)).fetchall()
    return [dict(row) for row in rows]

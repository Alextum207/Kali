import sqlite3
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now'))
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


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_scan(conn: sqlite3.Connection, url: str) -> int:
    cur = conn.execute("INSERT INTO scans (url) VALUES (?)", (url,))
    conn.commit()
    return cur.lastrowid


def insert_finding(conn: sqlite3.Connection, scan_id: int, finding: dict) -> int:
    cur = conn.execute(
        "INSERT INTO findings (scan_id, pattern_type, target_norm, confidence_score, evidence_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            scan_id,
            finding["pattern_type"],
            finding["target_norm"],
            finding["confidence_score"],
            json.dumps(finding.get("evidence_data", {})),
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


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None

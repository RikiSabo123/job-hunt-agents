"""Shared memory ("blackboard") that all agents read from and write to.

Agents never talk to each other directly. Each one writes its result here,
and the next agent reads what it needs. The manager only sees short summaries.
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime

# Lifecycle of a job: new -> matched / rejected -> researched -> cv_ready -> sent
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT, company TEXT, location TEXT, url TEXT,
    source      TEXT, posted TEXT, description TEXT,
    status      TEXT DEFAULT 'new',
    fit_score   INTEGER,
    fit_json    TEXT,
    company_json TEXT,
    cv_md       TEXT,
    cover_md    TEXT,
    cv_path     TEXT,
    sent_at     TEXT,
    created_at  TEXT
);
"""

JSON_FIELDS = {"fit_json", "company_json"}


def job_id(company: str, title: str) -> str:
    norm = re.sub(r"\W+", " ", f"{company}|{title}".lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:10]


class Board:
    def __init__(self, path: str = "jobs.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add_job(self, job: dict) -> str | None:
        """Insert a job if it was never seen before. Returns its id, or None if duplicate."""
        jid = job_id(job.get("company", ""), job.get("title", ""))
        cur = self.db.execute(
            "INSERT OR IGNORE INTO jobs (id, title, company, location, url, source, posted,"
            " description, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (jid, job.get("title"), job.get("company"), job.get("location"), job.get("url"),
             job.get("source"), job.get("posted"), job.get("description"),
             datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()
        return jid if cur.rowcount else None

    def update(self, jid: str, **fields):
        for k in JSON_FIELDS & fields.keys():
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), jid))
        self.db.commit()

    def get(self, jid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        for k in JSON_FIELDS:
            if job.get(k):
                job[k] = json.loads(job[k])
        return job

    def by_status(self, status: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id FROM jobs WHERE status = ? ORDER BY fit_score DESC NULLS LAST", (status,)
        ).fetchall()
        return [self.get(r["id"]) for r in rows]

    def counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

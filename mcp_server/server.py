"""Read-only MCP server over the shared job board (jobs.db).

Lets AI clients (Claude Desktop, Claude Code, Cursor) ask questions about the jobs
the agents found. It never writes: the database is opened in SQLite read-only mode.

Run:
    python mcp_server/server.py           # stdio transport
    mcp dev mcp_server/server.py          # MCP Inspector
Env:
    JOBS_DB   path to the database (default: <repo>/jobs.db)
"""
import functools
import json
import logging
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parent.parent
STATUSES = ("new", "matched", "rejected", "researched", "cv_ready", "sent")
MATCH_STATUSES = ("matched", "researched", "cv_ready", "sent")
LIST_FIELDS = "id, title, company, location, fit_score, status, url, posted"
SCORE_RANGE = (0, 10)  # the matcher scores jobs from 1 to 10
MAX_LIMIT = 50
MAX_DAYS = 365
MAX_DESCRIPTION = 4000

# stdout carries the MCP protocol, so every log line goes to stderr.
logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("job-hunt-mcp")

mcp = FastMCP("job-hunt")


class DatabaseMissing(Exception):
    pass


# Database --------------------------------------------------------------------------------
def db_path() -> Path:
    return Path(os.getenv("JOBS_DB") or REPO / "jobs.db")


def connect() -> sqlite3.Connection:
    """Open the board read-only. Any write through this connection fails."""
    path = db_path()
    if not path.is_file():
        raise DatabaseMissing(f"Database not found at {path}. "
                              "Run mcp_server/seed_demo.py for demo data, or set JOBS_DB.")
    # as_uri() escapes spaces and '?' in Windows paths: file:///C:/... ?mode=ro
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch(sql: str, params: tuple = ()) -> list[dict]:
    """Run one parameterized SELECT and return plain dicts."""
    with closing(connect()) as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    log.info("query returned %d rows", len(rows))  # counts only, never job content
    return rows


def guarded(fn):
    """Turn a missing database or SQLite failure into an error dict instead of a crash."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatabaseMissing as e:
            return {"error": str(e)}
        except sqlite3.Error as e:
            log.error("%s failed: %s", fn.__name__, type(e).__name__)  # no job content in logs
            return {"error": f"Database error: {type(e).__name__}"}
    return wrapper


# Helpers ---------------------------------------------------------------------------------
def parse_json(raw: str | None) -> dict | list | None:
    """Parse a JSON column. Malformed JSON becomes None instead of an exception."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Skipping malformed JSON column")
        return None


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def out_of_range(name: str, value: int | None, low: int, high: int) -> dict | None:
    if value is not None and not low <= value <= high:
        return {"error": f"{name} must be between {low} and {high}, got {value}"}
    return None


def bad_status(status: str | None) -> dict | None:
    if status is not None and status not in STATUSES:
        return {"error": f"Unknown status '{status}'. Allowed: {', '.join(STATUSES)}"}
    return None


def like(text: str) -> str:
    """A LIKE pattern that treats % and _ in user input as plain characters."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


ORDER_BY = " ORDER BY fit_score IS NULL, fit_score DESC, created_at DESC LIMIT ?"


# Tools -----------------------------------------------------------------------------------
@mcp.tool()
@guarded
def search_jobs(query: str = "", location: str | None = None, min_score: int | None = None,
                status: str | None = None, limit: int = 10) -> list[dict] | dict:
    """Search the job board.

    query: case-insensitive text matched against title, company and description.
    location: case-insensitive text matched against the job location (e.g. "Jerusalem").
    min_score: minimum fit score, 0-10 (the matcher scores 1-10; 7+ means worth applying).
    status: one of new, matched, rejected, researched, cv_ready, sent.
    limit: max results, 1-50.
    Returns id, title, company, location, fit_score, status, url, posted,
    best fit first (unscored jobs last), then newest.
    """
    error = bad_status(status) or out_of_range("min_score", min_score, *SCORE_RANGE)
    if error:
        return error
    sql, params = f"SELECT {LIST_FIELDS} FROM jobs WHERE 1=1", []
    if query:
        sql += (" AND (title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\'"
                " OR description LIKE ? ESCAPE '\\')")
        params += [like(query)] * 3
    if location:
        sql += " AND location LIKE ? ESCAPE '\\'"
        params.append(like(location))
    if min_score is not None:
        sql += " AND fit_score >= ?"
        params.append(min_score)
    if status:
        sql += " AND status = ?"
        params.append(status)
    return fetch(sql + ORDER_BY, (*params, clamp(limit, 1, MAX_LIMIT)))


@mcp.tool()
@guarded
def get_job(job_id: str, include_documents: bool = False) -> dict:
    """Get the full record of one job by its id.

    Includes the fit analysis (fit_json: score, fits, gaps, deal_breakers, one_line)
    and company research (company_json). The description is cut at 4000 characters
    ("truncated": true when cut). The tailored CV (cv_md) and cover letter (cover_md)
    are only included when include_documents is true.
    """
    rows = fetch("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not rows:
        return {"error": f"Job not found: {job_id}"}
    job = rows[0]
    job["fit_json"] = parse_json(job["fit_json"])
    job["company_json"] = parse_json(job["company_json"])
    description = job.get("description") or ""
    if len(description) > MAX_DESCRIPTION:
        job["description"] = description[:MAX_DESCRIPTION]
        job["truncated"] = True
    if not include_documents:
        job.pop("cv_md", None)
        job.pop("cover_md", None)
    return job


@mcp.tool()
@guarded
def top_matches(limit: int = 5, days: int | None = None) -> list[dict] | dict:
    """The best-fitting jobs that passed the matcher (matched, researched, cv_ready, sent).

    limit: how many, 1-50.
    days: only jobs added to the board in the last N days (1-365).
    Returns the search_jobs fields plus one_line (why it fits) and gaps from the
    fit analysis, highest fit score first.
    """
    error = out_of_range("days", days, 1, MAX_DAYS)
    if error:
        return error
    marks = ", ".join("?" for _ in MATCH_STATUSES)
    sql = (f"SELECT {LIST_FIELDS}, fit_json FROM jobs "
           f"WHERE status IN ({marks}) AND fit_score IS NOT NULL")
    params = list(MATCH_STATUSES)
    if days is not None:
        # created_at is written by state.py as local time, isoformat(timespec="seconds").
        sql += " AND created_at >= ?"
        params.append((datetime.now() - timedelta(days=days)).isoformat(timespec="seconds"))
    rows = fetch(sql + ORDER_BY, (*params, clamp(limit, 1, MAX_LIMIT)))
    for row in rows:
        fit = parse_json(row.pop("fit_json"))
        fit = fit if isinstance(fit, dict) else {}
        row["one_line"] = fit.get("one_line")
        row["gaps"] = fit.get("gaps")
    return rows


@mcp.tool()
@guarded
def board_stats() -> dict:
    """Overview of the board: number of jobs at each pipeline stage
    (new -> matched/rejected -> researched -> cv_ready -> sent), total jobs,
    average fit score of scored jobs (1-10 scale) and when the newest job was added."""
    counts = {s: 0 for s in STATUSES}
    for row in fetch("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
        counts[row["status"] or "unknown"] = row["n"]
    summary = fetch("SELECT COUNT(*) AS total, AVG(fit_score) AS avg_score,"
                    " MAX(created_at) AS newest FROM jobs")[0]
    avg = summary["avg_score"]
    return {
        "by_status": counts,
        "total": summary["total"],
        "avg_fit_score": round(avg, 2) if avg is not None else None,
        "newest_created_at": summary["newest"],
    }


if __name__ == "__main__":
    log.info("Starting job-hunt MCP server (read-only), db=%s", db_path())
    mcp.run()  # stdio

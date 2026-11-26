"""Tests for the read-only MCP server. Each test gets its own temporary database; no network."""
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp_server import server  # noqa: E402
from mcp_server.seed_demo import seed  # noqa: E402
from state import SCHEMA  # noqa: E402

NOW = datetime.now()


def ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def fit(score: int, gaps: list[str]) -> str:
    return json.dumps({"score": score, "fits": ["React"], "gaps": gaps,
                       "deal_breakers": [], "one_line": f"score {score}"})


# id, title, company, location, description, status, fit_score, fit_json, created_at
ROWS = [
    ("a1", "Junior Full Stack Developer", "Alpha", "Jerusalem", "React and Node",
     "cv_ready", 9, fit(9, ["AWS"]), ago(1)),
    ("b2", "Backend Developer", "Beta", "Tel Aviv", "Python services",
     "matched", 7, fit(7, ["Kafka"]), ago(2)),
    ("c3", "Full Stack Engineer", "Gamma", "Jerusalem (Hybrid)", "TypeScript",
     "researched", 8, fit(8, ["Docker"]), ago(20)),
    ("d4", "Data Engineer", "Delta", "Haifa", "Spark pipelines",
     "rejected", 4, fit(4, ["Spark"]), ago(3)),
    ("e5", "QA Automation", "Epsilon", "Modi'in", "Playwright tests",
     "new", None, None, ago(0)),
    ("f6", "Frontend Developer", "Zeta", "Jerusalem", "React UI",
     "new", None, None, ago(5)),
]


@pytest.fixture
def db(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "jobs.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO jobs (id, title, company, location, description, status, fit_score,"
            " fit_json, created_at, cv_md, cover_md) VALUES (?,?,?,?,?,?,?,?,?,'# CV','Dear team')",
            ROWS)
        conn.commit()
    monkeypatch.setenv("JOBS_DB", str(path))
    return path


def write(path: Path, sql: str, params: tuple = ()) -> None:
    """Change the test database directly (the server itself can't)."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(sql, params)
        conn.commit()


# search_jobs ---------------------------------------------------------------------------
def test_search_returns_fields_sorted_by_score(db):
    jobs = server.search_jobs()
    assert set(jobs[0]) == {"id", "title", "company", "location", "fit_score", "status",
                            "url", "posted"}
    # scored jobs by score, then unscored jobs newest first
    assert [j["id"] for j in jobs] == ["a1", "c3", "b2", "d4", "e5", "f6"]


def test_search_filters(db):
    assert [j["id"] for j in server.search_jobs(query="full stack")] == ["a1", "c3"]
    assert [j["id"] for j in server.search_jobs(query="BETA")] == ["b2"]          # company
    assert [j["id"] for j in server.search_jobs(query="playwright")] == ["e5"]    # description
    assert [j["id"] for j in server.search_jobs(location="jerusalem", min_score=8)] == ["a1", "c3"]
    assert [j["id"] for j in server.search_jobs(status="new")] == ["e5", "f6"]


def test_search_wildcards_are_literal(db):
    assert server.search_jobs(query="%") == []
    assert server.search_jobs(query="_") == []


def test_search_sql_injection_is_harmless(db):
    assert server.search_jobs(query="'; DROP TABLE jobs; --") == []
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == len(ROWS)


def test_search_invalid_inputs(db):
    assert "error" in server.search_jobs(status="hired")
    assert "error" in server.search_jobs(min_score=11)
    assert "error" in server.search_jobs(min_score=-1)
    assert len(server.search_jobs(limit=0)) == 1      # clamped up to 1
    assert len(server.search_jobs(limit=1000)) == len(ROWS)  # clamped down to 50


# get_job -------------------------------------------------------------------------------
def test_get_job_parses_json_and_hides_documents(db):
    job = server.get_job("a1")
    assert job["title"] == "Junior Full Stack Developer"
    assert job["fit_json"]["gaps"] == ["AWS"]
    assert "cv_md" not in job and "cover_md" not in job
    assert "truncated" not in job


def test_get_job_with_documents(db):
    job = server.get_job("a1", include_documents=True)
    assert job["cv_md"] == "# CV"
    assert job["cover_md"] == "Dear team"


def test_get_job_unknown_id(db):
    assert server.get_job("nope") == {"error": "Job not found: nope"}


def test_get_job_truncates_long_description(db):
    write(db, "UPDATE jobs SET description = ? WHERE id = 'a1'", ("x" * 5000,))
    job = server.get_job("a1")
    assert len(job["description"]) == server.MAX_DESCRIPTION
    assert job["truncated"] is True


def test_malformed_json_does_not_crash(db):
    write(db, "UPDATE jobs SET fit_json = '{not json', company_json = '[' WHERE id = 'a1'")
    job = server.get_job("a1")
    assert job["fit_json"] is None and job["company_json"] is None
    top = {j["id"]: j for j in server.top_matches()}
    assert top["a1"]["gaps"] is None and top["a1"]["one_line"] is None


# top_matches ---------------------------------------------------------------------------
def test_top_matches(db):
    top = server.top_matches()
    assert [j["id"] for j in top] == ["a1", "c3", "b2"]  # rejected and new are excluded
    assert top[0]["gaps"] == ["AWS"] and top[0]["one_line"] == "score 9"
    assert {"id", "title", "fit_score", "status", "url"} <= set(top[0])


def test_top_matches_days_and_limit(db):
    assert [j["id"] for j in server.top_matches(days=7)] == ["a1", "b2"]
    assert len(server.top_matches(limit=1)) == 1
    assert "error" in server.top_matches(days=0)
    assert "error" in server.top_matches(days=366)


# board_stats ---------------------------------------------------------------------------
def test_board_stats(db):
    stats = server.board_stats()
    assert stats["by_status"] == {"new": 2, "matched": 1, "rejected": 1, "researched": 1,
                                  "cv_ready": 1, "sent": 0}
    assert stats["total"] == 6
    assert stats["avg_fit_score"] == 7.0  # (9 + 7 + 8 + 4) / 4, unscored jobs ignored
    assert stats["newest_created_at"] == ago(0)


# safety --------------------------------------------------------------------------------
def test_connection_is_read_only(db):
    with closing(server.connect()) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO jobs (id) VALUES ('hacked')")


def test_missing_database_returns_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DB", str(tmp_path / "missing.db"))
    for result in (server.search_jobs(), server.get_job("a1"), server.top_matches(),
                   server.board_stats()):
        assert "Database not found at" in result["error"]
        assert "seed_demo.py" in result["error"]


def test_exactly_four_tools_registered():
    import asyncio
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"search_jobs", "get_job", "top_matches", "board_stats"}


def test_demo_seed_works_with_server(tmp_path, monkeypatch):
    path = tmp_path / "demo.db"
    assert seed(path) == 12
    monkeypatch.setenv("JOBS_DB", str(path))
    assert server.board_stats()["total"] == 12
    assert server.top_matches(limit=3)[0]["fit_score"] >= 8

"""Create a demo job board with FICTIONAL jobs, so the MCP server can be tried without real data.

Run:
    python mcp_server/seed_demo.py                  # -> mcp_server/demo_jobs.db
    python mcp_server/seed_demo.py --db other.db

Every company, URL and document below is made up. Scores use the matcher's 1-10 scale
(7+ = matched, below 7 = rejected), like the real pipeline.
"""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from state import SCHEMA, job_id  # noqa: E402  (same schema and ids as the real board)

DEFAULT_DB = HERE / "demo_jobs.db"
COLUMNS = ("id, title, company, location, url, source, posted, description, status, fit_score,"
           " fit_json, company_json, cv_md, cover_md, cv_path, sent_at, created_at")


def fit(score: int, fits: list[str], gaps: list[str], one_line: str,
        deal_breakers: list[str] | None = None) -> dict:
    return {"score": score, "fits": fits, "gaps": gaps,
            "deal_breakers": deal_breakers or [], "one_line": one_line}


def company(what: str, stack: list[str], size: str, points: list[str]) -> dict:
    return {"what_they_do": what, "product": what, "tech_stack": stack, "size_and_stage": size,
            "recent_news": [], "culture_signals": ["hybrid work"], "official_apply_url": None,
            "talking_points": points, "red_flags": [], "sources": []}


# (title, company, location, status, fit, company research, days ago, description)
JOBS = [
    ("Junior Full Stack Developer", "Nimbus Analytics", "Jerusalem", "cv_ready",
     fit(9, ["React", "Node.js", "TypeScript"], ["No production AWS experience"],
         "Stack matches the candidate's projects almost one to one."),
     company("Dashboards for small retailers", ["React", "Node.js", "PostgreSQL"],
             "Seed, ~25 people", ["Open-source charting library"]), 1,
     "Build React dashboards and Node.js APIs. 0-2 years, TypeScript a plus."),
    ("Full Stack Developer (Junior)", "Gefen Health", "Jerusalem (Hybrid)", "researched",
     fit(8, ["Full stack projects", "REST APIs"], ["No healthcare domain knowledge", "No Docker"],
         "Good junior fit; domain is new to the candidate."),
     company("Clinic scheduling software", ["Next.js", "Python", "Docker"],
             "Series A, ~60 people", ["Patient-first product"]), 2,
     "Next.js front end and Python services for clinic scheduling. Graduates welcome."),
    ("Backend Developer - Entry Level", "Orbit Payments", "Tel Aviv", "sent",
     fit(8, ["Node.js", "SQL"], ["No message queues experience"],
         "Strong backend basics, missing Kafka."),
     company("Payment routing for marketplaces", ["Node.js", "Kafka", "MySQL"],
             "Series B, ~150 people", ["Engineering blog on idempotency"]), 9,
     "Node.js microservices, SQL, unit testing. 1 year of experience preferred."),
    ("Junior AI Engineer", "Lavender Labs", "Modi'in", "matched",
     fit(7, ["Python", "LLM side projects"], ["No ML degree", "Little PyTorch"],
         "Worth applying: strong LLM projects, light on ML theory."),
     None, 3,
     "Prompt pipelines, evaluation scripts and Python services around LLMs."),
    ("QA Automation Engineer (Junior)", "Shaked Security", "Petah Tikva", "matched",
     fit(7, ["JavaScript", "Testing mindset"], ["No Playwright", "No CI pipelines"],
         "Reasonable fit if willing to move toward QA."),
     None, 4,
     "Write Playwright tests and maintain CI for a security product. 0-2 years."),
    ("Frontend Developer - Graduate", "Rimon Games", "Ramat Gan", "cv_ready",
     fit(8, ["React", "CSS", "Animations"], ["No game industry experience"],
         "Strong front end skills, good portfolio match."),
     company("Casual mobile and web games", ["React", "Canvas", "TypeScript"],
             "Profitable, ~40 people", ["Award-winning puzzle game"]), 2,
     "React and Canvas UI for web games. Graduates and bootcamp alumni welcome."),
    ("Junior Data Engineer", "Kineret Data", "Haifa", "rejected",
     fit(5, ["Python", "SQL"], ["No Spark", "No Airflow", "Location is far"],
         "Long shot: data tooling is missing.", ["Daily on-site in Haifa"]),
     None, 6,
     "Spark and Airflow pipelines. On-site in Haifa five days a week."),
    ("Junior Mobile Developer", "Ofek Mobility", "Herzliya", "rejected",
     fit(4, ["JavaScript"], ["No Kotlin", "No Swift"],
         "Native mobile stack the candidate never used."),
     None, 7,
     "Native Android (Kotlin) and iOS (Swift) apps for fleet drivers."),
    ("DevOps Engineer - Junior", "Hadas Cloud", "Rehovot", "rejected",
     fit(3, ["Linux basics"], ["No Kubernetes", "No Terraform", "No on-call experience"],
         "Irrelevant for a full stack profile."),
     None, 10,
     "Kubernetes, Terraform and on-call rotation. 2+ years required."),
    ("Junior Backend Developer (C#)", "Ezra Logistics", "Airport City", "new",
     None, None, 0,
     "C# and .NET services for warehouse logistics. 0-2 years."),
    ("Full Stack Developer", "Tamar EdTech", "Be'er Sheva (Remote)", "new",
     None, None, 0,
     "Remote role building learning tools with React and Node.js."),
    ("Junior Software Engineer", "Tzuf Robotics", "Shoham", "matched",
     fit(7, ["Python", "C basics"], ["No embedded experience"],
         "Python is a match; embedded work is a stretch."),
     None, 30,
     "Python tooling around robot simulations, some C. Entry level."),
]

CV = "# Demo Candidate\n\n## Skills\n- React, Node.js, TypeScript\n\n## Projects\n- Demo project\n"
COVER = "Hello, I am a demo candidate. This cover letter is fictional demo data."


def row(job: tuple, now: datetime) -> tuple:
    title, comp, location, status, fit_data, research, days_ago, description = job
    has_docs = status in ("cv_ready", "sent")
    slug = comp.lower().replace(" ", "-")
    return (
        job_id(comp, title), title, comp, location,
        f"https://jobs.example.com/{slug}/{job_id(comp, title)}", "demo",
        (now - timedelta(days=days_ago + 1)).date().isoformat(), description, status,
        fit_data["score"] if fit_data else None,
        json.dumps(fit_data) if fit_data else None,
        json.dumps(research) if research else None,
        CV if has_docs else None, COVER if has_docs else None,
        f"output/Demo_CV_{slug}.docx" if has_docs else None,
        now.date().isoformat() if status == "sent" else None,
        (now - timedelta(days=days_ago, hours=len(title))).isoformat(timespec="seconds"),
    )


def seed(path: Path) -> int:
    """Recreate the demo database at path. Returns the number of jobs written."""
    path.unlink(missing_ok=True)
    now = datetime.now()
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        marks = ", ".join("?" * len(COLUMNS.split(",")))
        db.executemany(f"INSERT INTO jobs ({COLUMNS}) VALUES ({marks})", [row(j, now) for j in JOBS])
        db.commit()
    return len(JOBS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    print(f"Wrote {seed(args.db)} demo jobs to {args.db}")

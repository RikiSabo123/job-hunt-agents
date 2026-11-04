"""The five specialist agents.

Each worker: reads what it needs from the Board, does one job with its own
system prompt, writes the full result back to the Board, and returns a SHORT
summary to the manager. Big data stays on the board; the manager gets headlines.
"""
import json
from datetime import date

import config
import llm
from cv_docx import markdown_to_docx
from state import Board


def web_search(*a, **kw):
    from search import web_search as _ws  # imported lazily: only free mode needs it
    return _ws(*a, **kw)

NO_INVENT = ("Use ONLY facts from the candidate profile. Never invent experience, "
             "technologies, numbers, titles or dates.")


# 1. Scout — finds fresh junior postings ------------------------------------------------
SCOUT_SYSTEM = """You are a job scout for the Israeli tech market.
Search the web thoroughly (Hebrew and English queries, each role separately) for job postings
that match the criteria. Good sources: LinkedIn jobs, AllJobs, Drushim, JobMaster, GotFriends,
Comeet/Greenhouse/Lever career pages, company career pages.
Skip anything that requires 3+ years as a hard requirement. Skip senior/lead roles.
Prefer postings from the last few days. Only return postings you actually found - never invent."""


SCOUT_QUERIES = [
    "junior full stack developer Israel job",
    "משרת ג'וניור Full Stack",
    "junior backend developer Tel Aviv job",
    "junior developer Jerusalem job",
    "junior AI engineer Israel job",
    "junior QA automation engineer Israel",
    "מפתח ג'וניור משרה מודיעין",
    "entry level software engineer hybrid Israel",
]


def scout(board: Board, focus: str = "") -> str:
    prompt = (f"Criteria:\n{json.dumps(config.CRITERIA, ensure_ascii=False, indent=2)}\n"
              f"Today is {date.today()}.\n"
              + (f"Extra focus for this search: {focus}\n" if focus else ""))
    if llm.PROVIDER != "anthropic" and not llm.GEMINI_GROUNDING:  # free mode: we search, the model reads the results
        queries = SCOUT_QUERIES + ([focus] if focus else [])
        prompt += ("\nSearch results (pick only real, specific job postings from these):\n"
                   + web_search(queries))
    prompt += ("\nReturn a JSON array of up to 15 postings. Each item: "
               '{"title","company","location","url","source","posted","description"} '
               "where description is a 3-5 line summary of requirements and responsibilities.")
    jobs = llm.ask_json(SCOUT_SYSTEM, prompt, web=True)
    new_ids = [jid for j in jobs if (jid := board.add_job(j))]
    return f"Scout found {len(jobs)} postings, {len(new_ids)} are new: {new_ids}"


# 2. Matcher — honest fit check ---------------------------------------------------------
MATCHER_SYSTEM = """You are a strict, honest technical recruiter.
Score how well the candidate fits the job from 1 to 10 for a realistic chance of getting an interview.
10 = near perfect, 7 = worth applying, 4 = long shot, 1 = irrelevant. Do not inflate."""


def matcher(board: Board, jid: str) -> str:
    job = board.get(jid)
    prompt = (f"Candidate profile:\n{config.PROFILE}\n\nJob:\n{_job_text(job)}\n\n"
              'Return {"score": int, "fits": [..], "gaps": [..], "deal_breakers": [..], '
              '"one_line": "why, in one sentence"}')
    fit = llm.ask_json(MATCHER_SYSTEM, prompt)
    score = int(fit.get("score", 0))
    status = "matched" if score >= config.MIN_FIT_SCORE else "rejected"
    board.update(jid, fit_score=score, fit_json=fit, status=status)
    return f"{job['title']} @ {job['company']}: score {score} -> {status}. {fit.get('one_line', '')}"


def matcher_batch(board: Board, ids: list[str]) -> str:
    """Scores many jobs in ONE model call - saves free-tier requests."""
    if not ids:
        return "No new jobs to score."
    jobs = {jid: board.get(jid) for jid in ids}
    listing = "\n\n".join(f"[{jid}]\n{_job_text(j)}" for jid, j in jobs.items())
    prompt = (f"Candidate profile:\n{config.PROFILE}\n\nJobs:\n{listing}\n\n"
              'Return {"<job id>": {"score": int, "fits": [..], "gaps": [..], '
              '"deal_breakers": [..], "one_line": ".."}, ...} with one entry per job id.')
    results = llm.ask_json(MATCHER_SYSTEM, prompt)
    lines = []
    for jid, fit in results.items():
        if jid not in jobs:
            continue
        score = int(fit.get("score", 0))
        status = "matched" if score >= config.MIN_FIT_SCORE else "rejected"
        board.update(jid, fit_score=score, fit_json=fit, status=status)
        lines.append(f"{jobs[jid]['company']}: {score} -> {status}")
    return "Scored: " + "; ".join(lines)


# 3. Researcher — the company itself, not just the job board ---------------------------
RESEARCHER_SYSTEM = """You research companies for a job applicant.
Go beyond the job posting: the company's own site, engineering blog, GitHub, news, funding,
product, tech stack, team size, culture, and the official careers page / application channel.
Report only what you found and say when something is unknown."""


def researcher(board: Board, jid: str) -> str:
    job = board.get(jid)
    prompt = f"Research this company for an applicant to the role below.\n{_job_text(job)}\n\n"
    if llm.PROVIDER != "anthropic" and not llm.GEMINI_GROUNDING:  # free mode: search the company ourselves
        c = job["company"]
        prompt += "Search results about the company:\n" + web_search([
            f"{c} Israel company", f"{c} engineering blog OR tech stack",
            f"{c} careers", f"{c} news 2026", f"{c} מה החברה עושה",
        ], per_query=5) + "\n\n"
    prompt += ('Return {"what_they_do", "product", "tech_stack": [..], "size_and_stage", '
              '"recent_news": [..], "culture_signals": [..], "official_apply_url", '
              '"talking_points": ["specific things to mention in a CV/cover letter"], '
              '"red_flags": [..], "sources": [urls]}')
    info = llm.ask_json(RESEARCHER_SYSTEM, prompt, web=True)
    board.update(jid, company_json=info, status="researched")
    return f"Researched {job['company']}: {info.get('what_they_do', '')[:150]}"


# 4. CV writer — tailored CV + short cover letter --------------------------------------
CV_SYSTEM = f"""You are an expert tech CV writer for the Israeli market.
Write a one-page CV in English, tailored to one specific job, plus a short cover letter.
{NO_INVENT} You may reorder, rephrase, cut and emphasise. Mirror the job's keywords only
where the candidate truly has them. Keep the candidate's real contact details."""


def cv_writer(board: Board, jid: str) -> str:
    job = board.get(jid)
    prompt = (f"Candidate profile:\n{config.PROFILE}\n\nJob:\n{_job_text(job)}\n\n"
              f"Fit analysis:\n{json.dumps(job.get('fit_json'), ensure_ascii=False)}\n\n"
              f"Company research:\n{json.dumps(job.get('company_json'), ensure_ascii=False)}\n\n"
              'Return {"cv_markdown": "full CV in markdown (# name, ## sections, - bullets)", '
              '"cover_letter": "max 150 words, mentions 1-2 real company talking points", '
              '"changes": ["what you changed vs the base profile and why"]}')
    out = llm.ask_json(CV_SYSTEM, prompt, max_tokens=12000)
    safe = "".join(c if c.isalnum() else "_" for c in f"{job['company']}_{job['title']}")[:60]
    path = config.OUT_DIR / f"Rivka_Sabo_CV_{safe}.docx"
    markdown_to_docx(out["cv_markdown"], path)
    board.update(jid, cv_md=out["cv_markdown"], cover_md=out["cover_letter"],
                 cv_path=str(path), status="cv_ready")
    return f"CV ready for {job['company']}: {path.name}. Changes: {'; '.join(out.get('changes', [])[:3])}"


# 5. Sender — one digest email to YOU, with all CVs attached ---------------------------
def sender(board: Board) -> str:
    from mailer import send_digest
    ready = board.by_status("cv_ready")
    if not ready:
        return "Nothing to send: no jobs in status cv_ready."
    where = send_digest(ready)
    for job in ready:
        board.update(job["id"], status="sent", sent_at=date.today().isoformat())
    return f"Digest with {len(ready)} jobs {where}."


def _job_text(job: dict) -> str:
    return (f"Title: {job['title']}\nCompany: {job['company']}\nLocation: {job.get('location')}\n"
            f"URL: {job.get('url')}\nPosted: {job.get('posted')}\n"
            f"Description: {job.get('description')}")

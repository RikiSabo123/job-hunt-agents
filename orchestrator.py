"""The manager agent: decides which worker runs, in what order, on which job.

Run:
    python orchestrator.py              # free mode (Gemini): fixed-order manager
                                        # paid mode (PROVIDER=anthropic): an LLM manager decides everything
    python orchestrator.py --pipeline   # always the fixed order
"""
import argparse
import json

import config
import llm
import workers
from state import Board

BOSS_SYSTEM = f"""You are the manager of a small team of job-hunting agents working for Rivka,
a junior full-stack developer in Israel. Your goal for this run: deliver ONE email to Rivka
with the best fresh job matches, each with company research and a tailored CV.

Your team (call them as tools):
- run_scout: searches job boards. You may call it again with a `focus` to fill gaps
  (e.g. a role or area that returned nothing).
- run_matcher: scores one job. Jobs scoring >= {config.MIN_FIT_SCORE} become 'matched'.
- run_researcher: researches the company behind a matched job.
- run_cv_writer: writes a tailored CV + cover letter for a researched job.
- run_sender: emails Rivka the digest of every job in 'cv_ready'. Call it ONCE, at the end.
- list_jobs: see jobs in a given status on the shared board.

Rules:
- Score every new job before researching anything.
- Write at most {config.MAX_CVS_PER_RUN} CVs per run - pick the highest scores.
- Never research or write a CV for a job that is not 'matched'.
- If after two scout calls there are no matches, call run_sender anyway (it will report nothing to send) and stop.
- When done, reply with a 3-line summary in Hebrew."""

TOOLS = [
    {"name": "run_scout", "description": "Search for fresh junior job postings.",
     "input_schema": {"type": "object", "properties": {
         "focus": {"type": "string", "description": "optional extra focus, e.g. 'QA in Jerusalem'"}}}},
    {"name": "run_matcher", "description": "Score one job's fit for Rivka.",
     "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "run_researcher", "description": "Research the company of a matched job.",
     "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "run_cv_writer", "description": "Write a tailored CV for a researched job.",
     "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "run_sender", "description": "Email Rivka the digest of all cv_ready jobs.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_jobs", "description": "List jobs on the board by status "
     "(new, matched, rejected, researched, cv_ready, sent).",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string"}},
                      "required": ["status"]}},
]


def run_tool(board: Board, name: str, args: dict) -> str:
    try:
        if name == "run_scout":
            return workers.scout(board, args.get("focus", ""))
        if name == "run_matcher":
            return workers.matcher(board, args["job_id"])
        if name == "run_researcher":
            return workers.researcher(board, args["job_id"])
        if name == "run_cv_writer":
            return workers.cv_writer(board, args["job_id"])
        if name == "run_sender":
            return workers.sender(board)
        if name == "list_jobs":
            jobs = board.by_status(args["status"])
            return json.dumps([{"id": j["id"], "title": j["title"], "company": j["company"],
                                "score": j["fit_score"]} for j in jobs], ensure_ascii=False)
        return f"Unknown tool {name}"
    except Exception as e:  # a failing worker must not crash the whole team
        return f"ERROR in {name}: {e}"


def run_boss(board: Board):
    messages = [{"role": "user", "content":
                 f"Start today's run. Board status now: {board.counts()}"}]
    for step in range(config.MAX_BOSS_STEPS):
        resp = llm.client().messages.create(
            model=llm.BOSS_MODEL, max_tokens=4000, system=BOSS_SYSTEM,
            tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})

        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:  # the manager is done
            print("\n".join(b.text for b in resp.content if b.type == "text"))
            return
        results = []
        for call in calls:
            print(f"[step {step}] manager -> {call.name}({call.input})")
            out = run_tool(board, call.name, call.input)
            print(f"           <- {out[:200]}")
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out})
        messages.append({"role": "user", "content": results})
    print("Stopped: reached MAX_BOSS_STEPS.")


def _safe(label: str, fn, *args):
    """Run one worker; a failure is reported but doesn't stop the rest of the team."""
    try:
        print(fn(*args))
        return True
    except Exception as e:
        print(f"ERROR in {label}: {e}")
        return False


def run_pipeline(board: Board):
    """Same team, fixed order, no manager. Good for debugging one stage at a time."""
    if not _safe("scout", workers.scout, board):
        # Fail the run so the next scheduled attempt of the day tries again.
        raise SystemExit("Scout failed - no search this run. Exiting with an error so a backup run retries.")
    _safe("matcher", workers.matcher_batch, board, [j["id"] for j in board.by_status("new")])
    # Jobs researched in an earlier run whose CV failed get their CV first.
    todo = board.by_status("researched") + board.by_status("matched")
    for job in todo[: config.MAX_CVS_PER_RUN]:
        if job["status"] == "researched" or _safe("researcher", workers.researcher, board, job["id"]):
            _safe("cv_writer", workers.cv_writer, board, job["id"])
    _safe("sender", workers.sender, board)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", action="store_true", help="fixed order, no manager agent")
    ap.add_argument("--db", default=str(config.BASE / "jobs.db"))
    args = ap.parse_args()
    board = Board(args.db)
    if llm.PROVIDER != "anthropic" and not args.pipeline:
        print("Free mode: the manager runs the team in a fixed order (an LLM manager needs PROVIDER=anthropic).")
        args.pipeline = True
    (run_pipeline if args.pipeline else run_boss)(board)
